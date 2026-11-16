from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from kvopt.workload.phase5_asyncllm_adapter import (
    PINNED_VLLM_VERSION,
    AsyncLLMAdapterError,
    AsyncLLMNativeAdapter,
    AsyncLLMRequestSpec,
    NativeTerminalKind,
    PinnedEngineCoreLifecycleProxy,
    install_pinned_engine_core_lifecycle_proxy,
    validate_pinned_asyncllm,
)


@dataclass(frozen=True)
class _Output:
    request_id: str
    finished: bool


class _Collector:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[object] = asyncio.Queue()
        self.closed = False

    async def get(self) -> object:
        value = await self.queue.get()
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.closed = True


class _Engine:
    def __init__(self) -> None:
        self.collectors: dict[str, _Collector] = {}
        self.frontend: set[str] = set()
        self.abort_calls: list[tuple[str, bool]] = []
        self.add_failure: BaseException | None = None
        self.fail_before_registration = False

    async def add_request(
        self,
        *,
        request_id: str,
        prompt: object,
        params: object,
        arrival_time: float,
    ) -> _Collector:
        del prompt, params, arrival_time
        if self.add_failure is not None:
            if not self.fail_before_registration:
                self.frontend.add(request_id)
            error = self.add_failure
            raise error
        self.frontend.add(request_id)
        collector = _Collector()
        self.collectors[request_id] = collector
        return collector

    async def abort(self, request_id: str, *, internal: bool = False) -> None:
        self.abort_calls.append((request_id, internal))
        self.frontend.discard(request_id)

    async def emit(self, request_id: str, *, finished: bool) -> None:
        if finished:
            self.frontend.discard(request_id)
        await self.collectors[request_id].queue.put(_Output(request_id, finished))


class _Clock:
    def __init__(self, start: float = 100.0) -> None:
        self.value = start

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _spec(request_id: str = "r1", offset: float = 0.0) -> AsyncLLMRequestSpec:
    return AsyncLLMRequestSpec(
        logical_request_id=request_id,
        native_request_id=f"native:{request_id}",
        external_request_id=f"external:{request_id}",
        prompt={"prompt_token_ids": [1, 2, 3]},
        params=object(),
        planned_arrival_offset_seconds=offset,
    )


def _adapter(engine: _Engine, clock: _Clock | None = None) -> AsyncLLMNativeAdapter:
    actual_clock = _Clock() if clock is None else clock
    return AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version=PINNED_VLLM_VERSION,
        run_epoch_monotonic=100.0,
        clock=actual_clock,
        frontend_has_request=lambda request_id: request_id in engine.frontend,
    )


async def _yield() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_frontend_terminal_does_not_release_without_native_terminal() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        await engine.emit("native:r1", finished=False)
        await engine.emit("native:r1", finished=True)
        await _yield()
        assert await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        ) == ()
        row = adapter.report()["requests"][0]
        assert row["partial_output_count"] == 1
        assert row["output_processor_terminal"] is True
        assert row["native_terminal_confirmed"] is False

        await adapter.confirm_native_terminal(
            "r1", kind=NativeTerminalKind.NATURAL, timestamp=700.0
        )
        completed = await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        )
        assert [row.logical_request_id for row in completed] == ["r1"]
        await adapter.shutdown()

    asyncio.run(scenario())


def test_native_terminal_before_frontend_waits_for_output_processor() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        await adapter.confirm_native_terminal(
            "r1", kind=NativeTerminalKind.NATURAL, timestamp=700.0
        )
        assert await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        ) == ()
        await engine.emit("native:r1", finished=True)
        await _yield()
        assert len(
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        ) == 1
        await adapter.shutdown()

    asyncio.run(scenario())


def test_stop_string_abort_send_is_not_native_confirmation() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        await engine.emit("native:r1", finished=True)
        await _yield()
        adapter.observe_internal_abort_dispatched("r1")
        assert await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        ) == ()
        report = adapter.report()["requests"][0]
        assert report["abort_dispatched"] is True
        assert report["native_terminal_confirmed"] is False

        await adapter.confirm_native_terminal(
            "r1", kind=NativeTerminalKind.ABORT_CONFIRMED, timestamp=701.0
        )
        assert len(
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        ) == 1
        await adapter.shutdown()

    asyncio.run(scenario())


def test_abort_confirmation_requires_prior_abort_dispatch() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        with pytest.raises(AsyncLLMAdapterError, match="lacks abort dispatch"):
            await adapter.confirm_native_terminal(
                "r1", kind=NativeTerminalKind.ABORT_CONFIRMED, timestamp=701.0
            )
        await adapter.shutdown(require_native_confirmation=False)

    asyncio.run(scenario())


def test_dispatch_failure_rolls_back_frontend_state() -> None:
    async def scenario() -> None:
        engine = _Engine()
        engine.add_failure = RuntimeError("Core submission failed")
        adapter = _adapter(engine)
        with pytest.raises(RuntimeError, match="Core submission failed"):
            await adapter.submit(_spec())
        assert engine.frontend == set()
        assert engine.abort_calls == [("native:r1", True)]
        assert adapter.report()["requests"][0]["failure_reason"].startswith(
            "DISPATCH_FAILED"
        )
        await adapter.shutdown(require_native_confirmation=False)

    asyncio.run(scenario())


def test_output_processor_registration_failure_leaves_no_state_or_task() -> None:
    async def scenario() -> None:
        engine = _Engine()
        engine.add_failure = RuntimeError("registration failed")
        engine.fail_before_registration = True
        adapter = _adapter(engine)
        with pytest.raises(RuntimeError, match="registration failed"):
            await adapter.submit(_spec())
        assert engine.frontend == set()
        report = adapter.report()["requests"][0]
        assert report["collector_task_done"] is True
        assert report["failure_reason"].startswith("DISPATCH_FAILED")
        await adapter.shutdown(require_native_confirmation=False)

    asyncio.run(scenario())


def test_collector_pump_failure_is_fail_closed_and_aborts_request() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        await engine.collectors["native:r1"].queue.put(RuntimeError("pump died"))
        await _yield()
        with pytest.raises(AsyncLLMAdapterError, match="collector pump failed"):
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        assert engine.abort_calls == [("native:r1", True)]
        await adapter.shutdown(require_native_confirmation=False)
        assert adapter.report()["requests"][0]["collector_task_done"] is True

    asyncio.run(scenario())


def test_shutdown_cancels_tasks_and_fails_closed_without_abort_confirmation() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        with pytest.raises(AsyncLLMAdapterError, match="confirmation missing"):
            await adapter.shutdown()
        report = adapter.report()
        assert report["closed"] is True
        assert report["requests"][0]["collector_task_done"] is True
        assert engine.frontend == set()

    asyncio.run(scenario())


def test_two_requests_overlap_and_complete_out_of_order() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec("r1"))
        await adapter.submit(_spec("r2"))
        assert set(engine.frontend) == {"native:r1", "native:r2"}

        await engine.emit("native:r2", finished=True)
        await adapter.confirm_native_terminal(
            "r2", kind=NativeTerminalKind.NATURAL, timestamp=702.0
        )
        await _yield()
        completed = await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        )
        assert [row.logical_request_id for row in completed] == ["r2"]

        await engine.emit("native:r1", finished=True)
        await adapter.confirm_native_terminal(
            "r1", kind=NativeTerminalKind.NATURAL, timestamp=703.0
        )
        await _yield()
        assert len(
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        ) == 1
        await adapter.shutdown()

    asyncio.run(scenario())


def test_timing_evidence_keeps_dispatch_and_engine_clocks_separate() -> None:
    async def scenario() -> None:
        engine = _Engine()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        adapter.observe_native_submission(
            "r1", timestamp=700.0, native_request_id="native:r1"
        )
        adapter.observe_scheduler_timing(
            "r1", queued_timestamp=700.1, scheduled_timestamp=700.2
        )
        await engine.emit("native:r1", finished=True)
        await adapter.confirm_native_terminal(
            "r1", kind=NativeTerminalKind.NATURAL, timestamp=701.0
        )
        await _yield()
        report = adapter.report()
        assert report["clock_contract"]["cross_domain_subtraction"] == "PROHIBITED"
        kinds = [row["kind"] for row in report["events"]]
        assert "ADAPTER_DISPATCH_RETURNED" in kinds
        assert "NATIVE_SUBMISSION_OBSERVED" in kinds
        assert "NATIVE_SCHEDULER_OBSERVED" in kinds
        await adapter.shutdown()

    asyncio.run(scenario())


def test_version_and_surface_are_pinned_and_batch_drain_is_rejected() -> None:
    engine = _Engine()
    with pytest.raises(AsyncLLMAdapterError, match="version must be"):
        validate_pinned_asyncllm(engine, vllm_version="0.28.0")

    engine.wait_for_completion = object()  # type: ignore[attr-defined]
    with pytest.raises(AsyncLLMAdapterError, match="prohibited"):
        validate_pinned_asyncllm(engine, vllm_version=PINNED_VLLM_VERSION)


@dataclass(frozen=True)
class _CoreOutput:
    request_id: str
    finish_reason: str | None


@dataclass(frozen=True)
class _CoreBatch:
    outputs: tuple[_CoreOutput, ...]
    timestamp: float


class _CoreClient:
    def __init__(self) -> None:
        self.batches: asyncio.Queue[_CoreBatch] = asyncio.Queue()
        self.aborts: list[object] = []

    async def get_output_async(self) -> _CoreBatch:
        return await self.batches.get()

    async def abort_requests_async(self, request_ids: object) -> None:
        self.aborts.append(request_ids)


def test_engine_core_proxy_observes_same_stream_without_second_consumer() -> None:
    async def scenario() -> None:
        engine = _Engine()
        core = _CoreClient()
        engine.engine_core = core  # type: ignore[attr-defined]
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        proxy = install_pinned_engine_core_lifecycle_proxy(engine, adapter)
        assert isinstance(proxy, PinnedEngineCoreLifecycleProxy)

        await core.batches.put(
            _CoreBatch((_CoreOutput("native:r1", "stop"),), timestamp=700.0)
        )
        observed = await engine.engine_core.get_output_async()  # type: ignore[attr-defined]
        assert observed.timestamp == 700.0
        assert adapter.report()["requests"][0]["native_terminal_confirmed"] is True

        await engine.engine_core.abort_requests_async(["native:r1"])  # type: ignore[attr-defined]
        assert adapter.report()["requests"][0]["abort_dispatched"] is True
        await engine.emit("native:r1", finished=True)
        await _yield()
        assert len(
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        ) == 1
        await adapter.shutdown()

    asyncio.run(scenario())


def test_engine_core_proxy_does_not_treat_abort_dispatch_as_confirmation() -> None:
    async def scenario() -> None:
        engine = _Engine()
        engine.engine_core = _CoreClient()  # type: ignore[attr-defined]
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        install_pinned_engine_core_lifecycle_proxy(engine, adapter)
        await engine.engine_core.abort_requests_async("native:r1")  # type: ignore[attr-defined]
        row = adapter.report()["requests"][0]
        assert row["abort_dispatched"] is True
        assert row["native_terminal_confirmed"] is False
        engine.frontend.discard("native:r1")
        await adapter.shutdown(require_native_confirmation=False)

    asyncio.run(scenario())
