from __future__ import annotations

from dataclasses import replace

import pytest

from kvopt.workload.phase5_candidate_evaluation import (
    CANDIDATE_IDS,
    CandidateDecision,
    CandidateDecisionSnapshot,
    evaluate_candidate_family,
)


def _snapshot():
    return CandidateDecisionSnapshot(
        decision_id="d1",
        group_id="g1",
        stratum="SWE_BENCH",
        program_id="p1",
        session_id="s1",
        turn_id="t1",
        trace_sha256="1" * 64,
        logical_time=1.0,
        legal_candidate_ids=("x", "y"),
        candidate_features_by_algorithm={row: {"feature": 1} for row in CANDIDATE_IDS},
        a0_baseline_selection="x",
        native_block_pool_snapshot_sha256="2" * 64,
        free_queue_order_sha256="3" * 64,
        refcount_snapshot_sha256="4" * 64,
        eligibility_protection_sha256="5" * 64,
        evidence_coverage={"pool": True, "queue": True, "identity": True},
    )


class _Adapter:
    correctness_gate_status = "PASS"

    def __init__(self, candidate_id, reverse=False):
        self.candidate_id = candidate_id
        self.reverse = reverse

    def evaluate(self, snapshot):
        scores = {"x": 1.0, "y": 2.0}
        if self.reverse:
            scores = {"x": 2.0, "y": 1.0}
        order = tuple(sorted(scores, key=lambda row: (scores[row], row)))
        return CandidateDecision(
            candidate_id=self.candidate_id,
            snapshot_sha256=snapshot.sha256,
            selected_candidate_id=order[0],
            scores=scores,
            ordered_candidate_ids=order,
            simulated_native_victim_sequences={
                "x": (1,),
                "y": (2,),
            },
            simulated_native_victim_block_ids=(1,) if not self.reverse else (2,),
            branch="STEP_2",
            fell_back=False,
            fallback_reason=None,
        )


def test_three_candidates_share_one_snapshot_and_report_divergence() -> None:
    report = evaluate_candidate_family(
        snapshot=_snapshot(),
        adapters=(
            _Adapter("A1_ORIGINAL"),
            _Adapter("A3_SUFFIX", reverse=True),
            _Adapter("DVA_ER_V1"),
        ),
    )
    assert report["status"] == "PASS"
    assert report["pairwise_selection_divergence"]["A1_ORIGINAL_vs_A3_SUFFIX"]
    assert report["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"


def test_dva_correctness_gate_and_common_snapshot_fail_closed() -> None:
    dva = _Adapter("DVA_ER_V1")
    dva.correctness_gate_status = "NOT_EXECUTED"
    with pytest.raises(ValueError, match="correctness gate"):
        evaluate_candidate_family(
            snapshot=_snapshot(),
            adapters=(_Adapter("A1_ORIGINAL"), _Adapter("A3_SUFFIX"), dva),
        )

    class WrongSnapshot(_Adapter):
        def evaluate(self, snapshot):
            return replace(super().evaluate(snapshot), snapshot_sha256="0" * 64)

    with pytest.raises(ValueError, match="different snapshot"):
        evaluate_candidate_family(
            snapshot=_snapshot(),
            adapters=(
                _Adapter("A1_ORIGINAL"),
                WrongSnapshot("A3_SUFFIX"),
                _Adapter("DVA_ER_V1"),
            ),
        )


def test_future_information_and_nonfinite_score_are_rejected() -> None:
    with pytest.raises(ValueError, match="future information"):
        replace(
            _snapshot(),
            candidate_features_by_algorithm={
                **_snapshot().candidate_features_by_algorithm,
                "DVA_ER_V1": {"future_reuse_outcome": True},
            },
        )

    class NonFinite(_Adapter):
        def evaluate(self, snapshot):
            decision = super().evaluate(snapshot)
            return replace(decision, scores={"x": float("nan"), "y": 1.0})

    with pytest.raises(ValueError, match="finite"):
        evaluate_candidate_family(
            snapshot=_snapshot(),
            adapters=(
                NonFinite("A1_ORIGINAL"),
                _Adapter("A3_SUFFIX"),
                _Adapter("DVA_ER_V1"),
            ),
        )
