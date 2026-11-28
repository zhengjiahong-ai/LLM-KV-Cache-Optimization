from __future__ import annotations

import pytest

from kvopt.workload.phase5_calibration import SYSTEM_IDS
from kvopt.workload.phase5_calibration_execution import (
    CalibrationExecutionError,
    materialize_calibration_execution_manifest,
)
from kvopt.workload.phase5_system_runtime import SYSTEM_RUNTIME_CONTRACTS


def _fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    groups = [f"SWE_G{index:02d}" for index in range(1, 5)]
    bindings = []
    arrivals = []
    runs = []
    for group in groups:
        starts = []
        for ordinal in range(1, 5):
            program = f"{group}-p{ordinal}"
            bindings.append(
                {
                    "group_id": group,
                    "ordinal": ordinal,
                    "program_id": program,
                    "session_id": f"{program}:session",
                    "token_materialization_file_sha256": f"{ordinal:064x}",
                }
            )
            starts.append(
                {"ordinal": ordinal, "program_id": program, "start_offset_seconds": ordinal - 1.0}
            )
        arrivals.append({"group_id": group, "starts": starts})
        for repeat in range(1, 4):
            for position, system in enumerate(SYSTEM_IDS):
                runs.append(
                    {
                        "run_id": f"{group}-{repeat}-{system}",
                        "group_id": group,
                        "system_id": system,
                        "repeat_index": repeat,
                        "execution_order_index": position,
                    }
                )
    readiness = [
        {
            "system_id": system,
            "status": "PASS",
            "policy_id": SYSTEM_RUNTIME_CONTRACTS[system]["policy_id"],
            "native_execution_architecture": "ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
            "production_entrypoint": "entrypoint",
        }
        for system in SYSTEM_IDS
    ]
    freeze = {
        "schema_version": "phase5.swe_calibration_freeze.v1",
        "campaign_plan": {"run_count": 72, "runs": runs},
        "system_readiness": readiness,
        "freeze_sha256": "a" * 64,
        "execution_authorized_by_m1": True,
        "execution_ready": True,
    }
    inputs = {
        "schema_version": "phase5.swe_calibration_input_index.v1",
        "status": "PASS",
        "program_count": 16,
        "input_index_sha256": "b" * 64,
        "bindings": bindings,
    }
    arrival = {
        "arrival_manifest_content_sha256": "c" * 64,
        "groups": arrivals,
    }
    return freeze, inputs, arrival


def test_execution_manifest_contains_exact_72_run_inventory() -> None:
    freeze, inputs, arrival = _fixture()
    result = materialize_calibration_execution_manifest(
        freeze=freeze, input_index=inputs, arrival_manifest=arrival
    )
    assert result["status"] == "READY_FOR_EXECUTION"
    assert result["run_count"] == 72
    assert len(result["runs"]) == 72


def test_execution_manifest_rejects_arrival_member_drift() -> None:
    freeze, inputs, arrival = _fixture()
    arrival["groups"][0]["starts"][0]["program_id"] = "replacement"  # type: ignore[index]
    with pytest.raises(CalibrationExecutionError, match="Program order"):
        materialize_calibration_execution_manifest(
            freeze=freeze, input_index=inputs, arrival_manifest=arrival
        )
