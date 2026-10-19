import hashlib
import json
from pathlib import Path

from kvopt.workload.phase2g_a2_profile_extension_runner import (
    _measurement_config,
    assemble_extended_profile,
)


def _point(token_count: int, value: float) -> dict[str, object]:
    return {
        "token_count": token_count,
        "warmup_pairs": [{} for _ in range(5)],
        "measured_pairs": [{"raw_delta_seconds": value} for _ in range(20)],
        "measured_raw_deltas_seconds": [value] * 20,
        "median_raw_delta_seconds": value,
    }


def test_measurement_config_freezes_only_the_authorized_extension(tmp_path: Path) -> None:
    base_profile = tmp_path / "base.json"
    base_profile.write_text("{}\n", encoding="utf-8")
    config = _measurement_config(
        {
            "runtime_mode": "vllm-metal-observability",
            "model": {"name": "model", "revision": "revision"},
            "tokenizer": {"name": "model", "revision": "revision"},
        },
        base_profile,
    )

    assert config["backend_options"]["program_prefix_tokens"] == {
        "profile-extension": 544
    }
    assert config["cache"] == {"block_size": 16, "block_override": 66}
    assert config["generation"] == {"max_new_tokens": 1, "temperature": 0.0}
    assert config["backend_options"]["gpu_memory_utilization"] == 0.75
    assert config["backend_options"]["phase2g_block_policy"] == "A0"


def test_assemble_extended_profile_copies_legacy_points_exactly(tmp_path: Path) -> None:
    legacy_points = [_point(count, count / 10_000) for count in (16, 32, 128, 256, 512)]
    base = {
        "schema": "continuum.prefill_reload.profile.v1",
        "status": "complete",
        "protocol": {
            "canonical_unit": "seconds",
            "grid": [16, 32, 128, 256, 512],
            "warmup_pairs_per_point": 5,
            "measured_pairs_per_point": 20,
            "raw_delta_definition": "MISS - HIT",
        },
        "points": legacy_points,
    }
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    measurement = {
        "status": "complete",
        "git_sha": "a" * 40,
        "base_profile_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "point": _point(544, 0.2),
    }
    measurement_path = tmp_path / "measurement.json"
    measurement_path.write_text(json.dumps(measurement), encoding="utf-8")

    extended = assemble_extended_profile(
        base_profile=base_path,
        measurement_path=measurement_path,
    )

    assert extended["points"][:5] == legacy_points
    assert extended["points"][5]["token_count"] == 544
    assert extended["protocol"]["grid"] == [16, 32, 128, 256, 512, 544]
    assert extended["extension"]["measured_extension_points"] == [544]
