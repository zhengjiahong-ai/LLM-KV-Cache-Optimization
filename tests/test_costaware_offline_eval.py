"""Tests for the M4 offline rule evaluator."""

from __future__ import annotations

import pytest

from kvopt.costaware.offline_eval import (
    CANONICAL_LOSS_VIEW,
    evaluate_rules,
    leave_one_family_out,
    paired_comparison,
    reproduce_executed_baseline,
)
from kvopt.costaware.rules import CANDIDATE_RULES, rule_by_id
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.loss_views import CandidateLossEvidenceRow

_PREFIX = "p"


def _candidate(
    *,
    run_id: str,
    decision_event_index: int,
    program_id: str,
    selected: bool,
    prefill_reload_seconds: float,
    block_count: int,
    retention_deadline_timestamp: float,
    decision_native_lru_position: int,
    next_tool_type: str | None = "search",
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
        block_ids=tuple(range(block_count)),
        block_count=block_count,
        initially_reclaimable_block_ids=tuple(range(block_count)),
        initially_reclaimable_block_count=block_count,
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


def _dataset() -> tuple[tuple[DecisionCandidateRow, ...], tuple[CandidateLossEvidenceRow, ...]]:
    """Three decisions where the executed baseline is deliberately suboptimal.

    Sizes are proportional to recomputation cost so the size-only cluster is
    rank-identical, which exercises the degeneracy audit.
    """
    candidates = (
        # Decision 10: the executed baseline releases the most expensive entry.
        _candidate(run_id="run-1", decision_event_index=10, program_id="pg-a",
                   selected=True, prefill_reload_seconds=0.5, block_count=40,
                   retention_deadline_timestamp=100.0, decision_native_lru_position=0,
                   next_tool_type="code"),
        _candidate(run_id="run-1", decision_event_index=10, program_id="pg-b",
                   selected=False, prefill_reload_seconds=0.1, block_count=8,
                   retention_deadline_timestamp=200.0, decision_native_lru_position=1,
                   next_tool_type="code"),
        _candidate(run_id="run-1", decision_event_index=10, program_id="pg-c",
                   selected=False, prefill_reload_seconds=0.3, block_count=24,
                   retention_deadline_timestamp=150.0, decision_native_lru_position=2,
                   next_tool_type="search"),
        # Decision 20: an exact tie, so any pick is hindsight-optimal.
        _candidate(run_id="run-1", decision_event_index=20, program_id="pg-d",
                   selected=True, prefill_reload_seconds=0.2, block_count=16,
                   retention_deadline_timestamp=100.0, decision_native_lru_position=0),
        _candidate(run_id="run-1", decision_event_index=20, program_id="pg-e",
                   selected=False, prefill_reload_seconds=0.2, block_count=16,
                   retention_deadline_timestamp=200.0, decision_native_lru_position=1),
        # Decision 30 in a second family.
        _candidate(run_id="run-2", decision_event_index=30, program_id="pg-f",
                   selected=True, prefill_reload_seconds=0.4, block_count=32,
                   retention_deadline_timestamp=100.0, decision_native_lru_position=0,
                   next_tool_type="code"),
        _candidate(run_id="run-2", decision_event_index=30, program_id="pg-g",
                   selected=False, prefill_reload_seconds=0.4, block_count=32,
                   retention_deadline_timestamp=200.0, decision_native_lru_position=1,
                   next_tool_type="search"),
    )
    losses = {
        ("run-1", 10, "pg-a"): 0.5,
        ("run-1", 10, "pg-b"): 0.1,
        ("run-1", 10, "pg-c"): 0.0,
        ("run-1", 20, "pg-d"): 0.2,
        ("run-1", 20, "pg-e"): 0.2,
        ("run-2", 30, "pg-f"): 0.4,
        ("run-2", 30, "pg-g"): 0.0,
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
    return candidates, evidence


def _families() -> dict[str, str | None]:
    return {"run-1": "F1", "run-2": "F2"}


def _evaluate(**overrides: object):
    candidates, evidence = _dataset()
    arguments: dict[str, object] = {
        "candidates": candidates,
        "evidence": evidence,
        "families_by_run": _families(),
    }
    arguments.update(overrides)
    return evaluate_rules(**arguments)  # type: ignore[arg-type]


def test_every_registered_rule_is_evaluated() -> None:
    evaluation = _evaluate()
    assert evaluation.evaluated_decisions == 3
    assert evaluation.skipped_decisions == 0
    assert {aggregate.rule_id for aggregate in evaluation.aggregates} == {
        rule.rule_id for rule in CANDIDATE_RULES
    }
    assert evaluation.loss_view == CANONICAL_LOSS_VIEW


def test_executed_baseline_regret_matches_hand_computed_values() -> None:
    aggregate = _evaluate().for_rule("M0_p1b_executed_ordering")
    assert aggregate.decisions == 3
    # Regrets are 0.5, 0.0, 0.4.
    assert aggregate.mean_absolute_regret == pytest.approx(0.3)
    assert aggregate.non_tied_decisions == 2
    assert aggregate.strictly_worse_decisions == 2
    assert aggregate.misselection_rate == pytest.approx(1.0)


def test_cost_only_rule_improves_but_stays_degenerate_with_baseline() -> None:
    evaluation = _evaluate()
    aggregate = evaluation.for_rule("M1_prefill_reload_ascending")
    # Regrets are 0.1, 0.0, 0.4.
    assert aggregate.mean_absolute_regret == pytest.approx(0.5 / 3.0)
    assert aggregate.misselection_rate == pytest.approx(1.0)


def test_lifecycle_rule_reaches_zero_regret_on_this_fixture() -> None:
    aggregate = _evaluate().for_rule("M2_non_code_first")
    assert aggregate.mean_absolute_regret == pytest.approx(0.0)
    assert aggregate.non_tied_decisions == 0
    assert aggregate.misselection_rate is None
    assert aggregate.tie_rate == pytest.approx(1.0)


def test_selection_count_is_held_equal_to_the_executed_baseline() -> None:
    evaluation = _evaluate()
    for outcome in evaluation.outcomes:
        assert outcome.selection_count == 1
        assert len(outcome.selected_identities) == 1


def test_rule_outcome_is_hindsight_best_when_it_picks_the_cheapest_candidate() -> None:
    evaluation = _evaluate()
    first_decision = next(
        outcome
        for outcome in evaluation.outcomes
        if outcome.rule_id == "M2_non_code_first"
        and outcome.decision_event_index == 10
    )
    assert first_decision.selected_identities == (("pg-c", _PREFIX),)
    assert first_decision.selected_is_hindsight_best is True
    assert first_decision.absolute_regret == pytest.approx(0.0)


def test_decision_with_fewer_than_two_available_losses_is_skipped() -> None:
    candidates, evidence = _dataset()
    trimmed = tuple(
        row
        for row in evidence
        if not (row.decision_event_index == 30 and row.program_id == "pg-f")
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=trimmed,
        families_by_run=_families(),
    )
    assert evaluation.evaluated_decisions == 2
    assert evaluation.skipped_decisions == 1


def test_unavailable_evidence_does_not_silently_coerce_to_zero() -> None:
    candidates, evidence = _dataset()
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
    evaluation = evaluate_rules(candidates=candidates, evidence=masked)
    assert evaluation.evaluated_decisions == 0
    assert evaluation.available_candidates == 0
    assert all(
        aggregate.decisions == 0 for aggregate in evaluation.aggregates
    )


def test_partially_available_decision_is_skipped_not_approximated() -> None:
    """A decision is only comparable when every candidate has evidence."""
    candidates, evidence = _dataset()
    partially_masked = tuple(
        _evidence(
            run_id=row.run_id,
            decision_event_index=row.decision_event_index,
            program_id=row.program_id,
            loss=None,
            availability="unavailable",
        )
        if row.decision_event_index == 10 and row.program_id == "pg-b"
        else row
        for row in evidence
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=partially_masked,
        families_by_run=_families(),
    )
    assert evaluation.evaluated_decisions == 2
    assert evaluation.skipped_decisions == 1


def test_non_canonical_loss_view_is_ignored() -> None:
    candidates, evidence = _dataset()
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
    evaluation = evaluate_rules(candidates=candidates, evidence=other_view)
    assert evaluation.evaluated_decisions == 0


def test_included_runs_restricts_the_evaluation() -> None:
    evaluation = _evaluate(included_runs=frozenset({"run-2"}))
    assert evaluation.evaluated_decisions == 1


def test_degeneracy_audit_flags_the_rank_identical_size_cluster() -> None:
    evaluation = _evaluate()
    for row in evaluation.degeneracy:
        pair = {row.rule_a, row.rule_b}
        if pair == {"M1_prefill_reload_ascending", "M1_block_count_ascending"}:
            assert row.shared_decisions == 3
            assert row.identical_selection_rate == pytest.approx(1.0)
            break
    else:
        raise AssertionError("size cluster degeneracy was not reported")


def test_degeneracy_audit_reports_a_discriminating_pair() -> None:
    evaluation = _evaluate()
    for row in evaluation.degeneracy:
        pair = {row.rule_a, row.rule_b}
        if pair == {"M1_prefill_reload_ascending", "M2_non_code_first"}:
            assert row.identical_selection_rate is not None
            assert row.identical_selection_rate < 1.0
            break
    else:
        raise AssertionError("discriminating pair was not reported")


def test_reproduce_executed_baseline_confirms_the_harness() -> None:
    candidates, _evidence_rows = _dataset()
    reproduction = reproduce_executed_baseline(
        candidates=candidates,
        execution_rule=rule_by_id("M0_p1b_executed_ordering"),
        decision_keys=[("run-1", 10), ("run-1", 20), ("run-2", 30)],
    )
    assert reproduction.shared_decisions == 3
    assert reproduction.matching_decisions == 3
    assert reproduction.match_rate == pytest.approx(1.0)
    assert reproduction.missing_native_lru_position == 0


def test_reproduce_executed_baseline_detects_a_mismatch() -> None:
    candidates, _evidence_rows = _dataset()
    flipped = tuple(
        row
        if row.decision_event_index != 10
        else DecisionCandidateRow(
            **{
                **{
                    field: getattr(row, field)
                    for field in DecisionCandidateRow.__dataclass_fields__
                },
                "selected": row.program_id == "pg-b",
                "release_order": 1 if row.program_id == "pg-b" else None,
            }
        )
        for row in candidates
    )
    reproduction = reproduce_executed_baseline(
        candidates=flipped,
        execution_rule=rule_by_id("M0_p1b_executed_ordering"),
        decision_keys=[("run-1", 10)],
    )
    assert reproduction.shared_decisions == 1
    assert reproduction.matching_decisions == 0
    assert reproduction.match_rate == pytest.approx(0.0)


def test_paired_comparison_counts_improved_tied_and_worsened() -> None:
    evaluation = _evaluate()
    stats = paired_comparison(
        evaluation,
        baseline_rule_id="M0_p1b_executed_ordering",
        challenger_rule_id="M2_non_code_first",
    )
    assert stats["shared_decisions"] == 3
    assert stats["improved"] == 2
    assert stats["worsened"] == 0
    assert stats["tied"] == 1
    assert stats["mean_loss_delta_seconds"] == pytest.approx(0.3)


def test_paired_comparison_rejects_disjoint_rules() -> None:
    evaluation = _evaluate()
    with pytest.raises(ValueError, match="share no evaluated decisions"):
        paired_comparison(
            evaluation,
            baseline_rule_id="M0_p1b_executed_ordering",
            challenger_rule_id="not_a_rule",
        )


def test_leave_one_family_out_holds_each_family_out_in_turn() -> None:
    candidates, evidence = _dataset()
    holdout = leave_one_family_out(
        candidates=candidates,
        evidence=evidence,
        families_by_run=_families(),
    )
    assert set(holdout) == {"F1", "F2"}
    # Holding out F1 leaves only the single run-2 decision.
    assert holdout["F1"]["M2_non_code_first"].decisions == 1
    # Holding out F2 leaves the two run-1 decisions.
    assert holdout["F2"]["M2_non_code_first"].decisions == 2


def test_for_rule_rejects_unknown_rule() -> None:
    with pytest.raises(KeyError, match="not present"):
        _evaluate().for_rule("not_a_rule")


def test_evaluate_rejects_non_sequence_input() -> None:
    with pytest.raises(TypeError, match="candidates must be an ordered sequence"):
        evaluate_rules(candidates="not-a-sequence", evidence=())  # type: ignore[arg-type]
