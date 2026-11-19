"""Independent, fail-closed G0--G6 ledger for the Phase 5 Formal protocol.

This module only evaluates supplied evidence.  It cannot resolve protocol-owned
research decisions, authorize GPU execution, or turn an unobservable fact into
a passing gate.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .phase5_replay import canonical_sha256

FORMAL_GATE_IDS = (
    "G0_M1_PROTOCOL_FREEZE",
    "G1_WORKLOAD_ACQUISITION_AND_SEAL",
    "G2_SIX_SYSTEM_FREEZE",
    "G3_REPLAY_CONFORMANCE",
    "G4_CALIBRATION_COMPLETE",
    "G5_GPU_RESOURCE_AUTHORIZATION",
    "G6_MANIFEST_AND_EVALUATOR_DRY_RUN",
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_PASS = "PASS"
_OBSERVED = "OBSERVED"


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _evaluate_gate(gate_id: str, supplied: object) -> dict[str, object]:
    reasons: list[str] = []
    evidence_rows: list[dict[str, object]] = []
    claimed_hash: object = None
    claimed_status: object = None

    if not isinstance(supplied, Mapping):
        reasons.append("GATE_EVIDENCE_MISSING")
    else:
        claimed_status = supplied.get("status")
        if claimed_status != _PASS:
            reasons.append(f"GATE_STATUS_{claimed_status or 'MISSING'}")
        claimed_hash = supplied.get("evidence_set_sha256")
        raw_rows = supplied.get("evidence")
        if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
            reasons.append("EVIDENCE_SET_MISSING")
        elif not raw_rows:
            reasons.append("EVIDENCE_SET_EMPTY")
        else:
            seen_ids: set[str] = set()
            for ordinal, raw_row in enumerate(raw_rows):
                if not isinstance(raw_row, Mapping):
                    reasons.append(f"EVIDENCE_{ordinal}_INVALID")
                    continue
                row = dict(raw_row)
                evidence_rows.append(row)
                evidence_id = row.get("evidence_id")
                if not isinstance(evidence_id, str) or not evidence_id:
                    reasons.append(f"EVIDENCE_{ordinal}_IDENTITY_MISSING")
                elif evidence_id in seen_ids:
                    reasons.append(f"EVIDENCE_ID_DUPLICATE:{evidence_id}")
                else:
                    seen_ids.add(evidence_id)
                if row.get("status") != _PASS:
                    reasons.append(
                        f"EVIDENCE_{evidence_id or ordinal}_STATUS_"
                        f"{row.get('status') or 'MISSING'}"
                    )
                if row.get("observability") != _OBSERVED:
                    reasons.append(
                        f"EVIDENCE_{evidence_id or ordinal}_OBSERVABILITY_"
                        f"{row.get('observability') or 'MISSING'}"
                    )
                if not _valid_sha256(row.get("sha256")):
                    reasons.append(f"EVIDENCE_{evidence_id or ordinal}_SHA256_INVALID")

    observed_hash = canonical_sha256(evidence_rows) if evidence_rows else None
    if not _valid_sha256(claimed_hash):
        reasons.append("EVIDENCE_SET_SHA256_INVALID")
    elif claimed_hash != observed_hash:
        reasons.append("EVIDENCE_SET_SHA256_MISMATCH")

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "gate_id": gate_id,
        "status": _PASS if not unique_reasons else "FAIL_CLOSED",
        "claimed_status": claimed_status,
        "evidence_count": len(evidence_rows),
        "evidence_set_sha256": observed_hash,
        "claimed_evidence_set_sha256": claimed_hash,
        "failure_reasons": unique_reasons,
    }


def evaluate_phase5_formal_gate_ledger(
    *,
    gate_evidence: Mapping[str, object],
    unresolved_requirements: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate all formal entry gates without granting execution authority.

    ``unresolved_requirements`` must be read from the frozen Protocol.  Any
    remaining entry, regardless of its descriptive status, keeps the ledger
    fail-closed; this evaluator intentionally has no API for resolving U1--U7.
    """

    unknown_gates = sorted(set(gate_evidence) - set(FORMAL_GATE_IDS))
    gates = [
        _evaluate_gate(gate_id, gate_evidence.get(gate_id))
        for gate_id in FORMAL_GATE_IDS
    ]

    unresolved: list[dict[str, object]] = []
    unresolved_failures: list[str] = []
    for ordinal, raw_row in enumerate(unresolved_requirements):
        if not isinstance(raw_row, Mapping):
            unresolved_failures.append(f"UNRESOLVED_{ordinal}_INVALID")
            continue
        row = dict(raw_row)
        unresolved.append(row)
        requirement_id = row.get("id")
        unresolved_failures.append(
            f"PROTOCOL_REQUIREMENT_UNRESOLVED:{requirement_id or ordinal}"
        )

    failures = [
        f"{gate['gate_id']}:{reason}"
        for gate in gates
        for reason in gate["failure_reasons"]
    ]
    failures.extend(f"UNKNOWN_GATE:{gate_id}" for gate_id in unknown_gates)
    failures.extend(unresolved_failures)
    status = _PASS if not failures else "FAIL_CLOSED"
    payload = {
        "schema_version": "phase5.formal_gate_ledger.v1",
        "status": status,
        "gate_order": list(FORMAL_GATE_IDS),
        "gates": gates,
        "unknown_gates": unknown_gates,
        "unresolved_requirements": unresolved,
        "failure_reasons": failures,
        "gpu_execution_authorized": False,
        "authorization_effect": "NONE",
    }
    return {**payload, "ledger_sha256": canonical_sha256(payload)}


def validate_phase5_formal_gate_ledger(ledger: Mapping[str, object]) -> None:
    """Validate ledger integrity and its non-authorizing contract."""

    if ledger.get("schema_version") != "phase5.formal_gate_ledger.v1":
        raise ValueError("unsupported Phase 5 Formal gate ledger")
    if ledger.get("gpu_execution_authorized") is not False:
        raise ValueError("gate ledger cannot authorize GPU execution")
    if ledger.get("authorization_effect") != "NONE":
        raise ValueError("gate ledger cannot have an authorization effect")
    content = dict(ledger)
    observed_hash = content.pop("ledger_sha256", None)
    if observed_hash != canonical_sha256(content):
        raise ValueError("Phase 5 Formal gate ledger hash mismatch")
    gates = ledger.get("gates")
    if not isinstance(gates, list):
        raise TypeError("gate ledger gates must be a list")
    if [row.get("gate_id") for row in gates if isinstance(row, Mapping)] != list(
        FORMAL_GATE_IDS
    ):
        raise ValueError("gate ledger must contain exact ordered G0--G6 gates")
    expected_status = (
        _PASS
        if all(row.get("status") == _PASS for row in gates)
        and not ledger.get("unknown_gates")
        and not ledger.get("unresolved_requirements")
        and not ledger.get("failure_reasons")
        else "FAIL_CLOSED"
    )
    if ledger.get("status") != expected_status:
        raise ValueError("gate ledger aggregate status is inconsistent")
