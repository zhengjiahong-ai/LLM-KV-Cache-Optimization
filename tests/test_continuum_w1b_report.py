from kvopt.profiling.continuum_w1b_report import _delta


def test_delta_uses_candidate_minus_baseline() -> None:
    candidate = {"totals": {"metric": 7}}
    baseline = {"totals": {"metric": 10}}
    assert _delta(candidate, baseline, "metric") == -3


def test_delta_is_unavailable_when_either_arm_is_missing() -> None:
    candidate = {"totals": {"metric": None}}
    baseline = {"totals": {"metric": 10}}
    assert _delta(candidate, baseline, "metric") is None
