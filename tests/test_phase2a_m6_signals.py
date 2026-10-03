from kvopt.profiling.analysis import CandidateLossRow
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.signals import (
    SignalRunMetadata,
    build_signal_analysis_tables,
)


def _candidate(run_id: str, program_id: str, blocks: int) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id=run_id,
        decision_event_index=10,
        source_event_index=10,
        candidate_position=0,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        selected=program_id == "a",
        release_order=1 if program_id == "a" else None,
        retention_deadline_timestamp=1.0,
        waiting_followup=True,
        block_ids=tuple(range(blocks)),
        block_count=blocks,
        initially_reclaimable_block_ids=(),
        initially_reclaimable_block_count=0,
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=float(blocks),
        eta=1.0,
        queue_delay_t_seconds=1.0,
    )


def _loss(run_id: str, program_id: str, loss: float) -> CandidateLossRow:
    return CandidateLossRow(
        run_id=run_id,
        decision_event_index=10,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        loss_view="proxy",
        loss=loss,
        selected=program_id == "a",
    )


def test_signal_analysis_supports_stable_cross_family_rank_signal() -> None:
    metadata = tuple(
        SignalRunMetadata(
            run_id=f"run-{index}",
            scenario_family_id=f"family-{index}",
            seed=index,
        )
        for index in range(1, 4)
    )
    candidates = tuple(
        candidate
        for index in range(1, 4)
        for candidate in (
            _candidate(f"run-{index}", "a", 1),
            _candidate(f"run-{index}", "b", 3),
        )
    )
    losses = tuple(
        loss
        for index in range(1, 4)
        for loss in (
            _loss(f"run-{index}", "a", 1.0),
            _loss(f"run-{index}", "b", 3.0),
        )
    )

    tables = build_signal_analysis_tables(candidates, losses, metadata)
    block_support = next(
        row for row in tables.support if row.feature == "block_count"
    )

    assert block_support.overall_spearman_rho == 1.0
    assert block_support.evaluable_family_count == 3
    assert block_support.evaluable_seed_count == 3
    assert block_support.supported
    assert "returned_after_decision" not in {
        row.feature for row in tables.associations
    }
    assert tables.evaluation.status == "SUPPORTED"
    assert tables.evaluation.online_signal_supported is True


def test_signal_analysis_preserves_insufficient_coverage() -> None:
    tables = build_signal_analysis_tables(
        (_candidate("run-1", "a", 1), _candidate("run-1", "b", 3)),
        (_loss("run-1", "a", 1.0), _loss("run-1", "b", 3.0)),
        (SignalRunMetadata("run-1", "family-1", 1),),
    )

    assert tables.evaluation.status == "INSUFFICIENT_COVERAGE"
    assert tables.evaluation.online_signal_supported is None
