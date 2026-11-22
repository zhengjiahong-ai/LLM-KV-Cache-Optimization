from __future__ import annotations

import hashlib

import pytest

from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5_trace_contract import (
    NormalizedAgentTrace,
    TokenMaterialization,
    TraceEvidenceLevel,
    TraceMessage,
    TraceSourceProvenance,
    TraceTerminalState,
    TraceTurn,
)
from kvopt.workload.phase5_workload_qualification import (
    AcquisitionTerminalState,
    QualificationInputs,
    map_acquisition_terminal_state,
    qualify_formal_session,
    validate_qualified_group,
)


def _trace(
    index: int = 1,
    *,
    terminal=TraceTerminalState.COMPLETED,
    turn_count: int = 4,
):
    raw = f"raw-{index}".encode()
    request_ids = tuple(f"p{index}:r{ordinal}" for ordinal in range(1, turn_count + 1))
    trace = NormalizedAgentTrace(
        trace_id=f"trace-{index}",
        program_id=f"program-{index}",
        session_id=f"session-{index}",
        task_id=f"task-{index}",
        provenance=TraceSourceProvenance(
            source_kind="TEST",
            dataset_name="fixture",
            source_revision="revision",
            source_uri="fixture://trace",
            license_expression="TEST-ONLY",
            raw_artifact_sha256=hashlib.sha256(raw).hexdigest(),
            raw_artifact_identity=f"raw-{index}",
        ),
        evidence_level=TraceEvidenceLevel.FULL_REPLAYABLE,
        turns=tuple(
            TraceTurn(
                turn_id=f"turn-{index}-{ordinal}",
                ordinal=ordinal,
                request_id=request_id,
                messages=(
                    TraceMessage(
                        f"message-{index}-{ordinal}", 1, "user", "x"
                    ),
                ),
                model_identity="model",
                submitted_at_seconds=float(ordinal - 1),
                completed_at_seconds=float(ordinal),
                clock_domain="source",
                terminal_state=terminal,
                failure_reason=(
                    "collector transport failure"
                    if terminal is TraceTerminalState.FAILED
                    else None
                ),
            )
            for ordinal, request_id in enumerate(request_ids, start=1)
        ),
        terminal_state=terminal,
        adapter_name="fixture",
        adapter_version="1",
    )
    token_ids = (1, 2, 3)
    materializations = tuple(
        TokenMaterialization(
            request_id=request_id,
            rendered_prompt_sha256="1" * 64,
            token_ids=token_ids,
            token_ids_sha256=canonical_sha256(list(token_ids)),
            model_revision="model-revision",
            tokenizer_revision="tokenizer-revision",
            chat_template_sha256="2" * 64,
        )
        for request_id in request_ids
    )
    return trace, materializations


def _inputs(**changes):
    values = {
        "license_accepted": True,
        "outcome_blind": True,
        "censor_reason": None,
        "tool_fixture_sha256_by_call_id": {},
    }
    values.update(changes)
    return QualificationInputs(**values)


def test_qualifies_replay_ready_session_without_selecting_cohort() -> None:
    trace, tokens = _trace()
    report = qualify_formal_session(
        trace=trace, token_materializations=tokens, inputs=_inputs()
    )
    assert report["status"] == "QUALIFIED"
    assert report["formal_cohort_selected"] is False
    assert report["execution_authorized"] is False
    assert all(report["checks"].values())
    assert len(report["observed_tool_gaps"]) == 3
    assert all(row["tool_gap_seconds"] == 0.0 for row in report["observed_tool_gaps"])


def test_q4_rejects_overlap_and_mixed_clock_gap_evidence() -> None:
    trace, tokens = _trace()
    turns = list(trace.turns)
    following = turns[1]
    turns[1] = TraceTurn(
        turn_id=following.turn_id,
        ordinal=following.ordinal,
        request_id=following.request_id,
        messages=following.messages,
        model_identity=following.model_identity,
        submitted_at_seconds=0.5,
        completed_at_seconds=following.completed_at_seconds,
        clock_domain="different-clock",
        terminal_state=following.terminal_state,
        failure_reason=following.failure_reason,
    )
    invalid = NormalizedAgentTrace(
        trace_id=trace.trace_id,
        program_id=trace.program_id,
        session_id=trace.session_id,
        task_id=trace.task_id,
        provenance=trace.provenance,
        evidence_level=trace.evidence_level,
        turns=tuple(turns),
        terminal_state=trace.terminal_state,
        adapter_name=trace.adapter_name,
        adapter_version=trace.adapter_version,
    )
    report = qualify_formal_session(
        trace=invalid, token_materializations=tokens, inputs=_inputs()
    )
    assert report["checks"]["Q4_ORDER_AND_GAPS"] is False
    assert report["observed_tool_gaps"][0]["valid"] is False


@pytest.mark.parametrize(
    ("acquisition_state", "expected"),
    [
        (AcquisitionTerminalState.NATURAL_COMPLETION, TraceTerminalState.COMPLETED),
        (
            AcquisitionTerminalState.CONTEXT_LIMIT_FAILURE,
            TraceTerminalState.FAILED,
        ),
        (AcquisitionTerminalState.TOOL_FAILURE, TraceTerminalState.FAILED),
        (AcquisitionTerminalState.PROVIDER_TIMEOUT, TraceTerminalState.FAILED),
        (
            AcquisitionTerminalState.INFRASTRUCTURE_FAILURE,
            TraceTerminalState.FAILED,
        ),
        (AcquisitionTerminalState.MODEL_FAILURE, TraceTerminalState.FAILED),
        (AcquisitionTerminalState.INCOMPLETE_EVIDENCE, TraceTerminalState.FAILED),
    ],
)
def test_acquisition_terminal_mapping(acquisition_state, expected) -> None:
    assert map_acquisition_terminal_state(acquisition_state) is expected


def test_step_limit_terminal_mapping_requires_explicit_reason() -> None:
    with pytest.raises(ValueError, match="explicit reason"):
        map_acquisition_terminal_state(
            AcquisitionTerminalState.STEP_LIMIT_RIGHT_CENSORED
        )
    assert (
        map_acquisition_terminal_state(
            AcquisitionTerminalState.STEP_LIMIT_RIGHT_CENSORED,
            censor_reason="collector step limit 100 reached",
        )
        is TraceTerminalState.RIGHT_CENSORED
    )


@pytest.mark.parametrize(
    ("changes", "failed_rule"),
    [
        ({"license_accepted": False}, "Q8_LICENSE"),
        ({"outcome_blind": False}, "Q9_OUTCOME_BLIND"),
    ],
)
def test_external_acquisition_facts_fail_closed(changes, failed_rule) -> None:
    trace, tokens = _trace()
    report = qualify_formal_session(
        trace=trace, token_materializations=tokens, inputs=_inputs(**changes)
    )
    assert report["status"] == "EXCLUDED"
    assert failed_rule in report["failed_rules"]


def test_right_censor_requires_reason_and_is_not_zero_filled() -> None:
    trace, tokens = _trace(terminal=TraceTerminalState.RIGHT_CENSORED)
    rejected = qualify_formal_session(
        trace=trace, token_materializations=tokens, inputs=_inputs()
    )
    accepted = qualify_formal_session(
        trace=trace,
        token_materializations=tokens,
        inputs=_inputs(censor_reason="source trace ended"),
    )
    assert rejected["checks"]["Q5_TERMINAL_OR_CENSOR"] is False
    assert accepted["status"] == "QUALIFIED"
    assert accepted["terminal_class"] == "RIGHT_CENSORED"


def test_context_limit_excludes_instead_of_truncating() -> None:
    trace, tokens = _trace()
    report = qualify_formal_session(
        trace=trace,
        token_materializations=tokens,
        inputs=_inputs(),
        maximum_prompt_tokens=2,
        maximum_generation_tokens=1,
        maximum_prompt_plus_generation_tokens=3,
    )
    assert report["status"] == "EXCLUDED"
    assert report["checks"]["Q6_CONTEXT_AND_EXACT_TOKENS"] is False


def test_session_above_sixteen_turns_passes_without_additional_ceiling() -> None:
    trace, tokens = _trace(turn_count=17)
    report = qualify_formal_session(
        trace=trace, token_materializations=tokens, inputs=_inputs()
    )
    assert report["status"] == "QUALIFIED"
    assert report["checks"]["Q6_CONTEXT_AND_EXACT_TOKENS"] is True


def test_session_below_four_turns_fails_q6() -> None:
    trace, tokens = _trace(turn_count=3)
    report = qualify_formal_session(
        trace=trace, token_materializations=tokens, inputs=_inputs()
    )
    assert report["status"] == "EXCLUDED"
    assert report["checks"]["Q6_CONTEXT_AND_EXACT_TOKENS"] is False


def test_missing_exact_token_evidence_fails_q2_and_q6() -> None:
    trace, tokens = _trace(turn_count=17)
    report = qualify_formal_session(
        trace=trace, token_materializations=tokens[:-1], inputs=_inputs()
    )
    assert report["status"] == "EXCLUDED"
    assert report["checks"]["Q2_EXACT_TOKEN_IDS"] is False
    assert report["checks"]["Q6_CONTEXT_AND_EXACT_TOKENS"] is False


def test_incomplete_and_invalid_censor_provenance_fail_closed() -> None:
    incomplete_trace, tokens = _trace(turn_count=17)
    incomplete_trace = NormalizedAgentTrace(
        trace_id=incomplete_trace.trace_id,
        program_id=incomplete_trace.program_id,
        session_id=incomplete_trace.session_id,
        task_id=incomplete_trace.task_id,
        provenance=incomplete_trace.provenance,
        evidence_level=TraceEvidenceLevel.PARTIAL_MESSAGES,
        turns=incomplete_trace.turns,
        terminal_state=incomplete_trace.terminal_state,
        adapter_name=incomplete_trace.adapter_name,
        adapter_version=incomplete_trace.adapter_version,
        qualification_limitations=("missing source payload",),
    )
    incomplete = qualify_formal_session(
        trace=incomplete_trace, token_materializations=tokens, inputs=_inputs()
    )
    censored_trace, censored_tokens = _trace(
        turn_count=17, terminal=TraceTerminalState.RIGHT_CENSORED
    )
    invalid_censor = qualify_formal_session(
        trace=censored_trace,
        token_materializations=censored_tokens,
        inputs=_inputs(censor_reason="  "),
    )
    assert incomplete["checks"]["Q1_COMPLETE_PAYLOAD"] is False
    assert invalid_censor["checks"]["Q5_TERMINAL_OR_CENSOR"] is False


def test_infrastructure_failure_is_not_treated_as_censoring() -> None:
    trace, tokens = _trace(turn_count=17, terminal=TraceTerminalState.FAILED)
    report = qualify_formal_session(
        trace=trace,
        token_materializations=tokens,
        inputs=_inputs(censor_reason="collector transport failure"),
    )
    assert report["status"] == "EXCLUDED"
    assert report["terminal_class"] == "EXCLUDED"
    assert report["checks"]["Q5_TERMINAL_OR_CENSOR"] is False


def test_group_requires_four_distinct_qualified_programs() -> None:
    reports = []
    for index in range(1, 5):
        trace, tokens = _trace(index)
        reports.append(
            qualify_formal_session(
                trace=trace, token_materializations=tokens, inputs=_inputs()
            )
        )
    assert validate_qualified_group(reports)["status"] == "PASS"
    with pytest.raises(ValueError, match="frozen Program count"):
        validate_qualified_group(reports[:3])
