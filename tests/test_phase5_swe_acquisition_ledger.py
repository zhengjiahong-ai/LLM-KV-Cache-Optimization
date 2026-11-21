from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_swe_acquisition_ledger import build_failure_ledger


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    instance_id = "django__django-1"
    run_directory = tmp_path / instance_id
    run_directory.mkdir()
    _write(run_directory / f"{instance_id}.traj.json", {"messages": []})
    _write(run_directory / "acquisition-sidecar.json", {"model_calls": []})
    reason = (
        "RemoteProtocolError: peer closed connection without sending complete "
        "message body (incomplete chunked read)"
    )
    _write(
        run_directory / "run.json",
        {
            "instance_id": instance_id,
            "status": "failed",
            "agent_outcome": "FAILED",
            "agent_exit_status": "RemoteProtocolError",
            "failure_reason": reason,
            "model_call_count": 45,
            "tool_call_count": 44,
        },
    )
    reconciliation = tmp_path / "reconciliation.json"
    _write(
        reconciliation,
        {
            "status": "COMPLETE",
            "unresolved_candidate_ids": [instance_id],
            "attempts": [
                {
                    "instance_id": instance_id,
                    "attempt_source": "PRIMARY",
                    "run_directory": str(run_directory),
                    "status": "failed",
                    "failure_reason": reason,
                }
            ],
        },
    )
    return reconciliation


def test_builds_adjudicated_failed_session_ledger(tmp_path: Path) -> None:
    reconciliation = _fixture(tmp_path)
    report = build_failure_ledger(reconciliation)

    assert report["failed_session_count"] == 1
    assert report["reconciliation_sha256"] == hashlib.sha256(
        reconciliation.read_bytes()
    ).hexdigest()
    entry = report["entries"][0]
    assert entry["terminal_state"] == "FAILED"
    assert entry["right_censored"] is False
    assert entry["qualification_status"] == "EXCLUDED"
    assert entry["completed_session"] is False
    assert entry["failure_code"] == "INFRASTRUCTURE_INCOMPLETE_CHUNKED_READ"
    assert len(entry["artifact_sha256"]) == 3


def test_rejects_right_censor_substitution(tmp_path: Path) -> None:
    reconciliation = _fixture(tmp_path)
    payload = json.loads(reconciliation.read_text())
    run_path = Path(payload["attempts"][0]["run_directory"]) / "run.json"
    run = json.loads(run_path.read_text())
    run["agent_outcome"] = "INCOMPLETE"
    _write(run_path, run)

    with pytest.raises(ValueError, match="does not match the M4 failure class"):
        build_failure_ledger(reconciliation)


def test_requires_exactly_one_adjudicated_failure(tmp_path: Path) -> None:
    reconciliation = _fixture(tmp_path)
    payload = json.loads(reconciliation.read_text())
    payload["attempts"].append(dict(payload["attempts"][0]))
    _write(reconciliation, payload)

    with pytest.raises(ValueError, match="must have one adjudicated failure"):
        build_failure_ledger(reconciliation)
