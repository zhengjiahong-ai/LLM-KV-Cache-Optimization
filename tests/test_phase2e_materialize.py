import json
from collections import Counter
from pathlib import Path

from kvopt.workload.phase2e_materialize import materialize_phase2e

DIST = Path(__file__).parents[1] / "configs" / "phase2" / "phase2e-workload-distribution-v1.json"


def test_materializes_balanced_execution_locked_campaign(tmp_path: Path) -> None:
    path = materialize_phase2e(distribution_path=DIST, output_dir=tmp_path / "campaign")
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["scenario_count"] == 36
    assert manifest["planned_run_count"] == 144
    assert manifest["joint_freeze_complete"] is False
    assert manifest["measured_campaign_authorized"] is False
    assert Counter(row["family"] for row in manifest["scenarios"]) == {
        family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")
    }
    for scenario in manifest["scenarios"]:
        rows = [row for row in manifest["runs"] if row["scenario_id"] == scenario["scenario_id"]]
        assert Counter(row["baseline"] for row in rows) == {
            "native-lru": 2,
            "continuum-baseline": 2,
        }
        assert {row["repeat"] for row in rows} == {1, 2}
        configs = [
            json.loads((path.parent / row["config"]).read_text(encoding="utf-8"))
            for row in rows
        ]
        assert len({config["seed"] for config in configs}) == 1


def test_family_semantics_are_materialized_in_real_trace_inputs(tmp_path: Path) -> None:
    path = materialize_phase2e(distribution_path=DIST, output_dir=tmp_path / "campaign")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    scenarios = {row["scenario_id"]: row for row in manifest["scenarios"]}

    assert scenarios["f4-draw-01"]["shared_prefix_control"] is False
    assert scenarios["f4-draw-02"]["shared_prefix_control"] is True
    assert scenarios["f5-draw-01"]["pressure_count"] == 2
    assert min(
        scenarios["f1-draw-01"]["family_parameters"]["agent_turn_counts"].values()
    ) == 3
    assert max(
        scenarios["f2-draw-01"]["family_parameters"]["agent_turn_counts"].values()
    ) == 4
    f6_trace = json.loads(
        (path.parent / scenarios["f6-draw-01"]["trace"]).read_text(encoding="utf-8")
    )
    first_offsets = [
        row["planned_arrival_offset_seconds"]
        for row in f6_trace["requests"]
        if row["turn_index"] == 1
    ]
    assert len(set(first_offsets)) == 1
