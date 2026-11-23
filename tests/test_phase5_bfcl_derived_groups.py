from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_bfcl_derived import BFCLDerivedError
from kvopt.workload.phase5_bfcl_derived_groups import (
    build_bfcl_derived_candidate_groups,
    validate_bfcl_derived_candidate_groups,
)


def _membership() -> tuple[dict[str, object], dict[str, int]]:
    clusters = []
    sessions = []
    counts = {}
    for index in range(88):
        both = index < 71
        modes = ["NO_SNIPPET", "SNIPPET"] if both else ["SNIPPET"]
        record_ids = []
        for mode in modes:
            record_id = (
                f"web_search_no_snippet_{index}"
                if mode == "NO_SNIPPET"
                else f"web_search_base_{index}"
            )
            record_ids.append(record_id)
            sessions.append(
                {
                    "archive_record_id": record_id,
                    "phase5_case_id": f"case:{record_id}",
                    "derived_session_sha256": "a" * 64,
                    "synthetic_tool_gap_schedule_sha256": "b" * 64,
                }
            )
            counts[record_id] = 3 if index == 5 and mode == "NO_SNIPPET" else 4
        clusters.append(
            {
                "source_question_id": f"web_search_{index}",
                "program_identity": f"bfcl_derived_program_{index:03d}",
                "eligible_modes": modes,
                "eligible_archive_record_ids": record_ids,
                "independent_program_count": 1,
            }
        )
    return {
        "status": "READY_FOR_M4_INDEPENDENT_REVIEW",
        "source_question_clusters": clusters,
        "session_membership": sessions,
    }, counts


def test_grouping_is_ordered_disjoint_alternating_and_does_not_substitute() -> None:
    membership, counts = _membership()
    groups, pairs, audit, summary = build_bfcl_derived_candidate_groups(
        membership=membership,
        session_request_count=counts,
    )
    validate_bfcl_derived_candidate_groups(groups, pairs, audit, summary)
    assert groups["candidate_group_count"] == 22
    assert groups["candidate_groups"][0]["source_question_order"] == [
        "web_search_0",
        "web_search_1",
        "web_search_2",
        "web_search_3",
    ]
    assert [row["primary_mode"] for row in pairs["program_mode_assignments"][:4]] == [
        "SNIPPET",
        "NO_SNIPPET",
        "SNIPPET",
        "NO_SNIPPET",
    ]
    assert groups["candidate_groups"][1]["status"] == ("CANDIDATE_GROUP_UNQUALIFIED_MIN_TURNS")
    assert groups["candidate_groups"][1]["member_substitution_performed"] is False
    assert summary["primary_session_below_minimum_turn_count"] == 1
    assert summary["unqualified_minimum_turn_group_count"] == 1
    assert groups["formal_cohort_selected"] is False
    assert groups["gpu_execution_authorized"] is False


def test_group_validator_rejects_program_overlap_and_hash_tamper() -> None:
    membership, counts = _membership()
    groups, pairs, audit, summary = build_bfcl_derived_candidate_groups(
        membership=membership,
        session_request_count=counts,
    )
    tampered = deepcopy(groups)
    tampered["candidate_groups"][1]["program_identity_order"][0] = tampered["candidate_groups"][0][
        "program_identity_order"
    ][0]
    with pytest.raises(BFCLDerivedError, match="mismatch"):
        validate_bfcl_derived_candidate_groups(tampered, pairs, audit, summary)


def test_group_builder_rejects_incomplete_session_evidence() -> None:
    membership, counts = _membership()
    counts.pop(next(iter(counts)))
    with pytest.raises(BFCLDerivedError, match="exact eligible Sessions"):
        build_bfcl_derived_candidate_groups(
            membership=membership,
            session_request_count=counts,
        )
