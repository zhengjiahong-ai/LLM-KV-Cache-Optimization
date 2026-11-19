"""Join candidate decisions to SelectionPlan and physical eviction evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kvopt.workload.phase5_replay import canonical_sha256


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty text")
    return value


def _block_ids(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be an array")
    result = tuple(value)
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in result):
        raise ValueError(f"{label} must contain non-negative block IDs")
    if len(result) != len(set(result)):
        raise ValueError(f"{label} contains duplicate block IDs")
    return result


def join_candidate_physical_evidence(
    *,
    evaluation: Mapping[str, object],
    candidate_id: str,
    selection_plan: Mapping[str, object],
    physical_outcome: Mapping[str, object],
) -> dict[str, object]:
    """Bind planned and observed victims without claiming downstream benefit."""

    if evaluation.get("status") != "PASS":
        raise ValueError("candidate evaluation is not PASS")
    decision_id = _text(evaluation.get("decision_id"), "decision_id")
    snapshot_sha = _text(evaluation.get("snapshot_sha256"), "snapshot_sha256")
    decisions = evaluation.get("decisions")
    if not isinstance(decisions, Mapping) or candidate_id not in decisions:
        raise ValueError("candidate decision is absent from the evaluation")
    decision = decisions[candidate_id]
    if not isinstance(decision, Mapping):
        raise TypeError("candidate decision must be an object")
    if selection_plan.get("decision_id") != decision_id:
        raise ValueError("SelectionPlan decision identity mismatch")
    if selection_plan.get("candidate_id") != candidate_id:
        raise ValueError("SelectionPlan candidate identity mismatch")
    if physical_outcome.get("decision_id") != decision_id:
        raise ValueError("physical outcome decision identity mismatch")
    if physical_outcome.get("candidate_id") != candidate_id:
        raise ValueError("physical outcome candidate identity mismatch")
    if physical_outcome.get("status") != "PHYSICAL_EVICTION_OBSERVED":
        raise ValueError("physical eviction outcome is not observable")

    predicted = _block_ids(
        decision.get("simulated_native_victim_block_ids"),
        "simulated Native victim sequence",
    )
    planned = _block_ids(
        selection_plan.get("selected_native_block_ids"),
        "SelectionPlan block IDs",
    )
    if planned != predicted:
        raise ValueError("SelectionPlan differs from the candidate victim sequence")
    matched = _block_ids(
        physical_outcome.get("matched_physical_block_ids"),
        "matched physical block IDs",
    )
    unmatched = _block_ids(
        physical_outcome.get("unmatched_physical_block_ids"),
        "unmatched physical block IDs",
    )
    hashless = _block_ids(
        physical_outcome.get("hashless_physical_block_ids"),
        "hashless physical block IDs",
    )
    if not set(matched) <= set(planned):
        raise ValueError("matched physical blocks are outside the SelectionPlan")
    if set(unmatched) & set(planned):
        raise ValueError("unmatched physical blocks overlap the SelectionPlan")
    if set(matched) & set(unmatched) or set(matched) & set(hashless) or set(unmatched) & set(hashless):
        raise ValueError("physical outcome block classes are not disjoint")

    payload = {
        "schema_version": "phase5.candidate_physical_evidence.v1",
        "status": "PASS",
        "decision_id": decision_id,
        "snapshot_sha256": snapshot_sha,
        "candidate_id": candidate_id,
        "candidate_loss_by_entry": dict(decision.get("scores", {})),
        "selected_entry_id": decision.get("selected_candidate_id"),
        "predicted_native_victim_sequence": list(predicted),
        "selection_plan_native_block_ids": list(planned),
        "matched_physical_block_ids": list(matched),
        "unmatched_physical_block_ids": list(unmatched),
        "hashless_physical_block_ids": list(hashless),
        "predicted_equals_observed_matched": predicted == matched,
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
        "algorithmic_benefit_claim": "NOT_ESTABLISHED",
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}
