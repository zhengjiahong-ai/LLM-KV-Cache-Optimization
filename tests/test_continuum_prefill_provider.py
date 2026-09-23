from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from kvopt.continuum.types import InputSource

TOKEN_GRID = (16, 32, 128, 256, 512)
FORMAL_MEDIANS = {
    16: 0.009522290994937066,
    32: 0.011798791994806379,
    128: 0.04975464601011481,
    256: 0.0887301250040764,
    512: 0.17105704150890233,
}


def _point(token_count: int, median_value: float) -> dict[str, Any]:
    measured = [median_value] * 20
    return {
        "token_count": token_count,
        "warmup_pairs": [{} for _ in range(5)],
        "measured_pairs": [{"raw_delta_seconds": value} for value in measured],
        "measured_raw_deltas_seconds": measured,
        "median_raw_delta_seconds": median_value,
    }


def _artifact(
    *,
    medians: dict[int, float] | None = None,
    points: list[dict[str, Any]] | None = None,
    protocol: dict[str, Any] | None = None,
    schema: str = "continuum.prefill_reload.profile.v1",
    status: str = "complete",
) -> dict[str, Any]:
    selected = FORMAL_MEDIANS if medians is None else medians
    return {
        "schema": schema,
        "status": status,
        "protocol": {
            "canonical_unit": "seconds",
            "grid": list(TOKEN_GRID),
            "warmup_pairs_per_point": 5,
            "measured_pairs_per_point": 20,
            "raw_delta_definition": "MISS - HIT",
            **(protocol or {}),
        },
        "provenance": {"run_id": "test-run"},
        "points": (
            [_point(token_count, selected[token_count]) for token_count in TOKEN_GRID]
            if points is None
            else points
        ),
    }


def _write_artifact(tmp_path: Path, artifact: dict[str, Any]) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def _load(path: Path) -> Any:
    from kvopt.continuum.prefill_profile import load_prefill_reload_provider

    return load_prefill_reload_provider(path)


def test_loads_complete_profile_and_returns_exact_formal_points(tmp_path: Path) -> None:
    provider = _load(_write_artifact(tmp_path, _artifact()))

    for token_count, expected in FORMAL_MEDIANS.items():
        seconds, provenance = provider.estimate(token_count)
        assert seconds == expected
        assert provenance.source is InputSource.APPROXIMATED


def test_provider_uses_values_from_loaded_artifact(tmp_path: Path) -> None:
    medians = dict(FORMAL_MEDIANS)
    medians[256] = 0.123
    provider = _load(_write_artifact(tmp_path, _artifact(medians=medians)))

    assert provider.estimate(256)[0] == 0.123


def test_accepts_negative_raw_delta_with_nonnegative_median(tmp_path: Path) -> None:
    points = [_point(token_count, FORMAL_MEDIANS[token_count]) for token_count in TOKEN_GRID]
    negative_raw = [-0.25] + [0.01] * 19
    points[0]["measured_pairs"] = [
        {"raw_delta_seconds": value} for value in negative_raw
    ]
    points[0]["measured_raw_deltas_seconds"] = negative_raw
    points[0]["median_raw_delta_seconds"] = 0.01

    provider = _load(_write_artifact(tmp_path, _artifact(points=points)))

    assert provider.estimate(16)[0] == 0.01


@pytest.mark.parametrize(
    "mutate",
    [
        lambda artifact: artifact.update(schema="wrong.schema"),
        lambda artifact: artifact.update(status="incomplete"),
        lambda artifact: artifact["protocol"].update(canonical_unit="milliseconds"),
        lambda artifact: artifact["protocol"].update(grid=[16, 32, 64, 256, 512]),
        lambda artifact: artifact["points"].pop(),
        lambda artifact: artifact["points"].__setitem__(1, artifact["points"][0]),
        lambda artifact: artifact["points"][0]["measured_pairs"].pop(),
        lambda artifact: artifact["points"][0]["measured_raw_deltas_seconds"].__setitem__(
            0, math.inf
        ),
        lambda artifact: artifact["points"][0].update(median_raw_delta_seconds=math.nan),
        lambda artifact: artifact["points"][0].update(median_raw_delta_seconds=0.0),
    ],
)
def test_rejects_invalid_or_inconsistent_artifact(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], object]
) -> None:
    artifact = _artifact()
    mutate(artifact)

    with pytest.raises((TypeError, ValueError)):
        _load(_write_artifact(tmp_path, artifact))


def test_rejects_negative_final_median(tmp_path: Path) -> None:
    medians = dict(FORMAL_MEDIANS)
    medians[16] = -0.01

    with pytest.raises(ValueError):
        _load(_write_artifact(tmp_path, _artifact(medians=medians)))


@pytest.mark.parametrize(
    ("token_count", "expected"),
    [
        (17, 0.009664572307429),
        (64, 0.024450743333243),
        (257, 0.089051714521673),
        (511, 0.170735451991305),
    ],
)
def test_interpolates_between_adjacent_formal_points(
    tmp_path: Path, token_count: int, expected: float
) -> None:
    provider = _load(_write_artifact(tmp_path, _artifact()))

    assert provider.estimate(token_count)[0] == pytest.approx(expected)


@pytest.mark.parametrize("token_count", [15, 513, 0, -1, True, 17.0, "17"])
def test_rejects_unsupported_or_invalid_token_count(
    tmp_path: Path, token_count: object
) -> None:
    provider = _load(_write_artifact(tmp_path, _artifact()))

    with pytest.raises((TypeError, ValueError)):
        provider.estimate(token_count)  # type: ignore[arg-type]
