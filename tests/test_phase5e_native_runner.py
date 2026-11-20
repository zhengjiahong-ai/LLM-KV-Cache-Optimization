from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kvopt.continuum import FakeClock
from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_gpu_conformance import (
    build_phase5e_review_candidate,
    materialize_phase5e_prompt_token_ids,
)
from kvopt.workload.phase5_native_async import PressureExecutionEvidence
from kvopt.workload.phase5e_native_evidence_source import Phase5ENativeEvidenceError
from kvopt.workload.phase5e_native_runner import (
    Phase5ENativeAuthorization,
    Phase5ENativeRunnerError,
    build_allocation_watermark_reader,
    create_pinned_asyncllm,
    install_production_a3_runtime,
    resolve_production_evidence_source,
    run_phase5e_native_pipeline,
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
        source._mark_installed(report)
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
