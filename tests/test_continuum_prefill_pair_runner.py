from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import pytest

TOKEN_GRID = (16, 32, 128, 256, 512)


@dataclass(frozen=True)
class _NativeRequestObservation:
    num_cached_tokens: int
    num_cache_creation_tokens: int
    prefix_material_created: bool
    prefix_material_reused: bool


@dataclass(frozen=True)
class _StepOutput:
    request_id: str
    generated_token_ids: tuple[int, ...]
    finished: bool


class _FakeClock:
    def __init__(self, boundary: _FakeNativeBoundary) -> None:
        self._boundary = boundary

    def __call__(self) -> float:
        return 100.0 + self._boundary.step_calls * 0.25


class _FakeNativeBoundary:
    """Semantic fake for the native request/observation boundary."""

    def __init__(
        self,
        observations: Sequence[_NativeRequestObservation],
        *,
        target_presence: Sequence[bool] = (True, False),
    ) -> None:
        self._observations = tuple(observations)
        self._target_presence = tuple(target_presence)
        self._observation_index = 0
        self._presence_index = 0
        self._active_request_id: str | None = None
        self._active_output_emitted = False
        self.submissions: list[dict[str, object]] = []
        self.step_calls = 0
        self.empty_step_count = 0
        self.idle_checks = 0
        self.pressure_batches = 0
        self.presence_reads = 0

    def submit_target(
        self,
        token_ids: Sequence[int],
        *,
        max_tokens: int,
        temperature: float,
        seed: int,
    ) -> str:
        if self._active_request_id is not None:
            raise AssertionError("target submitted before the previous request was idle")
        request_id = f"native-request-{len(self.submissions)}"
        self._active_request_id = request_id
        self._active_output_emitted = False
        self.submissions.append(
            {
                "request_id": request_id,
                "token_ids": tuple(token_ids),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "seed": seed,
            }
        )
        return request_id

    def step(self) -> tuple[_StepOutput, ...]:
        if self._active_request_id is None:
            raise AssertionError("step called without an active request")
        self.step_calls += 1
        if not self._active_output_emitted:
            self._active_output_emitted = True
            self.empty_step_count += 1
            return ()
        request_id = self._active_request_id
        self._active_request_id = None
        return (_StepOutput(request_id, (1,), True),)

    def is_idle(self) -> bool:
        self.idle_checks += 1
        return self._active_request_id is None

    def request_observation(self, _request_id: str) -> _NativeRequestObservation:
        if self._observation_index >= len(self._observations):
            raise AssertionError("unexpected native observation request")
        observation = self._observations[self._observation_index]
        self._observation_index += 1
        return observation

    def read_target_material_presence(self) -> bool:
        if self._presence_index >= len(self._target_presence):
            raise AssertionError("target presence was read beyond the configured sequence")
        self.presence_reads += 1
        present = self._target_presence[self._presence_index]
        self._presence_index += 1
        return present

    def run_pressure_batch(self) -> None:
        self.pressure_batches += 1


def _token_pair(r: int) -> tuple[tuple[int, ...], int]:
    base = 10_000 + TOKEN_GRID.index(r) * 2_000
    prefix = tuple(base + index for index in range(r))
    suffix = base + r
    return prefix, suffix


def _valid_observations(r: int) -> tuple[_NativeRequestObservation, ...]:
    return (
        _NativeRequestObservation(0, r, True, False),
        _NativeRequestObservation(r, 0, False, True),
    )


def _run_pair(
    boundary: _FakeNativeBoundary,
    r: int,
    *,
    diagnostics: Callable[[Mapping[str, object]], None] | None = None,
    prefix_token_ids: Sequence[int] | None = None,
    suffix_token_id: int | None = None,
) -> tuple[float, float]:
    from scripts.spikes.run_continuum_prefill_profile import run_prefill_pair

    prefix, suffix = _token_pair(r)
    if prefix_token_ids is not None:
        prefix = tuple(prefix_token_ids)
    if suffix_token_id is not None:
        suffix = suffix_token_id
    return run_prefill_pair(
        r=r,
        prefix_token_ids=prefix,
        suffix_token_id=suffix,
        native=boundary,
        timer=_FakeClock(boundary),
        diagnostics_sink=diagnostics,
        max_pressure_batches=8,
    )


def test_pair_runner_uses_corrected_r_plus_one_inputs_for_frozen_grid() -> None:
    for r in TOKEN_GRID:
        boundary = _FakeNativeBoundary(_valid_observations(r))

        _run_pair(boundary, r)

        assert len(boundary.submissions) == 2
        first, second = boundary.submissions[:2]
        prefix, suffix = _token_pair(r)
        assert first["token_ids"] == prefix + (suffix,)
        assert second["token_ids"] == first["token_ids"]
        assert len(first["token_ids"]) == r + 1

    prefix, suffix = _token_pair(16)
    boundary = _FakeNativeBoundary(_valid_observations(16))
    with pytest.raises(ValueError):
        _run_pair(
            boundary,
            16,
            prefix_token_ids=prefix[:-1],
            suffix_token_id=suffix,
        )
    assert boundary.submissions == []


def test_pair_runner_uses_first_nonempty_token_and_waits_for_idle() -> None:
    boundary = _FakeNativeBoundary(_valid_observations(16))

    result = _run_pair(boundary, 16)

    assert result == pytest.approx((0.5, 0.5))
    assert boundary.empty_step_count >= 2
    assert boundary.step_calls >= 4
    assert boundary.idle_checks >= 3
    assert all(call["max_tokens"] == 1 for call in boundary.submissions)
    assert all(call["temperature"] == 0.0 for call in boundary.submissions)
    assert all(call["seed"] == 0 for call in boundary.submissions)


def test_pair_runner_rejects_invalid_miss_before_returning_latency() -> None:
    invalid_misses = (
        _NativeRequestObservation(16, 16, True, False),
        _NativeRequestObservation(0, 16, False, True),
    )
    for invalid_miss in invalid_misses:
        boundary = _FakeNativeBoundary((invalid_miss, *_valid_observations(16)[1:]))

        with pytest.raises(ValueError):
            _run_pair(boundary, 16)


def test_pair_runner_rejects_invalid_hit_before_returning_latency() -> None:
    invalid_hits = (
        _NativeRequestObservation(8, 0, False, True),
        _NativeRequestObservation(16, 0, True, False),
    )
    for invalid_hit in invalid_hits:
        observations = (
            _valid_observations(16)[0],
            invalid_hit,
        )
        boundary = _FakeNativeBoundary(observations)

        with pytest.raises(ValueError):
            _run_pair(boundary, 16)


def test_pair_runner_stops_pressure_when_native_target_material_disappears() -> None:
    boundary = _FakeNativeBoundary(
        _valid_observations(256),
        target_presence=(True, True, False),
    )

    result = _run_pair(boundary, 256)

    assert result == pytest.approx((0.5, 0.5))
    assert boundary.pressure_batches == 2
    assert boundary.presence_reads == 3
    assert len(boundary.submissions) == 2

    still_hit = _NativeRequestObservation(256, 0, False, True)
    boundary = _FakeNativeBoundary(
        (still_hit, _valid_observations(256)[1]),
        target_presence=(True, True, False),
    )
    with pytest.raises(ValueError):
        _run_pair(boundary, 256)
    assert boundary.pressure_batches == 2

    boundary = _FakeNativeBoundary(
        _valid_observations(256),
        target_presence=(True,) * 9,
    )
    with pytest.raises(ValueError):
        _run_pair(boundary, 256)
    assert boundary.pressure_batches == 8


def test_pair_runner_returns_tuple_only_after_validated_pair_and_records_diagnostics() -> None:
    boundary = _FakeNativeBoundary(_valid_observations(128))
    records: list[Mapping[str, object]] = []

    result = _run_pair(boundary, 128, diagnostics=records.append)

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert records
    diagnostic = records[-1]
    assert diagnostic["r"] == 128
    assert diagnostic["request_length"] == 129
    assert diagnostic["miss_num_cached_tokens"] == 0
    assert diagnostic["hit_num_cached_tokens"] == 128
    assert diagnostic["pressure_batches"] == 1
