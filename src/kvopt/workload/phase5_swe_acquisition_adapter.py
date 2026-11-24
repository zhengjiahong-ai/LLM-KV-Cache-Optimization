"""Convert one observed mini-SWE-agent run into a Phase 5 acquisition record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from .phase5_acquisition import (
    MINI_SWE_SCHEMA,
    SWE_LICENSE_COMPONENTS,
    SWE_LICENSE_EXPRESSION,
    SWE_LICENSE_NOTES,
    SWE_LICENSE_REDISTRIBUTION_STATUS,
)
from .phase5_replay import canonical_sha256

_TOOL_RESULT = re.compile(
    r"<returncode>(-?\d+)</returncode>\n<output>\n(.*)</output>", re.DOTALL
)
_ACQUISITION_ORIGINS = {
    "PHASE5_NEW_ACQUISITION",
    "PHASE5_HISTORICAL_CANDIDATE_FRESH_REACQUISITION",
    "HISTORICAL_W1C_REUSE",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _load_object(path: Path, label: str) -> Mapping[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), label)


def _trajectory_path(run_directory: Path, instance_id: str) -> Path:
    expected = run_directory / f"{instance_id}.traj.json"
    if expected.is_file():
        return expected
    matches = sorted(run_directory.glob("*.traj.json"))
    if len(matches) != 1:
        raise FileNotFoundError("mini-SWE run must contain exactly one trajectory")
    return matches[0]


def _message(row: Mapping[str, object]) -> dict[str, object]:
    role = _text(row.get("role"), "message role")
    preserved = {key: value for key, value in row.items() if key != "role"}
    return {"role": role, "content": preserved}


def _tool_result(
    *,
    trajectory_messages: list[object],
    assistant_index: int,
    terminal_submission: bool,
) -> object:
    if assistant_index + 1 >= len(trajectory_messages):
        raise ValueError("successful tool call lacks a following observation")
    next_message = _mapping(trajectory_messages[assistant_index + 1], "tool result")
    content = next_message.get("content")
    if isinstance(content, str):
        match = _TOOL_RESULT.fullmatch(content)
        if match is not None:
            return {"returncode": int(match.group(1)), "output": match.group(2)}
        if terminal_submission:
            return {
                "returncode": 0,
                "output": f"COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n{content}",
            }
    raise ValueError("tool result cannot be recovered from trajectory")


def build_mini_swe_acquisition_record(
    *,
    run_directory: Path,
    chat_template_sha256: str,
    license_expression: str,
    acquisition_origin: str,
) -> dict[str, object]:
    """Validate and adapt an immutable W1/Phase 3 mini-SWE run directory."""

    if not re.fullmatch(r"[0-9a-f]{64}", chat_template_sha256):
        raise ValueError("chat_template_sha256 must be a lowercase SHA-256")
    if license_expression != SWE_LICENSE_EXPRESSION:
        raise ValueError(
            "license_expression must match the frozen M4 internal-research LicenseRef"
        )
    if acquisition_origin not in _ACQUISITION_ORIGINS:
        raise ValueError("unsupported Phase 5 SWE acquisition origin")
    run_path = run_directory / "run.json"
    sidecar_path = run_directory / "acquisition-sidecar.json"
    if not run_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError("mini-SWE run lacks run.json or acquisition-sidecar.json")
    run = _load_object(run_path, "run manifest")
    sidecar = _load_object(sidecar_path, "acquisition sidecar")
    instance_id = _text(run.get("instance_id"), "instance_id")
    trajectory_path = _trajectory_path(run_directory, instance_id)
    trajectory = _load_object(trajectory_path, "trajectory")
    if run.get("schema_version") != "continuum.w1a_acquisition_run.v1":
        raise ValueError("unsupported mini-SWE run schema")
    if sidecar.get("schema_version") != "continuum.w1a_acquisition_sidecar.v1":
        raise ValueError("unsupported mini-SWE sidecar schema")
    if run.get("sidecar_sha256") != _sha256(sidecar_path):
        raise ValueError("run manifest sidecar SHA-256 mismatch")
    if run.get("trajectory_sha256") != _sha256(trajectory_path):
        raise ValueError("run manifest trajectory SHA-256 mismatch")
    if sidecar.get("trajectory_sha256") != _sha256(trajectory_path):
        raise ValueError("sidecar trajectory SHA-256 mismatch")
    if sidecar.get("program_id") != instance_id:
        raise ValueError("sidecar identity differs from run identity")
    if trajectory.get("instance_id") != instance_id:
        raise ValueError("trajectory identity differs from run identity")

    dataset = _mapping(run.get("dataset"), "dataset")
    model = _mapping(run.get("model"), "model")
    revision = _text(dataset.get("revision"), "dataset revision")
    model_name = _text(model.get("model_name"), "model name")
    model_revision = _text(model.get("model_revision"), "model revision")
    tokenizer_revision = _text(
        model.get("tokenizer_revision"), "tokenizer revision"
    )
    trajectory_messages = _array(trajectory.get("messages"), "trajectory messages")
    assistant_indexes = [
        index
        for index, row in enumerate(trajectory_messages)
        if isinstance(row, Mapping) and row.get("role") == "assistant"
    ]
    model_calls = _array(sidecar.get("model_calls"), "sidecar model_calls")
    tool_calls = _array(sidecar.get("tool_calls"), "sidecar tool_calls")
    successful_model_calls = [
        row
        for row in model_calls
        if isinstance(row, Mapping) and row.get("status") == "SUCCESS"
    ]
    failed_model_calls = [
        row
        for row in model_calls
        if isinstance(row, Mapping) and row.get("status") != "SUCCESS"
    ]
    if len(assistant_indexes) != len(successful_model_calls):
        raise ValueError(
            "successful model call count differs from trajectory assistant count"
        )
    if model_calls[: len(successful_model_calls)] != successful_model_calls:
        raise ValueError("failed model call is not a trailing acquisition attempt")
    tools_by_request: dict[str, Mapping[str, object]] = {}
    for value in tool_calls:
        row = _mapping(value, "tool call")
        request_id = _text(row.get("request_id"), "tool request_id")
        if request_id in tools_by_request:
            raise ValueError("multiple tool calls reference one mini-SWE request")
        tools_by_request[request_id] = row

    run_outcome = str(run.get("agent_outcome"))
    if run_outcome == "SUBMITTED":
        terminal_state = "COMPLETED"
    elif run_outcome == "INCOMPLETE":
        terminal_state = "RIGHT_CENSORED"
    elif run_outcome == "FAILED":
        terminal_state = "FAILED"
    else:
        raise ValueError("unsupported mini-SWE run outcome")
    turns: list[dict[str, object]] = []
    for ordinal, value in enumerate(successful_model_calls, start=1):
        call = _mapping(value, "model call")
        request_id = _text(call.get("request_id"), "request_id")
        expected_request_id = f"{instance_id}:turn:{ordinal}"
        if request_id != expected_request_id:
            raise ValueError("mini-SWE request identity sequence mismatch")
        prompt_messages = _array(call.get("messages"), "model messages")
        assistant_index = assistant_indexes[ordinal - 1]
        trajectory_prompt = trajectory_messages[:assistant_index]
        if prompt_messages != trajectory_prompt:
            raise ValueError("sidecar prompt messages differ from trajectory")
        assistant = _mapping(
            trajectory_messages[assistant_index], "assistant response"
        )
        expected_response = {
            "content": assistant.get("content"),
            "extra": assistant.get("extra"),
        }
        if call.get("response_sha256") != canonical_sha256(expected_response):
            raise ValueError("assistant response SHA-256 mismatch")
        normalized_messages = [
            _message(_mapping(row, "prompt message")) for row in prompt_messages
        ]
        response = _message(assistant)
        tool = tools_by_request.get(request_id)
        if tool is not None:
            tool_status = str(tool.get("status"))
            if tool_status not in {"SUCCESS", "FAILED"}:
                raise ValueError("unsupported mini-SWE tool status")
            action = _text(tool.get("action"), "tool action")
            terminal_submission = (
                run_outcome == "SUBMITTED"
                and ordinal == len(successful_model_calls)
                and "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in action
            )
            result = (
                _tool_result(
                    trajectory_messages=trajectory_messages,
                    assistant_index=assistant_index,
                    terminal_submission=terminal_submission,
                )
                if tool_status == "SUCCESS"
                else None
            )
            if (
                tool_status == "SUCCESS"
                and tool.get("result_sha256") != canonical_sha256(result)
            ):
                raise ValueError("tool result SHA-256 mismatch")
            tool_record: dict[str, object] = {
                "tool_call_id": f"{request_id}:tool:1",
                "tool_name": "bash",
                "arguments": {"action": action},
                "result": result,
                "state": "COMPLETED" if tool_status == "SUCCESS" else "FAILED",
                "started_at_seconds": tool.get("tool_start_monotonic_seconds"),
                "ended_at_seconds": tool.get("tool_completion_monotonic_seconds"),
                "clock_domain": "WRAPPER_MONOTONIC",
            }
            if tool_status == "FAILED":
                tool_record["error"] = _text(tool.get("error"), "tool error")
            response["tool_calls"] = [tool_record]
        normalized_messages.append(response)
        tokens = _array(call.get("submitted_token_ids"), "submitted_token_ids")
        turns.append(
            {
                "turn_id": f"{request_id}:turn",
                "request_id": request_id,
                "messages": normalized_messages,
                "rendered_prompt": _text(
                    call.get("rendered_prompt"), "rendered_prompt"
                ),
                "submitted_token_ids": tokens,
                "submitted_at_seconds": call.get(
                    "model_submit_monotonic_seconds"
                ),
                "completed_at_seconds": call.get(
                    "model_completion_monotonic_seconds"
                ),
                "clock_domain": "WRAPPER_MONOTONIC",
                "terminal_state": "COMPLETED",
            }
        )
    artifacts = {
        "run.json": _sha256(run_path),
        trajectory_path.name: _sha256(trajectory_path),
        "acquisition-sidecar.json": _sha256(sidecar_path),
    }
    limitations = [
        f"TRAILING_MODEL_CALL_{row.get('status', 'UNKNOWN')!s}:"
        f"{row.get('error', 'UNSPECIFIED')!s}"
        for row in failed_model_calls
    ]
    return {
        "schema_version": MINI_SWE_SCHEMA,
        "trace_id": f"phase5:swe:{instance_id}",
        "program_id": instance_id,
        "session_id": f"phase5:swe:{instance_id}:session:1",
        "task_id": instance_id,
        "source": {
            "kind": "SWE_BENCH_VERIFIED_MINI_SWE_AGENT",
            "dataset": _text(dataset.get("name"), "dataset name"),
            "revision": revision,
            "uri": "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified",
            "license": license_expression,
        },
        "license_components": dict(SWE_LICENSE_COMPONENTS),
        "license_redistribution_status": SWE_LICENSE_REDISTRIBUTION_STATUS,
        "license_notes": SWE_LICENSE_NOTES,
        "model_identity": f"{model_name}@{model_revision}",
        "model_revision": model_revision,
        "tokenizer_revision": tokenizer_revision,
        "chat_template_sha256": chat_template_sha256,
        "terminal_state": terminal_state,
        "turns": turns,
        "limitations": limitations,
        "failed_model_calls": failed_model_calls,
        "acquisition_origin": acquisition_origin,
        "historical_candidate_provenance_only": acquisition_origin
        == "PHASE5_HISTORICAL_CANDIDATE_FRESH_REACQUISITION",
        "old_w1c_evidence_reused": acquisition_origin == "HISTORICAL_W1C_REUSE",
        "original_artifact_sha256": artifacts,
        "original_artifact_set_sha256": canonical_sha256(artifacts),
        "original_repository_git_sha": run.get("repository_git_sha"),
        "mini_swe_agent_git_sha": run.get("author_repository_git_sha"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--chat-template-sha256", required=True)
    parser.add_argument("--license-expression", required=True)
    parser.add_argument(
        "--acquisition-origin",
        choices=tuple(sorted(_ACQUISITION_ORIGINS)),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    record = build_mini_swe_acquisition_record(
        run_directory=arguments.run_directory.resolve(),
        chat_template_sha256=arguments.chat_template_sha256,
        license_expression=arguments.license_expression,
        acquisition_origin=arguments.acquisition_origin,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote: {arguments.output.resolve()}")
    print(f"sha256: {_sha256(arguments.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
