"""Build the bounded W1-B Native A0/A1/A2 comparison report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

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
    inputs = {
        str(row["request_id"]): str(row["payload"]["submitted_token_ids_sha256"])
        for row in _events(run, "BACKEND_INPUT_MATERIALIZED")
        if row.get("payload", {}).get("kind") == "turn"
    }
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
    checks = {
        "execution_success": run.manifest.get("execution_status") == "success",
        "config_binding": run.manifest.get("config_sha256") == binding["config_sha256"],
        "trace_binding": run.manifest.get("trace_sha256") == binding["trace_sha256"],
        "request_completeness": token_complete,
        "input_digest_completeness": set(inputs) == set(expected_request_ids),
    }
    return {
        "run_id": run.run_id,
        "group_id": stage["group_id"],
        "arm": stage["arm"],
        "status": "VALID" if all(checks.values()) else "INVALID",
        "checks": checks,
        "input_digests": inputs,
        "expected_request_ids": expected_request_ids,
        "missing_request_ids": missing,
        "extra_request_ids": extra,
        "unavailable_request_ids": unavailable,
        "selection_sequence": _selection_sequence(run),
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
    evaluated = {
        row["run_id"]: evaluate_run(runs_root / row["run_id"], row) for row in manifest["runs"]
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
        forced = all(row["forced_release_decision_count"] > 0 for row in arms.values())
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
    return {
        "schema_version": "continuum.w1b_native_comparison_report.v1",
        "scope": "BOUNDED_NATIVE_COMPARABILITY_SMOKE",
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha(manifest_path),
        "planned_run_count": manifest["planned_run_count"],
        "evaluated_run_count": len(evaluated),
        "valid_group_count": sum(
            row["status"] == "VALID_BOUNDED_MECHANISM_SMOKE" for row in groups
        ),
        "groups": groups,
        "gate": "PASS" if complete else "FAIL",
        "research_claim": "BOUNDED_SMOKE_ONLY_NO_FORMAL_BENEFIT_CLAIM",
        "limitations": [
            "one runtime repeat per arm and group",
            "controlled timing is not the observed W1-A arrival process",
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
