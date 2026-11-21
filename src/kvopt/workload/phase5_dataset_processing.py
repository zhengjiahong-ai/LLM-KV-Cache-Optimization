"""Reproducible Phase 5 dataset loading and qualification helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase5_replay import canonical_sha256
from .phase5_trace_contract import (
    NormalizedAgentTrace,
    TokenMaterialization,
    ToolCallRecord,
    ToolCallState,
    TraceEvidenceLevel,
    TraceMessage,
    TraceSourceProvenance,
    TraceTerminalState,
    TraceTurn,
)
from .phase5_workload_qualification import QualificationInputs, qualify_formal_session


def file_sha256(path: Path) -> str:
    """Return the byte-exact SHA-256 identity of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_normalized_trace(path: Path) -> NormalizedAgentTrace:
    """Load a normalized trace through the strict dataclass contracts."""

    value = json.loads(path.read_text(encoding="utf-8"))
    provenance = TraceSourceProvenance(**value["provenance"])
    turns: list[TraceTurn] = []
    for turn in value["turns"]:
        messages: list[TraceMessage] = []
        for message in turn["messages"]:
            calls = tuple(
                ToolCallRecord(
                    tool_call_id=call["tool_call_id"],
                    tool_name=call["tool_name"],
                    arguments=call["arguments"],
                    result=call.get("result"),
                    state=ToolCallState(call["state"]),
                    started_at_seconds=call.get("started_at_seconds"),
                    ended_at_seconds=call.get("ended_at_seconds"),
                    clock_domain=call.get("clock_domain"),
                    error=call.get("error"),
                )
                for call in message.get("tool_calls", [])
            )
            messages.append(
                TraceMessage(
                    message_id=message["message_id"],
                    ordinal=message["ordinal"],
                    role=message["role"],
                    content=message["content"],
                    tool_calls=calls,
                    source_timestamp_seconds=message.get("source_timestamp_seconds"),
                    clock_domain=message.get("clock_domain"),
                )
            )
        turns.append(
            TraceTurn(
                turn_id=turn["turn_id"],
                ordinal=turn["ordinal"],
                request_id=turn.get("request_id"),
                messages=tuple(messages),
                model_identity=turn.get("model_identity"),
                submitted_at_seconds=turn.get("submitted_at_seconds"),
                completed_at_seconds=turn.get("completed_at_seconds"),
                clock_domain=turn.get("clock_domain"),
                terminal_state=TraceTerminalState(turn["terminal_state"]),
                failure_reason=turn.get("failure_reason"),
            )
        )
    return NormalizedAgentTrace(
        trace_id=value["trace_id"],
        program_id=value["program_id"],
        session_id=value["session_id"],
        task_id=value["task_id"],
        provenance=provenance,
        evidence_level=TraceEvidenceLevel(value["evidence_level"]),
        turns=tuple(turns),
        terminal_state=TraceTerminalState(value["terminal_state"]),
        adapter_name=value["adapter_name"],
        adapter_version=value["adapter_version"],
        qualification_limitations=tuple(value.get("qualification_limitations", [])),
    )


def load_token_materializations(path: Path) -> tuple[TokenMaterialization, ...]:
    """Load exact Token IDs and revalidate every embedded identity hash."""

    values = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        TokenMaterialization(
            request_id=row["request_id"],
            rendered_prompt_sha256=row["rendered_prompt_sha256"],
            token_ids=tuple(row["token_ids"]),
            token_ids_sha256=row["token_ids_sha256"],
            model_revision=row["model_revision"],
            tokenizer_revision=row["tokenizer_revision"],
            chat_template_sha256=row["chat_template_sha256"],
        )
        for row in values
    )


def qualify_existing_session(
    *,
    session_directory: Path,
    protocol_sha256: str,
    qualification_contract_sha256: str,
    terminal_adjudication: Mapping[str, str],
    terminal_adjudication_sha256: str,
) -> dict[str, object]:
    """Requalify one immutable Session and bind the current protocol identities."""

    trace_path = session_directory / "normalized-trace.json"
    tokens_path = session_directory / "token-materialization.json"
    fixtures_path = session_directory / "tool-fixtures.json"
    prior_path = session_directory / "qualification.json"
    trace = load_normalized_trace(trace_path)
    tokens = load_token_materializations(tokens_path)
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    fixture_hashes = {
        str(call_id): canonical_sha256(payload)
        for call_id, payload in fixtures.items()
    }
    report = qualify_formal_session(
        trace=trace,
        token_materializations=tokens,
        inputs=QualificationInputs(
            license_accepted=prior["checks"]["Q8_LICENSE"] is True,
            outcome_blind=prior["checks"]["Q9_OUTCOME_BLIND"] is True,
            censor_reason=prior.get("censor_reason"),
            tool_fixture_sha256_by_call_id=fixture_hashes,
        ),
    )
    forced_reason = terminal_adjudication.get(trace.session_id)
    if forced_reason is not None:
        checks = dict(report["checks"])
        checks["Q5_TERMINAL_OR_CENSOR"] = False
        failed = [rule for rule, passed in checks.items() if not passed]
        report = {
            **report,
            "terminal_class": "EXCLUDED",
            "censor_reason": None,
            "checks": checks,
            "failed_rules": failed,
            "status": "EXCLUDED",
            "terminal_adjudication_reason": forced_reason,
        }
    bound = {
        **{key: value for key, value in report.items() if key != "qualification_sha256"},
        "protocol_sha256": protocol_sha256,
        "qualification_contract_sha256": qualification_contract_sha256,
        "terminal_adjudication_sha256": terminal_adjudication_sha256,
        "input_evidence_sha256": {
            "normalized_trace": file_sha256(trace_path),
            "token_materialization": file_sha256(tokens_path),
            "tool_fixtures": file_sha256(fixtures_path),
            "prior_qualification": file_sha256(prior_path),
        },
    }
    return {**bound, "qualification_sha256": canonical_sha256(bound)}


def build_collection_summary(
    *,
    reports: Sequence[Mapping[str, object]],
    protocol_sha256: str,
    qualification_contract_sha256: str,
) -> dict[str, object]:
    """Summarize mechanical qualification without choosing a formal Cohort."""

    statuses = Counter(str(report["status"]) for report in reports)
    failures = Counter(
        str(rule) for report in reports for rule in report["failed_rules"]
    )
    terminals = Counter(str(report["terminal_class"]) for report in reports)
    status_terminals = Counter(
        f"{report['status']}::{report['terminal_class']}" for report in reports
    )
    payload: dict[str, object] = {
        "schema_version": "phase5.acquisition_collection.v2",
        "protocol_sha256": protocol_sha256,
        "qualification_contract_sha256": qualification_contract_sha256,
        "session_count": len(reports),
        "status_counts": dict(sorted(statuses.items())),
        "terminal_class_counts": dict(sorted(terminals.items())),
        "status_terminal_class_counts": dict(sorted(status_terminals.items())),
        "rule_failure_counts": dict(sorted(failures.items())),
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
        "qualification_sha256_values": sorted(
            str(report["qualification_sha256"]) for report in reports
        ),
    }
    return {**payload, "collection_summary_sha256": canonical_sha256(payload)}
