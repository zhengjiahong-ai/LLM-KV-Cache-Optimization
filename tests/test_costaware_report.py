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
        "PRESSURE-FEASIBLE ORACLE",
        "SCENARIO CLUSTERS",
        "PAIRED COMPARISON",
        "DEGENERACY",
        "ABLATION",
        "DENOMINATOR DIAGNOSTIC",
        "LEAVE-ONE-FAMILY-OUT",
    ):
        assert heading in text
    assert "offline proxy only" in text


def test_report_separates_diagnostic_and_canonical_denominators() -> None:
    """Q9: the two tie conventions must never be merged into one field."""
    report = build_offline_report(_EXEMPLARS)
    baseline = next(
        row
        for row in report["evaluation"]["aggregates"]
        if row["rule_id"] == EXECUTED_BASELINE_RULE_ID
    )
    # The M4 diagnostic denominator answers "can the choice matter" and is
    # deliberately not named ``non_tied``.
    assert "non_tied_decisions" not in baseline
    assert baseline["loss_discriminating_decisions"] >= (
        baseline["positive_regret_decisions"]
    )
    assert baseline["positive_regret_rate"] == pytest.approx(
        baseline["positive_regret_decisions"]
        / baseline["loss_discriminating_decisions"]
    )
    # The canonical view reuses the M6 definition and is size-matched, so it can
    # never exceed the number of decisions where the sizes agree.
    assert baseline["canonical_non_tied_decisions"] <= (
        baseline["canonical_applicable_decisions"]
    )
    assert baseline["canonical_applicable_decisions"] <= baseline["decisions"]
    comparator = report["canonical_m6_comparator"]
    assert "unique" in str(comparator["tie_definition"])


def test_report_feasible_metrics_follow_the_frozen_order() -> None:
    """Q11: absolute regret and paired delta lead; normalised regret trails."""
    report = build_offline_report(_EXEMPLARS)
    for aggregate in report["pressure_feasible_oracle"]["aggregates"]:
        keys = list(aggregate)
        assert keys.index("mean_absolute_regret") < keys.index(
            "mean_paired_loss_delta_vs_baseline"
        )
        assert keys.index("mean_paired_loss_delta_vs_baseline") < keys.index(
            "better_than_baseline_decisions"
        )
        assert keys.index("better_than_baseline_decisions") < keys.index(
            "zero_regret_rate"
        )
        assert keys.index("zero_regret_rate") < keys.index(
            "mean_normalized_regret"
        )
        assert "oracle_best_rate" not in aggregate
        assert aggregate["zero_regret_rate"] == pytest.approx(
            1.0 - aggregate["positive_regret_decisions"] / aggregate["decisions"]
        )


def test_report_publishes_the_effective_cluster_sample() -> None:
    """Q10: raw rows overstate the evidence, so the cluster view is reported."""
    report = build_offline_report(_EXEMPLARS)
    clusters = report["scenario_clusters"]
    assert clusters["raw_decision_count"] == report["evaluation"][
        "evaluated_decisions"
    ]
    assert 0 < clusters["effective_cluster_count"] <= clusters[
        "raw_decision_count"
    ]
    assert len(clusters["decisions"]) == clusters["effective_cluster_count"]
    assert clusters["clusters_identical_across_seeds"] <= clusters[
        "effective_cluster_count"
    ]
    for row in clusters["decisions"]:
        assert row["seed_count"] >= 1


def test_report_publishes_the_unique_decision_pattern_count() -> None:
    """Q10 asks for the distinct decision problems, not only the cluster count."""
    report = build_offline_report(_EXEMPLARS)
    clusters = report["scenario_clusters"]
    unique = clusters["unique_decision_pattern_count"]
    assert 0 < unique <= clusters["effective_cluster_count"]
    # Every distinct pattern is listed exactly once, with its multiplicity.
    patterns = clusters["decision_patterns"]
    assert len(patterns) == unique
    assert sum(row["cluster_count"] for row in patterns) <= clusters[
        "effective_cluster_count"
    ]
    assert len({tuple(row["losses"]) for row in patterns}) == unique
    for row in clusters["decisions"]:
        assert tuple(row["decision_pattern"]) in {
            tuple(pattern["losses"]) for pattern in patterns
        }


def test_report_publishes_both_paired_views() -> None:
    """Q10: raw and cluster-level paired results must both be reported."""
    report = build_offline_report(_EXEMPLARS)
    raw = report["paired_vs_executed_baseline"]
    clustered = report["paired_vs_executed_baseline_cluster_level"]
    assert raw and clustered
    assert set(raw) == set(clustered)
    clusters = report["scenario_clusters"]
    for rule_id, stats in clustered.items():
        assert stats["shared_clusters"] <= clusters["effective_cluster_count"]
        assert (
            stats["improved"] + stats["worsened"] + stats["tied"]
            == stats["shared_clusters"]
        )
        assert raw[rule_id]["shared_decisions"] >= stats["shared_clusters"]


def test_report_surfaces_the_canonical_baseline_numbers() -> None:
    """Q9: the M6-aligned numbers have exactly one home in the report."""
    report = build_offline_report(_EXEMPLARS)
    summary = report["canonical_m6_comparator"]["baseline_canonical_summary"]
    assert summary is not None
    assert summary["rule_id"] == EXECUTED_BASELINE_RULE_ID
    assert summary["canonical_non_tied_decisions"] <= summary[
        "canonical_applicable_decisions"
    ]
    assert summary["canonical_positive_regret_decisions"] <= summary[
        "canonical_non_tied_decisions"
    ]
    # The diagnostic denominator must stay out of the canonical section.
    assert "loss_discriminating_decisions" not in summary


def test_cli_writes_a_json_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    exit_code = main(
        ["--artifact-root", str(_EXEMPLARS), "--output", str(output)]
    )
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "phase2a.m4.offline_report.v2"
    assert payload["replay_fidelity"]["release_set_match_rate"] == pytest.approx(1.0)


def test_cli_reports_a_missing_root_without_traceback(tmp_path: Path) -> None:
    exit_code = main(["--artifact-root", str(tmp_path / "missing")])
    assert exit_code == 2


def test_cli_reports_an_empty_root_without_traceback(tmp_path: Path) -> None:
    exit_code = main(["--artifact-root", str(tmp_path)])
    assert exit_code == 3
