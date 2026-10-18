import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a1_bounded_materialize import (
    materialize_bounded_campaign,
)
from kvopt.workload.phase2g_a1_bounded_validate import validate_bounded_campaign

DISTRIBUTION = Path("configs/phase2/phase2g-a1-bounded-distribution-v1.json")


def _campaign(tmp_path: Path) -> Path:
    return materialize_bounded_campaign(
        distribution_path=DISTRIBUTION,
        output_dir=tmp_path / "campaign",
    )


def test_validator_accepts_complete_locked_campaign(tmp_path: Path) -> None:
    report = validate_bounded_campaign(_campaign(tmp_path))

    assert report["status"] == "PASS"
    assert report["scenario_count"] == 36
    assert report["run_count"] == 144
    assert set(report["execution_order_counts"].values()) == {36}
    assert report["execution_authorized"] is False


def test_validator_rejects_config_hash_drift(tmp_path: Path) -> None:
    manifest_path = _campaign(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_path = manifest_path.parent / manifest["runs"][0]["config"]
    config_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="config hash mismatch"):
        validate_bounded_campaign(manifest_path)


def test_validator_rejects_execution_unlock(tmp_path: Path) -> None:
    manifest_path = _campaign(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution_authorized"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="execution-locked"):
        validate_bounded_campaign(manifest_path)
