"""Execute one isolated Phase 2D E2 shared-retention fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import traceback
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from kvopt.profiling.artifacts import JsonlExperimentEventSink

from .phase2 import load_phase2_trace
from .phase2_runner import _git_dirty, _git_sha, _load_factory, _validate_config
from .phase2b_fidelity_runner import execute_phase2b_trace


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_e2(config_path: Path, *, output_root: Path, run_id: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id) is None:
        raise ValueError("run_id must be a safe path component")
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
    _validate_config(config)
    stage = config.get("phase2d_stage")
    options = config.get("backend_options")
    if not isinstance(stage, dict) or stage.get("stage") != "E2":
        raise ValueError("config is not a Phase 2D E2 fixture")
    if stage.get("forced_victim") is not None:
        raise ValueError("E2 must not force a victim")
    if not isinstance(options, dict) or options.get("phase2c_native_pilot_mode") is not True:
        raise ValueError("E2 requires the accepted segmented-content runtime mode")
    trace_path = config_path.parent / str(config["trace"])
    trace = load_phase2_trace(trace_path)
    output = output_root.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "config.json", config)
    _write_json(output / "trace.json", trace.to_dict())
    (output / "replay.jsonl").touch()
    manifest: dict[str, object] = {
        "schema_version": "phase2d.e2_run.v1",
        "run_kind": "NON_HOLDOUT_RESEARCH_PILOT",
        "stage": "E2",
        "run_id": run_id,
        "case_id": stage.get("case_id"),
        "repeat": stage.get("repeat"),
        "execution_status": "running",
        "gate_status": "PENDING_EVIDENCE_REVIEW",
        "failure_reason": None,
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "platform": platform.platform(),
        "config_sha256": _sha256(config_path),
        "trace_sha256": _sha256(trace_path),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "ended_at_utc": None,
    }
    _write_json(output / "run.json", manifest)
    writer = JsonlExperimentEventSink(output / "events.jsonl", run_id)
    backend = None
    try:
        backend = _load_factory(str(config["backend_factory"]))(config, writer)
        result = execute_phase2b_trace(
            trace,
            backend,
            seed=int(config["seed"]),
            max_in_flight=1,
            timeout_seconds=180.0,
            pressure_safety_ceiling=int(config["pressure"]["safety_ceiling"]),
        )
        with (output / "replay.jsonl").open("w", encoding="utf-8") as stream:
            for row in result.submissions:
                stream.write(json.dumps(asdict(row), sort_keys=True) + "\n")
        manifest.update(
            execution_status="success",
            submission_count=len(result.submissions),
            completion_count=len(result.completions),
            pressure_attempts=result.pressure_attempts,
        )
    except Exception as error:  # noqa: BLE001 - preserve arbitrary runtime failure
        manifest["execution_status"] = "failed"
        manifest["failure_reason"] = f"{type(error).__name__}: {error}"
        (output / "stderr.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception as error:  # noqa: BLE001
                manifest["execution_status"] = "failed"
                manifest["failure_reason"] = f"backend close: {type(error).__name__}: {error}"
        writer.close()
        manifest["event_count"] = writer.event_count
        manifest["ended_at_utc"] = datetime.now(UTC).isoformat()
        _write_json(output / "run.json", manifest)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)
    output = run_e2(arguments.config, output_root=arguments.output_root, run_id=arguments.run_id)
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
