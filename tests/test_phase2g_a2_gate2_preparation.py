import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_gate2_materialize import materialize_gate2_campaign
from kvopt.workload.phase2g_a2_gate2_validate import validate_gate2_campaign

DISTRIBUTION = Path("configs/phase2/phase2g-a2-native-gate2-distribution-v1.json")


def _campaign(tmp_path: Path) -> Path:
    return materialize_gate2_campaign(
        distribution_path=DISTRIBUTION,
        output_dir=tmp_path / "campaign",
    )


def test_materializes_locked_36_scenario_144_run_campaign(tmp_path: Path) -> None:
    path = _campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["scenario_count"] == 36
    assert manifest["planned_run_count"] == 144
    assert manifest["execution_authorized"] is False
    assert manifest["formal_native_execution_authorized"] is False
    assert manifest["outcomes_materialized"] is False
    assert Counter(row["family"] for row in manifest["scenarios"]) == Counter(
        {family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}
    )


def test_a0_and_a2_only_change_block_selection_arm(tmp_path: Path) -> None:
    path = _campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for run in manifest["runs"]:
        grouped[str(run["scenario_id"])].append(run)

    for rows in grouped.values():
        assert Counter((row["policy"], row["repeat"]) for row in rows) == Counter(
            (policy, repeat) for policy in ("A0", "A2") for repeat in (1, 2)
        )
        assert len({row["input_contract_sha256"] for row in rows}) == 1
        configs = [
            json.loads((path.parent / str(row["config"])).read_text(encoding="utf-8"))
            for row in rows
        ]
        assert all(
            config["backend_options"]["phase2g_release_policy"] == "A0"
            for config in configs
        )
        assert {
            config["backend_options"]["phase2g_block_policy"] for config in configs
        } == {"A0", "A2"}


def test_validator_accepts_frozen_materialization(tmp_path: Path) -> None:
    report = validate_gate2_campaign(_campaign(tmp_path))

    assert report["status"] == "PASS"
    assert report["scenario_count"] == 36
    assert report["planned_run_count"] == 144
    assert report["execution_authorized"] is False
    assert report["outcomes_inspected"] is False


def test_validator_rejects_execution_unlock(tmp_path: Path) -> None:
    path = _campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["execution_authorized"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="execution_authorized must remain false"):
        validate_gate2_campaign(path)


def test_validator_rejects_entry_release_drift(tmp_path: Path) -> None:
    path = _campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    run = manifest["runs"][0]
    config_path = path.parent / run["config"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["backend_options"]["phase2g_release_policy"] = "A1"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    run["config_sha256"] = __import__("hashlib").sha256(config_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest/config identity mismatch"):
        validate_gate2_campaign(path)
