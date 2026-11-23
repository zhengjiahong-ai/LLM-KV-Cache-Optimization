"""Deterministic four-Program grouping for the accepted BFCL derived pool."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .phase5_bfcl_derived import BFCLDerivedError
from .phase5_replay import canonical_sha256

_SOURCE_ID = re.compile(r"web_search_(\d{1,2})")


def _source_index(source_question_id: str) -> int:
    match = _SOURCE_ID.fullmatch(source_question_id)
    if match is None or not 0 <= int(match.group(1)) < 100:
        raise BFCLDerivedError("invalid BFCL source-question identity")
    return int(match.group(1))


def _select_record(cluster: Mapping[str, Any], mode: str) -> str:
    matches = [
        str(record_id)
        for record_id in cluster["eligible_archive_record_ids"]
        if ("no_snippet" in str(record_id)) == (mode == "NO_SNIPPET")
    ]
    if len(matches) != 1:
        raise BFCLDerivedError("BFCL mode does not map to exactly one Session")
    return matches[0]


def build_bfcl_derived_candidate_groups(
    *,
    membership: Mapping[str, Any],
    session_request_count: Mapping[str, int],
    minimum_turns_per_session: int = 4,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    """Apply the M1-frozen order/group/mode rule without replacement."""

    if membership.get("status") != "READY_FOR_M4_INDEPENDENT_REVIEW":
        raise BFCLDerivedError("candidate pool is not ready for grouping")
    clusters = membership.get("source_question_clusters")
    sessions = membership.get("session_membership")
    if not isinstance(clusters, list) or not isinstance(sessions, list):
        raise BFCLDerivedError("candidate pool lacks membership identities")
    eligible_clusters = [
        row
        for row in clusters
        if isinstance(row, dict) and row.get("independent_program_count") == 1
    ]
    eligible_clusters.sort(key=lambda row: _source_index(str(row["source_question_id"])))
    indexes = [_source_index(str(row["source_question_id"])) for row in eligible_clusters]
    if len(eligible_clusters) != 88 or len(indexes) != len(set(indexes)):
        raise BFCLDerivedError("candidate Program identity set is invalid")
    session_by_record = {
        str(row["archive_record_id"]): row for row in sessions if isinstance(row, dict)
    }
    if set(session_request_count) != set(session_by_record):
        raise BFCLDerivedError("request-count evidence does not cover exact eligible Sessions")

    both_ordinal = 0
    program_rows = []
    pair_rows = []
    for program_ordinal, cluster in enumerate(eligible_clusters, start=1):
        modes = list(cluster["eligible_modes"])
        if modes == ["NO_SNIPPET", "SNIPPET"]:
            primary_mode = "SNIPPET" if both_ordinal % 2 == 0 else "NO_SNIPPET"
            both_ordinal += 1
            alternate_mode = "NO_SNIPPET" if primary_mode == "SNIPPET" else "SNIPPET"
        elif len(modes) == 1 and modes[0] in {"SNIPPET", "NO_SNIPPET"}:
            primary_mode = modes[0]
            alternate_mode = None
        else:
            raise BFCLDerivedError("eligible Program has an invalid mode set")
        primary_id = _select_record(cluster, primary_mode)
        primary_identity = session_by_record[primary_id]
        primary_turns = session_request_count[primary_id]
        primary_check = "PASS" if primary_turns >= minimum_turns_per_session else "FAIL"
        alternate = None
        if alternate_mode is not None:
            alternate_id = _select_record(cluster, alternate_mode)
            alternate_identity = session_by_record[alternate_id]
            alternate_turns = session_request_count[alternate_id]
            alternate = {
                "mode": alternate_mode,
                "archive_record_id": alternate_id,
                "phase5_case_id": alternate_identity["phase5_case_id"],
                "derived_session_sha256": alternate_identity["derived_session_sha256"],
                "synthetic_tool_gap_schedule_sha256": alternate_identity[
                    "synthetic_tool_gap_schedule_sha256"
                ],
                "request_count": alternate_turns,
                "minimum_turns_check": (
                    "PASS" if alternate_turns >= minimum_turns_per_session else "FAIL"
                ),
                "analysis_role": "WITHIN_PROGRAM_PAIRED_MODE_ALTERNATIVE",
            }
        program = {
            "program_ordinal": program_ordinal,
            "source_question_index": _source_index(str(cluster["source_question_id"])),
            "source_question_id": cluster["source_question_id"],
            "program_identity": cluster["program_identity"],
            "primary_session": {
                "mode": primary_mode,
                "archive_record_id": primary_id,
                "phase5_case_id": primary_identity["phase5_case_id"],
                "derived_session_sha256": primary_identity["derived_session_sha256"],
                "synthetic_tool_gap_schedule_sha256": primary_identity[
                    "synthetic_tool_gap_schedule_sha256"
                ],
                "request_count": primary_turns,
                "minimum_turns_check": primary_check,
            },
            "paired_mode_alternative": alternate,
            "mode_pairing_semantics": "PAIRED_VARIANTS_NOT_INDEPENDENT_PROGRAMS",
        }
        program_rows.append(program)
        pair_rows.append(
            {
                "source_question_id": cluster["source_question_id"],
                "program_identity": cluster["program_identity"],
                "primary_mode": primary_mode,
                "primary_archive_record_id": primary_id,
                "paired_alternative": alternate,
                "independent_program_count": 1,
            }
        )

    groups = []
    for group_offset in range(0, len(program_rows), 4):
        group_programs = program_rows[group_offset : group_offset + 4]
        if len(group_programs) != 4:
            raise BFCLDerivedError("candidate Programs do not form complete groups")
        group_id = f"BFCL_DERIVED_G{group_offset // 4 + 1:02d}"
        failed = [
            row["program_identity"]
            for row in group_programs
            if row["primary_session"]["minimum_turns_check"] != "PASS"
        ]
        status = (
            "CANDIDATE_GROUP_ANALYSIS_CHECKS_PASS"
            if not failed
            else "CANDIDATE_GROUP_UNQUALIFIED_MIN_TURNS"
        )
        group_payload = {
            "group_id": group_id,
            "candidate_group_ordinal": group_offset // 4 + 1,
            "programs": group_programs,
            "program_identity_order": [row["program_identity"] for row in group_programs],
            "source_question_order": [row["source_question_id"] for row in group_programs],
            "status": status,
            "failed_minimum_turn_program_identities": failed,
            "member_substitution_performed": False,
            "calibration_group_assigned": False,
            "formal_group_assigned": False,
        }
        groups.append(
            {
                **group_payload,
                "candidate_group_content_sha256": canonical_sha256(group_payload),
            }
        )

    all_program_ids = [
        program_id for group in groups for program_id in group["program_identity_order"]
    ]
    if len(all_program_ids) != 88 or len(set(all_program_ids)) != 88:
        raise BFCLDerivedError("candidate Groups are not disjoint by Program identity")
    group_manifest_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_candidate_group_manifest.v1",
        "status": "READY_FOR_M4_GROUP_REVIEW",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "construction_rule": "ASCENDING_SOURCE_INDEX_SUCCESSIVE_GROUPS_OF_FOUR",
        "both_mode_primary_rule": "ALTERNATE_SNIPPET_NO_SNIPPET_START_SNIPPET",
        "minimum_turns_per_primary_session": minimum_turns_per_session,
        "candidate_group_count": len(groups),
        "analysis_checks_pass_group_count": sum(
            row["status"] == "CANDIDATE_GROUP_ANALYSIS_CHECKS_PASS" for row in groups
        ),
        "unqualified_minimum_turn_group_count": sum(
            row["status"] == "CANDIDATE_GROUP_UNQUALIFIED_MIN_TURNS" for row in groups
        ),
        "candidate_groups": groups,
        "calibration_groups_assigned": False,
        "formal_groups_assigned": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    group_manifest = {
        **group_manifest_payload,
        "group_manifest_content_sha256": canonical_sha256(group_manifest_payload),
    }
    paired_ledger_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_paired_mode_ledger.v1",
        "pairing_semantics": "WITHIN_PROGRAM_NOT_INDEPENDENT_PROGRAMS",
        "both_mode_program_count": both_ordinal,
        "primary_mode_counts": dict(
            sorted(Counter(row["primary_mode"] for row in pair_rows).items())
        ),
        "program_mode_assignments": pair_rows,
    }
    paired_ledger = {
        **paired_ledger_payload,
        "paired_ledger_content_sha256": canonical_sha256(paired_ledger_payload),
    }
    audit_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_group_outcome_blind_audit.v1",
        "status": "PASS",
        "checks": {
            "SOURCE_INDEX_ASCENDING": indexes == sorted(indexes),
            "SUCCESSIVE_GROUPS_OF_FOUR": True,
            "PROGRAM_IDENTITIES_DISJOINT": len(all_program_ids) == len(set(all_program_ids)),
            "BOTH_MODE_ALTERNATION_STARTS_SNIPPET": all(
                row["primary_mode"] == ("SNIPPET" if ordinal % 2 == 0 else "NO_SNIPPET")
                for ordinal, row in enumerate(
                    [row for row in pair_rows if row["paired_alternative"] is not None]
                )
            ),
            "NO_MEMBER_SUBSTITUTION": all(
                group["member_substitution_performed"] is False for group in groups
            ),
            "NO_SYSTEM_OUTCOME_INPUTS": True,
        },
        "selection_inputs": [
            "source_question_index",
            "eligible_modes",
            "frozen_membership_order",
            "minimum_turns_per_session",
        ],
        "forbidden_inputs_absent": [
            "system_outcome",
            "candidate_exposure",
            "victim_set",
            "recomputation",
            "latency",
            "throughput",
        ],
    }
    audit = {**audit_payload, "audit_content_sha256": canonical_sha256(audit_payload)}
    summary_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_group_statistics.v1",
        "candidate_program_count": 88,
        "candidate_group_count": 22,
        "analysis_checks_pass_group_count": group_manifest["analysis_checks_pass_group_count"],
        "unqualified_minimum_turn_group_count": group_manifest[
            "unqualified_minimum_turn_group_count"
        ],
        "primary_session_below_minimum_turn_count": sum(
            row["primary_session"]["minimum_turns_check"] == "FAIL" for row in program_rows
        ),
        "primary_mode_counts": paired_ledger["primary_mode_counts"],
        "both_mode_program_count": both_ordinal,
        "member_substitution_count": 0,
        "candidate_capacity_is_formal_group_count": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    summary = {**summary_payload, "summary_content_sha256": canonical_sha256(summary_payload)}
    return group_manifest, paired_ledger, audit, summary


def validate_bfcl_derived_candidate_groups(
    group_manifest: Mapping[str, Any],
    paired_ledger: Mapping[str, Any],
    audit: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    """Fail closed on group hashes, overlap, pairing or authorization drift."""

    for payload, hash_name in (
        (group_manifest, "group_manifest_content_sha256"),
        (paired_ledger, "paired_ledger_content_sha256"),
        (audit, "audit_content_sha256"),
        (summary, "summary_content_sha256"),
    ):
        content = dict(payload)
        observed = content.pop(hash_name, None)
        if observed != canonical_sha256(content):
            raise BFCLDerivedError(f"candidate Group {hash_name} mismatch")
    groups = group_manifest.get("candidate_groups")
    if not isinstance(groups, list) or len(groups) != 22:
        raise BFCLDerivedError("candidate Group inventory is incomplete")
    program_ids = [program_id for group in groups for program_id in group["program_identity_order"]]
    if len(program_ids) != 88 or len(program_ids) != len(set(program_ids)):
        raise BFCLDerivedError("candidate Group Program overlap detected")
    if paired_ledger.get("both_mode_program_count") != 71:
        raise BFCLDerivedError("paired-mode inventory drifted")
    if audit.get("status") != "PASS" or not all(audit.get("checks", {}).values()):
        raise BFCLDerivedError("outcome-blind Group audit failed")
    if summary.get("candidate_group_count") != 22:
        raise BFCLDerivedError("candidate Group statistics drifted")
    if any(
        value is not False
        for value in (
            group_manifest.get("calibration_groups_assigned"),
            group_manifest.get("formal_groups_assigned"),
            group_manifest.get("formal_cohort_selected"),
            group_manifest.get("gpu_execution_authorized"),
        )
    ):
        raise BFCLDerivedError("candidate Group package exceeds authorization")
