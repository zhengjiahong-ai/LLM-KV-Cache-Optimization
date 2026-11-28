from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_calibration_replay import (
    CalibrationReplayError,
    bind_calibration_replay_templates,
    materialize_calibration_run_replay,
)


def _run(tmp_path):
    programs = []
    starts = []
    for index in range(4):
        program = f"program-{index}"
        session = f"session-{index}"
        trace = {
            "program_id": program,
            "session_id": session,
            "turns": [
                {
                    "request_id": f"{program}:r1",
                    "submitted_at_seconds": 10.0,
                    "completed_at_seconds": 11.0,
                },
                {
                    "request_id": f"{program}:r2",
                    "submitted_at_seconds": 13.0,
                    "completed_at_seconds": 14.0,
                },
            ],
        }
        path = tmp_path / f"{program}.json"
        path.write_text(json.dumps(trace), encoding="utf-8")
        programs.append(
            {
                "program_id": program,
                "session_id": session,
                "normalized_trace_path": str(path),
            }
        )
        starts.append(
            {
                "program_id": program,
                "start_offset_seconds": float(index),
            }
        )
    return {
        "run_id": "run-1",
        "group_id": "SWE_G01",
        "system_id": "DVA_ER_V1",
        "programs": programs,
        "program_start_offsets": starts,
    }


def test_materializes_exact_requests_and_terminal_armed_timers(tmp_path) -> None:
    result = materialize_calibration_run_replay(_run(tmp_path))
    assert result["status"] == "PASS"
    assert result["request_count"] == 8
    assert result["controller_timer_count"] == 4
    assert result["controller_timers"][0]["timeout_seconds"] == 2.0
    assert result["controller_timers"][0]["arm_boundary"] == (
        "OBSERVED_PREDECESSOR_TERMINAL"
    )


def test_negative_empirical_gap_fails_closed(tmp_path) -> None:
    run = _run(tmp_path)
    path = run["programs"][0]["normalized_trace_path"]
    trace_path = Path(path)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["turns"][1]["submitted_at_seconds"] = 10.5
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(CalibrationReplayError, match="negative"):
        materialize_calibration_run_replay(run)


def test_binds_one_group_template_to_all_runs(tmp_path) -> None:
    run = _run(tmp_path)
    templates = {}
    runs = []
    for group_index in range(1, 5):
        group_id = f"SWE_G{group_index:02d}"
        group_run = {**run, "group_id": group_id}
        templates[group_id] = materialize_calibration_run_replay(group_run)
        for repeat in range(18):
            runs.append({**group_run, "run_id": f"{group_id}:{repeat}"})
    result = bind_calibration_replay_templates(
        {"runs": runs, "execution_manifest_sha256": "old"}, templates
    )
    assert len(result["runs"]) == 72
    assert len(result["replay_templates"]) == 4
    assert result["runs"][0]["replay_sha256"] == templates["SWE_G01"][
        "replay_sha256"
    ]
