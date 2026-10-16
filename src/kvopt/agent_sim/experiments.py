"""Phase 2F experiment orchestration: arms, paired statistics, and the
counterfactual first-divergence analysis.

Statistical unit is the independent scenario draw. Requests, turns and
decisions are never treated as independent samples. All comparisons are
paired on the same trace, capacity, block size, event times and seeds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from kvopt.agent_sim.content import prompt_block_content_ids
from kvopt.agent_sim.policies import (
    InBandTailFirstPolicy,
    NativeLRUPolicy,
    OraclePolicy,
    RetentionNativePolicy,
)
from kvopt.agent_sim.simulator import AgentSimulator, ScenarioResult
from kvopt.agent_sim.trace import SimulationTrace

BLOCK_SIZE = 16
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 20_261_016


@dataclass(frozen=True, slots=True)
class ArmSpec:
    arm_id: str
    label: str
    retention: bool
    kind: str  # "native" | "candidate_v0" | "oracle" | "diagnostic"
    scheduler: str = "native"
    reverse_direction: bool = False

    def build_policy(self):
        if self.kind == "native":
            return RetentionNativePolicy() if self.retention else NativeLRUPolicy()
        if self.kind == "candidate_v0":
            return InBandTailFirstPolicy(
                strategy_id=self.arm_id,
                retention=self.retention,
                reverse_direction=self.reverse_direction,
            )
        if self.kind == "oracle":
            return OraclePolicy()
        raise ValueError(f"unknown arm kind {self.kind}")


ARM_SPECS: dict[str, ArmSpec] = {
    "A0": ArmSpec("A0", "Native LRU", retention=False, kind="native"),
    "A1": ArmSpec("A1", "Continuum Retention + Native LRU", retention=True, kind="native"),
    "A2": ArmSpec("A2", "Ours-Evict (simulation candidate v0)", retention=False, kind="candidate_v0"),
    "A3": ArmSpec("A3", "Ours-Evict + Continuum Retention", retention=True, kind="candidate_v0"),
    "A4": ArmSpec(
        "A4",
        "Full Continuum reference (retention + scheduler adaptation)",
        retention=True,
        kind="native",
        scheduler="continuum",
    ),
    "O1": ArmSpec(
        "O1",
        "Oracle-like reference (Belady-style next-use, not proven optimal; no retention)",
        retention=False,
        kind="oracle",
    ),
    "O2": ArmSpec(
        "O2",
        "Oracle-like reference (Belady-style next-use, not proven optimal) + retention",
        retention=True,
        kind="oracle",
    ),
    "D1": ArmSpec(
        "D1",
        "Direction reversal diagnostic (in-band shallow-first)",
        retention=False,
        kind="candidate_v0",
        reverse_direction=True,
    ),
}


def future_index_for(trace: SimulationTrace) -> dict[str, tuple[int, ...]]:
    """content_id -> ordered request indices that need it (oracle only)."""
    index: dict[str, list[int]] = {}
    for position, request in enumerate(trace.requests):
        for content_id in prompt_block_content_ids(
            request.segments, trace.block_size_tokens
        ):
            index.setdefault(content_id, []).append(position)
    return {key: tuple(value) for key, value in index.items()}


@dataclass(slots=True)
class DrawMetrics:
    """Arm-level aggregates for one scenario draw (measured window only)."""

    arm_id: str
    trace_id: str
    family: str
    draw: int
    request_count: int = 0
    aggregate_recomputed_tokens: int = 0
    aggregate_actual_prefill_tokens: int = 0
    aggregate_new_suffix_tokens: int = 0
    cache_reuse_efficiency: float = 0.0
    hashed_eviction_count: int = 0
    hashless_reuse_count: int = 0
    live_cached_blocks: int = 0
    decision_count: int = 0
    nontrivial_decision_count: int = 0
    protected_block_token_seconds: float = 0.0
    protected_reuse_blocks: int = 0
    protected_unused_blocks: int = 0
    protected_survived_blocks: int = 0
    protected_destroyed_blocks: int = 0
    natural_ttl_expiry_count: int = 0
    forced_release_count: int = 0
    zero_marginal_release_count: int = 0
    shared_owner_blocked_decisions: int = 0
    per_agent_recomputed: dict[str, int] = field(default_factory=dict)
    per_request_hit_depth: dict[str, int] = field(default_factory=dict)
    p95_recomputed_tokens: float = 0.0
    worst_agent_cumulative_recomputed: int = 0
    agent_top1_share: float = 0.0
    policy_seconds: float = 0.0
    error: str | None = None


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    position = quantile * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def draw_metrics(result: ScenarioResult, block_size: int = BLOCK_SIZE) -> DrawMetrics:
    measured = [record for record in result.requests if record.window == "measured"]
    metrics = DrawMetrics(
        arm_id=result.arm_id,
        trace_id=result.trace_id,
        family=result.family,
        draw=result.draw,
        request_count=len(measured),
        aggregate_recomputed_tokens=sum(r.recomputed_tokens for r in measured),
        aggregate_actual_prefill_tokens=sum(r.actual_prefill_tokens for r in measured),
        aggregate_new_suffix_tokens=sum(r.new_suffix_tokens for r in measured),
        hashed_eviction_count=result.hashed_eviction_count,
        hashless_reuse_count=result.hashless_reuse_count,
        live_cached_blocks=result.live_cached_blocks,
        decision_count=len(result.decisions),
        nontrivial_decision_count=sum(1 for d in result.decisions if d.nontrivial),
        protected_block_token_seconds=result.protected_block_token_seconds,
        protected_reuse_blocks=result.protected_reuse_blocks,
        protected_unused_blocks=result.protected_unused_blocks,
        protected_survived_blocks=result.protected_survived_blocks,
        protected_destroyed_blocks=result.protected_destroyed_blocks,
        natural_ttl_expiry_count=result.natural_ttl_expiry_count,
        forced_release_count=result.forced_release_count,
        zero_marginal_release_count=result.zero_marginal_release_count,
        shared_owner_blocked_decisions=result.shared_owner_blocked_decisions,
        error=result.error,
    )
    prompt_tokens = sum(r.prompt_tokens for r in measured)
    cached_tokens = sum(r.cached_prefix_tokens for r in measured)
    metrics.cache_reuse_efficiency = (
        cached_tokens / prompt_tokens if prompt_tokens else 0.0
    )
    for record in measured:
        metrics.per_agent_recomputed[record.program_id] = (
            metrics.per_agent_recomputed.get(record.program_id, 0)
            + record.recomputed_tokens
        )
        metrics.per_request_hit_depth[record.request_id] = record.hit_depth
    recomputed = sorted(float(r.recomputed_tokens) for r in measured)
    metrics.p95_recomputed_tokens = _percentile(recomputed, 0.95)
    if metrics.per_agent_recomputed:
        totals = sorted(metrics.per_agent_recomputed.values(), reverse=True)
        metrics.worst_agent_cumulative_recomputed = totals[0]
        overall = sum(totals)
        metrics.agent_top1_share = totals[0] / overall if overall else 0.0
    metrics.policy_seconds = result.policy_seconds
    return metrics


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """Paired (same draw) comparison of challenger against baseline."""

    baseline_arm: str
    challenger_arm: str
    family: str
    draw_deltas: tuple[float, ...]  # challenger - baseline recomputed tokens
    draw_delta_r: tuple[float, ...]  # B * max(0, j_base - j_chal) per draw
    draw_gross: tuple[float, ...]
    mean_delta: float
    median_delta: float
    ci95_low: float
    ci95_high: float
    improved_draws: int
    tied_draws: int
    degraded_draws: int
    ngr: float | str


def _bootstrap_mean_ci(
    values: tuple[float, ...], *, iterations: int, seed: int
) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    count = len(values)
    means = []
    for _ in range(iterations):
        sample = [values[rng.randrange(count)] for _ in range(count)]
        means.append(sum(sample) / count)
    means.sort()
    lower = means[int(0.025 * iterations)]
    upper = means[min(int(0.975 * iterations), iterations - 1)]
    return (lower, upper)


def paired_comparison(
    baseline: dict[int, DrawMetrics],
    challenger: dict[int, DrawMetrics],
    *,
    baseline_arm: str,
    challenger_arm: str,
    family: str,
    baseline_result_by_draw: dict[int, ScenarioResult] | None = None,
    challenger_result_by_draw: dict[int, ScenarioResult] | None = None,
    block_size: int = BLOCK_SIZE,
) -> PairedComparison:
    draws = sorted(set(baseline) & set(challenger))
    deltas: list[float] = []
    delta_r: list[float] = []
    gross: list[float] = []
    for draw in draws:
        base = baseline[draw]
        chall = challenger[draw]
        if base.error or chall.error:
            continue
        deltas.append(float(chall.aggregate_recomputed_tokens - base.aggregate_recomputed_tokens))
        draw_delta_r = 0.0
        draw_gross = 0.0
        if baseline_result_by_draw and challenger_result_by_draw:
            base_hits = baseline_result_by_draw[draw]
            chall_hits = challenger_result_by_draw[draw]
            base_by_request = {
                record.request_id: record.hit_depth
                for record in base_hits.requests
                if record.window == "measured"
            }
            chall_by_request = {
                record.request_id: record.hit_depth
                for record in chall_hits.requests
                if record.window == "measured"
            }
            for request_id, base_depth in base_by_request.items():
                chall_depth = chall_by_request.get(request_id)
                if chall_depth is None:
                    continue
                draw_delta_r += block_size * max(0, base_depth - chall_depth)
                draw_gross += block_size * abs(base_depth - chall_depth)
        delta_r.append(draw_delta_r)
        gross.append(draw_gross)
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    ordered = sorted(deltas)
    median = _percentile(ordered, 0.5) if ordered else 0.0
    low, high = _bootstrap_mean_ci(
        tuple(deltas), iterations=BOOTSTRAP_ITERATIONS, seed=BOOTSTRAP_SEED
    )
    improved = sum(1 for value in deltas if value < 0)
    tied = sum(1 for value in deltas if value == 0)
    degraded = sum(1 for value in deltas if value > 0)
    total_gross = sum(gross)
    if total_gross == 0:
        ngr: float | str = "NOT_APPLICABLE_ZERO_GROSS"
    else:
        ngr = abs(sum(deltas)) / total_gross
    return PairedComparison(
        baseline_arm=baseline_arm,
        challenger_arm=challenger_arm,
        family=family,
        draw_deltas=tuple(deltas),
        draw_delta_r=tuple(delta_r),
        draw_gross=tuple(gross),
        mean_delta=mean_delta,
        median_delta=median,
        ci95_low=low,
        ci95_high=high,
        improved_draws=improved,
        tied_draws=tied,
        degraded_draws=degraded,
        ngr=ngr,
    )


def victim_set_divergence(
    baseline: ScenarioResult, challenger: ScenarioResult
) -> dict[str, float]:
    """Share of index-aligned decisions with different victim ID sets."""
    if len(baseline.decisions) != len(challenger.decisions):
        return {"comparable": 0.0, "divergence_rate": float("nan")}
    divergent = sum(
        1
        for left, right in zip(baseline.decisions, challenger.decisions)
        if set(left.victim_block_ids) != set(right.victim_block_ids)
    )
    return {
        "comparable": 1.0,
        "divergence_rate": divergent / len(baseline.decisions) if baseline.decisions else 0.0,
        "nontrivial_share": (
            sum(1 for d in baseline.decisions if d.nontrivial) / len(baseline.decisions)
            if baseline.decisions
            else 0.0
        ),
    }


def first_divergence_delta_r(
    trace: SimulationTrace,
    *,
    baseline_arm: ArmSpec,
    challenger_arm: ArmSpec,
) -> dict[str, object] | None:
    """Causal ΔR of the first victim-set divergence between two arms.

    Runs the baseline arm while shadow-computing the challenger's choice from
    identical state; at the first divergence, re-runs the baseline arm with the
    challenger's victims substituted at that single decision. The difference in
    future recomputed tokens is then attributable to that one decision alone.
    """
    if baseline_arm.retention != challenger_arm.retention:
        raise ValueError("counterfactual pair must share the retention setting")
    shadow = AgentSimulator(
        trace,
        baseline_arm.build_policy(),
        arm_id=f"{baseline_arm.arm_id}+shadow",
        retention=baseline_arm.retention,
        shadow_policy=challenger_arm.build_policy(),
    )
    baseline_result = shadow.run()
    divergence = shadow.first_divergence
    if divergence is None or baseline_result.error:
        return None

    branch = AgentSimulator(
        trace,
        baseline_arm.build_policy(),
        arm_id="branch",
        retention=baseline_arm.retention,
        intervention={
            int(divergence["decision_index"]): tuple(divergence["challenger_victims"])
        },
    ).run()
    if branch.error:
        return {"error": branch.error, "divergence": divergence}
    base_hits = {
        record.request_id: record.hit_depth
        for record in baseline_result.requests
        if record.window == "measured"
    }
    branch_hits = {
        record.request_id: record.hit_depth
        for record in branch.requests
        if record.window == "measured"
    }
    # ``damage`` is the task's ΔR formula: extra recomputation the challenger's
    # choice causes relative to the baseline. ``improvement`` is its mirror:
    # recomputation the challenger's choice avoids. Exactly one is non-zero
    # per request unless both policies hit the same depth.
    damage = 0
    improvement = 0
    for request_id, base_depth in base_hits.items():
        branch_depth = branch_hits.get(request_id)
        if branch_depth is None:
            continue
        damage += BLOCK_SIZE * max(0, base_depth - branch_depth)
        improvement += BLOCK_SIZE * max(0, branch_depth - base_depth)
    return {
        "divergence": divergence,
        "delta_r_damage_tokens": damage,
        "delta_r_improvement_tokens": improvement,
        "baseline_recomputed": sum(
            r.recomputed_tokens for r in baseline_result.requests if r.window == "measured"
        ),
        "branch_recomputed": sum(
            r.recomputed_tokens for r in branch.requests if r.window == "measured"
        ),
    }


def run_arm(
    trace: SimulationTrace, arm: ArmSpec, *, future_index=None
) -> ScenarioResult:
    simulator = AgentSimulator(
        trace,
        arm.build_policy(),
        arm_id=arm.arm_id,
        retention=arm.retention,
        scheduler=arm.scheduler,
        future_index=future_index if arm.kind == "oracle" else None,
    )
    return simulator.run()
