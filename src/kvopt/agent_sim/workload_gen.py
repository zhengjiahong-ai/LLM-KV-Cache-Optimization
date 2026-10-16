"""Deterministic Agent-scenario workload generator for Phase 2F.

Seven ``simulation-only`` families, ten independent draws each. The existing
Phase 2E F1-F6 workloads are *not* touched; they remain the regression
baseline. Every draw is fully determined by (family, draw, seed): all
randomness comes from one seeded ``random.Random`` with a fixed call order.

Families (task mapping):

* S1 continuous tool-calling agent        (task A)
* S2 heterogeneous tool waits             (task B)
* S3 shared root + private branches       (task C)
* S4 burst concurrency under pressure     (task D)
* S5 long incremental sessions            (task E)
* S6 cold/warm start + history drift      (task F)
* S7 negative controls                    (task G)

Design intent per family is documented inline; capacity and arrival patterns
are chosen so that physical eviction pressure and non-trivial victim-selection
windows (``|EligibleCandidates| > required_blocks``) actually occur.
"""

from __future__ import annotations

import math
import random

from .content import Segment, prompt_block_content_ids
from .trace import GENERATOR_VERSION, SimulationTrace, TraceRequest, validate_trace

FAMILIES = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
DRAWS_PER_FAMILY = 10
BLOCK_SIZE = 16

# Tool types and their gap distributions (seconds). Only the *observed* gap is
# ever visible to policies; the generator uses these to build the timeline.
_TOOL_GAP_RANGES = {
    "browser": (0.3, 0.8),
    "python": (0.5, 1.5),
    "search": (0.2, 0.6),
    "alpha": (0.5, 1.5),
    "beta": (0.05, 0.2),
    "slowtool": (8.0, 20.0),
    "fasttool": (0.1, 0.3),
}


def _gap(rng: random.Random, tool_type: str) -> float:
    low, high = _TOOL_GAP_RANGES[tool_type]
    return round(rng.uniform(low, high), 6)


def _segments(*pairs: tuple[str, int]) -> tuple[Segment, ...]:
    return tuple(Segment(key=key, tokens=tokens) for key, tokens in pairs)


class _Builder:
    """Accumulates one program's requests with a running clock."""

    def __init__(self) -> None:
        self.requests: list[TraceRequest] = []

    def add(
        self,
        *,
        request_id: str,
        program_id: str,
        turn_index: int,
        arrival: float,
        segments: tuple[Segment, ...],
        next_tool_type: str | None,
        tool_gap_seconds: float | None,
        outcome: str,
        window: str,
        is_terminal: bool | None = None,
    ) -> None:
        self.requests.append(
            TraceRequest(
                request_id=request_id,
                program_id=program_id,
                turn_index=turn_index,
                arrival_offset_seconds=round(arrival, 6),
                segments=segments,
                is_terminal=next_tool_type is None if is_terminal is None else is_terminal,
                next_tool_type=next_tool_type,
                tool_gap_seconds=tool_gap_seconds,
                outcome=outcome,
                window=window,
            )
        )



def _capacity_blocks(requests: list[TraceRequest], pressure_factor: float) -> int:
    """Deterministic capacity from the draw's distinct cacheable content.

    ``pressure_factor`` is the intended working-set ratio: below 1.0 the pool
    cannot hold every distinct cacheable block, which forces physical
    evictions; above 1.0 there is no pressure (negative-control regimes).
    """
    distinct: set[str] = set()
    max_request_blocks = 0
    for request in requests:
        content_ids = prompt_block_content_ids(request.segments, BLOCK_SIZE)
        distinct.update(content_ids)
        max_request_blocks = max(max_request_blocks, len(content_ids) + 1)
    capacity = math.ceil(len(distinct) * pressure_factor)
    return max(capacity, max_request_blocks + 4)


def _chain_segments(prefix: tuple[Segment, ...], key: str, tokens: int) -> tuple[Segment, ...]:
    return prefix + (Segment(key=key, tokens=tokens),)


# ----------------------------------------------------------------------
# family builders
# ----------------------------------------------------------------------
def _build_s1(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Continuous tool-calling agent under background churn pressure."""
    builder = _Builder()
    turns = 8
    growth = 3  # blocks per turn (48 tokens)
    prefix = _segments((f"s1-{draw}-fg-system", 48))
    clock = 0.0
    tools = ("browser", "python", "search")
    for turn in range(1, turns + 1):
        last = turn == turns
        tool = None if last else tools[(turn - 1) % 3]
        gap = None if last else _gap(rng, tool)
        builder.add(
            request_id=f"s1-{draw}-fg:{turn}",
            program_id=f"s1-{draw}-fg",
            turn_index=turn,
            arrival=clock,
            segments=prefix,
            next_tool_type=tool,
            tool_gap_seconds=gap,
            outcome="COMPLETED",
            window="measured",
        )
        if last:
            break
        clock += gap
        prefix = _chain_segments(prefix, f"s1-{draw}-fg-tool-{turn}", growth * BLOCK_SIZE)
    # background churn: unique one-shot content, no reuse, creates pressure
    churn_blocks = 4
    churn_count = 10 + (draw % 4)
    churn_clock = 0.4
    for index in range(churn_count):
        builder.add(
            request_id=f"s1-{draw}-churn:{index}",
            program_id=f"s1-{draw}-churn-{index}",
            turn_index=1,
            arrival=churn_clock,
            segments=_segments((f"s1-{draw}-churn-{index}-body", churn_blocks * BLOCK_SIZE)),
            next_tool_type=None,
            tool_gap_seconds=None,
            outcome="COMPLETED",
            window="measured",
        )
        churn_clock += rng.uniform(0.8, 2.0)
    return builder.requests, 0.65


def _build_s2(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Heterogeneous tool waits: fast vs slow returning agents."""
    builder = _Builder()
    turns = 4 + (draw % 3)
    growth = 2
    for agent_index in range(1, 5):
        agent = f"a{agent_index}"
        slow = agent_index >= 3
        prefix = _segments((f"s2-{draw}-{agent}-system", 64))
        clock = 0.2 * (agent_index - 1)
        for turn in range(1, turns + 1):
            last = turn == turns
            tool = None if last else ("slowtool" if slow else "fasttool")
            gap = None if last else (rng.uniform(8.0, 20.0) if slow else rng.uniform(0.1, 0.3))
            gap = None if gap is None else round(gap, 6)
            builder.add(
                request_id=f"s2-{draw}-{agent}:{turn}",
                program_id=f"s2-{draw}-{agent}",
                turn_index=turn,
                arrival=clock,
                segments=prefix,
                next_tool_type=tool,
                tool_gap_seconds=gap,
                outcome="COMPLETED",
                window="measured",
            )
            if last:
                break
            clock += gap
            prefix = _chain_segments(prefix, f"s2-{draw}-{agent}-t{turn}", growth * BLOCK_SIZE)
    return builder.requests, 0.70


def _build_s3(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Multi-agent shared root with private branches (prefix-tree sharing)."""
    builder = _Builder()
    root = (f"s3-{draw}-root", 96)  # 6 shared blocks
    turns = 5
    growth = 2
    agent_count = 3 + (draw % 2)
    for agent_index in range(1, agent_count + 1):
        agent = f"a{agent_index}"
        branch = 2 + (draw % 3)
        prefix = _segments(root, (f"s3-{draw}-{agent}-branch", branch * BLOCK_SIZE))
        clock = 0.7 * (agent_index - 1)
        for turn in range(1, turns + 1):
            last = turn == turns
            tool = None if last else ("browser" if turn % 2 else "python")
            gap = None if last else _gap(rng, tool)
            builder.add(
                request_id=f"s3-{draw}-{agent}:{turn}",
                program_id=f"s3-{draw}-{agent}",
                turn_index=turn,
                arrival=clock,
                segments=prefix,
                next_tool_type=tool,
                tool_gap_seconds=gap,
                outcome="COMPLETED",
                window="measured",
            )
            if last:
                break
            clock += gap + rng.uniform(0.0, 1.0)
            prefix = _chain_segments(prefix, f"s3-{draw}-{agent}-t{turn}", growth * BLOCK_SIZE)
    return builder.requests, 0.70


def _build_s4(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Burst concurrency with tight capacity: repeated multi-block reclamation."""
    builder = _Builder()
    agents = 5 + (draw % 3)
    root = (f"s4-{draw}-root", 64)  # 4 shared blocks
    branch = 6
    for agent_index in range(1, agents + 1):
        agent = f"a{agent_index}"
        prefix = _segments(root, (f"s4-{draw}-{agent}-branch", branch * BLOCK_SIZE))
        # Turn 1: a true burst — every agent's first request arrives together.
        builder.add(
            request_id=f"s4-{draw}-{agent}:1",
            program_id=f"s4-{draw}-{agent}",
            turn_index=1,
            arrival=0.0,
            segments=prefix,
            is_terminal=False,
            next_tool_type="python",
            tool_gap_seconds=6.0,
            outcome="COMPLETED",
            window="measured",
        )
        prefix = _chain_segments(prefix, f"s4-{draw}-{agent}-t1", 2 * BLOCK_SIZE)
        # Turn 2: synchronized second burst — returning (protected) follow-ups
        # arrive together with brand-new programs, so admission order differs
        # between native FIFO and the frozen Continuum scheduler policy.
        builder.add(
            request_id=f"s4-{draw}-{agent}:2",
            program_id=f"s4-{draw}-{agent}",
            turn_index=2,
            arrival=6.0,
            segments=prefix,
            is_terminal=False,
            next_tool_type="python",
            tool_gap_seconds=6.0,
            outcome="COMPLETED",
            window="measured",
        )
        prefix = _chain_segments(prefix, f"s4-{draw}-{agent}-t2", 2 * BLOCK_SIZE)
        builder.add(
            request_id=f"s4-{draw}-{agent}:3",
            program_id=f"s4-{draw}-{agent}",
            turn_index=3,
            arrival=12.0,
            segments=prefix,
            is_terminal=True,
            next_tool_type=None,
            tool_gap_seconds=None,
            outcome="COMPLETED",
            window="measured",
        )
    # Two fresh one-shot programs join the second burst (ids sort before the
    # agents, so native FIFO would serve them first).
    for index in (1, 2):
        builder.add(
            request_id=f"s4-{draw}-00new{index}:1",
            program_id=f"s4-{draw}-00new{index}",
            turn_index=1,
            arrival=6.0,
            segments=_segments((f"s4-{draw}-00new{index}-body", 5 * BLOCK_SIZE)),
            is_terminal=True,
            next_tool_type=None,
            tool_gap_seconds=None,
            outcome="COMPLETED",
            window="measured",
        )
    return builder.requests, 0.45


def _build_s5(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Long incremental sessions; crosses the frozen 100-sample TTL threshold."""
    builder = _Builder()
    turns = 30 + 2 * (draw % 6)
    growth = 2
    for agent_index in range(1, 4):
        agent = f"a{agent_index}"
        prefix = _segments((f"s5-{draw}-{agent}-system", 64))
        clock = 0.5 * (agent_index - 1)
        for turn in range(1, turns + 1):
            last = turn == turns
            tool = None if last else ("browser" if turn % 3 else "search")
            gap = None if last else _gap(rng, tool)
            builder.add(
                request_id=f"s5-{draw}-{agent}:{turn}",
                program_id=f"s5-{draw}-{agent}",
                turn_index=turn,
                arrival=clock,
                segments=prefix,
                next_tool_type=tool,
                tool_gap_seconds=gap,
                outcome="COMPLETED",
                window="measured",
            )
            if last:
                break
            clock += gap
            prefix = _chain_segments(prefix, f"s5-{draw}-{agent}-t{turn}", growth * BLOCK_SIZE)
    return builder.requests, 0.55


def _build_s6(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Cold start vs warm start (history drift between warmup and measured)."""
    builder = _Builder()
    warm = draw > 5
    if warm:
        # 22-24 short programs x 6 turns -> >100 server-gap samples, so the
        # measured window runs in GLOBAL TTL history mode (the frozen
        # duration_history_threshold is 100).
        for index in range(22 + (draw % 3)):
            program = f"s6-{draw}-warm-{index}"
            prefix = _segments((f"{program}-system", 32))
            clock = 0.05 * index
            for turn in range(1, 7):
                last = turn == 6
                tool = None if last else "alpha"
                gap = None if last else _gap(rng, tool)
                builder.add(
                    request_id=f"{program}:{turn}",
                    program_id=program,
                    turn_index=turn,
                    arrival=clock,
                    segments=prefix,
                    next_tool_type=tool,
                    tool_gap_seconds=gap,
                    outcome="COMPLETED",
                    window="warmup",
                )
                if last:
                    break
                clock += gap
                prefix = _chain_segments(prefix, f"{program}-t{turn}", BLOCK_SIZE)
        clock = 30.0
    else:
        clock = 0.0
    for agent_index in range(1, 4):
        agent = f"a{agent_index}"
        prefix = _segments((f"s6-{draw}-{agent}-system", 48))
        local = clock + 0.3 * (agent_index - 1)
        for turn in range(1, 5):
            last = turn == 4
            tool = None if last else "beta"
            gap = None if last else _gap(rng, tool)
            builder.add(
                request_id=f"s6-{draw}-{agent}:{turn}",
                program_id=f"s6-{draw}-{agent}",
                turn_index=turn,
                arrival=local,
                segments=prefix,
                next_tool_type=tool,
                tool_gap_seconds=gap,
                outcome="COMPLETED",
                window="measured",
            )
            if last:
                break
            local += gap
            prefix = _chain_segments(prefix, f"s6-{draw}-{agent}-t{turn}", 2 * BLOCK_SIZE)
    return builder.requests, 0.75


def _build_s7(rng: random.Random, draw: int) -> tuple[list[TraceRequest], float]:
    """Negative controls: no reuse / no pressure / no sharing / shallow pressure."""
    builder = _Builder()
    if draw <= 3:
        # no subsequent reuse anywhere: every request has unique content
        for index in range(14):
            builder.add(
                request_id=f"s7-{draw}-u:{index}",
                program_id=f"s7-{draw}-u-{index}",
                turn_index=1,
                arrival=round(0.5 * index, 6),
                segments=_segments((f"s7-{draw}-unique-{index}", rng.choice([64, 96, 128]))),
                next_tool_type=None,
                tool_gap_seconds=None,
                outcome="COMPLETED",
                window="measured",
            )
        return builder.requests, 4.0
    if draw <= 6:
        # no pressure: capacity far above the working set
        for agent_index in range(1, 4):
            agent = f"a{agent_index}"
            prefix = _segments((f"s7-{draw}-{agent}-system", 48))
            clock = 0.4 * (agent_index - 1)
            for turn in range(1, 5):
                last = turn == 4
                tool = None if last else "browser"
                gap = None if last else _gap(rng, tool)
                builder.add(
                    request_id=f"s7-{draw}-{agent}:{turn}",
                    program_id=f"s7-{draw}-{agent}",
                    turn_index=turn,
                    arrival=clock,
                    segments=prefix,
                    next_tool_type=tool,
                    tool_gap_seconds=gap,
                    outcome="COMPLETED",
                    window="measured",
                )
                if last:
                    break
                clock += gap
                prefix = _chain_segments(prefix, f"s7-{draw}-{agent}-t{turn}", 2 * BLOCK_SIZE)
        return builder.requests, 8.0
    if draw <= 8:
        # pressure but no cross-program sharing
        for agent_index in range(1, 5):
            agent = f"a{agent_index}"
            prefix = _segments((f"s7-{draw}-{agent}-system", 64))
            clock = 0.3 * (agent_index - 1)
            for turn in range(1, 6):
                last = turn == 5
                tool = None if last else "search"
                gap = None if last else _gap(rng, tool)
                builder.add(
                    request_id=f"s7-{draw}-{agent}:{turn}",
                    program_id=f"s7-{draw}-{agent}",
                    turn_index=turn,
                    arrival=clock,
                    segments=prefix,
                    next_tool_type=tool,
                    tool_gap_seconds=gap,
                    outcome="COMPLETED",
                    window="measured",
                )
                if last:
                    break
                clock += gap
                prefix = _chain_segments(prefix, f"s7-{draw}-{agent}-t{turn}", 2 * BLOCK_SIZE)
        return builder.requests, 0.75
    # shallow pressure: few evictions, small or zero deltas allowed
    for agent_index in range(1, 4):
        agent = f"a{agent_index}"
        prefix = _segments((f"s7-{draw}-{agent}-system", 48))
        clock = 0.4 * (agent_index - 1)
        for turn in range(1, 6):
            last = turn == 5
            tool = None if last else "python"
            gap = None if last else _gap(rng, tool)
            builder.add(
                request_id=f"s7-{draw}-{agent}:{turn}",
                program_id=f"s7-{draw}-{agent}",
                turn_index=turn,
                arrival=clock,
                segments=prefix,
                next_tool_type=tool,
                tool_gap_seconds=gap,
                outcome="COMPLETED",
                window="measured",
            )
            if last:
                break
            clock += gap
            prefix = _chain_segments(prefix, f"s7-{draw}-{agent}-t{turn}", 2 * BLOCK_SIZE)
    return builder.requests, 0.9


_BUILDERS = {
    "S1": _build_s1,
    "S2": _build_s2,
    "S3": _build_s3,
    "S4": _build_s4,
    "S5": _build_s5,
    "S6": _build_s6,
    "S7": _build_s7,
}

# Extra tool types used by the families (documented distributions).


def generate_scenario(
    family: str,
    draw: int,
    *,
    seed: int,
    free_order: str = "head_first",
    extrapolate_prefill_profile: bool = True,
) -> SimulationTrace:
    """Generate one deterministic scenario draw."""
    if family not in _BUILDERS:
        raise ValueError(f"unknown family {family}")
    if not 1 <= draw <= DRAWS_PER_FAMILY:
        raise ValueError("draw must be within 1..10")
    rng = random.Random(f"{seed}:{family}:{draw}")
    requests, pressure_factor = _BUILDERS[family](rng, draw)
    requests.sort(key=lambda item: (item.arrival_offset_seconds, item.request_id))
    total_blocks = _capacity_blocks(requests, pressure_factor)
    trace = SimulationTrace(
        schema_version="phase2f.trace.v1",
        trace_id=f"phase2f-{family.lower()}-draw-{draw:02d}",
        family=family,
        draw=draw,
        seed=seed,
        generator_version=GENERATOR_VERSION,
        total_blocks=total_blocks,
        block_size_tokens=BLOCK_SIZE,
        free_order=free_order,
        extrapolate_prefill_profile=extrapolate_prefill_profile,
        requests=tuple(requests),
    )
    validate_trace(trace)
    return trace


def generate_campaign(
    *,
    seed: int = 20261016,
    families: tuple[str, ...] = FAMILIES,
    draws_per_family: int = DRAWS_PER_FAMILY,
    free_order: str = "head_first",
    extrapolate_prefill_profile: bool = True,
) -> tuple[SimulationTrace, ...]:
    """Generate every scenario draw of the campaign (deterministic)."""
    traces = []
    for family in families:
        for draw in range(1, draws_per_family + 1):
            traces.append(
                generate_scenario(
                    family,
                    draw,
                    seed=seed,
                    free_order=free_order,
                    extrapolate_prefill_profile=extrapolate_prefill_profile,
                )
            )
    return tuple(traces)
