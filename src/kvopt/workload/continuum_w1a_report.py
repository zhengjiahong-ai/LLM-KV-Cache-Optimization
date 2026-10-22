"""Build the bounded W1-A acquisition report from immutable run evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from itertools import combinations
from pathlib import Path


def _load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lcp_length(left: list[int], right: list[int]) -> int:
    length = 0
    for left_token, right_token in zip(left, right, strict=False):
        if left_token != right_token:
            break
        length += 1
    return length


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def build_report(root: Path) -> dict[str, object]:
    run_dirs = sorted(path.parent for path in root.glob("*/run.json"))
    if not run_dirs:
        raise ValueError("no W1-A run manifests found")
    tasks: list[dict[str, object]] = []
    first_tokens: dict[str, list[int]] = {}
    all_model_elapsed: list[float] = []
    all_tool_elapsed: list[float] = []
    all_inter_request_gap: list[float] = []
    all_post_tool_gap: list[float] = []

    for run_dir in run_dirs:
        run_path = run_dir / "run.json"
        sidecar_path = run_dir / "acquisition-sidecar.json"
        trajectory_path = run_dir / f"{run_dir.name}.traj.json"
        evidence_path = run_dir / "converted" / "acquisition-evidence.json"
        validation_path = run_dir / "converted" / "validation-report.json"
        required = [sidecar_path, trajectory_path, evidence_path, validation_path]
        if any(not path.is_file() for path in required):
            raise ValueError(f"incomplete W1-A run evidence: {run_dir.name}")
        run = _load_object(run_path)
        sidecar = _load_object(sidecar_path)
        evidence = _load_object(evidence_path)
        validation = _load_object(validation_path)
        instance_id = str(run.get("instance_id"))
        if instance_id != run_dir.name or sidecar.get("program_id") != instance_id:
            raise ValueError("run directory, manifest, and sidecar identity mismatch")
        model_calls = sidecar.get("model_calls")
        tool_calls = sidecar.get("tool_calls")
        requests = evidence.get("requests")
        if not isinstance(model_calls, list) or not isinstance(tool_calls, list):
            raise TypeError("sidecar call collections must be lists")
        if not isinstance(requests, list) or len(requests) != len(model_calls):
            raise ValueError("converted request count does not match model calls")
        token_sequences: list[list[int]] = []
        model_elapsed: list[float] = []
        tool_elapsed: list[float] = []
        for call, request in zip(model_calls, requests, strict=True):
            if not isinstance(call, dict) or not isinstance(request, dict):
                raise TypeError("request observations must be objects")
            tokens = call.get("submitted_token_ids")
            if not isinstance(tokens, list) or any(not isinstance(token, int) for token in tokens):
                raise ValueError("deterministic submitted token observation is incomplete")
            token_sequences.append(tokens)
            model_elapsed.append(float(request["model_elapsed_seconds"]))
            tool = request.get("tool_evidence")
            if isinstance(tool, dict):
                tool_elapsed.append(float(tool["tool_elapsed_seconds"]))
        first_tokens[instance_id] = token_sequences[0]
        inter_request_gap = [
            float(model_calls[index]["model_submit_monotonic_seconds"])
            - float(model_calls[index - 1]["model_completion_monotonic_seconds"])
            for index in range(1, len(model_calls))
        ]
        tool_by_request = {
            str(call["request_id"]): call for call in tool_calls if isinstance(call, dict)
        }
        post_tool_gap: list[float] = []
        for index in range(1, len(model_calls)):
            previous_id = str(model_calls[index - 1]["request_id"])
            tool = tool_by_request.get(previous_id)
            if tool is not None:
                post_tool_gap.append(
                    float(model_calls[index]["model_submit_monotonic_seconds"])
                    - float(tool["tool_completion_monotonic_seconds"])
                )
        if any(value < 0 for value in [*inter_request_gap, *post_tool_gap]):
            raise ValueError("observed request/tool timing is out of order")
        lengths = [len(tokens) for tokens in token_sequences]
        all_model_elapsed.extend(model_elapsed)
        all_tool_elapsed.extend(tool_elapsed)
        all_inter_request_gap.extend(inter_request_gap)
        all_post_tool_gap.extend(post_tool_gap)
        tasks.append(
            {
                "instance_id": instance_id,
                "agent_exit_status": run.get("agent_exit_status"),
                "agent_outcome": run.get("agent_outcome"),
                "conversion_verdict": validation.get("verdict"),
                "model_call_count": len(model_calls),
                "tool_call_count": len(tool_calls),
                "initial_prompt_tokens": lengths[0],
                "maximum_prompt_tokens": max(lengths),
                "context_growth_tokens": max(lengths) - lengths[0],
                "all_successive_requests_preserve_token_prefix": evidence.get(
                    "submitted_token_prefix_growth_all_turns"
                ),
                "wrapper_timing_complete": evidence.get("wrapper_timing_complete"),
                "deterministic_tokenization_complete": evidence.get(
                    "deterministic_tokenization_complete"
                ),
                "native_runtime_submitted_token_ids_observed": evidence.get(
                    "native_runtime_submitted_token_ids_observed"
                ),
                "median_model_elapsed_seconds": _median(model_elapsed),
                "median_tool_elapsed_seconds": _median(tool_elapsed),
                "median_inter_request_gap_seconds": _median(inter_request_gap),
                "evidence_sha256": {
                    "run": _sha256(run_path),
                    "trajectory": _sha256(trajectory_path),
                    "sidecar": _sha256(sidecar_path),
                    "acquisition_evidence": _sha256(evidence_path),
                    "validation": _sha256(validation_path),
                },
            }
        )

    cross_session = []
    for left_id, right_id in combinations(sorted(first_tokens), 2):
        cross_session.append(
            {
                "left_instance_id": left_id,
                "right_instance_id": right_id,
                "first_request_lcp_tokens": _lcp_length(
                    first_tokens[left_id], first_tokens[right_id]
                ),
            }
        )
    complete = all(
        task["conversion_verdict"] == "CONDITIONAL_PASS"
        and task["wrapper_timing_complete"] is True
        and task["deterministic_tokenization_complete"] is True
        for task in tasks
    )
    submitted = sum(task["agent_outcome"] == "SUBMITTED" for task in tasks)
    recommendation = "CONDITIONAL_GO" if complete and submitted >= 1 else "NO_GO"
    return {
        "schema_version": "continuum.w1a_acquisition_report.v1",
        "scope": "BOUNDED_TRAJECTORY_ACQUISITION_NO_NATIVE_CAMPAIGN",
        "task_count": len(tasks),
        "tasks": tasks,
        "missingness": {
            "submitted_task_count": submitted,
            "incomplete_task_count": sum(
                task["agent_outcome"] == "INCOMPLETE" for task in tasks
            ),
            "failed_task_count": sum(task["agent_outcome"] == "FAILED" for task in tasks),
            "native_runtime_token_ids_missing_task_count": sum(
                task["native_runtime_submitted_token_ids_observed"] is not True
                for task in tasks
            ),
            "native_apc_or_kv_residency_observed": False,
        },
        "aggregate": {
            "model_call_count": sum(task["model_call_count"] for task in tasks),
            "tool_call_count": sum(task["tool_call_count"] for task in tasks),
            "maximum_prompt_tokens": max(task["maximum_prompt_tokens"] for task in tasks),
            "median_model_elapsed_seconds": _median(all_model_elapsed),
            "median_tool_elapsed_seconds": _median(all_tool_elapsed),
            "median_inter_request_gap_seconds": _median(all_inter_request_gap),
            "median_post_tool_gap_seconds": _median(all_post_tool_gap),
        },
        "cross_session_first_request_prefix": {
            "pair_count": len(cross_session),
            "minimum_lcp_tokens": min(
                row["first_request_lcp_tokens"] for row in cross_session
            ),
            "maximum_lcp_tokens": max(
                row["first_request_lcp_tokens"] for row in cross_session
            ),
            "pairs": cross_session,
            "interpretation": "TOKEN_PREFIX_IDENTITY_ONLY_NOT_NATIVE_APC_OR_RESIDENCY",
        },
        "evidence_boundaries": {
            "logical_message_growth": "OBSERVED",
            "deterministic_token_prefix_identity": "OBSERVED_NOT_RUNTIME_SUBMISSION",
            "wrapper_request_and_tool_timing": "OBSERVED",
            "native_apc_sharing": "NOT_OBSERVED",
            "physical_kv_residency": "NOT_OBSERVED",
            "continuum_paper_workload_reproduction": "NOT_CLAIMED",
        },
        "recommendation": recommendation,
        "recommendation_reason": (
            "The frozen sample produced auditable multi-turn tool trajectories and at least "
            "one submitted task, but most tasks reached the unchanged author step limit and "
            "Native APC/residency was outside this acquisition scope."
        ),
    }


def _markdown(report: dict[str, object]) -> str:
    aggregate = report["aggregate"]
    missingness = report["missingness"]
    assert isinstance(aggregate, dict) and isinstance(missingness, dict)
    lines = [
        "# Continuum W1-A Bounded Trajectory Acquisition",
        "",
        f"**Recommendation:** `{report['recommendation']}`",
        "",
        "## Result",
        "",
        f"- Frozen tasks acquired: {report['task_count']}",
        f"- Submitted tasks: {missingness['submitted_task_count']}",
        f"- Incomplete tasks: {missingness['incomplete_task_count']}",
        f"- Model calls: {aggregate['model_call_count']}",
        f"- Tool calls: {aggregate['tool_call_count']}",
        f"- Maximum prompt tokens: {aggregate['maximum_prompt_tokens']}",
        "",
        "## Evidence boundary",
        "",
        (
            "Logical message growth, deterministic token-prefix identity, and "
            "wrapper-boundary request/tool timing are observed. Native APC sharing, "
            "physical KV residency, and the original Continuum paper workload are not "
            "claimed."
        ),
        "",
        "## Missingness",
        "",
        (
            f"{missingness['incomplete_task_count']} tasks did not submit before the "
            "unchanged author 50-step limit. Deterministic local "
            "tokenization is available for every request, but runtime-submitted token IDs "
            "were not exposed by the serving API."
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.runs_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "w1a-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_root / "w1a-report.md").write_text(
        _markdown(report), encoding="utf-8"
    )
    print(f"wrote W1-A acquisition report: {args.output_root / 'w1a-report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
