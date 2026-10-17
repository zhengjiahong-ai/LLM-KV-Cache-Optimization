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
