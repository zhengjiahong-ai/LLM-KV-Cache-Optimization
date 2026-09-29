"""Policy-neutral Phase 2 execution and artifact lifecycle."""

from __future__ import annotations

import hashlib
import importlib
import json
import platform
import re
import subprocess
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from kvopt.profiling.artifacts import JsonlExperimentEventSink
from kvopt.profiling.experiment_events import (
    ExperimentEvent,
    ExperimentEventSink,
    NullExperimentEventSink,
)

from .phase2 import PlannedRequest, PressureStage, load_phase2_trace


class Phase2Backend(Protocol):
    """Deployment-owned adapter; it emits only facts actually observed by its backend."""

    def execute(self, request: PlannedRequest) -> None: ...

    def close(self) -> None: ...


class HardwareObservationProvider(Protocol):
    """Optional hardware-specific capability description, without mandatory counters."""

    def describe(self) -> dict[str, object]: ...


class HardwareTelemetryProvider(HardwareObservationProvider, Protocol):
    """Optional extension for raw hardware observations."""

    def observe(self) -> tuple[ExperimentEvent, ...]: ...


class PressureObservation(Protocol):
    """Monotonic control-plane counter independent of raw event persistence."""

    @property
    def forced_release_count(self) -> int: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _load_factory(reference: str):
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise ValueError("factory must be module:callable")
    module_name, name = reference.split(":")
    if not module_name or not name:
        raise ValueError("factory must be module:callable")
    factory = getattr(importlib.import_module(module_name), name)
    if not callable(factory):
        raise TypeError("factory target must be callable")
    return factory


def _git_sha() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _git_dirty() -> bool | None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True, check=False,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def _required_object(config: dict[str, object], key: str) -> dict[str, object]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"config.{key} must be an object")
    return value


def _required_text(config: dict[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"config.{key} must be non-empty text")
    return value


def _validate_config(config: dict[str, object]) -> None:
    if config.get("schema_version") != "phase2.config.v1":
        raise ValueError("unsupported config schema_version")
    for name in ("policy", "runtime_mode", "backend_factory", "backend_revision"):
        _required_text(config, name)
    for name in ("model", "tokenizer"):
        identity = _required_object(config, name)
        for field in ("name", "revision"):
            _required_text(identity, field)
    for name in ("cache", "generation", "batching", "pressure"):
        _required_object(config, name)
    seed = config.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("config.seed must be a non-negative integer")
    observe = config.get("observe", True)
    if not isinstance(observe, bool):
        raise TypeError("config.observe must be bool")
    pressure = _required_object(config, "pressure")
    ceiling = pressure.get("safety_ceiling")
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
        raise ValueError("config.pressure.safety_ceiling must be positive")
    cache = _required_object(config, "cache")
    blocks = cache.get("block_override")
    if isinstance(blocks, bool) or not isinstance(blocks, int) or blocks < 1:
        raise ValueError("config.cache.block_override must be positive")


def run_phase2(
    config_path: str | Path,
    *,
    output_root: str | Path,
    run_id: str | None = None,
    hardware_provider: HardwareObservationProvider | None = None,
) -> Path:
    """Execute one trace and preserve partial evidence if execution fails."""
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError("config must be a JSON object")
    _validate_config(config)
    trace_path = Path(_required_text(config, "trace"))
    if not trace_path.is_absolute():
        trace_path = config_path.parent / trace_path
    trace = load_phase2_trace(trace_path)
    identity = run_id or f"phase2-{uuid.uuid4().hex[:12]}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", identity) is None:
        raise ValueError("run_id must be a safe path component")
    output = Path(output_root) / identity
    output.mkdir(parents=True, exist_ok=False)
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    manifest: dict[str, object] = {
        "schema_version": "phase2.run.v1",
        "run_id": identity,
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "trace_id": trace.trace_id,
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(config_json.encode()).hexdigest(),
        "config": config,
        "seed": config["seed"],
        "backend": config["backend_factory"],
        "backend_revision": config["backend_revision"],
        "model": config["model"],
        "tokenizer": config["tokenizer"],
        "platform": platform.platform(),
        "hardware": {"availability": "unavailable", "reason": "no compatible provider"},
        "cache": config["cache"],
        "pressure": config["pressure"],
        "batching": config["batching"],
        "generation": config["generation"],
        "started_at_utc": _now(),
        "ended_at_utc": None,
        "status": "running",
        "failure_reason": None,
        "observed_forced_release_count": 0,
        "persisted_forced_release_event_count": 0,
        "pressure_selected_block_ids": [],
        "observation_availability": {
            "lifecycle": "optional backend emission",
            "forced_release": "optional approved observer emission",
            "native_apc_hit_miss": "unavailable without backend observation",
            "hardware_counters": "provider supplied" if hardware_provider else "unavailable",
        },
    }
    _save_json(output / "run.json", manifest)
    _save_json(output / "trace.json", trace.to_dict())
    backend: Phase2Backend | None = None
    writer: JsonlExperimentEventSink | None = None
    replay = None
    try:
        if hardware_provider is not None:
            manifest["hardware"] = hardware_provider.describe()
            _save_json(output / "run.json", manifest)
        writer = JsonlExperimentEventSink(output / "events.jsonl", identity)
        sink: ExperimentEventSink = writer if config.get("observe", True) else NullExperimentEventSink()
        replay = (output / "replay.jsonl").open("x", encoding="utf-8", newline="\n")
        backend = _load_factory(_required_text(config, "backend_factory"))(config, sink)
        if not callable(getattr(backend, "execute", None)):
            raise TypeError("backend must provide execute")
        for action in trace.actions():
            if isinstance(action, PlannedRequest):
                _execute(backend, action, replay)
                continue
            assert isinstance(action, PressureStage)
            ceiling = min(action.max_requests, config["pressure"]["safety_ceiling"])
            observed_before: int | None = None
            if action.stop_on_forced_release:
                _require_pressure_capability(backend)
                observed_before = _pressure_count(backend)
            for attempt in range(1, ceiling + 1):
                _execute(backend, action.request(attempt, config["seed"]), replay)
                selected = _selected_blocks(backend)
                if selected:
                    manifest["pressure_selected_block_ids"].append(list(selected))
                if action.stop_on_forced_release:
                    assert observed_before is not None
                    observed_after = _pressure_count(backend)
                    if observed_after > observed_before:
                        break
            else:
                if action.stop_on_forced_release:
                    manifest.setdefault("pressure_ceiling_reached", []).append(action.stage_id)
        manifest["status"] = "success"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["failure_reason"] = f"{type(error).__name__}: {error}"
        (output / "stderr.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if replay is not None:
            replay.close()
        if backend is not None:
            control_count = _optional_pressure_count(backend)
            if control_count is not None:
                manifest["observed_forced_release_count"] = control_count
            try:
                backend.close()
            except Exception as error:
                manifest["status"] = "failed"
                manifest["failure_reason"] = f"backend close: {type(error).__name__}: {error}"
        if writer is not None:
            manifest["persisted_forced_release_event_count"] = writer.forced_release_count
            manifest["event_count"] = writer.event_count
            if hardware_provider is not None:
                try:
                    events = _hardware_events(hardware_provider)
                    if config.get("observe", True):
                        for event in events:
                            writer.emit(event)
                        manifest["event_count"] = writer.event_count
                    manifest["hardware_telemetry"] = {
                        "availability": "available",
                        "event_count": len(events),
                        "persisted": config.get("observe", True),
                    }
                except Exception as error:
                    manifest["hardware_telemetry"] = {
                        "availability": "error",
                        "reason": f"{type(error).__name__}: {error}",
                    }
                    manifest["observation_availability"]["hardware_telemetry"] = "error"
            writer.close()
        manifest["ended_at_utc"] = _now()
        _save_json(output / "run.json", manifest)
    return output


def _execute(backend: Phase2Backend, request: PlannedRequest, replay) -> None:
    replay.write(json.dumps(request.to_dict(), sort_keys=True, allow_nan=False) + "\n")
    replay.flush()
    backend.execute(request)


def _optional_pressure_count(backend: Phase2Backend) -> int | None:
    if not hasattr(backend, "forced_release_count"):
        return None
    count = getattr(backend, "forced_release_count")
    count = count() if callable(count) else count
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise TypeError("backend forced_release_count must be a non-negative integer")
    return count


def _pressure_count(backend: Phase2Backend) -> int:
    count = _optional_pressure_count(backend)
    if count is None:
        raise RuntimeError(
            "backend missing required monotonic forced_release_count capability"
        )
    return count


def _require_pressure_capability(backend: Phase2Backend) -> None:
    _pressure_count(backend)


def _selected_blocks(backend: Phase2Backend) -> tuple[int, ...]:
    value = getattr(backend, "last_selected_block_ids", ())
    value = value() if callable(value) else value
    if value is None:
        return ()
    if isinstance(value, tuple) and all(isinstance(item, int) for item in value):
        return value
    return ()


def _hardware_events(provider: HardwareObservationProvider) -> tuple[ExperimentEvent, ...]:
    observe = getattr(provider, "observe", None)
    if observe is None:
        return ()
    if not callable(observe):
        raise TypeError("hardware provider observe must be callable")
    events = observe()
    if not isinstance(events, tuple) or not all(
        isinstance(event, ExperimentEvent) for event in events
    ):
        raise TypeError("hardware provider observe must return ExperimentEvent tuple")
    return events
