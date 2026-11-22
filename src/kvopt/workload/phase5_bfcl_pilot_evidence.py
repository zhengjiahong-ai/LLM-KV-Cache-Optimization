"""Fail-closed lifecycle evidence for the bounded BFCL paired pilot."""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .phase5_replay import canonical_sha256
from .phase5_workload_qualification import (
    AcquisitionTerminalState,
    map_acquisition_terminal_state,
)

_CASE_ID: ContextVar[str | None] = ContextVar("phase5_bfcl_pilot_case", default=None)


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
            self.record("MODEL_REQUEST_DISPATCH")
            try:
                result = original(inference_data)
            except BaseException as error:
                self.record(
                    "MODEL_REQUEST_FAILED",
                    error_type=type(error).__name__,
                )
                raise
            self.record("MODEL_RESPONSE_COMPLETE")
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
        gaps = []
        for completion, dispatch in zip(completions, dispatches[1:], strict=False):
            end = completion.get("monotonic_seconds")
            start = dispatch.get("monotonic_seconds")
            valid = (
                isinstance(end, (int, float))
                and not isinstance(end, bool)
                and isinstance(start, (int, float))
                and not isinstance(start, bool)
                and float(start) >= float(end)
                and completion.get("clock_domain") == dispatch.get("clock_domain")
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
        checks = {
            "EVENTS_PRESENT": bool(rows),
            "ORDINALS_CONTIGUOUS": ordinals == list(range(1, len(rows) + 1)),
            "SINGLE_MONOTONIC_CLOCK": clocks == {"system_monotonic"},
            "MODEL_BOUNDARIES_BALANCED": len(dispatches) == len(completions),
            "ALL_TOOL_GAPS_OBSERVED": (
                len(gaps) == expected_gap_count
                and all(gap["valid"] is True for gap in gaps)
            ),
            "EXACTLY_ONE_TERMINAL": len(terminals) == 1,
            "TERMINAL_NOT_INFERRED": (
                len(terminals) == 1
                and terminals[0].get("acquisition_terminal_state") is not None
            ),
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
