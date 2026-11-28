"""Fail-closed evidence package for one SWE Calibration run."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase5_archive import create_phase5_evidence_archive


class CalibrationArchiveError(RuntimeError):
    """A Calibration run cannot be represented by a complete archive."""


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
    if failure is None and (
        controller_result is None or controller_result.get("status") != "PASS"
    ):
        raise CalibrationArchiveError("PASS archive lacks a PASS controller result")
    _write(output_root / "run-contract.json", dict(run_contract))
    _write(output_root / "authorization-consumption.json", dict(consumption_record))
    _write(output_root / "preflight.json", dict(preflight))
    _write(output_root / "controller-result.json", controller_result)
    _write(output_root / "native-evidence.json", [dict(row) for row in native_evidence])
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
            "engine-cleanup.json",
            "run.json",
        ),
    )
    return {**archive, "run_status": status, "run_id": run_contract.get("run_id")}
