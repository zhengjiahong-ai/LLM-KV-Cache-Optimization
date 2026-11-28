#!/usr/bin/env python3
"""Materialize the exact SWE Calibration plan and fail closed on readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from kvopt.workload.phase5_calibration_execution import (
    materialize_calibration_execution_manifest,
)
from kvopt.workload.phase5_calibration_freeze import materialize_calibration_freeze
from kvopt.workload.phase5_calibration_identity import audit_calibration_execution_identity
from kvopt.workload.phase5_calibration_inputs import materialize_calibration_input_index
from kvopt.workload.phase5_calibration_replay import (
    bind_calibration_replay_templates,
    materialize_calibration_replay_templates,
)


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--calibration-child",
        type=Path,
        default=Path(
            "docs/experiments/phase5-swe-cohort-data/"
            "swe-calibration-child-manifest.json"
        ),
    )
    parser.add_argument(
        "--arrival-manifest",
        type=Path,
        default=Path(
            "docs/experiments/phase5-swe-cohort-data/"
            "swe-frozen-poisson-arrival-manifest.json"
        ),
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("configs/phase5/phase5-formal-protocol-v1.json"),
    )
    parser.add_argument(
        "--system-readiness",
        type=Path,
        default=Path("configs/phase5/phase5-calibration-system-readiness-v1.json"),
    )
    parser.add_argument(
        "--candidate-inventory",
        type=Path,
        default=Path(
            "artifacts/phase5-swe-historical-reacquisition-review-v4/"
            "swe-combined-48-program-candidate-inventory.json"
        ),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        action="append",
        default=[],
        help="Private processed evidence root; may be repeated.",
    )
    parser.add_argument("--input-index-output", type=Path)
    parser.add_argument("--rematerialization-root", type=Path)
    parser.add_argument("--execution-manifest-output", type=Path)
    arguments = parser.parse_args()
    repository = arguments.repository.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else repository / path

    child_path = resolve(arguments.calibration_child)
    arrival_path = resolve(arguments.arrival_manifest)
    protocol_path = resolve(arguments.protocol)
    readiness_path = resolve(arguments.system_readiness)
    inventory_path = resolve(arguments.candidate_inventory)
    readiness = _load(readiness_path)
    systems = readiness.get("systems")
    if not isinstance(systems, dict):
        raise TypeError("system readiness lacks systems")
    architecture = readiness.get("native_execution_architecture")
    normalized = {
        system_id: {
            **row,
            "native_execution_architecture": architecture,
        }
        for system_id, row in systems.items()
        if isinstance(row, dict)
    }
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    input_index = None
    identity_audit = None
    if arguments.evidence_root:
        input_index = materialize_calibration_input_index(
            calibration_child=_load(child_path),
            candidate_inventory=_load(inventory_path),
            evidence_roots=[resolve(path) for path in arguments.evidence_root],
            rematerialization_root=(
                None
                if arguments.rematerialization_root is None
                else resolve(arguments.rematerialization_root)
            ),
        )
        identity_audit = audit_calibration_execution_identity(
            protocol=_load(protocol_path), input_index=input_index
        )
    freeze = materialize_calibration_freeze(
        calibration_child=_load(child_path),
        arrival_manifest=_load(arrival_path),
        protocol_sha256=_sha256(protocol_path),
        git_sha=git_sha,
        system_readiness=normalized,
        runner_readiness=(
            readiness.get("calibration_runner")
            if isinstance(readiness.get("calibration_runner"), dict)
            else None
        ),
        execution_identity_audit=identity_audit,
    )
    output = resolve(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    input_index_path = None
    execution_manifest_path = None
    if input_index is not None:
        input_index_path = (
            resolve(arguments.input_index_output)
            if arguments.input_index_output is not None
            else output.with_name("calibration-input-index.json")
        )
        input_index_path.parent.mkdir(parents=True, exist_ok=True)
        input_index_path.write_text(
            json.dumps(input_index, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        execution_manifest = materialize_calibration_execution_manifest(
            freeze=freeze,
            input_index=input_index,
            arrival_manifest=_load(arrival_path),
        )
        replay_templates = materialize_calibration_replay_templates(execution_manifest)
        replay_root = output.parent / "replay-templates"
        replay_root.mkdir(parents=True, exist_ok=True)
        for group_id, template in replay_templates.items():
            (replay_root / f"{group_id}.json").write_text(
                json.dumps(template, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        execution_manifest = bind_calibration_replay_templates(
            execution_manifest, replay_templates
        )
        execution_manifest_path = (
            resolve(arguments.execution_manifest_output)
            if arguments.execution_manifest_output is not None
            else output.with_name("calibration-execution-manifest.json")
        )
        execution_manifest_path.write_text(
            json.dumps(execution_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "status": freeze["status"],
        "run_count": freeze["run_count"],
        "execution_ready": freeze["execution_ready"],
        "blockers": freeze["blockers"],
        "freeze_sha256": freeze["freeze_sha256"],
        "output": str(output),
        "input_index_output": (
            None if input_index_path is None else str(input_index_path)
        ),
        "execution_manifest_output": (
            None
            if execution_manifest_path is None
            else str(execution_manifest_path)
        ),
    }, indent=2, sort_keys=True))
    return 0 if freeze["execution_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
