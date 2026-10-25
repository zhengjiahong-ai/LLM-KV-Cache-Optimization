import hashlib
import json

import pytest

from kvopt.workload.continuum_native_formal_profile import assemble
from kvopt.workload.continuum_w1b_profile_runner import measurement_config


def _protocol() -> dict:
    return {
        "schema_version": "continuum.native_costaware_prefill_profile_protocol.v1",
        "token_grid": [256, 32256],
        "model": {"name": "m", "revision": "r", "tokenizer_revision": "t"},
        "measurement": {
            "pressure_prompt_tokens": 512,
            "block_size_tokens": 16,
            "seed": 1,
            "max_new_tokens": 1,
            "temperature": 0.0,
            "maximum_pressure_batches": 64,
            "gpu_memory_utilization": 0.8,
            "max_num_batched_tokens": 2048,
            "enable_chunked_prefill": True,
            "enforce_eager": True,
        },
    }


def test_formal_profile_measurement_uses_independent_campaign_identity() -> None:
    config = measurement_config(base_config={}, protocol=_protocol(), token_count=32256)
    assert config["campaign_kind"] == "continuum_native_costaware_prefill_profile"
    assert config["cache"]["block_override"] == 2048
    assert config["backend_options"]["program_prefix_tokens"] == {
        "formal-profile": 32256
    }
    assert config["backend_options"]["max_num_batched_tokens"] == 2048
    assert config["backend_options"]["enable_chunked_prefill"] is True
    assert config["backend_options"]["enforce_eager"] is True


def test_formal_profile_measurement_rejects_unfrozen_point() -> None:
    with pytest.raises(ValueError, match="outside the frozen profile grid"):
        measurement_config(base_config={}, protocol=_protocol(), token_count=16384)


def test_assemble_uses_protocol_pair_counts(tmp_path) -> None:
    protocol = _protocol()
    protocol["token_grid"] = [1024, 4096]
    protocol["coverage_requirement"] = {"maximum_known_query_tokens": 4096}
    protocol["measurement"].update(
        warmup_pairs_per_point=2,
        measured_pairs_per_point=8,
    )
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    protocol_sha = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    points_dir = tmp_path / "points"
    points_dir.mkdir()
    for token_count, median in ((1024, 0.1), (4096, 0.2)):
        deltas = [median] * 8
        point = {
            "schema_version": "continuum.native_costaware_prefill_profile_point.v1",
            "protocol_sha256": protocol_sha,
            "git_sha": "a" * 40,
            "base_config_sha256": "b" * 64,
            "point": {
                "token_count": token_count,
                "warmup_pairs": [{}, {}],
                "measured_pairs": [{} for _ in range(8)],
                "measured_raw_deltas_seconds": deltas,
                "median_raw_delta_seconds": median,
            },
        }
        (points_dir / f"point-{token_count}.json").write_text(
            json.dumps(point), encoding="utf-8"
        )

    profile = assemble(
        protocol_path=protocol_path,
        points_dir=points_dir,
        output_path=tmp_path / "profile.json",
    )

    assert profile["protocol"]["warmup_pairs_per_point"] == 2
    assert profile["protocol"]["measured_pairs_per_point"] == 8
