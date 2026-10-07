"""Tests for the executable rule-acceptance protocol.

The protocol's unit is the **independent scenario draw**, not the decision row
and not the decision-position cluster. Several tests below exist specifically to
pin that distinction, because getting it wrong inflates the sample.
"""

from __future__ import annotations

import pytest

from kvopt.costaware.acceptance import (
    FORMAL_FAMILIES,
    LEVEL_DIAGNOSTIC_ONLY,
    LEVEL_IMPLEMENTATION_ELIGIBLE,
    LEVEL_NOT_ACCEPTED,
    LEVEL_PROXY_CANDIDATE,
    LEVEL_RUNTIME_CANDIDATE,
    PROXY_LOSS_VIEW,
    RUNTIME_LOSS_VIEW,
    SCOPE_DECISION_CLUSTER,
    SCOPE_SCENARIO_DRAW,
    TIER_PROXY,
    TIER_RUNTIME,
    AcceptanceCriteria,
    ClusterPairedDelta,
    ImplementationAttestation,
    RulePreregistration,
    ScenarioPairedDelta,
    bootstrap_ci,
    calibrate_latency_epsilon,
    cluster_paired_deltas,
    evaluate_acceptance,
    family_direction_agreement,
    holdout_adequacy,
    latency_non_inferior,
    paired_result,
    scenario_paired_deltas,
    select_metric_tier,
)
from kvopt.costaware.offline_eval import RuleDecisionOutcome, RuleEvaluation

_BASELINE = "M0_p1b_executed_ordering"
_CHALLENGER = "H1_R1_reverse_deadline"

#: Small iteration count so the suite stays fast; the protocol's default is
#: 10_000 and is asserted separately.
_FAST = AcceptanceCriteria(bootstrap_iterations=400, bootstrap_seed=7)


def _scenario_delta(
    group: str,
    family: str | None,
    value: float,
    *,
    positions: int = 1,
    seeds: int = 3,
) -> ScenarioPairedDelta:
    """One independent scenario draw whose delta is ``value``."""
    return ScenarioPairedDelta(
        scenario_group=group,
        scenario_family_id=family,
        decision_positions=positions,
        seed_repeats=seeds,
        baseline_loss=1.0,
        challenger_loss=1.0 - value,
        delta=value,
    )


def _draws_across_families(value: float, *, per_family: int = 5) -> list:
    """``6 x per_family`` independent scenario draws, all moving by ``value``."""
    return [
        _scenario_delta(f"{family}-sc{position}", family, value)
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
        loss_view=PROXY_LOSS_VIEW,
        selected_identities=(("a", "p"),),
        selected_loss=selected_loss,
        hindsight_best_loss=0.0,
        absolute_regret=selected_loss,
        normalized_regret=0.0,
        selected_is_hindsight_best=False,
        candidate_loss_tied=False,
    )


def _evaluation(
    outcomes: list, *, loss_view: str = PROXY_LOSS_VIEW
) -> RuleEvaluation:
    return RuleEvaluation(
        loss_view=loss_view,
        evaluated_decisions=0,
        skipped_decisions=0,
        available_candidates=0,
        aggregates=(),
        outcomes=tuple(outcomes),
        degeneracy=(),
    )


def _paired_outcomes(deltas: list) -> list:
    """Turn scenario deltas into outcomes the real code path can aggregate."""
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
    return outcomes


def _preregistration() -> RulePreregistration:
    return RulePreregistration(
        rule_id=_CHALLENGER,
        family="H1",
        formula="descending on retention_deadline_timestamp",
        direction="descending",
        tie_break="stable logical identity",
        fallback="frozen baseline ordering",
        boundary="forced-release candidate sets only",
        proxy_primary_metric=PROXY_LOSS_VIEW,
        runtime_primary_metric=RUNTIME_LOSS_VIEW,
        frozen_at="2026-10-07",
        frozen_commit="0" * 40,
    )


# --- the statistical unit -------------------------------------------------


def test_draws_are_counted_per_scenario_not_per_decision_position() -> None:
    """A second decision in one scenario is not a second independent sample."""
    outcomes = []
    for position in (40, 47):
        for seed in (101, 211):
            run_id = f"f4-sc-seed-{seed}"
            outcomes.append(
                _outcome(_BASELINE, run_id, "F4", 1.0, index=position)
            )
            outcomes.append(
                _outcome(_CHALLENGER, run_id, "F4", 0.5, index=position)
            )
    deltas = scenario_paired_deltas(
        _evaluation(outcomes),
        baseline_rule_id=_BASELINE,
        challenger_rule_id=_CHALLENGER,
    )
    assert len(deltas) == 1
    assert deltas[0].scenario_group == "f4-sc"
    assert deltas[0].decision_positions == 2
    assert deltas[0].seed_repeats == 2
    assert deltas[0].delta == pytest.approx(0.5)

    # The diagnostic view still shows both positions.
    clusters = cluster_paired_deltas(
        _evaluation(outcomes),
        baseline_rule_id=_BASELINE,
        challenger_rule_id=_CHALLENGER,
    )
    assert len(clusters) == 2


def test_aggregation_order_is_seeds_then_positions() -> None:
    """Seeds average inside a position; positions average inside a scenario.

    Reversing the order would weight a position with more seeds more heavily, so
    the two are distinguished here by giving the positions unequal seed counts.
    """
    outcomes = [
        # position 40: baseline seeds 1.0 and 3.0 -> mean 2.0, challenger 1.0
        _outcome(_BASELINE, "sc-seed-101", "F1", 1.0, index=40),
        _outcome(_BASELINE, "sc-seed-211", "F1", 3.0, index=40),
        _outcome(_CHALLENGER, "sc-seed-101", "F1", 1.0, index=40),
        _outcome(_CHALLENGER, "sc-seed-211", "F1", 1.0, index=40),
        # position 47: single seed, both rules at 5.0
        _outcome(_BASELINE, "sc-seed-101", "F1", 5.0, index=47),
        _outcome(_CHALLENGER, "sc-seed-101", "F1", 5.0, index=47),
    ]
    deltas = scenario_paired_deltas(
        _evaluation(outcomes),
        baseline_rule_id=_BASELINE,
        challenger_rule_id=_CHALLENGER,
    )
    assert len(deltas) == 1
    # baseline: (2.0 + 5.0) / 2 = 3.5 ; challenger: (1.0 + 5.0) / 2 = 3.0
    assert deltas[0].baseline_loss == pytest.approx(3.5)
    assert deltas[0].challenger_loss == pytest.approx(3.0)
    assert deltas[0].delta == pytest.approx(0.5)


def test_sign_convention_is_positive_when_the_challenger_improves() -> None:
    outcomes = [
        _outcome(_BASELINE, "sc-seed-101", "F1", 1.0),
        _outcome(_CHALLENGER, "sc-seed-101", "F1", 0.25),
    ]
    deltas = scenario_paired_deltas(
        _evaluation(outcomes),
        baseline_rule_id=_BASELINE,
        challenger_rule_id=_CHALLENGER,
    )
    assert deltas[0].delta == pytest.approx(0.75)


def test_scenario_deltas_reject_rules_that_share_nothing() -> None:
    outcomes = [_outcome(_BASELINE, "sc-seed-101", "F1", 1.0)]
    with pytest.raises(ValueError, match="share no evaluated scenarios"):
        scenario_paired_deltas(
            _evaluation(outcomes),
            baseline_rule_id=_BASELINE,
            challenger_rule_id=_CHALLENGER,
        )


# --- bootstrap confidence interval ----------------------------------------


def test_bootstrap_is_reproducible_for_a_frozen_seed() -> None:
    """The interval must not be re-drawn until it looks favourable."""
    values = [0.5, -0.1, 0.3, 0.9, -0.4, 0.2, 0.7, 0.05]
    assert bootstrap_ci(values, _FAST) == bootstrap_ci(values, _FAST)


def test_bootstrap_interval_brackets_the_mean() -> None:
    values = [0.5, -0.1, 0.3, 0.9, -0.4, 0.2, 0.7, 0.05]
    lower, upper = bootstrap_ci(values, _FAST)
    assert lower <= sum(values) / len(values) <= upper


def test_bootstrap_on_identical_values_collapses_to_that_value() -> None:
    lower, upper = bootstrap_ci([0.5] * 30, _FAST)
    assert lower == pytest.approx(0.5)
    assert upper == pytest.approx(0.5)


def test_bootstrap_on_a_symmetric_spread_straddles_zero() -> None:
    """A rule with no consistent direction must not clear the lower bound."""
    values = [1.0, -1.0] * 15
    result = paired_result(
        [
            _scenario_delta(f"sc{i}", "F1", value)
            for i, value in enumerate(values)
        ],
        _FAST,
    )
    assert result.mean_delta == pytest.approx(0.0)
    assert not result.ci_lower_above_zero


def test_bootstrap_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="at least one unit"):
        bootstrap_ci([], _FAST)


def test_frozen_protocol_uses_ten_thousand_iterations_by_default() -> None:
    assert AcceptanceCriteria().bootstrap_iterations == 10_000


# --- paired result --------------------------------------------------------


def test_paired_result_counts_and_improvement_ratio() -> None:
    deltas = (
        [_scenario_delta(f"win{i}", "F1", 0.5) for i in range(4)]
        + [_scenario_delta("loss1", "F1", -0.2)]
        + [_scenario_delta(f"tie{i}", "F1", 0.0) for i in range(2)]
    )
    result = paired_result(deltas, _FAST)
    assert result.units == 7
    assert (result.improved, result.worsened, result.tied) == (4, 1, 2)
    assert result.better_than_worse is True
    assert result.scope == SCOPE_SCENARIO_DRAW


def test_counts_sum_with_ties_to_the_unit_count() -> None:
    deltas = [
        _scenario_delta(f"c{i}", "F2", value)
        for i, value in enumerate([0.5, -0.2, 0.0, 0.3])
    ]
    result = paired_result(deltas, _FAST)
    assert result.improved + result.worsened + result.tied == result.units


def test_equal_better_and_worse_counts_are_not_an_improvement() -> None:
    deltas = [
        _scenario_delta("w1", "F1", 0.5),
        _scenario_delta("l1", "F1", -0.5),
    ]
    result = paired_result(deltas, _FAST)
    assert result.improved == result.worsened
    assert result.better_than_worse is False


def test_diagnostic_view_records_its_own_scope() -> None:
    """A payload must never present a diagnostic view as the draw-level result."""
    result = paired_result(
        [
            ClusterPairedDelta(
                scenario_group="sc",
                decision_event_index=40,
                scenario_family_id="F1",
                baseline_loss=1.0,
                challenger_loss=0.5,
                delta=0.5,
            )
        ],
        _FAST,
        scope=SCOPE_DECISION_CLUSTER,
    )
    assert result.scope == SCOPE_DECISION_CLUSTER


# --- family direction agreement ------------------------------------------


def test_all_families_agreeing_reaches_full_agreement() -> None:
    result = family_direction_agreement(_draws_across_families(0.5), _FAST)
    assert result.evaluable_families == 6
    assert result.agreeing_families == 6
    assert result.agreement_rate == pytest.approx(1.0)
    assert result.satisfied


def test_one_dissenting_family_still_passes_the_two_thirds_rule() -> None:
    """A single dissenting family is tolerated; the threshold is two thirds."""
    deltas = [
        _scenario_delta(row.scenario_group, row.scenario_family_id, -1.0)
        if row.scenario_family_id == "F1"
        else row
        for row in _draws_across_families(0.5)
    ]
    result = family_direction_agreement(deltas, _FAST)
    assert result.agreeing_families == 5
    assert result.agreement_rate == pytest.approx(5 / 6)
    assert result.satisfied


def test_half_the_families_dissenting_fails() -> None:
    """A rule that wins in half the families is memorizing, not generalizing."""
    deltas = [
        _scenario_delta(row.scenario_group, row.scenario_family_id, -1.0)
        if row.scenario_family_id in {"F1", "F2", "F3"}
        else row
        for row in _draws_across_families(0.5)
    ]
    result = family_direction_agreement(deltas, _FAST)
    assert result.agreeing_families == 3
    assert result.agreement_rate == pytest.approx(0.5)
    assert not result.satisfied


def test_family_means_use_the_same_positive_is_improvement_sign() -> None:
    """The per-family table must be comparable with the paired table."""
    result = family_direction_agreement(_draws_across_families(0.5), _FAST)
    assert [family for family, _, _ in result.per_family] == list(FORMAL_FAMILIES)
    assert all(count == 5 for _, count, _ in result.per_family)
    assert all(mean == pytest.approx(0.5) for _, _, mean in result.per_family)


def test_unlabelled_draws_are_excluded_from_family_agreement() -> None:
    deltas = _draws_across_families(0.5) + [_scenario_delta("orphan", None, 0.5)]
    result = family_direction_agreement(deltas, _FAST)
    assert result.evaluable_families == 6


# --- holdout adequacy ----------------------------------------------------


def test_thirty_scenario_draws_across_all_families_is_adequate() -> None:
    adequacy = holdout_adequacy(_draws_across_families(0.5), _FAST)
    assert adequacy.units == 30
    assert adequacy.minimum_units == 30
    assert adequacy.scope == SCOPE_SCENARIO_DRAW
    assert adequacy.families_present == FORMAL_FAMILIES
    assert adequacy.families_missing == ()
    assert adequacy.adequate


def test_twenty_nine_scenario_draws_is_inadequate() -> None:
    """One short of the frozen minimum cannot support a claim."""
    adequacy = holdout_adequacy(_draws_across_families(0.5)[:-1], _FAST)
    assert adequacy.units == 29
    assert adequacy.families_missing == ()
    assert not adequacy.adequate


def test_a_missing_formal_family_is_inadequate() -> None:
    deltas = [
        row
        for row in _draws_across_families(0.5, per_family=7)
        if row.scenario_family_id != "F6"
    ]
    adequacy = holdout_adequacy(deltas, _FAST)
    assert adequacy.units >= 30
    assert adequacy.families_missing == ("F6",)
    assert not adequacy.adequate


def test_the_floor_is_measured_in_draws_not_decision_positions() -> None:
    """18 scenarios with 2 positions each is 18 draws, not 36.

    This is the inflation the ruling removed: on the discovery campaign the
    decision-position view reports 20 units where only 18 are independent.
    """
    deltas = [
        _scenario_delta(f"sc{i}", FORMAL_FAMILIES[i % 6], 0.5, positions=2)
        for i in range(18)
    ]
    adequacy = holdout_adequacy(deltas, _FAST)
    assert adequacy.units == 18
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
            formula="descending",
            direction="descending",
            tie_break="   ",
            fallback="baseline",
            boundary="forced-release candidate sets only",
            proxy_primary_metric=PROXY_LOSS_VIEW,
            runtime_primary_metric=RUNTIME_LOSS_VIEW,
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_requires_a_stated_boundary() -> None:
    """M1 requires the applicability boundary to be frozen, not implied."""
    with pytest.raises(ValueError, match="boundary"):
        RulePreregistration(
            rule_id=_CHALLENGER,
            family="H1",
            formula="descending",
            direction="descending",
            tie_break="stable logical identity",
            fallback="baseline",
            boundary="",
            proxy_primary_metric=PROXY_LOSS_VIEW,
            runtime_primary_metric=RUNTIME_LOSS_VIEW,
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_requires_both_frozen_tiers() -> None:
    """Naming only the proxy metric would force a runtime run to be Level A."""
    with pytest.raises(ValueError, match="runtime metric"):
        RulePreregistration(
            rule_id=_CHALLENGER,
            family="H1",
            formula="descending",
            direction="descending",
            tie_break="stable logical identity",
            fallback="baseline",
            boundary="forced-release candidate sets only",
            proxy_primary_metric=PROXY_LOSS_VIEW,
            runtime_primary_metric="whatever_looks_best_today",
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_rejects_an_unknown_proxy_metric() -> None:
    with pytest.raises(ValueError, match="proxy metric"):
        RulePreregistration(
            rule_id=_CHALLENGER,
            family="H1",
            formula="descending",
            direction="descending",
            tie_break="stable logical identity",
            fallback="baseline",
            boundary="forced-release candidate sets only",
            proxy_primary_metric="cluster_mean_proxy_loss",
            runtime_primary_metric=RUNTIME_LOSS_VIEW,
            frozen_at="2026-10-07",
            frozen_commit="0" * 40,
        )


def test_preregistration_publishes_both_tiers() -> None:
    payload = _preregistration().as_payload()
    assert payload["metrics"] == {
        TIER_PROXY: PROXY_LOSS_VIEW,
        TIER_RUNTIME: RUNTIME_LOSS_VIEW,
    }


# --- tier selection ------------------------------------------------------


def test_proxy_only_evidence_selects_the_frozen_proxy_metric() -> None:
    evaluation = _evaluation(_paired_outcomes([_scenario_delta("sc", "F1", 0.5)]))
    tier, metric = select_metric_tier(
        _preregistration(), proxy_evaluation=evaluation
    )
    assert tier == TIER_PROXY
    assert metric == PROXY_LOSS_VIEW


def test_runtime_evidence_forces_the_frozen_runtime_metric() -> None:
    """The tier follows the evidence, so the metric cannot be picked later."""
    runtime = _evaluation(
        _paired_outcomes([_scenario_delta("sc", "F1", 0.5)]),
        loss_view=RUNTIME_LOSS_VIEW,
    )
    tier, metric = select_metric_tier(
        _preregistration(), runtime_evaluation=runtime
    )
    assert tier == TIER_RUNTIME
    assert metric == RUNTIME_LOSS_VIEW


def test_runtime_evidence_computed_on_the_wrong_view_is_rejected() -> None:
    runtime = _evaluation(
        _paired_outcomes([_scenario_delta("sc", "F1", 0.5)]),
        loss_view="something_else",
    )
    with pytest.raises(ValueError, match="must be computed on"):
        select_metric_tier(_preregistration(), runtime_evaluation=runtime)


def test_proxy_evidence_computed_on_the_wrong_view_is_rejected() -> None:
    proxy = _evaluation(
        _paired_outcomes([_scenario_delta("sc", "F1", 0.5)]),
        loss_view="something_else",
    )
    with pytest.raises(ValueError, match="must be computed on"):
        select_metric_tier(_preregistration(), proxy_evaluation=proxy)


def test_no_evidence_at_all_is_rejected() -> None:
    with pytest.raises(ValueError, match="no evaluation supplied"):
        select_metric_tier(_preregistration())


# --- the verdict ---------------------------------------------------------


def _evaluate(
    value: float = 0.5,
    *,
    per_family: int = 5,
    runtime: bool = False,
    **kwargs: object,
):
    """Evaluate a synthetic challenger through the real code path."""
    deltas = _draws_across_families(value, per_family=per_family)
    loss_view = RUNTIME_LOSS_VIEW if runtime else PROXY_LOSS_VIEW
    evaluation = _evaluation(_paired_outcomes(deltas), loss_view=loss_view)
    arguments: dict[str, object] = {
        "preregistration": _preregistration(),
        "baseline_rule_id": _BASELINE,
        "criteria": _FAST,
    }
    arguments["runtime_evaluation" if runtime else "proxy_evaluation"] = evaluation
    arguments.update(kwargs)
    return evaluate_acceptance(**arguments)  # type: ignore[arg-type]


def test_a_clean_proxy_win_earns_proxy_candidate_only() -> None:
    verdict = _evaluate(0.5)
    assert verdict.level == LEVEL_PROXY_CANDIDATE
    assert verdict.accepted
    assert verdict.failures == ()
    assert verdict.evidence_tier == TIER_PROXY
    assert verdict.primary_metric == PROXY_LOSS_VIEW
    # Level A explicitly does not authorize a runtime claim.
    assert verdict.level != LEVEL_RUNTIME_CANDIDATE


def test_a_win_without_enough_draws_is_diagnostic_only() -> None:
    """However good the numbers look, a small holdout supports nothing."""
    verdict = _evaluate(0.5, per_family=4)
    assert verdict.holdout.units == 24
    assert verdict.level == LEVEL_DIAGNOSTIC_ONLY
    assert not verdict.accepted
    assert "holdout_adequate" in verdict.failures


def test_the_verdict_records_the_scenario_draw_unit() -> None:
    verdict = _evaluate(0.5)
    assert verdict.paired.scope == SCOPE_SCENARIO_DRAW
    assert verdict.holdout.scope == SCOPE_SCENARIO_DRAW
    assert verdict.diagnostic_paired is not None
    assert verdict.diagnostic_paired.scope == SCOPE_DECISION_CLUSTER


def test_a_rule_that_loses_is_not_accepted() -> None:
    verdict = _evaluate(-0.5)
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert not verdict.accepted


def test_family_memorization_alone_blocks_acceptance() -> None:
    """The exact failure the protocol exists to catch."""
    deltas = [
        _scenario_delta(row.scenario_group, row.scenario_family_id, -1.0)
        if row.scenario_family_id in {"F2", "F3", "F4"}
        else row
        for row in _draws_across_families(0.5)
    ]
    verdict = evaluate_acceptance(
        preregistration=_preregistration(),
        baseline_rule_id=_BASELINE,
        criteria=_FAST,
        proxy_evaluation=_evaluation(_paired_outcomes(deltas)),
    )
    assert verdict.holdout.adequate
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert "family_direction_agreement" in verdict.failures


def test_runtime_tier_needs_a_latency_margin() -> None:
    """Level B cannot pass on recompute alone; latency must be applied."""
    verdict = _evaluate(0.5, runtime=True)
    assert verdict.evidence_tier == TIER_RUNTIME
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert "latency_non_inferior" in verdict.failures


def test_runtime_tier_with_a_clean_latency_result_earns_runtime_candidate() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    verdict = _evaluate(
        0.5,
        runtime=True,
        epsilon_latency=epsilon,
        baseline_latency_mean=1.0,
        challenger_latency_mean=1.01,
    )
    assert verdict.level == LEVEL_RUNTIME_CANDIDATE
    assert verdict.primary_metric == RUNTIME_LOSS_VIEW
    assert verdict.latency is not None and verdict.latency.non_inferior


def test_runtime_tier_with_a_latency_regression_is_rejected() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    verdict = _evaluate(
        0.5,
        runtime=True,
        epsilon_latency=epsilon,
        baseline_latency_mean=1.0,
        challenger_latency_mean=5.0,
    )
    assert verdict.level == LEVEL_NOT_ACCEPTED
    assert "latency_non_inferior" in verdict.failures


def test_level_c_requires_the_attestations() -> None:
    epsilon = calibrate_latency_epsilon([1.00, 1.10, 0.95])
    kwargs = {
        "runtime": True,
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
        runtime=True,
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
    assert payload["evidence_tier"] == TIER_PROXY
    assert payload["statistical_unit"] == SCOPE_SCENARIO_DRAW
    assert "positive = the challenger improved" in payload["sign_convention"]
    assert payload["criteria"]["statistical_unit"] == SCOPE_SCENARIO_DRAW
    assert payload["criteria"]["minimum_scenario_draws"] == 30
    assert payload["criteria"]["bootstrap_iterations"] == _FAST.bootstrap_iterations
    assert payload["criteria"]["bootstrap_seed"] == _FAST.bootstrap_seed
    assert payload["criteria"]["family_agreement_minimum"] == pytest.approx(2 / 3)
    assert payload["paired"]["scope"] == SCOPE_SCENARIO_DRAW
    assert payload["paired"]["units"] == 30
    assert payload["holdout"]["families_missing"] == []
    assert (
        payload["paired_diagnostic_decision_position"]["scope"]
        == SCOPE_DECISION_CLUSTER
    )


def test_verdict_payload_is_json_serializable() -> None:
    import json

    payload = _evaluate(0.5).as_payload()
    assert json.loads(json.dumps(payload))["level"] == LEVEL_PROXY_CANDIDATE
