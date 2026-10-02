"""Deterministic statistical summaries for Phase 2A analysis."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .analysis import CandidateFeatureSpreadRow, DecisionRegretRow
from .ingestion import ArtifactValidationError
from .loss_views import CandidateLossSpreadRow


@dataclass(frozen=True, slots=True)
class AnalysisRunMetadata:
    """Minimum run metadata required for grouped statistical analysis."""

    run_id: str
    scenario_id: str | None
    seed: int
    valid_for_candidate_analysis: bool


@dataclass(frozen=True, slots=True)
class CandidateHeterogeneitySummaryRow:
    """Feature-spread summary for one analysis scope."""

    scope: str
    scenario_id: str | None
    feature: str
    decision_count: int
    seed_count: int
    positive_spread_count: int
    positive_spread_rate: float
    mean_spread: float
    mean_spread_ci_lower: float
    mean_spread_ci_upper: float


@dataclass(frozen=True, slots=True)
class RegretSummaryRow:
    """Headroom summary for one loss view and analysis scope."""

    scope: str
    scenario_id: str | None
    loss_view: str
    decision_count: int
    seed_count: int
    non_tied_decision_count: int
    non_tied_misselection_count: int
    non_tied_misselection_rate: float | None
    mean_absolute_regret: float
    mean_absolute_regret_ci_lower: float
    mean_absolute_regret_ci_upper: float
    mean_normalized_regret: float
    mean_normalized_regret_ci_lower: float
    mean_normalized_regret_ci_upper: float


@dataclass(frozen=True, slots=True)
class LossHeterogeneitySummaryRow:
    """Within-decision realized-loss spread for one analysis scope."""

    scope: str
    scenario_id: str | None
    loss_view: str
    decision_count: int
    seed_count: int
    positive_spread_count: int
    positive_spread_rate: float
    mean_spread: float
    mean_spread_ci_lower: float
    mean_spread_ci_upper: float


@dataclass(frozen=True, slots=True)
class StatisticalSummaryTables:
    """Candidate heterogeneity and baseline-headroom summaries."""

    candidate_heterogeneity: tuple[CandidateHeterogeneitySummaryRow, ...]
    loss_heterogeneity: tuple[LossHeterogeneitySummaryRow, ...]
    regret: tuple[RegretSummaryRow, ...]


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return (
        ordered[lower_index] * (1.0 - weight)
        + ordered[upper_index] * weight
    )


def _bootstrap_mean(
    values: Sequence[float],
    *,
    random_source: random.Random,
    resamples: int,
    confidence_level: float,
) -> tuple[float, float, float]:
    if not values:
        raise ValueError("bootstrap requires at least one value")
    mean = sum(values) / len(values)
    if len(values) == 1:
        return mean, mean, mean

    bootstrap_means = [
        sum(random_source.choice(values) for _ in values) / len(values)
        for _ in range(resamples)
    ]
    tail = (1.0 - confidence_level) / 2.0
    return (
        mean,
        _quantile(bootstrap_means, tail),
        _quantile(bootstrap_means, 1.0 - tail),
    )


def _analysis_scopes(
    metadata: AnalysisRunMetadata,
) -> tuple[tuple[str, str | None], ...]:
    scopes: list[tuple[str, str | None]] = [("overall", None)]
    if metadata.scenario_id is not None:
        scopes.append(("scenario", metadata.scenario_id))
    return tuple(scopes)


def build_statistical_summary_tables(
    run_metadata: Iterable[AnalysisRunMetadata],
    feature_spreads: Iterable[CandidateFeatureSpreadRow],
    loss_spreads: Iterable[CandidateLossSpreadRow],
    decision_regret: Iterable[DecisionRegretRow],
    *,
    bootstrap_resamples: int = 2_000,
    bootstrap_seed: int = 0,
    confidence_level: float = 0.95,
) -> StatisticalSummaryTables:
    """Aggregate valid runs with deterministic percentile bootstrap CIs."""

    if bootstrap_resamples <= 0:
        raise ValueError("bootstrap_resamples must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")

    metadata_by_run: dict[str, AnalysisRunMetadata] = {}
    for metadata in run_metadata:
        if metadata.run_id in metadata_by_run:
            raise ArtifactValidationError(
                f"duplicate analysis run metadata: {metadata.run_id}"
            )
        metadata_by_run[metadata.run_id] = metadata

    heterogeneity_groups: dict[
        tuple[str, str | None, str],
        list[tuple[CandidateFeatureSpreadRow, AnalysisRunMetadata]],
    ] = defaultdict(list)
    for row in feature_spreads:
        metadata = metadata_by_run.get(row.run_id)
        if metadata is None:
            raise ArtifactValidationError(
                f"feature spread references unknown run: {row.run_id}"
            )
        if not metadata.valid_for_candidate_analysis:
            continue
        for scope, scenario_id in _analysis_scopes(metadata):
            heterogeneity_groups[(scope, scenario_id, row.feature)].append(
                (row, metadata)
            )

    regret_groups: dict[
        tuple[str, str | None, str],
        list[tuple[DecisionRegretRow, AnalysisRunMetadata]],
    ] = defaultdict(list)
    for row in decision_regret:
        metadata = metadata_by_run.get(row.run_id)
        if metadata is None:
            raise ArtifactValidationError(
                f"decision regret references unknown run: {row.run_id}"
            )
        if not metadata.valid_for_candidate_analysis:
            continue
        for scope, scenario_id in _analysis_scopes(metadata):
            regret_groups[(scope, scenario_id, row.loss_view)].append(
                (row, metadata)
            )

    loss_spread_groups: dict[
        tuple[str, str | None, str],
        list[tuple[CandidateLossSpreadRow, AnalysisRunMetadata]],
    ] = defaultdict(list)
    for row in loss_spreads:
        metadata = metadata_by_run.get(row.run_id)
        if metadata is None:
            raise ArtifactValidationError(
                f"loss spread references unknown run: {row.run_id}"
            )
        if not metadata.valid_for_candidate_analysis:
            continue
        for scope, scenario_id in _analysis_scopes(metadata):
            loss_spread_groups[(scope, scenario_id, row.loss_view)].append(
                (row, metadata)
            )

    random_source = random.Random(bootstrap_seed)
    heterogeneity_rows: list[CandidateHeterogeneitySummaryRow] = []
    for (scope, scenario_id, feature), group in sorted(
        heterogeneity_groups.items(),
        key=lambda item: (
            item[0][0],
            item[0][1] or "",
            item[0][2],
        ),
    ):
        spreads = [row.spread for row, _ in group]
        mean, lower, upper = _bootstrap_mean(
            spreads,
            random_source=random_source,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
        )
        positive_count = sum(value > 0 for value in spreads)
        heterogeneity_rows.append(
            CandidateHeterogeneitySummaryRow(
                scope=scope,
                scenario_id=scenario_id,
                feature=feature,
                decision_count=len(group),
                seed_count=len({metadata.seed for _, metadata in group}),
                positive_spread_count=positive_count,
                positive_spread_rate=positive_count / len(group),
                mean_spread=mean,
                mean_spread_ci_lower=lower,
                mean_spread_ci_upper=upper,
            )
        )

    regret_rows: list[RegretSummaryRow] = []
    for (scope, scenario_id, loss_view), group in sorted(
        regret_groups.items(),
        key=lambda item: (
            item[0][0],
            item[0][1] or "",
            item[0][2],
        ),
    ):
        absolute = [row.absolute_regret for row, _ in group]
        normalized = [row.normalized_regret for row, _ in group]
        absolute_mean, absolute_lower, absolute_upper = _bootstrap_mean(
            absolute,
            random_source=random_source,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
        )
        normalized_mean, normalized_lower, normalized_upper = _bootstrap_mean(
            normalized,
            random_source=random_source,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
        )
        non_tied = [
            row for row, _ in group if row.hindsight_best_set_count == 1
        ]
        misselected = sum(
            not row.selected_is_hindsight_best for row in non_tied
        )
        regret_rows.append(
            RegretSummaryRow(
                scope=scope,
                scenario_id=scenario_id,
                loss_view=loss_view,
                decision_count=len(group),
                seed_count=len({metadata.seed for _, metadata in group}),
                non_tied_decision_count=len(non_tied),
                non_tied_misselection_count=misselected,
                non_tied_misselection_rate=(
                    None if not non_tied else misselected / len(non_tied)
                ),
                mean_absolute_regret=absolute_mean,
                mean_absolute_regret_ci_lower=absolute_lower,
                mean_absolute_regret_ci_upper=absolute_upper,
                mean_normalized_regret=normalized_mean,
                mean_normalized_regret_ci_lower=normalized_lower,
                mean_normalized_regret_ci_upper=normalized_upper,
            )
        )

    loss_heterogeneity_rows: list[LossHeterogeneitySummaryRow] = []
    for (scope, scenario_id, loss_view), group in sorted(
        loss_spread_groups.items(),
        key=lambda item: (
            item[0][0],
            item[0][1] or "",
            item[0][2],
        ),
    ):
        spreads = [row.loss_spread for row, _ in group]
        mean, lower, upper = _bootstrap_mean(
            spreads,
            random_source=random_source,
            resamples=bootstrap_resamples,
            confidence_level=confidence_level,
        )
        positive_count = sum(value > 0 for value in spreads)
        loss_heterogeneity_rows.append(
            LossHeterogeneitySummaryRow(
                scope=scope,
                scenario_id=scenario_id,
                loss_view=loss_view,
                decision_count=len(group),
                seed_count=len({metadata.seed for _, metadata in group}),
                positive_spread_count=positive_count,
                positive_spread_rate=positive_count / len(group),
                mean_spread=mean,
                mean_spread_ci_lower=lower,
                mean_spread_ci_upper=upper,
            )
        )

    return StatisticalSummaryTables(
        candidate_heterogeneity=tuple(heterogeneity_rows),
        loss_heterogeneity=tuple(loss_heterogeneity_rows),
        regret=tuple(regret_rows),
    )
