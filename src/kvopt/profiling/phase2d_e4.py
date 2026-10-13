"""Fail-closed Gate D4 evaluation for true in-flight overlap evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON must be an object: {path}")
    return value


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _one(events: list[dict[str, Any]], event_type: str, request_id: str | None = None) -> dict[str, Any] | None:
    matches = [
        row
        for row in events
        if row.get("event_type") == event_type
        and (request_id is None or row.get("request_id") == request_id)
    ]
    return matches[0] if len(matches) == 1 else None


def _run_evidence(run_dir: Path) -> dict[str, Any]:
    run = _json(run_dir / "run.json")
    config = _json(run_dir / "config.json")
    events = _events(run_dir / "events.jsonl")
    stage = config.get("phase2d_stage", {})
    reasons: list[str] = []
    if run.get("execution_status") != "success":
        reasons.append("execution did not succeed")
    if run.get("peak_inflight") != 2:
        reasons.append("observed peak_inflight is not two")
    intervals: dict[str, dict[str, Any]] = {}
    for request_id in ("e4-a:1", "e4-b:1"):
        submitted = _one(events, "VLLM_REQUEST_SUBMITTED", request_id)
        native = _one(events, "VLLM_NATIVE_REQUEST_OBSERVATION", request_id)
        completed = _one(events, "VLLM_REQUEST_COMPLETED", request_id)
        if submitted is None or native is None or completed is None:
            reasons.append(f"{request_id} lacks unique submit/native/completion evidence")
            continue
        payload = native.get("payload", {})
        admission = payload.get("native_scheduler_admission_timestamp")
        if not isinstance(admission, (int, float)):
            reasons.append(f"{request_id} lacks native scheduler admission time")
            continue
        submit_time = submitted.get("timestamp")
        completion_time = completed.get("timestamp")
        if not isinstance(submit_time, (int, float)) or not isinstance(completion_time, (int, float)):
            reasons.append(f"{request_id} has invalid submit/completion time")
            continue
        if not submit_time <= admission <= completion_time:
            reasons.append(f"{request_id} timestamps are out of order")
        intervals[request_id] = {
            "native_request_id": submitted.get("payload", {}).get("native_request_id"),
            "submitted_at": submit_time,
            "scheduler_admission_at": admission,
            "completed_at": completion_time,
            "native_hash_process_id": payload.get("native_hash_process_id"),
        }
    overlap: float | None = None
    if len(intervals) == 2:
        left, right = intervals.values()
        overlap = max(
            0.0,
            min(left["completed_at"], right["completed_at"])
            - max(left["scheduler_admission_at"], right["scheduler_admission_at"]),
        )
        if overlap <= 0:
            reasons.append("native scheduler-to-completion intervals do not overlap")
        if left["native_request_id"] == right["native_request_id"]:
            reasons.append("concurrent requests do not have distinct native identities")
        if left["native_hash_process_id"] != right["native_hash_process_id"]:
            reasons.append("concurrent requests do not share one native hash process")
    decision = _one(events, "FORCED_RELEASE_DECISION")
    selected: list[str] = []
    decision_index: int | None = None
    candidate_signature: list[tuple[Any, ...]] = []
    queue_signature: list[tuple[Any, ...]] = []
    if decision is None:
        reasons.append("exactly one forced-release decision is required")
    else:
        decision_index = decision.get("event_index")
        payload = decision.get("payload", {})
        candidates = payload.get("candidates", [])
        candidate_signature = sorted(
            (
                row.get("program_id"),
                len(row.get("block_ids", [])),
                len(row.get("initially_reclaimable_block_ids", [])),
                row.get("waiting_followup"),
            )
            for row in candidates
        )
        if {row[0] for row in candidate_signature} != {"e4-a", "e4-b"}:
            reasons.append("decision lacks the two expected logical candidates")
        if {row[2] for row in candidate_signature} != {4}:
            reasons.append("candidate marginal relief is not four blocks")
        queue_signature = [
            (row.get("native_lru_rank"), row.get("has_block_hash"))
            for row in payload.get("original_free_queue", [])
        ]
        selected = [row.get("program_id") for row in payload.get("selected_releases", [])]
        expected = stage.get("forced_first_logical_release_program_id")
        if not selected or selected[0] != expected:
            reasons.append("first logical release does not match the E4 arm")
        if len(intervals) == 2 and decision.get("timestamp") <= max(
            row["completed_at"] for row in intervals.values()
        ):
            reasons.append("pressure decision did not follow both concurrent completions")
    evictions = [row for row in events if row.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"]
    if decision_index is not None and not any(
        isinstance(row.get("event_index"), int) and row["event_index"] > decision_index
        for row in evictions
    ):
        reasons.append("no native hashed eviction follows the pressure decision")
    return_native: dict[str, dict[str, Any]] = {}
    block_size = int(config["cache"]["block_size"])
    for request_id in ("e4-a:2", "e4-b:2"):
        native = _one(events, "VLLM_NATIVE_REQUEST_OBSERVATION", request_id)
        if native is None:
            reasons.append(f"{request_id} lacks native APC evidence")
            continue
        payload = native.get("payload", {})
        cached = payload.get("native_cached_prefix_tokens")
        prompt = payload.get("native_prompt_tokens")
        if not isinstance(cached, int) or not isinstance(prompt, int) or cached < 0 or cached > prompt or cached % block_size:
            reasons.append(f"{request_id} has invalid cached-token evidence")
            continue
        return_native[request_id] = {
            "cached_prefix_tokens": cached,
            "prompt_tokens": prompt,
            "observed_recomputed_tokens": prompt - cached,
            "native_hash_process_id": payload.get("native_hash_process_id"),
        }
    content = {
        str(row.get("request_id")): row.get("payload", {}).get("submitted_token_ids_sha256")
        for row in events
        if row.get("event_type") == "BACKEND_INPUT_MATERIALIZED"
    }
    return {
        "run_id": run.get("run_id"),
        "arm": stage.get("arm"),
        "status": "VALID" if not reasons else "INVALID",
        "reasons": reasons,
        "peak_inflight": run.get("peak_inflight"),
        "request_intervals": intervals,
        "scheduler_to_completion_overlap_seconds": overlap,
        "decision_event_index": decision_index,
        "selected_logical_releases": selected,
        "candidate_signature": candidate_signature,
        "free_queue_signature": queue_signature,
        "materialized_content_digests": content,
        "return_native_observations": return_native,
        "native_hashed_eviction_count": len(evictions),
        "native_physical_victim_forced": False,
    }


def evaluate_e4(runs_root: Path) -> dict[str, Any]:
    runs = [_run_evidence(path.parent) for path in sorted(runs_root.glob("*/run.json"))]
    by_arm = {row["arm"]: row for row in runs}
    reasons: list[str] = []
    if set(by_arm) != {"release-a", "release-b"} or len(runs) != 2:
        reasons.append("exactly one release-a and one release-b run are required")
    else:
        for arm, row in by_arm.items():
            reasons.extend(f"{arm}: {value}" for value in row["reasons"])
        left, right = by_arm["release-a"], by_arm["release-b"]
        for field in (
            "candidate_signature",
            "free_queue_signature",
            "materialized_content_digests",
        ):
            if left[field] != right[field]:
                reasons.append(f"paired arms differ in {field}")
    status = "TRUE_OVERLAP_DEMONSTRATED" if not reasons else "NOT_DEMONSTRATED"
    return {
        "schema_version": "phase2d.e4_gate.v1",
        "gate": "D4",
        "status": status,
        "reasons": reasons,
        "runs": runs,
        "intervention_layer": "FIRST_LOGICAL_RETENTION_RELEASE",
        "native_physical_victim_forced": False,
        "claim_boundary": "Concurrency applicability evidence only; not proof of E3 causal effect or policy benefit.",
        "formal_claim": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = evaluate_e4(arguments.runs_root)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Gate D4 {result['status']}: {arguments.output}")
    return 0 if result["status"] == "TRUE_OVERLAP_DEMONSTRATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
