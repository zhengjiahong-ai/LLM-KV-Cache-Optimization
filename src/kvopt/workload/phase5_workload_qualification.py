"""Fail-closed Phase 5 formal workload qualification.

This module implements the mechanical Q1--Q9 checks from M4's workload
qualification contract.  It does not select a cohort, approve a licence, or
turn an incomplete source record into an Agent trace.  Those decisions remain
explicit inputs owned by the acquisition/freeze process.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from .phase5_replay import canonical_sha256
from .phase5_trace_contract import (
    NormalizedAgentTrace,
    TokenMaterialization,
    TraceEvidenceLevel,
    TraceTerminalState,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_RULES = (
    "Q1_COMPLETE_PAYLOAD",
    "Q2_EXACT_TOKEN_IDS",
    "Q3_IDENTITY",
    "Q4_ORDER_AND_GAPS",
    "Q5_TERMINAL_OR_CENSOR",
    "Q6_CONTEXT_AND_TURNS",
    "Q7_FROZEN_TOOLS",
    "Q8_LICENSE",
    "Q9_OUTCOME_BLIND",
)


@dataclass(frozen=True, slots=True)
class QualificationInputs:
    """Acquisition facts that cannot be inferred from normalized content."""

    license_accepted: bool
    outcome_blind: bool
    censor_reason: str | None
    tool_fixture_sha256_by_call_id: Mapping[str, str]


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def qualify_formal_session(
    *,
    trace: NormalizedAgentTrace,
    token_materializations: Sequence[TokenMaterialization],
    inputs: QualificationInputs,
    maximum_prompt_tokens: int = 32768,
    minimum_turns: int = 4,
    maximum_turns: int = 16,
) -> dict[str, object]:
    """Evaluate Q1--Q9 without making any research-design decisions."""

    if (
        maximum_prompt_tokens <= 0
        or minimum_turns <= 0
        or maximum_turns < minimum_turns
    ):
        raise ValueError("qualification limits must be positive")
    request_ids = tuple(turn.request_id for turn in trace.turns)
    materialized = {row.request_id: row for row in token_materializations}
    duplicate_materializations = len(materialized) != len(token_materializations)
    tool_calls = tuple(
        call
        for turn in trace.turns
        for message in turn.messages
        for call in message.tool_calls
    )
    tool_call_ids = tuple(call.tool_call_id for call in tool_calls)

    q1 = trace.evidence_level is TraceEvidenceLevel.FULL_REPLAYABLE
    q2 = (
        not duplicate_materializations
        and None not in request_ids
        and set(materialized) == set(request_ids)
    )
    q3 = (
        None not in request_ids
        and len(request_ids) == len(set(request_ids))
        and tuple(turn.ordinal for turn in trace.turns)
        == tuple(range(1, len(trace.turns) + 1))
    )
    submissions = tuple(turn.submitted_at_seconds for turn in trace.turns)
    q4 = (
        all(value is not None for value in submissions)
        and all(
            later >= earlier
            for earlier, later in pairwise(submissions)
        )
    )
    natural = trace.terminal_state is TraceTerminalState.COMPLETED
    censored = trace.terminal_state is TraceTerminalState.RIGHT_CENSORED
    q5 = natural or (
        censored
        and isinstance(inputs.censor_reason, str)
        and bool(inputs.censor_reason.strip())
    )
    q6 = (
        minimum_turns <= len(trace.turns) <= maximum_turns
        and q2
        and all(
            len(materialized[request_id].token_ids) <= maximum_prompt_tokens
            for request_id in request_ids
            if request_id is not None and request_id in materialized
        )
    )
    frozen_tool_ids = set(inputs.tool_fixture_sha256_by_call_id)
    q7 = (
        len(tool_call_ids) == len(set(tool_call_ids))
        and frozen_tool_ids == set(tool_call_ids)
        and all(
            _valid_sha256(value)
            for value in inputs.tool_fixture_sha256_by_call_id.values()
        )
    )
    q8 = inputs.license_accepted
    q9 = inputs.outcome_blind
    checks = dict(
        zip(_RULES, (q1, q2, q3, q4, q5, q6, q7, q8, q9), strict=True)
    )
    failed = [rule for rule in _RULES if not checks[rule]]
    payload: dict[str, object] = {
        "schema_version": "phase5.formal_session_qualification.v1",
        "trace_id": trace.trace_id,
        "program_id": trace.program_id,
        "session_id": trace.session_id,
        "source_trace_sha256": trace.sha256,
        "minimum_evidence_level": "L2_REPLAY_READY_TRACE",
        "observed_evidence_level": (
            "L2_REPLAY_READY_TRACE"
            if trace.evidence_level is TraceEvidenceLevel.FULL_REPLAYABLE
            else "BELOW_L2"
        ),
        "terminal_class": (
            "NATURAL_TERMINAL"
            if natural
            else "RIGHT_CENSORED"
            if censored
            else "EXCLUDED"
        ),
        "censor_reason": inputs.censor_reason if censored else None,
        "checks": checks,
        "failed_rules": failed,
        "status": "QUALIFIED" if not failed else "EXCLUDED",
        "formal_cohort_selected": False,
        "execution_authorized": False,
    }
    return {**payload, "qualification_sha256": canonical_sha256(payload)}


def validate_qualified_group(
    reports: Sequence[Mapping[str, object]], *, programs_per_group: int = 4
) -> dict[str, object]:
    """Require four distinct qualified Programs and one Session per Program."""

    if len(reports) != programs_per_group:
        raise ValueError("formal Group must contain the frozen Program count")
    if any(row.get("status") != "QUALIFIED" for row in reports):
        raise ValueError("formal Group contains an unqualified Session")
    program_ids = [row.get("program_id") for row in reports]
    session_ids = [row.get("session_id") for row in reports]
    if len(set(program_ids)) != programs_per_group:
        raise ValueError("formal Group Program identities must be unique")
    if len(set(session_ids)) != programs_per_group:
        raise ValueError("formal Group Session identities must be unique")
    payload = {
        "schema_version": "phase5.formal_group_qualification.v1",
        "status": "PASS",
        "program_count": programs_per_group,
        "session_count": programs_per_group,
        "qualification_sha256_values": sorted(
            str(row["qualification_sha256"]) for row in reports
        ),
        "formal_cohort_selected": False,
    }
    return {**payload, "group_qualification_sha256": canonical_sha256(payload)}
