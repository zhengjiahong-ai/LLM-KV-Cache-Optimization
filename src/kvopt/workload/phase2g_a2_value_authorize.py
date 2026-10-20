"""Freeze the authorized A2 bounded Native value evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

A2_IMPLEMENTATION_SHA = "15a65e36604af5679987bb91d224fd20ce560e8a"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_authorization(
    *,
    repository: Path,
    campaign_manifest: Path,
    validation_report: Path,
    smoke_report: Path,
) -> dict[str, object]:
    manifest = json.loads(campaign_manifest.read_text(encoding="utf-8"))
    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
    if manifest.get("run_kind") != "A2_BOUNDED_NATIVE_VALUE_EVALUATION_V2":
        raise ValueError("authorization requires the bounded-value v2 campaign")
    if manifest.get("execution_authorized") is not False or manifest.get(
        "formal_native_execution_authorized"
    ) is not False:
        raise ValueError("source campaign must remain execution-locked")
    if manifest.get("tested_a2_implementation_git_sha") != A2_IMPLEMENTATION_SHA:
        raise ValueError("frozen A2 implementation SHA mismatch")
    if validation.get("status") != "PASS" or validation.get(
        "manifest_sha256"
    ) != _sha(campaign_manifest):
        raise ValueError("validation is not a PASS bound to the campaign")
    if smoke.get("status") != "PASS" or smoke.get("manifest_sha256") != _sha(
        campaign_manifest
    ):
        raise ValueError("smoke report is not a PASS bound to the campaign")
    if manifest.get("scenario_count") != 36 or manifest.get("planned_run_count") != 144:
        raise ValueError("bounded value campaign must contain 36 scenarios and 144 runs")
    if Counter(str(row["family"]) for row in manifest["scenarios"]) != Counter(
        {family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}
    ):
        raise ValueError("bounded value campaign must contain six scenarios per family")
    repairs = manifest.get("workload_construction_repairs")
    if repairs != {
        "f4_capacity_uses_first_pressure_resident_content": True,
        "f6_nonreturn_not_terminal_before_pressure": True,
        "old_gate2_v3_artifacts_modified": False,
    }:
        raise ValueError("workload construction repair contract is incomplete")
    profile = manifest.get("prefill_profile_binding")
    if not isinstance(profile, dict):
        raise TypeError("bounded value campaign lacks a profile binding")
    profile_path = (repository / str(profile.get("path"))).resolve()
    if repository not in profile_path.parents or not profile_path.is_file():
        raise ValueError("bounded profile path escapes or is missing")
    if _sha(profile_path) != profile.get("sha256"):
        raise ValueError("bounded profile SHA-256 mismatch")

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
        raise ValueError("authorization requires a clean working tree")

    bindings = {
        "distribution": repository
        / "configs/phase2/phase2g-a2-bounded-value-distribution-v2.json",
        "trace_contract": repository / "src/kvopt/workload/phase2.py",
        "materializer": repository
        / "src/kvopt/workload/phase2g_a2_gate2_materialize.py",
        "validator": repository / "src/kvopt/workload/phase2g_a2_gate2_validate.py",
        "authorizer": repository / "src/kvopt/workload/phase2g_a2_value_authorize.py",
        "runner": repository / "src/kvopt/workload/phase2g_a2_gate2_runner.py",
        "evaluator": repository / "src/kvopt/profiling/phase2g_a2_gate2.py",
        "smoke_evaluator": repository
        / "src/kvopt/profiling/phase2g_a2_value_smoke.py",
        "a2_native_adapter": repository / "src/kvopt/costaware/a2_native.py",
        "a2_selector": repository / "src/kvopt/costaware/a2_selector.py",
        "metal_backend": repository
        / "scripts/spikes/phase2_minimal_observability_metal.py",
    }
    return {
        "schema_version": "phase2g.a2_bounded_value_authorization.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authorization_basis": "M1_A2_BOUNDED_NATIVE_VALUE_EVALUATION_AUTHORIZED",
        "implementation_baseline_merge_commit": (
            "f1bb91773d1723ca4991742bef8939df073c54b4"
        ),
        "execution_authorized": True,
        "formal_native_execution_authorized": True,
        "campaign_manifest_path": str(campaign_manifest.resolve()),
        "campaign_manifest_sha256": _sha(campaign_manifest),
        "validation_report_sha256": _sha(validation_report),
        "smoke_report_sha256": _sha(smoke_report),
        "tested_a2_implementation_git_sha": A2_IMPLEMENTATION_SHA,
        "extended_profile_path": str(profile_path),
        "extended_profile_sha256": profile["sha256"],
        "experiment_tooling_git_sha": git_sha,
        "authorized_config_sha256": {
            str(row["run_id"]): str(row["config_sha256"])
            for row in manifest["runs"]
        },
        "authorized_trace_sha256": {
            str(row["scenario_id"]): str(row["trace_sha256"])
            for row in manifest["scenarios"]
        },
        "code_bindings": {
            name: {"path": str(path.relative_to(repository)), "sha256": _sha(path)}
            for name, path in bindings.items()
        },
        "scenario_count": 36,
        "planned_run_count": 144,
        "independent_statistical_unit": "scenario_draw",
        "runtime_repeats_are_independent": False,
        "primary_metric": "aggregate_recomputed_tokens",
        "frozen_boundaries": {
            "a0_entry_release_modified": False,
            "a2_formula_modified": False,
            "native_ownership_modified": False,
            "old_gate2_v3_modified": False,
            "a3_authorized": False,
            "b1_unlocked": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--smoke-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    record = build_authorization(
        repository=args.repository.resolve(),
        campaign_manifest=args.manifest.resolve(),
        validation_report=args.validation.resolve(),
        smoke_report=args.smoke_report.resolve(),
    )
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote A2 bounded-value authorization: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
