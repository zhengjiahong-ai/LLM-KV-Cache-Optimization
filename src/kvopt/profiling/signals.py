"""Leakage-safe rank diagnostics for decision-time candidate signals."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .analysis import CandidateLossRow
from .datasets import DecisionCandidateRow
from .ingestion import ArtifactValidationError


@dataclass(frozen=True, slots=True)
class SignalRunMetadata:
    """Run grouping fields needed for cross-family and cross-seed checks."""

    run_id: str
    scenario_family_id: str | None
    seed: int


@dataclass(frozen=True, slots=True)
class SignalAssociationRow:
    """Spearman association for one feature, loss view, and grouping."""

    loss_view: str
    feature: str
    group_type: str
    group_value: str
    observation_count: int
    decision_count: int
    spearman_rho: float | None


@dataclass(frozen=True, slots=True)
class SignalSupportRow:
    """Pre-registered stability decision for one feature and loss view."""

    loss_view: str
    feature: str
    overall_spearman_rho: float | None
    evaluable_family_count: int
    family_direction_agreement_rate: float | None
    evaluable_seed_count: int
    seed_direction_agreement_rate: float | None
    coverage_sufficient: bool
    supported: bool


@dataclass(frozen=True, slots=True)
class SignalEvaluationRow:
    """Overall decision-time signal-gate input."""

    status: str
    online_signal_supported: bool | None
    evaluated_feature_count: int
    supported_feature_count: int
    minimum_absolute_rho: float
    minimum_group_count: int
    minimum_direction_agreement_rate: float


@dataclass(frozen=True, slots=True)
class SignalAnalysisTables:
    """Association details, per-feature support, and overall evaluation."""

    associations: tuple[SignalAssociationRow, ...]
    support: tuple[SignalSupportRow, ...]
    evaluation: SignalEvaluationRow


@dataclass(frozen=True, slots=True)
class _RankObservation:
    run_id: str
    decision_event_index: int
    scenario_family_id: str | None
    seed: int
    loss_view: str
    feature: str
    feature_rank: float
    loss_rank: float


_ONLINE_FEATURES = (
    "block_count",
    "initially_reclaimable_block_count",
    "decision_native_lru_position",
    "retention_deadline_timestamp",
    "waiting_followup",
    "next_tool_type=search",
    "next_tool_type=database",
    "next_tool_type=code",
    "elapsed_since_ttl_decision_seconds",
    "prefill_reload_seconds",
    "eta",
    "queue_delay_t_seconds",
)
_MINIMUM_ABSOLUTE_RHO = 0.2
_MINIMUM_GROUP_COUNT = 3
_MINIMUM_DIRECTION_AGREEMENT_RATE = 2.0 / 3.0


def _feature_value(row: DecisionCandidateRow, feature: str) -> float | None:
    if feature == "waiting_followup":
        return float(row.waiting_followup)
    if feature.startswith("next_tool_type="):
        category = feature.removeprefix("next_tool_type=")
        return float(row.next_tool_type == category)
    value = getattr(row, feature)
    return None if value is None else float(value)


def _average_ranks(values: Sequence[float]) -> tuple[float, ...]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[ordered[position]] = average_rank
        start = end
    return tuple(ranks)


def _normalized_ranks(values: Sequence[float]) -> tuple[float, ...]:
    ranks = _average_ranks(values)
    if len(ranks) < 2:
        return tuple(0.5 for _rank in ranks)
    return tuple((rank - 1.0) / (len(ranks) - 1.0) for rank in ranks)


def _correlation(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) < 2 or len(x_values) != len(y_values):
        return None
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    x_centered = [value - x_mean for value in x_values]
    y_centered = [value - y_mean for value in y_values]
    denominator = math.sqrt(
        sum(value * value for value in x_centered)
        * sum(value * value for value in y_centered)
    )
    if denominator == 0:
        return None
    return sum(
        x_value * y_value
        for x_value, y_value in zip(x_centered, y_centered, strict=True)
    ) / denominator


def _association(
    observations: Sequence[_RankObservation],
    *,
    group_type: str,
    group_value: str,
) -> SignalAssociationRow:
    first = observations[0]
    return SignalAssociationRow(
        loss_view=first.loss_view,
        feature=first.feature,
        group_type=group_type,
        group_value=group_value,
        observation_count=len(observations),
        decision_count=len(
            {
                (row.run_id, row.decision_event_index)
                for row in observations
            }
        ),
        spearman_rho=_correlation(
            [row.feature_rank for row in observations],
            [row.loss_rank for row in observations],
        ),
    )


def _empty_association(loss_view: str, feature: str) -> SignalAssociationRow:
    return SignalAssociationRow(
        loss_view=loss_view,
        feature=feature,
        group_type="overall",
        group_value="all",
        observation_count=0,
        decision_count=0,
        spearman_rho=None,
    )


def _direction_agreement(
    overall_rho: float | None,
    group_rows: Sequence[SignalAssociationRow],
) -> float | None:
    usable = [row.spearman_rho for row in group_rows if row.spearman_rho is not None]
    if overall_rho is None or not usable or overall_rho == 0:
        return None
    direction = 1 if overall_rho > 0 else -1
    matching = sum((rho > 0) == (direction > 0) for rho in usable)
    return matching / len(usable)


def build_signal_analysis_tables(
    candidates: Iterable[DecisionCandidateRow],
    candidate_losses: Iterable[CandidateLossRow],
    run_metadata: Iterable[SignalRunMetadata],
) -> SignalAnalysisTables:
    """Analyze only allowlisted decision-time fields against offline losses."""

    metadata_by_run: dict[str, SignalRunMetadata] = {}
    for metadata in run_metadata:
        if metadata.run_id in metadata_by_run:
            raise ArtifactValidationError(
                f"duplicate signal run metadata: {metadata.run_id}"
            )
        metadata_by_run[metadata.run_id] = metadata

    candidates_by_key: dict[
        tuple[str, int, str, str],
        DecisionCandidateRow,
    ] = {}
    for row in candidates:
        key = (
            row.run_id,
            row.decision_event_index,
            row.program_id,
            row.prefix_id,
        )
        if key in candidates_by_key:
            raise ArtifactValidationError(
                f"duplicate signal candidate key: {key}"
            )
        candidates_by_key[key] = row
    loss_groups: dict[tuple[str, int, str], list[CandidateLossRow]] = defaultdict(list)
    for loss in candidate_losses:
        group_key = (loss.run_id, loss.decision_event_index, loss.loss_view)
        identity = (loss.program_id, loss.prefix_id)
        if any(
            (row.program_id, row.prefix_id) == identity
            for row in loss_groups[group_key]
        ):
            raise ArtifactValidationError(
                f"duplicate signal candidate loss: {group_key + identity}"
            )
        loss_groups[group_key].append(loss)

    observations: list[_RankObservation] = []
    signal_keys: set[tuple[str, str]] = set()
    for (run_id, event_index, loss_view), losses in sorted(loss_groups.items()):
        metadata = metadata_by_run.get(run_id)
        if metadata is None:
            raise ArtifactValidationError(
                f"candidate loss references unknown signal run: {run_id}"
            )
        decision_candidates: list[DecisionCandidateRow] = []
        for loss in losses:
            key = (run_id, event_index, loss.program_id, loss.prefix_id)
            candidate = candidates_by_key.get(key)
            if candidate is None:
                raise ArtifactValidationError(
                    f"candidate loss is missing decision-time candidate: {key}"
                )
            decision_candidates.append(candidate)
        signal_keys.update(
            (loss_view, feature) for feature in _ONLINE_FEATURES
        )
        loss_values = [row.loss for row in losses]
        if len(set(loss_values)) < 2:
            continue
        loss_ranks = _normalized_ranks(loss_values)
        for feature in _ONLINE_FEATURES:
            feature_values = [
                _feature_value(row, feature) for row in decision_candidates
            ]
            if any(value is None for value in feature_values):
                continue
            numeric_feature_values = [
                value for value in feature_values if value is not None
            ]
            if len(set(numeric_feature_values)) < 2:
                continue
            feature_ranks = _normalized_ranks(numeric_feature_values)
            for position in range(len(losses)):
                observations.append(
                    _RankObservation(
                        run_id=run_id,
                        decision_event_index=event_index,
                        scenario_family_id=metadata.scenario_family_id,
                        seed=metadata.seed,
                        loss_view=loss_view,
                        feature=feature,
                        feature_rank=feature_ranks[position],
                        loss_rank=loss_ranks[position],
                    )
                )

    by_signal: dict[tuple[str, str], list[_RankObservation]] = defaultdict(list)
    for row in observations:
        by_signal[(row.loss_view, row.feature)].append(row)

    associations: list[SignalAssociationRow] = []
    for signal_key in sorted(signal_keys):
        rows = by_signal.get(signal_key, [])
        if not rows:
            associations.append(_empty_association(*signal_key))
            continue
        associations.append(
            _association(rows, group_type="overall", group_value="all")
        )
        family_groups: dict[str, list[_RankObservation]] = defaultdict(list)
        seed_groups: dict[int, list[_RankObservation]] = defaultdict(list)
        for row in rows:
            if row.scenario_family_id is not None:
                family_groups[row.scenario_family_id].append(row)
            seed_groups[row.seed].append(row)
        associations.extend(
            _association(group, group_type="scenario_family", group_value=family)
            for family, group in sorted(family_groups.items())
        )
        associations.extend(
            _association(group, group_type="seed", group_value=str(seed))
            for seed, group in sorted(seed_groups.items())
        )

    association_groups: dict[tuple[str, str], list[SignalAssociationRow]] = defaultdict(list)
    for row in associations:
        association_groups[(row.loss_view, row.feature)].append(row)

    support_rows: list[SignalSupportRow] = []
    for (loss_view, feature), rows in sorted(association_groups.items()):
        overall = next(row for row in rows if row.group_type == "overall")
        families = [
            row
            for row in rows
            if row.group_type == "scenario_family" and row.spearman_rho is not None
        ]
        seeds = [
            row
            for row in rows
            if row.group_type == "seed" and row.spearman_rho is not None
        ]
        family_agreement = _direction_agreement(overall.spearman_rho, families)
        seed_agreement = _direction_agreement(overall.spearman_rho, seeds)
        coverage_sufficient = (
            len(families) >= _MINIMUM_GROUP_COUNT
            and len(seeds) >= _MINIMUM_GROUP_COUNT
        )
        supported = (
            coverage_sufficient
            and overall.spearman_rho is not None
            and abs(overall.spearman_rho) >= _MINIMUM_ABSOLUTE_RHO
            and family_agreement is not None
            and family_agreement >= _MINIMUM_DIRECTION_AGREEMENT_RATE
            and seed_agreement is not None
            and seed_agreement >= _MINIMUM_DIRECTION_AGREEMENT_RATE
        )
        support_rows.append(
            SignalSupportRow(
                loss_view=loss_view,
                feature=feature,
                overall_spearman_rho=overall.spearman_rho,
                evaluable_family_count=len(families),
                family_direction_agreement_rate=family_agreement,
                evaluable_seed_count=len(seeds),
                seed_direction_agreement_rate=seed_agreement,
                coverage_sufficient=coverage_sufficient,
                supported=supported,
            )
        )

    evaluation_complete = any(row.coverage_sufficient for row in support_rows)
    supported_count = sum(row.supported for row in support_rows)
    evaluation = SignalEvaluationRow(
        status=(
            "SUPPORTED"
            if supported_count
            else "NO_STABLE_SIGNAL"
            if evaluation_complete
            else "INSUFFICIENT_COVERAGE"
        ),
        online_signal_supported=(
            None if not evaluation_complete else supported_count > 0
        ),
        evaluated_feature_count=len(support_rows),
        supported_feature_count=supported_count,
        minimum_absolute_rho=_MINIMUM_ABSOLUTE_RHO,
        minimum_group_count=_MINIMUM_GROUP_COUNT,
        minimum_direction_agreement_rate=(
            _MINIMUM_DIRECTION_AGREEMENT_RATE
        ),
    )
    return SignalAnalysisTables(
        associations=tuple(associations),
        support=tuple(support_rows),
        evaluation=evaluation,
    )
