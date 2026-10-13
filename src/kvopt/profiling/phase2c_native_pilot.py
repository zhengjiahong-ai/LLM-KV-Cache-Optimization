"""Evaluate Phase 2C native-pilot topology claims from raw events only."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON document must be an object: {path}")
    return value


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _hash_lcp(left: Sequence[object], right: Sequence[object]) -> int:
    count = 0
    for left_hash, right_hash in zip(left, right, strict=False):
        if left_hash != right_hash:
            break
        count += 1
    return count


def evaluate_pilot_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    run = _read_json(run_dir / "run.json")
    config = _read_json(run_dir / "config.json")
    pilot = config.get("phase2c_pilot")
    if not isinstance(pilot, dict):
        raise TypeError("run config lacks phase2c_pilot metadata")
    events = _events(run_dir / "events.jsonl")
    materialized = {
        row.get("request_id"): row
        for row in events
        if row.get("event_type") == "BACKEND_INPUT_MATERIALIZED"
    }
    observations = {
        row.get("request_id"): row
        for row in events
        if row.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
    }
    rows: list[dict[str, Any]] = []
    request_statuses: list[str] = []
    expected = pilot.get("expected_requests")
    if not isinstance(expected, list):
        raise TypeError("pilot expected_requests must be an array")
    process_ids: set[str] = set()
    for request in expected:
        if not isinstance(request, dict):
            raise TypeError("expected request must be an object")
        request_id = str(request["request_id"])
        eligible = int(request["eligible_prefix_tokens"])
        submitted = materialized.get(request_id)
        native = observations.get(request_id)
        status = "PASS"
        reason = "native content relation and APC outcome match the frozen case"
        outcome: str | None = None
        actual_lcp_tokens: int | None = None
        source_indices: list[int] = []
        if submitted is None or native is None:
            status = "NOT_OBSERVABLE"
            reason = "submitted token identity or native APC observation is missing"
        else:
            source_indices.extend([int(submitted["event_index"]), int(native["event_index"])])
            submitted_payload = submitted.get("payload", {})
            native_payload = native.get("payload", {})
            block_size = native_payload.get("native_hash_block_size")
            hashes = native_payload.get("native_apc_block_hashes")
            cached = native_payload.get("native_cached_prefix_tokens")
            process_id = native_payload.get("native_hash_process_id")
            if isinstance(process_id, str):
                process_ids.add(process_id)
            if (
                submitted_payload.get("submitted_prefix_token_ids_sha256") is None
                or not isinstance(block_size, int)
                or not isinstance(hashes, list)
                or not isinstance(cached, int)
            ):
                status = "NOT_OBSERVABLE"
                reason = "required materialized digest or native APC fields are missing"
            elif submitted_payload.get("prefix_segments") != request.get("segments"):
                status = "FAIL"
                reason = "materialized content segments differ from the frozen request"
            elif eligible == 0:
                outcome = "NO_REUSE_ELIGIBLE_PREFIX"
                actual_lcp_tokens = 0
                if cached != 0:
                    status = "FAIL"
                    reason = "first ineligible request unexpectedly reported cached prefix"
            else:
                reference_id = str(request["lcp_with"])
                reference_native = observations.get(reference_id)
                reference_submitted = materialized.get(reference_id)
                if reference_native is None or reference_submitted is None:
                    status = "NOT_OBSERVABLE"
                    reason = "referenced prior request evidence is missing"
                else:
                    reference_payload = reference_native.get("payload", {})
                    reference_materialized_payload = reference_submitted.get("payload", {})
                    reference_hashes = reference_payload.get("native_apc_block_hashes")
                    reference_process = reference_payload.get("native_hash_process_id")
                    if not isinstance(reference_hashes, list):
                        status = "NOT_OBSERVABLE"
                        reason = "referenced native hash chain is missing"
                    elif reference_process != process_id:
                        status = "FAIL"
                        reason = "content relation crosses native hash processes"
                    else:
                        submitted_digest = submitted_payload.get(
                            "submitted_prefix_token_ids_sha256"
                        )
                        reference_digest = reference_materialized_payload.get(
                            "submitted_prefix_token_ids_sha256"
                        )
                        current_tokens = sum(int(segment[1]) for segment in request["segments"])
                        reference_request = next(
                            row for row in expected if row["request_id"] == reference_id
                        )
                        reference_tokens = sum(
                            int(segment[1]) for segment in reference_request["segments"]
                        )
                        exact_relation = eligible == current_tokens == reference_tokens
                        if exact_relation and submitted_digest != reference_digest:
                            status = "FAIL"
                            reason = "declared exact prefixes have different submitted digests"
                        elif not exact_relation and submitted_digest == reference_digest:
                            status = "FAIL"
                            reason = "declared non-exact prefixes have the same submitted digest"
                        actual_lcp_tokens = _hash_lcp(reference_hashes, hashes) * block_size
                        expected_blocks = eligible // block_size
                        if _hash_lcp(reference_hashes, hashes) != expected_blocks:
                            status = "FAIL"
                            reason = "native hash-chain LCP differs from frozen content LCP"
                        if cached == 0:
                            outcome = "MISS"
                        elif cached >= eligible:
                            outcome = "FULL_HIT"
                        else:
                            outcome = "PARTIAL_HIT"
            rows.append(
                {
                    "request_id": request_id,
                    "reference_request_id": request.get("lcp_with"),
                    "eligible_prefix_tokens": eligible,
                    "actual_native_lcp_tokens": actual_lcp_tokens,
                    "native_cached_prefix_tokens": (
                        None
                        if native is None
                        else native.get("payload", {}).get("native_cached_prefix_tokens")
                    ),
                    "apc_outcome": outcome,
                    "status": status,
                    "reason": reason,
                    "source_event_indices": source_indices,
                }
            )
            request_statuses.append(status)
    pressure_status = "NOT_APPLICABLE"
    pressure_reason = "case has no controlled native allocation pressure"
    pressure_indices: list[int] = []
    if pilot.get("pressure") == "controlled_native_allocation":
        releases = [row for row in events if row.get("event_type") == "FORCED_RELEASE_DECISION"]
        evictions = [
            row
            for row in events
            if row.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
            and row.get("payload", {}).get("hash_removed_after") is True
        ]
        final_request_id = str(expected[-1]["request_id"])
        final_observation = observations.get(final_request_id)
        valid_windows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if final_observation is not None:
            final_index = int(final_observation["event_index"])
            final_process = final_observation.get("payload", {}).get("native_hash_process_id")
            for release in releases:
                release_index = int(release["event_index"])
                for eviction in evictions:
                    eviction_index = int(eviction["event_index"])
                    eviction_process = eviction.get("payload", {}).get("native_hash_process_id")
                    if (
                        release_index < eviction_index < final_index
                        and eviction_process == final_process
                    ):
                        valid_windows.append((release, eviction))
        if valid_windows and final_observation is not None:
            release, eviction = valid_windows[0]
            pressure_status = "PASS"
            pressure_reason = (
                "ordered release, native hash cleanup, and subsequent APC observation "
                "occurred in one native hash process; no content-level attribution claimed"
            )
            pressure_indices = [
                int(release["event_index"]),
                int(eviction["event_index"]),
                int(final_observation["event_index"]),
            ]
        else:
            pressure_status = "NOT_DEMONSTRATED"
            pressure_reason = (
                "no same-process release < native hashed eviction < return observation window"
            )

    if run.get("execution_status") != "success" or "FAIL" in request_statuses:
        overall = "FAIL"
    elif "NOT_OBSERVABLE" in request_statuses:
        overall = "NOT_OBSERVABLE"
    elif pressure_status == "NOT_DEMONSTRATED":
        overall = "NOT_DEMONSTRATED"
    elif len(process_ids) != 1:
        overall = "FAIL"
    else:
        overall = "PASS"
    return {
        "schema_version": "phase2c.native_pilot_run_audit.v1",
        "run_id": run.get("run_id"),
        "case_id": pilot.get("case_id"),
        "topology": pilot.get("topology"),
        "repeat": pilot.get("repeat"),
        "execution_status": run.get("execution_status"),
        "gate_status": overall,
        "native_hash_process_ids": sorted(process_ids),
        "requests": rows,
        "pressure_gate": {
            "status": pressure_status,
            "reason": pressure_reason,
            "source_event_indices": pressure_indices,
        },
    }


def build_pilot_report(runs_root: Path) -> dict[str, Any]:
    audits = [evaluate_pilot_run(path.parent) for path in sorted(runs_root.glob("*/run.json"))]
    by_topology: dict[str, list[str]] = {}
    for audit in audits:
        by_topology.setdefault(str(audit["topology"]), []).append(str(audit["gate_status"]))
    topology_results = []
    for topology, statuses in sorted(by_topology.items()):
        if "FAIL" in statuses:
            status = "FAIL"
        elif "NOT_OBSERVABLE" in statuses:
            status = "NOT_OBSERVABLE"
        elif "NOT_DEMONSTRATED" in statuses:
            status = "NOT_DEMONSTRATED"
        elif statuses and all(value == "PASS" for value in statuses):
            status = "PASS"
        else:
            status = "NOT_DEMONSTRATED"
        topology_results.append({"topology": topology, "status": status, "run_statuses": statuses})
    return {
        "schema_version": "phase2c.native_pilot_report.v1",
        "run_kind": "NON_HOLDOUT_NATIVE_PILOT",
        "run_count": len(audits),
        "topologies": topology_results,
        "runs": audits,
        "formal_claim": False,
        "cost_aware_method_claim": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_pilot_report(arguments.runs_root)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2C native pilot report: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
