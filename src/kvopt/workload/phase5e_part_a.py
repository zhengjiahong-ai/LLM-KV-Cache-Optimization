"""Bounded Phase 5E Part A controller and independent pre-archive gates."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Protocol

from .phase2b_fidelity_runner import RequestCompletion, RequestHandle
from .phase5_asyncllm_adapter import AsyncLLMRequestSpec
from .phase5_gpu_conformance import Phase5GPUConformancePlan
from .phase5_native_async import PressureExecutionEvidence
from .phase5e_a3_retention import evaluate_p5e_g9


class Phase5EG9GateFailure(RuntimeError):
    """G9 rejected the bound A3 input before Native Pressure execution."""

    def __init__(self, report: Mapping[str, object]) -> None:
        super().__init__(str(report.get("failure_reason", "P5E-G9 failed closed")))
        self.report = dict(report)


class PartAAdapter(Protocol):
    async def submit(self, spec: AsyncLLMRequestSpec) -> RequestHandle: ...

    async def collect_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> tuple[RequestCompletion, ...]: ...

    async def execute_native_pressure(
        self,
        request: object,
        *,
        expected_inflight_request_ids: tuple[str, ...],
    ) -> PressureExecutionEvidence: ...

    async def arm_native_pressure(
        self,
        request: object,
        *,
        expected_inflight_request_ids: tuple[str, ...],
    ) -> None: ...

    async def shutdown(
        self,
        *,
        require_native_confirmation: bool = True,
        require_frontend_observability: bool = False,
    ) -> None: ...

    def report(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class PartARequestInput:
    logical_request_id: str
    prompt: object
    sampling_params: object


@dataclass(frozen=True, slots=True)
class PartAControllerResult:
    status: str
    run_id: str
    controller_submission_order: tuple[str, ...]
    completion_order: tuple[str, ...]
    peak_controller_inflight: int
    pressure: PressureExecutionEvidence
    adapter_report: Mapping[str, object]
    gates: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5e.part_a_controller.v1",
            "status": self.status,
            "run_id": self.run_id,
            "controller_submission_order": list(self.controller_submission_order),
            "completion_order": list(self.completion_order),
            "peak_controller_inflight": self.peak_controller_inflight,
            "pressure": asdict(self.pressure),
            "adapter_report": dict(self.adapter_report),
            "gates": dict(self.gates),
        }


def _event_rows(report: Mapping[str, object], kind: str) -> list[Mapping[str, object]]:
    events = report.get("events")
    if not isinstance(events, list):
        raise TypeError("Adapter report lacks lifecycle events")
    rows = [row for row in events if isinstance(row, Mapping) and row.get("kind") == kind]
    return sorted(rows, key=lambda row: int(row.get("index", -1)))


def evaluate_part_a_prearchive_gates(
    *,
    plan: Phase5GPUConformancePlan,
    run_id: str,
    controller_submission_order: tuple[str, ...],
    peak_controller_inflight: int,
    pressure: PressureExecutionEvidence,
    adapter_report: Mapping[str, object],
    candidate_exposure_report: Mapping[str, object],
    g9_report: Mapping[str, object],
) -> dict[str, object]:
    """Independently evaluate G1-G7 and G9; G0/G8 remain external gates."""

    expected = plan.frozen_native_enqueue_order
    dispatches = _event_rows(adapter_report, "ADAPTER_DISPATCH_STARTED")
    native_submissions = _event_rows(adapter_report, "NATIVE_SUBMISSION_OBSERVED")
    native_terminals = _event_rows(adapter_report, "NATIVE_TERMINAL_CONFIRMED")
    dispatch_order = tuple(str(row.get("request_id")) for row in dispatches)
    native_order = tuple(str(row.get("request_id")) for row in native_submissions)
    terminals = {
        str(row.get("request_id")): row for row in native_terminals
    }
    if len(terminals) != len(native_terminals):
        raise ValueError("Native terminal evidence contains duplicate request IDs")
    request_rows = adapter_report.get("requests")
    if not isinstance(request_rows, list):
        raise TypeError("Adapter report lacks request lifecycle rows")
    lifecycle_valid = len(request_rows) == 8 and all(
        isinstance(row, Mapping)
        and row.get("output_processor_terminal") is True
        and row.get("native_terminal_confirmed") is True
        and row.get("native_terminal_kind") == "NATURAL_CORE_TERMINAL"
        and row.get("abort_dispatched") is False
        and row.get("failure_reason") is None
        for row in request_rows
    )
    second_wave = plan.pressure.expected_inflight_request_ids
    second_submissions = [
        row for row in native_submissions if row.get("request_id") in set(second_wave)
    ]
    first_wave = expected[:4]
    first_terminals = [terminals[row] for row in first_wave if row in terminals]
    r1_natural_completion_barrier = (
        len(first_terminals) == len(first_wave)
        and len(second_submissions) == len(second_wave)
        and max(int(row["index"]) for row in first_terminals)
        < min(int(row["index"]) for row in second_submissions)
    )
    second_terminals = [terminals[row] for row in second_wave if row in terminals]
    overlap = (
        len(second_submissions) == len(second_wave)
        and len(second_terminals) == len(second_wave)
        and int(second_submissions[-1]["index"])
        < min(int(row["index"]) for row in second_terminals)
    )
    pressure_valid = (
        pressure.boundary_id == plan.pressure.boundary_id
        and pressure.inflight_request_ids == second_wave
        and pressure.pressure_token_ids_sha256
        == plan.pressure.pressure_prompt_token_ids_sha256
        and pressure.required_blocks == plan.pressure.required_blocks
        and pressure.engine_core_identity_verified is True
        and pressure.free_blocks_before == pressure.free_blocks_after_release
        and bool(pressure.forced_release_decision_ids)
        and bool(pressure.native_evicted_block_ids)
        and pressure.allocation_watermark_source
        == "PINNED_KV_CACHE_MANAGER_REQUEST_BLOCK_TABLE"
        and pressure.observed_allocated_blocks_by_request
        == plan.pressure.expected_allocated_blocks_by_request
    )
    exposure_valid = (
        candidate_exposure_report.get("status") == "PASS"
        and candidate_exposure_report.get("downstream_recompute_attribution")
        == "NOT_ESTABLISHED"
    )
    cleanup_valid = (
        adapter_report.get("state") == "CLOSED"
        and adapter_report.get("request_state_observability") == "OBSERVABLE"
        and adapter_report.get("active_submit_count") == 0
        and adapter_report.get("fatal_error") is None
        and all(
            isinstance(row, Mapping) and row.get("collector_task_done") is True
            for row in request_rows
        )
    )
    gates = {
        "P5E-G0": {"status": "EXTERNAL_FREEZE_GATE_REQUIRED"},
        "P5E-G1": {
            "status": "PASS"
            if controller_submission_order == expected
            and dispatch_order == expected
            and r1_natural_completion_barrier
            else "FAIL_CLOSED",
            "expected": list(expected),
            "controller": list(controller_submission_order),
            "dispatch": list(dispatch_order),
            "r1_natural_completion_barrier": r1_natural_completion_barrier,
        },
        "P5E-G2": {
            "status": "PASS" if native_order == expected else "FAIL_CLOSED",
            "actual": list(native_order),
        },
        "P5E-G3": {
            "status": "PASS"
            if peak_controller_inflight >= 2 and overlap
            else "FAIL_CLOSED",
            "peak_controller_inflight": peak_controller_inflight,
            "native_lifecycle_overlap": overlap,
            "gpu_kernel_overlap_claim": "NOT_CLAIMED",
        },
        "P5E-G4": {"status": "PASS" if lifecycle_valid else "FAIL_CLOSED"},
        "P5E-G5": {"status": "PASS" if pressure_valid else "FAIL_CLOSED"},
        "P5E-G6": {
            "status": "PASS" if exposure_valid else "FAIL_CLOSED",
            "algorithmic_benefit_claim": "NOT_ESTABLISHED",
        },
        "P5E-G7": {"status": "PASS" if cleanup_valid else "FAIL_CLOSED"},
        "P5E-G8": {"status": "EXTERNAL_ARCHIVE_GATE_REQUIRED"},
        "P5E-G9": dict(g9_report),
    }
    internal = [gates[f"P5E-G{index}"]["status"] for index in range(1, 8)] + [
        gates["P5E-G9"]["status"]
    ]
    return {
        "schema_version": "phase5e.part_a_prearchive_gates.v1",
        "run_id": run_id,
        "status": "PASS" if all(row == "PASS" for row in internal) else "FAIL_CLOSED",
        "gates": gates,
    }


async def execute_phase5e_part_a(
    *,
    plan: Phase5GPUConformancePlan,
    run_id: str,
    requests: Mapping[str, PartARequestInput],
    adapter: PartAAdapter,
    candidate_exposure_evaluator: Callable[[], Mapping[str, object]],
    retention_input_manifest_provider: Callable[[], Mapping[str, object]],
    run_epoch_monotonic: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> PartAControllerResult:
    """Execute the frozen two-wave Part A sequence exactly once."""

    expected = plan.frozen_native_enqueue_order
    if set(requests) != set(expected):
        raise ValueError("Part A request inputs differ from frozen request set")
    if not math.isfinite(run_epoch_monotonic) or run_epoch_monotonic < 0:
        raise ValueError("run epoch must be finite and non-negative")
    offsets = {
        request_id: program.arrival_offsets_seconds[index]
        for program in plan.programs
        for index, request_id in enumerate(program.request_ids)
    }
    submitted: list[str] = []
    completed: list[str] = []
    inflight: set[str] = set()
    peak = 0

    async def dispatch(request_id: str) -> None:
        target = run_epoch_monotonic + offsets[request_id]
        delay = target - monotonic()
        if delay > 0:
            await sleep(delay)
        row = requests[request_id]
        if row.logical_request_id != request_id:
            raise ValueError("Part A request input changed logical identity")
        handle = await adapter.submit(
            AsyncLLMRequestSpec(
                logical_request_id=request_id,
                external_request_id=f"{run_id}:{request_id}",
                prompt=row.prompt,
                params=row.sampling_params,
                planned_arrival_offset_seconds=offsets[request_id],
            )
        )
        if handle.logical_request_id != request_id:
            raise RuntimeError("Adapter changed logical request identity")
        submitted.append(request_id)
        inflight.add(request_id)

    async def collect_wave(wave: tuple[str, ...]) -> None:
        remaining = set(wave)
        while remaining:
            rows = await adapter.collect_completed(
                timeout_seconds=float(plan.resource_budget.run_timeout_seconds),
                wait_for_one=True,
            )
            if not rows:
                raise TimeoutError("Part A Native completion wait timed out")
            for row in rows:
                request_id = row.logical_request_id
                if request_id not in remaining or row.status != "success":
                    raise RuntimeError("Part A received invalid or duplicate completion")
                remaining.remove(request_id)
                inflight.remove(request_id)
                completed.append(request_id)

    first_wave = expected[:4]
    second_wave = expected[4:]
    for request_id in first_wave:
        await dispatch(request_id)
        peak = max(peak, len(inflight))
    await collect_wave(first_wave)
    g9_value = retention_input_manifest_provider()
    if inspect.isawaitable(g9_value):
        g9_value = await g9_value
    g9 = evaluate_p5e_g9(g9_value)
    if g9["status"] != "PASS":
        raise Phase5EG9GateFailure(g9)
    pressure_request = plan.pressure.to_native_allocation_request(
        plan.resource_budget.block_size_tokens
    )
    arm_pressure = getattr(adapter, "arm_native_pressure", None)
    if callable(arm_pressure):
        await arm_pressure(
            pressure_request,
            expected_inflight_request_ids=second_wave,
        )
    for request_id in second_wave:
        await dispatch(request_id)
        peak = max(peak, len(inflight))
    pressure = await adapter.execute_native_pressure(
        pressure_request,
        expected_inflight_request_ids=second_wave,
    )
    await collect_wave(second_wave)
    await adapter.shutdown(
        require_native_confirmation=True,
        require_frontend_observability=True,
    )
    adapter_report = adapter.report()
    exposure = candidate_exposure_evaluator()
    if inspect.isawaitable(exposure):
        exposure = await exposure
    gates = evaluate_part_a_prearchive_gates(
        plan=plan,
        run_id=run_id,
        controller_submission_order=tuple(submitted),
        peak_controller_inflight=peak,
        pressure=pressure,
        adapter_report=adapter_report,
        candidate_exposure_report=exposure,
        g9_report=g9,
    )
    return PartAControllerResult(
        status=str(gates["status"]),
        run_id=run_id,
        controller_submission_order=tuple(submitted),
        completion_order=tuple(completed),
        peak_controller_inflight=peak,
        pressure=pressure,
        adapter_report=adapter_report,
        gates=gates,
    )
