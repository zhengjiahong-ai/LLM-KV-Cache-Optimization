"""Prefill reload profiling orchestration.

This module coordinates paired MISS/HIT observations.  The runner supplied by
the caller owns the backend-specific request and cache setup; this collector
only controls the frozen measurement grid, evidence recording, and summaries.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from statistics import median
from typing import Any

TOKEN_GRID = (16, 32, 128, 256, 512)
WARMUP_PAIRS = 5
MEASURED_PAIRS = 20


def collect_prefill_profile(
    *,
    pair_runner: Callable[..., tuple[float, float]],
    provenance: Mapping[str, object],
) -> Mapping[str, object]:
    """Collect paired TTFT observations over the frozen prefill grid."""

    raw_evidence: list[dict[str, Any]] = []
    summary: dict[int, float] = {}

    for token_count in TOKEN_GRID:
        measured_deltas: list[float] = []

        for repetition_index in range(WARMUP_PAIRS):
            miss_ttft, hit_ttft = pair_runner(
                token_count,
                max_tokens=1,
                deterministic=True,
                metric="ttft",
            )
            raw_evidence.append(
                _evidence_record(
                    token_count=token_count,
                    repetition_index=repetition_index,
                    warmup=True,
                    miss_ttft=miss_ttft,
                    hit_ttft=hit_ttft,
                )
            )

        for repetition_index in range(MEASURED_PAIRS):
            miss_ttft, hit_ttft = pair_runner(
                token_count,
                max_tokens=1,
                deterministic=True,
                metric="ttft",
            )
            delta = miss_ttft - hit_ttft
            measured_deltas.append(delta)
            raw_evidence.append(
                _evidence_record(
                    token_count=token_count,
                    repetition_index=repetition_index,
                    warmup=False,
                    miss_ttft=miss_ttft,
                    hit_ttft=hit_ttft,
                )
            )

        summary[token_count] = float(median(measured_deltas))

    return {
        "raw_evidence": tuple(raw_evidence),
        "summary": summary,
        "provenance": dict(provenance),
    }


def _evidence_record(
    *,
    token_count: int,
    repetition_index: int,
    warmup: bool,
    miss_ttft: float,
    hit_ttft: float,
) -> dict[str, Any]:
    return {
        "token_count": token_count,
        "repetition_index": repetition_index,
        "warmup": warmup,
        "miss_ttft_seconds": miss_ttft,
        "hit_ttft_seconds": hit_ttft,
        "delta_seconds": miss_ttft - hit_ttft,
    }
