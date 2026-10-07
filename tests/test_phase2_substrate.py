from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.profiling.artifacts import JsonlExperimentEventSink
from kvopt.profiling.experiment_events import (
    ExperimentEvent,
    InMemoryExperimentEventSink,
    NullExperimentEventSink,
)
from kvopt.workload.phase2 import PlannedRequest, load_phase2_trace
from kvopt.workload.phase2_smoke import SyntheticSmokeBackend
from kvopt.workload.phase2_runner import (
    REQUIRED_OBSERVATION_CAPABILITIES,
    run_phase2,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase2/smoke-config.json"
TRACE = ROOT / "configs/phase2/smoke-trace.json"


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_smoke_replay_is_identical_and_joinable_across_runs(tmp_path: Path) -> None:
    first = run_phase2(CONFIG, output_root=tmp_path, run_id="first")
    second = run_phase2(CONFIG, output_root=tmp_path, run_id="second")
    assert (first / "replay.jsonl").read_bytes() == (second / "replay.jsonl").read_bytes()
    assert (first / "trace.json").read_bytes() == (second / "trace.json").read_bytes()
    round_trip = load_phase2_trace(first / "trace.json")
    assert round_trip.trace_id == "infrastructure-smoke-v1"
    assert tuple(item.request_id for item in round_trip.requests) == (
        "agent-a:turn:1", "agent-a:turn:2", "agent-b:turn:1"
    )

    manifest = json.loads((first / "run.json").read_text(encoding="utf-8"))
    events = _records(first / "events.jsonl")
    replay = _records(first / "replay.jsonl")
    assert manifest["status"] == "success"
    assert manifest["observed_forced_release_count"] == 1
    assert manifest["hardware"]["availability"] == "unavailable"
    assert [event["event_index"] for event in events] == list(range(len(events)))
    assert all(event["clock_domain"] for event in events)
    assert [item["request_id"] for item in replay] == [
        "agent-a:turn:1", "agent-b:turn:1", "pressure:between-turns:1", "agent-a:turn:2"
    ]
    decision = next(event for event in events if event["event_type"] == "FORCED_RELEASE_DECISION")
    candidate = decision["payload"]["candidates"][0]
    release = decision["payload"]["selected_releases"][0]
    assert candidate["program_id"] == release["program_id"] == "agent-a"
    assert candidate["prefix_id"] == release["prefix_id"]
    assert candidate["initially_reclaimable_block_ids"] == release["newly_eligible_block_ids"]
    assert decision["payload"]["original_free_queue"][0]["native_lru_rank"] == 0
    assert any(
        event["event_type"] == "TURN_FINISHED" and event.get("request_id") == "agent-a:turn:2"
        for event in events
    )
    waiting = next(event for event in events if event["event_type"] == "FOLLOWUP_WAITING")
    assert waiting["request_id"] == "agent-a:turn:2"
    assert "oracle" not in json.dumps(events)


def test_observe_toggle_keeps_full_pressure_loop_identical(tmp_path: Path) -> None:
    true_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    false_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    false_config["observe"] = False
    true_config["trace"] = str((ROOT / "configs/phase2/smoke-trace.json").resolve())
    false_config["trace"] = true_config["trace"]
    true_path = tmp_path / "true.json"
    false_path = tmp_path / "false.json"
    true_path.write_text(json.dumps(true_config), encoding="utf-8")
    false_path.write_text(json.dumps(false_config), encoding="utf-8")
    first = run_phase2(true_path, output_root=tmp_path, run_id="observed")
    second = run_phase2(false_path, output_root=tmp_path, run_id="unobserved")
    first_replay = _records(first / "replay.jsonl")
    second_replay = _records(second / "replay.jsonl")
    assert first_replay == second_replay
    assert sum(item["kind"] == "pressure" for item in first_replay) == 1
    assert sum(item["kind"] == "pressure" for item in second_replay) == 1
    first_manifest = json.loads((first / "run.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "run.json").read_text(encoding="utf-8"))
    assert first_manifest["pressure_selected_block_ids"] == second_manifest["pressure_selected_block_ids"]
    assert first_manifest["observed_forced_release_count"] == 1
    assert first_manifest["persisted_forced_release_event_count"] == 1
    assert second_manifest["observed_forced_release_count"] == 1
    assert second_manifest["persisted_forced_release_event_count"] == 0
    first_selection = next(
        event["payload"]["selected_block_ids"]
        for event in _records(first / "events.jsonl")
        if event["event_type"] == "SYNTHETIC_PRESSURE_SELECTION"
    )
    assert first_selection == [1]
    assert (second / "events.jsonl").read_text(encoding="utf-8") == ""


def test_pressure_stops_at_safety_ceiling_when_no_release(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["pressure"]["safety_ceiling"] = 2
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    trace["programs"] = []
    (tmp_path / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    config["trace"] = "trace.json"
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    output = run_phase2(tmp_path / "config.json", output_root=tmp_path, run_id="ceiling")
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["pressure_ceiling_reached"] == ["between-turns"]
    assert manifest["observed_forced_release_count"] == 0
    assert len(_records(output / "replay.jsonl")) == 2


def test_backend_failure_keeps_partial_evidence(tmp_path: Path, monkeypatch) -> None:
    class FailingBackend:
        def __init__(self, _config, sink):
            self.sink = sink

        def execute(self, request):
            self.sink.emit(ExperimentEvent.create(
                event_type="OBSERVED_BEFORE_FAILURE", timestamp=1,
                clock_domain="test", source="test", payload={"request_id": request.request_id}
            ))
            raise RuntimeError("backend stopped")

        def close(self):
            pass

    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory", lambda _reference: FailingBackend
    )
    output = run_phase2(CONFIG, output_root=tmp_path, run_id="failed")
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure_reason"] == "RuntimeError: backend stopped"
    assert len(_records(output / "events.jsonl")) == 1
    assert len(_records(output / "replay.jsonl")) == 1
    assert _records(output / "replay.jsonl")[0]["request_id"] == "agent-a:turn:1"
    assert (output / "stderr.log").exists()


def test_factory_failure_still_creates_empty_replay_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory",
        lambda _reference: (_ for _ in ()).throw(ImportError("factory missing")),
    )
    output = run_phase2(CONFIG, output_root=tmp_path, run_id="factory-failed")
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure_reason"] == "ImportError: factory missing"
    assert (output / "events.jsonl").read_text(encoding="utf-8") == ""
    assert (output / "replay.jsonl").read_text(encoding="utf-8") == ""


def test_pressure_capability_missing_fails_before_pressure_requests(
    tmp_path: Path, monkeypatch
) -> None:
    class BackendWithoutPressureCapability:
        def __init__(self, _config, _sink):
            pass

        def execute(self, _request):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory",
        lambda _reference: BackendWithoutPressureCapability,
    )
    output = run_phase2(CONFIG, output_root=tmp_path, run_id="missing-pressure-capability")
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    replay = _records(output / "replay.jsonl")
    assert manifest["status"] == "failed"
    assert "missing required monotonic forced_release_count capability" in manifest[
        "failure_reason"
    ]
    assert all(item["kind"] != "pressure" for item in replay)
    assert "missing required monotonic forced_release_count capability" in (
        output / "stderr.log"
    ).read_text(encoding="utf-8")


def test_observation_toggle_does_not_change_synthetic_selection() -> None:
    trace = load_phase2_trace(TRACE)
    first_turn = next(request for request in trace.requests if request.request_id == "agent-a:turn:1")
    pressure = next(stage for stage in trace.pressure_stages if stage.stage_id == "between-turns")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    observed = InMemoryExperimentEventSink()
    unobserved = NullExperimentEventSink()
    first_backend = SyntheticSmokeBackend(config, observed)
    second_backend = SyntheticSmokeBackend(config, unobserved)
    first_backend.execute(first_turn)
    second_backend.execute(first_turn)
    first_backend.execute(pressure.request(1, 42))
    second_backend.execute(pressure.request(1, 42))
    observed_selection = next(
        event.payload["selected_block_ids"]
        for event in observed.snapshot()
        if event.event_type == "SYNTHETIC_PRESSURE_SELECTION"
    )
    unobserved_selection = second_backend.selected_block_ids[0]
    assert observed_selection == unobserved_selection
    assert tuple(event.event_type for event in observed.snapshot()).count("FORCED_RELEASE_DECISION") == 1


def test_event_sink_rejects_malformed_events_without_advancing_index(tmp_path: Path) -> None:
    with JsonlExperimentEventSink(tmp_path / "events.jsonl", "test") as sink:
        with pytest.raises(TypeError):
            sink.emit({"event_type": "BAD"})  # type: ignore[arg-type]
        sink.emit(ExperimentEvent.create(
            event_type="GOOD", timestamp=0, clock_domain="test", source="test"
        ))
        assert sink.event_count == 1
    assert _records(tmp_path / "events.jsonl")[0]["event_index"] == 0


def test_event_sink_preserves_native_request_identity_in_envelope(
    tmp_path: Path,
) -> None:
    with JsonlExperimentEventSink(tmp_path / "events.jsonl", "test") as sink:
        sink.emit(
            ExperimentEvent.create(
                event_type="VLLM_NATIVE_REQUEST_OBSERVATION",
                timestamp=1.0,
                clock_domain="engine_core_monotonic",
                source="test",
                native_request_id="native-1",
            )
        )

    assert _records(tmp_path / "events.jsonl")[0]["native_request_id"] == (
        "native-1"
    )


def test_trace_rejects_duplicate_program_identity(tmp_path: Path) -> None:
    raw = json.loads(TRACE.read_text(encoding="utf-8"))
    raw["programs"].append(raw["programs"][0])
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_phase2_trace(path)


def test_normalized_trace_rejects_decreasing_arrival_order(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "docs/experiments/phase2-m5-smoke/synthetic-smoke-v2/trace.json").read_text())
    raw["requests"][0]["planned_arrival_offset_seconds"] = 5
    raw["requests"][1]["planned_arrival_offset_seconds"] = 2
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="arrival offsets"):
        load_phase2_trace(path)


def test_normalized_trace_round_trip_is_valid(tmp_path: Path) -> None:
    trace = load_phase2_trace(ROOT / "docs/experiments/phase2-m5-smoke/synthetic-smoke-v2/trace.json")
    path = tmp_path / "round-trip.json"
    path.write_text(json.dumps(trace.to_dict()), encoding="utf-8")
    reloaded = load_phase2_trace(path)
    assert reloaded.to_dict() == trace.to_dict()


def test_fake_hardware_provider_events_are_written(tmp_path: Path) -> None:
    class FakeProvider:
        def describe(self):
            return {"availability": "available", "provider": "fake"}

        def observe(self):
            return (ExperimentEvent.create(
                event_type="HARDWARE_SAMPLE", timestamp=1.0,
                clock_domain="fake_hardware", source="fake", payload={"power_w": 12.5}
            ),)

    output = run_phase2(CONFIG, output_root=tmp_path, run_id="hardware", hardware_provider=FakeProvider())
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    events = _records(output / "events.jsonl")
    assert manifest["hardware"] == {"availability": "available", "provider": "fake"}
    assert any(event["event_type"] == "HARDWARE_SAMPLE" for event in events)


def test_failing_hardware_provider_does_not_break_finalization(tmp_path: Path) -> None:
    class FailingProvider:
        def describe(self):
            return {"availability": "available", "provider": "failing-fake"}

        def observe(self):
            raise RuntimeError("telemetry unavailable")

    output = run_phase2(
        CONFIG,
        output_root=tmp_path,
        run_id="hardware-failed",
        hardware_provider=FailingProvider(),
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["hardware_telemetry"]["availability"] == "error"
    assert "telemetry unavailable" in manifest["hardware_telemetry"]["reason"]
    assert (output / "events.jsonl").exists()
    assert (output / "run.json").exists()



def test_two_pressure_stages_use_monotonic_forced_release_count(
    tmp_path: Path, monkeypatch
) -> None:
    class CountingBackend:
        def __init__(self, _config, _sink):
            self.forced_release_count = 0

        def execute(self, request):
            if request.kind == "pressure":
                self.forced_release_count += 1

        def close(self):
            pass

    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": "two-pressure-stages",
        "programs": [],
        "pressure_stages": [
            {
                "stage_id": "first",
                "arrival_offset_seconds": 1,
                "prompt": "pressure first",
                "max_requests": 3,
                "stop_on_forced_release": True,
            },
            {
                "stage_id": "second",
                "arrival_offset_seconds": 2,
                "prompt": "pressure second",
                "max_requests": 3,
                "stop_on_forced_release": True,
            },
        ],
    }
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    (tmp_path / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    config["trace"] = "trace.json"
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory",
        lambda _reference: CountingBackend,
    )

    output = run_phase2(
        tmp_path / "config.json",
        output_root=tmp_path,
        run_id="two-pressure-stages",
    )

    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    replay = _records(output / "replay.jsonl")
    pressure_requests = [item for item in replay if item["kind"] == "pressure"]
    assert manifest["status"] == "success"
    assert len(pressure_requests) == 2
    assert [item["request_id"] for item in pressure_requests] == [
        "pressure:first:1",
        "pressure:second:1",
    ]
    assert manifest["observed_forced_release_count"] == 2
    assert manifest["persisted_forced_release_event_count"] == 0


def test_run_manifest_registers_complete_observation_capability_contract(
    tmp_path: Path,
) -> None:
    output = run_phase2(
        CONFIG,
        output_root=tmp_path,
        run_id="capability-contract",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    contract = manifest["observation_capability_contract"]
    availability = manifest["observation_availability"]

    assert contract["schema_version"] == "phase2.observation_capabilities.v1"
    assert contract["complete"] is True
    assert tuple(contract["required"]) == REQUIRED_OBSERVATION_CAPABILITIES
    assert set(REQUIRED_OBSERVATION_CAPABILITIES) <= set(availability)

    for name in REQUIRED_OBSERVATION_CAPABILITIES:
        entry = availability[name]
        assert entry["status"] in {"AVAILABLE", "UNAVAILABLE", "ERROR"}
        if entry["status"] in {"UNAVAILABLE", "ERROR"}:
            assert isinstance(entry["reason"], str)
            assert entry["reason"].strip()


def test_runner_explicitly_marks_undeclared_backend_capabilities_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class MinimalBackend:
        def __init__(self, _config, _sink):
            self.forced_release_count = 0

        def execute(self, request):
            if request.kind == "pressure":
                self.forced_release_count += 1

        def close(self):
            pass

    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory",
        lambda _reference: MinimalBackend,
    )
    output = run_phase2(
        CONFIG,
        output_root=tmp_path,
        run_id="capability-defaults",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    availability = manifest["observation_availability"]

    assert manifest["observation_capability_contract"]["complete"] is True
    assert availability["recomputed_prefill_tokens"] == {
        "status": "UNAVAILABLE",
        "reason": "backend did not declare this capability",
    }
    assert availability["native_block_content_identity"] == {
        "status": "UNAVAILABLE",
        "reason": "backend did not declare this capability",
    }


def test_runner_persists_final_data_driven_backend_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class DynamicBackend:
        def __init__(self, _config, _sink):
            self.forced_release_count = 0
            self.observation_capabilities = {
                "recomputed_prefill_tokens": {
                    "status": "UNAVAILABLE",
                    "reason": "no completed observation",
                }
            }

        def execute(self, request):
            self.observation_capabilities["recomputed_prefill_tokens"] = {
                "status": "AVAILABLE",
                "reason": "direct native evidence observed",
            }
            if request.kind == "pressure":
                self.forced_release_count += 1

        def close(self):
            pass

    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory",
        lambda _reference: DynamicBackend,
    )
    output = run_phase2(
        CONFIG,
        output_root=tmp_path,
        run_id="dynamic-capability",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))

    assert manifest["observation_availability"][
        "recomputed_prefill_tokens"
    ] == {
        "status": "AVAILABLE",
        "reason": "direct native evidence observed",
    }


def test_invalid_backend_capability_declaration_fails_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class InvalidCapabilityBackend:
        observation_capabilities = {
            "native_apc_hit_miss": {
                "status": "UNAVAILABLE",
                "reason": None,
            }
        }

        def __init__(self, _config, _sink):
            self.forced_release_count = 0

        def execute(self, _request):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        "kvopt.workload.phase2_runner._load_factory",
        lambda _reference: InvalidCapabilityBackend,
    )
    output = run_phase2(
        CONFIG,
        output_root=tmp_path,
        run_id="invalid-capability",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))

    assert manifest["status"] == "failed"
    assert manifest["observation_capability_contract"]["complete"] is False
    assert "UNAVAILABLE capability requires a non-empty reason" in manifest[
        "failure_reason"
    ]
