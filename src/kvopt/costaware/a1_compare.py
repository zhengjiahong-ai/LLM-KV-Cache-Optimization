"""A0 vs A1 offline comparison over the existing replay layer.

What this reports, and what it deliberately does not
----------------------------------------------------
Three layers are kept strictly apart, because M1 asked for exactly that:

1. **release order** differs between A0 and A1;
2. the **released entry set** differs (order can differ without the set differing);
3. the **pressure target** is met or not, and how much becomes eligible.

None of these is a cache benefit. Aggregate recomputed tokens is a physical
outcome of which blocks the block layer evicts, and that step is not simulated
here: ``ReplayOutcome`` records a count rather than a block set, and the snapshot
carries no block depth. Every payload therefore marks itself
``is_physical_benefit: false``.

``at_risk_blocks`` is reported only for the controlled scenarios, where the ground
truth about which entries return is known by construction. It is an **exposure
proxy** -- eligible blocks belonging to returning entries -- not a recomputation
count, and it is evaluation-side only.

Usage
-----
    python -m kvopt.costaware.a1_compare --controlled
    python -m kvopt.costaware.a1_compare --corpus <artifact-root> [--formal]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from kvopt.profiling.datasets import DecisionCandidateRow

from .a1_entry import A1EntryCostAwareStrategy
from .a1_scenarios import ControlledScenario, all_scenarios
from .replay import (
    CandidateKey,
    DecisionSnapshot,
    ExecutedP1BStrategy,
    ReplayOutcome,
    ReplayState,
    candidate_key,
    load_decision_snapshots,
    replay_decision,
    validate_replay_fidelity,
)

FROZEN_STRATEGY_ID = "M0_executed_p1b_replay"


@dataclass(frozen=True, slots=True)
class ArmOutcome:
    """One arm on one decision."""

    strategy_id: str
    released: tuple[CandidateKey, ...]
    eligible_initial: int
    eligible_final: int
    target: int
    satisfied: bool
    exhausted: bool
    iterations: int


@dataclass(frozen=True, slots=True)
class DecisionComparison:
    """A0 versus A1 on a single decision."""

    run_id: str
    decision_event_index: int
    target: int
    a0: ArmOutcome
    a1: ArmOutcome
    order_differs: bool
    set_differs: bool
    cost_proxy_a1: float
    branch_trace: tuple[str, ...]
    pair_lookahead_proposals: tuple[dict[str, object], ...] = ()
    at_risk_blocks: int | None = None
    #: Selection evidence only; never a measured cache benefit.
    is_physical_benefit: bool = False


def _outcome(result: ReplayOutcome) -> ArmOutcome:
    return ArmOutcome(
        strategy_id=result.strategy_id,
        released=result.released,
        eligible_initial=result.eligible_blocks_initial,
        eligible_final=result.eligible_blocks_final,
        target=result.target,
        satisfied=result.satisfied,
        exhausted=result.exhausted,
        iterations=result.iterations,
    )


def _walk(
    snapshot: DecisionSnapshot,
    rows: dict[CandidateKey, DecisionCandidateRow],
    strategy,
) -> tuple[ReplayOutcome, tuple[str, ...], float, tuple[dict[str, object], ...]]:
    """Replay one decision, returning the outcome, branch trace and cost proxy.

    The trace and proxy come from walking the same ladder the strategy walked, so
    the reported diagnostics cannot drift from the actual choice.
    """
    result = replay_decision(snapshot, strategy, rows)

    if not hasattr(strategy, "select"):
        return result, (), 0.0, ()

    trace: list[str] = []
    pair_proposals: list[dict[str, object]] = []
    cost = 0.0
    state = ReplayState(snapshot)
    for _ in range(len(snapshot.candidate_keys) + 1):
        if len(state.eligible_block_ids()) >= snapshot.target:
            break
        remaining = [
            rows[key]
            for key in snapshot.candidate_keys
            if key not in state.released and key in rows
        ]
        if not remaining:
            break
        selection = strategy.select(remaining, state)
        trace.append(selection.branch)
        # Only actually selected releases enter cost_proxy_a1. A lookahead
        # score is a proposal, not a cost realised by the first zero-relief
        # member; report it separately and re-rank next iteration.
        if selection.proposed_partner is not None:
            pair_proposals.append({
                "released_first": selection.key,
                "proposed_partner": selection.proposed_partner,
                "joint_new_blocks": selection.joint_new_blocks,
                "joint_reuse_proxy": selection.joint_reuse_proxy,
                "joint_cost_proxy": selection.joint_cost_proxy,
            })
        for score in selection.scores:
            if score.key == selection.key:
                cost += score.expected_recompute
                break
        state.release(selection.key)

    return result, tuple(trace), cost, tuple(pair_proposals)


def compare_one(
    snapshot: DecisionSnapshot,
    rows: dict[CandidateKey, DecisionCandidateRow],
    *,
    strategy: A1EntryCostAwareStrategy | None = None,
    returns_after_decision: dict[CandidateKey, bool] | None = None,
) -> DecisionComparison:
    """Run A0 and A1 on the same snapshot and classify the difference."""
    strategy = strategy or A1EntryCostAwareStrategy()

    a0_result, _a0_trace, _a0_cost, _ = _walk(snapshot, rows, ExecutedP1BStrategy())
    a1_result, trace, cost, pair_proposals = _walk(snapshot, rows, strategy)

    at_risk: int | None = None
    if returns_after_decision:
        returning = {k for k, returns in returns_after_decision.items() if returns}
        exposed = 0
        state = ReplayState(snapshot)
        for key in a1_result.released:
            newly = state.newly_eligible_after(key)
            if key in returning:
                exposed += len(newly)
            state.release(key)
        at_risk = min(a1_result.target, exposed)

    return DecisionComparison(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        target=snapshot.target,
        a0=_outcome(a0_result),
        a1=_outcome(a1_result),
        order_differs=tuple(a0_result.released) != tuple(a1_result.released),
        set_differs=set(a0_result.released) != set(a1_result.released),
        cost_proxy_a1=cost,
        branch_trace=trace,
        pair_lookahead_proposals=pair_proposals,
        at_risk_blocks=at_risk,
    )


def compare_scenario(
    scenario: ControlledScenario,
    *,
    strategy: A1EntryCostAwareStrategy | None = None,
) -> DecisionComparison:
    return compare_one(
        scenario.snapshot,
        scenario.rows,
        strategy=strategy,
        returns_after_decision=scenario.returns_after_decision or None,
    )


def summarise(comparisons: Sequence[DecisionComparison]) -> dict[str, object]:
    """Aggregate selection-level agreement over a corpus."""
    total = len(comparisons)
    order_differs = sum(1 for c in comparisons if c.order_differs)
    set_differs = sum(1 for c in comparisons if c.set_differs)
    both_ok = sum(1 for c in comparisons if c.a0.satisfied and c.a1.satisfied)
    a0_ok = sum(1 for c in comparisons if c.a0.satisfied)
    a1_ok = sum(1 for c in comparisons if c.a1.satisfied)
    branches: dict[str, int] = {}
    for comparison in comparisons:
        for branch in comparison.branch_trace:
            branches[branch] = branches.get(branch, 0) + 1
    return {
        "decisions": total,
        "order_differs": order_differs,
        "set_differs": set_differs,
        "order_differs_without_set_change": order_differs - set_differs,
        "a0_meets_target": a0_ok,
        "a1_meets_target": a1_ok,
        "both_meet_target": both_ok,
        "a1_only_meets_target": a1_ok - both_ok,
        "a1_fails_where_a0_succeeds": a0_ok - both_ok,
        "branch_counts": branches,
        "is_physical_benefit": False,
    }


def _format_controlled(
    scenarios: Sequence[ControlledScenario],
    comparisons: Sequence[DecisionComparison],
) -> str:
    lines = [
        "# A0 vs A1 — controlled scenarios",
        "",
        "Selection-level comparison only. Physical block eviction is not simulated,",
        "so none of these numbers is aggregate recomputed tokens.",
        "",
    ]
    for scenario, comparison in zip(scenarios, comparisons, strict=True):
        lines.extend(
            [
                f"## {scenario.name}",
                "",
                f"- purpose: {scenario.purpose}",
                f"- expectation: {scenario.expectation}",
                f"- target: {comparison.target}",
                (
                    f"- A0 released {[k[0] for k in comparison.a0.released]}"
                    f" -> eligible {comparison.a0.eligible_final}"
                    f", satisfied={comparison.a0.satisfied}"
                    f", iterations={comparison.a0.iterations}"
                ),
                (
                    f"- A1 released {[k[0] for k in comparison.a1.released]}"
                    f" -> eligible {comparison.a1.eligible_final}"
                    f", satisfied={comparison.a1.satisfied}"
                    f", iterations={comparison.a1.iterations}"
                ),
                (
                    f"- order differs: {comparison.order_differs}"
                    f"; released set differs: {comparison.set_differs}"
                ),
                f"- A1 cost proxy: {comparison.cost_proxy_a1:.3f}",
                f"- A1 branch trace: {list(comparison.branch_trace)}",
            ]
        )
        if comparison.at_risk_blocks is not None:
            lines.append(
                f"- at-risk blocks of returning entries under A1:"
                f" {comparison.at_risk_blocks}"
            )
        if scenario.notes:
            lines.append(f"- notes: {scenario.notes}")
        lines.append("")
    return "\n".join(lines)


def run_corpus(
    artifact_root: Path,
    *,
    formal: bool = False,
    strategy: A1EntryCostAwareStrategy | None = None,
) -> tuple[dict[str, object], list[DecisionComparison]]:
    """Load a corpus the same way the existing offline evaluator does."""
    from kvopt.profiling.pipeline import (
        build_derived_dataset_bundle,
        discover_run_artifacts,
    )

    strategy = strategy or A1EntryCostAwareStrategy()
    raw_runs = discover_run_artifacts(artifact_root)
    bundle = build_derived_dataset_bundle(raw_runs, formal_campaign=formal)
    snapshots = load_decision_snapshots(raw_runs)

    rows_by_decision: dict[
        tuple[str, int], dict[CandidateKey, DecisionCandidateRow]
    ] = {}
    for row in bundle.decision_candidates:
        rows_by_decision.setdefault(
            (row.run_id, row.decision_event_index), {}
        )[candidate_key(row)] = row

    # A0 must reproduce the frozen behaviour before any A1 number means anything.
    fidelity = validate_replay_fidelity(
        snapshots, rows_by_decision, ExecutedP1BStrategy()
    )

    if fidelity.decisions_compared != len(snapshots) or any(
        rate != 1.0 for rate in (
            fidelity.release_set_match_rate,
            fidelity.release_sequence_match_rate,
            fidelity.initial_reclaimable_match_rate,
        )
    ):
        raise ValueError(
            "BASELINE_FIDELITY_FAILED: "
            f"snapshots={len(snapshots)}, compared={fidelity.decisions_compared}, "
            f"set={fidelity.release_set_match_rate}, "
            f"sequence={fidelity.release_sequence_match_rate}, "
            f"initial={fidelity.initial_reclaimable_match_rate}"
        )

    comparisons: list[DecisionComparison] = []
    for snapshot in snapshots:
        rows = rows_by_decision.get(
            (snapshot.run_id, snapshot.decision_event_index)
        )
        if not rows or any(key not in rows for key in snapshot.candidate_keys):
            raise ValueError(f"MISSING_DECISION_ROWS: {snapshot.run_id}@{snapshot.decision_event_index}")
        comparisons.append(compare_one(snapshot, rows, strategy=strategy))

    summary = summarise(comparisons)
    summary["a0_fidelity"] = {
        "release_set_match_rate": fidelity.release_set_match_rate,
        "release_sequence_match_rate": fidelity.release_sequence_match_rate,
        "initial_reclaimable_match_rate": fidelity.initial_reclaimable_match_rate,
    }
    return summary, comparisons


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare the frozen A0 release order with A1 entry cost-aware."
    )
    parser.add_argument(
        "--controlled",
        action="store_true",
        help="run the controlled scenarios (default when --corpus is absent)",
    )
    parser.add_argument(
        "--corpus", type=Path, help="artifact root containing run directories"
    )
    parser.add_argument(
        "--formal",
        action="store_true",
        help="validate the canonical campaign contract while loading the corpus",
    )
    parser.add_argument("--json", type=Path, help="write the full result as JSON")
    parser.add_argument("--lambda", dest="lambda_", type=float, default=0.5)
    parser.add_argument("--tau", type=float, default=30.0)
    args = parser.parse_args(argv)

    strategy = A1EntryCostAwareStrategy(lambda_=args.lambda_, tau_seconds=args.tau)
    payload: dict[str, object] = {
        "strategy": {
            "id": strategy.strategy_id,
            "lambda_": strategy.lambda_,
            "tau_seconds": strategy.tau_seconds,
        },
        "baseline": FROZEN_STRATEGY_ID,
        "is_physical_benefit": False,
    }

    if args.corpus:
        summary, comparisons = run_corpus(
            args.corpus, formal=args.formal, strategy=strategy
        )
        payload["corpus"] = summary
        payload["decisions"] = [asdict(comparison) for comparison in comparisons]
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        scenarios = all_scenarios()
        comparisons = [compare_scenario(s, strategy=strategy) for s in scenarios]
        print(_format_controlled(scenarios, comparisons))
        payload["controlled"] = [
            {
                "scenario": scenario.name,
                "purpose": scenario.purpose,
                "expectation": scenario.expectation,
                "notes": scenario.notes,
                "comparison": asdict(comparison),
            }
            for scenario, comparison in zip(scenarios, comparisons, strict=True)
        ]

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
