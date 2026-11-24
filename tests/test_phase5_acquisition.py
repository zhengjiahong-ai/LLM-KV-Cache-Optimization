from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_acquisition import (
    SWE_LICENSE_EXPRESSION,
    process_collection,
)


def _record(*, turns: int = 4, revision: str = "source-revision") -> dict[str, object]:
    rows = []
    for ordinal in range(1, turns + 1):
        request_id = f"program-1:turn:{ordinal}"
        tool_call = {
            "tool_call_id": f"{request_id}:tool:1",
            "tool_name": "web_search",
            "arguments": {"query": f"query {ordinal}"},
            "result": {"results": [{"url": "https://example.invalid", "text": "x"}]},
            "state": "COMPLETED",
            "started_at_seconds": float(ordinal) + 0.2,
            "ended_at_seconds": float(ordinal) + 0.3,
            "clock_domain": "source_monotonic",
        }
        rows.append(
            {
                "turn_id": f"turn-{ordinal}",
                "request_id": request_id,
                "messages": [
                    {
                        "role": "user",
                        "content": f"question {ordinal}",
                    },
                    {
                        "role": "assistant",
                        "content": "searching",
                        "tool_calls": [tool_call],
                    },
                ],
                "rendered_prompt": f"prompt {ordinal}",
                "submitted_token_ids": [1, 2, ordinal],
                "submitted_at_seconds": float(ordinal),
                "completed_at_seconds": float(ordinal) + 0.1,
                "clock_domain": "source_monotonic",
                "terminal_state": "COMPLETED",
            }
        )
    return {
        "schema_version": "phase5.bfcl_web_search_acquisition.v1",
        "trace_id": "trace-1",
        "program_id": "program-1",
        "session_id": "session-1",
        "task_id": "bfcl-1",
        "source": {
            "kind": "BFCL_V4_WEB_SEARCH",
            "dataset": "BFCL v4 Web Search",
            "revision": revision,
            "uri": "https://example.invalid/bfcl",
            "license": "Apache-2.0 AND SEARCH_RESULTS_REVIEW_REQUIRED",
        },
        "model_identity": "model@revision",
        "model_revision": "model-revision",
        "tokenizer_revision": "tokenizer-revision",
        "chat_template_sha256": "a" * 64,
        "terminal_state": "COMPLETED",
        "turns": rows,
    }


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_collection_preserves_raw_normalized_tokens_fixtures_and_qualification(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "bfcl.json", _record())
    output = tmp_path / "output"

    summary = process_collection(
        inputs=(source,),
        output_root=output,
        license_accepted=True,
        outcome_blind=True,
    )

    assert summary["trace_count"] == 1
    assert summary["qualified_count"] == 1
    assert summary["gpu_execution_authorized"] is False
    session = output / "sessions/session-1"
    assert (session / "raw/bfcl.json").read_bytes() == source.read_bytes()
    fixtures = json.loads((session / "tool-fixtures.json").read_text())
    assert len(fixtures) == 4
    qualification = json.loads((session / "qualification.json").read_text())
    assert qualification["status"] == "QUALIFIED"
    assert (output / "sha256-manifest.json").is_file()


def test_short_session_is_excluded_by_q6(tmp_path: Path) -> None:
    source = _write(tmp_path / "short.json", _record(turns=3))
    output = tmp_path / "output"
    process_collection(
        inputs=(source,),
        output_root=output,
        license_accepted=True,
        outcome_blind=True,
    )
    report = json.loads(
        (output / "sessions/session-1/qualification.json").read_text()
    )
    assert report["status"] == "EXCLUDED"
    assert report["checks"]["Q6_CONTEXT_AND_EXACT_TOKENS"] is False


def test_unresolved_source_revision_fails_closed(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "unresolved.json", _record(revision="PINNED_BY_M1")
    )
    with pytest.raises(ValueError, match="revision remains unresolved"):
        process_collection(
            inputs=(source,),
            output_root=tmp_path / "output",
            license_accepted=True,
            outcome_blind=True,
        )


def test_mini_swe_missing_license_components_fails_closed(tmp_path: Path) -> None:
    record = _record()
    record["schema_version"] = "phase5.mini_swe_acquisition_bundle.v1"
    record["source"]["license"] = SWE_LICENSE_EXPRESSION
    source = _write(tmp_path / "swe.json", record)

    with pytest.raises(TypeError, match="license_components"):
        process_collection(
            inputs=(source,),
            output_root=tmp_path / "output",
            license_accepted=True,
            outcome_blind=True,
        )


def test_missing_license_or_outcome_blindness_is_recorded_not_assumed(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "bfcl.json", _record())
    output = tmp_path / "output"
    process_collection(
        inputs=(source,),
        output_root=output,
        license_accepted=False,
        outcome_blind=False,
    )
    report = json.loads(
        (output / "sessions/session-1/qualification.json").read_text()
    )
    assert report["status"] == "EXCLUDED"
    assert set(report["failed_rules"]) == {"Q8_LICENSE", "Q9_OUTCOME_BLIND"}
