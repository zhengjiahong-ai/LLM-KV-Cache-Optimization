"""CPU-only contracts for Phase 5 multi-program replay preparation.

The module deliberately does not replace the accepted two-session Native
runner.  It freezes N-session timing and identity inputs, produces an auditable
event plan, and verifies the observed Native submission stream.  A later GPU
stage must bind an asynchronous backend to this contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from itertools import pairwise

_SHA256 = re.compile(r"[0-9a-f]{64}")


def canonical_sha256(value: object) -> str:
    """Hash one JSON-compatible value using the project canonical form."""

    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _seconds(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class ArrivalMode(StrEnum):
    FIXED = "FIXED"
    FROZEN_POISSON = "FROZEN_POISSON"


class EventKind(StrEnum):
    ARRIVAL = "ARRIVAL"
    COMPLETION = "COMPLETION"


@dataclass(frozen=True, slots=True)
class ProgramStart:
    program_id: str
    start_offset_seconds: float
    ordinal: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArrivalPlan:
    mode: ArrivalMode
    starts: tuple[ProgramStart, ...]
    fixed_stagger_seconds: float | None
    poisson_rate_per_second: float | None
    seed: int | None
    generator: str

    def __post_init__(self) -> None:
        if len(self.starts) < 2:
            raise ValueError("Phase 5 arrival plan requires at least two programs")
        if len({row.program_id for row in self.starts}) != len(self.starts):
            raise ValueError("arrival plan program IDs must be unique")
        if tuple(row.ordinal for row in self.starts) != tuple(
            range(1, len(self.starts) + 1)
        ):
            raise ValueError("arrival plan ordinals must be contiguous")
        offsets = tuple(row.start_offset_seconds for row in self.starts)
        if any(later < earlier for earlier, later in pairwise(offsets)):
            raise ValueError("program start offsets must be monotonic")
        if self.mode is ArrivalMode.FIXED:
            if self.fixed_stagger_seconds is None:
                raise ValueError("fixed arrival plan lacks its stagger")
            if self.poisson_rate_per_second is not None or self.seed is not None:
                raise ValueError("fixed arrival plan cannot carry Poisson parameters")
        elif (
            self.poisson_rate_per_second is None
            or self.poisson_rate_per_second <= 0
            or self.seed is None
        ):
            raise ValueError("Frozen-Poisson plan requires positive rate and seed")

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.arrival_plan.v1",
            "mode": self.mode.value,
            "starts": [row.to_dict() for row in self.starts],
            "fixed_stagger_seconds": self.fixed_stagger_seconds,
            "poisson_rate_per_second": self.poisson_rate_per_second,
            "seed": self.seed,
            "generator": self.generator,
        }


def fixed_arrival_plan(
    program_ids: Sequence[str], *, stagger_seconds: float
) -> ArrivalPlan:
    """Freeze deterministic, equally spaced program starts."""

    stagger = _seconds(stagger_seconds, "stagger_seconds")
    identities = tuple(_identity(row, "program_id") for row in program_ids)
    return ArrivalPlan(
        mode=ArrivalMode.FIXED,
        starts=tuple(
            ProgramStart(program_id, index * stagger, index + 1)
            for index, program_id in enumerate(identities)
        ),
        fixed_stagger_seconds=stagger,
        poisson_rate_per_second=None,
        seed=None,
        generator="DETERMINISTIC_EQUAL_STAGGER_V1",
    )


def frozen_poisson_arrival_plan(
    program_ids: Sequence[str], *, rate_per_second: float, seed: int
) -> ArrivalPlan:
    """Sample once and persist the realized Poisson inter-program arrivals."""

    rate = _seconds(rate_per_second, "rate_per_second")
    if rate == 0:
        raise ValueError("rate_per_second must be positive")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be int")
    identities = tuple(_identity(row, "program_id") for row in program_ids)
    rng = random.Random(seed)
    elapsed = 0.0
    starts: list[ProgramStart] = []
    for index, program_id in enumerate(identities):
        if index:
            elapsed += rng.expovariate(rate)
        starts.append(ProgramStart(program_id, elapsed, index + 1))
    return ArrivalPlan(
        mode=ArrivalMode.FROZEN_POISSON,
        starts=tuple(starts),
        fixed_stagger_seconds=None,
        poisson_rate_per_second=rate,
        seed=seed,
        generator="PYTHON_RANDOM_MT19937_EXPONENTIAL_V1",
    )


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    event_id: str
    logical_timestamp: float
    kind: EventKind
    program_id: str
    request_id: str
    turn_index: int
    source: str

    def to_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["kind"] = self.kind.value
        return row


@dataclass(frozen=True, slots=True)
class NSessionReplayPlan:
    arrival_plan_sha256: str
    events: tuple[ReplayEvent, ...]
    expected_native_enqueue_order: tuple[str, ...]
    per_program_request_order: Mapping[str, tuple[str, ...]]
    tie_break_rule: str

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.n_session_replay_plan.v1",
            "arrival_plan_sha256": self.arrival_plan_sha256,
            "events": [row.to_dict() for row in self.events],
            "expected_native_enqueue_order": list(self.expected_native_enqueue_order),
            "per_program_request_order": {
                key: list(value) for key, value in sorted(self.per_program_request_order.items())
            },
            "tie_break_rule": self.tie_break_rule,
        }


def materialize_n_session_plan(
    *,
    sessions: Mapping[str, Sequence[Mapping[str, object]]],
    arrival_plan: ArrivalPlan,
) -> NSessionReplayPlan:
    """Merge any number of source sessions without changing intra-session gaps."""

    starts = {row.program_id: row.start_offset_seconds for row in arrival_plan.starts}
    if set(sessions) != set(starts):
        raise ValueError("sessions and arrival plan program sets differ")
    events: list[ReplayEvent] = []
    orders: dict[str, tuple[str, ...]] = {}
    request_ids: set[str] = set()
    for program_id, calls in sessions.items():
        _identity(program_id, "program_id")
        if not calls:
            raise ValueError("each Phase 5 session must contain requests")
        first_submit = _seconds(
            calls[0].get("model_submit_monotonic_seconds"), "source submit timestamp"
        )
        previous_submit = first_submit
        order: list[str] = []
        for turn_index, call in enumerate(calls, start=1):
            request_id = _identity(call.get("request_id"), "request_id")
            if request_id in request_ids:
                raise ValueError("request IDs must be globally unique")
            request_ids.add(request_id)
            submitted = _seconds(
                call.get("model_submit_monotonic_seconds"), "source submit timestamp"
            )
            completed = _seconds(
                call.get("model_completion_monotonic_seconds"),
                "source completion timestamp",
            )
            if submitted < previous_submit:
                raise ValueError("source submissions must be monotonic per program")
            if completed <= submitted:
                raise ValueError("source request duration must be positive")
            declared_turn = call.get("turn_index", turn_index)
            if declared_turn != turn_index:
                raise ValueError("source turn indexes must be contiguous")
            previous_submit = submitted
            order.append(request_id)
            base = starts[program_id]
            events.extend(
                (
                    ReplayEvent(
                        event_id=f"arrival:{request_id}",
                        logical_timestamp=base + submitted - first_submit,
                        kind=EventKind.ARRIVAL,
                        program_id=program_id,
                        request_id=request_id,
                        turn_index=turn_index,
                        source="SOURCE_MODEL_SUBMIT_PLUS_FROZEN_PROGRAM_START",
                    ),
                    ReplayEvent(
                        event_id=f"completion:{request_id}",
                        logical_timestamp=base + completed - first_submit,
                        kind=EventKind.COMPLETION,
                        program_id=program_id,
                        request_id=request_id,
                        turn_index=turn_index,
                        source="SOURCE_MODEL_COMPLETION_PLUS_FROZEN_PROGRAM_START",
                    ),
                )
            )
        orders[program_id] = tuple(order)
    kind_order = {EventKind.COMPLETION: 0, EventKind.ARRIVAL: 1}
    events.sort(
        key=lambda row: (
            row.logical_timestamp,
            kind_order[row.kind],
            row.program_id,
            row.turn_index,
            row.request_id,
        )
    )
    expected = tuple(row.request_id for row in events if row.kind is EventKind.ARRIVAL)
    return NSessionReplayPlan(
        arrival_plan_sha256=arrival_plan.sha256,
        events=tuple(events),
        expected_native_enqueue_order=expected,
        per_program_request_order=orders,
        tie_break_rule="TIMESTAMP_COMPLETION_THEN_ARRIVAL_PROGRAM_TURN_REQUEST_V1",
    )


def evaluate_event_driven_capacity(
    replay_plan: NSessionReplayPlan, *, maximum_inflight_requests: int
) -> dict[str, object]:
    """Validate event-driven overlap without executing a Native backend.

    The result is a CPU planning proof.  It does not claim that vLLM reproduced
    the overlap; the actual enqueue gate remains mandatory after execution.
    """

    if (
        isinstance(maximum_inflight_requests, bool)
        or not isinstance(maximum_inflight_requests, int)
        or maximum_inflight_requests < 1
    ):
        raise ValueError("maximum_inflight_requests must be a positive integer")
    active: set[str] = set()
    seen_arrivals: set[str] = set()
    peak = 0
    over_capacity: list[dict[str, object]] = []
    timeline = []
    for row in replay_plan.events:
        if row.kind is EventKind.ARRIVAL:
            if row.request_id in seen_arrivals:
                raise ValueError("replay plan contains a duplicate arrival")
            seen_arrivals.add(row.request_id)
            active.add(row.request_id)
        else:
            if row.request_id not in active:
                raise ValueError("completion lacks one active request")
            active.remove(row.request_id)
        peak = max(peak, len(active))
        state = {
            "event_id": row.event_id,
            "logical_timestamp": row.logical_timestamp,
            "active_request_ids": sorted(active),
            "active_request_count": len(active),
        }
        timeline.append(state)
        if len(active) > maximum_inflight_requests:
            over_capacity.append(state)
    expected = set(replay_plan.expected_native_enqueue_order)
    if seen_arrivals != expected or active:
        raise ValueError("replay event lifecycle is incomplete")
    return {
        "schema_version": "phase5.event_driven_capacity.v1",
        "status": "PASS" if not over_capacity else "CAPACITY_EXCEEDED",
        "maximum_inflight_requests": maximum_inflight_requests,
        "peak_planned_inflight_requests": peak,
        "over_capacity_events": over_capacity,
        "timeline": timeline,
        "native_execution_claim": "NOT_EXECUTED_CPU_PLANNING_ONLY",
    }


def create_phase5_workload_seal(
    *,
    workload_id: str,
    source: Mapping[str, object],
    request_token_sha256: Mapping[str, str],
    replay_plan: NSessionReplayPlan,
) -> dict[str, object]:
    """Bind source, token identity and one realized replay plan."""

    identity = _identity(workload_id, "workload_id")
    expected = set(replay_plan.expected_native_enqueue_order)
    if set(request_token_sha256) != expected:
        raise ValueError("token identity map does not match replay requests")
    tokens = {
        _identity(key, "request_id"): _sha(value, "token_ids_sha256")
        for key, value in request_token_sha256.items()
    }
    required_source = ("kind", "revision", "license", "content_sha256")
    if any(key not in source for key in required_source):
        raise ValueError("workload source lacks provenance fields")
    source_row = dict(source)
    for key in ("kind", "revision", "license"):
        _identity(source_row[key], f"source.{key}")
    _sha(source_row["content_sha256"], "source.content_sha256")
    payload = {
        "schema_version": "phase5.workload_seal.v1",
        "workload_id": identity,
        "source": source_row,
        "program_ids": sorted(replay_plan.per_program_request_order),
        "request_token_ids_sha256": dict(sorted(tokens.items())),
        "replay_plan": replay_plan.to_dict(),
        "replay_plan_sha256": replay_plan.sha256,
        "native_enqueue_order_sha256": canonical_sha256(
            list(replay_plan.expected_native_enqueue_order)
        ),
        "execution_authorized": False,
    }
    return {**payload, "seal_content_sha256": canonical_sha256(payload)}


def validate_phase5_workload_seal(seal: Mapping[str, object]) -> None:
    """Fail closed on any self-binding or identity drift."""

    if seal.get("schema_version") != "phase5.workload_seal.v1":
        raise ValueError("unsupported Phase 5 workload seal")
    if seal.get("execution_authorized") is not False:
        raise ValueError("Phase 5A seal must not authorize execution")
    content = dict(seal)
    observed = content.pop("seal_content_sha256", None)
    if observed != canonical_sha256(content):
        raise ValueError("Phase 5 workload seal content hash mismatch")
    replay = seal.get("replay_plan")
    if not isinstance(replay, Mapping):
        raise TypeError("Phase 5 workload seal lacks replay plan")
    if seal.get("replay_plan_sha256") != canonical_sha256(replay):
        raise ValueError("Phase 5 replay plan hash mismatch")
    order = replay.get("expected_native_enqueue_order")
    if not isinstance(order, list) or not order:
        raise ValueError("Phase 5 replay plan lacks enqueue order")
    if len(order) != len(set(order)):
        raise ValueError("Phase 5 enqueue order contains duplicates")
    if seal.get("native_enqueue_order_sha256") != canonical_sha256(order):
        raise ValueError("Phase 5 enqueue-order hash mismatch")
    tokens = seal.get("request_token_ids_sha256")
    if not isinstance(tokens, Mapping) or set(tokens) != set(order):
        raise ValueError("Phase 5 token identities do not cover enqueue order")
    for value in tokens.values():
        _sha(value, "token_ids_sha256")


def evaluate_native_enqueue_order(
    *, seal: Mapping[str, object], events: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Compare the actual Native submission stream with the frozen seal."""

    validate_phase5_workload_seal(seal)
    replay = seal["replay_plan"]
    assert isinstance(replay, Mapping)
    expected_raw = replay["expected_native_enqueue_order"]
    per_program_raw = replay["per_program_request_order"]
    assert isinstance(expected_raw, list) and isinstance(per_program_raw, Mapping)
    expected = tuple(str(row) for row in expected_raw)
    expected_set = set(expected)
    submitted_rows = sorted(
        (row for row in events if row.get("event_type") == "VLLM_REQUEST_SUBMITTED"),
        key=lambda row: int(row.get("event_index", -1)),
    )
    actual = tuple(
        str(row["request_id"])
        for row in submitted_rows
        if row.get("request_id") in expected_set
    )
    unknown = tuple(
        str(row.get("request_id"))
        for row in submitted_rows
        if row.get("request_id") not in expected_set
        and not str(row.get("request_id", "")).startswith("pressure:")
    )
    duplicates = sorted({row for row in actual if actual.count(row) > 1})
    missing = sorted(expected_set - set(actual))
    per_program = {}
    per_program_valid = True
    for program_id, order_raw in per_program_raw.items():
        order = tuple(str(row) for row in order_raw)
        observed = tuple(row for row in actual if row in set(order))
        valid = observed == order
        per_program[str(program_id)] = {
            "expected": list(order),
            "actual": list(observed),
            "status": "PASS" if valid else "FAIL",
        }
        per_program_valid = per_program_valid and valid
    exact = actual == expected
    status = (
        "PASS"
        if exact and per_program_valid and not unknown and not duplicates and not missing
        else "FAIL_CLOSED"
    )
    return {
        "schema_version": "phase5.native_enqueue_order_gate.v1",
        "status": status,
        "expected_count": len(expected),
        "actual_count": len(actual),
        "expected_sequence_sha256": canonical_sha256(list(expected)),
        "actual_sequence_sha256": canonical_sha256(list(actual)),
        "exact_sequence_match": exact,
        "per_program_order_valid": per_program_valid,
        "per_program": per_program,
        "missing_request_ids": missing,
        "duplicate_request_ids": duplicates,
        "unknown_nonpressure_request_ids": list(unknown),
    }


def validate_cross_arm_enqueue_equality(
    reports: Mapping[str, Mapping[str, object]], *, required_arms: Sequence[str]
) -> dict[str, object]:
    """Require every arm to pass and expose one identical actual sequence."""

    arms = tuple(required_arms)
    if set(reports) != set(arms) or len(arms) != len(set(arms)):
        raise ValueError("cross-arm enqueue audit arm set mismatch")
    if any(report.get("status") != "PASS" for report in reports.values()):
        return {
            "schema_version": "phase5.cross_arm_enqueue_gate.v1",
            "status": "FAIL_CLOSED",
            "reason": "ONE_OR_MORE_ARM_GATES_FAILED",
        }
    digests = {
        str(report.get("actual_sequence_sha256")) for report in reports.values()
    }
    return {
        "schema_version": "phase5.cross_arm_enqueue_gate.v1",
        "status": "PASS" if len(digests) == 1 else "FAIL_CLOSED",
        "reason": "IDENTICAL" if len(digests) == 1 else "CROSS_ARM_SEQUENCE_MISMATCH",
        "actual_sequence_sha256": next(iter(digests)) if len(digests) == 1 else None,
    }


def group_events_by_program(
    events: Sequence[ReplayEvent],
) -> Mapping[str, tuple[ReplayEvent, ...]]:
    """Small inspection helper used by CPU design tests and reports."""

    grouped: dict[str, list[ReplayEvent]] = defaultdict(list)
    for row in events:
        grouped[row.program_id].append(row)
    return {key: tuple(value) for key, value in sorted(grouped.items())}

