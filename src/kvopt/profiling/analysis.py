"""Leakage-safe feature spreads and offline hindsight-regret analysis."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from math import comb

from .datasets import DecisionCandidateRow
from .ingestion import ArtifactValidationError


@dataclass(frozen=True, slots=True)
class CandidateFeatureSpreadRow:
    """Within-decision spread of one decision-time numeric feature."""

    run_id: str
    decision_event_index: int
    feature: str
    candidate_count: int
    minimum: float
    maximum: float
    spread: float


@dataclass(frozen=True, slots=True)
class CandidateLossRow:
    """Explicit offline loss for one candidate under one named loss view."""

    run_id: str
    decision_event_index: int
    program_id: str
    prefix_id: str
    loss_view: str
    loss: float
    selected: bool


@dataclass(frozen=True, slots=True)
class DecisionRegretRow:
    """Set-aware hindsight comparison for one decision and loss view."""

    run_id: str
    decision_event_index: int
    loss_view: str
    candidate_count: int
    selection_count: int
    selected_candidates: tuple[tuple[str, str], ...]
    hindsight_mandatory_candidates: tuple[tuple[str, str], ...]
    hindsight_boundary_candidates: tuple[tuple[str, str], ...]
    hindsight_best_set_count: int
    selected_loss: float
    hindsight_best_loss: float
    absolute_regret: float
    normalized_regret: float
    selected_is_hindsight_best: bool


_ONLINE_NUMERIC_FEATURES = (
    "block_count",
    "initially_reclaimable_block_count",
    "retention_deadline_timestamp",
    "elapsed_since_ttl_decision_seconds",
    "prefill_reload_seconds",
    "eta",
    "queue_delay_t_seconds",
)


def build_candidate_feature_spreads(
    candidates: Iterable[DecisionCandidateRow],
) -> tuple[CandidateFeatureSpreadRow, ...]:
    """Summarize only the allowlisted decision-time numeric features."""

    groups: dict[tuple[str, int], list[DecisionCandidateRow]] = defaultdict(list)
    for candidate in candidates:
        if not isinstance(candidate, DecisionCandidateRow):
            raise TypeError(
                "candidates must contain DecisionCandidateRow instances"
            )
        groups[(candidate.run_id, candidate.decision_event_index)].append(
            candidate
        )

    rows: list[CandidateFeatureSpreadRow] = []
    for (run_id, decision_event_index), group in sorted(groups.items()):
        for feature in _ONLINE_NUMERIC_FEATURES:
            values = [float(getattr(candidate, feature)) for candidate in group]
            minimum = min(values)
            maximum = max(values)
            rows.append(
                CandidateFeatureSpreadRow(
                    run_id=run_id,
                    decision_event_index=decision_event_index,
                    feature=feature,
                    candidate_count=len(group),
                    minimum=minimum,
                    maximum=maximum,
                    spread=maximum - minimum,
                )
            )
    return tuple(rows)


def _validated_loss(row: CandidateLossRow) -> float:
    if not isinstance(row.loss_view, str) or not row.loss_view.strip():
        raise ArtifactValidationError("loss_view must be non-empty text")
    if isinstance(row.loss, bool) or not isinstance(row.loss, (int, float)):
        raise ArtifactValidationError("candidate loss must be a number")
    loss = float(row.loss)
    if not math.isfinite(loss) or loss < 0:
        raise ArtifactValidationError(
            "candidate loss must be finite and non-negative"
        )
    return loss


def build_decision_regret_table(
    candidate_losses: Iterable[CandidateLossRow],
    *,
    epsilon: float = 1e-12,
) -> tuple[DecisionRegretRow, ...]:
    """Compare actual release sets with minimum-loss hindsight sets."""

    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be finite and positive")

    groups: dict[tuple[str, int, str], list[CandidateLossRow]] = defaultdict(list)
    for row in candidate_losses:
        if not isinstance(row, CandidateLossRow):
            raise TypeError(
                "candidate_losses must contain CandidateLossRow instances"
            )
        _validated_loss(row)
        groups[(row.run_id, row.decision_event_index, row.loss_view)].append(row)

    results: list[DecisionRegretRow] = []
    for (run_id, decision_event_index, loss_view), group in sorted(groups.items()):
        if len(group) < 2:
            raise ArtifactValidationError(
                "regret analysis requires at least two candidates per decision"
            )

        identities = [(row.program_id, row.prefix_id) for row in group]
        if len(identities) != len(set(identities)):
            raise ArtifactValidationError(
                "candidate loss rows contain duplicate candidate identity"
            )

        selected = [row for row in group if row.selected]
        if not selected:
            raise ArtifactValidationError(
                "regret analysis requires at least one selected candidate"
            )

        selection_count = len(selected)
        ranked = sorted(group, key=lambda row: (float(row.loss), row.program_id, row.prefix_id))
        best_loss = sum(float(row.loss) for row in ranked[:selection_count])
        selected_loss = sum(float(row.loss) for row in selected)
        cutoff = float(ranked[selection_count - 1].loss)
        mandatory = [
            row
            for row in ranked
            if float(row.loss) < cutoff
            and not math.isclose(float(row.loss), cutoff, abs_tol=epsilon, rel_tol=0)
        ]
        boundary = [
            row
            for row in ranked
            if math.isclose(float(row.loss), cutoff, abs_tol=epsilon, rel_tol=0)
        ]
        boundary_slots = selection_count - len(mandatory)
        best_set_count = comb(len(boundary), boundary_slots)
        best_identities = {
            (row.program_id, row.prefix_id) for row in mandatory + boundary
        }
        mandatory_identities = {
            (row.program_id, row.prefix_id) for row in mandatory
        }
        selected_identities = {
            (row.program_id, row.prefix_id) for row in selected
        }
        selected_is_best = (
            mandatory_identities.issubset(selected_identities)
            and selected_identities.issubset(best_identities)
        )

        absolute_regret = selected_loss - best_loss
        if math.isclose(absolute_regret, 0.0, abs_tol=epsilon, rel_tol=0):
            absolute_regret = 0.0
        results.append(
            DecisionRegretRow(
                run_id=run_id,
                decision_event_index=decision_event_index,
                loss_view=loss_view,
                candidate_count=len(group),
                selection_count=selection_count,
                selected_candidates=tuple(
                    sorted((row.program_id, row.prefix_id) for row in selected)
                ),
                hindsight_mandatory_candidates=tuple(
                    sorted((row.program_id, row.prefix_id) for row in mandatory)
                ),
                hindsight_boundary_candidates=tuple(
                    sorted((row.program_id, row.prefix_id) for row in boundary)
                ),
                hindsight_best_set_count=best_set_count,
                selected_loss=selected_loss,
                hindsight_best_loss=best_loss,
                absolute_regret=absolute_regret,
                normalized_regret=(
                    absolute_regret / max(abs(selected_loss), epsilon)
                ),
                selected_is_hindsight_best=selected_is_best,
            )
        )
    return tuple(results)
