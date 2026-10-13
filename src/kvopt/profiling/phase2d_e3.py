"""Fail-closed Gate D3 evaluation for paired logical-release intervention."""

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


def _decision_signature(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_blocks": payload.get("required_blocks"),
        "candidates": sorted(
            (
                row.get("program_id"),
                len(row.get("block_ids", [])),
                len(row.get("initially_reclaimable_block_ids", [])),
                row.get("waiting_followup"),
            )
            for row in payload.get("candidates", [])
        ),
        "free_queue": [
            (
                row.get("native_lru_rank"),
                row.get("has_block_hash"),
            )
            for row in payload.get("original_free_queue", [])
        ],
    }


def _extract_run(run_dir: Path) -> dict[str, Any]:
    run = _json(run_dir / "run.json")
    config = _json(run_dir / "config.json")
    events = _events(run_dir / "events.jsonl")
    stage = config.get("phase2d_stage")
    if not isinstance(stage, dict) or stage.get("stage") != "E3":
        raise ValueError(f"not an E3 run: {run_dir}")
    decisions = [row for row in events if row.get("event_type") == "FORCED_RELEASE_DECISION"]
    materialized = {
        str(row.get("request_id")): row.get("payload", {}).get("submitted_token_ids_sha256")
        for row in events
        if row.get("event_type") == "BACKEND_INPUT_MATERIALIZED"
    }
    native = {
        str(row.get("request_id")): row
        for row in events
        if row.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
    }
    reasons: list[str] = []
    if run.get("execution_status") != "success":
        reasons.append("execution did not succeed")
    if len(decisions) != 1:
        reasons.append("exactly one forced-release decision is required")
        decision_payload: dict[str, Any] = {}
    else:
        decision_payload = decisions[0].get("payload", {})
    candidates = decision_payload.get("candidates", [])
    candidate_programs = {row.get("program_id") for row in candidates}
    if candidate_programs != {"e3-a", "e3-b"} or len(candidates) != 2:
        reasons.append("decision must contain exactly the two expected candidates")
    relief = {row.get("program_id"): len(row.get("initially_reclaimable_block_ids", [])) for row in candidates}
    if set(relief.values()) != {4}:
        reasons.append("candidate marginal relief is not the frozen four blocks")
    selected = decision_payload.get("selected_releases", [])
    selected_programs = [row.get("program_id") for row in selected]
    expected_release = stage.get("forced_first_logical_release_program_id")
    if not selected_programs or selected_programs[0] != expected_release:
        reasons.append("first logical release does not match the diagnostic arm")
    target = str(stage.get("evaluation_program"))
    target_request = f"{target}:2"
    target_event = native.get(target_request)
    recomputed_tokens: int | None = None
    cached_tokens: int | None = None
    prompt_tokens: int | None = None
    if target_event is None:
        reasons.append("target return lacks native APC observation")
    else:
        payload = target_event.get("payload", {})
        cached_tokens = payload.get("native_cached_prefix_tokens")
        prompt_tokens = payload.get("native_prompt_tokens")
        if not isinstance(cached_tokens, int) or not isinstance(prompt_tokens, int):
            reasons.append("target return has invalid native token counts")
        elif cached_tokens < 0 or cached_tokens > prompt_tokens:
            reasons.append("target cached-prefix tokens are out of range")
        else:
            recomputed_tokens = prompt_tokens - cached_tokens
    return {
        "run_id": run.get("run_id"),
        "case_id": stage.get("case_id"),
        "arm": stage.get("arm"),
        "repeat": stage.get("repeat"),
        "evaluation_program": target,
        "expected_first_logical_release": expected_release,
        "observed_release_sequence": selected_programs,
        "candidate_marginal_relief_blocks": relief,
        "decision_signature": _decision_signature(decision_payload),
        "materialized_content_digests": materialized,
        "target_request_id": target_request,
        "native_cached_prefix_tokens": cached_tokens,
        "native_prompt_tokens": prompt_tokens,
        "observed_recomputed_tokens": recomputed_tokens,
        "native_physical_victim_forced": False,
        "reasons": reasons,
    }


def evaluate_e3(runs_root: Path) -> dict[str, Any]:
    runs = [_extract_run(path.parent) for path in sorted(runs_root.glob("*/run.json"))]
    by_pair = {(str(row["case_id"]), int(row["repeat"]), str(row["arm"])): row for row in runs}
    pairs: list[dict[str, Any]] = []
    expected_cases = ("e3-target-a-headroom", "e3-target-b-control")
    for case_id in expected_cases:
        for repeat in (1, 2):
            arm_a = by_pair.get((case_id, repeat, "release-a"))
            arm_b = by_pair.get((case_id, repeat, "release-b"))
            reasons: list[str] = []
            if arm_a is None or arm_b is None:
                reasons.append("both paired arms are required")
            else:
                reasons.extend(f"release-a: {value}" for value in arm_a["reasons"])
                reasons.extend(f"release-b: {value}" for value in arm_b["reasons"])
                if arm_a["decision_signature"] != arm_b["decision_signature"]:
                    reasons.append("pre-decision pressure/candidate/free-queue state differs")
                if arm_a["materialized_content_digests"] != arm_b["materialized_content_digests"]:
                    reasons.append("materialized workload content differs between arms")
                if arm_a["candidate_marginal_relief_blocks"] != arm_b["candidate_marginal_relief_blocks"]:
                    reasons.append("candidate capacity relief differs between arms")
            delta: int | None = None
            if not reasons and arm_a is not None and arm_b is not None:
                left = arm_a["observed_recomputed_tokens"]
                right = arm_b["observed_recomputed_tokens"]
                if isinstance(left, int) and isinstance(right, int):
                    delta = left - right
                else:
                    reasons.append("paired native recomputation metric is unavailable")
            pairs.append(
                {
                    "case_id": case_id,
                    "repeat": repeat,
                    "status": "VALID" if not reasons else "INVALID",
                    "reasons": reasons,
                    "release_a_run": None if arm_a is None else arm_a["run_id"],
                    "release_b_run": None if arm_b is None else arm_b["run_id"],
                    "release_a_observed_recomputed_tokens": None if arm_a is None else arm_a["observed_recomputed_tokens"],
                    "release_b_observed_recomputed_tokens": None if arm_b is None else arm_b["observed_recomputed_tokens"],
                    "delta_recomputed_tokens_release_a_minus_release_b": delta,
                }
            )
    valid = [row for row in pairs if row["status"] == "VALID"]
    if len(valid) != 4:
        status = "COMPARABILITY_FAILED"
    elif any(row["delta_recomputed_tokens_release_a_minus_release_b"] != 0 for row in valid):
        status = "HEADROOM_OBSERVED"
    else:
        status = "NO_HEADROOM_IN_TESTED_FIXTURES"
    return {
        "schema_version": "phase2d.e3_gate.v1",
        "gate": "D3",
        "status": status,
        "intervention_layer": "FIRST_LOGICAL_RETENTION_RELEASE",
        "native_physical_victim_forced": False,
        "metric": "native_prompt_tokens - native_cached_prefix_tokens",
        "valid_pair_count": len(valid),
        "pairs": pairs,
        "runs": runs,
        "claim_boundary": "Local victim-selection headroom only; no predictability or policy-benefit claim.",
        "formal_claim": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = evaluate_e3(arguments.runs_root)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Gate D3 {result['status']}: {arguments.output}")
    return 0 if result["status"] in {"HEADROOM_OBSERVED", "NO_HEADROOM_IN_TESTED_FIXTURES"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
