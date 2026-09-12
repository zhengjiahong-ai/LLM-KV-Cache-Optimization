"""Policy contract for real vLLM block-level eviction."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from kvopt.continuum.selection import EligibilityPreparation

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


class RetentionAwareLRUAdapter(EvictionPolicyAdapter):
    """Select victims from a validated retention-aware eligibility plan."""

    def __init__(self, preparation: EligibilityPreparation) -> None:
        if not isinstance(preparation, EligibilityPreparation):
            raise TypeError("preparation must be EligibilityPreparation")
        self._preparation = preparation

    def select_victims(
        self,
        candidates: Sequence[EvictionCandidate],
        context: EvictionContext,
    ) -> Sequence[int]:
        if context.required_blocks <= 0:
            return []
        expected_ids = self._preparation.original_block_order
        actual_ids = tuple(candidate.block_id for candidate in candidates)
        if actual_ids != tuple(block_id.block_id for block_id in expected_ids):
            raise ValueError("candidates must match the preparation queue")
        eligible_ids = self._preparation.virtual_eligible_order
        limit = min(context.required_blocks, len(eligible_ids))
        return [block_id.block_id for block_id in eligible_ids[:limit]]
