"""Tests for the reproducible M4 offline report and its CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.costaware.cli import main
from kvopt.costaware.report import (
    EXECUTED_BASELINE_RULE_ID,
    build_offline_report,
    render_text,
)

_EXEMPLARS = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "experiments"
    / "phase2a-m6-formal"
    / "curated-evidence"
    / "exemplars"
)


def test_report_carries_faithful_replay_fidelity() -> None:
    """No regret number is trustworthy unless fidelity is exact."""
    report = build_offline_report(_EXEMPLARS)
    fidelity = report["replay_fidelity"]
    assert fidelity["decisions_compared"] == 3
    assert fidelity["release_set_match_rate"] == pytest.approx(1.0)
    assert fidelity["release_sequence_match_rate"] == pytest.approx(1.0)
    assert fidelity["initial_reclaimable_match_rate"] == pytest.approx(1.0)
    assert fidelity["initial_reclaimable_fields_compared"] == 11


def test_report_reports_release_burden_against_the_observed_baseline() -> None:
    report = build_offline_report(_EXEMPLARS)
    burden = {
        row["rule_id"]: row for row in report["evaluation"]["release_burden"]
    }
    baseline = burden[EXECUTED_BASELINE_RULE_ID]
    assert baseline["mean_releases_vs_baseline"] == pytest.approx(0.0)
    assert baseline["frugal_decisions"] == 0
    assert baseline["saturated_decisions"] == 0
    assert baseline["unsatisfied_decisions"] == 0


def test_report_declares_its_evidence_level() -> None:
    report = build_offline_report(_EXEMPLARS)
    assert "proxy" in str(report["evidence_level"])
    assert report["formal_campaign"] is False


def test_report_records_seeds_so_missing_seeds_are_visible() -> None:
    """Only seed 101 is in-repo; the report must not imply full seed coverage."""
    report = build_offline_report(_EXEMPLARS)
    assert report["inputs"]["seeds"] == [101]
    assert report["inputs"]["scenario_families"] == ["F1", "F4", "F6"]


def test_report_restricting_rules_narrows_the_study() -> None:
    report = build_offline_report(
        _EXEMPLARS, rule_ids=["M0_p1b_executed_ordering", "M2_non_code_first"]
    )
    ids = {row["rule_id"] for row in report["evaluation"]["aggregates"]}
    assert ids == {"M0_p1b_executed_ordering", "M2_non_code_first"}


def test_report_rejects_a_missing_artifact_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="artifact root does not exist"):
        build_offline_report(tmp_path / "nope")


def test_report_rejects_an_empty_artifact_root(tmp_path: Path) -> None:
    """An empty root is rejected by the artifact pipeline, not silently."""
    with pytest.raises(ValueError, match="no run.json files found"):
        build_offline_report(tmp_path)


def test_render_text_includes_every_section() -> None:
    text = render_text(build_offline_report(_EXEMPLARS))
    for heading in (
        "REPLAY FIDELITY",
        "EVALUATION",
        "RELEASE BURDEN",
        "PAIRED COMPARISON",
        "DEGENERACY",
        "ABLATION",
        "DENOMINATOR DIAGNOSTIC",
        "LEAVE-ONE-FAMILY-OUT",
    ):
        assert heading in text
    assert "offline proxy only" in text


def test_cli_writes_a_json_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    exit_code = main(
        ["--artifact-root", str(_EXEMPLARS), "--output", str(output)]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "phase2a.m4.offline_report.v1"
    assert payload["replay_fidelity"]["release_set_match_rate"] == pytest.approx(1.0)


def test_cli_reports_a_missing_root_without_traceback(tmp_path: Path) -> None:
    exit_code = main(["--artifact-root", str(tmp_path / "missing")])
    assert exit_code == 2


def test_cli_reports_an_empty_root_without_traceback(tmp_path: Path) -> None:
    exit_code = main(["--artifact-root", str(tmp_path)])
    assert exit_code == 3
