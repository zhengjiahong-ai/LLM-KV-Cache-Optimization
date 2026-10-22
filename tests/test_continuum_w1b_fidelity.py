from __future__ import annotations

import json
from pathlib import Path

from kvopt.workload.continuum_w1b_fidelity import evaluate, materialize


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_evaluate_accepts_exact_native_input_chain(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.json"
    _write(
        fixture,
        {
            "expected_request_digests": {"s:turn:1": "digest"},
            "expected_token_counts": {"s:turn:1": 3},
        },
    )
    run_dir = tmp_path / "run"
    _write(run_dir / "run.json", {"execution_status": "success"})
    events = [
        {
            "event_index": 1,
            "event_type": "BACKEND_INPUT_MATERIALIZED",
            "request_id": "s:turn:1",
            "payload": {
                "submitted_token_ids_sha256": "digest",
                "token_count": 3,
                "w1b_replay_input_equivalence": "EXACT_TOKEN_SEQUENCE_SUBMITTED",
            },
        },
        {
            "event_index": 2,
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "request_id": "s:turn:1",
            "payload": {"native_prompt_tokens": 3},
        },
    ]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )
    result = evaluate(
        fixture_path=fixture,
        run_dir=run_dir,
        output_path=tmp_path / "report.json",
    )
    assert result["verdict"] == "PASS_NATIVE_INPUT_FIDELITY_ONLY"


def test_evaluate_fails_on_native_token_count_mismatch(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.json"
    _write(
        fixture,
        {
            "expected_request_digests": {"s:turn:1": "digest"},
            "expected_token_counts": {"s:turn:1": 3},
        },
    )
    run_dir = tmp_path / "run"
    _write(run_dir / "run.json", {"execution_status": "success"})
    events = [
        {
            "event_index": 1,
            "event_type": "BACKEND_INPUT_MATERIALIZED",
            "request_id": "s:turn:1",
            "payload": {
                "submitted_token_ids_sha256": "digest",
                "token_count": 3,
                "w1b_replay_input_equivalence": "EXACT_TOKEN_SEQUENCE_SUBMITTED",
            },
        },
        {
            "event_index": 2,
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "request_id": "s:turn:1",
            "payload": {"native_prompt_tokens": 2},
        },
    ]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )
    result = evaluate(
        fixture_path=fixture,
        run_dir=run_dir,
        output_path=tmp_path / "report.json",
    )
    assert result["verdict"] == "FAIL"


def test_materialize_separates_input_fidelity_from_ttl_costs(tmp_path: Path) -> None:
    session_path = tmp_path / "replay" / "session.json"
    requests = [
        {
            "request_id": "astropy__astropy-13236:turn:1",
            "turn_index": 1,
            "token_ids": list(range(32)),
            "token_ids_sha256": "digest",
            "token_count": 32,
        }
    ]
    _write(
        session_path,
        {
            "session_id": "astropy__astropy-13236",
            "completion_status": "OBSERVED_COMPLETE",
            "requests": requests,
        },
    )
    import hashlib

    session_sha = hashlib.sha256(session_path.read_bytes()).hexdigest()
    replay_path = tmp_path / "replay" / "manifest.json"
    _write(
        replay_path,
        {
            "schema_version": "continuum.w1b_native_replay_manifest.v1",
            "sessions": [
                {
                    "session_id": "astropy__astropy-13236",
                    "path": "session.json",
                    "sha256": session_sha,
                }
            ],
        },
    )
    freeze_path = tmp_path / "freeze.json"
    _write(
        freeze_path,
        {
            "schema_version": "continuum.w1b_native_smoke_freeze.v1",
            "native_fidelity_status": "PENDING",
            "source_replay_manifest": str(replay_path),
            "source_replay_manifest_sha256": hashlib.sha256(
                replay_path.read_bytes()
            ).hexdigest(),
            "runtime": {
                "seed": 1,
                "model": "model",
                "model_revision": "revision",
                "tokenizer": "model",
                "tokenizer_revision": "revision",
                "max_new_tokens": 1,
                "temperature": 0.0,
            },
        },
    )
    materialize(freeze_path=freeze_path, output_dir=tmp_path / "fixture")
    config = json.loads((tmp_path / "fixture" / "config.json").read_text())
    assert config["backend_options"]["w1b_native_input_fidelity_only"] is True
