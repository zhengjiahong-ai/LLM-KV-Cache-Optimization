from __future__ import annotations

import base64

import pytest

from kvopt.workload.phase5_bfcl_acquisition import (
    SearchObservation,
    build_bfcl_acquisition_record,
    validate_sampling_frame,
)


def _frame() -> list[dict[str, str]]:
    return [
        {
            "case_id": f"{case_class.lower()}-{ordinal:03d}",
            "case_class": case_class,
            "case_sha256": f"{ordinal:064x}",
        }
        for case_class in ("SNIPPET", "NO_SNIPPET")
        for ordinal in range(1, 101)
    ]


def test_validates_exact_bfcl_sampling_frame() -> None:
    report = validate_sampling_frame(_frame(), source_revision="bfcl-revision")
    assert report["status"] == "PASS"
    assert report["case_count"] == 200
    assert report["case_counts"] == {"SNIPPET": 100, "NO_SNIPPET": 100}
    assert report["formal_cohort_selected"] is False


def test_rejects_duplicate_or_unbalanced_frame() -> None:
    duplicate = _frame()
    duplicate[-1]["case_id"] = duplicate[0]["case_id"]
    with pytest.raises(ValueError, match="duplicate"):
        validate_sampling_frame(duplicate, source_revision="revision")
    unbalanced = _frame()
    unbalanced[-1]["case_class"] = "SNIPPET"
    with pytest.raises(ValueError, match="100 cases per class"):
        validate_sampling_frame(unbalanced, source_revision="revision")


def test_rejects_unresolved_revision() -> None:
    with pytest.raises(ValueError, match="unresolved"):
        validate_sampling_frame(_frame(), source_revision="PINNED_BY_M1")


def test_freezes_complete_search_response_bytes() -> None:
    response = b'{"results":[{"url":"https://example.test","text":"answer"}]}'
    fixture = SearchObservation(
        provider="provider-v1",
        query="query",
        arguments={"top_k": 5},
        response_bytes=response,
        started_at_seconds=1.0,
        ended_at_seconds=2.0,
        clock_domain="WRAPPER_MONOTONIC",
        collected_at_utc="2026-11-20T00:00:00Z",
        source_urls=("https://example.test",),
        http_status=200,
    ).fixture(tool_call_id="case:tool:1")
    assert base64.b64decode(fixture["response_base64"]) == response
    assert fixture["response_byte_count"] == len(response)
    assert fixture["state"] == "COMPLETED"
    assert len(fixture["fixture_sha256"]) == 64


def test_retains_search_failure_without_synthetic_result() -> None:
    fixture = SearchObservation(
        provider="provider-v1",
        query="query",
        arguments={},
        response_bytes=b"",
        started_at_seconds=1.0,
        ended_at_seconds=1.1,
        clock_domain="WRAPPER_MONOTONIC",
        collected_at_utc="2026-11-20T00:00:00Z",
        error="TimeoutError",
    ).fixture(tool_call_id="case:tool:1")
    assert fixture["state"] == "FAILED"
    assert fixture["response_byte_count"] == 0
    assert fixture["error"] == "TimeoutError"


def test_builds_record_without_selecting_formal_cohort() -> None:
    turn = {
        "turn_id": "case:turn:1",
        "request_id": "case:request:1",
        "messages": [{"role": "user", "content": "question"}],
        "rendered_prompt": "question",
        "submitted_token_ids": [1, 2],
        "submitted_at_seconds": 1.0,
        "completed_at_seconds": 2.0,
        "clock_domain": "WRAPPER_MONOTONIC",
        "terminal_state": "COMPLETED",
    }
    record = build_bfcl_acquisition_record(
        case={
            "case_id": "case",
            "case_class": "SNIPPET",
            "case_sha256": "a" * 64,
        },
        source_revision="revision",
        source_uri="https://example.test/dataset",
        license_expression="UPSTREAM_REVIEW_REQUIRED",
        model_identity="model@revision",
        model_revision="revision",
        tokenizer_revision="revision",
        chat_template_sha256="b" * 64,
        turns=[turn],
        terminal_state="COMPLETED",
    )
    assert record["schema_version"] == "phase5.bfcl_web_search_acquisition.v1"
    assert record["case_class"] == "SNIPPET"
    assert record["formal_cohort_selected"] is False
