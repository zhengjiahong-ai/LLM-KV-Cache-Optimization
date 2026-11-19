"""CPU/Mock execution contract for the Phase 5 six-system campaign.

This module does not implement any policy or launch GPU work.  It verifies that
an injected executor obeys the frozen per-cell isolation and identity contract.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

SYSTEM_IDS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)


class SixSystemRunnerError(RuntimeError):
    """Raised when execution violates the frozen six-system contract."""


@dataclass(frozen=True)
class SixSystemRunSpec:
    run_id: str
    group_id: str
    stratum: str
    repeat_index: int
    system_id: str
    execution_position: int
    workload_seal_sha256: str
    arrival_realization_sha256: str
    expected_enqueue_sequence_sha256: str


@dataclass(frozen=True)
class SixSystemRunObservation:
    run_id: str
    status: str
    process_identity: str
    engine_identity: str
    process_was_new: bool
    engine_was_new: bool
    empty_cache_preflight_passed: bool
    preheat_performed: bool
    retry_count: int
    actual_enqueue_sequence_sha256: str | None
    failure_reason: str | None = None


@dataclass(frozen=True)
class SixSystemCellResult:
    status: str
    observations: tuple[SixSystemRunObservation, ...]
    failure_reason: str | None


Executor = Callable[[SixSystemRunSpec], SixSystemRunObservation]


def validate_six_system_specs(specs: Sequence[SixSystemRunSpec]) -> None:
    if len(specs) != len(SYSTEM_IDS):
        raise SixSystemRunnerError("cell must contain exactly six systems")
    if len({spec.run_id for spec in specs}) != len(specs):
        raise SixSystemRunnerError("run_id must be unique within the cell")
    observed_systems = {spec.system_id for spec in specs}
    if observed_systems != set(SYSTEM_IDS):
        raise SixSystemRunnerError("cell system set differs from the frozen six systems")
    if {spec.execution_position for spec in specs} != set(range(len(SYSTEM_IDS))):
        raise SixSystemRunnerError("execution positions must be exactly 0..5")
    shared_identity = {
        (
            spec.group_id,
            spec.stratum,
            spec.repeat_index,
            spec.workload_seal_sha256,
            spec.arrival_realization_sha256,
            spec.expected_enqueue_sequence_sha256,
        )
        for spec in specs
    }
    if len(shared_identity) != 1:
        raise SixSystemRunnerError(
            "six systems must share one workload, arrival and enqueue realization"
        )


def run_six_system_cell(
    specs: Sequence[SixSystemRunSpec], *, executor: Executor
) -> SixSystemCellResult:
    """Execute one paired cell once per arm and fail closed without retries."""

    validate_six_system_specs(specs)
    observations: list[SixSystemRunObservation] = []
    process_ids: set[str] = set()
    engine_ids: set[str] = set()
    for spec in sorted(specs, key=lambda row: row.execution_position):
        try:
            observation = executor(spec)
        except Exception as error:  # noqa: BLE001 - executor failures must fail closed
            return SixSystemCellResult(
                status="FAIL_CLOSED",
                observations=tuple(observations),
                failure_reason=f"executor failure for {spec.run_id}: {error}",
            )
        observations.append(observation)
        failure = _observation_failure(
            spec, observation, process_ids=process_ids, engine_ids=engine_ids
        )
        if failure is not None:
            return SixSystemCellResult(
                status="FAIL_CLOSED",
                observations=tuple(observations),
                failure_reason=failure,
            )
        process_ids.add(observation.process_identity)
        engine_ids.add(observation.engine_identity)
    return SixSystemCellResult(
        status="PASS", observations=tuple(observations), failure_reason=None
    )


def _observation_failure(
    spec: SixSystemRunSpec,
    observation: SixSystemRunObservation,
    *,
    process_ids: set[str],
    engine_ids: set[str],
) -> str | None:
    if observation.run_id != spec.run_id:
        return f"run identity mismatch for {spec.run_id}"
    if observation.status != "PASS":
        return observation.failure_reason or f"run failed: {spec.run_id}"
    if observation.retry_count != 0:
        return f"automatic retry is prohibited: {spec.run_id}"
    if not observation.process_was_new or observation.process_identity in process_ids:
        return f"fresh process isolation failed: {spec.run_id}"
    if not observation.engine_was_new or observation.engine_identity in engine_ids:
        return f"fresh EngineCore isolation failed: {spec.run_id}"
    if not observation.empty_cache_preflight_passed:
        return f"empty-cache preflight failed: {spec.run_id}"
    if observation.preheat_performed:
        return f"preheat is prohibited: {spec.run_id}"
    if observation.actual_enqueue_sequence_sha256 is None:
        return f"actual enqueue order is not observable: {spec.run_id}"
    if (
        observation.actual_enqueue_sequence_sha256
        != spec.expected_enqueue_sequence_sha256
    ):
        return f"actual enqueue order mismatch: {spec.run_id}"
    return None

