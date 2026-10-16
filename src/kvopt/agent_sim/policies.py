"""Victim-selection policies for the Phase 2F simulator.

Every policy receives the *complete* free queue as candidates (with native
``lru_rank``) plus retention eligibility tiers, and returns the ordered victim
block IDs. Policies never mutate pool state; the engine executes the choice.

Fidelity notes:

* A0/A1 use the **frozen** ``NativeLRUAdapter`` / ``RetentionAwareLRUAdapter``
  from ``kvopt.runtime.vllm.adapter`` so the native and retention baselines are
  bit-identical to the production path.
* ``InBandTailFirstPolicy`` is ``simulation candidate v0`` (see
  ``docs/phase2f-m4-combined-algorithm-design.md`` §2). It relies on
  ``depth``/``band`` signals that are simulation-observable only; when those
  signals are absent it degrades to native LRU ordering exactly.
* ``OraclePolicy`` uses future trace knowledge and is a research upper-bound
  reference only. It must never be labelled ``Ours-Evict``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from kvopt.continuum.selection import EligibilityPreparation, EligibilityTier
from kvopt.runtime.vllm.adapter import NativeLRUAdapter, RetentionAwareLRUAdapter
from kvopt.runtime.vllm.types import EvictionCandidate, EvictionContext


@dataclass(frozen=True, slots=True)
class SimCandidate:
    """One free-queue block as seen by a policy at decision time."""

    block_id: int
    lru_rank: int
    has_block_hash: bool
    tier: EligibilityTier | None
    depth: int
    band_id: int
    band_hashless: bool
    band_pos: int
    content_id: str | None = None

    @property
    def eligible(self) -> bool:
        return self.tier is not None


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a policy may see for one victim-selection decision."""

    required_blocks: int
    free_blocks: int
    total_blocks: int
    timestamp: float
    decision_index: int
    request_id: str
    preparation: EligibilityPreparation | None = None
    future_index: dict[str, tuple[int, ...]] | None = None
    current_request_index: int | None = None


def validate_selection(
    candidates: Sequence[SimCandidate],
    selected: Sequence[int],
    required_blocks: int,
) -> None:
    """Legality gate: unique IDs, drawn from candidates, exact count."""
    candidate_ids = {candidate.block_id for candidate in candidates}
    if len(set(selected)) != len(selected):
        raise ValueError("policy selected duplicate block IDs")
    for block_id in selected:
        if block_id not in candidate_ids:
            raise ValueError("policy selected a non-candidate block")
    expected = min(required_blocks, len(candidates))
    if len(selected) != expected:
        raise ValueError(
            f"policy selected {len(selected)} blocks, expected {expected}"
        )


class NativeLRUPolicy:
    """A0: the frozen native adapter over the complete queue."""

    strategy_id = "A0_native_lru"

    def __init__(self) -> None:
        self._adapter = NativeLRUAdapter()

    def select(
        self,
        candidates: Sequence[SimCandidate],
        context: DecisionContext,
    ) -> tuple[int, ...]:
        if context.required_blocks <= 0:
            return ()
        frozen = [
            EvictionCandidate(
                block_id=candidate.block_id,
                ref_cnt=0,
                has_block_hash=candidate.has_block_hash,
                lru_rank=candidate.lru_rank,
            )
            for candidate in candidates
        ]
        frozen_context = EvictionContext(
            required_blocks=context.required_blocks,
            free_blocks=context.free_blocks,
            total_blocks=context.total_blocks,
            timestamp=context.timestamp,
        )
        selected = tuple(
            int(block_id)
            for block_id in self._adapter.select_victims(frozen, frozen_context)
        )
        validate_selection(candidates, selected, context.required_blocks)
        return selected


class RetentionNativePolicy:
    """A1: the frozen retention-aware adapter over the complete queue."""

    strategy_id = "A1_retention_native_lru"

    def select(
        self,
        candidates: Sequence[SimCandidate],
        context: DecisionContext,
    ) -> tuple[int, ...]:
        if context.required_blocks <= 0:
            return ()
        if context.preparation is None:
            raise ValueError("retention policy requires an eligibility preparation")
        frozen = [
            EvictionCandidate(
                block_id=candidate.block_id,
                ref_cnt=0,
                has_block_hash=candidate.has_block_hash,
                lru_rank=candidate.lru_rank,
            )
            for candidate in candidates
        ]
        frozen_context = EvictionContext(
            required_blocks=context.required_blocks,
            free_blocks=context.free_blocks,
            total_blocks=context.total_blocks,
            timestamp=context.timestamp,
        )
        adapter = RetentionAwareLRUAdapter(context.preparation)
        selected = tuple(
            int(block_id)
            for block_id in adapter.select_victims(frozen, frozen_context)
        )
        validate_selection(candidates, selected, context.required_blocks)
        return selected


@dataclass(frozen=True, slots=True)
class InBandTailFirstPolicy:
    """A2/A3: ``simulation candidate v0`` — in-band deep-first victim choice.

    Sort key (ascending)::

        retention on : (tier, band_min_rank, -depth, lru_rank)
        retention off: (band_min_rank, -depth, lru_rank)

    A *band* is one free event's queue run, keyed by ``(event_id, kind)``:
    hashless blocks are prepended to the queue head and hashed blocks appended
    to the tail (vLLM ``free_blocks`` semantics), so the two kinds are separate
    runs. ``band_min_rank`` orders bands exactly as the native queue does, so
    the cross-band allocation is native; only the direction *inside* a hashed
    band is reversed (deepest first), which preserves the shallow contiguous
    prefix. ``depth`` is the block's 1-based position on its prefix trie path
    (a content property, stable across slot reuse).

    Flags:

    * ``ignore_structure``: drop depth *and* band, order by ``lru_rank`` only
      (with retention: ``(tier, lru_rank)``). This is the documented safe
      degradation and is **exactly** native LRU order — asserted by tests.
    * ``constant_depth``: keep the band grouping but drop depth (diagnostic:
      isolates whether the gain comes from band structure alone).
    * ``reverse_direction``: flip the in-band direction (diagnostic arm D1).
    """

    strategy_id: str = "A2_ours_evict_candidate_v0"
    retention: bool = False
    ignore_structure: bool = False
    constant_depth: bool = False
    reverse_direction: bool = False

    def _key(self, candidate: SimCandidate, band_min_rank: dict[tuple[int, bool], int]):
        if self.ignore_structure:
            if self.retention:
                return (int(candidate.tier), candidate.lru_rank)
            return (candidate.lru_rank,)
        depth_sign = 1 if self.reverse_direction else -1
        if self.constant_depth:
            depth_sign = 0
        band_rank = band_min_rank.get(
            (candidate.band_id, candidate.band_hashless), candidate.lru_rank
        )
        if self.retention:
            return (
                int(candidate.tier),
                band_rank,
                depth_sign * candidate.depth,
                candidate.lru_rank,
            )
        return (band_rank, depth_sign * candidate.depth, candidate.lru_rank)

    def select(
        self,
        candidates: Sequence[SimCandidate],
        context: DecisionContext,
    ) -> tuple[int, ...]:
        if context.required_blocks <= 0:
            return ()
        eligible = [candidate for candidate in candidates if candidate.eligible]
        band_min_rank: dict[tuple[int, bool], int] = {}
        for candidate in eligible:
            band = (candidate.band_id, candidate.band_hashless)
            current = band_min_rank.get(band)
            if current is None or candidate.lru_rank < current:
                band_min_rank[band] = candidate.lru_rank
        ordered = sorted(eligible, key=lambda item: self._key(item, band_min_rank))
        selected = tuple(candidate.block_id for candidate in ordered[: context.required_blocks])
        validate_selection(candidates, selected, context.required_blocks)
        return selected


@dataclass(frozen=True, slots=True)
class OraclePolicy:
    """Belady-style oracle over the eligible set (research upper bound only).

    Evicts, in order: blocks whose content is never requested again, then
    blocks whose next use is furthest in the future. Ties break toward deeper
    blocks (less prefix damage) and then colder native rank. Uses the future
    trace; never a deployable policy.
    """

    strategy_id: str = "ORACLE_belady"

    def select(
        self,
        candidates: Sequence[SimCandidate],
        context: DecisionContext,
    ) -> tuple[int, ...]:
        if context.required_blocks <= 0:
            return ()
        if context.future_index is None or context.current_request_index is None:
            raise ValueError("oracle policy requires the future trace index")
        eligible = [candidate for candidate in candidates if candidate.eligible]
        current = context.current_request_index

        def next_use(content_id: str | None) -> int:
            if content_id is None:
                return 1 << 62  # hashless: no cached content, no future match
            uses = context.future_index.get(content_id, ())
            for index in uses:
                if index > current:
                    return index
            return 1 << 62

        def key(candidate: SimCandidate) -> tuple[int, int, int]:
            return (-next_use(candidate.content_id), -candidate.depth, candidate.lru_rank)

        ordered = sorted(eligible, key=key)
        selected = tuple(candidate.block_id for candidate in ordered[: context.required_blocks])
        validate_selection(candidates, selected, context.required_blocks)
        return selected
