"""Protocol-independent trace contracts for Phase 5 workload acquisition.

Raw source artifacts remain immutable and external to this representation.  A
normalized trace keeps only explicit, attributable facts and never promotes a
summary-only record into a replayable Agent trace.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from .phase5_replay import canonical_sha256

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_time(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric or None")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _sha(value: str, label: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


class TraceEvidenceLevel(StrEnum):
    FULL_REPLAYABLE = "FULL_REPLAYABLE"
    PARTIAL_MESSAGES = "PARTIAL_MESSAGES"
    SUMMARY_ONLY = "SUMMARY_ONLY"


class TraceTerminalState(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TRUNCATED = "TRUNCATED"
    RIGHT_CENSORED = "RIGHT_CENSORED"


class ToolCallState(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TRUNCATED = "TRUNCATED"
    MISSING_RESULT = "MISSING_RESULT"


@dataclass(frozen=True, slots=True)
class RawTraceArtifact:
    artifact_identity: str
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        _text(self.artifact_identity, "artifact_identity")
        _sha(self.sha256, "raw trace sha256")
        if not self.content:
            raise ValueError("raw trace artifact cannot be empty")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("raw trace artifact SHA-256 mismatch")


class TraceAdapter(Protocol):
    adapter_name: str
    adapter_version: str

    def normalize(
        self,
        *,
        raw_artifact: RawTraceArtifact,
        provenance: TraceSourceProvenance,
    ) -> NormalizedAgentTrace: ...


@dataclass(frozen=True, slots=True)
class TraceSourceProvenance:
    source_kind: str
    dataset_name: str
    source_revision: str
    source_uri: str
    license_expression: str
    raw_artifact_sha256: str
    raw_artifact_identity: str

    def __post_init__(self) -> None:
        for field in (
            "source_kind",
            "dataset_name",
            "source_revision",
            "source_uri",
            "license_expression",
            "raw_artifact_identity",
        ):
            _text(getattr(self, field), field)
        _sha(self.raw_artifact_sha256, "raw_artifact_sha256")


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    tool_call_id: str
    tool_name: str
    arguments: object
    result: object | None
    state: ToolCallState
    started_at_seconds: float | None = None
    ended_at_seconds: float | None = None
    clock_domain: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        _text(self.tool_call_id, "tool_call_id")
        _text(self.tool_name, "tool_name")
        start = _optional_time(self.started_at_seconds, "tool start")
        end = _optional_time(self.ended_at_seconds, "tool end")
        if (start is None) != (end is None):
            raise ValueError("tool timing must provide both start and end")
        if start is not None and end is not None and end < start:
            raise ValueError("tool end precedes tool start")
        if start is not None:
            _text(self.clock_domain, "tool clock_domain")
        if self.state is ToolCallState.COMPLETED and self.result is None:
            raise ValueError("completed tool call lacks its result")
        if self.state is ToolCallState.FAILED and not self.error:
            raise ValueError("failed tool call lacks its error")


@dataclass(frozen=True, slots=True)
class TraceMessage:
    message_id: str
    ordinal: int
    role: str
    content: object
    tool_calls: tuple[ToolCallRecord, ...] = ()
    source_timestamp_seconds: float | None = None
    clock_domain: str | None = None

    def __post_init__(self) -> None:
        _text(self.message_id, "message_id")
        if self.ordinal <= 0:
            raise ValueError("message ordinal must be positive")
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("unsupported message role")
        timestamp = _optional_time(self.source_timestamp_seconds, "message timestamp")
        if timestamp is not None:
            _text(self.clock_domain, "message clock_domain")
        call_ids = [row.tool_call_id for row in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("message contains duplicate tool_call_id values")


@dataclass(frozen=True, slots=True)
class TraceTurn:
    turn_id: str
    ordinal: int
    request_id: str | None
    messages: tuple[TraceMessage, ...]
    model_identity: str | None
    submitted_at_seconds: float | None
    completed_at_seconds: float | None
    clock_domain: str | None
    terminal_state: TraceTerminalState
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.turn_id, "turn_id")
        if self.ordinal <= 0:
            raise ValueError("turn ordinal must be positive")
        if not self.messages:
            raise ValueError("trace turn must retain at least one message")
        if tuple(row.ordinal for row in self.messages) != tuple(
            range(1, len(self.messages) + 1)
        ):
            raise ValueError("message ordinals must be contiguous")
        if len({row.message_id for row in self.messages}) != len(self.messages):
            raise ValueError("message identities must be unique within a turn")
        start = _optional_time(self.submitted_at_seconds, "model submit")
        end = _optional_time(self.completed_at_seconds, "model completion")
        if (start is None) != (end is None):
            raise ValueError("model timing must provide both submit and completion")
        if start is not None:
            _text(self.clock_domain, "model clock_domain")
            if end is not None and end <= start:
                raise ValueError("model completion must follow submission")
        if self.request_id is not None:
            _text(self.request_id, "request_id")
        if self.model_identity is not None:
            _text(self.model_identity, "model_identity")
        if self.terminal_state is TraceTerminalState.FAILED and not self.failure_reason:
            raise ValueError("failed turn lacks failure_reason")


@dataclass(frozen=True, slots=True)
class NormalizedAgentTrace:
    trace_id: str
    program_id: str
    session_id: str
    task_id: str
    provenance: TraceSourceProvenance
    evidence_level: TraceEvidenceLevel
    turns: tuple[TraceTurn, ...]
    terminal_state: TraceTerminalState
    adapter_name: str
    adapter_version: str
    qualification_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "trace_id",
            "program_id",
            "session_id",
            "task_id",
            "adapter_name",
            "adapter_version",
        ):
            _text(getattr(self, field), field)
        if not self.turns:
            raise ValueError("normalized trace must contain turns")
        if tuple(row.ordinal for row in self.turns) != tuple(
            range(1, len(self.turns) + 1)
        ):
            raise ValueError("turn ordinals must be contiguous")
        if len({row.turn_id for row in self.turns}) != len(self.turns):
            raise ValueError("turn identities must be unique")
        request_ids = [row.request_id for row in self.turns if row.request_id is not None]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("request identities must be unique")
        if self.evidence_level is TraceEvidenceLevel.FULL_REPLAYABLE:
            if self.qualification_limitations:
                raise ValueError("full replayable trace cannot carry limitations")
            for turn in self.turns:
                if turn.request_id is None or turn.model_identity is None:
                    raise ValueError("full trace lacks request or model identity")
                if turn.submitted_at_seconds is None:
                    raise ValueError("full trace lacks model timing")
                for message in turn.messages:
                    for call in message.tool_calls:
                        if call.state is ToolCallState.MISSING_RESULT:
                            raise ValueError("full trace contains missing tool result")
        elif not self.qualification_limitations:
            raise ValueError("incomplete trace must state its limitations")

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["evidence_level"] = self.evidence_level.value
        value["terminal_state"] = self.terminal_state.value
        for turn, encoded_turn in zip(self.turns, value["turns"], strict=True):
            encoded_turn["terminal_state"] = turn.terminal_state.value
            for message, encoded_message in zip(
                turn.messages, encoded_turn["messages"], strict=True
            ):
                for call, encoded_call in zip(
                    message.tool_calls, encoded_message["tool_calls"], strict=True
                ):
                    encoded_call["state"] = call.state.value
        return {"schema_version": "phase5.normalized_agent_trace.v1", **value}

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class TokenMaterialization:
    request_id: str
    rendered_prompt_sha256: str
    token_ids: tuple[int, ...]
    token_ids_sha256: str
    model_revision: str
    tokenizer_revision: str
    chat_template_sha256: str

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        for field in (
            "rendered_prompt_sha256",
            "token_ids_sha256",
            "chat_template_sha256",
        ):
            _sha(getattr(self, field), field)
        _text(self.model_revision, "model_revision")
        _text(self.tokenizer_revision, "tokenizer_revision")
        if not self.token_ids or any(
            isinstance(row, bool) or not isinstance(row, int) or row < 0
            for row in self.token_ids
        ):
            raise ValueError("token_ids must be non-empty non-negative integers")
        if canonical_sha256(list(self.token_ids)) != self.token_ids_sha256:
            raise ValueError("token_ids_sha256 does not bind complete Token IDs")


def validate_trace_collection(
    traces: Sequence[NormalizedAgentTrace],
) -> dict[str, object]:
    """Validate global identity and raw-source separation without selecting a cohort."""

    if not traces:
        raise ValueError("trace collection cannot be empty")
    for field in ("trace_id", "program_id", "session_id"):
        values = [getattr(row, field) for row in traces]
        if len(values) != len(set(values)):
            raise ValueError(f"trace collection contains duplicate {field}")
    levels = {level.value: 0 for level in TraceEvidenceLevel}
    terminals = {state.value: 0 for state in TraceTerminalState}
    for trace in traces:
        levels[trace.evidence_level.value] += 1
        terminals[trace.terminal_state.value] += 1
    return {
        "schema_version": "phase5.trace_collection_validation.v1",
        "status": "PASS",
        "trace_count": len(traces),
        "evidence_level_counts": levels,
        "terminal_state_counts": terminals,
        "formal_cohort_selected": False,
        "collection_sha256": canonical_sha256([row.to_dict() for row in traces]),
    }


def normalize_trace_artifact(
    *,
    raw_artifact: RawTraceArtifact,
    provenance: TraceSourceProvenance,
    adapter: TraceAdapter,
) -> NormalizedAgentTrace:
    """Run one adapter while preserving the immutable raw-artifact binding."""

    if provenance.raw_artifact_sha256 != raw_artifact.sha256:
        raise ValueError("Trace provenance differs from raw artifact hash")
    if provenance.raw_artifact_identity != raw_artifact.artifact_identity:
        raise ValueError("Trace provenance differs from raw artifact identity")
    trace = adapter.normalize(raw_artifact=raw_artifact, provenance=provenance)
    if trace.provenance != provenance:
        raise ValueError("Trace adapter changed source provenance")
    if trace.adapter_name != adapter.adapter_name:
        raise ValueError("Trace adapter changed adapter_name")
    if trace.adapter_version != adapter.adapter_version:
        raise ValueError("Trace adapter changed adapter_version")
    return trace


def provenance_from_record(record: Mapping[str, object]) -> TraceSourceProvenance:
    """Strict helper for source adapters; unknown fields remain in raw artifacts."""

    return TraceSourceProvenance(
        source_kind=str(record.get("source_kind", "")),
        dataset_name=str(record.get("dataset_name", "")),
        source_revision=str(record.get("source_revision", "")),
        source_uri=str(record.get("source_uri", "")),
        license_expression=str(record.get("license_expression", "")),
        raw_artifact_sha256=str(record.get("raw_artifact_sha256", "")),
        raw_artifact_identity=str(record.get("raw_artifact_identity", "")),
    )
