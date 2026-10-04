from kvopt.profiling.gate import (
    EmpiricalGapInputs,
    evaluate_empirical_gap_gate,
)
from kvopt.profiling.statistics import (
    LossHeterogeneitySummaryRow,
    RegretSummaryRow,
)


def _inputs(*, formal: bool, signal: bool | None = True) -> EmpiricalGapInputs:
    return EmpiricalGapInputs(
        formal_campaign=formal,
        otherwise_valid_decision_count=30,
        joinable_decision_count=30,
        valid_decision_count=30,
        scenario_family_count=3,
        seed_count=3,
        physical_missingness_explicit=True,
        provenance_complete=True,
        online_signal_supported=signal,
        direct_loss_views=(),
        capability_contract_complete=True,
    )


def _heterogeneity(rate: float = 0.5) -> LossHeterogeneitySummaryRow:
    return LossHeterogeneitySummaryRow(
        scope="overall",
        scenario_id=None,
        loss_view="proxy",
        decision_count=30,
        seed_count=3,
        positive_spread_count=int(30 * rate),
        positive_spread_rate=rate,
        mean_spread=1.0,
        mean_spread_ci_lower=0.2 if rate >= 0.25 else 0.0,
        mean_spread_ci_upper=1.8,
    )


def _regret() -> RegretSummaryRow:
    return RegretSummaryRow(
        scope="overall",
        scenario_id=None,
        loss_view="proxy",
        decision_count=30,
        seed_count=3,
        non_tied_decision_count=20,
        non_tied_misselection_count=4,
        non_tied_misselection_rate=0.2,
        mean_absolute_regret=1.0,
        mean_absolute_regret_ci_lower=0.1,
        mean_absolute_regret_ci_upper=1.9,
        mean_normalized_regret=0.2,
        mean_normalized_regret_ci_lower=0.05,
        mean_normalized_regret_ci_upper=0.35,
    )


def test_gate_rejects_foundation_or_unverified_campaign() -> None:
    report = evaluate_empirical_gap_gate(
        _inputs(formal=False),
        (_heterogeneity(),),
        (_regret(),),
    )

    assert report.overall_outcome == "INSUFFICIENT-EVENTS"


def test_gate_reports_proxy_only_evidence_as_provisional() -> None:
    report = evaluate_empirical_gap_gate(
        _inputs(formal=True),
        (_heterogeneity(),),
        (_regret(),),
    )

    assert report.overall_outcome == "GAP-PROVISIONAL"
    assert report.passing_loss_views == ("proxy",)


def test_gate_does_not_claim_missing_signal_was_evaluated() -> None:
    report = evaluate_empirical_gap_gate(
        _inputs(formal=True, signal=None),
        (_heterogeneity(),),
        (_regret(),),
    )

    assert report.overall_outcome == "INCOMPLETE-SIGNAL-EVALUATION"


def test_gate_reports_no_measurable_gap_when_heterogeneity_fails() -> None:
    report = evaluate_empirical_gap_gate(
        _inputs(formal=True),
        (_heterogeneity(rate=0.1),),
        (_regret(),),
    )

    assert report.overall_outcome == "NO-MEASURABLE-GAP"


def test_gate_rejects_incomplete_v5_capability_contract() -> None:
    inputs = _inputs(formal=True)
    inputs = EmpiricalGapInputs(
        **{
            **inputs.__dict__,
            "capability_contract_complete": False,
        }
    )
    report = evaluate_empirical_gap_gate(
        inputs,
        (_heterogeneity(),),
        (_regret(),),
    )

    assert report.overall_outcome == "DATA-INVALID"
    integrity = next(
        row for row in report.checks if row.gate == "data_integrity"
    )
    assert integrity.status == "FAIL"
    assert "capability_contract_complete=False" in integrity.explanation
