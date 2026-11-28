from __future__ import annotations

import json
from pathlib import Path

from kvopt.workload.phase5_archive import validate_phase5_evidence_archive
from kvopt.workload.phase5_calibration_archive import finalize_calibration_run_archive


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
