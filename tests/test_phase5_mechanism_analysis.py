from __future__ import annotations

from kvopt.profiling.phase5_mechanism_analysis import evaluate_m0_m5


def _chain(selected: str = "entry-a") -> dict[str, object]:
    return {
        "physical": {
            "decision_id": "d1",
            "candidate_loss_by_entry": {"entry-a": 1.0, "entry-b": 2.0},
            "selected_entry_id": selected,
            "predicted_native_victim_sequences_by_entry": {
                "entry-a": [1, 2],
                "entry-b": [3, 4],
            },
            "matched_physical_block_ids": [1, 2],
            "a0_selected_entry_id": "entry-b",
            "a0_predicted_native_victim_sequence": [3, 4],
            "a0_matched_physical_block_ids": [3, 4],
        },
        "downstream": {
            "observations": [{"observed_recomputed_tokens": 8}],
        },
    }


def test_m0_m5_are_observations_not_gates() -> None:
    report = evaluate_m0_m5(decision_chains=[_chain()], system_effect=None)
    assert report["status"] == "DESCRIPTIVE_OBSERVATION_NOT_EXECUTION_GATE"
    assert report["levels"]["M0_DECISION_SPACE"]["multi_candidate_decision_count"] == 1
    assert (
        report["levels"]["M1_SELECTION_DIVERGENCE"][
            "selected_entry_vs_a0_divergence_count"
        ]
        == 1
    )
    assert (
        report["levels"]["M2_PREDICTED_VICTIM_DIVERGENCE"][
            "selected_prediction_vs_a0_divergence_count"
        ]
        == 1
    )
    assert (
        report["levels"]["M3_ACTUAL_PHYSICAL_EVICTION"][
            "selected_physical_vs_a0_divergence_count"
        ]
        == 1
    )
    assert report["levels"]["M5_SYSTEM_EFFECT"]["status"] == "NOT_OBSERVABLE"
    assert report["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"


def test_no_decisions_is_a_reportable_result() -> None:
    report = evaluate_m0_m5(decision_chains=[], system_effect={"estimate": 0.0})
    assert report["levels"]["M0_DECISION_SPACE"]["status"] == "NOT_OBSERVABLE"
    assert report["levels"]["M5_SYSTEM_EFFECT"]["status"] == "OBSERVED"


def test_missing_a0_comparator_is_not_misreported_as_divergence() -> None:
    chain = _chain()
    physical = chain["physical"]
    assert isinstance(physical, dict)
    del physical["a0_selected_entry_id"]
    del physical["a0_predicted_native_victim_sequence"]
    del physical["a0_matched_physical_block_ids"]

    report = evaluate_m0_m5(decision_chains=[chain], system_effect=None)
    assert report["levels"]["M1_SELECTION_DIVERGENCE"]["status"] == "NOT_OBSERVABLE"
    assert (
        report["levels"]["M2_PREDICTED_VICTIM_DIVERGENCE"]["status"]
        == "NOT_OBSERVABLE"
    )
    assert report["levels"]["M3_ACTUAL_PHYSICAL_EVICTION"]["status"] == "OBSERVED"
    assert (
        report["levels"]["M3_ACTUAL_PHYSICAL_EVICTION"][
            "a0_comparable_decision_count"
        ]
        == 0
    )
