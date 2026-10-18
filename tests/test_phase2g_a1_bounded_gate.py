from kvopt.profiling.phase2g_a1_bounded_gate import (
    _aggregate_scenarios,
    compare_pair,
)


def _arm(policy: str, *, selected: str, physical: str, tokens: int) -> dict[str, object]:
    return {
        "status": "VALID",
        "scenario_id": "f1-draw-01",
        "family": "F1",
        "policy": policy,
        "repeat": 1,
        "git_sha": "git",
        "trace_sha256": "trace",
        "request_ids": ["a:1", "a:2"],
        "materialized_token_digests": {"a:1": "one", "a:2": "two"},
        "pairing_config": {"cache": 37},
        "selection_sequence": [[selected]],
        "pressure_release_mechanism_realized": True,
        "physical_eviction_count": 1,
        "physical_eviction_signature": [(physical, 0)],
        "aggregate_recomputed_tokens": tokens,
    }


def _outcome(*, recomputed: int, new_suffix: int, cached: int) -> dict[str, object]:
    """One eligible request's frozen token facts."""
    return {
        "recomputed_tokens": recomputed,
        "new_suffix_tokens": new_suffix,
        "actual_prefill_tokens": recomputed + new_suffix,
        "cached_prefix_tokens": cached,
    }


def _arm_with_metric(
    policy: str,
    *,
    selected: str,
    physical: str,
    outcome: dict[str, object],
) -> dict[str, object]:
    arm = _arm(policy, selected=selected, physical=physical, tokens=0)
    recoverable = int(outcome["recomputed_tokens"])
    suffix = int(outcome["new_suffix_tokens"])
    arm["request_outcomes"] = {"a:2": outcome}
    arm["aggregate_recomputed_tokens"] = recoverable
    arm["aggregate_actual_prefill_tokens"] = recoverable + suffix
    arm["aggregate_new_suffix_tokens"] = suffix
    return arm


def test_pair_metric_equivalence_is_exact_when_new_suffix_matches() -> None:
    """Same (N, E), different occupancy: the two candidate metrics must agree."""
    a0 = _arm_with_metric(
        "A0",
        selected="a",
        physical="a",
        outcome=_outcome(recomputed=48, new_suffix=36, cached=16),
    )
    a1 = _arm_with_metric(
        "A1",
        selected="b",
        physical="b",
        outcome=_outcome(recomputed=16, new_suffix=36, cached=48),
    )

    result = compare_pair(a0, a1)

    assert result["metric_equivalence"] == "EXACT"
    assert result["request_completeness"] == "COMPLETE"
    assert result["new_suffix_identical_across_arms"] is True
    assert result["token_delta_a1_minus_a0"] == -32
    assert result["delta_actual_prefill_a1_minus_a0"] == -32
    assert result["delta_new_suffix_a1_minus_a0"] == 0
    assert result["delta_difference_actual_prefill_minus_recomputed"] == 0


def test_pair_reports_non_equivalence_instead_of_choosing_a_metric() -> None:
    a0 = _arm_with_metric(
        "A0",
        selected="a",
        physical="a",
        outcome=_outcome(recomputed=0, new_suffix=100, cached=100),
    )
    a1 = _arm_with_metric(
        "A1",
        selected="b",
        physical="b",
        outcome=_outcome(recomputed=40, new_suffix=20, cached=140),
    )

    result = compare_pair(a0, a1)

    assert result["metric_equivalence"] == "NOT_EQUIVALENT"
    assert result["new_suffix_identical_across_arms"] is False
    assert result["new_suffix_differing_request_ids"] == ["a:2"]
    # Prefill improves while recomputation regresses; both are reported.
    assert result["delta_actual_prefill_a1_minus_a0"] == -40
    assert result["token_delta_a1_minus_a0"] == 40
    assert result["delta_difference_actual_prefill_minus_recomputed"] == -80


def test_pair_marks_unpaired_eligible_population_not_computable() -> None:
    a0 = _arm_with_metric(
        "A0",
        selected="a",
        physical="a",
        outcome=_outcome(recomputed=48, new_suffix=36, cached=16),
    )
    a1 = _arm_with_metric(
        "A1",
        selected="b",
        physical="b",
        outcome=_outcome(recomputed=16, new_suffix=36, cached=48),
    )
    a1["request_outcomes"] = {"a:9": _outcome(recomputed=16, new_suffix=36, cached=48)}

    result = compare_pair(a0, a1)

    assert result["request_completeness"] == "UNPAIRED"
    assert result["metric_equivalence"] == "NOT_COMPUTABLE"
    assert result["unpaired_request_ids"] == ["a:2", "a:9"]


def test_pair_reports_native_benefit_only_after_both_divergences() -> None:
    result = compare_pair(
        _arm("A0", selected="a", physical="a", tokens=200),
        _arm("A1", selected="b", physical="b", tokens=120),
    )

    assert result["evidence_state"] == "NATIVE_BENEFIT_OBSERVED"
    assert result["token_delta_a1_minus_a0"] == -80


def test_pair_preserves_no_selection_divergence() -> None:
    result = compare_pair(
        _arm("A0", selected="a", physical="a", tokens=200),
        _arm("A1", selected="a", physical="a", tokens=200),
    )

    assert result["evidence_state"] == "NO_SELECTION_DIVERGENCE"


def test_pair_preserves_not_realized_without_forced_release() -> None:
    a0 = _arm("A0", selected="a", physical="a", tokens=200)
    a1 = _arm("A1", selected="a", physical="a", tokens=200)
    a0["pressure_release_mechanism_realized"] = False
    a1["pressure_release_mechanism_realized"] = False
    a0["selection_sequence"] = []
    a1["selection_sequence"] = []
    a0["physical_eviction_count"] = 0
    a1["physical_eviction_count"] = 0

    result = compare_pair(a0, a1)

    assert result["status"] == "COMPARABLE"
    assert result["evidence_state"] == "NOT_REALIZED"


def test_pair_fails_closed_on_unpaired_content() -> None:
    a0 = _arm("A0", selected="a", physical="a", tokens=200)
    a1 = _arm("A1", selected="b", physical="b", tokens=120)
    a1["materialized_token_digests"] = {"a:1": "different"}

    result = compare_pair(a0, a1)

    assert result["status"] == "NOT_COMPARABLE"
    assert result["evidence_state"] == "INCONCLUSIVE"


def test_runtime_repeats_are_aggregated_within_scenario() -> None:
    rows = []
    for repeat, delta in ((1, -80), (2, -40)):
        rows.append(
            {
                "scenario_id": "f1-draw-01",
                "family": "F1",
                "repeat": repeat,
                "status": "COMPARABLE",
                "evidence_state": "NATIVE_BENEFIT_OBSERVED",
                "selection_diverged": True,
                "physical_diverged": True,
                "token_delta_a1_minus_a0": delta,
            }
        )

    result = _aggregate_scenarios(rows)

    assert len(result) == 1
    assert result[0]["mean_token_delta_a1_minus_a0"] == -60
    assert result[0]["direction"] == "BETTER"
