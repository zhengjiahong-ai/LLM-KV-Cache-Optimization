"""Join Phase 5B Native lifecycle and candidate-exposure evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .phase5_candidate_exposure import evaluate_run_candidate_exposure


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
