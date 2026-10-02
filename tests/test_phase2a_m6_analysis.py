import pytest

from kvopt.profiling.analysis import (
    CandidateLossRow,
    build_candidate_feature_spreads,
    build_decision_regret_table,
)
from kvopt.profiling.datasets import DecisionCandidateRow


def _candidate(
    program_id: str,
    *,
    block_count: int,
    prefill_reload_seconds: float,
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id="run-1",
        decision_event_index=10,
        source_event_index=10,
        candidate_position=0,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        selected=program_id == "a",
        release_order=1 if program_id == "a" else None,
        retention_deadline_timestamp=20.0,
        waiting_followup=True,
        block_ids=tuple(range(block_count)),
        block_count=block_count,
        initially_reclaimable_block_ids=(),
        initially_reclaimable_block_count=0,
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=2.0,
        prefill_reload_seconds=prefill_reload_seconds,
        eta=3.0,
        queue_delay_t_seconds=0.5,
    )


def _loss(
    program_id: str,
    loss: float,
    *,
    selected: bool,
    decision_event_index: int = 10,
) -> CandidateLossRow:
    return CandidateLossRow(
        run_id="run-1",
        decision_event_index=decision_event_index,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        loss_view="logical_release_proxy",
        loss=loss,
        selected=selected,
    )


def test_feature_spreads_use_decision_time_allowlist() -> None:
    rows = build_candidate_feature_spreads(
        (
            _candidate("a", block_count=2, prefill_reload_seconds=0.4),
            _candidate("b", block_count=5, prefill_reload_seconds=1.0),
        )
    )
    by_feature = {row.feature: row for row in rows}

    assert by_feature["block_count"].spread == 3.0
    assert by_feature["prefill_reload_seconds"].spread == pytest.approx(0.6)
    assert "returned_after_decision" not in by_feature


def test_regret_preserves_single_release_hindsight_tie() -> None:
    row = build_decision_regret_table(
        (
            _loss("a", 8.0, selected=True),
            _loss("b", 2.0, selected=False),
            _loss("c", 2.0, selected=False),
        )
    )[0]

    assert row.hindsight_boundary_candidates == (
        ("b", "prefix-b"),
        ("c", "prefix-c"),
    )
    assert row.hindsight_best_set_count == 2
    assert row.selected_loss == 8.0
    assert row.hindsight_best_loss == 2.0
    assert row.absolute_regret == 6.0
    assert row.normalized_regret == pytest.approx(0.75)
    assert not row.selected_is_hindsight_best


def test_regret_evaluates_multi_release_set_with_boundary_tie() -> None:
    row = build_decision_regret_table(
        (
            _loss("a", 1.0, selected=True, decision_event_index=20),
            _loss("b", 2.0, selected=True, decision_event_index=20),
            _loss("c", 2.0, selected=False, decision_event_index=20),
        )
    )[0]

    assert row.selection_count == 2
    assert row.hindsight_mandatory_candidates == (("a", "prefix-a"),)
    assert row.hindsight_boundary_candidates == (
        ("b", "prefix-b"),
        ("c", "prefix-c"),
    )
    assert row.hindsight_best_set_count == 2
    assert row.absolute_regret == 0.0
    assert row.selected_is_hindsight_best
