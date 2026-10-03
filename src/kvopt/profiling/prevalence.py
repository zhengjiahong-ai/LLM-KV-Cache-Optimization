"""Baseline prevalence summaries for formal Phase 2A profiling."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .datasets import DecisionRow, LogicalReleaseRow, RunRow
from .ingestion import ArtifactValidationError
from .request_outcomes import RequestOutcomeRow


@dataclass(frozen=True, slots=True)
class RunPrevalenceRow:
    """Per-run pressure and forced-release prevalence."""

    run_id: str
    scenario_family_id: str | None
    seed: int
    run_status: str
    request_count: int
    decision_count: int
    multi_candidate_decision_count: int
    forced_release_per_request: float | None
    repeated_pressure: bool
    repeated_logical_release_count: int


@dataclass(frozen=True, slots=True)
class PrevalenceSummaryRow:
    """Aggregate baseline prevalence for one reporting scope."""

    scope: str
    scenario_family_id: str | None
    run_count: int
    successful_run_count: int
    failed_run_count: int
    seed_count: int
    request_count: int
    decision_count: int
    multi_candidate_decision_count: int
    multi_candidate_decision_rate: float | None
    forced_release_per_request: float | None
    mean_candidate_count: float | None
    minimum_candidate_count: int | None
    maximum_candidate_count: int | None
    mean_required_blocks: float | None
    minimum_required_blocks: int | None
    maximum_required_blocks: int | None
    mean_selected_release_count: float | None
    repeated_pressure_run_count: int
    repeated_pressure_run_rate: float | None
    repeated_logical_release_count: int


@dataclass(frozen=True, slots=True)
class PrevalenceTables:
    """Run-level and aggregate baseline prevalence tables."""

    runs: tuple[RunPrevalenceRow, ...]
    summary: tuple[PrevalenceSummaryRow, ...]


def _mean(values: Sequence[int]) -> float | None:
    return None if not values else sum(values) / len(values)


def build_prevalence_tables(
    runs: Iterable[RunRow],
    decisions: Iterable[DecisionRow],
    logical_releases: Iterable[LogicalReleaseRow],
    requests: Iterable[RequestOutcomeRow],
) -> PrevalenceTables:
    """Summarize prevalence without folding failed runs into event rates."""

    run_rows = tuple(runs)
    run_by_id: dict[str, RunRow] = {}
    for run in run_rows:
        if run.run_id in run_by_id:
            raise ArtifactValidationError(
                f"duplicate prevalence run_id: {run.run_id}"
            )
        run_by_id[run.run_id] = run

    decisions_by_run: dict[str, list[DecisionRow]] = defaultdict(list)
    for decision in decisions:
        if decision.run_id not in run_by_id:
            raise ArtifactValidationError(
                f"decision references unknown prevalence run: {decision.run_id}"
            )
        decisions_by_run[decision.run_id].append(decision)

    request_count_by_run: dict[str, int] = defaultdict(int)
    for request in requests:
        if request.run_id not in run_by_id:
            raise ArtifactValidationError(
                f"request references unknown prevalence run: {request.run_id}"
            )
        request_count_by_run[request.run_id] += 1

    releases_by_identity: dict[tuple[str, str, str], int] = defaultdict(int)
    for release in logical_releases:
        if release.run_id not in run_by_id:
            raise ArtifactValidationError(
                f"release references unknown prevalence run: {release.run_id}"
            )
        releases_by_identity[
            (release.run_id, release.program_id, release.prefix_id)
        ] += 1
    repeated_by_run: dict[str, int] = defaultdict(int)
    for (run_id, _, _), count in releases_by_identity.items():
        repeated_by_run[run_id] += max(0, count - 1)

    per_run: list[RunPrevalenceRow] = []
    for run in run_rows:
        run_decisions = decisions_by_run[run.run_id]
        request_count = request_count_by_run[run.run_id]
        decision_count = len(run_decisions)
        per_run.append(
            RunPrevalenceRow(
                run_id=run.run_id,
                scenario_family_id=run.scenario_family_id,
                seed=run.seed,
                run_status=run.status,
                request_count=request_count,
                decision_count=decision_count,
                multi_candidate_decision_count=sum(
                    row.candidate_count >= 2 for row in run_decisions
                ),
                forced_release_per_request=(
                    None
                    if request_count == 0
                    else decision_count / request_count
                ),
                repeated_pressure=decision_count > 1,
                repeated_logical_release_count=repeated_by_run[run.run_id],
            )
        )

    scopes: dict[tuple[str, str | None], list[RunRow]] = defaultdict(list)
    for run in run_rows:
        scopes[("overall", None)].append(run)
        if run.scenario_family_id is not None:
            scopes[("scenario_family", run.scenario_family_id)].append(run)

    per_run_by_id = {row.run_id: row for row in per_run}
    summary: list[PrevalenceSummaryRow] = []
    for (scope, family_id), scope_runs in sorted(
        scopes.items(),
        key=lambda item: (item[0][0], item[0][1] or ""),
    ):
        successful = [run for run in scope_runs if run.status == "success"]
        successful_ids = {run.run_id for run in successful}
        scope_decisions = [
            decision
            for run_id in successful_ids
            for decision in decisions_by_run[run_id]
        ]
        request_count = sum(
            request_count_by_run[run_id] for run_id in successful_ids
        )
        multi_count = sum(
            decision.candidate_count >= 2 for decision in scope_decisions
        )
        candidate_counts = [row.candidate_count for row in scope_decisions]
        required_blocks = [row.required_blocks for row in scope_decisions]
        selected_counts = [
            row.selected_release_count for row in scope_decisions
        ]
        repeated_pressure_count = sum(
            per_run_by_id[run.run_id].repeated_pressure
            for run in successful
        )
        summary.append(
            PrevalenceSummaryRow(
                scope=scope,
                scenario_family_id=family_id,
                run_count=len(scope_runs),
                successful_run_count=len(successful),
                failed_run_count=len(scope_runs) - len(successful),
                seed_count=len({run.seed for run in successful}),
                request_count=request_count,
                decision_count=len(scope_decisions),
                multi_candidate_decision_count=multi_count,
                multi_candidate_decision_rate=(
                    None
                    if not scope_decisions
                    else multi_count / len(scope_decisions)
                ),
                forced_release_per_request=(
                    None
                    if request_count == 0
                    else len(scope_decisions) / request_count
                ),
                mean_candidate_count=_mean(candidate_counts),
                minimum_candidate_count=(
                    None if not candidate_counts else min(candidate_counts)
                ),
                maximum_candidate_count=(
                    None if not candidate_counts else max(candidate_counts)
                ),
                mean_required_blocks=_mean(required_blocks),
                minimum_required_blocks=(
                    None if not required_blocks else min(required_blocks)
                ),
                maximum_required_blocks=(
                    None if not required_blocks else max(required_blocks)
                ),
                mean_selected_release_count=_mean(selected_counts),
                repeated_pressure_run_count=repeated_pressure_count,
                repeated_pressure_run_rate=(
                    None
                    if not successful
                    else repeated_pressure_count / len(successful)
                ),
                repeated_logical_release_count=sum(
                    repeated_by_run[run_id] for run_id in successful_ids
                ),
            )
        )

    return PrevalenceTables(runs=tuple(per_run), summary=tuple(summary))
