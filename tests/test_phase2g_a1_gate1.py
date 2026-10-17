from kvopt.profiling.phase2g_a1_gate1 import compare_pair


def _arm(policy: str, *, selected: str, recomputed: int) -> dict[str, object]:
    return {
        "status": "VALID",
        "case_id": "case",
        "repeat": 1,
        "policy": policy,
        "git_sha": "git",
        "trace_sha256": "trace",
        "request_ids": ["a:1", "a:2"],
        "materialized_token_digests": {"a:1": "one", "a:2": "two"},
        "pairing_config": {"cache": 37},
        "selected_programs": [selected],
        "physical_eviction_signature": [(selected, 0)],
        "return_recomputed_tokens": {"a:2": recomputed},
    }


def test_divergence_pair_requires_all_three_mechanism_layers() -> None:
    result = compare_pair(
        _arm("A0", selected="a", recomputed=129),
        _arm("A1", selected="b", recomputed=1),
        expected_relation="DIFFERENT",
    )

    assert result["status"] == "PASS"


def test_control_pair_requires_same_mechanism_outcome() -> None:
    result = compare_pair(
        _arm("A0", selected="a", recomputed=129),
        _arm("A1", selected="a", recomputed=129),
        expected_relation="SAME",
    )

    assert result["status"] == "PASS"


def test_pair_fails_closed_on_materialized_token_difference() -> None:
    a0 = _arm("A0", selected="a", recomputed=129)
    a1 = _arm("A1", selected="b", recomputed=1)
    a1["materialized_token_digests"] = {"a:1": "different"}

    result = compare_pair(a0, a1, expected_relation="DIFFERENT")

    assert result["status"] == "FAIL"
    assert result["pairing_checks"]["same_materialized_tokens"] is False
