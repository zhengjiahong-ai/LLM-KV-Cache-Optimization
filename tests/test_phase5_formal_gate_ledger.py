from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_formal_gate_ledger import (
    FORMAL_GATE_IDS,
    evaluate_phase5_formal_gate_ledger,
    validate_phase5_formal_gate_ledger,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _passing_gate(gate_id: str) -> dict[str, object]:
    evidence = [
        {
            "evidence_id": f"{gate_id}:evidence",
            "status": "PASS",
            "observability": "OBSERVED",
            "sha256": canonical_sha256({"gate_id": gate_id}),
        }
    ]
    return {
        "status": "PASS",
        "evidence": evidence,
        "evidence_set_sha256": canonical_sha256(evidence),
    }


def _passing_inputs() -> dict[str, object]:
    return {gate_id: _passing_gate(gate_id) for gate_id in FORMAL_GATE_IDS}


def test_complete_observed_gate_set_is_integrity_valid_but_never_authorizes_gpu() -> None:
    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=_passing_inputs(), unresolved_requirements=[]
    )

    assert ledger["status"] == "PASS"
    assert ledger["gpu_execution_authorized"] is False
    assert ledger["authorization_effect"] == "NONE"
    validate_phase5_formal_gate_ledger(ledger)


@pytest.mark.parametrize("status", ["UNRESOLVED", "NOT_OBSERVABLE", "MISSING"])
def test_nonpassing_evidence_status_fails_closed(status: str) -> None:
    inputs = _passing_inputs()
    inputs[FORMAL_GATE_IDS[2]]["evidence"][0]["status"] = status
    inputs[FORMAL_GATE_IDS[2]]["evidence_set_sha256"] = canonical_sha256(
        inputs[FORMAL_GATE_IDS[2]]["evidence"]
    )

    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=inputs, unresolved_requirements=[]
    )

    assert ledger["status"] == "FAIL_CLOSED"
    assert ledger["gates"][2]["status"] == "FAIL_CLOSED"


def test_not_observable_evidence_fails_closed_even_when_claimed_pass() -> None:
    inputs = _passing_inputs()
    inputs[FORMAL_GATE_IDS[3]]["evidence"][0]["observability"] = "NOT_OBSERVABLE"
    inputs[FORMAL_GATE_IDS[3]]["evidence_set_sha256"] = canonical_sha256(
        inputs[FORMAL_GATE_IDS[3]]["evidence"]
    )

    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=inputs, unresolved_requirements=[]
    )

    assert ledger["status"] == "FAIL_CLOSED"
    assert any(
        "OBSERVABILITY_NOT_OBSERVABLE" in reason
        for reason in ledger["gates"][3]["failure_reasons"]
    )


def test_missing_gate_and_empty_evidence_fail_closed_independently() -> None:
    inputs = _passing_inputs()
    del inputs[FORMAL_GATE_IDS[0]]
    inputs[FORMAL_GATE_IDS[1]] = {
        "status": "PASS",
        "evidence": [],
        "evidence_set_sha256": canonical_sha256([]),
    }

    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=inputs, unresolved_requirements=[]
    )

    assert ledger["gates"][0]["status"] == "FAIL_CLOSED"
    assert ledger["gates"][1]["status"] == "FAIL_CLOSED"
    assert ledger["status"] == "FAIL_CLOSED"


def test_evidence_hash_mismatch_and_duplicate_identity_fail_closed() -> None:
    inputs = _passing_inputs()
    gate = inputs[FORMAL_GATE_IDS[4]]
    gate["evidence"].append(deepcopy(gate["evidence"][0]))

    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=inputs, unresolved_requirements=[]
    )

    reasons = ledger["gates"][4]["failure_reasons"]
    assert any(reason.startswith("EVIDENCE_ID_DUPLICATE") for reason in reasons)
    assert "EVIDENCE_SET_SHA256_MISMATCH" in reasons


def test_protocol_unresolved_items_cannot_be_closed_by_gate_evidence() -> None:
    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=_passing_inputs(),
        unresolved_requirements=[
            {
                "id": "U1_COST_AWARE_CANDIDATE_FAMILY",
                "status": "NOT_FROZEN",
                "owner": "M1",
            },
            {
                "id": "U7_CENSORED_SESSION_POLICY",
                "status": "FREEZE_REQUIRED",
                "owner": "M1/M4",
            },
        ],
    )

    assert all(gate["status"] == "PASS" for gate in ledger["gates"])
    assert ledger["status"] == "FAIL_CLOSED"
    assert ledger["gpu_execution_authorized"] is False
    assert any(
        "U1_COST_AWARE_CANDIDATE_FAMILY" in row
        for row in ledger["failure_reasons"]
    )


def test_unknown_gate_fails_closed() -> None:
    inputs = _passing_inputs()
    inputs["G7_UNDECLARED"] = _passing_gate("G7_UNDECLARED")

    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=inputs, unresolved_requirements=[]
    )

    assert ledger["status"] == "FAIL_CLOSED"
    assert ledger["unknown_gates"] == ["G7_UNDECLARED"]


def test_validator_rejects_tampering_and_authorization() -> None:
    ledger = evaluate_phase5_formal_gate_ledger(
        gate_evidence=_passing_inputs(), unresolved_requirements=[]
    )
    tampered = dict(ledger)
    tampered["gpu_execution_authorized"] = True
    with pytest.raises(ValueError, match="cannot authorize"):
        validate_phase5_formal_gate_ledger(tampered)

    tampered = dict(ledger)
    tampered["status"] = "FAIL_CLOSED"
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_phase5_formal_gate_ledger(tampered)
