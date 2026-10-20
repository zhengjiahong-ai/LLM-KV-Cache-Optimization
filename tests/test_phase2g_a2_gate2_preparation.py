import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_gate2_materialize import materialize_gate2_campaign
from kvopt.workload.phase2g_a2_gate2_validate import validate_gate2_campaign

DISTRIBUTION = Path("configs/phase2/phase2g-a2-native-gate2-distribution-v1.json")
VALUE_DISTRIBUTION = Path(
    "configs/phase2/phase2g-a2-bounded-value-distribution-v2.json"
)


def _campaign(tmp_path: Path) -> Path:
    return materialize_gate2_campaign(
        distribution_path=DISTRIBUTION,
        output_dir=tmp_path / "campaign",
    )


def _value_campaign(tmp_path: Path) -> Path:
    return materialize_gate2_campaign(
        distribution_path=VALUE_DISTRIBUTION,
        output_dir=tmp_path / "value-campaign",
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


def test_validator_rejects_duplicate_run_id_and_pairing_key(tmp_path: Path) -> None:
    path = _campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["runs"][1]["run_id"] = manifest["runs"][0]["run_id"]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate run ID"):
        validate_gate2_campaign(path)

    manifest = json.loads(_campaign(tmp_path / "second").read_text(encoding="utf-8"))
    manifest["runs"][1]["scenario_id"] = manifest["runs"][0]["scenario_id"]
    manifest["runs"][1]["policy"] = manifest["runs"][0]["policy"]
    manifest["runs"][1]["repeat"] = manifest["runs"][0]["repeat"]
    second_path = tmp_path / "second" / "campaign" / "manifest.json"
    second_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate scenario/policy/repeat"):
        validate_gate2_campaign(second_path)


def test_validator_rejects_trace_and_input_digest_tampering(tmp_path: Path) -> None:
    path = _campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["runs"][0]["trace_sha256"] = "tampered"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest/config identity mismatch"):
        validate_gate2_campaign(path)

    second_path = _campaign(tmp_path / "second")
    manifest = json.loads(second_path.read_text(encoding="utf-8"))
    manifest["runs"][0]["input_contract_sha256"] = "tampered"
    second_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="input contract digest mismatch"):
        validate_gate2_campaign(second_path)


def test_value_campaign_binds_base_and_preserves_old_artifacts(tmp_path: Path) -> None:
    path = _value_campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validation = validate_gate2_campaign(path)

    assert manifest["run_kind"] == "A2_BOUNDED_NATIVE_VALUE_EVALUATION_V2"
    assert manifest["base_distribution_sha256"]
    assert validation["status"] == "PASS"
    assert manifest["workload_construction_repairs"] == {
        "f4_capacity_uses_first_pressure_resident_content": True,
        "f6_nonreturn_not_terminal_before_pressure": True,
        "old_gate2_v3_artifacts_modified": False,
    }


def test_f4_capacity_uses_only_content_resident_at_first_pressure(
    tmp_path: Path,
) -> None:
    path = _value_campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    scenario = next(row for row in manifest["scenarios"] if row["scenario_id"] == "f4-draw-06")
    run = next(row for row in manifest["runs"] if row["scenario_id"] == "f4-draw-06")
    config = json.loads((path.parent / run["config"]).read_text(encoding="utf-8"))
    all_unique = {
        str(key): int(tokens)
        for rows in config["backend_options"]["prefix_segments_by_request"].values()
        for key, tokens in rows
    }
    basis = scenario["capacity_basis"]

    assert basis["mode"] == "FIRST_PRESSURE_RESIDENT_UNIQUE_CONTENT"
    assert basis["protected_blocks"] == config["backend_options"][
        "phase2g_unique_protected_blocks"
    ]
    assert sum(basis["unique_segment_tokens"].values()) < sum(all_unique.values())
    assert all(request_id.endswith(":1") for request_id in basis["arrived_request_ids"])


def test_f6_omitted_return_is_not_declared_terminal_before_pressure(
    tmp_path: Path,
) -> None:
    path = _value_campaign(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    scenario = next(row for row in manifest["scenarios"] if row["scenario_id"] == "f6-draw-02")
    trace = json.loads((path.parent / scenario["trace"]).read_text(encoding="utf-8"))
    omitted = scenario["family_parameters"]["omitted_program_id"]
    requests = [row for row in trace["requests"] if row["program_id"] == omitted]

    assert len(requests) == 1
    assert trace["allow_incomplete_programs"] is True
    assert requests[0]["is_terminal"] is False
    assert requests[0]["next_tool_type"] == "phase2g-f6"
    assert scenario["family_parameters"]["future_nonreturn_leaked_before_pressure"] is False
