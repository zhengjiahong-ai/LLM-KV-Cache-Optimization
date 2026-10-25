"""Evaluate the 54-run bounded A0/A1/A2 Native campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from kvopt.workload.phase2b_fidelity import token_ids_sha256

from .ingestion import load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(run: object, event_type: str) -> list[dict[str, Any]]:
    return [
        row
        for row in run.events  # type: ignore[attr-defined]
        if row.get("event_type") == event_type
    ]


def _eviction_signature(run: object) -> list[str]:
    decisions = _events(run, "FORCED_RELEASE_DECISION")
    if not decisions:
        return []
    start = int(decisions[-1]["event_index"])
    downstream = [
        int(row["event_index"])
        for row in _events(run, "VLLM_NATIVE_REQUEST_OBSERVATION")
        if int(row["event_index"]) > start
        and not str(row.get("program_id", "")).startswith("pressure:")
    ]
    end = min(downstream) if downstream else 2**63
    return sorted(
        str(row["payload"]["native_cache_key_before"])
        for row in _events(run, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
        if start < int(row["event_index"]) < end
        and row.get("payload", {}).get("hash_removed_after") is True
        and row.get("payload", {}).get("native_cache_key_before")
    )


def _a1_diagnostics(run: object) -> dict[str, Any]:
    events = _events(run, "COST_AWARE_RELEASE_DECISION")
    spans: list[float] = []
    selected: list[list[str]] = []
    earliest_matches = 0
    overshoot_matches = 0
    comparison_count = 0
    forced = _events(run, "FORCED_RELEASE_DECISION")
    for event, decision in zip(events, forced, strict=False):
        traces = event.get("payload", {}).get("selection_trace", [])
        if not traces:
            continue
        required = int(decision.get("payload", {}).get("required_blocks", 0))
        for trace in traces:
            scores = trace.get("scores", [])
            if not scores:
                continue
            q_values = [float(row["reuse_proxy"]) for row in scores]
            spans.append(max(q_values) - min(q_values))
            key = list(trace["key"])
            selected.append(key)
            sufficient = [row for row in scores if int(row["new_blocks"]) >= required]
            candidates = sufficient or scores
            earliest = min(
                candidates,
                key=lambda row: (float(row["deadline"]), tuple(row["key"])),
            )
            overshoot = min(
                candidates,
                key=lambda row: (
                    abs(int(row["new_blocks"]) - required),
                    float(row["deadline"]),
                    tuple(row["key"]),
                ),
            )
            earliest_matches += list(earliest["key"]) == key
            overshoot_matches += list(overshoot["key"]) == key
            comparison_count += 1
            required = max(0, required - int(next(
                row["new_blocks"] for row in scores if list(row["key"]) == key
            )))
    return {
        "decision_count": comparison_count,
        "selected_keys": selected,
        "q_spans": spans,
        "maximum_q_span": max(spans) if spans else None,
        "earliest_deadline_match_count": earliest_matches,
        "minimum_overshoot_match_count": overshoot_matches,
    }


def evaluate_run(run_dir: Path, binding: dict[str, Any]) -> dict[str, Any]:
    run = load_run_artifacts(run_dir)
    config = _load(run_dir / "config.json")
    expected_ids = [str(row["request_id"]) for row in run.trace["requests"]]
    evidence = {
        row.request_id: row
        for row in build_request_runtime_evidence_table((run,))
        if row.kind == "turn"
    }
    materialized = [
        row
        for row in _events(run, "BACKEND_INPUT_MATERIALIZED")
        if row.get("payload", {}).get("kind") == "turn"
    ]
    counts = Counter(str(row["request_id"]) for row in materialized)
    observed_inputs = {
        str(row["request_id"]): str(row["payload"]["submitted_token_ids_sha256"])
        for row in materialized
        if counts[str(row["request_id"])] == 1
    }
    expected_inputs = {
        request_id: token_ids_sha256(tokens)
        for request_id, tokens in config["backend_options"][
            "replay_token_ids_by_request"
        ].items()
    }
    unavailable = [
        request_id
        for request_id, row in evidence.items()
        if row.availability != "AVAILABLE"
    ]
    complete = (
        set(evidence) == set(expected_ids)
        and not unavailable
        and observed_inputs == expected_inputs
    )
    request_rows = {
        request_id: {
            "program_id": row.program_id,
            "N": row.native_prompt_tokens,
            "E": row.eligible_prefix_tokens,
            "C": row.native_cached_prefix_tokens,
            "actual_prefill_tokens": row.actual_prefill_tokens,
            "recomputed_tokens": row.observed_recomputed_tokens,
            "new_suffix_tokens": (
                None
                if row.native_prompt_tokens is None or row.eligible_prefix_tokens is None
                else row.native_prompt_tokens - row.eligible_prefix_tokens
            ),
            "apc_outcome": row.apc_outcome,
        }
        for request_id, row in sorted(evidence.items())
    }
    totals = {
        "aggregate_recomputed_tokens": None,
        "aggregate_actual_prefill_tokens": None,
        "aggregate_new_suffix_tokens": None,
    }
    if complete:
        totals = {
            "aggregate_recomputed_tokens": sum(
                int(row["recomputed_tokens"]) for row in request_rows.values()
            ),
            "aggregate_actual_prefill_tokens": sum(
                int(row["actual_prefill_tokens"]) for row in request_rows.values()
            ),
            "aggregate_new_suffix_tokens": sum(
                int(row["new_suffix_tokens"]) for row in request_rows.values()
            ),
        }
    forced = _events(run, "FORCED_RELEASE_DECISION")
    ttl_modes = [
        candidate.get("ttl_history_mode")
        for event in forced
        for candidate in event.get("payload", {}).get("candidates", [])
    ]
    profile_ordering_status = (
        "NOT_APPLICABLE_COLD_START"
        if ttl_modes and set(ttl_modes) == {"cold_start"}
        else "INCONCLUSIVE_COST_ORDERING"
    )
    time_events = _events(run, "CONTROLLED_REPLAY_TIME_ADVANCED")
    expected_boundaries = config["controlled_sparse_replay"]["boundaries"]
    physical_signature = _eviction_signature(run)
    checks = {
        "execution_success": run.manifest.get("status") == "success",
        "config_binding": run.manifest.get("config_sha256") == binding["config_sha256"],
        "trace_binding": run.manifest.get("trace_sha256") == binding["trace_sha256"],
        "request_and_input_completeness": complete,
        "logical_boundary_count": len(time_events) == len(expected_boundaries),
        "logical_sequence_binding": run.manifest.get("controlled_sparse_replay", {}).get(
            "logical_sequence_sha256"
        )
        == binding["logical_sequence_sha256"],
        "forced_release_exposed": bool(forced)
        and all(row.get("payload", {}).get("selected_releases") for row in forced),
    }
    mechanism_checks = {
        "physical_eviction_identity": bool(physical_signature),
    }
    mechanism_status = (
        "REALIZED"
        if all(mechanism_checks.values())
        else "NOT_REALIZED"
    )
    arm = str(binding["arm"])
    return {
        "run_id": run.run_id,
        "group_id": binding["group_id"],
        "pressure_regime": binding["pressure_regime"],
        "arm": arm,
        "status": "VALID" if all(checks.values()) else "INVALID",
        "checks": checks,
        "mechanism_status": mechanism_status,
        "mechanism_checks": mechanism_checks,
        "request_outcomes": request_rows,
        "totals": totals,
        "selection_sequence": [
            [row["program_id"] for row in event["payload"]["selected_releases"]]
            for event in forced
        ],
        "physical_eviction_signature": physical_signature,
        "physical_attribution": "TEMPORAL_ASSOCIATION_ONLY",
        "a1_diagnostics": _a1_diagnostics(run) if arm == "A1" else None,
        "a2_decision_count": len(_events(run, "COST_AWARE_BLOCK_DECISION")),
        "ttl_history_modes": ttl_modes,
        "profile_cost_ordering_status": profile_ordering_status,
        "execution_telemetry": run.manifest.get("execution_telemetry"),
    }


def _delta(left: dict[str, Any], right: dict[str, Any], key: str) -> int | None:
    a = left["totals"][key]
    b = right["totals"][key]
    return None if a is None or b is None else int(a) - int(b)


def build_report(*, manifest_path: Path, runs_root: Path) -> dict[str, Any]:
    manifest = _load(manifest_path)
    evaluated: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for binding in manifest["runs"]:
        run_dir = runs_root / binding["run_id"]
        if not run_dir.is_dir():
            missing.append(binding["run_id"])
            continue
        evaluated[binding["run_id"]] = evaluate_run(run_dir, binding)
    cells: list[dict[str, Any]] = []
    for group_id in sorted({row["group_id"] for row in manifest["runs"]}):
        for regime in ("moderate", "deep"):
            ids = {
                arm: f"{group_id}-{regime}-{arm.lower()}-repeat-1"
                for arm in ("A0", "A1", "A2")
            }
            if any(run_id not in evaluated for run_id in ids.values()):
                cells.append(
                    {"group_id": group_id, "pressure_regime": regime, "status": "INCOMPLETE"}
                )
                continue
            arms = {arm: evaluated[run_id] for arm, run_id in ids.items()}
            valid = all(row["status"] == "VALID" for row in arms.values())
            cells.append(
                {
                    "group_id": group_id,
                    "pressure_regime": regime,
                    "status": "VALID" if valid else "INVALID",
                    "a1_minus_a0": {
                        key: _delta(arms["A1"], arms["A0"], key)
                        for key in arms["A0"]["totals"]
                    },
                    "a2_minus_a0": {
                        key: _delta(arms["A2"], arms["A0"], key)
                        for key in arms["A0"]["totals"]
                    },
                    "a1_selection_divergence_from_a0": (
                        arms["A1"]["selection_sequence"]
                        != arms["A0"]["selection_sequence"]
                    ),
                    "physical_eviction_divergence": {
                        arm: arms[arm]["physical_eviction_signature"]
                        != arms["A0"]["physical_eviction_signature"]
                        for arm in ("A1", "A2")
                    },
                    "arms": arms,
                }
            )
    groups: list[dict[str, Any]] = []
    for group_id in sorted({row["group_id"] for row in manifest["runs"]}):
        rows = [row for row in cells if row["group_id"] == group_id]
        complete = len(rows) == 2 and all(row["status"] == "VALID" for row in rows)
        effects: dict[str, int | None] = {}
        for arm in ("a1", "a2"):
            values = [
                row[f"{arm}_minus_a0"]["aggregate_recomputed_tokens"]
                for row in rows
                if row.get(f"{arm}_minus_a0")
            ]
            effects[f"{arm}_minus_a0_recomputed_tokens"] = (
                sum(int(value) for value in values if value is not None)
                if complete and all(value is not None for value in values)
                else None
            )
        groups.append(
            {
                "group_id": group_id,
                "status": "COMPLETE" if complete else "INCOMPLETE",
                **effects,
            }
        )
    summary: dict[str, Any] = {}
    for arm in ("a1", "a2"):
        key = f"{arm}_minus_a0_recomputed_tokens"
        values = [row[key] for row in groups if row[key] is not None]
        summary[arm] = {
            "comparable_group_count": len(values),
            "mean_delta": statistics.mean(values) if values else None,
            "median_delta": statistics.median(values) if values else None,
            "better": sum(value < 0 for value in values),
            "worse": sum(value > 0 for value in values),
            "tied": sum(value == 0 for value in values),
        }
    complete = not missing and len(evaluated) == 54 and all(
        row["status"] == "COMPLETE" for row in groups
    )
    mechanism_status_counts = dict(
        sorted(Counter(row["mechanism_status"] for row in evaluated.values()).items())
    )
    profile_ordering_status_counts = dict(
        sorted(
            Counter(
                row["profile_cost_ordering_status"] for row in evaluated.values()
            ).items()
        )
    )
    return {
        "schema_version": "continuum.native_costaware_bounded_report.v1",
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha(manifest_path),
        "planned_run_count": 54,
        "evaluated_run_count": len(evaluated),
        "missing_run_ids": missing,
        "cells": cells,
        "groups": groups,
        "summary": summary,
        "mechanism_status_counts": mechanism_status_counts,
        "profile_cost_ordering_status_counts": profile_ordering_status_counts,
        "gate": "PASS" if complete else "INCONCLUSIVE",
        "statistical_unit_count": 9,
        "claim_scope": "EXPLORATORY_PAIRED_COMPARISON_ON_PREDEFINED_GROUP_GRID",
        "content_level_causal_attribution": "NOT_ESTABLISHED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(manifest_path=args.manifest, runs_root=args.runs_root)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"bounded report: {report['gate']}")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
