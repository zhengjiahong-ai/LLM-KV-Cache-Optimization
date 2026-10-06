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
    RuleEvaluation,
    ablation_table,
    behaviour_breakdown,
    cluster_paired_comparison,
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
    cluster_paired: dict[str, dict[str, float | int]] = {}
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
            try:
                cluster_paired[rule.rule_id] = cluster_paired_comparison(
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
        "schema_version": "phase2a.m4.offline_report.v2",
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
            "role": "the one to quote next to M6; also sensitivity for M4",
            "tie_definition": (
                "canonical M6 non-tied = the decision's hindsight-optimal release "
                "set is unique; the canonical_* aggregate fields above use exactly "
                "this definition and are restricted to decisions where the rule "
                "released the observed number of entries"
            ),
            "definition": (
                "size-matched lowest-loss hindsight from "
                "build_decision_regret_table; does not check pressure feasibility"
            ),
            # The M6-aligned numbers, surfaced where a reviewer looks for them so
            # the canonical non-tied / misselection rate has exactly one home and
            # is never quoted from the M4 diagnostic denominator.
            "baseline_canonical_summary": _canonical_summary_payload(
                evaluation, EXECUTED_BASELINE_RULE_ID
            ),
            "note": (
                "unchanged canonical M6 code; reported separately from the "
                "pressure-feasible oracle so the two denominators never compete; "
                "the M4 diagnostic denominator lives in "
                "evaluation.aggregates[*].loss_discriminating_decisions and must "
                "not be quoted as canonical non_tied"
            ),
        },
        "paired_vs_executed_baseline": paired,
        # Q10: the same paired test on the effective sample. Raw counts sum to
        # 60 decision rows; cluster counts sum to the cluster count. Both are
        # published because neither is a substitute for the other.
        "paired_vs_executed_baseline_cluster_level": cluster_paired,
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
                    "loss_discriminating_decisions": (
                        aggregate.loss_discriminating_decisions
                    ),
                    "positive_regret_decisions": (
                        aggregate.positive_regret_decisions
                    ),
                    "positive_regret_rate": aggregate.positive_regret_rate,
                    "mean_absolute_regret": aggregate.mean_absolute_regret,
                    "mean_normalized_regret": aggregate.mean_normalized_regret,
                }
                for rule_id, aggregate in mapping.items()
            }
            for family, mapping in holdout.items()
        },
        # Q10: the 60 decision rows are not 60 independent observations. Seeds
        # are near-replicas under the planned proxy, so clustering by
        # (scenario group, decision position) gives the effective sample size.
        "scenario_clusters": {
            "role": "effective-sample view; analysis-level, no campaign rerun",
            "grouping": "run_id minus the -seed-NNN suffix, by decision position",
            "effective_cluster_count": evaluation.effective_cluster_count,
            "raw_decision_count": evaluation.evaluated_decisions,
            "clusters_identical_across_seeds": (
                evaluation.clusters_identical_across_seeds
            ),
            # Q10 asks specifically for the unique decision-pattern count: two
            # clusters with the same candidate loss multiset pose the same
            # decision problem, so a deterministic rule cannot behave differently
            # on them and they are not separate evidence.
            "unique_decision_pattern_count": (
                evaluation.unique_decision_pattern_count
            ),
            "decision_patterns": [
                {"losses": list(pattern), "cluster_count": count}
                for pattern, count in evaluation.decision_pattern_counts
            ],
            "decisions": [
                {
                    "scenario_group": row.scenario_group,
                    "decision_event_index": row.decision_event_index,
                    "seed_count": row.seed_count,
                    "loss_profile_identical_across_seeds": (
                        row.loss_profile_identical_across_seeds
                    ),
                    "decision_pattern": list(row.decision_pattern),
                }
                for row in evaluation.clusters
            ],
        },
    }


def _canonical_summary_payload(
    evaluation: RuleEvaluation, rule_id: str
) -> dict[str, object] | None:
    """The canonical M6-aligned numbers for one rule, or ``None`` if absent.

    Q9 requires that the canonical non-tied / misselection rate has exactly one
    home. Surfacing it inside ``canonical_m6_comparator`` keeps a reviewer from
    quoting the M4 diagnostic denominator as if it were the canonical figure.
    """
    try:
        aggregate = evaluation.for_rule(rule_id)
    except KeyError:
        return None
    return {
        "rule_id": aggregate.rule_id,
        "canonical_applicable_decisions": (
            aggregate.canonical_applicable_decisions
        ),
        "canonical_non_tied_decisions": (
            aggregate.canonical_non_tied_decisions
        ),
        "canonical_positive_regret_decisions": (
            aggregate.canonical_positive_regret_decisions
        ),
        "canonical_misselection_rate": aggregate.canonical_misselection_rate,
        "mean_absolute_regret": aggregate.mean_absolute_regret,
        "mean_normalized_regret": aggregate.mean_normalized_regret,
    }


def _aggregate_payload(aggregate: RuleAggregate) -> dict[str, object]:
    """Serialize one rule aggregate.

    ``loss_discriminating_*`` is the M4 diagnostic denominator; it can differ
    from the decision at all. ``canonical_*`` reuses the canonical M6 tie
    definition (unique hindsight-best set) and is the one to quote next to M6.
    """
    return {
        "rule_id": aggregate.rule_id,
        "family": aggregate.family,
        "decisions": aggregate.decisions,
        "loss_discriminating_decisions": (
            aggregate.loss_discriminating_decisions
        ),
        "positive_regret_decisions": aggregate.positive_regret_decisions,
        "positive_regret_rate": aggregate.positive_regret_rate,
        "canonical_applicable_decisions": (
            aggregate.canonical_applicable_decisions
        ),
        "canonical_non_tied_decisions": (
            aggregate.canonical_non_tied_decisions
        ),
        "canonical_positive_regret_decisions": (
            aggregate.canonical_positive_regret_decisions
        ),
        "canonical_misselection_rate": aggregate.canonical_misselection_rate,
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
    """Serialize one feasibility-aware aggregate in the frozen Q11 order.

    Zero regret means no loss: selecting a different but equally optimal set is
    not a misselection. Normalised regret is last because it degenerates when
    ``oracle_loss`` is zero.
    """
    return {
        "rule_id": aggregate.rule_id,
        "decisions": aggregate.decisions,
        "mean_absolute_regret": aggregate.mean_absolute_regret,
        "median_absolute_regret": aggregate.median_absolute_regret,
        "mean_paired_loss_delta_vs_baseline": (
            aggregate.mean_paired_loss_delta_vs_baseline
        ),
        "better_than_baseline_decisions": (
            aggregate.better_than_baseline_decisions
        ),
        "worse_than_baseline_decisions": (
            aggregate.worse_than_baseline_decisions
        ),
        "tied_with_baseline_decisions": (
            aggregate.tied_with_baseline_decisions
        ),
        "zero_regret_rate": aggregate.zero_regret_rate,
        "positive_regret_decisions": aggregate.positive_regret_decisions,
        "mean_entry_count_delta": aggregate.mean_entry_count_delta,
        "mean_normalized_regret": aggregate.mean_normalized_regret,
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
        f"  {'rule':32s} {'dec':>4s} {'lossdisc':>8s} {'posreg':>6s} "
        f"{'C-app':>5s} {'C-nontied':>9s} {'C-misrate':>9s} "
        f"{'mean_abs':>10s}"
    )
    emit(header)
    emit("  " + "-" * (len(header) - 2))
    for aggregate in evaluation["aggregates"]:  # type: ignore[union-attr]
        emit(
            f"  {aggregate['rule_id']:32s} {aggregate['decisions']:4d} "
            f"{aggregate['loss_discriminating_decisions']:8d} "
            f"{aggregate['positive_regret_decisions']:6d} "
            f"{aggregate['canonical_applicable_decisions']:5d} "
            f"{aggregate['canonical_non_tied_decisions']:9d} "
            f"{_fmt(aggregate['canonical_misselection_rate'], 3):>9s} "
            f"{_fmt(aggregate['mean_absolute_regret']):>10s}"
        )
    emit("  lossdisc = M4 diagnostic denominator (choice can matter)")
    emit("  C-* = canonical M6 tie definition (unique hindsight-best set); use")
    emit("        C-nontied / C-misrate whenever the numbers sit next to M6")
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
        f"  {'rule':32s} {'dec':>4s} {'mean_abs':>10s} {'med_abs':>9s} "
        f"{'pairedΔ':>10s} {'B':>3s} {'W':>3s} {'T':>3s} {'zero':>6s} "
        f"{'entryΔ':>7s} {'mean_norm':>10s}"
    )
    emit(header)
    emit("  " + "-" * (len(header) - 2))
    for aggregate in oracle["aggregates"]:  # type: ignore[union-attr]
        emit(
            f"  {aggregate['rule_id']:32s} {aggregate['decisions']:4d} "
            f"{_fmt(aggregate['mean_absolute_regret']):>10s} "
            f"{_fmt(aggregate['median_absolute_regret']):>9s} "
            f"{_fmt(aggregate['mean_paired_loss_delta_vs_baseline']):>10s} "
            f"{aggregate['better_than_baseline_decisions']:3d} "
            f"{aggregate['worse_than_baseline_decisions']:3d} "
            f"{aggregate['tied_with_baseline_decisions']:3d} "
            f"{_fmt(aggregate['zero_regret_rate'], 3):>6s} "
            f"{_fmt(aggregate['mean_entry_count_delta'], 2):>7s} "
            f"{_fmt(aggregate['mean_normalized_regret']):>10s}"
        )
    emit("  frozen order (Q11): mean/median abs regret, paired delta, B/W/T,")
    emit("  zero-regret rate; mean_norm last because it degenerates at zero loss")
    emit("  pairedΔ > 0 = lower selected loss than P1B; zero = no regret, so a")
    emit("  different but equally optimal set is NOT a misselection")
    emit("  entryΔ = released entries minus the oracle's; positive = less efficient")
    emit()

    clusters = report.get("scenario_clusters")  # type: ignore[union-attr]
    if clusters:
        emit(line)
        emit("SCENARIO CLUSTERS  (effective sample, analysis-level only)")
        emit("  grouping: run_id minus -seed-NNN, by decision position")
        emit(line)
        emit(
            f"  raw decision rows            : "
            f"{clusters['raw_decision_count']}"
        )
        emit(
            f"  effective cluster decisions  : "
            f"{clusters['effective_cluster_count']}"
        )
        emit(
            f"  clusters with identical loss profile across seeds: "
            f"{clusters['clusters_identical_across_seeds']} / "
            f"{clusters['effective_cluster_count']}"
        )
        emit(
            f"  unique decision-pattern count: "
            f"{clusters['unique_decision_pattern_count']}"
        )
        emit("  a pattern is the candidate loss multiset; two clusters with the")
        emit("  same pattern pose the SAME problem, so a deterministic rule")
        emit("  cannot act differently on them and they are not separate evidence")
        for pattern in clusters["decision_patterns"]:  # type: ignore[union-attr]
            losses = ", ".join(f"{value:.6g}" for value in pattern["losses"])
            emit(f"    [{losses}] x {pattern['cluster_count']} clusters")
        emit("  seeds are near-replicas under the planned proxy, so raw row")
        emit("  counts overstate independent evidence; quote both views")
        emit()
    emit("  canonical M6 regret above is size-matched and does NOT check")
    emit("  pressure feasibility; it is retained for provenance only")
    canonical = report.get("canonical_m6_comparator")  # type: ignore[union-attr]
    if canonical:
        summary = canonical.get("baseline_canonical_summary")  # type: ignore[union-attr]
        if summary:
            emit()
            emit("  canonical M6 comparator, executed baseline (the numbers to")
            emit("  quote next to M6; NOT the M4 diagnostic denominator):")
            emit(
                f"    applicable={summary['canonical_applicable_decisions']}  "
                f"non_tied={summary['canonical_non_tied_decisions']}  "
                f"positive_regret="
                f"{summary['canonical_positive_regret_decisions']}  "
                f"misselection_rate="
                f"{_fmt(summary['canonical_misselection_rate'], 4)}"
            )
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

    cluster_paired = report.get(  # type: ignore[union-attr]
        "paired_vs_executed_baseline_cluster_level"
    )
    if cluster_paired:
        emit(line)
        emit("PAIRED COMPARISON, CLUSTER LEVEL (same test, seeds collapsed)")
        emit("  each (scenario group, decision position) counted once (Q10)")
        emit(line)
        header = (
            f"  {'challenger':38s} {'shared':>6s} {'better':>6s} "
            f"{'worse':>6s} {'tied':>5s} {'mean_delta_s':>13s}"
        )
        emit(header)
        emit("  " + "-" * (len(header) - 2))
        for rule_id, stats in cluster_paired.items():  # type: ignore[union-attr]
            emit(
                f"  {rule_id:38s} {stats['shared_clusters']:6d} "
                f"{stats['improved']:6d} {stats['worsened']:6d} "
                f"{stats['tied']:5d} "
                f"{_fmt(stats['mean_loss_delta_seconds']):>13s}"
            )
        emit("  quote this next to the raw view; the raw counts are inflated by")
        emit("  seed replicas and must not be read as the number of trials")
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
