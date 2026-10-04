"""Evaluate the frozen Phase 2A Empirical Gap Gate."""

from __future__ import annotations

from dataclasses import dataclass

from .statistics import LossHeterogeneitySummaryRow, RegretSummaryRow


@dataclass(frozen=True, slots=True)
class EmpiricalGapInputs:
    """Auditable scalar and summary inputs to the frozen gate."""

    formal_campaign: bool
    otherwise_valid_decision_count: int
    joinable_decision_count: int
    valid_decision_count: int
    scenario_family_count: int
    seed_count: int
    physical_missingness_explicit: bool
    provenance_complete: bool
    online_signal_supported: bool | None
    direct_loss_views: tuple[str, ...]
    capability_contract_complete: bool = False


@dataclass(frozen=True, slots=True)
class GateCheckRow:
    """One required or supporting gate result."""

    gate: str
    status: str
    explanation: str


@dataclass(frozen=True, slots=True)
class EmpiricalGapReport:
    """Overall frozen-gate conclusion with individual checks."""

    overall_outcome: str
    passing_loss_views: tuple[str, ...]
    checks: tuple[GateCheckRow, ...]


def _overall_rows(
    rows: tuple[LossHeterogeneitySummaryRow, ...]
    | tuple[RegretSummaryRow, ...],
):
    return tuple(row for row in rows if row.scope == "overall")


def evaluate_empirical_gap_gate(
    inputs: EmpiricalGapInputs,
    loss_heterogeneity: tuple[LossHeterogeneitySummaryRow, ...],
    regret: tuple[RegretSummaryRow, ...],
) -> EmpiricalGapReport:
    """Apply the documented thresholds without inferring missing evidence."""

    if not inputs.capability_contract_complete:
        integrity_status = "FAIL"
        join_rate = None
    elif inputs.otherwise_valid_decision_count == 0:
        integrity_status = "INSUFFICIENT"
        join_rate = None
    else:
        join_rate = (
            inputs.joinable_decision_count
            / inputs.otherwise_valid_decision_count
        )
        integrity_status = (
            "PASS"
            if join_rate >= 0.95
            and inputs.physical_missingness_explicit
            and inputs.provenance_complete
            and inputs.capability_contract_complete
            else "FAIL"
        )
    integrity = GateCheckRow(
        gate="data_integrity",
        status=integrity_status,
        explanation=(
            (
                "capability_contract_complete=False"
                if not inputs.capability_contract_complete
                else "no otherwise-valid multi-candidate decisions"
            )
            if join_rate is None
            else (
                f"decision join coverage={join_rate:.3f}; "
                f"capability_contract_complete={inputs.capability_contract_complete}"
            )
        ),
    )

    volume_pass = (
        inputs.formal_campaign
        and inputs.valid_decision_count >= 30
        and inputs.scenario_family_count >= 3
        and inputs.seed_count >= 3
    )
    volume = GateCheckRow(
        gate="event_volume",
        status="PASS" if volume_pass else "INSUFFICIENT",
        explanation=(
            f"formal={inputs.formal_campaign}, "
            f"valid_decisions={inputs.valid_decision_count}, "
            f"scenario_families={inputs.scenario_family_count}, "
            f"seeds={inputs.seed_count}"
        ),
    )

    heterogeneity_passing = {
        row.loss_view
        for row in _overall_rows(loss_heterogeneity)
        if row.positive_spread_rate >= 0.25
        and row.mean_spread_ci_lower > 0
    }
    heterogeneity = GateCheckRow(
        gate="loss_heterogeneity",
        status="PASS" if heterogeneity_passing else "FAIL",
        explanation=(
            "passing views=" + ",".join(sorted(heterogeneity_passing))
            if heterogeneity_passing
            else "no loss view passed spread thresholds"
        ),
    )

    headroom_passing = {
        row.loss_view
        for row in _overall_rows(regret)
        if row.non_tied_misselection_rate is not None
        and row.non_tied_misselection_rate >= 0.10
        and row.mean_normalized_regret > 0
        and row.mean_normalized_regret_ci_lower > 0
    }
    headroom = GateCheckRow(
        gate="baseline_headroom",
        status="PASS" if headroom_passing else "FAIL",
        explanation=(
            "passing views=" + ",".join(sorted(headroom_passing))
            if headroom_passing
            else "no loss view passed regret thresholds"
        ),
    )

    if inputs.online_signal_supported is None:
        signal_status = "NOT_EVALUATED"
        signal_explanation = "decision-time signal analysis not yet available"
    elif inputs.online_signal_supported:
        signal_status = "PASS"
        signal_explanation = "at least one stable online signal is supported"
    else:
        signal_status = "FAIL"
        signal_explanation = "no stable online signal is supported"
    signal = GateCheckRow(
        gate="decision_time_signal",
        status=signal_status,
        explanation=signal_explanation,
    )

    common_passing = heterogeneity_passing.intersection(headroom_passing)
    if integrity.status == "FAIL":
        overall = "DATA-INVALID"
    elif integrity.status != "PASS" or volume.status != "PASS":
        overall = "INSUFFICIENT-EVENTS"
    elif not common_passing:
        overall = "NO-MEASURABLE-GAP"
    elif signal.status == "NOT_EVALUATED":
        overall = "INCOMPLETE-SIGNAL-EVALUATION"
    elif signal.status == "FAIL":
        overall = "HEADROOM-BUT-NO-ONLINE-SIGNAL"
    elif common_passing.isdisjoint(inputs.direct_loss_views):
        overall = "GAP-PROVISIONAL"
    else:
        overall = "GAP-PASS"

    return EmpiricalGapReport(
        overall_outcome=overall,
        passing_loss_views=tuple(sorted(common_passing)),
        checks=(integrity, volume, heterogeneity, headroom, signal),
    )
