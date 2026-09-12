import math

import pytest

from kvopt.continuum.snapshots import TTLHistoryMode, TTLInput
from kvopt.continuum.ttl import (
    PrefillReloadProvider,
    compute_default_ttl_seconds,
    estimate_ttl,
)
from kvopt.continuum.types import (
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)

PROGRAM_ID = ProgramIdentity("program-1")
REQUEST_ID = RequestIdentity("request-1")
PREFIX_ID = PrefixIdentity("prefix-1")
OBSERVED = InputProvenance(InputSource.OBSERVED)
APPROXIMATED = InputProvenance(InputSource.APPROXIMATED, "offline profile")


def _ttl_input(**overrides: object) -> TTLInput:
    values: dict[str, object] = {
        "program_id": PROGRAM_ID,
        "request_id": REQUEST_ID,
        "prefix_id": PREFIX_ID,
        "decision_timestamp": 10.0,
        "next_tool_type": "search",
        "global_server_gap_samples_seconds": (1.0, 2.0),
        "tool_server_gap_samples_seconds": (1.5,),
        "queue_delay_t_seconds": 0.5,
        "eta": 1.0,
        "prefill_reload_seconds": 3.0,
        "default_ttl_seconds": 7.0,
        "server_gap_history_provenance": OBSERVED,
        "queue_delay_provenance": OBSERVED,
        "eta_provenance": OBSERVED,
        "prefill_reload_provenance": APPROXIMATED,
        "default_ttl_provenance": APPROXIMATED,
    }
    values.update(overrides)
    return TTLInput(**values)


def test_dynamic_ttl_implements_equation_two() -> None:
    decision = estimate_ttl(
        _ttl_input(
            global_server_gap_samples_seconds=(2.0,) * 101,
            tool_server_gap_samples_seconds=(),
            queue_delay_t_seconds=2.0,
            eta=1.0,
            prefill_reload_seconds=3.0,
            next_tool_type=None,
        ),
        duration_history_threshold=100,
    )

    # Benefit is 2 * 1 + 3 = 5; candidates are 0 and 2, so tau=2 wins.
    assert decision.ttl_seconds == 2.0
    assert decision.history_mode is TTLHistoryMode.GLOBAL


@pytest.mark.parametrize(
    ("global_count", "tool_count", "expected_mode"),
    [
        (100, 100, TTLHistoryMode.COLD_START),
        (101, 100, TTLHistoryMode.GLOBAL),
        (101, 101, TTLHistoryMode.TOOL_SPECIFIC),
    ],
)
def test_history_tier_uses_exact_threshold_boundaries(
    global_count: int, tool_count: int, expected_mode: TTLHistoryMode
) -> None:
    decision = estimate_ttl(
        _ttl_input(
            global_server_gap_samples_seconds=(1.0,) * global_count,
            tool_server_gap_samples_seconds=(1.0,) * tool_count,
        ),
        duration_history_threshold=100,
    )

    assert decision.history_mode is expected_mode
    if expected_mode is TTLHistoryMode.COLD_START:
        assert decision.ttl_seconds == 7.0


def test_empirical_cdf_is_inclusive_and_counts_duplicate_samples() -> None:
    decision = estimate_ttl(
        _ttl_input(
            global_server_gap_samples_seconds=(2.0,) * 150
            + (5.0,) * 51,
            tool_server_gap_samples_seconds=(),
            next_tool_type=None,
            queue_delay_t_seconds=0.0,
            eta=1.0,
            prefill_reload_seconds=8.0,
        ),
        duration_history_threshold=100,
    )

    # At tau=2 the inclusive CDF counts all 150 duplicate samples.
    assert decision.ttl_seconds == 2.0


def test_ttl_candidates_include_zero_and_unique_observed_durations() -> None:
    decision = estimate_ttl(
        _ttl_input(
            global_server_gap_samples_seconds=(4.0,) * 50
            + (2.0,) * 151,
            tool_server_gap_samples_seconds=(),
            next_tool_type=None,
            queue_delay_t_seconds=0.0,
            eta=1.0,
            prefill_reload_seconds=0.5,
        ),
        duration_history_threshold=100,
    )

    # The only candidates are 0, 2, and 4; zero is needed when all others score negative.
    assert decision.ttl_seconds == 0.0


def test_objective_tie_break_selects_smaller_ttl() -> None:
    decision = estimate_ttl(
        _ttl_input(
            global_server_gap_samples_seconds=(2.0,) * 150
            + (4.0,) * 50,
            tool_server_gap_samples_seconds=(),
            queue_delay_t_seconds=0.0,
            eta=1.0,
            prefill_reload_seconds=8.0,
            next_tool_type=None,
        ),
        duration_history_threshold=100,
    )

    # Both tau=2 and tau=4 score 4; the frozen tie-break chooses tau=2.
    assert decision.ttl_seconds == 2.0


@pytest.mark.parametrize(
    ("profile_seconds", "expected"),
    [(0.5, 0.0), (1.0, 0.0), (2.0, math.log(2.0))],
)
def test_default_ttl_uses_frozen_log_formula(
    profile_seconds: float, expected: float
) -> None:
    assert compute_default_ttl_seconds(profile_seconds) == pytest.approx(expected)


@pytest.mark.parametrize("profile_seconds", [0.0, -1.0, math.inf, math.nan])
def test_default_ttl_rejects_invalid_profile_values(profile_seconds: float) -> None:
    with pytest.raises(ValueError):
        compute_default_ttl_seconds(profile_seconds)


def test_missing_next_tool_type_uses_global_history_with_reason() -> None:
    decision = estimate_ttl(
        _ttl_input(
            next_tool_type=None,
            global_server_gap_samples_seconds=(2.0,) * 101,
            tool_server_gap_samples_seconds=(),
        ),
        duration_history_threshold=100,
    )

    assert decision.history_mode is TTLHistoryMode.GLOBAL
    assert decision.reason is not None
    assert "next_tool_type" in decision.reason


class FixedPrefillReloadProvider(PrefillReloadProvider):
    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        assert token_count > 0
        return 0.25, APPROXIMATED


def test_prefill_reload_provider_boundary_returns_seconds_and_provenance() -> None:
    seconds, provenance = FixedPrefillReloadProvider().estimate(128)

    assert seconds == 0.25
    assert provenance == APPROXIMATED


def test_estimator_preserves_negative_finite_eta_without_clipping() -> None:
    decision = estimate_ttl(
        _ttl_input(
            global_server_gap_samples_seconds=(2.0,) * 101,
            tool_server_gap_samples_seconds=(),
            next_tool_type=None,
            queue_delay_t_seconds=2.0,
            eta=-1.0,
            prefill_reload_seconds=3.0,
        ),
        duration_history_threshold=100,
    )

    assert decision.ttl_input.eta == -1.0
    assert decision.ttl_seconds == 0.0
