"""Build the fail-closed Phase 2E T1 native-fidelity evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from .ingestion import ArtifactValidationError, RawRunArtifacts, load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _events(run: RawRunArtifacts, event_type: str) -> list[dict[str, object]]:
    return [row for row in run.events if row.get("event_type") == event_type]


def _runtime_mode(run: RawRunArtifacts) -> str | None:
    ready = _events(run, "REAL_RUNTIME_READY")
    if len(ready) != 1:
        return None
    payload = ready[0].get("payload")
    return payload.get("retention_mode") if isinstance(payload, dict) else None


def _lifecycle_overlap_seconds(run: RawRunArtifacts) -> float:
    submitted: dict[str, float] = {}
    completed: dict[str, float] = {}
    for row in run.events:
        request_id = row.get("request_id")
        if not isinstance(request_id, str) or request_id.startswith("pressure:"):
            continue
        timestamp = row.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            continue
        if row.get("event_type") == "VLLM_REQUEST_SUBMITTED":
            submitted[request_id] = float(timestamp)
        elif row.get("event_type") == "VLLM_REQUEST_COMPLETED":
            completed[request_id] = float(timestamp)
    intervals = [(submitted[key], completed[key]) for key in submitted.keys() & completed]
    return max(
        (
            min(left[1], right[1]) - max(left[0], right[0])
            for index, left in enumerate(intervals)
            for right in intervals[index + 1 :]
        ),
        default=0.0,
    )


def _native_execution_overlap(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    intervals = [
        {
            "request_id": str(row["request_id"]),
            "native_request_id": row.get("native_request_id"),
            "native_hash_process_id": row.get("native_hash_process_id"),
            "clock_domain": row.get("native_clock_domain"),
            "start": float(row["native_scheduler_admission_timestamp"]),
            "end": float(row["native_first_token_timestamp"]),
        }
        for row in rows
        if not str(row["request_id"]).startswith("pressure:")
        and row.get("native_clock_domain") == "engine_core_monotonic"
        and row.get("native_scheduler_admission_timestamp") is not None
        and row.get("native_first_token_timestamp") is not None
    ]
    candidates = [
        (
            min(float(left["end"]), float(right["end"]))
            - max(float(left["start"]), float(right["start"])),
            left,
            right,
        )
        for index, left in enumerate(intervals)
        for right in intervals[index + 1 :]
    ]
    overlap, left, right = max(
        candidates,
        key=lambda item: item[0],
        default=(0.0, None, None),
    )
    identities_valid = bool(
        left
        and right
        and left["request_id"] != right["request_id"]
        and left["native_request_id"]
        and right["native_request_id"]
        and left["native_request_id"] != right["native_request_id"]
        and left["native_hash_process_id"]
        and left["native_hash_process_id"] == right["native_hash_process_id"]
        and left["clock_domain"] == right["clock_domain"] == "engine_core_monotonic"
    )
    return {
        "overlap_seconds": max(0.0, overlap),
        "identity_checks_pass": identities_valid,
        "left": left,
        "right": right,
    }


def _materialized_digests(run: RawRunArtifacts) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for row in _events(run, "BACKEND_INPUT_MATERIALIZED"):
        request_id = row.get("request_id")
        payload = row.get("payload")
        if not isinstance(request_id, str) or not isinstance(payload, dict):
            continue
        digest = payload.get("submitted_token_ids_sha256")
        result[request_id] = digest if isinstance(digest, str) and digest else None
    return result


def _config_comparability(runs: Sequence[RawRunArtifacts]) -> dict[str, object]:
    configs = [
        json.loads((run.run_dir / "config.json").read_text(encoding="utf-8"))
        for run in runs
    ]
    manifests = [run.manifest for run in runs]
    request_sets = [
        sorted(
            str(row["request_id"])
            for row in run.replay
            if isinstance(row.get("request_id"), str)
        )
        for run in runs
    ]
    same_fields = (
        "model",
        "tokenizer",
        "generation",
        "batching",
        "cache",
        "runtime_mode",
        "backend_factory",
        "backend_revision",
        "seed",
        "observe",
    )
    field_checks = {
        field: configs[0].get(field) == configs[1].get(field)
        for field in same_fields
    }
    runtime_fields = (
        "vllm_release_version",
        "vllm_metal_distribution_version_raw",
        "vllm_metal_source_commit",
        "platform_plugin_identity",
        "platform_plugin_class",
        "metal_paged_kv_enabled",
        "gpu_memory_utilization",
        "cache_block_override",
        "block_size",
        "engine_core_observation_topology",
    )
    ready_payloads: list[dict[str, object]] = []
    for run in runs:
        ready = _events(run, "REAL_RUNTIME_READY")
        payload = ready[0].get("payload") if len(ready) == 1 else None
        ready_payloads.append(payload if isinstance(payload, dict) else {})
    runtime_checks = {
        field: ready_payloads[0].get(field) is not None
        and ready_payloads[0].get(field) == ready_payloads[1].get(field)
        for field in runtime_fields
    }
    sha_checks = {
        field: all(isinstance(row.get(field), str) and row.get(field) for row in manifests)
        and len({str(row[field]) for row in manifests}) == 1
        for field in ("git_sha", "trace_sha256")
    }
    digests = [_materialized_digests(run) for run in runs]
    digest_request_ids_equal = set(digests[0]) == set(digests[1]) == set(request_sets[0])
    digest_values_equal = digest_request_ids_equal and all(
        digests[0][request_id] == digests[1][request_id]
        for request_id in request_sets[0]
    )
    all_digests_present = digest_request_ids_equal and all(
        digests[arm][request_id]
        for arm in (0, 1)
        for request_id in request_sets[0]
    )
    checks = {
        "expected_request_ids_equal": request_sets[0] == request_sets[1]
        and bool(request_sets[0]),
        **{f"config_{key}_equal": value for key, value in field_checks.items()},
        **{f"runtime_{key}_equal": value for key, value in runtime_checks.items()},
        **{f"nonempty_{key}_equal": value for key, value in sha_checks.items()},
        "materialized_digest_request_ids_equal": digest_request_ids_equal,
        "materialized_digest_values_equal": digest_values_equal,
    }
    strict_checks = {**checks, "all_materialized_digests_nonempty": all_digests_present}
    status = (
        "COMPARABLE"
        if all(strict_checks.values())
        else (
            "COMPARABLE_WITH_LEGACY_PRESSURE_DIGEST_LIMITATION"
            if all(checks.values())
            and all(
                value is not None
                for digest_map in digests
                for request_id, value in digest_map.items()
                if not request_id.startswith("pressure:")
            )
            else "NOT_COMPARABLE"
        )
    )
    return {
        "status": status,
        "checks": strict_checks,
        "expected_request_ids": request_sets[0] if request_sets[0] == request_sets[1] else request_sets,
        "materialized_token_digests": digests,
        "intentional_differences": {
            "policy": [config.get("policy") for config in configs],
            "retention_mode": [_runtime_mode(run) for run in runs],
            "phase2e_stage.baseline": [
                config.get("phase2e_stage", {}).get("baseline") for config in configs
            ],
            "config_sha256": [manifest.get("config_sha256") for manifest in manifests],
        },
        "instrumentation_difference_assessment": (
            "same observer and event contract; retention hook mode differs by the "
            "authorized baseline policy, so wall-clock comparisons remain descriptive"
        ),
    }


def build_physical_evictions(run: RawRunArtifacts) -> tuple[dict[str, object], ...]:
    """Join pre-eviction keys to prior ordered snapshots without guessing."""

    snapshots = _events(run, "VLLM_PREFIX_SNAPSHOT")
    result: list[dict[str, object]] = []
    for eviction in _events(run, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"):
        payload = eviction.get("payload")
        if not isinstance(payload, dict):
            raise ArtifactValidationError("physical eviction payload must be an object")
        key = payload.get("native_cache_key_before")
        process_id = payload.get("native_hash_process_id")
        event_index = int(eviction["event_index"])
        matches: list[tuple[dict[str, object], int]] = []
        for snapshot in snapshots:
            if int(snapshot["event_index"]) >= event_index:
                continue
            snapshot_payload = snapshot.get("payload")
            if not isinstance(snapshot_payload, dict):
                continue
            if snapshot_payload.get("native_hash_process_id") != process_id:
                continue
            keys = snapshot_payload.get("ordered_native_cache_keys")
            block_ids = snapshot_payload.get("block_ids")
            if not isinstance(keys, list) or not isinstance(block_ids, list):
                continue
            for position, snapshot_key in enumerate(keys):
                # Slot reuse is safe only if both slot and pre-eviction key agree.
                if (
                    snapshot_key == key
                    and position < len(block_ids)
                    and block_ids[position] == payload.get("block_id")
                ):
                    matches.append((snapshot, position))
        latest = max(matches, key=lambda item: int(item[0]["event_index"]), default=None)
        mapped = latest is not None
        snapshot = latest[0] if latest else None
        position = latest[1] if latest else None
        snapshot_payload = snapshot.get("payload") if snapshot else None
        block_size = (
            snapshot_payload.get("native_hash_block_size")
            if isinstance(snapshot_payload, dict)
            else None
        )
        result.append(
            {
                "run_id": run.run_id,
                "event_index": event_index,
                "timestamp": eviction.get("timestamp"),
                "native_hash_process_id": process_id,
                "block_id": payload.get("block_id"),
                "native_cache_key_before": key,
                "hash_removed_after": payload.get("hash_removed_after"),
                "prefix_position_status": "MAPPED" if mapped else "NOT_IDENTIFIABLE",
                "source_snapshot_event_index": (
                    int(snapshot["event_index"]) if snapshot else None
                ),
                "source_request_id": snapshot.get("request_id") if snapshot else None,
                "source_program_id": snapshot.get("program_id") if snapshot else None,
                "prefix_block_index": position,
                "prefix_token_start": (
                    position * int(block_size)
                    if position is not None and isinstance(block_size, int)
                    else None
                ),
                "prefix_token_end": (
                    (position + 1) * int(block_size)
                    if position is not None and isinstance(block_size, int)
                    else None
                ),
                "logical_owner_attribution": payload.get("logical_owner_attribution"),
            }
        )
    return tuple(result)


def build_t1_audit(
    runs: Sequence[RawRunArtifacts],
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    if len(runs) != 2:
        raise ArtifactValidationError("T1 audit requires exactly two run arms")
    configs = {
        str(json.loads((run.run_dir / "config.json").read_text(encoding="utf-8"))["policy"]): run
        for run in runs
    }
    if set(configs) != {"native-lru", "continuum-baseline"}:
        raise ArtifactValidationError("T1 requires native-lru and continuum-baseline")
    evidence = build_request_runtime_evidence_table(runs)
    evidence_rows = [asdict(row) for row in evidence]
    evictions = [row for run in runs for row in build_physical_evictions(run)]
    decisions = [
        {
            "run_id": run.run_id,
            "event_index": row["event_index"],
            "payload": row.get("payload"),
        }
        for run in runs
        for row in _events(run, "FORCED_RELEASE_DECISION")
    ]
    by_run = {run.run_id: [row for row in evidence_rows if row["run_id"] == run.run_id] for run in runs}
    comparability = _config_comparability(runs)
    per_run: dict[str, object] = {}
    gate_pass = True
    for policy, run in configs.items():
        rows = by_run[run.run_id]
        available = sum(row["availability"] == "AVAILABLE" for row in rows)
        timing = sum(
            row["native_queue_delay_status"] == "available"
            and row["native_prefill_to_first_token_status"] == "available"
            for row in rows
        )
        run_evictions = [row for row in evictions if row["run_id"] == run.run_id]
        mapped = sum(row["prefix_position_status"] == "MAPPED" for row in run_evictions)
        expected_mode = "native" if policy == "native-lru" else "controlled"
        native_overlap = _native_execution_overlap(rows)
        checks = {
            "execution_success": run.manifest.get("execution_status") == "success",
            "request_completeness": len(rows) == 5 and run.manifest.get("completion_count") == 5,
            "native_token_evidence_complete": available == len(rows),
            "native_timestamps_complete": timing == len(rows),
            "request_lifecycle_overlap_observed": _lifecycle_overlap_seconds(run) > 0,
            "native_admission_to_first_token_overlap_observed": (
                native_overlap["overlap_seconds"] > 0
                and native_overlap["identity_checks_pass"] is True
            ),
            "retention_mode_matches_baseline": _runtime_mode(run) == expected_mode,
            "pre_eviction_content_identity_observed": bool(run_evictions)
            and all(row["native_cache_key_before"] for row in run_evictions),
        }
        gate_pass = gate_pass and all(checks.values())
        per_run[run.run_id] = {
            "baseline": policy,
            "checks": checks,
            "peak_inflight": run.manifest.get("peak_inflight"),
            "maximum_request_lifecycle_overlap_seconds": _lifecycle_overlap_seconds(run),
            "native_admission_to_first_token_overlap": native_overlap,
            "native_overlap_claim": (
                "overlapping engine-core admission-to-first-token windows; "
                "not a claim of simultaneous GPU kernel execution"
            ),
            "request_evidence_available": available,
            "request_count": len(rows),
            "physical_eviction_count": len(run_evictions),
            "p5_mapped_eviction_count": mapped,
            "p5_unmapped_eviction_count": len(run_evictions) - mapped,
            "forced_release_decision_count": len(_events(run, "FORCED_RELEASE_DECISION")),
        }
    gate_pass = gate_pass and comparability["status"] in {
        "COMPARABLE",
        "COMPARABLE_WITH_LEGACY_PRESSURE_DIGEST_LIMITATION",
    }
    missingness = {
        run.run_id: {
            "expected_requests": len(by_run[run.run_id]),
            "unavailable_request_evidence": sum(
                row["availability"] != "AVAILABLE" for row in by_run[run.run_id]
            ),
            "unmapped_physical_evictions": sum(
                row["run_id"] == run.run_id
                and row["prefix_position_status"] != "MAPPED"
                for row in evictions
            ),
            "logical_owner_attribution": (
                "NOT_OBSERVABLE"
                if not any(
                    row["run_id"] == run.run_id and row["logical_owner_attribution"]
                    for row in evictions
                )
                else "AVAILABLE"
            ),
        }
        for run in runs
    }
    audit = {
        "schema_version": "phase2e.t1_fidelity_audit.v1",
        "scope": "NON_HOLDOUT_RESEARCH_DISCOVERY",
        "gate": "GATE_A_NATIVE_FIDELITY_SMOKE",
        "status": "PASS" if gate_pass else "FAIL",
        "paired_run_comparability": comparability,
        "runs": per_run,
        "capability_boundaries": {
            "request_metrics": "DEMONSTRATED" if gate_pass else "NOT_DEMONSTRATED",
            "pre_eviction_content_identity": "DEMONSTRATED",
            "p5_block_to_prefix_position": (
                "PARTIALLY_DEMONSTRATED"
                if any(row["prefix_position_status"] == "MAPPED" for row in evictions)
                else "NOT_OBSERVABLE"
            ),
            "continuum_logical_owner_attribution": "NOT_OBSERVABLE",
            "forced_release_decision_geometry": (
                "DEMONSTRATED" if decisions else "NOT_DEMONSTRATED"
            ),
            "causal_eviction_to_recompute_attribution": "NOT_CLAIMED_BY_T1",
        },
        "missingness": missingness,
        "measured_campaign_authorized": False,
        "joint_freeze_complete": False,
    }
    tables = {
        "request_evidence": evidence_rows,
        "decision_candidates": decisions,
        "physical_evictions": evictions,
    }
    return audit, tables


def build_targeted_forced_release_audit(
    run: RawRunArtifacts,
) -> tuple[dict[str, object], list[dict[str, object]], tuple[dict[str, object], ...]]:
    decisions = _events(run, "FORCED_RELEASE_DECISION")
    evictions = build_physical_evictions(run)
    if len(decisions) != 1:
        raise ArtifactValidationError("targeted RC4 smoke requires one forced-release decision")
    decision = decisions[0]
    payload = decision.get("payload")
    if not isinstance(payload, dict):
        raise ArtifactValidationError("forced-release payload must be an object")
    candidates = payload.get("candidates")
    releases = payload.get("selected_releases")
    if not isinstance(candidates, list) or not isinstance(releases, list) or not releases:
        raise ArtifactValidationError("forced-release candidates/releases are incomplete")
    decision_index = int(decision["event_index"])
    selected_by_program = {
        str(row["program_id"]): set(row.get("newly_eligible_block_ids", []))
        for row in releases
        if isinstance(row, dict) and row.get("program_id") is not None
    }
    candidate_rows = [
        {
            "run_id": run.run_id,
            "decision_event_index": decision_index,
            "program_id": row.get("program_id"),
            "prefix_id": row.get("prefix_id"),
            "block_ids": row.get("block_ids"),
            "initially_reclaimable_block_ids": row.get("initially_reclaimable_block_ids"),
            "eligibility_tier_observed": any(
                item.get("eligibility_tier") is not None
                and item.get("block_id") in set(row.get("initially_reclaimable_block_ids", []))
                for item in payload.get("original_free_queue", [])
                if isinstance(item, dict)
            ),
            "selected": str(row.get("program_id")) in selected_by_program,
        }
        for row in candidates
        if isinstance(row, dict)
    ]
    next_non_pressure_submission = min(
        (
            int(row["event_index"])
            for row in _events(run, "VLLM_REQUEST_SUBMITTED")
            if int(row["event_index"]) > decision_index
            and not str(row.get("request_id", "")).startswith("pressure:")
        ),
        default=max(int(row["event_index"]) for row in run.events) + 1,
    )
    selected_evictions = [
        row
        for row in evictions
        if int(row["event_index"]) > decision_index
        and int(row["event_index"]) < next_non_pressure_submission
        and row.get("block_id")
        in set().union(*selected_by_program.values())
    ]
    selected_blocks = set().union(*selected_by_program.values())
    evicted_blocks = {row["block_id"] for row in selected_evictions}
    mapped_programs = {row["source_program_id"] for row in selected_evictions}
    checks = {
        "execution_success": run.manifest.get("execution_status") == "success",
        "single_real_forced_release_decision": len(decisions) == 1,
        "candidate_geometry_present": len(candidate_rows) >= 2,
        "selected_logical_release_present": bool(selected_by_program),
        "selected_blocks_became_physically_evicted": selected_blocks <= evicted_blocks,
        "decision_precedes_selected_physical_evictions": bool(selected_evictions)
        and decision_index < min(int(row["event_index"]) for row in selected_evictions),
        "selected_evictions_have_pre_eviction_identity": all(
            row.get("native_cache_key_before") for row in selected_evictions
        ),
        "selected_evictions_map_to_selected_prefix": mapped_programs
        == set(selected_by_program),
    }
    audit = {
        "schema_version": "phase2e.t1_rc4_forced_release_audit.v1",
        "scope": "NON_HOLDOUT_RESEARCH_DISCOVERY",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "decision_event_index": decision_index,
        "selected_programs": sorted(selected_by_program),
        "selected_block_ids": sorted(selected_blocks),
        "matched_physical_eviction_event_indices": [
            row["event_index"] for row in selected_evictions
        ],
        "p5_mapped_selected_evictions": sum(
            row["prefix_position_status"] == "MAPPED" for row in selected_evictions
        ),
        "p5_total_selected_evictions": len(selected_evictions),
        "capability_boundaries": {
            "forced_release_decision_geometry": "DEMONSTRATED",
            "selected_release_to_physical_eviction_sequence": "DEMONSTRATED",
            "physical_event_persisted_logical_owner": "NOT_OBSERVABLE",
            "content_level_counterfactual_causality": "NOT_CLAIMED",
        },
        "measured_campaign_authorized": False,
        "joint_freeze_complete": False,
    }
    return audit, candidate_rows, evictions


def write_t1_package(*, run_root: Path, output_dir: Path) -> Path:
    run_dirs = sorted(path for path in run_root.iterdir() if path.is_dir())
    runs = tuple(load_run_artifacts(path) for path in run_dirs)
    audit, tables = build_t1_audit(runs)
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_jsonl(output_dir / "request_evidence.jsonl", tables["request_evidence"])
    _write_jsonl(output_dir / "decision_candidates.jsonl", tables["decision_candidates"])
    _write_jsonl(output_dir / "physical_evictions.jsonl", tables["physical_evictions"])
    _write_json(output_dir / "missingness_summary.json", audit["missingness"])
    _write_json(output_dir / "fidelity-audit.json", audit)
    files = sorted(path for path in output_dir.iterdir() if path.is_file())
    manifest = {
        "schema_version": "phase2e.t1_evidence_package.v1",
        "audit_status": audit["status"],
        "source_run_root": str(run_root.resolve()),
        "files": [
            {"path": path.name, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in files
        ],
    }
    path = output_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def write_targeted_package(*, run_dir: Path, output_dir: Path) -> Path:
    run = load_run_artifacts(run_dir)
    audit, candidates, evictions = build_targeted_forced_release_audit(run)
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "forced-release-audit.json", audit)
    _write_jsonl(output_dir / "decision_candidates.jsonl", candidates)
    _write_jsonl(output_dir / "physical_evictions.jsonl", evictions)
    files = sorted(path for path in output_dir.iterdir() if path.is_file())
    path = output_dir / "manifest.json"
    _write_json(
        path,
        {
            "schema_version": "phase2e.t1_rc4_evidence_package.v1",
            "audit_status": audit["status"],
            "source_run_dir": str(run_dir.resolve()),
            "files": [
                {"path": item.name, "size_bytes": item.stat().st_size, "sha256": _sha256(item)}
                for item in files
            ],
        },
    )
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-root", type=Path)
    source.add_argument("--targeted-run-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.targeted_run_dir is not None:
        path = write_targeted_package(
            run_dir=arguments.targeted_run_dir,
            output_dir=arguments.output_dir,
        )
    else:
        assert arguments.run_root is not None
        path = write_t1_package(
            run_root=arguments.run_root,
            output_dir=arguments.output_dir,
        )
    print(f"wrote Phase 2E T1 evidence package: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
