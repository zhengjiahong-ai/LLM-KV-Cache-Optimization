"""Calibration-to-Formal freeze candidate binding for Phase 5."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from .phase5_campaign_plan import assert_calibration_formal_disjoint
from .phase5_formal_orchestrator import validate_campaign_plan_identity
from .phase5_replay import canonical_sha256


class FormalFreezeError(RuntimeError):
    """Raised when Calibration cannot deterministically freeze a Formal plan."""


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalFreezeError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _group_counts(plan: Mapping[str, object]) -> Counter[str]:
    rows = plan.get("runs")
    if not isinstance(rows, list):
        raise FormalFreezeError("Formal plan has no run matrix")
    result: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise FormalFreezeError("Formal run row must be an object")
        stratum = row.get("stratum")
        group_id = row.get("group_id")
        if not isinstance(stratum, str) or not isinstance(group_id, str):
            raise FormalFreezeError("Formal run Group identity is invalid")
        identity = (stratum, group_id)
        if identity not in seen:
            result[stratum] += 1
            seen.add(identity)
    return result


def build_formal_freeze_candidate(
    *,
    calibration_plan: Mapping[str, object],
    calibration_analysis: Mapping[str, object],
    calibration_evidence_archive_sha256: str,
    formal_plan: Mapping[str, object],
    code_commit: str,
) -> dict[str, object]:
    """Bind exact Calibration outputs to the Formal plan without authorizing it."""

    validate_campaign_plan_identity(calibration_plan)
    validate_campaign_plan_identity(formal_plan)
    if calibration_plan.get("phase") != "CALIBRATION":
        raise FormalFreezeError("Calibration plan phase is not CALIBRATION")
    if formal_plan.get("phase") != "FORMAL":
        raise FormalFreezeError("Formal plan phase is not FORMAL")
    if calibration_plan.get("protocol_sha256") != formal_plan.get("protocol_sha256"):
        raise FormalFreezeError("Calibration and Formal protocol hashes differ")
    assert_calibration_formal_disjoint(calibration_plan, formal_plan)
    if calibration_analysis.get("status") != (
        "CALIBRATION_ANALYZED_EXECUTION_NOT_AUTHORIZED"
    ):
        raise FormalFreezeError("Calibration analysis status is not accepted")
    analysis_sha = calibration_analysis.get("analysis_sha256")
    analysis_payload = dict(calibration_analysis)
    analysis_payload.pop("analysis_sha256", None)
    if analysis_sha != canonical_sha256(analysis_payload):
        raise FormalFreezeError("Calibration analysis SHA-256 binding is invalid")
    sizing = calibration_analysis.get("sample_size")
    if not isinstance(sizing, Mapping) or sizing.get("distribution") != (
        "NONCENTRAL_T_ITERATIVE"
    ):
        raise FormalFreezeError("Calibration did not use the frozen power solver")
    selected = sizing.get("selected_groups_per_stratum")
    if not isinstance(selected, Mapping):
        raise FormalFreezeError("Calibration lacks selected Groups per stratum")
    selected_counts = {
        key: value for key, value in selected.items() if key == "SWE_BENCH"
    }
    if set(selected_counts) != {"SWE_BENCH"}:
        raise FormalFreezeError("Calibration sample size SWE stratum is incomplete")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 8 <= value <= 16
        for value in selected_counts.values()
    ):
        raise FormalFreezeError("Calibration sample size is outside 8..16")
    if dict(_group_counts(formal_plan)) != selected_counts:
        raise FormalFreezeError("Formal Group counts differ from Calibration sizing")
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise FormalFreezeError("code_commit must be a full Git SHA")
    payload = {
        "schema_version": "phase5.formal_freeze_candidate.v1",
        "status": "READY_FOR_M1_EXECUTION_AUTHORIZATION",
        "protocol_sha256": formal_plan["protocol_sha256"],
        "calibration_plan_sha256": calibration_plan["plan_sha256"],
        "calibration_analysis_sha256": analysis_sha,
        "calibration_evidence_archive_sha256": _digest(
            calibration_evidence_archive_sha256,
            "calibration_evidence_archive_sha256",
        ),
        "formal_plan_sha256": formal_plan["plan_sha256"],
        "selected_groups_per_stratum": selected_counts,
        "code_commit": code_commit,
        "execution_authorized": False,
        "authorization_effect": "NONE",
    }
    return {**payload, "freeze_candidate_sha256": canonical_sha256(payload)}
