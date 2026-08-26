"""Plugin contract for cache eviction policies."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from kvopt.kv_cache.state import CacheState


class EvictionPolicy(ABC):
    """Choose request-level cache victims from an immutable state snapshot."""

    @abstractmethod
    def select_victims(
        self, cache_state: CacheState, required_blocks: int, current_time: float
    ) -> Sequence[str]:
        """Return request IDs whose released blocks satisfy ``required_blocks``."""
