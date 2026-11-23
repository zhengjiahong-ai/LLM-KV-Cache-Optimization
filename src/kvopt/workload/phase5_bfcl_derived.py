"""Controlled-timing contracts for the 199 accepted BFCL derived traces.

The public BFCL-Result archive preserves semantic model/tool interaction but
does not preserve observed request timing or an explicit source terminal.  This
module keeps those absences visible.  It never promotes synthetic timing into
source evidence and never maps replay exhaustion to natural completion.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .phase5_replay import canonical_sha256
from .phase5_trace_contract import TokenMaterialization

_SHA256 = re.compile(r"[0-9a-f]{64}")
ASSISTANT_TOOL_CALL_SERIALIZATION = "BFCL_HANDLER_DECODED_LIST_BRACKET_JOIN_V1"
REQUIRED_FORMAL_SYSTEMS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED_A0",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)
BFCL_DERIVED_APPENDIX_SCHEMA = "phase5.bfcl_derived_protocol_appendix.v1"
BFCL_DERIVED_Q1_Q9_STATUS = "NOT_EVALUATED"


class BFCLDerivedError(ValueError):
    """Raised when derived BFCL evidence would be mislabeled or incomplete."""


class BFCLSourceTerminalState(StrEnum):
    SOURCE_TERMINAL_UNKNOWN = "SOURCE_TERMINAL_UNKNOWN"


class BFCLReplayTerminalState(StrEnum):
    REPLAY_TRACE_EXHAUSTED = "REPLAY_TRACE_EXHAUSTED"


def validate_bfcl_derived_protocol_appendix(
    appendix: Mapping[str, Any], *, file_sha256: str | None = None
) -> dict[str, str]:
    """Validate the frozen appendix and return its bound contract identities."""

    if appendix.get("schema_version") != BFCL_DERIVED_APPENDIX_SCHEMA:
        raise BFCLDerivedError("unsupported BFCL derived protocol appendix")
    if appendix.get("status") != "FROZEN":
        raise BFCLDerivedError("BFCL derived protocol appendix is not frozen")
    if appendix.get("workload_type") != "BFCL_DERIVED_CONTROLLED_TIMING":
        raise BFCLDerivedError("BFCL derived workload type mismatch")
    canonical_payload = dict(appendix)
    observed_canonical = canonical_payload.pop("protocol_appendix_sha256", None)
    if observed_canonical != canonical_sha256(canonical_payload):
        raise BFCLDerivedError("protocol appendix canonical SHA-256 mismatch")
    if file_sha256 is not None and _SHA256.fullmatch(file_sha256) is None:
        raise BFCLDerivedError("protocol appendix file SHA-256 is invalid")

    accepted = appendix.get("accepted_archive_record_ids")
    excluded = appendix.get("excluded_archive_record_ids")
    timing = appendix.get("synthetic_tool_gap_schedule")
    if not isinstance(accepted, list) or not isinstance(excluded, list):
        raise BFCLDerivedError("protocol appendix identity lists are missing")
    if len(accepted) != 199 or len(accepted) != len(set(accepted)):
        raise BFCLDerivedError("protocol appendix accepted identity set is invalid")
    if excluded != ["web_search_no_snippet_51"] or set(accepted) & set(excluded):
        raise BFCLDerivedError("protocol appendix exclusion identity is invalid")
    accepted_ids_sha256 = canonical_sha256(accepted)
    if not isinstance(timing, dict):
        raise BFCLDerivedError("protocol appendix synthetic schedule is missing")
    gaps = timing.get("gap_seconds_by_archive_record_id")
    if (
        timing.get("generator") != "DETERMINISTIC_CONSTANT_1S_V1"
        or timing.get("timing_semantics") != "SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED"
        or not isinstance(gaps, dict)
        or set(gaps) != set(accepted)
    ):
        raise BFCLDerivedError("protocol appendix synthetic schedule contract drifted")
    flat_gaps: list[float] = []
    for record_id in accepted:
        values = gaps.get(record_id)
        if not isinstance(values, list):
            raise BFCLDerivedError("protocol appendix synthetic schedule row is invalid")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) != 1.0
            for value in values
        ):
            raise BFCLDerivedError("protocol appendix synthetic gap value drifted")
        flat_gaps.extend(float(value) for value in values)
    synthetic_schedule_sha256 = canonical_sha256(timing)
    if len(flat_gaps) != 841:
        raise BFCLDerivedError("protocol appendix synthetic boundary count mismatch")
    contract_hashes = {}
    for key in ("q4_derived", "q5_derived"):
        value = appendix.get(key)
        if not isinstance(value, dict):
            raise BFCLDerivedError(f"protocol appendix {key} contract is missing")
        contract_hashes[key] = canonical_sha256(value)
    return {
        "protocol_appendix_canonical_sha256": str(observed_canonical),
        "protocol_appendix_file_sha256": file_sha256 or "NOT_PROVIDED",
        "accepted_ids_sha256": accepted_ids_sha256,
        "synthetic_schedule_sha256": synthetic_schedule_sha256,
        "q4_derived_sha256": contract_hashes["q4_derived"],
        "q5_derived_sha256": contract_hashes["q5_derived"],
    }


@dataclass(frozen=True, slots=True)
class BFCLDerivedRequest:
    request_id: str
    ordinal: int
    prompt_messages: tuple[dict[str, Any], ...]
    assistant_response: dict[str, Any]
    tool_messages_after_response: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.request_id or self.ordinal <= 0 or not self.prompt_messages:
            raise BFCLDerivedError("derived request identity/prompt is incomplete")
        if self.assistant_response.get("role") != "assistant":
            raise BFCLDerivedError("derived request lacks its assistant response")
        if any(row.get("role") != "tool" for row in self.tool_messages_after_response):
            raise BFCLDerivedError("derived request contains a non-tool result message")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BFCLDerivedSession:
    archive_record_id: str
    phase5_case_id: str
    source_case_id: str
    search_mode: str
    source_model: str
    raw_record_sha256: str
    requests: tuple[BFCLDerivedRequest, ...]
    source_terminal_state: BFCLSourceTerminalState
    replay_terminal_state: BFCLReplayTerminalState

    def __post_init__(self) -> None:
        if self.search_mode not in {"SNIPPET", "NO_SNIPPET"}:
            raise BFCLDerivedError("unsupported BFCL search mode")
        if _SHA256.fullmatch(self.raw_record_sha256) is None:
            raise BFCLDerivedError("raw record SHA-256 is invalid")
        if not self.requests:
            raise BFCLDerivedError("derived session contains no model requests")
        if tuple(row.ordinal for row in self.requests) != tuple(range(1, len(self.requests) + 1)):
            raise BFCLDerivedError("derived request ordinals are not contiguous")
        ids = [row.request_id for row in self.requests]
        if len(ids) != len(set(ids)):
            raise BFCLDerivedError("derived session contains duplicate request IDs")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.bfcl_derived_session.v1",
            "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
            "archive_record_id": self.archive_record_id,
            "phase5_case_id": self.phase5_case_id,
            "source_case_id": self.source_case_id,
            "search_mode": self.search_mode,
            "source_model": self.source_model,
            "source_model_is_phase5_execution_model": False,
            "raw_record_sha256": self.raw_record_sha256,
            "requests": [row.to_dict() for row in self.requests],
            "source_terminal_state": self.source_terminal_state.value,
            "replay_terminal_state": self.replay_terminal_state.value,
            "observed_tool_gap_available": False,
            "synthetic_timing_mislabeled_as_source_evidence": False,
            "assistant_tool_call_serialization": ASSISTANT_TOOL_CALL_SERIALIZATION,
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


def adapt_bfcl_result_record(
    *,
    row: Mapping[str, Any],
    raw_record_sha256: str,
    phase5_case_id: str,
    source_case_id: str,
    search_mode: str,
    source_model: str = "gpt-5.2-2025-12-11-FC",
) -> BFCLDerivedSession:
    """Convert one semantic archive record without inventing time or terminal facts."""

    archive_record_id = str(row.get("id", ""))
    if not archive_record_id or isinstance(row.get("result"), str):
        raise BFCLDerivedError("archive record is not a complete semantic trace")
    logs = row.get("inference_log")
    if not isinstance(logs, list) or len(logs) != 1 or not isinstance(logs[0], dict):
        raise BFCLDerivedError("archive record lacks one complete inference log")
    log = logs[0]
    initial = log.get("begin_of_turn_query")
    if not isinstance(initial, list) or not initial:
        raise BFCLDerivedError("archive record lacks its initial messages")
    history = [dict(message) for message in initial if isinstance(message, dict)]
    if len(history) != len(initial):
        raise BFCLDerivedError("initial messages contain a non-object row")

    step_rows: list[tuple[int, list[dict[str, Any]]]] = []
    for key, value in log.items():
        if key == "begin_of_turn_query":
            continue
        if not key.startswith("step_") or not key.removeprefix("step_").isdigit():
            continue
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise BFCLDerivedError("inference step contains a non-message row")
        step_rows.append((int(key.removeprefix("step_")), list(value)))
    step_rows.sort(key=lambda row: row[0])
    if [index for index, _ in step_rows] != list(range(len(step_rows))):
        raise BFCLDerivedError("inference step indexes are not contiguous")

    requests = []
    for ordinal, (_step_index, messages) in enumerate(step_rows, start=1):
        semantic = [row for row in messages if row.get("role") != "handler_log"]
        assistants = [row for row in semantic if row.get("role") == "assistant"]
        if len(assistants) != 1 or semantic[0] is not assistants[0]:
            raise BFCLDerivedError("step must begin with exactly one assistant response")
        tool_messages = tuple(dict(row) for row in semantic[1:] if row.get("role") == "tool")
        if len(tool_messages) != len(semantic) - 1:
            raise BFCLDerivedError("step contains unsupported semantic message ordering")
        request = BFCLDerivedRequest(
            request_id=f"{phase5_case_id}:request:{ordinal}",
            ordinal=ordinal,
            prompt_messages=tuple(dict(message) for message in history),
            assistant_response=dict(assistants[0]),
            tool_messages_after_response=tool_messages,
        )
        requests.append(request)
        assistant_for_prompt = dict(assistants[0])
        if isinstance(assistant_for_prompt.get("content"), list):
            decoded = [
                row.get("model_response_decoded")
                for row in messages
                if row.get("role") == "handler_log"
                and row.get("content") == "Successfully decoded model response."
            ]
            if (
                len(decoded) != 1
                or not isinstance(decoded[0], list)
                or any(not isinstance(row, str) for row in decoded[0])
            ):
                raise BFCLDerivedError(
                    "structured assistant response lacks BFCL decoded-call evidence"
                )
            assistant_for_prompt["content"] = "[" + ", ".join(decoded[0]) + "]"
        elif not isinstance(assistant_for_prompt.get("content"), str):
            raise BFCLDerivedError("assistant response content is not replay-renderable")
        history.append(assistant_for_prompt)
        history.extend(dict(message) for message in tool_messages)

    return BFCLDerivedSession(
        archive_record_id=archive_record_id,
        phase5_case_id=phase5_case_id,
        source_case_id=source_case_id,
        search_mode=search_mode,
        source_model=source_model,
        raw_record_sha256=raw_record_sha256,
        requests=tuple(requests),
        source_terminal_state=BFCLSourceTerminalState.SOURCE_TERMINAL_UNKNOWN,
        replay_terminal_state=BFCLReplayTerminalState.REPLAY_TRACE_EXHAUSTED,
    )


@dataclass(frozen=True, slots=True)
class BFCLSyntheticToolGapSchedule:
    phase5_case_id: str
    contract_sha256: str
    gap_seconds_by_preceding_request_id: Mapping[str, float]
    generator: str

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.contract_sha256) is None:
            raise BFCLDerivedError("timing contract SHA-256 is invalid")
        for request_id, value in self.gap_seconds_by_preceding_request_id.items():
            if not request_id or isinstance(value, bool) or not isinstance(value, (int, float)):
                raise BFCLDerivedError("synthetic Tool Gap entry is invalid")
            if not math.isfinite(float(value)) or float(value) < 0:
                raise BFCLDerivedError("synthetic Tool Gap must be finite/non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.bfcl_synthetic_tool_gap_schedule.v1",
            "phase5_case_id": self.phase5_case_id,
            "timing_semantics": "SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED",
            "contract_sha256": self.contract_sha256,
            "generator": self.generator,
            "gap_seconds_by_preceding_request_id": dict(
                sorted(self.gap_seconds_by_preceding_request_id.items())
            ),
            "future_gap_visibility": "FORBIDDEN_UNTIL_PRECEDING_REQUEST_COMPLETES",
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


def build_explicit_synthetic_tool_gap_schedule(
    *,
    session: BFCLDerivedSession,
    gap_seconds: Sequence[float],
    contract_sha256: str,
    generator: str,
) -> BFCLSyntheticToolGapSchedule:
    """Freeze caller-supplied gaps; this function does not choose research values."""

    expected = max(0, len(session.requests) - 1)
    if len(gap_seconds) != expected:
        raise BFCLDerivedError("synthetic Tool Gap count differs from request boundaries")
    return BFCLSyntheticToolGapSchedule(
        phase5_case_id=session.phase5_case_id,
        contract_sha256=contract_sha256,
        gap_seconds_by_preceding_request_id={
            request.request_id: float(gap)
            for request, gap in zip(session.requests[:-1], gap_seconds, strict=True)
        },
        generator=generator,
    )


def build_frozen_schedule_from_protocol_appendix(
    *,
    session: BFCLDerivedSession,
    protocol_appendix: Mapping[str, Any],
) -> BFCLSyntheticToolGapSchedule:
    """Rebuild one expected schedule directly from the frozen appendix."""

    identities = validate_bfcl_derived_protocol_appendix(protocol_appendix)
    timing = protocol_appendix["synthetic_tool_gap_schedule"]
    if not isinstance(timing, dict):
        raise BFCLDerivedError("protocol appendix synthetic schedule is missing")
    gaps_by_record = timing["gap_seconds_by_archive_record_id"]
    if not isinstance(gaps_by_record, dict):
        raise BFCLDerivedError("protocol appendix synthetic schedule map is missing")
    gaps = gaps_by_record.get(session.archive_record_id)
    if not isinstance(gaps, list):
        raise BFCLDerivedError("session is absent from the frozen appendix schedule")
    return build_explicit_synthetic_tool_gap_schedule(
        session=session,
        gap_seconds=gaps,
        contract_sha256=identities["protocol_appendix_canonical_sha256"],
        generator=str(timing["generator"]),
    )


class BFCLSyntheticTimingCursor:
    """Reveal one frozen gap only after its preceding request completes."""

    def __init__(
        self,
        *,
        session: BFCLDerivedSession,
        schedule: BFCLSyntheticToolGapSchedule,
    ) -> None:
        if schedule.phase5_case_id != session.phase5_case_id:
            raise BFCLDerivedError("schedule/session identity mismatch")
        expected = {row.request_id for row in session.requests[:-1]}
        if set(schedule.gap_seconds_by_preceding_request_id) != expected:
            raise BFCLDerivedError("schedule does not cover exact request boundaries")
        self._requests = session.requests
        self._schedule = schedule
        self._next_completion = 0

    def complete_and_reveal_next_gap(self, request_id: str) -> float | None:
        if self._next_completion >= len(self._requests):
            raise BFCLDerivedError("replay trace is already exhausted")
        expected = self._requests[self._next_completion].request_id
        if request_id != expected:
            raise BFCLDerivedError("completion order differs from frozen trace")
        self._next_completion += 1
        return self._schedule.gap_seconds_by_preceding_request_id.get(request_id)

    @property
    def terminal_state(self) -> BFCLReplayTerminalState | None:
        if self._next_completion == len(self._requests):
            return BFCLReplayTerminalState.REPLAY_TRACE_EXHAUSTED
        return None


def materialize_derived_tokens(
    *,
    session: BFCLDerivedSession,
    render_and_tokenize: Callable[[Sequence[Mapping[str, Any]]], tuple[str, Sequence[int]]],
    model_revision: str,
    tokenizer_revision: str,
    chat_template_sha256: str,
) -> tuple[TokenMaterialization, ...]:
    """Materialize Qwen inputs while retaining the GPT source-model distinction."""

    rows = []
    for request in session.requests:
        rendered, token_ids = render_and_tokenize(request.prompt_messages)
        ids = tuple(int(value) for value in token_ids)
        rows.append(
            TokenMaterialization(
                request_id=request.request_id,
                rendered_prompt_sha256=canonical_sha256(rendered),
                token_ids=ids,
                token_ids_sha256=canonical_sha256(list(ids)),
                model_revision=model_revision,
                tokenizer_revision=tokenizer_revision,
                chat_template_sha256=chat_template_sha256,
            )
        )
    return tuple(rows)


def classify_bfcl_context_budget(
    *,
    sessions: Sequence[BFCLDerivedSession],
    token_materializations_by_record: Mapping[str, Sequence[TokenMaterialization]],
    maximum_prompt_tokens: int,
    maximum_generation_tokens: int,
    maximum_combined_tokens: int,
) -> dict[str, object]:
    """Mechanically partition accepted sessions without failing the collection."""

    if set(token_materializations_by_record) != {session.archive_record_id for session in sessions}:
        raise BFCLDerivedError("context classification token coverage mismatch")
    exclusions = []
    eligible_ids = []
    for session in sessions:
        over_limit = [
            {
                "request_id": row.request_id,
                "prompt_tokens": len(row.token_ids),
                "combined_tokens": len(row.token_ids) + maximum_generation_tokens,
            }
            for row in token_materializations_by_record[session.archive_record_id]
            if len(row.token_ids) > maximum_prompt_tokens
            or len(row.token_ids) + maximum_generation_tokens > maximum_combined_tokens
        ]
        if over_limit:
            exclusions.append(
                {
                    "archive_record_id": session.archive_record_id,
                    "phase5_case_id": session.phase5_case_id,
                    "search_mode": session.search_mode,
                    "status": "EXCLUDED_CONTEXT_BUDGET",
                    "over_limit_requests": over_limit,
                }
            )
        else:
            eligible_ids.append(session.archive_record_id)
    return {
        "schema_version": "phase5.bfcl_context_budget_exclusions.v1",
        "policy": "EXCLUDE_SESSION_FROM_FORMAL_DERIVED_ELIGIBILITY",
        "maximum_prompt_tokens": maximum_prompt_tokens,
        "maximum_generation_tokens": maximum_generation_tokens,
        "maximum_combined_tokens": maximum_combined_tokens,
        "excluded_session_count": len(exclusions),
        "excluded_request_count": sum(len(row["over_limit_requests"]) for row in exclusions),
        "excluded_archive_record_ids": [row["archive_record_id"] for row in exclusions],
        "formal_eligible_session_count": len(eligible_ids),
        "formal_eligible_archive_record_ids": eligible_ids,
        "exclusions": exclusions,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }


def create_bfcl_derived_workload_seal(
    *,
    sessions: Sequence[BFCLDerivedSession],
    schedules: Sequence[BFCLSyntheticToolGapSchedule],
    token_materializations: Sequence[TokenMaterialization],
    expected_archive_record_ids: Sequence[str],
    excluded_archive_record_ids: Sequence[str],
    source_archive_sha256: Mapping[str, str],
    protocol_appendix_canonical_sha256: str,
    protocol_appendix_file_sha256: str,
    context_budget_exclusions: Mapping[str, object],
    tool_definitions_sha256: str,
    arrival_generator_sha256: str,
) -> dict[str, object]:
    """Bind derived BFCL identities without selecting a formal Cohort."""

    if _SHA256.fullmatch(protocol_appendix_canonical_sha256) is None:
        raise BFCLDerivedError("protocol appendix canonical SHA-256 is invalid")
    if _SHA256.fullmatch(protocol_appendix_file_sha256) is None:
        raise BFCLDerivedError("protocol appendix file SHA-256 is invalid")
    if _SHA256.fullmatch(tool_definitions_sha256) is None:
        raise BFCLDerivedError("tool definitions SHA-256 is invalid")
    if _SHA256.fullmatch(arrival_generator_sha256) is None:
        raise BFCLDerivedError("arrival generator SHA-256 is invalid")
    ids = [row.archive_record_id for row in sessions]
    if ids != list(expected_archive_record_ids) or len(ids) != len(set(ids)):
        raise BFCLDerivedError("derived sessions differ from the frozen accepted IDs")
    if set(ids) & set(excluded_archive_record_ids):
        raise BFCLDerivedError("excluded archive record entered the derived workload")
    schedule_by_case = {row.phase5_case_id: row for row in schedules}
    if len(schedule_by_case) != len(schedules) or set(schedule_by_case) != {
        row.phase5_case_id for row in sessions
    }:
        raise BFCLDerivedError("synthetic schedules do not cover exact derived sessions")
    expected_requests = [request.request_id for session in sessions for request in session.requests]
    tokens = {row.request_id: row for row in token_materializations}
    if len(tokens) != len(token_materializations) or set(tokens) != set(expected_requests):
        raise BFCLDerivedError("derived Token Materialization coverage mismatch")
    if any(_SHA256.fullmatch(value) is None for value in source_archive_sha256.values()):
        raise BFCLDerivedError("source archive hash map is invalid")
    exclusion_ids = context_budget_exclusions.get("excluded_archive_record_ids")
    eligible_ids = context_budget_exclusions.get("formal_eligible_archive_record_ids")
    if (
        not isinstance(exclusion_ids, list)
        or not isinstance(eligible_ids, list)
        or set(exclusion_ids) & set(eligible_ids)
        or set(exclusion_ids) | set(eligible_ids) != set(ids)
    ):
        raise BFCLDerivedError("context-budget exclusion partition is invalid")

    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_workload_seal.v1",
        "workload_type": "BFCL_DERIVED_CONTROLLED_TIMING",
        "protocol_appendix_canonical_sha256": protocol_appendix_canonical_sha256,
        "protocol_appendix_file_sha256": protocol_appendix_file_sha256,
        "tool_definitions_sha256": tool_definitions_sha256,
        "arrival_generator_sha256": arrival_generator_sha256,
        "source_model": "gpt-5.2-2025-12-11-FC",
        "materialization_model_is_source_model": False,
        "source_terminal_state": "SOURCE_TERMINAL_UNKNOWN",
        "replay_terminal_state": "REPLAY_TRACE_EXHAUSTED",
        "source_archive_sha256": dict(sorted(source_archive_sha256.items())),
        "accepted_archive_record_ids": ids,
        "excluded_archive_record_ids": list(excluded_archive_record_ids),
        "context_budget_exclusions_sha256": canonical_sha256(context_budget_exclusions),
        "context_budget_excluded_archive_record_ids": exclusion_ids,
        "formal_eligible_archive_record_ids": eligible_ids,
        "session_identities": {
            row.phase5_case_id: {
                "archive_record_id": row.archive_record_id,
                "derived_session_sha256": row.sha256,
                "synthetic_tool_gap_schedule_sha256": schedule_by_case[row.phase5_case_id].sha256,
            }
            for row in sessions
        },
        "request_token_identities": {
            request_id: {
                "token_ids_sha256": tokens[request_id].token_ids_sha256,
                "rendered_prompt_sha256": tokens[request_id].rendered_prompt_sha256,
                "model_revision": tokens[request_id].model_revision,
                "tokenizer_revision": tokens[request_id].tokenizer_revision,
                "chat_template_sha256": tokens[request_id].chat_template_sha256,
                "trace_semantics": "DERIVED_NOT_QWEN_NATIVE_TRACE",
            }
            for request_id in expected_requests
        },
        "required_formal_systems": list(REQUIRED_FORMAL_SYSTEMS),
        "same_synthetic_schedule_required_across_systems": True,
        "cross_system_timing_identity_sha256": canonical_sha256(
            [
                [
                    row.phase5_case_id,
                    schedule_by_case[row.phase5_case_id].sha256,
                ]
                for row in sessions
            ]
        ),
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "seal_content_sha256": canonical_sha256(payload)}


def evaluate_bfcl_derived_mechanical_readiness(
    *,
    session: BFCLDerivedSession,
    schedule: BFCLSyntheticToolGapSchedule,
    token_materializations: Sequence[TokenMaterialization],
    maximum_prompt_tokens: int = 32640,
    maximum_generation_tokens: int = 128,
    maximum_context_tokens: int = 32768,
) -> dict[str, object]:
    """Check engineering evidence without claiming M4 Q1--Q9 qualification."""

    tokens = {row.request_id: row for row in token_materializations}
    expected_requests = [row.request_id for row in session.requests]
    expected_gap_requests = set(expected_requests[:-1])
    checks = {
        "DERIVED_WORKLOAD_IDENTITY": bool(session.phase5_case_id),
        "SOURCE_TERMINAL_UNKNOWN": session.source_terminal_state
        is BFCLSourceTerminalState.SOURCE_TERMINAL_UNKNOWN,
        "REPLAY_TERMINAL_EXHAUSTED": session.replay_terminal_state
        is BFCLReplayTerminalState.REPLAY_TRACE_EXHAUSTED,
        "EXACT_TOKEN_COVERAGE": len(tokens) == len(token_materializations)
        and set(tokens) == set(expected_requests),
        "SYNTHETIC_GAP_COVERAGE": schedule.phase5_case_id == session.phase5_case_id
        and set(schedule.gap_seconds_by_preceding_request_id) == expected_gap_requests,
        "SYNTHETIC_NOT_SOURCE_TIMING": schedule.to_dict()["timing_semantics"]
        == "SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED",
        "PROMPT_CONTEXT_BUDGET": all(
            len(tokens[request_id].token_ids) <= maximum_prompt_tokens
            and len(tokens[request_id].token_ids) + maximum_generation_tokens
            <= maximum_context_tokens
            for request_id in expected_requests
            if request_id in tokens
        )
        and set(tokens) == set(expected_requests),
    }
    failed = [name for name, passed in checks.items() if not passed]
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_mechanical_readiness.v1",
        "phase5_case_id": session.phase5_case_id,
        "archive_record_id": session.archive_record_id,
        "checks": checks,
        "failed_checks": failed,
        "status": "READY_FOR_M4_CONTRACT_QUALIFICATION" if not failed else "FAIL_CLOSED",
        "formal_q1_q9_status": "NOT_EVALUATED_PENDING_FROZEN_M4_APPENDIX",
        "maximum_prompt_tokens": maximum_prompt_tokens,
        "maximum_generation_tokens": maximum_generation_tokens,
        "maximum_context_tokens": maximum_context_tokens,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "readiness_sha256": canonical_sha256(payload)}


def evaluate_bfcl_derived_q4d_q5d(
    *,
    session: BFCLDerivedSession,
    schedule: BFCLSyntheticToolGapSchedule,
    frozen_appendix_schedule: BFCLSyntheticToolGapSchedule,
    frozen_appendix_schedule_map_sha256: str,
    system_schedule_sha256: Mapping[str, str],
    consumed_request_ids_by_system: Mapping[str, Sequence[str]],
    replay_terminal_by_system: Mapping[str, str],
    released_after_preceding_completion_by_system: Mapping[str, bool],
    future_gap_visible_before_completion_by_system: Mapping[str, bool],
) -> dict[str, object]:
    """Evaluate the frozen Q4D/Q5D data and deterministic replay contracts."""

    expected_requests = [row.request_id for row in session.requests]
    expected_boundaries = set(expected_requests[:-1])
    q4_checks = {
        "EXACT_BOUNDARY_COVERAGE": set(schedule.gap_seconds_by_preceding_request_id)
        == expected_boundaries,
        "FINITE_NON_NEGATIVE_GAPS": all(
            math.isfinite(float(value)) and float(value) >= 0
            for value in schedule.gap_seconds_by_preceding_request_id.values()
        ),
        "FROZEN_SCHEDULE_HASH": schedule.sha256 == frozen_appendix_schedule.sha256
        and schedule.to_dict() == frozen_appendix_schedule.to_dict()
        and _SHA256.fullmatch(frozen_appendix_schedule_map_sha256) is not None,
        "RELEASE_ONLY_AFTER_PRECEDING_COMPLETION": set(
            released_after_preceding_completion_by_system
        )
        == set(REQUIRED_FORMAL_SYSTEMS)
        and all(released_after_preceding_completion_by_system.values()),
        "NO_FUTURE_GAP_VISIBILITY": set(future_gap_visible_before_completion_by_system)
        == set(REQUIRED_FORMAL_SYSTEMS)
        and not any(future_gap_visible_before_completion_by_system.values())
        and schedule.to_dict()["future_gap_visibility"]
        == "FORBIDDEN_UNTIL_PRECEDING_REQUEST_COMPLETES",
        "SIX_SYSTEM_SCHEDULE_IDENTITY": set(system_schedule_sha256) == set(REQUIRED_FORMAL_SYSTEMS)
        and set(system_schedule_sha256.values()) == {frozen_appendix_schedule.sha256},
        "SYNTHETIC_TIMING_LABEL": schedule.to_dict()["timing_semantics"]
        == "SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED",
    }
    q5_checks = {
        "SOURCE_TERMINAL_UNKNOWN": session.source_terminal_state
        is BFCLSourceTerminalState.SOURCE_TERMINAL_UNKNOWN,
        "REPLAY_TERMINAL_EXHAUSTED": set(replay_terminal_by_system) == set(REQUIRED_FORMAL_SYSTEMS)
        and set(replay_terminal_by_system.values())
        == {BFCLReplayTerminalState.REPLAY_TRACE_EXHAUSTED.value},
        "REQUESTS_CONSUMED_EXACTLY_ONCE": set(consumed_request_ids_by_system)
        == set(REQUIRED_FORMAL_SYSTEMS)
        and all(
            list(values) == expected_requests for values in consumed_request_ids_by_system.values()
        ),
        "NO_SOURCE_TERMINAL_INFERENCE": session.to_dict().get("source_terminal_state")
        == "SOURCE_TERMINAL_UNKNOWN",
        "NO_COMPLETED_OR_RIGHT_CENSORED_MAPPING": not any(
            value in {"COMPLETED", "NATURAL_COMPLETION", "RIGHT_CENSORED"}
            for value in replay_terminal_by_system.values()
        ),
    }
    q4_failed = [name for name, passed in q4_checks.items() if not passed]
    q5_failed = [name for name, passed in q5_checks.items() if not passed]
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_derived_q4d_q5d_evaluation.v1",
        "phase5_case_id": session.phase5_case_id,
        "archive_record_id": session.archive_record_id,
        "evidence_scope": "FROZEN_DATA_AND_DETERMINISTIC_REPLAY_CONTRACT",
        "native_runtime_conformance_claimed": False,
        "frozen_appendix_schedule_sha256": frozen_appendix_schedule.sha256,
        "frozen_appendix_schedule_map_sha256": frozen_appendix_schedule_map_sha256,
        "q4d": {
            "status": "PASS" if not q4_failed else "FAIL_CLOSED",
            "checks": q4_checks,
            "failed_checks": q4_failed,
        },
        "q5d": {
            "status": "PASS" if not q5_failed else "FAIL_CLOSED",
            "checks": q5_checks,
            "failed_checks": q5_failed,
        },
        "status": "PASS" if not q4_failed and not q5_failed else "FAIL_CLOSED",
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "evaluation_sha256": canonical_sha256(payload)}


def validate_bfcl_derived_workload_seal(seal: Mapping[str, object]) -> None:
    """Fail closed on identity drift or accidental execution authorization."""

    if seal.get("schema_version") != "phase5.bfcl_derived_workload_seal.v1":
        raise BFCLDerivedError("unsupported BFCL derived workload seal")
    if seal.get("workload_type") != "BFCL_DERIVED_CONTROLLED_TIMING":
        raise BFCLDerivedError("BFCL workload type mismatch")
    if seal.get("source_terminal_state") != "SOURCE_TERMINAL_UNKNOWN":
        raise BFCLDerivedError("source terminal was incorrectly promoted")
    if seal.get("replay_terminal_state") != "REPLAY_TRACE_EXHAUSTED":
        raise BFCLDerivedError("replay terminal mismatch")
    if seal.get("required_formal_systems") != list(REQUIRED_FORMAL_SYSTEMS):
        raise BFCLDerivedError("formal system identity set mismatch")
    if seal.get("same_synthetic_schedule_required_across_systems") is not True:
        raise BFCLDerivedError("cross-system schedule equality is not required")
    if _SHA256.fullmatch(str(seal.get("protocol_appendix_canonical_sha256"))) is None:
        raise BFCLDerivedError("protocol appendix canonical identity is missing")
    if _SHA256.fullmatch(str(seal.get("protocol_appendix_file_sha256"))) is None:
        raise BFCLDerivedError("protocol appendix file identity is missing")
    if _SHA256.fullmatch(str(seal.get("context_budget_exclusions_sha256"))) is None:
        raise BFCLDerivedError("context-budget exclusion identity is missing")
    if seal.get("formal_cohort_selected") is not False:
        raise BFCLDerivedError("engineering seal cannot select a Formal Cohort")
    if seal.get("gpu_execution_authorized") is not False:
        raise BFCLDerivedError("engineering seal cannot authorize GPU execution")
    content = dict(seal)
    observed = content.pop("seal_content_sha256", None)
    if observed != canonical_sha256(content):
        raise BFCLDerivedError("BFCL derived workload seal hash mismatch")
