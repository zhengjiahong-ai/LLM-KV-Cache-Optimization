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
    parser.add_argument("--historical-w1c-root", type=Path, required=True)
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
    ranks = batch.get("candidate_ranks")
    if not isinstance(ranks, list) or len(ranks) != len(ordered):
        raise TypeError("batch manifest lacks candidate_ranks")
    for rank, identity in zip(ranks, ordered, strict=True):
        run_root = args.raw_root.resolve() / identity
        run_path = run_root / "run.json"
        trajectory_paths = sorted(run_root.glob("*.traj.json"))
        sidecar_path = run_root / "acquisition-sidecar.json"
        if len(trajectory_paths) != 1:
            raise ValueError(f"{identity} must have exactly one trajectory")
        run = _load(run_path)
        if not isinstance(run, dict) or run.get("instance_id") != identity:
            raise ValueError(f"run identity mismatch: {identity}")
        fresh_hashes = {
            "run_json_sha256": _sha256(run_path),
            "trajectory_sha256": _sha256(trajectory_paths[0]),
            "sidecar_sha256": _sha256(sidecar_path),
        }
        historical_comparisons = []
        for condition in ("S50", "S100"):
            historical_root = args.historical_w1c_root.resolve() / condition / identity
            historical_run = historical_root / "run.json"
            historical_sidecar = historical_root / "acquisition-sidecar.json"
            historical_trajectories = sorted(historical_root.glob("*.traj.json"))
            if len(historical_trajectories) != 1:
                raise ValueError(
                    f"historical {condition}/{identity} must have one trajectory"
                )
            old_hashes = {
                "run_json_sha256": _sha256(historical_run),
                "trajectory_sha256": _sha256(historical_trajectories[0]),
                "sidecar_sha256": _sha256(historical_sidecar),
            }
            historical_comparisons.append(
                {
                    "condition": condition,
                    "historical_evidence_paths": {
                        "run_json": str(historical_run),
                        "trajectory": str(historical_trajectories[0]),
                        "sidecar": str(historical_sidecar),
                    },
                    "historical_artifact_hashes": old_hashes,
                    "per_artifact_hash_match": {
                        key: fresh_hashes[key] == old_hashes[key]
                        for key in sorted(fresh_hashes)
                    },
                    "any_artifact_hash_match": any(
                        fresh_hashes[key] == old_hashes[key]
                        for key in fresh_hashes
                    ),
                }
            )
        model = run.get("model")
        dataset = run.get("dataset")
        if not isinstance(model, dict) or not isinstance(dataset, dict):
            raise TypeError(f"run model/dataset identity missing: {identity}")
        attempt_rows.append(
            {
                "instance_id": identity,
                "phase5_rank": rank,
                "attempt_id": f"phase5-swe-historical-rank-{rank:02d}:{identity}",
                "phase5_acquisition_identity": (
                    "PHASE5_HISTORICAL_CANDIDATE_FRESH_REACQUISITION:"
                    f"{identity}"
                ),
                "status": run.get("status"),
                "agent_outcome": run.get("agent_outcome"),
                "agent_exit_status": run.get("agent_exit_status"),
                "started_at_utc": run.get("started_at_utc"),
                "finished_at_utc": run.get("finished_at_utc"),
                "condition": run.get("condition"),
                "repository_git_sha": run.get("repository_git_sha"),
                "mini_swe_agent_git_sha": run.get("author_repository_git_sha"),
                "config_sha256": run.get("config_sha256"),
                "dataset_identity": dataset,
                "model_identity": model,
                "server_runtime": run.get("server_runtime"),
                "fresh_evidence_paths": {
                    "run_json": str(run_path),
                    "trajectory": str(trajectory_paths[0]),
                    "sidecar": str(sidecar_path),
                },
                **fresh_hashes,
                "old_w1c_evidence_reused": False,
                "historical_w1c_hash_comparisons": historical_comparisons,
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
                "source_trace_sha256": qualification["source_trace_sha256"],
                "raw_artifact_identity": normalized["provenance"][
                    "raw_artifact_identity"
                ],
                "raw_artifact_sha256": normalized["provenance"][
                    "raw_artifact_sha256"
                ],
                "source_revision": normalized["provenance"]["source_revision"],
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
        "historical_w1c_feasibility_report_file_sha256": (
            args.historical_w1c_root / "feasibility-report.json"
        ),
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
    lineage = output / "lineage"
    lineage.mkdir()
    lineage_sources = {
        "phase5-swe-historical-reacquisition-batch.json": args.batch_manifest,
        "phase5-swe-historical-reacquisition-authorization.json": args.authorization,
        "phase5-swe-sampling-frame-v1.json": args.sampling_frame,
    }
    for name, source in lineage_sources.items():
        (lineage / name).write_bytes(source.resolve().read_bytes())
    manifest = {
        "schema_version": "phase5.swe_reacquisition_review_manifest.v2",
        "files": {
            str(path.relative_to(output)): _sha256(path)
            for path in sorted(output.rglob("*.json"))
            if path.name != "sha256-manifest.json"
        },
    }
    _write(output / "sha256-manifest.json", manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
