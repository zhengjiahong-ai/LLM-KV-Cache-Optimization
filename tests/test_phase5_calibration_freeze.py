from __future__ import annotations

import hashlib

import pytest

from kvopt.workload.phase5_calibration import SYSTEM_IDS
from kvopt.workload.phase5_calibration_freeze import (
    CalibrationFreezeError,
    materialize_calibration_freeze,
)
from kvopt.workload.phase5_system_runtime import SYSTEM_RUNTIME_CONTRACTS


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _child() -> dict[str, object]:
    return {
        "schema_version": "phase5.swe_child_manifest.v1",
        "role": "CALIBRATION",
        "child_content_sha256": _sha("child"),
        "groups": [
            {"group_id": f"SWE_G{index:02d}", "group_content_sha256": _sha(f"g{index}")}
            for index in range(1, 5)
        ],
    }


def _arrivals() -> dict[str, object]:
    return {
        "arrival_mode": "FROZEN_POISSON",
        "arrival_manifest_content_sha256": _sha("arrivals"),
        "reuse_contract": {
            "per_system_resampling_allowed": False,
            "per_repeat_resampling_allowed": False,
        },
        "groups": [
            {"group_id": f"SWE_G{index:02d}", "schedule_sha256": _sha(f"a{index}")}
            for index in range(1, 13)
        ],
    }


def _readiness(status: str = "PASS") -> dict[str, dict[str, object]]:
    return {
        system_id: {
            "status": status,
            "native_execution_architecture": "ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
            "production_entrypoint": f"kvopt.phase5:{system_id.lower()}",
            "policy_id": SYSTEM_RUNTIME_CONTRACTS[system_id]["policy_id"],
            "evidence_sha256": _sha(system_id),
        }
        for system_id in SYSTEM_IDS
    }


def test_materializes_ready_exact_72_run_freeze() -> None:
    freeze = materialize_calibration_freeze(
        calibration_child=_child(),
        arrival_manifest=_arrivals(),
        protocol_sha256=_sha("protocol"),
        git_sha="a" * 40,
        system_readiness=_readiness(),
    )
    assert freeze["status"] == "READY"
    assert freeze["execution_ready"] is True
    assert freeze["campaign_plan"]["run_count"] == 72
    assert freeze["formal_execution_authorized"] is False


def test_missing_native_system_fails_closed_without_changing_plan() -> None:
    readiness = _readiness()
    readiness["DVA_ER_V1"]["status"] = "NOT_RUN"
    freeze = materialize_calibration_freeze(
        calibration_child=_child(),
        arrival_manifest=_arrivals(),
        protocol_sha256=_sha("protocol"),
        git_sha="a" * 40,
        system_readiness=readiness,
    )
    assert freeze["status"] == "FAIL_CLOSED_EXECUTION_NOT_READY"
    assert freeze["execution_ready"] is False
    assert freeze["campaign_plan"]["run_count"] == 72
    assert "DVA_ER_V1:NATIVE_READINESS_NOT_PASS" in freeze["blockers"]


def test_first_calibration_run_may_supply_native_readiness_evidence() -> None:
    readiness = _readiness("READY_FOR_FIRST_CALIBRATION_RUN")
    freeze = materialize_calibration_freeze(
        calibration_child=_child(),
        arrival_manifest=_arrivals(),
        protocol_sha256=_sha("protocol"),
        git_sha="a" * 40,
        system_readiness=readiness,
    )
    assert freeze["status"] == "READY"
    assert freeze["execution_ready"] is True


def test_rejects_non_frozen_budget() -> None:
    with pytest.raises(CalibrationFreezeError, match="budget"):
        materialize_calibration_freeze(
            calibration_child=_child(),
            arrival_manifest=_arrivals(),
            protocol_sha256=_sha("protocol"),
            git_sha="a" * 40,
            system_readiness=_readiness(),
            budget_ceiling_gpu_hours=31.0,
        )


def test_missing_calibration_runner_fails_closed() -> None:
    freeze = materialize_calibration_freeze(
        calibration_child=_child(),
        arrival_manifest=_arrivals(),
        protocol_sha256=_sha("protocol"),
        git_sha="a" * 40,
        system_readiness=_readiness(),
        runner_readiness={"status": "NOT_IMPLEMENTED", "entrypoint": None},
    )
    assert freeze["execution_ready"] is False
    assert "CALIBRATION_RUNNER:NOT_READY" in freeze["blockers"]
    assert "CALIBRATION_RUNNER:ENTRYPOINT_MISSING" in freeze["blockers"]


def test_execution_identity_mismatch_fails_closed() -> None:
    freeze = materialize_calibration_freeze(
        calibration_child=_child(),
        arrival_manifest=_arrivals(),
        protocol_sha256=_sha("protocol"),
        git_sha="a" * 40,
        system_readiness=_readiness(),
        execution_identity_audit={"status": "FAIL_CLOSED_IDENTITY_MISMATCH"},
    )
    assert freeze["execution_ready"] is False
    assert "MODEL_TOKENIZER_IDENTITY:MISMATCH" in freeze["blockers"]
