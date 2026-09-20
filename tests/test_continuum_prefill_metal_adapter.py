from __future__ import annotations

import importlib
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any

import pytest

TOKEN_GRID = (16, 32, 128, 256, 512)
VOCAB_SIZE = 32_768


@dataclass(frozen=True)
class _Completion:
    token_ids: tuple[int, ...]


@dataclass(frozen=True)
class _RequestOutput:
    request_id: str
    outputs: tuple[_Completion, ...]
    finished: bool


@dataclass(frozen=True)
class _RawNativeObservation:
    num_cached_tokens: int
    num_cache_creation_tokens: int
    native_hashes: tuple[bytes, ...]


@dataclass(frozen=True)
class _TokensPrompt:
    prompt_token_ids: tuple[int, ...]


@dataclass(frozen=True)
class _SamplingParams:
    max_tokens: int
    temperature: float
    seed: int


class _ReadOnlyNativeSurface:
    """Fake read-only hash surface shaped after the qualified native evidence."""

    def __init__(self) -> None:
        self.present_hashes: set[bytes] = set()
        self.lookup_calls = 0
        self.mutation_attempts = 0
        self._observations: dict[str, _RawNativeObservation] = {}
        self._cleaned: set[str] = set()

    def lookup_hash(self, native_hash: bytes) -> bool:
        self.lookup_calls += 1
        return native_hash in self.present_hashes

    def record_observation(
        self,
        internal_id: str,
        observation: _RawNativeObservation,
    ) -> None:
        self._observations[internal_id] = observation

    def observation_for_internal(self, internal_id: str) -> _RawNativeObservation:
        if internal_id in self._cleaned:
            raise RuntimeError("native request observation was already cleaned")
        return self._observations[internal_id]

    def cleanup_observations(self) -> None:
        self._cleaned.update(self._observations)


class _FakeEngine:
    """Small real-shaped Engine API with an expiring native observation window."""

    def __init__(
        self,
        *,
        native: _ReadOnlyNativeSurface,
        auto_complete: bool = False,
    ) -> None:
        self.added: list[dict[str, object]] = []
        self._native = native
        self._internal_by_external: dict[str, str] = {}
        self._outputs: deque[tuple[_RequestOutput, ...]] = deque()
        self._unfinished = False
        self._auto_complete = auto_complete
        self.max_concurrent_requests = 0

    def add_request(
        self,
        request_id: str,
        prompt: object,
        sampling_params: object,
    ) -> str:
        if self._unfinished:
            raise AssertionError("request submitted before previous request completed")
        internal_id = f"{request_id}-internal-random-suffix"
        if isinstance(prompt, _TokensPrompt):
            token_ids = prompt.prompt_token_ids
        else:
            token_ids = tuple(prompt)  # type: ignore[arg-type]
        self._internal_by_external[request_id] = internal_id
        self.added.append(
            {
                "external_id": request_id,
                "internal_id": internal_id,
                "prompt": prompt,
                "sampling_params": sampling_params,
                "token_ids": token_ids,
            }
        )
        self._unfinished = True
        self.max_concurrent_requests = max(
            self.max_concurrent_requests,
            int(self._unfinished),
        )
        if self._auto_complete:
            prefix_tokens = max(len(token_ids) - 1, 1)
            self._outputs.append(())
            self.queue_output(
                _RequestOutput(request_id, (_Completion((1,)),), finished=True),
                _raw_observation(prefix_tokens, miss=True),
            )
        return internal_id

    def queue_output(
        self,
        output: _RequestOutput,
        observation: _RawNativeObservation,
    ) -> None:
        internal_id = self._internal_by_external[output.request_id]
        self._native.record_observation(internal_id, observation)
        self._outputs.append((output,))

    def step(self) -> tuple[_RequestOutput, ...]:
        if not self._outputs:
            return ()
        outputs = self._outputs.popleft()
        if any(output.finished for output in outputs):
            self._unfinished = False
        return outputs

    def has_unfinished_requests(self) -> bool:
        if not self._unfinished:
            self._native.cleanup_observations()
        return self._unfinished

    def finish_current_request(self) -> None:
        self._unfinished = False

    def internal_for_external(self, external_id: str) -> str:
        return self._internal_by_external[external_id]


def _load_adapter_module() -> Any:
    """Keep the single future module seam local to this RED file."""

    return importlib.import_module("scripts.spikes.run_continuum_prefill_profile_metal")


def _build_adapter(engine: _FakeEngine, native: _ReadOnlyNativeSurface) -> Any:
    module = _load_adapter_module()
    return module.build_adapter(
        engine=engine,
        native=native,
        vocabulary_size=VOCAB_SIZE,
        observation_reader=native.observation_for_internal,
        tokens_input_factory=lambda token_ids: _TokensPrompt(tuple(token_ids)),
        sampling_params_factory=lambda **kwargs: _SamplingParams(**kwargs),
    )


def _raw_observation(r: int, *, miss: bool) -> _RawNativeObservation:
    return _RawNativeObservation(
        num_cached_tokens=0 if miss else r,
        num_cache_creation_tokens=r if miss else 0,
        native_hashes=(f"target-hash-{r}".encode(),),
    )


def test_adapter_correlates_external_and_internal_ids_and_normalizes_step_output() -> None:
    native = _ReadOnlyNativeSurface()
    engine = _FakeEngine(native=native)
    adapter = _build_adapter(engine, native)

    external_id = adapter.submit_target(
        (101, 102, 103),
        max_tokens=1,
        temperature=0.0,
        seed=0,
    )
    assert adapter.step() == ()
    engine.queue_output(
        _RequestOutput(external_id, (_Completion((7,)),), finished=True),
        _raw_observation(16, miss=True),
    )

    assert external_id == engine.added[-1]["external_id"]
    assert engine.added[-1]["internal_id"] != external_id
    assert isinstance(engine.added[-1]["prompt"], _TokensPrompt)
    assert isinstance(engine.added[-1]["sampling_params"], _SamplingParams)
    normalized = adapter.step()

    assert len(normalized) == 1
    assert normalized[0].request_id == external_id
    assert normalized[0].generated_token_ids == (7,)
    assert normalized[0].finished is True
    assert native.observation_for_internal(engine.internal_for_external(external_id))


def test_adapter_idle_delegates_only_to_engine_unfinished_request_state() -> None:
    native = _ReadOnlyNativeSurface()
    engine = _FakeEngine(native=native)
    adapter = _build_adapter(engine, native)

    assert adapter.is_idle() is True
    adapter.submit_target(
        (1, 2),
        max_tokens=1,
        temperature=0.0,
        seed=0,
    )
    assert adapter.is_idle() is False
    engine.finish_current_request()
    assert adapter.is_idle() is True


def test_adapter_captures_observation_before_native_cleanup() -> None:
    native = _ReadOnlyNativeSurface()
    engine = _FakeEngine(native=native)
    adapter = _build_adapter(engine, native)

    external_id = adapter.submit_target(
        tuple(range(17)),
        max_tokens=1,
        temperature=0.0,
        seed=0,
    )
    assert adapter.step() == ()
    engine.queue_output(
        _RequestOutput(external_id, (_Completion((9,)),), finished=True),
        _raw_observation(16, miss=True),
    )
    adapter.step()
    engine.finish_current_request()
    assert adapter.is_idle() is True

    observation = adapter.request_observation(external_id)
    assert observation.num_cached_tokens == 0
    assert observation.num_cache_creation_tokens == 16
    assert observation.prefix_material_created is True
    assert observation.prefix_material_reused is False

    hit_id = adapter.submit_target(
        tuple(range(17)),
        max_tokens=1,
        temperature=0.0,
        seed=0,
    )
    assert adapter.step() == ()
    engine.queue_output(
        _RequestOutput(hit_id, (_Completion((10,)),), finished=True),
        _raw_observation(16, miss=False),
    )
    adapter.step()
    engine.finish_current_request()
    assert adapter.is_idle() is True

    hit_observation = adapter.request_observation(hit_id)
    assert hit_observation.num_cached_tokens == 16
    assert hit_observation.num_cache_creation_tokens == 0
    assert hit_observation.prefix_material_created is False
    assert hit_observation.prefix_material_reused is True


def test_adapter_reads_target_presence_from_captured_hash_material_without_mutation() -> None:
    native = _ReadOnlyNativeSurface()
    engine = _FakeEngine(native=native)
    adapter = _build_adapter(engine, native)

    target_hashes = (b"target-hash-0", b"target-hash-1")
    adapter.capture_target_material(target_hashes)
    assert adapter.read_target_material_presence() is False
    native.present_hashes.add(b"target-hash-0")
    assert adapter.read_target_material_presence() is False
    native.present_hashes.add(b"target-hash-1")
    assert adapter.read_target_material_presence() is True
    native.present_hashes.remove(b"target-hash-1")
    assert adapter.read_target_material_presence() is False
    assert native.lookup_calls > 0
    assert native.mutation_attempts == 0


def test_adapter_runs_32_distinct_serial_pressure_requests_without_native_mutation() -> None:
    native = _ReadOnlyNativeSurface()
    engine = _FakeEngine(native=native, auto_complete=True)
    adapter = _build_adapter(engine, native)

    target_first_block = tuple(adapter.target_token_ids(256)[:16])
    adapter.run_pressure_batch()
    first_batch = tuple(
        entry["token_ids"]  # type: ignore[assignment]
        for entry in engine.added
    )
    adapter.run_pressure_batch()
    second_batch = tuple(
        entry["token_ids"]  # type: ignore[assignment]
        for entry in engine.added[32:]
    )
    adapter.run_pressure_batch()

    batch = tuple(
        entry["token_ids"]  # type: ignore[assignment]
        for entry in engine.added
    )
    assert len(first_batch) == 32
    assert len(second_batch) == 32
    assert len(batch) == 96
    assert all(len(token_ids) == 512 for token_ids in batch)
    assert len(set(batch)) == 96
    assert set(first_batch).isdisjoint(second_batch)
    assert set(first_batch).isdisjoint(batch[64:])
    assert set(second_batch).isdisjoint(batch[64:])
    assert all(tuple(token_ids[:16]) != target_first_block for token_ids in batch)
    assert engine.max_concurrent_requests == 1
    assert native.mutation_attempts == 0
    assert adapter.is_idle() is True
    for entry in (engine.added[0], engine.added[32]):
        with pytest.raises(ValueError):
            adapter.request_observation(str(entry["external_id"]))


def test_adapter_seeds_each_grid_point_once_and_constructs_valid_non_nested_targets() -> None:
    before_vllm = {
        name for name in sys.modules if name == "vllm" or name.startswith("vllm.")
    }
    _load_adapter_module()
    after_vllm = {
        name for name in sys.modules if name == "vllm" or name.startswith("vllm.")
    }
    assert after_vllm == before_vllm

    native = _ReadOnlyNativeSurface()
    engine = _FakeEngine(native=native, auto_complete=True)
    adapter = _build_adapter(engine, native)

    targets = {
        token_count: tuple(adapter.target_token_ids(token_count))
        for token_count in TOKEN_GRID
    }
    for token_count, target in targets.items():
        assert len(target) == token_count + 1
        assert target == tuple(adapter.target_token_ids(token_count))
        assert all(0 <= token_id < VOCAB_SIZE for token_id in target)

    for index, smaller_count in enumerate(TOKEN_GRID):
        for larger_count in TOKEN_GRID[index + 1 :]:
            assert targets[smaller_count][:smaller_count] != targets[larger_count][:smaller_count]

    for token_count in TOKEN_GRID:
        native.present_hashes.clear()
        native.present_hashes.add(f"target-hash-{token_count}".encode())
        adapter.ensure_seeded(token_count)
        assert adapter.read_target_material_presence() is True
        adapter.ensure_seeded(token_count)
        assert adapter.read_target_material_presence() is True

    native.present_hashes.clear()
    native.present_hashes.add(b"target-hash-16")
    adapter.ensure_seeded(16)
    assert adapter.read_target_material_presence() is True

    assert len(engine.added) == len(TOKEN_GRID)
    assert adapter.is_idle() is True
    assert native.lookup_calls >= len(TOKEN_GRID)
    assert adapter.read_target_material_presence() is True
