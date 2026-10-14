import json
from pathlib import Path

from kvopt.workload.phase2e_materialize import materialize_phase2e
from kvopt.workload.phase2e_validate import validate_phase2e_campaign

DIST = Path(__file__).parents[1] / "configs" / "phase2" / "phase2e-workload-distribution-v1.json"


def test_validates_all_36_scenarios_fail_closed(tmp_path: Path) -> None:
    manifest = materialize_phase2e(distribution_path=DIST, output_dir=tmp_path / "campaign")

    report = validate_phase2e_campaign(manifest)

    assert report["status"] == "PASS"
    assert report["scenario_count"] == 36
    assert report["run_count"] == 144
    assert all(
        all(checks.values())
        for checks in report["scenario_checks"].values()
    )


def test_rejects_modified_materialized_config(tmp_path: Path) -> None:
    manifest_path = materialize_phase2e(
        distribution_path=DIST,
        output_dir=tmp_path / "campaign",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_path = manifest_path.parent / manifest["runs"][0]["config"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["generation"]["max_new_tokens"] = 2
    config_path.write_text(json.dumps(config), encoding="utf-8")

    try:
        validate_phase2e_campaign(manifest_path)
    except ValueError as error:
        assert "config hash mismatch" in str(error)
    else:
        raise AssertionError("modified config should fail validation")
