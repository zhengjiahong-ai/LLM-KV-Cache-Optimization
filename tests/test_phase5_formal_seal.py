from __future__ import annotations

from dataclasses import replace

import pytest

from kvopt.workload.phase5_formal_seal import (
    create_protocol_independent_workload_seal,
    validate_protocol_independent_workload_seal,
)
from kvopt.workload.phase5_replay import (
    canonical_sha256,
    fixed_arrival_plan,
    materialize_n_session_plan,
)
from kvopt.workload.phase5_trace_contract import (
    NormalizedAgentTrace,
    TokenMaterialization,
    TraceEvidenceLevel,
    TraceMessage,
    TraceSourceProvenance,
    TraceTerminalState,
    TraceTurn,
)


def _inputs():
    provenance = TraceSourceProvenance(
        source_kind="CONTROLLED_TEST",
        dataset_name="test",
        source_revision="rev",
        source_uri="https://example.invalid",
        license_expression="TEST_ONLY",
        raw_artifact_sha256="a" * 64,
        raw_artifact_identity="raw.json",
    )
    traces = []
    sessions = {}
    tokens = []
    for index in (1, 2):
        program_id = f"p{index}"
        request_id = f"{program_id}:r1"
        turn = TraceTurn(
            turn_id=f"{request_id}:turn",
            ordinal=1,
            request_id=request_id,
            messages=(
                TraceMessage(
                    message_id=f"{request_id}:message",
                    ordinal=1,
                    role="user",
                    content="prompt",
                ),
            ),
            model_identity="model@rev",
            submitted_at_seconds=10.0,
            completed_at_seconds=11.0,
            clock_domain="source_monotonic",
            terminal_state=TraceTerminalState.COMPLETED,
        )
        traces.append(
            NormalizedAgentTrace(
                trace_id=f"trace:{program_id}",
                program_id=program_id,
                session_id=f"session:{program_id}",
                task_id=f"task:{program_id}",
                provenance=provenance,
                evidence_level=TraceEvidenceLevel.FULL_REPLAYABLE,
                turns=(turn,),
                terminal_state=TraceTerminalState.COMPLETED,
                adapter_name="test",
                adapter_version="1",
            )
        )
        sessions[program_id] = [
            {
                "request_id": request_id,
                "turn_index": 1,
                "model_submit_monotonic_seconds": 10.0,
                "model_completion_monotonic_seconds": 11.0,
            }
        ]
        token_ids = (index, index + 1)
        tokens.append(
            TokenMaterialization(
                request_id=request_id,
                rendered_prompt_sha256=canonical_sha256(f"prompt:{index}"),
                token_ids=token_ids,
                token_ids_sha256=canonical_sha256(list(token_ids)),
                model_revision="model-rev",
                tokenizer_revision="tokenizer-rev",
                chat_template_sha256="b" * 64,
            )
        )
    replay = materialize_n_session_plan(
        sessions=sessions,
        arrival_plan=fixed_arrival_plan(("p1", "p2"), stagger_seconds=0.1),
    )
    return tuple(traces), tuple(tokens), replay


def test_protocol_independent_seal_binds_trace_token_replay_and_cross_system_id() -> None:
    traces, tokens, replay = _inputs()
    seal = create_protocol_independent_workload_seal(
        workload_identity="phase5-candidate-inputs-v1",
        traces=traces,
        token_materializations=tokens,
        replay_plan=replay,
    )

    validate_protocol_independent_workload_seal(seal)
    assert seal["formal_cohort_status"] == "NOT_SELECTED"
    assert seal["protocol_binding"] is None
    assert seal["arm_binding"] is None
    assert seal["execution_authorized"] is False
    assert len(seal["cross_system_workload_identity_sha256"]) == 64


def test_seal_rejects_incomplete_trace_and_missing_token_identity() -> None:
    traces, tokens, replay = _inputs()
    incomplete = replace(
        traces[0],
        evidence_level=TraceEvidenceLevel.PARTIAL_MESSAGES,
        qualification_limitations=("MISSING_TIMING",),
    )
    with pytest.raises(ValueError, match="incomplete traces"):
        create_protocol_independent_workload_seal(
            workload_identity="candidate",
            traces=(incomplete, traces[1]),
            token_materializations=tokens,
            replay_plan=replay,
        )
    with pytest.raises(ValueError, match="do not cover"):
        create_protocol_independent_workload_seal(
            workload_identity="candidate",
            traces=traces,
            token_materializations=tokens[:1],
            replay_plan=replay,
        )


def test_seal_tampering_fails_closed() -> None:
    traces, tokens, replay = _inputs()
    seal = create_protocol_independent_workload_seal(
        workload_identity="candidate",
        traces=traces,
        token_materializations=tokens,
        replay_plan=replay,
    )
    changed = dict(seal)
    changed["formal_cohort_status"] = "FROZEN"
    with pytest.raises(ValueError, match="cannot freeze"):
        validate_protocol_independent_workload_seal(changed)
