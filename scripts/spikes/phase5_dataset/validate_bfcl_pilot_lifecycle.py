#!/usr/bin/env python3
"""Bind BFCL pilot lifecycle events to normalized Q4 trace timestamps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_bfcl_pilot_evidence import (
    load_lifecycle_events,
    validate_lifecycle_trace_binding,
)
from kvopt.workload.phase5_dataset_processing import load_normalized_trace
from kvopt.workload.phase5_replay import canonical_sha256

EXPECTED_CASE_IDS = (
    "web_search_base_0",
    "web_search_no_snippet_0",
)


def _trace_arguments(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        case_id, separator, path = value.partition("=")
        if not separator or case_id not in EXPECTED_CASE_IDS or case_id in parsed:
            raise ValueError("trace must be one unique frozen CASE_ID=PATH binding")
        parsed[case_id] = Path(path)
    if set(parsed) != set(EXPECTED_CASE_IDS):
        raise ValueError("both frozen paired-pilot traces are required")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lifecycle-events", type=Path, required=True)
    parser.add_argument("--trace", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    traces = _trace_arguments(args.trace)
    events = load_lifecycle_events(args.lifecycle_events)
    bindings = [
        validate_lifecycle_trace_binding(
            events,
            case_id=case_id,
            trace=load_normalized_trace(traces[case_id]),
        )
        for case_id in EXPECTED_CASE_IDS
    ]
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_paired_pilot_trace_binding.v1",
        "case_ids": list(EXPECTED_CASE_IDS),
        "bindings": bindings,
        "status": (
            "PASS"
            if all(row["status"] == "PASS" for row in bindings)
            else "FAIL_CLOSED"
        ),
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    report = {**payload, "report_sha256": canonical_sha256(payload)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
