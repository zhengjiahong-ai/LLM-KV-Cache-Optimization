"""Tests for the executable rule-acceptance protocol."""

from __future__ import annotations

import pytest

from kvopt.costaware.acceptance import (
    FORMAL_FAMILIES,
    LEVEL_DIAGNOSTIC_ONLY,
    LEVEL_IMPLEMENTATION_ELIGIBLE,
    LEVEL_NOT_ACCEPTED,
    LEVEL_PROXY_CANDIDATE,
    LEVEL_RUNTIME_CANDIDATE,
    PRIMARY_METRIC_PROXY_LOSS,
    PRIMARY_METRIC_RECOMPUTED_TOKENS,
    AcceptanceCriteria,
    ClusterPairedDelta,
    ImplementationAttestation,
    RulePreregistration,
    bootstrap_cluster_ci,
    calibrate_latency_epsilon,
    cluster_paired_deltas,
    cluster_paired_result,
    evaluate_acceptance,
    family_direction_agreement,
    holdout_adequacy,
    latency_non_inferior,
)
from kvopt.costaware.offline_eval import RuleDecisionOutcome, RuleEvaluation

_BASELINE = "M0_p1b_executed_ordering"
_CHALLENGER = "H1_R1_reverse_deadline"

#: Small iteration count so the suite stays fast; the protocol's default is
#: 10_000 and is asserted separately.
_FAST = AcceptanceCriteria(bootstrap_iterations=400, bootstrap_seed=7)


def _delta(
    group: str,
    family: str | None,
    value: float,
    *,
    index: int = 10,
) -> ClusterPairedDelta:
    return ClusterPairedDelta(
        scenario_group=group,
        decision_event_index=index,
        scenario_family_id=family,
        baseline_loss=1.0,
        challenger_loss=1.0 - value,
        delta=value,
    )


def _deltas_across_families(value: float, *, per_family: int = 5) -> list:
    """``6 x per_family`` clusters, all moving by ``value``."""
    return [
        _delta(f"{family}-sc{position}-seed-101", family, value)
        for family in FORMAL_FAMILIES
        for position in range(per_family)
    ]


def _outcome(
    rule_id: str,
    run_id: str,
    family: str | None,
    selected_loss: float,
    *,
    index: int = 10,
) -> RuleDecisionOutcome:
    return RuleDecisionOutcome(
        rule_id=rule_id,
        run_id=run_id,
        decision_event_index=index,
        scenario_family_id=family,
        candidate_count=2,
        selection_count=1,
        loss_view="proxy",
        selected_identities=(("a", "p"),),
        selected_loss=selected_loss,
        hindsight_best_loss=0.0,
        absolute_regret=selected_loss,
        normalized_regret=0.0,
        selected_is_hindsight_best=False,
        candidate_loss_tied=False,
    )


def _evaluation(outcomes: list) -> RuleEvaluation:
    return RuleEvaluation(
        loss_view="proxy",
        evaluated_decisions=0,
        skipped_decisions=0,
        available_candidates=0,
        aggregates=(),
        outcomes=tuple(outcomes),
        degeneracy=(),
    )


def _preregistration(
    *, metric: str = PRIMARY_METRIC_PROXY_LOSS
) -> RulePreregistration:
    return RulePreregistration(
        rule_id=_CHALLENGER,
        family="H1",
        formula="ascending (deadline, native lru, identity)",
        direction="ascending",
        tie_break="identity",
        fallback="frozen baseline ordering",
        boundary="forced-release candidate sets only",
        primary_metric=metric,
        frozen_at="2026-10-07",
        frozen_commit="0" * 40,
    )


# --- cluster paired deltas -------------------------------------------------


def test_cluster_deltas_count_each_cluster_once_regardless_of_seeds() -> None:
    """Seeds are runtime noise, so a cluster with three seeds is one sample."""
    outcomes = [
        _outcome(_BASELINE, f"f1-sc-seed-{seed}", "F1", 1.0)
        for seed in (101, 211, 307)
    ] + [
        _outcome(_CHALLENGER, f"f1-sc-seed-{seed}", "F1", 0.5)
        for seed in (101, 211, 307)
    ]
    deltas = cluster_paired_deltas(
        _evaluation(outcomes),
        baseline_rule_id=_BASELINE,
        challenger_rule_id=_CHALLENGER,
    )
    assert len(deltas) == 1
    assert deltas[0].scenario_group == "f1-sc"
    assert deltas[0].scenario_family_id == "F1"
    assert deltas[0].delta == pytest.approx(0.5)


def test_cluster_deltas_average_seeds_before_pairing() -> None:
    """Divergent seeds inside one cluster collapse to their mean first."""
    outcomes = [
        _outcome(_BASELINE, "f1-sc-seed-101", "F1", 1.0),
        _outcome(_BASELINE, "f1-sc-seed-211", "F1", 3.0),
        _outcome(_CHALLENGER, "f1-sc-seed-101", "F1", 1.0),
        _outcome(_CHALLENGER, "f1-sc-seed-211", "F1", 1.0),
    ]
    deltas = cluster_paired_deltas(
        _evaluation(outcomes),
        baseline_rule_id=_BASELINE,
        challenger_rule_id=_CHALLENGER,
    )
    # baseline mean 2.0, challenger mean 1.0
    assert deltas[0].baseline_loss == pytest.approx(2.0)
    assert deltas[0].challenger_loss == pytest.approx(1.0)
    assert deltas[0].delta == pytest.approx(1.0)


def test_cluster_deltas_reject_rules_that_share_nothing() -> None:
    outcomes = [_outcome(_BASELINE, "f1-sc-seed-101", "F1", 1.0)]
    with pytest.raises(ValueError, match="share no evaluated clusters"):
        cluster_paired_deltas(
            _evaluation(outcomes),
            baseline_rule_id=_BASELINE,
            challenger_rule_id=_CHALLENGER,
        )


# --- bootstrap confidence interval ----------------------------------------


def test_bootstrap_is_reproducible_for_a_frozen_seed() -> None:
    """The interval must not be re-drawn until it looks favourable."""
    values = [0.5, -0.1, 0.3, 0.9, -0.4, 0.2, 0.7, 0.05]
    first = bootstrap_cluster_ci(values, _FAST)
    second = bootstrap_cluster_ci(values, _FAST)
    assert first == second


def test_bootstrap_interval_brackets_the_mean() -> None:
    values = [0.5, -0.1, 0.3, 0.9, -0.4, 0.2, 0.7, 0.05]
    lower, upper = bootstrap_cluster_ci(values, _FAST)
    assert lower <= sum(values) / len(values) <= upper


def test_bootstrap_on_identical_values_collapses_to_that_value() -> None:
    lower, upper = bootstrap_cluster_ci([0.5] * 30, _FAST)
    assert lower == pytest.approx(0.5)
    assert upper == pytest.approx(0.5)


def test_bootstrap_on_a_symmetric_spread_straddles_zero() -> None:
    """A rule with no consistent direction must not clear the lower bound."""
    values = [1.0, -1.0] * 15
    result = cluster_paired_result(
        [_delta(f"f1-sc{i}", "F1", value) for i, value in enumerate(values)],
        _FAST,
    )
    assert result.mean_delta == pytest.approx(0.0)
    assert not result.ci_lower_above_zero


def test_bootstrap_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="at least one cluster"):
        bootstrap_cluster_ci([], _FAST)


def test_frozen_protocol_uses_ten_thousand_iterations_by_default() -> None:
    assert AcceptanceCriteria().bootstrap_iterations == 10_000


# --- cluster paired result ------------------------------------------------


def test_cluster_paired_result_counts_and_improvement_ratio() -> None:
    deltas = (
        [_delta(f"win{i}", "F1", 0.5) for i in range(4)]
        + [_delta(f"loss{i}", "F1", -0.2) for i in range(1)]
        + [_delta(f"tie{i}", "F1", 0.0) for i in range(2)]
    )
    result = cluster_paired_result(deltas, _FAST)
    assert result.clusters == 7
    assert (result.improved, result.worsened, result.tied) == (4, 1, 2)
    assert result.better_than_worse is True
    assert result.mean_delta > 0


def test_better_and_worse_counts_sum_with_ties_to_the_cluster_count() -> None:
    deltas = [_delta(f"c{i}", "F2", value) for i, value in enumerate(
        [0.5, -0.2, 0.0, 0.3]
    )]
    result = cluster_paired_result(deltas, _FAST)
    assert result.improved + result.worsened + result.tied == result.clusters


def test_equal_better_and_worse_counts_are_not_an_improvement() -> None:
    deltas = [_delta("w1", "F1", 0.5), _delta("l1", "F1", -0.5)]
    result = cluster_paired_result(deltas, _FAST)
    assert result.improved == result.worsened
    assert result.better_than_worse is False


# --- family direction agreement ------------------------------------------


def test_all_families_agreeing_reaches_full_agreement() -> None:
    result = family_direction_agreement(_deltas_across_families(0.5), _FAST)
    assert result.evaluable_families == 6
    assert result.agreeing_families == 6
    assert result.agreement_rate == pytest.approx(1.0)
    assert result.satisfied


def test_one_dissenting_family_still_passes_the_two_thirds_rule() -> None:
    """A single dissenting family is tolerated; the threshold is two thirds."""
    deltas = [
        _delta(row.scenario_group, row.scenario_family_id, -1.0)
        if row.scenario_family_id == "F1"
        else row
        for row in _deltas_across_families(0.5)
    ]
    result = family_direction_agreement(deltas, _FAST)
    assert result.agreeing_families == 5
    assert result.agreement_rate == pytest.approx(5 / 6)
    assert result.satisfied


def test_half_the_families_dissenting_fails() -> None:
    """A rule that wins in half the families is memorizing, not generalizing."""
    deltas = _deltas_across_families(0.5)
    for family in ("F1", "F2", "F3"):
        deltas = [
            _delta(row.scenario_group, family, -1.0)
            if row.scenario_family_id == family
            else row
            for row in deltas
        ]
    result = family_direction_agreement(deltas, _FAST)
    assert result.agreeing_families == 3
    assert result.agreement_rate == pytest.approx(0.5)
    assert not result.satisfied


def test_family_agreement_reports_per_family_means() -> None:
    result = family_direction_agreement(_deltas_across_families(0.5), _FAST)
    assert [family for family, _, _ in result.per_family] == list(FORMAL_FAMILIES)
    assert all(count == 5 for _, count, _ in result.per_family)
    assert all(mean == pytest.approx(0.5) for _, _, mean in result.per_family)


def test_unlabelled_clusters_are_excluded_from_family_agreement() -> None:
    deltas = _deltas_across_families(0.5) + [_delta("orphan", None, 0.5)]
    result = family_direction_agreement(deltas, _FAST)
    assert result.evaluable_families == 6


# --- holdout adequacy ----------------------------------------------------


def test_thirty_clusters_across_all_families_is_adequate() -> None:
    adequacy = holdout_adequacy(_deltas_across_families(0.5), _FAST)
    assert adequacy.clusters == 30
    assert adequacy.families_present == FORMAL_FAMILIES
    assert adequacy.families_missing == ()
    assert adequacy.adequate


def test_twenty_nine_clusters_is_inadequate() -> None:
    """One short of the frozen minimum cannot support a claim."""
    deltas = _deltas_across_families(0.5)[:-1]
    adequacy = holdout_adequacy(deltas, _FAST)
    assert adequacy.clusters == 29
    assert adequacy.families_missing == ()
    assert not adequacy.adequate


def test_a_missing_formal_family_is_inadequate() -> None:
    deltas = [
        row for row in _deltas_across_families(0.5, per_family=7)
        if row.scenario_family_id != "F6"
    ]
    adequacy = holdout_adequacy(deltas, _FAST)
    assert adequacy.clusters >= 30
    assert adequacy.families_missing == ("F6",)
    assert not adequacy.adequate


# --- latency epsilon calibration -----------------------------------------


def test_epsilon_is_the_largest_deviation_from_the_baseline_mean() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    assert epsilon.baseline_mean == pytest.approx(1.0166666666666666)
    assert epsilon.epsilon == pytest.approx(0.0833333333333333)
    assert epsilon.rule == "max_absolute_deviation_from_baseline_mean"


def test_epsilon_requires_at_least_three_baseline_repeats() -> None:
    """The margin cannot be calibrated from a single run."""
    with pytest.raises(ValueError, match="at least 3 baseline repeats"):
        calibrate_latency_epsilon([1.0, 1.1])


def test_epsilon_rejects_non_finite_repeats() -> None:
    with pytest.raises(ValueError, match="finite"):
        calibrate_latency_epsilon([1.0, 1.1, float("nan")])


def test_latency_inside_the_calibrated_margin_is_non_inferior() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    check = latency_non_inferior(
        baseline_mean=1.0166666666666666,
        challenger_mean=1.05,
        epsilon=epsilon,
    )
    assert check.non_inferior


def test_latency_beyond_the_calibrated_margin_is_a_regression() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    check = latency_non_inferior(
        baseline_mean=1.0, challenger_mean=1.5, epsilon=epsilon
    )
    assert not check.non_inferior
    assert check.observed_regression == pytest.approx(0.5)


# --- preregistration -----------------------------------------------------


def test_preregistration_rejects_blank_fields() -> None:
    with pytest.raises(ValueError, match="tie_break"):
        RulePreregistration(
            rule_id=_CHALLENGER,
            family="H1",
            formula="ascending",
            direction="ascending",
            tie_break="   ",
            fallback="baseline",
            boundary="forced-release candidate sets only",
            primary_metric=PRIMARY_METRIC_PROXY_LOSS,
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_requires_a_stated_boundary() -> None:
    """M1 requires the applicability boundary to be frozen, not implied."""
    with pytest.raises(ValueError, match="boundary"):
        RulePreregistration(
            rule_id=_CHALLENGER,
            family="H1",
            formula="ascending",
            direction="ascending",
            tie_break="identity",
            fallback="baseline",
            boundary="",
            primary_metric=PRIMARY_METRIC_PROXY_LOSS,
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_rejects_an_unknown_primary_metric() -> None:
    with pytest.raises(ValueError, match="unsupported primary metric"):
        RulePreregistration(
            rule_id=_CHALLENGER,
            family="H1",
            formula="ascending",
            direction="ascending",
            tie_break="identity",
            fallback="baseline",
            boundary="forced-release candidate sets only",
            primary_metric="whatever_looks_best_today",
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_is_serializable() -> None:
    payload = _preregistration().as_payload()
    assert payload["rule_id"] == _CHALLENGER
    assert payload["primary_metric"] == PRIMARY_METRIC_PROXY_LOSS


# --- the verdict ---------------------------------------------------------


def _evaluate(
    deltas_across_families: float = 0.5,
    *,
    per_family: int = 5,
    metric: str = PRIMARY_METRIC_PROXY_LOSS,
    **kwargs: object,
):
    """Evaluate a synthetic challenger built from ``ClusterPairedDelta`` values.

    The deltas are turned back into outcomes so the verdict is produced by the
    real code path rather than by a stub.
    """
    deltas = _deltas_across_families(deltas_across_families, per_family=per_family)
    outcomes: list = []
    for row in deltas:
        run_id = f"{row.scenario_group}-seed-101"
        outcomes.append(
            _outcome(_BASELINE, run_id, row.scenario_family_id, row.baseline_loss)
        )
        outcomes.append(
            _outcome(
                _CHALLENGER, run_id, row.scenario_family_id, row.challenger_loss
            )
        )
    return evaluate_acceptance(
        _evaluation(outcomes),
        preregistration=_preregistration(metric=metric),
        baseline_rule_id=_BASELINE,
        criteria=_FAST,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_clean_proxy_win_earns_proxy_candidate_only() -> None:
    verdict = _evaluate(0.5)
    assert verdict.level == LEVEL_PROXY_CANDIDATE
    assert verdict.accepted
    assert verdict.failures == ()
    # Level A explicitly does not authorize a runtime claim.
    assert verdict.level != LEVEL_RUNTIME_CANDIDATE


def test_a_win_without_enough_clusters_is_diagnostic_only() -> None:
    """However good the numbers look, a small holdout supports nothing."""
    verdict = _evaluate(0.5, per_family=4)
    assert verdict.holdout.clusters == 24
    assert verdict.level == LEVEL_DIAGNOSTIC_ONLY
    assert not verdict.accepted
    assert "holdout_adequate" in verdict.failures


def test_a_rule_that_loses_is_not_accepted() -> None:
    verdict = _evaluate(-0.5)
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert not verdict.accepted


def test_family_memorization_alone_blocks_acceptance() -> None:
    """The exact failure the protocol exists to catch."""
    deltas = _deltas_across_families(0.5)
    for family in ("F2", "F3", "F4"):
        deltas = [
            _delta(row.scenario_group, family, -1.0)
            if row.scenario_family_id == family
            else row
            for row in deltas
        ]
    outcomes: list = []
    for row in deltas:
        run_id = f"{row.scenario_group}-seed-101"
        outcomes.append(
            _outcome(_BASELINE, run_id, row.scenario_family_id, row.baseline_loss)
        )
        outcomes.append(
            _outcome(
                _CHALLENGER, run_id, row.scenario_family_id, row.challenger_loss
            )
        )
    verdict = evaluate_acceptance(
        _evaluation(outcomes),
        preregistration=_preregistration(),
        baseline_rule_id=_BASELINE,
        criteria=_FAST,
    )
    assert verdict.holdout.adequate
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert "family_direction_agreement" in verdict.failures


def test_runtime_metric_needs_a_latency_margin() -> None:
    """Level B cannot pass on recompute alone; latency must be applied."""
    verdict = _evaluate(0.5, metric=PRIMARY_METRIC_RECOMPUTED_TOKENS)
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert "latency_non_inferior" in verdict.failures


def test_runtime_metric_with_a_clean_latency_result_earns_runtime_candidate() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    verdict = _evaluate(
        0.5,
        metric=PRIMARY_METRIC_RECOMPUTED_TOKENS,
        epsilon_latency=epsilon,
        baseline_latency_mean=1.0,
        challenger_latency_mean=1.01,
    )
    assert verdict.level == LEVEL_RUNTIME_CANDIDATE
    assert verdict.latency is not None and verdict.latency.non_inferior


def test_runtime_metric_with_a_latency_regression_is_rejected() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    verdict = _evaluate(
        0.5,
        metric=PRIMARY_METRIC_RECOMPUTED_TOKENS,
        epsilon_latency=epsilon,
        baseline_latency_mean=1.0,
        challenger_latency_mean=5.0,
    )
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert "latency_non_inferior" in verdict.failures


def test_level_c_requires_the_attestations() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    kwargs = {
        "metric": PRIMARY_METRIC_RECOMPUTED_TOKENS,
        "epsilon_latency": epsilon,
        "baseline_latency_mean": 1.0,
        "challenger_latency_mean": 1.01,
    }
    without = _evaluate(0.5, **kwargs)
    assert without.level == LEVEL_RUNTIME_CANDIDATE

    with_attestation = _evaluate(
        0.5,
        attestation=ImplementationAttestation(
            interface_reviewed=True,
            novelty_reviewed=True,
            runtime_overhead_bounded=True,
        ),
        **kwargs,
    )
    assert with_attestation.level == LEVEL_IMPLEMENTATION_ELIGIBLE


def test_partial_attestation_is_not_enough_for_level_c() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    verdict = _evaluate(
        0.5,
        metric=PRIMARY_METRIC_RECOMPUTED_TOKENS,
        epsilon_latency=epsilon,
        baseline_latency_mean=1.0,
        challenger_latency_mean=1.01,
        attestation=ImplementationAttestation(
            interface_reviewed=True,
            novelty_reviewed=False,
            runtime_overhead_bounded=True,
        ),
    )
    assert verdict.level == LEVEL_RUNTIME_CANDIDATE


def test_diagnostic_only_outranks_a_failing_check() -> None:
    """Below the sample floor the label is diagnostic, not a rejection."""
    verdict = _evaluate(-0.5, per_family=3)
    assert verdict.level == LEVEL_DIAGNOSTIC_ONLY
    assert verdict.holdout.adequate is False


def test_verdict_payload_records_the_protocol_it_applied() -> None:
    payload = _evaluate(0.5).as_payload()
    assert payload["accepted"] is True
    assert payload["criteria"]["bootstrap_iterations"] == _FAST.bootstrap_iterations
    assert payload["criteria"]["bootstrap_seed"] == _FAST.bootstrap_seed
    assert payload["criteria"]["minimum_clusters"] == 30
    assert payload["criteria"]["family_agreement_minimum"] == pytest.approx(2 / 3)
    assert payload["cluster_paired"]["bootstrap_seed"] == _FAST.bootstrap_seed
    assert payload["checks"]["holdout_adequate"] is True
    assert payload["holdout"]["families_missing"] == []


def test_verdict_payload_is_json_serializable() -> None:
    import json

    payload = _evaluate(0.5).as_payload()
    assert json.loads(json.dumps(payload))["level"] == LEVEL_PROXY_CANDIDATE
