from kvopt.profiling.phase2e_campaign_gate import compare_pair


def _arm(baseline: str, digest: str = "abc") -> dict[str, object]:
    return {
        "status": "VALID",
        "scenario_id": "f1-draw-01",
        "baseline": baseline,
        "repeat": 1,
        "materialized_token_digests": {"request-1": digest},
        "request_evidence": [{"request_id": "request-1"}],
    }


def test_pair_requires_exact_actual_token_identity() -> None:
    result = compare_pair(_arm("native-lru"), _arm("continuum-baseline"))

    assert result["status"] == "COMPARABLE"


def test_pair_fails_closed_on_digest_difference() -> None:
    result = compare_pair(
        _arm("native-lru", "left"),
        _arm("continuum-baseline", "right"),
    )

    assert result["status"] == "NOT_COMPARABLE"
    assert result["checks"]["materialized_digest_identity_equal"] is False
