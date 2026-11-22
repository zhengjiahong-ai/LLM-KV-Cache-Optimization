"""Fail-closed lifecycle evidence for the bounded BFCL paired pilot."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

from .phase5_replay import canonical_sha256
from .phase5_trace_contract import NormalizedAgentTrace
from .phase5_workload_qualification import (
    AcquisitionTerminalState,
    map_acquisition_terminal_state,
)

_CASE_ID: ContextVar[str | None] = ContextVar("phase5_bfcl_pilot_case", default=None)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class BFCLPilotEvidenceError(RuntimeError):
    """Raised when lifecycle evidence cannot satisfy the frozen pilot contract."""


class BFCLPilotEvidenceRecorder:
    """Write ordered model/tool events from one monotonic clock domain."""

    def __init__(
        self,
        *,
        path: Path,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], str] | None = None,
    ) -> None:
        self.path = path
        self._monotonic = monotonic
        self._utc_now = utc_now or (
            lambda: datetime.now(timezone.utc).isoformat()
        )
        self._lock = threading.Lock()
        self._ordinals: Counter[str] = Counter()
        self._model_requests: Counter[str] = Counter()

    @contextmanager
    def bind_case(self, case_id: str) -> Iterator[None]:
        if not case_id:
            raise BFCLPilotEvidenceError("case identity cannot be empty")
        token = _CASE_ID.set(case_id)
        try:
            yield
        finally:
            _CASE_ID.reset(token)

    def record(self, event: str, **payload: object) -> dict[str, object]:
        case_id = _CASE_ID.get()
        if not case_id:
            raise BFCLPilotEvidenceError("lifecycle event has no bound case identity")
        with self._lock:
            self._ordinals[case_id] += 1
            row = {
                "schema_version": "phase5.bfcl_pilot_lifecycle_event.v1",
                "case_id": case_id,
                "event_ordinal": self._ordinals[case_id],
                "event": event,
                "clock_domain": "system_monotonic",
                "monotonic_seconds": float(self._monotonic()),
                "observed_at_utc": self._utc_now(),
                **payload,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    @contextmanager
    def instrument_model_query(self, handler: object) -> Iterator[None]:
        """Record dispatch and fully consumed response around BFCL's query call."""

        original = handler._query_FC  # type: ignore[attr-defined]

        def wrapped(inference_data: dict[str, object]) -> Any:
            case_id = _CASE_ID.get()
            if not case_id:
                raise BFCLPilotEvidenceError("model query has no bound case identity")
            self._model_requests[case_id] += 1
            request_ordinal = self._model_requests[case_id]
            request_id = f"{case_id}:request:{request_ordinal}"
            self.record(
                "MODEL_REQUEST_DISPATCH",
                request_id=request_id,
                request_ordinal=request_ordinal,
            )
            try:
                result = original(inference_data)
            except BaseException as error:
                self.record(
                    "MODEL_REQUEST_FAILED",
                    request_id=request_id,
                    request_ordinal=request_ordinal,
                    error_type=type(error).__name__,
                )
                raise
            self.record(
                "MODEL_RESPONSE_COMPLETE",
                request_id=request_id,
                request_ordinal=request_ordinal,
            )
            return result

        handler._query_FC = wrapped  # type: ignore[attr-defined]
        try:
            yield
        finally:
            handler._query_FC = original  # type: ignore[attr-defined]

    def terminal(
        self,
        state: AcquisitionTerminalState,
        *,
        censor_reason: str | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, object]:
        trace_state = map_acquisition_terminal_state(
            state, censor_reason=censor_reason
        )
        if trace_state.value == "FAILED" and not failure_reason:
            raise BFCLPilotEvidenceError("failed terminal requires failure_reason")
        return self.record(
            "SESSION_TERMINAL",
            acquisition_terminal_state=state.value,
            trace_terminal_state=trace_state.value,
            censor_reason=censor_reason,
            failure_reason=failure_reason,
        )


def classify_inference_terminal(
    result: object, *, error: BaseException | None = None
) -> tuple[AcquisitionTerminalState, str | None]:
    """Classify the runner outcome without treating error strings as success."""

    if error is not None:
        return (
            AcquisitionTerminalState.MODEL_FAILURE,
            f"{type(error).__name__}: {error}",
        )
    if isinstance(result, str) and result.startswith("Error during inference:"):
        return AcquisitionTerminalState.MODEL_FAILURE, result
    return AcquisitionTerminalState.NATURAL_COMPLETION, None


def validate_provider_approval(
    path: Path,
    *,
    expected_case_bindings: Sequence[Mapping[str, object]],
    expected_provider: str,
) -> dict[str, object]:
    """Resolve every authority/domain hash before any endpoint network call."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BFCLPilotEvidenceError("provider approval must be a JSON object")
    approval_root = path.parent.resolve()

    def file_sha256(candidate: Path) -> str:
        return hashlib.sha256(candidate.read_bytes()).hexdigest()

    def evidence_matches(row: object) -> bool:
        if not isinstance(row, dict):
            return False
        relative = row.get("evidence_path")
        expected_sha = row.get("evidence_sha256")
        if not isinstance(relative, str) or not isinstance(expected_sha, str):
            return False
        candidate = (approval_root / relative).resolve()
        if candidate != approval_root and approval_root not in candidate.parents:
            return False
        return (
            candidate.is_file()
            and _SHA256.fullmatch(expected_sha) is not None
            and file_sha256(candidate) == expected_sha
        )

    bindings = [dict(row) for row in expected_case_bindings]
    native_ids = [str(row["native_case_id"]) for row in bindings]
    domains = value.get("page_fetch_domains")
    reviews = value.get("domain_reviews")
    domain_reviews_valid = (
        isinstance(domains, list)
        and bool(domains)
        and len(set(domains)) == len(domains)
        and isinstance(reviews, list)
        and len(reviews) == len(domains)
        and {row.get("domain") for row in reviews if isinstance(row, dict)}
        == set(domains)
        and all(
            isinstance(row, dict)
            and row.get("technical_provenance_status") == "ACCEPTED"
            and row.get("publisher_permission_status") == "CONFIRMED"
            and row.get("robots_status") == "ALLOWED"
            and row.get("access_control_status") == "PUBLIC_NO_LOGIN_NO_PAYWALL"
            and evidence_matches(row)
            for row in reviews
        )
    )
    authority_evidence = value.get("authority_evidence")
    authority_bound = (
        isinstance(authority_evidence, dict)
        and set(authority_evidence) == {"m1", "m4"}
        and all(evidence_matches(row) for row in authority_evidence.values())
    )
    checks = {
        "STATUS_APPROVED": value.get("status") == "APPROVED",
        "EXACT_CASE_IDS": value.get("case_ids") == native_ids,
        "FORMAL_NATIVE_CASE_BINDINGS": value.get("case_bindings") == bindings,
        "PROVIDER_PINNED": value.get("provider") == expected_provider,
        "API_VERSION_PINNED": bool(value.get("api_version")),
        "PAGE_FETCH_DOMAINS_PINNED": isinstance(domains, list) and bool(domains),
        "PER_DOMAIN_REVIEWS_ACCEPTED": domain_reviews_valid,
        "AUTHORITY_EVIDENCE_HASH_BOUND": authority_bound,
        "M4_TECHNICAL_PROVENANCE_ACCEPTED": (
            value.get("m4_technical_provenance_accepted") is True
        ),
        "M1_PERMISSION_CONFIRMED": value.get("m1_permission_confirmed") is True,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BFCLPilotEvidenceError(
            f"provider approval is not execution-ready: {failed}"
        )
    approval_sha = file_sha256(path)
    return {**value, "checks": checks, "approval_sha256": approval_sha}


def load_lifecycle_events(path: Path) -> tuple[dict[str, object], ...]:
    """Load lifecycle JSONL without accepting non-object rows."""

    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise BFCLPilotEvidenceError(f"non-object lifecycle row {line_number}")
        rows.append(value)
    return tuple(rows)


def evaluate_paired_pilot_lifecycle(
    events: Sequence[Mapping[str, object]], *, expected_case_ids: Sequence[str]
) -> dict[str, object]:
    """Recompute Tool Gaps and terminal evidence for the exact frozen pair."""

    if len(expected_case_ids) != 2 or len(set(expected_case_ids)) != 2:
        raise BFCLPilotEvidenceError("paired pilot requires two unique case IDs")
    by_case: dict[str, list[Mapping[str, object]]] = {
        case_id: [] for case_id in expected_case_ids
    }
    unexpected = []
    for row in events:
        case_id = str(row.get("case_id"))
        if case_id not in by_case:
            unexpected.append(case_id)
            continue
        by_case[case_id].append(row)

    cases = []
    for case_id in expected_case_ids:
        rows = by_case[case_id]
        ordinals = [row.get("event_ordinal") for row in rows]
        clocks = {row.get("clock_domain") for row in rows}
        dispatches = [
            row for row in rows if row.get("event") == "MODEL_REQUEST_DISPATCH"
        ]
        completions = [
            row for row in rows if row.get("event") == "MODEL_RESPONSE_COMPLETE"
        ]
        terminals = [row for row in rows if row.get("event") == "SESSION_TERMINAL"]
        tool_calls = [row for row in rows if row.get("event") == "TOOL_CALL_EMISSION"]
        tool_results = [
            row for row in rows if row.get("event") == "TOOL_RESULT_DELIVERY"
        ]
        provider_dispatches = [
            row for row in rows if row.get("event") == "PROVIDER_REQUEST_DISPATCH"
        ]
        provider_outcomes = [
            row
            for row in rows
            if row.get("event")
            in {"PROVIDER_RESPONSE_COMPLETE", "PROVIDER_REQUEST_FAILED"}
        ]
        times = [row.get("monotonic_seconds") for row in rows]
        gaps = []
        for completion, dispatch in zip(completions, dispatches[1:], strict=False):
            end = completion.get("monotonic_seconds")
            start = dispatch.get("monotonic_seconds")
            valid = (
                isinstance(end, (int, float))
                and not isinstance(end, bool)
                and math.isfinite(float(end))
                and isinstance(start, (int, float))
                and not isinstance(start, bool)
                and math.isfinite(float(start))
                and float(start) >= float(end)
                and completion.get("clock_domain") == dispatch.get("clock_domain")
                and isinstance(completion.get("event_ordinal"), int)
                and isinstance(dispatch.get("event_ordinal"), int)
                and int(completion["event_ordinal"])
                < int(dispatch["event_ordinal"])
            )
            gaps.append(
                {
                    "model_response_complete_ordinal": completion.get(
                        "event_ordinal"
                    ),
                    "next_model_request_dispatch_ordinal": dispatch.get(
                        "event_ordinal"
                    ),
                    "clock_domain": (
                        completion.get("clock_domain") if valid else None
                    ),
                    "tool_gap_seconds": float(start) - float(end) if valid else None,
                    "valid": valid,
                }
            )
        expected_gap_count = max(0, len(dispatches) - 1)
        model_order_valid = len(dispatches) == len(completions) and all(
            dispatch.get("request_id") == completion.get("request_id")
            and isinstance(dispatch.get("event_ordinal"), int)
            and isinstance(completion.get("event_ordinal"), int)
            and int(dispatch["event_ordinal"]) < int(completion["event_ordinal"])
            for dispatch, completion in zip(dispatches, completions, strict=True)
        )
        tool_order_valid = len(tool_calls) == len(tool_results) and all(
            call.get("tool_call_id") == result.get("tool_call_id")
            and isinstance(call.get("event_ordinal"), int)
            and isinstance(result.get("event_ordinal"), int)
            and int(call["event_ordinal"]) < int(result["event_ordinal"])
            for call, result in zip(tool_calls, tool_results, strict=True)
        )
        provider_order_valid = len(provider_dispatches) == len(provider_outcomes) and all(
            dispatch.get("provider_request_id") == outcome.get("provider_request_id")
            and isinstance(dispatch.get("event_ordinal"), int)
            and isinstance(outcome.get("event_ordinal"), int)
            and int(dispatch["event_ordinal"]) < int(outcome["event_ordinal"])
            for dispatch, outcome in zip(
                provider_dispatches, provider_outcomes, strict=True
            )
        )
        terminal_mapping_valid = False
        terminal_reason_valid = False
        if len(terminals) == 1:
            terminal = terminals[0]
            try:
                acquisition = AcquisitionTerminalState(
                    str(terminal.get("acquisition_terminal_state"))
                )
                expected_trace = map_acquisition_terminal_state(
                    acquisition,
                    censor_reason=(
                        str(terminal["censor_reason"])
                        if terminal.get("censor_reason") is not None
                        else None
                    ),
                )
                terminal_mapping_valid = (
                    terminal.get("trace_terminal_state") == expected_trace.value
                )
                terminal_reason_valid = (
                    expected_trace.value != "FAILED"
                    or bool(str(terminal.get("failure_reason") or "").strip())
                )
            except (ValueError, TypeError):
                pass
        checks = {
            "EVENTS_PRESENT": bool(rows),
            "ORDINALS_CONTIGUOUS": ordinals == list(range(1, len(rows) + 1)),
            "SINGLE_MONOTONIC_CLOCK": clocks == {"system_monotonic"},
            "FINITE_NONDECREASING_EVENT_TIMES": (
                all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    for value in times
                )
                and all(
                    float(later) >= float(earlier)
                    for earlier, later in pairwise(times)
                )
            ),
            "MODEL_BOUNDARIES_BALANCED": len(dispatches) == len(completions),
            "MODEL_BOUNDARY_ORDER": model_order_valid,
            "MINIMUM_MODEL_REQUESTS": len(dispatches) >= 2,
            "TOOL_CALL_RESULT_BALANCED": tool_order_valid and bool(tool_calls),
            "PROVIDER_LIFECYCLE_BALANCED": (
                provider_order_valid and bool(provider_dispatches)
            ),
            "ALL_TOOL_GAPS_OBSERVED": (
                len(gaps) == expected_gap_count
                and all(gap["valid"] is True for gap in gaps)
            ),
            "EXACTLY_ONE_TERMINAL": len(terminals) == 1,
            "TERMINAL_IS_LAST_EVENT": (
                len(terminals) == 1
                and terminals[0].get("event_ordinal") == len(rows)
            ),
            "TERMINAL_NOT_INFERRED": (
                len(terminals) == 1
                and terminals[0].get("acquisition_terminal_state") is not None
            ),
            "TERMINAL_MAPPING_VALID": terminal_mapping_valid,
            "TERMINAL_REASON_VALID": terminal_reason_valid,
        }
        cases.append(
            {
                "case_id": case_id,
                "event_count": len(rows),
                "model_request_count": len(dispatches),
                "tool_gaps": gaps,
                "terminal": terminals[0] if len(terminals) == 1 else None,
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL_CLOSED",
            }
        )

    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_paired_pilot_lifecycle.v1",
        "expected_case_ids": list(expected_case_ids),
        "unexpected_case_ids": sorted(set(unexpected)),
        "cases": cases,
        "status": (
            "PASS"
            if not unexpected and all(case["status"] == "PASS" for case in cases)
            else "FAIL_CLOSED"
        ),
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "lifecycle_sha256": canonical_sha256(payload)}


def validate_lifecycle_trace_binding(
    events: Sequence[Mapping[str, object]],
    *,
    case_id: str,
    trace: NormalizedAgentTrace,
) -> dict[str, object]:
    """Bind normalized Q4 timestamps to their originating lifecycle events."""

    rows = [row for row in events if row.get("case_id") == case_id]
    dispatches = [
        row for row in rows if row.get("event") == "MODEL_REQUEST_DISPATCH"
    ]
    completions = [
        row for row in rows if row.get("event") == "MODEL_RESPONSE_COMPLETE"
    ]
    turn_bindings = []
    for turn, dispatch, completion in zip(
        trace.turns, dispatches, completions, strict=False
    ):
        checks = {
            "REQUEST_ID_MATCH": turn.request_id == dispatch.get("request_id")
            and turn.request_id == completion.get("request_id"),
            "SUBMISSION_BOUND": (
                turn.submitted_at_seconds == dispatch.get("monotonic_seconds")
            ),
            "COMPLETION_BOUND": (
                turn.completed_at_seconds == completion.get("monotonic_seconds")
            ),
            "CLOCK_BOUND": (
                turn.clock_domain == "system_monotonic"
                and dispatch.get("clock_domain") == turn.clock_domain
                and completion.get("clock_domain") == turn.clock_domain
            ),
        }
        turn_bindings.append(
            {
                "turn_id": turn.turn_id,
                "request_id": turn.request_id,
                "dispatch_event_ordinal": dispatch.get("event_ordinal"),
                "completion_event_ordinal": completion.get("event_ordinal"),
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL_CLOSED",
            }
        )
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_lifecycle_trace_binding.v1",
        "case_id": case_id,
        "trace_id": trace.trace_id,
        "source_trace_sha256": trace.sha256,
        "turn_count": len(trace.turns),
        "dispatch_count": len(dispatches),
        "completion_count": len(completions),
        "turn_bindings": turn_bindings,
        "status": (
            "PASS"
            if len(trace.turns) == len(dispatches) == len(completions)
            and all(row["status"] == "PASS" for row in turn_bindings)
            else "FAIL_CLOSED"
        ),
    }
    return {**payload, "binding_sha256": canonical_sha256(payload)}
