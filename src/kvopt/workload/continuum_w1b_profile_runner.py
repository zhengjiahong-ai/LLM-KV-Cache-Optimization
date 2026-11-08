"""Measure one frozen W1-B 3B long-context PrefillReload point."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .continuum_w1b_profile import W1B_TOKEN_GRID

FORMAL_PROFILE_SCHEMA = "continuum.native_costaware_prefill_profile_protocol.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _DiscardingSink:
    def emit(self, _event: object) -> None:
        return None


class _NativeHashSurface:
    def __init__(self, capture: object) -> None:
        self._capture = capture

    def lookup_hash(self, native_hash: bytes) -> bool:
        pool = getattr(self._capture, "pool", None)
        if pool is None:
            return False
        return pool.cached_block_hash_to_block.get_one_block(native_hash) is not None


def measurement_config(
    *, base_config: dict[str, Any], protocol: dict[str, Any], token_count: int
) -> dict[str, Any]:
    schema = protocol.get("schema_version")
    token_grid = protocol.get("token_grid", list(W1B_TOKEN_GRID))
    if not isinstance(token_grid, list) or token_count not in token_grid:
        raise ValueError("token count is outside the frozen profile grid")
    config = json.loads(json.dumps(base_config))
    measurement = protocol["measurement"]
    model = protocol["model"]
    pressure_tokens = int(measurement["pressure_prompt_tokens"])
    block_size = int(measurement["block_size_tokens"])
    target_and_pressure_blocks = (
        token_count // block_size + pressure_tokens // block_size
    )
    runtime = protocol.get("execution_backend", {})
    if not isinstance(runtime, dict):
        raise TypeError("execution_backend must be an object")
    max_model_len = int(
        runtime.get("max_model_len", max(token_count, pressure_tokens) + 1)
    )
    block_override = (
        max(target_and_pressure_blocks, (max_model_len + block_size - 1) // block_size)
        if schema == FORMAL_PROFILE_SCHEMA
        else target_and_pressure_blocks
    )
    config.update(
        campaign_kind=(
            "continuum_native_costaware_prefill_profile"
            if schema == FORMAL_PROFILE_SCHEMA
            else "continuum_w1b_prefill_profile"
        ),
        policy="continuum-a0",
        seed=int(measurement["seed"]),
        model={"name": model["name"], "revision": model["revision"]},
        tokenizer={
            "name": model.get("tokenizer_name", model["name"]),
            "revision": model["tokenizer_revision"],
        },
        generation={
            "max_new_tokens": int(measurement["max_new_tokens"]),
            "temperature": float(measurement["temperature"]),
        },
        batching={"max_concurrent_requests": 1},
        cache={
            "block_size": block_size,
            "block_override": block_override,
        },
        pressure={
            "initial_shortage_blocks": 1,
            "required_blocks": pressure_tokens // block_size,
            "safety_ceiling": int(measurement["maximum_pressure_batches"]),
        },
        backend_options={
            "execute_planned_timing": False,
            "executor_mode": "submit_collect",
            "gpu_memory_utilization": float(measurement["gpu_memory_utilization"]),
            "max_model_len": max_model_len,
            "max_num_batched_tokens": int(
                measurement.get(
                    "max_num_batched_tokens",
                    max(token_count, pressure_tokens) + 1,
                )
            ),
            "enable_chunked_prefill": bool(
                measurement.get("enable_chunked_prefill", False)
            ),
            "enforce_eager": bool(measurement.get("enforce_eager", False)),
            "phase2g_release_policy": "A0",
            "phase2g_block_policy": "A0",
            "program_prefix_tokens": {
                (
                    "formal-profile"
                    if schema == FORMAL_PROFILE_SCHEMA
                    else "w1b-profile"
                ): token_count
            },
            "pressure_prompt_tokens": pressure_tokens,
            "prefill_profile_path": (
                "docs/experiments/phase1b-continuum/artifacts/"
                "prefill-reload-profile-formal-20260920T045859Z-6183d106.json"
            ),
        },
    )
    return config


def measure_point(
    *, base_config_path: Path, protocol_path: Path, token_count: int
) -> dict[str, Any]:
    protocol = _load(protocol_path)
    schema = protocol.get("schema_version")
    if schema not in {
        "continuum.w1b_prefill_profile_protocol.v1",
        FORMAL_PROFILE_SCHEMA,
    }:
        raise ValueError("unsupported PrefillReload profile protocol")
    if schema == "continuum.w1b_prefill_profile_protocol.v1" and protocol.get(
        "token_grid"
    ) != list(W1B_TOKEN_GRID):
        raise ValueError("W1-B profile token grid changed")
    base_config = _load(base_config_path)
    config = measurement_config(
        base_config=base_config,
        protocol=protocol,
        token_count=token_count,
    )
    if config.get("runtime_mode") == "vllm-cuda-observability":
        from scripts.spikes.phase2_minimal_observability_cuda import (
            MinimalCudaObservabilityBackend as NativeObservabilityBackend,
        )
    elif config.get("runtime_mode") == "vllm-metal-observability":
        from scripts.spikes.phase2_minimal_observability_metal import (
            MinimalMetalObservabilityBackend as NativeObservabilityBackend,
        )
    else:
        raise ValueError("profile requires an explicitly qualified native runtime mode")
    from scripts.spikes.run_continuum_phase1b_validation_metal import (
        _coherent_child_request_snapshot,
    )
    from scripts.spikes.run_continuum_prefill_profile import run_prefill_pair
    from scripts.spikes.run_continuum_prefill_profile_metal import build_adapter

    backend = NativeObservabilityBackend(config, _DiscardingSink())
    try:
        def registered(external_id: str, internal_id: str) -> None:
            backend._registry.register_batch(("formal-profile",), (internal_id,))
            backend._registry.register_external_batch((internal_id,), (external_id,))

        def observation(internal_id: str) -> object:
            _prefix, observed_tokens, _block_ids, cache_keys = (
                _coherent_child_request_snapshot(
                    backend._native_observations,
                    internal_id,
                    maximum_token_count=max(token_count, 512),
                )
            )
            if observed_tokens not in {token_count, 512}:
                raise ValueError("W1-B profile observed unexpected material")
            return SimpleNamespace(native_hashes=tuple(cache_keys))

        adapter = build_adapter(
            engine=backend._llm.llm_engine,
            native=_NativeHashSurface(backend._native_pool_capture),
            vocabulary_size=backend._vocabulary_size,
            observation_reader=observation,
            token_grid=(token_count,),
            request_registered=registered,
            require_zero_cached_prefix=(schema == FORMAL_PROFILE_SCHEMA),
        )
        adapter.ensure_seeded(token_count)
        token_ids = adapter.target_token_ids(token_count)
        prefix, suffix = token_ids[:-1], token_ids[-1]
        measurement = protocol["measurement"]
        warmups: list[dict[str, Any]] = []
        measured: list[dict[str, Any]] = []
        for phase, count, target in (
            ("warmup", int(measurement["warmup_pairs_per_point"]), warmups),
            ("measured", int(measurement["measured_pairs_per_point"]), measured),
        ):
            for pair_index in range(count):
                diagnostics: list[dict[str, Any]] = []
                miss, hit = run_prefill_pair(
                    r=token_count,
                    prefix_token_ids=prefix,
                    suffix_token_id=suffix,
                    native=adapter,
                    timer=time.perf_counter,
                    diagnostics_sink=(
                        lambda row, rows=diagnostics: rows.append(dict(row))
                    ),
                    max_pressure_batches=int(measurement["maximum_pressure_batches"]),
                    allowed_token_counts=(token_count,),
                )
                target.append(
                    {
                        **diagnostics[0],
                        "phase": phase,
                        "pair_index": pair_index,
                        "token_count": token_count,
                        "raw_delta_seconds": miss - hit,
                    }
                )
        deltas = [float(row["raw_delta_seconds"]) for row in measured]
        return {
            "schema_version": (
                "continuum.native_costaware_prefill_profile_point.v1"
                if schema == FORMAL_PROFILE_SCHEMA
                else "continuum.w1b_prefill_profile_point.v1"
            ),
            "status": "complete",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "git_sha": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "protocol_path": str(protocol_path.resolve()),
            "protocol_sha256": _sha256(protocol_path),
            "base_config_path": str(base_config_path.resolve()),
            "base_config_sha256": _sha256(base_config_path),
            "runtime_config": config,
            "point": {
                "token_count": token_count,
                "warmup_pairs": warmups,
                "measured_pairs": measured,
                "measured_raw_deltas_seconds": deltas,
                "median_raw_delta_seconds": float(statistics.median(deltas)),
            },
        }
    finally:
        backend.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--token-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"W1-B profile point already exists: {args.output}")
    result = measure_point(
        base_config_path=args.base_config,
        protocol_path=args.protocol,
        token_count=args.token_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote W1-B PrefillReload point {args.token_count}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
