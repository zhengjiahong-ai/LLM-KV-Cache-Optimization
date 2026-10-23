"""Build the bounded W1-B Native A0/A1/A2 comparison report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from itertools import pairwise
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


def _selection_sequence(run: object) -> list[list[str]]:
    return [
        [
            str(release["program_id"])
            for release in row.get("payload", {}).get("selected_releases", [])
        ]
        for row in _events(run, "FORCED_RELEASE_DECISION")
    ]


def _timing_evidence(run: object) -> dict[str, Any]:
    submitted = {
        str(row["request_id"]): row
        for row in _events(run, "VLLM_REQUEST_SUBMITTED")
        if row.get("program_id") and not str(row["program_id"]).startswith("pressure:")
    }
    completed = {
        str(row["request_id"]): row
        for row in _events(run, "VLLM_REQUEST_COMPLETED")
        if row.get("program_id") and not str(row["program_id"]).startswith("pressure:")
    }
    rows: list[dict[str, Any]] = []
    by_program: dict[str, list[dict[str, Any]]] = {}
    for request in run.trace["requests"]:  # type: ignore[attr-defined]
        by_program.setdefault(str(request["program_id"]), []).append(request)
    for program_id, requests in by_program.items():
        ordered = sorted(requests, key=lambda row: int(row["turn_index"]))
        for previous, current in pairwise(ordered):
            previous_event = completed.get(str(previous["request_id"]))
            current_event = submitted.get(str(current["request_id"]))
            gap = (
                None
                if previous_event is None or current_event is None
                else float(current_event["timestamp"]) - float(previous_event["timestamp"])
            )
            rows.append(
                {
                    "program_id": program_id,
                    "previous_request_id": previous["request_id"],
                    "next_request_id": current["request_id"],
                    "post_completion_gap_seconds": gap,
                    "completion_barrier_satisfied": gap is not None and gap >= 0.0,
                }
            )
    return {
        "executed_schedule": (
            "ABSOLUTE_PLANNED_OFFSETS_WITH_PER_SESSION_COMPLETION_BARRIER_"
            "ZERO_MINIMUM_POST_COMPLETION_GAP"
        ),
        "observed_tool_gap_replay_claimed": False,
        "transitions": rows,
        "all_completion_barriers_satisfied": bool(rows)
        and all(row["completion_barrier_satisfied"] for row in rows),
    }


def _decision_evidence(run: object) -> list[dict[str, Any]]:
    native_observations = _events(run, "VLLM_NATIVE_REQUEST_OBSERVATION")
    evictions = _events(run, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
    rows: list[dict[str, Any]] = []
    for decision in _events(run, "FORCED_RELEASE_DECISION"):
        payload = decision.get("payload", {})
        index = int(decision["event_index"])
        downstream = [
            {
                "event_index": int(event["event_index"]),
                "request_id": event.get("request_id"),
                "program_id": event.get("program_id"),
            }
            for event in native_observations
            if int(event["event_index"]) > index and not str(event.get("program_id", "")).startswith("pressure:")
        ]
        post_evictions = [
            int(event["event_index"])
            for event in evictions
            if int(event["event_index"]) > index
            and event.get("payload", {}).get("hash_removed_after") is True
            and event.get("payload", {}).get("native_cache_key_before")
        ]
        rows.append(
            {
                "event_index": index,
                "candidate_count": len(payload.get("candidates", [])),
                "selected_release_count": len(payload.get("selected_releases", [])),
                "selected_program_ids": [
                    row.get("program_id") for row in payload.get("selected_releases", [])
                ],
                "post_decision_physical_eviction_event_indexes": post_evictions,
                "downstream_request_links": downstream,
                "exposure_complete": bool(payload.get("candidates"))
                and bool(payload.get("selected_releases")),
                "post_release_native_hash_evidence_available": bool(post_evictions),
                "downstream_evidence_available": bool(downstream),
            }
        )
    return rows


def _unique_materialized_digests(
    events: list[dict[str, Any]],
) -> tuple[dict[str, str], Counter[str]]:
    counts = Counter(str(row["request_id"]) for row in events)
    return (
        {
            str(row["request_id"]): str(row["payload"]["submitted_token_ids_sha256"])
            for row in events
            if counts[str(row["request_id"])] == 1
        },
        counts,
    )


def _frozen_input_digests(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    freeze_path = Path(str(manifest["freeze_path"]))
    if _sha(freeze_path) != manifest.get("freeze_sha256"):
        raise ValueError("W1-B freeze binding mismatch")
    freeze = _load(freeze_path)
    source_path = Path(str(freeze["source_replay_manifest"]))
    if _sha(source_path) != freeze.get("source_replay_manifest_sha256"):
        raise ValueError("W1-B source replay manifest binding mismatch")
    source = _load(source_path)
    sessions = {row["session_id"]: row for row in source["sessions"]}
    result: dict[str, dict[str, str]] = {}
    for group in freeze["groups"]:
        group_digests: dict[str, str] = {}
        for selected in group["sessions"]:
            binding = sessions[selected["session_id"]]
            session_path = source_path.parent / binding["path"]
            if _sha(session_path) != binding["sha256"]:
                raise ValueError("W1-B source session binding mismatch")
            session = _load(session_path)
            rows = [session["requests"][turn - 1] for turn in selected["selected_turns"]]
            if [row["token_ids_sha256"] for row in rows] != selected["selected_token_sha256"]:
                raise ValueError("W1-B selected source digest binding mismatch")
            group_digests.update(
                {
                    str(row["request_id"]): token_ids_sha256(row["token_ids"])
                    for row in rows
                }
            )
        result[str(group["group_id"])] = group_digests
    return result


def evaluate_run(run_dir: Path, binding: dict[str, Any]) -> dict[str, Any]:
    run = load_run_artifacts(run_dir)
    config = _load(run_dir / "config.json")
    stage = config["continuum_w1b_stage"]
    expected_request_ids = [str(row["request_id"]) for row in run.trace["requests"]]
    evidence = {
        row.request_id: row
        for row in build_request_runtime_evidence_table((run,))
        if row.kind == "turn"
    }
    missing = sorted(set(expected_request_ids) - set(evidence))
    extra = sorted(set(evidence) - set(expected_request_ids))
    unavailable = sorted(
        request_id for request_id, row in evidence.items() if row.availability != "AVAILABLE"
    )
    materialized_events = [
        row
        for row in _events(run, "BACKEND_INPUT_MATERIALIZED")
        if row.get("payload", {}).get("kind") == "turn"
    ]
    inputs, materialized_counts = _unique_materialized_digests(materialized_events)
    config_expected_inputs = {
        request_id: token_ids_sha256(token_ids)
        for request_id, token_ids in config["backend_options"]["replay_token_ids_by_request"].items()
    }
    expected_inputs = binding["frozen_input_digests"]
    rows = {
        request_id: {
            "program_id": row.program_id,
            "native_prompt_tokens": row.native_prompt_tokens,
            "eligible_prefix_tokens": row.eligible_prefix_tokens,
            "native_cached_prefix_tokens": row.native_cached_prefix_tokens,
            "actual_prefill_tokens": row.actual_prefill_tokens,
            "observed_recomputed_tokens": row.observed_recomputed_tokens,
            "new_suffix_tokens": (
                None
                if row.native_prompt_tokens is None or row.eligible_prefix_tokens is None
                else row.native_prompt_tokens - row.eligible_prefix_tokens
            ),
            "apc_outcome": row.apc_outcome,
        }
        for request_id, row in sorted(evidence.items())
    }
    token_complete = not missing and not extra and not unavailable
    totals = {
        "request_count": len(rows),
        "aggregate_actual_prefill_tokens": (
            sum(int(row["actual_prefill_tokens"]) for row in rows.values())
            if token_complete
            else None
        ),
        "aggregate_recomputed_tokens": (
            sum(int(row["observed_recomputed_tokens"]) for row in rows.values())
            if token_complete
            else None
        ),
        "aggregate_new_suffix_tokens": (
            sum(int(row["new_suffix_tokens"]) for row in rows.values()) if token_complete else None
        ),
    }
    event_counts = Counter(str(row["event_type"]) for row in run.events)
    a2_decisions = _events(run, "COST_AWARE_BLOCK_DECISION")
    a2_internal_divergence = sum(
        set(row.get("payload", {}).get("selected_victims", []))
        != set(row.get("payload", {}).get("native_lru_victims", []))
        for row in a2_decisions
    )
    timing = _timing_evidence(run)
    decisions = _decision_evidence(run)
    checks = {
        "execution_success": run.manifest.get("execution_status") == "success",
        "config_binding": run.manifest.get("config_sha256") == binding["config_sha256"],
        "trace_binding": run.manifest.get("trace_sha256") == binding["trace_sha256"],
        "request_completeness": token_complete,
        "input_digest_completeness": set(inputs) == set(expected_request_ids),
        "input_materialization_unique": all(
            materialized_counts[request_id] == 1 for request_id in expected_request_ids
        ),
        "frozen_source_input_identity": inputs == expected_inputs,
        "config_matches_frozen_source": config_expected_inputs == expected_inputs,
        "completion_barrier_timing": timing["all_completion_barriers_satisfied"],
    }
    return {
        "run_id": run.run_id,
        "group_id": stage["group_id"],
        "arm": stage["arm"],
        "status": "VALID" if all(checks.values()) else "INVALID",
        "checks": checks,
        "input_digests": inputs,
        "expected_input_digests": expected_inputs,
        "input_materialization_counts": dict(sorted(materialized_counts.items())),
        "expected_request_ids": expected_request_ids,
        "missing_request_ids": missing,
        "extra_request_ids": extra,
        "unavailable_request_ids": unavailable,
        "selection_sequence": _selection_sequence(run),
        "timing_evidence": timing,
        "forced_release_decisions": decisions,
        "forced_release_decision_count": event_counts["FORCED_RELEASE_DECISION"],
        "a1_decision_count": event_counts["COST_AWARE_RELEASE_DECISION"],
        "a2_decision_count": event_counts["COST_AWARE_BLOCK_DECISION"],
        "a2_internal_native_lru_divergence_count": a2_internal_divergence,
        "physical_eviction_count": event_counts["VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"],
        "right_censored_window_end_count": event_counts["W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED"],
        "totals": totals,
        "request_outcomes": rows,
    }


def _delta(candidate: dict[str, Any], baseline: dict[str, Any], key: str) -> int | None:
    left = candidate["totals"][key]
    right = baseline["totals"][key]
    return None if left is None or right is None else int(left) - int(right)


def build_report(*, manifest_path: Path, runs_root: Path) -> dict[str, Any]:
    manifest = _load(manifest_path)
    frozen_inputs = _frozen_input_digests(manifest)
    evaluated = {
        row["run_id"]: evaluate_run(
            runs_root / row["run_id"],
            {**row, "frozen_input_digests": frozen_inputs[row["group_id"]]},
        )
        for row in manifest["runs"]
    }
    groups: list[dict[str, Any]] = []
    for group_id in sorted({row["group_id"] for row in manifest["runs"]}):
        arms = {arm: evaluated[f"{group_id}-{arm.lower()}-repeat-1"] for arm in ("A0", "A1", "A2")}
        inputs_equal = (
            arms["A0"]["input_digests"]
            == arms["A1"]["input_digests"]
            == arms["A2"]["input_digests"]
        )
        all_valid = all(row["status"] == "VALID" for row in arms.values())
        native_comparable = all_valid and inputs_equal
        forced = all(
            row["forced_release_decisions"]
            and all(item["exposure_complete"] for item in row["forced_release_decisions"])
            for row in arms.values()
        )
        downstream = all(
            all(
                item["post_release_native_hash_evidence_available"]
                and item["downstream_evidence_available"]
                for item in row["forced_release_decisions"]
            )
            for row in arms.values()
        )
        groups.append(
            {
                "group_id": group_id,
                "status": (
                    "VALID_BOUNDED_MECHANISM_SMOKE"
                    if all_valid and inputs_equal and forced
                    else "VALID_REPLAY_NO_DECISION_EXPOSURE"
                    if all_valid and inputs_equal
                    else "INVALID"
                ),
                "cross_arm_input_identity": inputs_equal,
                "native_input_and_runtime_comparability": (
                    "PASS_NATIVE_INPUT_AND_RUNTIME_COMPARABILITY"
                    if native_comparable
                    else "FAIL_NATIVE_INPUT_AND_RUNTIME_COMPARABILITY"
                ),
                "forced_release_decision_exposure": (
                    "PASS_FORCED_RELEASE_DECISION_EXPOSURE"
                    if forced
                    else "NOT_DEMONSTRATED"
                ),
                "downstream_apc_recomputation_evidence": (
                    "AVAILABLE" if downstream else "MISSING"
                ),
                "selection_sequences": {
                    arm: row["selection_sequence"] for arm, row in arms.items()
                },
                "a1_minus_a0": {
                    key: _delta(arms["A1"], arms["A0"], key)
                    for key in (
                        "aggregate_recomputed_tokens",
                        "aggregate_actual_prefill_tokens",
                        "aggregate_new_suffix_tokens",
                    )
                },
                "a2_minus_a0": {
                    key: _delta(arms["A2"], arms["A0"], key)
                    for key in (
                        "aggregate_recomputed_tokens",
                        "aggregate_actual_prefill_tokens",
                        "aggregate_new_suffix_tokens",
                    )
                },
                "arms": arms,
            }
        )
    complete = len(evaluated) == 12 and all(
        row["status"] == "VALID_BOUNDED_MECHANISM_SMOKE" for row in groups
    )
    profile_path = Path(str(manifest["profile_path"]))
    profile = _load(profile_path)
    expected_model = {
        "name": "Qwen/Qwen2.5-Coder-3B-Instruct",
        "revision": "2ffd030b308f6bdd29ee43e7383f30ce8ac2e225",
        "tokenizer_revision": "2ffd030b308f6bdd29ee43e7383f30ce8ac2e225",
    }
    profile_checks = {
        "sha256_binding": _sha(profile_path) == manifest.get("profile_sha256"),
        "schema": profile.get("schema") == "continuum.prefill_reload.w1b_long_context_profile.v1",
        "status": profile.get("status") == "complete",
        "model_tokenizer_provenance": profile.get("model") == expected_model,
        "bounded_protocol": profile.get("protocol", {}).get("warmup_pairs_per_point") == 5
        and profile.get("protocol", {}).get("measured_pairs_per_point") == 20
        and profile.get("protocol", {}).get("extrapolation") == "PROHIBITED",
        "measured_grid": [row.get("token_count") for row in profile.get("points", [])]
        == [256, 1024, 2048, 3072, 4096, 5120],
    }
    coverage_path = manifest_path.parent / "prefill-reload-coverage-audit.json"
    coverage = _load(coverage_path) if coverage_path.is_file() else {}
    profile_checks["query_coverage_16_of_16"] = (
        coverage.get("execution_gate") == "PASS"
        and coverage.get("query_count") == 16
        and coverage.get("supported_query_count") == 16
    )
    complete = complete and all(profile_checks.values())
    return {
        "schema_version": "continuum.w1b_native_comparison_report.v2",
        "scope": "REAL_AGENT_CONTENT_CONTROLLED_SPARSE_TURN_PRESSURE_REPLAY",
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha(manifest_path),
        "planned_run_count": manifest["planned_run_count"],
        "evaluated_run_count": len(evaluated),
        "valid_group_count": sum(
            row["status"] == "VALID_BOUNDED_MECHANISM_SMOKE" for row in groups
        ),
        "groups": groups,
        "profile_qualification": profile_checks,
        "gate": "PASS" if complete else "FAIL",
        "research_claim": "BOUNDED_SMOKE_ONLY_NO_FORMAL_BENEFIT_CLAIM",
        "limitations": [
            "one runtime repeat per arm and group",
            "controlled timing is not the observed W1-A arrival process",
            "no positive post-completion tool gap was enforced",
            "pressure execution used a drain barrier",
            "physical eviction counts are descriptive and not per-block causal attribution",
            "results do not represent the Continuum paper's original serving trace",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(manifest_path=args.manifest, runs_root=args.runs_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"W1-B bounded Native comparison: {report['gate']} -> {args.output}")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
