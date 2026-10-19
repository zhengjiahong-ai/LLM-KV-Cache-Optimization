"""Measure and assemble the authorized 544-token PrefillReload extension."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

EXTENSION_TOKEN_COUNT = 544
WARMUP_PAIRS = 5
MEASURED_PAIRS = 20
MAX_PRESSURE_BATCHES = 64


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


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


def _extension_cache_keys(
    snapshot_reader: Any,
    observations: list[dict[str, object]],
    internal_id: str,
) -> tuple[bytes, ...]:
    _prefix, token_count, _block_ids, cache_keys = snapshot_reader(
        observations,
        internal_id,
    )
    if token_count not in {512, EXTENSION_TOKEN_COUNT}:
        raise ValueError("extension snapshot is neither target nor pressure material")
    return tuple(cache_keys)


def _measurement_config(base_config: dict[str, Any], base_profile: Path) -> dict[str, Any]:
    config = json.loads(json.dumps(base_config))
    config["campaign_kind"] = "phase2g_a2_prefill_profile_extension"
    config["policy"] = "continuum-baseline"
    config["seed"] = 20261019
    config["generation"] = {"max_new_tokens": 1, "temperature": 0.0}
    config["batching"] = {"max_concurrent_requests": 1}
    config["cache"] = {"block_size": 16, "block_override": 66}
    config["pressure"] = {
        "initial_shortage_blocks": 1,
        "required_blocks": 32,
        "safety_ceiling": MAX_PRESSURE_BATCHES,
    }
    config["backend_options"] = {
        "execute_planned_timing": False,
        "executor_mode": "submit_collect",
        "gpu_memory_utilization": 0.75,
        "phase2g_release_policy": "A0",
        "phase2g_block_policy": "A0",
        "program_prefix_tokens": {"profile-extension": EXTENSION_TOKEN_COUNT},
        "pressure_prompt_tokens": 512,
        "prefill_profile_path": str(base_profile.resolve()),
    }
    return config


def measure_extension(*, base_config_path: Path, base_profile: Path) -> dict[str, object]:
    from scripts.spikes.phase2_minimal_observability_metal import (
        MinimalMetalObservabilityBackend,
    )
    from scripts.spikes.run_continuum_phase1b_validation_metal import (
        _coherent_child_request_snapshot,
    )
    from scripts.spikes.run_continuum_prefill_profile import run_prefill_pair
    from scripts.spikes.run_continuum_prefill_profile_metal import build_adapter

    base_config = json.loads(base_config_path.read_text(encoding="utf-8"))
    config = _measurement_config(base_config, base_profile)
    backend = MinimalMetalObservabilityBackend(config, _DiscardingSink())
    try:
        def registered(external_id: str, internal_id: str) -> None:
            backend._registry.register_batch(("profile-extension",), (internal_id,))
            backend._registry.register_external_batch((internal_id,), (external_id,))

        def observation(internal_id: str) -> object:
            cache_keys = _extension_cache_keys(
                _coherent_child_request_snapshot,
                backend._native_observations,
                internal_id,
            )
            return SimpleNamespace(native_hashes=cache_keys)

        adapter = build_adapter(
            engine=backend._llm.llm_engine,
            native=_NativeHashSurface(backend._native_pool_capture),
            vocabulary_size=backend._vocabulary_size,
            observation_reader=observation,
            token_grid=(EXTENSION_TOKEN_COUNT,),
            request_registered=registered,
        )
        adapter.ensure_seeded(EXTENSION_TOKEN_COUNT)
        token_ids = adapter.target_token_ids(EXTENSION_TOKEN_COUNT)
        prefix, suffix = token_ids[:-1], token_ids[-1]
        warmups: list[dict[str, object]] = []
        measured: list[dict[str, object]] = []
        for phase, count, target in (
            ("warmup", WARMUP_PAIRS, warmups),
            ("measured", MEASURED_PAIRS, measured),
        ):
            for pair_index in range(count):
                diagnostics: list[dict[str, object]] = []
                miss, hit = run_prefill_pair(
                    r=EXTENSION_TOKEN_COUNT,
                    prefix_token_ids=prefix,
                    suffix_token_id=suffix,
                    native=adapter,
                    timer=time.perf_counter,
                    diagnostics_sink=(
                        lambda row, rows=diagnostics: rows.append(dict(row))
                    ),
                    max_pressure_batches=MAX_PRESSURE_BATCHES,
                    allowed_token_counts=(EXTENSION_TOKEN_COUNT,),
                )
                row = {
                    **diagnostics[0],
                    "phase": phase,
                    "pair_index": pair_index,
                    "token_count": EXTENSION_TOKEN_COUNT,
                    "raw_delta_seconds": miss - hit,
                }
                target.append(row)
        deltas = [float(row["raw_delta_seconds"]) for row in measured]
        return {
            "schema_version": "phase2g.a2_prefill_profile_extension_measurement.v1",
            "status": "complete",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "git_sha": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "base_config_path": str(base_config_path.resolve()),
            "base_config_sha256": _sha(base_config_path),
            "base_profile_path": str(base_profile.resolve()),
            "base_profile_sha256": _sha(base_profile),
            "protocol": {
                "canonical_unit": "seconds",
                "measured_extension_points": [EXTENSION_TOKEN_COUNT],
                "warmup_pairs_per_point": WARMUP_PAIRS,
                "measured_pairs_per_point": MEASURED_PAIRS,
                "raw_delta_definition": "MISS - HIT",
                "pressure_batch_size": 32,
                "pressure_token_count": 512,
                "maximum_pressure_batches": MAX_PRESSURE_BATCHES,
            },
            "point": {
                "token_count": EXTENSION_TOKEN_COUNT,
                "warmup_pairs": warmups,
                "measured_pairs": measured,
                "measured_raw_deltas_seconds": deltas,
                "median_raw_delta_seconds": float(statistics.median(deltas)),
            },
        }
    finally:
        backend.close()


def assemble_extended_profile(
    *, base_profile: Path, measurement_path: Path
) -> dict[str, object]:
    base = json.loads(base_profile.read_text(encoding="utf-8"))
    measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
    if measurement.get("status") != "complete":
        raise ValueError("extension measurement is incomplete")
    point = measurement.get("point")
    if not isinstance(point, dict) or point.get("token_count") != EXTENSION_TOKEN_COUNT:
        raise ValueError("extension measurement does not contain the 544-token point")
    if measurement.get("base_profile_sha256") != _sha(base_profile):
        raise ValueError("extension measurement base profile binding mismatch")
    return {
        "schema": "continuum.prefill_reload.extended_profile.v1",
        "status": "complete",
        "protocol": {**base["protocol"], "grid": [16, 32, 128, 256, 512, 544]},
        "provenance": {
            "base_profile_sha256": _sha(base_profile),
            "extension_measurement_sha256": _sha(measurement_path),
            "extension_measurement_git_sha": measurement["git_sha"],
        },
        "extension": {
            "base_profile_path": str(base_profile),
            "base_profile_sha256": _sha(base_profile),
            "measured_extension_points": [544],
            "interpolation_rule": "piecewise_linear_between_measured_points",
        },
        "points": [*base["points"], point],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--base-profile", type=Path, required=True)
    parser.add_argument("--measurement-output", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path, required=True)
    args = parser.parse_args(argv)
    measurement = measure_extension(
        base_config_path=args.base_config.resolve(),
        base_profile=args.base_profile.resolve(),
    )
    _write(args.measurement_output, measurement)
    _write(
        args.profile_output,
        assemble_extended_profile(
            base_profile=args.base_profile,
            measurement_path=args.measurement_output,
        ),
    )
    print(f"wrote extended PrefillReload profile: {args.profile_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
