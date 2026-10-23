from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1b_smoke import freeze_protocol


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    session = {
        "completion_status": "RIGHT_CENSORED_INCOMPLETE",
        "right_censored": True,
        "requests": [
            {
                "request_id": "s1:turn:1",
                "token_count": 4,
                "token_ids_sha256": "one",
            },
            {
                "request_id": "s1:turn:2",
                "token_count": 8,
                "token_ids_sha256": "two",
            },
        ],
    }
    for session_id in ("s1", "s2", "s3", "s4", "s5", "s6"):
        value = dict(session)
        value["requests"] = [dict(row) for row in session["requests"]]
        for index, row in enumerate(value["requests"], start=1):
            row["request_id"] = f"{session_id}:turn:{index}"
        path = tmp_path / "replay" / "sessions" / f"{session_id}.json"
        _write(path, value)
    bindings = []
    for session_id in ("s1", "s2", "s3", "s4", "s5", "s6"):
        path = tmp_path / "replay" / "sessions" / f"{session_id}.json"
        import hashlib

        bindings.append(
            {
                "session_id": session_id,
                "path": f"sessions/{session_id}.json",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "continuum.w1b_native_replay_manifest.v1",
        "native_comparability_smoke_executed": False,
        "sessions": bindings,
    }
    manifest_path = tmp_path / "replay" / "manifest.json"
    _write(manifest_path, manifest)
    protocol = {
        "schema_version": "continuum.w1b_native_smoke_protocol.v1",
        "scope": "BOUNDED_NATIVE_COMPARABILITY_SMOKE",
        "source_replay_manifest": str(manifest_path),
        "arms": ["A0", "A1", "A2"],
        "runtime_repeats": 1,
        "schedule": {"kind": "CONTROLLED_REPLAY_SCHEDULE", "mode": "CAUSAL_REPLAY"},
        "runtime": {"max_model_len": 32},
        "groups": [
            {"group_id": f"g{i}", "sessions": [{"session_id": f"s{2*i-1}", "turns": [1, 2]}, {"session_id": f"s{2*i}", "turns": [1, 2]}]}
            for i in range(1, 4)
        ],
        "gates": {},
        "formal_performance_campaign_authorized": False,
    }
    protocol_path = tmp_path / "protocol.json"
    _write(protocol_path, protocol)
    return protocol_path


def test_freeze_protocol_binds_three_arms_and_source_tokens(tmp_path: Path) -> None:
    protocol = _fixture(tmp_path)
    result = freeze_protocol(protocol_path=protocol, output_path=tmp_path / "freeze.json")
    assert result["planned_run_count"] == 9
    assert result["native_fidelity_status"] == "PENDING"
    assert result["groups"][0]["sessions"][0]["selected_token_sha256"] == ["one", "two"]


def test_freeze_protocol_rejects_policy_outcome_driven_repeat(tmp_path: Path) -> None:
    protocol_path = _fixture(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["runtime_repeats"] = 2
    _write(protocol_path, protocol)
    with pytest.raises(ValueError, match="one run per arm"):
        freeze_protocol(protocol_path=protocol_path, output_path=tmp_path / "freeze.json")


def test_freeze_protocol_rejects_request_over_context_limit(tmp_path: Path) -> None:
    protocol_path = _fixture(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["runtime"]["max_model_len"] = 8
    _write(protocol_path, protocol)
    with pytest.raises(ValueError, match="exceeds frozen model context"):
        freeze_protocol(protocol_path=protocol_path, output_path=tmp_path / "freeze.json")
