"""Policy contract for real vLLM block-level eviction."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from .types import EvictionCandidate, EvictionContext


class EvictionPolicyAdapter(ABC):
    """Choose block-level victims without mutating vLLM cache state directly."""

    @abstractmethod
    def select_victims(
        self,
        candidates: Sequence[EvictionCandidate],
        context: EvictionContext,
    ) -> Sequence[int]:
        """Return candidate block IDs in eviction order.

        Implementations must return unique IDs drawn from ``candidates`` and
        must not mutate the underlying vLLM queue or block metadata.
        """


class NativeLRUAdapter(EvictionPolicyAdapter):
    """Reference policy matching the native vLLM free-queue LRU order."""

    def select_victims(
        self,
        candidates: Sequence[EvictionCandidate],
        context: EvictionContext,
    ) -> Sequence[int]:
        if context.required_blocks <= 0:
            return []

        ordered = sorted(candidates, key=lambda candidate: candidate.lru_rank)
        return [candidate.block_id for candidate in ordered[: context.required_blocks]]
