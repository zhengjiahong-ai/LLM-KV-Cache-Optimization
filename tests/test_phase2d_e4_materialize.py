import json
from pathlib import Path

from kvopt.workload.phase2d_e4_materialize import materialize_e4

FIXTURE = Path("configs/phase2/phase2d-e4-concurrency-fixture-v1.json")


def test_materializes_two_arm_true_overlap_fixture(tmp_path: Path) -> None:
    path = materialize_e4(fixture_path=FIXTURE, output_dir=tmp_path / "e4")
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["planned_run_count"] == 2
    assert manifest["true_overlap_required"] is True
    assert manifest["native_physical_victim_forced"] is False
    config = json.loads(
        (tmp_path / "e4" / "e4-concurrent-shared-release-a-repeat-1.config.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["batching"]["max_concurrent_requests"] == 2
    trace = json.loads(
        (tmp_path / "e4" / "e4-concurrent-shared-release-a-repeat-1.trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert [row["planned_arrival_offset_seconds"] for row in trace["requests"][:2]] == [0.0, 0.0]
    assert all(row["is_terminal"] for row in trace["requests"][2:])
