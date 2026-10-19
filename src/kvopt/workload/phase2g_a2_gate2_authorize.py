"""Create the M1-authorized Phase 2G A2 Gate 2 execution record."""

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
V3_AUTHORIZATION_REVIEW_MERGE_COMMIT = (
    "57a84113d590f3a4174e6ef14fdd5ede91d85f96"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_authorization(
    *, repository: Path, campaign_manifest: Path, validation_report: Path
) -> dict[str, object]:
    manifest = json.loads(campaign_manifest.read_text(encoding="utf-8"))
    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "phase2g.a2_gate2_materialization.v1":
        raise ValueError("unsupported Phase 2G A2 Gate 2 manifest")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("source manifest must remain execution-locked")
    if manifest.get("formal_native_execution_authorized") is not False:
        raise ValueError("source manifest formal execution flag must remain false")
    if manifest.get("tested_a2_implementation_git_sha") != A2_IMPLEMENTATION_SHA:
        raise ValueError("frozen A2 implementation SHA mismatch")
    if validation.get("schema_version") != "phase2g.a2_gate2_validation.v1":
        raise ValueError("unsupported Gate 2 validation report")
    if validation.get("status") != "PASS":
        raise ValueError("Gate 2 validation must pass before authorization")
    if validation.get("manifest_sha256") != _sha(campaign_manifest):
        raise ValueError("validation report is not bound to the campaign manifest")
    if manifest.get("scenario_count") != 36 or manifest.get("planned_run_count") != 144:
        raise ValueError("authorized campaign must contain 36 scenarios and 144 runs")
    repair = manifest.get("profile_range_repair")
    if not isinstance(repair, dict):
        raise TypeError("v3 authorization requires the accepted profile range repair")
    if (
        repair.get("required_profile_max_tokens") != 544
        or repair.get("legacy_points_preserved") is not True
        or repair.get("traces_preserved") is not True
        or repair.get("workload_inputs_preserved") is not True
        or repair.get("a2_implementation_preserved") is not True
    ):
        raise ValueError("v3 profile range repair contract is incomplete")
    raw_profile_path = repair.get("extended_profile_path")
    expected_profile_sha = repair.get("extended_profile_sha256")
    if not isinstance(raw_profile_path, str) or not raw_profile_path:
        raise TypeError("extended profile path must be non-empty text")
    if not isinstance(expected_profile_sha, str) or len(expected_profile_sha) != 64:
        raise TypeError("extended profile SHA-256 must be SHA-256 text")
    profile_path = (repository / raw_profile_path).resolve()
    if repository not in profile_path.parents or not profile_path.is_file():
        raise ValueError("extended profile path escapes or is missing from repository")
    if _sha(profile_path) != expected_profile_sha:
        raise ValueError("extended profile SHA-256 mismatch before authorization")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if (
        profile.get("schema") != "continuum.prefill_reload.extended_profile.v1"
        or profile.get("status") != "complete"
        or profile.get("extension", {}).get("measured_extension_points") != [544]
    ):
        raise ValueError("extended profile does not satisfy the accepted v3 contract")

    run_ids = [str(row["run_id"]) for row in manifest["runs"]]
    pair_keys = [
        (str(row["scenario_id"]), str(row["policy"]), int(row["repeat"]))
        for row in manifest["runs"]
    ]
    if len(set(run_ids)) != 144 or len(set(pair_keys)) != 144:
        raise ValueError("authorization requires 144 unique run and pairing keys")
    if Counter(str(row["family"]) for row in manifest["scenarios"]) != Counter(
        {family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}
    ):
        raise ValueError("authorization requires six scenarios in each family")

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
    if len(git_sha) != 40:
        raise ValueError("authorization requires a full experiment tooling SHA")

    bindings = {
        "distribution": repository
        / "configs/phase2/phase2g-a2-native-gate2-distribution-v1.json",
        "materializer": repository
        / "src/kvopt/workload/phase2g_a2_gate2_materialize.py",
        "validator": repository / "src/kvopt/workload/phase2g_a2_gate2_validate.py",
        "authorizer": repository / "src/kvopt/workload/phase2g_a2_gate2_authorize.py",
        "runner": repository / "src/kvopt/workload/phase2g_a2_gate2_runner.py",
        "evaluator": repository / "src/kvopt/profiling/phase2g_a2_gate2.py",
        "a2_native_adapter": repository / "src/kvopt/costaware/a2_native.py",
        "a2_selector": repository / "src/kvopt/costaware/a2_selector.py",
        "pressure_coordinator": repository / "src/kvopt/continuum/pressure.py",
        "metal_backend": repository / "scripts/spikes/phase2_minimal_observability_metal.py",
    }
    missing = [name for name, path in bindings.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"authorization binding is missing: {missing}")
    return {
        "schema_version": "phase2g.a2_gate2_authorization.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "authorization_basis": "M1_PHASE_2G_A2_NATIVE_GATE2_FORMAL_EXECUTION_AUTHORIZED",
        "authorization_review_merge_commit": V3_AUTHORIZATION_REVIEW_MERGE_COMMIT,
        "formal_native_execution_authorized": True,
        "execution_authorized": True,
        "campaign_manifest_path": str(campaign_manifest.resolve()),
        "campaign_manifest_sha256": _sha(campaign_manifest),
        "validation_report_path": str(validation_report.resolve()),
        "validation_report_sha256": _sha(validation_report),
        "tested_a2_implementation_git_sha": A2_IMPLEMENTATION_SHA,
        "extended_profile_path": str(profile_path),
        "extended_profile_sha256": expected_profile_sha,
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
            name: {
                "path": str(path.relative_to(repository)),
                "sha256": _sha(path),
            }
            for name, path in bindings.items()
        },
        "scenario_count": 36,
        "planned_run_count": 144,
        "independent_statistical_unit": "scenario_draw",
        "runtime_repeats_are_independent": False,
        "primary_metric": "aggregate_recomputed_tokens",
        "preservation_contract": {
            "preserve_success": True,
            "preserve_failure": True,
            "preserve_missingness": True,
            "preserve_not_realized": True,
            "silent_exclusion_prohibited": True,
        },
        "frozen_boundaries": {
            "a0_entry_release_modified": False,
            "a2_formula_modified": False,
            "native_ownership_modified": False,
            "a3_authorized": False,
            "b1_unlocked": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    record = build_authorization(
        repository=args.repository.resolve(),
        campaign_manifest=args.manifest.resolve(),
        validation_report=args.validation.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2G A2 Gate 2 authorization: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
