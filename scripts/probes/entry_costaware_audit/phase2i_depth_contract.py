"""Phase 2I RC5: the runtime depth contract, as executable checks.

Why this exists
---------------
An earlier version of the design claimed that ``RetentionEntrySnapshot.block_ids``
index equals the original prefix depth. That is false once a block is evicted:

    retention.py::observe_eviction(block_id)
        entry.block_ids = tuple(b for b in entry.block_ids if b != block_id)
    retention.py::reconcile_entry_evictions(key, block_ids)
        entry.block_ids = tuple(b for b in entry.block_ids if b not in stale)

Both **compact** the tuple. If depth ``d`` is evicted, every block after it shifts
down by one, so ``index(block) + 1`` stops being that block's depth, and
``len(block_ids)`` stops being the chain length ``m``. ``S = m - d_min + 1`` would then
be computed from a compressed index and would be wrong for every block behind a hole.

The fix, and what this file proves
----------------------------------
Keep depth as **metadata recorded when the chain was observed**, not as an array
position, and bind it to **content identity** so a recycled physical slot cannot
inherit an old depth:

    ChainDepthProof
        chain_id                     (program_id, prefix_id)
        native_hash_process_id       proves the hashes come from one runtime
        block_ids                    physical slots at observation time
        content_hashes               aligned with block_ids
        depths                       aligned with block_ids, the authoritative depth
        observed_at                  monotonic timestamp of the observation

Depth is recovered by looking up ``(native_hash_process_id, content_hash)``, never by
position and never by ``block_id`` alone. A block whose content identity no longer
matches the recorded proof contributes **no** depth; the caller must then fail closed
rather than substitute a compressed index.

RC8 adds the identity and freshness half of that contract. Storing
``native_hash_process_id``, ``chain_id`` and ``observed_at`` is worthless unless the
lookup *checks* them, so every query now carries the chain it belongs to, the runtime
process it was observed in, and the decision time it is being used for. A proof from a
different chain, a different process, the future, or one that has gone stale resolves to
``None`` with an explicit reason instead of silently returning a number.

Run this file directly to execute the contract checks.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

#: How long a recorded chain proof stays usable. This is a correctness ceiling, not a
#: tuning knob: a proof older than this may describe a prefix the runtime has since
#: rebuilt, and the depth it carries would then be an assertion about a chain that no
#: longer exists. The structural requirement (the proof must be the latest observation
#: strictly before the decision) is checked separately and is the stronger of the two.
DEFAULT_MAX_AGE_SECONDS = 600.0


class DepthStatus(str, Enum):
    """Why a depth lookup did or did not produce a value.

    Only ``OK`` yields a depth. Every other member is a fail-closed signal that the
    caller must surface rather than paper over.
    """

    OK = "OK"
    WRONG_CHAIN = "WRONG_CHAIN"
    WRONG_PROCESS = "WRONG_PROCESS"
    FUTURE_PROOF = "FUTURE_PROOF"
    STALE_PROOF = "STALE_PROOF"
    CONTENT_MISMATCH = "CONTENT_MISMATCH"
    UNKNOWN_BLOCK = "UNKNOWN_BLOCK"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class DepthQuery:
    """The identity and time context a depth lookup must be validated against.

    A bare ``(block_id, content_hash)`` pair is not enough: the same physical slot can

    appear in another chain, in another runtime process, or at a much later time.
    """

    chain_id: tuple[str, str]
    native_hash_process_id: str
    decision_at: float


@dataclass(frozen=True, slots=True)
class ChainDepthProof:
    """Immutable, content-keyed depth record for one observed chain."""

    chain_id: tuple[str, str]
    native_hash_process_id: str
    block_ids: tuple[int, ...]
    content_hashes: tuple[str | None, ...]
    depths: tuple[int, ...]
    observed_at: float
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS

    def __post_init__(self) -> None:
        if not self.native_hash_process_id:
            raise ValueError("native_hash_process_id must be non-empty")
        count = len(self.block_ids)
        if count == 0:
            raise ValueError("a chain proof must describe at least one block")
        if len(self.content_hashes) != count or len(self.depths) != count:
            raise ValueError("block_ids, content_hashes and depths must be aligned")
        if len(set(self.block_ids)) != count:
            raise ValueError("block_ids must not contain duplicates")
        if sorted(self.depths) != list(range(1, count + 1)):
            raise ValueError("depths must be exactly 1..n, one per block, no holes")
        if not self.chain_id[0] or not self.chain_id[1]:
            raise ValueError("chain_id must name both a program and a prefix")
        if self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")

    @property
    def chain_length(self) -> int:
        """``m``: the full prefix length at observation time, never a live count."""
        return len(self.depths)

    @property
    def identity_verified(self) -> bool:
        """False when any recorded slot lacks a usable content identity.

        The archive can contain snapshots whose ordered content keys are absent or
        unusable. Such a proof can still describe depths, but it cannot prove that a
        block still holds the content it held when the chain was observed, so it must
        be reported as ``IDENTITY_UNVERIFIED`` rather than treated as verified.
        """
        return all(value is not None and value != "" for value in self.content_hashes)

    def depth_of(
        self, query: DepthQuery, block_id: int, content_hash: str
    ) -> tuple[int | None, DepthStatus]:
        """Depth of one slot, validated against identity, freshness and content.

        Every rejection is attributed to exactly one reason so the caller can report
        *why* a decision became unscorable instead of guessing.
        """
        if query.chain_id != self.chain_id:
            return None, DepthStatus.WRONG_CHAIN
        if query.native_hash_process_id != self.native_hash_process_id:
            return None, DepthStatus.WRONG_PROCESS
        if query.decision_at < self.observed_at:
            return None, DepthStatus.FUTURE_PROOF
        if query.decision_at - self.observed_at > self.max_age_seconds:
            return None, DepthStatus.STALE_PROOF
        if not self.identity_verified:
            return None, DepthStatus.IDENTITY_UNVERIFIED
        for index, known_block in enumerate(self.block_ids):
            if known_block != block_id:
                continue
            if self.content_hashes[index] != content_hash:
                return None, DepthStatus.CONTENT_MISMATCH
            return self.depths[index], DepthStatus.OK
        return None, DepthStatus.UNKNOWN_BLOCK

    def depths_for(
        self,
        query: DepthQuery,
        block_ids: tuple[int, ...],
        live_hashes: dict[int, str],
    ) -> tuple[dict[int, int], dict[int, DepthStatus]]:
        """Resolve depths for a victim set, splitting resolved from unresolvable.

        Returns ``(resolved, unresolved)`` where ``unresolved`` maps each unresolved
        block to the status that explains it. The caller must treat a non-empty
        ``unresolved`` as a fail-closed condition: no depth is guessed for those, and a
        partial resolution is never accepted as a partial score.
        """
        resolved: dict[int, int] = {}
        unresolved: dict[int, DepthStatus] = {}
        for block_id in block_ids:
            content_hash = live_hashes.get(block_id)
            if content_hash is None:
                unresolved[block_id] = DepthStatus.IDENTITY_UNVERIFIED
                continue
            depth, status = self.depth_of(query, block_id, content_hash)
            if depth is None:
                unresolved[block_id] = status
            else:
                resolved[block_id] = depth
        return resolved, unresolved


# ---------------------------------------------------------------------------
# contract checks
# ---------------------------------------------------------------------------


def check_partial_eviction_does_not_drift_depth() -> list[str]:
    """Depth must survive the hole left by an evicted interior block.

    Every survivor is asserted **individually** against an explicit expected depth. An
    earlier version compared against a compound ``or`` of two candidate values, which
    meant a compressed index that happened to equal the other branch would still PASS —
    the check had no teeth exactly where it mattered.
    """
    problems: list[str] = []
    proof = ChainDepthProof(
        chain_id=("program-a", "prefix-1"),
        native_hash_process_id="pid-1",
        block_ids=(10, 11, 12, 13, 14, 15),
        content_hashes=("h1", "h2", "h3", "h4", "h5", "h6"),
        depths=(1, 2, 3, 4, 5, 6),
        observed_at=100.0,
    )
    query = DepthQuery(("program-a", "prefix-1"), "pid-1", decision_at=150.0)
    # Depth 3 (block 12) is evicted, so the live snapshot becomes (10, 11, 13, 14, 15).
    # The naive rule "index + 1" would now call block 13 depth 3 instead of 4.
    survivors = (10, 11, 13, 14, 15)
    live = {10: "h1", 11: "h2", 13: "h4", 14: "h5", 15: "h6"}
    expected = {10: 1, 11: 2, 13: 4, 14: 5, 15: 6}
    for block_id in survivors:
        depth, status = proof.depth_of(query, block_id, live[block_id])
        if status is not DepthStatus.OK:
            problems.append(f"block {block_id} unresolved with {status.value}")
            continue
        if depth != expected[block_id]:
            problems.append(
                f"block {block_id} reported depth {depth}, expected {expected[block_id]}"
            )
    # The check only has teeth if at least one survivor disagrees with its array index.
    drifted = [b for b in survivors if expected[b] != survivors.index(b) + 1]
    if not drifted:
        problems.append("expected at least one survivor to differ from its array index")
    if sorted(drifted) != [13, 14, 15]:
        problems.append(
            f"survivors whose depth differs from index are {drifted}, expected [13, 14, 15]"
        )
    if proof.chain_length != 6:
        problems.append(f"chain length became {proof.chain_length}, expected 6")
    return problems


def check_recycled_block_id_does_not_inherit_depth() -> list[str]:
    """A reused physical slot with new content must not report the old depth."""
    problems: list[str] = []
    proof = ChainDepthProof(
        chain_id=("program-b", "prefix-2"),
        native_hash_process_id="pid-1",
        block_ids=(20, 21, 22),
        content_hashes=("a1", "a2", "a3"),
        depths=(1, 2, 3),
        observed_at=200.0,
    )
    query = DepthQuery(("program-b", "prefix-2"), "pid-1", decision_at=210.0)
    # Slot 21 is recycled for unrelated content "zz".
    inherited, status = proof.depth_of(query, 21, "zz")
    if inherited is not None:
        problems.append(f"recycled slot inherited depth {inherited}")
    if status is not DepthStatus.CONTENT_MISMATCH:
        problems.append(f"recycled slot reported {status.value}, expected CONTENT_MISMATCH")
    # The same slot with its original content is still valid.
    depth, status = proof.depth_of(query, 21, "a2")
    if (depth, status) != (2, DepthStatus.OK):
        problems.append(f"original content resolved to ({depth}, {status.value})")
    return problems


def check_resolution_reports_unresolvable_separately() -> list[str]:
    """Unresolvable victims must be reported, never silently dropped."""
    problems: list[str] = []
    proof = ChainDepthProof(
        chain_id=("program-c", "prefix-3"),
        native_hash_process_id="pid-1",
        block_ids=(30, 31, 32, 33),
        content_hashes=("c1", "c2", "c3", "c4"),
        depths=(1, 2, 3, 4),
        observed_at=300.0,
    )
    query = DepthQuery(("program-c", "prefix-3"), "pid-1", decision_at=310.0)
    victims = (30, 31, 33, 99)
    live = {30: "c1", 31: "c2", 33: "c4", 99: "unknown"}
    resolved, unresolved = proof.depths_for(query, victims, live)
    if resolved != {30: 1, 31: 2, 33: 4}:
        problems.append(f"resolved set is {resolved}")
    if set(unresolved) != {99}:
        problems.append(f"unresolved set is {sorted(unresolved)}, expected [99]")
    if unresolved.get(99) is not DepthStatus.UNKNOWN_BLOCK:
        problems.append(f"block 99 reported {unresolved.get(99)}, expected UNKNOWN_BLOCK")
    # A partial resolution must not be usable as a partial score.
    if not unresolved:
        problems.append("partial resolution was reported as fully resolved")
    return problems


def check_suffix_uses_recorded_length_not_live_count() -> list[str]:
    """``S = m - d_min + 1`` must use the recorded chain length."""
    problems: list[str] = []
    proof = ChainDepthProof(
        chain_id=("program-d", "prefix-4"),
        native_hash_process_id="pid-1",
        block_ids=tuple(range(40, 50)),
        content_hashes=tuple(f"d{i}" for i in range(1, 11)),
        depths=tuple(range(1, 11)),
        observed_at=400.0,
    )
    query = DepthQuery(("program-d", "prefix-4"), "pid-1", decision_at=450.0)
    # Four interior blocks evicted; live list has 6 entries but m is still 10.
    survivors = (40, 41, 45, 46, 47, 48, 49)
    live = {b: f"d{b - 39}" for b in survivors}
    victim_ids = (45, 46)
    resolved, unresolved = proof.depths_for(query, victim_ids, live)
    if unresolved:
        problems.append(f"unexpected unresolved victims {sorted(unresolved)}")
    d_min = min(resolved.values())
    suffix_from_records = proof.chain_length - d_min + 1
    suffix_from_live = len(survivors) - d_min + 1
    # Victims are depths 6 and 7 of a 10-block chain, so the killed suffix is 5.
    if suffix_from_records != 5:
        problems.append(f"recorded-length suffix is {suffix_from_records}, expected 5")
    if suffix_from_live == suffix_from_records:
        problems.append("expected the live-count suffix to differ, so the check has teeth")
    return problems


def check_degenerate_geometry_is_detected() -> list[str]:
    """An all-deepest victim set must be detectable, not assumed harmless."""
    problems: list[str] = []
    proof = ChainDepthProof(
        chain_id=("program-e", "prefix-5"),
        native_hash_process_id="pid-1",
        block_ids=(50, 51, 52, 53),
        content_hashes=("e1", "e2", "e3", "e4"),
        depths=(1, 2, 3, 4),
        observed_at=500.0,
    )
    query = DepthQuery(("program-e", "prefix-5"), "pid-1", decision_at=520.0)
    live = {b: f"e{b - 49}" for b in (50, 51, 52, 53)}
    deepest_only, _ = proof.depths_for(query, (53,), live)
    interior, _ = proof.depths_for(query, (51, 53), live)
    suffix_deepest = proof.chain_length - min(deepest_only.values()) + 1
    suffix_interior = proof.chain_length - min(interior.values()) + 1
    if suffix_deepest != 1:
        problems.append(f"all-deepest suffix is {suffix_deepest}, expected 1")
    # Shallowest victim is depth 2 of 4, so the killed suffix is 3.
    if suffix_interior != 3:
        problems.append(f"interior-victim suffix is {suffix_interior}, expected 3")
    return problems


# ---------------------------------------------------------------------------
# RC8: identity and freshness must be *checked*, not merely stored
# ---------------------------------------------------------------------------


def _rc8_proof(content_hashes: tuple[str | None, ...] = ("g1", "g2", "g3")) -> ChainDepthProof:
    return ChainDepthProof(
        chain_id=("program-f", "prefix-6"),
        native_hash_process_id="pid-A",
        block_ids=(60, 61, 62),
        content_hashes=content_hashes,
        depths=(1, 2, 3),
        observed_at=1_000.0,
    )


def check_query_must_match_chain_and_process() -> list[str]:
    """A proof from another chain or another runtime must not answer the query."""
    problems: list[str] = []
    proof = _rc8_proof()

    other_chain = DepthQuery(("program-f", "prefix-OTHER"), "pid-A", decision_at=1_010.0)
    depth, status = proof.depth_of(other_chain, 61, "g2")
    if depth is not None:
        problems.append(f"cross-chain query returned depth {depth}")
    if status is not DepthStatus.WRONG_CHAIN:
        problems.append(f"cross-chain query reported {status.value}, expected WRONG_CHAIN")

    other_process = DepthQuery(("program-f", "prefix-6"), "pid-B", decision_at=1_010.0)
    depth, status = proof.depth_of(other_process, 61, "g2")
    if depth is not None:
        problems.append(f"cross-process query returned depth {depth}")
    if status is not DepthStatus.WRONG_PROCESS:
        problems.append(f"cross-process query reported {status.value}, expected WRONG_PROCESS")

    # The matching identity still resolves, so the check is not rejecting everything.
    good = DepthQuery(("program-f", "prefix-6"), "pid-A", decision_at=1_010.0)
    if proof.depth_of(good, 61, "g2") != (2, DepthStatus.OK):
        problems.append("matching chain/process failed to resolve")
    return problems


def check_proof_must_precede_decision_and_stay_fresh() -> list[str]:
    """A proof from the future, or one that has aged out, is not evidence."""
    problems: list[str] = []
    proof = _rc8_proof()

    before_observation = DepthQuery(("program-f", "prefix-6"), "pid-A", decision_at=999.0)
    depth, status = proof.depth_of(before_observation, 61, "g2")
    if depth is not None:
        problems.append(f"future proof returned depth {depth}")
    if status is not DepthStatus.FUTURE_PROOF:
        problems.append(f"future proof reported {status.value}, expected FUTURE_PROOF")

    just_after = DepthQuery(("program-f", "prefix-6"), "pid-A", decision_at=1_000.0)
    if proof.depth_of(just_after, 61, "g2") != (2, DepthStatus.OK):
        problems.append("a proof observed exactly at decision time must still be usable")

    aged_out = DepthQuery(
        ("program-f", "prefix-6"),
        "pid-A",
        decision_at=1_000.0 + DEFAULT_MAX_AGE_SECONDS + 1.0,
    )
    depth, status = proof.depth_of(aged_out, 61, "g2")
    if depth is not None:
        problems.append(f"stale proof returned depth {depth}")
    if status is not DepthStatus.STALE_PROOF:
        problems.append(f"stale proof reported {status.value}, expected STALE_PROOF")

    at_limit = DepthQuery(
        ("program-f", "prefix-6"),
        "pid-A",
        decision_at=1_000.0 + DEFAULT_MAX_AGE_SECONDS,
    )
    if proof.depth_of(at_limit, 61, "g2") != (2, DepthStatus.OK):
        problems.append("a proof exactly at the age limit must still be usable")
    return problems


def check_missing_content_identity_is_unverified_not_ok() -> list[str]:
    """Without content identity the proof cannot claim a verified depth.

    Offline archives may lack ordered content keys for a snapshot. That case must be
    reported as ``IDENTITY_UNVERIFIED`` so the caller fails closed instead of treating a
    depth-only record as proof of *which* content occupies the slot.
    """
    problems: list[str] = []
    proof = _rc8_proof(content_hashes=("g1", None, "g3"))
    if proof.identity_verified:
        problems.append("a proof with a missing content key claimed to be verified")
    query = DepthQuery(("program-f", "prefix-6"), "pid-A", decision_at=1_010.0)
    depth, status = proof.depth_of(query, 60, "g1")
    if depth is not None:
        problems.append(f"unverified identity returned depth {depth}")
    if status is not DepthStatus.IDENTITY_UNVERIFIED:
        problems.append(f"unverified identity reported {status.value}")
    resolved, unresolved = proof.depths_for(query, (60, 61), {60: "g1", 61: "g2"})
    if resolved:
        problems.append(f"partially verified proof resolved {resolved}")
    if set(unresolved) != {60, 61}:
        problems.append(f"unresolved is {sorted(unresolved)}, expected both victims")
    if any(status is not DepthStatus.IDENTITY_UNVERIFIED for status in unresolved.values()):
        problems.append("unverified reasons were not preserved")
    return problems


def check_archive_shaped_proof_round_trips() -> list[str]:
    """A proof built from archive-shaped snapshot fields must resolve its own chain.

    Mirrors ``VLLM_PREFIX_SNAPSHOT``: ordered ``block_ids`` plus
    ``ordered_native_cache_keys`` plus ``native_hash_process_id``. The depths are the
    observation-time positions, which is exactly what the snapshot order encodes.
    """
    problems: list[str] = []
    block_ids = (1, 2, 3, 4, 84, 85)
    cache_keys = tuple(f"key{i}" for i in range(1, 7))
    proof = ChainDepthProof(
        chain_id=("proj__repo-1234", "prefix-0"),
        native_hash_process_id="1299",
        block_ids=block_ids,
        content_hashes=cache_keys,
        depths=tuple(range(1, len(block_ids) + 1)),
        observed_at=10.0,
    )
    query = DepthQuery(("proj__repo-1234", "prefix-0"), "1299", decision_at=20.0)
    # Interior eviction: block 3 holds depth 3, block 84 holds depth 5.
    for block_id, expected in ((3, 3), (84, 5), (85, 6)):
        depth, status = proof.depth_of(query, block_id, cache_keys[block_ids.index(block_id)])
        if (depth, status) != (expected, DepthStatus.OK):
            problems.append(
                f"block {block_id} resolved to ({depth}, {status.value}), expected {expected}"
            )
    if proof.chain_length != len(block_ids):
        problems.append(f"chain length is {proof.chain_length}")
    return problems


CHECKS = (
    ("partial eviction does not drift depth", check_partial_eviction_does_not_drift_depth),
    ("recycled block id does not inherit depth", check_recycled_block_id_does_not_inherit_depth),
    (
        "unresolvable victims are reported, not dropped",
        check_resolution_reports_unresolvable_separately,
    ),
    (
        "suffix uses recorded length, not live count",
        check_suffix_uses_recorded_length_not_live_count,
    ),
    ("degenerate all-deepest geometry is detectable", check_degenerate_geometry_is_detected),
    ("RC8 query must match chain and process", check_query_must_match_chain_and_process),
    (
        "RC8 proof must precede decision and stay fresh",
        check_proof_must_precede_decision_and_stay_fresh,
    ),
    (
        "RC8 missing content identity is unverified, not OK",
        check_missing_content_identity_is_unverified_not_ok,
    ),
    ("RC8 archive-shaped proof round trips", check_archive_shaped_proof_round_trips),
)


def main() -> int:
    failures = 0
    for name, check in CHECKS:
        problems = check()
        if problems:
            failures += 1
            print(f"  FAIL  {name}")
            for problem in problems:
                print(f"          {problem}")
        else:
            print(f"  PASS  {name}")
    print()
    if failures:
        print(f"{failures} contract check(s) failed")
        return 1
    print("all contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
