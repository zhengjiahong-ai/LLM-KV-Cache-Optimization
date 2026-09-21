"""Offline PrefillReload profile loading and deterministic lookup."""

from __future__ import annotations

import json
import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import InputProvenance, InputSource

TOKEN_GRID = (16, 32, 128, 256, 512)
_SCHEMA = "continuum.prefill_reload.profile.v1"
_STATUS = "complete"
_PROVENANCE_REASON = "offline PrefillReload profile"

_EXPECTED_PROTOCOL = {
    "canonical_unit": "seconds",
    "grid": list(TOKEN_GRID),
    "warmup_pairs_per_point": 5,
    "measured_pairs_per_point": 20,
    "raw_delta_definition": "MISS - HIT",
}


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _require_finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{field_name} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _require_non_negative_finite_number(value: object, field_name: str) -> float:
    number = _require_finite_number(value, field_name)
    if number < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


def _validate_protocol(protocol: object) -> None:
    actual = _require_mapping(protocol, "protocol")
    for field_name, expected in _EXPECTED_PROTOCOL.items():
        if actual.get(field_name) != expected:
            raise ValueError(f"protocol.{field_name} does not match frozen protocol")


def _validate_point(point: object, expected_token_count: int) -> float:
    data = _require_mapping(point, "point")
    token_count = data.get("token_count")
    if isinstance(token_count, bool) or not isinstance(token_count, int):
        raise TypeError("point.token_count must be int")
    if token_count != expected_token_count:
        raise ValueError("point token_count does not match frozen grid")

    warmup_pairs = data.get("warmup_pairs")
    if not isinstance(warmup_pairs, list) or len(warmup_pairs) != 5:
        raise ValueError("each point must contain exactly 5 warmup pairs")
    measured_pairs = data.get("measured_pairs")
    if not isinstance(measured_pairs, list) or len(measured_pairs) != 20:
        raise ValueError("each point must contain exactly 20 measured pairs")

    raw_deltas = data.get("measured_raw_deltas_seconds")
    if not isinstance(raw_deltas, list) or len(raw_deltas) != 20:
        raise ValueError("each point must contain exactly 20 raw measured deltas")
    normalized_deltas = [
        _require_finite_number(value, "measured_raw_deltas_seconds")
        for value in raw_deltas
    ]
    median = _require_non_negative_finite_number(
        data.get("median_raw_delta_seconds"), "median_raw_delta_seconds"
    )
    expected_median = float(statistics.median(normalized_deltas))
    if not math.isclose(median, expected_median, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("median_raw_delta_seconds is inconsistent with raw deltas")
    return median


@dataclass(frozen=True, slots=True)
class _ProfilePrefillReloadProvider:
    """Immutable provider backed by one validated offline profile."""

    token_counts: tuple[int, ...]
    reload_seconds: tuple[float, ...]
    provenance: InputProvenance

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        if isinstance(token_count, bool) or not isinstance(token_count, int):
            raise TypeError("token_count must be int")
        if token_count < self.token_counts[0] or token_count > self.token_counts[-1]:
            raise ValueError("token_count is outside the supported profile range")

        exact_index = bisect_right(self.token_counts, token_count)
        if exact_index and self.token_counts[exact_index - 1] == token_count:
            return self.reload_seconds[exact_index - 1], self.provenance

        upper_index = exact_index
        lower_index = upper_index - 1
        lower_tokens = self.token_counts[lower_index]
        upper_tokens = self.token_counts[upper_index]
        lower_seconds = self.reload_seconds[lower_index]
        upper_seconds = self.reload_seconds[upper_index]
        fraction = (token_count - lower_tokens) / (upper_tokens - lower_tokens)
        seconds = lower_seconds + fraction * (upper_seconds - lower_seconds)
        return seconds, self.provenance


def load_prefill_reload_provider(
    path: str | Path,
) -> _ProfilePrefillReloadProvider:
    """Load and validate a complete frozen PrefillReload profile artifact."""
    profile_path = Path(path)
    with profile_path.open("r", encoding="utf-8") as stream:
        artifact = json.load(stream)
    data = _require_mapping(artifact, "artifact")
    if data.get("schema") != _SCHEMA:
        raise ValueError("artifact schema does not match frozen profile schema")
    if data.get("status") != _STATUS:
        raise ValueError("only complete profile artifacts are loadable")
    _validate_protocol(data.get("protocol"))

    points = data.get("points")
    if not isinstance(points, list) or len(points) != len(TOKEN_GRID):
        raise ValueError("profile must contain exactly the frozen token grid")
    by_token_count: dict[int, float] = {}
    for point in points:
        point_data = _require_mapping(point, "point")
        token_count = point_data.get("token_count")
        if isinstance(token_count, bool) or not isinstance(token_count, int):
            raise TypeError("point.token_count must be int")
        if token_count not in TOKEN_GRID or token_count in by_token_count:
            raise ValueError("profile points must match the frozen grid exactly")
        by_token_count[token_count] = _validate_point(point, token_count)
    if set(by_token_count) != set(TOKEN_GRID):
        raise ValueError("profile points must match the frozen grid exactly")

    provenance = InputProvenance(InputSource.APPROXIMATED, _PROVENANCE_REASON)
    return _ProfilePrefillReloadProvider(
        TOKEN_GRID,
        tuple(by_token_count[token_count] for token_count in TOKEN_GRID),
        provenance,
    )
