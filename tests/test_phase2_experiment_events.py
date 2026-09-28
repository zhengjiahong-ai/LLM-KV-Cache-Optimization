from __future__ import annotations

import pytest

from kvopt.continuum import (
    BlockIdentity,
    EligibilityPreparation,
    EligibilityTier,
    FakeClock,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramCompleted,
    PressureReleaseEffect,
    ProgramIdentity,
    ProgramStarted,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    RetentionEntryKey,
)
from kvopt.continuum.selection import BlockEligibilitySnapshot
from kvopt.continuum.runtime import build_runtime
from kvopt.profiling import (
    ExperimentEvent,
    ExperimentForcedReleaseObserver,
    ForcedReleaseCandidateSnapshot,
    ForcedReleaseDecisionSnapshot,
    InMemoryExperimentEventSink,
    experiment_event_from_lifecycle,
)


class _PrefillProvider:
    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        return 0.1, InputProvenance(
            InputSource.APPROXIMATED,
            "test profile",
        )


def test_experiment_event_payload_is_deeply_immutable() -> None:
    event = ExperimentEvent.create(
        event_type="TEST",
        timestamp=1.0,
        clock_domain="test",
        source="test",
        payload={
            "nested": {"value": 1},
            "sequence": [1, 2],
        },
    )

    assert event.payload.to_dict() == {
        "nested": {"value": 1},
        "sequence": [1, 2],
    }
    with pytest.raises(TypeError):
        event.payload["new"] = 3  # type: ignore[index]
    nested = event.payload["nested"]
    assert hasattr(nested, "__getitem__")
    with pytest.raises(TypeError):
        nested["value"] = 2  # type: ignore[index]


def test_runtime_mirrors_supported_lifecycle_without_changing_state() -> None:
    sink = InMemoryExperimentEventSink()
    clock = FakeClock()
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=_PrefillProvider(),
        default_ttl_seconds=1.0,
        experiment_event_sink=sink,
    )
    program = ProgramIdentity("program-a")
    request = RequestIdentity("request-a")

    runtime.handle(RequestArrived(program, request, 1.0))
    runtime.handle(RequestAdmitted(program, request, 1.5))

    events = sink.snapshot()
    assert tuple(event.event_type for event in events) == (
        "REQUEST_ARRIVED",
        "REQUEST_ADMITTED",
    )
    assert events[0].program_id == program
    assert events[0].request_id == request
    assert events[0].timestamp == 1.0
    assert events[0].clock_domain == "continuum_lifecycle"

    clock.set(1.5)
    candidate = runtime.scheduler_candidates((request,))[0]
    assert candidate.program_arrival_timestamp == 1.0
    assert candidate.request_arrival_timestamp == 1.0


def test_forced_release_observer_uses_common_experiment_sink() -> None:
    program = ProgramIdentity("program-a")
    prefix = PrefixIdentity("prefix-a")
    key = RetentionEntryKey(program, prefix)
    release = PressureReleaseEffect(key, (BlockIdentity(7),))
    preparation = EligibilityPreparation(
        required_blocks=1,
        original_free_queue=(
            BlockEligibilitySnapshot(
                block_id=BlockIdentity(7),
                native_lru_rank=0,
                has_block_hash=True,
                eligibility_tier=EligibilityTier.TIER_2,
            ),
        ),
        ordinary_expired_entries=(),
        pressure_releases=(release,),
        preparation_timestamp=2.0,
    )
    snapshot = ForcedReleaseDecisionSnapshot(
        preparation=preparation,
        candidates=(
            ForcedReleaseCandidateSnapshot(
                entry_key=key,
                retention_deadline_timestamp=5.0,
                waiting_followup=False,
                block_ids=(BlockIdentity(7),),
                initially_reclaimable_block_ids=(BlockIdentity(7),),
                next_tool_type="search",
                elapsed_since_ttl_decision_seconds=2.0,
                prefill_reload_seconds=0.2,
                eta=1.0,
                queue_delay_t_seconds=0.0,
            ),
        ),
    )
    sink = InMemoryExperimentEventSink()

    ExperimentForcedReleaseObserver(sink).observe(snapshot)

    events = sink.snapshot()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "FORCED_RELEASE_DECISION"
    assert event.timestamp == 2.0
    assert event.source == "continuum.forced_release"
    payload = event.payload.to_dict()
    assert payload["required_blocks"] == 1
    assert payload["candidates"][0]["program_id"] == "program-a"
    assert payload["selected_releases"][0]["newly_eligible_block_ids"] == [7]


def test_program_lifecycle_events_are_raw_observations() -> None:
    program = ProgramIdentity("program-a")
    started = experiment_event_from_lifecycle(ProgramStarted(program, 1.0))
    completed = experiment_event_from_lifecycle(ProgramCompleted(program, 2.0))
    assert started.event_type == "PROGRAM_STARTED"
    assert started.program_id == program
    assert started.timestamp == 1.0
    assert completed.event_type == "PROGRAM_COMPLETED"
    assert completed.timestamp == 2.0


def test_runtime_accepts_program_lifecycle_markers_without_state_change() -> None:
    sink = InMemoryExperimentEventSink()
    runtime = build_runtime(
        clock=FakeClock(),
        prefill_reload_provider=_PrefillProvider(),
        default_ttl_seconds=1.0,
        experiment_event_sink=sink,
    )
    program = ProgramIdentity("program-a")
    runtime.handle(ProgramStarted(program, 0.0))
    runtime.handle(ProgramCompleted(program, 1.0))
    assert tuple(event.event_type for event in sink.snapshot()) == (
        "PROGRAM_STARTED", "PROGRAM_COMPLETED"
    )
