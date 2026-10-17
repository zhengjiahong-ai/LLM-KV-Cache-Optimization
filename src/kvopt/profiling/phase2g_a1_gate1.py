"""Evaluate the authorized Phase 2G A1 native Gate 1 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from .ingestion import load_run_artifacts
from .phase2e_fidelity import _materialized_digests


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(run: object, event_type: str) -> list[dict[str, object]]:
    return [
        row
        for row in run.events  # type: ignore[attr-defined]
        if row.get("event_type") == event_type
    ]


def evaluate_run(run_dir: Path) -> dict[str, object]:
    run = load_run_artifacts(run_dir)
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    stage = config["phase2g_stage"]
    forced = _events(run, "FORCED_RELEASE_DECISION")
    cost_events = [
        row
        for row in _events(run, "COST_AWARE_RELEASE_DECISION")
        if row.get("payload", {}).get("selection_trace")
    ]
    native = _events(run, "VLLM_NATIVE_REQUEST_OBSERVATION")
    evictions = _events(run, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
    selected = [
        str(row["program_id"])
        for decision in forced
        for row in decision.get("payload", {}).get("selected_releases", [])
    ]
    return_recompute = {
        str(row["request_id"]): int(row["payload"]["native_prompt_tokens"])
        - int(row["payload"]["native_cached_prefix_tokens"])
        for row in native
        if str(row.get("request_id", "")).endswith(":2")
    }
    decision_index = int(forced[0]["event_index"]) if len(forced) == 1 else -1
    pressure_observations = [
        row
        for row in native
        if str(row.get("request_id", "")).startswith("pressure:")
        and int(row["event_index"]) > decision_index
    ]
    pressure_end_index = (
        int(pressure_observations[0]["event_index"])
        if pressure_observations
        else decision_index
    )
    pressure_evictions = [
        row
        for row in evictions
        if decision_index < int(row["event_index"]) < pressure_end_index
    ]
    initial_hash_positions: dict[str, tuple[str, int]] = {}
    for row in native:
        if not str(row.get("request_id", "")).endswith(":1"):
            continue
        for position, block_hash in enumerate(
            row.get("payload", {}).get("native_apc_block_hashes", [])
        ):
            initial_hash_positions[str(block_hash)] = (
                str(row.get("program_id")),
                position,
            )
    physical_signature: list[tuple[str, int]] = []
    for row in pressure_evictions:
        native_key = str(row.get("payload", {}).get("native_cache_key_before", ""))
        matches = [
            identity
            for block_hash, identity in initial_hash_positions.items()
            if native_key.startswith(block_hash)
        ]
        if len(matches) == 1:
            physical_signature.append(matches[0])
    policy = str(stage["policy"])
    checks = {
        "execution_success": run.manifest.get("execution_status") == "success",
        "clean_git": run.manifest.get("git_dirty") is False,
        "single_forced_release_decision": len(forced) == 1,
        "single_selected_entry": len(selected) == 1,
        "a1_trace_contract": len(cost_events) == (1 if policy == "A1" else 0),
        "native_physical_eviction_observed": bool(pressure_evictions),
        "eviction_identity_complete": bool(pressure_evictions)
        and all(
            row.get("payload", {}).get("native_cache_key_before")
            and row.get("payload", {}).get("hash_removed_after") is True
            for row in pressure_evictions
        ),
        "pressure_evictions_map_to_initial_content": len(physical_signature)
        == len(pressure_evictions),
        "return_apc_observed": set(return_recompute) == {"gate1-a:2", "gate1-b:2"},
        "single_native_hash_process": len(
            {
                row.get("payload", {}).get("native_hash_process_id")
                for row in native + evictions
            }
        )
        == 1,
    }
    return {
        "run_id": run.run_id,
        "case_id": stage["case_id"],
        "policy": policy,
        "repeat": int(stage["repeat"]),
        "git_sha": run.manifest.get("git_sha"),
        "trace_sha256": run.manifest.get("trace_sha256"),
        "status": "VALID" if all(checks.values()) else "INVALID",
        "checks": checks,
        "selected_programs": selected,
        "selection_trace": [row["payload"]["selection_trace"] for row in cost_events],
        "physical_eviction_count": len(pressure_evictions),
        "physical_eviction_keys": sorted(
            str(row["payload"]["native_cache_key_before"])
            for row in pressure_evictions
        ),
        "physical_eviction_signature": sorted(physical_signature),
        "return_recomputed_tokens": return_recompute,
        "materialized_token_digests": _materialized_digests(run),
        "request_ids": sorted(str(row.get("request_id")) for row in run.replay),
        "pairing_config": {
            "model": config.get("model"),
            "tokenizer": config.get("tokenizer"),
            "generation": config.get("generation"),
            "batching": config.get("batching"),
            "cache": config.get("cache"),
            "seed": config.get("seed"),
            "backend_revision": config.get("backend_revision"),
        },
    }


def compare_pair(
    a0: Mapping[str, object],
    a1: Mapping[str, object],
    *,
    expected_relation: str,
) -> dict[str, object]:
    pairing_checks = {
        "both_valid": a0.get("status") == a1.get("status") == "VALID",
        "same_case_repeat": (a0.get("case_id"), a0.get("repeat"))
        == (a1.get("case_id"), a1.get("repeat")),
        "same_git_sha": bool(a0.get("git_sha")) and a0.get("git_sha") == a1.get("git_sha"),
        "same_trace": bool(a0.get("trace_sha256"))
        and a0.get("trace_sha256") == a1.get("trace_sha256"),
        "same_requests": a0.get("request_ids") == a1.get("request_ids"),
        "same_materialized_tokens": bool(a0.get("materialized_token_digests"))
        and a0.get("materialized_token_digests") == a1.get("materialized_token_digests"),
        "same_runtime_config": a0.get("pairing_config") == a1.get("pairing_config"),
    }
    selected_equal = a0.get("selected_programs") == a1.get("selected_programs")
    relation_realized = selected_equal == (expected_relation == "SAME")
    physical_equal = a0.get("physical_eviction_signature") == a1.get(
        "physical_eviction_signature"
    )
    recompute_equal = a0.get("return_recomputed_tokens") == a1.get("return_recomputed_tokens")
    mechanism_checks = {
        "selection_relation_realized": relation_realized,
        "physical_relation_realized": physical_equal == (expected_relation == "SAME"),
        "recomputation_relation_realized": recompute_equal
        == (expected_relation == "SAME"),
    }
    return {
        "status": (
            "PASS"
            if all(pairing_checks.values()) and all(mechanism_checks.values())
            else "FAIL"
        ),
        "expected_relation": expected_relation,
        "pairing_checks": pairing_checks,
        "mechanism_checks": mechanism_checks,
        "a0_selected_programs": a0.get("selected_programs"),
        "a1_selected_programs": a1.get("selected_programs"),
        "a0_return_recomputed_tokens": a0.get("return_recomputed_tokens"),
        "a1_return_recomputed_tokens": a1.get("return_recomputed_tokens"),
    }


def evaluate_gate1(
    *, manifest_path: Path, run_roots: Sequence[Path]
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs: list[dict[str, object]] = []
    for entry in manifest["runs"]:
        matches = [
            root / entry["run_id"]
            for root in run_roots
            if (root / entry["run_id"] / "run.json").is_file()
            and (root / entry["run_id"] / "config.json").is_file()
            and _sha256(root / entry["run_id"] / "config.json")
            == entry["config_sha256"]
        ]
        if len(matches) != 1:
            runs.append({**entry, "status": "MISSING" if not matches else "AMBIGUOUS"})
        else:
            runs.append(evaluate_run(matches[0]))
    by_key = {
        (str(row["case_id"]), int(row["repeat"]), str(row["policy"])): row
        for row in runs
        if row.get("status") != "MISSING" and row.get("status") != "AMBIGUOUS"
    }
    pairs: list[dict[str, object]] = []
    expected_by_case = {
        str(row["case_id"]): str(row["expected_selection_relation"])
        for row in manifest["runs"]
    }
    for case_id in sorted(expected_by_case):
        for repeat in (1, 2):
            a0 = by_key.get((case_id, repeat, "A0"))
            a1 = by_key.get((case_id, repeat, "A1"))
            result = (
                compare_pair(a0, a1, expected_relation=expected_by_case[case_id])
                if a0 is not None and a1 is not None
                else {"status": "FAIL", "reason": "paired arm missing"}
            )
            pairs.append({"case_id": case_id, "repeat": repeat, **result})
    passed = len(runs) == 8 and all(row.get("status") == "VALID" for row in runs) and all(row["status"] == "PASS" for row in pairs)
    return {
        "schema_version": "phase2g.a1_native_gate1_report.v1",
        "gate": "PASS" if passed else "FAIL",
        "gate2_ready": passed,
        "planned_run_count": len(manifest["runs"]),
        "run_status_counts": dict(Counter(str(row.get("status")) for row in runs)),
        "pair_status_counts": dict(Counter(str(row["status"]) for row in pairs)),
        "runs": runs,
        "pairs": pairs,
        "limitations": [
            "Gate 1 validates native integration and mechanism realization, not aggregate benefit.",
            "Logical release and physical eviction remain distinct evidence layers.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_gate1(manifest_path=args.manifest, run_roots=args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Phase 2G A1 Gate 1: {report['gate']} -> {args.output}")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
