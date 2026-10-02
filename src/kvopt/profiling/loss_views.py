"""Construct explicit, capability-safe candidate loss views."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .analysis import CandidateLossRow, DecisionRegretRow, build_decision_regret_table
from .datasets import DecisionCandidateRow
from .decision_outcomes import DecisionOutcomeRow
from .ingestion import ArtifactValidationError


@dataclass(frozen=True, slots=True)
class CandidateLossEvidenceRow:
    """One candidate's value or explicit missingness under one loss view."""

    run_id: str
    decision_event_index: int
    program_id: str
    prefix_id: str
    selected: bool
    loss_view: str
    evidence_kind: str
    unit: str
    loss: float | None
    availability: str
    unavailable_reason: str | None
    source_event_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LossViewAvailabilityRow:
    """Decision-level gate controlling whether a view may enter regret."""

    run_id: str
    decision_event_index: int
    loss_view: str
    candidate_count: int
    available_candidate_count: int
    usable_for_regret: bool
    unusable_reason: str | None


@dataclass(frozen=True, slots=True)
class CandidateLossSpreadRow:
    """Within-decision spread for one fully comparable loss view."""

    run_id: str
    decision_event_index: int
    loss_view: str
    candidate_count: int
    minimum_loss: float
    maximum_loss: float
    loss_spread: float


@dataclass(frozen=True, slots=True)
class LossViewTables:
    """Loss evidence, comparability gates, and safe regret results."""

    evidence: tuple[CandidateLossEvidenceRow, ...]
    availability: tuple[LossViewAvailabilityRow, ...]
    comparable_losses: tuple[CandidateLossRow, ...]
    loss_spreads: tuple[CandidateLossSpreadRow, ...]
    decision_regret: tuple[DecisionRegretRow, ...]


_LOGICAL_PROXY = "trace_return_weighted_prefill_proxy"
_PHYSICAL = "observed_physical_eviction_blocks"
_RECOMPUTE = "observed_recomputed_tokens"


def _candidate_key(
    row: DecisionCandidateRow | DecisionOutcomeRow,
) -> tuple[str, int, str, str]:
    return (
        row.run_id,
        row.decision_event_index,
        row.program_id,
        row.prefix_id,
    )


def _logical_proxy_evidence(
    candidate: DecisionCandidateRow,
    outcome: DecisionOutcomeRow,
) -> CandidateLossEvidenceRow:
    source_indexes = [candidate.decision_event_index]
    if outcome.return_arrival_event_index is not None:
        source_indexes.append(outcome.return_arrival_event_index)
    return CandidateLossEvidenceRow(
        run_id=candidate.run_id,
        decision_event_index=candidate.decision_event_index,
        program_id=candidate.program_id,
        prefix_id=candidate.prefix_id,
        selected=candidate.selected,
        loss_view=_LOGICAL_PROXY,
        evidence_kind="trace_derived_proxy",
        unit="seconds",
        loss=(
            candidate.prefill_reload_seconds
            if outcome.returned_after_decision
            else 0.0
        ),
        availability="available",
        unavailable_reason=None,
        source_event_indexes=tuple(source_indexes),
    )


def _physical_evidence(
    candidate: DecisionCandidateRow,
    outcome: DecisionOutcomeRow,
) -> CandidateLossEvidenceRow:
    loss: float | None = None
    availability = "unavailable"
    reason: str | None
    if not candidate.selected:
        reason = "unselected_counterfactual_not_observed"
    elif outcome.physical_eviction_match_status == "ambiguous_block_reuse":
        reason = "ambiguous_block_slot_reuse"
    elif outcome.physical_eviction_match_status == "block_slot_proxy":
        loss = float(outcome.physical_eviction_count)
        availability = "available"
        reason = None
    else:
        reason = "zero_not_provable_without_complete_eviction_capability"

    return CandidateLossEvidenceRow(
        run_id=candidate.run_id,
        decision_event_index=candidate.decision_event_index,
        program_id=candidate.program_id,
        prefix_id=candidate.prefix_id,
        selected=candidate.selected,
        loss_view=_PHYSICAL,
        evidence_kind="block_slot_proxy",
        unit="blocks",
        loss=loss,
        availability=availability,
        unavailable_reason=reason,
        source_event_indexes=(
            candidate.decision_event_index,
            *outcome.physical_eviction_event_indexes,
        ),
    )


def _recompute_evidence(
    candidate: DecisionCandidateRow,
) -> CandidateLossEvidenceRow:
    return CandidateLossEvidenceRow(
        run_id=candidate.run_id,
        decision_event_index=candidate.decision_event_index,
        program_id=candidate.program_id,
        prefix_id=candidate.prefix_id,
        selected=candidate.selected,
        loss_view=_RECOMPUTE,
        evidence_kind="direct_runtime_observation",
        unit="tokens",
        loss=None,
        availability="unavailable",
        unavailable_reason="recompute_token_observation_not_recorded",
        source_event_indexes=(candidate.decision_event_index,),
    )


def _gate_loss_views(
    evidence: tuple[CandidateLossEvidenceRow, ...],
) -> tuple[
    tuple[LossViewAvailabilityRow, ...],
    tuple[CandidateLossRow, ...],
]:
    groups: dict[
        tuple[str, int, str],
        list[CandidateLossEvidenceRow],
    ] = defaultdict(list)
    for row in evidence:
        groups[(row.run_id, row.decision_event_index, row.loss_view)].append(row)

    availability_rows: list[LossViewAvailabilityRow] = []
    comparable: list[CandidateLossRow] = []
    for (run_id, event_index, loss_view), group in sorted(groups.items()):
        available_count = sum(row.availability == "available" for row in group)
        if len(group) < 2:
            reason = "fewer_than_two_candidates"
        elif available_count != len(group):
            reason = "candidate_evidence_unavailable"
        else:
            reason = None
        usable = reason is None
        availability_rows.append(
            LossViewAvailabilityRow(
                run_id=run_id,
                decision_event_index=event_index,
                loss_view=loss_view,
                candidate_count=len(group),
                available_candidate_count=available_count,
                usable_for_regret=usable,
                unusable_reason=reason,
            )
        )
        if usable:
            comparable.extend(
                CandidateLossRow(
                    run_id=row.run_id,
                    decision_event_index=row.decision_event_index,
                    program_id=row.program_id,
                    prefix_id=row.prefix_id,
                    loss_view=row.loss_view,
                    loss=row.loss,
                    selected=row.selected,
                )
                for row in group
                if row.loss is not None
            )
    return tuple(availability_rows), tuple(comparable)


def build_loss_view_tables(
    candidates: Iterable[DecisionCandidateRow],
    outcomes: Iterable[DecisionOutcomeRow],
) -> LossViewTables:
    """Build distinct proxy, physical, and recompute evidence views."""

    candidate_rows = tuple(candidates)
    outcome_rows = tuple(outcomes)
    outcomes_by_key: dict[tuple[str, int, str, str], DecisionOutcomeRow] = {}
    for outcome in outcome_rows:
        key = _candidate_key(outcome)
        if key in outcomes_by_key:
            raise ArtifactValidationError(
                f"duplicate decision outcome key: {key}"
            )
        outcomes_by_key[key] = outcome

    evidence: list[CandidateLossEvidenceRow] = []
    candidate_keys: set[tuple[str, int, str, str]] = set()
    for candidate in candidate_rows:
        key = _candidate_key(candidate)
        if key in candidate_keys:
            raise ArtifactValidationError(
                f"duplicate decision candidate key: {key}"
            )
        candidate_keys.add(key)
        outcome = outcomes_by_key.get(key)
        if outcome is None:
            raise ArtifactValidationError(
                f"decision candidate is missing outcome: {key}"
            )
        if candidate.selected != outcome.selected:
            raise ArtifactValidationError(
                f"candidate and outcome disagree on selection: {key}"
            )
        evidence.extend(
            (
                _logical_proxy_evidence(candidate, outcome),
                _physical_evidence(candidate, outcome),
                _recompute_evidence(candidate),
            )
        )

    unknown_outcomes = set(outcomes_by_key).difference(candidate_keys)
    if unknown_outcomes:
        raise ArtifactValidationError(
            f"decision outcomes have no candidate: {sorted(unknown_outcomes)}"
        )

    evidence_rows = tuple(evidence)
    availability, comparable = _gate_loss_views(evidence_rows)
    comparable_groups: dict[
        tuple[str, int, str],
        list[CandidateLossRow],
    ] = defaultdict(list)
    for row in comparable:
        comparable_groups[
            (row.run_id, row.decision_event_index, row.loss_view)
        ].append(row)
    loss_spreads = tuple(
        CandidateLossSpreadRow(
            run_id=run_id,
            decision_event_index=event_index,
            loss_view=loss_view,
            candidate_count=len(group),
            minimum_loss=min(row.loss for row in group),
            maximum_loss=max(row.loss for row in group),
            loss_spread=(
                max(row.loss for row in group)
                - min(row.loss for row in group)
            ),
        )
        for (run_id, event_index, loss_view), group in sorted(
            comparable_groups.items()
        )
    )
    return LossViewTables(
        evidence=evidence_rows,
        availability=availability,
        comparable_losses=comparable,
        loss_spreads=loss_spreads,
        decision_regret=build_decision_regret_table(comparable),
    )
