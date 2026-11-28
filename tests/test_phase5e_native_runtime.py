from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.continuum import FakeClock, ProgramIdentity, RetentionMode
from kvopt.profiling.experiment_events import ExperimentEvent
from kvopt.workload import phase5e_native_runtime as runtime
from kvopt.workload.phase5_dva_native_provider import DVAERNativeDecisionProvider
from kvopt.workload.phase5e_native_runtime import (
    Phase5ENativeRuntimeError,
    Phase5ERuntimeEventSource,
    install_phase5_calibration_runtime,
    install_phase5e_a3_runtime,
    validate_pinned_vllm_source_identity,
)


class _Integration:
    def __init__(self, source: Phase5ERuntimeEventSource) -> None:
        self.event_source = source
        self.snapshots = []

    def apply_pressure(self, **_kwargs: object) -> None:
        return None

    def observe_native_eviction(self, _block_id: object) -> None:
        return None

    def a3_retention_input_manifest(self) -> dict[str, object]:
        return {}

    def program_for_internal_request(self, _request_id: str) -> ProgramIdentity:
        return ProgramIdentity("p1")

    def logical_for_internal_request(self, _request_id: str) -> str:
        return "p1:turn:1"

    def observe_terminal_request_snapshot(self, *_args: object, **_kwargs: object) -> None:
        self.snapshots.append((_args, _kwargs))

    def build_dva_er_native_decision_provider(
        self, **native_objects: object
    ) -> DVAERNativeDecisionProvider:
        return DVAERNativeDecisionProvider(
            engine_core_identity="test-core",
            engine_core=native_objects["engine_core"],
            block_pool_reader=dict,
            candidate_reader=dict,
            timer_reader=dict,
        )


def _ownership() -> tuple[object, object, object, object]:
    class Manager:
        block_size = 16

        def __init__(self, block_pool: object) -> None:
            self.block_pool = block_pool

        def get_computed_blocks(self, _request: object):
            return ((), 16)

        def allocate_slots(self, request: object, *args: object, **kwargs: object):
            return request, args, kwargs

    class Scheduler:
        def __init__(self, manager: object) -> None:
            self.kv_cache_manager = manager

        def _free_request(self, _request: object) -> None:
            return None

    block_pool = object()
    manager = Manager(block_pool)
    scheduler = Scheduler(manager)
    core = SimpleNamespace(scheduler=scheduler)
    return core, scheduler, manager, block_pool


def test_runtime_event_source_assigns_stable_indices_and_detaches() -> None:
    source = Phase5ERuntimeEventSource()
    source.emit(
        ExperimentEvent.create(
            event_type="FORCED_RELEASE_DECISION_BINDING",
            timestamp=1.0,
            clock_domain="continuum_pressure",
            source="test",
            payload={"decision_id": "d1"},
        )
    )
    source.emit({"event_type": "TEST", "payload": {"value": 1}})
    first = source.snapshot()
    assert [row["event_index"] for row in first] == [0, 1]
    first[0]["event_type"] = "MUTATED"  # type: ignore[index]
    assert source.snapshot()[0]["event_type"] == "FORCED_RELEASE_DECISION_BINDING"


def test_runtime_event_source_rejects_producer_event_index() -> None:
    source = Phase5ERuntimeEventSource()
    with pytest.raises(Phase5ENativeRuntimeError, match="cannot assign"):
        source.emit({"event_index": 7, "event_type": "TEST", "payload": {}})


def test_pinned_source_identity_fails_closed_on_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "module.py"
    source.write_text("reviewed = False\n", encoding="utf-8")
    monkeypatch.setattr(
        runtime.importlib,
        "import_module",
        lambda _name: SimpleNamespace(__file__=str(source)),
    )
    with pytest.raises(Phase5ENativeRuntimeError, match="identity mismatch"):
        validate_pinned_vllm_source_identity()


def test_pinned_source_identity_returns_all_reviewed_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    files = {}
    expected = {}
    for index, module_name in enumerate(runtime.PINNED_VLLM_SOURCE_SHA256):
        path = tmp_path / f"source-{index}.py"
        path.write_text(f"identity = {index}\n", encoding="utf-8")
        files[module_name] = path
        expected[module_name] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime, "PINNED_VLLM_SOURCE_SHA256", expected)
    monkeypatch.setattr(
        runtime.importlib,
        "import_module",
        lambda name: SimpleNamespace(__file__=str(files[name])),
    )
    assert validate_pinned_vllm_source_identity() == expected


def test_runtime_install_requires_same_core_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, _scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)
    with pytest.raises(Phase5ENativeRuntimeError, match="Scheduler"):
        install_phase5e_a3_runtime(
            engine_core=core,
            scheduler=object(),
            kv_cache_manager=manager,
            block_pool=block_pool,
            integration=_Integration(source),
            clock=FakeClock(),
            event_source=source,
        )


def test_runtime_install_requires_live_a3_retention_manifest_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    integration.a3_retention_input_manifest = None  # type: ignore[method-assign]
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)

    with pytest.raises(Phase5ENativeRuntimeError, match="retention input manifest"):
        install_phase5e_a3_runtime(
            engine_core=core,
            scheduler=scheduler,
            kv_cache_manager=manager,
            block_pool=block_pool,
            integration=integration,
            clock=FakeClock(),
            event_source=source,
        )


def test_runtime_install_requires_production_dva_provider_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    integration.build_dva_er_native_decision_provider = None  # type: ignore[method-assign]
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)

    with pytest.raises(RuntimeError, match="build_dva_er_native_decision_provider"):
        install_phase5e_a3_runtime(
            engine_core=core,
            scheduler=scheduler,
            kv_cache_manager=manager,
            block_pool=block_pool,
            integration=integration,
            clock=FakeClock(),
            event_source=source,
        )
    assert not hasattr(core, "kvopt_phase5_event_source")


def test_runtime_install_rejects_provider_bound_to_another_engine_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)

    def detached_builder(**_native_objects: object) -> DVAERNativeDecisionProvider:
        return DVAERNativeDecisionProvider(
            engine_core_identity="detached-core",
            engine_core=object(),
            block_pool_reader=dict,
            candidate_reader=dict,
            timer_reader=dict,
        )

    integration.build_dva_er_native_decision_provider = detached_builder  # type: ignore[method-assign]
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)

    with pytest.raises(RuntimeError, match="not bound to the supplied EngineCore"):
        install_phase5e_a3_runtime(
            engine_core=core,
            scheduler=scheduler,
            kv_cache_manager=manager,
            block_pool=block_pool,
            integration=integration,
            clock=FakeClock(),
            event_source=source,
        )
    assert not hasattr(core, "kvopt_phase5_event_source")


def test_runtime_install_binds_source_before_controlled_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    calls = []

    def install(**kwargs: object) -> None:
        assert core.kvopt_phase5_event_source is source
        calls.append(kwargs)

    monkeypatch.setattr(
        runtime,
        "validate_pinned_vllm_source_identity",
        lambda: {"module": "a" * 64},
    )
    monkeypatch.setattr(runtime, "install_retention_hook", install)
    report = install_phase5e_a3_runtime(
        engine_core=core,
        scheduler=scheduler,
        kv_cache_manager=manager,
        block_pool=block_pool,
        integration=integration,
        clock=FakeClock(),
        event_source=source,
    )
    assert report["status"] == "PASS"
    assert report["source_sha256"] == {"module": "a" * 64}
    assert report["dva_er_production_provider"]["status"] == "READY"
    assert source.installation_report() == report
    assert calls[0]["mode"] is RetentionMode.CONTROLLED
    assert calls[0]["integration"] is integration


def test_runtime_install_rolls_back_source_when_hook_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)

    def fail(**_kwargs: object) -> None:
        raise RuntimeError("hook failed")

    monkeypatch.setattr(runtime, "install_retention_hook", fail)
    with pytest.raises(RuntimeError, match="hook failed"):
        install_phase5e_a3_runtime(
            engine_core=core,
            scheduler=scheduler,
            kv_cache_manager=manager,
            block_pool=block_pool,
            integration=_Integration(source),
            clock=FakeClock(),
            event_source=source,
        )
    assert not hasattr(core, "kvopt_phase5_event_source")
    with pytest.raises(Phase5ENativeRuntimeError, match="not attached"):
        source.installation_report()


def test_terminal_snapshot_is_captured_before_native_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    block = SimpleNamespace(
        block_id=7,
        ref_cnt=0,
        block_hash=b"hash-7",
        block_hash_num_tokens=16,
        is_null=False,
    )
    manager.get_blocks = lambda _request_id: SimpleNamespace(blocks=((block,),))
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)
    monkeypatch.setattr(runtime, "install_retention_hook", lambda **_kwargs: None)
    install_phase5e_a3_runtime(
        engine_core=core,
        scheduler=scheduler,
        kv_cache_manager=manager,
        block_pool=block_pool,
        integration=integration,
        clock=FakeClock(3.0),
        event_source=source,
    )

    scheduler._free_request(SimpleNamespace(request_id="native-r1"))

    assert len(integration.snapshots) == 1
    snapshot = integration.snapshots[0][0][0]
    assert snapshot.request_id.value == "native-r1"
    assert snapshot.block_groups[0][0].block_id == 7
    assert snapshot.block_groups[0][0].native_hash_hex == b"hash-7".hex()
    assert integration.snapshots[0][1]["observed_at"] == 3.0


def test_terminal_snapshot_preserves_real_hashless_tail_for_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    hashed = SimpleNamespace(
        block_id=7,
        ref_cnt=0,
        block_hash=b"hash-7",
        block_hash_num_tokens=16,
        is_null=False,
    )
    partial = SimpleNamespace(
        block_id=8,
        ref_cnt=0,
        block_hash=None,
        block_hash_num_tokens=None,
        is_null=False,
    )
    manager.get_blocks = lambda _request_id: SimpleNamespace(
        blocks=((hashed, partial),)
    )
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)
    monkeypatch.setattr(runtime, "install_retention_hook", lambda **_kwargs: None)
    install_phase5e_a3_runtime(
        engine_core=core,
        scheduler=scheduler,
        kv_cache_manager=manager,
        block_pool=block_pool,
        integration=integration,
        clock=FakeClock(3.0),
        event_source=source,
    )

    scheduler._free_request(SimpleNamespace(request_id="native-r1"))

    snapshot = integration.snapshots[0][0][0]
    assert snapshot.block_groups[0][0].native_hash_hex == b"hash-7".hex()
    assert snapshot.block_groups[0][1].native_hash_hex is None


@pytest.mark.parametrize(
    ("system_id", "expected_mode"),
    [
        ("NATIVE", RetentionMode.NATIVE),
        ("CONTINUUM_ADAPTED", RetentionMode.CONTROLLED),
        ("A1_ORIGINAL", RetentionMode.CONTROLLED),
        ("A3_SUFFIX", RetentionMode.CONTROLLED),
    ],
)
def test_calibration_runtime_installs_exact_project_arm(
    monkeypatch: pytest.MonkeyPatch,
    system_id: str,
    expected_mode: RetentionMode,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    integration.system_id = system_id
    integration.policy_id = f"policy-{system_id}"
    calls = []
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)
    monkeypatch.setattr(
        runtime, "install_retention_hook", lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(runtime, "install_production_provider", lambda **_kwargs: None)
    monkeypatch.setattr(
        runtime,
        "_install_terminal_snapshot_hook",
        lambda **_kwargs: (type(scheduler), scheduler._free_request),
    )
    report = install_phase5_calibration_runtime(
        system_id=system_id,
        engine_core=core,
        scheduler=scheduler,
        kv_cache_manager=manager,
        block_pool=block_pool,
        integration=integration,
        clock=FakeClock(),
        event_source=source,
    )
    assert report["system_id"] == system_id
    assert report["policy_id"] == f"policy-{system_id}"
    assert report["native_request_observation"] == (
        "PROJECT_KV_CACHE_MANAGER_GET_COMPUTED_BLOCKS"
    )
    assert calls[0]["mode"] is expected_mode


def test_calibration_native_observation_hook_records_apc_without_policy_change() -> None:
    _core, _scheduler, manager, _block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    clock = FakeClock()
    owner, original = runtime._install_native_request_observation_hook(
        kv_cache_manager=manager,
        integration=integration,
        event_source=source,
        clock=clock,
    )
    request = SimpleNamespace(
        request_id="native-1",
        num_tokens=32,
        block_hashes=[b"a" * 32, b"b" * 32],
    )
    assert manager.get_computed_blocks(request) == ((), 16)
    rows = source.snapshot()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "VLLM_NATIVE_REQUEST_OBSERVATION"
    assert rows[0]["request_id"] == "p1:turn:1"
    assert rows[0]["payload"]["native_cached_prefix_tokens"] == 16
    runtime._restore_native_request_observation_hook(owner, original)


def test_calibration_runtime_installs_dva_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, scheduler, manager, block_pool = _ownership()
    source = Phase5ERuntimeEventSource()
    integration = _Integration(source)
    integration.system_id = "DVA_ER_V1"
    integration.policy_id = "DVA_ER_V1_H60"
    monkeypatch.setattr(runtime, "validate_pinned_vllm_source_identity", dict)
    calls = []
    monkeypatch.setattr(runtime, "install_retention_hook", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(runtime, "install_production_provider", lambda **_kwargs: None)
    monkeypatch.setattr(
        runtime,
        "_install_terminal_snapshot_hook",
        lambda **_kwargs: (type(scheduler), scheduler._free_request),
    )
    report = install_phase5_calibration_runtime(
        system_id="DVA_ER_V1",
        engine_core=core,
        scheduler=scheduler,
        kv_cache_manager=manager,
        block_pool=block_pool,
        integration=integration,
        clock=FakeClock(),
        event_source=source,
    )
    assert report["system_id"] == "DVA_ER_V1"
    assert calls[0]["mode"] is RetentionMode.CONTROLLED
