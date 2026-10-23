"""Build the bounded W1-C S50/S100 feasibility and opportunity report."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from kvopt.workload.continuum_w1a_conversion import build_sidecar_evidence


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lcp(left: list[int], right: list[int]) -> int:
    count = 0
    for first, second in zip(left, right, strict=False):
        if first != second:
            break
        count += 1
    return count


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _classify(manifest: dict[str, Any], trajectory: dict[str, Any] | None = None) -> str:
    if manifest.get("agent_outcome") == "SUBMITTED":
        return "NATURAL_COMPLETION"
    if manifest.get("agent_exit_status") == "ContextLengthExceeded":
        return "FAILED_CONTEXT_LIMIT"
    exit_status = manifest.get("agent_exit_status")
    if exit_status == "JobTimeoutError":
        return "FAILED_JOB_TIMEOUT"
    if exit_status == "LimitsExceeded":
        info = trajectory.get("info", {}) if trajectory else {}
        stats = info.get("model_stats", {}) if isinstance(info, dict) else {}
        calls = stats.get("api_calls") if isinstance(stats, dict) else None
        cost = stats.get("instance_cost") if isinstance(stats, dict) else None
        step_limit = manifest.get("effective_step_limit")
        cost_limit = manifest.get("cost_limit")
        if calls == step_limit and isinstance(cost, (int, float)) and cost < cost_limit:
            return "RIGHT_CENSORED_STEP_LIMIT"
        if isinstance(cost, (int, float)) and cost >= cost_limit:
            return "RIGHT_CENSORED_COST_LIMIT"
        return "INCOMPLETE_UNKNOWN_LIMIT"
    reason = str(manifest.get("failure_reason", "")).lower()
    if "context" in reason or "maximum model length" in reason:
        return "FAILED_CONTEXT_LIMIT"
    if any(word in reason for word in ("docker", "connect", "timeout", "ssl")):
        return "FAILED_INFRASTRUCTURE"
    return "FAILED_OTHER"


def _validate_context_limit_sidecar(
    sidecar: dict[str, Any], *, trajectory: dict[str, Any], trajectory_path: Path,
    instance_id: str, tokenize_messages: Any
) -> None:
    calls = sidecar.get("model_calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("context-limit sidecar lacks model calls")
    failed = calls[-1]
    if failed.get("status") == "SUCCESS" or any(
        call.get("status") != "SUCCESS" for call in calls[:-1]
    ):
        raise ValueError("context-limit sidecar must have one final failed call")
    successful_sidecar = copy.deepcopy(sidecar)
    successful_sidecar["model_calls"] = calls[:-1]
    failed_messages = failed.get("messages")
    trajectory_messages = trajectory.get("messages")
    if not isinstance(failed_messages, list) or not isinstance(trajectory_messages, list):
        raise TypeError("context-limit messages are not lists")
    if trajectory_messages[:-1] != failed_messages:
        raise ValueError("failed context request does not bind trajectory prefix")
    terminal_observation = trajectory_messages[-1]
    if (
        not isinstance(terminal_observation, dict)
        or terminal_observation.get("role") != "user"
        or str(terminal_observation.get("content", "")) not in str(failed.get("error", ""))
    ):
        raise ValueError("trajectory lacks the final context-limit observation")
    successful_trajectory = copy.deepcopy(trajectory)
    successful_trajectory["messages"] = failed_messages
    build_sidecar_evidence(
        successful_sidecar,
        trajectory=successful_trajectory,
        trajectory_path=trajectory_path,
        instance_id=instance_id,
        tokenize_messages=tokenize_messages,
    )
    if failed.get("messages_sha256") != _canonical_sha256(failed_messages):
        raise ValueError("failed context request messages SHA-256 mismatch")
    rendered, token_ids = tokenize_messages(failed_messages)
    if failed.get("rendered_prompt") != rendered:
        raise ValueError("failed context request rendered prompt mismatch")
    if failed.get("submitted_token_ids") != token_ids:
        raise ValueError("failed context request token IDs mismatch")
    if "maximum context length" not in str(failed.get("error", "")):
        raise ValueError("failed context request lacks context-limit evidence")
    expected_id = f"{instance_id}:turn:{len(calls)}"
    if failed.get("request_id") != expected_id:
        raise ValueError("failed context request identity mismatch")


def _run_row(
    run_dir: Path, instance_id: str, condition: str, *, config: dict[str, Any],
    config_path: Path, execution_git_sha: str, tokenize_messages: Any
) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    if not manifest_path.is_file():
        return {"instance_id": instance_id, "condition": condition, "status": "MISSING"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    expected_manifest = {
        "status": "completed",
        "instance_id": instance_id,
        "condition": condition,
        "config_sha256": _sha256(config_path),
        "repository_git_sha": execution_git_sha,
        "author_repository_git_sha": config["author_runner"]["commit"],
        "effective_step_limit": config["author_runner"]["effective_step_limit"],
        "cost_limit": config["author_runner"]["cost_limit"],
        "max_model_len": config["server_runtime"]["max_model_len"],
        "dataset": config["dataset"],
        "model": config["model"],
        "server_runtime": config["server_runtime"],
        "environment": config["environment"],
    }
    for field, value in expected_manifest.items():
        if manifest.get(field) != value:
            problems.append(f"run {field} binding mismatch")
    trajectory_files = list(run_dir.glob("*.traj.json"))
    sidecar_path = run_dir / "acquisition-sidecar.json"
    sidecar: dict[str, Any] | None = None
    trajectory: dict[str, Any] | None = None
    if trajectory_files:
        trajectory_path = trajectory_files[0]
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
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
    execution_binding_valid = not problems
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
        failed_calls = [call for call in calls if call.get("status") != "SUCCESS"]
        if trajectory is not None:
            trajectory_assistant_count = sum(
                message.get("role") == "assistant"
                for message in trajectory.get("messages", [])
            )
            successful_calls = len(calls) - len(failed_calls)
            if successful_calls != trajectory_assistant_count:
                problems.append("successful model calls do not match assistant turns")
            if failed_calls and not (
                len(failed_calls) == 1
                and manifest.get("agent_exit_status") == "ContextLengthExceeded"
                and calls[-1] is failed_calls[0]
                and "maximum context length" in str(failed_calls[0].get("error", ""))
            ):
                problems.append("failed model call is not a bound context-limit observation")
            execution_binding_valid = not problems
            try:
                if manifest.get("agent_exit_status") == "ContextLengthExceeded":
                    _validate_context_limit_sidecar(
                        sidecar,
                        trajectory=trajectory,
                        trajectory_path=trajectory_files[0],
                        instance_id=instance_id,
                        tokenize_messages=tokenize_messages,
                    )
                else:
                    build_sidecar_evidence(
                        sidecar,
                        trajectory=trajectory,
                        trajectory_path=trajectory_files[0],
                        instance_id=instance_id,
                        tokenize_messages=tokenize_messages,
                    )
            except (TypeError, ValueError) as error:
                problems.append(f"source-to-sidecar validation failed: {error}")
        previous: list[int] | None = None
        for call in calls:
            tokens = call.get("submitted_token_ids")
            if not isinstance(tokens, list) or not all(isinstance(value, int) for value in tokens):
                problems.append("missing deterministic token IDs")
                continue
            if call.get("status") != "SUCCESS":
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
        "execution_binding_valid": execution_binding_valid,
        "problems": problems,
        "outcome": _classify(manifest, trajectory),
        "model_call_count": manifest.get("model_call_count", 0),
        "successful_model_call_count": (
            sum(call.get("status") == "SUCCESS" for call in sidecar.get("model_calls", []))
            if sidecar is not None
            else 0
        ),
        "failed_model_call_count": (
            sum(call.get("status") != "SUCCESS" for call in sidecar.get("model_calls", []))
            if sidecar is not None
            else 0
        ),
        "tool_call_count": manifest.get("tool_call_count", 0),
        "wall_elapsed_seconds": manifest.get("wall_elapsed_seconds"),
        "prompt_token_counts": token_counts,
        "rejected_attempted_prompt_token_counts": (
            [
                len(call["submitted_token_ids"])
                for call in sidecar.get("model_calls", [])
                if call.get("status") != "SUCCESS"
                and isinstance(call.get("submitted_token_ids"), list)
            ]
            if sidecar is not None
            else []
        ),
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


def build_report(
    freeze_path: Path, runs_root: Path, *, s50_config_path: Path | None = None,
    s100_config_path: Path | None = None, authorization_path: Path | None = None,
    tokenize_messages: Any = None
) -> dict[str, Any]:
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    ids = freeze.get("pilot_instance_ids")
    if not isinstance(ids, list) or len(ids) != 20 or len(set(ids)) != 20:
        raise ValueError("freeze must contain exactly 20 unique pilot tasks")
    if any(path is None for path in (s50_config_path, s100_config_path, authorization_path)):
        if runs_root.exists() and any(runs_root.iterdir()):
            raise ValueError("run validation requires configs and authorization")
        configs = {"S50": {}, "S100": {}}
        execution_git_sha = ""
    else:
        configs = {
            "S50": json.loads(s50_config_path.read_text(encoding="utf-8")),
            "S100": json.loads(s100_config_path.read_text(encoding="utf-8")),
        }
        normalized = copy.deepcopy(configs)
        for value in normalized.values():
            value.pop("condition", None)
            value["author_runner"].pop("effective_step_limit", None)
        if normalized["S50"] != normalized["S100"]:
            raise ValueError("S50/S100 policy-independent configuration drift")
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        if authorization.get("schema_version") != "continuum.w1c_pilot_authorization.v1":
            raise ValueError("unsupported W1-C authorization")
        if authorization.get("pilot_instance_ids") != ids:
            raise ValueError("authorization task identities do not match freeze")
        bindings = authorization.get("bindings", {})
        if bindings.get("s50_config_sha256") != _sha256(s50_config_path):
            raise ValueError("S50 authorization binding mismatch")
        if bindings.get("s100_config_sha256") != _sha256(s100_config_path):
            raise ValueError("S100 authorization binding mismatch")
        if bindings.get("sampling_freeze_sha256") != _sha256(freeze_path):
            raise ValueError("sampling freeze authorization binding mismatch")
        execution_git_sha = str(authorization.get("repository_git_sha"))
        if tokenize_messages is None:
            raise ValueError("run validation requires pinned tokenization")
    expected = {(condition, instance_id) for condition in ("S50", "S100") for instance_id in ids}
    observed_dirs = {
        (condition, path.name)
        for condition in ("S50", "S100")
        for path in (runs_root / condition).iterdir()
        if path.is_dir()
    } if all((runs_root / condition).is_dir() for condition in ("S50", "S100")) else set()
    rows = [
        _run_row(
            runs_root / condition / instance_id,
            instance_id,
            condition,
            config=configs[condition],
            config_path=s50_config_path if condition == "S50" else s100_config_path,
            execution_git_sha=execution_git_sha,
            tokenize_messages=tokenize_messages,
        )
        for instance_id in ids for condition in ("S50", "S100")
    ]
    row_by_key = {(row["condition"], row["instance_id"]): row for row in rows}
    pairs: list[dict[str, Any]] = []
    for instance_id in ids:
        s50 = row_by_key[("S50", instance_id)]
        s100 = row_by_key[("S100", instance_id)]
        comparable = s50["status"] == s100["status"] == "VALID"
        lifecycle_comparable = bool(
            s50.get("execution_binding_valid")
            and s100.get("execution_binding_valid")
        )
        pairs.append({
            "instance_id": instance_id,
            "repository": instance_id.split("__", 1)[0],
            "comparable": comparable,
            "lifecycle_comparable": lifecycle_comparable,
            "s50_outcome": s50.get("outcome"),
            "s100_outcome": s100.get("outcome"),
            "model_call_delta_s100_minus_s50": (
                s100["model_call_count"] - s50["model_call_count"]
                if lifecycle_comparable else None
            ),
            "successful_model_call_delta_s100_minus_s50": (
                s100["successful_model_call_count"] - s50["successful_model_call_count"]
                if lifecycle_comparable else None
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
    lifecycle_pairs = [pair for pair in pairs if pair["lifecycle_comparable"]]
    attempted_deltas = [
        pair["model_call_delta_s100_minus_s50"] for pair in lifecycle_pairs
    ]
    successful_deltas = [
        pair["successful_model_call_delta_s100_minus_s50"]
        for pair in lifecycle_pairs
    ]
    if comparable >= 10:
        recommendation = "CONDITIONAL_GO_FOR_BOUNDED_WORKLOAD_DESIGN"
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
        "lifecycle_comparable_pair_count": len(lifecycle_pairs),
        "lifecycle_metrics": {
            "attempted_model_call_delta_mean_s100_minus_s50": (
                statistics.mean(attempted_deltas) if attempted_deltas else None
            ),
            "successful_model_call_delta_mean_s100_minus_s50": (
                statistics.mean(successful_deltas) if successful_deltas else None
            ),
            "rejected_attempts_are_excluded_from_successful_prompt_statistics": True,
        },
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
            "conditional": "at least 10 valid pairs; permits bounded design review only",
            "otherwise": "NO_GO_CURRENT_ACQUISITION_CONFIGURATION",
            "automatic_authorization": "NONE",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--s50-config", type=Path, required=True)
    parser.add_argument("--s100-config", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    configs = json.loads(args.s50_config.read_text(encoding="utf-8"))
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        configs["model"]["tokenizer_name"],
        revision=configs["model"]["tokenizer_revision"],
        local_files_only=True,
    )

    def tokenize_messages(messages):
        rendered = tokenizer.apply_chat_template(
            list(messages), tokenize=False, add_generation_prompt=True
        )
        return rendered, tokenizer.encode(rendered, add_special_tokens=False)

    report = build_report(
        args.freeze.resolve(),
        args.runs_root.resolve(),
        s50_config_path=args.s50_config.resolve(),
        s100_config_path=args.s100_config.resolve(),
        authorization_path=args.authorization.resolve(),
        tokenize_messages=tokenize_messages,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"W1-C feasibility: {report['recommendation']} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
