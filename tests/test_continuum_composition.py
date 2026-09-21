from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kvopt.continuum import ContinuumConfig, FakeClock, InputProvenance, InputSource

TOKEN_GRID = (16, 32, 128, 256, 512)
FORMAL_MEDIANS = {
    16: 0.009522290994937066,
    32: 0.011798791994806379,
    128: 0.04975464601011481,
    256: 0.0887301250040764,
    512: 0.17105704150890233,
}


def _point(token_count: int, median: float) -> dict[str, Any]:
    return {
        "token_count": token_count,
        "warmup_pairs": [{} for _ in range(5)],
        "measured_pairs": [{} for _ in range(20)],
        "measured_raw_deltas_seconds": [median] * 20,
        "median_raw_delta_seconds": median,
    }


def _artifact(*, status: str = "complete") -> dict[str, Any]:
    return {
        "schema": "continuum.prefill_reload.profile.v1",
        "status": status,
        "protocol": {
            "canonical_unit": "seconds",
            "grid": list(TOKEN_GRID),
            "warmup_pairs_per_point": 5,
            "measured_pairs_per_point": 20,
            "raw_delta_definition": "MISS - HIT",
        },
        "provenance": {"run_id": "composition-test"},
        "points": [_point(token_count, FORMAL_MEDIANS[token_count]) for token_count in TOKEN_GRID],
    }


def _write_profile(tmp_path: Path, *, status: str = "complete") -> Path:
    path = tmp_path / "prefill-profile.json"
    path.write_text(json.dumps(_artifact(status=status)), encoding="utf-8")
    return path


def _config(path: Path, *, version: str = "v1") -> ContinuumConfig:
    return ContinuumConfig(
        enabled=True,
        duration_history_threshold=37,
        queue_delay_window_size=11,
        prefill_profile_path=str(path),
        prefill_profile_version=version,
    )


def test_build_runtime_from_config_loads_profile_and_derives_default_ttl(
    tmp_path: Path,
) -> None:
    from kvopt.continuum.composition import build_runtime_from_config

    runtime = build_runtime_from_config(config=_config(_write_profile(tmp_path)), clock=FakeClock())

    assert runtime._default_ttl_seconds == 0.0  # type: ignore[attr-defined]
    seconds, provenance = runtime._prefill_reload_provider.estimate(256)  # type: ignore[attr-defined]
    assert seconds == FORMAL_MEDIANS[256]
    assert provenance.source is InputSource.APPROXIMATED


def test_build_runtime_from_config_requires_profile_path(tmp_path: Path) -> None:
    from kvopt.continuum.composition import build_runtime_from_config

    config = ContinuumConfig(enabled=True, prefill_profile_version="v1")

    with pytest.raises(ValueError, match="prefill_profile_path"):
        build_runtime_from_config(config=config, clock=FakeClock())


def test_build_runtime_from_config_requires_supported_profile_version(
    tmp_path: Path,
) -> None:
    from kvopt.continuum.composition import build_runtime_from_config

    with pytest.raises(ValueError, match="prefill_profile_version"):
        build_runtime_from_config(
            config=_config(_write_profile(tmp_path), version="v2"),
            clock=FakeClock(),
        )


def test_build_runtime_from_config_rejects_incomplete_profile(tmp_path: Path) -> None:
    from kvopt.continuum.composition import build_runtime_from_config

    with pytest.raises(ValueError):
        build_runtime_from_config(
            config=_config(_write_profile(tmp_path, status="incomplete")),
            clock=FakeClock(),
        )


def test_composition_uses_provider_at_representative_token_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kvopt.continuum import composition

    class SpyProvider:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
            self.calls.append(token_count)
            return FORMAL_MEDIANS[256], InputProvenance(
                InputSource.APPROXIMATED, "test profile"
            )

    provider = SpyProvider()
    monkeypatch.setattr(composition, "load_prefill_reload_provider", lambda _path: provider)
    monkeypatch.setattr(composition, "build_runtime", lambda **kwargs: kwargs)

    result = composition.build_runtime_from_config(
        config=_config(_write_profile(tmp_path)), clock=FakeClock()
    )

    assert provider.calls == [256]
    assert result["default_ttl_seconds"] == 0.0


def test_composition_forwards_independent_runtime_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kvopt.continuum import composition

    captured: dict[str, object] = {}

    def fake_build_runtime(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(composition, "build_runtime", fake_build_runtime)

    composition.build_runtime_from_config(
        config=_config(_write_profile(tmp_path)), clock=FakeClock()
    )

    assert captured["duration_history_threshold"] == 37
    assert captured["queue_delay_window_size"] == 11
    assert captured["default_ttl_seconds"] == 0.0
    assert captured["prefill_reload_provider"] is not None
