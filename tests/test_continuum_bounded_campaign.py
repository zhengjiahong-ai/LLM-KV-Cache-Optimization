from __future__ import annotations

import json
from pathlib import Path

from kvopt.workload.continuum_bounded_campaign import materialize_campaign
from kvopt.workload.continuum_bounded_gate import validate_campaign

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_materialize_campaign_freezes_54_runs_and_cross_arm_time(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    resource = tmp_path / "resource.json"
    output = tmp_path / "campaign"
    _write(
        profile,
        {
            "schema": "continuum.prefill_reload.formal_long_context_interpreted_profile.v1",
            "status": "complete",
            "provenance": {
                "raw_measurement_modified": False,
                "raw_profile_sha256": "a" * 64,
                "interpretation_contract_sha256": "b" * 64,
            },
        },
    )
    _write(
        resource,
        {
            "status": "PASS",
            "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "model_revision": "d18ecad881a290f0c792f1c2b5dbee1820d4a424",
            "available_kv_blocks": 10000,
            "gpu_memory_utilization": 0.8,
        },
    )

    manifest = materialize_campaign(
        protocol_path=ROOT
        / "configs/phase2/continuum-native-cost-aware-bounded-protocol-v1.json",
        source_freeze_path=ROOT
        / "configs/phase2/continuum-native-cost-aware-formal-freeze-candidate-v1.json",
        profile_path=profile,
        resource_record_path=resource,
        output_dir=output,
    )

    assert manifest["planned_run_count"] == 54
    assert len(manifest["traces"]) == 18
    for cell in manifest["logical_sequence_sha256_by_cell"]:
        runs = [row for row in manifest["runs"] if row["run_id"].startswith(cell)]
        assert len(runs) == 3
        assert len({row["logical_sequence_sha256"] for row in runs}) == 1
    sample = json.loads(
        (output / "g01-short-extreme-deep-a2-repeat-1.config.json").read_text()
    )
    assert sample["backend_options"]["phase2g_block_policy"] == "A2"
    assert sample["controlled_sparse_replay"]["maximum_concurrent_requests"] == 2
    assert sample["cache"]["block_override"] == 2048
    assert sample["backend_options"]["pressure_prompt_tokens"] <= 32768
    validation = validate_campaign(output / "manifest.json")
    assert validation["status"] == "PASS"
    assert validation["problems"] == []


def test_validation_rejects_tampered_logical_sequence(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    resource = tmp_path / "resource.json"
    output = tmp_path / "campaign"
    _write(
        profile,
        {
            "schema": "continuum.prefill_reload.formal_long_context_interpreted_profile.v1",
            "status": "complete",
            "provenance": {
                "raw_measurement_modified": False,
                "raw_profile_sha256": "a" * 64,
                "interpretation_contract_sha256": "b" * 64,
            },
        },
    )
    _write(
        resource,
        {
            "status": "PASS",
            "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "model_revision": "d18ecad881a290f0c792f1c2b5dbee1820d4a424",
            "available_kv_blocks": 10000,
            "gpu_memory_utilization": 0.8,
        },
    )
    manifest = materialize_campaign(
        protocol_path=ROOT
        / "configs/phase2/continuum-native-cost-aware-bounded-protocol-v1.json",
        source_freeze_path=ROOT
        / "configs/phase2/continuum-native-cost-aware-formal-freeze-candidate-v1.json",
        profile_path=profile,
        resource_record_path=resource,
        output_dir=output,
    )
    row = manifest["runs"][0]
    config_path = output / row["config"]
    config = json.loads(config_path.read_text())
    config["controlled_sparse_replay"]["logical_sequence_sha256"] = "0" * 64
    _write(config_path, config)

    validation = validate_campaign(output / "manifest.json")

    assert validation["status"] == "FAIL"
    assert any("config binding mismatch" in problem for problem in validation["problems"])
