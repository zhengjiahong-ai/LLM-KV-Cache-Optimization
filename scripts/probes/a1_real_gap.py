"""Offline measurement of the A1 structural gap on frozen H1 evidence.

Implements the three §6 statistics that need **no** content-identity proof:
rank, tier and owner membership are already persisted in FORCED_RELEASE_DECISION.

  1. unlock set != eviction set           -- A1 charges for blocks that are not evicted
  2. same N_i, different eviction set     -- A1 cannot separate the two
  3. optimal release cardinality < A1's   -- sequential greedy over-releases

The fourth statistic in the research note (rank vs content depth) does need identity
and is NOT computed here; it stays blocked on the content-hash exposure gap.

Read-only. No native run, no algorithm change.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

TIER_HASHLESS = 0
TIER_HASHED = 1

#: Below this many candidates, exhaustive search over release sets is cheap enough.
EXHAUSTIVE_LIMIT = 8


@dataclass(frozen=True)
class QueueBlock:
    block_id: int
    rank: int
    has_hash: bool
    tier: int
    owners: frozenset[str]


@dataclass(frozen=True)
class ObservedDecision:
    run_id: str
    index: int
    target: int
    blocks: tuple[QueueBlock, ...]
    entries: tuple[str, ...]
    observed_releases: tuple[str, ...]
    #: entry key -> its prefix block ids, shallowest first (decision-time coherent)
    prefixes: dict[str, tuple[int, ...]]
    #: entry key -> reuse proxy (uniform unless a deadline is supplied)
    q: dict[str, float]


def _load(path: Path, *, q_mode: str = "uniform", tau: float = 30.0) -> ObservedDecision | None:
    """Read one run's last FORCED_RELEASE_DECISION.

    ``q_mode`` selects the reuse proxy:

    - ``uniform``: every entry weighted 0.5. Isolates the **structural** question --
      does the choice of *which depths die* differ, independently of any prediction.
    - ``deadline``: ``sigmoid((retention_deadline_timestamp - t) / tau)``, the frozen
      A1 proxy. This is the ONLY legitimate extra signal available, so it is the only
      remaining lever for entry-level headroom.
    """
    decision = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event_type") != "FORCED_RELEASE_DECISION":
            continue
        payload = event["payload"]
        queue = tuple(
            (row["block_id"], row["native_lru_rank"], row["has_block_hash"])
            for row in payload["original_free_queue"]
        )        # owners: a block belongs to every candidate whose prefix contains it
        owners: dict[int, set[str]] = {block_id: set() for block_id, _, _ in queue}
        entries: list[str] = []
        prefixes: dict[str, tuple[int, ...]] = {}
        weights: dict[str, float] = {}
        timestamp = float(event.get("timestamp", 0.0))
        for candidate in payload["candidates"]:
            key = f"{candidate['program_id']}|{candidate['prefix_id']}"
            entries.append(key)
            prefix = tuple(candidate["block_ids"])
            prefixes[key] = prefix
            for block_id in prefix:
                if block_id in owners:
                    owners[block_id].add(key)
            if q_mode == "deadline":
                deadline = candidate.get("retention_deadline_timestamp")
                if deadline is None:
                    weights[key] = 0.5
                else:
                    x = (float(deadline) - timestamp) / tau
                    weights[key] = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))
            else:
                weights[key] = 0.5
        blocks = tuple(
            QueueBlock(
                block_id=block_id,
                rank=rank,
                has_hash=has_hash,
                tier=TIER_HASHLESS if not has_hash else TIER_HASHED,
                owners=frozenset(owners.get(block_id, ())),
            )
            for block_id, rank, has_hash in queue
        )
        target = min(int(payload["required_blocks"]), len(blocks))
        released: list[str] = []
        for release in payload.get("selected_releases", []):
            pid = release.get("program_id")
            prefix = release.get("prefix_id")
            if pid is None or prefix is None:
                continue
            released.append(f"{pid}|{prefix}")
        decision = ObservedDecision(
            run_id=event.get("run_id", path.parent.name),
            index=int(event.get("event_index", 0)),
            target=target,
            blocks=blocks,
            entries=tuple(entries),
            observed_releases=tuple(released),
            prefixes=prefixes,
            q=weights,
        )
    return decision


# --------------------------------------------------------------------------
# frozen-rule simulation (eligibility_tier, native_lru_rank)
# --------------------------------------------------------------------------


def eligible(decision: ObservedDecision, released: frozenset[str]) -> tuple[QueueBlock, ...]:
    rows = []
    for block in decision.blocks:
        if not block.has_hash:
            rows.append((TIER_HASHLESS, block.rank, block))
        elif block.owners <= released:
            rows.append((TIER_HASHED, block.rank, block))
    rows.sort(key=lambda row: (row[0], row[1]))
    return tuple(block for _, _, block in rows)


def relief(decision: ObservedDecision, released: frozenset[str]) -> int:
    return len(eligible(decision, released))


def evicted(decision: ObservedDecision, released: frozenset[str]) -> frozenset[int]:
    return frozenset(
        block.block_id for block in eligible(decision, released)[: decision.target]
    )


def new_blocks(
    decision: ObservedDecision, current: frozenset[str], add: str
) -> frozenset[int]:
    """Blocks that become eligible when ``add`` joins the released set."""
    before = {block.block_id for block in eligible(decision, current)}
    after = {block.block_id for block in eligible(decision, current | {add})}
    return frozenset(after - before)


def a1_minimal_set(decision: ObservedDecision, *, lambda_: float = 0.5) -> tuple[str, ...]:
    """A1: repeatedly take the entry with the smallest Rhat, until the target is met."""
    current: frozenset[str] = frozenset()
    order: list[str] = []
    while relief(decision, current) < decision.target:
        remaining = [e for e in decision.entries if e not in current]
        if not remaining:
            break
        need = max(0, decision.target - relief(decision, current))
        best = None
        for entry in remaining:
            n_i = len(new_blocks(decision, current, entry))
            forced = min(need, n_i)
            residual = max(0, n_i - forced)
            score = decision.q.get(entry, 0.5) * (forced + lambda_ * residual)
            key = (score, entry)
            if best is None or key < best:
                best = key
        assert best is not None
        current = current | {best[1]}
        order.append(best[1])
    return tuple(order)


def loss(decision: ObservedDecision, released: frozenset[str]) -> float:
    """APC loss of the eviction the frozen rule will perform.

    ``q`` is uniform inside one decision, so the value measures **which depths die**
    and nothing else. ``block_ids`` ordering within a candidate is the prefix order,
    which is decision-time coherent (both come from the same event). Cross-time slot
    reuse is not at issue here; cross-arm identity is, and this statistic does not
    compare arms.
    """
    dead = evicted(decision, released)
    total = 0.0
    for key, prefix in decision.prefixes.items():
        depths = [i + 1 for i, block_id in enumerate(prefix) if block_id in dead]
        if not depths:
            continue
        total += decision.q.get(key, 0.5) * (len(prefix) - min(depths) + 1)
    return total


def best_feasible_loss(decision: ObservedDecision, max_size: int = 3) -> float | None:
    """Lowest realised loss over release sets up to ``max_size`` that reach the target."""
    if len(decision.entries) > EXHAUSTIVE_LIMIT:
        return None
    best: float | None = None
    for size in range(min(max_size, len(decision.entries)) + 1):
        for combo in itertools.combinations(decision.entries, size):
            released = frozenset(combo)
            if relief(decision, released) < decision.target:
                continue
            value = loss(decision, released)
            if best is None or value < best - 1e-12:
                best = value
    return best


def minimal_cardinality(decision: ObservedDecision) -> int | None:
    """Smallest release-set size that still reaches the target."""
    if len(decision.entries) > EXHAUSTIVE_LIMIT:
        return None
    for size in range(len(decision.entries) + 1):
        for combo in itertools.combinations(decision.entries, size):
            if relief(decision, frozenset(combo)) >= decision.target:
                return size
    return None


# --------------------------------------------------------------------------
# the three statistics
# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    q_mode = "uniform"
    tau = 30.0
    roots: list[Path] = []
    for arg in argv[1:]:
        if arg.startswith("--q="):
            q_mode = arg.split("=", 1)[1]
        elif arg.startswith("--tau="):
            tau = float(arg.split("=", 1)[1])
        else:
            roots.append(Path(arg))
    if not roots:
        print("usage: a1_real_gap.py [--q=uniform|deadline] [--tau=30] <root> [...]")
        return 2
    print(f"reuse proxy: {q_mode}" + (f" (tau={tau})" if q_mode == "deadline" else ""))
    print()

    stats = Counter()
    decisions = 0
    unlock_excess: list[int] = []
    a1_sizes: list[int] = []
    minimal_sizes: list[int] = []
    over_release = 0
    same_relief_pairs = 0
    same_relief_diff_evict = 0
    same_relief_diff_loss = 0
    loss_gaps: list[float] = []
    loss_examples: list[tuple] = []
    examples = []
    #: mean A1 loss minus mean best singleton loss, uniform q
    a1_losses: list[float] = []
    best_singleton_gaps: list[float] = []
    optimal_gaps: list[float] = []

    for root in roots:
        for path in sorted(root.rglob("events.jsonl")):
            decision = _load(path, q_mode=q_mode, tau=tau)
            if decision is None or not decision.blocks:
                continue
            decisions += 1
            stats["with_freedom"] += int(decision.target < len(decision.blocks))

            base_released = frozenset(decision.observed_releases)
            if relief(decision, frozenset()) >= decision.target:
                stats["target_already_met_without_release"] += 1

            # --- 1. unlock set vs eviction set, measured on the observed release set
            before_evict = evicted(decision, frozenset())
            after_evict = evicted(decision, base_released)
            if before_evict == after_evict:
                stats["observed_release_did_not_change_eviction_set"] += 1
            if base_released:
                newly = frozenset(after_evict - before_evict)
                gone = frozenset(before_evict - after_evict)
                if gone:
                    stats["release_pushed_out_a_colder_block"] += 1
                if newly <= after_evict:
                    stats["newly_evicted_blocks_are_all_new"] += 1
                # A1 charges for every block the entry unlocks; count the ones that
                # never get evicted
                unlocked = {
                    b.block_id
                    for b in eligible(decision, base_released)
                } - {b.block_id for b in eligible(decision, frozenset())}
                not_evicted = unlocked - after_evict
                unlock_excess.append(len(not_evicted))

            # --- 2. same N_i, different eviction set
            #
            # Measured from the EMPTY release state, because that is the state A1 faces
            # when it scores its first pick. Measuring from the fully-released set would
            # make any extra entry irrelevant once the target is already met.
            singletons = []
            for entry in decision.entries:
                n_i = len(new_blocks(decision, frozenset(), entry))
                released_one = frozenset({entry})
                singletons.append(
                    (n_i, entry, evicted(decision, released_one), loss(decision, released_one))
                )
            for left, right in itertools.combinations(singletons, 2):
                if left[0] != right[0]:
                    continue
                same_relief_pairs += 1
                if left[2] != right[2]:
                    same_relief_diff_evict += 1
                if abs(left[3] - right[3]) > 1e-9:
                    same_relief_diff_loss += 1
                    loss_gaps.append(abs(left[3] - right[3]))
                    if len(loss_examples) < 3:
                        loss_examples.append(
                            (
                                decision.run_id,
                                decision.target,
                                left[0],
                                left[1][-34:],
                                right[1][-34:],
                                round(left[3], 3),
                                round(right[3], 3),
                            )
                        )
                    if len(examples) < 5:
                        examples.append(
                            (
                                decision.run_id,
                                decision.index,
                                decision.target,
                                left[1],
                                right[1],
                                left[0],
                                sorted(left[2]),
                                sorted(right[2]),
                            )
                        )

            # --- 3. cardinality: A1 vs minimal
            a1_set = a1_minimal_set(decision)
            a1_sizes.append(len(a1_set))
            a1_loss = loss(decision, frozenset(a1_set))
            a1_losses.append(a1_loss)
            # Only compare against FEASIBLE single-entry releases: a singleton that
            # does not reach the target is not an alternative to A1's answer.
            feasible = [
                loss(decision, frozenset({entry}))
                for entry in decision.entries
                if relief(decision, frozenset({entry})) >= decision.target
            ]
            if feasible:
                best_singleton_gaps.append(a1_loss - min(feasible))
            # Full optimum over small release sets, so the gap is not just a
            # one-step artefact.
            optimum = best_feasible_loss(decision)
            if optimum is not None:
                optimal_gaps.append(a1_loss - optimum)
            minimal = minimal_cardinality(decision)
            if minimal is not None:
                minimal_sizes.append(minimal)
                if len(a1_set) > minimal:
                    over_release += 1

    print(f"decisions analysed: {decisions}")
    for key in (
        "with_freedom",
        "target_already_met_without_release",
        "observed_release_did_not_change_eviction_set",
        "release_pushed_out_a_colder_block",
    ):
        print(f"  {key:48s} {stats[key]}")

    print()
    print("== 1. unlocked blocks that are never evicted ==")
    if unlock_excess:
        print(f"  decisions with a release:        {len(unlock_excess)}")
        print(f"  mean excess blocks per decision: {statistics.fmean(unlock_excess):.3f}")
        print(f"  decisions with excess > 0:       {sum(1 for x in unlock_excess if x)}")
        print(f"  max excess:                      {max(unlock_excess)}")

    print()
    print("== 2. equal relief, different eviction set ==")
    print(f"  singleton pairs with equal N_i:  {same_relief_pairs}")
    print(f"  ... that evict different blocks: {same_relief_diff_evict}")
    print(f"  ... that incur different LOSS:   {same_relief_diff_loss}   <- the one that matters")
    if same_relief_pairs:
        print(f"  block-set difference rate: {same_relief_diff_evict / same_relief_pairs:.4f}")
        print(f"  loss difference rate:      {same_relief_diff_loss / same_relief_pairs:.4f}")
    if loss_gaps:
        print(f"  mean |loss gap| when it differs: {statistics.fmean(loss_gaps):.3f} blocks")
        print(f"  max  |loss gap|:                 {max(loss_gaps):.3f} blocks")
    for run, target, n_i, left, right, l_left, l_right in loss_examples:
        print(
            f"    {run} target={target} N={n_i}: "
            f"{left} L={l_left}  vs  {right} L={l_right}"
        )

    print()
    print("== 2b. A1's chosen set vs feasible alternatives (uniform q) ==")
    if best_singleton_gaps:
        better = sum(1 for gap in best_singleton_gaps if gap > 1e-9)
        print(
            f"  decisions with a feasible single entry:  {len(best_singleton_gaps)}"
        )
        print(f"  ... where that single entry beats A1:    {better}")
        print(
            f"  mean A1 excess loss over best single:    "
            f"{statistics.fmean(best_singleton_gaps):.4f}"
        )
        print(f"  max A1 excess loss:                      {max(best_singleton_gaps):.4f}")
    if optimal_gaps:
        better_opt = sum(1 for gap in optimal_gaps if gap > 1e-9)
        print()
        print(f"  decisions with an exhaustive optimum:    {len(optimal_gaps)}")
        print(f"  ... where some set beats A1:             {better_opt}")
        print(f"  mean A1 excess loss over optimum:        {statistics.fmean(optimal_gaps):.4f}")
        print(f"  max A1 excess loss over optimum:         {max(optimal_gaps):.4f}")

    print()
    print("== 3. release-set cardinality ==")
    if a1_sizes:
        print(f"  mean A1 set size:                {statistics.fmean(a1_sizes):.3f}")
    if minimal_sizes:
        print(f"  mean minimal set size:           {statistics.fmean(minimal_sizes):.3f}")
        print(f"  A1 over-releases:                {over_release} / {len(minimal_sizes)}")
        if minimal_sizes:
            print(f"  rate: {over_release / len(minimal_sizes):.4f}")

    print()
    print("== not measured here ==")
    print("  rank vs content depth: needs content identity, blocked on the")
    print("  content-hash exposure gap (402/778 unverified in the A2 campaign).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
