"""Phase 2F micro-benchmarks: the four core mechanism tests.

These run *before* any scenario-draw campaign (per the execution contract) and
pin the physical semantics the whole study rests on:

(a) evicting a middle block truncates the contiguous prefix strictly;
(b) a recycled physical block_id never produces a phantom hit;
(c) a shared root block is unreclaimable while any protected owner remains;
(d) in-chain deep-first eviction (candidate v0) beats native shallow-first
    eviction on the next same-prefix request (ΔR = 6B in the pinned fixture).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kvopt.agent_sim.content import Segment, prompt_block_content_ids
from kvopt.agent_sim.policies import InBandTailFirstPolicy, NativeLRUPolicy
from kvopt.agent_sim.pool import BlockPool
from kvopt.agent_sim.simulator import AgentSimulator
from kvopt.agent_sim.trace import SimulationTrace, TraceRequest, validate_trace

BLOCK = 16


def _trace(requests: list[TraceRequest], total_blocks: int) -> SimulationTrace:
    trace = SimulationTrace(
        schema_version="phase2f.trace.v1",
        trace_id="micro",
        family="MICRO",
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
    outcome: str = "COMPLETED",
    window: str = "measured",
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
        outcome=outcome,
        window=window,
    )


def _run(trace: SimulationTrace, policy, *, retention: bool = False):
    simulator = AgentSimulator(trace, policy, arm_id="test", retention=retention)
    return simulator.run()


def _recomputed(result, request_id: str) -> int:
    for record in result.requests:
        if record.request_id == request_id:
            return record.recomputed_tokens
    raise KeyError(request_id)


# ----------------------------------------------------------------------
# (a) middle-block eviction strictly truncates the contiguous prefix
# ----------------------------------------------------------------------
def test_middle_block_eviction_truncates_prefix() -> None:
    pool = BlockPool(8)
    ids = prompt_block_content_ids((Segment(key="chain", tokens=8 * BLOCK),), BLOCK)
    # 8 full blocks -> cacheable prefix is (128-1)//16 = 7 blocks.
    assert len(ids) == 7
    owned = []
    for position, content_id in enumerate(ids):
        block = pool.evict_and_take(position, content_id, position + 1, hashed=True)
        owned.append(block)
    # Return the chain to the free queue (one free event), then physically
    # evict the middle block (depth 4).
    pool.release(tuple(owned), event_id=1)
    victim = owned[3]
    assert victim.in_queue and victim.ref_cnt == 0
    pool.evict_and_take(victim.block_id, "unrelated", 1, hashed=True)
    # The chain now matches only blocks 1..3; block 4 onward must not count.
    hit = 0
    while hit < len(ids) and ids[hit] in pool.cache_mapping:
        hit += 1
    assert hit == 3, f"expected strict truncation at 3, got {hit}"
    # A later block of the same chain is still cached but unreachable.
    assert ids[4] in pool.cache_mapping
    assert ids[3] not in pool.cache_mapping


# ----------------------------------------------------------------------
# (b) recycled block_id never produces a phantom hit
# ----------------------------------------------------------------------
def test_recycled_block_id_has_no_phantom_hit() -> None:
    pool = BlockPool(4)
    first = prompt_block_content_ids((Segment(key="alpha", tokens=4 * BLOCK),), BLOCK)
    second = prompt_block_content_ids((Segment(key="beta", tokens=4 * BLOCK),), BLOCK)
    assert len(first) == 3 and len(second) == 3
    owned = []
    for position, content_id in enumerate(first):
        owned.append(pool.evict_and_take(position, content_id, position + 1, hashed=True))
    pool.release(tuple(owned), event_id=1)
    # Evict every alpha block; the slots are immediately reassigned to beta.
    for position, content_id in enumerate(second):
        pool.evict_and_take(position, content_id, position + 1, hashed=True)
    for content_id in first:
        assert content_id not in pool.cache_mapping
        assert pool.acquire(content_id) is None
    for content_id in second:
        assert pool.acquire(content_id) is not None


# ----------------------------------------------------------------------
# (c) shared root stays protected until every owner releases it
# ----------------------------------------------------------------------
def test_shared_root_survives_until_last_owner_releases() -> None:
    root = Segment(key="shared-root", tokens=5 * BLOCK)  # 4 cacheable blocks
    branch_a = Segment(key="branch-a", tokens=3 * BLOCK)
    branch_b = Segment(key="branch-b", tokens=3 * BLOCK)
    churn = Segment(key="churn-body", tokens=9 * BLOCK)  # 8 cacheable + tail
    requests = [
        _request("a1", "prog-a", 1, 0.0, (root,), terminal=False, tool="browser", gap=5.0),
        _request("b1", "prog-b", 1, 0.1, (root,), terminal=False, tool="browser", gap=5.0),
        _request("c1", "churn", 1, 1.0, (churn,)),
        _request("a2", "prog-a", 2, 5.0, (root, branch_a)),
        _request("b2", "prog-b", 2, 5.1, (root, branch_b)),
    ]
    # Capacity forces reclamation while both programs hold protected entries.
    trace = _trace(requests, total_blocks=10)
    result = _run(trace, NativeLRUPolicy(), retention=True)
    assert result.error is None, result.error
    root_ids = set(prompt_block_content_ids((root,), BLOCK))
    churn_decision = next(
        decision for decision in result.decisions if decision.request_id == "c1"
    )
    # Pressure forced at least two logical releases.
    assert churn_decision.forced_release_count >= 2, churn_decision
    effects = churn_decision.forced_release_effects
    # The shared root blocks are not reclaimable while the first owner is
    # still protected: the first release is zero-marginal (both entries
    # reference the same physical blocks, so nothing new becomes eligible).
    assert effects[0][2] == (), effects[0]
    assert result.zero_marginal_release_count >= 1
    # Only after the LAST owner releases do the root blocks become eligible.
    assert len(effects[-1][2]) >= len(root_ids), effects[-1]
    # The blocked shared-owner state was observable at the decision.
    assert churn_decision.shared_owner_blocked_count >= len(root_ids)
    # Not every shared block is destroyed: the ones native did not need stay
    # cached and remain matchable afterwards.
    surviving = {
        record.request_id: record.hit_depth for record in result.requests
    }
    assert surviving["a2"] + surviving["b2"] >= 1, surviving


# ----------------------------------------------------------------------
# (d) deep-first eviction beats native shallow-first on the next request
# ----------------------------------------------------------------------
def test_in_chain_deep_first_reduces_delta_r() -> None:
    # One program with a 10-cacheable-block chain (176 tokens), then a churn
    # request that must reclaim exactly 4 of the chain's blocks, then the
    # program returns with the same prefix.
    chain = Segment(key="chain", tokens=11 * BLOCK)  # 10 cacheable + tail
    churn = Segment(key="churn-body", tokens=10 * BLOCK)  # 9 cacheable + tail
    requests = [
        _request("p1", "prog", 1, 0.0, (chain,), terminal=False, tool="python", gap=5.0),
        _request("c1", "churn", 1, 1.0, (churn,)),
        _request("p2", "prog", 2, 6.0, (chain,)),
    ]
    trace = _trace(requests, total_blocks=16)
    native = _run(trace, NativeLRUPolicy())
    ours = _run(trace, InBandTailFirstPolicy(strategy_id="A2"))
    assert native.error is None, native.error
    assert ours.error is None, ours.error
    native_recompute = _recomputed(native, "p2")
    ours_recompute = _recomputed(ours, "p2")
    # Native evicts the four shallowest blocks a1..a4 -> full recompute.
    assert native_recompute == 10 * BLOCK, native_recompute
    # Candidate v0 evicts the four deepest blocks a7..a10 -> a1..a6 survive,
    # so only the four missing blocks are recomputed.
    assert ours_recompute == 4 * BLOCK, ours_recompute
    # ΔR = B * max(0, j_old - j_new) = 16 * (6 - 0) = 96.
    assert native_recompute - ours_recompute == 6 * BLOCK
    # And the victim sets really differ (not just the order).
    native_victims = {
        record.request_id: set(record.victim_block_ids)
        for record in native.decisions
    }
    ours_victims = {
        record.request_id: set(record.victim_block_ids)
        for record in ours.decisions
    }
    assert native_victims["c1"] != ours_victims["c1"]
