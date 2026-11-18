from __future__ import annotations

import pytest

from kvopt.profiling.phase5_formal_analysis import (
    CONTRASTS,
    PRIMARY_FAMILIES,
    SYSTEM_IDS,
    analyze_phase5_formal_groups,
)


def _rows(group_count: int = 4):
    offsets = {
        "NATIVE": 8.0,
        "CONTINUUM_OFFICIAL": 7.0,
        "CONTINUUM_ADAPTED": 6.0,
        "A1_ORIGINAL": 5.0,
        "A3_SUFFIX": 4.0,
        "DVA_ER_V1": 3.0,
    }
    rows = []
    for stratum in ("SWE_BENCH", "BFCL_WEB_SEARCH"):
        for group in range(1, group_count + 1):
            for system_id in SYSTEM_IDS:
                for repeat in (1, 2):
                    rows.append(
                        {
                            "run_id": f"{stratum}:g{group}:{system_id}:r{repeat}",
                            "group_id": f"g{group}",
                            "stratum": stratum,
                            "system_id": system_id,
                            "repeat_index": repeat,
                            "status": "PASS",
                            "metric_value": 100.0 + offsets[system_id] + group + repeat,
                        }
                    )
    return rows


def test_six_system_group_pipeline_reports_eight_frozen_contrasts() -> None:
    report = analyze_phase5_formal_groups(
        _rows(), bootstrap_resamples=200, bootstrap_seed=17
    )

    assert report["status"] == "PASS"
    assert report["systems"] == list(SYSTEM_IDS)
    assert report["primary_contrasts"] == list(CONTRASTS)
    for stratum in ("SWE_BENCH", "BFCL_WEB_SEARCH"):
        result = report["strata"][stratum]
        assert result["complete_group_count"] == 4
        assert set(result["contrasts"]) == set(CONTRASTS)
        assert all(row["group_count"] == 4 for row in result["contrasts"].values())
        assert set(result["families"]) == set(PRIMARY_FAMILIES)


def test_repeat_values_are_averaged_before_paired_group_difference() -> None:
    rows = _rows(group_count=1)
    for row in rows:
        if row["stratum"] == "SWE_BENCH" and row["system_id"] == "A1_ORIGINAL":
            row["metric_value"] = 10.0 if row["repeat_index"] == 1 else 30.0
        if (
            row["stratum"] == "SWE_BENCH"
            and row["system_id"] == "CONTINUUM_ADAPTED"
        ):
            row["metric_value"] = 2.0 if row["repeat_index"] == 1 else 6.0

    report = analyze_phase5_formal_groups(rows, bootstrap_resamples=20)

    contrast = report["strata"]["SWE_BENCH"]["contrasts"]["A1_vs_A0"]
    assert contrast["mean_difference"] == 16.0


def test_missing_one_repeat_excludes_whole_group_from_every_contrast() -> None:
    rows = _rows(group_count=2)
    rows = [
        row
        for row in rows
        if not (
            row["stratum"] == "SWE_BENCH"
            and row["group_id"] == "g1"
            and row["system_id"] == "A3_SUFFIX"
            and row["repeat_index"] == 2
        )
    ]

    report = analyze_phase5_formal_groups(rows, bootstrap_resamples=20)

    swe = report["strata"]["SWE_BENCH"]
    assert swe["complete_group_count"] == 1
    assert all(row["group_ids"] == ["g2"] for row in swe["contrasts"].values())
    excluded = next(
        row
        for row in report["incomplete_groups"]
        if row["stratum"] == "SWE_BENCH" and row["group_id"] == "g1"
    )
    assert "A3_SUFFIX:repeat:2:MISSING" in excluded["reasons"]


def test_nonfinite_or_failed_metric_is_not_imputed() -> None:
    rows = _rows(group_count=1)
    target = next(
        row
        for row in rows
        if row["stratum"] == "BFCL_WEB_SEARCH"
        and row["system_id"] == "DVA_ER_V1"
        and row["repeat_index"] == 1
    )
    target["metric_value"] = float("nan")

    report = analyze_phase5_formal_groups(rows, bootstrap_resamples=20)

    assert report["strata"]["BFCL_WEB_SEARCH"]["complete_group_count"] == 0
    assert report["strata"]["BFCL_WEB_SEARCH"]["families"][
        "CANDIDATE_MECHANISM"
    ]["status"] == "NOT_EVALUABLE_INCOMPLETE_FAMILY"


def test_holm_is_applied_separately_to_each_family_and_stratum() -> None:
    report = analyze_phase5_formal_groups(
        _rows(), bootstrap_resamples=20, bootstrap_seed=99
    )

    for stratum in report["strata"].values():
        candidate = stratum["families"]["CANDIDATE_MECHANISM"]
        context = stratum["families"]["SYSTEM_CONTEXT"]
        assert len(candidate["holm_adjusted_pvalues"]) == 6
        assert len(context["holm_adjusted_pvalues"]) == 2


def test_bootstrap_is_reproducible_for_frozen_seed() -> None:
    first = analyze_phase5_formal_groups(
        _rows(), bootstrap_resamples=100, bootstrap_seed=20261201
    )
    second = analyze_phase5_formal_groups(
        _rows(), bootstrap_resamples=100, bootstrap_seed=20261201
    )

    assert first == second


def test_duplicate_run_or_cell_and_unknown_system_fail_closed() -> None:
    rows = _rows(group_count=1)
    with pytest.raises(ValueError, match="duplicate run_id"):
        analyze_phase5_formal_groups([*rows, dict(rows[0])], bootstrap_resamples=10)

    bad = [dict(row) for row in rows]
    bad[0]["run_id"] = "different-run"
    bad[0]["system_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="unknown system_id"):
        analyze_phase5_formal_groups(bad, bootstrap_resamples=10)


def test_no_complete_groups_is_explicitly_not_evaluable() -> None:
    rows = _rows(group_count=1)
    for row in rows:
        row["status"] = "INCOMPLETE"

    report = analyze_phase5_formal_groups(rows, bootstrap_resamples=10)

    assert report["status"] == "NOT_EVALUABLE_NO_COMPLETE_GROUPS"
    assert report["complete_group_count"] == 0
