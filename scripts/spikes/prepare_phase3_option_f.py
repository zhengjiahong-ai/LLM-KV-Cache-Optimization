"""Prepare the non-executing Phase 3 Option F G0 freeze candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase3_option_f import (
    build_g0_freeze_candidate,
    finalize_g0_freeze_candidate,
    materialize_option_f_run_inputs,
)


def _reports(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema_version") == "phase3.load_calibration_run_report.v1"
        ):
            result.append(path)
    if len(result) != 40:
        raise ValueError(f"expected 40 calibration reports, found {len(result)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-seal", type=Path, required=True)
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--calibration-reports", type=Path, required=True)
    parser.add_argument("--execution-summary", type=Path, required=True)
    parser.add_argument("--formal-to-native-run-map", type=Path, required=True)
    parser.add_argument("--native-evidence-archive", type=Path, required=True)
    parser.add_argument("--analysis-archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/phase3-final-evaluation-protocol-v4.md"),
    )
    parser.add_argument(
        "--authorization",
        type=Path,
        default=Path("docs/experiments/phase3-option-f-m1-authorization.md"),
    )
    arguments = parser.parse_args()
    output = arguments.output_root.resolve()
    g0 = output / "g0"
    inputs = output / "inputs"
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    candidate = build_g0_freeze_candidate(
        cohort_seal_path=arguments.cohort_seal.resolve(),
        calibration_manifest_path=arguments.calibration_manifest.resolve(),
        report_paths=_reports(arguments.calibration_reports.resolve()),
        evidence_bindings={
            "execution_summary": arguments.execution_summary.resolve(),
            "formal_to_native_run_map": arguments.formal_to_native_run_map.resolve(),
            "native_evidence_archive": arguments.native_evidence_archive.resolve(),
            "analysis_archive": arguments.analysis_archive.resolve(),
        },
        output_dir=g0,
    )
    materialize_option_f_run_inputs(
        calibration_manifest_path=arguments.calibration_manifest.resolve(),
        classification_path=g0 / "calibration-classification.json",
        output_dir=inputs,
    )
    freeze = finalize_g0_freeze_candidate(
        g0_directory=g0,
        input_directory=inputs,
        protocol_path=arguments.protocol.resolve(),
        authorization_path=arguments.authorization.resolve(),
    )
    print("PHASE3_OPTION_F_G0_PREPARATION: PASS")
    print("g0_candidate_sha256:", candidate["g0_freeze_candidate_sha256"])
    print("g0_freeze_manifest_sha256:", freeze["sha256"])
    print("noise_runs: 30")
    print("main_runs: 240")
    print("execution_authorized: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
