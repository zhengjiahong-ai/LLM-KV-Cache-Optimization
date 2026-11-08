"""RC-A: how many A2 decisions had a real cost-aware choice?

The earlier version of this probe classified decisions with ``step_costs`` and
reported 28 ``S4`` / 38 ``S5``. Those numbers are withdrawn: ``step_costs`` holds the
marginal cost of the block greedy *picked*, one entry per pick
(``a2_selector.greedy_select``), not the cost distribution over the candidates of one
decision. A decision with hundreds of candidates whose costs differ can show a
single-entry ``step_costs``, and a decision with an uninteresting spread can show
several.

This version rebuilds the complete decision geometry from recorded evidence
(``rebuild_geometry``) and computes the same-step marginal cost of **every**
remaining candidate, so the classification measures what it claims to measure.

Classes (mutually exclusive, ordered by strength of the obstruction):

  F  not_scored            cost model never ran, or the rebuild finds a content gap
  N  no_freedom            need <= 0 or need >= |legal|: every legal block is evicted
  D  no_signal             every step's candidate marginals are identical
  L  signal_but_same_set    marginals differ, but the cost-optimal set is the rank set
  C  signal_changes_set     marginals differ and the cost-optimal set differs

Only ``C`` is a decision where cost-aware selection would actually have changed A2's
answer. ``L`` is a latent opportunity: the model had signal but it did not bind.

Why the answer is structural rather than incidental, and what would have to change for
a decision to become ``C``, is reported by the first-step diagnostic: a divergence can
only start at a step where the coldest remaining candidate is strictly more expensive
than a warmer one.
"""

from __future__ import annotations

import math
import sys
from collections import Counter

sys.path.insert(0, "src")

from rebuild_geometry import (
    Rebuild,
    iter_decisions,
    marginal_table,
    rebuild,
)

from kvopt.costaware.a2_selector import (
    chain_loss,
    exhaustive_select,
    greedy_select,
    marginal_cost,
)

#: Above this many combinations the exhaustive reference is reported as over budget
#: instead of being run. The engine's own budget is 20_000; this is deliberately
#: larger so "the engine truncated" and "the analysis could not enumerate" stay
#: separate findings.
ANALYSIS_CAP = 300_000


def exact_set(rb: Rebuild) -> tuple[tuple[int, ...] | None, int]:
    """Exact victim set, or ``None`` with the combination count when over the cap."""
    legal = len(rb.geometry.blocks)
    k = min(rb.need, legal)
    if k <= 0:
        return (), 1
    combinations = math.comb(legal, k)
    if combinations > ANALYSIS_CAP:
        return None, combinations
    found = exhaustive_select(rb.geometry, rb.need, budget=combinations)
    return (None if found is None else tuple(found[0])), combinations


def first_step_diagnostic(rb: Rebuild) -> str:
    """What the coldest candidate's cost allows at the first pick."""
    rows = marginal_table(rb.geometry, rb.need, marginal_cost)
    if not rows:
        return "no_pick"
    costs = rows[0]
    coldest = min(rb.geometry.blocks, key=lambda b: (rb.geometry.blocks[b].native_rank, b))
    coldest_cost = costs[coldest]
    cheapest = min(costs.values())
    if coldest_cost <= 1e-12:
        return "coldest_is_free"
    if cheapest >= coldest_cost - 1e-12:
        return "coldest_is_cheapest_priced"
    return "warmer_is_cheaper"


def loss_of(rb: Rebuild, blocks: tuple[int, ...]) -> float:
    """Proxy-weighted loss of one victim set under the rebuilt geometry."""
    evicted: dict = {}
    for block_id in blocks:
        block = rb.geometry.blocks.get(block_id)
        if block is not None:
            for member in block.memberships:
                evicted.setdefault(member.chain, set()).add(member.depth)
    return chain_loss(evicted, rb.geometry)


def unrealised_loss(rb: Rebuild, chosen: tuple[int, ...]) -> float:
    """Proxy-weighted loss of the rank-LRU set minus that of the chosen set."""
    return loss_of(rb, rb.native) - loss_of(rb, chosen)


def legacy_class(payload: dict) -> str:
    """The withdrawn ``step_costs`` rule, kept only to show what it used to claim."""
    if payload.get("selector") != "incremental_greedy":
        return "legacy_not_greedy"
    legal = payload.get("legal_block_ids") or []
    required = int(payload.get("required_blocks") or 0)
    steps = [c for c in (payload.get("step_costs") or []) if abs(c) > 1e-12]
    if len(legal) <= 1 or required >= len(legal):
        return "legacy_no_freedom"
    if len({round(c, 12) for c in steps}) <= 1:
        return "legacy_S4_equal_step_costs"
    return "legacy_S5_live_choice"


def main() -> int:
    total = 0
    classes: Counter[str] = Counter()
    diagnostic: Counter[str] = Counter()
    hashless = unverified = 0
    state_ok = rank_ok = 0
    engine_deviations: Counter[str] = Counter()
    legacy: Counter[str] = Counter()
    spread_histogram: Counter[int] = Counter()
    lost: list[float] = []
    certainties: Counter[str] = Counter()
    legal_sizes: list[int] = []

    for run, payload in iter_decisions():
        rb = rebuild(run, payload)
        total += 1
        hashless += rb.hashless_count
        unverified += rb.unverified_count
        state_ok += int(rb.state_ok)
        rank_ok += int(rb.rank_order_ok)
        legacy[legacy_class(payload)] += 1
        if set(rb.selected) != set(rb.native):
            engine_deviations["all"] += 1

        if rb.selector == "native_lru_fallback" or not rb.geometry.scorable:
            cls = "F_not_scored"
        elif rb.need <= 0 or rb.need >= rb.legal_count:
            cls = "N_no_freedom"
        else:
            legal_sizes.append(rb.legal_count)
            exact_blocks, _combinations = exact_set(rb)
            rank_loss = loss_of(rb, rb.native)
            if exact_blocks is not None:
                certainty = "exact_enumerated"
                chosen = exact_blocks
            elif abs(rank_loss) <= 1e-12:
                # loss is non-negative, so a zero-loss rank set is globally optimal and
                # no enumeration is needed to certify it.
                certainty = "certified_zero_loss"
                chosen = rb.native
            else:
                certainty = "undetermined_over_cap"
                greedy_blocks, _ = greedy_select(rb.geometry, rb.need)
                chosen = greedy_blocks
            certainties[certainty] += 1
            rows = marginal_table(rb.geometry, rb.need, marginal_cost)
            spreads = [max(row.values()) - min(row.values()) for row in rows]
            if not any(spread > 1e-12 for spread in spreads):
                cls = "D_no_signal"
            elif set(chosen) == set(rb.native):
                cls = "L_signal_but_same_set"
            else:
                cls = "C_signal_changes_set"
                lost.append(unrealised_loss(rb, chosen))
            diagnostic[first_step_diagnostic(rb)] += 1
            spread_histogram[max(len({round(c, 12) for c in row.values()}) for row in rows)] += 1
        classes[cls] += 1
        if set(rb.selected) != set(rb.native):
            engine_deviations[cls] += 1

    print(f"decisions with an A2 block audit: {total}")
    print()
    print("== rebuild fidelity ==")
    print(f"  identity-state counts reproduced exactly   {state_ok} / {total}")
    print(f"  native_lru_victims == legal prefix         {rank_ok} / {total}")
    print(f"  hashless legal candidates retained         {hashless}")
    print(f"  unverified legal candidates marked as gap  {unverified}")
    if legal_sizes:
        legal_sizes.sort()
        print(
            f"  legal candidates per comparable decision   median {legal_sizes[len(legal_sizes) // 2]}, "
            f"max {legal_sizes[-1]}"
        )
    print()
    print("== RC-A classification, same-step all-candidate marginals ==")
    for key in sorted(classes):
        print(f"  {key:24s} {classes[key]:4d}  {classes[key] / total:6.1%}")
    print()
    print("== first-step diagnostic (comparable decisions) ==")
    for key in sorted(diagnostic):
        print(f"  {key:26s} {diagnostic[key]:4d}")
    print()
    print("== how optimality of the rank set was established ==")
    for key in sorted(certainties):
        print(f"  {key:26s} {certainties[key]:4d}")
    print()
    print("== distinct marginal values involved in a comparable decision ==")
    for count, decisions in sorted(spread_histogram.items()):
        print(f"  {count:5d} distinct value(s)   {decisions:4d} decision(s)")
    print()
    print("== what the withdrawn rule used to report ==")
    for key in sorted(legacy):
        print(f"  {key:28s} {legacy[key]:4d}")
    print("  (step_costs holds one entry per greedy pick, not a candidate spread)")
    print()
    print("== engine behaviour ==")
    print(f"  decisions where recorded selection != rank-LRU {sum(engine_deviations.values())}")
    for key in sorted(engine_deviations):
        if key != "all":
            print(f"    {key:24s} {engine_deviations[key]}")
    print(
        f"  comparable decisions over the exact-search cap {certainties['undetermined_over_cap']}"
    )
    if lost:
        lost.sort()
        print()
        print("== unrealised proxy loss on C decisions ==")
        print(f"  decisions  {len(lost)}")
        print(f"  median     {lost[len(lost) // 2]:.6f}")
        print(f"  max        {lost[-1]:.6f}")
    print()
    print("== answers ==")
    print(f"  decisions where cost-aware changes A2's set: {classes['C_signal_changes_set']}")
    print(
        f"  of which the engine actually deviated:       "
        f"{engine_deviations['C_signal_changes_set']}"
    )
    print(f"  decisions with cost signal, same set:        {classes['L_signal_but_same_set']}")
    print(f"  decisions with no cost signal at all:        {classes['D_no_signal']}")
    print(f"  decisions where the model never ran:         {classes['F_not_scored']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
