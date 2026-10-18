"""Tests for the Phase 2G Gate 2 frozen token-metric semantics.

The point of these tests is that the *relationship* between the two candidate
metrics is established arithmetically, not assumed. Gate 2 previously reported
``N - C`` under the name ``recomputed_tokens``; the frozen recomputation metric is
``E - C``. These tests pin down exactly when the mistake does and does not change
a paired conclusion.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from kvopt.profiling.phase2g_a1_metric import (
    RequestTokenFacts,
    pair_verdict,
    request_token_facts,
    totals,
)


def _facts(
    request_id: str,
    *,
    prompt: int,
    eligible: int,
    cached: int,
    program_id: str = "a",
) -> RequestTokenFacts:
    return RequestTokenFacts(
        request_id=request_id,
        program_id=program_id,
        prompt_tokens=prompt,
        eligible_prefix_tokens=eligible,
        cached_prefix_tokens=cached,
        actual_prefill_tokens=prompt - cached,
        recomputed_tokens=eligible - cached,
        new_suffix_tokens=prompt - eligible,
    )


def test_identity_holds_per_request() -> None:
    row = _facts("r", prompt=100, eligible=64, cached=32)
    assert row.actual_prefill_tokens == row.recomputed_tokens + row.new_suffix_tokens
    assert (row.actual_prefill_tokens, row.recomputed_tokens, row.new_suffix_tokens) == (68, 32, 36)


def test_totals_sum_only_the_named_population() -> None:
    facts = {
        "a": _facts("a", prompt=100, eligible=64, cached=32),
        "b": _facts("b", prompt=50, eligible=0, cached=0),
    }
    assert totals(facts, ["a"]).recomputed_tokens == 32
    assert totals(facts, ["a", "b"]).recomputed_tokens == 32
    assert totals(facts, ["a", "b"]).actual_prefill_tokens == 68 + 50


def test_deltas_coincide_when_eligible_prefix_is_arm_invariant() -> None:
    """The realistic case: same request, same (N, E), different occupancy C."""
    a0 = {"r": _facts("r", prompt=100, eligible=64, cached=16)}
    a1 = {"r": _facts("r", prompt=100, eligible=64, cached=48)}

    verdict = pair_verdict(a0, a1, ["r"])

    assert verdict.equivalence == "EXACT"
    assert verdict.deltas_coincide
    # A1 cached more, so both metrics improve by the same amount.
    assert verdict.delta_recomputed_tokens == -32
    assert verdict.delta_actual_prefill_tokens == -32
    assert verdict.delta_new_suffix_tokens == 0


def test_deltas_diverge_when_eligible_prefix_is_arm_dependent() -> None:
    """If E itself moves, the two metrics answer different questions."""
    a0 = {"r": _facts("r", prompt=100, eligible=64, cached=16)}
    a1 = {"r": _facts("r", prompt=100, eligible=32, cached=16)}

    verdict = pair_verdict(a0, a1, ["r"])

    assert verdict.equivalence == "NOT_EQUIVALENT"
    assert not verdict.deltas_coincide
    # Actual prefill is unchanged because C is unchanged ...
    assert verdict.delta_actual_prefill_tokens == 0
    # ... while the frozen recomputation metric drops by the lost eligibility.
    assert verdict.delta_recomputed_tokens == -32
    assert verdict.delta_new_suffix_tokens == 32


def test_unpaired_population_is_not_computable() -> None:
    a0 = {"r": _facts("r", prompt=100, eligible=64, cached=16)}
    a1 = {"s": _facts("s", prompt=100, eligible=64, cached=16)}

    verdict = pair_verdict(a0, a1, ["r", "s"])

    assert verdict.equivalence == "NOT_COMPUTABLE"
    assert verdict.unpaired_request_ids == ("r", "s")


def test_identity_is_asserted_even_when_metrics_diverge() -> None:
    """The arithmetic check must hold in both branches, not only the convenient one."""
    a0 = {"r": _facts("r", prompt=100, eligible=64, cached=16)}
    a1 = {"r": _facts("r", prompt=100, eligible=32, cached=16)}
    # No exception means ΔW == ΔR + ΔS held.
    verdict = pair_verdict(a0, a1, ["r"])
    assert (
        verdict.delta_actual_prefill_tokens
        == verdict.delta_recomputed_tokens + verdict.delta_new_suffix_tokens
    )


def test_old_and_new_metric_disagree_in_sign_when_eligibility_grows() -> None:
    """A case where reporting only N - C would invert the conclusion.

    ``ΔW = -ΔC`` while ``ΔR = ΔE - ΔC``, so when eligibility grows by more than the
    cache does, prefill improves while recomputation worsens. A report that only
    carried ``N - C`` would have called this a win.
    """
    a0 = {"r": _facts("r", prompt=200, eligible=100, cached=100)}
    a1 = {"r": _facts("r", prompt=200, eligible=180, cached=140)}

    verdict = pair_verdict(a0, a1, ["r"])

    assert verdict.delta_actual_prefill_tokens == -40, "prefill looks better"
    assert verdict.delta_recomputed_tokens == 40, "but recomputation got worse"
    assert verdict.delta_new_suffix_tokens == -80
    assert verdict.equivalence == "NOT_EQUIVALENT"
    assert (
        verdict.delta_actual_prefill_tokens
        == verdict.delta_recomputed_tokens + verdict.delta_new_suffix_tokens
    )


def test_request_token_facts_rejects_runs_without_prefix_provenance() -> None:
    class _Empty:
        run_id = "empty"
        events: ClassVar[list[dict[str, object]]] = []
        replay: ClassVar[list[dict[str, object]]] = []

    # No replay rows at all: the frozen table is empty, so nothing is invented.
    assert request_token_facts([_Empty()]) == {}


def test_missing_metric_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request without a derivable E - C must abort, not be silently dropped."""

    class _Row:
        request_id = "r"
        program_id = "a"
        observed_recomputed_tokens = None
        availability = "UNAVAILABLE"
        unavailable_reason = "no_compatible_prior_native_hash_provenance"
        native_prompt_tokens = 100
        eligible_prefix_tokens = None
        native_cached_prefix_tokens = 0
        actual_prefill_tokens = None

    monkeypatch.setattr(
        "kvopt.profiling.phase2g_a1_metric.build_request_runtime_evidence_table",
        lambda _runs: (_Row(),),
    )
    with pytest.raises(ValueError, match="no frozen recomputation metric"):
        request_token_facts([object()])
