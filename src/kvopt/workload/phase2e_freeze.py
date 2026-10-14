"""Create the execution-locked Phase 2E joint-freeze review record."""

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


def build_freeze_candidate(
    *,
    repository: Path,
    campaign_manifest: Path,
    validation_report: Path,
) -> dict[str, object]:
    manifest = json.loads(campaign_manifest.read_text(encoding="utf-8"))
    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    if validation.get("status") != "PASS":
        raise ValueError("campaign validation must pass before freeze review")
    if validation.get("manifest_sha256") != _sha(campaign_manifest):
        raise ValueError("validation is not bound to the campaign manifest")
    bindings = {
        "measurement_contract": repository / "docs/phase2e-m4-task-a-metrics-freeze.md",
        "observation_request": repository / "docs/phase2e-m4-m6-observation-request.md",
        "capability_reconciliation": repository / "docs/phase2e-m4-t1-capability-reconciliation.md",
        "distribution": repository / "configs/phase2/phase2e-workload-distribution-v1.json",
        "materializer": repository / "src/kvopt/workload/phase2e_materialize.py",
        "validator": repository / "src/kvopt/workload/phase2e_validate.py",
        "runner": repository / "src/kvopt/workload/phase2e_runner.py",
        "gate_c_evaluator": repository / "src/kvopt/profiling/phase2e_gate.py",
        "campaign_evaluator": repository / "src/kvopt/profiling/phase2e_campaign_gate.py",
        "runtime_evidence": repository / "src/kvopt/profiling/runtime_evidence.py",
    }
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
    return {
        "schema_version": "phase2e.joint_freeze_candidate.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "PENDING_M4_JOINT_REVIEW",
        "git_sha": git_sha,
        "git_dirty": dirty,
        "m4_measurement_contract_pr": 45,
        "m4_capability_reconciliation_pr": 46,
        "bindings": {
            name: {"path": str(path.relative_to(repository)), "sha256": _sha(path)}
            for name, path in bindings.items()
        },
        "campaign_manifest_path": str(campaign_manifest.resolve()),
        "campaign_manifest_sha256": _sha(campaign_manifest),
        "validation_report_path": str(validation_report.resolve()),
        "validation_report_sha256": _sha(validation_report),
        "scenario_count": manifest["scenario_count"],
        "family_counts": validation["family_counts"],
        "independent_statistical_unit": "scenario_draw",
        "runtime_repeats": 2,
        "runtime_repeats_are_independent": False,
        "baseline_count": 2,
        "planned_execution_count": manifest["planned_run_count"],
        "execution_order_balanced": True,
        "authorized_config_sha256": sorted(
            str(row["config_sha256"]) for row in manifest["runs"]
        ),
        "known_limits": {
            "p5": "PARTIALLY_DEMONSTRATED; position claims require mapped evidence",
            "logical_owner_attribution": "NOT_OBSERVABLE",
            "eviction_to_recomputation_causality": "NOT_ESTABLISHED",
            "native_overlap": "engine-core admission-to-first-token overlap, not GPU-kernel concurrency",
            "synthetic_representativeness": "mechanism-representative, not production-distribution representative",
        },
        "prohibited_claims": [
            "tail-first correctness without mapped P5 evidence",
            "physical shared-owner attribution",
            "single-eviction causal recomputation attribution",
            "new Cost-Aware policy benefit",
        ],
        "archive_protocol": {
            "preserve_failed_runs": True,
            "preserve_missingness": True,
            "preserve_exclusions_separately": True,
            "raw_events_required": True,
            "sha256_manifest_required": True,
        },
        "joint_freeze_complete": False,
        "measured_campaign_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = build_freeze_candidate(
        repository=args.repository.resolve(),
        campaign_manifest=args.campaign_manifest.resolve(),
        validation_report=args.validation_report.resolve(),
    )
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote Phase 2E joint freeze candidate: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
