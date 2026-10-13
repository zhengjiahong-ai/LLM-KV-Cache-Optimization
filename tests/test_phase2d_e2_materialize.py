import json
from pathlib import Path

from kvopt.workload.phase2d_e2_materialize import materialize_e2

FIXTURE = Path("configs/phase2/phase2d-e2-shared-retention-fixture-v1.json")


def test_materializes_bounded_shared_fixture_and_negative_control(tmp_path: Path) -> None:
    manifest_path = materialize_e2(
        fixture_path=FIXTURE,
        output_dir=tmp_path / "e2",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["planned_run_count"] == 4
    assert manifest["forced_victim"] is False
    assert {row["case_id"] for row in manifest["runs"]} == {
        "e2-shared-root",
        "e2-distinct-root-control",
    }

    shared = json.loads(
        (tmp_path / "e2" / "e2-shared-root-repeat-1.config.json").read_text(encoding="utf-8")
    )
    segments = shared["backend_options"]["prefix_segments_by_request"]
    assert segments["e2-a:1"][0] == segments["e2-b:1"][0]
    assert segments["e2-a:1"][1] != segments["e2-b:1"][1]
    assert shared["cache"]["block_override"] == 33
    assert shared["phase2d_stage"]["expected_shared_protected_blocks"] == 8
    assert shared["phase2d_stage"]["forced_victim"] is None

    trace = json.loads(
        (tmp_path / "e2" / "e2-shared-root-repeat-1.trace.json").read_text(encoding="utf-8")
    )
    assert [row["is_terminal"] for row in trace["requests"]] == [
        False,
        False,
        True,
        True,
    ]
    assert trace["pressure_stages"][0]["planned_arrival_offset_seconds"] == 2.0


def test_fixture_keeps_e2_non_formal_and_without_forced_victim() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["run_kind"] == "NON_HOLDOUT_RESEARCH_PILOT"
    assert fixture["execution_authorized"] is True
    assert fixture["forced_victim_authorized_in_e2"] is False
    assert fixture["formal_campaign"] is False
    assert fixture["cost_aware_policy"] is False
