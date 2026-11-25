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
    predicted_sequences: list[tuple[int, ...]] = []
    physical_sequences: list[tuple[int, ...]] = []
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
        for sequence in predictions.values():
            if not isinstance(sequence, list) or any(
                isinstance(block, bool) or not isinstance(block, int) for block in sequence
            ):
                raise ValueError("predicted victim sequence is invalid")
            predicted_sequences.append(tuple(sequence))
        observed = physical.get("matched_physical_block_ids")
        if not isinstance(observed, list):
            raise TypeError("physical victim observation is unavailable")
        physical_sequences.append(tuple(observed))
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
            "status": "OBSERVED" if selections else "NOT_OBSERVABLE",
            "distinct_selected_entry_count": len(set(selections)),
        },
        "M2_PREDICTED_VICTIM_DIVERGENCE": {
            "status": "OBSERVED" if predicted_sequences else "NOT_OBSERVABLE",
            "distinct_predicted_sequence_count": len(set(predicted_sequences)),
        },
        "M3_ACTUAL_PHYSICAL_EVICTION": {
            "status": "OBSERVED" if physical_sequences else "NOT_OBSERVABLE",
            "distinct_physical_sequence_count": len(set(physical_sequences)),
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
