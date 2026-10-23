from kvopt.profiling.continuum_w1b_report import _delta, _unique_materialized_digests


def test_delta_uses_candidate_minus_baseline() -> None:
    candidate = {"totals": {"metric": 7}}
    baseline = {"totals": {"metric": 10}}
    assert _delta(candidate, baseline, "metric") == -3


def test_delta_is_unavailable_when_either_arm_is_missing() -> None:
    candidate = {"totals": {"metric": None}}
    baseline = {"totals": {"metric": 10}}
    assert _delta(candidate, baseline, "metric") is None


def test_duplicate_materialization_is_not_collapsed_into_valid_identity() -> None:
    events = [
        {"request_id": "r", "payload": {"submitted_token_ids_sha256": "a"}},
        {"request_id": "r", "payload": {"submitted_token_ids_sha256": "a"}},
    ]

    digests, counts = _unique_materialized_digests(events)

    assert digests == {}
    assert counts == {"r": 2}
