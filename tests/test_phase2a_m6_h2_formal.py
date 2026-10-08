import json
from pathlib import Path

from kvopt.workload.phase2_h2_formal import materialize_formal_m1


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
