"""Materialize the frozen six-run Phase 2H Native smoke inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .phase2h_history_rich_preflight import (
    ARMS,
    BLOCK_SIZE,
    CAPACITY_BLOCKS,
    PRESSURE_ROUNDS,
    SCENARIOS,
    _canonical_sha,
    _load_calls,
    _pressure_token_ids,
)
from .phase2h_history_rich_proposal import materialize_history_rich_mock_timeline

MODEL_REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _arm(arm: str) -> tuple[str, str, str]:
    if arm == "A0":
        return "A0", "A0", "continuum-a0-entry-native-lru"
    if arm == "A1":
        return "A1", "A0", "continuum-a1-entry-native-lru"
    if arm == "A2":
        return "A0", "A2", "continuum-a0-entry-a2-block"
    raise ValueError(arm)


def materialize(
    *, source_root: Path, profile_path: Path, output_dir: Path
) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not profile_path.is_file():
        raise FileNotFoundError(profile_path)
    output_dir.mkdir(parents=True)
    runs: list[dict[str, object]] = []
    for scenario_id, spec in SCENARIOS.items():
        tasks = tuple(spec["tasks"])
        sessions = tuple(_load_calls(source_root, task) for task in tasks)
        timeline = materialize_history_rich_mock_timeline(sessions=sessions)
        boundaries = [
            {
                "boundary_id": row.boundary_id,
                "logical_timestamp": row.logical_timestamp,
                "source": row.source,
                "kind": row.kind.value,
                "request_id": row.request_id,
            }
            for row in timeline.boundaries
        ]
        clock_boundaries = [
            {
                "boundary_id": row["boundary_id"],
                "logical_timestamp": row["logical_timestamp"],
                "source": row["source"],
            }
            for row in boundaries
        ]
        timeline_sha = _canonical_sha(clock_boundaries)
        requests = []
        replay_tokens: dict[str, list[int]] = {}
        right_censored: list[str] = []
        prefix_tokens: dict[str, int] = {}
        for task, calls in zip(tasks, sessions, strict=True):
            prefix_tokens[task] = len(calls[-1]["submitted_token_ids"]) // BLOCK_SIZE * BLOCK_SIZE
            for index, call in enumerate(calls):
                request_id = str(call["request_id"])
                next_gap = None
                if index + 1 < len(calls):
                    next_gap = max(
                        0.0,
                        float(calls[index + 1]["model_submit_monotonic_seconds"])
                        - float(call["model_completion_monotonic_seconds"]),
                    )
                requests.append(
                    {
                        "program_id": task,
                        "request_id": request_id,
                        "turn_index": int(call["turn_index"]),
                        "planned_arrival_offset_seconds": 0.0,
                        "prompt": str(call["rendered_prompt"]),
                        "prefix_prompt": "",
                        "is_terminal": False,
                        "next_tool_type": "observed-agent-gap",
                        # The Phase 2 trace schema requires a numeric duration.
                        # This value is never consumed for the final right-censored
                        # request because no later request closes its server gap.
                        "tool_gap_seconds": 0.0 if next_gap is None else next_gap,
                        "kind": "turn",
                    }
                )
                replay_tokens[request_id] = list(call["submitted_token_ids"])
            right_censored.append(str(calls[-1]["request_id"]))
        trace_path = output_dir / f"{scenario_id}.trace.json"
        _write(
            trace_path,
            {
                "schema_version": "phase2.trace.v1",
                "trace_id": f"phase2h-{scenario_id}",
                "allow_incomplete_programs": True,
                "requests": requests,
                "pressure_stages": [],
            },
        )
        pressure_sizes: dict[str, int] = {}
        pressure_ids: dict[str, list[int]] = {}
        pressure_stages = {}
        for round_index in PRESSURE_ROUNDS:
            boundary_id = f"pressure:after-round-{round_index}"
            stage_id = f"{scenario_id}-after-round-{round_index}"
            seed = f"phase2h:{scenario_id}:after-round-{round_index}:pressure-v1"
            ids = _pressure_token_ids(seed, int(spec["pressure_tokens"]))
            pressure_sizes[stage_id] = len(ids)
            pressure_ids[stage_id] = list(ids)
            pressure_stages[boundary_id] = {
                "stage_id": stage_id,
                "prompt": seed,
                "max_requests": 1,
                "stop_on_forced_release": False,
            }
        pressure_sha = _canonical_sha(pressure_ids)
        for arm in ARMS:
            release_policy, block_policy, policy_name = _arm(arm)
            run_id = f"{scenario_id}-{arm.lower()}-repeat-1"
            config_path = output_dir / f"{run_id}.config.json"
            config = {
                "schema_version": "phase2.config.v1",
                "campaign_kind": "phase2h_history_rich_native_smoke",
                "runtime_mode": "vllm-cuda-observability",
                "backend_factory": (
                    "scripts.spikes.phase2_minimal_observability_cuda:"
                    "build_phase2_cuda_observability_backend"
                ),
                "backend_revision": "phase2h-history-rich-cuda-v1",
                "model": {"name": "Qwen/Qwen2.5-Coder-1.5B-Instruct", "revision": MODEL_REVISION},
                "tokenizer": {
                    "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
                    "revision": MODEL_REVISION,
                },
                "generation": {"max_new_tokens": 1, "temperature": 0.0},
                "cache": {"block_size": BLOCK_SIZE, "block_override": CAPACITY_BLOCKS},
                "batching": {"max_concurrent_requests": 2},
                "pressure": {
                    "required_blocks": int(spec["pressure_tokens"]) // BLOCK_SIZE,
                    "initial_shortage_blocks": int(spec["target_shortage_blocks"]),
                    "safety_ceiling": 1,
                },
                "seed": 20261121,
                "observe": True,
                "policy": policy_name,
                "trace": trace_path.name,
                "controlled_sparse_replay": {
                    "maximum_concurrent_requests": 2,
                    "native_timeout_seconds": 1800.0,
                    "boundaries": boundaries,
                    "logical_sequence_sha256": timeline_sha,
                },
                "backend_options": {
                    "execute_planned_timing": False,
                    "executor_mode": "submit_collect",
                    "gpu_memory_utilization": 0.8,
                    "max_model_len": 32768,
                    "max_num_batched_tokens": 2048,
                    "enable_chunked_prefill": True,
                    "enforce_eager": True,
                    "capture_terminal_prefix_snapshot": True,
                    "continuum_w1b_replay_mode": True,
                    "replay_token_ids_by_request": replay_tokens,
                    "expected_native_submission_sha256_by_request": {
                        key: hashlib.sha256(
                            json.dumps(value, separators=(",", ":")).encode()
                        ).hexdigest()
                        for key, value in replay_tokens.items()
                    },
                    "w1b_right_censored_end_request_ids": right_censored,
                    "program_prefix_tokens": prefix_tokens,
                    "pressure_prompt_tokens": int(spec["pressure_tokens"]),
                    "pressure_stage_prompt_tokens": pressure_sizes,
                    "pressure_token_ids_by_stage": pressure_ids,
                    "phase2g_release_policy": release_policy,
                    "phase2g_block_policy": block_policy,
                    "phase2g_a1_lambda": 0.5,
                    "phase2g_a1_tau_seconds": 30.0,
                    "phase2g_a2_tau_seconds": 30.0,
                    "prefill_profile_path": str(profile_path.resolve()),
                    "controlled_sparse_replay_boundaries": clock_boundaries,
                    "controlled_pressure_stages_by_boundary": pressure_stages,
                },
            }
            _write(config_path, config)
            runs.append(
                {
                    "run_id": run_id,
                    "scenario_id": scenario_id,
                    "arm": arm,
                    "config": config_path.name,
                    "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    "trace": trace_path.name,
                    "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                    "timeline_sha256": timeline_sha,
                    "pressure_input_sha256": pressure_sha,
                }
            )
    manifest = {
        "schema_version": "phase2h.history_rich_native_manifest.v1",
        "execution_authorized": False,
        "planned_run_count": len(runs),
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "runs": runs,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = materialize(
        source_root=args.source_root,
        profile_path=args.profile,
        output_dir=args.output_dir,
    )
    print(f"materialized {result['planned_run_count']} unauthorized Phase 2H run configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
