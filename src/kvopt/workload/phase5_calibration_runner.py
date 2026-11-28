"""Shared trace-driven controller for one frozen SWE Calibration run.

This module owns no GPU and starts no process on import.  The production CLI
injects the pinned AsyncLLM adapter and EngineCore control channel; CPU tests
exercise the identical ordering, terminal and timer contract.
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .phase2b_fidelity_runner import RequestCompletion, RequestHandle
from .phase5_asyncllm_adapter import (
    AsyncLLMNativeAdapter,
    AsyncLLMProtocol,
    AsyncLLMRequestSpec,
)
from .phase5_calibration_controller import (
    arm_followup_after_terminal,
    remaining_followup_delay,
)
from .phase5_replay import canonical_sha256
from .phase5_system_runtime import validate_no_policy_fallback
from .phase5e_engine_core_bridge import (
    EngineCoreRemoteEvidenceSource,
    EngineCoreUtilityBridge,
    resolve_async_utility_client,
)


class CalibrationRunnerError(RuntimeError):
    """One run violated its frozen replay or Native lifecycle contract."""


class CalibrationAdapter(Protocol):
    async def submit(self, spec: AsyncLLMRequestSpec) -> RequestHandle: ...

    async def collect_completed(
        self, *, timeout_seconds: float, wait_for_one: bool
    ) -> Sequence[RequestCompletion]: ...

    async def shutdown(
        self,
        *,
        require_native_confirmation: bool = True,
        require_frontend_observability: bool = False,
    ) -> None: ...

    def report(self) -> Mapping[str, object]: ...


TimerSink = Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]


@dataclass(frozen=True, slots=True)
class InstalledCalibrationRuntime:
    adapter: AsyncLLMNativeAdapter
    evidence: EngineCoreRemoteEvidenceSource
    bridge: EngineCoreUtilityBridge
    installation_report: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class InstalledOfficialRuntime:
    adapter: AsyncLLMNativeAdapter
    client: object
    installation_report: Mapping[str, object]

    async def export_evidence(self) -> Mapping[str, object]:
        method = getattr(self.client, "call_utility_async", None)
        if not callable(method):
            raise CalibrationRunnerError("Official Utility RPC is unavailable")
        value = await method("kvopt_phase5_official_evidence")
        if not isinstance(value, Mapping):
            raise CalibrationRunnerError("Official evidence export is malformed")
        return dict(value)


async def install_project_calibration_runtime(
    *,
    engine: AsyncLLMProtocol,
    run_contract: Mapping[str, object],
    run_epoch_monotonic: float,
    clock: Callable[[], float],
) -> InstalledCalibrationRuntime:
    """Install one of the five project/pinned-vLLM arms in EngineCore."""

    system_id = str(run_contract.get("system_id"))
    if system_id == "CONTINUUM_OFFICIAL":
        raise CalibrationRunnerError("Official Continuum requires its independent runtime")
    request_rows = run_contract.get("request_inputs")
    expected = run_contract.get("expected_native_enqueue_order")
    if not isinstance(request_rows, list) or not isinstance(expected, list):
        raise CalibrationRunnerError("run contract lacks request inputs")
    program_rows: dict[str, Mapping[str, object]] = {}
    for row in request_rows:
        if not isinstance(row, Mapping):
            raise CalibrationRunnerError("run request lineage is malformed")
        program_id = str(row.get("program_id"))
        prior = program_rows.setdefault(program_id, row)
        if (
            prior.get("session_id") != row.get("session_id")
            or prior.get("source_trace_sha256") != row.get("source_trace_sha256")
        ):
            raise CalibrationRunnerError("Program lineage changes within one run")
    adapter = AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version="0.27.1",
        run_epoch_monotonic=run_epoch_monotonic,
        clock=clock,
    )
    bridge = EngineCoreUtilityBridge(resolve_async_utility_client(engine))
    evidence = await bridge.install(
        {
            "schema_version": "phase5.calibration_engine_core_install.v1",
            "run_id": run_contract["run_id"],
            "system_id": system_id,
            "policy_id": run_contract["policy_id"],
            "native_execution_architecture": "ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
            "request_identity_prefix": f"{run_contract['run_id']}:",
            "kv_pool_blocks": 2048,
            "reserved_null_blocks": 1,
            "expected_initial_free_blocks": 2047,
            "all_logical_request_ids": expected,
            "first_wave_logical_request_ids": [],
            "group_id": run_contract["group_id"],
            "session_by_program": {
                program_id: row["session_id"]
                for program_id, row in program_rows.items()
            },
            "trace_sha256_by_program": {
                program_id: row["source_trace_sha256"]
                for program_id, row in program_rows.items()
            },
        }
    )
    report = evidence.runtime_installation_report()
    validate_no_policy_fallback(
        requested_system_id=system_id,
        installed_system_id=str(report.get("system_id")),
        installed_policy_id=str(report.get("policy_id")),
    )
    if (
        report.get("control_transport") != "ASYNCMPLCLIENT_UTILITY_RPC"
        or report.get("native_objects_cross_process") is not False
    ):
        raise CalibrationRunnerError("EngineCore ownership contract differs")
    return InstalledCalibrationRuntime(adapter, evidence, bridge, report)


def project_timer_sink(runtime: InstalledCalibrationRuntime) -> TimerSink:
    async def sink(payload: Mapping[str, object]) -> Mapping[str, object]:
        return await runtime.bridge.controller_event(
            "CONTROLLER_ARM_TIMER", payload
        )

    return sink


async def install_official_calibration_runtime(
    *,
    engine: AsyncLLMProtocol,
    run_contract: Mapping[str, object],
    run_epoch_monotonic: float,
    clock: Callable[[], float],
) -> InstalledOfficialRuntime:
    """Install the observation-only plugin in the frozen Official runtime."""

    if (
        run_contract.get("system_id") != "CONTINUUM_OFFICIAL"
        or run_contract.get("policy_id") != "CONTINUUM_OFFICIAL_316A5879"
    ):
        raise CalibrationRunnerError("Official Continuum identity differs")
    adapter = AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version="0.27.1",
        run_epoch_monotonic=run_epoch_monotonic,
        clock=clock,
    )
    client = resolve_async_utility_client(engine)
    value = await client.call_utility_async(
        "kvopt_phase5_official_install",
        {
            "schema_version": "phase5.official_continuum_install.v1",
            "run_id": run_contract["run_id"],
            "system_id": "CONTINUUM_OFFICIAL",
            "policy_id": "CONTINUUM_OFFICIAL_316A5879",
            "source_revision": "316a58794a6ff86b216e579b74fd56ed0c5a911f",
            "request_identity_prefix": f"{run_contract['run_id']}:",
        },
    )
    if not isinstance(value, Mapping) or not isinstance(
        value.get("installation_report"), Mapping
    ):
        raise CalibrationRunnerError("Official installation result is malformed")
    report = dict(value["installation_report"])
    validate_no_policy_fallback(
        requested_system_id="CONTINUUM_OFFICIAL",
        installed_system_id=str(report.get("system_id")),
        installed_policy_id=str(report.get("policy_id")),
    )
    if (
        report.get("status") != "PASS"
        or report.get("observation_only") is not True
        or report.get("control_transport") != "ASYNCMPLCLIENT_UTILITY_RPC"
        or report.get("native_objects_cross_process") is not False
    ):
        raise CalibrationRunnerError("Official runtime ownership contract differs")
    return InstalledOfficialRuntime(adapter, client, report)


def official_timer_sink() -> TimerSink:
    async def sink(_payload: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "status": "PASS",
            "recording_scope": "FRONTEND_WORKLOAD_CONTROL_ONLY",
            "policy_input": False,
        }

    return sink


@dataclass(frozen=True, slots=True)
class CalibrationRequestInput:
    logical_request_id: str
    prompt_token_ids: tuple[int, ...]
    sampling_params: object
    logical_arrival_seconds: float
    program_id: str
    session_id: str
    predecessor_request_id: str | None = None


def build_calibration_request_inputs(
    *, run_contract: Mapping[str, object], sampling_params: object
) -> dict[str, CalibrationRequestInput]:
    """Convert a validated run contract into exact controller inputs."""

    rows = run_contract.get("request_inputs")
    arrivals = run_contract.get("logical_arrival_seconds_by_request")
    timers = run_contract.get("controller_timers")
    expected = run_contract.get("expected_native_enqueue_order")
    if not all(isinstance(value, (list, dict)) for value in (rows, arrivals, timers, expected)):
        raise CalibrationRunnerError("run contract replay inputs are malformed")
    assert isinstance(rows, list)
    assert isinstance(arrivals, dict)
    assert isinstance(timers, list)
    assert isinstance(expected, list)
    predecessor_by_successor: dict[str, str] = {}
    for timer in timers:
        if not isinstance(timer, Mapping):
            raise CalibrationRunnerError("controller timer row is malformed")
        predecessor = timer.get("predecessor_request_id")
        successor = timer.get("successor_request_id")
        if (
            not isinstance(predecessor, str)
            or not isinstance(successor, str)
            or successor in predecessor_by_successor
        ):
            raise CalibrationRunnerError("controller timer lineage is invalid")
        predecessor_by_successor[successor] = predecessor
    by_id = {
        str(row.get("request_id")): row for row in rows if isinstance(row, Mapping)
    }
    if set(by_id) != set(expected) or set(arrivals) != set(expected):
        raise CalibrationRunnerError("run contract request set differs")
    result = {}
    for request_id in expected:
        row = by_id[request_id]
        token_ids = row.get("token_ids")
        if not isinstance(token_ids, list) or not token_ids:
            raise CalibrationRunnerError("request Prompt Token IDs are missing")
        result[request_id] = CalibrationRequestInput(
            logical_request_id=request_id,
            prompt_token_ids=tuple(token_ids),
            sampling_params=sampling_params,
            logical_arrival_seconds=float(arrivals[request_id]),
            program_id=str(row.get("program_id")),
            session_id=str(row.get("session_id")),
            predecessor_request_id=predecessor_by_successor.get(request_id),
        )
    return result


def create_calibration_asyncllm(run_contract: Mapping[str, object]) -> AsyncLLMProtocol:
    """Create the frozen 1.5B engine synchronously before the asyncio loop."""

    if os.environ.get("VLLM_ENABLE_V1_MULTIPROCESSING") != "0":
        raise CalibrationRunnerError("VLLM_ENABLE_V1_MULTIPROCESSING=0 is required")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise CalibrationRunnerError("AsyncLLM must be created before asyncio.run")
    import vllm  # type: ignore[import-not-found]
    from vllm.engine.arg_utils import AsyncEngineArgs  # type: ignore[import-not-found]
    from vllm.v1.engine.async_llm import AsyncLLM  # type: ignore[import-not-found]

    if vllm.__version__ != "0.27.1":
        raise CalibrationRunnerError("Calibration vLLM version differs")
    model = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    revision = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
    engine_args = AsyncEngineArgs(
        model=model,
        tokenizer=model,
        revision=revision,
        tokenizer_revision=revision,
        max_model_len=32768,
        max_num_seqs=4,
        max_num_batched_tokens=8192,
        block_size=16,
        num_gpu_blocks_override=2048,
        enable_prefix_caching=True,
        disable_log_stats=False,
    )
    engine = AsyncLLM.from_engine_args(engine_args, start_engine_loop=False)
    if getattr(engine, "output_handler", None) is not None:
        engine.shutdown()
        raise CalibrationRunnerError("AsyncLLM output handler started before integration")
    del run_contract
    return engine


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationRunnerError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CalibrationRunnerError(f"{label} must be finite and non-negative")
    return result


async def execute_calibration_replay(
    *,
    run_id: str,
    expected_enqueue_order: Sequence[str],
    requests: Mapping[str, CalibrationRequestInput],
    adapter: CalibrationAdapter,
    timer_sink: TimerSink,
    run_epoch_monotonic: float,
    completion_timeout_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, object]:
    """Execute one run once, preserving exact order and online information."""

    expected = tuple(expected_enqueue_order)
    if not run_id or not expected or len(expected) != len(set(expected)):
        raise CalibrationRunnerError("run or enqueue identity is invalid")
    if set(requests) != set(expected):
        raise CalibrationRunnerError("request inputs differ from frozen enqueue set")
    epoch = _finite_nonnegative(run_epoch_monotonic, "run epoch")
    timeout = _finite_nonnegative(completion_timeout_seconds, "completion timeout")
    if timeout == 0.0:
        raise CalibrationRunnerError("completion timeout must be positive")

    terminal_events = {request_id: asyncio.Event() for request_id in expected}
    terminal_elapsed: dict[str, float] = {}
    submitted: list[str] = []
    completed: list[str] = []
    handles: dict[str, RequestHandle] = {}
    submission_available = asyncio.Event()

    async def collect_all() -> None:
        while len(completed) < len(expected):
            if len(completed) == len(submitted):
                submission_available.clear()
                if len(submitted) == len(expected):
                    raise CalibrationRunnerError(
                        "all requests were submitted without complete terminal evidence"
                    )
                await submission_available.wait()
                continue
            rows = await adapter.collect_completed(
                timeout_seconds=timeout,
                wait_for_one=True,
            )
            if not rows:
                raise CalibrationRunnerError("Native completion wait timed out")
            for row in rows:
                request_id = row.logical_request_id
                handle = handles.get(request_id)
                if (
                    handle is None
                    or request_id in terminal_elapsed
                    or row.status != "success"
                    or row.native_request_id != handle.native_request_id
                    or row.external_request_id != handle.external_request_id
                ):
                    raise CalibrationRunnerError(
                        "Native completion identity or status is invalid"
                    )
                terminal_elapsed[request_id] = max(0.0, monotonic() - epoch)
                completed.append(request_id)
                terminal_events[request_id].set()

    collector = asyncio.create_task(collect_all(), name=f"calibration:{run_id}:collector")
    timers: list[dict[str, object]] = []
    try:
        for request_id in expected:
            row = requests[request_id]
            if row.logical_request_id != request_id:
                raise CalibrationRunnerError("request input changed logical identity")
            if row.predecessor_request_id is not None:
                predecessor = row.predecessor_request_id
                if predecessor not in terminal_events:
                    raise CalibrationRunnerError("predecessor is outside frozen request set")
                await terminal_events[predecessor].wait()
                remaining = remaining_followup_delay(
                    successor_logical_arrival_seconds=row.logical_arrival_seconds,
                    run_elapsed_seconds_at_terminal=terminal_elapsed[predecessor],
                )
                timer = arm_followup_after_terminal(
                    candidate_id=row.program_id,
                    chain_id=f"{predecessor}->{request_id}",
                    program_id=row.program_id,
                    session_id=row.session_id,
                    predecessor_request_id=predecessor,
                    successor_request_id=request_id,
                    observed_tool_gap_seconds=remaining,
                    predecessor_terminal_observed=True,
                )
                timer_result = await timer_sink(timer.engine_core_payload())
                if timer_result.get("status") != "PASS":
                    raise CalibrationRunnerError("EngineCore controller timer failed")
                timers.append(timer.engine_core_payload())
            target = epoch + _finite_nonnegative(
                row.logical_arrival_seconds, "logical arrival"
            )
            delay = target - monotonic()
            if delay > 0:
                await sleep(delay)
            handle = await adapter.submit(
                AsyncLLMRequestSpec(
                    logical_request_id=request_id,
                    external_request_id=f"{run_id}:{request_id}",
                    prompt={"prompt_token_ids": list(row.prompt_token_ids)},
                    params=row.sampling_params,
                    planned_arrival_offset_seconds=row.logical_arrival_seconds,
                )
            )
            if handle.logical_request_id != request_id:
                raise CalibrationRunnerError("Adapter changed logical request identity")
            handles[request_id] = handle
            submitted.append(request_id)
            submission_available.set()
        await collector
        await adapter.shutdown(
            require_native_confirmation=True,
            require_frontend_observability=True,
        )
    except BaseException:
        collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        raise

    actual_sha256 = canonical_sha256(submitted)
    expected_sha256 = canonical_sha256(list(expected))
    if tuple(submitted) != expected or actual_sha256 != expected_sha256:
        raise CalibrationRunnerError("complete actual enqueue sequence differs")
    payload = {
        "schema_version": "phase5.swe_calibration_native_run_controller.v1",
        "status": "PASS",
        "run_id": run_id,
        "request_count": len(expected),
        "controller_timer_count": len(timers),
        "controller_submission_order": submitted,
        "native_completion_order": completed,
        "actual_enqueue_sequence_sha256": actual_sha256,
        "timer_runtime_rule": (
            "REMAINING_DELAY_FROM_FROZEN_ABSOLUTE_ARRIVAL_AFTER_REAL_TERMINAL"
        ),
        "adapter_report": dict(adapter.report()),
        "automatic_retry_allowed": False,
    }
    return {**payload, "controller_result_sha256": canonical_sha256(payload)}
