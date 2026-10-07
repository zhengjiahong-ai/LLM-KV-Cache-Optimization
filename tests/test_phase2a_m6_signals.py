from dataclasses import replace

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
    assert block_support.proxy_supported
    assert block_support.runtime_replicated is False
    assert block_support.support_level == "PROXY_SUPPORTED"
    assert "returned_after_decision" not in {
        row.feature for row in tables.associations
    }
    assert tables.evaluation.status == "SUPPORTED"
    assert tables.evaluation.online_signal_supported is True
    assert tables.evaluation.proxy_supported is True
    assert tables.evaluation.runtime_replicated is False
    assert tables.evaluation.support_level == "PROXY_SUPPORTED"


def test_signal_analysis_rejects_within_decision_constant_feature() -> None:
    metadata = tuple(
        SignalRunMetadata(
            run_id=f"run-{size}",
            scenario_family_id=f"family-{size}",
            seed=size,
        )
        for size in range(2, 5)
    )
    candidates = tuple(
        _candidate(f"run-{size}", chr(ord("a") + position), position + 1)
        for size in range(2, 5)
        for position in range(size)
    )
    losses = tuple(
        _loss(
            f"run-{size}",
            chr(ord("a") + position),
            float(position + 1),
        )
        for size in range(2, 5)
        for position in range(size)
    )

    tables = build_signal_analysis_tables(candidates, losses, metadata)
    eta_support = next(
        row for row in tables.support if row.feature == "eta"
    )
    eta_association = next(
        row
        for row in tables.associations
        if row.feature == "eta" and row.group_type == "overall"
    )

    assert eta_association.observation_count == 0
    assert eta_association.decision_count == 0
    assert eta_support.overall_spearman_rho is None
    assert not eta_support.coverage_sufficient
    assert not eta_support.supported


def test_signal_analysis_evaluates_next_tool_type_without_ordering_categories() -> None:
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
            replace(
                _candidate(f"run-{index}", "a", 1),
                next_tool_type="search",
            ),
            replace(
                _candidate(f"run-{index}", "b", 1),
                next_tool_type="code",
            ),
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
    code_support = next(
        row
        for row in tables.support
        if row.feature == "next_tool_type=code"
    )

    assert code_support.overall_spearman_rho == 1.0
    assert code_support.supported


def test_signal_analysis_evaluates_decision_native_lru_position() -> None:
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
            replace(
                _candidate(f"run-{index}", "a", 1),
                decision_native_lru_position=0,
            ),
            replace(
                _candidate(f"run-{index}", "b", 1),
                decision_native_lru_position=5,
            ),
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
    lru_support = next(
        row
        for row in tables.support
        if row.feature == "decision_native_lru_position"
    )

    assert lru_support.overall_spearman_rho == 1.0
    assert lru_support.supported


def test_signal_analysis_preserves_insufficient_coverage() -> None:
    tables = build_signal_analysis_tables(
        (_candidate("run-1", "a", 1), _candidate("run-1", "b", 3)),
        (_loss("run-1", "a", 1.0), _loss("run-1", "b", 3.0)),
        (SignalRunMetadata("run-1", "family-1", 1),),
    )

    assert tables.evaluation.status == "INSUFFICIENT_COVERAGE"
    assert tables.evaluation.online_signal_supported is None


def test_signal_analysis_reports_feature_missingness_per_decision() -> None:
    metadata = (
        SignalRunMetadata("run-complete", "family-1", 1),
        SignalRunMetadata("run-missing", "family-2", 2),
    )
    candidates = (
        replace(
            _candidate("run-complete", "a", 1),
            decision_native_lru_position=1,
        ),
        replace(
            _candidate("run-complete", "b", 3),
            decision_native_lru_position=2,
        ),
        _candidate("run-missing", "a", 1),
        replace(
            _candidate("run-missing", "b", 3),
            decision_native_lru_position=2,
        ),
    )
    losses = (
        _loss("run-complete", "a", 1.0),
        _loss("run-complete", "b", 3.0),
        _loss("run-missing", "a", 1.0),
        _loss("run-missing", "b", 3.0),
    )

    tables = build_signal_analysis_tables(candidates, losses, metadata)
    coverage = next(
        row
        for row in tables.feature_coverage
        if row.loss_view == "proxy"
        and row.feature == "decision_native_lru_position"
    )

    assert coverage.decision_count == 2
    assert coverage.evaluated_decision_count == 1
    assert coverage.skipped_decision_count == 1
    assert coverage.skipped_reason == "feature_unobserved"
    assert (
        coverage.evaluated_decision_count
        + coverage.skipped_decision_count
        == coverage.decision_count
    )


def test_signal_feature_coverage_reconciles_every_feature() -> None:
    tables = build_signal_analysis_tables(
        (_candidate("run-1", "a", 1), _candidate("run-1", "b", 3)),
        (_loss("run-1", "a", 1.0), _loss("run-1", "b", 3.0)),
        (SignalRunMetadata("run-1", "family-1", 1),),
    )

    assert tables.feature_coverage
    assert all(
        row.evaluated_decision_count + row.skipped_decision_count
        == row.decision_count
        for row in tables.feature_coverage
    )
