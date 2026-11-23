from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_bfcl_derived import BFCLDerivedError
from kvopt.workload.phase5_bfcl_derived_cohort import (
    build_bfcl_derived_cohort_proposal,
    validate_bfcl_derived_cohort_proposal,
)


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
    )
    tampered = deepcopy(seal)
    tampered["snippet_no_snippet_modes_are_independent_programs"] = True
    with pytest.raises(BFCLDerivedError, match="Seal hash mismatch"):
        validate_bfcl_derived_cohort_proposal(membership, tampered)
    bad_membership = deepcopy(membership)
    bad_membership["independent_source_question_program_count"] = 159
    with pytest.raises(BFCLDerivedError, match="membership hash mismatch"):
        validate_bfcl_derived_cohort_proposal(bad_membership, seal)
