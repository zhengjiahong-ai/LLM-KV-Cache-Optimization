import json
from pathlib import Path

from kvopt.workload.phase2_h1_materialize import materialize_h1_scenarios


def test_h1_materializer_is_deterministic_unique_and_never_executes(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    design = root / "configs/phase2/h1-independent-campaign-design.json"
    freeze = root / "configs/phase2/h1-scenario-materialization-freeze.json"

    first = materialize_h1_scenarios(design, freeze, tmp_path / "first")
    second = materialize_h1_scenarios(design, freeze, tmp_path / "second")
    first_manifest = json.loads((first.parent / "scenario-manifest.json").read_text())
    second_manifest = json.loads((second.parent / "scenario-manifest.json").read_text())

    assert first_manifest == second_manifest
    assert len(first_manifest["scenarios"]) == 42
    assert first_manifest["validation"]["family_counts"] == {
        family: 7 for family in ("F1", "F2", "F3", "F4", "F5", "F6")
    }
    assert first_manifest["validation"]["unique_structural_signature_count"] == 42
    assert first_manifest["validation"]["runtime_run_count_after_authorization"] == 126
    assert not first_manifest["scenario_outcomes_materialized"]
    assert not first_manifest["formal_h1_outcome_execution_authorized"]
    assert not first_manifest["runtime_seed_counts_as_sample"]
    assert not json.loads(first.read_text())["outcome_execution_authorized"]


def test_h1_materializer_meets_corner_quotas_and_candidate_variation(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    seal = materialize_h1_scenarios(
        root / "configs/phase2/h1-independent-campaign-design.json",
        root / "configs/phase2/h1-scenario-materialization-freeze.json",
        tmp_path / "holdout",
    )
    manifest = json.loads((seal.parent / "scenario-manifest.json").read_text())

    minimums = {
        "multi_release": 4,
        "near_horizon": 4,
        "no_return_within_trace": 3,
        "repeated_pressure": 4,
        "shared_prefix": 4,
    }
    for name, minimum in minimums.items():
        assert manifest["validation"]["corner_case_counts"][name] >= minimum
    for scenario in manifest["scenarios"]:
        assert len({row["eta"] for row in scenario["candidates"]}) >= 2
        assert len({row["queue_delay_seconds"] for row in scenario["candidates"]}) >= 2
        assert scenario["runtime_seeds"] == [101, 211, 307]


def test_v2_rematerializes_all_aligned_scenarios_under_d1(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    seal = materialize_h1_scenarios(
        root / "configs/phase2/h1-independent-campaign-design-v2.json",
        root / "configs/phase2/h1-scenario-materialization-freeze-v2.json",
        tmp_path / "holdout-v2",
    )
    manifest = json.loads((seal.parent / "scenario-manifest.json").read_text())

    assert manifest["schema_version"] == "phase2a.h1_sealed_scenario_manifest.v2"
    assert manifest["validation"]["runtime_block_alignment_tokens"] == 16
    assert manifest["validation"]["runtime_block_alignment_valid"] is True
    assert len(manifest["scenarios"]) == 42
    assert all(
        candidate["prefix_tokens"] % 16 == 0
        for scenario in manifest["scenarios"]
        for candidate in scenario["candidates"]
    )
    assert not json.loads(seal.read_text())["outcome_execution_authorized"]
