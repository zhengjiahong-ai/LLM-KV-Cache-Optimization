from kvopt.profiling.analysis import (
    CandidateFeatureSpreadRow,
    DecisionRegretRow,
)
from kvopt.profiling.loss_views import CandidateLossSpreadRow
from kvopt.profiling.statistics import (
    AnalysisRunMetadata,
    build_statistical_summary_tables,
)


def _metadata(
    run_id: str,
    seed: int,
    *,
    valid: bool = True,
) -> AnalysisRunMetadata:
    return AnalysisRunMetadata(
        run_id=run_id,
        scenario_id="scenario-a",
        seed=seed,
        valid_for_candidate_analysis=valid,
    )


def _spread(run_id: str, spread: float) -> CandidateFeatureSpreadRow:
    return CandidateFeatureSpreadRow(
        run_id=run_id,
        decision_event_index=10,
        feature="block_count",
        candidate_count=2,
        minimum=1.0,
        maximum=1.0 + spread,
        spread=spread,
    )


def _regret(
    run_id: str,
    *,
    normalized: float,
    selected_is_best: bool,
    best_set_count: int = 1,
) -> DecisionRegretRow:
    return DecisionRegretRow(
        run_id=run_id,
        decision_event_index=10,
        loss_view="proxy",
        candidate_count=2,
        selection_count=1,
        selected_candidates=(("a", "prefix-a"),),
        hindsight_mandatory_candidates=(),
        hindsight_boundary_candidates=(("b", "prefix-b"),),
        hindsight_best_set_count=best_set_count,
        selected_loss=4.0,
        hindsight_best_loss=4.0 * (1.0 - normalized),
        absolute_regret=4.0 * normalized,
        normalized_regret=normalized,
        selected_is_hindsight_best=selected_is_best,
    )


def _loss_spread(run_id: str, spread: float) -> CandidateLossSpreadRow:
    return CandidateLossSpreadRow(
        run_id=run_id,
        decision_event_index=10,
        loss_view="proxy",
        candidate_count=2,
        minimum_loss=0.0,
        maximum_loss=spread,
        loss_spread=spread,
    )


def test_statistics_aggregate_overall_and_scenario_with_bootstrap() -> None:
    tables = build_statistical_summary_tables(
        (_metadata("run-1", 1), _metadata("run-2", 2)),
        (_spread("run-1", 1.0), _spread("run-2", 3.0)),
        (_loss_spread("run-1", 2.0), _loss_spread("run-2", 4.0)),
        (
            _regret("run-1", normalized=0.5, selected_is_best=False),
            _regret("run-2", normalized=0.0, selected_is_best=True),
        ),
        bootstrap_resamples=200,
        bootstrap_seed=7,
    )
    overall_feature = next(
        row
        for row in tables.candidate_heterogeneity
        if row.scope == "overall"
    )
    overall_regret = next(
        row for row in tables.regret if row.scope == "overall"
    )
    overall_loss = next(
        row for row in tables.loss_heterogeneity if row.scope == "overall"
    )

    assert len(tables.candidate_heterogeneity) == 2
    assert overall_feature.seed_count == 2
    assert overall_feature.positive_spread_rate == 1.0
    assert overall_feature.mean_spread == 2.0
    assert overall_feature.mean_spread_ci_lower <= 2.0
    assert overall_feature.mean_spread_ci_upper >= 2.0
    assert overall_regret.non_tied_misselection_rate == 0.5
    assert overall_regret.mean_normalized_regret == 0.25
    assert overall_loss.mean_spread == 3.0
    assert overall_loss.positive_spread_rate == 1.0


def test_statistics_exclude_invalid_runs_and_preserve_ties() -> None:
    tables = build_statistical_summary_tables(
        (
            _metadata("run-valid", 1),
            _metadata("run-invalid", 2, valid=False),
        ),
        (_spread("run-valid", 0.0), _spread("run-invalid", 100.0)),
        (
            _loss_spread("run-valid", 0.0),
            _loss_spread("run-invalid", 100.0),
        ),
        (
            _regret(
                "run-valid",
                normalized=0.0,
                selected_is_best=True,
                best_set_count=2,
            ),
            _regret(
                "run-invalid",
                normalized=1.0,
                selected_is_best=False,
            ),
        ),
        bootstrap_resamples=20,
    )
    overall_feature = next(
        row
        for row in tables.candidate_heterogeneity
        if row.scope == "overall"
    )
    overall_regret = next(
        row for row in tables.regret if row.scope == "overall"
    )

    assert overall_feature.decision_count == 1
    assert overall_feature.mean_spread == 0.0
    assert overall_regret.decision_count == 1
    assert overall_regret.non_tied_decision_count == 0
    assert overall_regret.non_tied_misselection_rate is None
