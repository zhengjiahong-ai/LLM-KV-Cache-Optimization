"""Cost-aware forced-unpin victim selection for the Phase 2 spike.

The proposed method overrides only the protected-entry release ranking of
the frozen Continuum pressure coordinator. TTL estimation, retention state,
lazy expiry, tier assignment, and native block bookkeeping are inherited
unchanged, so the frozen baseline semantics of ``docs/baseline-freeze.md``
remain intact whenever this coordinator is not explicitly selected.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.continuum.selection import RetentionEntryKey
from kvopt.continuum.snapshots import RetentionEntrySnapshot, TTLHistoryMode
from kvopt.continuum.types import (
    BlockIdentity,
    _as_non_negative_finite_float,
)


def _empirical_cdf(samples: tuple[float, ...], value: float) -> float:
    """Fraction of history samples at or below ``value``."""
    if not samples:
        raise ValueError("empirical CDF requires at least one sample")
    return sum(sample <= value for sample in samples) / len(samples)


@dataclass(frozen=True, slots=True)
class ForcedUnpinConfig:
    """Weights of the request-level expected-loss score."""

    lambda_queue_seconds: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "lambda_queue_seconds",
            _as_non_negative_finite_float(
                self.lambda_queue_seconds, "lambda_queue_seconds"
            ),
        )


def estimate_conditional_return_probability(
    entry: RetentionEntrySnapshot, timestamp: float
) -> float:
    """P(gap ends within the remaining retention window | still running).

    Reuses the exact duration history the frozen TTL estimator selected for
    the entry: tool-specific samples for tool-specific decisions, global
    samples otherwise, and full uncertainty (1.0) for cold-start entries
    with no usable history.
    """
    now = _as_non_negative_finite_float(timestamp, "timestamp")
    decision = entry.ttl_decision
    ttl_input = decision.ttl_input
    if decision.history_mode is TTLHistoryMode.TOOL_SPECIFIC:
        samples = ttl_input.tool_server_gap_samples_seconds
    else:
        samples = ttl_input.global_server_gap_samples_seconds
    if not samples:
        return 1.0
    elapsed = now - decision.decision_timestamp
    remaining = decision.deadline_timestamp - now
    if elapsed < 0.0 or remaining <= 0.0:
        return 0.0
    cdf_elapsed = _empirical_cdf(samples, elapsed)
    survived = 1.0 - cdf_elapsed
    if survived <= 0.0:
        return 0.0
    cdf_deadline = _empirical_cdf(samples, elapsed + remaining)
    return (cdf_deadline - cdf_elapsed) / survived


def estimate_eviction_loss(
    entry: RetentionEntrySnapshot,
    timestamp: float,
    config: ForcedUnpinConfig | None = None,
) -> float:
    """Expected per-block eviction loss of releasing one protected entry.

    ``score(r) = P_return(r) * (C_recompute(r) + lambda * C_queue(r)) / Blocks(r)``

    Lower scores are released first. All terms come from the entry's frozen
    TTL input snapshot; no new runtime state is introduced. Entries with no
    observed blocks score ``+inf`` so they are released only as a last
    resort.
    """
    if not isinstance(entry, RetentionEntrySnapshot):
        raise TypeError("entry must be RetentionEntrySnapshot")
    now = _as_non_negative_finite_float(timestamp, "timestamp")
    weights = ForcedUnpinConfig() if config is None else config
    if not isinstance(weights, ForcedUnpinConfig):
        raise TypeError("config must be ForcedUnpinConfig")
    block_count = len(entry.block_ids)
    if block_count == 0:
        return math.inf
    ttl_input = entry.ttl_decision.ttl_input
    reuse_cost = (
        ttl_input.prefill_reload_seconds
        + weights.lambda_queue_seconds * ttl_input.queue_delay_t_seconds
    )
    probability = estimate_conditional_return_probability(entry, now)
    return probability * reuse_cost / block_count


class CostAwareForcedUnpinCoordinator(RetentionAwareSelectionCoordinator):
    """Pressure-release ranking by lowest expected per-block eviction loss.

    The frozen baseline ranks release candidates by earliest retention
    deadline (plus native-LRU and identity tie-breakers). This coordinator
    ranks them by the cost-aware score instead and keeps deadline and stable
    identity as deterministic tie-breakers. It is bound to the
    single-threaded scheduler hook path: ``prepare`` binds the decision
    timestamp for the duration of one call.
    """

    def __init__(self, config: ForcedUnpinConfig | None = None) -> None:
        if config is not None and not isinstance(config, ForcedUnpinConfig):
            raise TypeError("config must be ForcedUnpinConfig or None")
        self._config = ForcedUnpinConfig() if config is None else config
        self._prepare_timestamp: float | None = None

    def prepare(
        self,
        candidates: Sequence[object],
        retention_entries: Sequence[RetentionEntrySnapshot],
        *,
        required_blocks: int,
        timestamp: float,
    ) -> object:
        now = _as_non_negative_finite_float(timestamp, "timestamp")
        self._prepare_timestamp = now
        try:
            return super().prepare(
                candidates,
                retention_entries,
                required_blocks=required_blocks,
                timestamp=timestamp,
            )
        finally:
            self._prepare_timestamp = None

    def _release_sort_key(
        self,
        key: RetentionEntryKey,
        entry: RetentionEntrySnapshot,
        states: Sequence[object],
        entries: dict[RetentionEntryKey, RetentionEntrySnapshot],
        entries_by_block: dict[BlockIdentity, tuple[RetentionEntryKey, ...]],
        released_keys: set[RetentionEntryKey],
    ) -> tuple[float, float, tuple[str, str]]:
        now = self._prepare_timestamp
        if now is None:
            raise RuntimeError("release ranking requires an active prepare call")
        score = estimate_eviction_loss(entry, now, self._config)
        return (score, entry.deadline_timestamp, key.sort_key)
