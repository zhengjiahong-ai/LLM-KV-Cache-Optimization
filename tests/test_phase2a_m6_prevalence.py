from dataclasses import replace

from kvopt.profiling.datasets import (
    DecisionRow,
    LogicalReleaseRow,
    RunRow,
)
from kvopt.profiling.prevalence import build_prevalence_tables
from kvopt.profiling.request_outcomes import RequestOutcomeRow


def _run(run_id: str, seed: int, status: str = "success") -> RunRow:
    return RunRow(
        run_id=run_id,
        source_run_dir=f"/runs/{run_id}",
        status=status,
        failure_reason=None,
        git_sha="abc",
        git_dirty=False,
        trace_id="trace",
        trace_sha256="trace-sha",
        config_sha256="config-sha",
        seed=seed,
        policy="continuum",
        runtime_mode="synthetic",
        scenario_id="scenario-a",
        scenario_family_id="family-a",
        backend="synthetic",
        backend_revision="1",
        model_name="model",
        model_revision="1",
        tokenizer_name="tokenizer",
        tokenizer_revision="1",
        platform="test",
        started_at_utc=None,
        ended_at_utc=None,
        event_count=10,
        forced_release_event_count=1,
        observation_availability={},
    )


def _decision(run_id: str, event_index: int, candidates: int) -> DecisionRow:
    return DecisionRow(
        run_id=run_id,
        decision_event_index=event_index,
        source_event_index=event_index,
        timestamp=float(event_index),
        clock_domain="runtime",
        source="test",
        required_blocks=2,
        candidate_count=candidates,
        selected_release_count=1,
        original_free_queue_count=2,
        ordinary_expired_entry_count=0,
    )


def _release(run_id: str, event_index: int) -> LogicalReleaseRow:
    return LogicalReleaseRow(
        run_id=run_id,
        decision_event_index=event_index,
        source_event_index=event_index,
        release_order=1,
        program_id="agent-a",
        prefix_id="prefix-a",
        newly_eligible_block_ids=(1,),
        newly_eligible_block_count=1,
    )


def _request(run_id: str, request_id: str) -> RequestOutcomeRow:
    base = RequestOutcomeRow(
        run_id=run_id,
        request_id=request_id,
        program_id="agent-a",
        turn_index=1,
        kind="program_turn",
        planned_arrival_offset_seconds=0.0,
        tool_gap_seconds=None,
        arrival_event_index=None,
        arrival_timestamp=None,
        arrival_clock_domain=None,
        logical_admission_event_index=None,
        logical_admission_timestamp=None,
        logical_admission_clock_domain=None,
        logical_admission_delay_seconds=None,
        logical_admission_delay_status="missing_landmark",
        submission_event_index=None,
        submission_timestamp=None,
        submission_clock_domain=None,
        completion_event_index=None,
        completion_timestamp=None,
        completion_clock_domain=None,
        backend_service_seconds=None,
        backend_service_status="missing_landmark",
        prefix_snapshot_event_index=None,
        prefix_id=None,
        reusable_token_count=None,
        block_ids=None,
        output_token_count=None,
    )
    return replace(base, request_id=request_id)


def test_prevalence_summarizes_successes_and_preserves_failures() -> None:
    tables = build_prevalence_tables(
        (_run("run-1", 1), _run("run-2", 2), _run("failed", 3, "failed")),
        (
            _decision("run-1", 10, 2),
            _decision("run-1", 20, 3),
            _decision("run-2", 10, 1),
            _decision("failed", 10, 9),
        ),
        (_release("run-1", 10), _release("run-1", 20)),
        (
            _request("run-1", "request-1"),
            _request("run-1", "request-2"),
            _request("run-2", "request-3"),
        ),
    )
    overall = next(row for row in tables.summary if row.scope == "overall")
    run_one = next(row for row in tables.runs if row.run_id == "run-1")

    assert overall.run_count == 3
    assert overall.successful_run_count == 2
    assert overall.failed_run_count == 1
    assert overall.request_count == 3
    assert overall.decision_count == 3
    assert overall.multi_candidate_decision_count == 2
    assert overall.forced_release_per_request == 1.0
    assert overall.maximum_candidate_count == 3
    assert overall.repeated_pressure_run_count == 1
    assert overall.repeated_logical_release_count == 1
    assert run_one.repeated_pressure
