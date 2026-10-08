from kvopt.profiling.h2_headroom import analyze_m4_rows


def _rows(entry: int, block: int) -> list[dict[str, object]]:
    rows = []
    for prefix in (512, 2048, 8192, 24576):
        for evicted in (1, 4, 16):
            cell = f"m4-r{prefix}-j{evicted}"
            for repeat in range(1, 10):
                rows.extend(
                    (
                        {
                            "cell_id": cell,
                            "arm": "entry",
                            "repeat_index": repeat,
                            "observed_recomputed_tokens": entry,
                        },
                        {
                            "cell_id": cell,
                            "arm": "block",
                            "repeat_index": repeat,
                            "observed_recomputed_tokens": block,
                        },
                    )
                )
    return rows


def test_m4_frozen_rule_fails_when_paths_coincide() -> None:
    outcome = analyze_m4_rows(_rows(64, 64))

    assert outcome["candidate_outcome"] == "FAIL_PENDING_REVIEW"
    assert outcome["supporting_cell_count"] == 0
    assert outcome["no_resolved_headroom_cell_count"] == 12
    assert all(cell["no_resolved_headroom_repetition_count"] == 9 for cell in outcome["cell_results"])
    assert outcome["scope"] == "single_prefix_controlled_mechanism_headroom_only"


def test_m4_frozen_rule_passes_only_with_resolved_headroom() -> None:
    outcome = analyze_m4_rows(_rows(80, 64))

    assert outcome["candidate_outcome"] == "PASS_PENDING_REVIEW"
    assert outcome["supporting_cell_count"] == 12
    assert all(cell["supporting_repetition_count"] == 9 for cell in outcome["cell_results"])
