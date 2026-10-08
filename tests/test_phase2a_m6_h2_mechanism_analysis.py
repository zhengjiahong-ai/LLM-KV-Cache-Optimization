from kvopt.profiling.h2_mechanism import _m2_outcome, _m3_outcome


def test_m2_exact_native_token_rule_produces_pending_review_pass() -> None:
    rows = []
    probes = {
        "m2-k0": 0,
        "m2-k16": 256,
        "m2-k32": 512,
        "m2-k48": 768,
        "m2-k64": 1024,
        "m2-no-eviction-control": 1024,
    }
    for probe_id, cached in probes.items():
        for repeat in range(1, 10):
            rows.append(
                {
                    "probe_id": probe_id,
                    "repeat_index": repeat,
                    "native_cached_prefix_tokens": cached,
                    "recomputed_prefill_tokens": 1024 - cached,
                    "expected_cached_prefix_tokens": cached,
                    "expected_recomputed_prefill_tokens": 1024 - cached,
                }
            )

    outcome = _m2_outcome(rows)

    assert outcome["candidate_outcome"] == "PASS_PENDING_REVIEW"
    assert all(row["exact_repetition_count"] == 9 for row in outcome["probe_results"])
    assert not outcome["formal_verdict_authorized"]


def test_m3_frozen_position_rule_produces_pending_review_pass() -> None:
    rows = []
    for prefix_tokens in (512, 2048, 8192, 24576):
        for evicted_blocks in (1, 4, 16):
            cell_id = f"m3-r{prefix_tokens}-j{evicted_blocks}"
            for position in ("leading", "trailing"):
                recomputed = prefix_tokens if position == "leading" else evicted_blocks * 16
                for repeat in range(1, 10):
                    rows.append(
                        {
                            "cell_id": cell_id,
                            "position": position,
                            "repeat_index": repeat,
                            "recomputed_prefill_tokens": recomputed,
                        }
                    )

    outcome = _m3_outcome(rows)

    assert outcome["candidate_outcome"] == "PASS_PENDING_REVIEW"
    assert outcome["supporting_cell_count"] == 12
    assert outcome["no_resolved_effect_cell_count"] == 0
    assert all(cell["supporting_repetition_count"] == 9 for cell in outcome["cell_results"])
    assert not outcome["formal_verdict_authorized"]
