"""Deterministic spike: Continuum baseline vs cost-aware forced-unpin.

Drives the real Phase 1B components (``RuntimeCoordinator``,
``RetentionManager``, ``RetentionRuntimeIntegration``) on a scripted
multi-turn workload without a vLLM process. Metrics are deterministic
functional counters and recompute-cost proxies derived from the canonical
PrefillReload profile; they are NOT measured GPU latency.

Run with:  python experiments/costaware_forced_unpin/run_experiments.py
"""

from __future__ import annotations

import heapq
import json
import math
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    FakeClock,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    RetentionMode,
    TurnFinished,
)
from kvopt.continuum.pressure import (
    RetentionAwareSelectionCoordinator,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.continuum.snapshots import (
    EvictedRequestQueueDelayRecord,
    RetentionEntrySnapshot,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.costaware import (
    CostAwareForcedUnpinCoordinator,
    ForcedUnpinConfig,
    estimate_conditional_return_probability,
)
from kvopt.runtime.vllm.retention_integration import (
    RetentionRuntimeIntegration,
)

BLOCK_TOKENS = 16
# Canonical qualified profile point: PrefillReload(256) = 0.0887301250040764 s.
SECONDS_PER_TOKEN = 0.0887301250040764 / 256
GEN_SECONDS = 0.5
DURATION_HISTORY_THRESHOLD = 4


@dataclass
class _Block:
    block_id: int
    block_hash: object | None
    ref_cnt: int = 0


@dataclass
class _Candidate:
    block_id: int
    has_block_hash: bool
    lru_rank: int


class LinearPrefillReload:
    """Linear PrefillReload provider anchored at the canonical profile point."""

    def __init__(self, seconds_per_token: float) -> None:
        self._seconds_per_token = seconds_per_token

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        seconds = self._seconds_per_token * token_count
        return seconds, InputProvenance(
            InputSource.APPROXIMATED, "linear canonical PrefillReload(256) profile"
        )


class AffinePrefillReload:
    """PrefillReload with a fixed launch overhead plus a linear region.

    Real prefill has startup cost; small prefixes then carry a much higher
    loss per cached block, which is exactly the non-uniform loss/block regime
    in which per-block greedy victim selection can diverge from deadline
    ordering.
    """

    def __init__(self, overhead_seconds: float, seconds_per_token: float) -> None:
        self._overhead = overhead_seconds
        self._seconds_per_token = seconds_per_token

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        seconds = self._overhead + self._seconds_per_token * token_count
        return seconds, InputProvenance(
            InputSource.APPROXIMATED, "affine PrefillReload profile"
        )


class PowerPrefillReload:
    """Power-law PrefillReload normalized to the linear cost at the reference.

    ``C(r) = spt * r * (r / REFERENCE_TOKENS) ** (exponent - 1)`` keeps the
    reference-length cost identical to the canonical linear profile while
    spreading the per-block loss across prefix sizes by ``r ** (exponent-1)``
    (sub-linear exponents make small prefixes expensive per block,
    super-linear exponents make large prefixes expensive per block).
    """

    REFERENCE_TOKENS = 32768

    def __init__(self, exponent: float) -> None:
        self._exponent = exponent

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        scale = (token_count / self.REFERENCE_TOKENS) ** (self._exponent - 1.0)
        seconds = SECONDS_PER_TOKEN * token_count * scale
        return seconds, InputProvenance(
            InputSource.APPROXIMATED,
            f"power-law PrefillReload profile exponent={self._exponent}",
        )


@dataclass(frozen=True)
class ProgramPlan:
    """One scripted agent program: turns, tool identity, and tool gaps."""

    program: str
    start: float
    tokens: int
    tools: tuple[str | None, ...]
    gaps: tuple[float, ...]

    @property
    def turns(self) -> int:
        return len(self.tools)


@dataclass
class VictimRecord:
    """One forced-unpin decision observed by the world."""

    program: str
    blocks: int
    tokens: int
    prefill_seconds: float
    deadline_remaining_seconds: float
    return_probability: float


@dataclass
class WorldMetrics:
    pressure_calls: int = 0
    evicted_cached_blocks: int = 0
    tier1_evicted_cached_blocks: int = 0
    forced_unpin_events: int = 0
    forced_unpin_blocks: int = 0
    forced_unpin_victims: list[VictimRecord] = field(default_factory=list)
    ordinary_expiry_events: int = 0
    hit_followups: int = 0
    miss_followups: int = 0
    recompute_tokens: int = 0
    recompute_seconds: float = 0.0
    ttft_penalty_seconds: list[float] = field(default_factory=list)
    queue_wait_seconds: list[float] = field(default_factory=list)
    completed_programs: int = 0


class ScenarioError(RuntimeError):
    """Raised when a scenario is infeasible on the configured capacity."""


class _World:
    """One deterministic replica of the scripted workload under one policy."""

    def __init__(
        self,
        *,
        name: str,
        capacity_blocks: int,
        plans: tuple[ProgramPlan, ...],
        selection_coordinator: object | None,
        prefill_provider: object | None = None,
        default_ttl_seconds: float = 2.0,
    ) -> None:
        self._name = name
        self._capacity = capacity_blocks
        self._plans = plans
        self._free: list[_Block] = [
            _Block(block_id, None) for block_id in range(capacity_blocks)
        ]
        self._free_ids = {block.block_id for block in self._free}
        self._prefix_blocks: dict[str, list[_Block]] = {}
        self._prefix_tokens: dict[str, int] = {}
        self._wait_start: dict[tuple[str, int], float] = {}
        self._last_selected: list[_Block] = []
        self._clock = FakeClock()
        self._runtime = build_runtime(
            clock=self._clock,
            prefill_reload_provider=(
                LinearPrefillReload(SECONDS_PER_TOKEN)
                if prefill_provider is None
                else prefill_provider
            ),
            default_ttl_seconds=default_ttl_seconds,
            duration_history_threshold=DURATION_HISTORY_THRESHOLD,
        )
        self._integration = RetentionRuntimeIntegration(
            self._runtime.retention, selection_coordinator
        )
        self._prefill_provider = (
            LinearPrefillReload(SECONDS_PER_TOKEN)
            if prefill_provider is None
            else prefill_provider
        )
        self.metrics = WorldMetrics()

    # ---- event loop -----------------------------------------------------

    def run(self) -> WorldMetrics:
        # Discrete-event loop: one arrival and one finish event per turn.
        heap: list[tuple[float, int, str, str, int]] = []
        for sequence, plan in enumerate(self._plans):
            heapq.heappush(heap, (plan.start, sequence, "arrive", plan.program, 0))
        while heap:
            timestamp, _seq, kind, program, turn = heapq.heappop(heap)
            plan = self._plan_for(program)
            if kind == "arrive":
                needed = self._needed_blocks(plan, turn)
                if needed > self._capacity:
                    raise ScenarioError(
                        f"scenario {self._name}: prefix of {needed} blocks exceeds "
                        f"capacity {self._capacity}"
                    )
                if needed > len(self._free):
                    # Native waiting-queue behavior: the request waits until
                    # frees from finishing turns make the allocation feasible.
                    self._wait_start.setdefault((program, turn), timestamp)
                    heapq.heappush(
                        heap, (timestamp + 0.1, _next_sequence(), "arrive", program, turn)
                    )
                    continue
                wait_started = self._wait_start.pop((program, turn), None)
                if wait_started is not None:
                    self.metrics.queue_wait_seconds.append(timestamp - wait_started)
                admission_delay = self._arrive(plan, turn, timestamp)
                finish_at = timestamp + admission_delay + GEN_SECONDS
                heapq.heappush(heap, (finish_at, _next_sequence(), "finish", program, turn))
            else:
                self._finish_turn(plan, turn, timestamp)
                if turn + 1 < plan.turns:
                    next_arrival = timestamp + plan.gaps[turn]
                    heapq.heappush(
                        heap, (next_arrival, _next_sequence(), "arrive", program, turn + 1)
                    )
        return self.metrics

    def _needed_blocks(self, plan: ProgramPlan, turn: int) -> int:
        blocks = self._prefix_blocks.get(plan.program, [])
        hit = bool(blocks) and all(
            block.block_id in self._free_ids for block in blocks
        )
        if turn > 0 and hit:
            return 0
        return math.ceil(plan.tokens / BLOCK_TOKENS)

    def _plan_for(self, program: str) -> ProgramPlan:
        for plan in self._plans:
            if plan.program == program:
                return plan
        raise ScenarioError(f"unknown program {program}")

    def _arrive(self, plan: ProgramPlan, turn: int, timestamp: float) -> float:
        """Process one request arrival; returns the admission delay."""
        program = ProgramIdentity(plan.program)
        request = self._request_id(plan.program, turn)
        self._clock.set(timestamp)
        self._runtime.handle(RequestArrived(program, request, timestamp))

        blocks = self._prefix_blocks.get(plan.program, [])
        hit = bool(blocks) and all(
            block.block_id in self._free_ids for block in blocks
        )
        admission_delay = 0.0
        if turn == 0:
            self._prefix_blocks[plan.program] = self._allocate(plan, timestamp)
            self._prefix_tokens[plan.program] = plan.tokens
        elif hit:
            self.metrics.hit_followups += 1
            for block in blocks:
                self._free.remove(block)
                self._free_ids.discard(block.block_id)
        else:
            self.metrics.miss_followups += 1
            recompute = self._prefill_provider.estimate(plan.tokens)[0]
            self.metrics.recompute_tokens += plan.tokens
            self.metrics.recompute_seconds += recompute
            self.metrics.ttft_penalty_seconds.append(recompute)
            admission_delay = recompute
            self._prefix_blocks[plan.program] = self._allocate(plan, timestamp)
            self._runtime.record_queue_delay(
                EvictedRequestQueueDelayRecord(
                    program, request, timestamp, timestamp + recompute
                )
            )

        # The clock advances only with event time; the delayed admission
        # timestamp travels inside the event itself (interleaved events may
        # legitimately pop between arrival and admission).
        admitted_at = timestamp + admission_delay
        self._runtime.handle(RequestAdmitted(program, request, admitted_at))
        return admission_delay

    def _finish_turn(self, plan: ProgramPlan, turn: int, timestamp: float) -> None:
        program = ProgramIdentity(plan.program)
        request = self._request_id(plan.program, turn)
        prefix = PrefixIdentity(f"prefix-{plan.program}")
        blocks = self._prefix_blocks.get(plan.program, [])
        self._clock.set(timestamp)
        self._runtime.handle(
            BlocksObserved(
                program,
                request,
                prefix,
                tuple(BlockIdentity(block.block_id) for block in blocks),
                timestamp,
            )
        )
        self._runtime.record_prefill_context_token_count(
            PrefillContextTokenCountRecord(
                program, request, prefix, plan.tokens, InputProvenance(InputSource.OBSERVED)
            )
        )
        tool = plan.tools[turn]
        self._runtime.handle(TurnFinished(program, request, timestamp, tool is None, tool))
        for block in blocks:
            block.block_hash = prefix
            block.ref_cnt = 0
            self._free.append(block)
            self._free_ids.add(block.block_id)
        if tool is None:
            self.metrics.completed_programs += 1

    # ---- pressure path --------------------------------------------------

    def _allocate(self, plan: ProgramPlan, timestamp: float) -> list[_Block]:
        needed = math.ceil(plan.tokens / BLOCK_TOKENS)
        if needed > len(self._free):
            raise ScenarioError(
                f"scenario {self._name}: capacity {self._capacity} cannot supply "
                f"{needed} free blocks at t={timestamp}"
            )
        self.metrics.pressure_calls += 1
        self._last_selected = []
        result = self._integration.apply_pressure(
            mode=RetentionMode.CONTROLLED,
            blocks=tuple(self._free),
            required_blocks=needed,
            timestamp=timestamp,
            remove_selected=self._remove_selected,
        )
        selected = self._last_selected
        evicted = [block for block in selected if block.block_hash is not None]
        for block in evicted:
            self._integration.observe_native_eviction(BlockIdentity(block.block_id))
        self.metrics.evicted_cached_blocks += len(evicted)
        plan_state = result.selection_plan
        if plan_state is not None:
            tier2_ids = {
                block.block_id for block in plan_state.preparation.tier_2_block_ids
            }
            self.metrics.tier1_evicted_cached_blocks += sum(
                block.block_id not in tier2_ids for block in evicted
            )
            self.metrics.ordinary_expiry_events += len(
                plan_state.preparation.ordinary_expired_entries
            )
            self._record_releases(plan_state, timestamp)
        for block in selected:
            block.block_hash = None
            block.ref_cnt = 1
        return selected

    def _remove_selected(self, block_ids: tuple[int, ...]) -> None:
        """Mirror the controlled-mode queue removal callback."""
        ids = set(block_ids)
        self._last_selected = [block for block in self._free if block.block_id in ids]
        self._free = [block for block in self._free if block.block_id not in ids]
        self._free_ids -= ids

    def _record_releases(self, plan_state: object, timestamp: float) -> None:
        preparation = plan_state.preparation
        for release in preparation.pressure_releases:
            key = release.entry_key
            self.metrics.forced_unpin_events += 1
            self.metrics.forced_unpin_blocks += len(release.newly_eligible_block_ids)
            entry = self._runtime.retention.snapshot(key)
            if entry is None:
                continue
            self.metrics.forced_unpin_victims.append(
                VictimRecord(
                    program=key.program_id.value,
                    blocks=len(entry.block_ids),
                    tokens=self._prefix_tokens.get(key.program_id.value, 0),
                    prefill_seconds=entry.ttl_decision.ttl_input.prefill_reload_seconds,
                    deadline_remaining_seconds=entry.deadline_timestamp - timestamp,
                    return_probability=estimate_conditional_return_probability(
                        entry, timestamp
                    ),
                )
            )

    @staticmethod
    def _request_id(program: str, turn: int) -> RequestIdentity:
        return RequestIdentity(f"{program}-r{turn}")


_SEQUENCE = [0]


def _next_sequence() -> int:
    _SEQUENCE[0] += 1
    return _SEQUENCE[0]


# ---- scenario construction -------------------------------------------------


@dataclass(frozen=True)
class ToolProfile:
    """Lognormal tool-gap distribution (heavy tail, aging hazard effects)."""

    name: str
    gap_median: float
    gap_sigma: float

    def sample(self, rng: random.Random) -> float:
        return math.exp(
            math.log(self.gap_median) + self.gap_sigma * rng.gauss(0.0, 1.0)
        )


FAST = ToolProfile("fast", 1.0, 0.4)
SEARCH = ToolProfile("search", 4.0, 0.6)
SLOW = ToolProfile("slow", 20.0, 1.0)
# Heavy-tail variant used to expose elapsed-age (hazard-rate) divergence:
# deadlines ignore elapsed age, conditional return probability does not.
HEAVY = ToolProfile("heavy", 5.0, 1.2)
_TOOL_PROFILES = {"fast": FAST, "search": SEARCH, "slow": SLOW, "heavy": HEAVY}


def _warmup_plans(
    rng: random.Random, profiles: tuple[ToolProfile, ...], samples_per_tool: int
) -> tuple[ProgramPlan, ...]:
    plans: list[ProgramPlan] = []
    start = 0.0
    for profile in profiles:
        for index in range(samples_per_tool):
            plans.append(
                ProgramPlan(
                    program=f"warm-{profile.name}-{index}",
                    start=start,
                    tokens=64,
                    tools=(profile.name, None),
                    gaps=(profile.sample(rng),),
                )
            )
            start += 0.1
    return tuple(plans)


def _scenario_plans(
    rng: random.Random,
    *,
    prefix: str,
    count: int,
    tokens: int | tuple[int, ...],
    tool: str | tuple[str, ...],
    turns: int,
    spacing: float,
    start: float,
) -> tuple[ProgramPlan, ...]:
    plans: list[ProgramPlan] = []
    for index in range(count):
        program_tokens = (
            tokens if isinstance(tokens, int) else tokens[index % len(tokens)]
        )
        program_tool = tool if isinstance(tool, str) else tool[index % len(tool)]
        tools = tuple(
            program_tool if turn < turns - 1 else None for turn in range(turns)
        )
        gaps = tuple(
            _TOOL_PROFILES[program_tool].sample(rng) for _ in range(turns - 1)
        )
        plans.append(
            ProgramPlan(
                program=f"{prefix}-{index}",
                start=start + index * spacing,
                tokens=program_tokens,
                tools=tools,
                gaps=gaps,
            )
        )
    return tuple(plans)


Scenario = tuple[str, int, tuple[ProgramPlan, ...], object | None]


def build_scenarios() -> tuple[Scenario, ...]:
    rng = random.Random(20260924)
    warmups = _warmup_plans(rng, (FAST, SEARCH, SLOW, HEAVY), 6)
    scenario_start = 35.0

    def plan(
        name: str,
        capacity: int,
        provider: object | None = None,
        **kwargs: object,
    ) -> Scenario:
        return (
            name,
            capacity,
            warmups + _scenario_plans(rng, prefix=name.split("-")[0], **kwargs),
            provider,
        )  # type: ignore[arg-type]

    return (
        plan(
            "uniform_medium",
            1000,
            count=16,
            tokens=2048,
            tool="search",
            turns=4,
            spacing=1.0,
            start=scenario_start,
        ),
        plan(
            "mixed_length",
            3000,
            count=16,
            tokens=(1024, 4096, 16384, 32768),
            tool="search",
            turns=4,
            spacing=1.5,
            start=scenario_start,
        ),
        plan(
            "fast_slow_tools",
            2000,
            count=16,
            tokens=4096,
            tool=("fast", "slow"),
            turns=4,
            spacing=1.0,
            start=scenario_start,
        ),
        plan(
            "anticorrelated_size_gap",
            3000,
            count=16,
            tokens=(32768, 2048),
            tool=("fast", "slow"),
            turns=4,
            spacing=1.2,
            start=scenario_start,
        ),
        plan(
            "high_pressure",
            700,
            count=16,
            tokens=2048,
            tool="search",
            turns=4,
            spacing=1.0,
            start=scenario_start,
        ),
        plan(
            "heavy_tail_aged",
            5000,
            count=20,
            tokens=(32768, 65536),
            tool="heavy",
            turns=4,
            spacing=0.8,
            start=scenario_start,
        ),
        plan(
            "affine_prefill_overhead",
            2600,
            provider=AffinePrefillReload(0.5, SECONDS_PER_TOKEN),
            count=20,
            tokens=(512, 4096, 16384, 32768),
            tool="search",
            turns=4,
            spacing=1.0,
            start=scenario_start,
        ),
    )


POLICIES: tuple[tuple[str, Callable[[], object | None]], ...] = (
    ("baseline", lambda: None),
    ("costaware-lambda0", lambda: CostAwareForcedUnpinCoordinator(ForcedUnpinConfig(0.0))),
    ("costaware-lambda1", lambda: CostAwareForcedUnpinCoordinator(ForcedUnpinConfig(1.0))),
)


def _summarize(metrics: WorldMetrics) -> dict[str, object]:
    followups = metrics.hit_followups + metrics.miss_followups
    penalties = metrics.ttft_penalty_seconds
    return {
        "pressure_calls": metrics.pressure_calls,
        "evicted_cached_blocks": metrics.evicted_cached_blocks,
        "tier1_evicted_cached_blocks": metrics.tier1_evicted_cached_blocks,
        "forced_unpin_events": metrics.forced_unpin_events,
        "forced_unpin_blocks": metrics.forced_unpin_blocks,
        "ordinary_expiry_events": metrics.ordinary_expiry_events,
        "hit_followups": metrics.hit_followups,
        "miss_followups": metrics.miss_followups,
        "hit_rate": round(metrics.hit_followups / followups, 4) if followups else None,
        "recompute_tokens": metrics.recompute_tokens,
        "recompute_seconds": round(metrics.recompute_seconds, 4),
        "mean_ttft_penalty_seconds": (
            round(sum(penalties) / len(penalties), 4) if penalties else 0.0
        ),
        "max_ttft_penalty_seconds": round(max(penalties), 4) if penalties else 0.0,
        "queue_wait_seconds_total": round(sum(metrics.queue_wait_seconds), 4),
        "completed_programs": metrics.completed_programs,
    }


def run_worlds() -> dict[str, dict[str, dict[str, object]]]:
    results: dict[str, dict[str, dict[str, object]]] = {}
    for name, capacity, plans, provider in build_scenarios():
        results[name] = {}
        for policy_name, factory in POLICIES:
            world = _World(
                name=name,
                capacity_blocks=capacity,
                plans=plans,
                selection_coordinator=factory(),
                prefill_provider=provider,
            )
            results[name][policy_name] = _summarize(world.run())
    return results


# ---- overhead benchmark ----------------------------------------------------


def _bench_entry(
    *,
    prefix: str,
    ttl_seconds: float,
    block_ids: tuple[int, ...],
    samples: tuple[float, ...],
) -> RetentionEntrySnapshot:
    ttl_input = TTLInput(
        program_id=ProgramIdentity("program-bench"),
        request_id=RequestIdentity("request-bench"),
        prefix_id=PrefixIdentity(prefix),
        decision_timestamp=0.0,
        next_tool_type="search",
        global_server_gap_samples_seconds=samples,
        tool_server_gap_samples_seconds=samples,
        queue_delay_t_seconds=0.05,
        eta=1.0,
        prefill_reload_seconds=0.35,
        default_ttl_seconds=2.0,
        server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=InputProvenance(InputSource.OBSERVED),
        prefill_reload_provenance=InputProvenance(InputSource.APPROXIMATED, "bench"),
        default_ttl_provenance=InputProvenance(InputSource.APPROXIMATED, "bench"),
    )
    decision = TTLDecision(ttl_input, ttl_seconds, TTLHistoryMode.TOOL_SPECIFIC, None)
    return RetentionEntrySnapshot(
        ttl_decision=decision,
        protected=True,
        waiting_followup=False,
        block_ids=tuple(BlockIdentity(block_id) for block_id in block_ids),
    )


# ---- prefill-profile matrix (escape route b) --------------------------------


MATRIX_PROFILES: tuple[tuple[str, Callable[[], object]], ...] = (
    ("linear", lambda: LinearPrefillReload(SECONDS_PER_TOKEN)),
    ("affine-5s", lambda: AffinePrefillReload(5.0, SECONDS_PER_TOKEN)),
    ("power-0.5", lambda: PowerPrefillReload(0.5)),
    ("power-1.5", lambda: PowerPrefillReload(1.5)),
)

# Scenarios kept for the matrix: each has forced unpins and prefix-size
# diversity (high_pressure is the size-homogeneous tight-capacity control).
MATRIX_SCENARIOS = (
    "mixed_length",
    "anticorrelated_size_gap",
    "heavy_tail_aged",
    "high_pressure",
)


def run_profile_matrix() -> dict[str, dict[str, dict[str, object]]]:
    """Replay the forced-unpin scenarios under non-linear prefill profiles.

    Non-uniform loss per cached block is the only regime in which the
    per-block greedy ranking can diverge from the frozen deadline ordering.
    The linear cell is a consistency control: it must reproduce the main run.
    """
    by_name = {
        name: (capacity, plans) for name, capacity, plans, _provider in build_scenarios()
    }
    matrix: dict[str, dict[str, dict[str, object]]] = {}
    for scenario_name in MATRIX_SCENARIOS:
        capacity, plans = by_name[scenario_name]
        for profile_label, profile_factory in MATRIX_PROFILES:
            cell = f"{scenario_name}@{profile_label}"
            print(f"  matrix cell {cell}", flush=True)
            matrix[cell] = {}
            for policy_name, policy_factory in POLICIES:
                world = _World(
                    name=cell,
                    capacity_blocks=capacity,
                    plans=plans,
                    selection_coordinator=policy_factory(),
                    prefill_provider=profile_factory(),
                )
                matrix[cell][policy_name] = _summarize(world.run())
    return matrix


def bench_overhead() -> dict[str, object]:
    """Time prepare() for both coordinators on one synthetic pressured state."""
    entries_count = 60
    blocks_per_entry = 4
    hashed = entries_count * blocks_per_entry
    unhashed = 160
    candidates = [
        _Candidate(index, index < hashed, index) for index in range(hashed + unhashed)
    ]
    entries = tuple(
        _bench_entry(
            prefix=f"prefix-{index}",
            ttl_seconds=20.0 + index * 0.1,
            block_ids=tuple(
                range(index * blocks_per_entry, (index + 1) * blocks_per_entry)
            ),
            samples=tuple(3.0 + 0.1 * step for step in range(12)),
        )
        for index in range(entries_count)
    )
    required = unhashed + 5 * blocks_per_entry  # forces five whole-entry releases

    coordinators = (
        ("baseline", RetentionAwareSelectionCoordinator()),
        ("costaware", CostAwareForcedUnpinCoordinator()),
        (
            "costaware-marginal",
            CostAwareForcedUnpinCoordinator(
                ForcedUnpinConfig(0.0, marginal_block_denominator=True)
            ),
        ),
    )
    timings: dict[str, float] = {}
    for label, coordinator in coordinators:
        best = math.inf
        for _ in range(20):
            started = time.perf_counter()
            coordinator.prepare(
                candidates, entries, required_blocks=required, timestamp=1.0
            )
            best = min(best, time.perf_counter() - started)
        timings[label] = best
    no_pressure = {
        label: len(
            coordinator.prepare(
                candidates, entries, required_blocks=unhashed, timestamp=1.0
            ).pressure_releases
        )
        for label, coordinator in coordinators
    }
    return {
        "entries": entries_count,
        "queue_blocks": hashed + unhashed,
        "forced_releases": 5,
        "repetitions": 20,
        "prepare_seconds_best": {k: round(v, 6) for k, v in timings.items()},
        "no_pressure_prepare_releases": no_pressure,
    }


def main() -> None:
    results = run_worlds()
    overhead = bench_overhead()
    matrix = run_profile_matrix()
    output = {"scenarios": results, "overhead_benchmark": overhead, "profile_matrix": matrix}
    target = Path(__file__).parent / "results"
    target.mkdir(exist_ok=True)
    (target / "summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for name, policies in results.items():
        print(f"== {name} ==")
        for policy, summary in policies.items():
            print(
                f"  {policy:<20} unpin={summary['forced_unpin_events']:<4} "
                f"hit_rate={summary['hit_rate']} "
                f"recompute_s={summary['recompute_seconds']} "
                f"miss={summary['miss_followups']}"
            )
    print("== profile matrix ==")
    for cell, policies in matrix.items():
        print(f"  {cell}")
        for policy, summary in policies.items():
            print(
                f"    {policy:<20} unpin={summary['forced_unpin_events']:<4} "
                f"hit_rate={summary['hit_rate']} "
                f"recompute_s={summary['recompute_seconds']} "
                f"miss={summary['miss_followups']}"
            )
    print("== overhead ==")
    print(json.dumps(overhead["prepare_seconds_best"], indent=2))
    print(f"results written to {target / 'summary.json'}")


if __name__ == "__main__":
    main()
