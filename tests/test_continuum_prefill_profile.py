from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

import pytest

TOKEN_GRID = (16, 32, 128, 256, 512)
PROFILE_PROVENANCE: Mapping[str, object] = {
    "vllm_release": "0.27.1",
    "backend": "MLX / Metal",
    "hardware": "macOS Apple Silicon arm64",
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    "tokenizer": "Qwen/Qwen2.5-0.5B-Instruct",
    "tokenizer_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    "vllm_enable_v1_multiprocessing": False,
    "block_size": 16,
    "automatic_prefix_caching": True,
    "paged_kv": True,
    "in_process_engine_core": True,
}


class _PairProbe:
    """Deterministic pair source for RED tests; no vLLM or model dependency."""

    def __init__(self, deltas: Mapping[int, tuple[float, ...]] | None = None) -> None:
        self._deltas = deltas or {}
        self._counts: Counter[int] = Counter()
        self.calls: list[dict[str, object]] = []

    def __call__(self, token_count: int, **kwargs: object) -> tuple[float, float]:
        repetition = self._counts[token_count]
        self._counts[token_count] += 1
        self.calls.append({"token_count": token_count, **kwargs})
        configured = self._deltas.get(token_count)
        if configured is None:
            delta = 100.0 + repetition if repetition < 5 else float(repetition - 4)
        else:
            delta = configured[repetition]
        hit_ttft = 1.0
        return hit_ttft + delta, hit_ttft


def _run_harness(probe: _PairProbe) -> Mapping[str, object]:
    from kvopt.runtime.vllm.prefill_profile import collect_prefill_profile

    return collect_prefill_profile(
        pair_runner=probe,
        provenance=PROFILE_PROVENANCE,
    )


def _measured_record(
    result: Mapping[str, object], token_count: int, repetition_index: int
) -> Mapping[str, object]:
    records = result["raw_evidence"]
    assert isinstance(records, tuple)
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if (
            record.get("token_count") == token_count
            and record.get("warmup") is False
            and record.get("repetition_index") == repetition_index
        ):
            return record
    raise AssertionError("measured record not found")


def test_prefill_profile_records_paired_ttft_delta_without_clamping() -> None:
    probe = _PairProbe(
        {
            16: (100.0, 101.0, 102.0, 103.0, 104.0, -0.25) + (1.0,) * 19,
        }
    )

    result = _run_harness(probe)
    record = _measured_record(result, 16, 0)

    assert record["miss_ttft_seconds"] == pytest.approx(0.75)
    assert record["hit_ttft_seconds"] == pytest.approx(1.0)
    assert record["delta_seconds"] == pytest.approx(-0.25)


def test_prefill_profile_excludes_warmup_pairs_from_summary() -> None:
    probe = _PairProbe(
        {
            16: (100.0, 101.0, 102.0, 103.0, 104.0)
            + tuple(float(index) for index in range(1, 21)),
        }
    )

    result = _run_harness(probe)
    summary = result["summary"]
    assert isinstance(summary, Mapping)
    assert summary[16] == pytest.approx(10.5)


def test_prefill_profile_uses_exact_frozen_grid_and_pair_counts() -> None:
    probe = _PairProbe()

    result = _run_harness(probe)
    call_counts = Counter(call["token_count"] for call in probe.calls)
    records = result["raw_evidence"]
    summary = result["summary"]
    assert isinstance(records, tuple)
    assert isinstance(summary, Mapping)

    assert tuple(sorted(call_counts)) == TOKEN_GRID
    assert call_counts == Counter({token_count: 25 for token_count in TOKEN_GRID})
    assert len(records) == 125
    assert tuple(sorted(summary)) == TOKEN_GRID
    for token_count in TOKEN_GRID:
        token_records = [
            record
            for record in records
            if isinstance(record, Mapping) and record["token_count"] == token_count
        ]
        assert sum(record["warmup"] is True for record in token_records) == 5
        assert sum(record["warmup"] is False for record in token_records) == 20


def test_prefill_profile_summary_is_median_of_raw_measured_deltas() -> None:
    measured_deltas = (
        -9.0,
        -8.0,
        -7.0,
        -6.0,
        -5.0,
        -4.0,
        -3.0,
        -2.0,
        -1.0,
        -0.5,
        -0.25,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
        7.0,
        8.0,
        9.0,
    )
    probe = _PairProbe(
        {32: (100.0, 101.0, 102.0, 103.0, 104.0) + measured_deltas}
    )

    result = _run_harness(probe)
    summary = result["summary"]
    assert isinstance(summary, Mapping)
    assert summary[32] == pytest.approx(-0.375)


def test_prefill_profile_preserves_raw_fields_and_minimal_profile_provenance() -> None:
    result = _run_harness(_PairProbe())
    record = _measured_record(result, 128, 0)
    provenance = result["provenance"]

    assert {
        "token_count",
        "repetition_index",
        "warmup",
        "miss_ttft_seconds",
        "hit_ttft_seconds",
        "delta_seconds",
    } <= set(record)
    assert isinstance(record["repetition_index"], int)
    assert isinstance(provenance, Mapping)
    assert set(PROFILE_PROVENANCE) <= set(provenance)
    assert "prompt" not in record


def test_prefill_profile_is_ttft_only_and_uses_one_token_deterministic_generation() -> None:
    probe = _PairProbe()

    _run_harness(probe)

    assert probe.calls
    assert all(call["max_tokens"] == 1 for call in probe.calls)
    assert all(call["deterministic"] is True for call in probe.calls)
    assert all(call["metric"] == "ttft" for call in probe.calls)
