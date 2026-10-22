import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1b_replay import (
    SESSION_SCHEMA,
    _token_digest,
    validate_replay,
)


def _write_manifest(tmp_path: Path) -> Path:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    session = {
        "schema_version": SESSION_SCHEMA,
        "session_id": "task-a",
        "completion_status": "RIGHT_CENSORED_INCOMPLETE",
        "right_censored": True,
        "requests": [
            {
                "request_id": "task-a:turn:1",
                "rendered_prompt": "hello",
                "rendered_prompt_sha256": hashlib.sha256(b"hello").hexdigest(),
                "token_ids": [1, 2],
                "token_ids_sha256": _token_digest([1, 2]),
            },
            {
                "request_id": "task-a:turn:2",
                "rendered_prompt": "hello world",
                "rendered_prompt_sha256": hashlib.sha256(b"hello world").hexdigest(),
                "token_ids": [1, 2, 3],
                "token_ids_sha256": _token_digest([1, 2, 3]),
            },
        ],
    }
    session_path = sessions / "task-a.json"
    session_path.write_text(json.dumps(session), encoding="utf-8")
    digest = hashlib.sha256(session_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "continuum.w1b_native_replay_manifest.v1",
        "formal_performance_campaign_authorized": False,
        "session_count": 1,
        "request_count": 2,
        "sessions": [
            {
                "session_id": "task-a",
                "path": "sessions/task-a.json",
                "sha256": digest,
                "request_count": 2,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_validate_replay_accepts_token_exact_prefix_growth(tmp_path: Path) -> None:
    report = validate_replay(_write_manifest(tmp_path))

    assert report["verdict"] == "PASS_MATERIALIZATION_NATIVE_FIDELITY_PENDING"
    assert report["request_count"] == 2
    assert report["checks"]["native_input_equivalence_pending"] is True


def test_validate_replay_rejects_tampered_session(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    session_path = tmp_path / "sessions" / "task-a.json"
    session = json.loads(session_path.read_text())
    session["requests"][1]["token_ids"] = [9]
    session_path.write_text(json.dumps(session), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_replay(manifest_path)


def test_validate_replay_rejects_nonprefix_turn(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    session_path = tmp_path / "sessions" / "task-a.json"
    session = json.loads(session_path.read_text())
    session["requests"][1]["token_ids"] = [9]
    session["requests"][1]["token_ids_sha256"] = _token_digest([9])
    session_path.write_text(json.dumps(session), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text())
    manifest["sessions"][0]["sha256"] = hashlib.sha256(
        session_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="token-prefix growth"):
        validate_replay(manifest_path)
