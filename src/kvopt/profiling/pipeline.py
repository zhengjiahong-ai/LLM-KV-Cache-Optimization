"""Build and persist the complete Phase 2A derived dataset bundle."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .analysis import DecisionRegretRow
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
from .decision_outcomes import DecisionOutcomeRow, build_decision_outcomes_table
from .ingestion import (
    ArtifactValidationError,
    RawRunArtifacts,
    load_run_artifacts,
)
from .loss_views import (
    CandidateLossEvidenceRow,
    LossViewAvailabilityRow,
    build_loss_view_tables,
)
from .request_outcomes import RequestOutcomeRow, build_request_outcomes_table


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
    decision_outcomes: tuple[DecisionOutcomeRow, ...]
    candidate_loss_evidence: tuple[CandidateLossEvidenceRow, ...]
    loss_view_availability: tuple[LossViewAvailabilityRow, ...]
    decision_regret: tuple[DecisionRegretRow, ...]
    run_validity: tuple[RunValidityRow, ...]
    capabilities: tuple[CapabilityRow, ...]


_TRACEABLE_LIFECYCLE_EVENTS = {
    "REQUEST_ARRIVED",
    "VLLM_PREFIX_SNAPSHOT",
    "TURN_FINISHED",
    "PROGRAM_COMPLETED",
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


def _build_run_validity(
    raw_runs: tuple[RawRunArtifacts, ...],
    run_rows: tuple[RunRow, ...],
    decisions: tuple[DecisionRow, ...],
) -> tuple[RunValidityRow, ...]:
    decisions_by_run: dict[str, list[DecisionRow]] = {}
    for decision in decisions:
        decisions_by_run.setdefault(decision.run_id, []).append(decision)

    run_rows_by_id = {row.run_id: row for row in run_rows}
    rows: list[RunValidityRow] = []
    for artifacts in raw_runs:
        run_row = run_rows_by_id[artifacts.run_id]
        run_decisions = decisions_by_run.get(artifacts.run_id, [])
        multi_candidate = [
            decision
            for decision in run_decisions
            if decision.candidate_count >= 2
        ]
        valid_decision_count = 0
        for decision in multi_candidate:
            has_future_lifecycle = any(
                event.get("event_type") in _TRACEABLE_LIFECYCLE_EVENTS
                and isinstance(event.get("event_index"), int)
                and event["event_index"] > decision.decision_event_index
                for event in artifacts.events
            )
            if decision.selected_release_count > 0 and has_future_lifecycle:
                valid_decision_count += 1

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
                run_id=artifacts.run_id,
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
) -> tuple[CapabilityRow, ...]:
    rows: list[CapabilityRow] = []
    for run in run_rows:
        for capability, raw_value in sorted(
            run.observation_availability.items()
        ):
            reason: str | None = None
            if isinstance(raw_value, str) and raw_value.strip():
                availability = raw_value
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
                if raw_reason is not None and (
                    not isinstance(raw_reason, str) or not raw_reason.strip()
                ):
                    raise ArtifactValidationError(
                        f"capability {capability} reason must be non-empty text or null"
                    )
                availability = raw_availability
                reason = raw_reason
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
    return tuple(rows)


def build_derived_dataset_bundle(
    runs: Iterable[RawRunArtifacts],
) -> DerivedDatasetBundle:
    """Build every canonical Phase 2A table from validated raw runs."""

    raw_runs = tuple(runs)
    run_rows = build_runs_table(raw_runs)
    decision_tables = build_decision_tables(raw_runs)
    decision_outcomes = build_decision_outcomes_table(raw_runs)
    loss_views = build_loss_view_tables(
        decision_tables.candidates,
        decision_outcomes,
    )
    return DerivedDatasetBundle(
        runs=run_rows,
        decisions=decision_tables.decisions,
        decision_candidates=decision_tables.candidates,
        logical_releases=build_logical_releases_table(raw_runs),
        physical_evictions=build_physical_evictions_table(raw_runs),
        request_outcomes=build_request_outcomes_table(raw_runs),
        decision_outcomes=decision_outcomes,
        candidate_loss_evidence=loss_views.evidence,
        loss_view_availability=loss_views.availability,
        decision_regret=loss_views.decision_regret,
        run_validity=_build_run_validity(
            raw_runs,
            run_rows,
            decision_tables.decisions,
        ),
        capabilities=_build_capabilities(run_rows),
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
        "decision_outcomes": bundle.decision_outcomes,
        "candidate_loss_evidence": bundle.candidate_loss_evidence,
        "loss_view_availability": bundle.loss_view_availability,
        "decision_regret": bundle.decision_regret,
        "run_validity": bundle.run_validity,
        "capabilities": bundle.capabilities,
    }
    for name, rows in tables.items():
        _write_jsonl(output_dir / f"{name}.jsonl", rows)

    manifest = {
        "schema_version": "phase2a.derived.v1",
        "source_run_ids": [row.run_id for row in bundle.runs],
        "row_counts": {name: len(rows) for name, rows in tables.items()},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
