"""Assemble the machine-readable Method Support Pack for Member 4."""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import DecisionRegretRow
from .gate import EmpiricalGapReport
from .prevalence import PrevalenceSummaryRow
from .signals import SignalEvaluationRow, SignalSupportRow
from .statistics import (
    CandidateHeterogeneitySummaryRow,
    LossHeterogeneitySummaryRow,
    RegretSummaryRow,
)


@dataclass(frozen=True, slots=True)
class CapabilityFinding:
    run_id: str
    capability: str
    availability: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class PrevalenceFinding:
    run_count: int
    successful_run_count: int
    failed_run_count: int
    seed_count: int
    request_count: int
    decision_count: int
    multi_candidate_decision_rate: float | None
    forced_release_per_request: float | None
    mean_candidate_count: float | None
    maximum_candidate_count: int | None
    mean_required_blocks: float | None
    mean_selected_release_count: float | None
    repeated_pressure_run_rate: float | None
    repeated_logical_release_count: int


@dataclass(frozen=True, slots=True)
class FeatureFinding:
    feature: str
    decision_count: int
    positive_spread_rate: float
    mean_spread: float
    mean_spread_ci_lower: float
    mean_spread_ci_upper: float


@dataclass(frozen=True, slots=True)
class LossViewFinding:
    loss_view: str
    evidence_level: str
    decision_count: int
    positive_spread_rate: float | None
    mean_spread: float | None
    mean_spread_ci_lower: float | None
    tie_rate: float | None
    non_tied_misselection_rate: float | None
    mean_absolute_regret: float | None
    mean_normalized_regret: float | None
    normalized_regret_ci_lower: float | None


@dataclass(frozen=True, slots=True)
class HighRegretExample:
    run_id: str
    decision_event_index: int
    loss_view: str
    selected_loss: float
    hindsight_best_loss: float
    absolute_regret: float
    normalized_regret: float


@dataclass(frozen=True, slots=True)
class SignalFinding:
    loss_view: str
    feature: str
    overall_spearman_rho: float | None
    evaluable_family_count: int
    family_direction_agreement_rate: float | None
    evaluable_seed_count: int
    seed_direction_agreement_rate: float | None
    supported: bool


@dataclass(frozen=True, slots=True)
class MethodConstraints:
    safe_online_features: tuple[str, ...]
    weak_or_unstable_online_features: tuple[str, ...]
    future_only_forbidden_online: tuple[str, ...]
    unavailable_capabilities: tuple[CapabilityFinding, ...]
    required_corner_cases: tuple[str, ...]
    best_supported_loss_views: tuple[str, ...]
    unresolved_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MethodSupportPack:
    schema_version: str
    formal_campaign: bool
    gate_outcome: str
    prevalence: PrevalenceFinding
    candidate_heterogeneity: tuple[FeatureFinding, ...]
    outcome_heterogeneity_and_headroom: tuple[LossViewFinding, ...]
    high_regret_examples: tuple[HighRegretExample, ...]
    signal_evaluation_status: str
    signals: tuple[SignalFinding, ...]
    constraints: MethodConstraints
    source_tables: tuple[str, ...]


def _unavailable_capabilities(
    capabilities: tuple[CapabilityFinding, ...],
) -> tuple[CapabilityFinding, ...]:
    return tuple(
        row
        for row in capabilities
        if "unavailable" in row.availability.lower()
        or "error" in row.availability.lower()
    )


def build_method_support_pack(
    *,
    formal_campaign: bool,
    prevalence: tuple[PrevalenceSummaryRow, ...],
    candidate_heterogeneity: tuple[CandidateHeterogeneitySummaryRow, ...],
    loss_heterogeneity: tuple[LossHeterogeneitySummaryRow, ...],
    regret_summary: tuple[RegretSummaryRow, ...],
    decision_regret: tuple[DecisionRegretRow, ...],
    signal_support: tuple[SignalSupportRow, ...],
    signal_evaluation: SignalEvaluationRow,
    capabilities: tuple[CapabilityFinding, ...],
    direct_loss_views: tuple[str, ...],
    gate_report: EmpiricalGapReport,
) -> MethodSupportPack:
    """Build a compact report whose claims point back to derived tables."""

    overall_prevalence = next(
        row for row in prevalence if row.scope == "overall"
    )
    feature_findings = tuple(
        FeatureFinding(
            feature=row.feature,
            decision_count=row.decision_count,
            positive_spread_rate=row.positive_spread_rate,
            mean_spread=row.mean_spread,
            mean_spread_ci_lower=row.mean_spread_ci_lower,
            mean_spread_ci_upper=row.mean_spread_ci_upper,
        )
        for row in candidate_heterogeneity
        if row.scope == "overall"
    )

    loss_by_view = {
        row.loss_view: row
        for row in loss_heterogeneity
        if row.scope == "overall"
    }
    regret_by_view = {
        row.loss_view: row
        for row in regret_summary
        if row.scope == "overall"
    }
    loss_findings: list[LossViewFinding] = []
    for loss_view in sorted(set(loss_by_view).union(regret_by_view)):
        spread = loss_by_view.get(loss_view)
        regret = regret_by_view.get(loss_view)
        tie_rate = None
        if regret is not None and regret.decision_count:
            tie_rate = (
                regret.decision_count - regret.non_tied_decision_count
            ) / regret.decision_count
        loss_findings.append(
            LossViewFinding(
                loss_view=loss_view,
                evidence_level=(
                    "direct" if loss_view in direct_loss_views else "proxy"
                ),
                decision_count=(
                    spread.decision_count
                    if spread is not None
                    else regret.decision_count
                    if regret is not None
                    else 0
                ),
                positive_spread_rate=(
                    None if spread is None else spread.positive_spread_rate
                ),
                mean_spread=None if spread is None else spread.mean_spread,
                mean_spread_ci_lower=(
                    None if spread is None else spread.mean_spread_ci_lower
                ),
                tie_rate=tie_rate,
                non_tied_misselection_rate=(
                    None
                    if regret is None
                    else regret.non_tied_misselection_rate
                ),
                mean_absolute_regret=(
                    None if regret is None else regret.mean_absolute_regret
                ),
                mean_normalized_regret=(
                    None if regret is None else regret.mean_normalized_regret
                ),
                normalized_regret_ci_lower=(
                    None
                    if regret is None
                    else regret.mean_normalized_regret_ci_lower
                ),
            )
        )

    signals = tuple(
        SignalFinding(
            loss_view=row.loss_view,
            feature=row.feature,
            overall_spearman_rho=row.overall_spearman_rho,
            evaluable_family_count=row.evaluable_family_count,
            family_direction_agreement_rate=(
                row.family_direction_agreement_rate
            ),
            evaluable_seed_count=row.evaluable_seed_count,
            seed_direction_agreement_rate=row.seed_direction_agreement_rate,
            supported=row.supported,
        )
        for row in signal_support
    )
    unavailable = _unavailable_capabilities(capabilities)
    unresolved = [
        "unselected-victim counterfactual outcomes require controlled replay",
        "serving-impact loss is not yet constructed",
    ]
    if unavailable:
        unresolved.append("one or more runtime observation capabilities are unavailable")
    if signal_evaluation.online_signal_supported is None:
        unresolved.append("signal stability has insufficient family/seed coverage")
    if not direct_loss_views:
        unresolved.append("headroom currently lacks a direct realized-loss view")

    return MethodSupportPack(
        schema_version="phase2a.method-support.v1",
        formal_campaign=formal_campaign,
        gate_outcome=gate_report.overall_outcome,
        prevalence=PrevalenceFinding(
            run_count=overall_prevalence.run_count,
            successful_run_count=overall_prevalence.successful_run_count,
            failed_run_count=overall_prevalence.failed_run_count,
            seed_count=overall_prevalence.seed_count,
            request_count=overall_prevalence.request_count,
            decision_count=overall_prevalence.decision_count,
            multi_candidate_decision_rate=(
                overall_prevalence.multi_candidate_decision_rate
            ),
            forced_release_per_request=(
                overall_prevalence.forced_release_per_request
            ),
            mean_candidate_count=overall_prevalence.mean_candidate_count,
            maximum_candidate_count=overall_prevalence.maximum_candidate_count,
            mean_required_blocks=overall_prevalence.mean_required_blocks,
            mean_selected_release_count=(
                overall_prevalence.mean_selected_release_count
            ),
            repeated_pressure_run_rate=(
                overall_prevalence.repeated_pressure_run_rate
            ),
            repeated_logical_release_count=(
                overall_prevalence.repeated_logical_release_count
            ),
        ),
        candidate_heterogeneity=feature_findings,
        outcome_heterogeneity_and_headroom=tuple(loss_findings),
        high_regret_examples=tuple(
            HighRegretExample(
                run_id=row.run_id,
                decision_event_index=row.decision_event_index,
                loss_view=row.loss_view,
                selected_loss=row.selected_loss,
                hindsight_best_loss=row.hindsight_best_loss,
                absolute_regret=row.absolute_regret,
                normalized_regret=row.normalized_regret,
            )
            for row in sorted(
                decision_regret,
                key=lambda item: item.absolute_regret,
                reverse=True,
            )[:10]
        ),
        signal_evaluation_status=signal_evaluation.status,
        signals=signals,
        constraints=MethodConstraints(
            safe_online_features=(
                "block_count",
                "initially_reclaimable_block_count",
                "retention_deadline_timestamp",
                "waiting_followup",
                "next_tool_type",
                "elapsed_since_ttl_decision_seconds",
                "prefill_reload_seconds",
                "eta",
                "queue_delay_t_seconds",
            ),
            weak_or_unstable_online_features=tuple(
                sorted({row.feature for row in signals if not row.supported})
            ),
            future_only_forbidden_online=(
                "returned_after_decision",
                "time_to_return_seconds",
                "physical_eviction_count",
                "recomputed_tokens",
                "serving_impact",
                "hindsight_best_candidate",
                "absolute_regret",
                "normalized_regret",
            ),
            unavailable_capabilities=unavailable,
            required_corner_cases=(
                "multiple selected releases",
                "repeated release of one logical object",
                "block-slot reuse with changing content",
                "shared or overlapping block ownership",
                "selected candidate never returns",
                "unselected candidate returns first",
                "ties in realized loss",
            ),
            best_supported_loss_views=gate_report.passing_loss_views,
            unresolved_questions=tuple(unresolved),
        ),
        source_tables=(
            "runs.jsonl",
            "decisions.jsonl",
            "decision_candidates.jsonl",
            "candidate_feature_spreads.jsonl",
            "candidate_loss_evidence.jsonl",
            "candidate_loss_spreads.jsonl",
            "decision_regret.jsonl",
            "signal_associations.jsonl",
            "capabilities.jsonl",
            "empirical_gap_report.jsonl",
        ),
    )
