"""Materialize and validate the bounded W1-B A0/A1/A2 Native smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROFILE_SCHEMA = "continuum.prefill_reload.w1b_long_context_profile.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _arm_options(arm: str) -> tuple[str, str, str]:
    if arm == "A0":
        return "A0", "A0", "continuum-a0-entry-native-lru"
    if arm == "A1":
        return "A1", "A0", "continuum-a1-entry-native-lru"
    if arm == "A2":
        return "A0", "A2", "continuum-a0-entry-a2-block"
    raise ValueError(f"unsupported W1-B arm: {arm}")


def materialize_campaign(
    *, freeze_path: Path, profile_path: Path, output_dir: Path
) -> dict[str, Any]:
    freeze = _load(freeze_path)
    profile = _load(profile_path)
    if freeze.get("native_fidelity_status") != "PASS_NATIVE_INPUT_FIDELITY_ONLY":
        raise ValueError("W1-B Native input fidelity gate has not passed")
    if profile.get("schema") != PROFILE_SCHEMA:
        raise ValueError("W1-B campaign requires the frozen long-context profile")
    runtime = freeze["runtime"]
    capacity_blocks = int(runtime["cache_capacity_tokens"]) // 16
    pressure_tokens = int(runtime["pressure_prompt_tokens"])
    pressure_blocks = pressure_tokens // 16
    if capacity_blocks != 1024 or pressure_blocks != 896:
        raise ValueError("unexpected W1-B v2 capacity contract")
    source_manifest_path = Path(freeze["source_replay_manifest"])
    source_manifest = _load(source_manifest_path)
    bindings = {row["session_id"]: row for row in source_manifest["sessions"]}
    runs: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for group in freeze["groups"]:
        group_id = group["group_id"]
        requests: list[dict[str, Any]] = []
        replay_tokens: dict[str, list[int]] = {}
        program_prefix_tokens: dict[str, int] = {}
        for session_position, selected_session in enumerate(group["sessions"]):
            session_id = selected_session["session_id"]
            binding = bindings[session_id]
            session_path = source_manifest_path.parent / binding["path"]
            if _sha(session_path) != binding["sha256"]:
                raise ValueError("source replay session SHA-256 mismatch")
            session = _load(session_path)
            selected_turns = selected_session["selected_turns"]
            selected = [session["requests"][turn - 1] for turn in selected_turns]
            maximum_token_count = max(row["token_count"] for row in selected)
            program_prefix_tokens[session_id] = maximum_token_count // 16 * 16
            for replay_turn, (source_turn, row) in enumerate(
                zip(selected_turns, selected, strict=True), start=1
            ):
                request_id = row["request_id"]
                replay_tokens[request_id] = row["token_ids"]
                naturally_terminal = not session["right_censored"] and source_turn == len(
                    session["requests"]
                )
                requests.append(
                    {
                        "program_id": session_id,
                        "request_id": request_id,
                        "turn_index": replay_turn,
                        "planned_arrival_offset_seconds": (
                            session_position * 0.25 + (replay_turn - 1) * 1.0
                        ),
                        "prompt": "exact-token replay; text is not the identity source",
                        "prefix_prompt": "",
                        "is_terminal": naturally_terminal,
                        "next_tool_type": None if naturally_terminal else "controlled-w1b-gap",
                        "tool_gap_seconds": None if naturally_terminal else 1.0,
                        "source_turn_index": source_turn,
                        "source_token_ids_sha256": row["token_ids_sha256"],
                    }
                )
        trace_path = output_dir / f"{group_id}.trace.json"
        trace = {
            "schema_version": "phase2.trace.v1",
            "trace_id": f"continuum-w1b-{group_id}",
            "allow_incomplete_programs": True,
            "requests": requests,
            "pressure_stages": [
                {
                    "stage_id": f"{group_id}-pressure",
                    "planned_arrival_offset_seconds": runtime["pressure_offset_seconds"],
                    "prompt": f"W1-B controlled pressure for {group_id}",
                    "max_requests": 1,
                    "stop_on_forced_release": False,
                }
            ],
        }
        _write(trace_path, trace)
        trace_sha = _sha(trace_path)
        traces.append({"group_id": group_id, "path": trace_path.name, "sha256": trace_sha})
        for arm in freeze["arms"]:
            release_policy, block_policy, policy_name = _arm_options(arm)
            run_id = f"{group_id}-{arm.lower()}-repeat-1"
            config_path = output_dir / f"{run_id}.config.json"
            config = {
                "schema_version": "phase2.config.v1",
                "campaign_kind": "continuum_w1b_native_smoke",
                "runtime_mode": "vllm-metal-observability",
                "backend_factory": "scripts.spikes.phase2_minimal_observability_metal:build_phase2_metal_observability_backend",
                "backend_revision": "continuum-w1b-native-smoke-v2",
                "model": {"name": runtime["model"], "revision": runtime["model_revision"]},
                "tokenizer": {
                    "name": runtime["tokenizer"],
                    "revision": runtime["tokenizer_revision"],
                },
                "generation": {"max_new_tokens": 1, "temperature": 0.0},
                "cache": {"block_size": 16, "block_override": capacity_blocks},
                "batching": {"max_concurrent_requests": 2},
                "pressure": {
                    "required_blocks": pressure_blocks,
                    "initial_shortage_blocks": 1,
                    "safety_ceiling": 1,
                },
                "seed": runtime["seed"],
                "observe": True,
                "policy": policy_name,
                "trace": trace_path.name,
                "backend_options": {
                    "execute_planned_timing": True,
                    "executor_mode": "submit_collect",
                    "gpu_memory_utilization": 0.75,
                    "phase2c_native_pilot_mode": True,
                    "phase2c_prefix_generator_version": "phase2c-segmented-prefix-v1",
                    "capture_terminal_prefix_snapshot": True,
                    "continuum_w1b_replay_mode": True,
                    "replay_token_ids_by_request": replay_tokens,
                    "program_prefix_tokens": program_prefix_tokens,
                    "pressure_prompt_tokens": pressure_tokens,
                    "phase2g_unique_protected_blocks": capacity_blocks - pressure_blocks,
                    "phase2g_release_policy": release_policy,
                    "phase2g_block_policy": block_policy,
                    "phase2g_a1_lambda": 0.5,
                    "phase2g_a1_tau_seconds": 30.0,
                    "phase2g_a2_tau_seconds": 30.0,
                    "prefill_profile_path": str(profile_path),
                },
                "continuum_w1b_stage": {
                    "stage": "NATIVE_COMPARABILITY_SMOKE",
                    "group_id": group_id,
                    "arm": arm,
                    "repeat": 1,
                    "source_freeze_sha256": _sha(freeze_path),
                    "trace_sha256": trace_sha,
                    "profile_sha256": _sha(profile_path),
                    "schedule_claim": "CONTROLLED_CAUSAL_REPLAY_NOT_OBSERVED_ARRIVALS",
                },
            }
            _write(config_path, config)
            runs.append(
                {
                    "run_id": run_id,
                    "group_id": group_id,
                    "arm": arm,
                    "repeat": 1,
                    "config": config_path.name,
                    "config_sha256": _sha(config_path),
                    "trace_sha256": trace_sha,
                }
            )
    manifest = {
        "schema_version": "continuum.w1b_native_smoke_campaign.v1",
        "scope": "BOUNDED_NATIVE_COMPARABILITY_SMOKE",
        "freeze_path": str(freeze_path),
        "freeze_sha256": _sha(freeze_path),
        "profile_path": str(profile_path),
        "profile_sha256": _sha(profile_path),
        "group_count": len(freeze["groups"]),
        "planned_run_count": len(runs),
        "traces": traces,
        "runs": runs,
        "native_fidelity_gate": freeze["native_fidelity_status"],
        "formal_performance_campaign": False,
        "measured_outcomes_materialized": False,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def validate_campaign(*, manifest_path: Path) -> dict[str, Any]:
    manifest = _load(manifest_path)
    root = manifest_path.parent
    problems: list[str] = []
    runs = manifest.get("runs", [])
    if manifest.get("planned_run_count") != 12 or len(runs) != 12:
        problems.append("campaign must contain exactly 12 planned runs")
    keys: set[tuple[str, str, int]] = set()
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        key = (run["group_id"], run["arm"], run["repeat"])
        if key in keys:
            problems.append(f"duplicate run key: {key}")
        keys.add(key)
        config_path = root / run["config"]
        if not config_path.is_file() or _sha(config_path) != run["config_sha256"]:
            problems.append(f"config binding mismatch: {run['run_id']}")
            continue
        config = _load(config_path)
        trace_path = root / config["trace"]
        if not trace_path.is_file() or _sha(trace_path) != run["trace_sha256"]:
            problems.append(f"trace binding mismatch: {run['run_id']}")
        groups.setdefault(run["group_id"], []).append(config)
    for group_id, configs in groups.items():
        if {row["continuum_w1b_stage"]["arm"] for row in configs} != {"A0", "A1", "A2"}:
            problems.append(f"missing arm in {group_id}")
            continue
        tokens = [row["backend_options"]["replay_token_ids_by_request"] for row in configs]
        if any(value != tokens[0] for value in tokens[1:]):
            problems.append(f"cross-arm token identity mismatch: {group_id}")
        fixed = [
            (
                row["trace"],
                row["cache"],
                row["pressure"],
                row["seed"],
                row["model"],
                row["tokenizer"],
            )
            for row in configs
        ]
        if any(value != fixed[0] for value in fixed[1:]):
            problems.append(f"cross-arm runtime contract mismatch: {group_id}")
    report = {
        "schema_version": "continuum.w1b_native_smoke_validation.v1",
        "status": "PASS" if not problems else "FAIL",
        "manifest_sha256": _sha(manifest_path),
        "checked_run_count": len(runs),
        "checked_group_count": len(groups),
        "problems": problems,
        "comparison_execution_ready": not problems,
    }
    _write(root / "validation-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--freeze", type=Path, required=True)
    materialize.add_argument("--profile", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        result = materialize_campaign(
            freeze_path=args.freeze, profile_path=args.profile, output_dir=args.output
        )
        print(f"materialized W1-B smoke: {result['planned_run_count']} runs -> {args.output}")
    else:
        result = validate_campaign(manifest_path=args.manifest)
        print(f"W1-B campaign validation: {result['status']}")
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
