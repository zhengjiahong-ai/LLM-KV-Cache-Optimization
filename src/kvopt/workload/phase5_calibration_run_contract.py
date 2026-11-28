"""Immutable per-run input and one-shot claim contracts for Calibration."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from .phase5_calibration import SYSTEM_IDS
from .phase5_replay import canonical_sha256
from .phase5_system_runtime import validate_system_runtime_identity


class CalibrationRunContractError(RuntimeError):
    """One Calibration cell is not exactly bound to the accepted inventory."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise CalibrationRunContractError(f"{label} is missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationRunContractError(f"{label} must contain an object")
    return value


def materialize_calibration_run_contract(
    *,
    execution_manifest_path: Path,
    run_id: str,
) -> dict[str, object]:
    """Resolve one run to exact replay, token and lineage evidence."""

    manifest = _object(execution_manifest_path, "Calibration execution manifest")
    if (
        manifest.get("schema_version")
        != "phase5.swe_calibration_execution_manifest.v1"
        or manifest.get("run_count") != 72
        or manifest.get("execution_authorized_by_m1") is not True
        or manifest.get("formal_execution_authorized") is not False
    ):
        raise CalibrationRunContractError("Calibration execution manifest is not frozen")
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        raise CalibrationRunContractError("Calibration run inventory is malformed")
    matches = [row for row in runs if isinstance(row, Mapping) and row.get("run_id") == run_id]
    if len(matches) != 1:
        raise CalibrationRunContractError("run_id does not resolve exactly once")
    run = dict(matches[0])
    system_id = str(run.get("system_id"))
    if system_id not in SYSTEM_IDS:
        raise CalibrationRunContractError("run system identity is unknown")
    validate_system_runtime_identity(
        system_id=system_id,
        policy_id=str(run.get("policy_id")),
        native_execution_architecture="ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
    )
    if (
        run.get("automatic_retry_allowed") is not False
        or run.get("fresh_process_required") is not True
        or run.get("fresh_engine_core_required") is not True
        or run.get("empty_cache_preflight_required") is not True
        or run.get("preheat_allowed") is not False
    ):
        raise CalibrationRunContractError("run isolation contract differs")

    replay_relative = run.get("replay_template_file")
    if not isinstance(replay_relative, str) or not replay_relative:
        raise CalibrationRunContractError("run replay template path is missing")
    replay_path = execution_manifest_path.parent / replay_relative
    replay = _object(replay_path, "Calibration replay template")
    if (
        replay.get("status") != "PASS"
        or replay.get("group_id") != run.get("group_id")
        or replay.get("replay_sha256") != run.get("replay_sha256")
    ):
        raise CalibrationRunContractError("run replay identity differs")
    replay_payload = dict(replay)
    replay_sha = replay_payload.pop("replay_sha256", None)
    if replay_sha != canonical_sha256(replay_payload):
        raise CalibrationRunContractError("replay canonical SHA-256 differs")
    replay_plan = replay.get("replay_plan")
    if not isinstance(replay_plan, Mapping):
        raise CalibrationRunContractError("run replay plan is missing")
    enqueue = replay_plan.get("expected_native_enqueue_order")
    if (
        not isinstance(enqueue, list)
        or not enqueue
        or len(enqueue) != len(set(enqueue))
        or canonical_sha256(enqueue) != run.get("expected_enqueue_sequence_sha256")
    ):
        raise CalibrationRunContractError("frozen enqueue sequence differs")

    request_rows: dict[str, dict[str, object]] = {}
    programs = run.get("programs")
    if not isinstance(programs, list) or len(programs) != 4:
        raise CalibrationRunContractError("run does not contain four Programs")
    for program in programs:
        if not isinstance(program, Mapping):
            raise CalibrationRunContractError("run Program binding is malformed")
        token_path = Path(str(program.get("token_materialization_path")))
        if (
            not token_path.is_file()
            or _sha256(token_path) != program.get("token_materialization_file_sha256")
        ):
            raise CalibrationRunContractError("token materialization SHA-256 differs")
        values = json.loads(token_path.read_text(encoding="utf-8"))
        if not isinstance(values, list) or not values:
            raise CalibrationRunContractError("token materialization has no requests")
        for value in values:
            if not isinstance(value, Mapping):
                raise CalibrationRunContractError("token request row is malformed")
            request_id = value.get("request_id")
            token_ids = value.get("token_ids")
            if (
                not isinstance(request_id, str)
                or request_id in request_rows
                or not isinstance(token_ids, list)
                or canonical_sha256(token_ids) != value.get("token_ids_sha256")
            ):
                raise CalibrationRunContractError("token request identity differs")
            request_rows[request_id] = {
                "request_id": request_id,
                "program_id": program.get("program_id"),
                "session_id": program.get("session_id"),
                "token_ids": token_ids,
                "token_ids_sha256": value.get("token_ids_sha256"),
            }
    if set(request_rows) != set(enqueue):
        raise CalibrationRunContractError("token requests differ from replay requests")

    payload = {
        "schema_version": "phase5.swe_calibration_run_contract.v1",
        "status": "READY_FOR_SINGLE_EXECUTION",
        "run_id": run_id,
        "system_id": system_id,
        "policy_id": run.get("policy_id"),
        "group_id": run.get("group_id"),
        "repeat_index": run.get("repeat_index"),
        "execution_position": run.get("execution_order_index"),
        "execution_manifest_file_sha256": _sha256(execution_manifest_path),
        "execution_manifest_content_sha256": manifest.get("execution_manifest_sha256"),
        "freeze_sha256": manifest.get("freeze_sha256"),
        "replay_template_file_sha256": _sha256(replay_path),
        "replay_sha256": replay_sha,
        "expected_native_enqueue_order": enqueue,
        "expected_enqueue_sequence_sha256": canonical_sha256(enqueue),
        "request_inputs": [request_rows[request_id] for request_id in enqueue],
        "controller_timers": replay.get("controller_timers"),
        "timer_runtime_rule": replay.get("timer_runtime_rule"),
        "automatic_retry_allowed": False,
        "formal_execution_authorized": False,
        "bfcl_gpu_execution_authorized": False,
    }
    return {**payload, "run_contract_sha256": canonical_sha256(payload)}


def claim_calibration_run_once(
    *, state_root: Path, run_contract: Mapping[str, object], git_sha: str
) -> Path:
    """Atomically consume exactly one frozen Calibration run cell."""

    run_id = run_contract.get("run_id")
    contract_sha = run_contract.get("run_contract_sha256")
    if (
        run_contract.get("status") != "READY_FOR_SINGLE_EXECUTION"
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(contract_sha, str)
        or len(contract_sha) != 64
        or not isinstance(git_sha, str)
        or len(git_sha) != 40
    ):
        raise CalibrationRunContractError("run claim identity is invalid")
    state_root.mkdir(parents=True, exist_ok=True)
    claim = state_root / f".{run_id}.consumed.json"
    payload = {
        "schema_version": "phase5.swe_calibration_run_consumption.v1",
        "run_id": run_id,
        "git_sha": git_sha,
        "run_contract_sha256": contract_sha,
        "execution_manifest_file_sha256": run_contract.get(
            "execution_manifest_file_sha256"
        ),
        "automatic_retry_allowed": False,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(claim, flags, 0o600)
    except FileExistsError as error:
        raise CalibrationRunContractError("Calibration run was already consumed") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        claim.unlink(missing_ok=True)
        raise
    return claim
