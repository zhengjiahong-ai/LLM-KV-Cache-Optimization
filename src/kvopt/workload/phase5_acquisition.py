"""Normalize and seal authorized Phase 5 Agent trace acquisitions.

The module consumes immutable acquisition records.  It does not select the
formal cohort and never upgrades incomplete evidence to a replay-ready trace.
Live search responses are emitted as hash-bound fixtures for later replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .phase5_replay import canonical_sha256
from .phase5_trace_contract import (
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
    validate_trace_collection,
)
from .phase5_workload_qualification import (
    QualificationInputs,
    qualify_formal_session,
)

MINI_SWE_SCHEMA = "phase5.mini_swe_acquisition_bundle.v1"
BFCL_SCHEMA = "phase5.bfcl_web_search_acquisition.v1"
COLLECTION_SCHEMA = "phase5.acquisition_collection.v1"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _time(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _terminal(value: object) -> TraceTerminalState:
    aliases = {
        "SUBMITTED": TraceTerminalState.COMPLETED,
        "COMPLETED": TraceTerminalState.COMPLETED,
        "FAILED": TraceTerminalState.FAILED,
        "TRUNCATED": TraceTerminalState.TRUNCATED,
        "INCOMPLETE": TraceTerminalState.RIGHT_CENSORED,
        "RIGHT_CENSORED": TraceTerminalState.RIGHT_CENSORED,
    }
    try:
        return aliases[str(value)]
    except KeyError as error:
        raise ValueError("unsupported acquisition terminal state") from error


def _tool_state(value: object) -> ToolCallState:
    try:
        return ToolCallState(str(value))
    except ValueError as error:
        raise ValueError("unsupported tool-call state") from error


def _provenance(record: Mapping[str, object], raw: RawTraceArtifact) -> TraceSourceProvenance:
    source = _mapping(record.get("source"), "source")
    revision = _text(source.get("revision"), "source revision")
    if revision == "PINNED_BY_M1":
        raise ValueError("source revision remains unresolved")
    return TraceSourceProvenance(
        source_kind=_text(source.get("kind"), "source kind"),
        dataset_name=_text(source.get("dataset"), "source dataset"),
        source_revision=revision,
        source_uri=_text(source.get("uri"), "source URI"),
        license_expression=_text(source.get("license"), "source license"),
        raw_artifact_sha256=raw.sha256,
        raw_artifact_identity=raw.artifact_identity,
    )


def _token_materialization(row: Mapping[str, object]) -> TokenMaterialization:
    tokens = tuple(_sequence(row.get("submitted_token_ids"), "submitted_token_ids"))
    if any(isinstance(token, bool) or not isinstance(token, int) for token in tokens):
        raise TypeError("submitted_token_ids must contain integers")
    rendered = _text(row.get("rendered_prompt"), "rendered_prompt")
    return TokenMaterialization(
        request_id=_text(row.get("request_id"), "request_id"),
        rendered_prompt_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        token_ids=tokens,
        token_ids_sha256=canonical_sha256(list(tokens)),
        model_revision=_text(row.get("model_revision"), "model_revision"),
        tokenizer_revision=_text(row.get("tokenizer_revision"), "tokenizer_revision"),
        chat_template_sha256=_text(
            row.get("chat_template_sha256"), "chat_template_sha256"
        ),
    )


def _tool_call(
    row: Mapping[str, object], *, request_id: str, ordinal: int
) -> ToolCallRecord:
    state = _tool_state(row.get("state", "COMPLETED"))
    result = row.get("result")
    return ToolCallRecord(
        tool_call_id=_text(
            row.get("tool_call_id", f"{request_id}:tool:{ordinal}"), "tool_call_id"
        ),
        tool_name=_text(row.get("tool_name"), "tool_name"),
        arguments=row.get("arguments"),
        result=result,
        state=state,
        started_at_seconds=_time(row.get("started_at_seconds"), "tool start"),
        ended_at_seconds=_time(row.get("ended_at_seconds"), "tool end"),
        clock_domain=_text(row.get("clock_domain"), "tool clock_domain"),
        error=str(row["error"]) if row.get("error") is not None else None,
    )


def _messages(rows: object, *, prefix: str) -> tuple[TraceMessage, ...]:
    result: list[TraceMessage] = []
    for ordinal, item in enumerate(_sequence(rows, "messages"), start=1):
        row = _mapping(item, "message")
        calls = tuple(
            _tool_call(_mapping(call, "tool call"), request_id=prefix, ordinal=index)
            for index, call in enumerate(
                _sequence(row.get("tool_calls", []), "tool_calls"), start=1
            )
        )
        result.append(
            TraceMessage(
                message_id=_text(
                    row.get("message_id", f"{prefix}:message:{ordinal}"), "message_id"
                ),
                ordinal=ordinal,
                role=_text(row.get("role"), "message role"),
                content=row.get("content"),
                tool_calls=calls,
                source_timestamp_seconds=(
                    None
                    if row.get("timestamp_seconds") is None
                    else _time(row["timestamp_seconds"], "message timestamp")
                ),
                clock_domain=(
                    None
                    if row.get("timestamp_seconds") is None
                    else _text(row.get("clock_domain"), "message clock_domain")
                ),
            )
        )
    if not result:
        raise ValueError("turn messages cannot be empty")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class AdaptedAcquisition:
    trace: NormalizedAgentTrace
    materializations: tuple[TokenMaterialization, ...]
    tool_fixtures: Mapping[str, object]


def adapt_acquisition(raw: RawTraceArtifact) -> AdaptedAcquisition:
    record = json.loads(raw.content)
    record = _mapping(record, "acquisition record")
    schema = record.get("schema_version")
    if schema not in {MINI_SWE_SCHEMA, BFCL_SCHEMA}:
        raise ValueError("unsupported Phase 5 acquisition schema")
    provenance = _provenance(record, raw)
    program_id = _text(record.get("program_id"), "program_id")
    session_id = _text(record.get("session_id"), "session_id")
    task_id = _text(record.get("task_id"), "task_id")
    model_identity = _text(record.get("model_identity"), "model_identity")
    terminal = _terminal(record.get("terminal_state"))
    turns: list[TraceTurn] = []
    materializations: list[TokenMaterialization] = []
    fixtures: dict[str, object] = {}
    for ordinal, item in enumerate(_sequence(record.get("turns"), "turns"), start=1):
        row = _mapping(item, "turn")
        request_id = _text(row.get("request_id"), "request_id")
        messages = _messages(row.get("messages"), prefix=request_id)
        materialization_row = dict(row)
        materialization_row.setdefault("model_revision", record.get("model_revision"))
        materialization_row.setdefault(
            "tokenizer_revision", record.get("tokenizer_revision")
        )
        materialization_row.setdefault(
            "chat_template_sha256", record.get("chat_template_sha256")
        )
        materializations.append(_token_materialization(materialization_row))
        for message in messages:
            for call in message.tool_calls:
                if call.result is not None:
                    fixtures[call.tool_call_id] = call.result
        turn_terminal = _terminal(row.get("terminal_state", "COMPLETED"))
        turns.append(
            TraceTurn(
                turn_id=_text(row.get("turn_id", f"{request_id}:turn"), "turn_id"),
                ordinal=ordinal,
                request_id=request_id,
                messages=messages,
                model_identity=model_identity,
                submitted_at_seconds=_time(
                    row.get("submitted_at_seconds"), "model submit"
                ),
                completed_at_seconds=_time(
                    row.get("completed_at_seconds"), "model completion"
                ),
                clock_domain=_text(row.get("clock_domain"), "model clock_domain"),
                terminal_state=turn_terminal,
                failure_reason=(
                    str(row["failure_reason"])
                    if row.get("failure_reason") is not None
                    else None
                ),
            )
        )
    evidence_level = TraceEvidenceLevel.FULL_REPLAYABLE
    limitations = tuple(str(value) for value in record.get("limitations", []))
    if limitations:
        evidence_level = TraceEvidenceLevel.PARTIAL_MESSAGES
    trace = NormalizedAgentTrace(
        trace_id=_text(record.get("trace_id"), "trace_id"),
        program_id=program_id,
        session_id=session_id,
        task_id=task_id,
        provenance=provenance,
        evidence_level=evidence_level,
        turns=tuple(turns),
        terminal_state=terminal,
        adapter_name=(
            "phase5-mini-swe-sidecar-adapter"
            if schema == MINI_SWE_SCHEMA
            else "phase5-bfcl-web-search-adapter"
        ),
        adapter_version="1",
        qualification_limitations=limitations,
    )
    return AdaptedAcquisition(trace, tuple(materializations), fixtures)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process_collection(
    *,
    inputs: Sequence[Path],
    output_root: Path,
    license_accepted: bool,
    outcome_blind: bool,
) -> dict[str, object]:
    if not inputs:
        raise ValueError("acquisition collection cannot be empty")
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    traces: list[NormalizedAgentTrace] = []
    session_rows: list[dict[str, object]] = []
    manifest_files: list[dict[str, object]] = []
    for source_path in inputs:
        content = source_path.read_bytes()
        raw = RawTraceArtifact(
            artifact_identity=source_path.name,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        adapted = adapt_acquisition(raw)
        traces.append(adapted.trace)
        session_root = output_root / "sessions" / adapted.trace.session_id
        raw_path = session_root / "raw" / source_path.name
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(content)
        normalized_path = session_root / "normalized-trace.json"
        token_path = session_root / "token-materialization.json"
        fixture_path = session_root / "tool-fixtures.json"
        fixture_hashes = {
            call_id: canonical_sha256(value)
            for call_id, value in adapted.tool_fixtures.items()
        }
        qualification = qualify_formal_session(
            trace=adapted.trace,
            token_materializations=adapted.materializations,
            inputs=QualificationInputs(
                license_accepted=license_accepted,
                outcome_blind=outcome_blind,
                censor_reason=(
                    "SOURCE_SESSION_RIGHT_CENSORED"
                    if adapted.trace.terminal_state
                    is TraceTerminalState.RIGHT_CENSORED
                    else None
                ),
                tool_fixture_sha256_by_call_id=fixture_hashes,
            ),
            maximum_prompt_tokens=32640,
            minimum_turns=4,
            maximum_turns=16,
        )
        qualification_path = session_root / "qualification.json"
        _write_json(normalized_path, adapted.trace.to_dict())
        _write_json(
            token_path,
            [
                {
                    "request_id": row.request_id,
                    "rendered_prompt_sha256": row.rendered_prompt_sha256,
                    "token_ids": list(row.token_ids),
                    "token_ids_sha256": row.token_ids_sha256,
                    "model_revision": row.model_revision,
                    "tokenizer_revision": row.tokenizer_revision,
                    "chat_template_sha256": row.chat_template_sha256,
                }
                for row in adapted.materializations
            ],
        )
        _write_json(fixture_path, adapted.tool_fixtures)
        _write_json(qualification_path, qualification)
        session_rows.append(
            {
                "trace_id": adapted.trace.trace_id,
                "program_id": adapted.trace.program_id,
                "session_id": adapted.trace.session_id,
                "source_kind": adapted.trace.provenance.source_kind,
                "raw_sha256": raw.sha256,
                "normalized_sha256": hashlib.sha256(normalized_path.read_bytes()).hexdigest(),
                "token_materialization_sha256": hashlib.sha256(
                    token_path.read_bytes()
                ).hexdigest(),
                "tool_fixtures_sha256": hashlib.sha256(
                    fixture_path.read_bytes()
                ).hexdigest(),
                "qualification_sha256": hashlib.sha256(
                    qualification_path.read_bytes()
                ).hexdigest(),
                "qualification_status": qualification["status"],
            }
        )
        for path in (raw_path, normalized_path, token_path, fixture_path, qualification_path):
            manifest_files.append(
                {
                    "path": str(path.relative_to(output_root)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
    validation = validate_trace_collection(traces)
    summary = {
        "schema_version": COLLECTION_SCHEMA,
        "status": "COMPLETE",
        "trace_count": len(traces),
        "qualified_count": sum(
            row["qualification_status"] == "QUALIFIED" for row in session_rows
        ),
        "excluded_count": sum(
            row["qualification_status"] == "EXCLUDED" for row in session_rows
        ),
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
        "trace_collection_validation": validation,
        "sessions": session_rows,
    }
    summary_path = output_root / "collection-summary.json"
    _write_json(summary_path, summary)
    manifest_files.append(
        {
            "path": summary_path.name,
            "sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "bytes": summary_path.stat().st_size,
        }
    )
    manifest = {
        "schema_version": "phase5.acquisition_sha256_manifest.v1",
        "files": sorted(manifest_files, key=lambda row: str(row["path"])),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    _write_json(output_root / "sha256-manifest.json", manifest)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--license-accepted", action="store_true")
    parser.add_argument("--outcome-blind", action="store_true")
    arguments = parser.parse_args()
    summary = process_collection(
        inputs=tuple(path.resolve() for path in arguments.input),
        output_root=arguments.output_root.resolve(),
        license_accepted=arguments.license_accepted,
        outcome_blind=arguments.outcome_blind,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
