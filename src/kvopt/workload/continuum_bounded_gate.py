"""Validate and authorize the frozen bounded Native campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .continuum_bounded_campaign import CAMPAIGN_SCHEMA

AUTHORIZATION_SCHEMA = "continuum.native_costaware_bounded_authorization.v1"
CODE_BINDINGS = (
    "scripts/spikes/phase2_minimal_observability_cuda.py",
    "scripts/spikes/phase2_minimal_observability_metal.py",
    "scripts/spikes/run_continuum_phase1b_validation_metal.py",
    "src/kvopt/continuum/prefill_profile.py",
    "src/kvopt/continuum/composition.py",
    "src/kvopt/continuum/replay_clock.py",
    "src/kvopt/profiling/continuum_bounded_report.py",
    "src/kvopt/workload/continuum_bounded_campaign.py",
    "src/kvopt/workload/continuum_bounded_gate.py",
    "src/kvopt/workload/continuum_bounded_pipeline.py",
    "src/kvopt/workload/continuum_bounded_preflight.py",
    "src/kvopt/workload/continuum_bounded_profile_runner.py",
    "src/kvopt/workload/continuum_bounded_runner.py",
    "src/kvopt/workload/continuum_bounded_timeline.py",
    "src/kvopt/workload/continuum_native_formal_profile.py",
    "src/kvopt/workload/continuum_w1b_profile_runner.py",
    "src/kvopt/workload/phase2_runner.py",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paired_contract(config: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(config))
    value["policy"] = "<POLICY>"
    options = value["backend_options"]
    options["phase2g_release_policy"] = "<RELEASE_POLICY>"
    options["phase2g_block_policy"] = "<BLOCK_POLICY>"
    return value


def validate_campaign(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = _load(manifest_path)
    problems: list[str] = []
    if manifest.get("schema_version") != CAMPAIGN_SCHEMA:
        problems.append("unsupported campaign schema")
    runs = manifest.get("runs")
    if not isinstance(runs, list) or len(runs) != 54:
        problems.append("campaign must contain 54 runs")
        runs = []
    root = manifest_path.parent
    run_ids: set[str] = set()
    keys: set[tuple[str, str, str, int]] = set()
    paired: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in runs:
        run_id = str(row.get("run_id", ""))
        key = (
            str(row.get("group_id", "")),
            str(row.get("pressure_regime", "")),
            str(row.get("arm", "")),
            int(row.get("repeat", 0)),
        )
        if not run_id or run_id in run_ids:
            problems.append(f"duplicate or empty run ID: {run_id!r}")
        if key in keys:
            problems.append(f"duplicate run key: {key!r}")
        run_ids.add(run_id)
        keys.add(key)
        config_path = root / str(row.get("config", ""))
        trace_path = root / str(row.get("trace", ""))
        if not config_path.is_file() or _sha(config_path) != row.get("config_sha256"):
            problems.append(f"config binding mismatch: {run_id}")
            continue
        if not trace_path.is_file() or _sha(trace_path) != row.get("trace_sha256"):
            problems.append(f"trace binding mismatch: {run_id}")
            continue
        config = _load(config_path)
        controlled = config.get("controlled_sparse_replay", {})
        if controlled.get("logical_sequence_sha256") != row.get(
            "logical_sequence_sha256"
        ):
            problems.append(f"logical sequence binding mismatch: {run_id}")
        backend_boundaries = config.get("backend_options", {}).get(
            "controlled_sparse_replay_boundaries"
        )
        expected_clock = [
            {
                "boundary_id": item["boundary_id"],
                "logical_timestamp": item["logical_timestamp"],
                "source": item["source"],
            }
            for item in controlled.get("boundaries", [])
        ]
        if backend_boundaries != expected_clock:
            problems.append(f"backend/runner logical boundaries differ: {run_id}")
        paired.setdefault(key[:2], []).append(config)
    expected_groups = {f"g{index:02d}" for index in range(1, 10)}
    observed_groups = {str(row.get("group_id", ""))[:3] for row in runs}
    if observed_groups != expected_groups:
        problems.append("campaign does not cover all nine frozen groups")
    for cell, configs in paired.items():
        if len(configs) != 3:
            problems.append(f"cell does not contain three arms: {cell}")
            continue
        contracts = {
            json.dumps(_paired_contract(config), sort_keys=True, separators=(",", ":"))
            for config in configs
        }
        if len(contracts) != 1:
            problems.append(f"cross-arm input contract differs: {cell}")
    return {
        "schema_version": "continuum.native_costaware_bounded_validation.v1",
        "status": "PASS" if not problems else "FAIL",
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha(manifest_path),
        "planned_run_count": len(runs),
        "problems": problems,
    }


def authorize_campaign(
    *, repository: Path, manifest_path: Path, validation_path: Path,
    fidelity_report_path: Path, output_path: Path,
) -> dict[str, Any]:
    repository = repository.resolve()
    validation = _load(validation_path)
    if validation.get("status") != "PASS":
        raise ValueError("bounded campaign validation has not passed")
    if validation.get("manifest_sha256") != _sha(manifest_path):
        raise ValueError("validation does not bind the current manifest")
    fidelity = _load(fidelity_report_path)
    if fidelity.get("status") != "PASS" or fidelity.get(
        "manifest_sha256"
    ) != _sha(manifest_path):
        raise ValueError("integrated Native fidelity preflight has not passed")
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("authorization requires a clean Git worktree")
    manifest = _load(manifest_path)
    root = manifest_path.resolve().parent
    code_hashes: dict[str, str] = {}
    for relative in CODE_BINDINGS:
        path = repository / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        code_hashes[relative] = _sha(path)
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "joint_freeze_complete": True,
        "measured_campaign_authorized": True,
        "experiment_tooling_git_sha": git_sha,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha(manifest_path),
        "validation_path": str(validation_path.resolve()),
        "validation_sha256": _sha(validation_path),
        "fidelity_report_path": str(fidelity_report_path.resolve()),
        "fidelity_report_sha256": _sha(fidelity_report_path),
        "profile_sha256": manifest["profile_sha256"],
        "raw_profile_sha256": manifest["raw_profile_sha256"],
        "profile_interpretation_contract_sha256": manifest[
            "profile_interpretation_contract_sha256"
        ],
        "resource_record_sha256": manifest["resource_record_sha256"],
        "config_sha256_by_run_id": {
            row["run_id"]: row["config_sha256"] for row in manifest["runs"]
        },
        "trace_sha256_by_cell": {
            row["cell_id"]: row["sha256"] for row in manifest["traces"]
        },
        "logical_sequence_sha256_by_cell": manifest[
            "logical_sequence_sha256_by_cell"
        ],
        "code_sha256": code_hashes,
        "campaign_root": str(root),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return authorization


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--repository", type=Path, required=True)
    authorize.add_argument("--manifest", type=Path, required=True)
    authorize.add_argument("--validation", type=Path, required=True)
    authorize.add_argument("--fidelity-report", type=Path, required=True)
    authorize.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        result = validate_campaign(args.manifest)
    else:
        result = authorize_campaign(
            repository=args.repository,
            manifest_path=args.manifest,
            validation_path=args.validation,
            fidelity_report_path=args.fidelity_report,
            output_path=args.output,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result.get("status", "AUTHORIZED"))
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
