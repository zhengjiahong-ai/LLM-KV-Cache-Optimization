"""Read-only readiness inventory for the Phase 5 SWE formal dataset."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .phase5_replay import canonical_sha256


class SWEDatasetReadinessError(ValueError):
    """Raised when SWE dataset identity or qualification evidence is inconsistent."""


def build_swe_dataset_readiness(
    *,
    session_evidence: Sequence[Mapping[str, Any]],
    input_bindings: Mapping[str, str],
    minimum_program_count: int = 48,
    calibration_program_count: int = 16,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Inventory qualified Programs without selecting a formal Cohort."""

    if len(session_evidence) != 57:
        raise SWEDatasetReadinessError("SWE processed Session inventory must contain 57 rows")
    session_ids = [str(row["session_id"]) for row in session_evidence]
    if len(session_ids) != len(set(session_ids)):
        raise SWEDatasetReadinessError("SWE Session identities are not unique")
    qualified = sorted(
        (row for row in session_evidence if row["qualification_status"] == "QUALIFIED"),
        key=lambda row: str(row["program_id"]),
    )
    excluded = sorted(
        (row for row in session_evidence if row["qualification_status"] == "EXCLUDED"),
        key=lambda row: str(row["program_id"]),
    )
    if len(qualified) != 35 or len(excluded) != 22:
        raise SWEDatasetReadinessError("SWE qualification counts drifted from accepted evidence")
    program_ids = [str(row["program_id"]) for row in qualified]
    if len(program_ids) != len(set(program_ids)):
        raise SWEDatasetReadinessError("qualified SWE Sessions are not independent Programs")
    for row in qualified:
        checks = row.get("qualification_checks")
        if not isinstance(checks, dict) or set(checks) != {f"Q{i}" for i in range(1, 10)}:
            raise SWEDatasetReadinessError("qualified SWE Program lacks exact Q1-Q9 evidence")
        if not all(checks.values()):
            raise SWEDatasetReadinessError("qualified SWE Program has a failed Q1-Q9 check")
    candidate_payload: dict[str, object] = {
        "schema_version": "phase5.swe_formal_candidate_program_inventory.v1",
        "status": "QUALIFIED_PROGRAM_POOL_INSUFFICIENT_FOR_MINIMUM_COHORT",
        "workload_type": "SWE_BENCH_VERIFIED_FORMAL",
        "qualified_program_count": len(qualified),
        "independent_program_count": len(set(program_ids)),
        "qualified_programs": qualified,
        "program_identity_order": program_ids,
        "selection_inputs": [
            "frozen_sampling_frame_order",
            "Q1_Q9_qualification",
            "program_identity",
        ],
        "outcome_metrics_used": False,
        "calibration_cohort_selected": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    candidates = {
        **candidate_payload,
        "candidate_inventory_content_sha256": canonical_sha256(candidate_payload),
    }
    exclusion_counts = Counter(
        reason for row in excluded for reason in row.get("failed_rules", [])
    )
    exclusion_payload: dict[str, object] = {
        "schema_version": "phase5.swe_formal_exclusion_ledger.v1",
        "status": "COMPLETE_FOR_57_PROCESSED_SESSIONS",
        "excluded_session_count": len(excluded),
        "rule_failure_counts": dict(sorted(exclusion_counts.items())),
        "excluded_sessions": excluded,
        "excluded_sessions_promoted": False,
        "historical_w1c_promoted": False,
    }
    exclusions = {
        **exclusion_payload,
        "exclusion_ledger_content_sha256": canonical_sha256(exclusion_payload),
    }
    formal_minimum_program_count = minimum_program_count - calibration_program_count
    summary_payload: dict[str, object] = {
        "schema_version": "phase5.swe_formal_dataset_readiness.v1",
        "status": "BLOCKED_INSUFFICIENT_INDEPENDENT_QUALIFIED_PROGRAMS",
        "processed_session_count": len(session_evidence),
        "qualified_session_count": len(qualified),
        "qualified_independent_program_count": len(set(program_ids)),
        "excluded_session_count": len(excluded),
        "terminal_class_counts": dict(
            sorted(Counter(str(row["terminal_class"]) for row in session_evidence).items())
        ),
        "qualified_terminal_class_counts": dict(
            sorted(Counter(str(row["terminal_class"]) for row in qualified).items())
        ),
        "minimum_total_program_count": minimum_program_count,
        "minimum_calibration_program_count": calibration_program_count,
        "minimum_formal_program_count": formal_minimum_program_count,
        "minimum_program_shortfall": minimum_program_count - len(qualified),
        "maximum_complete_four_program_groups_from_current_pool": len(qualified) // 4,
        "required_minimum_total_group_count": minimum_program_count // 4,
        "current_pool_remainder_program_count": len(qualified) % 4,
        "input_bindings": dict(sorted(input_bindings.items())),
        "candidate_inventory_content_sha256": candidates[
            "candidate_inventory_content_sha256"
        ],
        "exclusion_ledger_content_sha256": exclusions[
            "exclusion_ledger_content_sha256"
        ],
        "calibration_groups_constructed": False,
        "formal_groups_constructed": False,
        "workload_seal_issued": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    summary = {
        **summary_payload,
        "readiness_content_sha256": canonical_sha256(summary_payload),
    }
    validate_swe_dataset_readiness(candidates, exclusions, summary)
    return candidates, exclusions, summary


def validate_swe_dataset_readiness(
    candidates: Mapping[str, Any],
    exclusions: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    """Fail closed on identity, count, hash, or authorization drift."""

    for payload, hash_name in (
        (candidates, "candidate_inventory_content_sha256"),
        (exclusions, "exclusion_ledger_content_sha256"),
        (summary, "readiness_content_sha256"),
    ):
        content = dict(payload)
        observed = content.pop(hash_name, None)
        if observed != canonical_sha256(content):
            raise SWEDatasetReadinessError(f"SWE {hash_name} mismatch")
    if candidates.get("qualified_program_count") != 35:
        raise SWEDatasetReadinessError("SWE qualified Program count drifted")
    if exclusions.get("excluded_session_count") != 22:
        raise SWEDatasetReadinessError("SWE exclusion count drifted")
    if summary.get("minimum_program_shortfall") != 13:
        raise SWEDatasetReadinessError("SWE minimum Program shortfall drifted")
    if summary.get("status") != "BLOCKED_INSUFFICIENT_INDEPENDENT_QUALIFIED_PROGRAMS":
        raise SWEDatasetReadinessError("SWE readiness must fail closed on shortfall")
    if any(
        value is not False
        for value in (
            candidates.get("calibration_cohort_selected"),
            candidates.get("formal_cohort_selected"),
            candidates.get("gpu_execution_authorized"),
            summary.get("calibration_groups_constructed"),
            summary.get("formal_groups_constructed"),
            summary.get("workload_seal_issued"),
            summary.get("formal_cohort_selected"),
            summary.get("gpu_execution_authorized"),
        )
    ):
        raise SWEDatasetReadinessError("SWE readiness package exceeds authorization")
