"""Build and load the frozen W1-A server-gap warm-start history."""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import pairwise
from pathlib import Path
from typing import Any

from kvopt.continuum import (
    ProgramIdentity,
    RequestIdentity,
    ServerInterRequestGapRecord,
)

SCHEMA = "continuum.w1a_server_gap_history.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_history(
    *, sample_path: Path, runs_root: Path, output_path: Path
) -> dict[str, Any]:
    sample = _load(sample_path)
    instance_ids = sample.get("instance_ids")
    if not isinstance(instance_ids, list) or len(instance_ids) != 10:
        raise ValueError("warm-start requires the frozen ten-task W1-A sample")
    records: list[dict[str, Any]] = []
    tool_durations: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for instance_id in instance_ids:
        run_dir = runs_root / str(instance_id)
        run_path = run_dir / "run.json"
        sidecar_path = run_dir / "acquisition-sidecar.json"
        if not run_path.is_file() or not sidecar_path.is_file():
            raise FileNotFoundError(f"missing W1-A history source: {instance_id}")
        run = _load(run_path)
        sidecar = _load(sidecar_path)
        if run.get("instance_id") != instance_id or sidecar.get("program_id") != instance_id:
            raise ValueError("W1-A history source identity mismatch")
        if run.get("sidecar_sha256") != _sha256(sidecar_path):
            raise ValueError("W1-A history sidecar SHA-256 mismatch")
        calls = [row for row in sidecar.get("model_calls", []) if row.get("status") == "SUCCESS"]
        if len(calls) < 2:
            raise ValueError("W1-A history source needs two successful calls")
        tool_by_request = {
            row["request_id"]: row
            for row in sidecar.get("tool_calls", [])
            if row.get("status") == "SUCCESS"
        }
        for tool in tool_by_request.values():
            start = float(tool["tool_start_monotonic_seconds"])
            end = float(tool["tool_completion_monotonic_seconds"])
            if end < start:
                raise ValueError("W1-A external tool duration is negative")
            tool_durations.append(
                {
                    "program_id": instance_id,
                    "request_id": tool["request_id"],
                    "tool_type": "mini-swe-agent-shell",
                    "start_timestamp": start,
                    "end_timestamp": end,
                    "duration_seconds": end - start,
                    "history_use": "PROVENANCE_ONLY_NOT_SERVER_GAP_SAMPLE",
                }
            )
        for previous, following in pairwise(calls):
            finish = float(previous["model_completion_monotonic_seconds"])
            arrival = float(following["model_submit_monotonic_seconds"])
            if arrival < finish:
                raise ValueError("W1-A server inter-request gap is negative")
            records.append(
                {
                    "program_id": instance_id,
                    "previous_request_id": previous["request_id"],
                    "next_request_id": following["request_id"],
                    "previous_finish_timestamp": finish,
                    "next_arrival_timestamp": arrival,
                    "duration_seconds": arrival - finish,
                    "tool_type": (
                        "mini-swe-agent-shell"
                        if previous["request_id"] in tool_by_request
                        else None
                    ),
                    "timestamp_provenance": "WRAPPER_BOUNDARY_MONOTONIC_OBSERVED",
                    "source_sidecar_sha256": _sha256(sidecar_path),
                }
            )
        sources.append(
            {
                "instance_id": instance_id,
                "run_path": str(run_path),
                "run_sha256": _sha256(run_path),
                "sidecar_path": str(sidecar_path),
                "sidecar_sha256": _sha256(sidecar_path),
                "server_gap_count": len(calls) - 1,
            }
        )
    if len(records) <= 100:
        raise ValueError("W1-A history does not exceed the frozen threshold")
    manifest = {
        "schema_version": SCHEMA,
        "scope": "INDEPENDENT_W1A_HISTORY_WARM_START_NO_KV_PREWARM",
        "source_sample_path": str(sample_path),
        "source_sample_sha256": _sha256(sample_path),
        "source_task_count": len(instance_ids),
        "source_repository_scope": "ASTROPY_ONLY",
        "duration_history_threshold": 100,
        "server_gap_sample_count": len(records),
        "external_tool_duration_count": len(tool_durations),
        "server_gap_definition": "NEXT_MODEL_SUBMIT_MINUS_PREVIOUS_MODEL_COMPLETION",
        "external_tool_duration_is_server_gap_sample": False,
        "deduplication": "ONE_CONSECUTIVE_SUCCESSFUL_CALL_PAIR_PER_SOURCE_PROGRAM",
        "future_w1c_information_included": False,
        "kv_cache_prewarms": False,
        "sources": sources,
        "server_gap_records": records,
        "external_tool_duration_records": tool_durations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_history(path: Path) -> tuple[ServerInterRequestGapRecord, ...]:
    manifest = _load(path)
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("unsupported server-gap history schema")
    rows = manifest.get("server_gap_records")
    if not isinstance(rows, list) or len(rows) != manifest.get("server_gap_sample_count"):
        raise ValueError("server-gap history count mismatch")
    if len(rows) <= int(manifest.get("duration_history_threshold", 100)):
        raise ValueError("server-gap history does not exceed the frozen threshold")
    records = tuple(
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity(str(row["program_id"])),
            previous_request_id=RequestIdentity(str(row["previous_request_id"])),
            next_request_id=RequestIdentity(str(row["next_request_id"])),
            previous_finish_timestamp=float(row["previous_finish_timestamp"]),
            next_arrival_timestamp=float(row["next_arrival_timestamp"]),
            tool_type=row.get("tool_type"),
        )
        for row in rows
    )
    for row, record in zip(rows, records, strict=True):
        if abs(float(row["duration_seconds"]) - record.duration_seconds) > 1e-12:
            raise ValueError("server-gap duration does not match timestamps")
        if row.get("timestamp_provenance") != "WRAPPER_BOUNDARY_MONOTONIC_OBSERVED":
            raise ValueError("server-gap timestamp provenance is not observed")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = materialize_history(
        sample_path=args.sample, runs_root=args.runs_root, output_path=args.output
    )
    print(
        f"wrote W1-A history: {result['server_gap_sample_count']} server gaps -> "
        f"{args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
