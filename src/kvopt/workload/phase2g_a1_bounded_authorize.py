"""Create the immutable Phase 2G A1 bounded execution authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_authorization(
    *,
    repository: Path,
    gate1_report: Path,
    campaign_manifest: Path,
    validation_report: Path,
) -> dict[str, object]:
    gate1 = json.loads(gate1_report.read_text(encoding="utf-8"))
    manifest = json.loads(campaign_manifest.read_text(encoding="utf-8"))
    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    if gate1.get("schema_version") != "phase2g.a1_native_gate1_report.v1":
        raise ValueError("unsupported Phase 2G Gate 1 report")
    if gate1.get("gate") != "PASS" or gate1.get("gate2_ready") is not True:
        raise ValueError("Gate 1 must pass before bounded authorization")
    if manifest.get("schema_version") != "phase2g.a1_bounded_materialization.v1":
        raise ValueError("unsupported Phase 2G bounded manifest")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("source manifest must remain execution-locked")
    if validation.get("status") != "PASS":
        raise ValueError("bounded campaign validation must pass")
    if validation.get("manifest_sha256") != _sha(campaign_manifest):
        raise ValueError("validation is not bound to the bounded manifest")
    if manifest.get("scenario_count") != 36 or manifest.get("planned_run_count") != 144:
        raise ValueError("bounded campaign cardinality mismatch")
    bindings = {
        "distribution": repository / "configs/phase2/phase2g-a1-bounded-distribution-v1.json",
        "materializer": repository / "src/kvopt/workload/phase2g_a1_bounded_materialize.py",
        "validator": repository / "src/kvopt/workload/phase2g_a1_bounded_validate.py",
        "runner": repository / "src/kvopt/workload/phase2g_a1_bounded_runner.py",
        "campaign_evaluator": repository / "src/kvopt/profiling/phase2g_a1_bounded_gate.py",
        "ingestion": repository / "src/kvopt/profiling/ingestion.py",
        "a1_native_adapter": repository / "src/kvopt/costaware/a1_native.py",
        "pressure_coordinator": repository / "src/kvopt/continuum/pressure.py",
        "metal_observation_backend": repository
        / "scripts/spikes/phase2_minimal_observability_metal.py",
    }
    missing = [name for name, path in bindings.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"authorization binding is missing: {missing}")
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    config_hashes = sorted(str(row["config_sha256"]) for row in manifest["runs"])
    if len(config_hashes) != 144 or len(set(config_hashes)) != 144:
        raise ValueError("authorization requires 144 unique config hashes")
    return {
        "schema_version": "phase2g.a1_bounded_authorization.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authorization_basis": "M1_PHASE_2G_A1_NATIVE_PILOT_AND_BOUNDED_EVALUATION_AUTHORIZED",
        "gate1_status": "PASS",
        "gate1_report_path": str(gate1_report.resolve()),
        "gate1_report_sha256": _sha(gate1_report),
        "campaign_manifest_path": str(campaign_manifest.resolve()),
        "campaign_manifest_sha256": _sha(campaign_manifest),
        "validation_report_path": str(validation_report.resolve()),
        "validation_report_sha256": _sha(validation_report),
        "git_sha": git_sha,
        "git_dirty": dirty,
        "bindings": {
            name: {
                "path": str(path.relative_to(repository)),
                "sha256": _sha(path),
            }
            for name, path in bindings.items()
        },
        "scenario_count": 36,
        "family_counts": validation["family_counts"],
        "policy_count": 2,
        "runtime_repeats": 2,
        "runtime_repeats_are_independent": False,
        "independent_statistical_unit": "scenario_draw",
        "planned_execution_count": 144,
        "primary_metric": "aggregate_recomputed_tokens",
        "authorized_config_sha256": config_hashes,
        "preservation_contract": {
            "preserve_success": True,
            "preserve_failure": True,
            "preserve_missingness": True,
            "preserve_not_realized": True,
            "silent_exclusion_prohibited": True,
        },
        "frozen_boundaries": {
            "a0_behavior_modified": False,
            "native_block_pool_modified": False,
            "a2_a3_authorized": False,
            "b1_unlocked": False,
            "h1_h2_modified": False,
        },
        "bounded_campaign_authorized": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--gate1-report", type=Path, required=True)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    authorization = build_authorization(
        repository=args.repository.resolve(),
        gate1_report=args.gate1_report.resolve(),
        campaign_manifest=args.campaign_manifest.resolve(),
        validation_report=args.validation_report.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2G A1 bounded authorization: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
