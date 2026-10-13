"""Frozen contracts and preflight checks for the bounded Phase 2C native pilot."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kvopt.workload.phase2b_fidelity import prefix_content_token_ids

PILOT_RUN_KIND = "NON_HOLDOUT_NATIVE_PILOT"
PILOT_TOPOLOGIES = {
    "W-COLD",
    "W-EXACT",
    "W-XPROGRAM",
    "W-ROOT-FORK",
    "W-NESTED",
    "W-TURN-GROW",
    "W-HOT-COLD",
    "W-PRESSURE",
}
PILOT_PREFIX_GENERATOR_VERSION = "phase2c-segmented-prefix-v1"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON document must be an object: {path}")
    return value


def _segments(request: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    raw = request.get("segments")
    if not isinstance(raw, list) or not raw:
        raise ValueError("pilot request must contain non-empty segments")
    result: list[tuple[str, int]] = []
    for segment in raw:
        if (
            not isinstance(segment, list)
            or len(segment) != 2
            or not isinstance(segment[0], str)
            or not segment[0]
            or not isinstance(segment[1], int)
            or isinstance(segment[1], bool)
            or segment[1] <= 0
        ):
            raise TypeError("segment must be [non-empty content key, positive tokens]")
        result.append((segment[0], segment[1]))
    return tuple(result)


def expected_segment_lcp_tokens(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> int:
    """Return the preregistered LCP from whole explicit content segments."""
    total = 0
    for left_segment, right_segment in zip(_segments(left), _segments(right), strict=False):
        if left_segment != right_segment:
            break
        total += left_segment[1]
    return total


def segmented_prefix_token_ids(
    segments: Sequence[tuple[str, int]],
    *,
    vocabulary_size: int,
) -> tuple[int, ...]:
    """Materialize explicit whole-block content segments in declared order."""
    token_ids: list[int] = []
    for content_key, token_count in segments:
        token_ids.extend(
            prefix_content_token_ids(
                f"{PILOT_PREFIX_GENERATOR_VERSION}:{content_key}",
                vocabulary_size=vocabulary_size,
                token_count=token_count,
            )
        )
    return tuple(token_ids)


def segmented_turn_token_ids(
    request_id: str,
    segments: Sequence[tuple[str, int]],
    *,
    vocabulary_size: int,
) -> tuple[int, ...]:
    """Append the legacy request suffix after the reusable segmented prefix."""
    prefix = segmented_prefix_token_ids(segments, vocabulary_size=vocabulary_size)
    digest = hashlib.sha256(f"phase2c-suffix-v1:{request_id}".encode()).digest()
    suffix_only = (30_000 + int.from_bytes(digest[:4], "big") % 5_000) % vocabulary_size
    return (*prefix, suffix_only)


def validate_pilot_documents(
    authorization: Mapping[str, Any],
    contract: Mapping[str, Any],
    cases: Mapping[str, Any],
) -> None:
    """Reject scope drift and inconsistent content relations before execution."""
    if authorization.get("schema_version") != "phase2c.native_pilot_authorization.v1":
        raise ValueError("unsupported native pilot authorization")
    if authorization.get("authorization_status") != "AUTHORIZED":
        raise ValueError("native pilot is not authorized")
    for document in (authorization, contract, cases):
        if document.get("run_kind") != PILOT_RUN_KIND:
            raise ValueError("pilot documents must use NON_HOLDOUT_NATIVE_PILOT")
        if document.get("formal_campaign_authorized") is not False:
            raise ValueError("formal campaign must remain unauthorized")
        if document.get("cost_aware_policy_authorized") is not False:
            raise ValueError("Cost-Aware policy must remain unauthorized")
    if contract.get("schema_version") != "phase2c.native_pilot_contract.v1":
        raise ValueError("unsupported native pilot contract")
    if cases.get("schema_version") != "phase2c.native_pilot_cases.v1":
        raise ValueError("unsupported native pilot cases schema")
    if contract.get("controlled_repeats") != cases.get("controlled_repeats"):
        raise ValueError("controlled repeat count differs between contract and cases")
    if cases.get("controlled_repeats") != 2:
        raise ValueError("bounded pilot repeat count must remain two")
    block_size = cases.get("block_size_tokens")
    if block_size != 16:
        raise ValueError("bounded pilot requires the pinned 16-token block size")

    raw_cases = cases.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("pilot cases must be a non-empty list")
    case_ids = [row.get("case_id") for row in raw_cases if isinstance(row, dict)]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("pilot case IDs must be unique")
    if case_ids != contract.get("topology_case_ids"):
        raise ValueError("pilot case order differs from the frozen contract")
    if {row.get("topology") for row in raw_cases} != PILOT_TOPOLOGIES:
        raise ValueError("pilot cases must cover exactly the accepted topology set")

    for case in raw_cases:
        requests = case.get("requests")
        if not isinstance(requests, list) or not requests:
            raise ValueError("each pilot case must contain requests")
        by_request: dict[str, Mapping[str, Any]] = {}
        for request in requests:
            if not isinstance(request, dict):
                raise TypeError("pilot request must be an object")
            request_id = request.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                raise TypeError("pilot request_id must be non-empty text")
            if request_id in by_request:
                raise ValueError("request IDs must be unique within a case")
            segments = _segments(request)
            if any(tokens % block_size for _key, tokens in segments):
                raise ValueError("every reusable segment must be block aligned")
            declared = request.get("eligible_prefix_tokens")
            if not isinstance(declared, int) or isinstance(declared, bool) or declared < 0:
                raise TypeError("eligible_prefix_tokens must be a non-negative integer")
            reference_id = request.get("lcp_with")
            if reference_id is None:
                if declared != 0:
                    raise ValueError("request without lcp_with must not claim eligibility")
            else:
                reference = by_request.get(reference_id)
                if reference is None:
                    raise ValueError("lcp_with must reference an earlier request")
                expected = expected_segment_lcp_tokens(reference, request)
                if declared != expected:
                    raise ValueError(
                        f"declared eligible prefix {declared} differs from segment LCP {expected}"
                    )
            by_request[request_id] = request

    pressure_cases = [row for row in raw_cases if row.get("topology") == "W-PRESSURE"]
    if len(pressure_cases) != 2:
        raise ValueError("W-PRESSURE requires exactly one paired control and treatment")
    if {row.get("pressure") for row in pressure_cases} != {
        "none",
        "controlled_native_allocation",
    }:
        raise ValueError("W-PRESSURE pair must contain no-pressure and native-pressure cases")
    if len({row.get("pair_id") for row in pressure_cases}) != 1:
        raise ValueError("W-PRESSURE cases must share one pair_id")
    pressure_sequences = [
        tuple(_segments(request) for request in row["requests"])
        for row in pressure_cases
    ]
    if pressure_sequences[0] != pressure_sequences[1]:
        raise ValueError("W-PRESSURE pair must keep content identity fixed")


def load_and_validate_pilot(
    *,
    authorization_path: Path,
    contract_path: Path,
    cases_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authorization = _load_object(authorization_path)
    contract = _load_object(contract_path)
    cases = _load_object(cases_path)
    validate_pilot_documents(authorization, contract, cases)
    return authorization, contract, cases
