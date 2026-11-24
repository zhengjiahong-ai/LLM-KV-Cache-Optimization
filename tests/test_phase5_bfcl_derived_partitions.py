from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_bfcl_derived import BFCLDerivedError
from kvopt.workload.phase5_bfcl_derived_groups import (
    build_bfcl_derived_candidate_groups,
)
from kvopt.workload.phase5_bfcl_derived_partitions import (
    CALIBRATION_GROUP_IDS,
    EVALUATION_GROUP_IDS,
    build_bfcl_derived_supplement_partitions,
    validate_bfcl_derived_supplement_partitions,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _parents() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
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
            counts[record_id] = (
                3
                if index % 4 == 0
                and index // 4 + 1 in {1, 3, 6, 7, 8, 9, 11, 15, 18, 20}
                else 4
            )
        clusters.append(
            {
                "source_question_id": f"web_search_{index}",
                "program_identity": f"bfcl_derived_program_{index:03d}",
                "eligible_modes": modes,
                "eligible_archive_record_ids": record_ids,
                "independent_program_count": 1,
            }
        )
    membership = {
        "status": "READY_FOR_M4_INDEPENDENT_REVIEW",
        "source_question_clusters": clusters,
        "session_membership": sessions,
    }
    groups, pairs, _, _ = build_bfcl_derived_candidate_groups(
        membership=membership,
        session_request_count=counts,
    )
    group_seal = {
        "group_manifest_content_sha256": groups["group_manifest_content_sha256"],
        "paired_ledger_content_sha256": pairs["paired_ledger_content_sha256"],
        "seal_content_sha256": "c" * 64,
    }
    return groups, group_seal, pairs


def test_frozen_partitions_are_exact_disjoint_and_preserve_pairs() -> None:
    groups, group_seal, pairs = _parents()
    calibration, evaluation, child_pairs, audit, seal = (
        build_bfcl_derived_supplement_partitions(
            parent_group_manifest=groups,
            parent_group_seal=group_seal,
            parent_paired_ledger=pairs,
            parent_sha256_manifest={"parent": "d" * 64},
        )
    )
    validate_bfcl_derived_supplement_partitions(
        calibration, evaluation, child_pairs, audit, seal
    )
    assert calibration["group_id_order"] == list(CALIBRATION_GROUP_IDS)
    assert evaluation["group_id_order"] == list(EVALUATION_GROUP_IDS)
    assert calibration["program_count"] == 16
    assert evaluation["program_count"] == 32
    assert child_pairs["selected_program_count"] == 48
    assert audit["checks"]["PROGRAMS_DISJOINT"] is True
    assert seal["formal_cohort_selected"] is False
    assert seal["gpu_execution_authorized"] is False


def test_partition_builder_rejects_unqualified_frozen_group() -> None:
    groups, group_seal, pairs = _parents()
    groups["candidate_groups"][1]["status"] = "CANDIDATE_GROUP_UNQUALIFIED_MIN_TURNS"
    payload = dict(groups)
    payload.pop("group_manifest_content_sha256")
    groups["group_manifest_content_sha256"] = canonical_sha256(payload)
    group_seal["group_manifest_content_sha256"] = groups[
        "group_manifest_content_sha256"
    ]
    with pytest.raises(BFCLDerivedError, match="exact eligible Group set"):
        build_bfcl_derived_supplement_partitions(
            parent_group_manifest=groups,
            parent_group_seal=group_seal,
            parent_paired_ledger=pairs,
            parent_sha256_manifest={},
        )


def test_partition_validator_rejects_hash_tamper() -> None:
    groups, group_seal, pairs = _parents()
    outputs = list(
        build_bfcl_derived_supplement_partitions(
            parent_group_manifest=groups,
            parent_group_seal=group_seal,
            parent_paired_ledger=pairs,
            parent_sha256_manifest={},
        )
    )
    outputs[0] = deepcopy(outputs[0])
    outputs[0]["group_id_order"][0] = "BFCL_DERIVED_G01"
    with pytest.raises(BFCLDerivedError, match="mismatch"):
        validate_bfcl_derived_supplement_partitions(*outputs)
