"""Shared trace-driven controller for one frozen SWE Calibration run.

This module owns no GPU and starts no process on import.  The production CLI
injects the pinned AsyncLLM adapter and EngineCore control channel; CPU tests
exercise the identical ordering, terminal and timer contract.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .phase2b_fidelity_runner import RequestCompletion, RequestHandle
from .phase5_asyncllm_adapter import AsyncLLMRequestSpec
from .phase5_calibration_controller import (
    arm_followup_after_terminal,
    remaining_followup_delay,
)
from .phase5_replay import canonical_sha256


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
class CalibrationRequestInput:
    logical_request_id: str
    prompt_token_ids: tuple[int, ...]
    sampling_params: object
    logical_arrival_seconds: float
    program_id: str
    session_id: str
    predecessor_request_id: str | None = None


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
