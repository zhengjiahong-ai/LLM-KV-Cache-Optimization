from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest

from kvopt.continuum import Clock, FakeClock, RetentionMode
from kvopt.continuum.retention import RetentionManager
from kvopt.runtime.vllm import observer
from kvopt.runtime.vllm.retention_integration import (
    RetentionPressureResult,
    RetentionRuntimeIntegration,
)


@dataclass
class _FakeBlock:
    block_id: int


class _FakeQueue:
    _kvopt_policy_installed = False

    def __init__(self) -> None:
        self.popleft_calls = 0

    def popleft_n(self, required_blocks: int) -> list[_FakeBlock]:
        self.popleft_calls += 1
        return [_FakeBlock(7)]


class _FakeBlockPool:
    def _maybe_evict_cached_block(self, block: _FakeBlock) -> bool:
        return False


class _ClockRecordingIntegration(RetentionRuntimeIntegration):
    def __init__(self, manager: RetentionManager) -> None:
        super().__init__(manager)
        self.timestamps: list[float] = []

    def apply_pressure(self, **kwargs: Any) -> RetentionPressureResult:
        self.timestamps.append(kwargs["timestamp"])
        return RetentionPressureResult((7,), None)

    def observe_native_eviction(self, block_id: object) -> None:
        return None


@dataclass
class _FixedClock:
    value: object
    reads: int = 0

    def now(self) -> object:
        self.reads += 1
        return self.value


class _ExplodingClock:
    def now(self) -> float:
        raise AssertionError("NATIVE mode must not read the clock")


def _install_fake_vllm_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    vllm = ModuleType("vllm")
    v1 = ModuleType("vllm.v1")
    core = ModuleType("vllm.v1.core")
    block_pool = ModuleType("vllm.v1.core.block_pool")
    kv_cache_utils = ModuleType("vllm.v1.core.kv_cache_utils")
    block_pool.BlockPool = _FakeBlockPool
    kv_cache_utils.FreeKVCacheBlockQueue = _FakeQueue
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.v1", v1)
    monkeypatch.setitem(sys.modules, "vllm.v1.core", core)
    monkeypatch.setitem(sys.modules, "vllm.v1.core.block_pool", block_pool)
    monkeypatch.setitem(
        sys.modules,
        "vllm.v1.core.kv_cache_utils",
        kv_cache_utils,
    )


@pytest.fixture
def hook_environment(monkeypatch: pytest.MonkeyPatch):
    _install_fake_vllm_modules(monkeypatch)
    original_popleft = _FakeQueue.popleft_n
    original_evict = _FakeBlockPool._maybe_evict_cached_block
    original_queue_blocks = observer._queue_blocks
    _FakeQueue._kvopt_policy_installed = False
    observer._queue_blocks = lambda queue: [_FakeBlock(7)]
    yield
    _FakeQueue.popleft_n = original_popleft
    _FakeBlockPool._maybe_evict_cached_block = original_evict
    observer._queue_blocks = original_queue_blocks
    _FakeQueue._kvopt_policy_installed = False


def test_retention_hook_uses_injected_clock_for_pressure_timestamp(
    hook_environment,
) -> None:
    clock = FakeClock(12.5)
    assert isinstance(clock, Clock)
    manager = RetentionManager(clock)
    integration = _ClockRecordingIntegration(manager)

    observer.install_retention_hook(
        mode=RetentionMode.SHADOW,
        integration=integration,
        clock=clock,
    )
    _FakeQueue().popleft_n(1)
    clock.set(21.0)
    _FakeQueue().popleft_n(1)

    assert integration.timestamps == [12.5, 21.0]


@pytest.mark.parametrize("invalid", [True, -1.0, math.nan, math.inf, -math.inf])
def test_retention_hook_rejects_invalid_clock_values_at_pressure_boundary(
    hook_environment,
    invalid: object,
) -> None:
    clock = _FixedClock(invalid)
    manager = RetentionManager(FakeClock())
    integration = _ClockRecordingIntegration(manager)

    observer.install_retention_hook(
        mode=RetentionMode.SHADOW,
        integration=integration,
        clock=clock,
    )

    with pytest.raises((TypeError, ValueError)):
        _FakeQueue().popleft_n(1)

    assert clock.reads == 1
    assert integration.timestamps == []


def test_native_mode_does_not_read_injected_clock(hook_environment) -> None:
    integration = _ClockRecordingIntegration(RetentionManager(FakeClock()))

    observer.install_retention_hook(
        mode=RetentionMode.NATIVE,
        integration=integration,
        clock=_ExplodingClock(),
    )
