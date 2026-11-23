from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_derived import BFCLDerivedError
from kvopt.workload.phase5_bfcl_derived_cohort import (
    build_bfcl_derived_cohort_proposal,
    validate_bfcl_derived_cohort_lineage,
    validate_bfcl_derived_cohort_proposal,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _inputs():
    accepted = [f"web_search_base_{index}" for index in range(100)] + [
        f"web_search_no_snippet_{index}" for index in range(100) if index != 51
    ]
    # Freeze the same 71/15/2/12 source-question partition as the accepted asset.
    neither = {1, 3, 14, 25, 43, 65, 70, 76, 81, 87, 90, 97}
    no_only = {33, 58}
    snippet_only = {5, 23, 24, 29, 39, 44, 50, 51, 52, 61, 69, 72, 75, 86, 88}
    excluded = []
    for index in range(100):
        if index in neither or index in no_only:
            excluded.append(f"web_search_base_{index}")
        if index in neither or index in snippet_only:
            candidate = f"web_search_no_snippet_{index}"
            if candidate in accepted:
                excluded.append(candidate)
    identities = {}
    for record_id in accepted:
        if record_id in excluded:
            continue
        mode = "no_snippet" if "no_snippet" in record_id else "snippet"
        identities[record_id] = {
            "phase5_case_id": f"case:{record_id}:{mode}",
            "derived_session_sha256": "a" * 64,
            "synthetic_tool_gap_schedule_sha256": "b" * 64,
        }
    return accepted, excluded, identities


def test_cohort_proposal_preserves_source_question_independence() -> None:
    accepted, excluded, identities = _inputs()
    membership, seal = build_bfcl_derived_cohort_proposal(
        accepted_archive_record_ids=accepted,
        context_excluded_archive_record_ids=excluded,
        session_identity_by_archive_record_id=identities,
        parent_workload_seal_content_sha256="1" * 64,
        context_budget_exclusions_file_sha256="2" * 64,
        protocol_appendix_canonical_sha256="3" * 64,
        protocol_appendix_file_sha256="4" * 64,
        context_budget_exclusions_canonical_sha256="5" * 64,
        lineage_validation_sha256="6" * 64,
    )
    validate_bfcl_derived_cohort_proposal(membership, seal)
    assert membership["derived_eligible_session_count"] == 159
    assert membership["independent_source_question_program_count"] == 88
    assert membership["maximum_disjoint_four_program_group_count"] == 22
    assert membership["mode_pattern_counts"] == {
        "BOTH": 71,
        "NEITHER": 12,
        "NO_SNIPPET_ONLY": 2,
        "SNIPPET_ONLY": 15,
    }
    assert seal["snippet_no_snippet_modes_are_independent_programs"] is False
    assert seal["formal_cohort_selected"] is False
    assert seal["gpu_execution_authorized"] is False


def test_cohort_proposal_rejects_mode_double_count_or_hash_tamper() -> None:
    accepted, excluded, identities = _inputs()
    membership, seal = build_bfcl_derived_cohort_proposal(
        accepted_archive_record_ids=accepted,
        context_excluded_archive_record_ids=excluded,
        session_identity_by_archive_record_id=identities,
        parent_workload_seal_content_sha256="1" * 64,
        context_budget_exclusions_file_sha256="2" * 64,
        protocol_appendix_canonical_sha256="3" * 64,
        protocol_appendix_file_sha256="4" * 64,
        context_budget_exclusions_canonical_sha256="5" * 64,
        lineage_validation_sha256="6" * 64,
    )
    tampered = deepcopy(seal)
    tampered["snippet_no_snippet_modes_are_independent_programs"] = True
    with pytest.raises(BFCLDerivedError, match="Seal hash mismatch"):
        validate_bfcl_derived_cohort_proposal(membership, tampered)
    bad_membership = deepcopy(membership)
    bad_membership["independent_source_question_program_count"] = 159
    with pytest.raises(BFCLDerivedError, match="membership hash mismatch"):
        validate_bfcl_derived_cohort_proposal(bad_membership, seal)


def test_lineage_validator_checks_parent_appendix_context_and_order() -> None:
    appendix_path = Path("configs/phase5/phase5-bfcl-derived-protocol-appendix-v1.json")
    appendix = json.loads(appendix_path.read_text(encoding="utf-8"))
    accepted = appendix["accepted_archive_record_ids"]
    excluded = accepted[:40]
    eligible = accepted[40:]
    exclusions = {
        "excluded_archive_record_ids": excluded,
        "formal_eligible_archive_record_ids": eligible,
    }
    parent_payload = {
        "schema_version": "phase5.bfcl_derived_workload_seal.v1",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "source_terminal_state": "SOURCE_TERMINAL_UNKNOWN",
        "replay_terminal_state": "REPLAY_TRACE_EXHAUSTED",
        "required_formal_systems": [
            "NATIVE",
            "CONTINUUM_OFFICIAL",
            "CONTINUUM_ADAPTED_A0",
            "A1_ORIGINAL",
            "A3_SUFFIX",
            "DVA_ER_V1",
        ],
        "same_synthetic_schedule_required_across_systems": True,
        "protocol_appendix_canonical_sha256": appendix["protocol_appendix_sha256"],
        "protocol_appendix_file_sha256": hashlib.sha256(appendix_path.read_bytes()).hexdigest(),
        "context_budget_exclusions_sha256": canonical_sha256(exclusions),
        "accepted_archive_record_ids": accepted,
        "context_budget_excluded_archive_record_ids": excluded,
        "formal_eligible_archive_record_ids": eligible,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    parent = {
        **parent_payload,
        "seal_content_sha256": canonical_sha256(parent_payload),
    }
    lineage = validate_bfcl_derived_cohort_lineage(
        parent_workload_seal=parent,
        parent_evidence_manifest={
            "bfcl-derived-workload-seal.json": "8" * 64,
            "context-budget-exclusions.json": "7" * 64,
        },
        parent_workload_seal_file_sha256="8" * 64,
        parent_evidence_manifest_file_sha256="9" * 64,
        context_budget_exclusions=exclusions,
        context_budget_exclusions_file_sha256="7" * 64,
        protocol_appendix=appendix,
        protocol_appendix_file_sha256=hashlib.sha256(appendix_path.read_bytes()).hexdigest(),
    )
    assert lineage["status"] == "PASS"
    tampered_parent = deepcopy(parent)
    tampered_parent["accepted_archive_record_ids"] = list(reversed(accepted))
    tampered_payload = dict(tampered_parent)
    tampered_payload.pop("seal_content_sha256")
    tampered_parent["seal_content_sha256"] = canonical_sha256(tampered_payload)
    with pytest.raises(BFCLDerivedError, match="PARENT_ACCEPTED_ORDER_MATCH"):
        validate_bfcl_derived_cohort_lineage(
            parent_workload_seal=tampered_parent,
            parent_evidence_manifest={
                "bfcl-derived-workload-seal.json": "8" * 64,
                "context-budget-exclusions.json": "7" * 64,
            },
            parent_workload_seal_file_sha256="8" * 64,
            parent_evidence_manifest_file_sha256="9" * 64,
            context_budget_exclusions=exclusions,
            context_budget_exclusions_file_sha256="7" * 64,
            protocol_appendix=appendix,
            protocol_appendix_file_sha256=hashlib.sha256(appendix_path.read_bytes()).hexdigest(),
        )
