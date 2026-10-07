"""Executable rule-acceptance protocol for the M4 candidate-rule study.

This module turns M1's frozen acceptance protocol into code that can be applied
without reinterpreting it.

The protocol was frozen by M1 before any holdout existed, precisely so that the
metric cannot be re-chosen after seeing a result. It is implemented as code so
that the frozen form and the applied form cannot drift apart.

Design commitments, quoted from the ruling:

- the statistical unit is the **independent decision cluster**, not the raw run
  row: ``seed repetition 只用于 runtime noise / reproducibility，不计为独立 sample``;
- a rule's formula, direction, tie-break, fallback and acceptance metrics must be
  frozen **before** the final holdout materializes;
- ``Gate PASS != Rule Accepted``: the empirical gap gate decides whether the
  problem is worth attacking, not whether a rule wins.

Nothing here reads a future-derived label as an input, and nothing here is
runtime code.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from .offline_eval import RuleEvaluation, scenario_group

# --- verdict levels --------------------------------------------------------

LEVEL_NOT_ACCEPTED = "NOT_ACCEPTED"
LEVEL_DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
LEVEL_PROXY_CANDIDATE = "PROXY_CANDIDATE"
LEVEL_RUNTIME_CANDIDATE = "RUNTIME_CANDIDATE"
LEVEL_IMPLEMENTATION_ELIGIBLE = "IMPLEMENTATION_ELIGIBLE"

# --- statistical units -----------------------------------------------------

#: The unit every Level A/B claim and bootstrap is computed on (M1 ruling
#: 2026-10-07). One scenario draw is one independently designed workload; two
#: decisions inside it share that workload and are not independent evidence.
SCOPE_SCENARIO_DRAW = "independent_scenario_draw"

#: Retained for diagnosis only. Never used for the holdout floor or the CI.
SCOPE_DECISION_CLUSTER = "decision_position_cluster"

# --- metric tiers ----------------------------------------------------------

#: Which evidence tier a verdict was computed on. The tier is selected from the
#: evidence that actually exists; the metric itself is read from the frozen
#: preregistration, so it cannot be chosen after a result is known.
TIER_PROXY = "proxy"
TIER_RUNTIME = "runtime"

#: The frozen loss views backing each tier. ``runtime`` is the direct recompute
#: observation M1 approved; ``proxy`` is the planned-timing proxy the discovery
#: campaign used.
PROXY_LOSS_VIEW = "planned_return_weighted_prefill_proxy"
RUNTIME_LOSS_VIEW = "observed_recomputed_tokens"

#: Retained so existing imports keep working; prefer PROXY_LOSS_VIEW.
PRIMARY_METRIC_PROXY_LOSS = PROXY_LOSS_VIEW
PRIMARY_METRIC_RECOMPUTED_TOKENS = RUNTIME_LOSS_VIEW

#: The six formal scenarios defined by M6. A holdout that does not cover all of
#: them cannot support a method claim, however many draws it contains.
FORMAL_FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6")


@dataclass(frozen=True, slots=True)
class AcceptanceCriteria:
    """The frozen protocol. Change requires a new M1 ruling, not an edit here."""

    minimum_scenario_draws: int = 30
    """Holdout floor, counted in independent scenario draws (M1 ruling)."""
    required_families: tuple[str, ...] = FORMAL_FAMILIES
    family_agreement_minimum: float = 2.0 / 3.0
    bootstrap_iterations: int = 10_000
    bootstrap_seed: int = 20_261_007
    confidence: float = 0.95

    def as_payload(self) -> dict[str, object]:
        """Serializable form, so a report records the protocol it applied."""
        return {
            "statistical_unit": SCOPE_SCENARIO_DRAW,
            "minimum_scenario_draws": self.minimum_scenario_draws,
            "required_families": list(self.required_families),
            "family_agreement_minimum": self.family_agreement_minimum,
            "bootstrap_iterations": self.bootstrap_iterations,
            "bootstrap_seed": self.bootstrap_seed,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ScenarioPairedDelta:
    """One **independent scenario draw**'s paired difference.

    ``delta = baseline_loss - challenger_loss``, so **positive means the
    challenger improved**. This sign convention is frozen: every table in every
    report must state it, because the reverse convention appears in the probe
    scripts and mixing them inverts conclusions.

    Construction order is deliberate: seeds are averaged inside a decision
    position, positions are then averaged inside the scenario. The result is one
    observation per independent workload, which is the unit M1 fixed.
    """

    scenario_group: str
    scenario_family_id: str | None
    decision_positions: int
    seed_repeats: int
    baseline_loss: float
    challenger_loss: float
    delta: float


@dataclass(frozen=True, slots=True)
class ClusterPairedDelta:
    """One decision-position cluster's paired difference. **Diagnostic only.**

    Same sign convention as :class:`ScenarioPairedDelta`. Retained because it
    localises *where* inside a scenario a difference arises, but it is not the
    unit the holdout floor or the confidence interval uses: several clusters in
    one scenario share that scenario's workload.
    """

    scenario_group: str
    decision_event_index: int
    scenario_family_id: str | None
    baseline_loss: float
    challenger_loss: float
    delta: float


def _paired_per_unit(
    evaluation: RuleEvaluation,
    baseline_rule_id: str,
    challenger_rule_id: str,
) -> tuple[
    dict[tuple[str, int], list[float]],
    dict[tuple[str, int], list[float]],
    dict[tuple[str, int], str | None],
]:
    """Collect losses for both rules keyed by ``(scenario group, position)``."""
    losses: dict[str, dict[tuple[str, int], list[float]]] = {
        baseline_rule_id: {},
        challenger_rule_id: {},
    }
    families: dict[tuple[str, int], str | None] = {}
    for row in evaluation.outcomes:
        bucket = losses.get(row.rule_id)
        if bucket is None:
            continue
        key = (scenario_group(row.run_id), row.decision_event_index)
        bucket.setdefault(key, []).append(row.selected_loss)
        if key not in families or families[key] is None:
            families[key] = row.scenario_family_id
    return losses[baseline_rule_id], losses[challenger_rule_id], families


def cluster_paired_deltas(
    evaluation: RuleEvaluation,
    *,
    baseline_rule_id: str,
    challenger_rule_id: str,
) -> tuple[ClusterPairedDelta, ...]:
    """Per decision-position cluster deltas, seeds averaged inside each.

    **Diagnostic view.** See :func:`scenario_paired_deltas` for the unit that
    Level A/B actually tests.
    """
    baseline, challenger, families = _paired_per_unit(
        evaluation, baseline_rule_id, challenger_rule_id
    )
    shared = sorted(set(baseline).intersection(challenger))
    if not shared:
        raise ValueError("rules share no evaluated clusters")
    deltas: list[ClusterPairedDelta] = []
    for key in shared:
        baseline_loss = statistics.fmean(baseline[key])
        challenger_loss = statistics.fmean(challenger[key])
        deltas.append(
            ClusterPairedDelta(
                scenario_group=key[0],
                decision_event_index=key[1],
                scenario_family_id=families.get(key),
                baseline_loss=baseline_loss,
                challenger_loss=challenger_loss,
                delta=baseline_loss - challenger_loss,
            )
        )
    return tuple(deltas)


def scenario_paired_deltas(
    evaluation: RuleEvaluation,
    *,
    baseline_rule_id: str,
    challenger_rule_id: str,
) -> tuple[ScenarioPairedDelta, ...]:
    """Per **independent scenario draw** deltas: the unit M1 fixed.

    Aggregation order, which is the whole point of this function:

    1. average the seed repeats inside each decision position;
    2. average those position means inside each scenario group.

    Only step 2's output is resampled. Two decisions in the same scenario share
    that scenario's workload, so treating them as separate observations would
    overstate the evidence -- on the discovery campaign that inflation is 20
    clusters against 18 real draws.
    """
    baseline, challenger, families = _paired_per_unit(
        evaluation, baseline_rule_id, challenger_rule_id
    )
    shared = sorted(set(baseline).intersection(challenger))
    if not shared:
        raise ValueError("rules share no evaluated scenarios")

    per_scenario: dict[str, dict[str, object]] = {}
    for key in shared:
        group = key[0]
        entry = per_scenario.setdefault(
            group,
            {"baseline": [], "challenger": [], "seeds": 0},
        )
        entry["baseline"].append(statistics.fmean(baseline[key]))
        entry["challenger"].append(statistics.fmean(challenger[key]))
        entry["seeds"] = max(int(entry["seeds"]), len(baseline[key]))

    deltas: list[ScenarioPairedDelta] = []
    for group in sorted(per_scenario):
        entry = per_scenario[group]
        baseline_position_means = entry["baseline"]
        challenger_position_means = entry["challenger"]
        baseline_loss = statistics.fmean(baseline_position_means)
        challenger_loss = statistics.fmean(challenger_position_means)
        family = next(
            (
                families[key]
                for key in shared
                if key[0] == group and families.get(key)
            ),
            None,
        )
        deltas.append(
            ScenarioPairedDelta(
                scenario_group=group,
                scenario_family_id=family,
                decision_positions=len(baseline_position_means),
                seed_repeats=int(entry["seeds"]),
                baseline_loss=baseline_loss,
                challenger_loss=challenger_loss,
                delta=baseline_loss - challenger_loss,
            )
        )
    return tuple(deltas)


@dataclass(frozen=True, slots=True)
class PairedResult:
    """Paired summary with a bootstrap interval over the resampled unit."""

    scope: str
    units: int
    improved: int
    worsened: int
    tied: int
    mean_delta: float
    median_delta: float
    ci_lower: float
    ci_upper: float
    confidence: float
    bootstrap_iterations: int
    bootstrap_seed: int

    @property
    def better_than_worse(self) -> bool:
        return self.improved > self.worsened

    @property
    def ci_lower_above_zero(self) -> bool:
        return self.ci_lower > 0.0


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    """Linear-interpolated percentile over already-sorted values."""
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_ci(
    deltas: Sequence[float], criteria: AcceptanceCriteria
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean, resampling the given units.

    Callers must pass unit-level values (one per independent scenario draw for
    any Level A/B claim). The seed is part of the frozen protocol, so the
    interval is reproducible rather than re-drawn until it looks favourable.
    """
    if not deltas:
        raise ValueError("bootstrap requires at least one unit")
    rng = random.Random(criteria.bootstrap_seed)
    count = len(deltas)
    means: list[float] = []
    for _ in range(criteria.bootstrap_iterations):
        resampled = [deltas[rng.randrange(count)] for _ in range(count)]
        means.append(statistics.fmean(resampled))
    means.sort()
    tail = (1.0 - criteria.confidence) / 2.0
    return _percentile(means, tail), _percentile(means, 1.0 - tail)


def paired_result(
    deltas: Sequence[ScenarioPairedDelta] | Sequence[ClusterPairedDelta],
    criteria: AcceptanceCriteria,
    *,
    scope: str = SCOPE_SCENARIO_DRAW,
) -> PairedResult:
    """Summarize one unit's deltas under the frozen protocol.

    ``scope`` records which unit was passed, so a payload can never present a
    diagnostic decision-position view as if it were the draw-level result.
    """
    if not deltas:
        raise ValueError("at least one unit is required")
    values = [row.delta for row in deltas]
    improved = sum(1 for value in values if value > 0.0)
    worsened = sum(1 for value in values if value < 0.0)
    tied = len(values) - improved - worsened
    ci_lower, ci_upper = bootstrap_ci(values, criteria)
    return PairedResult(
        scope=scope,
        units=len(values),
        improved=improved,
        worsened=worsened,
        tied=tied,
        mean_delta=statistics.fmean(values),
        median_delta=statistics.median(values),
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        confidence=criteria.confidence,
        bootstrap_iterations=criteria.bootstrap_iterations,
        bootstrap_seed=criteria.bootstrap_seed,
    )


@dataclass(frozen=True, slots=True)
class FamilyDirection:
    """Per-family mean delta and the agreement rate across families.

    Means use the same frozen sign convention: **positive = challenger
    improved**. A reader must be able to compare this table with the paired
    table without flipping signs.
    """

    per_family: tuple[tuple[str, int, float], ...]
    agreeing_families: int
    evaluable_families: int
    agreement_rate: float | None
    minimum_rate: float

    @property
    def satisfied(self) -> bool:
        return (
            self.agreement_rate is not None
            and self.agreement_rate >= self.minimum_rate
        )


def family_direction_agreement(
    deltas: Sequence[ClusterPairedDelta], criteria: AcceptanceCriteria
) -> FamilyDirection:
    """Measure whether the improvement direction holds across scenario families.

    A rule that wins only inside one family is memorizing that family, which is
    the failure mode the protocol exists to catch.
    """
    grouped: dict[str, list[float]] = {}
    for row in deltas:
        if not row.scenario_family_id:
            continue
        grouped.setdefault(row.scenario_family_id, []).append(row.delta)
    per_family = tuple(
        (family, len(values), statistics.fmean(values))
        for family, values in sorted(grouped.items())
    )
    agreeing = sum(1 for _, _, mean in per_family if mean > 0.0)
    rate = (agreeing / len(per_family)) if per_family else None
    return FamilyDirection(
        per_family=per_family,
        agreeing_families=agreeing,
        evaluable_families=len(per_family),
        agreement_rate=rate,
        minimum_rate=criteria.family_agreement_minimum,
    )


@dataclass(frozen=True, slots=True)
class HoldoutAdequacy:
    """Whether the holdout can support a method claim at all."""

    scope: str
    units: int
    minimum_units: int
    families_present: tuple[str, ...]
    families_missing: tuple[str, ...]

    @property
    def adequate(self) -> bool:
        return self.units >= self.minimum_units and not self.families_missing


def holdout_adequacy(
    deltas: Sequence[ScenarioPairedDelta],
    criteria: AcceptanceCriteria,
    *,
    families_present: Sequence[str] | None = None,
) -> HoldoutAdequacy:
    """Check the frozen minimum: enough **scenario draws**, and every family.

    The unit is the independent scenario draw. Decision-position clusters are
    deliberately not accepted here, because several clusters inside one scenario
    share that scenario's workload and would inflate the count.

    Below the threshold a result may only be labelled diagnostic, however
    favourable its numbers look.
    """
    if families_present is None:
        present = {
            row.scenario_family_id for row in deltas if row.scenario_family_id
        }
    else:
        present = set(families_present)
    required = set(criteria.required_families)
    return HoldoutAdequacy(
        scope=SCOPE_SCENARIO_DRAW,
        units=len(deltas),
        minimum_units=criteria.minimum_scenario_draws,
        families_present=tuple(sorted(present)),
        families_missing=tuple(sorted(required - present)),
    )


# --- latency non-inferiority ----------------------------------------------


@dataclass(frozen=True, slots=True)
class LatencyEpsilon:
    """Calibrated non-inferiority margin, derived from baseline repeat jitter.

    The margin is measured, not chosen. Picking 5% or 10% by hand is exactly
    what the ruling forbids, because it lets the tolerance be tuned to the
    observed regression.
    """

    baseline_mean: float
    baseline_repeats: int
    epsilon: float
    rule: str


def calibrate_latency_epsilon(
    baseline_repeats: Sequence[float], *, minimum_repeats: int = 3
) -> LatencyEpsilon:
    """Derive ``epsilon`` from baseline-vs-baseline repeated-run jitter.

    Rule (frozen): the largest absolute deviation of any baseline repeat from
    the baseline mean. Two identical baseline runs already differ by this much,
    so a challenger inside it has demonstrated nothing worse than run-to-run
    noise.
    """
    values = [float(value) for value in baseline_repeats]
    if len(values) < minimum_repeats:
        raise ValueError(
            f"latency epsilon needs at least {minimum_repeats} baseline "
            f"repeats, got {len(values)}"
        )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("baseline repeats must be finite")
    mean = statistics.fmean(values)
    epsilon = max(abs(value - mean) for value in values)
    return LatencyEpsilon(
        baseline_mean=mean,
        baseline_repeats=len(values),
        epsilon=epsilon,
        rule="max_absolute_deviation_from_baseline_mean",
    )


@dataclass(frozen=True, slots=True)
class LatencyCheck:
    """Whether serving latency stayed inside the calibrated margin."""

    baseline_mean: float
    challenger_mean: float
    epsilon: float
    observed_regression: float
    non_inferior: bool


def latency_non_inferior(
    *, baseline_mean: float, challenger_mean: float, epsilon: LatencyEpsilon
) -> LatencyCheck:
    """Apply the calibrated margin. The margin is not adjustable here."""
    regression = challenger_mean - baseline_mean
    return LatencyCheck(
        baseline_mean=baseline_mean,
        challenger_mean=challenger_mean,
        epsilon=epsilon.epsilon,
        observed_regression=regression,
        non_inferior=regression <= epsilon.epsilon,
    )


# --- preregistration ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RulePreregistration:
    """A rule frozen before the final holdout is materialized.

    Every field is an attestation by the author that it was fixed in advance.
    The record is data precisely so it can be committed and quoted later: the
    protocol is unenforceable if the frozen form lives only in prose.

    **Both tiers are frozen now.** A record that named only a proxy metric would
    force a runtime-metric run to be judged as Level A, and naming the runtime
    metric later -- once the data is visible -- is exactly the post-hoc move the
    protocol exists to prevent. The evaluator therefore selects a tier from the
    evidence that exists and reads the metric for that tier from here; the
    caller never names a metric.
    """

    rule_id: str
    family: str
    formula: str
    direction: str
    tie_break: str
    fallback: str
    boundary: str
    proxy_primary_metric: str
    runtime_primary_metric: str
    frozen_at: str
    frozen_commit: str

    def __post_init__(self) -> None:
        for name in (
            "rule_id",
            "family",
            "formula",
            "direction",
            "tie_break",
            "fallback",
            "boundary",
            "proxy_primary_metric",
            "runtime_primary_metric",
            "frozen_at",
            "frozen_commit",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"preregistration field {name} must be set")
        if self.proxy_primary_metric != PROXY_LOSS_VIEW:
            raise ValueError(
                f"unsupported proxy metric: {self.proxy_primary_metric!r}; "
                f"the frozen proxy loss view is {PROXY_LOSS_VIEW!r}"
            )
        if self.runtime_primary_metric != RUNTIME_LOSS_VIEW:
            raise ValueError(
                f"unsupported runtime metric: {self.runtime_primary_metric!r}; "
                f"the frozen runtime loss view is {RUNTIME_LOSS_VIEW!r}"
            )

    def metric_for_tier(self, tier: str) -> str:
        """Return the metric frozen for ``tier``; never a caller choice."""
        if tier == TIER_PROXY:
            return self.proxy_primary_metric
        if tier == TIER_RUNTIME:
            return self.runtime_primary_metric
        raise ValueError(f"unknown metric tier: {tier!r}")

    def as_payload(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "family": self.family,
            "formula": self.formula,
            "direction": self.direction,
            "tie_break": self.tie_break,
            "fallback": self.fallback,
            "boundary": self.boundary,
            # Both tiers are published so a reader can see that Level B was
            # frozen in advance rather than named after the data arrived.
            "metrics": {
                TIER_PROXY: self.proxy_primary_metric,
                TIER_RUNTIME: self.runtime_primary_metric,
            },
            "frozen_at": self.frozen_at,
            "frozen_commit": self.frozen_commit,
        }


def select_metric_tier(
    preregistration: RulePreregistration,
    *,
    runtime_evaluation: RuleEvaluation | None = None,
    proxy_evaluation: RuleEvaluation | None = None,
) -> tuple[str, str]:
    """Choose the frozen metric for the tier the evidence actually supports.

    Selection is driven by **what data exists**, not by which metric looks
    better: runtime evidence present means the runtime tier is mandatory, and
    the metric then comes from the frozen record. The chosen evaluation must be
    computed on exactly the frozen loss view for its tier, so a caller cannot
    slip in a different view under the same tier name.
    """
    if runtime_evaluation is not None:
        tier = TIER_RUNTIME
        metric = preregistration.metric_for_tier(tier)
        if runtime_evaluation.loss_view != metric:
            raise ValueError(
                f"runtime evidence must be computed on {metric!r}, got "
                f"{runtime_evaluation.loss_view!r}"
            )
        return tier, metric
    if proxy_evaluation is None:
        raise ValueError(
            "no evaluation supplied: pass proxy_evaluation and/or "
            "runtime_evaluation"
        )
    tier = TIER_PROXY
    metric = preregistration.metric_for_tier(tier)
    if proxy_evaluation.loss_view != metric:
        raise ValueError(
            f"proxy evidence must be computed on {metric!r}, got "
            f"{proxy_evaluation.loss_view!r}"
        )
    return tier, metric


@dataclass(frozen=True, slots=True)
class ImplementationAttestation:
    """The Level C human reviews. Attested, never inferred from data."""

    interface_reviewed: bool
    novelty_reviewed: bool
    runtime_overhead_bounded: bool

    @property
    def satisfied(self) -> bool:
        return (
            self.interface_reviewed
            and self.novelty_reviewed
            and self.runtime_overhead_bounded
        )


# --- the verdict ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcceptanceVerdict:
    """The protocol's decision, with every check that produced it."""

    rule_id: str
    baseline_rule_id: str
    level: str
    evidence_tier: str
    primary_metric: str
    holdout: HoldoutAdequacy
    paired: PairedResult
    diagnostic_paired: PairedResult | None
    family: FamilyDirection
    latency: LatencyCheck | None
    checks: tuple[tuple[str, bool], ...]
    failures: tuple[str, ...]
    criteria: AcceptanceCriteria

    @property
    def accepted(self) -> bool:
        return self.level in {
            LEVEL_PROXY_CANDIDATE,
            LEVEL_RUNTIME_CANDIDATE,
            LEVEL_IMPLEMENTATION_ELIGIBLE,
        }

    def as_payload(self) -> dict[str, object]:
        """Serializable form for the report and for the PR record."""
        return {
            "rule_id": self.rule_id,
            "baseline_rule_id": self.baseline_rule_id,
            "level": self.level,
            "accepted": self.accepted,
            "evidence_tier": self.evidence_tier,
            "statistical_unit": SCOPE_SCENARIO_DRAW,
            "primary_metric": self.primary_metric,
            "sign_convention": (
                "delta = baseline_loss - challenger_loss; positive = the "
                "challenger improved"
            ),
            "checks": {name: passed for name, passed in self.checks},
            "failures": list(self.failures),
            "holdout": {
                "scope": self.holdout.scope,
                "units": self.holdout.units,
                "minimum_units": self.holdout.minimum_units,
                "families_present": list(self.holdout.families_present),
                "families_missing": list(self.holdout.families_missing),
                "adequate": self.holdout.adequate,
            },
            "paired": {
                "scope": self.paired.scope,
                "units": self.paired.units,
                "improved": self.paired.improved,
                "worsened": self.paired.worsened,
                "tied": self.paired.tied,
                "mean_delta": self.paired.mean_delta,
                "median_delta": self.paired.median_delta,
                "ci_lower": self.paired.ci_lower,
                "ci_upper": self.paired.ci_upper,
                "confidence": self.paired.confidence,
                "bootstrap_iterations": self.paired.bootstrap_iterations,
                "bootstrap_seed": self.paired.bootstrap_seed,
            },
            # Reported for localisation only. Never the unit of the CI or floor.
            "paired_diagnostic_decision_position": (
                None
                if self.diagnostic_paired is None
                else {
                    "scope": self.diagnostic_paired.scope,
                    "units": self.diagnostic_paired.units,
                    "improved": self.diagnostic_paired.improved,
                    "worsened": self.diagnostic_paired.worsened,
                    "tied": self.diagnostic_paired.tied,
                    "mean_delta": self.diagnostic_paired.mean_delta,
                }
            ),
            "family_direction": {
                "per_family": [
                    {"family": family, "units": count, "mean_delta": mean}
                    for family, count, mean in self.family.per_family
                ],
                "agreeing_families": self.family.agreeing_families,
                "evaluable_families": self.family.evaluable_families,
                "agreement_rate": self.family.agreement_rate,
                "minimum_rate": self.family.minimum_rate,
                "satisfied": self.family.satisfied,
            },
            "latency": (
                None
                if self.latency is None
                else {
                    "baseline_mean": self.latency.baseline_mean,
                    "challenger_mean": self.latency.challenger_mean,
                    "epsilon": self.latency.epsilon,
                    "observed_regression": self.latency.observed_regression,
                    "non_inferior": self.latency.non_inferior,
                }
            ),
            "criteria": self.criteria.as_payload(),
        }


def evaluate_acceptance(
    *,
    preregistration: RulePreregistration,
    baseline_rule_id: str,
    proxy_evaluation: RuleEvaluation | None = None,
    runtime_evaluation: RuleEvaluation | None = None,
    criteria: AcceptanceCriteria | None = None,
    epsilon_latency: LatencyEpsilon | None = None,
    baseline_latency_mean: float | None = None,
    challenger_latency_mean: float | None = None,
    attestation: ImplementationAttestation | None = None,
) -> AcceptanceVerdict:
    """Apply the frozen protocol and return the level the rule has earned.

    The caller supplies **evidence**, never a metric. Both tier metrics are read
    from the frozen preregistration, and the tier is selected from the evidence
    that exists: runtime evidence present forces the runtime tier. That is what
    makes a post-hoc metric swap impossible once data is visible.

    ``epsilon_latency`` must be calibrated separately from baseline repeats; the
    margin is never chosen here.
    """
    resolved = criteria or AcceptanceCriteria()
    challenger_rule_id = preregistration.rule_id
    tier, metric = select_metric_tier(
        preregistration,
        runtime_evaluation=runtime_evaluation,
        proxy_evaluation=proxy_evaluation,
    )
    evaluation = (
        runtime_evaluation if tier == TIER_RUNTIME else proxy_evaluation
    )
    assert evaluation is not None  # guaranteed by select_metric_tier

    deltas = scenario_paired_deltas(
        evaluation,
        baseline_rule_id=baseline_rule_id,
        challenger_rule_id=challenger_rule_id,
    )
    paired = paired_result(deltas, resolved, scope=SCOPE_SCENARIO_DRAW)
    family = family_direction_agreement(deltas, resolved)
    holdout = holdout_adequacy(deltas, resolved)
    diagnostic_paired = paired_result(
        cluster_paired_deltas(
            evaluation,
            baseline_rule_id=baseline_rule_id,
            challenger_rule_id=challenger_rule_id,
        ),
        resolved,
        scope=SCOPE_DECISION_CLUSTER,
    )

    latency: LatencyCheck | None = None
    if (
        epsilon_latency is not None
        and baseline_latency_mean is not None
        and challenger_latency_mean is not None
    ):
        latency = latency_non_inferior(
            baseline_mean=baseline_latency_mean,
            challenger_mean=challenger_latency_mean,
            epsilon=epsilon_latency,
        )

    checks: list[tuple[str, bool]] = [
        ("holdout_adequate", holdout.adequate),
        ("scenario_mean_improvement_positive", paired.mean_delta > 0.0),
        ("scenario_ci_lower_bound_positive", paired.ci_lower_above_zero),
        ("better_draws_outnumber_worse", paired.better_than_worse),
        ("family_direction_agreement", family.satisfied),
    ]

    is_runtime_tier = tier == TIER_RUNTIME
    if is_runtime_tier:
        # Serving latency must not regress beyond the calibrated margin.
        checks.append(
            ("latency_non_inferior", latency is not None and latency.non_inferior)
        )

    failures = tuple(name for name, passed in checks if not passed)

    if not holdout.adequate:
        # A claim needs the minimum sample; below it the only honest label is
        # that the result is diagnostic.
        level = LEVEL_DIAGNOSTIC_ONLY
    elif failures:
        level = LEVEL_NOT_ACCEPTED
    elif is_runtime_tier:
        level = LEVEL_RUNTIME_CANDIDATE
    else:
        level = LEVEL_PROXY_CANDIDATE

    if (
        level == LEVEL_RUNTIME_CANDIDATE
        and attestation is not None
        and attestation.satisfied
    ):
        level = LEVEL_IMPLEMENTATION_ELIGIBLE

    return AcceptanceVerdict(
        rule_id=challenger_rule_id,
        baseline_rule_id=baseline_rule_id,
        level=level,
        evidence_tier=tier,
        primary_metric=metric,
        holdout=holdout,
        paired=paired,
        diagnostic_paired=diagnostic_paired,
        family=family,
        latency=latency,
        checks=tuple(checks),
        failures=failures,
        criteria=resolved,
    )
