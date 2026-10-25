import pytest

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
