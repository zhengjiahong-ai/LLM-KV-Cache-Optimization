from __future__ import annotations

import pytest

from kvopt.continuum import (
    BlockEvicted,
    BlockIdentity,
    BlocksObserved,
    EvictedRequestQueueDelayRecord,
    FakeClock,
    FollowupCancelled,
    FollowupWaiting,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.continuum.selection import RetentionEntryKey


class _InjectedPrefillReload:
    def __init__(self, seconds: float = 0.25) -> None:
        self.seconds = seconds
        self.calls: list[int] = []

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        self.calls.append(token_count)
        return self.seconds, InputProvenance(
            InputSource.APPROXIMATED,
            "TEST_PROFILE",
        )


PROGRAM_A = ProgramIdentity("program-a")
PROGRAM_B = ProgramIdentity("program-b")
PREFIX_A = PrefixIdentity("adapter-prefix-a")
PREFIX_B = PrefixIdentity("adapter-prefix-b")
PREFIX_C = PrefixIdentity("adapter-prefix-c")
REQUEST_1 = RequestIdentity("request-1")
REQUEST_2 = RequestIdentity("request-2")
REQUEST_3 = RequestIdentity("request-3")
REQUEST_4 = RequestIdentity("request-4")


def _runtime(
    *,
    default_ttl_seconds: float = 7.0,
) -> tuple[object, FakeClock, _InjectedPrefillReload]:
    clock = FakeClock()
    provider = _InjectedPrefillReload()
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=provider,
        default_ttl_seconds=default_ttl_seconds,
        duration_history_threshold=100,
    )
    return runtime, clock, provider


def _arrive_and_admit(
    runtime: object,
    clock: FakeClock,
    program_id: ProgramIdentity,
    request_id: RequestIdentity,
    timestamp: float,
) -> None:
    clock.set(timestamp)
    runtime.handle(RequestArrived(program_id, request_id, timestamp))  # type: ignore[attr-defined]
    runtime.handle(RequestAdmitted(program_id, request_id, timestamp))  # type: ignore[attr-defined]


def _record_prefill_fact(
    runtime: object,
    program_id: ProgramIdentity,
    request_id: RequestIdentity,
    prefix_id: PrefixIdentity,
    token_count: int = 128,
) -> None:
    runtime.record_prefill_context_token_count(  # type: ignore[attr-defined]
        PrefillContextTokenCountRecord(
            program_id=program_id,
            request_id=request_id,
            prefix_id=prefix_id,
            token_count=token_count,
            provenance=InputProvenance(InputSource.OBSERVED),
        )
    )


def _observe_and_finish(
    runtime: object,
    clock: FakeClock,
    program_id: ProgramIdentity,
    request_id: RequestIdentity,
    prefix_id: PrefixIdentity,
    block_id: int,
    timestamp: float,
    *,
    terminal: bool = False,
) -> None:
    clock.set(timestamp)
    runtime.handle(  # type: ignore[attr-defined]
        BlocksObserved(
            program_id,
            request_id,
            prefix_id,
            (BlockIdentity(block_id),),
            timestamp,
        )
    )
    runtime.handle(  # type: ignore[attr-defined]
        TurnFinished(
            program_id,
            request_id,
            timestamp,
            terminal,
            next_tool_type=None if terminal else "search",
        )
    )


def _run_nonterminal_turn(
    runtime: object,
    clock: FakeClock,
    program_id: ProgramIdentity,
    request_id: RequestIdentity,
    prefix_id: PrefixIdentity,
    block_id: int,
    timestamp: float,
) -> None:
    _arrive_and_admit(runtime, clock, program_id, request_id, timestamp - 1.0)
    _record_prefill_fact(runtime, program_id, request_id, prefix_id)
    _observe_and_finish(
        runtime,
        clock,
        program_id,
        request_id,
        prefix_id,
        block_id,
        timestamp,
    )


def test_request_arrival_records_server_gap_without_ending_retention() -> None:
    runtime, clock, _provider = _runtime()
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 1.0)

    clock.set(3.5)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_2, 3.5))  # type: ignore[attr-defined]

    assert runtime.server_gap_history.global_samples() == (2.5,)  # type: ignore[attr-defined]
    entry = runtime.retention.snapshot(  # type: ignore[attr-defined]
        RetentionEntryKey(PROGRAM_A, PREFIX_A)
    )
    assert entry is not None
    assert entry.protected is True


def test_request_admitted_ends_prior_idle_retention_interval() -> None:
    runtime, clock, _provider = _runtime()
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 1.0)

    _arrive_and_admit(runtime, clock, PROGRAM_A, REQUEST_2, 3.5)

    entry = runtime.retention.snapshot(  # type: ignore[attr-defined]
        RetentionEntryKey(PROGRAM_A, PREFIX_A)
    )
    assert entry is not None
    assert entry.protected is False
    assert entry.waiting_followup is False


def test_waiting_and_cancelled_followups_are_program_scoped() -> None:
    runtime, clock, _provider = _runtime(default_ttl_seconds=1.0)
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 1.0)
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_2, PREFIX_B, 8, 3.0)
    _arrive_and_admit(runtime, clock, PROGRAM_B, REQUEST_4, 3.1)
    _record_prefill_fact(runtime, PROGRAM_B, REQUEST_4, PREFIX_C)
    _observe_and_finish(
        runtime,
        clock,
        PROGRAM_B,
        REQUEST_4,
        PREFIX_C,
        9,
        3.5,
    )

    clock.set(3.6)
    runtime.handle(FollowupWaiting(PROGRAM_A, REQUEST_3, 3.6))  # type: ignore[attr-defined]

    key_a = RetentionEntryKey(PROGRAM_A, PREFIX_A)
    key_b = RetentionEntryKey(PROGRAM_A, PREFIX_B)
    key_c = RetentionEntryKey(PROGRAM_B, PREFIX_C)
    assert runtime.retention.snapshot(key_a).waiting_followup is True  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_b).waiting_followup is True  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_c).waiting_followup is False  # type: ignore[attr-defined]

    clock.set(4.0)
    runtime.handle(FollowupCancelled(PROGRAM_A, REQUEST_3, 4.0))  # type: ignore[attr-defined]

    assert runtime.retention.snapshot(key_a).waiting_followup is False  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_b).waiting_followup is False  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_c).waiting_followup is False  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_a).protected is False  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_b).protected is False  # type: ignore[attr-defined]
    assert runtime.retention.snapshot(key_c).protected is True  # type: ignore[attr-defined]


def test_external_tool_duration_stays_out_of_server_gap_history() -> None:
    runtime, clock, _provider = _runtime()
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 3.0)

    clock.set(3.0)
    runtime.handle(ToolGapStarted(PROGRAM_A, "search", 3.0))  # type: ignore[attr-defined]
    clock.set(5.0)
    runtime.handle(ToolGapEnded(PROGRAM_A, "search", 5.0))  # type: ignore[attr-defined]

    clock.set(8.0)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_2, 8.0))  # type: ignore[attr-defined]

    assert runtime.external_tool_duration_history.global_samples() == (2.0,)  # type: ignore[attr-defined]
    assert runtime.server_gap_history.global_samples() == (5.0,)  # type: ignore[attr-defined]


def test_queue_delay_history_requires_explicit_typed_kv_loss_fact() -> None:
    runtime, _clock, _provider = _runtime()

    with pytest.raises(TypeError):
        runtime.record_queue_delay(2.0)  # type: ignore[attr-defined]

    runtime.record_queue_delay(  # type: ignore[attr-defined]
        EvictedRequestQueueDelayRecord(PROGRAM_A, REQUEST_1, 1.0, 3.0)
    )
    assert runtime.queue_delay_history.samples() == (2.0,)  # type: ignore[attr-defined]


def test_terminal_turn_cleans_program_state_records_eta_and_skips_provider() -> None:
    runtime, clock, provider = _runtime()
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 1.0)
    calls_before = tuple(provider.calls)

    _arrive_and_admit(runtime, clock, PROGRAM_A, REQUEST_2, 2.0)
    _observe_and_finish(
        runtime,
        clock,
        PROGRAM_A,
        REQUEST_2,
        PREFIX_B,
        8,
        3.0,
        terminal=True,
    )

    assert tuple(provider.calls) == calls_before
    assert runtime.retention.planning_snapshots() == ()  # type: ignore[attr-defined]
    assert runtime.eta_history.samples() == ((1, 1),)  # type: ignore[attr-defined]


def test_observed_blocks_create_association_and_eviction_clears_only_edge() -> None:
    runtime, clock, _provider = _runtime()
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 1.0)
    key = RetentionEntryKey(PROGRAM_A, PREFIX_A)

    assert runtime.retention.entries_for_block(BlockIdentity(7)) == (key,)  # type: ignore[attr-defined]

    clock.set(2.0)
    runtime.handle(BlockEvicted(BlockIdentity(7), 2.0))  # type: ignore[attr-defined]

    entry = runtime.retention.snapshot(key)  # type: ignore[attr-defined]
    assert entry is not None
    assert entry.protected is True
    assert entry.block_ids == ()
    assert runtime.retention.entries_for_block(BlockIdentity(7)) == ()  # type: ignore[attr-defined]


def test_nonterminal_ttl_input_consumes_runtime_histories() -> None:
    runtime, clock, _provider = _runtime()
    _run_nonterminal_turn(runtime, clock, PROGRAM_A, REQUEST_1, PREFIX_A, 7, 1.0)

    clock.set(3.5)
    runtime.handle(RequestArrived(PROGRAM_A, REQUEST_2, 3.5))  # type: ignore[attr-defined]
    runtime.record_queue_delay(  # type: ignore[attr-defined]
        EvictedRequestQueueDelayRecord(PROGRAM_A, REQUEST_2, 3.5, 5.5)
    )
    runtime.eta_history.record_completed_program(  # type: ignore[attr-defined]
        ProgramIdentity("seed-program-a"), 2
    )
    runtime.eta_history.record_completed_program(  # type: ignore[attr-defined]
        ProgramIdentity("seed-program-b"), 3
    )
    expected_eta, expected_eta_provenance = runtime.eta_history.eta()  # type: ignore[attr-defined]

    clock.set(5.5)
    runtime.handle(RequestAdmitted(PROGRAM_A, REQUEST_2, 5.5))  # type: ignore[attr-defined]
    _record_prefill_fact(runtime, PROGRAM_A, REQUEST_2, PREFIX_B)
    _observe_and_finish(
        runtime,
        clock,
        PROGRAM_A,
        REQUEST_2,
        PREFIX_B,
        8,
        6.0,
    )

    entry = runtime.retention.snapshot(  # type: ignore[attr-defined]
        RetentionEntryKey(PROGRAM_A, PREFIX_B)
    )
    assert entry is not None
    ttl_input = entry.ttl_decision.ttl_input
    assert ttl_input.global_server_gap_samples_seconds == (2.5,)
    assert ttl_input.tool_server_gap_samples_seconds == (2.5,)
    assert ttl_input.queue_delay_t_seconds == 2.0
    assert ttl_input.eta == pytest.approx(expected_eta)
    assert ttl_input.eta_provenance == expected_eta_provenance
