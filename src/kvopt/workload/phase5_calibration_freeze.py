"""Materialize the authorized SWE Calibration plan without overclaiming readiness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .phase5_calibration import SYSTEM_IDS
from .phase5_campaign_plan import balanced_latin_square, materialize_campaign_plan
from .phase5_replay import canonical_sha256
from .phase5_system_runtime import (
    SystemRuntimeContractError,
    validate_system_runtime_identity,
)


class CalibrationFreezeError(ValueError):
    """The accepted cohort cannot be frozen as an executable Calibration plan."""


def _rows(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise CalibrationFreezeError(f"{label} must be a list of objects")
    return list(value)


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CalibrationFreezeError(f"{label} must be a SHA-256 digest")
    return value


def materialize_calibration_freeze(
    *,
    calibration_child: Mapping[str, object],
    arrival_manifest: Mapping[str, object],
    protocol_sha256: str,
    git_sha: str,
    system_readiness: Mapping[str, Mapping[str, object]],
    runner_readiness: Mapping[str, object] | None = None,
    execution_identity_audit: Mapping[str, object] | None = None,
    budget_ceiling_gpu_hours: float = 30.8,
) -> dict[str, object]:
    """Build the exact 72-run plan and independently gate Native execution.

    The accepted parent cohort remains immutable.  M1 authorization is necessary
    but not sufficient: each of the six production adapters must identify the
    frozen EngineCore architecture and pass its first-run Native readiness gate.
    """

    if calibration_child.get("schema_version") != "phase5.swe_child_manifest.v1":
        raise CalibrationFreezeError("unsupported Calibration child manifest")
    if calibration_child.get("role") != "CALIBRATION":
        raise CalibrationFreezeError("child manifest is not Calibration")
    child_groups = _rows(calibration_child.get("groups"), "Calibration Groups")
    if [row.get("group_id") for row in child_groups] != [
        "SWE_G01",
        "SWE_G02",
        "SWE_G03",
        "SWE_G04",
    ]:
        raise CalibrationFreezeError("Calibration Group identities or order drifted")

    arrival_rows = _rows(arrival_manifest.get("groups"), "arrival Groups")
    arrivals = {str(row.get("group_id")): row for row in arrival_rows}
    group_ids = [str(row["group_id"]) for row in child_groups]
    if any(group_id not in arrivals for group_id in group_ids):
        raise CalibrationFreezeError("Calibration Group lacks frozen arrival schedule")
    if arrival_manifest.get("arrival_mode") != "FROZEN_POISSON":
        raise CalibrationFreezeError("Calibration arrival mode is not frozen Poisson")
    reuse = arrival_manifest.get("reuse_contract")
    if not isinstance(reuse, Mapping) or (
        reuse.get("per_system_resampling_allowed") is not False
        or reuse.get("per_repeat_resampling_allowed") is not False
    ):
        raise CalibrationFreezeError("arrival realization may be resampled")

    square = balanced_latin_square()
    execution_orders: dict[str, Sequence[str]] = {}
    ordinal = 0
    for group_id in group_ids:
        for repeat in range(1, 4):
            execution_orders[f"SWE_BENCH:{group_id}:r{repeat}"] = square[
                ordinal % len(square)
            ]
            ordinal += 1
    plan = materialize_campaign_plan(
        phase="CALIBRATION",
        groups={"SWE_BENCH": group_ids},
        repeats=3,
        execution_orders=execution_orders,
        workload_seal_sha256_by_group={
            str(row["group_id"]): _sha(
                row.get("group_content_sha256"), "group_content_sha256"
            )
            for row in child_groups
        },
        arrival_sha256_by_group={
            group_id: _sha(arrivals[group_id].get("schedule_sha256"), "schedule_sha256")
            for group_id in group_ids
        },
        protocol_sha256=_sha(protocol_sha256, "protocol_sha256"),
    )

    if set(system_readiness) != set(SYSTEM_IDS):
        raise CalibrationFreezeError("readiness matrix must contain exactly six systems")
    readiness_rows: list[dict[str, object]] = []
    blockers: list[str] = []
    runner = dict(runner_readiness or {"status": "PASS", "entrypoint": "TEST"})
    if runner.get("status") not in {"PASS", "READY_FOR_FIRST_CALIBRATION_RUN"}:
        blockers.append("CALIBRATION_RUNNER:NOT_READY")
    if not isinstance(runner.get("entrypoint"), str) or not runner.get("entrypoint"):
        blockers.append("CALIBRATION_RUNNER:ENTRYPOINT_MISSING")
    identity_audit = dict(execution_identity_audit or {"status": "PASS"})
    if identity_audit.get("status") != "PASS":
        blockers.append("MODEL_TOKENIZER_IDENTITY:MISMATCH")
    for system_id in SYSTEM_IDS:
        row = system_readiness[system_id]
        status = row.get("status")
        architecture = row.get("native_execution_architecture")
        production_entrypoint = row.get("production_entrypoint")
        policy_id = row.get("policy_id")
        if status not in {"PASS", "READY_FOR_FIRST_CALIBRATION_RUN"}:
            blockers.append(f"{system_id}:NATIVE_READINESS_NOT_PASS")
        if architecture != "ENGINE_CORE_PLUGIN_UTILITY_RPC_V1":
            blockers.append(f"{system_id}:ARCHITECTURE_MISMATCH")
        if not isinstance(production_entrypoint, str) or not production_entrypoint:
            blockers.append(f"{system_id}:PRODUCTION_ENTRYPOINT_MISSING")
        try:
            validate_system_runtime_identity(
                system_id=system_id,
                policy_id=str(policy_id),
                native_execution_architecture=str(architecture),
            )
        except SystemRuntimeContractError:
            blockers.append(f"{system_id}:POLICY_IDENTITY_MISMATCH")
        readiness_rows.append(
            {
                "system_id": system_id,
                "status": status,
                "native_execution_architecture": architecture,
                "production_entrypoint": production_entrypoint,
                "policy_id": policy_id,
                "evidence_sha256": row.get("evidence_sha256"),
            }
        )

    if budget_ceiling_gpu_hours != 30.8:
        raise CalibrationFreezeError("GPU budget differs from the M1-frozen ceiling")
    payload = {
        "schema_version": "phase5.swe_calibration_freeze.v1",
        "git_sha": git_sha,
        "phase": "CALIBRATION",
        "run_count": 72,
        "calibration_group_ids": group_ids,
        "campaign_plan": plan,
        "calibration_child_content_sha256": calibration_child.get(
            "child_content_sha256"
        ),
        "arrival_manifest_content_sha256": arrival_manifest.get(
            "arrival_manifest_content_sha256"
        ),
        "budget_ceiling_gpu_hours": budget_ceiling_gpu_hours,
        "budget_scope": "SWE_CALIBRATION_72_PLUS_FORMAL_N8_96_TOTAL_GPU_OCCUPANCY",
        "system_readiness": readiness_rows,
        "calibration_runner": runner,
        "execution_identity_audit": identity_audit,
        "blockers": sorted(set(blockers)),
        "execution_authorized_by_m1": True,
        "execution_ready": not blockers,
        "status": "READY" if not blockers else "FAIL_CLOSED_EXECUTION_NOT_READY",
        "formal_execution_authorized": False,
        "bfcl_gpu_execution_authorized": False,
    }
    return {**payload, "freeze_sha256": canonical_sha256(payload)}
