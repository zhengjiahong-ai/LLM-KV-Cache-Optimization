from __future__ import annotations

import copy

import pytest

from kvopt.workload.phase5_calibration import SYSTEM_IDS, analyze_calibration


def _records(value_step: int = 10):
    rows = []
    for stratum_index, stratum in enumerate(("SWE_BENCH", "BFCL_WEB_SEARCH")):
        for group_index in range(1, 5):
            for system_index, system_id in enumerate(SYSTEM_IDS):
                for repeat_index in range(1, 4):
                    rows.append(
                        {
                            "status": "PASS",
                            "stratum": stratum,
                            "group_id": f"{stratum_index}-{group_index}",
                            "system_id": system_id,
                            "repeat_index": repeat_index,
                            "formal_group": False,
                            "recomputed_tokens_E_minus_C": (
                                4000
                                + group_index * 100
                                + system_index * value_step
                                + repeat_index * value_step
                            ),
                        }
                    )
    return rows


def test_exact_96_run_calibration_and_sample_size() -> None:
    report = analyze_calibration(_records())
    assert report["record_count"] == 96
    assert report["formal_execution_authorized"] is False
    assert report["calibration_reused_as_formal_evidence"] is False
    for row in report["strata"].values():
        assert len(row["calibration_group_ids"]) == 4
        assert 8 <= row["selected_groups_if_authorized"] <= 16
        assert len(row["contrasts"]) == 3


def test_missing_duplicate_failed_and_formal_reuse_fail_closed() -> None:
    rows = _records()
    with pytest.raises(ValueError, match="exactly 96"):
        analyze_calibration(rows[:-1])

    duplicated = copy.deepcopy(rows)
    duplicated[-1] = copy.deepcopy(duplicated[0])
    with pytest.raises(ValueError, match="duplicate"):
        analyze_calibration(duplicated)

    failed = copy.deepcopy(rows)
    failed[0]["status"] = "FAIL_CLOSED"
    with pytest.raises(ValueError, match="non-PASS"):
        analyze_calibration(failed)

    reused = copy.deepcopy(rows)
    reused[0]["formal_group"] = True
    with pytest.raises(ValueError, match="reused"):
        analyze_calibration(reused)


def test_above_cap_requires_m1_decision_instead_of_silent_extension() -> None:
    rows = _records()
    for row in rows:
        if row["system_id"] == "COST_AWARE":
            row["recomputed_tokens_E_minus_C"] += row["repeat_index"] * 50000
    report = analyze_calibration(rows)
    assert report["status"] == "BLOCKED_REQUIRES_M1_UNDERPOWERED_DECISION"
    assert any(
        row["required_groups_unclamped"] > 16
        for row in report["strata"].values()
    )
