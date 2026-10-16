"""Phase 2F audit regression tests.

Each test pins one audit point from the Member-2 review:

1. no-lookahead isolation (ordinary policies never receive future fields);
2. future-index presence cannot change ordinary decisions;
3. monotonic simulation clock (tool-gap ends never rewind it);
4. tool-gap events carry their actual simulated timestamps;
5. evicted ancestors leave descendants cached but unreachable, and the chain
   becomes matchable again once the ancestor is re-cached (no stale state);
6. pool invariants hold across the campaign;
7. duplicate content assignment is rejected;
8. abnormal termination plus natural TTL expiry (bridge level);
9. A1/A3 retention paths produce identical TTL records;
10. admission ordering (A4) actually differs from FIFO on the mixed burst;
11. the server-gap mirror matches the frozen runtime history;
12. the protection-time integral is order-independent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kvopt.agent_sim.content import Segment, prompt_block_content_ids
from kvopt.agent_sim.policies import (
    DecisionContext,
    InBandTailFirstPolicy,
    NativeLRUPolicy,
    OraclePolicy,
    RetentionNativePolicy,
    SimCandidate,
)
from kvopt.agent_sim.pool import BlockPool
from kvopt.agent_sim.retention_bridge import RetentionBridge
from kvopt.agent_sim.simulator import AgentSimulator
from kvopt.agent_sim.trace import SimulationTrace, TraceRequest, validate_trace
from kvopt.agent_sim.workload_gen import generate_campaign, generate_scenario
from kvopt.agent_sim.experiments import ARM_SPECS, future_index_for, run_arm
from kvopt.continuum.clock import Clock
from kvopt.continuum.selection import EligibilityTier

BLOCK = 16


class RecordingPolicy:
    """Delegates to a wrapped policy and records every decision context."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.contexts: list[DecisionContext] = []

    @property
    def requires_future_trace(self) -> bool:
        return bool(getattr(self._inner, "requires_future_trace", False))

    def select(self, candidates, context):
        self.contexts.append(context)
        return self._inner.select(candidates, context)


class RecordingClock:
    """Clock that records every ``set`` call (monotonicity witness)."""

    def __init__(self) -> None:
        self._now = 0.0
        self.sets: list[float] = []

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += seconds
        return self._now

    def set(self, timestamp: float) -> None:
        self.sets.append(float(timestamp))
        self._now = float(timestamp)


def _trace(requests: list[TraceRequest], total_blocks: int) -> SimulationTrace:
    trace = SimulationTrace(
        schema_version="phase2f.trace.v1",
        trace_id="audit",
        family="AUDIT",
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


# ----------------------------------------------------------------------
# 1 + 2: no-lookahead isolation
# ----------------------------------------------------------------------
def test_ordinary_policies_never_receive_future_fields() -> None:
    trace = generate_scenario("S3", 1, seed=20261016)
    future_index = future_index_for(trace)
    for policy in (
        RecordingPolicy(NativeLRUPolicy()),
        RecordingPolicy(InBandTailFirstPolicy(strategy_id="A2")),
        RecordingPolicy(RetentionNativePolicy()),
        RecordingPolicy(InBandTailFirstPolicy(strategy_id="A3", retention=True)),
    ):
        retention = "retention" in policy._inner.strategy_id
        simulator = AgentSimulator(
            trace,
            policy,
            arm_id="audit",
            retention=retention,
            future_index=future_index,
        )
        result = simulator.run()
        assert result.error is None, result.error
        assert policy.contexts, "policy was never invoked"
        for context in policy.contexts:
            assert context.future_index is None, "future trace leaked to a policy"
            assert context.current_request_index is None


def test_future_index_presence_cannot_change_ordinary_decisions() -> None:
    trace = generate_scenario("S2", 3, seed=20261016)
    future_index = future_index_for(trace)
    for policy_factory, retention in (
        (lambda: NativeLRUPolicy(), False),
        (lambda: InBandTailFirstPolicy(strategy_id="A2"), False),
        (lambda: RetentionNativePolicy(), True),
        (lambda: InBandTailFirstPolicy(strategy_id="A3", retention=True), True),
    ):
        without = AgentSimulator(
            trace, policy_factory(), arm_id="a", retention=retention
        ).run()
        with_future = AgentSimulator(
            trace,
            policy_factory(),
            arm_id="a",
            retention=retention,
            future_index=future_index,
        ).run()
        assert without.error is None and with_future.error is None
        assert [d.victim_block_ids for d in without.decisions] == [
            d.victim_block_ids for d in with_future.decisions
        ]


def test_oracle_policy_does_receive_future_fields() -> None:
    trace = generate_scenario("S3", 1, seed=20261016)
    recorder = RecordingPolicy(OraclePolicy())
    simulator = AgentSimulator(
        trace,
        recorder,
        arm_id="O1",
        retention=False,
        future_index=future_index_for(trace),
    )
    result = simulator.run()
    assert result.error is None, result.error
    assert recorder.contexts
    assert all(context.future_index is not None for context in recorder.contexts)


# ----------------------------------------------------------------------
# 3 + 4: clock monotonicity and tool-gap timestamps
# ----------------------------------------------------------------------
def test_clock_never_moves_backwards_and_gaps_use_real_timestamps() -> None:
    for family, draw in (("S1", 1), ("S3", 2), ("S4", 1), ("S5", 1)):
        trace = generate_scenario(family, draw, seed=20261016)
        clock = RecordingClock()
        simulator = AgentSimulator(
            trace,
            NativeLRUPolicy(),
            arm_id="audit",
            retention=True,
        )
        # Swap in the recording clock before running (the bridge shares it).
        simulator.clock = clock
        simulator.bridge.runtime._clock = clock  # type: ignore[attr-defined]
        simulator.bridge.manager._clock = clock  # type: ignore[attr-defined]
        result = simulator.run()
        assert result.error is None, result.error
        assert clock.sets == sorted(clock.sets), "clock moved backwards"

        # Tool-gap events: external durations must equal the declared gaps and
        # start/end timestamps must match arrival and arrival + gap.
        records = simulator.bridge.runtime.external_tool_duration_history._records
        declared = {
            request.request_id: (request.arrival_offset_seconds, request.tool_gap_seconds)
            for request in trace.requests
            if not request.is_terminal
        }
        assert len(records) == len(declared), (family, draw)
        for record in records:
            arrival, gap = declared[record.program_id.value.split(":", 1)[0] and _key_of(trace, record)]
            assert record.start_timestamp == arrival
            assert record.end_timestamp == arrival + gap


def _key_of(trace: SimulationTrace, record) -> str:
    """Map an external tool record back to its trace request id."""
    for request in trace.requests:
        if request.program_id == record.program_id.value and (
            request.arrival_offset_seconds == record.start_timestamp
        ):
            return request.request_id
    raise AssertionError("tool-gap record does not match any trace request")


# ----------------------------------------------------------------------
# 5: evicted ancestor leaves descendants cached but unreachable
# ----------------------------------------------------------------------
def test_evicted_ancestor_descendants_recover_when_ancestor_recached() -> None:
    pool = BlockPool(8)
    ids = prompt_block_content_ids((Segment(key="chain", tokens=8 * BLOCK),), BLOCK)
    assert len(ids) == 7
    owned = [
        pool.evict_and_take(position, content_id, position + 1, hashed=True)
        for position, content_id in enumerate(ids)
    ]
    pool.release(tuple(owned), event_id=1)

    def match_depth() -> int:
        depth = 0
        while depth < len(ids) and ids[depth] in pool.cache_mapping:
            depth += 1
        return depth

    assert match_depth() == 7
    # Evict the ancestor (depth 3). Descendants remain cached but the strict
    # prefix match truncates at the first missing block.
    pool.evict_and_take(owned[2].block_id, "unrelated", 1, hashed=True)
    assert match_depth() == 2
    assert all(ids[position] in pool.cache_mapping for position in range(3, 7))
    # Re-cache the ancestor with the *same* content: release the slot that
    # took "unrelated" and reassign the ancestor content to it. The whole
    # chain becomes matchable again through the surviving descendants.
    pool.release((owned[2],), event_id=2)
    pool.evict_and_take(owned[2].block_id, ids[2], 3, hashed=True)
    assert match_depth() == 7
    pool.check_invariants()


# ----------------------------------------------------------------------
# 6 + 7: pool invariants and duplicate-content rejection
# ----------------------------------------------------------------------
def test_pool_invariants_hold_across_campaign() -> None:
    for trace in generate_campaign(seed=20261016, draws_per_family=2):
        for arm_id in ("A0", "A1", "A2", "A3"):
            result = run_arm(trace, ARM_SPECS[arm_id])
            assert result.error is None, (trace.trace_id, arm_id, result.error)


def test_duplicate_content_assignment_is_rejected() -> None:
    pool = BlockPool(4)
    first = prompt_block_content_ids((Segment(key="alpha", tokens=4 * BLOCK),), BLOCK)
    owned = [
        pool.evict_and_take(position, content_id, position + 1, hashed=True)
        for position, content_id in enumerate(first)
    ]
    pool.release(tuple(owned), event_id=1)
    # Block 0 holds first[0]; assigning the same content to block 1 must fail.
    try:
        pool.evict_and_take(1, first[0], 1, hashed=True)
    except ValueError as error:
        assert "duplicate content" in str(error)
        return
    raise AssertionError("duplicate content assignment was accepted")


# ----------------------------------------------------------------------
# 8: abnormal termination + natural TTL expiry (bridge level)
# ----------------------------------------------------------------------
def test_cancelled_program_can_expire_naturally() -> None:
    """A cancelled program with a positive TTL keeps protection until expiry."""
    bridge = RetentionBridge(
        clock=__import__("kvopt.continuum.clock", fromlist=["FakeClock"]).FakeClock(),
        extrapolate_prefill_profile=False,
    )
    from kvopt.continuum.clock import FakeClock
    from kvopt.continuum.types import PrefixIdentity, ProgramIdentity, RequestIdentity

    clock = FakeClock()
    bridge = RetentionBridge(clock=clock, extrapolate_prefill_profile=False)
    program = "prog-cancel"
    # 101 prior arrivals build >100 server-gap samples (GLOBAL history mode).
    for index in range(101):
        clock.set(float(index))
        bridge.request_arrived(program, f"warm-{index}", float(index))
        bridge.blocks_observed(
            program, f"warm-{index}", f"phase2f:warm-{index}", (index % 4,), float(index)
        )
        bridge.record_prefill_tokens(
            program, f"warm-{index}", f"phase2f:warm-{index}", 256
        )
        bridge.turn_finished(
            program_id=program,
            request_id=f"warm-{index}",
            timestamp=float(index),
            is_terminal=False,
            next_tool_type="browser",
        )
        bridge.followup_waiting(program, f"warm-{index}", float(index))
        bridge.tool_gap_started(program, "browser", float(index))
        bridge.tool_gap_ended(program, "browser", float(index) + 1.0)

    clock.set(500.0)
    bridge.request_arrived(program, "final", 500.0)
    bridge.blocks_observed(program, "final", "phase2f:final", (0,), 500.0)
    bridge.record_prefill_tokens(program, "final", "phase2f:final", 256)
    bridge.turn_finished(
        program_id=program,
        request_id="final",
        timestamp=500.0,
        is_terminal=False,
        next_tool_type=None,
    )
    entry = bridge.manager.snapshot(
        __import__("kvopt.continuum.selection", fromlist=["RetentionEntryKey"])
        .RetentionEntryKey(ProgramIdentity(program), PrefixIdentity("phase2f:final"))
    )
    assert entry is not None
    # GLOBAL history mode with a 1.0s gap and a small reload cost: the frozen
    # estimator may pick a positive TTL; if it does, the entry must survive the
    # cancellation and then expire naturally.
    bridge.followup_cancelled(program, "final", 500.0)
    survived = entry.ttl_decision.ttl_seconds > 0.0
    if survived:
        assert bridge.manager.snapshot(
            __import__("kvopt.continuum.selection", fromlist=["RetentionEntryKey"])
            .RetentionEntryKey(ProgramIdentity(program), PrefixIdentity("phase2f:final"))
        ).protected
        clock.set(500.0 + entry.ttl_decision.ttl_seconds + 0.001)
        expired = bridge.expire_due_and_count()
        assert expired >= 1, "natural TTL expiry did not fire after cancellation"
    else:
        # With TTL 0 the frozen cancel rule drops protection immediately.
        assert not bridge.manager.snapshot(
            __import__("kvopt.continuum.selection", fromlist=["RetentionEntryKey"])
            .RetentionEntryKey(ProgramIdentity(program), PrefixIdentity("phase2f:final"))
        ).protected


# ----------------------------------------------------------------------
# 9: A1/A3 retention paths are identical
# ----------------------------------------------------------------------
def test_retention_arms_share_identical_ttl_records() -> None:
    for family, draw in (("S1", 1), ("S3", 2), ("S5", 1)):
        trace = generate_scenario(family, draw, seed=20261016)
        a1 = run_arm(trace, ARM_SPECS["A1"])
        a3 = run_arm(trace, ARM_SPECS["A3"])
        assert a1.error is None and a3.error is None
        assert a1.ttl_probe_records == a3.ttl_probe_records, (family, draw)
        assert a1.forced_release_count == a3.forced_release_count


# ----------------------------------------------------------------------
# 10: admission ordering differs under the frozen scheduler policy
# ----------------------------------------------------------------------
def test_continuum_scheduler_changes_burst_admission_order() -> None:
    trace = generate_scenario("S4", 1, seed=20261016)  # mixed burst at t=6.0
    a1 = run_arm(trace, ARM_SPECS["A1"])
    a4 = run_arm(trace, ARM_SPECS["A4"])
    assert a1.error is None and a4.error is None
    hits_a1 = {r.request_id: r.hit_depth for r in a1.requests}
    hits_a4 = {r.request_id: r.hit_depth for r in a4.requests}
    assert hits_a1 != hits_a4, "scheduler adaptation had no observable effect"


# ----------------------------------------------------------------------
# 11: server-gap mirror fidelity
# ----------------------------------------------------------------------
def test_gap_mirror_matches_frozen_runtime_history() -> None:
    trace = generate_scenario("S5", 1, seed=20261016)
    simulator = AgentSimulator(
        trace, RetentionNativePolicy(), arm_id="A1", retention=True
    )
    result = simulator.run()
    assert result.error is None, result.error
    mirrored = [
        duration for _tool, duration in simulator.bridge._gap_mirror
    ]
    recorded = list(simulator.bridge.runtime.server_gap_history.global_samples())
    assert mirrored == recorded


# ----------------------------------------------------------------------
# 12: protection integral is order-independent
# ----------------------------------------------------------------------
def test_protection_integral_matches_documented_semantics() -> None:
    """The integral is a pure function of the recorded samples.

    Documented rule: at equal timestamps the last recorded sample wins; the
    remaining samples integrate in time order with the interval-start count.
    Re-integrating the same sample list is idempotent, and the value matches
    an independent reference computation.
    """
    trace = generate_scenario("S2", 1, seed=20261016)
    simulator = AgentSimulator(
        trace, RetentionNativePolicy(), arm_id="A1", retention=True
    )
    result = simulator.run()
    assert result.error is None, result.error
    samples = list(simulator._protection_samples)
    assert len(samples) > 4

    by_time: dict[float, int] = {}
    for timestamp, count in samples:
        by_time[timestamp] = count
    ordered = sorted(by_time.items())
    reference = 0.0
    for index in range(len(ordered) - 1):
        reference += (
            ordered[index][1]
            * trace.block_size_tokens
            * (ordered[index + 1][0] - ordered[index][0])
        )
    assert abs(result.protected_block_token_seconds - reference) < 1e-9

    # Idempotence: re-integrating the same samples reproduces the value.
    simulator._integrate_protection()
    assert abs(
        simulator.result.protected_block_token_seconds - reference
    ) < 1e-9
