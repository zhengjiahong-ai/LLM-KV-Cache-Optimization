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
    a0_physical_outcome: Mapping[str, object],
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
    boundary_id = _text(selection_plan.get("pressure_boundary_id"), "pressure boundary")
    if physical_outcome.get("pressure_boundary_id") != boundary_id:
        raise ValueError("physical outcome pressure boundary mismatch")
    if physical_outcome.get("status") != "PHYSICAL_EVICTION_OBSERVED":
        raise ValueError("physical eviction outcome is not observable")
    a0_selected = _text(evaluation.get("a0_baseline_selection"), "A0 selected Entry")

    predicted = _block_ids(
        decision.get("simulated_native_victim_block_ids"),
        "simulated Native victim sequence",
    )
    all_predicted_raw = decision.get("simulated_native_victim_sequences")
    if not isinstance(all_predicted_raw, Mapping):
        raise TypeError("complete per-entry victim sequences are absent")
    all_predicted = {
        _text(entry_id, "entry identity"): list(_block_ids(sequence, f"victim sequence {entry_id}"))
        for entry_id, sequence in all_predicted_raw.items()
    }
    if set(all_predicted) != set(decision.get("scores", {})):
        raise ValueError("victim sequence map differs from the scored candidate set")
    if a0_selected not in all_predicted:
        raise ValueError("A0 selected Entry is outside the predicted candidate set")
    a0_predicted = tuple(all_predicted[a0_selected])
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
    if (
        set(matched) & set(unmatched)
        or set(matched) & set(hashless)
        or set(unmatched) & set(hashless)
    ):
        raise ValueError("physical outcome block classes are not disjoint")
    content_rows = physical_outcome.get("block_content_identities")
    if not isinstance(content_rows, Mapping):
        raise TypeError("physical block/content identities are absent")
    observed_blocks = set(matched) | set(unmatched) | set(hashless)
    if set(map(str, observed_blocks)) != set(content_rows):
        raise ValueError("physical block/content identity coverage differs")
    for block_id, raw_identity in content_rows.items():
        try:
            numeric_block_id = int(block_id)
        except (TypeError, ValueError) as error:
            raise ValueError("physical content identity has an invalid block ID") from error
        identity = _text(raw_identity, f"content identity for block {block_id}")
        if (identity == "HASHLESS") != (numeric_block_id in set(hashless)):
            raise ValueError("HASHLESS content identity classification is inconsistent")

    if a0_physical_outcome.get("system_id") != "CONTINUUM_ADAPTED":
        raise ValueError("A0 physical outcome does not come from CONTINUUM_ADAPTED")
    if a0_physical_outcome.get("pressure_boundary_id") != boundary_id:
        raise ValueError("A0 physical outcome pressure boundary mismatch")
    if a0_physical_outcome.get("status") != "PHYSICAL_EVICTION_OBSERVED":
        raise ValueError("A0 physical eviction outcome is not observable")
    a0_matched = _block_ids(
        a0_physical_outcome.get("matched_physical_block_ids"),
        "A0 matched physical block IDs",
    )
    a0_unmatched = _block_ids(
        a0_physical_outcome.get("unmatched_physical_block_ids"),
        "A0 unmatched physical block IDs",
    )
    a0_hashless = _block_ids(
        a0_physical_outcome.get("hashless_physical_block_ids"),
        "A0 hashless physical block IDs",
    )
    if (
        set(a0_matched) & set(a0_unmatched)
        or set(a0_matched) & set(a0_hashless)
        or set(a0_unmatched) & set(a0_hashless)
    ):
        raise ValueError("A0 physical outcome block classes are not disjoint")
    a0_content_rows = a0_physical_outcome.get("block_content_identities")
    if not isinstance(a0_content_rows, Mapping):
        raise TypeError("A0 physical block/content identities are absent")
    a0_observed = set(a0_matched) | set(a0_unmatched) | set(a0_hashless)
    if set(map(str, a0_observed)) != set(a0_content_rows):
        raise ValueError("A0 physical block/content identity coverage differs")

    payload = {
        "schema_version": "phase5.candidate_physical_evidence.v1",
        "status": "PASS",
        "decision_id": decision_id,
        "pressure_boundary_id": boundary_id,
        "snapshot_sha256": snapshot_sha,
        "candidate_id": candidate_id,
        "candidate_loss_by_entry": dict(decision.get("scores", {})),
        "selected_entry_id": decision.get("selected_candidate_id"),
        "a0_selected_entry_id": a0_selected,
        "predicted_native_victim_sequence": list(predicted),
        "a0_predicted_native_victim_sequence": list(a0_predicted),
        "predicted_native_victim_sequences_by_entry": all_predicted,
        "selection_plan_native_block_ids": list(planned),
        "matched_physical_block_ids": list(matched),
        "a0_matched_physical_block_ids": list(a0_matched),
        "a0_unmatched_physical_block_ids": list(a0_unmatched),
        "a0_hashless_physical_block_ids": list(a0_hashless),
        "a0_block_content_identities": dict(a0_content_rows),
        "unmatched_physical_block_ids": list(unmatched),
        "hashless_physical_block_ids": list(hashless),
        "block_content_identities": dict(content_rows),
        "predicted_equals_observed_matched": predicted == matched,
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
        "algorithmic_benefit_claim": "NOT_ESTABLISHED",
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}
