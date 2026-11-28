from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_archive import validate_phase5_evidence_archive
from kvopt.workload.phase5_calibration_archive import (
    CalibrationArchiveError,
    finalize_calibration_run_archive,
    validate_calibration_native_evidence,
)


def test_calibration_archive_preserves_fail_closed_evidence(tmp_path: Path) -> None:
    output = tmp_path / "run"
    archive = tmp_path / "run.tar.gz"
    result = finalize_calibration_run_archive(
        output_root=output,
        archive_path=archive,
        run_contract={
            "run_id": "run-1",
            "system_id": "NATIVE",
            "group_id": "SWE_G01",
            "repeat_index": 1,
        },
        consumption_record={"status": "CONSUMED"},
        preflight={"status": "PASS"},
        controller_result=None,
        native_evidence=(),
        engine_cleanup={"status": "PASS"},
        failure=RuntimeError("native failure"),
    )
    assert result["run_status"] == "FAIL_CLOSED"
    assert validate_phase5_evidence_archive(archive)["status"] == "PASS"
    run = json.loads((output / "run.json").read_text())
    assert run["status"] == "FAIL_CLOSED"
    assert run["automatic_retry_allowed"] is False


def _observation(request_id: str) -> dict[str, object]:
    return {
        "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
        "request_id": request_id,
        "payload": {
            "native_prompt_tokens": 32,
            "native_cached_prefix_tokens": 16,
            "native_apc_block_hashes": ["a" * 64, "b" * 64],
            "native_hash_block_size": 16,
            "native_hash_process_id": "7",
            "native_hash_function": "SHA256_CBOR_BYTES",
        },
    }


def _snapshot(request_id: str) -> dict[str, object]:
    return {
        "event_type": "VLLM_PREFIX_SNAPSHOT",
        "request_id": request_id,
        "payload": {
            "ordered_native_hashes": ["a" * 64, "b" * 64],
            "hash_num_tokens": 32,
            "native_hash_block_size": 16,
            "native_hash_process_id": "7",
            "native_hash_function": "SHA256_CBOR_BYTES",
        },
    }


def test_calibration_native_evidence_requires_exact_request_coverage() -> None:
    contract = {"expected_native_enqueue_order": ["p1:r1", "p1:r2"]}
    missing = validate_calibration_native_evidence(
        run_contract=contract,
        native_evidence=(_observation("p1:r1"),),
    )
    assert missing["status"] == "FAIL_CLOSED"
    assert "NATIVE_OBSERVATION_COUNT_MISMATCH" in missing["failure_reasons"]
    complete = validate_calibration_native_evidence(
        run_contract=contract,
        native_evidence=(
            _observation("p1:r1"),
            _observation("p1:r2"),
            _snapshot("p1:r1"),
            _snapshot("p1:r2"),
        ),
    )
    assert complete["status"] == "PASS"
    assert complete["nec_materialization_ready"] is True


def test_calibration_pass_archive_rejects_missing_native_observations(
    tmp_path: Path,
) -> None:
    with pytest.raises(CalibrationArchiveError, match="Native APC"):
        finalize_calibration_run_archive(
            output_root=tmp_path / "run",
            archive_path=tmp_path / "run.tar.gz",
            run_contract={
                "run_id": "run-1",
                "system_id": "NATIVE",
                "group_id": "SWE_G01",
                "repeat_index": 1,
                "expected_native_enqueue_order": ["p1:r1"],
            },
            consumption_record={"status": "CONSUMED"},
            preflight={"status": "PASS"},
            controller_result={"status": "PASS"},
            native_evidence=(),
            engine_cleanup={"status": "PASS"},
        )
