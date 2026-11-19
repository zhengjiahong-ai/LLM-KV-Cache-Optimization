from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from kvopt.workload.phase5_candidate_evaluation import (
    CandidateDecision,
    CandidateDecisionSnapshot,
    evaluate_candidate_family,
)
from kvopt.workload.phase5_dva_candidate_adapter import DVAERCandidateAdapter


def _cpu_gate():
    return {
        "status": "PASS_CORRECTNESS_ONLY",
        "candidate": "DVA_ER_V1",
        "candidate_status": "PROVISIONAL_NOT_FROZEN",
        "gpu_executed": False,
        "implementation": "src/kvopt/costaware/dva_er.py",
        "test_module": "tests/test_dva_er.py",
        "tests_passed": 28,
        "checks": [
            "FULL_NATIVE_LRU_SEQUENCE_ORDER",
            "NO_FUTURE_FIELDS_IN_INPUT_CONTRACT",
            "OBSERVATION_NOT_AFTER_DECISION",
            "FUTURE_TRACE_ARRIVAL_SOURCE_REJECTED",
        ],
    }


def _dva_features():
    return {
        "candidate_key_by_id": {"x": ["program-x", "prefix"], "y": ["program-y", "prefix"]},
        "decision_timestamp": 10.0,
        "required_blocks": 1,
        "h_seconds": 60.0,
        "free_queue_order": [1, 2],
        "a0_order": ["y", "x"],
        "blocks": [
            {
                "block_id": 1,
                "has_hash": True,
                "refcount": 0,
                "native_lru_rank": 0,
                "owner_candidate_ids": ["x"],
                "protected_candidate_ids": ["x"],
            },
            {
                "block_id": 2,
                "has_hash": True,
                "refcount": 0,
                "native_lru_rank": 1,
                "owner_candidate_ids": ["y"],
                "protected_candidate_ids": ["y"],
            },
        ],
        "followups": {
            "x": {
                "chain_id": "chain-x",
                "active": False,
                "pending_tool_gap_seconds": None,
                "pending_tool_gap_source": None,
                "observed_at_timestamp": 9.0,
                "chain_established_at_timestamp": 8.0,
            },
            "y": {
                "chain_id": "chain-y",
                "active": True,
                "pending_tool_gap_seconds": 5.0,
                "pending_tool_gap_source": "CONTROLLER_ARMED_TIMER",
                "observed_at_timestamp": 9.0,
                "chain_established_at_timestamp": 8.0,
            },
        },
    }


def _snapshot(features=None):
    return CandidateDecisionSnapshot(
        decision_id="decision-1",
        group_id="group-1",
        stratum="SWE_BENCH",
        program_id="program",
        session_id="session",
        turn_id="turn",
        trace_sha256="1" * 64,
        logical_time=10.0,
        legal_candidate_ids=("x", "y"),
        candidate_features_by_algorithm={
            "A1_ORIGINAL": {"cost": {"x": 1.0, "y": 2.0}},
            "A3_SUFFIX": {"cost": {"x": 1.0, "y": 2.0}},
            "DVA_ER_V1": _dva_features() if features is None else features,
        },
        a0_baseline_selection="y",
        native_block_pool_snapshot_sha256="2" * 64,
        free_queue_order_sha256="3" * 64,
        refcount_snapshot_sha256="4" * 64,
        eligibility_protection_sha256="5" * 64,
        evidence_coverage={"pool": True, "queue": True, "followups": True},
    )


class _FixedAdapter:
    correctness_gate_status = "PASS"

    def __init__(self, candidate_id: str) -> None:
        self.candidate_id = candidate_id

    def evaluate(self, snapshot):
        return CandidateDecision(
            candidate_id=self.candidate_id,
            snapshot_sha256=snapshot.sha256,
            selected_candidate_id="y",
            scores={"x": 2.0, "y": 1.0},
            ordered_candidate_ids=("y", "x"),
            simulated_native_victim_block_ids=(2,),
            branch="FIXED_TEST_ADAPTER",
            fell_back=False,
            fallback_reason=None,
        )


def test_real_dva_er_is_integrated_into_candidate_family() -> None:
    adapter = DVAERCandidateAdapter(cpu_gate=_cpu_gate())
    report = evaluate_candidate_family(
        snapshot=_snapshot(),
        adapters=(
            _FixedAdapter("A1_ORIGINAL"),
            _FixedAdapter("A3_SUFFIX"),
            adapter,
        ),
    )
    dva = report["decisions"]["DVA_ER_V1"]
    assert dva["selected_candidate_id"] == "x"
    assert dva["scores"] == {"x": 0.0, "y": 1.0}
    assert dva["simulated_native_victim_block_ids"] == (1,)
    assert report["pairwise_selection_divergence"]["A1_ORIGINAL_vs_DVA_ER_V1"]
    assert report["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"
    assert adapter.candidate_status == "PROVISIONAL_NOT_FROZEN"
    assert adapter.native_conformance_status == "NOT_RUN"


def test_merged_cpu_gate_document_is_accepted() -> None:
    gate = json.loads(
        Path("docs/experiments/dva-er-v1-cpu-gate.json").read_text(
            encoding="utf-8"
        )
    )
    adapter = DVAERCandidateAdapter(cpu_gate=gate)
    assert adapter.correctness_gate_status == "PASS"
    assert adapter.candidate_status == "PROVISIONAL_NOT_FROZEN"


def test_cpu_gate_does_not_become_native_or_freeze_gate() -> None:
    gate = _cpu_gate()
    gate["gpu_executed"] = True
    with pytest.raises(ValueError, match="cannot claim GPU"):
        DVAERCandidateAdapter(cpu_gate=gate)
    gate = _cpu_gate()
    gate["candidate_status"] = "FROZEN"
    with pytest.raises(ValueError, match="freeze status"):
        DVAERCandidateAdapter(cpu_gate=gate)


def test_nested_future_evidence_is_rejected() -> None:
    features = deepcopy(_dva_features())
    features["followups"]["x"]["nested"] = {"future_reuse_outcome": True}
    adapter = DVAERCandidateAdapter(cpu_gate=_cpu_gate())
    with pytest.raises(ValueError, match="future evidence"):
        adapter.evaluate(_snapshot(features))


def test_decision_time_and_legal_candidate_identity_fail_closed() -> None:
    features = deepcopy(_dva_features())
    features["followups"]["x"]["observed_at_timestamp"] = 11.0
    adapter = DVAERCandidateAdapter(cpu_gate=_cpu_gate())
    with pytest.raises(Exception, match="after the decision"):
        adapter.evaluate(_snapshot(features))

    features = deepcopy(_dva_features())
    del features["candidate_key_by_id"]["y"]
    with pytest.raises(ValueError, match="legal set"):
        adapter.evaluate(_snapshot(features))
