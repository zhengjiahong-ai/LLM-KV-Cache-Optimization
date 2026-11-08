"""Materialize one authorized Phase 3 A0 Native fidelity preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

MODEL_REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
BLOCK_SIZE = 16
BLOCK_OVERRIDE = 2048


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def materialize_native_preflight(
    *,
    repository: Path,
    seal_path: Path,
    profile_path: Path,
    group_id: str,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not profile_path.is_file():
        raise FileNotFoundError(profile_path)
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("schema_version") != "phase3.cohort_seal.v1":
        raise ValueError("unsupported Phase 3 Cohort Seal")
    groups = [row for row in seal.get("groups", []) if row.get("group_id") == group_id]
    if len(groups) != 1:
        raise ValueError("preflight group must resolve uniquely")
    group = groups[0]
    if len(group.get("sessions", [])) != 2:
        raise ValueError("Phase 3 preflight requires two sessions")
    if group.get("frozen_request_order") != group.get("native_enqueue_order"):
        raise ValueError("frozen and Native enqueue orders differ")
    if len(group["frozen_request_order"]) != 24:
        raise ValueError("Phase 3 preflight requires 24 requests")

    output_dir.mkdir(parents=True)
    frozen_profile = output_dir / "prefill-profile.json"
    shutil.copyfile(profile_path, frozen_profile)
    replay_tokens: dict[str, list[int]] = {}
    expected_token_sha: dict[str, str] = {}
    requests: list[dict[str, object]] = []
    program_prefix_tokens: dict[str, int] = {}
    right_censored: list[str] = []
    selected_ids: set[str] = set()
    for session in group["sessions"]:
        instance_id = str(session["instance_id"])
        sidecar_path = repository / str(session["sidecar_path"])
        if _sha256(sidecar_path) != session["sidecar_sha256"]:
            raise ValueError("Cohort sidecar SHA-256 drift")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        calls = {str(row["request_id"]): row for row in sidecar["model_calls"]}
        selected = session["selected_requests"]
        for turn_index, frozen in enumerate(selected, start=1):
            request_id = str(frozen["request_id"])
            call = calls.get(request_id)
            if call is None:
                raise ValueError("frozen request is absent from its Sidecar")
            tokens = call.get("submitted_token_ids")
            if not isinstance(tokens, list) or not tokens or any(type(v) is not int for v in tokens):
                raise ValueError("frozen request lacks exact Token IDs")
            digest = _canonical_sha(tokens)
            if len(tokens) != frozen["token_count"] or digest != frozen["token_ids_sha256"]:
                raise ValueError("frozen request Token binding drift")
            next_gap = 0.0
            if turn_index < len(selected):
                next_call = calls[str(selected[turn_index]["request_id"])]
                next_gap = max(
                    0.0,
                    float(next_call["model_submit_monotonic_seconds"])
                    - float(call["model_completion_monotonic_seconds"]),
                )
            requests.append(
                {
                    "program_id": instance_id,
                    "request_id": request_id,
                    "turn_index": turn_index,
                    "planned_arrival_offset_seconds": 0.0,
                    "prompt": str(call["rendered_prompt"]),
                    "prefix_prompt": "",
                    "is_terminal": False,
                    "next_tool_type": "observed-agent-gap",
                    "tool_gap_seconds": next_gap,
                    "kind": "turn",
                }
            )
            replay_tokens[request_id] = list(tokens)
            expected_token_sha[request_id] = digest
            selected_ids.add(request_id)
        last_id = str(selected[-1]["request_id"])
        right_censored.append(last_id)
        program_prefix_tokens[instance_id] = (
            len(replay_tokens[last_id]) // BLOCK_SIZE * BLOCK_SIZE
        )
    if selected_ids != set(group["frozen_request_order"]):
        raise ValueError("materialized request identities differ from the Cohort Seal")

    trace_path = output_dir / f"{group_id}.trace.json"
    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": f"phase3-native-preflight-{group_id}",
        "allow_incomplete_programs": True,
        "requests": requests,
        "pressure_stages": [],
    }
    _write(trace_path, trace)
    boundaries = list(group["replay_timeline"])
    clock_boundaries = [
        {
            "boundary_id": row["boundary_id"],
            "logical_timestamp": row["logical_timestamp"],
            "source": row["source"],
        }
        for row in boundaries
    ]
    run_id = f"phase3-native-preflight-{group_id}-a0"
    config = {
        "schema_version": "phase2.config.v1",
        "campaign_kind": "phase3_final_evaluation",
        "execution_authorized": True,
        "run_id": run_id,
        "runtime_mode": "vllm-cuda-observability",
        "backend_factory": (
            "scripts.spikes.phase2_minimal_observability_cuda:"
            "build_phase2_cuda_observability_backend"
        ),
        "backend_revision": "phase3-native-preflight-v1",
        "model": {"name": "Qwen/Qwen2.5-Coder-1.5B-Instruct", "revision": MODEL_REVISION},
        "tokenizer": {"name": "Qwen/Qwen2.5-Coder-1.5B-Instruct", "revision": MODEL_REVISION},
        "generation": {"max_new_tokens": 1, "temperature": 0.0},
        "cache": {"block_size": BLOCK_SIZE, "block_override": BLOCK_OVERRIDE},
        "batching": {"max_concurrent_requests": 2},
        "pressure": {"required_blocks": 1, "initial_shortage_blocks": 1, "safety_ceiling": 1},
        "seed": 20261103,
        "observe": True,
        "policy": "project-continuum-entry-native-lru",
        "trace": trace_path.name,
        "controlled_sparse_replay": {
            "maximum_concurrent_requests": 2,
            "native_timeout_seconds": 1800.0,
            "boundaries": boundaries,
            "logical_sequence_sha256": _canonical_sha(clock_boundaries),
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
            "expected_native_submission_sha256_by_request": expected_token_sha,
            "w1b_right_censored_end_request_ids": right_censored,
            "program_prefix_tokens": program_prefix_tokens,
            "pressure_prompt_tokens": BLOCK_SIZE,
            "pressure_stage_prompt_tokens": {},
            "pressure_token_ids_by_stage": {},
            "phase2g_release_policy": "A0",
            "phase2g_block_policy": "A0",
            "phase2g_a1_lambda": 0.5,
            "phase2g_a1_tau_seconds": 30.0,
            "phase2g_a2_tau_seconds": 30.0,
            "phase3_arm": "A0",
            "prefill_profile_path": str(frozen_profile.resolve()),
            "controlled_sparse_replay_boundaries": clock_boundaries,
            "controlled_pressure_stages_by_boundary": {},
        },
    }
    config_path = output_dir / f"{run_id}.config.json"
    _write(config_path, config)
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    freeze = {
        "schema_version": "phase3.native_preflight_freeze.v1",
        "execution_authorized": True,
        "scope": "ONE_GROUP_A0_NATIVE_FIDELITY_NOT_CALIBRATION_OR_OUTCOME",
        "git_sha": git_sha,
        "cohort_seal_sha256": _sha256(seal_path),
        "group_id": group_id,
        "arm": "A0",
        "request_count": len(requests),
        "config": config_path.name,
        "config_sha256": _sha256(config_path),
        "trace": trace_path.name,
        "trace_sha256": _sha256(trace_path),
        "profile": frozen_profile.name,
        "profile_sha256": _sha256(frozen_profile),
    }
    _write(output_dir / "freeze-record.json", freeze)
    return freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--group-id", default="g14")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    freeze = materialize_native_preflight(
        repository=Path.cwd().resolve(),
        seal_path=args.seal.resolve(),
        profile_path=args.profile.resolve(),
        group_id=args.group_id,
        output_dir=args.output_dir.resolve(),
    )
    print(json.dumps(freeze, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
