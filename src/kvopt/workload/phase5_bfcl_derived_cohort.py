"""Outcome-blind preparation of the independent BFCL derived cohort pool."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .phase5_bfcl_derived import (
    REQUIRED_FORMAL_SYSTEMS,
    BFCLDerivedError,
    validate_bfcl_derived_protocol_appendix,
    validate_bfcl_derived_workload_seal,
)
from .phase5_replay import canonical_sha256

_SHA256 = re.compile(r"[0-9a-f]{64}")


def validate_bfcl_derived_cohort_lineage(
    *,
    parent_workload_seal: Mapping[str, Any],
    parent_evidence_manifest: Mapping[str, Any],
    parent_workload_seal_file_sha256: str,
    parent_evidence_manifest_file_sha256: str,
    context_budget_exclusions: Mapping[str, Any],
    context_budget_exclusions_file_sha256: str,
    protocol_appendix: Mapping[str, Any],
    protocol_appendix_file_sha256: str,
) -> dict[str, object]:
    """Close Parent Seal -> Appendix -> Context Exclusion lineage fail-closed."""

    validate_bfcl_derived_workload_seal(parent_workload_seal)
    appendix_ids = validate_bfcl_derived_protocol_appendix(
        protocol_appendix, file_sha256=protocol_appendix_file_sha256
    )
    for value in (
        context_budget_exclusions_file_sha256,
        parent_workload_seal_file_sha256,
        parent_evidence_manifest_file_sha256,
    ):
        if _SHA256.fullmatch(value) is None:
            raise BFCLDerivedError("parent evidence file SHA-256 is invalid")
    context_canonical_sha256 = canonical_sha256(context_budget_exclusions)
    checks = {
        "PARENT_WORKLOAD_SEAL_VALID": True,
        "PARENT_APPENDIX_CANONICAL_HASH_MATCH": parent_workload_seal.get(
            "protocol_appendix_canonical_sha256"
        )
        == appendix_ids["protocol_appendix_canonical_sha256"],
        "PARENT_APPENDIX_FILE_HASH_MATCH": parent_workload_seal.get("protocol_appendix_file_sha256")
        == protocol_appendix_file_sha256,
        "PARENT_CONTEXT_CANONICAL_HASH_MATCH": parent_workload_seal.get(
            "context_budget_exclusions_sha256"
        )
        == context_canonical_sha256,
        "PARENT_MANIFEST_BINDS_WORKLOAD_SEAL_FILE": parent_evidence_manifest.get(
            "bfcl-derived-workload-seal.json"
        )
        == parent_workload_seal_file_sha256,
        "PARENT_MANIFEST_BINDS_CONTEXT_EXCLUSION_FILE": parent_evidence_manifest.get(
            "context-budget-exclusions.json"
        )
        == context_budget_exclusions_file_sha256,
        "PARENT_ACCEPTED_ORDER_MATCH": parent_workload_seal.get("accepted_archive_record_ids")
        == protocol_appendix.get("accepted_archive_record_ids"),
        "PARENT_CONTEXT_EXCLUDED_ORDER_MATCH": parent_workload_seal.get(
            "context_budget_excluded_archive_record_ids"
        )
        == context_budget_exclusions.get("excluded_archive_record_ids"),
        "PARENT_ELIGIBLE_ORDER_MATCH": parent_workload_seal.get(
            "formal_eligible_archive_record_ids"
        )
        == context_budget_exclusions.get("formal_eligible_archive_record_ids"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BFCLDerivedError("derived cohort lineage validation failed: " + ", ".join(failed))
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_cohort_lineage_validation.v1",
        "status": "PASS",
        "checks": checks,
        "parent_workload_seal_content_sha256": parent_workload_seal["seal_content_sha256"],
        "parent_workload_seal_file_sha256": parent_workload_seal_file_sha256,
        "parent_evidence_manifest_file_sha256": parent_evidence_manifest_file_sha256,
        "protocol_appendix_canonical_sha256": appendix_ids["protocol_appendix_canonical_sha256"],
        "protocol_appendix_file_sha256": protocol_appendix_file_sha256,
        "context_budget_exclusions_canonical_sha256": context_canonical_sha256,
        "context_budget_exclusions_file_sha256": context_budget_exclusions_file_sha256,
    }
    return {**payload, "lineage_validation_sha256": canonical_sha256(payload)}


def _source_question_index(archive_record_id: str) -> int:
    for prefix in ("web_search_base_", "web_search_no_snippet_"):
        if archive_record_id.startswith(prefix):
            suffix = archive_record_id.removeprefix(prefix)
            if suffix.isdigit() and 0 <= int(suffix) < 100:
                return int(suffix)
    raise BFCLDerivedError(f"unsupported BFCL archive identity: {archive_record_id}")


def _mode(archive_record_id: str) -> str:
    return "NO_SNIPPET" if archive_record_id.startswith("web_search_no_snippet_") else "SNIPPET"


def build_bfcl_derived_cohort_proposal(
    *,
    accepted_archive_record_ids: Sequence[str],
    context_excluded_archive_record_ids: Sequence[str],
    session_identity_by_archive_record_id: Mapping[str, Mapping[str, Any]],
    parent_workload_seal_content_sha256: str,
    context_budget_exclusions_file_sha256: str,
    protocol_appendix_canonical_sha256: str,
    protocol_appendix_file_sha256: str,
    context_budget_exclusions_canonical_sha256: str,
    lineage_validation_sha256: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Freeze the eligible pool without selecting Calibration or Formal Groups."""

    for value in (
        parent_workload_seal_content_sha256,
        context_budget_exclusions_file_sha256,
        protocol_appendix_canonical_sha256,
        protocol_appendix_file_sha256,
        context_budget_exclusions_canonical_sha256,
        lineage_validation_sha256,
    ):
        if _SHA256.fullmatch(value) is None:
            raise BFCLDerivedError("derived cohort input SHA-256 is invalid")
    accepted = list(accepted_archive_record_ids)
    excluded = list(context_excluded_archive_record_ids)
    if len(accepted) != 199 or len(set(accepted)) != 199:
        raise BFCLDerivedError("derived cohort accepted identity set is invalid")
    if len(excluded) != 40 or len(set(excluded)) != 40 or not set(excluded) <= set(accepted):
        raise BFCLDerivedError("derived cohort context exclusion set is invalid")
    eligible = [record_id for record_id in accepted if record_id not in set(excluded)]
    if len(eligible) != 159 or set(session_identity_by_archive_record_id) != set(eligible):
        raise BFCLDerivedError("derived cohort eligible Session coverage mismatch")

    clusters: dict[int, list[str]] = {index: [] for index in range(100)}
    session_rows = []
    for ordinal, record_id in enumerate(eligible, start=1):
        source_index = _source_question_index(record_id)
        mode = _mode(record_id)
        identity = session_identity_by_archive_record_id[record_id]
        case_id = identity.get("phase5_case_id")
        session_sha256 = identity.get("derived_session_sha256")
        schedule_sha256 = identity.get("synthetic_tool_gap_schedule_sha256")
        if (
            not isinstance(case_id, str)
            or _SHA256.fullmatch(str(session_sha256)) is None
            or _SHA256.fullmatch(str(schedule_sha256)) is None
        ):
            raise BFCLDerivedError("derived cohort Session identity is incomplete")
        clusters[source_index].append(record_id)
        session_rows.append(
            {
                "membership_ordinal": ordinal,
                "archive_record_id": record_id,
                "phase5_case_id": case_id,
                "source_question_id": f"web_search_{source_index}",
                "program_identity": f"bfcl_derived_program_{source_index:03d}",
                "mode": mode,
                "derived_session_sha256": session_sha256,
                "synthetic_tool_gap_schedule_sha256": schedule_sha256,
                "source_terminal_state": "SOURCE_TERMINAL_UNKNOWN",
                "replay_terminal_state": "REPLAY_TRACE_EXHAUSTED",
                "timing_semantics": "SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED",
                "eligibility": "DERIVED_ELIGIBLE_PENDING_INDEPENDENT_COHORT_REVIEW",
            }
        )

    cluster_rows = []
    mode_pattern_counts: Counter[str] = Counter()
    for source_index, record_ids in clusters.items():
        modes = sorted(_mode(record_id) for record_id in record_ids)
        if len(modes) != len(set(modes)) or len(modes) > 2:
            raise BFCLDerivedError("source question contains duplicate mode Sessions")
        pattern = (
            "BOTH"
            if modes == ["NO_SNIPPET", "SNIPPET"]
            else f"{modes[0]}_ONLY"
            if modes
            else "NEITHER"
        )
        mode_pattern_counts[pattern] += 1
        cluster_rows.append(
            {
                "source_question_id": f"web_search_{source_index}",
                "program_identity": f"bfcl_derived_program_{source_index:03d}",
                "eligible_modes": modes,
                "eligible_archive_record_ids": record_ids,
                "independent_program_count": 1 if modes else 0,
                "mode_relationship": "PAIRED_VARIANTS_NOT_INDEPENDENT_PROGRAMS",
                "eligibility": "ELIGIBLE_PROGRAM_CLUSTER" if modes else "NO_ELIGIBLE_SESSION",
            }
        )
    if mode_pattern_counts != Counter(
        {"BOTH": 71, "SNIPPET_ONLY": 15, "NO_SNIPPET_ONLY": 2, "NEITHER": 12}
    ):
        raise BFCLDerivedError("derived cohort source-question partition drifted")

    membership_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_cohort_membership_proposal.v1",
        "status": "READY_FOR_M4_INDEPENDENT_REVIEW",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "selection_semantics": "OUTCOME_BLIND_APPENDIX_ORDER_FILTERED_BY_CONTEXT_BUDGET_ONLY",
        "accepted_asset_session_count": 199,
        "context_excluded_session_count": 40,
        "derived_eligible_session_count": 159,
        "eligible_snippet_session_count": sum(row["mode"] == "SNIPPET" for row in session_rows),
        "eligible_no_snippet_session_count": sum(
            row["mode"] == "NO_SNIPPET" for row in session_rows
        ),
        "independent_source_question_program_count": sum(
            row["independent_program_count"] for row in cluster_rows
        ),
        "maximum_disjoint_four_program_group_count": sum(
            row["independent_program_count"] for row in cluster_rows
        )
        // 4,
        "mode_pattern_counts": dict(sorted(mode_pattern_counts.items())),
        "session_membership": session_rows,
        "source_question_clusters": cluster_rows,
        "calibration_groups_assigned": False,
        "formal_groups_assigned": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    membership = {
        **membership_payload,
        "membership_content_sha256": canonical_sha256(membership_payload),
    }
    seal_payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_cohort_preparation_seal.v1",
        "status": "PROPOSAL_FROZEN_PENDING_M4_M1_ACCEPTANCE",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "membership_content_sha256": membership["membership_content_sha256"],
        "parent_workload_seal_content_sha256": parent_workload_seal_content_sha256,
        "context_budget_exclusions_file_sha256": context_budget_exclusions_file_sha256,
        "context_budget_exclusions_canonical_sha256": (context_budget_exclusions_canonical_sha256),
        "lineage_validation_sha256": lineage_validation_sha256,
        "lineage_validation_status": "PASS",
        "protocol_appendix_canonical_sha256": protocol_appendix_canonical_sha256,
        "protocol_appendix_file_sha256": protocol_appendix_file_sha256,
        "source_question_is_independent_program_unit": True,
        "snippet_no_snippet_modes_are_independent_programs": False,
        "required_formal_systems": list(REQUIRED_FORMAL_SYSTEMS),
        "synthetic_timing_semantics": "SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED",
        "source_terminal_state": "SOURCE_TERMINAL_UNKNOWN",
        "replay_terminal_state": "REPLAY_TRACE_EXHAUSTED",
        "formal_q1_q9_status": "NOT_EVALUATED",
        "derived_q4d_status": "PASS",
        "derived_q5d_status": "PASS",
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    seal = {**seal_payload, "seal_content_sha256": canonical_sha256(seal_payload)}
    return membership, seal


def validate_bfcl_derived_cohort_proposal(
    membership: Mapping[str, object], seal: Mapping[str, object]
) -> None:
    """Fail closed on membership, independence, status or hash drift."""

    content = dict(membership)
    observed_membership_hash = content.pop("membership_content_sha256", None)
    if observed_membership_hash != canonical_sha256(content):
        raise BFCLDerivedError("derived cohort membership hash mismatch")
    if membership.get("status") != "READY_FOR_M4_INDEPENDENT_REVIEW":
        raise BFCLDerivedError("derived cohort proposal status is invalid")
    if membership.get("derived_eligible_session_count") != 159:
        raise BFCLDerivedError("derived cohort eligible count drifted")
    if membership.get("independent_source_question_program_count") != 88:
        raise BFCLDerivedError("derived cohort independent Program count drifted")
    if membership.get("formal_cohort_selected") is not False:
        raise BFCLDerivedError("derived proposal cannot select a Formal Cohort")
    if membership.get("gpu_execution_authorized") is not False:
        raise BFCLDerivedError("derived proposal cannot authorize GPU execution")
    seal_content = dict(seal)
    observed_seal_hash = seal_content.pop("seal_content_sha256", None)
    if observed_seal_hash != canonical_sha256(seal_content):
        raise BFCLDerivedError("derived cohort preparation Seal hash mismatch")
    if seal.get("membership_content_sha256") != observed_membership_hash:
        raise BFCLDerivedError("derived cohort Seal does not bind membership")
    if seal.get("snippet_no_snippet_modes_are_independent_programs") is not False:
        raise BFCLDerivedError("BFCL modes were incorrectly treated as independent Programs")
    if seal.get("formal_q1_q9_status") != "NOT_EVALUATED":
        raise BFCLDerivedError("derived cohort Seal overclaims formal Q1-Q9")
    if (
        seal.get("formal_cohort_selected") is not False
        or seal.get("gpu_execution_authorized") is not False
    ):
        raise BFCLDerivedError("derived cohort Seal exceeds authorization")
