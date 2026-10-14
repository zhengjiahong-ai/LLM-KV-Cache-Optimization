from kvopt.profiling.phase2e_campaign_gate import compare_pair


def _arm(baseline: str, digest: str = "abc") -> dict[str, object]:
    return {
        "status": "VALID",
        "family_mechanism_status": "REALIZED",
        "pairing_provenance": {"git_sha": "git", "trace_sha256": "trace", "model": "m", "generation": {}, "cache": {}, "batching": {}, "seed": 1, "backend_revision": "rev"},
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


def test_mechanism_not_realized_is_not_eligible() -> None:
    a, b = _arm("native-lru"), _arm("continuum-baseline")
    b["family_mechanism_status"] = "NOT_REALIZED"
    result = compare_pair(a, b)
    assert result["status"] == "COMPARABLE"
    assert result["mechanism_evaluable"] is False


def test_pair_rejects_mismatched_provenance() -> None:
    left, right = _arm("native-lru"), _arm("continuum-baseline")
    right["pairing_provenance"]["backend_revision"] = "another-revision"
    result = compare_pair(left, right)
    assert result["status"] == "NOT_COMPARABLE"
    assert result["checks"]["provenance_equal"] is False
