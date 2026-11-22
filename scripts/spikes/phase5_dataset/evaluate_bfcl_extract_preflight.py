#!/usr/bin/env python3
"""Render the bounded BFCL Extract pre-call decision without network access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_bfcl_extract_preflight import (
    evaluate_extract_preflight,
)
from kvopt.workload.phase5_dataset_processing import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review = json.loads(args.input.read_text(encoding="utf-8"))
    report = evaluate_extract_preflight(review)
    args.output.mkdir(parents=True, exist_ok=False)
    report_path = args.output / "preflight-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "input_path": str(args.input),
        "input_sha256": file_sha256(args.input),
        "preflight_report_sha256": file_sha256(report_path),
    }
    (args.output / "sha256-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_SINGLE_CALLS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
