"""Reseal Gate 2 with the authorized measured PrefillReload extension."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from .phase2g_a2_gate2_materialize import _sha, _write

PROFILE_PATH = (
    "docs/experiments/phase2g-a2-profile-repair/"
    "prefill-reload-profile-extended-544.json"
)


def reseal_campaign(
    *,
    original_manifest_path: Path,
    extended_profile_path: Path,
    measurement_path: Path,
    range_audit_path: Path,
    output_dir: Path,
) -> Path:
    if output_dir.exists():
        raise FileExistsError(f"repaired campaign already exists: {output_dir}")
    original_manifest_path = original_manifest_path.resolve()
    original_root = original_manifest_path.parent
    original = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    profile = json.loads(extended_profile_path.read_text(encoding="utf-8"))
    measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
    audit = json.loads(range_audit_path.read_text(encoding="utf-8"))
    if profile.get("schema") != "continuum.prefill_reload.extended_profile.v1":
        raise ValueError("repaired campaign requires the extended profile schema")
    if measurement.get("status") != "complete":
        raise ValueError("profile extension measurement is incomplete")
    if audit.get("required_profile_max_tokens") != 544:
        raise ValueError("profile range audit does not freeze 544 tokens")
    if profile["extension"]["measured_extension_points"] != [544]:
        raise ValueError("extended profile grid is not the authorized minimum")

    output_dir.mkdir(parents=True)
    trace_names = {str(row["trace"]) for row in original["scenarios"]}
    for trace_name in trace_names:
        shutil.copyfile(original_root / trace_name, output_dir / trace_name)

    runs: list[dict[str, object]] = []
    for original_row in original["runs"]:
        row = dict(original_row)
        config_path = original_root / str(row["config"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["backend_options"]["prefill_profile_path"] = PROFILE_PATH
        repaired_config_path = output_dir / str(row["config"])
        _write(repaired_config_path, config)
        row["config_sha256"] = _sha(repaired_config_path)
        runs.append(row)

    scenarios: list[dict[str, object]] = []
    for original_scenario in original["scenarios"]:
        scenario = dict(original_scenario)
        trace_path = output_dir / str(scenario["trace"])
        if _sha(trace_path) != scenario["trace_sha256"]:
            raise ValueError(f"trace changed during repair: {scenario['scenario_id']}")
        scenarios.append(scenario)

    repaired = {
        **original,
        "scenarios": scenarios,
        "runs": runs,
        "profile_range_repair": {
            "classification": (
                "PRE_EXECUTION_SUBSTRATE_COVERAGE_REPAIR_DISCOVERED_DURING_FORMAL_EXECUTION"
            ),
            "original_manifest_path": str(original_manifest_path),
            "original_manifest_sha256": _sha(original_manifest_path),
            "legacy_profile_sha256": profile["extension"]["base_profile_sha256"],
            "extended_profile_path": PROFILE_PATH,
            "extended_profile_sha256": _sha(extended_profile_path),
            "extension_measurement_sha256": _sha(measurement_path),
            "profile_range_audit_sha256": _sha(range_audit_path),
            "required_profile_max_tokens": 544,
            "legacy_points_preserved": True,
            "traces_preserved": True,
            "workload_inputs_preserved": True,
            "a2_implementation_preserved": True,
        },
    }
    manifest_path = output_dir / "manifest.json"
    _write(manifest_path, repaired)
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-manifest", type=Path, required=True)
    parser.add_argument("--extended-profile", type=Path, required=True)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--range-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    path = reseal_campaign(
        original_manifest_path=args.original_manifest,
        extended_profile_path=args.extended_profile,
        measurement_path=args.measurement,
        range_audit_path=args.range_audit,
        output_dir=args.output_dir,
    )
    print(f"wrote repaired Gate 2 campaign: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
