import json
from pathlib import Path

from kvopt.workload.phase2d_e3_materialize import materialize_e3

FIXTURE = Path("configs/phase2/phase2d-e3-paired-headroom-fixture-v1.json")


def test_materializes_balanced_paired_diagnostic_fixture(tmp_path: Path) -> None:
    manifest_path = materialize_e3(fixture_path=FIXTURE, output_dir=tmp_path / "e3")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["planned_run_count"] == 8
    assert manifest["native_physical_victim_forced"] is False
    assert {row["arm"] for row in manifest["runs"]} == {"release-a", "release-b"}
    assert len({row["config_sha256"] for row in manifest["runs"]}) == 8

    config = json.loads(
        (tmp_path / "e3" / "e3-single-return-headroom-release-b-repeat-1.config.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["backend_options"]["phase2d_diagnostic_first_release_program_id"] == "e3-b"
    assert config["cache"]["block_override"] == 33
    assert config["phase2d_stage"]["return_programs"] == ["e3-a"]
    segments = config["backend_options"]["prefix_segments_by_request"]
    assert segments["e3-a:1"][0] == segments["e3-b:1"][0]
    assert segments["e3-a:1"][1] != segments["e3-b:1"][1]


def test_fixture_keeps_e3_non_formal_and_diagnostic_only() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["run_kind"] == "NON_HOLDOUT_RESEARCH_PILOT"
    assert fixture["forced_first_logical_release_authorized"] is True
    assert fixture["formal_campaign"] is False
    assert fixture["cost_aware_policy"] is False
