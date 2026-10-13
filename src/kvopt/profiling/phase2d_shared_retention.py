"""Read-only Phase 2D shared-retention feasibility audit."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _candidate_key(candidate: Mapping[str, object]) -> tuple[str, str]:
    return str(candidate.get("program_id")), str(candidate.get("prefix_id"))


def _latest_prefix_snapshot(
    events: Sequence[Mapping[str, object]],
    *,
    decision_index: int,
    program_id: str,
    prefix_id: str,
) -> Mapping[str, object] | None:
    matches = [
        event
        for event in events
        if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT"
        and int(event.get("event_index", -1)) < decision_index
        and event.get("program_id") == program_id
        and event.get("prefix_id") == prefix_id
    ]
    return max(matches, key=lambda row: int(row["event_index"]), default=None)


def _mapping_for_candidate(
    events: Sequence[Mapping[str, object]],
    candidate: Mapping[str, object],
    *,
    decision_index: int,
) -> dict[str, Any]:
    program_id, prefix_id = _candidate_key(candidate)
    snapshot = _latest_prefix_snapshot(
        events,
        decision_index=decision_index,
        program_id=program_id,
        prefix_id=prefix_id,
    )
    result: dict[str, Any] = {
        "program_id": program_id,
        "prefix_id": prefix_id,
        "block_count": len(candidate.get("block_ids", [])),
        "initially_reclaimable_block_count": len(
            candidate.get("initially_reclaimable_block_ids", [])
        ),
        "mapping_status": "NOT_OBSERVABLE",
        "mapping_reason": "no prior matching VLLM_PREFIX_SNAPSHOT",
        "prefix_snapshot_event_index": None,
        "native_hash_process_id": None,
        "blocks": [],
    }
    if snapshot is None:
        return result
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        result["mapping_reason"] = "prefix snapshot payload is not an object"
        return result
    candidate_blocks = candidate.get("block_ids")
    snapshot_blocks = payload.get("block_ids")
    hashes = payload.get("ordered_native_hashes")
    cache_keys = payload.get("ordered_native_cache_keys")
    process_id = payload.get("native_hash_process_id")
    if (
        not isinstance(candidate_blocks, list)
        or not isinstance(snapshot_blocks, list)
        or not isinstance(hashes, list)
        or not isinstance(cache_keys, list)
        or not isinstance(process_id, str)
        or not process_id
    ):
        result["mapping_reason"] = "prefix snapshot lacks block/hash/process fields"
        return result
    if candidate_blocks != snapshot_blocks:
        result["mapping_reason"] = "decision candidate blocks differ from latest snapshot"
        return result
    if not (len(candidate_blocks) == len(hashes) == len(cache_keys)):
        result["mapping_reason"] = "block/hash/cache-key lengths differ"
        return result
    snapshot_index = int(snapshot["event_index"])
    invalidated = {
        event.get("payload", {}).get("block_id")
        for event in events
        if snapshot_index < int(event.get("event_index", -1)) < decision_index
        and event.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
        and event.get("payload", {}).get("native_hash_process_id") == process_id
    }
    if invalidated.intersection(candidate_blocks):
        result["mapping_reason"] = "mapped physical block was evicted before decision"
        return result
    result.update(
        mapping_status="OBSERVABLE",
        mapping_reason="latest pre-decision block/hash/process mapping is complete",
        prefix_snapshot_event_index=snapshot_index,
        native_hash_process_id=process_id,
        blocks=[
            {
                "block_id": block_id,
                "native_hash": native_hash,
                "native_cache_key": cache_key,
            }
            for block_id, native_hash, cache_key in zip(
                candidate_blocks, hashes, cache_keys, strict=True
            )
        ],
    )
    return result


def audit_shared_retention(runs_root: Path) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for events_path in sorted(runs_root.glob("*/events.jsonl")):
        events = _events(events_path)
        for event in events:
            if event.get("event_type") != "FORCED_RELEASE_DECISION":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            raw_candidates = payload.get("candidates")
            if not isinstance(raw_candidates, list):
                continue
            decision_index = int(event["event_index"])
            mappings = [
                _mapping_for_candidate(
                    events,
                    candidate,
                    decision_index=decision_index,
                )
                for candidate in raw_candidates
                if isinstance(candidate, dict)
            ]
            complete = len(mappings) == len(raw_candidates) and all(
                row["mapping_status"] == "OBSERVABLE" for row in mappings
            )
            owners: dict[tuple[str, int, str], list[tuple[str, str]]] = {}
            if complete:
                for mapping in mappings:
                    owner = (mapping["program_id"], mapping["prefix_id"])
                    process_id = mapping["native_hash_process_id"]
                    for block in mapping["blocks"]:
                        identity = (
                            process_id,
                            int(block["block_id"]),
                            str(block["native_hash"]),
                        )
                        owners.setdefault(identity, []).append(owner)
            shared = [
                {
                    "native_hash_process_id": identity[0],
                    "block_id": identity[1],
                    "native_hash": identity[2],
                    "owners": [list(owner) for owner in owner_list],
                }
                for identity, owner_list in sorted(owners.items())
                if len(set(owner_list)) >= 2
            ]
            relief_counts = [int(row["initially_reclaimable_block_count"]) for row in mappings]
            decisions.append(
                {
                    "run_id": event.get("run_id"),
                    "decision_event_index": decision_index,
                    "decision_timestamp": event.get("timestamp"),
                    "candidate_count": len(raw_candidates),
                    "owner_mapping_status": ("OBSERVABLE" if complete else "NOT_OBSERVABLE"),
                    "candidate_mappings": mappings,
                    "shared_protected_blocks": shared,
                    "has_multiple_protected_owners": bool(shared),
                    "marginal_relief_counts": relief_counts,
                    "has_differentiated_marginal_relief": (
                        len(relief_counts) >= 2 and len(set(relief_counts)) >= 2
                    ),
                    "source": str(events_path),
                }
            )

    complete_count = sum(row["owner_mapping_status"] == "OBSERVABLE" for row in decisions)
    shared_count = sum(row["has_multiple_protected_owners"] for row in decisions)
    unknown_count = len(decisions) - complete_count
    if shared_count:
        conclusion = "OBSERVED_SHARED_PROTECTED"
    elif decisions and unknown_count == 0:
        conclusion = "OBSERVED_NO_SHARED_PROTECTED"
    else:
        conclusion = "NOT_OBSERVABLE"
    return {
        "schema_version": "phase2d.shared_retention_feasibility.v1",
        "audit_kind": "READ_ONLY_FEASIBILITY_AUDIT",
        "source_runs_root": str(runs_root),
        "conclusion": conclusion,
        "summary": {
            "valid_forced_release_decision_count": len(decisions),
            "legal_candidate_counts": [row["candidate_count"] for row in decisions],
            "fully_reconstructed_owner_mapping_count": complete_count,
            "multiple_protected_owner_decision_count": shared_count,
            "not_observable_decision_count": unknown_count,
            "differentiated_marginal_relief_decision_count": sum(
                row["has_differentiated_marginal_relief"] for row in decisions
            ),
        },
        "capabilities": {
            "decision_identity": "OBSERVABLE" if decisions else "NOT_OBSERVABLE",
            "logical_retention_entries": ("OBSERVABLE" if decisions else "NOT_OBSERVABLE"),
            "protection_state": "OBSERVABLE" if decisions else "NOT_OBSERVABLE",
            "entry_to_block_mapping": (
                "OBSERVABLE" if decisions and unknown_count == 0 else "NOT_OBSERVABLE"
            ),
            "block_content_identity": (
                "OBSERVABLE" if decisions and unknown_count == 0 else "NOT_OBSERVABLE"
            ),
            "native_free_queue_position": ("OBSERVABLE" if decisions else "NOT_OBSERVABLE"),
            "initially_reclaimable_blocks": ("OBSERVABLE" if decisions else "NOT_OBSERVABLE"),
            "native_process_identity": (
                "OBSERVABLE" if decisions and unknown_count == 0 else "NOT_OBSERVABLE"
            ),
        },
        "decisions": decisions,
        "boundaries": {
            "new_gpu_runs": False,
            "native_ref_count_used_as_logical_owner_count": False,
            "content_hash_used_as_owner_identity": False,
            "cross_decision_owner_join": False,
            "victim_intervention": False,
            "policy_modified": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = audit_shared_retention(arguments.runs_root)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"{result['conclusion']}: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
