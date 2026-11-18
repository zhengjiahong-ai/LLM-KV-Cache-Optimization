"""Protocol-independent identity seal for future Phase 5 formal workloads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .phase5_replay import NSessionReplayPlan, canonical_sha256
from .phase5_trace_contract import NormalizedAgentTrace, TokenMaterialization

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def create_protocol_independent_workload_seal(
    *,
    workload_identity: str,
    traces: Sequence[NormalizedAgentTrace],
    token_materializations: Sequence[TokenMaterialization],
    replay_plan: NSessionReplayPlan,
) -> dict[str, object]:
    """Bind one workload realization without choosing arms or sample size."""

    if not isinstance(workload_identity, str) or not workload_identity:
        raise ValueError("workload_identity must be non-empty")
    if not traces:
        raise ValueError("workload seal requires normalized traces")
    if any(trace.evidence_level.value != "FULL_REPLAYABLE" for trace in traces):
        raise ValueError("formal workload seal cannot include incomplete traces")
    program_ids = [trace.program_id for trace in traces]
    if len(program_ids) != len(set(program_ids)):
        raise ValueError("workload seal program identities must be unique")
    request_ids = tuple(replay_plan.expected_native_enqueue_order)
    materialized = {row.request_id: row for row in token_materializations}
    if len(materialized) != len(token_materializations):
        raise ValueError("token materializations contain duplicate request IDs")
    if set(materialized) != set(request_ids):
        raise ValueError("token materializations do not cover replay requests")
    trace_requests = {
        turn.request_id
        for trace in traces
        for turn in trace.turns
        if turn.request_id is not None
    }
    if trace_requests != set(request_ids):
        raise ValueError("normalized trace requests differ from replay plan")
    if set(program_ids) != set(replay_plan.per_program_request_order):
        raise ValueError("normalized trace programs differ from replay plan")

    payload = {
        "schema_version": "phase5.protocol_independent_workload_seal.v1",
        "workload_identity": workload_identity,
        "formal_cohort_status": "NOT_SELECTED",
        "protocol_binding": None,
        "arm_binding": None,
        "execution_authorized": False,
        "trace_identities": {
            trace.trace_id: {
                "program_id": trace.program_id,
                "session_id": trace.session_id,
                "task_id": trace.task_id,
                "normalized_trace_sha256": trace.sha256,
                "raw_artifact_sha256": trace.provenance.raw_artifact_sha256,
                "source_revision": trace.provenance.source_revision,
                "license_expression": trace.provenance.license_expression,
            }
            for trace in sorted(traces, key=lambda row: row.trace_id)
        },
        "request_identities": {
            request_id: {
                "token_ids_sha256": materialized[request_id].token_ids_sha256,
                "rendered_prompt_sha256": materialized[
                    request_id
                ].rendered_prompt_sha256,
                "model_revision": materialized[request_id].model_revision,
                "tokenizer_revision": materialized[request_id].tokenizer_revision,
                "chat_template_sha256": materialized[
                    request_id
                ].chat_template_sha256,
            }
            for request_id in request_ids
        },
        "replay_plan": replay_plan.to_dict(),
        "replay_plan_sha256": replay_plan.sha256,
        "replay_event_identity_sha256": canonical_sha256(
            [row.event_id for row in replay_plan.events]
        ),
        "native_enqueue_order_sha256": canonical_sha256(list(request_ids)),
        "cross_system_workload_identity_sha256": canonical_sha256(
            {
                "traces": [trace.sha256 for trace in traces],
                "requests": [
                    [request_id, materialized[request_id].token_ids_sha256]
                    for request_id in request_ids
                ],
                "replay_plan_sha256": replay_plan.sha256,
            }
        ),
    }
    return {**payload, "seal_content_sha256": canonical_sha256(payload)}


def validate_protocol_independent_workload_seal(
    seal: Mapping[str, object],
) -> None:
    if seal.get("schema_version") != "phase5.protocol_independent_workload_seal.v1":
        raise ValueError("unsupported protocol-independent workload seal")
    if seal.get("formal_cohort_status") != "NOT_SELECTED":
        raise ValueError("protocol-independent seal cannot freeze a formal cohort")
    if seal.get("protocol_binding") is not None or seal.get("arm_binding") is not None:
        raise ValueError("protocol-independent seal cannot bind protocol or arms")
    if seal.get("execution_authorized") is not False:
        raise ValueError("protocol-independent seal cannot authorize execution")
    content = dict(seal)
    observed = content.pop("seal_content_sha256", None)
    if observed != canonical_sha256(content):
        raise ValueError("protocol-independent workload seal hash mismatch")
    replay = seal.get("replay_plan")
    if not isinstance(replay, Mapping):
        raise TypeError("workload seal lacks replay plan")
    if seal.get("replay_plan_sha256") != canonical_sha256(replay):
        raise ValueError("workload seal replay hash mismatch")
    events = replay.get("events")
    order = replay.get("expected_native_enqueue_order")
    if not isinstance(events, list) or not isinstance(order, list) or not order:
        raise ValueError("workload seal replay identity is incomplete")
    if seal.get("replay_event_identity_sha256") != canonical_sha256(
        [row.get("event_id") for row in events]
    ):
        raise ValueError("workload seal replay-event identity mismatch")
    if seal.get("native_enqueue_order_sha256") != canonical_sha256(order):
        raise ValueError("workload seal enqueue identity mismatch")
    requests = seal.get("request_identities")
    if not isinstance(requests, Mapping) or set(requests) != set(order):
        raise ValueError("workload seal request identity set mismatch")
    for request_id, row in requests.items():
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("workload seal contains invalid request identity")
        if not isinstance(row, Mapping):
            raise TypeError("workload seal request identity must be an object")
        for field in (
            "token_ids_sha256",
            "rendered_prompt_sha256",
            "chat_template_sha256",
        ):
            _sha(row.get(field), f"request.{field}")
