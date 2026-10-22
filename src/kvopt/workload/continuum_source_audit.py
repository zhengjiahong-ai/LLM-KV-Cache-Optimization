"""Convert Mini-SWE-Agent trajectories into auditable Phase 2 trace inputs.

This module is intentionally offline-only.  It does not download datasets,
execute an agent, or authorize a Native experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
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
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("message timestamp must be finite")
    return result


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
    observed_timestamps = [
        timestamp
        for message in messages
        if (timestamp := _message_timestamp(message)) is not None
    ]
    if observed_timestamps != sorted(observed_timestamps):
        raise ValueError("message timestamps must be non-decreasing")
    requests: list[PlannedRequest] = []
    request_evidence: list[dict[str, object]] = []
    previous_prompt = ""
    all_token_ids_observed = True
    token_prefix_verified = True
    previous_token_ids: list[int] | None = None

    for turn_index, message_index in enumerate(assistant_indexes, start=1):
        assistant_message = messages[message_index]
        request_messages = messages[:message_index]
        if not request_messages:
            raise ValueError("assistant message cannot be the first trajectory message")
        prompt = _canonical_json(request_messages)
        timestamp = _message_timestamp(assistant_message)
        # Message timestamps do not have a proven submit/admit semantic.  Phase
        # 2 timing therefore stays ordinal even when diagnostic timestamps exist.
        arrival = float(turn_index - 1)
        timing_status = (
            "MESSAGE_TIMESTAMP_DIAGNOSTIC_NOT_REQUEST_TIMING"
            if timestamp is not None
            else "IMPUTED_ORDINAL_NOT_SOURCE_OBSERVED"
        )

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
            gap = 0.0
            tool_type = "shell"

        token_ids = assistant_message.get("input_token_ids")
        token_status = "SOURCE_OBSERVED"
        if not isinstance(token_ids, list) or any(not isinstance(item, int) for item in token_ids):
            token_ids = None
            token_status = "NOT_OBSERVABLE_IN_PUBLIC_TRAJECTORY"
            all_token_ids_observed = False
            previous_prefix_status: bool | None = None
            token_prefix_verified = False
        else:
            previous_prefix_status = (
                None
                if previous_token_ids is None
                else token_ids[: len(previous_token_ids)] == previous_token_ids
            )
            if previous_prefix_status is False:
                token_prefix_verified = False
        request_id = f"{resolved_id}:turn:{turn_index}"
        requests.append(
            PlannedRequest(
                program_id=resolved_id,
                request_id=request_id,
                turn_index=turn_index,
                planned_arrival_offset_seconds=arrival,
                prompt=prompt,
                # Canonical JSON arrays do not grow by literal suffix append:
                # the old closing bracket changes into a comma.  Do not expose
                # the logical parent as a physical prompt prefix.
                prefix_prompt="",
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
                "logical_parent_prompt_sha256": (
                    None if turn_index == 1 else _sha256_text(previous_prompt)
                ),
                "emitted_prefix_prompt_status": "UNKNOWN_NOT_MODEL_RENDERED",
                "submitted_token_ids": token_ids,
                "submitted_token_ids_status": token_status,
                "previous_submitted_tokens_are_prefix": previous_prefix_status,
                "timing_status": timing_status,
                "diagnostic_assistant_message_timestamp_seconds": timestamp,
                "diagnostic_next_user_message_timestamp_seconds": (
                    _message_timestamp(next_user) if next_user else None
                ),
            }
        )
        previous_prompt = prompt
        previous_token_ids = token_ids

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
            "logical_message_history_growth_preserved": True,
            "tool_observations_preserved_in_prompt": True,
            "synthetic_serialization_is_model_submitted_prompt": False,
            "literal_prompt_prefix_verified": False,
            "request_timing_complete": False,
            "submitted_token_ids_complete": all_token_ids_observed,
            "submitted_token_prefix_verified": (
                all_token_ids_observed and token_prefix_verified
            ),
        },
        "conversion_verdict": "CONDITIONAL_PASS_STRUCTURAL_ONLY",
    }
    return trace, report


def validate_conversion(
    trajectory: Mapping[str, Any], trace: Phase2Trace, report: Mapping[str, Any]
) -> dict[str, object]:
    source_info = trajectory.get("info")
    source_instance_id = source_info.get("instance_id") if isinstance(source_info, Mapping) else None
    report_instance_id = report.get("instance_id")
    identity = source_instance_id or report_instance_id
    expected_trace, expected_report = convert_mini_swe_trajectory(
        trajectory,
        instance_id=str(identity) if identity else None,
    )
    trace_matches = trace.to_dict() == expected_trace.to_dict()
    report_matches = dict(report) == expected_report
    literal_prefix_safe = all(request.prefix_prompt == "" for request in trace.requests)
    synthetic_parent_is_not_claimed_prefix = all(
        not request.prompt.startswith(trace.requests[index - 1].prompt)
        for index, request in enumerate(trace.requests)
        if index > 0
    )
    hard_checks = trace_matches and report_matches and literal_prefix_safe
    return {
        "schema_version": "continuum.workload_conversion_validation.v1",
        "checks": {
            "trace_recomputed_from_source": trace_matches,
            "report_hashes_and_provenance_recomputed": report_matches,
            "unverified_literal_prefix_not_emitted": literal_prefix_safe,
            "synthetic_parent_not_misclassified_as_literal_prefix": (
                synthetic_parent_is_not_claimed_prefix
            ),
            "request_timing_fidelity": False,
        },
        "verdict": "CONDITIONAL_PASS" if hard_checks else "FAIL",
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
