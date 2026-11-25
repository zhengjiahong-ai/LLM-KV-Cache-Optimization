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
        },
        "downstream": {
            "observations": [{"observed_recomputed_tokens": 8}],
        },
    }


def test_m0_m5_are_observations_not_gates() -> None:
    report = evaluate_m0_m5(decision_chains=[_chain()], system_effect=None)
    assert report["status"] == "DESCRIPTIVE_OBSERVATION_NOT_EXECUTION_GATE"
    assert report["levels"]["M0_DECISION_SPACE"]["multi_candidate_decision_count"] == 1
    assert report["levels"]["M5_SYSTEM_EFFECT"]["status"] == "NOT_OBSERVABLE"
    assert report["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"


def test_no_decisions_is_a_reportable_result() -> None:
    report = evaluate_m0_m5(decision_chains=[], system_effect={"estimate": 0.0})
    assert report["levels"]["M0_DECISION_SPACE"]["status"] == "NOT_OBSERVABLE"
    assert report["levels"]["M5_SYSTEM_EFFECT"]["status"] == "OBSERVED"
