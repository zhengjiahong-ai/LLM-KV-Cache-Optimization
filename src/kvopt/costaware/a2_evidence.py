"""Build A2 block geometry from recorded Phase 2G evidence.

Two event types are used, both already persisted:

``VLLM_PREFIX_SNAPSHOT``
    ``(program_id, prefix_id)``, ``block_ids`` and ``ordered_native_hashes``
    aligned by position. This is the **only** source of true prefix depth and
    content identity: position ``i`` means depth ``i + 1`` and the hash at that
    position is the block's content.

``FORCED_RELEASE_DECISION``
    ``required_blocks``, ``original_free_queue`` with ``native_lru_rank`` and
    ``has_block_hash``, and the candidate entries with their
    ``retention_deadline_timestamp`` and ``block_ids``. This gives the legal
    candidate set (through the frozen release replay) and the per-chain reuse
    proxy.

What is deliberately not used: ``native_lru_rank`` never becomes a depth, and a
block with several owners keeps all of them. Where depth or content cannot be
recovered, the decision records a gap instead of guessing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .a2_geometry import (
    GAP_DEPTH_UNKNOWN,
    GAP_NO_MEMBERSHIP,
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


@dataclass(frozen=True, slots=True)
class ChainPrefix:
    """One chain's ordered content: block ids and their hashes, position aligned."""

    chain: ChainKey
    event_index: int
    block_ids: tuple[int, ...]
    hashes: tuple[str, ...]

    def depth_of(self, block_id: int) -> int | None:
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
    """One decision plus the chain snapshots that were current at that moment."""

    snapshot: DecisionSnapshot
    rows: Mapping[CandidateKey, object]
    chains: Mapping[ChainKey, ChainPrefix]


def chain_key(program_id: str, prefix_id: str) -> ChainKey:
    return f"{program_id}:{prefix_id}"


def _snapshot_chains(events: Sequence[Mapping[str, object]]) -> dict[int, dict[ChainKey, ChainPrefix]]:
    """Index chain snapshots by event index, so a decision sees only prior ones."""
    per_event: dict[int, dict[ChainKey, ChainPrefix]] = {}
    current: dict[ChainKey, ChainPrefix] = {}
    for event in events:
        if event.get("event_type") != "VLLM_PREFIX_SNAPSHOT":
            continue
        payload = event.get("payload") or {}
        block_ids = tuple(int(b) for b in (payload.get("block_ids") or ()))
        hashes = tuple(str(h) for h in (payload.get("ordered_native_hashes") or ()))
        if len(block_ids) != len(hashes):
            # Positional alignment is the whole basis for depth; refuse to guess.
            continue
        chain = chain_key(str(event.get("program_id")), str(event.get("prefix_id")))
        current = dict(current)
        current[chain] = ChainPrefix(
            chain=chain,
            event_index=int(event.get("event_index", -1)),
            block_ids=block_ids,
            hashes=hashes,
        )
        per_event[int(event.get("event_index", -1))] = dict(current)
    return per_event


def _latest_before(
    per_event: Mapping[int, dict[ChainKey, ChainPrefix]], event_index: int
) -> dict[ChainKey, ChainPrefix]:
    candidates = [index for index in per_event if index <= event_index]
    if not candidates:
        return {}
    return per_event[max(candidates)]


def _deadline_by_chain(
    payload: Mapping[str, object],
) -> dict[ChainKey, float]:
    deadlines: dict[ChainKey, float] = {}
    for candidate in payload.get("candidates") or ():
        entry = dict(candidate)
        chain = chain_key(str(entry.get("program_id")), str(entry.get("prefix_id")))
        raw = entry.get("retention_deadline_timestamp")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            deadlines[chain] = float(raw)
    return deadlines


def build_geometry(
    decision: DecisionInput,
    *,
    need: int,
    tau_seconds: float = DEFAULT_TAU_SECONDS,
) -> DecisionGeometry:
    """Assemble the legal candidate set with memberships, depths and chain weights.

    ``need`` is the eviction count the frozen loop is trying to satisfy. The legal
    set is ``E(R)`` after the frozen release, so the entry layer is held fixed and
    only the block choice varies.
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

    chain_lengths: dict[ChainKey, int] = {
        chain: len(prefix.block_ids) for chain, prefix in decision.chains.items()
    }
    q_by_chain: dict[ChainKey, float] = {
        chain: reuse_proxy(deadline, snapshot.timestamp, tau_seconds)
        for chain, deadline in _deadline_by_chain_from_rows(rows).items()
    }
    for chain in chain_lengths:
        q_by_chain.setdefault(chain, 0.0)

    blocks: dict[int, LegalBlock] = {}
    gaps: dict[int, str] = {}
    block_has_hash = {block.block_id: block.has_block_hash for block in snapshot.queue}
    for block_id in legal_ids:
        has_hash = block_has_hash.get(block_id, True)
        memberships: list[Membership] = []
        for chain, prefix in decision.chains.items():
            depth = prefix.depth_of(block_id)
            if depth is None:
                continue
            content = prefix.hash_of(block_id)
            if content is None:
                gaps[block_id] = GAP_DEPTH_UNKNOWN
                continue
            memberships.append(
                Membership(chain=chain, depth=depth, content_hash=content)
            )
        if not memberships and has_hash:
            # A hash-carrying block with no chain is genuinely unobserved: its
            # content is not recoverable from the decision payload. A hashless
            # block needs no chain, because it costs nothing to evict.
            gaps[block_id] = GAP_NO_MEMBERSHIP
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
    )


def _deadline_by_chain_from_rows(
    rows: Mapping[CandidateKey, object],
) -> dict[ChainKey, float]:
    deadlines: dict[ChainKey, float] = {}
    for key, row in rows.items():
        raw = getattr(row, "retention_deadline_timestamp", None)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            deadlines[chain_key(key[0], key[1])] = float(raw)
    return deadlines


def decisions_from_events(
    run_id: str,
    events: Sequence[Mapping[str, object]],
    *,
    row_factory,
) -> list[DecisionInput]:
    """Every forced-release decision in one run, with its then-current chains.

    ``row_factory`` turns event candidates into ``DecisionCandidateRow``-shaped
    objects; it is injected so this module does not depend on the derived pipeline.
    """
    per_event = _snapshot_chains(events)
    built: list[DecisionInput] = []
    for event in events:
        if event.get("event_type") != "FORCED_RELEASE_DECISION":
            continue
        event_index = int(event.get("event_index", -1))
        snapshot = _snapshot_from_event(run_id, event)
        rows = {
            (key[0], key[1]): row_factory(run_id, event_index, entry)
            for key, entry in _candidate_entries(event)
        }
        built.append(
            DecisionInput(
                snapshot=snapshot,
                rows=rows,
                chains=_latest_before(per_event, event_index),
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


def candidate_row(
    run_id: str, decision_event_index: int, entry: Mapping[str, object]
):
    """Minimal candidate row for the frozen replay, built from persisted fields.

    Only fields the frozen release order reads are populated; everything else is
    left at a neutral value rather than invented, so a missing field cannot
    silently change the entry layer that A2 holds fixed.
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
