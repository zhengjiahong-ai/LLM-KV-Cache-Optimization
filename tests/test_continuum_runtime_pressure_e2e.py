from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest

from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    FakeClock,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    RetentionEntryKey,
    RetentionMode,
    TurnFinished,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.runtime.vllm.observer import install_retention_hook
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration


@dataclass
class _Block:
    block_id: int
    block_hash: object | None
    ref_cnt: int = 0
    prev_free_block: _Block | None = None
    next_free_block: _Block | None = None


class _Queue:
    _kvopt_policy_installed = False

    def __init__(self, blocks: list[_Block]) -> None:
        self._blocks = list(blocks)
        self.num_free_blocks = len(blocks)
        self.popleft_calls = 0
        self.remove_calls: list[_Block] = []
        self.fake_free_list_head = _Block(-1, None)
        self.fake_free_list_tail = _Block(-1, None)
        self.fake_free_list_head.next_free_block = self.fake_free_list_tail
        self.fake_free_list_tail.prev_free_block = self.fake_free_list_head
        for block in blocks:
            self._append(block)

    def _append(self, block: _Block) -> None:
        previous = self.fake_free_list_tail.prev_free_block
        assert previous is not None
        previous.next_free_block = block
        block.prev_free_block = previous
        block.next_free_block = self.fake_free_list_tail
        self.fake_free_list_tail.prev_free_block = block

    def _detach(self, block: _Block) -> None:
        previous = block.prev_free_block
        following = block.next_free_block
        assert previous is not None
        assert following is not None
        previous.next_free_block = following
        following.prev_free_block = previous
        block.prev_free_block = None
        block.next_free_block = None
        self._blocks.remove(block)
        self.num_free_blocks -= 1

    def popleft_n(self, count: int) -> list[_Block]:
        self.popleft_calls += 1
        selected = list(self._blocks[:count])
        for block in selected:
            self._detach(block)
        return selected

    def remove(self, block: _Block) -> None:
        self.remove_calls.append(block)
        self._detach(block)


class _Pool:
    def _maybe_evict_cached_block(self, _block: _Block) -> bool:
        return False


class _Provider:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def estimate(self, _token_count: int) -> tuple[float, InputProvenance]:
        self.calls.append(_token_count)
        return 0.25, InputProvenance(InputSource.APPROXIMATED, "test profile")


class _RecordingIntegration:
    def __init__(self, manager: Any) -> None:
        self.delegate = RetentionRuntimeIntegration(manager)
        self.pressure_timestamps: list[float] = []

    def apply_pressure(self, **kwargs: Any) -> Any:
        self.pressure_timestamps.append(kwargs["timestamp"])
        return self.delegate.apply_pressure(**kwargs)

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        self.delegate.observe_native_eviction(block_id)


@pytest.fixture
def fake_vllm(monkeypatch: pytest.MonkeyPatch):
    vllm = ModuleType("vllm")
    v1 = ModuleType("vllm.v1")
    core = ModuleType("vllm.v1.core")
    block_pool = ModuleType("vllm.v1.core.block_pool")
    kv_cache_utils = ModuleType("vllm.v1.core.kv_cache_utils")
    block_pool.BlockPool = _Pool
    kv_cache_utils.FreeKVCacheBlockQueue = _Queue
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.v1", v1)
    monkeypatch.setitem(sys.modules, "vllm.v1.core", core)
    monkeypatch.setitem(sys.modules, "vllm.v1.core.block_pool", block_pool)
    monkeypatch.setitem(
        sys.modules,
        "vllm.v1.core.kv_cache_utils",
        kv_cache_utils,
    )
    original_popleft = _Queue.popleft_n
    original_evict = _Pool._maybe_evict_cached_block
    _Queue._kvopt_policy_installed = False
    yield
    _Queue.popleft_n = original_popleft
    _Queue._kvopt_policy_installed = False
    _Pool._maybe_evict_cached_block = original_evict


def test_runtime_created_retention_drives_controlled_vllm_pressure(
    fake_vllm,
) -> None:
    program_id = ProgramIdentity("program-a")
    request_id = RequestIdentity("request-1")
    prefix_id = PrefixIdentity("opaque-prefix")
    clock = FakeClock()
    provider = _Provider()
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=provider,
        default_ttl_seconds=7.0,
    )
    integration = _RecordingIntegration(runtime.retention)

    clock.set(0.0)
    runtime.handle(RequestArrived(program_id, request_id, 0.0))
    runtime.handle(RequestAdmitted(program_id, request_id, 0.0))
    runtime.record_prefill_context_token_count(
        PrefillContextTokenCountRecord(
            program_id,
            request_id,
            prefix_id,
            128,
            InputProvenance(InputSource.OBSERVED),
        )
    )
    clock.set(1.0)
    runtime.handle(
        BlocksObserved(
            program_id,
            request_id,
            prefix_id,
            (BlockIdentity(7),),
            1.0,
        )
    )
    runtime.handle(TurnFinished(program_id, request_id, 1.0, False, "search"))
    assert provider.calls == [128]

    key = RetentionEntryKey(program_id, prefix_id)
    entry = runtime.retention.snapshot(key)
    assert entry is not None
    assert entry.protected is True

    install_retention_hook(
        mode=RetentionMode.CONTROLLED,
        integration=integration,
        clock=clock,
    )
    protected = _Block(7, object())
    unhashed = _Block(8, None)
    queue = _Queue([protected, unhashed])

    clock.set(2.5)
    result = queue.popleft_n(2)

    assert integration.pressure_timestamps == [2.5]
    assert result == [unhashed, protected]
    assert result[0] is unhashed
    assert result[1] is protected
    assert queue.popleft_calls == 0
    assert queue.remove_calls == [unhashed, protected]
    assert queue._blocks == []
    entry = runtime.retention.snapshot(key)
    assert entry is not None
    assert entry.protected is False
