#!/usr/bin/env python3
"""Build the read-only Phase 5 SWE reserve reacquisition review package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from kvopt.workload.phase5_swe_reacquisition_review import (
    build_swe_reacquisition_review,
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-inventory", type=Path, required=True)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--sampling-frame", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite review package: {output}")

    batch = _load(args.batch_manifest)
    conversion = _load(args.conversion_report)
    existing = _load(args.existing_inventory)
    if not isinstance(batch, dict) or not isinstance(conversion, dict):
        raise TypeError("batch manifest and conversion report must be objects")
    if not isinstance(existing, dict):
        raise TypeError("existing candidate inventory must be an object")
    ordered = batch.get("ordered_instance_ids")
    if not isinstance(ordered, list):
        raise TypeError("batch manifest lacks ordered_instance_ids")

    converted = {
        str(row["instance_id"]): row
        for row in conversion.get("converted_sessions", [])
    }
    conversion_excluded = {
        str(row["instance_id"]): row
        for row in conversion.get("excluded_sessions", [])
    }
    attempt_rows = []
    conversion_rows = []
    for identity in ordered:
        run_root = args.raw_root.resolve() / identity
        run_path = run_root / "run.json"
        trajectory_paths = sorted(run_root.glob("*.traj.json"))
        sidecar_path = run_root / "acquisition-sidecar.json"
        if len(trajectory_paths) != 1:
            raise ValueError(f"{identity} must have exactly one trajectory")
        run = _load(run_path)
        if not isinstance(run, dict) or run.get("instance_id") != identity:
            raise ValueError(f"run identity mismatch: {identity}")
        attempt_rows.append(
            {
                "instance_id": identity,
                "status": run.get("status"),
                "agent_outcome": run.get("agent_outcome"),
                "agent_exit_status": run.get("agent_exit_status"),
                "run_json_sha256": _sha256(run_path),
                "trajectory_sha256": _sha256(trajectory_paths[0]),
                "sidecar_sha256": _sha256(sidecar_path),
            }
        )
        if identity in converted:
            row = converted[identity]
            record_path = Path(row["record_path"])
            if _sha256(record_path) != row["record_sha256"]:
                raise ValueError(f"converted record hash mismatch: {identity}")
            conversion_rows.append(
                {
                    "instance_id": identity,
                    "status": "CONVERTED",
                    "record_sha256": row["record_sha256"],
                }
            )
        elif identity in conversion_excluded:
            row = conversion_excluded[identity]
            conversion_rows.append(
                {
                    "instance_id": identity,
                    "status": "EXCLUDED_PRE_NORMALIZATION",
                    "reason": row["reason"],
                    "retry_authorized": row["retry_authorized"],
                }
            )
        else:
            raise ValueError(f"conversion report omits {identity}")

    qualification_rows = []
    sessions_root = args.processed_root.resolve() / "sessions"
    for session_root in sorted(sessions_root.iterdir()):
        normalized_path = session_root / "normalized-trace.json"
        token_path = session_root / "token-materialization.json"
        qualification_path = session_root / "qualification.json"
        fixtures_path = session_root / "tool-fixtures.json"
        normalized = _load(normalized_path)
        qualification = _load(qualification_path)
        if not isinstance(normalized, dict) or not isinstance(qualification, dict):
            raise TypeError(f"invalid processed Session: {session_root}")
        checks = qualification.get("checks")
        if not isinstance(checks, dict):
            raise TypeError(f"qualification checks missing: {session_root}")
        qualification_rows.append(
            {
                "program_id": normalized["program_id"],
                "session_id": normalized["session_id"],
                "trace_id": normalized["trace_id"],
                "terminal_class": qualification["terminal_class"],
                "censor_reason": qualification.get("censor_reason"),
                "qualification_status": qualification["status"],
                "qualification_checks": {
                    name.split("_", 1)[0]: value for name, value in checks.items()
                },
                "failed_rules": qualification["failed_rules"],
                "qualification_sha256": qualification["qualification_sha256"],
                "normalized_trace_file_sha256": _sha256(normalized_path),
                "token_materialization_file_sha256": _sha256(token_path),
                "tool_fixtures_file_sha256": _sha256(fixtures_path),
                "qualification_file_sha256": _sha256(qualification_path),
            }
        )

    binding_paths = {
        "existing_candidate_inventory_file_sha256": args.existing_inventory,
        "batch_manifest_file_sha256": args.batch_manifest,
        "conversion_report_file_sha256": args.conversion_report,
        "processed_collection_summary_file_sha256": (
            args.processed_root / "collection-summary.json"
        ),
        "processed_sha256_manifest_file_sha256": (
            args.processed_root / "sha256-manifest.json"
        ),
        "sampling_frame_file_sha256": args.sampling_frame,
        "authorization_file_sha256": args.authorization,
    }
    ledger, candidates, summary = build_swe_reacquisition_review(
        existing_inventory=existing,
        ordered_instance_ids=ordered,
        attempt_rows=attempt_rows,
        conversion_rows=conversion_rows,
        qualification_rows=qualification_rows,
        input_bindings={name: _sha256(path.resolve()) for name, path in binding_paths.items()},
    )

    output.mkdir(parents=True)
    files = {
        "swe-historical-reacquisition-attempt-ledger.json": ledger,
        "swe-combined-48-program-candidate-inventory.json": candidates,
        "swe-historical-reacquisition-review-summary.json": summary,
    }
    for name, value in files.items():
        _write(output / name, value)
    manifest = {
        "schema_version": "phase5.swe_reacquisition_review_manifest.v1",
        "files": {
            name: _sha256(output / name) for name in sorted(files)
        },
    }
    _write(output / "sha256-manifest.json", manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
