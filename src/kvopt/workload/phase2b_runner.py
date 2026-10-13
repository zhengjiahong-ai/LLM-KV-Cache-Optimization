"""Execute one opt-in, non-holdout Phase 2B fidelity fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from kvopt.profiling.artifacts import JsonlExperimentEventSink

from .phase2 import load_phase2_trace
from .phase2_runner import _git_dirty, _git_sha, _load_factory, _validate_config
from .phase2b_fidelity import load_fidelity_contract, validate_phase2b_preflight
from .phase2b_fidelity_runner import build_inflight_gate, execute_phase2b_trace


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_phase2b_fidelity(
    config_path: str | Path,
    *,
    output_root: str | Path,
    run_id: str,
) -> Path:
    """Preserve partial artifacts and keep execution/fidelity status separate."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id) is None:
        raise ValueError("run_id must be a safe path component")
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
    _validate_config(config)
    trace_path = config_path.parent / str(config["trace"])
    contract_path = config_path.parent / str(config.get("fidelity_contract", ""))
    trace = load_phase2_trace(trace_path)
    contract = load_fidelity_contract(contract_path)
    output = Path(output_root).resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "config.json", config)
    _write_json(output / "trace.json", trace.to_dict())
    (output / "replay.jsonl").touch()
    manifest: dict[str, object] = {
        "schema_version": "phase2b.fidelity_run.v1",
        "run_kind": contract.run_kind,
        "case_id": contract.case_id,
        "run_id": run_id,
        "execution_status": "running",
        "fidelity_qualification": "PENDING",
        "failure_reason": None,
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "platform": platform.platform(),
        "config_sha256": _sha256(config_path),
        "trace_sha256": _sha256(trace_path),
        "contract_sha256": _sha256(contract_path),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "ended_at_utc": None,
    }
    _write_json(output / "run.json", manifest)
    backend = None
    writer = JsonlExperimentEventSink(output / "events.jsonl", run_id)
    gates: list[dict[str, object]] = []
    try:
        backend = _load_factory(str(config["backend_factory"]))(config, writer)
        supported = getattr(backend, "phase2b_supported_capabilities", ())
        supported = supported() if callable(supported) else supported
        if not isinstance(supported, Sequence) or isinstance(supported, str):
            raise TypeError("backend Phase 2B capabilities must be a sequence")
        validate_phase2b_preflight(
            contract=contract,
            config=config,
            trace=trace,
            supported_capabilities=tuple(supported),
            platform_ready=True,
        )
        result = execute_phase2b_trace(
            trace,
            backend,
            seed=int(config["seed"]),
            max_in_flight=contract.constraints.max_in_flight,
            timeout_seconds=contract.constraints.timeout_seconds,
            pressure_safety_ceiling=int(config["pressure"]["safety_ceiling"]),
        )
        with (output / "replay.jsonl").open("w", encoding="utf-8") as stream:
            for row in result.submissions:
                stream.write(json.dumps(asdict(row), sort_keys=True) + "\n")
        runtime_identity: Mapping[str, object] = {
            "git_sha": manifest["git_sha"],
            "backend_revision": config["backend_revision"],
            "model": config["model"],
            "tokenizer": config["tokenizer"],
        }
        submitted_event_indices = tuple(
            record["event_index"]
            for record in (
                json.loads(line)
                for line in (output / "events.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            )
            if record.get("event_type") == "VLLM_REQUEST_SUBMITTED"
        )
        gates.append(
            build_inflight_gate(
                result,
                required_peak=contract.constraints.max_in_flight,
                source_event_indices=submitted_event_indices,
                runtime_identity=dict(runtime_identity),
            ).to_dict()
        )
        manifest["execution_status"] = "success"
        manifest["peak_inflight"] = result.peak_inflight
        manifest["submission_count"] = len(result.submissions)
        manifest["completion_count"] = len(result.completions)
        manifest["pressure_attempts"] = result.pressure_attempts
    except Exception as error:  # noqa: BLE001 - preserve arbitrary backend failure
        manifest["execution_status"] = "failed"
        manifest["failure_reason"] = f"{type(error).__name__}: {error}"
        (output / "stderr.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception as error:  # noqa: BLE001 - finalization must continue
                manifest["execution_status"] = "failed"
                manifest["failure_reason"] = (
                    f"backend close: {type(error).__name__}: {error}"
                )
        writer.close()
        manifest["event_count"] = writer.event_count
        manifest["ended_at_utc"] = datetime.now(UTC).isoformat()
        # Execution establishes only G-INFLIGHT. Native content/history/pressure
        # gates are deliberately not inferred from a successful process exit.
        manifest["fidelity_qualification"] = "NOT_DEMONSTRATED"
        _write_json(output / "run.json", manifest)
        _write_json(
            output / "fidelity-result.json",
            {
                "schema_version": "phase2b.fidelity_result.v1",
                "run_id": run_id,
                "execution_status": manifest["execution_status"],
                "fidelity_qualification": manifest["fidelity_qualification"],
                "gates": gates,
                "note": "Native evidence gates are finalized from raw events after smoke execution.",
            },
        )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)
    output = run_phase2b_fidelity(
        arguments.config,
        output_root=arguments.output_root,
        run_id=arguments.run_id,
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
