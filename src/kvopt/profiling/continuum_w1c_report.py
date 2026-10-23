"""Build the bounded W1-C S50/S100 feasibility and opportunity report."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lcp(left: list[int], right: list[int]) -> int:
    count = 0
    for first, second in zip(left, right, strict=False):
        if first != second:
            break
        count += 1
    return count


def _classify(manifest: dict[str, Any]) -> str:
    if manifest.get("agent_outcome") == "SUBMITTED":
        return "NATURAL_COMPLETION"
    if manifest.get("agent_outcome") == "INCOMPLETE":
        return "RIGHT_CENSORED_STEP_LIMIT"
    reason = str(manifest.get("failure_reason", "")).lower()
    if "context" in reason or "maximum model length" in reason:
        return "FAILED_CONTEXT_LIMIT"
    if any(word in reason for word in ("docker", "connect", "timeout", "ssl")):
        return "FAILED_INFRASTRUCTURE"
    return "FAILED_OTHER"


def _run_row(run_dir: Path, instance_id: str, condition: str) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    if not manifest_path.is_file():
        return {"instance_id": instance_id, "condition": condition, "status": "MISSING"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if manifest.get("instance_id") != instance_id:
        problems.append("instance identity mismatch")
    if manifest.get("condition") != condition:
        problems.append("condition mismatch")
    trajectory_files = list(run_dir.glob("*.traj.json"))
    sidecar_path = run_dir / "acquisition-sidecar.json"
    sidecar: dict[str, Any] | None = None
    if trajectory_files:
        trajectory_path = trajectory_files[0]
        if manifest.get("trajectory_sha256") != _sha256(trajectory_path):
            problems.append("trajectory SHA-256 mismatch")
    elif manifest.get("model_call_count", 0):
        problems.append("model calls reported without trajectory")
    if sidecar_path.is_file():
        if manifest.get("sidecar_sha256") != _sha256(sidecar_path):
            problems.append("sidecar SHA-256 mismatch")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    elif manifest.get("model_call_count", 0):
        problems.append("model calls reported without sidecar")

    token_counts: list[int] = []
    lcps: list[int] = []
    model_elapsed: list[float] = []
    tool_elapsed: list[float] = []
    if sidecar is not None:
        calls = sidecar.get("model_calls", [])
        tools = sidecar.get("tool_calls", [])
        if len(calls) != manifest.get("model_call_count"):
            problems.append("model-call count mismatch")
        if len(tools) != manifest.get("tool_call_count"):
            problems.append("tool-call count mismatch")
        ids = [call.get("request_id") for call in calls]
        if len(ids) != len(set(ids)):
            problems.append("duplicate request identity")
        previous: list[int] | None = None
        for call in calls:
            tokens = call.get("submitted_token_ids")
            if not isinstance(tokens, list) or not all(isinstance(value, int) for value in tokens):
                problems.append("missing deterministic token IDs")
                continue
            token_counts.append(len(tokens))
            if previous is not None:
                lcps.append(_lcp(previous, tokens))
            previous = tokens
            start = call.get("model_submit_monotonic_seconds")
            end = call.get("model_completion_monotonic_seconds")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
                model_elapsed.append(float(end - start))
            else:
                problems.append("invalid model timing")
        for tool in tools:
            start = tool.get("tool_start_monotonic_seconds")
            end = tool.get("tool_completion_monotonic_seconds")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
                tool_elapsed.append(float(end - start))
            else:
                problems.append("invalid tool timing")
    return {
        "instance_id": instance_id,
        "repository": instance_id.split("__", 1)[0],
        "condition": condition,
        "status": "VALID" if not problems else "INVALID",
        "problems": problems,
        "outcome": _classify(manifest),
        "model_call_count": manifest.get("model_call_count", 0),
        "tool_call_count": manifest.get("tool_call_count", 0),
        "wall_elapsed_seconds": manifest.get("wall_elapsed_seconds"),
        "prompt_token_counts": token_counts,
        "max_prompt_tokens": max(token_counts, default=None),
        "context_growth_tokens": (
            token_counts[-1] - token_counts[0] if len(token_counts) >= 2 else None
        ),
        "adjacent_exact_lcp_tokens": lcps,
        "mean_adjacent_exact_lcp_tokens": statistics.mean(lcps) if lcps else None,
        "mean_model_elapsed_seconds": statistics.mean(model_elapsed) if model_elapsed else None,
        "mean_tool_elapsed_seconds": statistics.mean(tool_elapsed) if tool_elapsed else None,
        "token_identity_semantics": "PINNED_LOCAL_TOKENIZATION_NOT_NATIVE_SUBMISSION",
    }


def build_report(freeze_path: Path, runs_root: Path) -> dict[str, Any]:
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    ids = freeze.get("pilot_instance_ids")
    if not isinstance(ids, list) or len(ids) != 20 or len(set(ids)) != 20:
        raise ValueError("freeze must contain exactly 20 unique pilot tasks")
    expected = {(condition, instance_id) for condition in ("S50", "S100") for instance_id in ids}
    observed_dirs = {
        (condition, path.name)
        for condition in ("S50", "S100")
        for path in (runs_root / condition).iterdir()
        if path.is_dir()
    } if all((runs_root / condition).is_dir() for condition in ("S50", "S100")) else set()
    rows = [
        _run_row(runs_root / condition / instance_id, instance_id, condition)
        for instance_id in ids for condition in ("S50", "S100")
    ]
    row_by_key = {(row["condition"], row["instance_id"]): row for row in rows}
    pairs: list[dict[str, Any]] = []
    for instance_id in ids:
        s50 = row_by_key[("S50", instance_id)]
        s100 = row_by_key[("S100", instance_id)]
        comparable = s50["status"] == s100["status"] == "VALID"
        pairs.append({
            "instance_id": instance_id,
            "repository": instance_id.split("__", 1)[0],
            "comparable": comparable,
            "s50_outcome": s50.get("outcome"),
            "s100_outcome": s100.get("outcome"),
            "model_call_delta_s100_minus_s50": (
                s100["model_call_count"] - s50["model_call_count"] if comparable else None
            ),
            "tool_call_delta_s100_minus_s50": (
                s100["tool_call_count"] - s50["tool_call_count"] if comparable else None
            ),
            "max_prompt_token_delta_s100_minus_s50": (
                s100["max_prompt_tokens"] - s50["max_prompt_tokens"]
                if comparable and s100["max_prompt_tokens"] is not None and s50["max_prompt_tokens"] is not None
                else None
            ),
        })
    outcomes = Counter(row.get("outcome", row["status"]) for row in rows)
    comparable = sum(bool(pair["comparable"]) for pair in pairs)
    observed_repos = len({pair["repository"] for pair in pairs if pair["comparable"]})
    context_failures = outcomes["FAILED_CONTEXT_LIMIT"]
    infra_failures = outcomes["FAILED_INFRASTRUCTURE"]
    if comparable >= 16 and observed_repos >= 8 and context_failures <= 4 and infra_failures <= 4:
        recommendation = "GO_FOR_EXPANDED_WORKLOAD_REVIEW"
    elif comparable >= 10:
        recommendation = "CONDITIONAL_GO_WITH_LIMITATIONS"
    else:
        recommendation = "NO_GO_CURRENT_ACQUISITION_CONFIGURATION"
    family: dict[str, dict[str, int]] = defaultdict(lambda: {"tasks": 0, "comparable": 0})
    for pair in pairs:
        family[pair["repository"]]["tasks"] += 1
        family[pair["repository"]]["comparable"] += int(pair["comparable"])
    return {
        "schema_version": "continuum.w1c_feasibility_report.v1",
        "scope": "TRAJECTORY_FEASIBILITY_NOT_NATIVE_POLICY_EVALUATION",
        "freeze_sha256": _sha256(freeze_path),
        "expected_run_count": 40,
        "observed_expected_run_count": len(expected & observed_dirs),
        "missing_run_keys": sorted(f"{a}/{b}" for a, b in expected - observed_dirs),
        "extra_run_keys": sorted(f"{a}/{b}" for a, b in observed_dirs - expected),
        "valid_pair_count": comparable,
        "outcome_counts": dict(sorted(outcomes.items())),
        "repository_summary": dict(sorted(family.items())),
        "runs": rows,
        "pairs": pairs,
        "decision_opportunity_audit": {
            "observable": [
                "prompt_token_length", "adjacent_exact_token_lcp",
                "context_growth", "model_and_tool_boundary_timing",
            ],
            "decision_time_candidate_count": "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY",
            "marginal_newly_eligible_blocks": "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY",
            "pressure_requirement": "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY",
            "candidate_q_values_and_span": "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY",
            "policy_selection_divergence": "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY",
            "native_apc_or_kv_residency": "NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY",
        },
        "recommendation": recommendation,
        "recommendation_rules": {
            "go": "at least 16 valid pairs, 8 repositories, <=4 context failures, <=4 infrastructure failures",
            "conditional": "at least 10 valid pairs",
            "otherwise": "NO_GO_CURRENT_ACQUISITION_CONFIGURATION",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.freeze.resolve(), args.runs_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"W1-C feasibility: {report['recommendation']} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
