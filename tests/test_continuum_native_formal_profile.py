import hashlib
import json
from pathlib import Path

import pytest

from kvopt.continuum.prefill_profile import load_prefill_reload_provider
from kvopt.workload.continuum_native_formal_profile import (
    assemble,
    interpret_nonnegative_cost,
)
from kvopt.workload.continuum_w1b_profile_runner import measurement_config

ROOT = Path(__file__).resolve().parents[1]


def _protocol() -> dict:
    return {
        "schema_version": "continuum.native_costaware_prefill_profile_protocol.v1",
        "token_grid": [256, 32256],
        "execution_backend": {"max_model_len": 32768},
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


@pytest.mark.parametrize("token_count", [256, 32256])
def test_formal_profile_measurement_uses_independent_campaign_identity(
    token_count: int,
) -> None:
    config = measurement_config(
        base_config={}, protocol=_protocol(), token_count=token_count
    )
    assert config["campaign_kind"] == "continuum_native_costaware_prefill_profile"
    assert config["cache"]["block_override"] == 2048
    assert config["backend_options"]["program_prefix_tokens"] == {
        "formal-profile": token_count
    }
    assert config["backend_options"]["max_num_batched_tokens"] == 2048
    assert config["backend_options"]["enable_chunked_prefill"] is True
    assert config["backend_options"]["enforce_eager"] is True


def test_formal_profile_measurement_rejects_unfrozen_point() -> None:
    with pytest.raises(ValueError, match="outside the frozen profile grid"):
        measurement_config(base_config={}, protocol=_protocol(), token_count=16384)


def test_bounded_formal_profile_keeps_full_runtime_pool_at_every_anchor() -> None:
    protocol = json.loads(
        (
            ROOT
            / "configs/phase2/continuum-native-cost-aware-bounded-prefill-profile-v1.json"
        ).read_text()
    )

    for token_count in protocol["token_grid"]:
        config = measurement_config(
            base_config={}, protocol=protocol, token_count=token_count
        )
        assert config["cache"]["block_override"] == 2048
        assert config["backend_options"]["max_model_len"] == 32768


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


def test_authorized_interpretation_preserves_raw_and_projects_only_1024(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.json"
    raw = {
        "schema": "continuum.prefill_reload.formal_long_context_profile.v1",
        "status": "review_required",
        "protocol": {
            "canonical_unit": "seconds",
            "grid": [1024, 4096],
            "warmup_pairs_per_point": 2,
            "measured_pairs_per_point": 8,
            "raw_delta_definition": "MISS - HIT TTFT",
            "interpolation_rule": "piecewise_linear_between_measured_points",
            "extrapolation": "PROHIBITED",
        },
        "model": {"name": "m", "revision": "r"},
        "points": [
            {
                "token_count": 1024,
                "warmup_pairs": [{}, {}],
                "measured_pairs": [{} for _ in range(8)],
                "measured_raw_deltas_seconds": [-0.1] * 4 + [0.1] * 4,
                "median_raw_delta_seconds": 0.0,
                "validity_status": "REVIEW_REQUIRED_NON_POSITIVE_MEDIAN",
                "uncertainty": {
                    "bootstrap_median_95_percent_interval_seconds": [-0.1, 0.1]
                },
            },
            {
                "token_count": 4096,
                "warmup_pairs": [{}, {}],
                "measured_pairs": [{} for _ in range(8)],
                "measured_raw_deltas_seconds": [0.3] * 8,
                "median_raw_delta_seconds": 0.3,
                "validity_status": "PASS",
                "uncertainty": {
                    "bootstrap_median_95_percent_interval_seconds": [0.2, 0.4]
                },
            },
        ],
    }
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    raw_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "continuum.native_costaware_profile_interpretation_contract.v1"
                ),
                "raw_profile_sha256": raw_sha,
                "projection": {
                    "token_count": 1024,
                    "raw_status": "REVIEW_REQUIRED_NON_POSITIVE_MEDIAN",
                    "interpreted_status": "INDISTINGUISHABLE_FROM_ZERO",
                    "effective_cost_seconds": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "interpreted.json"

    interpreted = interpret_nonnegative_cost(
        raw_profile_path=raw_path,
        contract_path=contract_path,
        output_path=output,
    )

    assert raw_path.read_text(encoding="utf-8") == json.dumps(raw)
    assert interpreted["points"][0]["median_raw_delta_seconds"] == 0.0
    assert interpreted["points"][0]["effective_cost_seconds"] == 0.0
    assert interpreted["points"][1]["effective_cost_seconds"] == 0.3
    provider = load_prefill_reload_provider(output)
    assert provider.estimate(1024)[0] == 0.0
    assert provider.estimate(4096)[0] == 0.3
    assert provider.default_ttl_reference()[:2] == (4096, 0.3)


def test_interpretation_rejects_unapproved_raw_sha(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("{}", encoding="utf-8")
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": (
                    "continuum.native_costaware_profile_interpretation_contract.v1"
                ),
                "raw_profile_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="review-required"):
        interpret_nonnegative_cost(
            raw_profile_path=raw_path,
            contract_path=contract,
            output_path=tmp_path / "out.json",
        )
