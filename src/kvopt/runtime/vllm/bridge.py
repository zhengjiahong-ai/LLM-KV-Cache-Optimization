"""Bridge between vLLM free-queue snapshots and project eviction policies."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import time
from typing import Protocol

from .adapter import EvictionPolicyAdapter
from .types import EvictionCandidate, EvictionContext


class VLLMBlockLike(Protocol):
    """Minimal shape required from a vLLM KV-cache block snapshot."""

    block_id: int
    ref_cnt: int
    block_hash: object | None


@dataclass(slots=True)
class VLLMEvictionBridge:
    """Convert vLLM block state into policy input and validate selections.

    This class does not evict blocks itself. The caller remains responsible for
    handing the validated block IDs back to the existing vLLM allocation and
    eviction path.
    """

    policy: EvictionPolicyAdapter
    total_blocks: int

    def build_candidates(self, blocks: Iterable[VLLMBlockLike]) -> list[EvictionCandidate]:
        """Snapshot free-queue blocks in their current native LRU order."""
        return [
            EvictionCandidate(
                block_id=block.block_id,
                ref_cnt=block.ref_cnt,
                has_block_hash=block.block_hash is not None,
                lru_rank=lru_rank,
            )
            for lru_rank, block in enumerate(blocks)
        ]

    def select_blocks(
        self,
        blocks: Iterable[VLLMBlockLike],
        required_blocks: int,
        *,
        free_blocks: int | None = None,
        timestamp: float | None = None,
    ) -> list[int]:
        """Run the configured policy on an immutable snapshot of candidates."""
        candidates = self.build_candidates(blocks)
        context = EvictionContext(
            required_blocks=required_blocks,
            free_blocks=len(candidates) if free_blocks is None else free_blocks,
            total_blocks=self.total_blocks,
            timestamp=time.monotonic() if timestamp is None else timestamp,
        )
        selected = list(self.policy.select_victims(candidates, context))
        self._validate_selection(candidates, selected, required_blocks)
        return selected

    @staticmethod
    def _validate_selection(
        candidates: Sequence[EvictionCandidate],
        selected: Sequence[int],
        required_blocks: int,
    ) -> None:
        if required_blocks < 0:
            raise ValueError("required_blocks must be non-negative")
        if len(selected) < min(required_blocks, len(candidates)):
            raise ValueError("policy returned too few victim blocks")
        if len(selected) != len(set(selected)):
            raise ValueError("policy returned duplicate victim block IDs")

        candidate_ids = {candidate.block_id for candidate in candidates}
        unknown = [block_id for block_id in selected if block_id not in candidate_ids]
        if unknown:
            raise ValueError(f"policy returned non-candidate block IDs: {unknown}")
