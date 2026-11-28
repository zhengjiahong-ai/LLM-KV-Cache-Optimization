"""Build the immutable 72-run execution inventory for SWE Calibration."""

from __future__ import annotations

from collections.abc import Mapping

from .phase5_calibration import SYSTEM_IDS
from .phase5_replay import canonical_sha256
from .phase5_system_runtime import validate_system_runtime_identity


class CalibrationExecutionError(ValueError):
    """Calibration inputs cannot be turned into an executable run inventory."""


def materialize_calibration_execution_manifest(
    *,
    freeze: Mapping[str, object],
    input_index: Mapping[str, object],
    arrival_manifest: Mapping[str, object],
) -> dict[str, object]:
    """Join membership, replay inputs, arrivals and six-system identities."""

    if freeze.get("schema_version") != "phase5.swe_calibration_freeze.v1":
        raise CalibrationExecutionError("unsupported Calibration freeze")
    if input_index.get("schema_version") != "phase5.swe_calibration_input_index.v1":
        raise CalibrationExecutionError("unsupported Calibration input index")
    if input_index.get("status") != "PASS" or input_index.get("program_count") != 16:
        raise CalibrationExecutionError("private Calibration input index is not complete")
    plan = freeze.get("campaign_plan")
    if not isinstance(plan, Mapping) or plan.get("run_count") != 72:
        raise CalibrationExecutionError("Calibration campaign plan is not the exact 72-run plan")
    run_rows = plan.get("runs")
    bindings = input_index.get("bindings")
    arrival_rows = arrival_manifest.get("groups")
    readiness_rows = freeze.get("system_readiness")
    if not all(isinstance(value, list) for value in (run_rows, bindings, arrival_rows, readiness_rows)):
        raise CalibrationExecutionError("Calibration execution inputs are malformed")
    assert isinstance(run_rows, list)
    assert isinstance(bindings, list)
    assert isinstance(arrival_rows, list)
    assert isinstance(readiness_rows, list)

    by_group: dict[str, list[Mapping[str, object]]] = {}
    for row in bindings:
        if not isinstance(row, Mapping):
            raise CalibrationExecutionError("Calibration binding is malformed")
        by_group.setdefault(str(row.get("group_id")), []).append(row)
    arrivals = {
        str(row.get("group_id")): row for row in arrival_rows if isinstance(row, Mapping)
    }
    readiness = {
        str(row.get("system_id")): row
        for row in readiness_rows
        if isinstance(row, Mapping)
    }
    if set(readiness) != set(SYSTEM_IDS):
        raise CalibrationExecutionError("six-system readiness inventory is incomplete")

    runs: list[dict[str, object]] = []
    for row in run_rows:
        if not isinstance(row, Mapping):
            raise CalibrationExecutionError("campaign run row is malformed")
        group_id = str(row.get("group_id"))
        system_id = str(row.get("system_id"))
        programs = sorted(by_group.get(group_id, ()), key=lambda value: int(value["ordinal"]))
        arrival = arrivals.get(group_id)
        if len(programs) != 4 or not isinstance(arrival, Mapping):
            raise CalibrationExecutionError("run lacks four Programs or its arrival schedule")
        starts = arrival.get("starts")
        if not isinstance(starts, list):
            raise CalibrationExecutionError("arrival schedule is malformed")
        program_ids = [str(value["program_id"]) for value in programs]
        if [str(value.get("program_id")) for value in starts if isinstance(value, Mapping)] != program_ids:
            raise CalibrationExecutionError("arrival Program order differs from frozen membership")
        identity = readiness[system_id]
        validate_system_runtime_identity(
            system_id=system_id,
            policy_id=str(identity.get("policy_id")),
            native_execution_architecture=str(identity.get("native_execution_architecture")),
        )
        enqueue_payload = [
            {
                "program_id": value["program_id"],
                "session_id": value["session_id"],
                "token_materialization_file_sha256": value[
                    "token_materialization_file_sha256"
                ],
            }
            for value in programs
        ]
        runs.append(
            {
                **dict(row),
                "policy_id": identity.get("policy_id"),
                "production_entrypoint": identity.get("production_entrypoint"),
                "readiness_status": identity.get("status"),
                "programs": programs,
                "program_start_offsets": list(starts),
                "expected_enqueue_sequence_sha256": canonical_sha256(enqueue_payload),
                "automatic_retry_allowed": False,
                "fresh_process_required": True,
                "fresh_engine_core_required": True,
                "empty_cache_preflight_required": True,
                "preheat_allowed": False,
            }
        )
    if len(runs) != 72 or len({str(row["run_id"]) for row in runs}) != 72:
        raise CalibrationExecutionError("Calibration execution inventory is not exactly 72 runs")
    payload = {
        "schema_version": "phase5.swe_calibration_execution_manifest.v1",
        "status": (
            "READY_FOR_EXECUTION"
            if freeze.get("execution_ready") is True
            else "BLOCKED_SYSTEMS_NOT_READY"
        ),
        "run_count": 72,
        "systems": list(SYSTEM_IDS),
        "groups": ["SWE_G01", "SWE_G02", "SWE_G03", "SWE_G04"],
        "repeats": 3,
        "freeze_sha256": freeze.get("freeze_sha256"),
        "git_sha": freeze.get("git_sha"),
        "input_index_sha256": input_index.get("input_index_sha256"),
        "arrival_manifest_content_sha256": arrival_manifest.get(
            "arrival_manifest_content_sha256"
        ),
        "runs": runs,
        "execution_authorized_by_m1": freeze.get("execution_authorized_by_m1"),
        "execution_ready": freeze.get("execution_ready"),
        "formal_execution_authorized": False,
        "bfcl_gpu_execution_authorized": False,
    }
    return {**payload, "execution_manifest_sha256": canonical_sha256(payload)}
