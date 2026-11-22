from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_pilot_evidence import (
    BFCLPilotEvidenceError,
    BFCLPilotEvidenceRecorder,
    classify_inference_terminal,
    evaluate_paired_pilot_lifecycle,
    load_lifecycle_events,
    validate_lifecycle_trace_binding,
    validate_provider_approval,
)
from kvopt.workload.phase5_trace_contract import (
    NormalizedAgentTrace,
    TraceEvidenceLevel,
    TraceMessage,
    TraceSourceProvenance,
    TraceTerminalState,
    TraceTurn,
)
from kvopt.workload.phase5_workload_qualification import AcquisitionTerminalState


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


class _Handler:
    def _query_FC(self, _input: dict[str, object]) -> tuple[str, float]:
        return "response", 1.0


def test_recorder_captures_model_gap_and_explicit_terminal(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = BFCLPilotEvidenceRecorder(
        path=path, monotonic=_Clock(), utc_now=lambda: "2026-11-22T00:00:00Z"
    )
    handler = _Handler()
    for case_id in ("snippet", "no-snippet"):
        with recorder.bind_case(case_id), recorder.instrument_model_query(handler):
            handler._query_FC({})
            recorder.record("TOOL_CALL_EMISSION", tool_call_id=f"{case_id}:tool:1")
            recorder.record(
                "PROVIDER_REQUEST_DISPATCH",
                provider_request_id=f"{case_id}:provider:1",
            )
            recorder.record(
                "PROVIDER_RESPONSE_COMPLETE",
                provider_request_id=f"{case_id}:provider:1",
            )
            recorder.record("TOOL_RESULT_DELIVERY", tool_call_id=f"{case_id}:tool:1")
            handler._query_FC({})
            recorder.terminal(AcquisitionTerminalState.NATURAL_COMPLETION)

    report = evaluate_paired_pilot_lifecycle(
        load_lifecycle_events(path),
        expected_case_ids=("snippet", "no-snippet"),
    )
    assert report["status"] == "PASS"
    assert all(case["tool_gaps"][0]["tool_gap_seconds"] == 5.0 for case in report["cases"])


def test_lifecycle_timestamps_bind_exactly_to_normalized_trace(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = BFCLPilotEvidenceRecorder(
        path=path, monotonic=_Clock(), utc_now=lambda: "2026-11-22T00:00:00Z"
    )
    handler = _Handler()
    with recorder.bind_case("case"), recorder.instrument_model_query(handler):
        handler._query_FC({})
        handler._query_FC({})
        recorder.terminal(AcquisitionTerminalState.NATURAL_COMPLETION)
    events = load_lifecycle_events(path)
    boundaries = [
        row
        for row in events
        if row["event"] in {"MODEL_REQUEST_DISPATCH", "MODEL_RESPONSE_COMPLETE"}
    ]
    raw_sha = hashlib.sha256(b"raw").hexdigest()
    turns = []
    for ordinal in (1, 2):
        dispatch, completion = boundaries[(ordinal - 1) * 2 : ordinal * 2]
        turns.append(
            TraceTurn(
                turn_id=f"turn-{ordinal}",
                ordinal=ordinal,
                request_id=f"case:request:{ordinal}",
                messages=(TraceMessage(f"m-{ordinal}", 1, "user", "x"),),
                model_identity="model",
                submitted_at_seconds=dispatch["monotonic_seconds"],
                completed_at_seconds=completion["monotonic_seconds"],
                clock_domain="system_monotonic",
                terminal_state=TraceTerminalState.COMPLETED,
            )
        )
    trace = NormalizedAgentTrace(
        trace_id="trace",
        program_id="program",
        session_id="session",
        task_id="task",
        provenance=TraceSourceProvenance(
            source_kind="TEST",
            dataset_name="fixture",
            source_revision="revision",
            source_uri="fixture://raw",
            license_expression="TEST-ONLY",
            raw_artifact_sha256=raw_sha,
            raw_artifact_identity="raw",
        ),
        evidence_level=TraceEvidenceLevel.FULL_REPLAYABLE,
        turns=tuple(turns),
        terminal_state=TraceTerminalState.COMPLETED,
        adapter_name="fixture",
        adapter_version="1",
    )
    assert validate_lifecycle_trace_binding(
        events, case_id="case", trace=trace
    )["status"] == "PASS"


def test_terminal_before_later_event_and_wrong_mapping_fail_closed() -> None:
    events = (
        {
            "case_id": "snippet",
            "event_ordinal": 1,
            "event": "MODEL_REQUEST_DISPATCH",
            "request_id": "snippet:request:1",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 1.0,
        },
        {
            "case_id": "snippet",
            "event_ordinal": 2,
            "event": "MODEL_RESPONSE_COMPLETE",
            "request_id": "snippet:request:1",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 2.0,
        },
        {
            "case_id": "snippet",
            "event_ordinal": 3,
            "event": "SESSION_TERMINAL",
            "acquisition_terminal_state": "NATURAL_COMPLETION",
            "trace_terminal_state": "FAILED",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 3.0,
        },
        {
            "case_id": "snippet",
            "event_ordinal": 4,
            "event": "TOOL_RESULT_DELIVERY",
            "tool_call_id": "late",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 4.0,
        },
    )
    report = evaluate_paired_pilot_lifecycle(
        events, expected_case_ids=("snippet", "no-snippet")
    )
    checks = report["cases"][0]["checks"]
    assert checks["TERMINAL_IS_LAST_EVENT"] is False
    assert checks["TERMINAL_MAPPING_VALID"] is False


def test_inference_error_result_is_not_natural_completion() -> None:
    terminal, reason = classify_inference_terminal(
        "Error during inference: endpoint failed"
    )
    assert terminal is AcquisitionTerminalState.MODEL_FAILURE
    assert reason == "Error during inference: endpoint failed"


def test_two_terminals_and_model_failure_then_natural_fail_closed() -> None:
    events = (
        {
            "case_id": "snippet",
            "event_ordinal": 1,
            "event": "MODEL_REQUEST_DISPATCH",
            "request_id": "snippet:request:1",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 1.0,
        },
        {
            "case_id": "snippet",
            "event_ordinal": 2,
            "event": "MODEL_REQUEST_FAILED",
            "request_id": "snippet:request:1",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 2.0,
        },
        {
            "case_id": "snippet",
            "event_ordinal": 3,
            "event": "SESSION_TERMINAL",
            "acquisition_terminal_state": "MODEL_FAILURE",
            "trace_terminal_state": "FAILED",
            "failure_reason": "endpoint failed",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 3.0,
        },
        {
            "case_id": "snippet",
            "event_ordinal": 4,
            "event": "SESSION_TERMINAL",
            "acquisition_terminal_state": "NATURAL_COMPLETION",
            "trace_terminal_state": "COMPLETED",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 4.0,
        },
    )
    report = evaluate_paired_pilot_lifecycle(
        events, expected_case_ids=("snippet", "no-snippet")
    )
    assert report["cases"][0]["checks"]["EXACTLY_ONE_TERMINAL"] is False
    assert report["status"] == "FAIL_CLOSED"


def test_missing_terminal_or_model_completion_fails_closed() -> None:
    events = (
        {
            "case_id": "snippet",
            "event_ordinal": 1,
            "event": "MODEL_REQUEST_DISPATCH",
            "clock_domain": "system_monotonic",
            "monotonic_seconds": 1.0,
        },
    )
    report = evaluate_paired_pilot_lifecycle(
        events, expected_case_ids=("snippet", "no-snippet")
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["cases"][0]["checks"]["EXACTLY_ONE_TERMINAL"] is False


def test_failed_terminal_requires_failure_reason(tmp_path: Path) -> None:
    recorder = BFCLPilotEvidenceRecorder(path=tmp_path / "events.jsonl")
    with recorder.bind_case("case"), pytest.raises(
        BFCLPilotEvidenceError, match="failure_reason"
    ):
        recorder.terminal(AcquisitionTerminalState.PROVIDER_TIMEOUT)


def test_provider_approval_resolves_authority_and_domain_evidence(
    tmp_path: Path,
) -> None:
    evidence = {}
    for name in ("m1.md", "m4.md", "example.test.md"):
        path = tmp_path / name
        path.write_text(name)
        evidence[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    bindings = [
        {
            "native_case_id": "native-snippet",
            "formal_case_id": "formal-snippet",
            "phase5_case_index": 1,
        },
        {
            "native_case_id": "native-no-snippet",
            "formal_case_id": "formal-no-snippet",
            "phase5_case_index": 101,
        },
    ]
    approval = {
        "status": "APPROVED",
        "case_ids": ["native-snippet", "native-no-snippet"],
        "case_bindings": bindings,
        "provider": "TEST_PROVIDER",
        "api_version": "v1",
        "page_fetch_domains": ["example.test"],
        "domain_reviews": [
            {
                "domain": "example.test",
                "technical_provenance_status": "ACCEPTED",
                "publisher_permission_status": "CONFIRMED",
                "robots_status": "ALLOWED",
                "access_control_status": "PUBLIC_NO_LOGIN_NO_PAYWALL",
                "evidence_path": "example.test.md",
                "evidence_sha256": evidence["example.test.md"],
            }
        ],
        "authority_evidence": {
            "m1": {
                "evidence_path": "m1.md",
                "evidence_sha256": evidence["m1.md"],
            },
            "m4": {
                "evidence_path": "m4.md",
                "evidence_sha256": evidence["m4.md"],
            },
        },
        "m4_technical_provenance_accepted": True,
        "m1_permission_confirmed": True,
    }
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval))
    report = validate_provider_approval(
        path,
        expected_case_bindings=bindings,
        expected_provider="TEST_PROVIDER",
    )
    assert all(report["checks"].values())

    (tmp_path / "m4.md").write_text("tampered")
    with pytest.raises(BFCLPilotEvidenceError, match="not execution-ready"):
        validate_provider_approval(
            path,
            expected_case_bindings=bindings,
            expected_provider="TEST_PROVIDER",
        )


def test_provider_approval_rejects_duplicate_domain_reviews(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.md"
    evidence_path.write_text("evidence")
    sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    row = {
        "domain": "example.test",
        "technical_provenance_status": "ACCEPTED",
        "publisher_permission_status": "CONFIRMED",
        "robots_status": "ALLOWED",
        "access_control_status": "PUBLIC_NO_LOGIN_NO_PAYWALL",
        "evidence_path": "evidence.md",
        "evidence_sha256": sha,
    }
    path = tmp_path / "approval.json"
    path.write_text(
        json.dumps(
            {
                "status": "APPROVED",
                "case_ids": [],
                "case_bindings": [],
                "provider": "TEST_PROVIDER",
                "api_version": "v1",
                "page_fetch_domains": ["example.test"],
                "domain_reviews": [row, row],
                "authority_evidence": {},
                "m4_technical_provenance_accepted": True,
                "m1_permission_confirmed": True,
            }
        )
    )
    with pytest.raises(BFCLPilotEvidenceError, match="not execution-ready"):
        validate_provider_approval(
            path, expected_case_bindings=[], expected_provider="TEST_PROVIDER"
        )
