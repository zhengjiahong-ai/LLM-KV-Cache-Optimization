"""Offline evaluation of candidate rules against the canonical M6 proxy loss.

Design intent
-------------

The evaluator does not re-implement regret. It rebuilds each rule's release
set, marks it as ``selected``, and feeds the result through
:func:`kvopt.profiling.analysis.build_decision_regret_table`, which is the same
set-aware implementation that produced the canonical M6
``decision_regret`` table. Regret for a rule is therefore directly comparable
to the canonical executed-P1B regret.

Study discipline required by
``docs/phase2a-m4-method-design-input.md``:

- section 9: family-level holdout and paired per-decision comparison;
- section 10: degeneracy audit, including rank-identity between rules and the
  linear-cost collapse check.

This module never calls a model, a GPU, or vLLM. It is pure offline analysis
over already-persisted decision artifacts.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from kvopt.profiling.analysis import (
    CandidateLossRow,
    DecisionRegretRow,
    build_decision_regret_table,
)
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.loss_views import CandidateLossEvidenceRow

from .feasible_oracle import (
    FeasibleOracleRow,
    PressureFeasibleRegretRow,
    build_feasible_oracle,
    pressure_feasible_regret,
)
from .replay import (
    CandidateKey,
    DecisionSnapshot,
    ReplayOutcome,
    RuleStrategy,
    candidate_key,
    replay_decision,
)
from .rules import CANDIDATE_RULES, CandidateRule

#: The canonical loss view authorized for offline method design.
CANONICAL_LOSS_VIEW = "planned_return_weighted_prefill_proxy"


def _identity(row: DecisionCandidateRow) -> tuple[str, str]:
    return (row.program_id, row.prefix_id)


@dataclass(frozen=True, slots=True)
class RuleDecisionOutcome:
    """One rule's regret result for one decision.

    ``candidate_loss_tied`` is True when every candidate has the same loss, so no
    choice can matter. This is the M6 notion of a tied decision, and it is
    deliberately independent of whether *this rule* captured the available
    headroom: conflating the two would make the misselection rate hide decisions
    where headroom exists but the rule failed to take it.
    """

    rule_id: str
    run_id: str
    decision_event_index: int
    scenario_family_id: str | None
    candidate_count: int
    selection_count: int
    loss_view: str
    selected_identities: tuple[tuple[str, str], ...]
    selected_loss: float
    hindsight_best_loss: float
    absolute_regret: float
    normalized_regret: float
    selected_is_hindsight_best: bool
    candidate_loss_tied: bool
    target: int = 0
    """The shared ``required_blocks`` target this decision had to satisfy."""
    satisfied: bool = True
    """False when the rule was exhausted before reaching the target."""
    eligible_blocks_initial: int = 0
    eligible_blocks_final: int = 0


@dataclass(frozen=True, slots=True)
class RuleAggregate:
    """Aggregate behaviour of one rule across decisions.

    Two denominator conventions are reported side by side and **must not be
    mixed** (M1 ruling, Q9):

    - ``loss_discriminating_decisions`` counts decisions whose candidate losses
      are not all equal. This is the M4 diagnostic denominator: the decision is
      one the choice *can* affect. It is deliberately **not** called canonical
      ``non_tied``.
    - ``canonical_non_tied_decisions`` follows the canonical M6 definition,
      where a decision is non-tied only when its hindsight-optimal release set is
      unique (``hindsight_best_set_count == 1``). It is computed only over
      decisions where the rule released the same number of entries as observed,
      because the canonical optimum is defined for that count.
    """

    rule_id: str
    family: str
    decisions: int
    loss_discriminating_decisions: int
    positive_regret_decisions: int
    positive_regret_rate: float | None
    canonical_applicable_decisions: int
    canonical_non_tied_decisions: int
    canonical_positive_regret_decisions: int
    canonical_misselection_rate: float | None
    mean_absolute_regret: float
    mean_normalized_regret: float
    tie_rate: float


@dataclass(frozen=True, slots=True)
class ReleaseBurdenRow:
    """How many releases a rule needs to satisfy the shared target.

    Release count is a first-class outcome under the real pressure constraint:
    two rules can reach the same ``required_blocks`` with different numbers of
    releases, and released entries are what incur proxy loss.
    """

    rule_id: str
    decisions: int
    mean_target: float
    mean_releases: float
    mean_releases_vs_baseline: float
    saturated_decisions: int
    """Decisions where the rule needed more releases than the baseline."""
    frugal_decisions: int
    """Decisions where the rule needed fewer releases than the baseline."""
    unsatisfied_decisions: int = 0
    """Decisions where the rule was exhausted before reaching the target."""


@dataclass(frozen=True, slots=True)
class PressureFeasibleAggregate:
    """Per-rule summary against the pressure-feasible oracle.

    This is the M4 method-selection metric. The canonical M6 size-matched regret
    is retained separately for provenance.

    Frozen metric order (M1 ruling, Q11), because ``oracle_loss`` is exactly zero
    on 24/60 decisions and normalised regret degenerates towards 0/1 there:

    1. mean / median absolute regret
    2. paired selected-loss delta versus the baseline
    3. better / worse / tied decision counts
    4. zero-regret rate
    5. normalised regret - secondary and sensitivity only

    A decision counts as **not improving** only when its absolute regret is
    positive. Selecting a different but equally optimal set is not a
    misselection.
    """

    rule_id: str
    decisions: int
    mean_absolute_regret: float
    median_absolute_regret: float
    zero_regret_rate: float
    positive_regret_decisions: int
    better_than_baseline_decisions: int
    worse_than_baseline_decisions: int
    tied_with_baseline_decisions: int
    mean_paired_loss_delta_vs_baseline: float
    mean_entry_count_delta: float
    # Released entries minus the oracle's; positive means less efficient.
    mean_normalized_regret: float
    # Secondary only: degenerate when ``oracle_loss`` is zero.


@dataclass(frozen=True, slots=True)
class DegeneracyAuditRow:
    """Rank-identity audit between one rule pair over shared decisions."""

    rule_a: str
    rule_b: str
    shared_decisions: int
    identical_selection_count: int
    identical_selection_rate: float | None


@dataclass(frozen=True, slots=True)
class DenominatorDiagnosticRow:
    """One decision's evidence for the handoff section 10c sub-question.

    Section 10c asks whether dividing by the reclaimable-block count cancels the
    useful cost signal. If the metadata denominator moves in lockstep with the
    cost numerator, the ratio stops being a cost measure and becomes noise.
    """

    run_id: str
    decision_event_index: int
    candidate_count: int
    denominator_is_constant: bool
    """True when every candidate frees the same number of blocks."""
    numerator_denominator_spearman: float | None
    """Within-decision rank association between cost and the denominator."""
    rank_inversions: int
    """Pairs whose order flips when the denominator is applied."""
    comparable_pairs: int


@dataclass(frozen=True, slots=True)
class AblationRow:
    """One feature on/off comparison built from existing rule pairs."""

    variant: str
    changes: str
    shared_decisions: int
    identical_selection_rate: float | None
    mean_normalized_regret: float
    baseline_mean_normalized_regret: float


@dataclass(frozen=True, slots=True)
class BehaviourBreakdown:
    """Aggregates for one rule, split by one contextual dimension.

    Uses the M4 **diagnostic** denominator (``candidate_loss_tied``), i.e. "the
    choice can affect this decision". It is deliberately not named
    ``non_tied``; the canonical M6 view lives on ``RuleAggregate.canonical_*``.
    """

    rule_id: str
    dimension: str
    bucket: str
    decisions: int
    loss_discriminating_decisions: int
    positive_regret_decisions: int
    positive_regret_rate: float | None
    mean_absolute_regret: float
    mean_normalized_regret: float


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """Full offline evaluation result for one loss view."""

    loss_view: str
    evaluated_decisions: int
    skipped_decisions: int
    available_candidates: int
    aggregates: tuple[RuleAggregate, ...]
    outcomes: tuple[RuleDecisionOutcome, ...]
    degeneracy: tuple[DegeneracyAuditRow, ...]
    release_burden: tuple[ReleaseBurdenRow, ...] = ()
    unsatisfied_decisions: int = 0
    oracle_rows: tuple[FeasibleOracleRow, ...] = ()
    feasible_regret_rows: tuple[PressureFeasibleRegretRow, ...] = ()
    pressure_feasible_aggregates: tuple[PressureFeasibleAggregate, ...] = ()
    clusters: tuple[ScenarioClusterRow, ...] = ()

    @property
    def effective_cluster_count(self) -> int:
        """Distinct scenario-cluster decisions, the non-inflated sample size.

        Seeds are near-replicas under the planned proxy (Q10), so this is much
        smaller than ``evaluated_decisions`` and is the honest unit count for
        any cluster-level claim.
        """
        return len(self.clusters)

    @property
    def clusters_identical_across_seeds(self) -> int:
        """Clusters whose loss profile is the same in every represented seed."""
        return sum(
            1 for cluster in self.clusters
            if cluster.loss_profile_identical_across_seeds
        )

    @property
    def decision_pattern_counts(self) -> tuple[tuple[tuple[float, ...], int], ...]:
        """Cluster occurrences per identical decision problem (Q10)."""
        return decision_pattern_counts(self.clusters)

    @property
    def unique_decision_pattern_count(self) -> int:
        """Distinct decision problems actually posed, the tightest sample size.

        Q10 asks for this explicitly. It is at most ``effective_cluster_count``
        and is smaller whenever two scenarios present the same candidate loss
        multiset, which means a deterministic rule cannot behave differently on
        them and they carry no separate evidence.
        """
        return len(self.decision_pattern_counts)

    def for_rule(self, rule_id: str) -> RuleAggregate:
        for aggregate in self.aggregates:
            if aggregate.rule_id == rule_id:
                return aggregate
        raise KeyError(f"rule {rule_id!r} not present in evaluation")

    def feasible_for_rule(self, rule_id: str) -> PressureFeasibleAggregate:
        for aggregate in self.pressure_feasible_aggregates:
            if aggregate.rule_id == rule_id:
                return aggregate
        raise KeyError(
            f"rule {rule_id!r} not present in the pressure-feasible aggregates"
        )

    def burden_for_rule(self, rule_id: str) -> ReleaseBurdenRow:
        for row in self.release_burden:
            if row.rule_id == rule_id:
                return row
        raise KeyError(f"rule {rule_id!r} not present in release burden")


def _usable_evidence(
    evidence: Iterable[CandidateLossEvidenceRow], loss_view: str
) -> dict[tuple[str, int], dict[tuple[str, str], float]]:
    """Group available candidate losses by decision."""
    grouped: dict[tuple[str, int], dict[tuple[str, str], float]] = defaultdict(dict)
    for row in evidence:
        if row.loss_view != loss_view or row.availability != "available":
            continue
        if row.loss is None:
            continue
        key = (row.run_id, row.decision_event_index)
        grouped[key][(row.program_id, row.prefix_id)] = float(row.loss)
    return grouped


def _executed_selection(
    candidates: Iterable[DecisionCandidateRow],
) -> dict[tuple[str, int], set[tuple[str, str]]]:
    grouped: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
    for row in candidates:
        if row.selected:
            grouped[(row.run_id, row.decision_event_index)].add(_identity(row))
    return grouped


def _canonical_regret(
    rows: Iterable[DecisionRegretRow],
) -> dict[tuple[str, int], DecisionRegretRow]:
    return {(row.run_id, row.decision_event_index): row for row in rows}


def evaluate_rules(
    *,
    candidates: Sequence[DecisionCandidateRow],
    evidence: Sequence[CandidateLossEvidenceRow],
    snapshots: Sequence[DecisionSnapshot],
    canonical_regret: Sequence[DecisionRegretRow] = (),
    families_by_run: dict[str, str | None] | None = None,
    rules: Sequence[CandidateRule] = CANDIDATE_RULES,
    loss_view: str = CANONICAL_LOSS_VIEW,
    included_runs: frozenset[str] | None = None,
) -> RuleEvaluation:
    """Evaluate every rule under the real pressure constraint.

    Each rule replays the frozen forced-release loop against the **same**
    ``required_blocks`` target: surviving entries are re-ranked every iteration
    and the eligible set is recomputed from block ownership after each release.
    Release count is therefore an outcome, not an input.

    A decision participates only when every candidate has evidence under
    ``loss_view`` and a raw snapshot is available. A rule that cannot reach the
    target even after releasing every entry is recorded as unsatisfied and
    excluded from the regret aggregates, never silently accepted.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TypeError("candidates must be an ordered sequence")
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
        raise TypeError("evidence must be an ordered sequence")

    grouped_losses = _usable_evidence(evidence, loss_view)
    executed = _executed_selection(candidates)
    canonical = _canonical_regret(canonical_regret)
    family_lookup = families_by_run or {}
    snapshot_by_decision: dict[tuple[str, int], DecisionSnapshot] = {
        (snapshot.run_id, snapshot.decision_event_index): snapshot
        for snapshot in snapshots
    }

    by_decision: dict[tuple[str, int], list[DecisionCandidateRow]] = defaultdict(list)
    for row in candidates:
        by_decision[(row.run_id, row.decision_event_index)].append(row)

    strategies = [RuleStrategy(rule) for rule in rules]
    outcomes: dict[str, list[RuleDecisionOutcome]] = defaultdict(list)
    replays: dict[str, list[ReplayOutcome]] = defaultdict(list)
    selections: dict[str, dict[tuple[str, int], tuple[tuple[str, str], ...]]] = defaultdict(dict)
    evaluated = 0
    skipped = 0
    unsatisfied = 0
    available_candidate_total = 0

    for decision_key in sorted(grouped_losses):
        run_id, decision_event_index = decision_key
        if included_runs is not None and run_id not in included_runs:
            continue
        losses = grouped_losses[decision_key]
        if len(losses) < 2:
            skipped += 1
            continue
        group = list(by_decision.get(decision_key, ()))
        if len(group) != len(losses):
            # Comparable only when every candidate has evidence for this view.
            # Evaluating a subset would silently understate the hindsight best
            # and break the "never coerce missingness" rule.
            skipped += 1
            continue
        snapshot = snapshot_by_decision.get(decision_key)
        if snapshot is None or not executed[decision_key]:
            skipped += 1
            continue

        evaluated += 1
        available_candidate_total += len(group)
        rows_by_key = {candidate_key(row): row for row in group}
        for strategy in strategies:
            replay_outcome = replay_decision(snapshot, strategy, rows_by_key)
            replays[strategy.strategy_id].append(replay_outcome)
            chosen = replay_outcome.released
            selections[strategy.strategy_id][decision_key] = chosen
            if not replay_outcome.satisfied:
                unsatisfied += 1
                continue
            selected_set = set(chosen)
            loss_rows = [
                CandidateLossRow(
                    run_id=run_id,
                    decision_event_index=decision_event_index,
                    program_id=row.program_id,
                    prefix_id=row.prefix_id,
                    loss_view=loss_view,
                    loss=losses[_identity(row)],
                    selected=_identity(row) in selected_set,
                )
                for row in group
            ]
            regret_row = build_decision_regret_table(loss_rows)[0]
            outcomes[strategy.strategy_id].append(
                RuleDecisionOutcome(
                    rule_id=strategy.strategy_id,
                    run_id=run_id,
                    decision_event_index=decision_event_index,
                    scenario_family_id=family_lookup.get(run_id),
                    candidate_count=len(group),
                    selection_count=len(chosen),
                    loss_view=loss_view,
                    selected_identities=chosen,
                    selected_loss=regret_row.selected_loss,
                    hindsight_best_loss=regret_row.hindsight_best_loss,
                    absolute_regret=regret_row.absolute_regret,
                    normalized_regret=regret_row.normalized_regret,
                    selected_is_hindsight_best=regret_row.selected_is_hindsight_best,
                    candidate_loss_tied=len({losses[_identity(row)] for row in group}) == 1,
                    target=replay_outcome.target,
                    satisfied=replay_outcome.satisfied,
                    eligible_blocks_initial=replay_outcome.eligible_blocks_initial,
                    eligible_blocks_final=replay_outcome.eligible_blocks_final,
                )
            )

    observed_counts = {key: len(value) for key, value in executed.items()}
    aggregates = tuple(
        _aggregate(rule, outcomes[rule.rule_id], canonical, observed_counts)
        for rule in rules
    )
    oracle_losses = _oracle_loss_map(grouped_losses)
    oracle_rows = build_feasible_oracle(
        snapshots,
        oracle_losses,
        loss_view=loss_view,
        included_runs=included_runs,
    )
    feasible_rows = pressure_feasible_regret(
        oracle_rows=oracle_rows,
        selections=selections,
        losses=oracle_losses,
        loss_view=loss_view,
    )
    feasible_aggregates = _feasible_aggregates(
        rules, oracle_rows, feasible_rows
    )
    return RuleEvaluation(
        loss_view=loss_view,
        evaluated_decisions=evaluated,
        skipped_decisions=skipped,
        available_candidates=available_candidate_total,
        aggregates=aggregates,
        outcomes=tuple(
            outcome for rule in rules for outcome in outcomes[rule.rule_id]
        ),
        degeneracy=_rank_identity(selections, rules, canonical=canonical),
        release_burden=_release_burden(rules, replays, executed),
        unsatisfied_decisions=unsatisfied,
        oracle_rows=oracle_rows,
        feasible_regret_rows=feasible_rows,
        pressure_feasible_aggregates=feasible_aggregates,
        clusters=scenario_clusters(
            [
                snapshot
                for snapshot in snapshots
                if included_runs is None or snapshot.run_id in included_runs
            ],
            oracle_losses,
        ),
    )


def _oracle_loss_map(
    grouped_losses: dict[tuple[str, int], dict[tuple[str, str], float]],
) -> dict[tuple[str, int, tuple[str, str]], float]:
    """Re-key candidate losses to ``(run_id, decision_event_index, identity)``."""
    return {
        (run_id, decision_event_index, identity): loss
        for (run_id, decision_event_index), losses in grouped_losses.items()
        for identity, loss in losses.items()
    }


def _feasible_aggregates(
    rules: Sequence[CandidateRule],
    oracle_rows: Sequence[FeasibleOracleRow],
    feasible_rows: Sequence[PressureFeasibleRegretRow],
) -> tuple[PressureFeasibleAggregate, ...]:
    """Aggregate each rule's distance from the feasibility-aware optimum.

    Ordered per the frozen Q11 metric priority. A decision is only counted as
    not-improving when its absolute regret is positive, so choosing a different
    but equally optimal set is not penalised.
    """
    del oracle_rows
    grouped: dict[str, list[PressureFeasibleRegretRow]] = defaultdict(list)
    for row in feasible_rows:
        grouped[row.rule_id].append(row)

    baseline_id = "M0_p1b_executed_ordering"
    baseline_loss = {
        (row.run_id, row.decision_event_index): row.selected_loss
        for row in grouped.get(baseline_id, [])
    }

    aggregates: list[PressureFeasibleAggregate] = []
    for rule in rules:
        rows = grouped.get(rule.rule_id, [])
        if not rows:
            continue
        positive = [row for row in rows if row.absolute_regret > 0.0]
        better = worse = tied = 0
        deltas: list[float] = []
        for row in rows:
            reference = baseline_loss.get(
                (row.run_id, row.decision_event_index)
            )
            if reference is None:
                continue
            delta = reference - row.selected_loss
            deltas.append(delta)
            if math.isclose(delta, 0.0, abs_tol=1e-12):
                tied += 1
            elif delta > 0.0:
                better += 1
            else:
                worse += 1
        aggregates.append(
            PressureFeasibleAggregate(
                rule_id=rule.rule_id,
                decisions=len(rows),
                mean_absolute_regret=statistics.fmean(
                    row.absolute_regret for row in rows
                ),
                median_absolute_regret=statistics.median(
                    row.absolute_regret for row in rows
                ),
                zero_regret_rate=(
                    sum(1 for row in rows if row.absolute_regret == 0.0)
                    / len(rows)
                ),
                positive_regret_decisions=len(positive),
                better_than_baseline_decisions=better,
                worse_than_baseline_decisions=worse,
                tied_with_baseline_decisions=tied,
                mean_paired_loss_delta_vs_baseline=(
                    statistics.fmean(deltas) if deltas else float("nan")
                ),
                mean_entry_count_delta=statistics.fmean(
                    row.entry_count_delta for row in rows
                ),
                mean_normalized_regret=statistics.fmean(
                    row.normalized_regret for row in rows
                ),
            )
        )
    return tuple(aggregates)


def _release_burden(
    rules: Sequence[CandidateRule],
    replays: dict[str, list[ReplayOutcome]],
    executed: dict[tuple[str, int], set[tuple[str, str]]],
) -> tuple[ReleaseBurdenRow, ...]:
    """Summarize how many releases each rule needs for the shared target.

    The reference is the **observed** baseline release count from the artifacts,
    not a replayed one, so the comparison is against what the runtime actually
    did.
    """
    baseline_counts = {key: len(value) for key, value in executed.items()}
    rows: list[ReleaseBurdenRow] = []
    for rule in rules:
        rule_replays = replays.get(rule.rule_id, [])
        if not rule_replays:
            continue
        deltas: list[float] = []
        saturated = 0
        frugal = 0
        unsatisfied = 0
        for replay_outcome in rule_replays:
            if not replay_outcome.satisfied:
                unsatisfied += 1
            baseline = baseline_counts.get(
                (replay_outcome.run_id, replay_outcome.decision_event_index)
            )
            if baseline is None:
                continue
            delta = len(replay_outcome.released) - baseline
            deltas.append(float(delta))
            if delta > 0:
                saturated += 1
            elif delta < 0:
                frugal += 1
        if not deltas:
            continue
        rows.append(
            ReleaseBurdenRow(
                rule_id=rule.rule_id,
                decisions=len(rule_replays),
                mean_target=statistics.fmean(
                    item.target for item in rule_replays
                ),
                mean_releases=statistics.fmean(
                    len(item.released) for item in rule_replays
                ),
                mean_releases_vs_baseline=statistics.fmean(deltas),
                saturated_decisions=saturated,
                frugal_decisions=frugal,
                unsatisfied_decisions=unsatisfied,
            )
        )
    return tuple(rows)


def _aggregate(
    rule: CandidateRule,
    outcomes: Sequence[RuleDecisionOutcome],
    canonical: dict[tuple[str, int], DecisionRegretRow],
    observed_counts: dict[tuple[str, int], int],
) -> RuleAggregate:
    """Summarize one rule, keeping the two tie conventions apart (Q9)."""
    if not outcomes:
        return RuleAggregate(
            rule_id=rule.rule_id,
            family=rule.family,
            decisions=0,
            loss_discriminating_decisions=0,
            positive_regret_decisions=0,
            positive_regret_rate=None,
            canonical_applicable_decisions=0,
            canonical_non_tied_decisions=0,
            canonical_positive_regret_decisions=0,
            canonical_misselection_rate=None,
            mean_absolute_regret=float("nan"),
            mean_normalized_regret=float("nan"),
            tie_rate=float("nan"),
        )

    # M4 diagnostic denominator: the choice can affect the decision at all.
    discriminating = [row for row in outcomes if not row.candidate_loss_tied]
    discriminating_worse = [
        row for row in discriminating if not row.selected_is_hindsight_best
    ]

    # Canonical M6 denominator: the hindsight-optimal release set is unique.
    # Only comparable when the rule released the observed number of entries.
    applicable: list[RuleDecisionOutcome] = []
    for row in outcomes:
        key = (row.run_id, row.decision_event_index)
        canonical_row = canonical.get(key)
        if canonical_row is None:
            continue
        if observed_counts.get(key) != row.selection_count:
            continue
        applicable.append(row)
    canonical_non_tied = [
        row
        for row in applicable
        if canonical[
            (row.run_id, row.decision_event_index)
        ].hindsight_best_set_count
        == 1
    ]
    canonical_worse = [
        row for row in canonical_non_tied if not row.selected_is_hindsight_best
    ]

    return RuleAggregate(
        rule_id=rule.rule_id,
        family=rule.family,
        decisions=len(outcomes),
        loss_discriminating_decisions=len(discriminating),
        positive_regret_decisions=len(discriminating_worse),
        positive_regret_rate=(
            len(discriminating_worse) / len(discriminating)
            if discriminating
            else None
        ),
        canonical_applicable_decisions=len(applicable),
        canonical_non_tied_decisions=len(canonical_non_tied),
        canonical_positive_regret_decisions=len(canonical_worse),
        canonical_misselection_rate=(
            len(canonical_worse) / len(canonical_non_tied)
            if canonical_non_tied
            else None
        ),
        mean_absolute_regret=statistics.fmean(row.absolute_regret for row in outcomes),
        mean_normalized_regret=statistics.fmean(
            row.normalized_regret for row in outcomes
        ),
        tie_rate=(
            sum(1 for row in outcomes if row.candidate_loss_tied) / len(outcomes)
        ),
    )


@dataclass(frozen=True, slots=True)
class ScenarioClusterRow:
    """One scenario-cluster summary row (M1 ruling, Q10).

    Seeds were supplied to the runtime but the canonical loss is the planned
    proxy, which is driven by pre-designed scenario timing / prefix / return
    patterns. The three seeds are therefore near-replicas of one another, so the
    60 decision rows are not 60 independent observations. Clustering by
    (scenario group, decision position) gives the effective sample size.
    """

    scenario_group: str
    decision_event_index: int
    seed_count: int
    loss_profile_identical_across_seeds: bool
    decision_pattern: tuple[float, ...] = ()
    """Sorted canonical loss multiset of the decision's candidate set.

    Two clusters with the same pattern pose the *same* decision problem: the
    rule sees the same number of candidates with the same loss multiset, so any
    deterministic rule must behave identically. This is what allows the report
    to state the unique decision-pattern count required by Q10, which is
    smaller than the cluster count.
    """


def scenario_clusters(
    snapshots: Sequence[DecisionSnapshot],
    losses: Mapping[tuple[str, int, CandidateKey], float],
) -> tuple[ScenarioClusterRow, ...]:
    """Group decisions by scenario family-spec and decision position (Q10)."""
    grouped: dict[tuple[str, int], list[str]] = defaultdict(list)
    profiles: dict[tuple[str, int], set[tuple[float, ...]]] = defaultdict(set)
    for snapshot in snapshots:
        group = _scenario_group(snapshot.run_id)
        key = (group, snapshot.decision_event_index)
        grouped[key].append(snapshot.run_id)
        values = []
        for candidate in snapshot.candidate_keys:
            value = losses.get(
                (snapshot.run_id, snapshot.decision_event_index, candidate)
            )
            if value is None:
                values = []
                break
            values.append(round(float(value), 12))
        if values:
            profiles[key].add(tuple(sorted(values)))

    rows: list[ScenarioClusterRow] = []
    for key in sorted(grouped):
        run_ids = grouped[key]
        row_profiles = sorted(profiles.get(key, set()))
        rows.append(
            ScenarioClusterRow(
                scenario_group=key[0],
                decision_event_index=key[1],
                seed_count=len(run_ids),
                loss_profile_identical_across_seeds=len(row_profiles) <= 1,
                decision_pattern=(row_profiles[0] if row_profiles else ()),
            )
        )
    return tuple(rows)


def decision_pattern_counts(
    clusters: Sequence[ScenarioClusterRow],
) -> tuple[tuple[tuple[float, ...], int], ...]:
    """Count clusters that pose each identical decision problem (Q10).

    Keyed by the loss multiset rather than by scenario identity: two different
    scenarios with the same candidate losses present the same decision problem,
    so they are not independent evidence about a rule. Returned in descending
    frequency, then by pattern, so the largest multiplicities come first.
    """
    counts: dict[tuple[float, ...], int] = defaultdict(int)
    for cluster in clusters:
        if cluster.decision_pattern:
            counts[cluster.decision_pattern] += 1
    return tuple(
        sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _scenario_group(run_id: str) -> str:
    """Strip the ``-seed-NNN`` suffix so the three seeds share one group."""
    marker = "-seed-"
    index = run_id.rfind(marker)
    return run_id[:index] if index > 0 else run_id


def _rank_identity(
    selections: dict[str, dict[tuple[str, int], tuple[tuple[str, str], ...]]],
    rules: Sequence[CandidateRule],
    *,
    canonical: dict[tuple[str, int], DecisionRegretRow],
) -> tuple[DegeneracyAuditRow, ...]:
    """Audit whether two rules ever make different choices."""
    del canonical
    rows: list[DegeneracyAuditRow] = []
    for index, left in enumerate(rules):
        for right in rules[index + 1 :]:
            left_selection = selections[left.rule_id]
            right_selection = selections[right.rule_id]
            shared = sorted(set(left_selection).intersection(right_selection))
            if not shared:
                continue
            identical = sum(
                1
                for key in shared
                if set(left_selection[key]) == set(right_selection[key])
            )
            rows.append(
                DegeneracyAuditRow(
                    rule_a=left.rule_id,
                    rule_b=right.rule_id,
                    shared_decisions=len(shared),
                    identical_selection_count=identical,
                    identical_selection_rate=identical / len(shared),
                )
            )
    return tuple(rows)


def paired_comparison(
    evaluation: RuleEvaluation, *, baseline_rule_id: str, challenger_rule_id: str
) -> dict[str, float | int]:
    """Paired per-decision comparison of two rules over the same decisions."""
    baseline = {
        (row.run_id, row.decision_event_index): row
        for row in evaluation.outcomes
        if row.rule_id == baseline_rule_id
    }
    challenger = {
        (row.run_id, row.decision_event_index): row
        for row in evaluation.outcomes
        if row.rule_id == challenger_rule_id
    }
    shared = sorted(set(baseline).intersection(challenger))
    if not shared:
        raise ValueError("rules share no evaluated decisions")
    improved = worse = tied = 0
    deltas: list[float] = []
    for key in shared:
        base_loss = baseline[key].selected_loss
        challenger_loss = challenger[key].selected_loss
        delta = base_loss - challenger_loss
        deltas.append(delta)
        if math.isclose(delta, 0.0, abs_tol=1e-12):
            tied += 1
        elif delta > 0:
            improved += 1
        else:
            worse += 1
    return {
        "shared_decisions": len(shared),
        "improved": improved,
        "worsened": worse,
        "tied": tied,
        "mean_loss_delta_seconds": statistics.fmean(deltas),
        "median_loss_delta_seconds": statistics.median(deltas),
        "sum_loss_delta_seconds": sum(deltas),
    }


def cluster_paired_comparison(
    evaluation: RuleEvaluation,
    *,
    baseline_rule_id: str,
    challenger_rule_id: str,
) -> dict[str, float | int]:
    """Paired comparison that counts each scenario cluster exactly once (Q10).

    The raw comparison counts decision rows, which double-counts the seed
    replicas. Here every ``(scenario group, decision position)`` cluster is
    averaged over its seeds first and then paired, so the reported counts sum to
    the cluster count and cannot be inflated by duplicate seeds. Both views are
    published; neither replaces the other.
    """
    if not evaluation.clusters:
        raise ValueError("evaluation carries no scenario clusters")

    def per_cluster(rule_id: str) -> dict[tuple[str, int], list[float]]:
        grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
        for row in evaluation.outcomes:
            if row.rule_id != rule_id:
                continue
            grouped[
                (_scenario_group(row.run_id), row.decision_event_index)
            ].append(row.selected_loss)
        return grouped

    baseline = per_cluster(baseline_rule_id)
    challenger = per_cluster(challenger_rule_id)
    shared = sorted(set(baseline).intersection(challenger))
    if not shared:
        raise ValueError("rules share no evaluated clusters")

    improved = worse = tied = 0
    deltas: list[float] = []
    for key in shared:
        delta = statistics.fmean(baseline[key]) - statistics.fmean(
            challenger[key]
        )
        deltas.append(delta)
        if math.isclose(delta, 0.0, abs_tol=1e-12):
            tied += 1
        elif delta > 0:
            improved += 1
        else:
            worse += 1
    return {
        "shared_clusters": len(shared),
        "improved": improved,
        "worsened": worse,
        "tied": tied,
        "mean_loss_delta_seconds": statistics.fmean(deltas),
        "median_loss_delta_seconds": statistics.median(deltas),
        "sum_loss_delta_seconds": sum(deltas),
    }


def leave_one_family_out(
    *,
    candidates: Sequence[DecisionCandidateRow],
    evidence: Sequence[CandidateLossEvidenceRow],
    snapshots: Sequence[DecisionSnapshot],
    families_by_run: dict[str, str | None],
    rules: Sequence[CandidateRule] = CANDIDATE_RULES,
    loss_view: str = CANONICAL_LOSS_VIEW,
) -> dict[str, dict[str, RuleAggregate]]:
    """Evaluate each rule with every scenario family held out in turn."""
    families = sorted({value for value in families_by_run.values() if value})
    result: dict[str, dict[str, RuleAggregate]] = {}
    for family in families:
        held_in = frozenset(
            run_id for run_id, value in families_by_run.items() if value != family
        )
        evaluation = evaluate_rules(
            candidates=candidates,
            evidence=evidence,
            snapshots=snapshots,
            families_by_run=families_by_run,
            rules=rules,
            loss_view=loss_view,
            included_runs=held_in,
        )
        result[family] = {
            aggregate.rule_id: aggregate for aggregate in evaluation.aggregates
        }
    return result


def _spearman(values_a: Sequence[float], values_b: Sequence[float]) -> float | None:
    """Tie-aware Spearman rank correlation, or None when it is undefined."""
    if len(values_a) != len(values_b):
        raise ValueError("spearman inputs must have equal length")
    if len(values_a) < 2:
        return None

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        result = [0.0] * len(values)
        start = 0
        while start < len(order):
            end = start
            while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
                end += 1
            average = (start + end) / 2 + 1
            for index in range(start, end + 1):
                result[order[index]] = average
            start = end + 1
        return result

    ranks_a = ranks(values_a)
    ranks_b = ranks(values_b)
    mean_a = statistics.fmean(ranks_a)
    mean_b = statistics.fmean(ranks_b)
    cov = sum(
        (left - mean_a) * (right - mean_b) for left, right in zip(ranks_a, ranks_b)
    )
    var_a = sum((left - mean_a) ** 2 for left in ranks_a)
    var_b = sum((right - mean_b) ** 2 for right in ranks_b)
    if var_a == 0.0 or var_b == 0.0:
        return None
    return cov / (var_a * var_b) ** 0.5


def denominator_diagnostic(
    candidates: Sequence[DecisionCandidateRow],
) -> tuple[DenominatorDiagnosticRow, ...]:
    """Test handoff section 10c: does the reclaimable denominator cancel cost?

    Compares the cost ordering against the ``cost / reclaimable`` ordering inside
    each decision. If the two orderings disagree arbitrarily, the ratio is not a
    cost measure and the previously rejected marginal-denominator rule cannot be
    justified by it.
    """
    by_decision: dict[tuple[str, int], list[DecisionCandidateRow]] = defaultdict(list)
    for row in candidates:
        by_decision[(row.run_id, row.decision_event_index)].append(row)

    rows: list[DenominatorDiagnosticRow] = []
    for key in sorted(by_decision):
        group = [row for row in by_decision[key] if row.initially_reclaimable_block_count > 0]
        if len(group) < 2:
            continue
        costs = [float(row.prefill_reload_seconds) for row in group]
        denominators = [float(row.initially_reclaimable_block_count) for row in group]
        ratios = [cost / denominator for cost, denominator in zip(costs, denominators)]

        inversions = 0
        pairs = 0
        skipped = 0
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                pairs += 1
                if math.isclose(
                    ratios[left], ratios[right], rel_tol=1e-9, abs_tol=1e-12
                ):
                    # Near-equal ratios are a tie, not a reordering. Comparing raw
                    # floats here would report spurious inversions from rounding.
                    skipped += 1
                    continue
                cost_order = costs[left] - costs[right]
                ratio_order = ratios[left] - ratios[right]
                if (cost_order > 0) != (ratio_order > 0):
                    inversions += 1
        del skipped

        rows.append(
            DenominatorDiagnosticRow(
                run_id=key[0],
                decision_event_index=key[1],
                candidate_count=len(group),
                denominator_is_constant=len(set(denominators)) == 1,
                numerator_denominator_spearman=_spearman(costs, denominators),
                rank_inversions=inversions,
                comparable_pairs=pairs,
            )
        )
    return tuple(rows)


#: Feature on/off comparisons required by handoff section 9's ablation list.
ABLATION_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "size cluster: cost alone vs footprint alone",
        "M1_prefill_reload_ascending -> M1_block_count_ascending",
        "M1_prefill_reload_ascending:M1_block_count_ascending",
    ),
    (
        "size cluster: cost alone vs reclaimable alone",
        "M1_prefill_reload_ascending -> M1_reclaimable_ascending",
        "M1_prefill_reload_ascending:M1_reclaimable_ascending",
    ),
    (
        "size cluster: cost alone vs all three averaged",
        "M1_prefill_reload_ascending -> M3_size_score_only",
        "M1_prefill_reload_ascending:M3_size_score_only",
    ),
    (
        "tool indicator: off vs on, cost primary",
        "M1_prefill_reload_ascending -> M3_non_code_then_small_prefill",
        "M1_prefill_reload_ascending:M3_non_code_then_small_prefill",
    ),
    (
        "tool indicator: off vs on, size score primary",
        "M3_size_score_only -> M3_non_code_then_size_score",
        "M3_size_score_only:M3_non_code_then_size_score",
    ),
    (
        "denominator: cost alone vs cost/reclaimable",
        "M1_prefill_reload_ascending -> M1_marginal_cost_per_reclaimable",
        "M1_prefill_reload_ascending:M1_marginal_cost_per_reclaimable",
    ),
)


def ablation_table(evaluation: RuleEvaluation) -> tuple[AblationRow, ...]:
    """Feature on/off comparison using the existing rule set.

    An ablation that never changes a selection cannot be credited with an effect,
    so the rank-identity rate is reported next to the regret difference. A high
    identity rate with a regret difference would mean the two rules tie with the
    baseline for the same reason.
    """
    aggregates = {row.rule_id: row for row in evaluation.aggregates}
    identity = {
        frozenset((row.rule_a, row.rule_b)): row.identical_selection_rate
        for row in evaluation.degeneracy
    }

    rows: list[AblationRow] = []
    for label, changes, pair in ABLATION_PAIRS:
        left_id, right_id = pair.split(":")
        left = aggregates.get(left_id)
        right = aggregates.get(right_id)
        if left is None or right is None:
            continue
        rows.append(
            AblationRow(
                variant=label,
                changes=changes,
                shared_decisions=left.decisions,
                identical_selection_rate=identity.get(frozenset((left_id, right_id))),
                mean_normalized_regret=right.mean_normalized_regret,
                baseline_mean_normalized_regret=left.mean_normalized_regret,
            )
        )
    return tuple(rows)


def behaviour_breakdown(
    evaluation: RuleEvaluation,
    *,
    dimensions: Sequence[str] = ("scenario_family", "candidate_count", "selection_count"),
) -> tuple[BehaviourBreakdown, ...]:
    """Split each rule's outcomes by the contextual dimensions handoff section 9 lists."""
    if not dimensions:
        raise ValueError("dimensions must not be empty")
    unknown = sorted(set(dimensions) - {"scenario_family", "candidate_count", "selection_count"})
    if unknown:
        raise ValueError(f"unsupported dimensions: {unknown}")

    grouped: dict[tuple[str, str, str], list[RuleDecisionOutcome]] = defaultdict(list)
    for outcome in evaluation.outcomes:
        for dimension in dimensions:
            if dimension == "scenario_family":
                bucket = outcome.scenario_family_id or "(unlabelled)"
            elif dimension == "candidate_count":
                bucket = f"n={outcome.candidate_count}"
            else:
                bucket = f"releases={outcome.selection_count}"
            grouped[(outcome.rule_id, dimension, bucket)].append(outcome)

    rows: list[BehaviourBreakdown] = []
    for (rule_id, dimension, bucket) in sorted(grouped):
        outcomes = grouped[(rule_id, dimension, bucket)]
        non_tied = [row for row in outcomes if not row.candidate_loss_tied]
        worse = [row for row in non_tied if not row.selected_is_hindsight_best]
        rows.append(
            BehaviourBreakdown(
                rule_id=rule_id,
                dimension=dimension,
                bucket=bucket,
                decisions=len(outcomes),
                loss_discriminating_decisions=len(non_tied),
                positive_regret_decisions=len(worse),
                positive_regret_rate=(
                    (len(worse) / len(non_tied)) if non_tied else None
                ),
                mean_absolute_regret=statistics.fmean(
                    row.absolute_regret for row in outcomes
                ),
                mean_normalized_regret=statistics.fmean(
                    row.normalized_regret for row in outcomes
                ),
            )
        )
    return tuple(rows)
