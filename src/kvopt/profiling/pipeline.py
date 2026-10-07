"""Build and persist the complete Phase 2A derived dataset bundle."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .analysis import (
    CandidateFeatureSpreadRow,
    DecisionRegretRow,
    build_candidate_feature_spreads,
)
from .datasets import (
    DecisionCandidateRow,
    DecisionRow,
    LogicalReleaseRow,
    PhysicalEvictionRow,
    RunRow,
    build_decision_tables,
    build_logical_releases_table,
    build_physical_evictions_table,
    build_runs_table,
)
from .decision_outcomes import (
    DecisionOutcomeRow,
    HorizonSensitivityRow,
    HorizonSensitivitySummaryRow,
    build_decision_outcomes_table,
    build_horizon_sensitivity_tables,
)
from .gate import (
    EmpiricalGapInputs,
    EmpiricalGapReport,
    evaluate_empirical_gap_gate,
)
from .ingestion import (
    ArtifactValidationError,
    RawRunArtifacts,
    load_run_artifacts,
)
from .loss_views import (
    CandidateLossEvidenceRow,
    CandidateLossSpreadRow,
    LossViewAvailabilityRow,
    build_loss_view_tables,
)
from .method_support import (
    CapabilityFinding,
    MethodSupportPack,
    build_method_support_pack,
)
from .prevalence import (
    PrevalenceSummaryRow,
    RunPrevalenceRow,
    build_prevalence_tables,
)
from .request_outcomes import RequestOutcomeRow, build_request_outcomes_table
from .runtime_evidence import (
    RequestRuntimeEvidenceRow,
    build_request_runtime_evidence_table,
)
from .signals import (
    SignalAssociationRow,
    SignalEvaluationRow,
    SignalFeatureCoverageRow,
    SignalRunMetadata,
    SignalSupportRow,
    build_signal_analysis_tables,
)
from .statistics import (
    AnalysisRunMetadata,
    CandidateHeterogeneitySummaryRow,
    LossHeterogeneitySummaryRow,
    RegretSummaryRow,
    build_statistical_summary_tables,
)


@dataclass(frozen=True, slots=True)
class RunValidityRow:
    """Run-level gate for candidate-ranking analysis."""

    run_id: str
    run_status: str
    decision_count: int
    multi_candidate_decision_count: int
    valid_decision_count: int
    valid_for_candidate_analysis: bool
    invalid_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionValidityRow:
    """Decision-level gate for candidate comparison and regret."""

    run_id: str
    decision_event_index: int
    candidate_count: int
    selected_release_count: int
    post_decision_lifecycle_traceable: bool
    valid_for_candidate_analysis: bool
    invalid_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilityRow:
    """One explicitly reported observation capability for one run."""

    run_id: str
    capability: str
    availability: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class DerivedDatasetBundle:
    """All seven canonical tables plus analysis metadata."""

    runs: tuple[RunRow, ...]
    decisions: tuple[DecisionRow, ...]
    decision_candidates: tuple[DecisionCandidateRow, ...]
    logical_releases: tuple[LogicalReleaseRow, ...]
    physical_evictions: tuple[PhysicalEvictionRow, ...]
    request_outcomes: tuple[RequestOutcomeRow, ...]
    request_runtime_evidence: tuple[RequestRuntimeEvidenceRow, ...]
    decision_outcomes: tuple[DecisionOutcomeRow, ...]
    horizon_sensitivity: tuple[HorizonSensitivityRow, ...]
    horizon_sensitivity_summary: tuple[HorizonSensitivitySummaryRow, ...]
    candidate_loss_evidence: tuple[CandidateLossEvidenceRow, ...]
    loss_view_availability: tuple[LossViewAvailabilityRow, ...]
    decision_regret: tuple[DecisionRegretRow, ...]
    candidate_loss_spreads: tuple[CandidateLossSpreadRow, ...]
    candidate_feature_spreads: tuple[CandidateFeatureSpreadRow, ...]
    candidate_heterogeneity_summary: tuple[
        CandidateHeterogeneitySummaryRow,
        ...,
    ]
    regret_summary: tuple[RegretSummaryRow, ...]
    loss_heterogeneity_summary: tuple[LossHeterogeneitySummaryRow, ...]
    decision_validity: tuple[DecisionValidityRow, ...]
    run_validity: tuple[RunValidityRow, ...]
    capabilities: tuple[CapabilityRow, ...]
    signal_associations: tuple[SignalAssociationRow, ...]
    signal_support: tuple[SignalSupportRow, ...]
    signal_evaluation: SignalEvaluationRow
    signal_feature_coverage: tuple[SignalFeatureCoverageRow, ...]
    run_prevalence: tuple[RunPrevalenceRow, ...]
    prevalence_summary: tuple[PrevalenceSummaryRow, ...]
    empirical_gap_report: EmpiricalGapReport
    method_support_pack: MethodSupportPack
    formal_campaign: bool


_TRACEABLE_LIFECYCLE_EVENTS = {
    "REQUEST_ARRIVED",
    "VLLM_PREFIX_SNAPSHOT",
    "TURN_FINISHED",
    "PROGRAM_COMPLETED",
}

_BOOTSTRAP_RESAMPLES = 2_000
_BOOTSTRAP_SEED = 0
_CONFIDENCE_LEVEL = 0.95

_REQUIRED_V5_CAPABILITIES = {
    "runtime_identity",
    "logical_lifecycle",
    "prefix_block_mapping",
    "forced_release_snapshot",
    "native_block_eviction",
    "native_block_content_identity",
    "native_block_logical_owners",
    "native_block_lru_position",
    "generated_token_count",
    "native_apc_hit_miss",
    "recomputed_prefill_tokens",
    "native_first_token_timestamp",
    "native_scheduler_admission_timestamp",
    "hardware_counters",
}

_V5_CAPABILITY_STATUSES = {"AVAILABLE", "UNAVAILABLE", "ERROR"}


def _analysis_provenance() -> dict[str, object]:
    """Record the analysis code revision without requiring Git at runtime."""

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        git_sha = None
        git_dirty = None
    else:
        git_sha = revision.stdout.strip() if revision.returncode == 0 else None
        git_dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return {
        "entry_point": "kvopt.profiling.cli",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
    }



def discover_run_artifacts(
    artifact_root: str | Path,
) -> tuple[RawRunArtifacts, ...]:
    """Discover and validate run directories below an artifact root."""

    root = Path(artifact_root).resolve()
    if not root.is_dir():
        raise ArtifactValidationError(
            f"artifact root does not exist: {root}"
        )

    run_directories = tuple(
        sorted({manifest.parent for manifest in root.rglob("run.json")})
    )
    if not run_directories:
        raise ArtifactValidationError(
            f"no run.json files found below artifact root: {root}"
        )
    return tuple(load_run_artifacts(path) for path in run_directories)


def _build_decision_validity(
    raw_runs: tuple[RawRunArtifacts, ...],
    run_rows: tuple[RunRow, ...],
    decisions: tuple[DecisionRow, ...],
) -> tuple[DecisionValidityRow, ...]:
    artifacts_by_run = {run.run_id: run for run in raw_runs}
    run_rows_by_id = {run.run_id: run for run in run_rows}
    rows: list[DecisionValidityRow] = []
    for decision in decisions:
        artifacts = artifacts_by_run[decision.run_id]
        run_row = run_rows_by_id[decision.run_id]
        has_future_lifecycle = any(
            event.get("event_type") in _TRACEABLE_LIFECYCLE_EVENTS
            and isinstance(event.get("event_index"), int)
            and event["event_index"] > decision.decision_event_index
            for event in artifacts.events
        )
        reasons: list[str] = []
        if run_row.status != "success":
            reasons.append("run_status_not_success")
        if decision.candidate_count < 2:
            reasons.append("fewer_than_two_candidates")
        if decision.selected_release_count == 0:
            reasons.append("no_selected_release")
        if not has_future_lifecycle:
            reasons.append("post_decision_lifecycle_not_traceable")
        rows.append(
            DecisionValidityRow(
                run_id=decision.run_id,
                decision_event_index=decision.decision_event_index,
                candidate_count=decision.candidate_count,
                selected_release_count=decision.selected_release_count,
                post_decision_lifecycle_traceable=has_future_lifecycle,
                valid_for_candidate_analysis=not reasons,
                invalid_reasons=tuple(reasons),
            )
        )
    return tuple(rows)


def _build_run_validity(
    run_rows: tuple[RunRow, ...],
    decision_validity: tuple[DecisionValidityRow, ...],
) -> tuple[RunValidityRow, ...]:
    decisions_by_run: dict[str, list[DecisionValidityRow]] = {}
    for decision in decision_validity:
        decisions_by_run.setdefault(decision.run_id, []).append(decision)

    rows: list[RunValidityRow] = []
    for run_row in run_rows:
        run_decisions = decisions_by_run.get(run_row.run_id, [])
        multi_candidate = [
            decision
            for decision in run_decisions
            if decision.candidate_count >= 2
        ]
        valid_decision_count = sum(
            decision.valid_for_candidate_analysis
            for decision in run_decisions
        )

        reasons: list[str] = []
        if run_row.status != "success":
            reasons.append("run_status_not_success")
        if not run_decisions:
            reasons.append("no_forced_release_decision")
        elif not multi_candidate:
            reasons.append("no_multi_candidate_decision")
        elif valid_decision_count == 0:
            reasons.append("no_traceable_selected_multi_candidate_decision")

        rows.append(
            RunValidityRow(
                run_id=run_row.run_id,
                run_status=run_row.status,
                decision_count=len(run_decisions),
                multi_candidate_decision_count=len(multi_candidate),
                valid_decision_count=valid_decision_count,
                valid_for_candidate_analysis=(
                    run_row.status == "success" and valid_decision_count > 0
                ),
                invalid_reasons=tuple(reasons),
            )
        )
    return tuple(rows)


def _build_capabilities(
    run_rows: tuple[RunRow, ...],
) -> tuple[tuple[CapabilityRow, ...], bool]:
    rows: list[CapabilityRow] = []
    all_contracts_complete = True
    for run in run_rows:
        seen: set[str] = set()
        run_contract_complete = run.observation_capability_contract_complete
        for capability, raw_value in sorted(
            run.observation_availability.items()
        ):
            seen.add(capability)
            reason: str | None = None
            if isinstance(raw_value, str) and raw_value.strip():
                # Legacy pre-V5 manifests remain readable for diagnostics, but
                # string-only capability declarations do not satisfy V5.
                availability = raw_value
                run_contract_complete = False
            elif isinstance(raw_value, dict):
                raw_availability = raw_value.get(
                    "availability",
                    raw_value.get("status"),
                )
                raw_reason = raw_value.get("reason")
                if not isinstance(raw_availability, str) or not raw_availability.strip():
                    raise ArtifactValidationError(
                        f"capability {capability} availability must be non-empty text"
                    )
                availability = raw_availability
                reason = raw_reason
                if capability in _REQUIRED_V5_CAPABILITIES:
                    if availability not in _V5_CAPABILITY_STATUSES:
                        run_contract_complete = False
                    if availability in {"UNAVAILABLE", "ERROR"} and (
                        not isinstance(reason, str) or not reason.strip()
                    ):
                        run_contract_complete = False
            else:
                raise ArtifactValidationError(
                    f"capability {capability} must be text or an object"
                )
            rows.append(
                CapabilityRow(
                    run_id=run.run_id,
                    capability=capability,
                    availability=availability,
                    reason=reason,
                )
            )

        if not _REQUIRED_V5_CAPABILITIES.issubset(seen):
            run_contract_complete = False
        all_contracts_complete = (
            all_contracts_complete and run_contract_complete
        )
    return tuple(rows), all_contracts_complete


def build_derived_dataset_bundle(
    runs: Iterable[RawRunArtifacts],
    *,
    formal_campaign: bool = False,
) -> DerivedDatasetBundle:
    """Build every canonical Phase 2A table from validated raw runs."""

    raw_runs = tuple(runs)
    run_rows = build_runs_table(raw_runs)
    decision_tables = build_decision_tables(raw_runs)
    logical_releases = build_logical_releases_table(raw_runs)
    physical_evictions = build_physical_evictions_table(raw_runs)
    request_outcomes = build_request_outcomes_table(raw_runs)
    request_runtime_evidence = build_request_runtime_evidence_table(raw_runs)
    decision_outcomes = build_decision_outcomes_table(raw_runs)
    horizon_sensitivity, horizon_sensitivity_summary = (
        build_horizon_sensitivity_tables(decision_outcomes)
    )
    loss_views = build_loss_view_tables(
        decision_tables.candidates,
        decision_outcomes,
        request_runtime_evidence,
    )
    decision_validity = _build_decision_validity(
        raw_runs,
        run_rows,
        decision_tables.decisions,
    )
    run_validity = _build_run_validity(
        run_rows,
        decision_validity,
    )
    validity_by_run = {row.run_id: row for row in run_validity}
    feature_spreads = build_candidate_feature_spreads(
        decision_tables.candidates
    )
    valid_decision_keys = {
        (row.run_id, row.decision_event_index)
        for row in decision_validity
        if row.valid_for_candidate_analysis
    }
    summaries = build_statistical_summary_tables(
        (
            AnalysisRunMetadata(
                run_id=row.run_id,
                scenario_id=row.scenario_id,
                seed=row.seed,
                valid_for_candidate_analysis=validity_by_run[
                    row.run_id
                ].valid_for_candidate_analysis,
            )
            for row in run_rows
        ),
        (
            row
            for row in feature_spreads
            if (row.run_id, row.decision_event_index)
            in valid_decision_keys
        ),
        (
            row
            for row in loss_views.loss_spreads
            if (row.run_id, row.decision_event_index)
            in valid_decision_keys
        ),
        (
            row
            for row in loss_views.decision_regret
            if (row.run_id, row.decision_event_index)
            in valid_decision_keys
        ),
        bootstrap_resamples=_BOOTSTRAP_RESAMPLES,
        bootstrap_seed=_BOOTSTRAP_SEED,
        confidence_level=_CONFIDENCE_LEVEL,
    )
    valid_run_ids = {run_id for run_id, _ in valid_decision_keys}
    valid_run_rows = [row for row in run_rows if row.run_id in valid_run_ids]
    signal_tables = build_signal_analysis_tables(
        (
            row
            for row in decision_tables.candidates
            if (row.run_id, row.decision_event_index)
            in valid_decision_keys
        ),
        (
            row
            for row in loss_views.comparable_losses
            if (row.run_id, row.decision_event_index)
            in valid_decision_keys
        ),
        (
            SignalRunMetadata(
                run_id=row.run_id,
                scenario_family_id=row.scenario_family_id,
                seed=row.seed,
            )
            for row in valid_run_rows
        ),
    )
    physical_evidence = [
        row
        for row in loss_views.evidence
        if row.loss_view == "observed_physical_eviction_blocks"
    ]
    direct_loss_views = tuple(
        sorted(
            {
                row.loss_view
                for row in loss_views.evidence
                if row.availability == "available"
                and row.evidence_kind == "direct_runtime_observation"
            }
        )
    )
    capabilities, capability_contract_complete = _build_capabilities(
        run_rows
    )
    gap_report = evaluate_empirical_gap_gate(
        EmpiricalGapInputs(
            formal_campaign=formal_campaign,
            otherwise_valid_decision_count=sum(
                row.candidate_count >= 2
                and "run_status_not_success" not in row.invalid_reasons
                for row in decision_validity
            ),
            joinable_decision_count=len(valid_decision_keys),
            valid_decision_count=len(valid_decision_keys),
            scenario_family_count=len(
                {
                    row.scenario_family_id
                    for row in valid_run_rows
                    if row.scenario_family_id is not None
                }
            ),
            seed_count=len({row.seed for row in valid_run_rows}),
            physical_missingness_explicit=all(
                row.availability == "available"
                or row.unavailable_reason is not None
                for row in physical_evidence
            ),
            provenance_complete=all(
                row.run_id and row.decision_event_index >= 0
                for row in decision_tables.candidates
            ),
            capability_contract_complete=capability_contract_complete,
            online_signal_supported=(
                signal_tables.evaluation.online_signal_supported
            ),
            direct_loss_views=direct_loss_views,
        ),
        summaries.loss_heterogeneity,
        summaries.regret,
    )
    prevalence = build_prevalence_tables(
        run_rows,
        decision_tables.decisions,
        logical_releases,
        request_outcomes,
    )
    method_support_pack = build_method_support_pack(
        formal_campaign=formal_campaign,
        prevalence=prevalence.summary,
        candidate_heterogeneity=summaries.candidate_heterogeneity,
        loss_heterogeneity=summaries.loss_heterogeneity,
        regret_summary=summaries.regret,
        decision_regret=loss_views.decision_regret,
        signal_support=signal_tables.support,
        signal_evaluation=signal_tables.evaluation,
        signal_feature_coverage=signal_tables.feature_coverage,
        capabilities=tuple(
            CapabilityFinding(
                run_id=row.run_id,
                capability=row.capability,
                availability=row.availability,
                reason=row.reason,
            )
            for row in capabilities
        ),
        direct_loss_views=direct_loss_views,
        gate_report=gap_report,
    )
    return DerivedDatasetBundle(
        runs=run_rows,
        decisions=decision_tables.decisions,
        decision_candidates=decision_tables.candidates,
        logical_releases=logical_releases,
        physical_evictions=physical_evictions,
        request_outcomes=request_outcomes,
        request_runtime_evidence=request_runtime_evidence,
        decision_outcomes=decision_outcomes,
        horizon_sensitivity=horizon_sensitivity,
        horizon_sensitivity_summary=horizon_sensitivity_summary,
        candidate_loss_evidence=loss_views.evidence,
        loss_view_availability=loss_views.availability,
        decision_regret=loss_views.decision_regret,
        candidate_loss_spreads=loss_views.loss_spreads,
        candidate_feature_spreads=feature_spreads,
        candidate_heterogeneity_summary=summaries.candidate_heterogeneity,
        regret_summary=summaries.regret,
        loss_heterogeneity_summary=summaries.loss_heterogeneity,
        decision_validity=decision_validity,
        run_validity=run_validity,
        capabilities=capabilities,
        signal_associations=signal_tables.associations,
        signal_support=signal_tables.support,
        signal_evaluation=signal_tables.evaluation,
        signal_feature_coverage=signal_tables.feature_coverage,
        run_prevalence=prevalence.runs,
        prevalence_summary=prevalence.summary,
        empirical_gap_report=gap_report,
        method_support_pack=method_support_pack,
        formal_campaign=formal_campaign,
    )


def _write_jsonl(path: Path, rows: Sequence[Any]) -> None:
    with path.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(
                json.dumps(
                    asdict(row),
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            output.write("\n")


def write_derived_dataset_bundle(
    bundle: DerivedDatasetBundle,
    output_dir: Path,
) -> None:
    """Write a new derived directory without overwriting existing data."""

    output_dir.mkdir(parents=True, exist_ok=False)
    tables = {
        "runs": bundle.runs,
        "decisions": bundle.decisions,
        "decision_candidates": bundle.decision_candidates,
        "logical_releases": bundle.logical_releases,
        "physical_evictions": bundle.physical_evictions,
        "request_outcomes": bundle.request_outcomes,
        "request_runtime_evidence": bundle.request_runtime_evidence,
        "decision_outcomes": bundle.decision_outcomes,
        "horizon_sensitivity": bundle.horizon_sensitivity,
        "horizon_sensitivity_summary": bundle.horizon_sensitivity_summary,
        "candidate_loss_evidence": bundle.candidate_loss_evidence,
        "loss_view_availability": bundle.loss_view_availability,
        "decision_regret": bundle.decision_regret,
        "candidate_loss_spreads": bundle.candidate_loss_spreads,
        "candidate_feature_spreads": bundle.candidate_feature_spreads,
        "candidate_heterogeneity_summary": (
            bundle.candidate_heterogeneity_summary
        ),
        "regret_summary": bundle.regret_summary,
        "loss_heterogeneity_summary": bundle.loss_heterogeneity_summary,
        "decision_validity": bundle.decision_validity,
        "run_validity": bundle.run_validity,
        "capabilities": bundle.capabilities,
        "signal_associations": bundle.signal_associations,
        "signal_support": bundle.signal_support,
        "signal_evaluation": (bundle.signal_evaluation,),
        "signal_feature_coverage": bundle.signal_feature_coverage,
        "run_prevalence": bundle.run_prevalence,
        "prevalence_summary": bundle.prevalence_summary,
        "empirical_gap_report": (bundle.empirical_gap_report,),
    }
    for name, rows in tables.items():
        _write_jsonl(output_dir / f"{name}.jsonl", rows)

    (output_dir / "method_support_pack.json").write_text(
        json.dumps(
            asdict(bundle.method_support_pack),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "phase2a.derived.v4",
        "analysis_provenance": _analysis_provenance(),
        "source_run_ids": [row.run_id for row in bundle.runs],
        "row_counts": {name: len(rows) for name, rows in tables.items()},
        "method_support_pack": "method_support_pack.json",
        "analysis_parameters": {
            "bootstrap_resamples": _BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": _BOOTSTRAP_SEED,
            "confidence_level": _CONFIDENCE_LEVEL,
            "formal_campaign": bundle.formal_campaign,
            "canonical_loss_view": "planned_return_weighted_prefill_proxy",
            "canonical_timing_semantics": "planned_arrival_offsets",
            "observed_sensitivity_loss_view": (
                "observed_return_weighted_prefill_proxy_sensitivity"
            ),
            "observed_sensitivity_gate_eligible": False,
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
