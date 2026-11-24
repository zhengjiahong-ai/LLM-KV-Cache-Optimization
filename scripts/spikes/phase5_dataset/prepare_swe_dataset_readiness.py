#!/usr/bin/env python3
"""Build the read-only SWE formal-dataset readiness and shortfall package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_dataset_processing import file_sha256
from kvopt.workload.phase5_swe_dataset_readiness import build_swe_dataset_readiness


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--sampling-frame", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--qualification-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite SWE readiness package: {output}")
    processed = args.processed_root.resolve()
    rows = []
    for session_root in sorted((processed / "sessions").iterdir()):
        normalized_path = session_root / "normalized-trace.json"
        token_path = session_root / "token-materialization.json"
        qualification_path = session_root / "qualification.json"
        fixtures_path = session_root / "tool-fixtures.json"
        normalized = _load(normalized_path)
        qualification = _load(qualification_path)
        if not isinstance(normalized, dict) or not isinstance(qualification, dict):
            raise TypeError(f"invalid Session evidence: {session_root}")
        checks = qualification.get("checks")
        if not isinstance(checks, dict):
            raise TypeError(f"qualification checks missing: {session_root}")
        rows.append(
            {
                "program_id": normalized["program_id"],
                "session_id": normalized["session_id"],
                "trace_id": normalized["trace_id"],
                "task_id": normalized["task_id"],
                "terminal_class": qualification["terminal_class"],
                "censor_reason": qualification.get("censor_reason"),
                "qualification_status": qualification["status"],
                "qualification_checks": {
                    name.split("_", 1)[0]: value for name, value in checks.items()
                },
                "failed_rules": qualification["failed_rules"],
                "qualification_sha256": qualification["qualification_sha256"],
                "source_trace_sha256": qualification["source_trace_sha256"],
                "normalized_trace_file_sha256": file_sha256(normalized_path),
                "token_materialization_file_sha256": file_sha256(token_path),
                "tool_fixtures_file_sha256": file_sha256(fixtures_path),
                "qualification_file_sha256": file_sha256(qualification_path),
                "raw_artifact_identity": normalized["provenance"]["raw_artifact_identity"],
                "raw_artifact_sha256": normalized["provenance"]["raw_artifact_sha256"],
                "source_revision": normalized["provenance"]["source_revision"],
            }
        )
    binding_paths = {
        "processed_collection_summary_file_sha256": processed / "collection-summary.json",
        "processed_sha256_manifest_file_sha256": processed / "sha256-manifest.json",
        "attempt_reconciliation_file_sha256": args.reconciliation.resolve(),
        "conversion_report_file_sha256": args.conversion_report.resolve(),
        "sampling_frame_file_sha256": args.sampling_frame.resolve(),
        "formal_protocol_file_sha256": args.protocol.resolve(),
        "qualification_contract_file_sha256": args.qualification_contract.resolve(),
    }
    candidates, exclusions, summary = build_swe_dataset_readiness(
        session_evidence=rows,
        input_bindings={name: file_sha256(path) for name, path in binding_paths.items()},
    )
    output.mkdir(parents=True)
    files = {
        "swe-formal-candidate-program-inventory.json": candidates,
        "swe-formal-exclusion-ledger.json": exclusions,
        "swe-formal-dataset-readiness.json": summary,
    }
    for name, value in files.items():
        _write(output / name, value)
    manifest = {
        path.name: file_sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "sha256-manifest.json"
    }
    _write(output / "sha256-manifest.json", manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
