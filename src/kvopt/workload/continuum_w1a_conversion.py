"""Fail-closed W1-A CLI over the immutable W0 trajectory converter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .continuum_source_audit import convert_mini_swe_trajectory, validate_conversion
from .phase2 import Phase2Trace

SIDECAR_SCHEMA_VERSION = "continuum.w1a_acquisition_sidecar.v1"
TokenizeMessages = Callable[[Sequence[Mapping[str, Any]]], tuple[str, list[int]]]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def build_sidecar_evidence(
    sidecar: Mapping[str, object],
    *,
    trajectory: Mapping[str, object],
    trajectory_path: Path,
    instance_id: str,
    tokenize_messages: TokenizeMessages,
) -> dict[str, object]:
    """Validate and summarize wrapper-boundary acquisition observations."""
    if sidecar.get("schema_version") != SIDECAR_SCHEMA_VERSION:
        raise ValueError("unsupported W1-A acquisition sidecar schema_version")
    if sidecar.get("program_id") != instance_id:
        raise ValueError("sidecar program_id does not match trajectory instance_id")
    if sidecar.get("trajectory_sha256") != _sha256_file(trajectory_path):
        raise ValueError("sidecar trajectory SHA-256 does not match trajectory file")
    model_calls = sidecar.get("model_calls")
    tool_calls = sidecar.get("tool_calls")
    if not isinstance(model_calls, list) or not isinstance(tool_calls, list):
        raise TypeError("sidecar model_calls and tool_calls must be lists")
    if any(not isinstance(row, Mapping) for row in [*model_calls, *tool_calls]):
        raise TypeError("sidecar observations must be objects")
    messages = trajectory.get("messages")
    if not isinstance(messages, list) or any(
        not isinstance(message, Mapping) for message in messages
    ):
        raise TypeError("trajectory messages must be a list of objects")
    assistant_indexes = [
        index for index, message in enumerate(messages) if message.get("role") == "assistant"
    ]
    if len(model_calls) != len(assistant_indexes):
        raise ValueError("sidecar model call count does not match assistant turn count")

    expected_ids = [f"{instance_id}:turn:{index}" for index in range(1, len(model_calls) + 1)]
    observed_ids = [row.get("request_id") for row in model_calls]
    if observed_ids != expected_ids or len(set(observed_ids)) != len(observed_ids):
        raise ValueError("sidecar model request identity sequence is incomplete or duplicated")
    tool_by_request: dict[str, Mapping[str, object]] = {}
    for row in tool_calls:
        request_id = row.get("request_id")
        if request_id not in set(expected_ids):
            raise ValueError("sidecar tool call references an unknown request")
        if request_id in tool_by_request:
            raise ValueError("sidecar contains multiple tool calls for one request")
        tool_by_request[str(request_id)] = row

    request_rows: list[dict[str, object]] = []
    previous_tokens: list[int] | None = None
    prefix_checks: list[bool] = []
    for call_index, row in enumerate(model_calls):
        request_id = str(row["request_id"])
        assistant_index = assistant_indexes[call_index]
        expected_messages = [dict(message) for message in messages[:assistant_index]]
        if row.get("messages") != expected_messages:
            raise ValueError("sidecar messages do not match trajectory pre-assistant history")
        if row.get("messages_sha256") != _canonical_sha256(expected_messages):
            raise ValueError("sidecar messages SHA-256 does not match trajectory history")
        assistant = messages[assistant_index]
        expected_response = {
            "content": assistant.get("content"),
            "extra": assistant.get("extra"),
        }
        if row.get("response_sha256") != _canonical_sha256(expected_response):
            raise ValueError("sidecar model response does not match trajectory assistant turn")
        submit = _finite_number(
            row.get("model_submit_monotonic_seconds"), "model submit time"
        )
        completion = _finite_number(
            row.get("model_completion_monotonic_seconds"), "model completion time"
        )
        if completion < submit:
            raise ValueError("model completion precedes submission")
        tokens = row.get("submitted_token_ids")
        if not isinstance(tokens, list) or any(
            isinstance(token, bool) or not isinstance(token, int) for token in tokens
        ):
            tokens = None
        token_status = row.get("token_observation_status")
        rendered_prompt, expected_tokens = tokenize_messages(expected_messages)
        if row.get("rendered_prompt") != rendered_prompt:
            raise ValueError("sidecar rendered prompt does not match pinned tokenization")
        if row.get("rendered_prompt_sha256") != hashlib.sha256(
            rendered_prompt.encode("utf-8")
        ).hexdigest():
            raise ValueError("sidecar rendered prompt SHA-256 mismatch")
        if tokens != expected_tokens:
            raise ValueError("sidecar token IDs do not match pinned deterministic tokenization")
        prefix_status: bool | None = None
        if tokens is not None and previous_tokens is not None:
            prefix_status = tokens[: len(previous_tokens)] == previous_tokens
            prefix_checks.append(prefix_status)
        tool = tool_by_request.get(request_id)
        tool_evidence: dict[str, object] | None = None
        if tool is not None:
            action = tool.get("action")
            if not isinstance(action, str) or action not in str(assistant.get("content", "")):
                raise ValueError("sidecar tool action does not match trajectory assistant turn")
            if tool.get("action_sha256") != hashlib.sha256(action.encode()).hexdigest():
                raise ValueError("sidecar tool action SHA-256 mismatch")
            tool_start = _finite_number(
                tool.get("tool_start_monotonic_seconds"), "tool start time"
            )
            tool_completion = _finite_number(
                tool.get("tool_completion_monotonic_seconds"), "tool completion time"
            )
            if tool_completion < tool_start or tool_start < completion:
                raise ValueError("tool timing is inconsistent with its model request")
            next_message = (
                messages[assistant_index + 1]
                if assistant_index + 1 < len(messages)
                else None
            )
            result_binding = None
            if isinstance(next_message, Mapping) and next_message.get("role") == "user":
                content = next_message.get("content")
                if isinstance(content, str):
                    match = re.fullmatch(
                        r"<returncode>(-?\d+)</returncode>\n<output>\n(.*)</output>",
                        content,
                        flags=re.DOTALL,
                    )
                    if match is not None:
                        result = {
                            "output": match.group(2),
                            "returncode": int(match.group(1)),
                        }
                        if tool.get("result_sha256") != _canonical_sha256(result):
                            raise ValueError(
                                "sidecar tool result does not match trajectory observation"
                            )
                        result_binding = "TRAJECTORY_OBSERVATION_MATCH"
                    elif (
                        content == ""
                        and trajectory.get("info", {}).get("exit_status") == "Submitted"
                        and "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in action
                    ):
                        result_binding = "TERMINAL_SUBMISSION_NOT_SERIALIZED"
            if result_binding is None:
                raise ValueError(
                    "sidecar tool result cannot be bound to trajectory observation"
                )
            tool_evidence = {
                "status": tool.get("status"),
                "action_sha256": tool.get("action_sha256"),
                "tool_start_monotonic_seconds": tool_start,
                "tool_completion_monotonic_seconds": tool_completion,
                "tool_elapsed_seconds": tool_completion - tool_start,
                "trajectory_result_binding": result_binding,
            }
        request_rows.append(
            {
                "request_id": request_id,
                "status": row.get("status"),
                "messages_sha256": row.get("messages_sha256"),
                "rendered_prompt_sha256": row.get("rendered_prompt_sha256"),
                "model_submit_monotonic_seconds": submit,
                "model_completion_monotonic_seconds": completion,
                "model_elapsed_seconds": completion - submit,
                "submitted_token_count": None if tokens is None else len(tokens),
                "submitted_token_ids_sha256": (
                    None
                    if tokens is None
                    else hashlib.sha256(
                        json.dumps(tokens, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()
                ),
                "token_observation_status": token_status,
                "previous_submitted_tokens_are_prefix": prefix_status,
                "tool_evidence": tool_evidence,
            }
        )
        previous_tokens = tokens

    boundaries = sidecar.get("observation_boundaries")
    if not isinstance(boundaries, Mapping):
        raise TypeError("sidecar observation_boundaries must be an object")
    return {
        "schema_version": "continuum.w1a_acquisition_evidence.v1",
        "instance_id": instance_id,
        "trajectory_sha256": sidecar.get("trajectory_sha256"),
        "observation_boundaries": dict(boundaries),
        "model_call_count": len(model_calls),
        "tool_call_count": len(tool_calls),
        "request_identity_complete": True,
        "trajectory_payload_identity_complete": True,
        "pinned_tokenization_recomputed": True,
        "wrapper_timing_complete": all(
            row["status"] == "SUCCESS" for row in request_rows
        ),
        "deterministic_tokenization_complete": all(
            row["submitted_token_count"] is not None for row in request_rows
        ),
        "submitted_token_prefix_growth_all_turns": bool(prefix_checks)
        and all(prefix_checks),
        "native_runtime_submitted_token_ids_observed": False,
        "requests": request_rows,
    }


def _source_instance_id(trajectory: Mapping[str, object]) -> str | None:
    top_level_value = trajectory.get("instance_id")
    top_level_id = str(top_level_value) if top_level_value else None
    info = trajectory.get("info")
    if info is None:
        return top_level_id
    if not isinstance(info, Mapping):
        raise TypeError("trajectory info must be an object")
    value = info.get("instance_id")
    info_id = str(value) if value else None
    if top_level_id and info_id and top_level_id != info_id:
        raise ValueError("trajectory top-level and info instance_id conflict")
    return top_level_id or info_id


def resolve_instance_id(
    trajectory: Mapping[str, object], external_instance_id: str | None
) -> tuple[str, str]:
    """Source identity wins; an external identity may only fill a missing ID."""
    source_id = _source_instance_id(trajectory)
    if source_id and external_instance_id and source_id != external_instance_id:
        raise ValueError("external instance_id conflicts with source trajectory identity")
    resolved = source_id or external_instance_id
    if not resolved:
        raise ValueError("instance_id is required")
    provenance = "SOURCE_TRAJECTORY" if source_id else "EXTERNAL_FILL_FOR_MISSING_SOURCE_ID"
    return resolved, provenance


def apply_completion_semantics(
    trace: Phase2Trace,
    report: Mapping[str, object],
    *,
    program_complete: bool,
) -> tuple[Phase2Trace, dict[str, object]]:
    """Preserve W1-A right-censoring without changing the sealed W0 converter."""
    updated_report = dict(report)
    if program_complete:
        updated_report["program_completion_status"] = "OBSERVED_COMPLETE"
        return trace, updated_report
    requests = tuple(replace(request, is_terminal=False) for request in trace.requests)
    updated_report["program_completion_status"] = "RIGHT_CENSORED_INCOMPLETE"
    return (
        Phase2Trace(
            trace_id=trace.trace_id,
            requests=requests,
            pressure_stages=trace.pressure_stages,
            allow_incomplete_programs=True,
        ),
        updated_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--instance-id")
    args = parser.parse_args()
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8"))
    if not isinstance(trajectory, dict):
        raise TypeError("trajectory must be an object")
    instance_id, identity_provenance = resolve_instance_id(trajectory, args.instance_id)
    run_manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
    if not isinstance(run_manifest, dict):
        raise TypeError("run manifest must be an object")
    if run_manifest.get("instance_id") != instance_id:
        raise ValueError("run manifest identity does not match trajectory")
    trajectory_exit = trajectory.get("info", {}).get("exit_status")
    if run_manifest.get("agent_exit_status") != trajectory_exit:
        raise ValueError("run manifest outcome does not match trajectory exit status")
    agent_outcome = run_manifest.get("agent_outcome")
    if agent_outcome == "SUBMITTED":
        if trajectory_exit != "Submitted":
            raise ValueError("submitted run lacks a submitted trajectory exit")
        program_complete = True
    elif agent_outcome == "INCOMPLETE":
        if trajectory_exit not in {"LimitsExceeded", "ContextLengthExceeded"}:
            raise ValueError("incomplete run has an unsupported trajectory exit")
        program_complete = False
    else:
        raise ValueError("failed or unknown acquisition outcomes cannot be converted")
    base_trace, base_report = convert_mini_swe_trajectory(
        trajectory, instance_id=instance_id
    )
    validation = validate_conversion(trajectory, base_trace, base_report)
    trace, report = apply_completion_semantics(
        base_trace, base_report, program_complete=program_complete
    )
    validation.setdefault("checks", {})["completion_semantics_preserved"] = (
        trace.allow_incomplete_programs is (not program_complete)
        and all(request.is_terminal is False for request in trace.requests)
        if not program_complete
        else trace.requests[-1].is_terminal is True
    )
    validation["instance_id_provenance"] = identity_provenance
    sidecar_evidence = None
    if args.sidecar is not None:
        if args.config is None:
            raise ValueError("--config is required when --sidecar is provided")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("model"), dict):
            raise TypeError("acquisition config model must be an object")
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            config["model"]["tokenizer_name"],
            revision=config["model"]["tokenizer_revision"],
            local_files_only=True,
        )

        def tokenize_messages(messages):
            rendered = tokenizer.apply_chat_template(
                list(messages), tokenize=False, add_generation_prompt=True
            )
            return rendered, tokenizer.encode(rendered, add_special_tokens=False)

        sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
        if not isinstance(sidecar, dict):
            raise TypeError("sidecar must be an object")
        sidecar_evidence = build_sidecar_evidence(
            sidecar,
            trajectory=trajectory,
            trajectory_path=args.trajectory,
            instance_id=instance_id,
            tokenize_messages=tokenize_messages,
        )
        validation["checks"]["acquisition_sidecar_valid"] = True
        validation["checks"]["wrapper_request_timing_complete"] = sidecar_evidence[
            "wrapper_timing_complete"
        ]
        validation["checks"]["deterministic_tokenization_complete"] = sidecar_evidence[
            "deterministic_tokenization_complete"
        ]
        validation["checks"]["trajectory_payload_identity_complete"] = sidecar_evidence[
            "trajectory_payload_identity_complete"
        ]
    args.output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "trace.json": trace.to_dict(),
        "conversion-report.json": report,
        "validation-report.json": validation,
    }
    if sidecar_evidence is not None:
        outputs["acquisition-evidence.json"] = sidecar_evidence
    for name, payload in outputs.items():
        (args.output_root / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"wrote W1-A workload conversion: {args.output_root}")
    return 2 if validation["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
