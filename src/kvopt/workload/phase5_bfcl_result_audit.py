"""Read-only audit of public BFCL leaderboard Agentic result archives."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .phase5_dataset_processing import file_sha256
from .phase5_replay import canonical_sha256


class BFCLResultAuditError(ValueError):
    """Raised when an archive cannot be matched to the frozen BFCL frame."""


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    for line_number, line in enumerate(lines, start=1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise BFCLResultAuditError(f"non-object at {path}:{line_number}")
        rows.append(value)
    return rows, lines


def _tool_evidence(row: Mapping[str, Any]) -> dict[str, object]:
    logs = row.get("inference_log")
    if not isinstance(logs, list) or not logs or not isinstance(logs[0], dict):
        return {
            "inference_log_present": False,
            "model_request_count": 0,
            "tool_call_count": 0,
            "tool_result_count": 0,
            "search_call_count": 0,
            "fetch_call_count": 0,
            "complete_fetch_result_count": 0,
            "fetch_error_count": 0,
            "tool_calls_match_results": False,
            "final_answer_present": False,
            "absolute_timestamps_present": False,
            "explicit_terminal_status_present": False,
            "tool_definitions_present": False,
            "sampling_configuration_present": False,
        }

    tool_calls: list[str] = []
    tool_results: list[object] = []
    model_requests = 0
    timestamps = False
    for turn in logs:
        if not isinstance(turn, dict):
            continue
        for step, messages in turn.items():
            if step == "begin_of_turn_query" or not isinstance(messages, list):
                continue
            assistant_seen = False
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if any(
                    field in message
                    for field in ("timestamp", "created_at", "submitted_at", "completed_at")
                ):
                    timestamps = True
                if message.get("role") == "assistant" and isinstance(
                    message.get("content"), list
                ):
                    assistant_seen = True
                    for call in message["content"]:
                        if isinstance(call, dict):
                            tool_calls.extend(str(name) for name in call)
                elif message.get("role") == "tool":
                    content = message.get("content")
                    try:
                        parsed = ast.literal_eval(content) if isinstance(content, str) else None
                    except (SyntaxError, ValueError):
                        parsed = None
                    tool_results.append(parsed)
            model_requests += assistant_seen

    fetch_indices = [index for index, name in enumerate(tool_calls) if name == "fetch_url_content"]
    complete_fetches = 0
    fetch_errors = 0
    for index in fetch_indices:
        result = tool_results[index] if index < len(tool_results) else None
        if isinstance(result, dict) and isinstance(result.get("content"), str) and result["content"]:
            complete_fetches += 1
        elif isinstance(result, dict) and result.get("error"):
            fetch_errors += 1

    result = row.get("result")
    final_answer = (
        isinstance(result, list)
        and bool(result)
        and isinstance(result[0], list)
        and bool(result[0])
        and isinstance(result[0][-1], str)
    )
    return {
        "inference_log_present": True,
        "model_request_count": model_requests,
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_results),
        "search_call_count": tool_calls.count("search_engine_query"),
        "fetch_call_count": len(fetch_indices),
        "complete_fetch_result_count": complete_fetches,
        "fetch_error_count": fetch_errors,
        "tool_calls_match_results": len(tool_calls) == len(tool_results),
        "final_answer_present": final_answer,
        "absolute_timestamps_present": timestamps,
        "explicit_terminal_status_present": False,
        "tool_definitions_present": False,
        "sampling_configuration_present": False,
    }


def _initial_user_question(row: Mapping[str, Any]) -> str | None:
    logs = row.get("inference_log")
    if not isinstance(logs, list) or not logs or not isinstance(logs[0], dict):
        return None
    messages = logs[0].get("begin_of_turn_query")
    if not isinstance(messages, list):
        return None
    users = [message.get("content") for message in messages if message.get("role") == "user"]
    return str(users[-1]) if users else None


def audit_result_file(
    *,
    path: Path,
    mode: str,
    source_rows: list[dict[str, Any]],
    frame_cases: list[dict[str, Any]],
    expected_blob_sha1: str,
    observed_blob_sha1: str,
) -> dict[str, object]:
    """Audit one 100-record archived stratum against the frozen frame."""

    if mode not in {"SNIPPET", "NO_SNIPPET"}:
        raise BFCLResultAuditError(f"unsupported mode: {mode}")
    rows, raw_lines = _load_jsonl(path)
    prefix = "web_search_base_" if mode == "SNIPPET" else "web_search_no_snippet_"
    expected_ids = [f"{prefix}{index}" for index in range(len(source_rows))]
    observed_ids = [str(row.get("id")) for row in rows]
    duplicates = sorted(key for key, count in Counter(observed_ids).items() if count > 1)
    missing = sorted(set(expected_ids) - set(observed_ids))
    unexpected = sorted(set(observed_ids) - set(expected_ids))
    relevant_frame = [case for case in frame_cases if case["search_mode"] == mode]
    if len(relevant_frame) != len(source_rows):
        raise BFCLResultAuditError("frozen frame does not contain 100 cases per mode")

    details = []
    for row, raw_line in zip(rows, raw_lines, strict=True):
        result_id = str(row.get("id"))
        try:
            index = int(result_id.removeprefix(prefix))
        except ValueError:
            index = -1
        source = source_rows[index] if 0 <= index < len(source_rows) else None
        frame = relevant_frame[index] if 0 <= index < len(relevant_frame) else None
        evidence = _tool_evidence(row)
        question = _initial_user_question(row)
        source_question = (
            source["question"][0][0]["content"] if source is not None else None
        )
        expected_case_id = (
            f"bfcl_{source['id']}:{'snippet' if mode == 'SNIPPET' else 'no_snippet'}"
            if source is not None
            else None
        )
        frame_identity_matches = bool(
            frame is not None
            and source is not None
            and frame.get("source_case_id") == source.get("id")
            and frame.get("case_id") == expected_case_id
            and frame.get("search_mode") == mode
            and frame.get("show_snippet") is (mode == "SNIPPET")
            and isinstance(frame.get("content_sha256"), str)
            and len(frame["content_sha256"]) == 64
        )
        semantic_complete = bool(
            evidence["inference_log_present"]
            and evidence["tool_calls_match_results"]
            and evidence["final_answer_present"]
            and question == source_question
        )
        details.append(
            {
                "archive_record_id": result_id,
                "source_case_id": source["id"] if source else None,
                "phase5_case_id": frame["case_id"] if frame else None,
                "raw_record_sha256": hashlib.sha256(raw_line.encode()).hexdigest(),
                "source_question_matches": question == source_question,
                "frozen_frame_identity_matches": frame_identity_matches,
                "frozen_content_sha256": frame["content_sha256"] if frame else None,
                **evidence,
                "input_token_counts_present": isinstance(row.get("input_token_count"), list),
                "output_token_counts_present": isinstance(row.get("output_token_count"), list),
                "model_latency_durations_present": isinstance(row.get("latency"), list),
                "native_prompt_token_ids_present": False,
                "observed_tool_gap_timestamps_present": False,
                "semantic_agent_trace_complete": semantic_complete,
                "qwen_token_materialization_status": (
                    "PENDING_PINNED_RECONSTRUCTION"
                    if semantic_complete
                    else "NOT_RECONSTRUCTABLE"
                ),
                "replay_ready_status": "NOT_READY",
                "replay_blockers": [
                    blocker
                    for blocker, blocked in (
                        ("INCOMPLETE_SEMANTIC_TRACE", not semantic_complete),
                        ("NO_ABSOLUTE_REQUEST_TIMESTAMPS", True),
                        ("NO_OBSERVED_TOOL_GAP_TIMESTAMPS", True),
                        ("NO_EXPLICIT_TERMINAL_STATUS", True),
                        ("NO_EMBEDDED_TOOL_DEFINITIONS", True),
                        ("NO_EMBEDDED_SAMPLING_CONFIGURATION", True),
                        ("NO_NATIVE_TOKEN_IDS", True),
                        ("THIRD_PARTY_CONTENT_LICENSE_REVIEW_PENDING", True),
                    )
                    if blocked
                ],
            }
        )

    semantic_count = sum(row["semantic_agent_trace_complete"] for row in details)
    frame_identity_match_count = sum(
        row["frozen_frame_identity_matches"] for row in details
    )
    question_match_count = sum(row["source_question_matches"] for row in details)
    exact_id_coverage = observed_ids == expected_ids
    payload: dict[str, object] = {
        "path": str(path),
        "mode": mode,
        "expected_git_blob_sha1": expected_blob_sha1,
        "observed_git_blob_sha1": observed_blob_sha1,
        "git_blob_sha1_matches": observed_blob_sha1 == expected_blob_sha1,
        "file_sha256": file_sha256(path),
        "file_bytes": path.stat().st_size,
        "record_count": len(rows),
        "unique_id_count": len(set(observed_ids)),
        "duplicate_ids": duplicates,
        "missing_ids": missing,
        "unexpected_ids": unexpected,
        "exact_frozen_id_coverage": exact_id_coverage,
        "source_question_match_count": question_match_count,
        "frozen_frame_identity_match_count": frame_identity_match_count,
        "exact_frozen_frame_match": bool(
            exact_id_coverage
            and question_match_count == len(rows)
            and frame_identity_match_count == len(rows)
            and observed_blob_sha1 == expected_blob_sha1
        ),
        "semantic_trace_complete_count": semantic_count,
        "semantic_trace_incomplete_count": len(details) - semantic_count,
        "fetch_call_count": sum(row["fetch_call_count"] for row in details),
        "complete_fetch_result_count": sum(
            row["complete_fetch_result_count"] for row in details
        ),
        "fetch_error_count": sum(row["fetch_error_count"] for row in details),
        "absolute_timestamp_record_count": sum(
            row["absolute_timestamps_present"] for row in details
        ),
        "explicit_terminal_record_count": sum(
            row["explicit_terminal_status_present"] for row in details
        ),
        "native_token_trace_record_count": 0,
        "replay_ready_count": 0,
        "case_details": details,
    }
    return {**payload, "file_audit_sha256": canonical_sha256(payload)}


def build_archive_audit(
    *,
    repository_commit: str,
    repository_url: str,
    license_id: str,
    repository_license_sha256: str,
    repository_readme_sha256: str,
    file_audits: list[dict[str, object]],
) -> dict[str, object]:
    """Build the combined, content-minimized archive reuse decision."""

    exact_id_coverage = all(row["exact_frozen_id_coverage"] for row in file_audits)
    exact_frame_match = all(row["exact_frozen_frame_match"] for row in file_audits)
    replay_ready = sum(int(row["replay_ready_count"]) for row in file_audits)
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_result_archive_audit.v1",
        "repository": repository_url,
        "repository_commit": repository_commit,
        "repository_license": license_id,
        "repository_license_sha256": repository_license_sha256,
        "repository_readme_sha256": repository_readme_sha256,
        "repository_license_does_not_clear_third_party_content": True,
        "source_model": "gpt-5.2-2025-12-11-FC",
        "source_model_is_not_phase5_execution_model": True,
        "eligible_only_as_workload_tool_trace": True,
        "frozen_frame_exact_id_coverage": exact_id_coverage,
        "frozen_frame_exact_content_match": exact_frame_match,
        "total_record_count": sum(int(row["record_count"]) for row in file_audits),
        "semantic_trace_complete_count": sum(
            int(row["semantic_trace_complete_count"]) for row in file_audits
        ),
        "replay_ready_count": replay_ready,
        "direct_reuse_status": "NOT_READY" if replay_ready == 0 else "PARTIAL",
        "global_blockers": [
            "NO_ABSOLUTE_REQUEST_TIMESTAMPS",
            "NO_OBSERVED_TOOL_GAP_TIMESTAMPS",
            "NO_EXPLICIT_TERMINAL_STATUS",
            "NO_EMBEDDED_TOOL_DEFINITIONS",
            "NO_EMBEDDED_SAMPLING_CONFIGURATION",
            "NO_NATIVE_TOKEN_IDS",
            "THIRD_PARTY_CONTENT_LICENSE_REVIEW_PENDING",
        ],
        "file_audits": file_audits,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "archive_audit_sha256": canonical_sha256(payload)}
