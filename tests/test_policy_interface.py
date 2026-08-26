from dataclasses import FrozenInstanceError

import pytest

from kvopt.kv_cache.state import CacheState, RequestCacheState
from kvopt.policies.dummy import DummyEvictionPolicy


def test_dummy_policy_returns_enough_deterministic_victims() -> None:
    state = CacheState(5, 0, (RequestCacheState("b", 1, 16, 1.0), RequestCacheState("a", 2, 32, 2.0)))
    assert DummyEvictionPolicy().select_victims(state, 2, 3.0) == ["a"]


def test_cache_state_is_immutable() -> None:
    state = CacheState(1, 1, ())
    with pytest.raises(FrozenInstanceError):
        state.free_blocks = 0  # type: ignore[misc]
