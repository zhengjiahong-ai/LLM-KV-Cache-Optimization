from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_replay import (
    ArrivalMode,
    canonical_sha256,
    create_phase5_workload_seal,
    evaluate_event_driven_capacity,
    evaluate_native_enqueue_order,
    fixed_arrival_plan,
    frozen_poisson_arrival_plan,
    materialize_n_session_plan,
    validate_cross_arm_enqueue_equality,
    validate_phase5_workload_seal,
)


def _sessions(count: int = 4) -> dict[str, list[dict[str, object]]]:
    return {
        f"p{program}": [
            {
                "request_id": f"p{program}:turn:1",
                "turn_index": 1,
                "model_submit_monotonic_seconds": 10.0,
                "model_completion_monotonic_seconds": 11.0,
            },
            {
                "request_id": f"p{program}:turn:2",
                "turn_index": 2,
                "model_submit_monotonic_seconds": 13.0,
                "model_completion_monotonic_seconds": 14.0,
            },
        ]
        for program in range(1, count + 1)
    }


def _seal(count: int = 4) -> dict[str, object]:
    sessions = _sessions(count)
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.25)
    replay = materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)
    return create_phase5_workload_seal(
        workload_id="phase5-fixture",
        source={
            "kind": "CPU_FIXTURE",
            "revision": "fixture-v1",
            "license": "TEST_ONLY",
            "content_sha256": "10" * 32,
        },
        request_token_sha256={row: "20" * 32 for row in replay.expected_native_enqueue_order},
        replay_plan=replay,
    )


def _submission_events(order: list[str]) -> list[dict[str, object]]:
    return [
        {
            "event_index": index,
            "event_type": "VLLM_REQUEST_SUBMITTED",
            "request_id": request_id,
            "payload": {},
        }
        for index, request_id in enumerate(order, start=1)
    ]


def test_fixed_plan_supports_four_programs_and_preserves_turn_order() -> None:
    sessions = _sessions()
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.25)
    replay = materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)

    assert arrival.mode is ArrivalMode.FIXED
    assert len(replay.per_program_request_order) == 4
    assert replay.per_program_request_order["p2"] == ("p2:turn:1", "p2:turn:2")
    assert replay.expected_native_enqueue_order[:4] == (
        "p1:turn:1",
        "p2:turn:1",
        "p3:turn:1",
        "p4:turn:1",
    )


def test_frozen_poisson_plan_is_reproducible_and_seed_bound() -> None:
    programs = ("p1", "p2", "p3", "p4")
    first = frozen_poisson_arrival_plan(programs, rate_per_second=2.0, seed=17)
    second = frozen_poisson_arrival_plan(programs, rate_per_second=2.0, seed=17)
    different = frozen_poisson_arrival_plan(programs, rate_per_second=2.0, seed=18)

    assert first.to_dict() == second.to_dict()
    assert first.sha256 == second.sha256
    assert first.sha256 != different.sha256
    assert first.starts[0].start_offset_seconds == 0.0


def test_n_session_plan_rejects_program_set_and_turn_order_drift() -> None:
    sessions = _sessions()
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.25)
    missing = dict(sessions)
    missing.pop("p4")
    with pytest.raises(ValueError, match="program sets differ"):
        materialize_n_session_plan(sessions=missing, arrival_plan=arrival)

    invalid = deepcopy(sessions)
    invalid["p1"][1]["turn_index"] = 3
    with pytest.raises(ValueError, match="turn indexes"):
        materialize_n_session_plan(sessions=invalid, arrival_plan=arrival)


def test_n_session_plan_rejects_zero_duration_request() -> None:
    sessions = _sessions(2)
    sessions["p1"][0]["model_completion_monotonic_seconds"] = 10.0
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.25)
    with pytest.raises(ValueError, match="duration must be positive"):
        materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)


@pytest.mark.parametrize("program_count", [2, 4, 8, 16])
def test_event_driven_capacity_supports_requested_program_counts(
    program_count: int,
) -> None:
    sessions = _sessions(program_count)
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.0)
    replay = materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)
    report = evaluate_event_driven_capacity(
        replay, maximum_inflight_requests=program_count
    )
    assert report["status"] == "PASS"
    assert report["peak_planned_inflight_requests"] == program_count
    assert report["native_execution_claim"] == "NOT_EXECUTED_CPU_PLANNING_ONLY"


def test_event_driven_capacity_reports_overcommit_without_reordering() -> None:
    sessions = _sessions(4)
    replay = materialize_n_session_plan(
        sessions=sessions,
        arrival_plan=fixed_arrival_plan(tuple(sessions), stagger_seconds=0.0),
    )
    report = evaluate_event_driven_capacity(replay, maximum_inflight_requests=2)
    assert report["status"] == "CAPACITY_EXCEEDED"
    assert report["peak_planned_inflight_requests"] == 4
    assert report["over_capacity_events"]


def test_workload_seal_binds_tokens_timeline_and_non_authorization() -> None:
    seal = _seal()
    validate_phase5_workload_seal(seal)
    assert seal["execution_authorized"] is False
    assert seal["native_enqueue_order_sha256"] == canonical_sha256(
        seal["replay_plan"]["expected_native_enqueue_order"]
    )


def test_workload_seal_rejects_token_coverage_and_tampering() -> None:
    sessions = _sessions()
    arrival = fixed_arrival_plan(tuple(sessions), stagger_seconds=0.25)
    replay = materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)
    with pytest.raises(ValueError, match="token identity map"):
        create_phase5_workload_seal(
            workload_id="invalid",
            source={
                "kind": "FIXTURE",
                "revision": "v1",
                "license": "TEST_ONLY",
                "content_sha256": "10" * 32,
            },
            request_token_sha256={},
            replay_plan=replay,
        )

    seal = _seal()
    seal["workload_id"] = "tampered"
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_phase5_workload_seal(seal)


def test_actual_native_enqueue_gate_accepts_exact_sequence_and_pressure() -> None:
    seal = _seal()
    order = seal["replay_plan"]["expected_native_enqueue_order"]
    events = _submission_events(order)
    events.append(
        {
            "event_index": 999,
            "event_type": "VLLM_REQUEST_SUBMITTED",
            "request_id": "pressure:stage:1",
            "payload": {},
        }
    )
    report = evaluate_native_enqueue_order(seal=seal, events=events)
    assert report["status"] == "PASS"
    assert report["exact_sequence_match"] is True
    assert report["per_program_order_valid"] is True


def test_actual_native_enqueue_gate_fails_on_global_or_program_order_drift() -> None:
    seal = _seal()
    order = list(seal["replay_plan"]["expected_native_enqueue_order"])
    order[0], order[-1] = order[-1], order[0]
    report = evaluate_native_enqueue_order(
        seal=seal, events=_submission_events(order)
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["exact_sequence_match"] is False
    assert report["per_program_order_valid"] is False


def test_actual_native_enqueue_gate_fails_on_unknown_native_observation() -> None:
    seal = _seal()
    order = list(seal["replay_plan"]["expected_native_enqueue_order"])
    events = _submission_events(order + ["unknown:turn:1"])
    report = evaluate_native_enqueue_order(seal=seal, events=events)
    assert report["status"] == "FAIL_CLOSED"
    assert report["unknown_nonpressure_request_ids"] == ["unknown:turn:1"]


def test_cross_arm_gate_requires_each_arm_pass_and_same_sequence() -> None:
    seal = _seal()
    order = list(seal["replay_plan"]["expected_native_enqueue_order"])
    report = evaluate_native_enqueue_order(seal=seal, events=_submission_events(order))
    arms = ("A0", "A1", "A3")
    passed = validate_cross_arm_enqueue_equality(
        {arm: report for arm in arms}, required_arms=arms
    )
    assert passed["status"] == "PASS"

    failed_report = dict(report)
    failed_report["status"] = "FAIL_CLOSED"
    failed = validate_cross_arm_enqueue_equality(
        {"A0": report, "A1": failed_report, "A3": report}, required_arms=arms
    )
    assert failed["status"] == "FAIL_CLOSED"

