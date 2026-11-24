"""Fail-closed review package for the Phase 5 SWE reserve reacquisition."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .phase5_replay import canonical_sha256


class SWEReacquisitionReviewError(ValueError):
    """Raised when reserve acquisition evidence or identity is inconsistent."""


def _with_hash(payload: dict[str, object], field: str) -> dict[str, object]:
    return {**payload, field: canonical_sha256(payload)}


def build_swe_reacquisition_review(
    *,
    existing_inventory: Mapping[str, Any],
    ordered_instance_ids: Sequence[str],
    attempt_rows: Sequence[Mapping[str, Any]],
    conversion_rows: Sequence[Mapping[str, Any]],
    qualification_rows: Sequence[Mapping[str, Any]],
    input_bindings: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Reconcile 20 fresh attempts and propose a 48-Program review pool."""

    ordered = list(ordered_instance_ids)
    if len(ordered) != 20 or len(set(ordered)) != 20:
        raise SWEReacquisitionReviewError(
            "historical reserve must contain exactly 20 unique ordered identities"
        )
    old_rows = existing_inventory.get("qualified_programs")
    old_order = existing_inventory.get("program_identity_order")
    if not isinstance(old_rows, list) or not isinstance(old_order, list):
        raise SWEReacquisitionReviewError("existing candidate inventory is malformed")
    if len(old_rows) != 35 or len(old_order) != 35:
        raise SWEReacquisitionReviewError("existing qualified Program count must be 35")
    if [str(row["program_id"]) for row in old_rows] != [str(x) for x in old_order]:
        raise SWEReacquisitionReviewError("existing candidate order is inconsistent")

    attempts = {str(row["instance_id"]): dict(row) for row in attempt_rows}
    conversions = {str(row["instance_id"]): dict(row) for row in conversion_rows}
    qualifications = {
        str(row["program_id"]): dict(row) for row in qualification_rows
    }
    if set(attempts) != set(ordered) or len(attempts) != 20:
        raise SWEReacquisitionReviewError("attempt ledger does not cover frozen reserve")
    if set(conversions) != set(ordered) or len(conversions) != 20:
        raise SWEReacquisitionReviewError("conversion ledger does not cover frozen reserve")
    if any(attempts[identity].get("status") != "completed" for identity in ordered):
        raise SWEReacquisitionReviewError("all 20 authorized attempts must be represented")
    for identity in ordered:
        attempt = attempts[identity]
        if attempt.get("phase5_acquisition_identity") != (
            f"PHASE5_HISTORICAL_CANDIDATE_FRESH_REACQUISITION:{identity}"
        ):
            raise SWEReacquisitionReviewError("fresh Phase 5 attempt identity mismatch")
        if not attempt.get("started_at_utc") or not attempt.get("finished_at_utc"):
            raise SWEReacquisitionReviewError("fresh attempt timestamps are incomplete")
        if attempt.get("old_w1c_evidence_reused") is not False:
            raise SWEReacquisitionReviewError("fresh attempt claims old W1-C evidence reuse")
        comparisons = attempt.get("historical_w1c_hash_comparisons")
        if not isinstance(comparisons, list) or len(comparisons) != 2:
            raise SWEReacquisitionReviewError(
                "fresh attempt lacks both historical W1-C hash comparisons"
            )
        if any(row.get("any_artifact_hash_match") is not False for row in comparisons):
            raise SWEReacquisitionReviewError(
                "fresh attempt reuses a historical W1-C artifact hash"
            )

    ledger_rows = []
    qualified_new = []
    for identity in ordered:
        attempt = attempts[identity]
        conversion = conversions[identity]
        conversion_status = conversion.get("status")
        qualification = qualifications.get(identity)
        if conversion_status == "CONVERTED":
            if qualification is None:
                raise SWEReacquisitionReviewError(
                    "converted reserve record lacks qualification evidence"
                )
            qualification_status = qualification.get("qualification_status")
            if qualification_status not in {"QUALIFIED", "EXCLUDED"}:
                raise SWEReacquisitionReviewError("invalid qualification status")
            if qualification_status == "QUALIFIED":
                checks = qualification.get("qualification_checks")
                if not isinstance(checks, dict) or set(checks) != {
                    f"Q{i}" for i in range(1, 10)
                }:
                    raise SWEReacquisitionReviewError(
                        "qualified reserve Program lacks exact Q1-Q9 evidence"
                    )
                if not all(checks.values()):
                    raise SWEReacquisitionReviewError(
                        "qualified reserve Program has a failed Q1-Q9 check"
                    )
                qualified_new.append(
                    {
                        **qualification,
                        "attempt_id": attempt["attempt_id"],
                        "phase5_acquisition_identity": attempt[
                            "phase5_acquisition_identity"
                        ],
                        "run_json_sha256": attempt["run_json_sha256"],
                        "trajectory_sha256": attempt["trajectory_sha256"],
                        "sidecar_sha256": attempt["sidecar_sha256"],
                    }
                )
        elif conversion_status == "EXCLUDED_PRE_NORMALIZATION":
            if qualification is not None:
                raise SWEReacquisitionReviewError(
                    "pre-normalization exclusion cannot have qualification evidence"
                )
            qualification_status = "NOT_EVALUATED"
        else:
            raise SWEReacquisitionReviewError("invalid conversion status")
        ledger_rows.append(
            {
                "instance_id": identity,
                "attempt": attempt,
                "conversion": conversion,
                "qualification_status": qualification_status,
                "qualification": qualification,
            }
        )

    converted_count = sum(
        row["conversion"]["status"] == "CONVERTED" for row in ledger_rows
    )
    qualified_count = len(qualified_new)
    q_excluded_count = sum(
        row["qualification_status"] == "EXCLUDED" for row in ledger_rows
    )
    if (converted_count, 20 - converted_count, qualified_count, q_excluded_count) != (
        17,
        3,
        13,
        4,
    ):
        raise SWEReacquisitionReviewError(
            "reserve conversion or qualification counts drifted from observed evidence"
        )

    old_ids = [str(value) for value in old_order]
    new_ids = [str(row["program_id"]) for row in qualified_new]
    overlap = sorted(set(old_ids) & set(new_ids))
    if overlap:
        raise SWEReacquisitionReviewError("old and new qualified Programs overlap")
    combined_ids = old_ids + new_ids
    if len(combined_ids) != 48 or len(set(combined_ids)) != 48:
        raise SWEReacquisitionReviewError("combined pool is not 48 independent Programs")

    ledger_payload: dict[str, object] = {
        "schema_version": "phase5.swe_historical_reacquisition_ledger.v2",
        "status": "COMPLETE_WITH_EXCLUSIONS",
        "ordered_instance_ids": ordered,
        "attempted_count": 20,
        "completed_attempt_count": 20,
        "converted_count": converted_count,
        "pre_normalization_excluded_count": 20 - converted_count,
        "q1_q9_qualified_count": qualified_count,
        "q1_q9_excluded_count": q_excluded_count,
        "automatic_retry_performed": False,
        "old_w1c_evidence_reused": False,
        "historical_w1c_hash_match_count": 0,
        "rows": ledger_rows,
    }
    ledger = _with_hash(ledger_payload, "ledger_content_sha256")

    candidate_payload: dict[str, object] = {
        "schema_version": "phase5.swe_combined_candidate_program_inventory.v2",
        "status": "MINIMUM_48_PROGRAM_CANDIDATE_POOL_READY_FOR_M4_REVIEW",
        "workload_type": "SWE_BENCH_VERIFIED_FORMAL",
        "existing_qualified_program_count": 35,
        "fresh_qualified_program_count": 13,
        "combined_independent_program_count": 48,
        "existing_qualified_programs": old_rows,
        "fresh_qualified_programs": qualified_new,
        "program_identity_order": combined_ids,
        "cross_batch_overlap": overlap,
        "fresh_provenance_verified": True,
        "historical_w1c_hash_match_count": 0,
        "selection_inputs": [
            "frozen_sampling_frame_order",
            "Q1_Q9_qualification",
            "program_identity",
        ],
        "outcome_metrics_used": False,
        "calibration_groups_constructed": False,
        "formal_groups_constructed": False,
        "workload_seal_issued": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    candidates = _with_hash(
        candidate_payload, "candidate_inventory_content_sha256"
    )

    q_failures = Counter(
        reason
        for row in qualification_rows
        if row["qualification_status"] == "EXCLUDED"
        for reason in row.get("failed_rules", [])
    )
    summary_payload: dict[str, object] = {
        "schema_version": "phase5.swe_historical_reacquisition_review.v2",
        "status": "MINIMUM_DATASET_GATE_PASS_PENDING_M4_COHORT_REVIEW",
        "attempted_count": 20,
        "completed_attempt_count": 20,
        "converted_count": 17,
        "pre_normalization_excluded_count": 3,
        "fresh_q1_q9_qualified_count": 13,
        "fresh_q1_q9_excluded_count": 4,
        "fresh_q1_q9_rule_failure_counts": dict(sorted(q_failures.items())),
        "existing_qualified_program_count": 35,
        "combined_independent_program_count": 48,
        "minimum_required_program_count": 48,
        "minimum_dataset_gate": "PASS",
        "fresh_provenance_gate": "PASS",
        "historical_w1c_hash_match_count": 0,
        "input_bindings": dict(sorted(input_bindings.items())),
        "ledger_content_sha256": ledger["ledger_content_sha256"],
        "candidate_inventory_content_sha256": candidates[
            "candidate_inventory_content_sha256"
        ],
        "m4_independent_review_required": True,
        "calibration_groups_constructed": False,
        "formal_groups_constructed": False,
        "workload_seal_issued": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    summary = _with_hash(summary_payload, "review_content_sha256")
    validate_swe_reacquisition_review(ledger, candidates, summary)
    return ledger, candidates, summary


def validate_swe_reacquisition_review(
    ledger: Mapping[str, Any],
    candidates: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    """Validate hashes, counts, identities, and authorization boundaries."""

    for payload, field in (
        (ledger, "ledger_content_sha256"),
        (candidates, "candidate_inventory_content_sha256"),
        (summary, "review_content_sha256"),
    ):
        content = dict(payload)
        observed = content.pop(field, None)
        if observed != canonical_sha256(content):
            raise SWEReacquisitionReviewError(f"{field} mismatch")
    if ledger.get("q1_q9_qualified_count") != 13:
        raise SWEReacquisitionReviewError("fresh qualified count must be 13")
    identities = candidates.get("program_identity_order")
    if not isinstance(identities, list) or len(identities) != 48:
        raise SWEReacquisitionReviewError("combined Program inventory must contain 48")
    if len(set(identities)) != 48:
        raise SWEReacquisitionReviewError("combined Program identities are not unique")
    if summary.get("minimum_dataset_gate") != "PASS":
        raise SWEReacquisitionReviewError("minimum dataset gate must pass")
    if summary.get("fresh_provenance_gate") != "PASS":
        raise SWEReacquisitionReviewError("fresh provenance gate must pass")
    if ledger.get("historical_w1c_hash_match_count") != 0:
        raise SWEReacquisitionReviewError("historical W1-C hash reuse detected")
    if any(
        value is not False
        for value in (
            candidates.get("calibration_groups_constructed"),
            candidates.get("formal_groups_constructed"),
            candidates.get("workload_seal_issued"),
            candidates.get("formal_cohort_selected"),
            candidates.get("gpu_execution_authorized"),
            summary.get("calibration_groups_constructed"),
            summary.get("formal_groups_constructed"),
            summary.get("workload_seal_issued"),
            summary.get("formal_cohort_selected"),
            summary.get("gpu_execution_authorized"),
        )
    ):
        raise SWEReacquisitionReviewError("review package exceeds authorization")
