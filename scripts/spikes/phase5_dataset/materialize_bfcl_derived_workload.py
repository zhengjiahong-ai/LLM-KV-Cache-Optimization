#!/usr/bin/env python3
"""Materialize the M1-approved BFCL derived controlled-timing workload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from kvopt.workload.phase5_bfcl_derived import (
    ASSISTANT_TOOL_CALL_SERIALIZATION,
    BFCL_DERIVED_Q1_Q9_STATUS,
    REQUIRED_FORMAL_SYSTEMS,
    BFCLDerivedSession,
    BFCLSyntheticTimingCursor,
    adapt_bfcl_result_record,
    build_explicit_synthetic_tool_gap_schedule,
    build_frozen_schedule_from_protocol_appendix,
    classify_bfcl_context_budget,
    create_bfcl_derived_workload_seal,
    evaluate_bfcl_derived_mechanical_readiness,
    evaluate_bfcl_derived_q4d_q5d,
    materialize_derived_tokens,
    validate_bfcl_derived_protocol_appendix,
    validate_bfcl_derived_workload_seal,
)
from kvopt.workload.phase5_dataset_processing import file_sha256


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _load_rows(path: Path) -> list[tuple[str, dict[str, object]]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"non-object archive row at {path}:{line_number}")
        rows.append((line, value))
    return rows


def _case_identity(record_id: str) -> tuple[str, str, str]:
    if record_id.startswith("web_search_base_"):
        index = int(record_id.removeprefix("web_search_base_"))
        return f"bfcl_web_search_{index}:snippet", f"web_search_{index}", "SNIPPET"
    if record_id.startswith("web_search_no_snippet_"):
        index = int(record_id.removeprefix("web_search_no_snippet_"))
        return (
            f"bfcl_web_search_{index}:no_snippet",
            f"web_search_{index}",
            "NO_SNIPPET",
        )
    raise ValueError(f"unsupported BFCL archive record ID: {record_id}")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippet-archive", type=Path, required=True)
    parser.add_argument("--no-snippet-archive", type=Path, required=True)
    parser.add_argument("--protocol-appendix", type=Path, required=True)
    parser.add_argument("--tool-definitions", type=Path, required=True)
    parser.add_argument("--arrival-generator-manifest", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--private-evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    private_root = args.private_evidence_root.resolve()
    output = args.output.resolve()
    if output == private_root or private_root not in output.parents:
        raise ValueError("output must be a child of the private Evidence Root")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite derived evidence: {output}")

    appendix = _load_json(args.protocol_appendix)
    appendix_file_sha256 = file_sha256(args.protocol_appendix)
    appendix_identities = validate_bfcl_derived_protocol_appendix(
        appendix, file_sha256=appendix_file_sha256
    )
    if appendix.get("assistant_tool_call_serialization") != ASSISTANT_TOOL_CALL_SERIALIZATION:
        raise ValueError("BFCL assistant tool-call serialization is not frozen")
    accepted = appendix.get("accepted_archive_record_ids")
    excluded = appendix.get("excluded_archive_record_ids")
    timing = appendix.get("synthetic_tool_gap_schedule")
    if not isinstance(accepted, list) or not isinstance(excluded, list):
        raise TypeError("protocol appendix lacks accepted/excluded ID lists")
    if len(accepted) != len(set(accepted)) or set(accepted) & set(excluded):
        raise ValueError("protocol appendix archive identities overlap or duplicate")
    if not isinstance(timing, dict):
        raise TypeError("protocol appendix lacks synthetic Tool Gap schedule")
    gaps_by_record = timing.get("gap_seconds_by_archive_record_id")
    generator = timing.get("generator")
    if not isinstance(gaps_by_record, dict) or set(gaps_by_record) != set(accepted):
        raise ValueError("synthetic Tool Gap schedule does not cover accepted IDs")
    if not isinstance(generator, str) or not generator:
        raise ValueError("synthetic Tool Gap generator identity is missing")
    tool_definitions_sha256 = file_sha256(args.tool_definitions)
    arrival_generator_sha256 = file_sha256(args.arrival_generator_manifest)
    if tool_definitions_sha256 != appendix.get("tool_definitions_sha256"):
        raise ValueError("tool definitions SHA-256 differs from protocol appendix")
    if arrival_generator_sha256 != appendix.get("arrival_generator_sha256"):
        raise ValueError("arrival generator SHA-256 differs from protocol appendix")

    archive_rows = {}
    raw_lines = {}
    for path in (args.snippet_archive, args.no_snippet_archive):
        for raw_line, row in _load_rows(path):
            record_id = str(row.get("id", ""))
            if not record_id or record_id in archive_rows:
                raise ValueError("BFCL archives contain missing/duplicate record IDs")
            archive_rows[record_id] = row
            raw_lines[record_id] = raw_line
    if not set(accepted).issubset(archive_rows) or not set(excluded).issubset(archive_rows):
        raise ValueError("protocol appendix refers to an absent archive record")

    sessions: list[BFCLDerivedSession] = []
    for record_id in accepted:
        case_id, source_case_id, mode = _case_identity(str(record_id))
        raw_line = raw_lines[str(record_id)]
        sessions.append(
            adapt_bfcl_result_record(
                row=archive_rows[str(record_id)],
                raw_record_sha256=hashlib.sha256(raw_line.encode()).hexdigest(),
                phase5_case_id=case_id,
                source_case_id=source_case_id,
                search_mode=mode,
            )
        )

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    tokenizer_identity = appendix.get("tokenizer_identity")
    if not isinstance(tokenizer_identity, dict):
        raise TypeError("protocol appendix lacks tokenizer identity")
    tokenizer_config = args.tokenizer / "tokenizer_config.json"
    config = _load_json(tokenizer_config)
    chat_template = config.get("chat_template")
    if not isinstance(chat_template, str):
        raise TypeError("tokenizer chat template is missing")
    chat_template_sha256 = hashlib.sha256(chat_template.encode()).hexdigest()
    if chat_template_sha256 != tokenizer_identity.get("chat_template_sha256"):
        raise ValueError("chat template SHA-256 differs from protocol appendix")

    def render_and_tokenize(messages):
        rendered = tokenizer.apply_chat_template(
            list(messages), tokenize=False, add_generation_prompt=True
        )
        encoded = tokenizer(rendered, add_special_tokens=False)
        return rendered, encoded["input_ids"]

    appendix_canonical_sha256 = appendix_identities["protocol_appendix_canonical_sha256"]
    context_budget = appendix.get("context_budget")
    if not isinstance(context_budget, dict):
        raise TypeError("protocol appendix lacks context-budget contract")
    maximum_prompt_tokens = int(context_budget["maximum_prompt_tokens"])
    maximum_generation_tokens = int(context_budget["maximum_generation_tokens"])
    maximum_context_tokens = int(context_budget["maximum_combined_tokens"])
    schedules = []
    all_tokens = []
    materialized_by_record = {}
    schedule_by_record = {}
    readiness_by_record = {}
    output.mkdir(parents=True)
    for session in sessions:
        record_gaps = gaps_by_record[session.archive_record_id]
        if not isinstance(record_gaps, list):
            raise TypeError("synthetic Tool Gap row must be an array")
        schedule = build_explicit_synthetic_tool_gap_schedule(
            session=session,
            gap_seconds=record_gaps,
            contract_sha256=appendix_canonical_sha256,
            generator=generator,
        )
        tokens = materialize_derived_tokens(
            session=session,
            render_and_tokenize=render_and_tokenize,
            model_revision=str(tokenizer_identity["model_revision"]),
            tokenizer_revision=str(tokenizer_identity["tokenizer_revision"]),
            chat_template_sha256=chat_template_sha256,
        )
        report = evaluate_bfcl_derived_mechanical_readiness(
            session=session,
            schedule=schedule,
            token_materializations=tokens,
            maximum_prompt_tokens=maximum_prompt_tokens,
            maximum_generation_tokens=maximum_generation_tokens,
            maximum_context_tokens=maximum_context_tokens,
        )
        session_root = output / "sessions" / session.archive_record_id
        _write_json(session_root / "derived-session.json", session.to_dict())
        _write_json(session_root / "synthetic-tool-gap-schedule.json", schedule.to_dict())
        _write_json(
            session_root / "derived-token-materialization.json",
            [
                {
                    "request_id": row.request_id,
                    "rendered_prompt_sha256": row.rendered_prompt_sha256,
                    "token_ids": list(row.token_ids),
                    "token_ids_sha256": row.token_ids_sha256,
                    "model_revision": row.model_revision,
                    "tokenizer_revision": row.tokenizer_revision,
                    "chat_template_sha256": row.chat_template_sha256,
                    "trace_semantics": "DERIVED_NOT_QWEN_NATIVE_TRACE",
                }
                for row in tokens
            ],
        )
        _write_json(session_root / "mechanical-readiness.json", report)
        schedules.append(schedule)
        all_tokens.extend(tokens)
        materialized_by_record[session.archive_record_id] = tokens
        schedule_by_record[session.archive_record_id] = schedule
        readiness_by_record[session.archive_record_id] = report

    context_exclusions = classify_bfcl_context_budget(
        sessions=sessions,
        token_materializations_by_record=materialized_by_record,
        maximum_prompt_tokens=maximum_prompt_tokens,
        maximum_generation_tokens=maximum_generation_tokens,
        maximum_combined_tokens=maximum_context_tokens,
    )
    context_exclusion_rows = context_exclusions["exclusions"]
    formal_eligible_ids = context_exclusions["formal_eligible_archive_record_ids"]
    expected_context_counts = (
        int(context_budget["over_limit_sessions"]),
        int(context_budget["over_limit_requests"]),
        int(context_budget["expected_formal_eligible_sessions"]),
    )
    observed_context_counts = (
        len(context_exclusion_rows),
        int(context_exclusions["excluded_request_count"]),
        len(formal_eligible_ids),
    )
    if observed_context_counts != expected_context_counts:
        raise ValueError(
            "materialized context exclusions differ from frozen aggregate contract: "
            f"expected={expected_context_counts}, observed={observed_context_counts}"
        )
    _write_json(output / "context-budget-exclusions.json", context_exclusions)

    q4d_q5d_reports = []
    for session in sessions:
        if session.archive_record_id not in set(formal_eligible_ids):
            continue
        schedule = schedule_by_record[session.archive_record_id]
        frozen_appendix_schedule = build_frozen_schedule_from_protocol_appendix(
            session=session,
            protocol_appendix=appendix,
        )
        consumed_by_system = {}
        terminal_by_system = {}
        release_order_by_system = {}
        future_visibility_by_system = {}
        for system in REQUIRED_FORMAL_SYSTEMS:
            cursor = BFCLSyntheticTimingCursor(session=session, schedule=schedule)
            consumed = []
            released_in_order = True
            for request in session.requests:
                revealed_gap = cursor.complete_and_reveal_next_gap(request.request_id)
                expected_gap = schedule.gap_seconds_by_preceding_request_id.get(request.request_id)
                released_in_order = released_in_order and revealed_gap == expected_gap
                consumed.append(request.request_id)
            consumed_by_system[system] = consumed
            terminal_by_system[system] = (
                cursor.terminal_state.value if cursor.terminal_state else "REPLAY_INCOMPLETE"
            )
            release_order_by_system[system] = released_in_order
            future_visibility_by_system[system] = False
        report = evaluate_bfcl_derived_q4d_q5d(
            session=session,
            schedule=schedule,
            frozen_appendix_schedule=frozen_appendix_schedule,
            frozen_appendix_schedule_map_sha256=appendix_identities["synthetic_schedule_sha256"],
            system_schedule_sha256={system: schedule.sha256 for system in REQUIRED_FORMAL_SYSTEMS},
            consumed_request_ids_by_system=consumed_by_system,
            replay_terminal_by_system=terminal_by_system,
            released_after_preceding_completion_by_system=release_order_by_system,
            future_gap_visible_before_completion_by_system=future_visibility_by_system,
        )
        _write_json(
            output / "sessions" / session.archive_record_id / "q4d-q5d-evaluation.json",
            report,
        )
        q4d_q5d_reports.append(report)

    seal = create_bfcl_derived_workload_seal(
        sessions=sessions,
        schedules=schedules,
        token_materializations=all_tokens,
        expected_archive_record_ids=[str(row) for row in accepted],
        excluded_archive_record_ids=[str(row) for row in excluded],
        source_archive_sha256={
            "SNIPPET": file_sha256(args.snippet_archive),
            "NO_SNIPPET": file_sha256(args.no_snippet_archive),
        },
        protocol_appendix_canonical_sha256=appendix_canonical_sha256,
        protocol_appendix_file_sha256=appendix_file_sha256,
        context_budget_exclusions=context_exclusions,
        tool_definitions_sha256=tool_definitions_sha256,
        arrival_generator_sha256=arrival_generator_sha256,
    )
    validate_bfcl_derived_workload_seal(seal)
    _write_json(output / "bfcl-derived-workload-seal.json", seal)
    summary = {
        "schema_version": "phase5.bfcl_derived_collection.v1",
        "status": (
            "READY_WITH_CONTEXT_EXCLUSIONS"
            if len(q4d_q5d_reports) == len(formal_eligible_ids)
            and all(row["status"] == "PASS" for row in q4d_q5d_reports)
            else "FAIL_CLOSED"
        ),
        "session_count": len(sessions),
        "snippet_count": sum(row.search_mode == "SNIPPET" for row in sessions),
        "no_snippet_count": sum(row.search_mode == "NO_SNIPPET" for row in sessions),
        "excluded_archive_record_ids": list(excluded),
        "request_count": sum(len(row.requests) for row in sessions),
        "context_excluded_session_count": len(context_exclusion_rows),
        "context_excluded_request_count": context_exclusions["excluded_request_count"],
        "formal_eligible_session_count": len(formal_eligible_ids),
        "q4d_pass_count": sum(row["q4d"]["status"] == "PASS" for row in q4d_q5d_reports),
        "q5d_pass_count": sum(row["q5d"]["status"] == "PASS" for row in q4d_q5d_reports),
        "formal_q1_q9_status": BFCL_DERIVED_Q1_Q9_STATUS,
        "derived_q4d_status": (
            "PASS"
            if len(q4d_q5d_reports) == len(formal_eligible_ids)
            and all(row["q4d"]["status"] == "PASS" for row in q4d_q5d_reports)
            else "FAIL_CLOSED"
        ),
        "derived_q5d_status": (
            "PASS"
            if len(q4d_q5d_reports) == len(formal_eligible_ids)
            and all(row["q5d"]["status"] == "PASS" for row in q4d_q5d_reports)
            else "FAIL_CLOSED"
        ),
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
        "seal_content_sha256": seal["seal_content_sha256"],
    }
    _write_json(output / "collection-summary.json", summary)
    manifest = {
        str(path.relative_to(output)): file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "sha256-manifest.json"
    }
    _write_json(output / "sha256-manifest.json", manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] != "FAIL_CLOSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
