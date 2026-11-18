"""Fail-closed six-system adapter registry for the Phase 5 Formal Campaign."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .phase5_six_system_runner import (
    SYSTEM_IDS,
    SixSystemRunObservation,
    SixSystemRunSpec,
)


class SystemAdapterRegistryError(RuntimeError):
    """Raised when a six-system adapter set is not executable as frozen."""


SystemExecutor = Callable[[SixSystemRunSpec], SixSystemRunObservation]


@dataclass(frozen=True, slots=True)
class SystemAdapterBinding:
    system_id: str
    implementation_revision: str
    executor: SystemExecutor
    implementation_status: str
    cpu_correctness_status: str
    native_compatibility_status: str
    algorithm_frozen: bool


def validate_system_adapter_registry(
    bindings: Sequence[SystemAdapterBinding],
) -> Mapping[str, SystemAdapterBinding]:
    """Validate the exact protocol-owned six-system implementation boundary."""

    if len(bindings) != len(SYSTEM_IDS):
        raise SystemAdapterRegistryError("registry must contain exactly six systems")
    by_id = {binding.system_id: binding for binding in bindings}
    if len(by_id) != len(bindings) or set(by_id) != set(SYSTEM_IDS):
        raise SystemAdapterRegistryError(
            "registry system identities differ from the frozen six systems"
        )
    for system_id in SYSTEM_IDS:
        binding = by_id[system_id]
        if not binding.implementation_revision:
            raise SystemAdapterRegistryError(
                f"{system_id} implementation revision is not frozen"
            )
        if binding.implementation_status != "READY":
            raise SystemAdapterRegistryError(
                f"{system_id} implementation is not READY"
            )
        if not binding.algorithm_frozen:
            raise SystemAdapterRegistryError(f"{system_id} algorithm is not frozen")
        if binding.cpu_correctness_status != "PASS":
            raise SystemAdapterRegistryError(
                f"{system_id} CPU correctness gate did not pass"
            )
        if binding.native_compatibility_status != "PASS":
            raise SystemAdapterRegistryError(
                f"{system_id} Native compatibility gate did not pass"
            )
    return by_id


def route_system_execution(
    registry: Mapping[str, SystemAdapterBinding],
    spec: SixSystemRunSpec,
) -> SixSystemRunObservation:
    """Route one frozen run without substituting another system implementation."""

    if set(registry) != set(SYSTEM_IDS):
        raise SystemAdapterRegistryError("execution registry is not the exact six-system set")
    binding = registry.get(spec.system_id)
    if binding is None:
        raise SystemAdapterRegistryError(f"missing adapter for {spec.system_id}")
    return binding.executor(spec)
