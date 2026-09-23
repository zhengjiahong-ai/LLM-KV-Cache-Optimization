from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Any

import pytest

from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    FakeClock,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    SchedulerMode,
    SchedulingCandidate,
    TurnFinished,
)
from kvopt.continuum.runtime import build_runtime

PROGRAM_A = ProgramIdentity("program-a")
PROGRAM_B = ProgramIdentity("program-b")
REQUEST_A = RequestIdentity("request-a")
REQUEST_B = RequestIdentity("request-b")
REQUEST_C = RequestIdentity("request-c")


def _candidate(
    request_id: RequestIdentity,
    program_id: ProgramIdentity,
    *,
    program_arrival: float,
    request_arrival: float,
    preempted: bool = False,
    followup: bool = False,
    protected: bool = False,
    native_priority: int | None = None,
    deadline: float | None = None,
) -> SchedulingCandidate:
    return SchedulingCandidate(
        program_id=program_id,
        request_id=request_id,
        program_arrival_timestamp=program_arrival,
        request_arrival_timestamp=request_arrival,
        snapshot_timestamp=max(program_arrival, request_arrival),
        turn_index=0,
        is_preempted_waiting=preempted,
        is_followup=followup,
        program_is_protected=protected,
        native_priority=native_priority,
        retention_deadline_timestamp=deadline,
    )


def _order(candidates: tuple[SchedulingCandidate, ...]) -> tuple[RequestIdentity, ...]:
    from kvopt.continuum.scheduler import ContinuumSchedulingPolicy

    return tuple(ContinuumSchedulingPolicy().order(candidates))


def test_scheduler_priority_classes_put_preempted_then_protected_followup() -> None:
    ordinary = _candidate(
        REQUEST_A,
        PROGRAM_A,
        program_arrival=1.0,
        request_arrival=2.0,
    )
    protected_followup = _candidate(
        REQUEST_B,
        PROGRAM_A,
        program_arrival=1.0,
        request_arrival=60.0,
        followup=True,
        protected=True,
    )
    preempted = _candidate(
        REQUEST_C,
        PROGRAM_B,
        program_arrival=100.0,
        request_arrival=101.0,
        preempted=True,
    )

    assert _order((ordinary, protected_followup, preempted)) == (
        REQUEST_C,
        REQUEST_B,
        REQUEST_A,
    )


def test_scheduler_tie_break_ignores_native_priority_and_deadline() -> None:
    earliest_program = _candidate(
        REQUEST_C,
        PROGRAM_B,
        program_arrival=0.0,
        request_arrival=1.0,
        native_priority=100,
        deadline=100.0,
    )
    earliest_request = _candidate(
        REQUEST_B,
        PROGRAM_A,
        program_arrival=1.0,
        request_arrival=4.0,
        native_priority=0,
        deadline=0.0,
    )
    lexical_later = _candidate(
        RequestIdentity("request-z"),
        PROGRAM_A,
        program_arrival=1.0,
        request_arrival=5.0,
        native_priority=0,
        deadline=0.0,
    )
    lexical_earlier = _candidate(
        RequestIdentity("request-a"),
        PROGRAM_A,
        program_arrival=1.0,
        request_arrival=5.0,
        native_priority=100,
        deadline=100.0,
    )

    assert _order((lexical_later, earliest_program, lexical_earlier, earliest_request)) == (
        REQUEST_C,
        REQUEST_B,
        RequestIdentity("request-a"),
        RequestIdentity("request-z"),
    )


class _Provider:
    def estimate(self, _token_count: int) -> tuple[float, InputProvenance]:
        return 0.25, InputProvenance(InputSource.APPROXIMATED, "test profile")


def _runtime(*, default_ttl_seconds: float = 7.0):
    clock = FakeClock()
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=_Provider(),
        default_ttl_seconds=default_ttl_seconds,
    )
    return runtime, clock


def _finish_first_turn(runtime: Any, clock: FakeClock, *, timestamp: float = 1.0) -> None:
    clock.set(0.0)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_A, 0.0))
    runtime.handle(RequestAdmitted(PROGRAM_A, REQUEST_A, 0.0))
    runtime.record_prefill_context_token_count(
        PrefillContextTokenCountRecord(
            PROGRAM_A,
            REQUEST_A,
            PrefixIdentity("prefix-a"),
            128,
            InputProvenance(InputSource.OBSERVED),
        )
    )
    clock.set(timestamp)
    runtime.handle(
        BlocksObserved(
            PROGRAM_A,
            REQUEST_A,
            PrefixIdentity("prefix-a"),
            (BlockIdentity(7),),
            timestamp,
        )
    )
    runtime.handle(TurnFinished(PROGRAM_A, REQUEST_A, timestamp, False, "search"))


def test_runtime_scheduler_facts_use_request_arrival_and_program_first_arrival() -> None:
    runtime, clock = _runtime()
    clock.set(1.0)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_A, 1.0))
    clock.set(5.0)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_B, 5.0))

    candidates = runtime.scheduler_candidates((REQUEST_B,))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.program_arrival_timestamp == 1.0
    assert candidate.request_arrival_timestamp == 5.0
    assert candidate.is_followup is True
    assert candidate.snapshot_timestamp == 5.0


def test_scheduler_snapshot_expires_retention_before_reading_protection() -> None:
    runtime, clock = _runtime(default_ttl_seconds=1.0)
    _finish_first_turn(runtime, clock)

    clock.set(3.0)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_B, 3.0))
    candidate = runtime.scheduler_candidates((REQUEST_B,))[0]

    assert candidate.program_is_protected is False


class _RequestStatus(Enum):
    WAITING = "WAITING"
    PREEMPTED = "PREEMPTED"


@dataclass
class _Request:
    request_id: str
    arrival_time: float = 9_999.0
    priority: int = 0
    status: _RequestStatus = _RequestStatus.WAITING


class _FCFSQueue(deque[_Request]):
    def __init__(self, requests: list[_Request]) -> None:
        super().__init__(requests)

    def add_request(self, request: _Request) -> None:
        self.append(request)

    def pop_request(self) -> _Request:
        return self.popleft()

    def peek_request(self) -> _Request | None:
        return self[0] if self else None


class _Scheduler:
    _kvopt_scheduler_installed = False

    def __init__(self, requests: list[_Request]) -> None:
        self.waiting = _FCFSQueue(requests)
        self.skipped_waiting = _FCFSQueue([])
        self.running: list[_Request] = []
        self.schedule_calls = 0
        self.scheduled: _Request | None = None
        self.queue_seen_by_native_schedule: tuple[_Request, ...] | None = None

    def schedule(self) -> _Request | None:
        self.schedule_calls += 1
        self.queue_seen_by_native_schedule = tuple(self.waiting)
        if len(self.waiting) == 0:
            return None
        self.scheduled = self.waiting.pop_request()
        return self.scheduled


class _SchedulerRuntime:
    def __init__(self, candidates: tuple[SchedulingCandidate, ...]) -> None:
        self._candidates = {candidate.request_id: candidate for candidate in candidates}

    def scheduler_candidates(
        self,
        request_ids: tuple[RequestIdentity, ...],
    ) -> tuple[SchedulingCandidate, ...]:
        assert all(isinstance(request_id, RequestIdentity) for request_id in request_ids)
        return tuple(self._candidates[request_id] for request_id in request_ids)


class _FixedPolicy:
    def __init__(self, ordered_ids: tuple[RequestIdentity, ...]) -> None:
        self.ordered_ids = ordered_ids
        self.calls: list[tuple[SchedulingCandidate, ...]] = []

    def order(
        self, candidates: tuple[SchedulingCandidate, ...]
    ) -> tuple[RequestIdentity, ...]:
        self.calls.append(tuple(candidates))
        return self.ordered_ids


@pytest.fixture
def fake_scheduler_vllm(monkeypatch: pytest.MonkeyPatch):
    vllm = ModuleType("vllm")
    v1 = ModuleType("vllm.v1")
    request = ModuleType("vllm.v1.request")
    core = ModuleType("vllm.v1.core")
    sched = ModuleType("vllm.v1.core.sched")
    scheduler = ModuleType("vllm.v1.core.sched.scheduler")
    request.RequestStatus = _RequestStatus
    scheduler.Scheduler = _Scheduler
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.v1", v1)
    monkeypatch.setitem(sys.modules, "vllm.v1.request", request)
    monkeypatch.setitem(sys.modules, "vllm.v1.core", core)
    monkeypatch.setitem(sys.modules, "vllm.v1.core.sched", sched)
    monkeypatch.setitem(sys.modules, "vllm.v1.core.sched.scheduler", scheduler)
    original_schedule = _Scheduler.schedule
    _Scheduler._kvopt_scheduler_installed = False
    yield
    _Scheduler.schedule = original_schedule
    _Scheduler._kvopt_scheduler_installed = False


def _install_scheduler_hook(*, mode: SchedulerMode, runtime: Any, policy: Any) -> None:
    from kvopt.runtime.vllm.observer import install_scheduler_hook

    install_scheduler_hook(mode=mode, runtime=runtime, policy=policy)


def _scheduler_candidates() -> tuple[SchedulingCandidate, ...]:
    return (
        _candidate(
            REQUEST_A,
            PROGRAM_A,
            program_arrival=1.0,
            request_arrival=1.0,
        ),
        _candidate(
            REQUEST_B,
            PROGRAM_A,
            program_arrival=1.0,
            request_arrival=2.0,
            followup=True,
            protected=True,
        ),
        _candidate(
            REQUEST_C,
            PROGRAM_B,
            program_arrival=2.0,
            request_arrival=2.0,
            preempted=False,
        ),
    )


def test_scheduler_shadow_preserves_native_queue_and_calls_schedule_once(
    fake_scheduler_vllm,
) -> None:
    requests = [
        _Request(REQUEST_A.value),
        _Request(REQUEST_B.value),
        _Request(REQUEST_C.value, status=_RequestStatus.PREEMPTED),
    ]
    scheduler = _Scheduler(requests)
    policy = _FixedPolicy((REQUEST_C, REQUEST_B, REQUEST_A))
    runtime = _SchedulerRuntime(_scheduler_candidates())

    _install_scheduler_hook(
        mode=SchedulerMode.SHADOW,
        runtime=runtime,
        policy=policy,
    )
    result = scheduler.schedule()

    assert result is requests[0]
    assert scheduler.schedule_calls == 1
    assert scheduler.queue_seen_by_native_schedule is not None
    assert all(
        actual is expected
        for actual, expected in zip(
            scheduler.queue_seen_by_native_schedule, requests, strict=True
        )
    )
    assert list(scheduler.waiting) == requests[1:]
    assert policy.calls
    preempted_candidate = next(
        candidate for candidate in policy.calls[-1] if candidate.request_id == REQUEST_C
    )
    assert preempted_candidate.is_preempted_waiting is True


def test_scheduler_controlled_reorders_exact_fcfs_request_objects(
    fake_scheduler_vllm,
) -> None:
    requests = [
        _Request(REQUEST_A.value),
        _Request(REQUEST_B.value),
        _Request(REQUEST_C.value, status=_RequestStatus.PREEMPTED),
    ]
    scheduler = _Scheduler(requests)
    policy = _FixedPolicy((REQUEST_C, REQUEST_B, REQUEST_A))
    runtime = _SchedulerRuntime(_scheduler_candidates())

    _install_scheduler_hook(
        mode=SchedulerMode.CONTROLLED,
        runtime=runtime,
        policy=policy,
    )
    result = scheduler.schedule()

    assert result is requests[2]
    assert result.request_id == REQUEST_C.value
    assert scheduler.schedule_calls == 1
    assert scheduler.queue_seen_by_native_schedule is not None
    assert all(
        actual is expected
        for actual, expected in zip(
            scheduler.queue_seen_by_native_schedule,
            (requests[2], requests[1], requests[0]),
            strict=True,
        )
    )
    assert list(scheduler.waiting) == [requests[1], requests[0]]
    assert requests[0].status is _RequestStatus.WAITING
    assert requests[1].status is _RequestStatus.WAITING
    assert requests[2].status is _RequestStatus.PREEMPTED
    assert all(request.priority == 0 for request in requests)
    assert policy.calls
    preempted_candidate = next(
        candidate for candidate in policy.calls[-1] if candidate.request_id == REQUEST_C
    )
    assert preempted_candidate.is_preempted_waiting is True
