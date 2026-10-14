import json
from pathlib import Path

from kvopt.workload.phase2 import load_phase2_trace
from kvopt.workload.phase2e_t1_materialize import materialize_t1

FIXTURE = Path("configs/phase2/phase2e-t1-native-fidelity-smoke-v1.json")


def test_materializes_paired_non_measured_t1_smoke(tmp_path: Path) -> None:
    path = materialize_t1(fixture_path=FIXTURE, output_dir=tmp_path / "t1")
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["planned_run_count"] == 2
    assert manifest["measured_campaign"] is False
    assert manifest["joint_freeze_complete"] is False
    assert {row["baseline"] for row in manifest["runs"]} == {
        "native-lru",
        "continuum-baseline",
    }
    for row in manifest["runs"]:
        config = json.loads((path.parent / row["config"]).read_text(encoding="utf-8"))
        trace = load_phase2_trace(path.parent / row["trace"])
        assert config["policy"] == row["baseline"]
        assert config["batching"]["max_concurrent_requests"] == 2
        assert config["cache"]["block_override"] == 41
        assert [request.turn_index for request in trace.requests] == [1, 1, 2, 2]
        segments = config["backend_options"]["prefix_segments_by_request"]
        assert sum(value[1] for value in segments["t1-a:1"]) == 192
        assert sum(value[1] for value in segments["t1-a:2"]) == 256
