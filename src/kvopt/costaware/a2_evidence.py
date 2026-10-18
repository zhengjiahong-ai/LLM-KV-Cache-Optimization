"""Build A2 block geometry from recorded Phase 2G evidence.

The core problem
----------------
A free-queue row at decision time carries only ``block_id``, ``native_lru_rank``,
``has_block_hash`` and ``eligibility_tier``. **Block ids are recycled**: a slot that
held content ``A`` when a prefix snapshot was written may hold content ``B`` by the
time a decision is replayed. So a ``block_id`` is not a content identity, and joining
a historical snapshot's ``block_ids`` to a current free-queue ``block_id`` proves
nothing on its own.

How identity is proved
----------------------
This module reuses the protocol already established for shared-retention auditing in
:mod:`kvopt.profiling.phase2d_shared_retention` (``_mapping_for_candidate``), applied
per candidate chain:

1. take the **latest** ``VLLM_PREFIX_SNAPSHOT`` for that chain strictly before the
   decision — never an earlier one, so an invalid later snapshot invalidates the
   mapping instead of leaving a stale one active;
2. require the snapshot payload to carry ``block_ids``, ``ordered_native_hashes``,
   ``ordered_native_cache_keys`` and a non-empty ``native_hash_process_id``;
3. require the candidate's ``block_ids`` to equal the snapshot's ``block_ids``
   **as an ordered list**, which is what ties the current chain to that content;
4. require the three sequences to be the same length, so position is meaningful;
5. reject the mapping if any of those block ids was evicted by the same hash process
   between the snapshot and the decision.

Only a chain that passes all five yields memberships. Every other hash-carrying legal
block is recorded as unknown — never given a depth borrowed from a slot number.

What is deliberately not used: rank is never turned into depth, and ``block_id``
alone is never treated as a content identity.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .a2_geometry import (
    GAP_CONTENT_UNVERIFIED,
    GAP_DEPTH_UNKNOWN,
    ChainKey,
    DecisionGeometry,
    LegalBlock,
    Membership,
    reuse_proxy,
)
from .replay import (
    CandidateKey,
    DecisionSnapshot,
    ExecutedP1BStrategy,
    ReplayState,
    _snapshot_from_event,
    replay_decision,
)

DEFAULT_TAU_SECONDS = 30.0

#: Why a chain could not be proved. Kept as constants so reports stay comparable.
PROVED = "PROVED"
NO_PRIOR_SNAPSHOT = "no_prior_snapshot"
SNAPSHOT_PAYLOAD_INCOMPLETE = "snapshot_payload_incomplete"
CANDIDATE_BLOCKS_DIFFER = "candidate_blocks_differ_from_snapshot"
SEQUENCE_LENGTH_MISMATCH = "block_hash_key_lengths_differ"
BLOCK_EVICTED_BEFORE_DECISION = "mapped_block_evicted_before_decision"


@dataclass(frozen=True, slots=True)
class ChainProof:
    """The outcome of trying to prove one chain's content identity."""

    chain: ChainKey
    status: str
    reason: str
    snapshot_event_index: int | None = None
    process_id: str | None = None
    block_ids: tuple[int, ...] = ()
    hashes: tuple[str, ...] = ()

    @property
    def proved(self) -> bool:
        return self.status == PROVED

    def depth_of(self, block_id: int) -> int | None:
        """1-based position of the block, or ``None`` when not in this chain."""
        for position, candidate in enumerate(self.block_ids, start=1):
            if candidate == block_id:
                return position
        return None

    def hash_of(self, block_id: int) -> str | None:
        depth = self.depth_of(block_id)
        if depth is None or depth > len(self.hashes):
            return None
        return self.hashes[depth - 1]


@dataclass(frozen=True, slots=True)
class DecisionInput:
    """One decision plus the proofs available for its candidate chains."""

    snapshot: DecisionSnapshot
    rows: Mapping[CandidateKey, object]
    proofs: Mapping[ChainKey, ChainProof]
    candidates: tuple[Mapping[str, object], ...] = ()


def chain_key(program_id: str, prefix_id: str) -> ChainKey:
    return f"{program_id}:{prefix_id}"


def _latest_prior_snapshot(
    events: Sequence[Mapping[str, object]],
    *,
    decision_index: int,
    program_id: str,
    prefix_id: str,
) -> Mapping[str, object] | None:
    matches = [
        event
        for event in events
        if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT"
        and int(event.get("event_index", -1)) < decision_index
        and event.get("program_id") == program_id
        and event.get("prefix_id") == prefix_id
    ]
    return max(matches, key=lambda row: int(row["event_index"]), default=None)


def _evicted_block_ids(
    events: Sequence[Mapping[str, object]],
    *,
    after_index: int,
    decision_index: int,
    process_id: str,
) -> set[int]:
    """Block ids evicted by this hash process between the snapshot and the decision."""
    evicted: set[int] = set()
    for event in events:
        if event.get("event_type") != "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED":
            continue
        index = int(event.get("event_index", -1))
        if not after_index < index < decision_index:
            continue
        payload = event.get("payload") or {}
        if payload.get("native_hash_process_id") != process_id:
            continue
        block_id = payload.get("block_id")
        if isinstance(block_id, int) and not isinstance(block_id, bool):
            evicted.add(block_id)
    return evicted


def prove_chain(
    events: Sequence[Mapping[str, object]],
    *,
    candidate: Mapping[str, object],
    decision_index: int,
) -> ChainProof:
    """Prove that this candidate's blocks still hold the content a snapshot recorded.

    Mirrors ``phase2d_shared_retention._mapping_for_candidate``: ordered list equality
    with the latest prior snapshot, complete payload, and no intervening eviction by
    the same hash process. Failing any step yields a non-proved proof with a reason,
    never a partial mapping.
    """
    program_id = str(candidate.get("program_id"))
    prefix_id = str(candidate.get("prefix_id"))
    chain = chain_key(program_id, prefix_id)

    candidate_blocks = candidate.get("block_ids")
    if not isinstance(candidate_blocks, list) or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in candidate_blocks
    ):
        return ChainProof(chain, SNAPSHOT_PAYLOAD_INCOMPLETE, "candidate block_ids unusable")

    snapshot = _latest_prior_snapshot(
        events,
        decision_index=decision_index,
        program_id=program_id,
        prefix_id=prefix_id,
    )
    if snapshot is None:
        return ChainProof(chain, NO_PRIOR_SNAPSHOT, "no prior matching VLLM_PREFIX_SNAPSHOT")

    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        return ChainProof(
            chain, SNAPSHOT_PAYLOAD_INCOMPLETE, "snapshot payload is not an object"
        )

    snapshot_blocks = payload.get("block_ids")
    hashes = payload.get("ordered_native_hashes")
    cache_keys = payload.get("ordered_native_cache_keys")
    process_id = payload.get("native_hash_process_id")
    if (
        not isinstance(snapshot_blocks, list)
        or not isinstance(hashes, list)
        or not isinstance(cache_keys, list)
        or not isinstance(process_id, str)
        or not process_id
    ):
        return ChainProof(
            chain,
            SNAPSHOT_PAYLOAD_INCOMPLETE,
            "snapshot lacks block/hash/key/process fields",
        )

    if candidate_blocks != snapshot_blocks:
        return ChainProof(
            chain,
            CANDIDATE_BLOCKS_DIFFER,
            "decision candidate blocks differ from the latest prior snapshot",
        )
    if not (len(snapshot_blocks) == len(hashes) == len(cache_keys)):
        return ChainProof(
            chain, SEQUENCE_LENGTH_MISMATCH, "block/hash/cache-key lengths differ"
        )

    snapshot_index = int(snapshot["event_index"])
    evicted = _evicted_block_ids(
        events,
        after_index=snapshot_index,
        decision_index=decision_index,
        process_id=process_id,
    )
    if evicted.intersection(int(block) for block in snapshot_blocks):
        return ChainProof(
            chain,
            BLOCK_EVICTED_BEFORE_DECISION,
            "a mapped physical block was evicted before the decision; slot may be reused",
            snapshot_event_index=snapshot_index,
            process_id=process_id,
        )

    return ChainProof(
        chain,
        PROVED,
        "latest pre-decision block/hash/process mapping is complete and unevicted",
        snapshot_event_index=snapshot_index,
        process_id=process_id,
        block_ids=tuple(int(block) for block in snapshot_blocks),
        hashes=tuple(str(value) for value in hashes),
    )


def _deadline_by_chain(
    candidates: Sequence[Mapping[str, object]],
    rows: Mapping[CandidateKey, object],
) -> dict[ChainKey, float]:
    """Deadline per chain, read from the event payload rather than the row.

    The replay row fills a missing deadline with ``0.0`` so that the frozen release
    order stays total. That default must not become a reuse weight, so the original
    candidate entry is authoritative here.
    """
    deadlines: dict[ChainKey, float] = {}
    for entry in candidates:
        chain = chain_key(str(entry.get("program_id")), str(entry.get("prefix_id")))
        raw = entry.get("retention_deadline_timestamp")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            deadlines[chain] = float(raw)
    del rows
    return deadlines


def build_geometry(
    decision: DecisionInput,
    *,
    need: int,
    tau_seconds: float = DEFAULT_TAU_SECONDS,
) -> DecisionGeometry:
    """Assemble the legal candidate set with proved memberships and chain weights.

    ``need`` is the eviction count the frozen loop is trying to satisfy. The legal set
    is ``E(R)`` after the frozen release, so the entry layer is held fixed and only
    the block choice varies.

    A hash-carrying block whose chain could not be proved is recorded as
    ``content_unverified``. A proved chain without a reuse weight is recorded in
    ``unknown_weight_chains``. Either makes the decision unscorable rather than
    silently cheaper.
    """
    snapshot = decision.snapshot
    rows = decision.rows

    # The entry layer is held fixed: replay the frozen release, then take the
    # resulting legal set. Only the block choice varies between the two rules.
    replay = replay_decision(snapshot, ExecutedP1BStrategy(), rows)  # type: ignore[arg-type]
    state = ReplayState(snapshot)
    for key in replay.released:
        state.release(key)
    legal_ids = sorted(state.eligible_block_ids())

    proved = {chain: proof for chain, proof in decision.proofs.items() if proof.proved}
    chain_lengths: dict[ChainKey, int] = {
        chain: len(proof.block_ids) for chain, proof in proved.items()
    }

    deadlines = _deadline_by_chain(decision.candidates, rows)
    q_by_chain: dict[ChainKey, float] = {}
    weight_gaps: set[ChainKey] = set()
    for chain in proved:
        deadline = deadlines.get(chain)
        if deadline is None:
            # A real chain with content but no decision-time reuse weight is not a
            # zero-cost chain; defaulting it to 0 would understate its loss.
            weight_gaps.add(chain)
            continue
        q_by_chain[chain] = reuse_proxy(deadline, snapshot.timestamp, tau_seconds)

    blocks: dict[int, LegalBlock] = {}
    gaps: dict[int, str] = {}
    block_has_hash = {block.block_id: block.has_block_hash for block in snapshot.queue}
    for block_id in legal_ids:
        has_hash = block_has_hash.get(block_id, True)
        memberships: list[Membership] = []
        degraded = False
        for chain, proof in proved.items():
            depth = proof.depth_of(block_id)
            if depth is None:
                continue
            content = proof.hash_of(block_id)
            if content is None or chain in weight_gaps:
                degraded = True
                continue
            memberships.append(Membership(chain=chain, depth=depth, content_hash=content))
        if not memberships and has_hash:
            # No chain could prove this block's content. Recording a depth anyway
            # would be exactly the slot-id-as-identity error this module exists to
            # avoid, so the block is marked unknown instead.
            gaps[block_id] = GAP_DEPTH_UNKNOWN if degraded else GAP_CONTENT_UNVERIFIED
        blocks[block_id] = LegalBlock(
            block_id=block_id,
            native_rank=snapshot.ranking_by_block.get(block_id, 0),
            memberships=tuple(memberships),
            has_block_hash=has_hash,
        )

    del need
    return DecisionGeometry(
        blocks=blocks,
        chain_length=chain_lengths,
        q_by_chain=q_by_chain,
        gaps=gaps,
        unknown_weight_chains=tuple(sorted(weight_gaps)),
    )


def decisions_from_events(
    run_id: str,
    events: Sequence[Mapping[str, object]],
    *,
    row_factory,
) -> list[DecisionInput]:
    """Every forced-release decision in one run, with per-chain identity proofs.

    ``row_factory`` turns event candidates into ``DecisionCandidateRow``-shaped
    objects; it is injected so this module does not depend on the derived pipeline.
    """
    built: list[DecisionInput] = []
    for event in events:
        if event.get("event_type") != "FORCED_RELEASE_DECISION":
            continue
        event_index = int(event.get("event_index", -1))
        snapshot = _snapshot_from_event(run_id, event)
        candidates = tuple(_candidate_entries(event))
        rows = {
            (key[0], key[1]): row_factory(run_id, event_index, entry)
            for key, entry in candidates
        }
        proofs = {
            chain_key(str(entry.get("program_id")), str(entry.get("prefix_id"))): prove_chain(
                events, candidate=entry, decision_index=event_index
            )
            for _, entry in candidates
        }
        built.append(
            DecisionInput(
                snapshot=snapshot,
                rows=rows,
                proofs=proofs,
                candidates=tuple(entry for _, entry in candidates),
            )
        )
    return built


def _candidate_entries(
    event: Mapping[str, object],
) -> Iterable[tuple[CandidateKey, Mapping[str, object]]]:
    payload = event.get("payload") or {}
    for candidate in payload.get("candidates") or ():
        entry = dict(candidate)
        key = (str(entry.get("program_id")), str(entry.get("prefix_id")))
        yield key, entry


def read_run_events(run_dir: Path) -> list[dict[str, object]]:
    """Read ``events.jsonl`` for one run directory."""
    path = run_dir / "events.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"missing events.jsonl: {run_dir}")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def candidate_row(run_id: str, decision_event_index: int, entry: Mapping[str, object]):
    """Minimal candidate row for the frozen replay, built from persisted fields.

    Only fields the frozen release order reads are populated; everything else is left
    at a neutral value rather than invented, so a missing field cannot silently change
    the entry layer that A2 holds fixed.
    """
    from kvopt.profiling.datasets import DecisionCandidateRow

    block_ids = tuple(int(b) for b in (entry.get("block_ids") or ()))
    reclaimable = tuple(
        int(b) for b in (entry.get("initially_reclaimable_block_ids") or ())
    )
    deadline = entry.get("retention_deadline_timestamp")
    return DecisionCandidateRow(
        run_id=run_id,
        decision_event_index=decision_event_index,
        source_event_index=decision_event_index,
        candidate_position=0,
        program_id=str(entry.get("program_id")),
        prefix_id=str(entry.get("prefix_id")),
        selected=False,
        release_order=None,
        retention_deadline_timestamp=(
            float(deadline) if isinstance(deadline, (int, float)) else 0.0
        ),
        waiting_followup=bool(entry.get("waiting_followup", False)),
        block_ids=block_ids,
        block_count=len(block_ids),
        initially_reclaimable_block_ids=reclaimable,
        initially_reclaimable_block_count=len(reclaimable),
        next_tool_type=entry.get("next_tool_type"),
        elapsed_since_ttl_decision_seconds=float(
            entry.get("elapsed_since_ttl_decision_seconds") or 0.0
        ),
        prefill_reload_seconds=float(entry.get("prefill_reload_seconds") or 0.0),
        eta=float(entry.get("eta") or 0.0),
        queue_delay_t_seconds=float(entry.get("queue_delay_t_seconds") or 0.0),
        decision_native_lru_position=None,
    )


def decisions_for_run(run_dir: Path) -> list[DecisionInput]:
    """Convenience wrapper: read one run and return its decisions."""
    events = read_run_events(run_dir)
    return decisions_from_events(run_dir.name, events, row_factory=candidate_row)
