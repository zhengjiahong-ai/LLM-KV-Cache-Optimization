"""Convert Mini-SWE-Agent trajectories into auditable Phase 2 trace inputs.

This module is intentionally offline-only.  It does not download datasets,
execute an agent, or authorize a Native experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .phase2 import Phase2Trace, PlannedRequest

SCHEMA_VERSION = "continuum.workload_conversion.v1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _message_timestamp(message: Mapping[str, Any]) -> float | None:
    value = message.get("timestamp_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def convert_mini_swe_trajectory(
    trajectory: Mapping[str, Any],
    *,
    instance_id: str | None = None,
) -> tuple[Phase2Trace, dict[str, object]]:
    """Convert one ``mini-swe-agent-1`` trajectory without inventing evidence."""
    if trajectory.get("trajectory_format") != "mini-swe-agent-1":
        raise ValueError("unsupported Mini-SWE-Agent trajectory format")
    messages = trajectory.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("trajectory messages must be a non-empty list")
    if any(not isinstance(message, dict) for message in messages):
        raise TypeError("trajectory messages must be objects")

    resolved_id = instance_id or str(trajectory.get("info", {}).get("instance_id", ""))
    if not resolved_id:
        raise ValueError("instance_id is required")
    assistant_indexes = [
        index for index, message in enumerate(messages) if message.get("role") == "assistant"
    ]
    if not assistant_indexes:
        raise ValueError("trajectory has no model requests")

    first_timestamp = next(
        (
            timestamp
            for message in messages
            if (timestamp := _message_timestamp(message)) is not None
        ),
        None,
    )
    requests: list[PlannedRequest] = []
    request_evidence: list[dict[str, object]] = []
    previous_prompt = ""
    all_timestamps_observed = True
    all_token_ids_observed = True

    for turn_index, message_index in enumerate(assistant_indexes, start=1):
        assistant_message = messages[message_index]
        request_messages = messages[:message_index]
        if not request_messages:
            raise ValueError("assistant message cannot be the first trajectory message")
        prompt = _canonical_json(request_messages)
        timestamp = _message_timestamp(assistant_message)
        if timestamp is None or first_timestamp is None:
            arrival = float(turn_index - 1)
            timing_status = "IMPUTED_ORDINAL_NOT_SOURCE_OBSERVED"
            all_timestamps_observed = False
        else:
            arrival = max(0.0, timestamp - first_timestamp)
            timing_status = "SOURCE_OBSERVED"

        is_terminal = turn_index == len(assistant_indexes)
        next_user = next(
            (
                candidate
                for candidate in messages[message_index + 1 :]
                if candidate.get("role") == "user"
            ),
            None,
        )
        if is_terminal:
            gap = None
            tool_type = None
        else:
            next_timestamp = _message_timestamp(next_user) if next_user else None
            if timestamp is not None and next_timestamp is not None:
                gap = max(0.0, next_timestamp - timestamp)
            else:
                gap = 0.0
                all_timestamps_observed = False
            tool_type = "shell"

        token_ids = assistant_message.get("input_token_ids")
        token_status = "SOURCE_OBSERVED"
        if not isinstance(token_ids, list) or any(not isinstance(item, int) for item in token_ids):
            token_ids = None
            token_status = "NOT_OBSERVABLE_IN_PUBLIC_TRAJECTORY"
            all_token_ids_observed = False
        request_id = f"{resolved_id}:turn:{turn_index}"
        requests.append(
            PlannedRequest(
                program_id=resolved_id,
                request_id=request_id,
                turn_index=turn_index,
                planned_arrival_offset_seconds=arrival,
                prompt=prompt,
                prefix_prompt=previous_prompt,
                is_terminal=is_terminal,
                next_tool_type=tool_type,
                tool_gap_seconds=gap,
            )
        )
        request_evidence.append(
            {
                "request_id": request_id,
                "source_assistant_message_index": message_index,
                "materialized_prompt_sha256": _sha256_text(prompt),
                "prefix_prompt_sha256": _sha256_text(previous_prompt),
                "submitted_token_ids": token_ids,
                "submitted_token_ids_status": token_status,
                "timing_status": timing_status,
            }
        )
        previous_prompt = prompt

    trace = Phase2Trace(
        trace_id=f"continuum-swebench-{resolved_id}",
        requests=tuple(requests),
        pressure_stages=(),
    )
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": resolved_id,
        "source_trajectory_format": "mini-swe-agent-1",
        "source_trajectory_sha256": _sha256_text(_canonical_json(trajectory)),
        "request_count": len(requests),
        "request_evidence": request_evidence,
        "fidelity": {
            "message_order_preserved": True,
            "context_growth_preserved": True,
            "tool_observations_preserved_in_prompt": True,
            "source_timing_complete": all_timestamps_observed,
            "submitted_token_ids_complete": all_token_ids_observed,
        },
        "conversion_verdict": (
            "PASS"
            if all_timestamps_observed and all_token_ids_observed
            else "CONDITIONAL_PASS_MISSING_SOURCE_OBSERVATIONS"
        ),
    }
    return trace, report


def validate_conversion(
    trajectory: Mapping[str, Any], trace: Phase2Trace, report: Mapping[str, Any]
) -> dict[str, object]:
    messages = trajectory.get("messages")
    if not isinstance(messages, Sequence):
        raise TypeError("trajectory messages must be a sequence")
    assistant_indexes = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, Mapping) and message.get("role") == "assistant"
    ]
    expected_prompts = [_canonical_json(messages[:index]) for index in assistant_indexes]
    prompts_match = [request.prompt for request in trace.requests] == expected_prompts
    growth_match = all(
        request.prefix_prompt == ("" if index == 0 else trace.requests[index - 1].prompt)
        for index, request in enumerate(trace.requests)
    )
    evidence = report.get("request_evidence")
    identities_match = isinstance(evidence, list) and len(evidence) == len(trace.requests)
    hard_checks = prompts_match and growth_match and identities_match
    fidelity = report.get("fidelity", {})
    complete = (
        hard_checks
        and isinstance(fidelity, Mapping)
        and fidelity.get("source_timing_complete") is True
        and fidelity.get("submitted_token_ids_complete") is True
    )
    return {
        "schema_version": "continuum.workload_conversion_validation.v1",
        "checks": {
            "request_prompts_exact": prompts_match,
            "cumulative_context_growth_exact": growth_match,
            "request_identity_complete": identities_match,
            "source_timing_complete": fidelity.get("source_timing_complete", False)
            if isinstance(fidelity, Mapping)
            else False,
            "submitted_token_ids_complete": fidelity.get("submitted_token_ids_complete", False)
            if isinstance(fidelity, Mapping)
            else False,
        },
        "verdict": "PASS" if complete else "CONDITIONAL_PASS" if hard_checks else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--instance-id")
    args = parser.parse_args()
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8"))
    trace, report = convert_mini_swe_trajectory(trajectory, instance_id=args.instance_id)
    validation = validate_conversion(trajectory, trace, report)
    args.output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "trace.json": trace.to_dict(),
        "conversion-report.json": report,
        "validation-report.json": validation,
    }
    for name, payload in outputs.items():
        (args.output_root / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"wrote Continuum workload conversion: {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
