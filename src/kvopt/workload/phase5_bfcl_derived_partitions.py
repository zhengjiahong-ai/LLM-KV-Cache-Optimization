"""Frozen 4+8 partitions for the BFCL derived supplementary workload."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .phase5_bfcl_derived import BFCLDerivedError
from .phase5_replay import canonical_sha256

CALIBRATION_GROUP_IDS = (
    "BFCL_DERIVED_G02",
    "BFCL_DERIVED_G10",
    "BFCL_DERIVED_G14",
    "BFCL_DERIVED_G19",
)
EVALUATION_GROUP_IDS = (
    "BFCL_DERIVED_G04",
    "BFCL_DERIVED_G05",
    "BFCL_DERIVED_G12",
    "BFCL_DERIVED_G13",
    "BFCL_DERIVED_G16",
    "BFCL_DERIVED_G17",
    "BFCL_DERIVED_G21",
    "BFCL_DERIVED_G22",
)


def _partition_manifest(
    *,
    role: str,
    group_ids: Sequence[str],
    groups_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    groups = []
    for partition_ordinal, group_id in enumerate(group_ids, start=1):
        group = groups_by_id[group_id]
        if group.get("status") != "CANDIDATE_GROUP_ANALYSIS_CHECKS_PASS":
            raise BFCLDerivedError(f"frozen {role} Group is not analysis-check eligible")
        programs = group.get("programs")
        if not isinstance(programs, list) or len(programs) != 4:
            raise BFCLDerivedError(f"frozen {role} Group is not four-Program complete")
        group_row = {
            "partition_ordinal": partition_ordinal,
            "group_id": group_id,
            "parent_candidate_group_content_sha256": group[
                "candidate_group_content_sha256"
            ],
            "program_identity_order": group["program_identity_order"],
            "source_question_order": group["source_question_order"],
            "programs": programs,
        }
        groups.append(
            {
                **group_row,
                "child_group_content_sha256": canonical_sha256(group_row),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_child_partition_manifest.v1",
        "status": "FROZEN_M1_SCOPE_AMENDMENT_2026_11_24",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "partition_role": role,
        "group_count": len(groups),
        "program_count": 4 * len(groups),
        "group_id_order": list(group_ids),
        "groups": groups,
        "paired_alternatives_are_independent_programs": False,
        "formal_q1_q9_status": "NOT_EVALUATED",
        "gpu_execution_authorized": False,
    }
    return {**payload, "partition_content_sha256": canonical_sha256(payload)}


def build_bfcl_derived_supplement_partitions(
    *,
    parent_group_manifest: Mapping[str, Any],
    parent_group_seal: Mapping[str, Any],
    parent_paired_ledger: Mapping[str, Any],
    parent_sha256_manifest: Mapping[str, Any],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    """Build the M1-frozen 4 Calibration + 8 Evaluation child partitions."""

    if parent_group_manifest.get("workload_type") != "BFCL_DERIVED_CONTROLLED_TIMING":
        raise BFCLDerivedError("parent inventory has the wrong workload identity")
    if parent_group_manifest.get("candidate_group_count") != 22:
        raise BFCLDerivedError("parent candidate Group inventory is incomplete")
    if parent_group_seal.get("group_manifest_content_sha256") != parent_group_manifest.get(
        "group_manifest_content_sha256"
    ):
        raise BFCLDerivedError("parent Group Seal does not bind the inventory")
    if parent_group_seal.get("paired_ledger_content_sha256") != parent_paired_ledger.get(
        "paired_ledger_content_sha256"
    ):
        raise BFCLDerivedError("parent Group Seal does not bind the paired-mode ledger")
    groups = parent_group_manifest.get("candidate_groups")
    if not isinstance(groups, list):
        raise BFCLDerivedError("parent candidate Groups are missing")
    groups_by_id = {str(group["group_id"]): group for group in groups}
    if len(groups_by_id) != 22:
        raise BFCLDerivedError("parent candidate Group IDs are not unique")
    frozen_ids = set(CALIBRATION_GROUP_IDS) | set(EVALUATION_GROUP_IDS)
    if len(frozen_ids) != 12:
        raise BFCLDerivedError("frozen child partitions overlap by Group identity")
    eligible_ids = {
        group_id
        for group_id, group in groups_by_id.items()
        if group.get("status") == "CANDIDATE_GROUP_ANALYSIS_CHECKS_PASS"
    }
    if frozen_ids != eligible_ids:
        raise BFCLDerivedError("frozen partition is not the exact eligible Group set")

    calibration = _partition_manifest(
        role="DERIVED_CALIBRATION_DESCRIPTIVE",
        group_ids=CALIBRATION_GROUP_IDS,
        groups_by_id=groups_by_id,
    )
    evaluation = _partition_manifest(
        role="DERIVED_EVALUATION_EXPLORATORY",
        group_ids=EVALUATION_GROUP_IDS,
        groups_by_id=groups_by_id,
    )
    selected_groups = calibration["groups"] + evaluation["groups"]
    program_ids = [
        program_id
        for group in selected_groups
        for program_id in group["program_identity_order"]
    ]
    session_ids = [
        program["primary_session"]["archive_record_id"]
        for group in selected_groups
        for program in group["programs"]
    ]
    pair_rows = {
        row["program_identity"]: row
        for row in parent_paired_ledger["program_mode_assignments"]
    }
    child_pairs = []
    for group in selected_groups:
        for program in group["programs"]:
            pair = pair_rows.get(program["program_identity"])
            if pair is None:
                raise BFCLDerivedError("selected Program lacks parent paired-mode lineage")
            child_pairs.append(
                {
                    "group_id": group["group_id"],
                    "partition_role": (
                        "DERIVED_CALIBRATION_DESCRIPTIVE"
                        if group["group_id"] in CALIBRATION_GROUP_IDS
                        else "DERIVED_EVALUATION_EXPLORATORY"
                    ),
                    **pair,
                }
            )
    pair_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_child_paired_mode_ledger.v1",
        "pairing_semantics": "WITHIN_PROGRAM_NOT_INDEPENDENT_PROGRAMS",
        "selected_program_count": len(child_pairs),
        "program_mode_assignments": child_pairs,
    }
    paired_ledger = {
        **pair_payload,
        "paired_ledger_content_sha256": canonical_sha256(pair_payload),
    }
    checks = {
        "EXACT_CALIBRATION_GROUP_IDS": calibration["group_id_order"]
        == list(CALIBRATION_GROUP_IDS),
        "EXACT_EVALUATION_GROUP_IDS": evaluation["group_id_order"]
        == list(EVALUATION_GROUP_IDS),
        "GROUPS_DISJOINT": set(calibration["group_id_order"]).isdisjoint(
            evaluation["group_id_order"]
        ),
        "PROGRAMS_DISJOINT": len(program_ids) == 48 == len(set(program_ids)),
        "PRIMARY_SESSIONS_DISJOINT": len(session_ids) == 48 == len(set(session_ids)),
        "PAIRED_ALTERNATIVES_NOT_COUNTED_AS_PROGRAMS": all(
            row["independent_program_count"] == 1 for row in child_pairs
        ),
        "ALL_ELIGIBLE_GROUPS_SELECTED_WITHOUT_SUBSTITUTION": frozen_ids == eligible_ids,
        "SYNTHETIC_TIMING_PRESERVED": all(
            program["primary_session"]["synthetic_tool_gap_schedule_sha256"]
            for group in selected_groups
            for program in group["programs"]
        ),
    }
    audit_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_child_partition_audit.v1",
        "status": "PASS" if all(checks.values()) else "FAIL_CLOSED",
        "checks": checks,
        "calibration_group_count": 4,
        "evaluation_group_count": 8,
        "selected_program_count": len(program_ids),
        "selected_primary_session_count": len(session_ids),
        "unselected_unqualified_group_ids": sorted(set(groups_by_id) - frozen_ids),
        "member_substitution_performed": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    audit = {**audit_payload, "audit_content_sha256": canonical_sha256(audit_payload)}
    seal_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_supplement_seal.v1",
        "status": "READY_FOR_M4_INDEPENDENT_PARTITION_REVIEW",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "parent_group_manifest_content_sha256": parent_group_manifest[
            "group_manifest_content_sha256"
        ],
        "parent_group_preparation_seal_content_sha256": parent_group_seal[
            "seal_content_sha256"
        ],
        "parent_paired_ledger_content_sha256": parent_paired_ledger[
            "paired_ledger_content_sha256"
        ],
        "parent_sha256_manifest_canonical_sha256": canonical_sha256(
            parent_sha256_manifest
        ),
        "calibration_partition_content_sha256": calibration["partition_content_sha256"],
        "evaluation_partition_content_sha256": evaluation["partition_content_sha256"],
        "child_paired_ledger_content_sha256": paired_ledger[
            "paired_ledger_content_sha256"
        ],
        "partition_audit_content_sha256": audit["audit_content_sha256"],
        "source_terminal_semantics": "SOURCE_TERMINAL_UNKNOWN",
        "replay_terminal_semantics": "REPLAY_TRACE_EXHAUSTED",
        "synthetic_tool_gap_semantics": "DETERMINISTIC_CONSTANT_1S_V1",
        "formal_q1_q9_status": "NOT_EVALUATED",
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    seal = {**seal_payload, "seal_content_sha256": canonical_sha256(seal_payload)}
    validate_bfcl_derived_supplement_partitions(
        calibration, evaluation, paired_ledger, audit, seal
    )
    return calibration, evaluation, paired_ledger, audit, seal


def validate_bfcl_derived_supplement_partitions(
    calibration: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    paired_ledger: Mapping[str, Any],
    audit: Mapping[str, Any],
    seal: Mapping[str, Any],
) -> None:
    """Fail closed on partition identity, overlap, hash, or claim drift."""

    for payload, hash_name in (
        (calibration, "partition_content_sha256"),
        (evaluation, "partition_content_sha256"),
        (paired_ledger, "paired_ledger_content_sha256"),
        (audit, "audit_content_sha256"),
        (seal, "seal_content_sha256"),
    ):
        content = dict(payload)
        observed = content.pop(hash_name, None)
        if observed != canonical_sha256(content):
            raise BFCLDerivedError(f"BFCL child {hash_name} mismatch")
    if calibration.get("group_id_order") != list(CALIBRATION_GROUP_IDS):
        raise BFCLDerivedError("Calibration child Group IDs drifted")
    if evaluation.get("group_id_order") != list(EVALUATION_GROUP_IDS):
        raise BFCLDerivedError("Evaluation child Group IDs drifted")
    if calibration.get("program_count") != 16 or evaluation.get("program_count") != 32:
        raise BFCLDerivedError("BFCL child Program counts drifted")
    if audit.get("status") != "PASS" or not all(audit.get("checks", {}).values()):
        raise BFCLDerivedError("BFCL child partition audit failed")
    if paired_ledger.get("selected_program_count") != 48:
        raise BFCLDerivedError("BFCL child paired-mode ledger is incomplete")
    if any(
        seal.get(name) is not False
        for name in ("formal_cohort_selected", "gpu_execution_authorized")
    ):
        raise BFCLDerivedError("BFCL child package exceeds authorization")
