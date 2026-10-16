"""Phase 2F mechanism tests: legality, fallback, determinism, no-lookahead,
band boundaries, retention observability, and oracle sanity."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kvopt.agent_sim.content import Segment, prompt_block_content_ids
from kvopt.agent_sim.policies import (
    InBandTailFirstPolicy,
    NativeLRUPolicy,
    OraclePolicy,
    RetentionNativePolicy,
    validate_selection,
)
from kvopt.agent_sim.pool import BlockPool
from kvopt.agent_sim.simulator import AgentSimulator
from kvopt.agent_sim.trace import SimulationTrace, TraceRequest, validate_trace
from kvopt.agent_sim.workload_gen import generate_campaign, generate_scenario

BLOCK = 16


def _trace(requests: list[TraceRequest], total_blocks: int) -> SimulationTrace:
    trace = SimulationTrace(
        schema_version="phase2f.trace.v1",
        trace_id="mech",
        family="MECH",
        draw=1,
        seed=0,
        generator_version="test",
        total_blocks=total_blocks,
        block_size_tokens=BLOCK,
        free_order="head_first",
        extrapolate_prefill_profile=True,
        requests=tuple(requests),
    )
    validate_trace(trace)
    return trace


def _request(
    request_id: str,
    program_id: str,
    turn: int,
    arrival: float,
    segments: tuple[Segment, ...],
    *,
    terminal: bool = True,
    tool: str | None = None,
    gap: float | None = None,
) -> TraceRequest:
    return TraceRequest(
        request_id=request_id,
        program_id=program_id,
        turn_index=turn,
        arrival_offset_seconds=arrival,
        segments=segments,
        is_terminal=terminal,
        next_tool_type=tool,
        tool_gap_seconds=gap,
        outcome="COMPLETED",
        window="measured",
    )


def _run(trace: SimulationTrace, policy, *, retention: bool = False):
    simulator = AgentSimulator(trace, policy, arm_id="test", retention=retention)
    return simulator.run()


def _recomputed(result) -> int:
    return sum(record.recomputed_tokens for record in result.requests)


# ----------------------------------------------------------------------
def test_non_contiguous_cached_blocks_do_not_count_as_hits() -> None:
    pool = BlockPool(8)
    ids = prompt_block_content_ids((Segment(key="chain", tokens=8 * BLOCK),), BLOCK)
    owned = [
        pool.evict_and_take(position, content_id, position + 1, hashed=True)
        for position, content_id in enumerate(ids)
    ]
    pool.release(tuple(owned), event_id=1)
    # Evict block 2 (depth 3) but keep 3..6 cached: the hit must stop at 2.
    pool.evict_and_take(owned[2].block_id, "other", 1, hashed=True)
    hit = 0
    while hit < len(ids) and ids[hit] in pool.cache_mapping:
        hit += 1
    assert hit == 2
    assert all(ids[position] in pool.cache_mapping for position in range(3, len(ids)))


def test_validate_selection_rejects_illegal_choices() -> None:
    from kvopt.agent_sim.policies import SimCandidate
    from kvopt.continuum.selection import EligibilityTier

    candidates = [
        SimCandidate(
            block_id=index,
            lru_rank=index,
            has_block_hash=True,
            tier=EligibilityTier.TIER_1,
            depth=index + 1,
            band_id=0,
            band_hashless=False,
            band_pos=index + 1,
        )
        for index in range(4)
    ]
    validate_selection(candidates, (0, 1), 2)
    for bad in ((0, 0), (0, 9), (0,), (0, 1, 2, 3, 3)):
        try:
            validate_selection(candidates, bad, 2)
        except ValueError:
            continue
        raise AssertionError(f"illegal selection accepted: {bad}")


def test_ignore_structure_fallback_is_bitwise_native() -> None:
    """D3: without depth/band signals the policy must equal native LRU."""
    traces = generate_campaign(seed=20261016, families=("S1", "S3", "S4"), draws_per_family=3)
    for trace in traces:
        native = _run(trace, NativeLRUPolicy())
        fallback = _run(
            trace,
            InBandTailFirstPolicy(strategy_id="D3", ignore_structure=True),
        )
        assert native.error is None and fallback.error is None
        assert _recomputed(native) == _recomputed(fallback)
        assert [d.victim_block_ids for d in native.decisions] == [
            d.victim_block_ids for d in fallback.decisions
        ]
        # ... and the same under retention (tier, lru_rank) ordering.
        native_ret = _run(trace, RetentionNativePolicy(), retention=True)
        fallback_ret = _run(
            trace,
            InBandTailFirstPolicy(strategy_id="D3r", ignore_structure=True, retention=True),
            retention=True,
        )
        assert native_ret.error is None and fallback_ret.error is None
        assert _recomputed(native_ret) == _recomputed(fallback_ret)
        assert [d.victim_block_ids for d in native_ret.decisions] == [
            d.victim_block_ids for d in fallback_ret.decisions
        ]


def test_band_boundary_cut_selects_identical_victims() -> None:
    """When the cut falls at a band boundary, candidate v0 == native exactly."""
    # Two independent one-shot programs: after both complete, the queue holds
    # two hashed bands. A churn request that needs exactly the blocks of the
    # first (oldest) band must select the same set under both policies.
    first = Segment(key="first", tokens=4 * BLOCK)  # 3 cacheable + tail
    second = Segment(key="second", tokens=4 * BLOCK)
    churn = Segment(key="churn", tokens=4 * BLOCK)
    requests = [
        _request("f1", "prog-f", 1, 0.0, (first,)),
        _request("s1", "prog-s", 1, 0.5, (second,)),
        _request("c1", "churn", 1, 1.0, (churn,)),
    ]
    trace = _trace(requests, total_blocks=12)
    native = _run(trace, NativeLRUPolicy())
    ours = _run(trace, InBandTailFirstPolicy(strategy_id="A2"))
    assert native.error is None and ours.error is None
    native_victims = {
        record.request_id: set(record.victim_block_ids)
        for record in native.decisions
    }
    ours_victims = {
        record.request_id: set(record.victim_block_ids)
        for record in ours.decisions
    }
    # The churn decision consumes exactly the oldest band (a boundary cut).
    assert native_victims["c1"] == ours_victims["c1"], (native_victims, ours_victims)


def test_determinism_two_runs_are_identical() -> None:
    trace = generate_scenario("S3", 4, seed=20261016)
    for retention in (False, True):
        policy = (
            InBandTailFirstPolicy(strategy_id="A2/A3", retention=retention)
            if retention
            else InBandTailFirstPolicy(strategy_id="A2")
        )
        first = _run(trace, policy, retention=retention)
        second = _run(trace, policy, retention=retention)
        assert first.error is None and second.error is None
        assert _recomputed(first) == _recomputed(second)
        assert [r.hit_depth for r in first.requests] == [r.hit_depth for r in second.requests]
        assert [d.victim_block_ids for d in first.decisions] == [
            d.victim_block_ids for d in second.decisions
        ]


def test_no_lookahead_future_trace_cannot_change_past_decisions() -> None:
    """Truncating the trace after decision k must not change decisions <= k."""
    full = generate_scenario("S2", 2, seed=20261016)
    full_result = _run(full, InBandTailFirstPolicy(strategy_id="A2"))
    assert full_result.error is None
    cut_index = len(full.requests) // 2
    truncated = SimulationTrace(
        schema_version=full.schema_version,
        trace_id=full.trace_id,
        family=full.family,
        draw=full.draw,
        seed=full.seed,
        generator_version=full.generator_version,
        total_blocks=full.total_blocks,
        block_size_tokens=full.block_size_tokens,
        free_order=full.free_order,
        extrapolate_prefill_profile=full.extrapolate_prefill_profile,
        requests=full.requests[:cut_index],
    )
    validate_trace(truncated)
    truncated_result = _run(truncated, InBandTailFirstPolicy(strategy_id="A2"))
    assert truncated_result.error is None
    expected = [d.victim_block_ids for d in full_result.decisions][: len(truncated_result.decisions)]
    assert [d.victim_block_ids for d in truncated_result.decisions] == expected


def test_retention_lifecycle_is_observable() -> None:
    """Protection during gaps and forced release under pressure both occur."""
    trace = generate_scenario("S4", 1, seed=20261016)  # burst: heavy pressure
    result = _run(trace, RetentionNativePolicy(), retention=True)
    assert result.error is None, result.error
    # Protection is active during tool gaps (block-token-seconds > 0).
    assert result.protected_block_token_seconds > 0
    # Forced releases occur under pressure.
    assert result.forced_release_count > 0
    # Every entry eventually loses protection (no stuck protection).
    assert all(entry.unprotected_at is not None for entry in result.entries)


def test_natural_ttl_expiry_is_unreachable_at_frozen_scales() -> None:
    """Structural finding: with T=0 and R << gap scale, TTL collapses to 0.

    The frozen estimator then never produces a positive deadline for a
    non-waiting program, so natural TTL expiry cannot fire in-simulator. The
    campaign report carries the queue-delay sensitivity probe for this.
    """
    trace = generate_scenario("S5", 1, seed=20261016)
    result = _run(trace, RetentionNativePolicy(), retention=True)
    assert result.error is None, result.error
    assert result.natural_ttl_expiry_count == 0
    assert all(record.chosen_ttl_seconds == 0.0 for record in result.ttl_probe_records)


def test_protected_reuse_requires_sharing() -> None:
    """Cross-program reuse of a still-protected block is observed in S3."""
    trace = generate_scenario("S3", 1, seed=20261016)
    result = _run(trace, RetentionNativePolicy(), retention=True)
    assert result.error is None, result.error
    # A waiting program's protected blocks are re-hit by another program that
    # shares the root prefix: this is the retention value made visible.
    assert result.protected_reuse_blocks > 0
    assert result.shared_owner_blocked_decisions > 0


def test_ttl_history_modes_cold_and_global() -> None:
    """S6 cold draws stay COLD_START; warm draws cross the 100-sample gate."""
    cold = generate_scenario("S6", 1, seed=20261016)
    warm = generate_scenario("S6", 6, seed=20261016)
    cold_result = _run(cold, RetentionNativePolicy(), retention=True)
    warm_result = _run(warm, RetentionNativePolicy(), retention=True)
    assert cold_result.error is None and warm_result.error is None
    cold_modes = {record.history_mode for record in cold_result.ttl_probe_records}
    warm_modes = {record.history_mode for record in warm_result.ttl_probe_records}
    assert cold_modes == {"cold_start"}, cold_modes
    assert "global" in warm_modes or "tool_specific" in warm_modes, warm_modes


def test_oracle_is_legal_and_never_worse_than_native() -> None:
    """The Belady-style oracle must respect eligibility and dominate native."""
    traces = generate_campaign(seed=20261016, families=("S1", "S3"), draws_per_family=3)
    for trace in traces:
        future_index: dict[str, tuple[int, ...]] = {}
        for index, request in enumerate(trace.requests):
            for content_id in prompt_block_content_ids(request.segments, BLOCK):
                future_index.setdefault(content_id, []).append(index)
        future_index = {key: tuple(value) for key, value in future_index.items()}
        native = _run(trace, NativeLRUPolicy())
        oracle = AgentSimulator(
            trace, OraclePolicy(), arm_id="O1", retention=False, future_index=future_index
        ).run()
        assert native.error is None and oracle.error is None
        assert _recomputed(oracle) <= _recomputed(native), trace.trace_id
        # Legality: victim counts always match the requirement.
        for decision in oracle.decisions:
            assert len(decision.victim_block_ids) == decision.required_blocks
            assert decision.eligible_count >= decision.required_blocks


def test_negative_control_family_has_zero_or_no_divergence() -> None:
    """No-reuse and no-pressure draws must produce identical arm results."""
    for draw in (1, 2, 3, 4, 5, 6):
        trace = generate_scenario("S7", draw, seed=20261016)
        native = _run(trace, NativeLRUPolicy())
        ours = _run(trace, InBandTailFirstPolicy(strategy_id="A2"))
        assert native.error is None and ours.error is None
        assert _recomputed(native) == _recomputed(ours) == 0, (draw, _recomputed(native))
        assert native.hashed_eviction_count == ours.hashed_eviction_count
        if draw <= 3 or draw <= 6:
            assert native.hashed_eviction_count == 0

def test_trace_round_trip_through_dict() -> None:
    """Serialized traces reload identically (reproducible input contract)."""
    from kvopt.agent_sim.trace import trace_from_dict

    trace = generate_scenario("S3", 2, seed=20261016)
    reloaded = trace_from_dict(trace.to_dict())
    assert reloaded.trace_hash() == trace.trace_hash()
    assert reloaded.total_blocks == trace.total_blocks
    assert len(reloaded.requests) == len(trace.requests)
