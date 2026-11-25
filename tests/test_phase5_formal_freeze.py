from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_campaign_plan import (
    balanced_latin_square,
    materialize_campaign_plan,
)
from kvopt.workload.phase5_formal_freeze import (
    FormalFreezeError,
    build_formal_freeze_candidate,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _digest(character: str) -> str:
    return character * 64


def _plan(phase: str, count: int, repeats: int, prefix: str):
    groups = {"SWE_BENCH": [f"{prefix}s{index}" for index in range(count)]}
    square = balanced_latin_square()
    orders = {}
    ordinal = 0
    for stratum, group_ids in groups.items():
        for group_id in group_ids:
            for repeat in range(1, repeats + 1):
                orders[f"{stratum}:{group_id}:r{repeat}"] = square[
                    ordinal % len(square)
                ]
                ordinal += 1
    all_groups = [group_id for values in groups.values() for group_id in values]
    return materialize_campaign_plan(
        phase=phase,
        groups=groups,
        repeats=repeats,
        execution_orders=orders,
        workload_seal_sha256_by_group={row: _digest("a") for row in all_groups},
        arrival_sha256_by_group={row: _digest("b") for row in all_groups},
        protocol_sha256=_digest("c"),
    )


def _analysis(count: int = 8):
    payload = {
        "schema_version": "phase5.calibration_analysis.v2",
        "status": "CALIBRATION_ANALYZED_EXECUTION_NOT_AUTHORIZED",
        "matrix_sha256": _digest("d"),
        "variance_model": {},
        "sample_size": {
            "distribution": "NONCENTRAL_T_ITERATIVE",
            "selected_groups_per_stratum": {
                "SWE_BENCH": count,
            },
        },
        "candidate_contrasts": [],
        "formal_execution_authorized": False,
    }
    return {**payload, "analysis_sha256": canonical_sha256(payload)}


def test_calibration_binds_exact_formal_plan_without_authorizing_execution() -> None:
    report = build_formal_freeze_candidate(
        calibration_plan=_plan("CALIBRATION", 4, 3, "cal-"),
        calibration_analysis=_analysis(),
        calibration_evidence_archive_sha256=_digest("e"),
        formal_plan=_plan("FORMAL", 8, 2, "formal-"),
        code_commit="f" * 40,
    )
    assert report["status"] == "READY_FOR_M1_EXECUTION_AUTHORIZATION"
    assert report["execution_authorized"] is False
    assert report["selected_groups_per_stratum"] == {
        "SWE_BENCH": 8,
    }


def test_formal_group_count_must_equal_calibration_selection() -> None:
    with pytest.raises(FormalFreezeError, match="Group counts"):
        build_formal_freeze_candidate(
            calibration_plan=_plan("CALIBRATION", 4, 3, "cal-"),
            calibration_analysis=_analysis(12),
            calibration_evidence_archive_sha256=_digest("e"),
            formal_plan=_plan("FORMAL", 8, 2, "formal-"),
            code_commit="f" * 40,
        )


def test_changed_calibration_analysis_hash_fails_closed() -> None:
    analysis = deepcopy(_analysis())
    analysis["sample_size"]["selected_groups_per_stratum"]["SWE_BENCH"] = 9
    with pytest.raises(FormalFreezeError, match="SHA-256"):
        build_formal_freeze_candidate(
            calibration_plan=_plan("CALIBRATION", 4, 3, "cal-"),
            calibration_analysis=analysis,
            calibration_evidence_archive_sha256=_digest("e"),
            formal_plan=_plan("FORMAL", 8, 2, "formal-"),
            code_commit="f" * 40,
        )


def test_calibration_and_formal_groups_must_be_disjoint() -> None:
    calibration = _plan("CALIBRATION", 4, 3, "shared-")
    formal = _plan("FORMAL", 8, 2, "formal-")
    formal["runs"][0]["group_id"] = calibration["runs"][0]["group_id"]
    payload = dict(formal)
    payload.pop("plan_sha256")
    formal["plan_sha256"] = canonical_sha256(payload)
    with pytest.raises(ValueError, match="disjoint"):
        build_formal_freeze_candidate(
            calibration_plan=calibration,
            calibration_analysis=_analysis(),
            calibration_evidence_archive_sha256=_digest("e"),
            formal_plan=formal,
            code_commit="f" * 40,
        )
