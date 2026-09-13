from __future__ import annotations

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
    RequestIdentity,
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


PROGRAM = ProgramIdentity("program-a")
OTHER_PROGRAM = ProgramIdentity("program-b")
REQUEST = RequestIdentity("request-a")
OTHER_REQUEST = RequestIdentity("request-b")
PREFIX = PrefixIdentity("adapter-prefix-a")
OTHER_PREFIX = PrefixIdentity("adapter-prefix-b")


def _fact(
    *,
    program_id: ProgramIdentity = PROGRAM,
    request_id: RequestIdentity = REQUEST,
    prefix_id: PrefixIdentity = PREFIX,
    token_count: int = 128,
) -> PrefillContextTokenCountRecord:
    return PrefillContextTokenCountRecord(
        program_id=program_id,
        request_id=request_id,
        prefix_id=prefix_id,
        token_count=token_count,
        provenance=InputProvenance(InputSource.OBSERVED),
    )


def _runtime() -> tuple[object, FakeClock, _InjectedPrefillReload]:
    clock = FakeClock()
    provider = _InjectedPrefillReload()
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=provider,
        default_ttl_seconds=7.0,
        duration_history_threshold=100,
    )
    return runtime, clock, provider


def _finish_nonterminal(runtime: object, clock: FakeClock) -> None:
    clock.set(1.0)
    runtime.handle(  # type: ignore[attr-defined]
        BlocksObserved(
            PROGRAM,
            REQUEST,
            PREFIX,
            (BlockIdentity(7),),
            1.0,
        )
    )
    runtime.handle(  # type: ignore[attr-defined]
        TurnFinished(
            PROGRAM,
            REQUEST,
            1.0,
            False,
            next_tool_type="search",
        )
    )


def test_build_runtime_requires_explicit_prefill_reload_provider() -> None:
    with pytest.raises(TypeError, match="prefill_reload_provider"):
        build_runtime(clock=FakeClock(), default_ttl_seconds=7.0)


def test_matching_prefill_fact_reaches_provider_exactly_once_and_creates_retention() -> None:
    runtime, clock, provider = _runtime()
    runtime.record_prefill_context_token_count(_fact())  # type: ignore[attr-defined]

    _finish_nonterminal(runtime, clock)

    assert provider.calls == [128]
    entry = runtime.retention.snapshot(  # type: ignore[attr-defined]
        RetentionEntryKey(PROGRAM, PREFIX)
    )
    assert entry is not None
    assert entry.protected is True
    assert entry.deadline_timestamp == 8.0
    assert (
        entry.ttl_decision.ttl_input.eta_provenance.reason
        == "FULLY_MEMORYFUL_COLD_START"
    )


@pytest.mark.parametrize(
    "fact_kwargs",
    [
        {"program_id": OTHER_PROGRAM},
        {"request_id": OTHER_REQUEST},
        {"prefix_id": OTHER_PREFIX},
    ],
)
def test_mismatched_prefill_fact_fails_closed_without_provider_or_retention_mutation(
    fact_kwargs: dict[str, object],
) -> None:
    runtime, clock, provider = _runtime()
    runtime.record_prefill_context_token_count(  # type: ignore[attr-defined]
        _fact(**fact_kwargs),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError):
        _finish_nonterminal(runtime, clock)

    assert provider.calls == []
    assert runtime.retention.planning_snapshots() == ()  # type: ignore[attr-defined]


def test_missing_prefill_fact_fails_closed_without_provider_or_retention_mutation() -> None:
    runtime, clock, provider = _runtime()

    with pytest.raises(ValueError):
        _finish_nonterminal(runtime, clock)

    assert provider.calls == []
    assert runtime.retention.planning_snapshots() == ()  # type: ignore[attr-defined]
