from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_calibration_run_contract import (
    CalibrationRunContractError,
    claim_calibration_run_once,
    materialize_calibration_run_contract,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _fixture(tmp_path: Path) -> tuple[Path, str]:
    import hashlib

    request_ids = [f"program-{index}:turn:1" for index in range(1, 5)]
    programs = []
    for index, request_id in enumerate(request_ids, start=1):
        token_ids = [index, index + 1, index + 2]
        token_path = tmp_path / f"tokens-{index}.json"
        token_path.write_text(
            json.dumps([{
                "request_id": request_id,
                "token_ids": token_ids,
                "token_ids_sha256": canonical_sha256(token_ids),
            }]),
            encoding="utf-8",
        )
        programs.append({
            "program_id": f"program-{index}",
            "session_id": f"session-{index}",
            "source_trace_sha256": str(index) * 64,
            "token_materialization_path": str(token_path),
            "token_materialization_file_sha256": hashlib.sha256(
                token_path.read_bytes()
            ).hexdigest(),
        })
    replay_payload = {
        "schema_version": "phase5.swe_calibration_run_replay.v1",
        "status": "PASS",
        "group_id": "SWE_G01",
        "replay_plan": {
            "expected_native_enqueue_order": request_ids,
            "events": [
                {
                    "kind": "ARRIVAL",
                    "request_id": request_id,
                    "logical_timestamp": float(index),
                }
                for index, request_id in enumerate(request_ids)
            ],
        },
        "controller_timers": [],
        "timer_runtime_rule": "RULE",
    }
    replay = {**replay_payload, "replay_sha256": canonical_sha256(replay_payload)}
    replay_root = tmp_path / "replay-templates"
    replay_root.mkdir()
    replay_path = replay_root / "SWE_G01.json"
    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    run_id = "phase5-calibration-swe_bench-SWE_G01-r1-native"
    manifest_payload = {
        "schema_version": "phase5.swe_calibration_execution_manifest.v1",
        "run_count": 72,
        "execution_authorized_by_m1": True,
        "formal_execution_authorized": False,
        "freeze_sha256": "f" * 64,
        "git_sha": "a" * 40,
        "runs": [{
            "run_id": run_id,
            "system_id": "NATIVE",
            "policy_id": "VLLM_NATIVE_LRU",
            "group_id": "SWE_G01",
            "repeat_index": 1,
            "execution_order_index": 0,
            "automatic_retry_allowed": False,
            "fresh_process_required": True,
            "fresh_engine_core_required": True,
            "empty_cache_preflight_required": True,
            "preheat_allowed": False,
            "replay_template_file": "replay-templates/SWE_G01.json",
            "replay_sha256": replay["replay_sha256"],
            "expected_enqueue_sequence_sha256": canonical_sha256(request_ids),
            "programs": programs,
        }],
    }
    manifest = {
        **manifest_payload,
        "execution_manifest_sha256": canonical_sha256(manifest_payload),
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, run_id


def test_run_contract_binds_manifest_replay_and_tokens(tmp_path: Path) -> None:
    manifest, run_id = _fixture(tmp_path)
    contract = materialize_calibration_run_contract(
        execution_manifest_path=manifest, run_id=run_id
    )
    assert contract["status"] == "READY_FOR_SINGLE_EXECUTION"
    assert contract["expected_native_enqueue_order"] == [
        "program-1:turn:1",
        "program-2:turn:1",
        "program-3:turn:1",
        "program-4:turn:1",
    ]


def test_run_claim_is_atomic_and_single_use(tmp_path: Path) -> None:
    manifest, run_id = _fixture(tmp_path)
    contract = materialize_calibration_run_contract(
        execution_manifest_path=manifest, run_id=run_id
    )
    state = tmp_path / "state"
    claim_calibration_run_once(state_root=state, run_contract=contract, git_sha="a" * 40)
    with pytest.raises(CalibrationRunContractError, match="already consumed"):
        claim_calibration_run_once(
            state_root=state, run_contract=contract, git_sha="a" * 40
        )
