from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pytest

from kvopt.continuum import BlockIdentity, RetentionMode
from kvopt.runtime.vllm.observer import install_retention_hook


@dataclass
class _FakeBlock:
    block_id: int
    ref_cnt: int = 0
    block_hash: object | None = object()
    prev_free_block: _FakeBlock | None = None
    next_free_block: _FakeBlock | None = None


class _FakeFreeKVCacheBlockQueue:
    _kvopt_policy_installed = False

    def __init__(self, blocks: list[_FakeBlock]) -> None:
        self._blocks = list(blocks)
        self.num_free_blocks = len(blocks)
        self.popleft_calls = 0
        self.last_native_result: list[_FakeBlock] | None = None
        self.remove_calls: list[_FakeBlock] = []
        self.fake_free_list_head = _FakeBlock(-1, block_hash=None)
        self.fake_free_list_tail = _FakeBlock(-1, block_hash=None)
        self.fake_free_list_head.next_free_block = self.fake_free_list_tail
        self.fake_free_list_tail.prev_free_block = self.fake_free_list_head
        for block in blocks:
            self._append(block)

    def _append(self, block: _FakeBlock) -> None:
        previous = self.fake_free_list_tail.prev_free_block
        assert previous is not None
        previous.next_free_block = block
        block.prev_free_block = previous
        block.next_free_block = self.fake_free_list_tail
        self.fake_free_list_tail.prev_free_block = block

    def _detach(self, block: _FakeBlock) -> None:
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

    def popleft_n(self, count: int) -> list[_FakeBlock]:
        self.popleft_calls += 1
        selected = list(self._blocks[:count])
        for block in selected:
            self._detach(block)
        self.last_native_result = selected
        return selected

    def remove(self, block: _FakeBlock) -> None:
        self.remove_calls.append(block)
        self._detach(block)


class _NativeEvictionFailure(RuntimeError):
    pass


class _FakeBlockPool:
    behavior = "evicted"
    failure: BaseException | None = None

    def _maybe_evict_cached_block(self, block: _FakeBlock) -> bool:
        if type(self).behavior == "error":
            failure = type(self).failure
            if failure is None:
                failure = _NativeEvictionFailure("native cleanup failed")
            raise failure
        if type(self).behavior == "evicted":
            block.block_hash = None
            return True
        return False


@dataclass
class _HookResult:
    selected_block_ids: tuple[int, ...]


@dataclass
class _FakeIntegration:
    result: _HookResult = field(default_factory=lambda: _HookResult(()))
    failure: BaseException | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    eviction_calls: list[BlockIdentity] = field(default_factory=list)
    committed: bool = False

    def apply_pressure(self, **kwargs: Any) -> _HookResult:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        if kwargs["mode"] is RetentionMode.CONTROLLED:
            self.committed = True
            kwargs["remove_selected"](self.result.selected_block_ids)
        return self.result

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        self.eviction_calls.append(block_id)


def _install_fake_vllm_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    vllm = ModuleType("vllm")
    v1 = ModuleType("vllm.v1")
    core = ModuleType("vllm.v1.core")
    block_pool = ModuleType("vllm.v1.core.block_pool")
    kv_cache_utils = ModuleType("vllm.v1.core.kv_cache_utils")
    block_pool.BlockPool = _FakeBlockPool
    kv_cache_utils.FreeKVCacheBlockQueue = _FakeFreeKVCacheBlockQueue
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
    original_popleft = _FakeFreeKVCacheBlockQueue.popleft_n
    original_evict = _FakeBlockPool._maybe_evict_cached_block
    _FakeFreeKVCacheBlockQueue._kvopt_policy_installed = False
    _FakeBlockPool.behavior = "evicted"
    _FakeBlockPool.failure = None
    yield original_popleft, original_evict
    _FakeFreeKVCacheBlockQueue.popleft_n = original_popleft
    _FakeFreeKVCacheBlockQueue._kvopt_policy_installed = False
    _FakeBlockPool._maybe_evict_cached_block = original_evict
    _FakeBlockPool.behavior = "evicted"
    _FakeBlockPool.failure = None


def _queue_state(queue: _FakeFreeKVCacheBlockQueue) -> tuple[Any, ...]:
    blocks: list[_FakeBlock] = []
    current = queue.fake_free_list_head.next_free_block
    while current is not queue.fake_free_list_tail:
        assert current is not None
        blocks.append(current)
        current = current.next_free_block
    links = tuple(
        (
            block.block_id,
            None if block.prev_free_block is None else block.prev_free_block.block_id,
            None if block.next_free_block is None else block.next_free_block.block_id,
        )
        for block in blocks
    )
    return tuple(block.block_id for block in blocks), queue.num_free_blocks, links


def _blocks(*ids: int) -> list[_FakeBlock]:
    return [_FakeBlock(block_id) for block_id in ids]


def test_native_mode_leaves_original_popleft_unhooked(
    hook_environment,
) -> None:
    original_popleft, _ = hook_environment
    integration = _FakeIntegration()

    install_retention_hook(mode=RetentionMode.NATIVE, integration=integration)

    assert _FakeFreeKVCacheBlockQueue.popleft_n is original_popleft
    assert integration.calls == []
    assert integration.committed is False


def test_shadow_snapshots_complete_queue_then_delegates_original_popleft(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8,)))
    protected, eligible, cached = _blocks(7, 8, 9)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible, cached])

    install_retention_hook(mode=RetentionMode.SHADOW, integration=integration)
    result = queue.popleft_n(2)

    assert len(integration.calls) == 1
    assert tuple(integration.calls[0]["blocks"]) == (protected, eligible, cached)
    assert integration.calls[0]["required_blocks"] == 2
    assert result is queue.last_native_result
    assert result == [protected, eligible]
    assert queue.remove_calls == []


def test_hook_installation_is_idempotent_without_double_wrapping(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8,)))

    install_retention_hook(mode=RetentionMode.SHADOW, integration=integration)
    wrapped_popleft = _FakeFreeKVCacheBlockQueue.popleft_n
    wrapped_evict = _FakeBlockPool._maybe_evict_cached_block

    install_retention_hook(mode=RetentionMode.SHADOW, integration=integration)

    assert _FakeFreeKVCacheBlockQueue.popleft_n is wrapped_popleft
    assert _FakeBlockPool._maybe_evict_cached_block is wrapped_evict

    _, eligible = _blocks(7, 8)
    queue = _FakeFreeKVCacheBlockQueue([eligible])
    queue.popleft_n(1)
    assert len(integration.calls) == 1

    block = _FakeBlock(9)
    assert _FakeBlockPool()._maybe_evict_cached_block(block) is True
    assert integration.eviction_calls == [BlockIdentity(9)]


def test_controlled_removes_only_final_validated_block_objects(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8, 7)))
    protected, eligible, unselected = _blocks(7, 8, 9)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible, unselected])

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    result = queue.popleft_n(2)

    assert result == [eligible, protected]
    assert result[0] is eligible
    assert result[1] is protected
    assert queue.remove_calls == [eligible, protected]
    assert queue._blocks == [unselected]


def test_controlled_does_not_call_original_popleft(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8, 7)))
    protected, eligible = _blocks(7, 8)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible])

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    queue.popleft_n(2)

    assert queue.popleft_calls == 0
    assert queue.remove_calls == [eligible, protected]


def test_controlled_protected_head_does_not_block_later_eligible_block(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8,)))
    protected, eligible = _blocks(7, 8)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible])

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    result = queue.popleft_n(1)

    assert result == [eligible]
    assert queue._blocks == [protected]
    assert queue.remove_calls == [eligible]


def test_pre_removal_failure_leaves_queue_and_retention_unchanged(
    hook_environment,
) -> None:
    failure = RuntimeError("planning failed")
    integration = _FakeIntegration(failure=failure)
    protected, eligible = _blocks(7, 8)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible])
    before = _queue_state(queue)

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    with pytest.raises(RuntimeError) as raised:
        queue.popleft_n(1)

    assert raised.value is failure
    assert _queue_state(queue) == before
    assert queue.popleft_calls == 0
    assert queue.remove_calls == []
    assert integration.committed is False


def test_final_id_mapping_failure_is_atomic_before_queue_remove(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8, 999)))
    protected, eligible = _blocks(7, 8)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible])
    before = _queue_state(queue)

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    with pytest.raises(ValueError, match="block ID"):
        queue.popleft_n(2)

    assert _queue_state(queue) == before
    assert queue.remove_calls == []
    assert integration.eviction_calls == []
    assert integration.committed is True


def test_post_removal_partial_failure_does_not_rollback_or_observe_eviction(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8, 7)))
    protected, eligible = _blocks(7, 8)
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible])
    failure = RuntimeError("remove failed")

    original_remove = queue.remove

    def remove_with_failure(block: _FakeBlock) -> None:
        if block is protected:
            raise failure
        original_remove(block)

    queue.remove = remove_with_failure  # type: ignore[method-assign]
    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)

    with pytest.raises(RuntimeError) as raised:
        queue.popleft_n(2)

    assert raised.value is failure
    assert queue._blocks == [protected]
    assert protected.prev_free_block is not None
    assert eligible.prev_free_block is None
    assert integration.committed is True
    assert integration.eviction_calls == []


def test_actual_native_cached_eviction_triggers_stale_cleanup_after_native(
    hook_environment,
) -> None:
    integration = _FakeIntegration()
    block = _FakeBlock(7)
    events: list[str] = []
    original = _FakeBlockPool._maybe_evict_cached_block

    def native(pool: _FakeBlockPool, value: _FakeBlock) -> bool:
        events.append("native")
        return original(pool, value)

    _FakeBlockPool._maybe_evict_cached_block = native
    original_observe = integration.observe_native_eviction

    def observe(block_id: BlockIdentity) -> None:
        events.append("project")
        original_observe(block_id)

    integration.observe_native_eviction = observe  # type: ignore[method-assign]
    install_retention_hook(mode=RetentionMode.SHADOW, integration=integration)

    result = _FakeBlockPool()._maybe_evict_cached_block(block)

    assert result is True
    assert events == ["native", "project"]
    assert integration.eviction_calls == [BlockIdentity(7)]


def test_non_eviction_does_not_clear_stale_association(hook_environment) -> None:
    integration = _FakeIntegration()
    _FakeBlockPool.behavior = "not_evicted"
    block = _FakeBlock(7)

    install_retention_hook(mode=RetentionMode.SHADOW, integration=integration)
    result = _FakeBlockPool()._maybe_evict_cached_block(block)

    assert result is False
    assert integration.eviction_calls == []


def test_native_eviction_exception_does_not_fabricate_observation(
    hook_environment,
) -> None:
    integration = _FakeIntegration()
    _FakeBlockPool.behavior = "error"
    failure = _NativeEvictionFailure("sentinel")
    _FakeBlockPool.failure = failure
    block = _FakeBlock(7)

    install_retention_hook(mode=RetentionMode.SHADOW, integration=integration)
    with pytest.raises(_NativeEvictionFailure) as raised:
        _FakeBlockPool()._maybe_evict_cached_block(block)

    assert raised.value is failure
    assert integration.eviction_calls == []


def test_hook_does_not_mutate_ref_count_or_hash(hook_environment) -> None:
    integration = _FakeIntegration(_HookResult((8,)))
    protected, eligible = _blocks(7, 8)
    protected.ref_cnt = 3
    protected.block_hash = b"protected"
    eligible.ref_cnt = 4
    eligible.block_hash = b"eligible"
    queue = _FakeFreeKVCacheBlockQueue([protected, eligible])

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    queue.popleft_n(1)

    assert protected.ref_cnt == 3
    assert protected.block_hash == b"protected"
    assert eligible.ref_cnt == 4
    assert eligible.block_hash == b"eligible"


def test_controlled_removal_preserves_unselected_native_queue_order(
    hook_environment,
) -> None:
    integration = _FakeIntegration(_HookResult((8, 10)))
    first, selected_first, middle, selected_second = _blocks(7, 8, 9, 10)
    queue = _FakeFreeKVCacheBlockQueue(
        [first, selected_first, middle, selected_second]
    )

    install_retention_hook(mode=RetentionMode.CONTROLLED, integration=integration)
    queue.popleft_n(2)

    assert queue._blocks == [first, middle]
    assert [block.block_id for block in queue._blocks] == [7, 9]
