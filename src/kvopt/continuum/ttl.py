"""Pure dynamic-TTL calculations for the Phase 1B baseline."""

from __future__ import annotations

import math
from typing import Protocol

from .snapshots import TTLDecision, TTLHistoryMode, TTLInput
from .types import InputProvenance


class PrefillReloadProvider(Protocol):
    """Minimal boundary for a future offline PrefillReload profile."""

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        """Return the profiled reload seconds and its provenance."""


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def compute_default_ttl_seconds(profile_seconds: float) -> float:
    """Compute the frozen one-second-mean cold-start TTL concretization."""
    if isinstance(profile_seconds, bool) or not isinstance(profile_seconds, (int, float)):
        raise TypeError("profile_seconds must be a real number")
    profile = float(profile_seconds)
    if not math.isfinite(profile) or profile <= 0.0:
        raise ValueError("profile_seconds must be positive and finite")
    return max(0.0, math.log(profile))


def _empirical_cdf(samples: tuple[float, ...], candidate: float) -> float:
    return sum(sample <= candidate for sample in samples) / len(samples)


def _select_history(
    ttl_input: TTLInput, duration_history_threshold: int
) -> tuple[TTLHistoryMode, tuple[float, ...], str | None]:
    global_samples = ttl_input.global_server_gap_samples_seconds
    if len(global_samples) <= duration_history_threshold:
        return (
            TTLHistoryMode.COLD_START,
            (),
            "insufficient global server gap history",
        )
    if ttl_input.next_tool_type is None:
        return (
            TTLHistoryMode.GLOBAL,
            global_samples,
            "next_tool_type unavailable; using global duration history",
        )
    tool_samples = ttl_input.tool_server_gap_samples_seconds
    if len(tool_samples) <= duration_history_threshold:
        return TTLHistoryMode.GLOBAL, global_samples, None
    return TTLHistoryMode.TOOL_SPECIFIC, tool_samples, None


def _choose_empirical_ttl(
    samples: tuple[float, ...],
    queue_delay_seconds: float,
    eta: float,
    prefill_reload_seconds: float,
) -> float:
    candidates = sorted({0.0, *samples})
    benefit = queue_delay_seconds * eta + prefill_reload_seconds
    best_ttl = candidates[0]
    best_score = _empirical_cdf(samples, best_ttl) * benefit - best_ttl
    for candidate in candidates[1:]:
        score = _empirical_cdf(samples, candidate) * benefit - candidate
        if score > best_score:
            best_ttl = candidate
            best_score = score
    return best_ttl


def estimate_ttl(
    ttl_input: TTLInput, *, duration_history_threshold: int = 100
) -> TTLDecision:
    """Calculate one TTL decision from an immutable ``TTLInput``."""
    if not isinstance(ttl_input, TTLInput):
        raise TypeError("ttl_input must be TTLInput")
    threshold = _require_positive_int(
        duration_history_threshold, "duration_history_threshold"
    )
    mode, samples, reason = _select_history(ttl_input, threshold)
    if mode is TTLHistoryMode.COLD_START:
        ttl_seconds = ttl_input.default_ttl_seconds
    else:
        ttl_seconds = _choose_empirical_ttl(
            samples,
            ttl_input.queue_delay_t_seconds,
            ttl_input.eta,
            ttl_input.prefill_reload_seconds,
        )
    return TTLDecision(ttl_input, ttl_seconds, mode, reason)
