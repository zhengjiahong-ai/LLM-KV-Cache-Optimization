import pytest

from kvopt.profiling.public_workload_oracle import (
    evaluate, loss_by_request, make_paths, prepare, suffix_loss,
)


def test_block_alignment_and_parent_identity():
    a, b, c = make_paths([[1, 2, 3, 4, 100], [1, 2, 5, 6], [7, 8, 3, 4]], 2)
    assert len(a) == 2
    assert a[0] == b[0]
    assert a[1] != c[1]


def test_shared_hole_loses_contiguous_hits_and_refills_once():
    a, b = (1, 2, 3, 4), (1, 2, 5, 6)
    future = [a + (8,), b + (7,), a + (8, 9)]
    requests = prepare(set(a+b), future, {2, 4, 5})
    assert [q.baseline_hits for q in requests] == [4, 4, 5]
    assert loss_by_request(requests, {2}) == [3, 0, 0]
    assert loss_by_request(requests, {2, 4}) == [3, 0, 0]
    assert loss_by_request(requests, {2, 5}) == [3, 2, 0]
    assert suffix_loss([a, b], {2}) == 6


def test_untouched_branch_and_horizon_change_the_optimum():
    a, b = (1, 2, 3), (1, 4, 5, 6)
    short = evaluate([a, b], [a], [2, 4, 6], 1)
    long = evaluate([a, b], [a, b], [2, 4, 6], 1)
    assert short["oracle"] == 0
    assert short["warm_shallow_regret"] == 2
    assert long["oracle"] == 1
    assert long["legal_sets"] == 3
    assert long["greedy_regret"] == 0


def test_equal_hit_length_can_hide_different_victims():
    a, b = (1, 2), (1, 3)
    result = evaluate([a, b], [a, b], [2, 3], 1)
    assert result["victim_loss_span"] == 0
    assert result["rank_agreement"] is None


def test_invalid_candidate_and_budget_fail_closed():
    with pytest.raises(ValueError, match="subset"):
        prepare({1}, [(1,)], {2})
    for ranked, budget in [([1, 1, 2], 1), ([1, 2], 2)]:
        with pytest.raises(ValueError, match="unique"):
            evaluate([(1, 2)], [(1, 2)], ranked, budget)


def test_memoryfulness_matches_explicit_snapshots():
    np = pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    from scripts.public_workload_memoryfulness import eta, moments

    lengths = [2, 4, 9]
    for with_end in (False, True):
        points = [(k, n-k) for n in lengths for k in range(1, n+int(with_end))]
        expected = -np.corrcoef(np.array(points).T)[0, 1]
        assert eta(moments(lengths, with_end).sum(axis=0)) == pytest.approx(expected)
    assert eta(moments([8, 8]).sum(axis=0)) == pytest.approx(1)


def test_rank_tie_sensitivity_preserves_action_set():
    path = (1, 2, 3, 4)
    result = evaluate([path], [path], [1, 2, 3], 2, [3, 2, 1])
    assert result["warm_shallow_regret"] == 1
    assert result["warm_deep_regret"] == 0
    assert result["zero_marginal_pair_rate"] == 1
    with pytest.raises(ValueError, match="same candidate set"):
        evaluate([path], [path], [1, 2, 3], 2, [1, 2, 4])


def test_fixed_slots_distinguish_known_end_and_censoring():
    pytest.importorskip("pyarrow")
    pytest.importorskip("tokenizers")
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        import pandas as pd
        from analyze_public_workload_evidence import (
            request_counts, slot_order, summarize_request_counts,
        )

        inputs = [{25: object()}, {25: object(), 26: object()}]
        slots = slot_order(inputs, 4, 0, ["submit", "submit"])
        assert slots == [(0, 25), (1, 25), (1, 26)]
        rows = pd.DataFrame([request_counts(slots, 2), request_counts(slots[:-1], 2)])
        coverage = summarize_request_counts(rows, 4)
        assert coverage["terminal_empty_slots"] == 3
        assert coverage["full_horizon_clusters"] == 0
        assert coverage["future_requests_p50"] == 2.5
        assert coverage["future_requests_a_total"] == 2
        assert coverage["future_requests_b_total"] == 3
        single = pd.DataFrame([request_counts([(0, 25)], 1)])
        assert "future_requests_b_total" not in summarize_request_counts(single, 1)
        assert slot_order(inputs, 4, 0, ["step_limit", "submit"]) is None
        assert slot_order(inputs, 1, 1, ["step_limit", "submit"]) == [(1, 25)]
    finally:
        sys.path.pop(0)
