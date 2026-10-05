"""Reproducible offline report for the M4 candidate-rule study.

This module is the in-repo reproducible path required by the M4 handoff: it
takes raw Phase 2A run directories, replays the frozen pressure loop, evaluates
every registered rule, and returns a single structured report. It contains no
runtime policy and reads no future-derived label as an input.

Two consumers use it:

- ``python -m kvopt.costaware.cli`` for the canonical reproducible run;
- the git-ignored ``local/`` probes for a fast personal feedback loop.

Both share this module so the numbers cannot drift between the two paths.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from kvopt.profiling.pipeline import (
    build_derived_dataset_bundle,
    discover_run_artifacts,
)

from .offline_eval import (
    CANONICAL_LOSS_VIEW,
    PressureFeasibleAggregate,
    ReleaseBurdenRow,
    RuleAggregate,
    ablation_table,
    behaviour_breakdown,
    denominator_diagnostic,
    evaluate_rules,
    leave_one_family_out,
    paired_comparison,
)
from .replay import (
    ExecutedP1BStrategy,
    candidate_key,
    load_decision_snapshots,
    validate_replay_fidelity,
)
from .rules import CANDIDATE_RULES, rule_by_id

#: The reference every comparison is measured against.
EXECUTED_BASELINE_RULE_ID = "M0_p1b_executed_ordering"


def build_offline_report(
    artifact_root: str | Path,
    *,
    formal: bool = False,
    loss_view: str = CANONICAL_LOSS_VIEW,
    rule_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    """Load raw runs, replay the pressure loop, and evaluate the rule set.

    Raises whatever the artifact pipeline raises on malformed input; the caller
    decides how to surface it. Nothing is written here.
    """
    root = Path(artifact_root)
    if not root.exists():
        raise FileNotFoundError(f"artifact root does not exist: {root}")

    raw_runs = discover_run_artifacts(root)

    bundle = build_derived_dataset_bundle(raw_runs, formal_campaign=formal)
    snapshots = load_decision_snapshots(raw_runs)
    families_by_run = {row.run_id: row.scenario_family_id for row in bundle.runs}

    rules = (
        tuple(rule_by_id(rule_id) for rule_id in rule_ids)
        if rule_ids
        else CANDIDATE_RULES
    )

    rows_by_decision: dict[tuple[str, int], dict[tuple[str, str], object]] = {}
    for row in bundle.decision_candidates:
        rows_by_decision.setdefault(
            (row.run_id, row.decision_event_index), {}
        )[candidate_key(row)] = row

    fidelity = validate_replay_fidelity(
        snapshots, rows_by_decision, ExecutedP1BStrategy()  # type: ignore[arg-type]
    )

    evaluation = evaluate_rules(
        candidates=bundle.decision_candidates,
        evidence=bundle.candidate_loss_evidence,
        snapshots=snapshots,
        canonical_regret=bundle.decision_regret,
        families_by_run=families_by_run,
        rules=rules,
        loss_view=loss_view,
    )

    paired: dict[str, dict[str, float | int]] = {}
    if any(rule.rule_id == EXECUTED_BASELINE_RULE_ID for rule in rules):
        for rule in rules:
            if rule.rule_id == EXECUTED_BASELINE_RULE_ID:
                continue
            try:
                paired[rule.rule_id] = paired_comparison(
                    evaluation,
                    baseline_rule_id=EXECUTED_BASELINE_RULE_ID,
                    challenger_rule_id=rule.rule_id,
                )
            except ValueError:
                continue

    holdout = leave_one_family_out(
        candidates=bundle.decision_candidates,
        evidence=bundle.candidate_loss_evidence,
        snapshots=snapshots,
        families_by_run=families_by_run,
        rules=rules,
        loss_view=loss_view,
    )

    return {
        "schema_version": "phase2a.m4.offline_report.v1",
        "artifact_root": str(root),
        "formal_campaign": formal,
        "loss_view": loss_view,
        "evidence_level": "offline proxy only; not a runtime or serving claim",
        "inputs": {
            "runs": len(raw_runs),
            "decisions": len(bundle.decisions),
            "candidates": len(bundle.decision_candidates),
            "snapshots": len(snapshots),
            "scenario_families": sorted(
                {value for value in families_by_run.values() if value}
            ),
            "seeds": sorted({row.seed for row in bundle.runs}),
        },
        "replay_fidelity": {
            "strategy_id": fidelity.strategy_id,
            "decisions_compared": fidelity.decisions_compared,
            "release_set_match_rate": fidelity.release_set_match_rate,
            "release_sequence_match_rate": fidelity.release_sequence_match_rate,
            "initial_reclaimable_match_rate": fidelity.initial_reclaimable_match_rate,
            "initial_reclaimable_fields_compared": (
                fidelity.initial_reclaimable_fields_compared
            ),
        },
        "evaluation": {
            "evaluated_decisions": evaluation.evaluated_decisions,
            "skipped_decisions": evaluation.skipped_decisions,
            "unsatisfied_decisions": evaluation.unsatisfied_decisions,
            "available_candidates": evaluation.available_candidates,
            "aggregates": [
                _aggregate_payload(aggregate)
                for aggregate in evaluation.aggregates
            ],
            "release_burden": [
                _burden_payload(row) for row in evaluation.release_burden
            ],
        },
        # Kept separate from the canonical M6 comparator on purpose: they answer
        # different questions and must never be merged into one field.
        "pressure_feasible_oracle": {
            "role": "M4 method-selection metric",
            "definition": (
                "among release sets satisfying the same required_blocks target: "
                "minimise total canonical proxy loss, then released entry count, "
                "then stable identity order"
            ),
            "search": "exact subset enumeration",
            "decisions": [
                {
                    "run_id": row.run_id,
                    "decision_event_index": row.decision_event_index,
                    "target": row.target,
                    "candidate_count": row.candidate_count,
                    "feasible_set_count": row.feasible_set_count,
                    "oracle_released": [list(key) for key in row.oracle_released],
                    "oracle_loss": row.oracle_loss,
                    "oracle_entry_count": row.oracle_entry_count,
                    "worst_feasible_loss": row.worst_feasible_loss,
                    "loss_choices_matter": row.loss_choices_matter,
                    "unreachable": row.unreachable,
                }
                for row in evaluation.oracle_rows
            ],
            "aggregates": [
                _feasible_aggregate_payload(aggregate)
                for aggregate in evaluation.pressure_feasible_aggregates
            ],
        },
        "canonical_m6_comparator": {
            "role": "provenance and sensitivity only",
            "definition": (
                "size-matched lowest-loss hindsight from "
                "build_decision_regret_table; does not check pressure feasibility"
            ),
            "note": (
                "unchanged canonical M6 code; reported separately from the "
                "pressure-feasible oracle"
            ),
        },
        "paired_vs_executed_baseline": paired,
        "degeneracy": [
            {
                "rule_a": row.rule_a,
                "rule_b": row.rule_b,
                "shared_decisions": row.shared_decisions,
                "identical_selection_count": row.identical_selection_count,
                "identical_selection_rate": row.identical_selection_rate,
            }
            for row in evaluation.degeneracy
        ],
        "ablation": [asdict(row) for row in ablation_table(evaluation)],
        "behaviour_breakdown": [
            asdict(row) for row in behaviour_breakdown(evaluation)
        ],
        "denominator_diagnostic": [
            asdict(row)
            for row in denominator_diagnostic(bundle.decision_candidates)
        ],
        "leave_one_family_out": {
            family: {
                rule_id: {
                    "decisions": aggregate.decisions,
                    "non_tied_decisions": aggregate.non_tied_decisions,
                    "misselection_rate": aggregate.misselection_rate,
                    "mean_absolute_regret": aggregate.mean_absolute_regret,
                    "mean_normalized_regret": aggregate.mean_normalized_regret,
                }
                for rule_id, aggregate in mapping.items()
            }
            for family, mapping in holdout.items()
        },
    }


def _aggregate_payload(aggregate: RuleAggregate) -> dict[str, object]:
    return {
        "rule_id": aggregate.rule_id,
        "family": aggregate.family,
        "decisions": aggregate.decisions,
        "non_tied_decisions": aggregate.non_tied_decisions,
        "strictly_worse_decisions": aggregate.strictly_worse_decisions,
        "misselection_rate": aggregate.misselection_rate,
        "mean_absolute_regret": aggregate.mean_absolute_regret,
        "mean_normalized_regret": aggregate.mean_normalized_regret,
        "tie_rate": aggregate.tie_rate,
    }


def _burden_payload(row: ReleaseBurdenRow) -> dict[str, object]:
    return {
        "rule_id": row.rule_id,
        "decisions": row.decisions,
        "mean_target": row.mean_target,
        "mean_releases": row.mean_releases,
        "mean_releases_vs_baseline": row.mean_releases_vs_baseline,
        "saturated_decisions": row.saturated_decisions,
        "frugal_decisions": row.frugal_decisions,
        "unsatisfied_decisions": row.unsatisfied_decisions,
    }


def _feasible_aggregate_payload(
    aggregate: PressureFeasibleAggregate,
) -> dict[str, object]:
    return {
        "rule_id": aggregate.rule_id,
        "decisions": aggregate.decisions,
        "loss_choices_matter_decisions": (
            aggregate.loss_choices_matter_decisions
        ),
        "misselection_rate": aggregate.misselection_rate,
        "mean_absolute_regret": aggregate.mean_absolute_regret,
        "mean_normalized_regret": aggregate.mean_normalized_regret,
        "oracle_best_rate": aggregate.oracle_best_rate,
        "mean_entry_count_delta": aggregate.mean_entry_count_delta,
    }


def _fmt(value: object, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if math.isnan(value):
            return "n/a"
        return f"{value:.{digits}f}"
    return str(value)


def render_text(report: dict[str, object]) -> str:
    """Render the report as a human-readable text block."""
    out: list[str] = []
    line = "=" * 78

    def emit(text: str = "") -> None:
        out.append(text)

    inputs = report["inputs"]  # type: ignore[index]
    fidelity = report["replay_fidelity"]  # type: ignore[index]
    evaluation = report["evaluation"]  # type: ignore[index]

    emit(line)
    emit("M4 OFFLINE CANDIDATE-RULE REPORT")
    emit(line)
    emit(f"artifact root    : {report['artifact_root']}")
    emit(f"formal campaign  : {report['formal_campaign']}")
    emit(f"loss view        : {report['loss_view']}")
    emit(
        f"runs={inputs['runs']}  decisions={inputs['decisions']}  "
        f"candidates={inputs['candidates']}"
    )
    emit(
        f"families={inputs['scenario_families']}  seeds={inputs['seeds']}"
    )
    emit()

    emit(line)
    emit("REPLAY FIDELITY (must be 1.0 before any regret number is trusted)")
    emit(line)
    emit(f"  decisions compared        : {fidelity['decisions_compared']}")
    emit(f"  release SET match rate    : {_fmt(fidelity['release_set_match_rate'], 4)}")
    emit(
        f"  release ORDER match rate  : "
        f"{_fmt(fidelity['release_sequence_match_rate'], 4)}"
    )
    emit(
        f"  marginal blocks match rate: "
        f"{_fmt(fidelity['initial_reclaimable_match_rate'], 4)} "
        f"({fidelity['initial_reclaimable_fields_compared']} fields)"
    )
    emit()

    emit(line)
    emit("EVALUATION")
    emit(line)
    emit(
        f"  evaluated decisions : {evaluation['evaluated_decisions']}\n"
        f"  skipped decisions   : {evaluation['skipped_decisions']}\n"
        f"  unsatisfied         : {evaluation['unsatisfied_decisions']}\n"
        f"  candidates scored   : {evaluation['available_candidates']}"
    )
    emit()
    header = (
        f"  {'rule':38s} {'dec':>4s} {'nontied':>8s} {'misrate':>8s} "
        f"{'mean_abs':>10s} {'mean_norm':>10s}"
    )
    emit(header)
    emit("  " + "-" * (len(header) - 2))
    for aggregate in evaluation["aggregates"]:  # type: ignore[union-attr]
        emit(
            f"  {aggregate['rule_id']:38s} {aggregate['decisions']:4d} "
            f"{aggregate['non_tied_decisions']:8d} "
            f"{_fmt(aggregate['misselection_rate'], 3):>8s} "
            f"{_fmt(aggregate['mean_absolute_regret']):>10s} "
            f"{_fmt(aggregate['mean_normalized_regret']):>10s}"
        )
    emit()

    emit(line)
    emit("RELEASE BURDEN (releases needed for the shared required_blocks target)")
    emit(line)
    header = (
        f"  {'rule':38s} {'mean_rel':>9s} {'vs_p1b':>8s} "
        f"{'frugal':>7s} {'satur':>6s} {'unsat':>6s}"
    )
    emit(header)
    emit("  " + "-" * (len(header) - 2))
    for burden in evaluation["release_burden"]:  # type: ignore[union-attr]
        emit(
            f"  {burden['rule_id']:38s} "
            f"{_fmt(burden['mean_releases'], 3):>9s} "
            f"{_fmt(burden['mean_releases_vs_baseline'], 3):>8s} "
            f"{burden['frugal_decisions']:7d} {burden['saturated_decisions']:6d} "
            f"{burden['unsatisfied_decisions']:6d}"
        )
    emit("  frugal = fewer releases than the observed baseline; satur = more")
    emit()

    oracle = report["pressure_feasible_oracle"]  # type: ignore[index]
    emit(line)
    emit("PRESSURE-FEASIBLE ORACLE  (M4 method-selection metric)")
    emit("  exact search over subsets that satisfy the same required_blocks")
    emit("  order: least total proxy loss, then fewest entries, then identity")
    emit(line)
    emit(
        f"  decisions with an oracle : {len(oracle['decisions'])}"  # type: ignore[arg-type]
    )
    header = (
        f"  {'run / event':46s} {'target':>6s} {'n':>3s} {'feas':>5s} "
        f"{'oracle':>9s} {'worst':>9s} {'matters':>8s}"
    )
    emit(header)
    emit("  " + "-" * (len(header) - 2))
    for row in oracle["decisions"]:  # type: ignore[union-attr]
        label = f"{row['run_id']} ev{row['decision_event_index']}"
        emit(
            f"  {label:46s} {row['target']:6d} {row['candidate_count']:3d} "
            f"{row['feasible_set_count']:5d} "
            f"{_fmt(row['oracle_loss']):>9s} "
            f"{_fmt(row['worst_feasible_loss']):>9s} "
            f"{row['loss_choices_matter']!s:>8s}"
        )
    emit()
    header = (
        f"  {'rule':38s} {'dec':>4s} {'matters':>8s} {'misrate':>8s} "
        f"{'mean_abs':>10s} {'mean_norm':>10s} {'entryΔ':>7s}"
    )
    emit(header)
    emit("  " + "-" * (len(header) - 2))
    for aggregate in oracle["aggregates"]:  # type: ignore[union-attr]
        emit(
            f"  {aggregate['rule_id']:38s} {aggregate['decisions']:4d} "
            f"{aggregate['loss_choices_matter_decisions']:8d} "
            f"{_fmt(aggregate['misselection_rate'], 3):>8s} "
            f"{_fmt(aggregate['mean_absolute_regret']):>10s} "
            f"{_fmt(aggregate['mean_normalized_regret']):>10s} "
            f"{_fmt(aggregate['mean_entry_count_delta'], 2):>7s}"
        )
    emit("  entryΔ = released entries minus the oracle's; positive = less efficient")
    emit()
    emit("  canonical M6 regret above is size-matched and does NOT check")
    emit("  pressure feasibility; it is retained for provenance only")
    emit()

    paired = report["paired_vs_executed_baseline"]
    if paired:
        emit(line)
        emit("PAIRED COMPARISON vs the executed P1B baseline")
        emit(line)
        header = (
            f"  {'challenger':38s} {'shared':>6s} {'better':>6s} "
            f"{'worse':>6s} {'tied':>5s} {'mean_delta_s':>13s}"
        )
        emit(header)
        emit("  " + "-" * (len(header) - 2))
        for rule_id, stats in paired.items():  # type: ignore[union-attr]
            emit(
                f"  {rule_id:38s} {stats['shared_decisions']:6d} "
                f"{stats['improved']:6d} {stats['worsened']:6d} "
                f"{stats['tied']:5d} "
                f"{_fmt(stats['mean_loss_delta_seconds']):>13s}"
            )
        emit("  positive mean delta = the challenger releases a cheaper total set")
        emit()

    emit(line)
    emit("DEGENERACY: rule pairs that never disagree")
    emit(line)
    identical = [
        row
        for row in report["degeneracy"]  # type: ignore[union-attr]
        if row["identical_selection_rate"] == 1.0
    ]
    if identical:
        for row in identical:
            emit(
                f"  {row['rule_a']:36s} == {row['rule_b']:36s} "
                f"over {row['shared_decisions']:3d}"
            )
    else:
        emit("  (no fully rank-identical rule pair)")
    emit()

    emit(line)
    emit("ABLATION (identity 1.000 means the toggle never changes a decision)")
    emit(line)
    for row in report["ablation"]:  # type: ignore[union-attr]
        emit(
            f"  {row['variant']:46s} ident={_fmt(row['identical_selection_rate'], 3)} "
            f"mean_norm={_fmt(row['mean_normalized_regret'])} "
            f"base={_fmt(row['baseline_mean_normalized_regret'])}"
        )
    emit()

    emit(line)
    emit("DENOMINATOR DIAGNOSTIC (handoff section 10c)")
    emit(line)
    diagnostic = report["denominator_diagnostic"]  # type: ignore[index]
    constant = sum(1 for row in diagnostic if row["denominator_is_constant"])
    invertible = [row for row in diagnostic if row["comparable_pairs"]]
    inversions = sum(row["rank_inversions"] for row in invertible)
    pairs = sum(row["comparable_pairs"] for row in invertible)
    emit(f"  decisions with a CONSTANT denominator : {constant}/{len(diagnostic)}")
    emit(f"  cost-vs-ratio rank inversions          : {inversions}/{pairs}")
    emit()

    emit(line)
    emit("LEAVE-ONE-FAMILY-OUT (mean normalized regret per held-out family)")
    emit(line)
    holdout = report["leave_one_family_out"]  # type: ignore[index]
    families = sorted(holdout)
    if families:
        first_rule = next(iter(holdout[families[0]]))
        emit(f"  {'rule':38s} " + " ".join(f"{family:>12s}" for family in families))
        for rule_id in holdout[families[0]]:
            cells = [
                _fmt(holdout[family].get(rule_id, {}).get("mean_normalized_regret"))
                for family in families
            ]
            emit(f"  {rule_id:38s} " + " ".join(f"{cell:>12s}" for cell in cells))
        del first_rule
    emit()
    emit(f"evidence level: {report['evidence_level']}")
    emit(line)
    return "\n".join(out)
