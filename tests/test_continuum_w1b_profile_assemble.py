from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.continuum.prefill_profile import load_prefill_reload_provider
from kvopt.workload.continuum_w1b_profile import W1B_TOKEN_GRID


def _point(token_count: int) -> dict[str, object]:
    deltas = [float(token_count) / 1000] * 20
    return {
        "token_count": token_count,
        "warmup_pairs": [{} for _ in range(5)],
        "measured_pairs": [{} for _ in range(20)],
        "measured_raw_deltas_seconds": deltas,
        "median_raw_delta_seconds": deltas[0],
    }


def test_loader_interpolates_w1b_profile_without_extrapolation(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "schema": "continuum.prefill_reload.w1b_long_context_profile.v1",
                "status": "complete",
                "protocol": {
                    "canonical_unit": "seconds",
                    "grid": list(W1B_TOKEN_GRID),
                    "warmup_pairs_per_point": 5,
                    "measured_pairs_per_point": 20,
                    "raw_delta_definition": "MISS - HIT TTFT",
                    "interpolation_rule": "piecewise_linear_between_measured_points",
                    "extrapolation": "PROHIBITED",
                },
                "points": [_point(value) for value in W1B_TOKEN_GRID],
            }
        ),
        encoding="utf-8",
    )
    provider = load_prefill_reload_provider(path)
    estimate, _provenance = provider.estimate(1456)
    assert 1.024 < estimate < 2.048
    with pytest.raises(ValueError, match="outside"):
        provider.estimate(6000)
