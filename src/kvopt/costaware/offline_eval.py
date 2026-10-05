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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from kvopt.profiling.analysis import (
    CandidateLossRow,
    DecisionRegretRow,
    build_decision_regret_table,
)
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.loss_views import CandidateLossEvidenceRow

from .rules import CANDIDATE_RULES, CandidateRule

#: The canonical loss view authorized for offline method design.
CANONICAL_LOSS_VIEW = "planned_return_weighted_prefill_proxy"


def _identity(row: DecisionCandidateRow) -> tuple[str, str]:
    return (row.program_id, row.prefix_id)


@dataclass(frozen=True, slots=True)
class RuleDecisionOutcome:
    """One rule's regret result for one decision."""

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
    """True when every candidate has the same loss, so no choice can matter.

    This is the M6 notion of a tied decision. It is deliberately independent of
    whether *this rule* captured the available headroom: conflating the two
    would make the misselection rate hide decisions where headroom exists but
    the rule failed to take it.
    """


@dataclass(frozen=True, slots=True)
class RuleAggregate:
    """Aggregate behaviour of one rule across decisions."""

    rule_id: str
    family: str
    decisions: int
    non_tied_decisions: int
    strictly_worse_decisions: int
    misselection_rate: float | None
    mean_absolute_regret: float
    mean_normalized_regret: float
    tie_rate: float


@dataclass(frozen=True, slots=True)
class DegeneracyAuditRow:
    """Rank-identity audit between one rule pair over shared decisions."""

    rule_a: str
    rule_b: str
    shared_decisions: int
    identical_selection_count: int
    identical_selection_rate: float | None


@dataclass(frozen=True, slots=True)
class BaselineReproduction:
    """Check that a re-derived rule matches the canonical executed selection."""

    rule_id: str
    shared_decisions: int
    matching_decisions: int
    match_rate: float | None
    missing_native_lru_position: int


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

    def for_rule(self, rule_id: str) -> RuleAggregate:
        for aggregate in self.aggregates:
            if aggregate.rule_id == rule_id:
                return aggregate
        raise KeyError(f"rule {rule_id!r} not present in evaluation")


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
    canonical_regret: Sequence[DecisionRegretRow] = (),
    families_by_run: dict[str, str | None] | None = None,
    rules: Sequence[CandidateRule] = CANDIDATE_RULES,
    loss_view: str = CANONICAL_LOSS_VIEW,
    included_runs: frozenset[str] | None = None,
) -> RuleEvaluation:
    """Evaluate every rule on the decisions where ``loss_view`` is complete.

    A decision participates only when it has at least two candidates with
    available loss under ``loss_view`` and the executed baseline selected at
    least one of them. The number of released candidates is held equal to the
    executed baseline, so the comparison isolates *which* candidates are
    released rather than *how many*.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TypeError("candidates must be an ordered sequence")
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
        raise TypeError("evidence must be an ordered sequence")

    grouped_losses = _usable_evidence(evidence, loss_view)
    executed = _executed_selection(candidates)
    canonical = _canonical_regret(canonical_regret)
    family_lookup = families_by_run or {}

    by_decision: dict[tuple[str, int], list[DecisionCandidateRow]] = defaultdict(list)
    for row in candidates:
        by_decision[(row.run_id, row.decision_event_index)].append(row)

    outcomes: dict[str, list[RuleDecisionOutcome]] = defaultdict(list)
    selections: dict[str, dict[tuple[str, int], tuple[tuple[str, str], ...]]] = defaultdict(dict)
    evaluated = 0
    skipped = 0
    available_candidate_total = 0

    for decision_key in sorted(grouped_losses):
        run_id, _decision_event_index = decision_key
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
        selected_available = {identity for identity in executed[decision_key] if identity in losses}
        selection_count = len(selected_available)
        if selection_count < 1:
            skipped += 1
            continue

        evaluated += 1
        available_candidate_total += len(group)
        for rule in rules:
            chosen = rule.selection(group, selection_count)
            selections[rule.rule_id][decision_key] = chosen
            loss_rows = [
                CandidateLossRow(
                    run_id=run_id,
                    decision_event_index=decision_key[1],
                    program_id=row.program_id,
                    prefix_id=row.prefix_id,
                    loss_view=loss_view,
                    loss=losses[_identity(row)],
                    selected=_identity(row) in set(chosen),
                )
                for row in group
            ]
            regret_row = build_decision_regret_table(loss_rows)[0]
            outcomes[rule.rule_id].append(
                RuleDecisionOutcome(
                    rule_id=rule.rule_id,
                    run_id=run_id,
                    decision_event_index=decision_key[1],
                    scenario_family_id=family_lookup.get(run_id),
                    candidate_count=len(group),
                    selection_count=selection_count,
                    loss_view=loss_view,
                    selected_identities=chosen,
                    selected_loss=regret_row.selected_loss,
                    hindsight_best_loss=regret_row.hindsight_best_loss,
                    absolute_regret=regret_row.absolute_regret,
                    normalized_regret=regret_row.normalized_regret,
                    selected_is_hindsight_best=regret_row.selected_is_hindsight_best,
                    candidate_loss_tied=len({losses[_identity(row)] for row in group}) == 1,
                )
            )

    aggregates = tuple(
        _aggregate(rule, outcomes[rule.rule_id]) for rule in rules
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
    )


def _aggregate(
    rule: CandidateRule, outcomes: Sequence[RuleDecisionOutcome]
) -> RuleAggregate:
    if not outcomes:
        return RuleAggregate(
            rule_id=rule.rule_id,
            family=rule.family,
            decisions=0,
            non_tied_decisions=0,
            strictly_worse_decisions=0,
            misselection_rate=None,
            mean_absolute_regret=float("nan"),
            mean_normalized_regret=float("nan"),
            tie_rate=float("nan"),
        )
    # A decision is non-tied when its candidates have different losses, i.e. the
    # choice can matter. This is independent of whether this rule got it right.
    non_tied = [row for row in outcomes if not row.candidate_loss_tied]
    worse = [row for row in non_tied if not row.selected_is_hindsight_best]
    return RuleAggregate(
        rule_id=rule.rule_id,
        family=rule.family,
        decisions=len(outcomes),
        non_tied_decisions=len(non_tied),
        strictly_worse_decisions=len(worse),
        misselection_rate=(len(worse) / len(non_tied)) if non_tied else None,
        mean_absolute_regret=statistics.fmean(row.absolute_regret for row in outcomes),
        mean_normalized_regret=statistics.fmean(
            row.normalized_regret for row in outcomes
        ),
        tie_rate=(
            sum(1 for row in outcomes if row.candidate_loss_tied) / len(outcomes)
        ),
    )


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


def reproduce_executed_baseline(
    *,
    candidates: Sequence[DecisionCandidateRow],
    execution_rule: CandidateRule,
    decision_keys: Iterable[tuple[str, int]],
) -> BaselineReproduction:
    """Verify the evaluator re-derives the canonical executed selection.

    This is a self-check on the harness, not a research result. It confirms
    that :data:`~kvopt.costaware.rules.CANDIDATE_RULES` rule
    ``M0_p1b_executed_ordering`` reproduces the persisted P1B release set.
    """
    by_decision: dict[tuple[str, int], list[DecisionCandidateRow]] = defaultdict(list)
    for row in candidates:
        by_decision[(row.run_id, row.decision_event_index)].append(row)

    shared = 0
    matching = 0
    missing_position = 0
    for key in decision_keys:
        group = by_decision.get(key)
        if not group:
            continue
        executed = {_identity(row) for row in group if row.selected}
        if not executed:
            continue
        shared += 1
        if any(row.decision_native_lru_position is None for row in group):
            missing_position += 1
        rederived = set(execution_rule.selection(group, len(executed)))
        if rederived == executed:
            matching += 1
    return BaselineReproduction(
        rule_id=execution_rule.rule_id,
        shared_decisions=shared,
        matching_decisions=matching,
        match_rate=(matching / shared) if shared else None,
        missing_native_lru_position=missing_position,
    )


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


def leave_one_family_out(
    *,
    candidates: Sequence[DecisionCandidateRow],
    evidence: Sequence[CandidateLossEvidenceRow],
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
            families_by_run=families_by_run,
            rules=rules,
            loss_view=loss_view,
            included_runs=held_in,
        )
        result[family] = {
            aggregate.rule_id: aggregate for aggregate in evaluation.aggregates
        }
    return result
