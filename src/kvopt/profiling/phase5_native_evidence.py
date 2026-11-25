"""Join Phase 5B Native lifecycle and candidate-exposure evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .phase5_candidate_exposure import evaluate_run_candidate_exposure
from .phase5_candidate_physical_evidence import join_candidate_physical_evidence
from .phase5_downstream_observation import join_downstream_observations


def _payload(row: Mapping[str, object]) -> Mapping[str, object]:
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError("Native evidence payload must be an object")
    return payload


def evaluate_phase5_native_evidence(
    *,
    run_id: str,
    arm: str,
    events: Sequence[Mapping[str, object]],
    execution_report: Mapping[str, object],
) -> dict[str, object]:
    """Fail closed unless decisions join one executed pressure boundary.

    This validates the evidence topology, not downstream recomputation
    causality.  The latter remains explicitly NOT_ESTABLISHED.
    """

    if execution_report.get("status") != "PASS":
        raise ValueError("candidate evidence requires passing async execution")
    enqueue = execution_report.get("enqueue_gate")
    if not isinstance(enqueue, Mapping) or enqueue.get("status") != "PASS":
        raise ValueError("candidate evidence requires passing enqueue gate")
    boundaries_raw = execution_report.get("pressure_boundary_ids")
    if not isinstance(boundaries_raw, list):
        raise TypeError("async execution report lacks pressure boundaries")
    boundaries = set(boundaries_raw)
    report = evaluate_run_candidate_exposure(run_id=run_id, arm=arm, events=events)
    decisions = report.get("decisions")
    assert isinstance(decisions, list)
    for decision in decisions:
        identity = decision.get("decision_identity")
        if identity not in boundaries:
            raise ValueError("decision is not bound to an executed pressure boundary")

    bindings = [
        _payload(row)
        for row in events
        if row.get("event_type") == "FORCED_RELEASE_DECISION_BINDING"
    ]
    for binding in bindings:
        boundary = binding.get("frozen_decision_boundary_id", binding.get("boundary_id"))
        if boundary not in boundaries:
            raise ValueError("Native binding references an unknown pressure boundary")
        context = binding.get("execution_context", binding.get("context_type"))
        if context not in {None, "PRESSURE", "PHASE5_PRESSURE"}:
            raise ValueError("Native binding has a non-pressure execution context")
    return {
        "schema_version": "phase5.native_candidate_evidence.v1",
        "status": "PASS",
        "run_id": run_id,
        "arm": arm,
        "async_execution_status": "PASS",
        "actual_enqueue_status": "PASS",
        "pressure_boundary_count": len(boundaries),
        "candidate_exposure": report,
        "physical_causal_attribution": "NOT_ESTABLISHED",
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
    }


def evaluate_phase5_decision_evidence(
    *,
    candidate_evaluations: Sequence[Mapping[str, object]],
    selection_plans: Sequence[Mapping[str, object]],
    physical_outcomes: Sequence[Mapping[str, object]],
    a0_physical_outcomes_by_boundary: Mapping[str, Mapping[str, object]],
    downstream_by_decision: Mapping[str, Sequence[Mapping[str, object]]],
    candidate_id: str,
) -> dict[str, object]:
    """Independently join every candidate decision through downstream evidence."""

    def unique(rows: Sequence[Mapping[str, object]], label: str) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for row in rows:
            decision_id = row.get("decision_id")
            if not isinstance(decision_id, str) or not decision_id:
                raise ValueError(f"{label} lacks decision identity")
            if decision_id in result:
                raise ValueError(f"{label} decision identity is not unique")
            result[decision_id] = row
        return result

    evaluations = unique(candidate_evaluations, "candidate evaluation")
    plans = unique(selection_plans, "SelectionPlan")
    outcomes = unique(physical_outcomes, "Physical Outcome")
    if set(evaluations) != set(plans) or set(evaluations) != set(outcomes):
        raise ValueError("decision/SelectionPlan/Physical Outcome coverage differs")
    if set(downstream_by_decision) != set(evaluations):
        raise ValueError("downstream observation coverage differs")
    plan_boundaries = {str(row.get("pressure_boundary_id")) for row in plans.values()}
    if set(a0_physical_outcomes_by_boundary) != plan_boundaries:
        raise ValueError("A0 physical outcome boundary coverage differs")
    rows = []
    for decision_id, evaluation in evaluations.items():
        physical = join_candidate_physical_evidence(
            evaluation=evaluation,
            candidate_id=candidate_id,
            selection_plan=plans[decision_id],
            physical_outcome=outcomes[decision_id],
            a0_physical_outcome=a0_physical_outcomes_by_boundary[
                str(plans[decision_id].get("pressure_boundary_id"))
            ],
        )
        downstream = join_downstream_observations(
            physical_evidence=physical,
            observations=downstream_by_decision[decision_id],
        )
        rows.append({"physical": physical, "downstream": downstream})
    return {
        "schema_version": "phase5.decision_evidence_chain.v1",
        "status": "PASS",
        "candidate_id": candidate_id,
        "decision_count": len(rows),
        "decisions": rows,
        "native_runtime_conformance": "NOT_ESTABLISHED_BY_CPU_EVALUATION",
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
        "algorithmic_benefit_claim": "NOT_ESTABLISHED",
    }
