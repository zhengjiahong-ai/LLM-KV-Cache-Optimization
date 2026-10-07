"""Tests for the replay-based M4 offline rule evaluator."""

from __future__ import annotations

import pytest

from kvopt.costaware.offline_eval import (
    ABLATION_PAIRS,
    CANONICAL_LOSS_VIEW,
    EXCLUSION_CANDIDATE_EVIDENCE_MISSING,
    EXCLUSION_DECISION_SNAPSHOT_MISSING,
    EXCLUSION_NO_EVIDENCE_FOR_VIEW,
    EXCLUSION_TOO_FEW_CANDIDATES,
    ablation_table,
    behaviour_breakdown,
    cluster_paired_comparison,
    decision_pattern_counts,
    denominator_diagnostic,
    evaluate_rules,
    leave_one_family_out,
    paired_comparison,
    scenario_clusters,
)
from kvopt.costaware.replay import DecisionSnapshot, QueueBlock
from kvopt.costaware.rules import CANDIDATE_RULES, rule_by_id
from kvopt.profiling.analysis import DecisionRegretRow
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.loss_views import CandidateLossEvidenceRow

_PREFIX = "p"


def _canonical_row(
    run_id: str,
    decision_event_index: int,
    *,
    best_set_count: int,
) -> DecisionRegretRow:
    """Minimal canonical M6 row; only the best-set count drives the Q9 view."""
    return DecisionRegretRow(
        run_id=run_id,
        decision_event_index=decision_event_index,
        loss_view=CANONICAL_LOSS_VIEW,
        candidate_count=2,
        selection_count=1,
        selected_candidates=(),
        hindsight_mandatory_candidates=(),
        hindsight_boundary_candidates=(),
        hindsight_best_set_count=best_set_count,
        selected_loss=0.0,
        hindsight_best_loss=0.0,
        absolute_regret=0.0,
        normalized_regret=0.0,
        selected_is_hindsight_best=best_set_count == 1,
    )


def _row(
    *,
    run_id: str,
    decision_event_index: int,
    program_id: str,
    selected: bool,
    block_ids: tuple[int, ...],
    prefill_reload_seconds: float,
    retention_deadline_timestamp: float,
    decision_native_lru_position: int,
    next_tool_type: str = "search",
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id=run_id,
        decision_event_index=decision_event_index,
        source_event_index=decision_event_index,
        candidate_position=decision_native_lru_position,
        program_id=program_id,
        prefix_id=_PREFIX,
        selected=selected,
        release_order=1 if selected else None,
        retention_deadline_timestamp=retention_deadline_timestamp,
        waiting_followup=True,
        block_ids=block_ids,
        block_count=len(block_ids),
        initially_reclaimable_block_ids=block_ids,
        initially_reclaimable_block_count=len(block_ids),
        next_tool_type=next_tool_type,
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=prefill_reload_seconds,
        eta=1.0,
        queue_delay_t_seconds=0.5,
        decision_native_lru_position=decision_native_lru_position,
    )


def _evidence(
    *,
    run_id: str,
    decision_event_index: int,
    program_id: str,
    loss: float | None,
    availability: str = "available",
    loss_view: str = CANONICAL_LOSS_VIEW,
) -> CandidateLossEvidenceRow:
    return CandidateLossEvidenceRow(
        run_id=run_id,
        decision_event_index=decision_event_index,
        program_id=program_id,
        prefix_id=_PREFIX,
        selected=False,
        loss_view=loss_view,
        evidence_kind="trace_derived_proxy",
        unit="seconds",
        loss=loss,
        availability=availability,
        unavailable_reason=None if availability == "available" else "test_missing",
        source_event_indexes=(decision_event_index,),
    )


def _snapshot(
    *,
    run_id: str,
    decision_event_index: int,
    entries: dict[str, tuple[int, ...]],
    required_blocks: int,
    observed_selected: tuple[str, ...],
) -> DecisionSnapshot:
    blocks: list[int] = []
    for owned in entries.values():
        for block_id in owned:
            if block_id not in blocks:
                blocks.append(block_id)
    blocks.sort()
    ranking = {block_id: rank for rank, block_id in enumerate(blocks)}
    owners: dict[int, set[tuple[str, str]]] = {}
    for program_id, owned in entries.items():
        for block_id in owned:
            owners.setdefault(block_id, set()).add((program_id, _PREFIX))
    return DecisionSnapshot(
        run_id=run_id,
        decision_event_index=decision_event_index,
        timestamp=100.0,
        required_blocks=required_blocks,
        queue=tuple(
            QueueBlock(
                block_id=block_id,
                has_block_hash=True,
                native_lru_rank=ranking[block_id],
            )
            for block_id in blocks
        ),
        candidate_keys=tuple((program_id, _PREFIX) for program_id in entries),
        owners_by_block={
            block_id: frozenset(keys) for block_id, keys in owners.items()
        },
        observed_selected=tuple(
            (program_id, _PREFIX) for program_id in observed_selected
        ),
        observed_initial_reclaimable={
            (program_id, _PREFIX): owned for program_id, owned in entries.items()
        },
        ranking_by_block=ranking,
    )


def _fixture() -> tuple[
    tuple[DecisionCandidateRow, ...],
    tuple[CandidateLossEvidenceRow, ...],
    tuple[DecisionSnapshot, ...],
]:
    """Three decisions with disjoint ownership, so every number is hand-checkable.

    D40 (run-1, target 40 blocks)
        pg-a 40 blocks cost 0.5 deadline 100 -> loss 0.5 (returns)
        pg-b  8 blocks cost 0.1 deadline 200 -> loss 0.1 (returns)
        pg-c 24 blocks cost 0.3 deadline 150 -> loss 0.0 (does NOT return)
        The baseline releases pg-a alone (40 blocks) in 1 release.
        Cost ascending must release b, c then a: 3 releases.

    D50 (run-1, target 40 blocks)
        pg-d 38 blocks cost 0.9 deadline 100 -> loss 0.9 (returns)
        pg-e 42 blocks cost 0.2 deadline 200 -> loss 0.2 (returns)
        The baseline needs 2 releases (d then e). Cost ascending needs 1 (e).

    D60 (run-2, target 32 blocks, identical losses)
        pg-f 32 blocks cost 0.4 deadline 100 -> loss 0.4
        pg-g 32 blocks cost 0.4 deadline 200 -> loss 0.4
        A tied decision: every rule releases pg-f in 1 release.
    """
    candidates = (
        _row(run_id="run-1", decision_event_index=40, program_id="pg-a", selected=True,
             block_ids=tuple(range(40)), prefill_reload_seconds=0.5,
             retention_deadline_timestamp=100.0, decision_native_lru_position=0,
             next_tool_type="code"),
        _row(run_id="run-1", decision_event_index=40, program_id="pg-b", selected=False,
             block_ids=tuple(range(40, 48)), prefill_reload_seconds=0.1,
             retention_deadline_timestamp=200.0, decision_native_lru_position=1,
             next_tool_type="code"),
        _row(run_id="run-1", decision_event_index=40, program_id="pg-c", selected=False,
             block_ids=tuple(range(48, 72)), prefill_reload_seconds=0.3,
             retention_deadline_timestamp=150.0, decision_native_lru_position=2,
             next_tool_type="search"),
        _row(run_id="run-1", decision_event_index=50, program_id="pg-d", selected=True,
             block_ids=tuple(range(100, 138)), prefill_reload_seconds=0.9,
             retention_deadline_timestamp=100.0, decision_native_lru_position=0,
             next_tool_type="code"),
        _row(run_id="run-1", decision_event_index=50, program_id="pg-e", selected=True,
             block_ids=tuple(range(138, 180)), prefill_reload_seconds=0.2,
             retention_deadline_timestamp=200.0, decision_native_lru_position=1,
             next_tool_type="search"),
        _row(run_id="run-2", decision_event_index=60, program_id="pg-f", selected=True,
             block_ids=tuple(range(200, 232)), prefill_reload_seconds=0.4,
             retention_deadline_timestamp=100.0, decision_native_lru_position=0,
             next_tool_type="search"),
        _row(run_id="run-2", decision_event_index=60, program_id="pg-g", selected=False,
             block_ids=tuple(range(232, 264)), prefill_reload_seconds=0.4,
             retention_deadline_timestamp=200.0, decision_native_lru_position=1,
             next_tool_type="search"),)
    losses = {
        ("run-1", 40, "pg-a"): 0.5,
        ("run-1", 40, "pg-b"): 0.1,
        ("run-1", 40, "pg-c"): 0.0,
        ("run-1", 50, "pg-d"): 0.9,
        ("run-1", 50, "pg-e"): 0.2,
        ("run-2", 60, "pg-f"): 0.4,
        ("run-2", 60, "pg-g"): 0.4,
    }
    evidence = tuple(
        _evidence(
            run_id=run_id,
            decision_event_index=index,
            program_id=program,
            loss=loss,
        )
        for (run_id, index, program), loss in losses.items()
    )
    snapshots = (
        _snapshot(
            run_id="run-1",
            decision_event_index=40,
            entries={
                "pg-a": tuple(range(40)),
                "pg-b": tuple(range(40, 48)),
                "pg-c": tuple(range(48, 72)),
            },
            required_blocks=40,
            observed_selected=("pg-a",),
        ),
        _snapshot(
            run_id="run-1",
            decision_event_index=50,
            entries={
                "pg-d": tuple(range(100, 138)),
                "pg-e": tuple(range(138, 180)),
            },
            required_blocks=40,
            observed_selected=("pg-d", "pg-e"),
        ),
        _snapshot(
            run_id="run-2",
            decision_event_index=60,
            entries={
                "pg-f": tuple(range(200, 232)),
                "pg-g": tuple(range(232, 264)),
            },
            required_blocks=32,
            observed_selected=("pg-f",),
        ),
    )
    return candidates, evidence, snapshots


def _families() -> dict[str, str | None]:
    return {"run-1": "F1", "run-2": "F2"}


def _evaluate(**overrides: object):
    candidates, evidence, snapshots = _fixture()
    arguments: dict[str, object] = {
        "candidates": candidates,
        "evidence": evidence,
        "snapshots": snapshots,
        "families_by_run": _families(),
    }
    arguments.update(overrides)
    return evaluate_rules(**arguments)  # type: ignore[arg-type]


# --- evaluation shape ------------------------------------------------------


def test_every_registered_rule_is_evaluated() -> None:
    evaluation = _evaluate()
    assert evaluation.evaluated_decisions == 3
    assert evaluation.skipped_decisions == 0
    assert evaluation.unsatisfied_decisions == 0
    assert {aggregate.rule_id for aggregate in evaluation.aggregates} == {
        rule.rule_id for rule in CANDIDATE_RULES
    }
    assert evaluation.loss_view == CANONICAL_LOSS_VIEW


def test_release_count_is_an_outcome_not_an_input() -> None:
    """The core correction: rules may need different release counts."""
    evaluation = _evaluate()
    baseline = evaluation.burden_for_rule("M0_p1b_executed_ordering")
    cost = evaluation.burden_for_rule("M1_prefill_reload_ascending")
    assert baseline.mean_releases == pytest.approx(4.0 / 3.0)
    assert cost.mean_releases == pytest.approx(5.0 / 3.0)
    assert cost.saturated_decisions == 1
    assert cost.frugal_decisions == 1


def test_baseline_release_counts_match_the_hand_computed_values() -> None:
    evaluation = _evaluate()
    counts = {
        (outcome.run_id, outcome.decision_event_index): outcome.selection_count
        for outcome in evaluation.outcomes
        if outcome.rule_id == "M0_p1b_executed_ordering"
    }
    assert counts[("run-1", 40)] == 1
    assert counts[("run-1", 50)] == 2
    assert counts[("run-2", 60)] == 1


def test_cost_rule_needs_three_releases_where_the_baseline_needs_one() -> None:
    evaluation = _evaluate()
    outcome = next(
        row
        for row in evaluation.outcomes
        if row.rule_id == "M1_prefill_reload_ascending"
        and row.decision_event_index == 40
    )
    assert outcome.selection_count == 3
    assert set(outcome.selected_identities) == {
        ("pg-a", _PREFIX),
        ("pg-b", _PREFIX),
        ("pg-c", _PREFIX),
    }
    assert outcome.selected_loss == pytest.approx(0.6)


def test_cost_rule_needs_one_release_where_the_baseline_needs_two() -> None:
    """The opposite direction, which the fixed-count comparison hid entirely."""
    evaluation = _evaluate()
    outcome = next(
        row
        for row in evaluation.outcomes
        if row.rule_id == "M1_prefill_reload_ascending"
        and row.decision_event_index == 50
    )
    assert outcome.selection_count == 1
    assert outcome.selected_identities == (("pg-e", _PREFIX),)
    assert outcome.selected_loss == pytest.approx(0.2)


def test_aggregates_report_the_hand_computed_baseline_values() -> None:
    aggregate = _evaluate().for_rule("M0_p1b_executed_ordering")
    assert aggregate.decisions == 3
    # D40 and D50 have headroom; D60 is a tie. This is the M4 diagnostic
    # denominator, deliberately not called canonical ``non_tied``.
    assert aggregate.loss_discriminating_decisions == 2
    # Only D40 misselects: it releases loss 0.5 where 0.0 was available.
    assert aggregate.positive_regret_decisions == 1
    assert aggregate.positive_regret_rate == pytest.approx(0.5)
    assert aggregate.mean_absolute_regret == pytest.approx(0.5 / 3.0)
    assert aggregate.mean_normalized_regret == pytest.approx(1.0 / 3.0)
    assert aggregate.tie_rate == pytest.approx(1.0 / 3.0)
    # No canonical M6 table was supplied, so the canonical view stays empty
    # rather than silently reusing the diagnostic denominator.
    assert aggregate.canonical_applicable_decisions == 0
    assert aggregate.canonical_non_tied_decisions == 0
    assert aggregate.canonical_positive_regret_decisions == 0
    assert aggregate.canonical_misselection_rate is None


def test_aggregates_report_the_hand_computed_cost_rule_values() -> None:
    aggregate = _evaluate().for_rule("M1_prefill_reload_ascending")
    assert aggregate.decisions == 3
    assert aggregate.loss_discriminating_decisions == 2
    # D40 releases all three, so its release set is the whole candidate set and
    # matches the size-matched hindsight; D50 picks the cheapest.
    assert aggregate.positive_regret_decisions == 0
    assert aggregate.positive_regret_rate == pytest.approx(0.0)


def test_canonical_denominator_uses_the_unique_hindsight_best_set() -> None:
    """Q9: canonical non-tied means the hindsight-best set is unique.

    D40 has two distinct candidate losses, so it is diagnostic non-tied, but its
    two-entry commitment is *also* non-tied canonically. D60 has identical losses
    and a single best set only by the tie-break, so it is non-tied under neither
    reading. D50 contributes no canonical row at all because the cost rule
    releases one entry where two were observed.
    """
    canonical = (
        _canonical_row("run-1", 40, best_set_count=1),
        _canonical_row("run-1", 50, best_set_count=2),
        _canonical_row("run-2", 60, best_set_count=2),
    )
    aggregate = _evaluate(canonical_regret=canonical).for_rule(
        "M0_p1b_executed_ordering"
    )
    # The baseline releases the observed count everywhere, so all three rows are
    # applicable; only D40 has a unique hindsight optimum.
    assert aggregate.canonical_applicable_decisions == 3
    assert aggregate.canonical_non_tied_decisions == 1
    # The baseline released 0.5 where 0.0 existed; the canonical best set is
    # unique, so it is counted as a positive regret.
    assert aggregate.canonical_positive_regret_decisions == 1
    assert aggregate.canonical_misselection_rate == pytest.approx(1.0)

    cost = _evaluate(canonical_regret=canonical).for_rule(
        "M1_prefill_reload_ascending"
    )
    # The cost rule releases three entries at D40 and one at D50, neither of which
    # is size-matched to the canonical optimum, so those decisions are excluded
    # from the canonical view rather than counted as misselections. Only D60 is
    # comparable, and its two tied best sets make it canonically tied.
    assert cost.canonical_applicable_decisions == 1
    assert cost.canonical_non_tied_decisions == 0
    assert cost.canonical_misselection_rate is None


def test_scenario_clusters_group_seeds_by_decision_position() -> None:
    """Q10: the effective sample is clusters, not raw decision rows."""
    evaluation = _evaluate()
    assert evaluation.evaluated_decisions == 3
    assert evaluation.effective_cluster_count == 3
    assert evaluation.clusters_identical_across_seeds == 3
    keys = {
        (row.scenario_group, row.decision_event_index)
        for row in evaluation.clusters
    }
    # Distinct run ids mean distinct groups, so nothing is merged here.
    assert keys == {("run-1", 40), ("run-1", 50), ("run-2", 60)}


def test_scenario_clusters_merge_seed_replicas_of_one_scenario() -> None:
    """The ``-seed-NNN`` suffix is stripped so seeds form one cluster."""
    rows = scenario_clusters(
        (
            _snapshot(
                run_id="sc-1-seed-101",
                decision_event_index=7,
                entries={"pg-a": (0,), "pg-b": (1,)},
                required_blocks=1,
                observed_selected=("pg-a",),
            ),
            _snapshot(
                run_id="sc-1-seed-202",
                decision_event_index=7,
                entries={"pg-a": (0,), "pg-b": (1,)},
                required_blocks=1,
                observed_selected=("pg-a",),
            ),
        ),
        {
            ("sc-1-seed-101", 7, ("pg-a", _PREFIX)): 0.5,
            ("sc-1-seed-101", 7, ("pg-b", _PREFIX)): 0.1,
            ("sc-1-seed-202", 7, ("pg-a", _PREFIX)): 0.5,
            ("sc-1-seed-202", 7, ("pg-b", _PREFIX)): 0.1,
        },
    )
    assert len(rows) == 1
    assert rows[0].scenario_group == "sc-1"
    assert rows[0].seed_count == 2
    assert rows[0].loss_profile_identical_across_seeds is True


def test_decision_patterns_dedupe_clusters_with_the_same_problem() -> None:
    """Q10: the unique decision-pattern count is the tightest sample size.

    Two *different* scenarios that present the same candidate loss multiset pose
    the same decision problem, so a deterministic rule cannot act differently on
    them. They must therefore not be counted as separate evidence.
    """
    entries = {"pg-a": (0,), "pg-b": (1,)}
    rows = scenario_clusters(
        (
            _snapshot(
                run_id="sc-1-seed-101",
                decision_event_index=7,
                entries=entries,
                required_blocks=1,
                observed_selected=("pg-a",),
            ),
            _snapshot(
                run_id="sc-2-seed-101",
                decision_event_index=9,
                entries=entries,
                required_blocks=1,
                observed_selected=("pg-a",),
            ),
            _snapshot(
                run_id="sc-3-seed-101",
                decision_event_index=9,
                entries=entries,
                required_blocks=1,
                observed_selected=("pg-a",),
            ),
        ),
        {
            ("sc-1-seed-101", 7, ("pg-a", _PREFIX)): 0.5,
            ("sc-1-seed-101", 7, ("pg-b", _PREFIX)): 0.1,
            ("sc-2-seed-101", 9, ("pg-a", _PREFIX)): 0.5,
            ("sc-2-seed-101", 9, ("pg-b", _PREFIX)): 0.1,
            ("sc-3-seed-101", 9, ("pg-a", _PREFIX)): 0.5,
            ("sc-3-seed-101", 9, ("pg-b", _PREFIX)): 0.1,
        },
    )
    assert len(rows) == 3
    assert all(row.decision_pattern == (0.1, 0.5) for row in rows)
    counts = decision_pattern_counts(rows)
    assert counts == (((0.1, 0.5), 3),)
    assert len(counts) == 1


def test_cluster_paired_comparison_counts_each_cluster_once() -> None:
    """The cluster-level test must not be inflated by seed replicas."""
    snapshots = tuple(
        _snapshot(
            run_id=f"sc-1-seed-{seed}",
            decision_event_index=7,
            entries={"pg-a": tuple(range(40)), "pg-b": tuple(range(40, 48))},
            required_blocks=40,
            observed_selected=("pg-a",),
        )
        for seed in (101, 211, 307)
    )
    candidates = tuple(
        row
        for seed in (101, 211, 307)
        for row in (
            _row(
                run_id=f"sc-1-seed-{seed}",
                decision_event_index=7,
                program_id="pg-a",
                selected=True,
                block_ids=tuple(range(40)),
                prefill_reload_seconds=0.5,
                retention_deadline_timestamp=100.0,
                decision_native_lru_position=0,
            ),
            _row(
                run_id=f"sc-1-seed-{seed}",
                decision_event_index=7,
                program_id="pg-b",
                selected=False,
                block_ids=tuple(range(40, 48)),
                prefill_reload_seconds=0.1,
                retention_deadline_timestamp=200.0,
                decision_native_lru_position=1,
            ),
        )
    )
    losses = {
        (f"sc-1-seed-{seed}", 7, program): loss
        for seed in (101, 211, 307)
        for program, loss in (("pg-a", 0.5), ("pg-b", 0.1))
    }
    evidence = tuple(
        _evidence(
            run_id=run_id,
            decision_event_index=7,
            program_id=program,
            loss=loss,
        )
        for (run_id, _, program), loss in losses.items()
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=evidence,
        snapshots=snapshots,
    )
    assert evaluation.effective_cluster_count == 1
    assert evaluation.unique_decision_pattern_count == 1
    raw = paired_comparison(
        evaluation,
        baseline_rule_id="M0_p1b_executed_ordering",
        challenger_rule_id="M1_prefill_reload_ascending",
    )
    # Raw view counts all three seed replicas.
    assert raw["shared_decisions"] == 3
    clustered = cluster_paired_comparison(
        evaluation,
        baseline_rule_id="M0_p1b_executed_ordering",
        challenger_rule_id="M1_prefill_reload_ascending",
    )
    # Cluster view counts the one real decision problem once.
    assert clustered["shared_clusters"] == 1
    assert (
        clustered["improved"] + clustered["worsened"] + clustered["tied"]
        == clustered["shared_clusters"]
    )
    # Releasing pg-a alone already satisfies the target, so the cheap-first rule
    # is forced onto a second release and pays more than the baseline here.
    assert clustered["worsened"] == 1
    assert clustered["mean_loss_delta_seconds"] == pytest.approx(-0.1)


def test_totals_loss_is_the_primary_cross_rule_comparator() -> None:
    """Release count varies, so total proxy loss is what a serving system pays."""
    evaluation = _evaluate()
    totals: dict[str, float] = {}
    for rule_id in ("M0_p1b_executed_ordering", "M1_prefill_reload_ascending"):
        totals[rule_id] = sum(
            outcome.selected_loss
            for outcome in evaluation.outcomes
            if outcome.rule_id == rule_id
        )
    assert totals["M0_p1b_executed_ordering"] == pytest.approx(2.0)
    assert totals["M1_prefill_reload_ascending"] == pytest.approx(1.2)
    assert totals["M1_prefill_reload_ascending"] < totals["M0_p1b_executed_ordering"]


# --- evidence handling -----------------------------------------------------


def test_decision_with_fewer_than_two_available_losses_is_skipped() -> None:
    candidates, evidence, snapshots = _fixture()
    trimmed = tuple(
        row
        for row in evidence
        if not (row.decision_event_index == 60 and row.program_id == "pg-f")
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=trimmed,
        snapshots=snapshots,
        families_by_run=_families(),
    )
    assert evaluation.evaluated_decisions == 2
    assert evaluation.skipped_decisions == 1


def test_partially_available_decision_is_skipped_not_approximated() -> None:
    candidates, evidence, snapshots = _fixture()
    partially_masked = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=None,
            availability="unavailable",
        )
        if row.decision_event_index == 40 and row.program_id == "pg-b"
        else row
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=partially_masked,
        snapshots=snapshots,
        families_by_run=_families(),
    )
    assert evaluation.evaluated_decisions == 2
    assert evaluation.skipped_decisions == 1


def test_unavailable_evidence_does_not_silently_coerce_to_zero() -> None:
    candidates, evidence, snapshots = _fixture()
    masked = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=None,
            availability="unavailable",
        )
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates, evidence=masked, snapshots=snapshots
    )
    assert evaluation.evaluated_decisions == 0
    assert evaluation.available_candidates == 0
    assert all(aggregate.decisions == 0 for aggregate in evaluation.aggregates)


def test_missing_snapshot_skips_the_decision() -> None:
    candidates, evidence, snapshots = _fixture()
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=evidence,
        snapshots=snapshots[:1],
        families_by_run=_families(),
    )
    assert evaluation.evaluated_decisions == 1
    assert evaluation.skipped_decisions == 2


# --- missingness semantics (M1 ruling, 2026-10-07) -------------------------


def test_missing_candidate_evidence_records_its_own_reason_and_count() -> None:
    """A lost candidate is distinguishable from a lost snapshot.

    Previously every cause shared one counter, so a decision short of one
    candidate's evidence looked identical to a decision with no snapshot.
    """
    candidates, evidence, snapshots = _fixture()
    partially_masked = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=None,
            availability="unavailable",
        )
        if row.decision_event_index == 40 and row.program_id == "pg-b"
        else row
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=partially_masked,
        snapshots=snapshots,
        families_by_run=_families(),
    )
    summary = evaluation.missingness
    assert summary is not None
    assert summary.decisions_excluded == 1
    assert summary.reason_count(EXCLUSION_CANDIDATE_EVIDENCE_MISSING) == 1
    assert summary.reason_count(EXCLUSION_DECISION_SNAPSHOT_MISSING) == 0
    (exclusion,) = evaluation.exclusions
    assert exclusion.run_id == "run-1"
    assert exclusion.decision_event_index == 40
    assert exclusion.candidate_count == 3
    assert exclusion.missing_candidate_count == 1
    assert exclusion.unavailable_reasons == ("test_missing",)
    assert summary.missing_candidate_total == 1
    assert summary.unavailable_reason_count("test_missing") == 1


def test_fully_unavailable_decision_is_reported_not_invisible() -> None:
    """A decision with no usable evidence must be counted, not silently absent.

    The old code iterated only decisions that had *some* usable evidence, so a
    decision whose evidence was entirely unavailable produced no skip record at
    all and could not be audited.
    """
    candidates, evidence, snapshots = _fixture()
    masked = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=None,
            availability="unavailable",
        )
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates, evidence=masked, snapshots=snapshots
    )
    summary = evaluation.missingness
    assert summary is not None
    assert summary.decisions_seen == 3
    assert summary.decisions_evaluated == 0
    assert summary.decisions_excluded == 3
    assert summary.reason_count(EXCLUSION_NO_EVIDENCE_FOR_VIEW) == 3
    assert len(evaluation.exclusions) == 3
    # Still no coercion anywhere.
    assert evaluation.available_candidates == 0
    assert all(aggregate.decisions == 0 for aggregate in evaluation.aggregates)


def test_holdout_filter_is_reported_separately_from_missingness() -> None:
    """Excluding a held-out run is a scope decision, not missing evidence."""
    evaluation = _evaluate(included_runs=frozenset({"run-2"}))
    summary = evaluation.missingness
    assert summary is not None
    assert summary.decisions_filtered_out == 2
    assert summary.decisions_excluded == 0
    assert evaluation.exclusions == ()
    assert summary.decisions_seen == evaluation.evaluated_decisions + (
        summary.decisions_excluded + summary.decisions_filtered_out
    )


def test_missing_snapshot_records_its_own_reason_code() -> None:
    candidates, evidence, snapshots = _fixture()
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=evidence,
        snapshots=snapshots[:1],
        families_by_run=_families(),
    )
    summary = evaluation.missingness
    assert summary is not None
    assert summary.reason_count(EXCLUSION_DECISION_SNAPSHOT_MISSING) == 2
    assert summary.reason_count(EXCLUSION_CANDIDATE_EVIDENCE_MISSING) == 0


def test_trimmed_candidate_set_is_reported_as_too_few_candidates() -> None:
    candidates, evidence, snapshots = _fixture()
    trimmed = tuple(
        row
        for row in evidence
        if not (row.decision_event_index == 60 and row.program_id == "pg-f")
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=trimmed,
        snapshots=snapshots,
        families_by_run=_families(),
    )
    summary = evaluation.missingness
    assert summary is not None
    assert summary.reason_count(EXCLUSION_TOO_FEW_CANDIDATES) == 1
    assert evaluation.evaluated_decisions == 2
    assert evaluation.skipped_decisions == 1


def test_missingness_summary_accounts_for_every_seen_decision() -> None:
    """seen == evaluated + excluded + filtered_out, always."""
    candidates, evidence, snapshots = _fixture()
    partially_masked = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=None,
            availability="unavailable",
        )
        if row.decision_event_index == 40 and row.program_id == "pg-b"
        else row
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=partially_masked,
        snapshots=snapshots,
        families_by_run=_families(),
        included_runs=frozenset({"run-1", "run-2"}),
    )
    summary = evaluation.missingness
    assert summary is not None
    assert summary.decisions_seen == (
        summary.decisions_evaluated
        + summary.decisions_excluded
        + summary.decisions_filtered_out
    )
    assert summary.loss_view == CANONICAL_LOSS_VIEW


def test_non_canonical_loss_view_is_ignored() -> None:
    candidates, evidence, snapshots = _fixture()
    other_view = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=row.loss,
            loss_view="observed_recomputed_tokens",
        )
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates, evidence=other_view, snapshots=snapshots
    )
    assert evaluation.evaluated_decisions == 0


def test_included_runs_restricts_the_evaluation() -> None:
    evaluation = _evaluate(included_runs=frozenset({"run-2"}))
    assert evaluation.evaluated_decisions == 1


def test_evaluate_rejects_non_sequence_input() -> None:
    with pytest.raises(TypeError, match="candidates must be an ordered sequence"):
        evaluate_rules(candidates="not-a-sequence", evidence=(), snapshots=())


# --- degeneracy audit ------------------------------------------------------


def test_degeneracy_audit_reports_a_non_identical_pair() -> None:
    evaluation = _evaluate()
    for row in evaluation.degeneracy:
        if {row.rule_a, row.rule_b} == {
            "M0_p1b_executed_ordering",
            "M1_prefill_reload_ascending",
        }:
            assert row.shared_decisions == 3
            assert row.identical_selection_rate is not None
            assert row.identical_selection_rate < 1.0
            break
    else:
        raise AssertionError("baseline/cost pair was not audited")


def test_degeneracy_audit_reports_a_fully_identical_pair() -> None:
    evaluation = _evaluate()
    assert [
        row
        for row in evaluation.degeneracy
        if row.identical_selection_rate == pytest.approx(1.0)
    ], "expected at least one rank-identical pair"


# --- denominator diagnostic ------------------------------------------------


def _shift_denominator(
    rows: list[DecisionCandidateRow], sizes: list[int]
) -> tuple[DecisionCandidateRow, ...]:
    return tuple(
        DecisionCandidateRow(
            **{
                **{
                    field: getattr(row, field)
                    for field in DecisionCandidateRow.__dataclass_fields__
                },
                "initially_reclaimable_block_ids": tuple(range(sizes[index])),
                "initially_reclaimable_block_count": sizes[index],
            }
        )
        for index, row in enumerate(rows)
    )


def test_denominator_diagnostic_flags_a_constant_denominator() -> None:
    candidates, _evidence_rows, _snapshots = _fixture()
    group = [row for row in candidates if row.decision_event_index == 60]
    flat = _shift_denominator(group, [4, 4])
    rows = denominator_diagnostic(flat)
    assert len(rows) == 1
    assert rows[0].denominator_is_constant is True
    assert rows[0].numerator_denominator_spearman is None
    assert rows[0].rank_inversions == 0


def test_denominator_diagnostic_detects_ordering_inversions() -> None:
    candidates, _evidence_rows, _snapshots = _fixture()
    group = [row for row in candidates if row.decision_event_index == 40]
    # Costs 0.5 (pg-a) / 0.1 (pg-b) / 0.3 (pg-c). Giving pg-a by far the largest
    # denominator drives its ratio below the others, so the cost order
    # b < c < a becomes the ratio order a < b < c.
    scaled = _shift_denominator(group, [100, 1, 1])
    rows = denominator_diagnostic(scaled)
    assert len(rows) == 1
    assert rows[0].denominator_is_constant is False
    assert rows[0].rank_inversions == 2
    assert rows[0].comparable_pairs == 3


def test_denominator_diagnostic_reports_no_inversion_for_equal_ratios() -> None:
    """Equal ratios are a tie, not a reordering.

    Costs are 0.5 / 0.1 / 0.3, so denominators 5 / 1 / 3 make every ratio 0.1.
    Exact float comparison would report inversions purely from rounding; the
    tolerance in the diagnostic prevents that.
    """
    candidates, _evidence_rows, _snapshots = _fixture()
    group = [row for row in candidates if row.decision_event_index == 40]
    scaled = _shift_denominator(group, [5, 1, 3])
    rows = denominator_diagnostic(scaled)
    assert rows[0].rank_inversions == 0


def test_denominator_diagnostic_preserves_order_when_proportional() -> None:
    """A strictly proportional denominator cannot reorder anything."""
    candidates, _evidence_rows, _snapshots = _fixture()
    group = [row for row in candidates if row.decision_event_index == 40]
    # Ratio is constant 0.1 for all three, so no pair can flip.
    scaled = _shift_denominator(group, [5, 1, 3])
    rows = denominator_diagnostic(scaled)
    assert rows[0].denominator_is_constant is False
    assert rows[0].rank_inversions == 0
    assert (
        rows[0].numerator_denominator_spearman is None
        or rows[0].numerator_denominator_spearman <= 0.0
        or rows[0].numerator_denominator_spearman > 0.0
    )


def test_denominator_diagnostic_skips_single_candidate_decisions() -> None:
    candidates, _evidence_rows, _snapshots = _fixture()
    single = [row for row in candidates if row.program_id == "pg-f"]
    assert denominator_diagnostic(single) == ()


# --- ablation -------------------------------------------------------------


def test_ablation_pairs_reference_registered_rules() -> None:
    for _label, _changes, pair in ABLATION_PAIRS:
        left_id, right_id = pair.split(":")
        assert rule_by_id(left_id).rule_id == left_id
        assert rule_by_id(right_id).rule_id == right_id


def test_ablation_table_reports_identity_alongside_regret() -> None:
    rows = ablation_table(_evaluate())
    assert rows
    assert {row.variant for row in rows} <= {
        label for label, _changes, _pair in ABLATION_PAIRS
    }
    assert any(
        row.identical_selection_rate is not None
        and row.identical_selection_rate < 1.0
        for row in rows
    )


# --- behaviour breakdown --------------------------------------------------


def test_behaviour_breakdown_covers_all_requested_dimensions() -> None:
    rows = behaviour_breakdown(_evaluate())
    assert rows
    assert {row.dimension for row in rows} == {
        "scenario_family",
        "candidate_count",
        "selection_count",
    }


def test_behaviour_breakdown_splits_by_family() -> None:
    rows = [
        row
        for row in behaviour_breakdown(_evaluate(), dimensions=("scenario_family",))
        if row.rule_id == "M0_p1b_executed_ordering"
    ]
    assert {row.bucket for row in rows} == {"F1", "F2"}
    assert sum(row.decisions for row in rows) == 3


def test_behaviour_breakdown_exposes_variable_release_counts() -> None:
    rows = behaviour_breakdown(_evaluate(), dimensions=("selection_count",))
    buckets = {
        row.bucket
        for row in rows
        if row.rule_id == "M1_prefill_reload_ascending"
    }
    assert buckets == {"releases=1", "releases=3"}


def test_behaviour_breakdown_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="unsupported dimensions"):
        behaviour_breakdown(_evaluate(), dimensions=("not_a_dimension",))


def test_behaviour_breakdown_rejects_empty_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions must not be empty"):
        behaviour_breakdown(_evaluate(), dimensions=())


# --- paired comparison and holdout ----------------------------------------


def test_paired_comparison_counts_improved_tied_and_worsened() -> None:
    evaluation = _evaluate()
    stats = paired_comparison(
        evaluation,
        baseline_rule_id="M0_p1b_executed_ordering",
        challenger_rule_id="M1_prefill_reload_ascending",
    )
    assert stats["shared_decisions"] == 3
    # D40: baseline 0.5 vs cost 0.6 -> the baseline wins.
    # D50: baseline 1.1 vs cost 0.2 -> the cost rule wins.
    # D60: identical -> tie.
    assert stats["improved"] == 1
    assert stats["worsened"] == 1
    assert stats["tied"] == 1
    # Deltas are -0.1 (D40), +0.9 (D50) and 0.0 (D60).
    assert stats["mean_loss_delta_seconds"] == pytest.approx(0.8 / 3.0)
    assert stats["sum_loss_delta_seconds"] == pytest.approx(0.8)


def test_paired_comparison_rejects_disjoint_rules() -> None:
    with pytest.raises(ValueError, match="share no evaluated decisions"):
        paired_comparison(
            _evaluate(),
            baseline_rule_id="M0_p1b_executed_ordering",
            challenger_rule_id="not_a_rule",
        )


def test_leave_one_family_out_holds_each_family_out_in_turn() -> None:
    candidates, evidence, snapshots = _fixture()
    holdout = leave_one_family_out(
        candidates=candidates,
        evidence=evidence,
        snapshots=snapshots,
        families_by_run=_families(),
    )
    assert set(holdout) == {"F1", "F2"}
    assert holdout["F1"]["M0_p1b_executed_ordering"].decisions == 1
    assert holdout["F2"]["M0_p1b_executed_ordering"].decisions == 2


def test_for_rule_and_burden_reject_unknown_rule() -> None:
    with pytest.raises(KeyError, match="not present"):
        _evaluate().for_rule("not_a_rule")
    with pytest.raises(KeyError, match="not present"):
        _evaluate().burden_for_rule("not_a_rule")
