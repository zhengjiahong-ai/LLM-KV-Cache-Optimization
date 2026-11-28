from __future__ import annotations

from enum import Enum
from types import SimpleNamespace

import pytest

from kvopt.workload import phase5_official_engine_core_plugin as plugin


class _Policy(Enum):
    CONTINUUM = "continuum"


class _Manager:
    block_size = 16

    def get_computed_blocks(self, request):
        del request
        return ("blocks", 32)


class _EngineCore:
    def __init__(self) -> None:
        self.scheduler = SimpleNamespace(
            policy=_Policy.CONTINUUM, kv_cache_manager=_Manager()
        )

    def add_request(self, request, request_wave=0):
        return request, request_wave


class _Scheduler:
    def _free_request(self, request):
        return request


def _contract() -> dict[str, object]:
    return {
        "schema_version": "phase5.official_continuum_install.v1",
        "run_id": "run-1",
        "system_id": "CONTINUUM_OFFICIAL",
        "policy_id": "CONTINUUM_OFFICIAL_316A5879",
        "source_revision": plugin.OFFICIAL_REVISION,
        "request_identity_prefix": "run-1:",
    }


def test_official_plugin_is_observation_only_and_records_native_c(monkeypatch) -> None:
    monkeypatch.setattr(plugin, "validate_official_source_identity", lambda: {"x": "a" * 64})
    plugin.install_official_observer_methods(_EngineCore, _Manager, _Scheduler)
    core = _EngineCore()
    core.scheduler = _Scheduler()
    core.scheduler.policy = _Policy.CONTINUUM
    core.scheduler.kv_cache_manager = _Manager()
    result = core.kvopt_phase5_official_install(_contract())
    assert result["installation_report"]["observation_only"] is True
    request = SimpleNamespace(
        request_id="run-1:program:turn:1",
        job_id="program",
        num_tokens=64,
        block_hashes=[b"a" * 32, b"b" * 32],
    )
    core.add_request(request)
    assert core.scheduler.kv_cache_manager.get_computed_blocks(request) == ("blocks", 32)
    core.scheduler._free_request(request)
    evidence = core.kvopt_phase5_official_evidence()
    assert [row["event_type"] for row in evidence["events"]] == [
        "PHASE5_OFFICIAL_REQUEST_ADDED",
        "VLLM_NATIVE_REQUEST_OBSERVATION",
        "VLLM_PREFIX_SNAPSHOT",
    ]
    assert evidence["events"][1]["payload"]["native_cached_prefix_tokens"] == 32


def test_official_plugin_rejects_non_continuum_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(plugin, "validate_official_source_identity", dict)
    core = _EngineCore()
    core.scheduler.policy = "fcfs"
    with pytest.raises(plugin.OfficialContinuumObserverError, match="not continuum"):
        plugin._install(core, _contract())
