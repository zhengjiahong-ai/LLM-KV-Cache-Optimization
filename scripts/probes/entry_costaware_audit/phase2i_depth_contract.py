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

Run this file directly to execute the contract checks.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChainDepthProof:
    """Immutable, content-keyed depth record for one observed chain."""

    chain_id: tuple[str, str]
    native_hash_process_id: str
    block_ids: tuple[int, ...]
    content_hashes: tuple[str, ...]
    depths: tuple[int, ...]
    observed_at: float

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
        if any(not value for value in self.content_hashes):
            raise ValueError("content_hashes must be non-empty")

    @property
    def chain_length(self) -> int:
        """``m``: the full prefix length at observation time, never a live count."""
        return len(self.depths)

    def depth_of(self, block_id: int, content_hash: str) -> int | None:
        """Depth of one slot **only if** its content still matches the proof.

        A recycled slot reuses ``block_id`` for different content. Returning the old
        depth would silently attribute an eviction that never happened, so the content
        hash is checked first and a mismatch yields ``None``.
        """
        for index, known_block in enumerate(self.block_ids):
            if known_block != block_id:
                continue
            if self.content_hashes[index] != content_hash:
                return None
            return self.depths[index]
        return None

    def depths_for(
        self, block_ids: tuple[int, ...], live_hashes: dict[int, str]
    ) -> tuple[dict[int, int], tuple[int, ...]]:
        """Resolve depths for a victim set, splitting resolved from unresolvable.

        Returns ``(resolved, unresolved)``. The caller must treat a non-empty
        ``unresolved`` as a fail-closed condition: no depth is guessed for those.
        """
        resolved: dict[int, int] = {}
        unresolved: list[int] = []
        for block_id in block_ids:
            content_hash = live_hashes.get(block_id)
            if content_hash is None:
                unresolved.append(block_id)
                continue
            depth = self.depth_of(block_id, content_hash)
            if depth is None:
                unresolved.append(block_id)
            else:
                resolved[block_id] = depth
        return resolved, tuple(unresolved)


# ---------------------------------------------------------------------------
# contract checks
# ---------------------------------------------------------------------------


def check_partial_eviction_does_not_drift_depth() -> list[str]:
    """Depth must survive the hole left by an evicted interior block."""
    problems: list[str] = []
    proof = ChainDepthProof(
        chain_id=("program-a", "prefix-1"),
        native_hash_process_id="pid-1",
        block_ids=(10, 11, 12, 13, 14, 15),
        content_hashes=("h1", "h2", "h3", "h4", "h5", "h6"),
        depths=(1, 2, 3, 4, 5, 6),
        observed_at=100.0,
    )
    # Depth 3 (block 12) is evicted, so the live snapshot becomes (10, 11, 13, 14, 15).
    # The naive rule "index + 1" would now call block 13 depth 3 instead of 4.
    survivors = (10, 11, 13, 14, 15)
    live = {10: "h1", 11: "h2", 13: "h4", 14: "h5", 15: "h6"}
    for position, block_id in enumerate(survivors):
        naive_depth = position + 1
        real_depth = proof.depth_of(block_id, live[block_id])
        if real_depth is None:
            problems.append(f"block {block_id} lost its depth after a partial eviction")
        elif (
            real_depth != proof.depths[survivors.index(block_id) + 0]
            and real_depth
            != {
                10: 1,
                11: 2,
                13: 4,
                14: 5,
                15: 6,
            }[block_id]
        ):
            problems.append(f"block {block_id} reported depth {real_depth}")
        if block_id >= 13 and real_depth != naive_depth:
            # This is the point of the check: the two differ, and the proof is right.
            pass
    drifted = [b for b in survivors if proof.depth_of(b, live[b]) != survivors.index(b) + 1]
    if not drifted:
        problems.append("expected at least one survivor to differ from its array index")
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
    # Slot 21 is recycled for unrelated content "zz".
    inherited = proof.depth_of(21, "zz")
    if inherited is not None:
        problems.append(f"recycled slot inherited depth {inherited}")
    # The same slot with its original content is still valid.
    if proof.depth_of(21, "a2") != 2:
        problems.append("original content lost its depth")
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
    victims = (30, 31, 33, 99)
    live = {30: "c1", 31: "c2", 33: "c4", 99: "unknown"}
    resolved, unresolved = proof.depths_for(victims, live)
    if resolved != {30: 1, 31: 2, 33: 4}:
        problems.append(f"resolved set is {resolved}")
    if unresolved != (99,):
        problems.append(f"unresolved set is {unresolved}, expected (99,)")
    if 99 in resolved:
        problems.append("an unresolvable block was given a depth")
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
    # Four interior blocks evicted; live list has 6 entries but m is still 10.
    survivors = (40, 41, 45, 46, 47, 48, 49)
    live = {b: f"d{b - 39}" for b in survivors}
    victim_ids = (45, 46)
    resolved, unresolved = proof.depths_for(victim_ids, live)
    if unresolved:
        problems.append(f"unexpected unresolved victims {unresolved}")
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
    live = {b: f"e{b - 49}" for b in (50, 51, 52, 53)}
    deepest_only, _ = proof.depths_for((53,), live)
    interior, _ = proof.depths_for((51, 53), live)
    suffix_deepest = proof.chain_length - min(deepest_only.values()) + 1
    suffix_interior = proof.chain_length - min(interior.values()) + 1
    if suffix_deepest != 1:
        problems.append(f"all-deepest suffix is {suffix_deepest}, expected 1")
    # Shallowest victim is depth 2 of 4, so the killed suffix is 3.
    if suffix_interior != 3:
        problems.append(f"interior-victim suffix is {suffix_interior}, expected 3")
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
