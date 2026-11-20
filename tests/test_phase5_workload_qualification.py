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
    QualificationInputs,
    qualify_formal_session,
    validate_qualified_group,
)


def _trace(index: int = 1, *, terminal=TraceTerminalState.COMPLETED):
    raw = f"raw-{index}".encode()
    request_id = f"p{index}:r1"
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
        turns=(
            TraceTurn(
                turn_id=f"turn-{index}",
                ordinal=1,
                request_id=request_id,
                messages=(TraceMessage(f"message-{index}", 1, "user", "x"),),
                model_identity="model",
                submitted_at_seconds=0.0,
                completed_at_seconds=1.0,
                clock_domain="source",
                terminal_state=terminal,
            ),
        ),
        terminal_state=terminal,
        adapter_name="fixture",
        adapter_version="1",
    )
    tokens = (1, 2, 3)
    materialization = TokenMaterialization(
        request_id=request_id,
        rendered_prompt_sha256="1" * 64,
        token_ids=tokens,
        token_ids_sha256=canonical_sha256(list(tokens)),
        model_revision="model-revision",
        tokenizer_revision="tokenizer-revision",
        chat_template_sha256="2" * 64,
    )
    return trace, materialization


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
        trace=trace,
        token_materializations=(tokens,),
        inputs=_inputs(),
        minimum_turns=1,
    )
    assert report["status"] == "QUALIFIED"
    assert report["formal_cohort_selected"] is False
    assert report["execution_authorized"] is False
    assert all(report["checks"].values())


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
        trace=trace,
        token_materializations=(tokens,),
        inputs=_inputs(**changes),
        minimum_turns=1,
    )
    assert report["status"] == "EXCLUDED"
    assert failed_rule in report["failed_rules"]


def test_right_censor_requires_reason_and_is_not_zero_filled() -> None:
    trace, tokens = _trace(terminal=TraceTerminalState.RIGHT_CENSORED)
    rejected = qualify_formal_session(
        trace=trace,
        token_materializations=(tokens,),
        inputs=_inputs(),
        minimum_turns=1,
    )
    accepted = qualify_formal_session(
        trace=trace,
        token_materializations=(tokens,),
        inputs=_inputs(censor_reason="source trace ended"),
        minimum_turns=1,
    )
    assert rejected["checks"]["Q5_TERMINAL_OR_CENSOR"] is False
    assert accepted["status"] == "QUALIFIED"
    assert accepted["terminal_class"] == "RIGHT_CENSORED"


def test_context_limit_excludes_instead_of_truncating() -> None:
    trace, tokens = _trace()
    report = qualify_formal_session(
        trace=trace,
        token_materializations=(tokens,),
        inputs=_inputs(),
        maximum_prompt_tokens=2,
        minimum_turns=1,
    )
    assert report["status"] == "EXCLUDED"
    assert report["checks"]["Q6_CONTEXT_AND_TURNS"] is False


def test_less_than_four_turns_is_excluded() -> None:
    trace, tokens = _trace()
    report = qualify_formal_session(
        trace=trace,
        token_materializations=(tokens,),
        inputs=_inputs(),
    )
    assert report["status"] == "EXCLUDED"
    assert report["checks"]["Q6_CONTEXT_AND_TURNS"] is False


def test_group_requires_four_distinct_qualified_programs() -> None:
    reports = []
    for index in range(1, 5):
        trace, tokens = _trace(index)
        reports.append(
            qualify_formal_session(
                trace=trace,
                token_materializations=(tokens,),
                inputs=_inputs(),
                minimum_turns=1,
            )
        )
    assert validate_qualified_group(reports)["status"] == "PASS"
    with pytest.raises(ValueError, match="frozen Program count"):
        validate_qualified_group(reports[:3])
