from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5_trace_contract import (
    NormalizedAgentTrace,
    RawTraceArtifact,
    TokenMaterialization,
    ToolCallRecord,
    ToolCallState,
    TraceEvidenceLevel,
    TraceMessage,
    TraceSourceProvenance,
    TraceTerminalState,
    TraceTurn,
    normalize_trace_artifact,
    validate_trace_collection,
)


def _provenance() -> TraceSourceProvenance:
    return TraceSourceProvenance(
        source_kind="MINI_SWE_AGENT_TRAJECTORY",
        dataset_name="SWE-bench Verified",
        source_revision="revision-1",
        source_uri="https://example.invalid/source",
        license_expression="MIT AND UPSTREAM_TASK_LICENSE_REVIEW_REQUIRED",
        raw_artifact_sha256="a" * 64,
        raw_artifact_identity="raw/task-1.json",
    )


def _trace(program_id: str = "p1", request_id: str = "p1:r1") -> NormalizedAgentTrace:
    call = ToolCallRecord(
        tool_call_id=f"{request_id}:tool:1",
        tool_name="bash",
        arguments={"command": "pwd"},
        result={"stdout": "/repo"},
        state=ToolCallState.COMPLETED,
        started_at_seconds=1.2,
        ended_at_seconds=1.3,
        clock_domain="source_monotonic",
    )
    turn = TraceTurn(
        turn_id=f"{request_id}:turn",
        ordinal=1,
        request_id=request_id,
        messages=(
            TraceMessage(
                message_id=f"{request_id}:m1",
                ordinal=1,
                role="user",
                content="fix issue",
            ),
            TraceMessage(
                message_id=f"{request_id}:m2",
                ordinal=2,
                role="assistant",
                content="checking",
                tool_calls=(call,),
            ),
        ),
        model_identity="model@revision",
        submitted_at_seconds=1.0,
        completed_at_seconds=2.0,
        clock_domain="source_monotonic",
        terminal_state=TraceTerminalState.COMPLETED,
    )
    return NormalizedAgentTrace(
        trace_id=f"trace:{program_id}",
        program_id=program_id,
        session_id=f"session:{program_id}",
        task_id=f"task:{program_id}",
        provenance=_provenance(),
        evidence_level=TraceEvidenceLevel.FULL_REPLAYABLE,
        turns=(turn,),
        terminal_state=TraceTerminalState.COMPLETED,
        adapter_name="mini-swe-agent-v2",
        adapter_version="1",
    )


def test_full_trace_preserves_messages_tools_timing_and_identity() -> None:
    trace = _trace()
    encoded = trace.to_dict()

    assert encoded["evidence_level"] == "FULL_REPLAYABLE"
    assert encoded["turns"][0]["messages"][1]["tool_calls"][0]["result"] == {
        "stdout": "/repo"
    }
    assert len(trace.sha256) == 64
    report = validate_trace_collection((trace,))
    assert report["status"] == "PASS"
    assert report["formal_cohort_selected"] is False


def test_incomplete_trace_cannot_be_promoted_to_full_replayable() -> None:
    trace = _trace()
    missing_result = replace(
        trace.turns[0].messages[1].tool_calls[0],
        state=ToolCallState.MISSING_RESULT,
        result=None,
    )
    message = replace(trace.turns[0].messages[1], tool_calls=(missing_result,))
    turn = replace(trace.turns[0], messages=(trace.turns[0].messages[0], message))

    with pytest.raises(ValueError, match="missing tool result"):
        replace(trace, turns=(turn,))

    partial = replace(
        trace,
        evidence_level=TraceEvidenceLevel.PARTIAL_MESSAGES,
        turns=(turn,),
        qualification_limitations=("MISSING_TOOL_RESULT",),
    )
    assert partial.evidence_level is TraceEvidenceLevel.PARTIAL_MESSAGES


def test_failures_and_right_censoring_are_retained() -> None:
    trace = _trace()
    failed_turn = replace(
        trace.turns[0],
        terminal_state=TraceTerminalState.FAILED,
        failure_reason="tool process exited",
    )
    failed = replace(
        trace,
        turns=(failed_turn,),
        terminal_state=TraceTerminalState.FAILED,
    )
    censored = replace(
        trace,
        trace_id="trace:p2",
        program_id="p2",
        session_id="session:p2",
        turns=(replace(trace.turns[0], turn_id="p2:r1:turn", request_id="p2:r1"),),
        terminal_state=TraceTerminalState.RIGHT_CENSORED,
    )
    report = validate_trace_collection((failed, censored))
    assert report["terminal_state_counts"]["FAILED"] == 1
    assert report["terminal_state_counts"]["RIGHT_CENSORED"] == 1


def test_token_materialization_binds_complete_ids() -> None:
    token_ids = (1, 2, 3, 4)
    row = TokenMaterialization(
        request_id="p1:r1",
        rendered_prompt_sha256="b" * 64,
        token_ids=token_ids,
        token_ids_sha256=canonical_sha256(list(token_ids)),
        model_revision="model-revision",
        tokenizer_revision="tokenizer-revision",
        chat_template_sha256="c" * 64,
    )
    assert row.token_ids == token_ids

    with pytest.raises(ValueError, match="does not bind"):
        replace(row, token_ids_sha256="d" * 64)


def test_adapter_cannot_change_raw_source_binding() -> None:
    content = b'{"trajectory": []}'
    raw = RawTraceArtifact(
        artifact_identity="raw/task-1.json",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    provenance = replace(
        _provenance(),
        raw_artifact_sha256=raw.sha256,
        raw_artifact_identity=raw.artifact_identity,
    )

    class Adapter:
        adapter_name = "mini-swe-agent-v2"
        adapter_version = "1"

        def normalize(self, *, raw_artifact, provenance):
            del raw_artifact
            return replace(_trace(), provenance=provenance)

    trace = normalize_trace_artifact(
        raw_artifact=raw,
        provenance=provenance,
        adapter=Adapter(),
    )
    assert trace.provenance.raw_artifact_sha256 == raw.sha256

    with pytest.raises(ValueError, match="differs from raw artifact hash"):
        normalize_trace_artifact(
            raw_artifact=raw,
            provenance=replace(provenance, raw_artifact_sha256="f" * 64),
            adapter=Adapter(),
        )
