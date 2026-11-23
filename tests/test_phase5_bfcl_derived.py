from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_derived import (
    REQUIRED_FORMAL_SYSTEMS,
    BFCLDerivedError,
    BFCLReplayTerminalState,
    BFCLSourceTerminalState,
    BFCLSyntheticTimingCursor,
    adapt_bfcl_result_record,
    build_explicit_synthetic_tool_gap_schedule,
    classify_bfcl_context_budget,
    create_bfcl_derived_workload_seal,
    evaluate_bfcl_derived_mechanical_readiness,
    evaluate_bfcl_derived_q4d_q5d,
    materialize_derived_tokens,
    validate_bfcl_derived_protocol_appendix,
    validate_bfcl_derived_workload_seal,
)


def _row() -> dict[str, object]:
    return {
        "id": "web_search_base_0",
        "result": [[[{"search_engine_query": "{}"}], "answer"]],
        "inference_log": [
            {
                "begin_of_turn_query": [
                    {"role": "developer", "content": "instructions"},
                    {"role": "user", "content": "question"},
                ],
                "step_0": [
                    {
                        "role": "assistant",
                        "content": [{"search_engine_query": "{}"}],
                    },
                    {
                        "role": "handler_log",
                        "content": "Successfully decoded model response.",
                        "model_response_decoded": ["search_engine_query(keywords='question')"],
                    },
                    {"role": "tool", "content": "[]"},
                ],
                "step_1": [
                    {"role": "assistant", "content": "answer"},
                    {"role": "handler_log", "content": "decoded"},
                ],
            }
        ],
    }


def _session():
    return adapt_bfcl_result_record(
        row=_row(),
        raw_record_sha256=hashlib.sha256(b"record").hexdigest(),
        phase5_case_id="bfcl_web_search_0:snippet",
        source_case_id="web_search_0",
        search_mode="SNIPPET",
    )


def test_frozen_protocol_appendix_hashes_and_contracts_validate() -> None:
    path = Path("configs/phase5/phase5-bfcl-derived-protocol-appendix-v1.json")
    identities = validate_bfcl_derived_protocol_appendix(
        json.loads(path.read_text(encoding="utf-8")),
        file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert identities["protocol_appendix_canonical_sha256"] == (
        "0d5f5b92fb03a631707cf51cb46c993f1347c80e178543cf63f9f2db7e6de52e"
    )
    assert identities["accepted_ids_sha256"] == (
        "887ee93c72b4bc40d79a743e19e53e53f1ea085b722f6a395bd2c2edb9e8518e"
    )


def test_adapter_preserves_semantics_without_inventing_time_or_terminal() -> None:
    session = _session()
    assert len(session.requests) == 2
    assert session.requests[0].prompt_messages[-1]["content"] == "question"
    assert session.requests[1].prompt_messages[-1]["role"] == "tool"
    assert session.requests[1].prompt_messages[-2]["content"] == (
        "[search_engine_query(keywords='question')]"
    )
    assert session.source_terminal_state is BFCLSourceTerminalState.SOURCE_TERMINAL_UNKNOWN
    assert session.replay_terminal_state is BFCLReplayTerminalState.REPLAY_TRACE_EXHAUSTED
    encoded = session.to_dict()
    assert encoded["observed_tool_gap_available"] is False
    assert encoded["synthetic_timing_mislabeled_as_source_evidence"] is False


def test_failed_archive_record_remains_excluded() -> None:
    row = _row()
    row["id"] = "web_search_no_snippet_51"
    row["result"] = "Error during inference: context too long"
    with pytest.raises(BFCLDerivedError, match="not a complete semantic trace"):
        adapt_bfcl_result_record(
            row=row,
            raw_record_sha256="a" * 64,
            phase5_case_id="bfcl_web_search_51:no_snippet",
            source_case_id="web_search_51",
            search_mode="NO_SNIPPET",
        )


def test_synthetic_gap_is_revealed_only_after_preceding_completion() -> None:
    session = _session()
    schedule = build_explicit_synthetic_tool_gap_schedule(
        session=session,
        gap_seconds=(2.5,),
        contract_sha256="b" * 64,
        generator="M4_FROZEN_TEST_GENERATOR",
    )
    assert schedule.to_dict()["timing_semantics"] == ("SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED")
    cursor = BFCLSyntheticTimingCursor(session=session, schedule=schedule)
    with pytest.raises(BFCLDerivedError, match="completion order"):
        cursor.complete_and_reveal_next_gap(session.requests[1].request_id)
    assert cursor.complete_and_reveal_next_gap(session.requests[0].request_id) == 2.5
    assert cursor.terminal_state is None
    assert cursor.complete_and_reveal_next_gap(session.requests[1].request_id) is None
    assert cursor.terminal_state is BFCLReplayTerminalState.REPLAY_TRACE_EXHAUSTED


def test_derived_tokens_are_labeled_by_seal_not_as_native_trace() -> None:
    session = _session()

    def render(messages):
        rendered = "|".join(str(row["content"]) for row in messages)
        return rendered, tuple(rendered.encode())

    tokens = materialize_derived_tokens(
        session=session,
        render_and_tokenize=render,
        model_revision="model-revision",
        tokenizer_revision="tokenizer-revision",
        chat_template_sha256="c" * 64,
    )
    schedule = build_explicit_synthetic_tool_gap_schedule(
        session=session,
        gap_seconds=(1.0,),
        contract_sha256="d" * 64,
        generator="M4_FROZEN_TEST_GENERATOR",
    )
    seal = create_bfcl_derived_workload_seal(
        sessions=(session,),
        schedules=(schedule,),
        token_materializations=tokens,
        expected_archive_record_ids=(session.archive_record_id,),
        excluded_archive_record_ids=("web_search_no_snippet_51",),
        source_archive_sha256={"SNIPPET": "e" * 64, "NO_SNIPPET": "f" * 64},
        protocol_appendix_canonical_sha256="1" * 64,
        protocol_appendix_file_sha256="4" * 64,
        context_budget_exclusions={
            "excluded_archive_record_ids": [],
            "formal_eligible_archive_record_ids": [session.archive_record_id],
        },
        tool_definitions_sha256="2" * 64,
        arrival_generator_sha256="3" * 64,
    )
    validate_bfcl_derived_workload_seal(seal)
    assert all(
        row["trace_semantics"] == "DERIVED_NOT_QWEN_NATIVE_TRACE"
        for row in seal["request_token_identities"].values()
    )
    assert seal["formal_cohort_selected"] is False
    assert seal["gpu_execution_authorized"] is False
    readiness = evaluate_bfcl_derived_mechanical_readiness(
        session=session,
        schedule=schedule,
        token_materializations=tokens,
    )
    assert readiness["status"] == "READY_FOR_M4_CONTRACT_QUALIFICATION"
    assert readiness["formal_q1_q9_status"] == ("NOT_EVALUATED_PENDING_FROZEN_M4_APPENDIX")

    tampered = {**seal, "source_terminal_state": "NATURAL_COMPLETION"}
    with pytest.raises(BFCLDerivedError, match="source terminal"):
        validate_bfcl_derived_workload_seal(tampered)


def test_q4d_q5d_pass_only_for_six_identical_complete_replays() -> None:
    session = _session()
    schedule = build_explicit_synthetic_tool_gap_schedule(
        session=session,
        gap_seconds=(1.0,),
        contract_sha256="d" * 64,
        generator="DETERMINISTIC_CONSTANT_1S_V1",
    )
    request_ids = [row.request_id for row in session.requests]
    report = evaluate_bfcl_derived_q4d_q5d(
        session=session,
        schedule=schedule,
        expected_schedule_sha256=schedule.sha256,
        system_schedule_sha256={system: schedule.sha256 for system in REQUIRED_FORMAL_SYSTEMS},
        consumed_request_ids_by_system={system: request_ids for system in REQUIRED_FORMAL_SYSTEMS},
        replay_terminal_by_system={
            system: "REPLAY_TRACE_EXHAUSTED" for system in REQUIRED_FORMAL_SYSTEMS
        },
        released_after_preceding_completion_by_system={
            system: True for system in REQUIRED_FORMAL_SYSTEMS
        },
        future_gap_visible_before_completion_by_system={
            system: False for system in REQUIRED_FORMAL_SYSTEMS
        },
    )
    assert report["status"] == "PASS"
    assert report["q4d"]["status"] == "PASS"
    assert report["q5d"]["status"] == "PASS"
    assert report["native_runtime_conformance_claimed"] is False


def test_q4d_q5d_fail_closed_on_different_schedule_or_incomplete_replay() -> None:
    session = _session()
    schedule = build_explicit_synthetic_tool_gap_schedule(
        session=session,
        gap_seconds=(1.0,),
        contract_sha256="d" * 64,
        generator="DETERMINISTIC_CONSTANT_1S_V1",
    )
    request_ids = [row.request_id for row in session.requests]
    system_hashes = {system: schedule.sha256 for system in REQUIRED_FORMAL_SYSTEMS}
    system_hashes["NATIVE"] = "0" * 64
    consumed = {system: request_ids for system in REQUIRED_FORMAL_SYSTEMS}
    consumed["DVA_ER_V1"] = request_ids[:-1]
    report = evaluate_bfcl_derived_q4d_q5d(
        session=session,
        schedule=schedule,
        expected_schedule_sha256=schedule.sha256,
        system_schedule_sha256=system_hashes,
        consumed_request_ids_by_system=consumed,
        replay_terminal_by_system={
            system: "REPLAY_TRACE_EXHAUSTED" for system in REQUIRED_FORMAL_SYSTEMS
        },
        released_after_preceding_completion_by_system={
            system: True for system in REQUIRED_FORMAL_SYSTEMS
        },
        future_gap_visible_before_completion_by_system={
            system: False for system in REQUIRED_FORMAL_SYSTEMS
        },
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["q4d"]["status"] == "FAIL_CLOSED"
    assert report["q5d"]["status"] == "FAIL_CLOSED"


def test_context_overflow_excludes_session_without_failing_collection() -> None:
    session = _session()

    def render(messages):
        return "prompt", (1, 2, 3, 4)

    tokens = materialize_derived_tokens(
        session=session,
        render_and_tokenize=render,
        model_revision="model-revision",
        tokenizer_revision="tokenizer-revision",
        chat_template_sha256="c" * 64,
    )
    report = classify_bfcl_context_budget(
        sessions=(session,),
        token_materializations_by_record={session.archive_record_id: tokens},
        maximum_prompt_tokens=3,
        maximum_generation_tokens=1,
        maximum_combined_tokens=4,
    )
    assert report["excluded_session_count"] == 1
    assert report["formal_eligible_session_count"] == 0
    assert report["exclusions"][0]["status"] == "EXCLUDED_CONTEXT_BUDGET"
    assert report["formal_cohort_selected"] is False


def test_schedule_identity_must_match_session() -> None:
    session = _session()
    schedule = build_explicit_synthetic_tool_gap_schedule(
        session=session,
        gap_seconds=(1.0,),
        contract_sha256="d" * 64,
        generator="M4_FROZEN_TEST_GENERATOR",
    )
    with pytest.raises(BFCLDerivedError, match="identity mismatch"):
        BFCLSyntheticTimingCursor(
            session=replace(session, phase5_case_id="different"),
            schedule=schedule,
        )
