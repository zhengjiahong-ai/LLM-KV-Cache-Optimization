from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from kvopt.continuum import FakeClock
from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_gpu_conformance import (
    build_phase5e_review_candidate,
    materialize_phase5e_prompt_token_ids,
)
from kvopt.workload.phase5_native_async import PressureExecutionEvidence
from kvopt.workload.phase5e_a3_retention import (
    build_phase5e_cpu_mock_retention_manifest,
)
from kvopt.workload.phase5e_native_evidence_source import Phase5ENativeEvidenceError
from kvopt.workload.phase5e_native_runner import (
    Phase5ENativeAuthorization,
    Phase5ENativeRunnerError,
    build_allocation_watermark_reader,
    claim_native_execution_once,
    create_pinned_asyncllm,
    install_engine_core_production_stack,
    install_production_a3_runtime,
    install_production_native_stack,
    load_integration_factory,
    resolve_production_evidence_source,
    run_phase5e_native_pipeline,
    validate_reviewed_plan_identity,
    validate_runtime_engine_identity,
)
from kvopt.workload.phase5e_native_runtime import Phase5ERuntimeEventSource


class _IdentityAdapter:
    def internal_request_id(self, logical_id: str) -> str:
        return f"internal:{logical_id}"


class _Manager:
    def get_block_ids(self, internal_id: str):
        count = {"internal:r1": 3, "internal:r2": 2}[internal_id]
        return [list(range(count))]


class _Engine:
    output_handler = None

    def __init__(self) -> None:
        self.closed = False

    def shutdown(self, **_kwargs) -> None:
        self.closed = True


class _Evidence:
    def a3_retention_input_manifest(self):
        return build_phase5e_cpu_mock_retention_manifest(
            plan=build_phase5e_review_candidate("a" * 40)
        )

    def runtime_integration(self):
        return type(
            "IdentityObserver",
            (),
            {"bind_request_identity": lambda self, **_kwargs: None},
        )()

    def runtime_installation_report(self):
        return {
            "status": "PASS",
            "mode": "CONTROLLED_A3",
            "same_engine_core": True,
            "source_sha256": {"test": "a" * 64},
        }

    def pressure_outcome(self, boundary_id, allocated_block_ids):
        return {
            "forced_release_decision_ids": [f"decision:{boundary_id}"],
            "native_evicted_block_ids": list(allocated_block_ids),
        }

    def candidate_exposure_report(self):
        return {
            "status": "PASS",
            "downstream_recompute_attribution": "NOT_ESTABLISHED",
        }

    def raw_evidence(self):
        return ({"event_type": "TEST_NATIVE_EVIDENCE"},)


class _Adapter:
    def __init__(self, plan) -> None:
        self.plan = plan
        self.inflight = []
        self.events = []
        self.index = 0
        self.closed = False

    def _event(self, request_id, kind):
        self.index += 1
        self.events.append({"index": self.index, "request_id": request_id, "kind": kind})

    async def submit(self, spec):
        self._event(spec.logical_request_id, "ADAPTER_DISPATCH_STARTED")
        self._event(spec.logical_request_id, "NATIVE_SUBMISSION_OBSERVED")
        self.inflight.append(spec.logical_request_id)
        return RequestHandle(
            spec.logical_request_id,
            f"native:{spec.logical_request_id}",
            spec.external_request_id,
            1.0,
        )

    async def collect_completed(self, **_kwargs):
        result = []
        for request_id in tuple(self.inflight):
            self.inflight.remove(request_id)
            self._event(request_id, "NATIVE_TERMINAL_CONFIRMED")
            result.append(
                RequestCompletion(
                    request_id,
                    f"native:{request_id}",
                    f"P5E-A-01:{request_id}",
                    10.0,
                )
            )
        return tuple(result)

    async def execute_native_pressure(self, request, *, expected_inflight_request_ids):
        assert tuple(self.inflight) == expected_inflight_request_ids
        return PressureExecutionEvidence(
            boundary_id=request.boundary_id,
            native_snapshot_timestamp=5.0,
            inflight_request_ids=expected_inflight_request_ids,
            pressure_token_ids_sha256=request.pressure_token_ids_sha256,
            required_blocks=request.required_blocks,
            allocated_block_ids=tuple(range(request.required_blocks)),
            free_blocks_before=request.required_blocks,
            free_blocks_after_allocation=0,
            free_blocks_after_release=request.required_blocks,
            allocation_source="PINNED_BLOCK_POOL_GET_NEW_BLOCKS",
            engine_core_identity_verified=True,
            forced_release_decision_ids=("decision-1",),
            native_evicted_block_ids=(1,),
            allocation_watermark_source=("PINNED_KV_CACHE_MANAGER_REQUEST_BLOCK_TABLE"),
            observed_allocated_blocks_by_request=(
                self.plan.pressure.expected_allocated_blocks_by_request
            ),
        )

    async def shutdown(self, **_kwargs):
        self.closed = True

    def report(self):
        return {
            "state": "CLOSED" if self.closed else "OPEN",
            "request_state_observability": "OBSERVABLE",
            "active_submit_count": 0,
            "fatal_error": None,
            "events": self.events,
            "requests": [
                {
                    "logical_request_id": request_id,
                    "output_processor_terminal": True,
                    "native_terminal_confirmed": True,
                    "native_terminal_kind": "NATURAL_CORE_TERMINAL",
                    "abort_dispatched": False,
                    "failure_reason": None,
                    "collector_task_done": True,
                }
                for request_id in self.plan.frozen_native_enqueue_order
            ],
        }


class _FailingAdapter(_Adapter):
    async def execute_native_pressure(self, request, *, expected_inflight_request_ids):
        del request, expected_inflight_request_ids
        raise RuntimeError("frozen pressure failed")


def _explicit_inputs(plan):
    return {
        "prompt_token_ids": {
            request_id: list(
                materialize_phase5e_prompt_token_ids(program.program_ordinal, request_index)
            )
            for program in plan.programs
            for request_index, request_id in enumerate(program.request_ids, start=1)
        },
        "pressure_token_ids_sha256": (plan.pressure.pressure_prompt_token_ids_sha256),
    }


def _authorization():
    return Phase5ENativeAuthorization(
        run_id="P5E-A-01",
        git_sha="a" * 40,
        execution_manifest_sha256="b" * 64,
        authorization_sha256="c" * 64,
    )


def test_single_execution_claim_is_bound_to_freeze_not_output_directory(
    tmp_path: Path,
) -> None:
    authorization = _authorization()
    claim = claim_native_execution_once(
        freeze_root=tmp_path, authorization=authorization
    )
    payload = json.loads(claim.read_text(encoding="utf-8"))
    assert payload["authorization_sha256"] == authorization.authorization_sha256
    assert payload["automatic_retry_allowed"] is False
    with pytest.raises(FileExistsError):
        claim_native_execution_once(
            freeze_root=tmp_path, authorization=authorization
        )


def test_reviewed_plan_identity_uses_canonical_json_semantics() -> None:
    validate_reviewed_plan_identity(
        frozen_plan={"requests": ["r1", "r2"], "geometry": [["r1", 128]]},
        rebuilt_plan={"requests": ("r1", "r2"), "geometry": (("r1", 128),)},
    )

    with pytest.raises(Phase5ENativeRunnerError, match="reviewed plan differs"):
        validate_reviewed_plan_identity(
            frozen_plan={"requests": ["r1", "r2"]},
            rebuilt_plan={"requests": ("r2", "r1")},
        )


def test_integration_factory_reference_fails_closed() -> None:
    with pytest.raises(Phase5ENativeRunnerError, match="module:function"):
        load_integration_factory("not-a-reference")
    with pytest.raises(Phase5ENativeRunnerError, match="not callable"):
        load_integration_factory("json:decoder")


def test_allocation_watermark_uses_internal_request_block_tables() -> None:
    reader = build_allocation_watermark_reader(
        adapter=_IdentityAdapter(),  # type: ignore[arg-type]
        kv_cache_manager=_Manager(),
    )
    assert reader(("r1", "r2")) == {"r1": 3, "r2": 2}


def test_engine_creation_requires_inprocess_vllm_before_import(monkeypatch) -> None:
    monkeypatch.delenv("VLLM_ENABLE_V1_MULTIPROCESSING", raising=False)
    with pytest.raises(Phase5ENativeRunnerError, match="MULTIPROCESSING"):
        create_pinned_asyncllm(build_phase5e_review_candidate("a" * 40))


def _install_fake_vllm_engine_modules(monkeypatch, *, output_handler: object):
    captured = {}

    class FakeAsyncEngineArgs:
        def __init__(self, **kwargs) -> None:
            captured["engine_args"] = kwargs

    class FakeEngine:
        def __init__(self) -> None:
            self.output_handler = output_handler
            self.closed = False

        def shutdown(self) -> None:
            self.closed = True

    engine = FakeEngine()

    class FakeAsyncLLM:
        @classmethod
        def from_engine_args(cls, engine_args, *, start_engine_loop):
            captured["from_engine_args"] = {
                "engine_args": engine_args,
                "start_engine_loop": start_engine_loop,
            }
            return engine

    vllm = ModuleType("vllm")
    vllm.__version__ = "0.27.1"  # type: ignore[attr-defined]
    engine_package = ModuleType("vllm.engine")
    arg_utils = ModuleType("vllm.engine.arg_utils")
    arg_utils.AsyncEngineArgs = FakeAsyncEngineArgs  # type: ignore[attr-defined]
    v1_package = ModuleType("vllm.v1")
    v1_engine_package = ModuleType("vllm.v1.engine")
    async_llm = ModuleType("vllm.v1.engine.async_llm")
    async_llm.AsyncLLM = FakeAsyncLLM  # type: ignore[attr-defined]
    for name, module in (
        ("vllm", vllm),
        ("vllm.engine", engine_package),
        ("vllm.engine.arg_utils", arg_utils),
        ("vllm.v1", v1_package),
        ("vllm.v1.engine", v1_engine_package),
        ("vllm.v1.engine.async_llm", async_llm),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return engine, captured


def test_engine_creation_defers_output_handler_until_proxy_installation(monkeypatch) -> None:
    monkeypatch.setenv("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    engine, captured = _install_fake_vllm_engine_modules(
        monkeypatch, output_handler=None
    )

    result = create_pinned_asyncllm(build_phase5e_review_candidate("a" * 40))

    assert result is engine
    assert captured["from_engine_args"]["start_engine_loop"] is False
    assert engine.closed is False


def test_engine_creation_rejects_output_handler_started_despite_deferred_flag(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    engine, captured = _install_fake_vllm_engine_modules(
        monkeypatch, output_handler=object()
    )

    with pytest.raises(Phase5ENativeRunnerError, match="output handler started"):
        create_pinned_asyncllm(build_phase5e_review_candidate("a" * 40))

    assert captured["from_engine_args"]["start_engine_loop"] is False
    assert engine.closed is True


def test_engine_creation_rejects_construction_inside_running_event_loop(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VLLM_ENABLE_V1_MULTIPROCESSING", "0")

    async def create_inside_loop() -> None:
        with pytest.raises(Phase5ENativeRunnerError, match="before entering"):
            create_pinned_asyncllm(build_phase5e_review_candidate("a" * 40))

    asyncio.run(create_inside_loop())


def test_production_evidence_source_is_never_implicitly_mocked() -> None:
    with pytest.raises(Phase5ENativeEvidenceError, match="exactly one"):
        resolve_production_evidence_source(object())


def test_production_runtime_uses_one_source_for_integration_and_evaluator(
    monkeypatch,
) -> None:
    source_seen = []
    core = type("Core", (), {})()
    manager = type("Manager", (), {})()
    block_pool = object()
    manager.block_pool = block_pool
    scheduler = type("Scheduler", (), {"kv_cache_manager": manager})()
    core.scheduler = scheduler
    resolved = type(
        "Resolved",
        (),
        {
            "engine_core": core,
            "scheduler": scheduler,
            "kv_cache_manager": manager,
            "block_pool": block_pool,
        },
    )()
    delegate = type("Delegate", (), {"engine_core": core})()
    proxy = type("Proxy", (), {"_delegate": delegate})()
    engine = type("Engine", (), {"engine_core": proxy})()

    def install(**kwargs):
        source = kwargs["event_source"]
        core.kvopt_phase5_event_source = source
        report = {
            "status": "PASS",
            "mode": "CONTROLLED_A3",
            "same_engine_core": True,
        }
        source._mark_installed(report, kwargs["integration"])
        return report

    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.resolve_pinned_inprocess_native_core",
        lambda _engine: resolved,
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.install_phase5e_a3_runtime",
        install,
    )

    def factory(source: Phase5ERuntimeEventSource):
        source_seen.append(source)
        return type("Integration", (), {"event_source": source})()

    evidence, report = install_production_a3_runtime(
        engine=engine,
        integration_factory=factory,
        clock=FakeClock(),
    )
    assert report["status"] == "PASS"
    assert len(source_seen) == 1
    assert evidence.raw_evidence() == ()


def test_production_stack_installs_proxy_before_resolving_native_core(
    monkeypatch,
) -> None:
    order = []
    engine = type("Engine", (), {"engine_core": object()})()
    resolved = type(
        "Resolved",
        (),
        {
            "engine_core": object(),
            "scheduler": object(),
            "kv_cache_manager": object(),
            "block_pool": object(),
        },
    )()

    class Integration:
        def bind_request_identity(self, **_kwargs) -> None:
            return None

    class Adapter:
        def __init__(
            self, *, engine, native_request_identity_observer, clock, **_kwargs
        ):
            order.append("adapter_proxy")
            assert isinstance(native_request_identity_observer, Integration)
            assert callable(clock)
            assert clock() == 0.0
            engine.engine_core = "installed-proxy"

    def resolve(observed_engine):
        order.append("resolve_core")
        assert observed_engine.engine_core == "installed-proxy"
        return resolved

    def install(**kwargs):
        order.append("install_runtime")
        source = kwargs["event_source"]
        report = {"status": "PASS", "same_engine_core": True}
        source._mark_installed(report, kwargs["integration"])
        return report

    def bind_pressure(**kwargs):
        order.append("bind_pressure")
        assert kwargs["resolved"] is resolved
        assert callable(kwargs["clock"])
        assert kwargs["clock"]() == 0.0

    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.AsyncLLMNativeAdapter", Adapter
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.resolve_pinned_inprocess_native_core",
        resolve,
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.install_phase5e_a3_runtime", install
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.resolve_runtime_event_reader",
        lambda _engine: lambda: (),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner._bind_pinned_native_pressure",
        bind_pressure,
    )

    evidence, report, adapter = install_production_native_stack(
        engine=engine,
        plan=build_phase5e_review_candidate("a" * 40),
        integration_factory=lambda _source: Integration(),
        clock=FakeClock(),
        run_epoch_monotonic=1.0,
    )

    assert report["status"] == "PASS"
    assert isinstance(adapter, Adapter)
    assert evidence.raw_evidence() == ()
    assert order == [
        "adapter_proxy",
        "resolve_core",
        "install_runtime",
        "bind_pressure",
    ]


def test_engine_core_production_stack_adapts_clock_protocol_to_callable(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    class Adapter:
        def __init__(self, *, clock, **_kwargs):
            observed["clock"] = clock

        def bind_native_pressure_executor(self, executor) -> None:
            observed["executor"] = executor

    class Evidence:
        def runtime_installation_report(self):
            return {"status": "PASS"}

    class Bridge:
        def __init__(self, _client) -> None:
            pass

        async def install(self, contract):
            observed["contract"] = contract
            return Evidence()

    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.AsyncLLMNativeAdapter", Adapter
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.EngineCoreUtilityBridge", Bridge
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.resolve_async_utility_client",
        lambda _engine: object(),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase5e_native_runner.validate_runtime_engine_identity",
        lambda **_kwargs: None,
    )

    async def run() -> None:
        clock = FakeClock(7.0)
        evidence, report, _adapter = await install_engine_core_production_stack(
            engine=object(),
            plan=build_phase5e_review_candidate("a" * 40),
            clock=clock,
            run_epoch_monotonic=7.0,
        )
        assert evidence.runtime_installation_report() == report
        adapter_clock = observed["clock"]
        assert callable(adapter_clock)
        assert adapter_clock() == 7.0

    asyncio.run(run())


def test_live_engine_configuration_must_equal_frozen_geometry() -> None:
    plan = build_phase5e_review_candidate("a" * 40)
    engine = type(
        "Engine",
        (),
        {
            "vllm_config": type(
                "Config",
                (),
                {
                    "scheduler_config": type("Scheduler", (), {"max_num_seqs": 4})(),
                    "model_config": type("Model", (), {"max_model_len": 32768})(),
                    "cache_config": type(
                        "Cache",
                        (),
                        {"block_size": 16, "num_gpu_blocks_override": 2048},
                    )(),
                },
            )()
        },
    )()
    validate_runtime_engine_identity(engine=engine, plan=plan)
    engine.vllm_config.cache_config.num_gpu_blocks_override = 2047
    with pytest.raises(Phase5ENativeRunnerError, match="differs from freeze"):
        validate_runtime_engine_identity(engine=engine, plan=plan)


def test_native_runner_executes_gate_cleanup_and_archive(tmp_path: Path) -> None:
    async def scenario() -> None:
        plan = build_phase5e_review_candidate("a" * 40)
        engine = _Engine()
        result = await run_phase5e_native_pipeline(
            plan=plan,
            authorization=_authorization(),
            explicit_inputs=_explicit_inputs(plan),
            engine=engine,  # type: ignore[arg-type]
            evidence_source=_Evidence(),
            output_root=tmp_path / "native-run",
            archive_path=tmp_path / "native-run.tar.gz",
            run_epoch_monotonic=0.0,
            clock=lambda: 10.0,
            sampling_factory=dict,
            adapter_factory=lambda _engine, frozen, _source, _epoch: _Adapter(frozen),
        )
        assert result["status"] == "PASS"
        assert result["g0_freeze"] == result["g8_archive"] == "PASS"
        assert result["archive_validation"]["status"] == "PASS"
        assert engine.closed is True

    asyncio.run(scenario())


def test_native_runner_archives_failed_attempt_without_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        plan = build_phase5e_review_candidate("a" * 40)
        archive = tmp_path / "failed.tar.gz"
        with pytest.raises(RuntimeError, match="frozen pressure failed"):
            await run_phase5e_native_pipeline(
                plan=plan,
                authorization=_authorization(),
                explicit_inputs=_explicit_inputs(plan),
                engine=_Engine(),  # type: ignore[arg-type]
                evidence_source=_Evidence(),
                output_root=tmp_path / "failed",
                archive_path=archive,
                run_epoch_monotonic=0.0,
                clock=lambda: 10.0,
                sampling_factory=dict,
                adapter_factory=lambda _engine, frozen, _source, _epoch: _FailingAdapter(frozen),
            )
        assert archive.is_file()

    asyncio.run(scenario())
