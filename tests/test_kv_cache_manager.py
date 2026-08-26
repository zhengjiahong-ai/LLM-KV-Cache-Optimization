import pytest

from kvopt.kv_cache.manager import KVCacheManager
from kvopt.policies.dummy import DummyEvictionPolicy


def test_allocate_free_and_state() -> None:
    manager = KVCacheManager(4, 16, DummyEvictionPolicy())
    manager.allocate("r1", 2, 1.0, cached_tokens=32)
    state = manager.get_state()
    assert state.free_blocks == 2
    assert state.requests[0].cached_tokens == 32
    assert manager.free("r1") == 2
    assert manager.get_state().free_blocks == 4


def test_capacity_shortfall_calls_policy_and_evicts() -> None:
    manager = KVCacheManager(3, 16, DummyEvictionPolicy())
    manager.allocate("b", 2, 0.0)
    manager.allocate("a", 2, 1.0)
    assert manager.get_state().free_blocks == 1
    assert [state.request_id for state in manager.get_state().requests] == ["a"]


def test_rejects_allocation_larger_than_capacity() -> None:
    manager = KVCacheManager(3, 16, DummyEvictionPolicy())
    with pytest.raises(ValueError):
        manager.allocate("r1", 4, 0.0)
