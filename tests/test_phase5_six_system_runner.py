from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from kvopt.workload.phase5_six_system_runner import (
    SYSTEM_IDS,
    SixSystemRunnerError,
    SixSystemRunObservation,
    SixSystemRunSpec,
    run_six_system_cell,
    validate_six_system_specs,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _specs() -> list[SixSystemRunSpec]:
    order = (
        "CONTINUUM_ADAPTED",
        "A1_ORIGINAL",
        "NATIVE",
        "DVA_ER_V1",
        "CONTINUUM_OFFICIAL",
        "A3_SUFFIX",
    )
    return [
        SixSystemRunSpec(
            run_id=f"g01-r0-{system.lower()}",
            group_id="g01",
            stratum="SWE_BENCH",
            repeat_index=0,
            system_id=system,
            execution_position=position,
            workload_seal_sha256=_digest("workload"),
            arrival_realization_sha256=_digest("arrival"),
            expected_enqueue_sequence_sha256=_digest("enqueue"),
        )
        for position, system in enumerate(order)
    ]


def _observation(spec: SixSystemRunSpec) -> SixSystemRunObservation:
    return SixSystemRunObservation(
        run_id=spec.run_id,
        status="PASS",
        process_identity=f"process-{spec.run_id}",
        engine_identity=f"engine-{spec.run_id}",
        process_was_new=True,
        engine_was_new=True,
        empty_cache_preflight_passed=True,
        preheat_performed=False,
        retry_count=0,
        actual_enqueue_sequence_sha256=spec.expected_enqueue_sequence_sha256,
    )


def test_six_system_cell_passes_with_fresh_isolated_runs() -> None:
    calls: list[str] = []

    def executor(spec: SixSystemRunSpec) -> SixSystemRunObservation:
        calls.append(spec.system_id)
        return _observation(spec)

    result = run_six_system_cell(_specs(), executor=executor)
    assert result.status == "PASS"
    assert len(result.observations) == 6
    assert calls == [
        spec.system_id for spec in sorted(_specs(), key=lambda row: row.execution_position)
    ]


def test_exact_six_system_set_is_required() -> None:
    specs = _specs()[:-1]
    with pytest.raises(SixSystemRunnerError, match="exactly six"):
        validate_six_system_specs(specs)
    specs = _specs()
    specs[-1] = replace(specs[-1], system_id="NATIVE")
    with pytest.raises(SixSystemRunnerError, match="system set"):
        validate_six_system_specs(specs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("process_was_new", False, "fresh process"),
        ("engine_was_new", False, "fresh EngineCore"),
        ("empty_cache_preflight_passed", False, "empty-cache"),
        ("preheat_performed", True, "preheat"),
        ("retry_count", 1, "retry"),
        ("actual_enqueue_sequence_sha256", None, "not observable"),
        ("actual_enqueue_sequence_sha256", "0" * 64, "order mismatch"),
    ],
)
def test_execution_contract_fails_closed(field: str, value, message: str) -> None:
    def executor(spec: SixSystemRunSpec) -> SixSystemRunObservation:
        observation = _observation(spec)
        if spec.execution_position == 0:
            return replace(observation, **{field: value})
        return observation

    result = run_six_system_cell(_specs(), executor=executor)
    assert result.status == "FAIL_CLOSED"
    assert message in (result.failure_reason or "")
    assert len(result.observations) == 1


def test_failure_is_not_retried_and_stops_remaining_arms() -> None:
    calls = 0

    def executor(spec: SixSystemRunSpec) -> SixSystemRunObservation:
        nonlocal calls
        calls += 1
        return replace(
            _observation(spec), status="FAIL_CLOSED", failure_reason="native failure"
        )

    result = run_six_system_cell(_specs(), executor=executor)
    assert result.status == "FAIL_CLOSED"
    assert result.failure_reason == "native failure"
    assert calls == 1


def test_duplicate_process_or_engine_identity_fails_isolation() -> None:
    first_process = "shared-process"
    first_engine = "shared-engine"

    def executor(spec: SixSystemRunSpec) -> SixSystemRunObservation:
        observation = _observation(spec)
        if spec.execution_position < 2:
            return replace(
                observation,
                process_identity=first_process,
                engine_identity=first_engine,
            )
        return observation

    result = run_six_system_cell(_specs(), executor=executor)
    assert result.status == "FAIL_CLOSED"
    assert len(result.observations) == 2


def test_same_workload_and_arrival_are_required_across_arms() -> None:
    specs = _specs()
    specs[2] = replace(specs[2], arrival_realization_sha256=_digest("other"))
    with pytest.raises(SixSystemRunnerError, match="share one workload"):
        validate_six_system_specs(specs)


def test_runner_defines_no_policy_implementation() -> None:
    assert set(SYSTEM_IDS) == {
        "NATIVE",
        "CONTINUUM_OFFICIAL",
        "CONTINUUM_ADAPTED",
        "A1_ORIGINAL",
        "A3_SUFFIX",
        "DVA_ER_V1",
    }
