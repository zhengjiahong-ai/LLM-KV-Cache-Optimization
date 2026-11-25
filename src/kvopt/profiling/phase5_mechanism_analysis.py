"""M0--M5 observation framework for Phase 5 mechanism analysis.

These levels describe what was observed.  They are deliberately not execution
gates: absence of divergence is a valid research result, while absent evidence
is reported as NOT_OBSERVABLE rather than silently converted to zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kvopt.workload.phase5_replay import canonical_sha256


def _rows(value: object, label: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise TypeError(f"{label} must be an array of objects")
    return value


def evaluate_m0_m5(
    *,
    decision_chains: Sequence[Mapping[str, object]],
    system_effect: Mapping[str, object] | None,
) -> dict[str, object]:
    """Summarize decision, physical and downstream evidence without gating."""

    decision_ids: set[str] = set()
    candidate_counts: list[int] = []
    selections: list[str] = []
    selection_comparisons: list[bool] = []
    predicted_sequences: list[tuple[int, ...]] = []
    predicted_comparisons: list[bool] = []
    physical_sequences: list[tuple[int, ...]] = []
    physical_comparisons: list[bool] = []
    selected_prediction_comparisons: list[bool] = []
    recomputed_tokens: list[int] = []
    for chain in decision_chains:
        physical = chain.get("physical")
        downstream = chain.get("downstream")
        if not isinstance(physical, Mapping) or not isinstance(downstream, Mapping):
            raise TypeError("decision chain lacks physical/downstream evidence")
        decision_id = physical.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id or decision_id in decision_ids:
            raise ValueError("decision identity is missing or duplicated")
        decision_ids.add(decision_id)
        losses = physical.get("candidate_loss_by_entry")
        predictions = physical.get("predicted_native_victim_sequences_by_entry")
        if not isinstance(losses, Mapping) or not isinstance(predictions, Mapping):
            raise TypeError("complete candidate decision space is unavailable")
        if set(losses) != set(predictions):
            raise ValueError("candidate loss/victim prediction coverage differs")
        candidate_counts.append(len(losses))
        selected = physical.get("selected_entry_id")
        if not isinstance(selected, str) or selected not in losses:
            raise ValueError("selected Entry is outside the decision space")
        selections.append(selected)
        a0_selected = physical.get("a0_selected_entry_id")
        if a0_selected is not None:
            if not isinstance(a0_selected, str) or a0_selected not in losses:
                raise ValueError("A0 selected Entry is outside the decision space")
            selection_comparisons.append(selected != a0_selected)
        selected_prediction: tuple[int, ...] | None = None
        for sequence in predictions.values():
            if not isinstance(sequence, list) or any(
                isinstance(block, bool) or not isinstance(block, int) for block in sequence
            ):
                raise ValueError("predicted victim sequence is invalid")
            predicted_sequences.append(tuple(sequence))
        selected_prediction = tuple(predictions[selected])
        a0_prediction = physical.get("a0_predicted_native_victim_sequence")
        if a0_prediction is not None:
            if not isinstance(a0_prediction, list) or any(
                isinstance(block, bool) or not isinstance(block, int)
                for block in a0_prediction
            ):
                raise ValueError("A0 predicted victim sequence is invalid")
            predicted_comparisons.append(selected_prediction != tuple(a0_prediction))
        observed = physical.get("matched_physical_block_ids")
        if not isinstance(observed, list) or any(
            isinstance(block, bool) or not isinstance(block, int) for block in observed
        ):
            raise TypeError("physical victim observation is unavailable")
        observed_sequence = tuple(observed)
        physical_sequences.append(observed_sequence)
        selected_prediction_comparisons.append(observed_sequence != selected_prediction)
        a0_physical = physical.get("a0_matched_physical_block_ids")
        if a0_physical is not None:
            if not isinstance(a0_physical, list) or any(
                isinstance(block, bool) or not isinstance(block, int)
                for block in a0_physical
            ):
                raise ValueError("A0 physical victim sequence is invalid")
            physical_comparisons.append(observed_sequence != tuple(a0_physical))
        for observation in _rows(downstream.get("observations"), "downstream observations"):
            value = observation.get("observed_recomputed_tokens")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("downstream recomputation observation is invalid")
            recomputed_tokens.append(value)

    levels = {
        "M0_DECISION_SPACE": {
            "status": "OBSERVED" if decision_ids else "NOT_OBSERVABLE",
            "decision_count": len(decision_ids),
            "multi_candidate_decision_count": sum(value > 1 for value in candidate_counts),
        },
        "M1_SELECTION_DIVERGENCE": {
            "status": "OBSERVED" if selection_comparisons else "NOT_OBSERVABLE",
            "comparable_decision_count": len(selection_comparisons),
            "selected_entry_vs_a0_divergence_count": sum(selection_comparisons),
            "distinct_selected_entry_observation_count": len(set(selections)),
        },
        "M2_PREDICTED_VICTIM_DIVERGENCE": {
            "status": "OBSERVED" if predicted_comparisons else "NOT_OBSERVABLE",
            "comparable_decision_count": len(predicted_comparisons),
            "selected_prediction_vs_a0_divergence_count": sum(predicted_comparisons),
            "distinct_predicted_sequence_observation_count": len(
                set(predicted_sequences)
            ),
        },
        "M3_ACTUAL_PHYSICAL_EVICTION": {
            "status": "OBSERVED" if physical_sequences else "NOT_OBSERVABLE",
            "distinct_physical_sequence_observation_count": len(
                set(physical_sequences)
            ),
            "selected_physical_vs_prediction_mismatch_count": sum(
                selected_prediction_comparisons
            ),
            "a0_comparable_decision_count": len(physical_comparisons),
            "selected_physical_vs_a0_divergence_count": sum(physical_comparisons),
        },
        "M4_DOWNSTREAM_RECOMPUTE": {
            "status": "OBSERVED" if recomputed_tokens else "NOT_OBSERVABLE",
            "observation_count": len(recomputed_tokens),
            "observed_recomputed_tokens_sum": sum(recomputed_tokens),
            "downstream_recompute_attribution": "NOT_ESTABLISHED",
        },
        "M5_SYSTEM_EFFECT": {
            "status": "OBSERVED" if system_effect is not None else "NOT_OBSERVABLE",
            "paired_group_result": None if system_effect is None else dict(system_effect),
            "algorithmic_benefit_claim": "NOT_ESTABLISHED",
        },
    }
    payload = {
        "schema_version": "phase5.mechanism_analysis.m0_m5.v1",
        "status": "DESCRIPTIVE_OBSERVATION_NOT_EXECUTION_GATE",
        "levels": levels,
        "eviction_causal_attribution": "NOT_ESTABLISHED",
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
        "algorithmic_benefit_claim": "NOT_ESTABLISHED",
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}
