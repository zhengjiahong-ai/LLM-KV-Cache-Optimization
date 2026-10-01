"""Run the minimal Phase 2A real-runtime observability acceptance test."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from kvopt.workload.phase2_runner import run_phase2


_REQUIRED_ARTIFACTS = ("run.json", "trace.json", "replay.jsonl", "events.jsonl")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def _read_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise TypeError("events.jsonl entries must be objects")
        events.append(item)
    return events


def _check(ok: bool, detail: str) -> dict[str, object]:
    return {"status": "PASS" if ok else "FAIL", "detail": detail}


def build_observation_report(run_directory: Path) -> dict[str, object]:
    """Validate the minimum causal evidence chain, not performance quality."""
    artifact_presence = {
        name: (run_directory / name).is_file() for name in _REQUIRED_ARTIFACTS
    }
    run = _read_json(run_directory / "run.json")
    events = _read_events(run_directory / "events.jsonl")

    by_type: dict[str, list[dict[str, object]]] = {}
    for event in events:
        event_type = event.get("event_type")
        if isinstance(event_type, str):
            by_type.setdefault(event_type, []).append(event)

    decisions = [
        event
        for event in by_type.get("FORCED_RELEASE_DECISION", [])
        if isinstance(event.get("payload"), Mapping)
        and bool(event["payload"].get("selected_releases"))
    ]
    decision = decisions[0] if decisions else None
    decision_payload = (
        decision["payload"]
        if decision is not None and isinstance(decision.get("payload"), Mapping)
        else {}
    )
    candidates = (
        decision_payload.get("candidates", [])
        if isinstance(decision_payload, Mapping)
        else []
    )
    selected = (
        decision_payload.get("selected_releases", [])
        if isinstance(decision_payload, Mapping)
        else []
    )
    candidate_keys = {
        (item.get("program_id"), item.get("prefix_id"))
        for item in candidates
        if isinstance(item, Mapping)
    }
    selected_keys = {
        (item.get("program_id"), item.get("prefix_id"))
        for item in selected
        if isinstance(item, Mapping)
    }
    selected_blocks = {
        block_id
        for item in selected
        if isinstance(item, Mapping)
        for block_id in item.get("newly_eligible_block_ids", [])
        if isinstance(block_id, int) and not isinstance(block_id, bool)
    }
    evicted_blocks = {
        event["payload"].get("block_id")
        for event in by_type.get("BLOCK_EVICTED", [])
        if isinstance(event.get("payload"), Mapping)
        and isinstance(event["payload"].get("block_id"), int)
    }

    mapped_programs = {
        event.get("program_id")
        for event in by_type.get("BLOCKS_OBSERVED", [])
        if isinstance(event.get("program_id"), str)
        and isinstance(event.get("payload"), Mapping)
        and bool(event["payload"].get("block_ids"))
    }

    decision_timestamp = (
        float(decision["timestamp"])
        if decision is not None
        and isinstance(decision.get("timestamp"), (int, float))
        and not isinstance(decision.get("timestamp"), bool)
        else None
    )
    selected_programs = {
        item.get("program_id")
        for item in selected
        if isinstance(item, Mapping) and isinstance(item.get("program_id"), str)
    }
    future_arrivals = {
        event.get("program_id")
        for event in by_type.get("REQUEST_ARRIVED", [])
        if decision_timestamp is not None
        and isinstance(event.get("timestamp"), (int, float))
        and float(event["timestamp"]) > decision_timestamp
    }
    future_prefix_keys = {
        (event.get("program_id"), event.get("prefix_id"))
        for event in by_type.get("VLLM_PREFIX_SNAPSHOT", [])
        if decision_timestamp is not None
        and isinstance(event.get("timestamp"), (int, float))
        and float(event["timestamp"]) > decision_timestamp
    }

    required_candidate_fields = {
        "program_id",
        "prefix_id",
        "retention_deadline_timestamp",
        "waiting_followup",
        "block_ids",
        "initially_reclaimable_block_ids",
        "next_tool_type",
        "elapsed_since_ttl_decision_seconds",
        "prefill_reload_seconds",
        "eta",
        "queue_delay_t_seconds",
    }
    required_release_fields = {
        "program_id",
        "prefix_id",
        "newly_eligible_block_ids",
    }
    required_decision_fields = {
        "required_blocks",
        "original_free_queue",
        "ordinary_expired_entries",
        "candidates",
        "selected_releases",
    }
    decision_fields_complete = bool(decision_payload) and required_decision_fields <= set(
        decision_payload
    )
    candidate_fields_complete = (
        len(candidates) >= 2
        and all(
            isinstance(item, Mapping)
            and required_candidate_fields <= set(item)
            for item in candidates
        )
    )
    release_fields_complete = (
        bool(selected)
        and all(
            isinstance(item, Mapping)
            and required_release_fields <= set(item)
            for item in selected
        )
    )
    lifecycle_types = {
        "PROGRAM_STARTED",
        "REQUEST_ARRIVED",
        "REQUEST_ADMITTED",
        "TURN_FINISHED",
        "FOLLOWUP_WAITING",
        "TOOL_GAP_STARTED",
        "TOOL_GAP_ENDED",
        "BLOCKS_OBSERVED",
        "BLOCK_EVICTED",
        "PROGRAM_COMPLETED",
    }
    present_lifecycle_types = lifecycle_types & set(by_type)

    checks = {
        "artifacts_present": _check(
            all(artifact_presence.values()),
            f"required artifacts: {artifact_presence}",
        ),
        "run_completed": _check(
            run.get("status") == "success",
            f"run status={run.get('status')!r}",
        ),
        "lifecycle_contract_exposed": _check(
            lifecycle_types <= set(by_type),
            (
                f"present lifecycle events={sorted(present_lifecycle_types)}; "
                f"missing={sorted(lifecycle_types - set(by_type))}"
            ),
        ),
        "two_prefixes_mapped": _check(
            len(mapped_programs) >= 2,
            f"programs with BLOCKS_OBSERVED={sorted(str(x) for x in mapped_programs)}",
        ),
        "forced_release_observed": _check(
            decision is not None,
            f"forced-release decisions with selected releases={len(decisions)}",
        ),
        "forced_release_snapshot_fields": _check(
            decision_fields_complete
            and candidate_fields_complete
            and release_fields_complete,
            (
                f"decision_fields_complete={decision_fields_complete}; "
                f"candidate_fields_complete={candidate_fields_complete}; "
                f"release_fields_complete={release_fields_complete}"
            ),
        ),
        "candidate_set_has_choice": _check(
            len(candidate_keys) >= 2,
            f"candidate identities={sorted(str(x) for x in candidate_keys)}",
        ),
        "selected_release_is_candidate": _check(
            bool(selected_keys) and selected_keys <= candidate_keys,
            f"selected={sorted(str(x) for x in selected_keys)}",
        ),
        "physical_eviction_join": _check(
            bool(selected_blocks & evicted_blocks),
            (
                f"selected newly-eligible blocks={sorted(selected_blocks)}; "
                f"native evicted blocks={sorted(x for x in evicted_blocks if isinstance(x, int))}"
            ),
        ),
        "future_program_join": _check(
            bool(selected_programs & future_arrivals),
            (
                f"selected programs={sorted(str(x) for x in selected_programs)}; "
                f"future arrivals={sorted(str(x) for x in future_arrivals)}"
            ),
        ),
        "future_prefix_join": _check(
            bool(selected_keys & future_prefix_keys),
            (
                f"selected identities={sorted(str(x) for x in selected_keys)}; "
                f"future prefix identities={sorted(str(x) for x in future_prefix_keys)}"
            ),
        ),
    }

    completed = by_type.get("VLLM_REQUEST_COMPLETED", [])
    runtime_ready = by_type.get("REAL_RUNTIME_READY", [])
    capabilities = {
        "runtime_identity": {
            "status": "AVAILABLE" if runtime_ready else "UNAVAILABLE",
            "reason": "REAL_RUNTIME_READY event" if runtime_ready else "runtime identity event missing",
        },
        "logical_lifecycle": {
            "status": "AVAILABLE" if by_type.get("REQUEST_ARRIVED") else "UNAVAILABLE",
            "reason": "Phase 2 lifecycle events are persisted",
        },
        "prefix_block_mapping": {
            "status": "AVAILABLE" if mapped_programs else "UNAVAILABLE",
            "reason": "BLOCKS_OBSERVED / VLLM_PREFIX_SNAPSHOT",
        },
        "forced_release_snapshot": {
            "status": "AVAILABLE" if decision is not None else "UNAVAILABLE",
            "reason": "FORCED_RELEASE_DECISION",
        },
        "native_block_eviction": {
            "status": "AVAILABLE" if evicted_blocks else "UNAVAILABLE",
            "reason": "BLOCK_EVICTED callback evidence",
        },
        "generated_token_count": {
            "status": "AVAILABLE" if completed else "UNAVAILABLE",
            "reason": "VLLM_REQUEST_COMPLETED.output_token_count",
        },
        "native_apc_hit_miss": {
            "status": "UNAVAILABLE",
            "reason": "current approved backend boundary has no stable per-request APC hit/miss event",
        },
        "recomputed_prefill_tokens": {
            "status": "UNAVAILABLE",
            "reason": "current approved backend boundary has no direct recomputation-token event",
        },
        "native_first_token_timestamp": {
            "status": "UNAVAILABLE",
            "reason": "wait_for_completion path does not expose a first-token timestamp",
        },
        "native_scheduler_admission_timestamp": {
            "status": "UNAVAILABLE",
            "reason": "REQUEST_ADMITTED is a logical retention boundary in this adapter, not native scheduler timing",
        },
        "hardware_counters": {
            "status": "UNAVAILABLE",
            "reason": "device counters are intentionally outside this low-configuration acceptance test",
        },
    }

    passed = all(item["status"] == "PASS" for item in checks.values())
    return {
        "schema_version": "phase2a.minimal_observability_report.v1",
        "status": "PASS" if passed else "FAIL",
        "purpose": "real-runtime observability acceptance; not performance evidence",
        "run_id": run.get("run_id"),
        "checks": checks,
        "capabilities": capabilities,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs/phase2/metal-observability-config.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=root / "artifacts/phase2-observability",
    )
    parser.add_argument("--run-id")
    parser.add_argument(
        "--vllm-metal-source-checkout",
        type=Path,
        help="Optional pinned vLLM-Metal checkout for source-revision provenance.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_METAL_USE_PAGED_ATTENTION", "1")
    os.environ.setdefault("VLLM_METAL_MEMORY_FRACTION", "auto")
    os.environ.setdefault("VLLM_MLX_DEVICE", "gpu")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    if args.vllm_metal_source_checkout is not None:
        os.environ["VLLM_METAL_SOURCE_CHECKOUT"] = str(
            args.vllm_metal_source_checkout.resolve()
        )

    output = run_phase2(
        args.config.resolve(),
        output_root=args.output_root.resolve(),
        run_id=args.run_id,
    )
    report = build_observation_report(output)
    report_path = output / "observation-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(report_path)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
