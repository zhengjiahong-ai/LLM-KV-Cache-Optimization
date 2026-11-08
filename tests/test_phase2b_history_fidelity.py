from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    FakeClock,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    TurnFinished,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.continuum.snapshots import EvictedRequestQueueDelayRecord
from kvopt.profiling.experiment_events import InMemoryExperimentEventSink
from kvopt.workload.phase2b_fidelity import (
    HistoryObservation,
    build_history_gate,
)


class ConstantPrefillProvider:
    def estimate(self, token_count: int):
        assert token_count == 16
        return 0.1, InputProvenance(
            InputSource.APPROXIMATED,
            "test profile interpolation",
        )


def _runtime():
    sink = InMemoryExperimentEventSink()
    runtime = build_runtime(
        clock=FakeClock(),
        prefill_reload_provider=ConstantPrefillProvider(),
        default_ttl_seconds=30.0,
        experiment_event_sink=sink,
        history_observation_enabled=True,
    )
    return runtime, sink


def test_native_queue_duration_remains_separate_from_ttl_queue_history() -> None:
    runtime, sink = _runtime()
    program = ProgramIdentity("p")
    request = RequestIdentity("p:1")
    prefix = PrefixIdentity("prefix:p")
    runtime.handle(RequestArrived(program, request, 1.0))
    runtime.handle(RequestAdmitted(program, request, 1.5))
    runtime.record_native_queue_observation(
        program_id=program,
        request_id=request,
        queued_timestamp=10.0,
        scheduled_timestamp=12.0,
        clock_domain="engine_core_monotonic",
    )
    runtime.record_prefill_context_token_count(
        PrefillContextTokenCountRecord(
            program,
            request,
            prefix,
            16,
            InputProvenance(InputSource.OBSERVED),
        )
    )
    runtime.handle(
        BlocksObserved(program, request, prefix, (BlockIdentity(1),), 2.0)
    )
    runtime.handle(TurnFinished(program, request, 3.0, False, "search"))

    history_event = next(
        event
        for event in sink.snapshot()
        if event.event_type == "TTL_HISTORY_INPUT_OBSERVED"
    )
    payload = history_event.payload.to_dict()
    assert payload["native_queue_duration_seconds"] == 2.0
    assert payload["queue_delay_history_sample_count"] == 0
    assert payload["queue_delay_t_seconds"] == 0.0
    assert payload["native_queue_duration_used_as_ttl_history"] is False
    assert payload["eta"] == 1.0
    assert payload["eta_provenance_source"] == "APPROXIMATED"
    assert payload["eta_provenance_reason"] == "FULLY_MEMORYFUL_COLD_START"
    assert payload["global_server_gap_sample_count"] == 0
    assert payload["tool_server_gap_sample_count"] == 0
    assert payload["server_gap_history_provenance_source"] == "OBSERVED"
    decision = next(
        event for event in sink.snapshot() if event.event_type == "TTL_DECISION_OBSERVED"
    )
    decision_payload = decision.payload.to_dict()
    assert decision_payload["history_mode"] == "cold_start"
    assert decision_payload["ttl_seconds"] == 30.0
    assert decision_payload["deadline_timestamp"] == 33.0


def test_only_typed_evicted_request_record_enters_queue_history() -> None:
    runtime, sink = _runtime()
    program = ProgramIdentity("p")
    request = RequestIdentity("p:1")

    runtime.record_queue_delay(
        EvictedRequestQueueDelayRecord(program, request, 1.0, 3.5)
    )

    assert runtime.queue_delay_history.samples() == (2.5,)
    event = sink.snapshot()[0]
    assert event.event_type == "EVICTED_REQUEST_QUEUE_DELAY_RECORDED"
    assert event.payload.to_dict()["eligibility"] == (
        "EVICTED_REQUEST_QUEUE_DELAY_RECORD"
    )


def test_eta_completed_program_state_is_read_only_and_cold_start_is_preserved() -> None:
    runtime, _sink = _runtime()
    runtime.eta_history.record_completed_program(ProgramIdentity("short"), 2)
    runtime.eta_history.record_completed_program(ProgramIdentity("long"), 4)

    eta, provenance = runtime.eta_history.eta()
    assert runtime.eta_history.completed_programs() == (
        (ProgramIdentity("short"), 2),
        (ProgramIdentity("long"), 4),
    )
    assert len(runtime.eta_history.samples()) == 4
    assert provenance.source is InputSource.OBSERVED
    assert eta != 1.0


def test_sampled_targets_without_history_do_not_pass_runtime_variation() -> None:
    gate = build_history_gate(
        HistoryObservation(
            eta=1.0,
            eta_provenance_source="APPROXIMATED",
            eta_provenance_reason="FULLY_MEMORYFUL_COLD_START",
            eta_history_sample_count=0,
            queue_delay_history_sample_count=0,
            queue_delay_t_seconds=0.0,
            native_queue_duration_seconds=0.25,
            sampled_candidate_targets_present=True,
        ),
        require_observed_eta=True,
        require_eligible_queue_history=True,
        source_event_indices=(4,),
        runtime_identity={"backend": "fake"},
    )

    assert gate.status == "NOT_DEMONSTRATED"
    assert "scenario targets" in gate.reason
