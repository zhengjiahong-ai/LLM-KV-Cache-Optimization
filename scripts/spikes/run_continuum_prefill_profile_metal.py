"""Thin vLLM/Metal boundary for the prefill reload qualification runner.

The module deliberately keeps vLLM imports out of module scope.  A real
bootstrapper supplies an engine and a read-only native observation surface;
the adapter only translates their narrow runtime-shaped interfaces.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

TOKEN_GRID = (16, 32, 128, 256, 512)
PRESSURE_BATCH_SIZE = 32
PRESSURE_TOKEN_COUNT = 512


@dataclass(frozen=True)
class _NormalizedOutput:
    request_id: str
    generated_token_ids: tuple[int, ...]
    finished: bool


@dataclass(frozen=True)
class _CapturedObservation:
    num_cached_tokens: int
    num_cache_creation_tokens: int
    prefix_material_created: bool
    prefix_material_reused: bool
    native_hashes: tuple[bytes, ...]


class _MetalPrefillAdapter:
    def __init__(
        self,
        *,
        engine: Any,
        native: Any,
        vocabulary_size: int,
        observation_reader: Callable[[str], Any],
        tokens_input_factory: Callable[[Sequence[int]], Any],
        sampling_params_factory: Callable[..., Any],
    ) -> None:
        if vocabulary_size <= 0:
            raise ValueError("vocabulary_size must be positive")
        self._engine = engine
        self._native = native
        self._observation_reader = observation_reader
        self._tokens_input_factory = tokens_input_factory
        self._sampling_params_factory = sampling_params_factory
        self._vocabulary_size = vocabulary_size
        self._next_request_number = 0
        self._internal_by_external: dict[str, str] = {}
        self._observations: dict[str, _CapturedObservation] = {}
        self._target_hashes: tuple[bytes, ...] = ()
        self._target_hashes_by_r: dict[int, tuple[bytes, ...]] = {}
        self._seeded: set[int] = set()
        self._pressure_request_number = 0

    def submit_target(
        self,
        token_ids: Sequence[int],
        *,
        max_tokens: int,
        temperature: float,
        seed: int,
    ) -> str:
        external_id = f"continuum-prefill-{self._next_request_number}"
        self._next_request_number += 1
        internal_id = self._engine.add_request(
            external_id,
            self._tokens_input_factory(tuple(token_ids)),
            self._sampling_params_factory(
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
            ),
        )
        if not isinstance(internal_id, str) or not internal_id:
            raise ValueError("engine returned an invalid internal request ID")
        self._internal_by_external[external_id] = internal_id
        return external_id

    def step(self) -> tuple[_NormalizedOutput, ...]:
        native_outputs = self._engine.step()
        normalized: list[_NormalizedOutput] = []
        for native_output in native_outputs:
            external_id = getattr(native_output, "request_id", None)
            if not isinstance(external_id, str):
                continue
            internal_id = self._internal_by_external.get(external_id)
            if internal_id is None:
                continue
            generated_token_ids = _generated_token_ids(native_output)
            finished = bool(getattr(native_output, "finished", False))
            if generated_token_ids or finished:
                raw_observation = self._observation_reader(internal_id)
                self._observations[external_id] = _derive_observation(raw_observation)
            normalized.append(
                _NormalizedOutput(
                    request_id=external_id,
                    generated_token_ids=generated_token_ids,
                    finished=finished,
                )
            )
        return tuple(normalized)

    def is_idle(self) -> bool:
        return not self._engine.has_unfinished_requests()

    def request_observation(self, external_id: str) -> _CapturedObservation:
        try:
            return self._observations[external_id]
        except KeyError as exc:
            raise ValueError("request observation is not available") from exc

    def capture_target_material(self, native_hashes: Sequence[bytes]) -> None:
        self._target_hashes = tuple(native_hashes)

    def read_target_material_presence(self) -> bool:
        if not self._target_hashes:
            return False
        return all(self._native.lookup_hash(native_hash) for native_hash in self._target_hashes)

    def target_token_ids(self, token_count: int) -> tuple[int, ...]:
        if token_count not in TOKEN_GRID:
            raise ValueError("token_count must be one of the frozen profile points")
        prefix = tuple(
            (1_000 + token_count + index * 37) % self._vocabulary_size
            for index in range(token_count)
        )
        suffix = (30_000 + token_count) % self._vocabulary_size
        return prefix + (suffix,)

    def ensure_seeded(self, token_count: int) -> None:
        if token_count in self._seeded:
            self._target_hashes = self._target_hashes_by_r[token_count]
            return
        external_id = self.submit_target(
            self.target_token_ids(token_count),
            max_tokens=1,
            temperature=0.0,
            seed=0,
        )
        _drain_to_idle(self)
        observation = self.request_observation(external_id)
        self.capture_target_material(observation.native_hashes)
        self._target_hashes_by_r[token_count] = self._target_hashes
        if not self.read_target_material_presence():
            raise ValueError("seed target material is not present")
        self._seeded.add(token_count)

    def run_pressure_batch(self) -> None:
        for batch_index in range(PRESSURE_BATCH_SIZE):
            pressure_index = self._pressure_request_number + batch_index
            vocabulary_size = self._vocabulary_size
            token_ids = (
                0,
                pressure_index % vocabulary_size,
                (pressure_index // vocabulary_size) % vocabulary_size,
                *(
                    (13_000 + offset) % vocabulary_size
                    for offset in range(PRESSURE_TOKEN_COUNT - 3)
                ),
            )
            if any(token_id >= self._vocabulary_size for token_id in token_ids):
                raise ValueError("pressure token ID exceeds vocabulary")
            external_id = self.submit_target(
                token_ids,
                max_tokens=1,
                temperature=0.0,
                seed=batch_index,
            )
            _drain_to_idle(self)
            self._internal_by_external.pop(external_id, None)
            self._observations.pop(external_id, None)
        self._pressure_request_number += PRESSURE_BATCH_SIZE


def build_adapter(
    *,
    engine: Any,
    native: Any,
    vocabulary_size: int,
    observation_reader: Callable[[str], Any],
    tokens_input_factory: Callable[[Sequence[int]], Any] | None = None,
    sampling_params_factory: Callable[..., Any] | None = None,
) -> _MetalPrefillAdapter:
    """Build the adapter, lazily loading the pinned vLLM input factories."""

    if tokens_input_factory is None or sampling_params_factory is None:
        tokens_input_factory, sampling_params_factory = _lazy_request_factories()

    return _MetalPrefillAdapter(
        engine=engine,
        native=native,
        vocabulary_size=vocabulary_size,
        observation_reader=observation_reader,
        tokens_input_factory=tokens_input_factory,
        sampling_params_factory=sampling_params_factory,
    )


def _lazy_request_factories() -> tuple[
    Callable[[Sequence[int]], Any], Callable[..., Any]
]:
    from vllm import SamplingParams
    from vllm.inputs import tokens_input

    return tokens_input, SamplingParams


def _derive_observation(raw_observation: Any) -> _CapturedObservation:
    num_cached_tokens = int(raw_observation.num_cached_tokens)
    num_cache_creation_tokens = int(raw_observation.num_cache_creation_tokens)
    return _CapturedObservation(
        num_cached_tokens=num_cached_tokens,
        num_cache_creation_tokens=num_cache_creation_tokens,
        prefix_material_created=(
            num_cached_tokens == 0 and num_cache_creation_tokens > 0
        ),
        prefix_material_reused=(
            num_cached_tokens > 0 and num_cache_creation_tokens == 0
        ),
        native_hashes=tuple(raw_observation.native_hashes),
    )


def _generated_token_ids(native_output: Any) -> tuple[int, ...]:
    generated: list[int] = []
    for output in getattr(native_output, "outputs", ()):
        generated.extend(int(token_id) for token_id in getattr(output, "token_ids", ()))
    return tuple(generated)


def _drain_to_idle(adapter: _MetalPrefillAdapter) -> None:
    while not adapter.is_idle():
        adapter.step()
