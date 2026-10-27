"""Materialize the frozen 54-run controlled sparse Native campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .continuum_bounded_timeline import (
    insert_pressure_join_boundary,
    materialize_request_boundaries,
)
from .phase2b_fidelity import token_ids_sha256

PROFILE_SCHEMA = (
    "continuum.prefill_reload.formal_long_context_interpreted_profile.v1"
)
CAMPAIGN_SCHEMA = "continuum.native_costaware_bounded_campaign.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_token_digest(tokens: list[int]) -> str:
    return hashlib.sha256(
        json.dumps(tokens, separators=(",", ":")).encode()
    ).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _arm(arm: str) -> tuple[str, str, str]:
    if arm == "A0":
        return "A0", "A0", "continuum-a0-entry-native-lru"
    if arm == "A1":
        return "A1", "A0", "continuum-a1-entry-native-lru"
    if arm == "A2":
        return "A0", "A2", "continuum-a0-entry-a2-block"
    raise ValueError(f"unsupported Native arm: {arm}")


def _selected_calls(session: dict[str, Any]) -> list[dict[str, Any]]:
    sidecar_path = Path(session["sidecar_path"])
    if _sha(sidecar_path) != session.get("sidecar_sha256"):
        raise ValueError("source sidecar SHA-256 binding mismatch")
    sidecar = _load(sidecar_path)
    calls = {
        row["request_id"]: row
        for row in sidecar.get("model_calls", [])
        if row.get("status") == "SUCCESS"
    }
    selected: list[dict[str, Any]] = []
    for frozen in session["selected_requests"]:
        call = calls.get(frozen["request_id"])
        if call is None:
            raise ValueError("frozen selected request is absent from source sidecar")
        tokens = call.get("submitted_token_ids")
        if not isinstance(tokens, list) or not tokens:
            raise ValueError("selected request lacks explicit token IDs")
        if _source_token_digest(tokens) != frozen.get("token_ids_sha256"):
            raise ValueError("selected request token digest changed")
        if len(tokens) != frozen.get("token_count"):
            raise ValueError("selected request token count changed")
        selected.append(call)
    return selected


def _unique_chained_prefix_blocks(
    prefix_token_ids: list[list[int]], *, block_size: int = 16
) -> int:
    """Count physical prefix blocks while preserving parent-chain identity."""

    trie: dict[tuple[int, ...], dict[Any, Any]] = {}
    count = 0
    for tokens in prefix_token_ids:
        node = trie
        aligned = len(tokens) // block_size * block_size
        for offset in range(0, aligned, block_size):
            block = tuple(tokens[offset : offset + block_size])
            child = node.get(block)
            if child is None:
                child = {}
                node[block] = child
                count += 1
            node = child
    return count


def _pressure_geometry(
    *,
    program_prefix_tokens: dict[str, int],
    unique_protected_blocks: int,
    regime: str,
    minimum_capacity_blocks: int = 2048,
) -> tuple[int, int, int]:
    protected_blocks = unique_protected_blocks
    if regime == "moderate":
        shortage_blocks = 1
        minimum_pressure_blocks = 32
    elif regime == "deep":
        smallest_entry = min(value // 16 for value in program_prefix_tokens.values())
        shortage_blocks = smallest_entry + 1
        minimum_pressure_blocks = 256
    else:
        raise ValueError("unsupported pressure regime")
    pressure_blocks = max(
        minimum_pressure_blocks,
        minimum_capacity_blocks - protected_blocks - 1 + shortage_blocks,
    )
    if pressure_blocks > 2048:
        raise ValueError("pressure geometry exceeds the frozen 32K request limit")
    pressure_tokens = pressure_blocks * 16
    capacity_blocks = protected_blocks + pressure_blocks + 1 - shortage_blocks
    return pressure_tokens, shortage_blocks, capacity_blocks


def materialize_campaign(
    *,
    protocol_path: Path,
    source_freeze_path: Path,
    profile_path: Path,
    resource_record_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    protocol = _load(protocol_path)
    source = _load(source_freeze_path)
    profile = _load(profile_path)
    resource = _load(resource_record_path)
    if protocol.get("schema_version") != (
        "continuum.native_costaware_bounded_protocol.v1"
    ):
        raise ValueError("unsupported bounded protocol")
    if source.get("schema_version") != (
        "continuum.native_costaware_formal_freeze_candidate.v1"
    ):
        raise ValueError("unsupported source workload freeze")
    if profile.get("schema") != PROFILE_SCHEMA or profile.get("status") != "complete":
        raise ValueError("bounded campaign requires the approved interpreted profile")
    provenance = profile.get("provenance", {})
    if provenance.get("raw_measurement_modified") is not False or not provenance.get(
        "raw_profile_sha256"
    ):
        raise ValueError("bounded campaign requires preserved raw Profile binding")
    if resource.get("status") != "PASS":
        raise ValueError("target GPU preflight has not passed")
    if resource.get("model") != protocol["runtime"]["model"] or resource.get(
        "model_revision"
    ) != protocol["runtime"]["model_revision"]:
        raise ValueError("resource record model binding mismatch")
    available_blocks = int(resource["available_kv_blocks"])
    groups = {row["group_id"]: row for row in source["groups"]}
    expected_groups = [row["group_id"] for row in protocol["workload_groups"]]
    if set(groups) != set(expected_groups):
        raise ValueError("bounded protocol and source workload groups differ")

    runs: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    sequence_by_cell: dict[str, str] = {}
    runtime = protocol["runtime"]
    for group_id in expected_groups:
        group = groups[group_id]
        calls_by_session = [_selected_calls(session) for session in group["sessions"]]
        if any(len(calls) != 6 for calls in calls_by_session):
            raise ValueError("each bounded session must freeze six checkpoints")
        base_boundaries = materialize_request_boundaries(
            sessions=calls_by_session,
            cross_session_start_stagger_seconds=float(
                protocol["replay"]["cross_session_start_stagger_seconds"]
            ),
        )
        final_ids = tuple(calls[-1]["request_id"] for calls in calls_by_session)
        requests: list[dict[str, Any]] = []
        replay_tokens: dict[str, list[int]] = {}
        right_censored: list[str] = []
        program_prefix_tokens: dict[str, int] = {}
        program_prefix_token_ids: list[list[int]] = []
        for session, calls in zip(group["sessions"], calls_by_session, strict=True):
            program_id = session["instance_id"]
            penultimate_tokens = calls[-2]["submitted_token_ids"]
            program_prefix_tokens[program_id] = len(penultimate_tokens) // 16 * 16
            program_prefix_token_ids.append(penultimate_tokens)
            naturally_terminal = session["source_outcome"] == "NATURAL_COMPLETION"
            for replay_turn, call in enumerate(calls, start=1):
                request_id = call["request_id"]
                tokens = call["submitted_token_ids"]
                replay_tokens[request_id] = tokens
                is_last = replay_turn == len(calls)
                terminal = is_last and naturally_terminal
                if is_last and not terminal:
                    right_censored.append(request_id)
                requests.append(
                    {
                        "program_id": program_id,
                        "request_id": request_id,
                        "turn_index": replay_turn,
                        "planned_arrival_offset_seconds": 0.0,
                        "prompt": "exact-token controlled sparse replay",
                        "prefix_prompt": "",
                        "is_terminal": terminal,
                        "next_tool_type": None if terminal else "observed-agent-gap",
                        "tool_gap_seconds": None if terminal else 0.0,
                    }
                )
        unique_protected_blocks = _unique_chained_prefix_blocks(
            program_prefix_token_ids
        )
        for regime in protocol["pressure_regimes"]:
            pressure_tokens, shortage_blocks, capacity_blocks = _pressure_geometry(
                program_prefix_tokens=program_prefix_tokens,
                unique_protected_blocks=unique_protected_blocks,
                regime=regime,
            )
            if capacity_blocks > available_blocks:
                raise ValueError(
                    f"{group_id}/{regime} needs {capacity_blocks} KV blocks, "
                    f"but preflight exposed {available_blocks}"
                )
            pressure_boundary_id = f"pressure:{group_id}:{regime}"
            boundaries = insert_pressure_join_boundary(
                boundaries=base_boundaries,
                final_request_ids=final_ids,
                boundary_id=pressure_boundary_id,
            )
            boundary_payload = [
                {
                    "boundary_id": row.boundary_id,
                    "logical_timestamp": row.logical_timestamp,
                    "source": row.source,
                    "kind": row.kind.value,
                    "request_id": row.request_id,
                }
                for row in boundaries
            ]
            clock_payload = [
                {
                    "boundary_id": row.boundary_id,
                    "logical_timestamp": row.logical_timestamp,
                    "source": row.source,
                }
                for row in boundaries
            ]
            sequence_sha = hashlib.sha256(
                json.dumps(
                    clock_payload, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            cell_id = f"{group_id}-{regime}"
            sequence_by_cell[cell_id] = sequence_sha
            trace_path = output_dir / f"{cell_id}.trace.json"
            trace = {
                "schema_version": "phase2.trace.v1",
                "trace_id": f"continuum-bounded-{cell_id}",
                "allow_incomplete_programs": True,
                "requests": requests,
                "pressure_stages": [],
            }
            _write(trace_path, trace)
            traces.append(
                {
                    "cell_id": cell_id,
                    "path": trace_path.name,
                    "sha256": _sha(trace_path),
                    "logical_sequence_sha256": sequence_sha,
                }
            )
            for arm in protocol["native_policy_arms"]:
                release_policy, block_policy, policy_name = _arm(arm)
                run_id = f"{cell_id}-{arm.lower()}-repeat-1"
                config_path = output_dir / f"{run_id}.config.json"
                config = {
                    "schema_version": "phase2.config.v1",
                    "campaign_kind": "continuum_native_costaware_bounded_evaluation",
                    "runtime_mode": "vllm-cuda-observability",
                    "backend_factory": "scripts.spikes.phase2_minimal_observability_cuda:build_phase2_cuda_observability_backend",
                    "backend_revision": "continuum-bounded-cuda-v1",
                    "model": {
                        "name": runtime["model"],
                        "revision": runtime["model_revision"],
                    },
                    "tokenizer": {
                        "name": runtime["tokenizer"],
                        "revision": runtime["tokenizer_revision"],
                    },
                    "generation": {"max_new_tokens": 1, "temperature": 0.0},
                    "cache": {"block_size": 16, "block_override": capacity_blocks},
                    "batching": {"max_concurrent_requests": 2},
                    "pressure": {
                        "required_blocks": pressure_tokens // 16,
                        "initial_shortage_blocks": shortage_blocks,
                        "safety_ceiling": 1,
                    },
                    "seed": 20261121,
                    "observe": True,
                    "policy": policy_name,
                    "trace": trace_path.name,
                    "controlled_sparse_replay": {
                        "maximum_concurrent_requests": 2,
                        "native_timeout_seconds": 1800.0,
                        "boundaries": boundary_payload,
                        "logical_sequence_sha256": sequence_sha,
                    },
                    "backend_options": {
                        "execute_planned_timing": False,
                        "executor_mode": "submit_collect",
                        "gpu_memory_utilization": float(resource["gpu_memory_utilization"]),
                        "max_model_len": 32768,
                        "max_num_batched_tokens": 2048,
                        "enable_chunked_prefill": True,
                        "enforce_eager": True,
                        "capture_terminal_prefix_snapshot": True,
                        "continuum_w1b_replay_mode": True,
                        "replay_token_ids_by_request": replay_tokens,
                        "expected_native_submission_sha256_by_request": {
                            key: token_ids_sha256(value)
                            for key, value in replay_tokens.items()
                        },
                        "w1b_right_censored_end_request_ids": right_censored,
                        "program_prefix_tokens": program_prefix_tokens,
                        "pressure_prompt_tokens": pressure_tokens,
                        "phase2g_unique_protected_blocks": unique_protected_blocks,
                        "phase2g_release_policy": release_policy,
                        "phase2g_block_policy": block_policy,
                        "phase2g_a1_lambda": 0.5,
                        "phase2g_a1_tau_seconds": 30.0,
                        "phase2g_a2_tau_seconds": 30.0,
                        "prefill_profile_path": str(profile_path.resolve()),
                        "controlled_sparse_replay_boundaries": clock_payload,
                        "controlled_pressure_stages_by_boundary": {
                            pressure_boundary_id: {
                                "stage_id": f"{cell_id}-pressure",
                                "prompt": f"bounded controlled pressure {cell_id}",
                                "max_requests": 1,
                                "stop_on_forced_release": False,
                            }
                        },
                    },
                }
                _write(config_path, config)
                runs.append(
                    {
                        "run_id": run_id,
                        "group_id": group_id,
                        "pressure_regime": regime,
                        "arm": arm,
                        "repeat": 1,
                        "config": config_path.name,
                        "config_sha256": _sha(config_path),
                        "trace": trace_path.name,
                        "trace_sha256": _sha(trace_path),
                        "logical_sequence_sha256": sequence_sha,
                    }
                )
    if len(runs) != 54:
        raise RuntimeError("bounded campaign did not materialize 54 runs")
    manifest = {
        "schema_version": CAMPAIGN_SCHEMA,
        "protocol_path": str(protocol_path.resolve()),
        "protocol_sha256": _sha(protocol_path),
        "source_freeze_path": str(source_freeze_path.resolve()),
        "source_freeze_sha256": _sha(source_freeze_path),
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": _sha(profile_path),
        "raw_profile_sha256": provenance["raw_profile_sha256"],
        "profile_interpretation_contract_sha256": provenance[
            "interpretation_contract_sha256"
        ],
        "resource_record_path": str(resource_record_path.resolve()),
        "resource_record_sha256": _sha(resource_record_path),
        "planned_run_count": len(runs),
        "group_count": 9,
        "traces": traces,
        "runs": runs,
        "logical_sequence_sha256_by_cell": sequence_by_cell,
        "measured_outcomes_materialized": False,
        "execution_authorized": False,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--source-freeze", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--resource-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = materialize_campaign(
        protocol_path=args.protocol,
        source_freeze_path=args.source_freeze,
        profile_path=args.profile,
        resource_record_path=args.resource_record,
        output_dir=args.output,
    )
    print(f"materialized bounded campaign: {manifest['planned_run_count']} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
