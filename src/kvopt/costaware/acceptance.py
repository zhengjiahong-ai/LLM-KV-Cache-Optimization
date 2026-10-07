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

#: Primary metric names. The metric decides which level a rule is eligible for.
PRIMARY_METRIC_PROXY_LOSS = "cluster_mean_proxy_loss"
PRIMARY_METRIC_RECOMPUTED_TOKENS = "cluster_mean_recomputed_prefill_tokens"

#: The six formal scenarios defined by M6. A holdout that does not cover all of
#: them cannot support a method claim, however many clusters it contains.
FORMAL_FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6")


@dataclass(frozen=True, slots=True)
class AcceptanceCriteria:
    """The frozen protocol. Change requires a new M1 ruling, not an edit here."""

    minimum_clusters: int = 30
    required_families: tuple[str, ...] = FORMAL_FAMILIES
    family_agreement_minimum: float = 2.0 / 3.0
    bootstrap_iterations: int = 10_000
    bootstrap_seed: int = 20_261_007
    confidence: float = 0.95

    def as_payload(self) -> dict[str, object]:
        """Serializable form, so a report records the protocol it applied."""
        return {
            "minimum_clusters": self.minimum_clusters,
            "required_families": list(self.required_families),
            "family_agreement_minimum": self.family_agreement_minimum,
            "bootstrap_iterations": self.bootstrap_iterations,
            "bootstrap_seed": self.bootstrap_seed,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ClusterPairedDelta:
    """One cluster's paired loss difference: baseline minus challenger.

    Positive means the challenger released a cheaper set. The cluster is the
    unit of resampling, so each appears exactly once regardless of seed count.
    """

    scenario_group: str
    decision_event_index: int
    scenario_family_id: str | None
    baseline_loss: float
    challenger_loss: float
    delta: float


def cluster_paired_deltas(
    evaluation: RuleEvaluation,
    *,
    baseline_rule_id: str,
    challenger_rule_id: str,
) -> tuple[ClusterPairedDelta, ...]:
    """Per-cluster paired deltas, seeds averaged inside each cluster.

    This exposes the individual observations the protocol resamples. Averaging
    inside the cluster first is what stops repeated seeds from inflating the
    sample, and it keeps the paired counts summing to the cluster count.
    """
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

    baseline = losses[baseline_rule_id]
    challenger = losses[challenger_rule_id]
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


@dataclass(frozen=True, slots=True)
class ClusterPairedResult:
    """Cluster-level paired summary with a bootstrap interval."""

    clusters: int
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


def bootstrap_cluster_ci(
    deltas: Sequence[float], criteria: AcceptanceCriteria
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean delta, resampling clusters.

    The seed is part of the frozen protocol, so the interval is reproducible
    rather than re-drawn until it looks favourable.
    """
    if not deltas:
        raise ValueError("bootstrap requires at least one cluster")
    rng = random.Random(criteria.bootstrap_seed)
    count = len(deltas)
    means: list[float] = []
    for _ in range(criteria.bootstrap_iterations):
        resampled = [deltas[rng.randrange(count)] for _ in range(count)]
        means.append(statistics.fmean(resampled))
    means.sort()
    tail = (1.0 - criteria.confidence) / 2.0
    return _percentile(means, tail), _percentile(means, 1.0 - tail)


def cluster_paired_result(
    deltas: Sequence[ClusterPairedDelta], criteria: AcceptanceCriteria
) -> ClusterPairedResult:
    """Summarize cluster deltas under the frozen protocol."""
    if not deltas:
        raise ValueError("at least one cluster is required")
    values = [row.delta for row in deltas]
    improved = sum(1 for value in values if value > 0.0)
    worsened = sum(1 for value in values if value < 0.0)
    tied = len(values) - improved - worsened
    ci_lower, ci_upper = bootstrap_cluster_ci(values, criteria)
    return ClusterPairedResult(
        clusters=len(values),
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
    """Per-family cluster-level mean delta and the agreement rate across them."""

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

    clusters: int
    minimum_clusters: int
    families_present: tuple[str, ...]
    families_missing: tuple[str, ...]

    @property
    def adequate(self) -> bool:
        return (
            self.clusters >= self.minimum_clusters
            and not self.families_missing
        )


def holdout_adequacy(
    deltas: Sequence[ClusterPairedDelta],
    criteria: AcceptanceCriteria,
    *,
    families_present: Sequence[str] | None = None,
) -> HoldoutAdequacy:
    """Check the frozen minimum: enough clusters, and every formal family.

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
        clusters=len(deltas),
        minimum_clusters=criteria.minimum_clusters,
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
    """

    rule_id: str
    family: str
    formula: str
    direction: str
    tie_break: str
    fallback: str
    boundary: str
    primary_metric: str
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
            "primary_metric",
            "frozen_at",
            "frozen_commit",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"preregistration field {name} must be set")
        if self.primary_metric not in {
            PRIMARY_METRIC_PROXY_LOSS,
            PRIMARY_METRIC_RECOMPUTED_TOKENS,
        }:
            raise ValueError(
                f"unsupported primary metric: {self.primary_metric!r}"
            )

    def as_payload(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "family": self.family,
            "formula": self.formula,
            "direction": self.direction,
            "tie_break": self.tie_break,
            "fallback": self.fallback,
            "boundary": self.boundary,
            "primary_metric": self.primary_metric,
            "frozen_at": self.frozen_at,
            "frozen_commit": self.frozen_commit,
        }


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
    primary_metric: str
    holdout: HoldoutAdequacy
    paired: ClusterPairedResult
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
            "primary_metric": self.primary_metric,
            "checks": {name: passed for name, passed in self.checks},
            "failures": list(self.failures),
            "holdout": {
                "clusters": self.holdout.clusters,
                "minimum_clusters": self.holdout.minimum_clusters,
                "families_present": list(self.holdout.families_present),
                "families_missing": list(self.holdout.families_missing),
                "adequate": self.holdout.adequate,
            },
            "cluster_paired": {
                "clusters": self.paired.clusters,
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
            "family_direction": {
                "per_family": [
                    {"family": family, "clusters": count, "mean_delta": mean}
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
    evaluation: RuleEvaluation,
    *,
    preregistration: RulePreregistration,
    baseline_rule_id: str,
    criteria: AcceptanceCriteria | None = None,
    epsilon_latency: LatencyEpsilon | None = None,
    baseline_latency_mean: float | None = None,
    challenger_latency_mean: float | None = None,
    attestation: ImplementationAttestation | None = None,
) -> AcceptanceVerdict:
    """Apply the frozen protocol and return the level the rule has earned.

    The primary metric comes from the preregistration, not from the caller, so
    the metric cannot be swapped after a result is known. ``epsilon_latency``
    must be calibrated separately from baseline repeats; the margin is never
    chosen here.
    """
    resolved = criteria or AcceptanceCriteria()
    challenger_rule_id = preregistration.rule_id

    deltas = cluster_paired_deltas(
        evaluation,
        baseline_rule_id=baseline_rule_id,
        challenger_rule_id=challenger_rule_id,
    )
    paired = cluster_paired_result(deltas, resolved)
    family = family_direction_agreement(deltas, resolved)
    holdout = holdout_adequacy(deltas, resolved)

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
        ("cluster_mean_improvement_positive", paired.mean_delta > 0.0),
        ("cluster_ci_lower_bound_positive", paired.ci_lower_above_zero),
        ("better_decisions_outnumber_worse", paired.better_than_worse),
        ("family_direction_agreement", family.satisfied),
    ]

    is_runtime_metric = (
        preregistration.primary_metric == PRIMARY_METRIC_RECOMPUTED_TOKENS
    )
    if is_runtime_metric:
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
    elif is_runtime_metric:
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
        primary_metric=preregistration.primary_metric,
        holdout=holdout,
        paired=paired,
        family=family,
        latency=latency,
        checks=tuple(checks),
        failures=failures,
        criteria=resolved,
    )
