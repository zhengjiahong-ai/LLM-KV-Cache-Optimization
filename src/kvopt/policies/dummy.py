"""Non-experimental policy used only to make the scaffold executable."""

from collections.abc import Sequence

from kvopt.kv_cache.policy import EvictionPolicy
from kvopt.kv_cache.state import CacheState


class DummyEvictionPolicy(EvictionPolicy):
    """Select lexicographically smallest IDs for repository smoke testing.

    This policy exists only for repository smoke testing.
    It is not an experimental baseline.
    """

    def select_victims(
        self, cache_state: CacheState, required_blocks: int, current_time: float
    ) -> Sequence[str]:
        del current_time
        selected: list[str] = []
        released = 0
        for request in sorted(cache_state.requests, key=lambda item: item.request_id):
            selected.append(request.request_id)
            released += request.num_blocks
            if released >= required_blocks:
                break
        return selected
