import json
from pathlib import Path

import pytest

from kvopt.workload.phase2_h2_formal import materialize_formal_m1
from kvopt.workload.phase2_h2_formal_runner import execute_formal_m1


def test_formal_m1_matches_authorized_grid_and_execution_hashes(tmp_path: Path) -> None:
    authorization = Path(__file__).parents[1] / "configs/phase2/h2-measurement-authorization.json"
    campaign = materialize_formal_m1(authorization, tmp_path / "formal")
    manifest = json.loads(campaign.read_text())
    assert manifest["planned_run_count"] == 187
    assert len(manifest["points"]) == 17
    assert sum(len(p["runs"]) for p in manifest["points"]) == 187
    assert all(sum(r["role"] == "measured" for r in p["runs"]) == 9
               for p in manifest["points"])
    assert manifest["formal_measurement"]
    assert not manifest["formal_verdict_authorized"]


def test_formal_runner_rejects_changed_config_before_execution(tmp_path: Path) -> None:
    authorization = Path(__file__).parents[1] / "configs/phase2/h2-measurement-authorization.json"
    campaign = materialize_formal_m1(authorization, tmp_path / "formal")
    config_path = campaign.parent / "r16.config.json"
    config = json.loads(config_path.read_text())
    config["generation"]["max_new_tokens"] = 2
    config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="differs from authorization"):
        execute_formal_m1(campaign, authorization, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_formal_runner_rejects_changed_trace_before_execution(tmp_path: Path) -> None:
    authorization = Path(__file__).parents[1] / "configs/phase2/h2-measurement-authorization.json"
    campaign = materialize_formal_m1(authorization, tmp_path / "formal")
    trace_path = campaign.parent / "r16.trace.json"
    trace_path.write_text(trace_path.read_text() + " ")
    with pytest.raises(ValueError, match="trace hash mismatch"):
        execute_formal_m1(campaign, authorization, tmp_path / "runs")
