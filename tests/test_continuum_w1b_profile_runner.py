from __future__ import annotations

import pytest

from kvopt.workload.continuum_w1b_profile_runner import measurement_config


def _protocol() -> dict[str, object]:
    return {
        "model": {"name": "model", "revision": "r1", "tokenizer_revision": "r1"},
        "measurement": {
            "pressure_prompt_tokens": 512,
            "block_size_tokens": 16,
            "seed": 1,
            "max_new_tokens": 1,
            "temperature": 0.0,
            "maximum_pressure_batches": 64,
            "gpu_memory_utilization": 0.8,
        },
    }


def test_measurement_config_scales_cache_with_target() -> None:
    config = measurement_config(
        base_config={"schema_version": "phase2.config.v1"},
        protocol=_protocol(),
        token_count=5120,
    )
    assert config["cache"]["block_override"] == 352
    assert config["backend_options"]["program_prefix_tokens"] == {
        "w1b-profile": 5120
    }
    assert config["model"]["name"] == "model"


def test_measurement_config_rejects_post_hoc_grid_point() -> None:
    with pytest.raises(ValueError, match="outside the frozen"):
        measurement_config(
            base_config={},
            protocol=_protocol(),
            token_count=6000,
        )
