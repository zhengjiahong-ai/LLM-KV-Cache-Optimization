from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_acquisition import (
    SWE_LICENSE_COMPONENTS,
    SWE_LICENSE_EXPRESSION,
    SWE_LICENSE_NOTES,
    SWE_LICENSE_REDISTRIBUTION_STATUS,
)
from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5_swe_acquisition_adapter import (
    build_mini_swe_acquisition_record,
)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(root: Path, *, turns: int = 4) -> Path:
    instance_id = "repo__repo-1"
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "fix"},
    ]
    model_calls = []
    tool_calls = []
    for ordinal in range(1, turns + 1):
        request_id = f"{instance_id}:turn:{ordinal}"
        prompt = [dict(row) for row in messages]
        assistant = {"role": "assistant", "content": f"command {ordinal}", "extra": {}}
        model_calls.append(
            {
                "request_id": request_id,
                "messages": prompt,
                "status": "SUCCESS",
                "response_sha256": canonical_sha256(
                    {"content": assistant["content"], "extra": assistant["extra"]}
                ),
                "rendered_prompt": f"prompt {ordinal}",
                "submitted_token_ids": [1, 2, ordinal],
                "model_submit_monotonic_seconds": float(ordinal),
                "model_completion_monotonic_seconds": float(ordinal) + 0.1,
            }
        )
        messages.append(assistant)
        result = {"returncode": 0, "output": f"result {ordinal}"}
        messages.append(
            {
                "role": "user",
                "content": (
                    f"<returncode>0</returncode>\n<output>\nresult {ordinal}</output>"
                ),
            }
        )
        tool_calls.append(
            {
                "request_id": request_id,
                "status": "SUCCESS",
                "action": f"command {ordinal}",
                "result_sha256": canonical_sha256(result),
                "tool_start_monotonic_seconds": float(ordinal) + 0.2,
                "tool_completion_monotonic_seconds": float(ordinal) + 0.3,
            }
        )
    trajectory_path = root / f"{instance_id}.traj.json"
    trajectory = {"instance_id": instance_id, "messages": messages}
    _write(trajectory_path, trajectory)
    sidecar_path = root / "acquisition-sidecar.json"
    sidecar = {
        "schema_version": "continuum.w1a_acquisition_sidecar.v1",
        "program_id": instance_id,
        "trajectory_sha256": hashlib.sha256(trajectory_path.read_bytes()).hexdigest(),
        "model_calls": model_calls,
        "tool_calls": tool_calls,
    }
    _write(sidecar_path, sidecar)
    run = {
        "schema_version": "continuum.w1a_acquisition_run.v1",
        "instance_id": instance_id,
        "agent_outcome": "SUBMITTED",
        "dataset": {
            "name": "princeton-nlp/SWE-bench_Verified",
            "revision": "c104f840cc67f8b6eec6f759ebc8b2693d585d4a",
        },
        "model": {
            "model_name": "model",
            "model_revision": "model-revision",
            "tokenizer_revision": "tokenizer-revision",
        },
        "trajectory_sha256": hashlib.sha256(trajectory_path.read_bytes()).hexdigest(),
        "sidecar_sha256": hashlib.sha256(sidecar_path.read_bytes()).hexdigest(),
        "repository_git_sha": "repository-sha",
        "author_repository_git_sha": "agent-sha",
    }
    _write(root / "run.json", run)
    return root


def test_adapts_hash_bound_mini_swe_run(tmp_path: Path) -> None:
    record = build_mini_swe_acquisition_record(
        run_directory=_fixture(tmp_path),
        chat_template_sha256="a" * 64,
        license_expression=SWE_LICENSE_EXPRESSION,
        acquisition_origin="HISTORICAL_W1C_REUSE",
    )
    assert record["schema_version"] == "phase5.mini_swe_acquisition_bundle.v1"
    assert len(record["turns"]) == 4
    assert record["acquisition_origin"] == "HISTORICAL_W1C_REUSE"
    assert record["turns"][0]["messages"][-1]["tool_calls"][0]["result"] == {
        "returncode": 0,
        "output": "result 1",
    }
    assert len(record["original_artifact_sha256"]) == 3
    assert record["source"]["license"] == SWE_LICENSE_EXPRESSION
    assert record["license_components"] == SWE_LICENSE_COMPONENTS
    assert (
        record["license_redistribution_status"]
        == SWE_LICENSE_REDISTRIBUTION_STATUS
    )
    assert record["license_notes"] == SWE_LICENSE_NOTES


def test_fresh_historical_candidate_does_not_reuse_old_evidence(tmp_path: Path) -> None:
    record = build_mini_swe_acquisition_record(
        run_directory=_fixture(tmp_path),
        chat_template_sha256="a" * 64,
        license_expression=SWE_LICENSE_EXPRESSION,
        acquisition_origin="PHASE5_HISTORICAL_CANDIDATE_FRESH_REACQUISITION",
    )
    assert record["historical_candidate_provenance_only"] is True
    assert record["old_w1c_evidence_reused"] is False


def test_rejects_tampered_sidecar(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    sidecar = root / "acquisition-sidecar.json"
    sidecar.write_text(sidecar.read_text() + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="sidecar SHA-256 mismatch"):
        build_mini_swe_acquisition_record(
            run_directory=root,
            chat_template_sha256="a" * 64,
            license_expression=SWE_LICENSE_EXPRESSION,
            acquisition_origin="PHASE5_NEW_ACQUISITION",
        )


def test_rejects_noncontiguous_request_identity(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    sidecar_path = root / "acquisition-sidecar.json"
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["model_calls"][1]["request_id"] = "wrong"
    _write(sidecar_path, sidecar)
    run_path = root / "run.json"
    run = json.loads(run_path.read_text())
    run["sidecar_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    _write(run_path, run)
    with pytest.raises(ValueError, match="identity sequence mismatch"):
        build_mini_swe_acquisition_record(
            run_directory=root,
            chat_template_sha256="a" * 64,
            license_expression=SWE_LICENSE_EXPRESSION,
            acquisition_origin="PHASE5_NEW_ACQUISITION",
        )


def test_retains_trailing_failed_model_call_as_limitation(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    sidecar_path = root / "acquisition-sidecar.json"
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["model_calls"].append(
        {
            "request_id": "repo__repo-1:turn:5",
            "status": "FAILED",
            "error": "ContextLengthExceeded: maximum context reached",
        }
    )
    _write(sidecar_path, sidecar)
    run_path = root / "run.json"
    run = json.loads(run_path.read_text())
    run["agent_outcome"] = "INCOMPLETE"
    run["sidecar_sha256"] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    _write(run_path, run)

    record = build_mini_swe_acquisition_record(
        run_directory=root,
        chat_template_sha256="a" * 64,
        license_expression=SWE_LICENSE_EXPRESSION,
        acquisition_origin="PHASE5_NEW_ACQUISITION",
    )
    assert record["terminal_state"] == "RIGHT_CENSORED"
    assert len(record["turns"]) == 4
    assert record["limitations"] == [
        "TRAILING_MODEL_CALL_FAILED:ContextLengthExceeded: maximum context reached"
    ]


def test_rejects_blanket_mit_license_expression(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frozen M4 internal-research LicenseRef"):
        build_mini_swe_acquisition_record(
            run_directory=_fixture(tmp_path),
            chat_template_sha256="a" * 64,
            license_expression="MIT",
            acquisition_origin="PHASE5_NEW_ACQUISITION",
        )
