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
    PinnedNativeBlockPoolPressureExecutor,
    validate_pinned_asyncllm,
)
from kvopt.workload.phase5_native_async import NativePressureAllocationRequest
from kvopt.workload.phase5_replay import canonical_sha256


@dataclass(frozen=True)
class _RequestOutput:
    request_id: str  # vLLM returns the external request ID here.
    finished: bool


class _Collector:
    def __init__(self, internal_request_id: str) -> None:
        self.request_id = internal_request_id
        self.queue: asyncio.Queue[object] = asyncio.Queue()
        self.closed = False

    async def get(self) -> object:
        value = await self.queue.get()
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class _CoreOutput:
    request_id: str  # EngineCore uses the randomized internal request ID.
    finish_reason: str | None
    frontend_finished: bool = False


@dataclass(frozen=True)
class _CoreBatch:
    outputs: tuple[_CoreOutput, ...]
    timestamp: float


class _CoreClient:
    def __init__(self) -> None:
        self.batches: asyncio.Queue[_CoreBatch] = asyncio.Queue()
        self.aborts: list[tuple[str, ...]] = []
        self.get_output_calls = 0

    async def get_output_async(self) -> _CoreBatch:
        self.get_output_calls += 1
        return await self.batches.get()

    async def abort_requests_async(self, request_ids: object) -> None:
        identities = (
            (request_ids,) if isinstance(request_ids, str) else tuple(request_ids)
        )
        self.aborts.append(identities)


@dataclass
class _Block:
    block_id: int


class _BlockPool:
    def __init__(self, count: int = 8) -> None:
        self.free = [_Block(index) for index in range(count)]
        self.allocations: list[int] = []

    def get_num_free_blocks(self) -> int:
        return len(self.free)

    def get_new_blocks(self, num_blocks: int) -> list[object]:
        self.allocations.append(num_blocks)
        rows = self.free[:num_blocks]
        self.free = self.free[num_blocks:]
        return list(rows)

    def free_blocks(self, ordered_blocks: list[object]) -> None:
        self.free.extend(ordered_blocks)  # type: ignore[arg-type]


class _NativeCore:
    def __init__(self, block_pool: _BlockPool) -> None:
        manager = type("KVCacheManagerView", (), {"block_pool": block_pool})()
        self.scheduler = type("SchedulerView", (), {"kv_cache_manager": manager})()


def _native_pressure(boundary_id: str = "pressure-1") -> NativePressureAllocationRequest:
    token_ids = tuple(range(32))
    return NativePressureAllocationRequest(
        boundary_id=boundary_id,
        pressure_token_ids=token_ids,
        pressure_token_ids_sha256=canonical_sha256(list(token_ids)),
        block_size_tokens=16,
        required_blocks=2,
        expected_free_blocks_before=8,
    )


class _AsyncLLM:
    """API-shaped pinned AsyncLLM model with randomized internal IDs."""

    def __init__(self) -> None:
        self.engine_core: object = _CoreClient()
        self.output_handler: asyncio.Task[None] | None = None
        self.collectors: dict[str, _Collector] = {}
        self.external_to_internal: dict[str, str] = {}
        self.internal_to_external: dict[str, str] = {}
        self.frontend_internal_ids: set[str] = set()
        self.abort_calls: list[tuple[str, bool]] = []
        self.add_started = asyncio.Event()
        self.add_release: asyncio.Event | None = None
        self.abort_started = asyncio.Event()
        self.abort_release: asyncio.Event | None = None
        self.add_failure: BaseException | None = None
        self.fail_before_registration = False
        self.emit_terminal_before_add_returns = False
        self.fixed_internal_id: str | None = None
        self.output_handler_captured_proxy = False
        self.output_handler_exited = False

    async def add_request(
        self,
        *,
        request_id: str,
        prompt: object,
        params: object,
        arrival_time: float,
    ) -> _Collector:
        del prompt, params, arrival_time
        self.add_started.set()
        if self.add_failure is not None and self.fail_before_registration:
            raise self.add_failure
        internal_id = self.fixed_internal_id or f"{request_id}-random-7f3a"
        collector = _Collector(internal_id)
        self.collectors[internal_id] = collector
        self.external_to_internal[request_id] = internal_id
        self.internal_to_external[internal_id] = request_id
        self.frontend_internal_ids.add(internal_id)
        if self.output_handler is None:
            self.output_handler = asyncio.create_task(self._run_output_handler())
        if self.emit_terminal_before_add_returns:
            await self.raw_core.batches.put(
                _CoreBatch((_CoreOutput(internal_id, "stop", True),), 700.0)
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        if self.add_release is not None:
            await self.add_release.wait()
        if self.add_failure is not None:
            raise self.add_failure
        return collector

    async def abort(self, request_id: str, *, internal: bool = False) -> None:
        self.abort_calls.append((request_id, internal))
        self.abort_started.set()
        if self.abort_release is not None:
            await self.abort_release.wait()
        internal_id = (
            request_id if internal else self.external_to_internal.get(request_id)
        )
        if internal_id is not None:
            await self.engine_core.abort_requests_async([internal_id])  # type: ignore[attr-defined]
            self.frontend_internal_ids.discard(internal_id)

    async def _run_output_handler(self) -> None:
        core = self.engine_core
        self.output_handler_captured_proxy = isinstance(
            core, PinnedEngineCoreLifecycleProxy
        )
        try:
            while True:
                batch = await core.get_output_async()  # type: ignore[attr-defined]
                for output in batch.outputs:
                    external_id = self.internal_to_external[output.request_id]
                    if output.frontend_finished:
                        self.frontend_internal_ids.discard(output.request_id)
                    await self.collectors[output.request_id].queue.put(
                        _RequestOutput(external_id, output.frontend_finished)
                    )
        finally:
            self.output_handler_exited = True

    @property
    def raw_core(self) -> _CoreClient:
        core = self.engine_core
        if isinstance(core, PinnedEngineCoreLifecycleProxy):
            return core._delegate  # type: ignore[attr-defined]
        assert isinstance(core, _CoreClient)
        return core

    async def close(self) -> None:
        if self.output_handler is not None:
            self.output_handler.cancel()
            await asyncio.gather(self.output_handler, return_exceptions=True)


class _Clock:
    def __init__(self, start: float = 100.0) -> None:
        self.value = start

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _spec(request_id: str = "r1", offset: float = 0.0) -> AsyncLLMRequestSpec:
    return AsyncLLMRequestSpec(
        logical_request_id=request_id,
        external_request_id=f"external:{request_id}",
        prompt={"prompt_token_ids": [1, 2, 3]},
        params=object(),
        planned_arrival_offset_seconds=offset,
    )


def _adapter(
    engine: _AsyncLLM,
    *,
    observable: bool = True,
) -> AsyncLLMNativeAdapter:
    callback = (
        (lambda request_id: request_id in engine.frontend_internal_ids)
        if observable
        else None
    )
    return AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version=PINNED_VLLM_VERSION,
        run_epoch_monotonic=100.0,
        clock=_Clock(),
        frontend_has_internal_request=callback,
        verified_abort_confirmation_sources=frozenset(
            {"PINNED_CORE_ABORT_ACK_EVENT"}
        ),
    )


async def _yield() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def _natural_finish(
    engine: _AsyncLLM, handle_internal_id: str, *, timestamp: float = 700.0
) -> None:
    await engine.raw_core.batches.put(
        _CoreBatch(
            (_CoreOutput(handle_internal_id, "stop", frontend_finished=True),),
            timestamp,
        )
    )
    await _yield()


def test_randomized_internal_id_is_bound_to_external_and_logical_id() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        assert handle.external_request_id == "external:r1"
        assert handle.native_request_id == "external:r1-random-7f3a"
        assert handle.logical_request_id == "r1"
        await _yield()
        assert engine.output_handler_captured_proxy is True

        await _natural_finish(engine, handle.native_request_id)
        completed = await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        )
        assert completed[0].native_request_id == handle.native_request_id
        assert completed[0].external_request_id == "external:r1"
        row = adapter.report()["requests"][0]
        assert row["internal_request_id"] == handle.native_request_id
        assert row["external_request_id"] == "external:r1"
        await adapter.shutdown()
        await engine.close()
        assert engine.output_handler_exited is True

    asyncio.run(scenario())


def test_actual_background_output_handler_uses_proxy_as_single_consumer() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        await _natural_finish(engine, handle.native_request_id)
        assert engine.raw_core.get_output_calls == 2  # terminal batch + next wait
        assert engine.output_handler_captured_proxy is True
        assert adapter.report()["requests"][0]["native_terminal_confirmed"] is True
        await adapter.shutdown()
        await engine.close()

    asyncio.run(scenario())


def test_observer_installation_rejects_started_output_handler() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.output_handler = asyncio.create_task(asyncio.sleep(10))
        with pytest.raises(AsyncLLMAdapterError, match="before output handler startup"):
            _adapter(engine)
        engine.output_handler.cancel()
        await asyncio.gather(engine.output_handler, return_exceptions=True)

    asyncio.run(scenario())


def test_core_terminal_before_collector_return_is_buffered_then_bound() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.emit_terminal_before_add_returns = True
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        await _yield()
        completed = await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        )
        assert [row.native_request_id for row in completed] == [
            handle.native_request_id
        ]
        await adapter.shutdown()
        await engine.close()

    asyncio.run(scenario())


def test_processed_output_uses_external_not_internal_identity() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        await engine.collectors[handle.native_request_id].queue.put(
            _RequestOutput(handle.native_request_id, False)
        )
        await _yield()
        with pytest.raises(AsyncLLMAdapterError, match="collector pump failed"):
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())


def test_explicit_abort_uses_external_id_and_does_not_confirm_terminal() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        await adapter.abort("r1")
        assert engine.abort_calls == [("external:r1", False)]
        assert engine.raw_core.aborts == [(handle.native_request_id,)]
        row = adapter.report()["requests"][0]
        assert row["abort_dispatched"] is True
        assert row["native_terminal_confirmed"] is False
        event = next(
            event
            for event in adapter.report()["events"]
            if event["kind"] == "NATIVE_ABORT_DISPATCHED"
        )
        assert event["details"]["source"] == "EXPLICIT_EXTERNAL_ABORT"
        assert event["details"]["identity_kind"] == "EXTERNAL"
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())


def test_stop_string_abort_dispatch_requires_independent_confirmation_source() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        await engine.collectors[handle.native_request_id].queue.put(
            _RequestOutput("external:r1", True)
        )
        engine.frontend_internal_ids.discard(handle.native_request_id)
        await engine.engine_core.abort_requests_async([handle.native_request_id])  # type: ignore[attr-defined]
        await _yield()
        assert await adapter.collect_completed(
            timeout_seconds=0, wait_for_one=False
        ) == ()
        with pytest.raises(AsyncLLMAdapterError, match="not independently verified"):
            await adapter.confirm_native_terminal(
                "r1",
                kind=NativeTerminalKind.ABORT_CONFIRMED,
                timestamp=701.0,
                confirmation_source="ABORT_API_RETURN",
            )
        await adapter.confirm_native_terminal(
            "r1",
            kind=NativeTerminalKind.ABORT_CONFIRMED,
            timestamp=701.0,
            confirmation_source="PINNED_CORE_ABORT_ACK_EVENT",
        )
        assert len(
            await adapter.collect_completed(timeout_seconds=0, wait_for_one=False)
        ) == 1
        await adapter.shutdown()
        await engine.close()

    asyncio.run(scenario())


def test_submit_cancellation_rolls_back_registered_request() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.add_release = asyncio.Event()
        adapter = _adapter(engine)
        submit_task = asyncio.create_task(adapter.submit(_spec()))
        await engine.add_started.wait()
        submit_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await submit_task
        assert engine.frontend_internal_ids == set()
        assert engine.abort_calls == [("external:r1", False)]
        report = adapter.report()
        assert report["active_submit_count"] == 0
        assert any(
            event["details"].get("source") == "SUBMIT_CANCELLED_ROLLBACK"
            for event in report["events"]
            if event["kind"] == "NATIVE_ABORT_DISPATCHED"
        )
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())


def test_submit_and_shutdown_race_cannot_create_late_collector_task() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.add_release = asyncio.Event()
        adapter = _adapter(engine)
        submit_task = asyncio.create_task(adapter.submit(_spec()))
        await engine.add_started.wait()
        shutdown_task = asyncio.create_task(
            adapter.shutdown(require_native_confirmation=False)
        )
        await _yield()
        engine.add_release.set()
        with pytest.raises(AsyncLLMAdapterError, match="shutdown began"):
            await submit_task
        await shutdown_task
        row = adapter.report()["requests"][0]
        assert row["collector_task_done"] is True
        assert adapter.report()["state"] == "CLOSED"
        assert engine.frontend_internal_ids == set()
        await engine.close()

    asyncio.run(scenario())


def test_cancelled_shutdown_continues_and_second_call_joins_cleanup() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.abort_release = asyncio.Event()
        adapter = _adapter(engine)
        await adapter.submit(_spec())
        first = asyncio.create_task(adapter.shutdown(require_native_confirmation=False))
        await engine.abort_started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert adapter.report()["state"] == "SHUTTING_DOWN"
        engine.abort_release.set()
        await adapter.shutdown(require_native_confirmation=False)
        report = adapter.report()
        assert report["state"] == "CLOSED"
        assert report["requests"][0]["collector_task_done"] is True
        assert engine.frontend_internal_ids == set()
        await engine.close()

    asyncio.run(scenario())


def test_waiting_completion_is_woken_immediately_by_collector_failure() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        waiter = asyncio.create_task(
            adapter.collect_completed(timeout_seconds=60.0, wait_for_one=True)
        )
        await engine.collectors[handle.native_request_id].queue.put(
            RuntimeError("pump died")
        )
        with pytest.raises(AsyncLLMAdapterError, match="collector pump failed"):
            await asyncio.wait_for(waiter, timeout=0.2)
        event = next(
            event
            for event in adapter.report()["events"]
            if event["kind"] == "NATIVE_ABORT_DISPATCHED"
        )
        assert event["details"]["source"] == "COLLECTOR_FAILURE"
        assert event["details"]["identity_kind"] == "INTERNAL"
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())


def test_dispatch_failure_records_external_rollback_abort() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.add_failure = RuntimeError("Core submission failed")
        adapter = _adapter(engine)
        with pytest.raises(RuntimeError, match="Core submission failed"):
            await adapter.submit(_spec())
        assert engine.frontend_internal_ids == set()
        event = next(
            event
            for event in adapter.report()["events"]
            if event["kind"] == "NATIVE_ABORT_DISPATCHED"
        )
        assert event["details"]["source"] == "DISPATCH_FAILED_ROLLBACK"
        assert event["details"]["identity_kind"] == "EXTERNAL"
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())


def test_registration_failure_has_no_state_and_records_rollback_attempt() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        engine.add_failure = RuntimeError("registration failed")
        engine.fail_before_registration = True
        adapter = _adapter(engine)
        with pytest.raises(RuntimeError, match="registration failed"):
            await adapter.submit(_spec())
        assert engine.frontend_internal_ids == set()
        assert engine.abort_calls == [("external:r1", False)]
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())


def test_shutdown_abort_uses_internal_id_and_records_source() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        await adapter.shutdown(require_native_confirmation=False)
        assert engine.abort_calls == [(handle.native_request_id, True)]
        event = next(
            event
            for event in adapter.report()["events"]
            if event["kind"] == "NATIVE_ABORT_DISPATCHED"
        )
        assert event["details"]["source"] == "ADAPTER_SHUTDOWN"
        assert event["details"]["identity_kind"] == "INTERNAL"
        await engine.close()

    asyncio.run(scenario())


def test_missing_request_state_observer_is_explicitly_not_observable() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine, observable=False)
        await adapter.submit(_spec())
        report = adapter.report()
        assert report["request_state_observability"] == "NOT_OBSERVABLE"
        assert report["gpu_conformance_ready"] is False
        with pytest.raises(AsyncLLMAdapterError, match="NOT_OBSERVABLE"):
            await adapter.shutdown(
                require_native_confirmation=False,
                require_frontend_observability=True,
            )
        await engine.close()

    asyncio.run(scenario())


def test_pinned_request_states_mapping_is_used_when_has_request_is_absent() -> None:
    class OutputProcessorView:
        def __init__(self) -> None:
            self.request_states: dict[str, object] = {}

    engine = _AsyncLLM()
    engine.output_processor = OutputProcessorView()  # type: ignore[attr-defined]
    adapter = AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version=PINNED_VLLM_VERSION,
        run_epoch_monotonic=100.0,
        clock=_Clock(),
        verified_abort_confirmation_sources=frozenset(
            {"PINNED_CORE_ABORT_ACK_EVENT"}
        ),
    )
    report = adapter.report()
    assert report["request_state_observability"] == "OBSERVABLE"
    assert (
        report["request_state_query_source"]
        == "ASYNCLLM_OUTPUT_PROCESSOR_REQUEST_STATES_MAPPING"
    )


def test_missing_abort_confirmation_source_keeps_gpu_conformance_not_ready() -> None:
    engine = _AsyncLLM()
    adapter = AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version=PINNED_VLLM_VERSION,
        run_epoch_monotonic=100.0,
        clock=_Clock(),
        frontend_has_internal_request=lambda request_id: (
            request_id in engine.frontend_internal_ids
        ),
    )
    report = adapter.report()
    assert report["gpu_conformance_ready"] is False
    assert "ABORT_CONFIRMATION_SOURCE_NOT_ESTABLISHED" in report[
        "gpu_conformance_blockers"
    ]


def test_timing_evidence_keeps_external_internal_and_clock_domains_separate() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        adapter = _adapter(engine)
        handle = await adapter.submit(_spec())
        adapter.observe_native_submission(
            "r1", timestamp=700.0, internal_request_id=handle.native_request_id
        )
        adapter.observe_scheduler_timing(
            "r1", queued_timestamp=700.1, scheduled_timestamp=700.2
        )
        await _natural_finish(engine, handle.native_request_id, timestamp=701.0)
        report = adapter.report()
        assert report["clock_contract"]["cross_domain_subtraction"] == "PROHIBITED"
        binding = next(
            event
            for event in report["events"]
            if event["kind"] == "INTERNAL_REQUEST_ID_BOUND"
        )
        assert binding["details"] == {
            "external_request_id": "external:r1",
            "internal_request_id": handle.native_request_id,
        }
        await adapter.shutdown()
        await engine.close()

    asyncio.run(scenario())


def test_version_surface_and_batch_drain_are_pinned() -> None:
    engine = _AsyncLLM()
    with pytest.raises(AsyncLLMAdapterError, match="version must be"):
        validate_pinned_asyncllm(engine, vllm_version="0.28.0")
    engine.wait_for_completion = object()  # type: ignore[attr-defined]
    with pytest.raises(AsyncLLMAdapterError, match="prohibited"):
        validate_pinned_asyncllm(engine, vllm_version=PINNED_VLLM_VERSION)


def test_native_pressure_uses_real_block_pool_allocation_and_releases() -> None:
    pool = _BlockPool()
    core = _NativeCore(pool)
    executor = PinnedNativeBlockPoolPressureExecutor(
        block_pool=pool,
        adapter_engine_core=core,
        scheduler_engine_core=core,
        kv_instrumentation_engine_core=core,
        evidence_reader=lambda boundary_id, block_ids: {
            "forced_release_decision_ids": [f"decision:{boundary_id}"],
            "native_evicted_block_ids": list(block_ids),
        },
        clock=lambda: 12.0,
    )

    result = executor.execute(
        _native_pressure(),
        expected_inflight_request_ids=("r1", "r2"),
        actual_inflight_request_ids=("r1", "r2"),
    )

    assert pool.allocations == [2]
    assert result.allocated_block_ids == (0, 1)
    assert result.free_blocks_before == result.free_blocks_after_release == 8
    assert result.allocation_source == "PINNED_BLOCK_POOL_GET_NEW_BLOCKS"


def test_native_pressure_rejects_engine_identity_or_missing_evidence() -> None:
    pool = _BlockPool()
    core = _NativeCore(pool)
    with pytest.raises(AsyncLLMAdapterError, match="EngineCore differ"):
        PinnedNativeBlockPoolPressureExecutor(
            block_pool=pool,
            adapter_engine_core=core,
            scheduler_engine_core=object(),
            kv_instrumentation_engine_core=core,
            evidence_reader=lambda _boundary, _blocks: {},
        ).execute(
            _native_pressure(),
            expected_inflight_request_ids=("r1",),
            actual_inflight_request_ids=("r1",),
        )

    with pytest.raises(AsyncLLMAdapterError, match="not owned"):
        PinnedNativeBlockPoolPressureExecutor(
            block_pool=_BlockPool(),
            adapter_engine_core=core,
            scheduler_engine_core=core,
            kv_instrumentation_engine_core=core,
            evidence_reader=lambda _boundary, _blocks: {},
        ).execute(
            _native_pressure(),
            expected_inflight_request_ids=("r1",),
            actual_inflight_request_ids=("r1",),
        )

    executor = PinnedNativeBlockPoolPressureExecutor(
        block_pool=pool,
        adapter_engine_core=core,
        scheduler_engine_core=core,
        kv_instrumentation_engine_core=core,
        evidence_reader=lambda _boundary, _blocks: {
            "forced_release_decision_ids": [],
            "native_evicted_block_ids": [],
        },
    )
    with pytest.raises(ValueError, match="Forced Entry Release"):
        executor.execute(
            _native_pressure(),
            expected_inflight_request_ids=("r1",),
            actual_inflight_request_ids=("r1",),
        )


def test_asyncllm_adapter_routes_pressure_to_bound_native_executor() -> None:
    async def scenario() -> None:
        engine = _AsyncLLM()
        pool = _BlockPool()
        core = engine.engine_core
        manager = type("KVCacheManagerView", (), {"block_pool": pool})()
        core.scheduler = type(  # type: ignore[attr-defined]
            "SchedulerView", (), {"kv_cache_manager": manager}
        )()
        executor = PinnedNativeBlockPoolPressureExecutor(
            block_pool=pool,
            adapter_engine_core=core,
            scheduler_engine_core=core,
            kv_instrumentation_engine_core=core,
            evidence_reader=lambda boundary_id, block_ids: {
                "forced_release_decision_ids": [f"decision:{boundary_id}"],
                "native_evicted_block_ids": list(block_ids),
            },
            clock=lambda: 15.0,
        )
        adapter = AsyncLLMNativeAdapter(
            engine=engine,
            vllm_version=PINNED_VLLM_VERSION,
            run_epoch_monotonic=100.0,
            clock=_Clock(),
            frontend_has_internal_request=lambda request_id: (
                request_id in engine.frontend_internal_ids
            ),
            native_pressure_executor=executor,
        )
        await adapter.submit(_spec())
        result = await adapter.execute_native_pressure(
            _native_pressure(),
            expected_inflight_request_ids=("r1",),
        )
        assert result.required_blocks == 2
        assert any(
            event["kind"] == "NATIVE_PRESSURE_ALLOCATED"
            for event in adapter.report()["events"]
        )
        await adapter.shutdown(require_native_confirmation=False)
        await engine.close()

    asyncio.run(scenario())
