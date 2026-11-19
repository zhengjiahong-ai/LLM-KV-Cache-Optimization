from __future__ import annotations

from dataclasses import replace

import pytest

from kvopt.workload.phase5_six_system_runner import (
    SYSTEM_IDS,
    SixSystemRunObservation,
)
from kvopt.workload.phase5_system_adapters import (
    SystemAdapterBinding,
    SystemAdapterRegistryError,
    validate_system_adapter_registry,
)


def _executor(spec):
    return SixSystemRunObservation(
        run_id=spec.run_id,
        status="PASS",
        process_identity=f"process:{spec.run_id}",
        engine_identity=f"engine:{spec.run_id}",
        process_was_new=True,
        engine_was_new=True,
        empty_cache_preflight_passed=True,
        preheat_performed=False,
        retry_count=0,
        actual_enqueue_sequence_sha256=spec.expected_enqueue_sequence_sha256,
    )


def _bindings():
    return [
        SystemAdapterBinding(
            system_id=system_id,
            implementation_revision=f"revision:{system_id}",
            executor=_executor,
            implementation_status="READY",
            cpu_correctness_status="PASS",
            native_compatibility_status="PASS",
            algorithm_frozen=True,
        )
        for system_id in SYSTEM_IDS
    ]


def test_exact_six_system_adapter_registry_passes() -> None:
    assert set(validate_system_adapter_registry(_bindings())) == set(SYSTEM_IDS)


@pytest.mark.parametrize(
    ("system_id", "field", "value", "message"),
    [
        ("DVA_ER_V1", "cpu_correctness_status", "UNRESOLVED", "correctness"),
        (
            "CONTINUUM_OFFICIAL",
            "native_compatibility_status",
            "UNRESOLVED",
            "compatibility",
        ),
        ("A3_SUFFIX", "algorithm_frozen", False, "not frozen"),
        ("NATIVE", "implementation_status", "NOT_READY", "not READY"),
    ],
)
def test_unclosed_system_gate_fails_registry(
    system_id: str, field: str, value: object, message: str
) -> None:
    bindings = _bindings()
    index = next(
        index for index, binding in enumerate(bindings) if binding.system_id == system_id
    )
    bindings[index] = replace(bindings[index], **{field: value})
    with pytest.raises(SystemAdapterRegistryError, match=message):
        validate_system_adapter_registry(bindings)


def test_missing_or_duplicate_system_fails_registry() -> None:
    with pytest.raises(SystemAdapterRegistryError, match="exactly six"):
        validate_system_adapter_registry(_bindings()[:-1])
    bindings = _bindings()
    bindings[-1] = replace(bindings[-1], system_id="NATIVE")
    with pytest.raises(SystemAdapterRegistryError, match="identities"):
        validate_system_adapter_registry(bindings)


def test_provisional_dva_is_accepted_only_for_cpu_integration() -> None:
    bindings = _bindings()
    index = next(
        index
        for index, binding in enumerate(bindings)
        if binding.system_id == "DVA_ER_V1"
    )
    bindings[index] = replace(
        bindings[index],
        algorithm_frozen=False,
        native_compatibility_status="NOT_RUN",
    )
    assert set(
        validate_system_adapter_registry(
            bindings, require_formal_readiness=False
        )
    ) == set(SYSTEM_IDS)
    with pytest.raises(SystemAdapterRegistryError, match="not frozen"):
        validate_system_adapter_registry(bindings, require_formal_readiness=True)
