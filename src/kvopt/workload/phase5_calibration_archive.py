"""Fail-closed evidence package for one SWE Calibration run."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase5_archive import create_phase5_evidence_archive


class CalibrationArchiveError(RuntimeError):
    """A Calibration run cannot be represented by a complete archive."""


def validate_calibration_native_evidence(
    *,
    run_contract: Mapping[str, object],
    native_evidence: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Require exactly one complete Native APC observation per frozen request."""

    expected_value = run_contract.get("expected_native_enqueue_order")
    expected = (
        tuple(expected_value)
        if isinstance(expected_value, list)
        and all(isinstance(value, str) and value for value in expected_value)
        else ()
    )
    observations = [
        row
        for row in native_evidence
        if row.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
    ]
    snapshots = [
        row for row in native_evidence if row.get("event_type") == "VLLM_PREFIX_SNAPSHOT"
    ]
    observed_ids = [row.get("request_id") for row in observations]
    snapshot_ids = [row.get("request_id") for row in snapshots]
    failures: list[str] = []
    if not expected or len(expected) != len(set(expected)):
        failures.append("FROZEN_REQUEST_IDENTITIES_INVALID")
    if len(observations) != len(expected):
        failures.append("NATIVE_OBSERVATION_COUNT_MISMATCH")
    if len(observed_ids) != len(set(observed_ids)):
        failures.append("DUPLICATE_NATIVE_REQUEST_OBSERVATION")
    if set(observed_ids) != set(expected):
        failures.append("NATIVE_OBSERVATION_IDENTITY_MISMATCH")
    if len(snapshots) != len(expected):
        failures.append("PREFIX_SNAPSHOT_COUNT_MISMATCH")
    if len(snapshot_ids) != len(set(snapshot_ids)):
        failures.append("DUPLICATE_PREFIX_SNAPSHOT")
    if set(snapshot_ids) != set(expected):
        failures.append("PREFIX_SNAPSHOT_IDENTITY_MISMATCH")
    for row in observations:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            failures.append("NATIVE_OBSERVATION_PAYLOAD_MISSING")
            continue
        prompt = payload.get("native_prompt_tokens")
        cached = payload.get("native_cached_prefix_tokens")
        hashes = payload.get("native_apc_block_hashes")
        block_size = payload.get("native_hash_block_size")
        process_id = payload.get("native_hash_process_id")
        function = payload.get("native_hash_function")
        if (
            isinstance(prompt, bool)
            or not isinstance(prompt, int)
            or prompt < 0
            or isinstance(cached, bool)
            or not isinstance(cached, int)
            or not 0 <= cached <= prompt
            or not isinstance(hashes, list)
            or any(not isinstance(value, str) or len(value) != 64 for value in hashes)
            or isinstance(block_size, bool)
            or not isinstance(block_size, int)
            or block_size <= 0
            or not isinstance(process_id, str)
            or not process_id
            or not isinstance(function, str)
            or not function
        ):
            failures.append("NATIVE_OBSERVATION_FIELDS_INVALID")
    for row in snapshots:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            failures.append("PREFIX_SNAPSHOT_PAYLOAD_MISSING")
            continue
        hashes = payload.get("ordered_native_hashes")
        hash_tokens = payload.get("hash_num_tokens")
        block_size = payload.get("native_hash_block_size")
        process_id = payload.get("native_hash_process_id")
        function = payload.get("native_hash_function")
        if (
            not isinstance(hashes, list)
            or not hashes
            or any(not isinstance(value, str) or len(value) != 64 for value in hashes)
            or isinstance(hash_tokens, bool)
            or not isinstance(hash_tokens, int)
            or isinstance(block_size, bool)
            or not isinstance(block_size, int)
            or block_size <= 0
            or hash_tokens != len(hashes) * block_size
            or not isinstance(process_id, str)
            or not process_id
            or not isinstance(function, str)
            or not function
        ):
            failures.append("PREFIX_SNAPSHOT_FIELDS_INVALID")
    unique_failures = sorted(set(failures))
    return {
        "schema_version": "phase5.swe_calibration_native_evidence_validation.v1",
        "status": "PASS" if not unique_failures else "FAIL_CLOSED",
        "expected_request_count": len(expected),
        "native_observation_count": len(observations),
        "native_observation_request_ids": observed_ids,
        "prefix_snapshot_count": len(snapshots),
        "prefix_snapshot_request_ids": snapshot_ids,
        "failure_reasons": unique_failures,
        "nec_materialization_ready": not unique_failures,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finalize_calibration_run_archive(
    *,
    output_root: Path,
    archive_path: Path,
    run_contract: Mapping[str, object],
    consumption_record: Mapping[str, object],
    preflight: Mapping[str, object],
    controller_result: Mapping[str, object] | None,
    native_evidence: Sequence[Mapping[str, object]],
    engine_cleanup: Mapping[str, object],
    failure: BaseException | None = None,
) -> dict[str, object]:
    """Write and deterministically archive either PASS or FAIL_CLOSED evidence."""

    if output_root.exists() or archive_path.exists():
        raise FileExistsError("Calibration output or archive already exists")
    output_root.mkdir(parents=True)
    status = "PASS" if failure is None else "FAIL_CLOSED"
    evidence_validation = validate_calibration_native_evidence(
        run_contract=run_contract, native_evidence=native_evidence
    )
    if failure is None and (
        controller_result is None or controller_result.get("status") != "PASS"
    ):
        raise CalibrationArchiveError("PASS archive lacks a PASS controller result")
    if failure is None and evidence_validation["status"] != "PASS":
        raise CalibrationArchiveError("PASS archive lacks complete Native APC evidence")
    _write(output_root / "run-contract.json", dict(run_contract))
    _write(output_root / "authorization-consumption.json", dict(consumption_record))
    _write(output_root / "preflight.json", dict(preflight))
    _write(output_root / "controller-result.json", controller_result)
    _write(output_root / "native-evidence.json", [dict(row) for row in native_evidence])
    _write(output_root / "evidence-validation.json", evidence_validation)
    _write(output_root / "engine-cleanup.json", dict(engine_cleanup))
    _write(
        output_root / "run.json",
        {
            "schema_version": "phase5.swe_calibration_native_run.v1",
            "run_id": run_contract.get("run_id"),
            "system_id": run_contract.get("system_id"),
            "group_id": run_contract.get("group_id"),
            "repeat_index": run_contract.get("repeat_index"),
            "status": status,
            "failure_reason": None if failure is None else repr(failure),
            "automatic_retry_allowed": False,
            "formal_execution_authorized": False,
        },
    )
    archive = create_phase5_evidence_archive(
        source_root=output_root,
        archive_path=archive_path,
        required_relative_paths=(
            "run-contract.json",
            "authorization-consumption.json",
            "preflight.json",
            "controller-result.json",
            "native-evidence.json",
            "evidence-validation.json",
            "engine-cleanup.json",
            "run.json",
        ),
    )
    return {**archive, "run_status": status, "run_id": run_contract.get("run_id")}
