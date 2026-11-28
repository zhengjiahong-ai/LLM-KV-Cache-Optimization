from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_repository_readiness_materializes_ready_72_run_plan(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    output = tmp_path / "freeze.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/spikes/prepare_phase5_calibration.py",
            "--repository",
            str(repository),
            "--output",
            str(output),
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    freeze = json.loads(output.read_text(encoding="utf-8"))
    assert freeze["run_count"] == 72
    assert freeze["execution_ready"] is True
    assert freeze["status"] == "READY"
    assert freeze["campaign_plan"]["run_count"] == 72
    assert freeze["formal_execution_authorized"] is False
    assert "A3_SUFFIX:NATIVE_READINESS_NOT_PASS" not in freeze["blockers"]
    assert "DVA_ER_V1:NATIVE_READINESS_NOT_PASS" not in freeze["blockers"]
    assert freeze["blockers"] == []
    assert freeze["calibration_runner"] == {
        "status": "READY_FOR_FIRST_CALIBRATION_RUN",
        "entrypoint": "scripts/spikes/run_phase5_calibration.py",
    }
