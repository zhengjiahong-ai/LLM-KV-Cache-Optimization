"""Fail-closed W1-A CLI over the immutable W0 trajectory converter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path

from .continuum_source_audit import convert_mini_swe_trajectory, validate_conversion

SIDECAR_SCHEMA_VERSION = "continuum.w1a_acquisition_sidecar.v1"


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
    trajectory_path: Path,
    instance_id: str,
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
    for row in model_calls:
        request_id = str(row["request_id"])
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
        prefix_status: bool | None = None
        if tokens is not None and previous_tokens is not None:
            prefix_status = tokens[: len(previous_tokens)] == previous_tokens
            prefix_checks.append(prefix_status)
        tool = tool_by_request.get(request_id)
        tool_evidence: dict[str, object] | None = None
        if tool is not None:
            tool_start = _finite_number(
                tool.get("tool_start_monotonic_seconds"), "tool start time"
            )
            tool_completion = _finite_number(
                tool.get("tool_completion_monotonic_seconds"), "tool completion time"
            )
            if tool_completion < tool_start or tool_start < completion:
                raise ValueError("tool timing is inconsistent with its model request")
            tool_evidence = {
                "status": tool.get("status"),
                "action_sha256": tool.get("action_sha256"),
                "tool_start_monotonic_seconds": tool_start,
                "tool_completion_monotonic_seconds": tool_completion,
                "tool_elapsed_seconds": tool_completion - tool_start,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--instance-id")
    args = parser.parse_args()
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8"))
    if not isinstance(trajectory, dict):
        raise TypeError("trajectory must be an object")
    instance_id, identity_provenance = resolve_instance_id(trajectory, args.instance_id)
    trace, report = convert_mini_swe_trajectory(trajectory, instance_id=instance_id)
    validation = validate_conversion(trajectory, trace, report)
    validation["instance_id_provenance"] = identity_provenance
    sidecar_evidence = None
    if args.sidecar is not None:
        sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
        if not isinstance(sidecar, dict):
            raise TypeError("sidecar must be an object")
        sidecar_evidence = build_sidecar_evidence(
            sidecar,
            trajectory_path=args.trajectory,
            instance_id=instance_id,
        )
        validation["checks"]["acquisition_sidecar_valid"] = True
        validation["checks"]["wrapper_request_timing_complete"] = sidecar_evidence[
            "wrapper_timing_complete"
        ]
        validation["checks"]["deterministic_tokenization_complete"] = sidecar_evidence[
            "deterministic_tokenization_complete"
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
