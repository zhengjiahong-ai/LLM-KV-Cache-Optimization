import json
from pathlib import Path

from kvopt.workload.phase2c_native_pilot_materialize import materialize_pilot

ROOT = Path("configs/phase2")


def test_materializer_writes_frozen_bounded_matrix(tmp_path: Path) -> None:
    manifest_path = materialize_pilot(
        authorization_path=ROOT / "phase2c-native-pilot-authorization.json",
        contract_path=ROOT / "phase2c-native-pilot-contract-v1.json",
        cases_path=ROOT / "phase2c-native-pilot-cases-v1.json",
        output_dir=tmp_path / "pilot",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["planned_run_count"] == 18
    assert manifest["execution_started"] is False
    assert manifest["formal_campaign_authorized"] is False
    assert {row["topology"] for row in manifest["runs"]} == {
        "W-COLD",
        "W-EXACT",
        "W-XPROGRAM",
        "W-ROOT-FORK",
        "W-NESTED",
        "W-TURN-GROW",
        "W-HOT-COLD",
        "W-PRESSURE",
    }

    grow_config = json.loads(
        (tmp_path / "pilot" / "w-turn-grow-repeat-1.config.json").read_text(
            encoding="utf-8"
        )
    )
    segments = grow_config["backend_options"]["prefix_segments_by_request"]
    assert sum(value[1] for value in segments["grow:1"]) == 160
    assert sum(value[1] for value in segments["grow:2"]) == 192
    assert sum(value[1] for value in segments["grow:3"]) == 224

    pressure = json.loads(
        (tmp_path / "pilot" / "w-pressure-native-repeat-1.trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(pressure["pressure_stages"]) == 1
