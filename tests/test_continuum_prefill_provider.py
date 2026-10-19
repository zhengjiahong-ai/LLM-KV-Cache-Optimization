from __future__ import annotations

import hashlib
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


def _extended_artifact(base_path: Path, base: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "continuum.prefill_reload.extended_profile.v1",
        "status": "complete",
        "protocol": {
            **base["protocol"],
            "grid": [*TOKEN_GRID, 544],
        },
        "provenance": {"run_id": "extension-test"},
        "extension": {
            "base_profile_path": str(base_path),
            "base_profile_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
            "measured_extension_points": [544],
            "interpolation_rule": "piecewise_linear_between_measured_points",
        },
        "points": [*base["points"], _point(544, 0.2)],
    }


def test_extended_profile_preserves_legacy_points_and_supports_required_range(
    tmp_path: Path,
) -> None:
    base = _artifact()
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    extended_path = tmp_path / "extended.json"
    extended_path.write_text(
        json.dumps(_extended_artifact(base_path, base)), encoding="utf-8"
    )

    provider = _load(extended_path)

    for token_count, expected in FORMAL_MEDIANS.items():
        assert provider.estimate(token_count)[0] == expected
    assert provider.estimate(528)[0] == pytest.approx(
        FORMAL_MEDIANS[512] + (0.2 - FORMAL_MEDIANS[512]) / 2
    )
    assert provider.estimate(544)[0] == 0.2
    with pytest.raises(ValueError, match="outside"):
        provider.estimate(545)


def test_extended_profile_rejects_changed_legacy_point(tmp_path: Path) -> None:
    base = _artifact()
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    extended = _extended_artifact(base_path, base)
    extended["points"][0]["median_raw_delta_seconds"] = 0.5
    extended_path = tmp_path / "extended.json"
    extended_path.write_text(json.dumps(extended), encoding="utf-8")

    with pytest.raises(ValueError, match="changed legacy"):
        _load(extended_path)


def test_extended_profile_rejects_wrong_base_hash(tmp_path: Path) -> None:
    base = _artifact()
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    extended = _extended_artifact(base_path, base)
    extended["extension"]["base_profile_sha256"] = "0" * 64
    extended_path = tmp_path / "extended.json"
    extended_path.write_text(json.dumps(extended), encoding="utf-8")

    with pytest.raises(ValueError, match="base SHA-256"):
        _load(extended_path)
