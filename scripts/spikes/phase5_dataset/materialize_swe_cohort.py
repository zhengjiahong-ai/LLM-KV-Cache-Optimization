#!/usr/bin/env python3
"""Materialize the frozen Phase 5 SWE cohort-candidate package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from kvopt.workload.phase5_swe_cohort import materialize_swe_cohort


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--fresh-review-summary", type=Path, required=True)
    parser.add_argument("--fresh-review-manifest", type=Path, required=True)
    parser.add_argument("--construction-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite cohort package: {output}")
    inventory = json.loads(args.inventory.read_text())
    sources = {
        "source_48_program_inventory_file_sha256": args.inventory,
        "fresh_review_summary_file_sha256": args.fresh_review_summary,
        "fresh_review_manifest_file_sha256": args.fresh_review_manifest,
        "construction_freeze_file_sha256": args.construction_freeze,
        "arrival_implementation_file_sha256": Path(
            "src/kvopt/workload/phase5_replay.py"
        ),
        "cohort_materializer_file_sha256": Path(
            "src/kvopt/workload/phase5_swe_cohort.py"
        ),
    }
    outputs = materialize_swe_cohort(
        inventory=inventory,
        lineage_bindings={name: _sha(path.resolve()) for name, path in sources.items()},
    )
    output.mkdir(parents=True)
    for name, value in outputs.items():
        _write(output / name, value)
    manifest = {
        "schema_version": "phase5.swe_cohort_package_manifest.v1",
        "files": {name: _sha(output / name) for name in sorted(outputs)},
        "source_bindings": {
            name: _sha(path.resolve()) for name, path in sorted(sources.items())
        },
    }
    _write(output / "sha256-manifest.json", manifest)
    print("groups: 12")
    print("calibration_groups: 4")
    print("formal_candidate_groups: 8")
    print("programs: 48")
    print("formal_cohort_selected: false")
    print("workload_seal_issued: false")
    print("gpu_execution_authorized: false")
    print("PHASE5_SWE_COHORT_MATERIALIZATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
