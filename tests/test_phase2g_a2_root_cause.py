import json
from pathlib import Path

from kvopt.profiling.phase2g_a2_root_cause import audit


def _write_events(path: Path, rows: list[dict[str, object]]) -> None:
    path.mkdir(parents=True)
    (path / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_audit_preserves_unobservable_selection_and_compares_decision_sets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    forced = {
        "event_index": 1,
        "event_type": "FORCED_RELEASE_DECISION",
        "payload": {
            "required_blocks": 1,
            "original_free_queue": [
                {
                    "block_id": 7,
                    "eligibility_tier": 1,
                    "has_block_hash": True,
                    "native_lru_rank": 0,
                }
            ],
        },
    }
    _write_events(root / "s-a0-repeat-1", [forced])
    _write_events(
        root / "s-a2-repeat-1",
        [
            forced,
            {
                "event_index": 2,
                "event_type": "COST_AWARE_BLOCK_DECISION",
                "payload": {
                    "selector": "native_lru_fallback",
                    "fallbacks": ["content_unverified"],
                    "contract_problems": [],
                    "adapter_problems": [],
                    "legal_block_ids": [7],
                    "legal_content_hashes": [
                        {"block_id": 7, "content_hash": "hash-7"}
                    ],
                    "required_blocks": 1,
                    "identified_hashed_block_count": 1,
                    "chain_count": 1,
                    "shared_block_count": 0,
                    "native_lru_victims": [7],
                    "selected_victims": [7],
                },
            },
        ],
    )
    request_outcome = {
        "request:1": {
            "prompt_tokens": 17,
            "eligible_prefix_tokens": 16,
            "cached_prefix_tokens": 8,
        }
    }
    report = {
        "runs": [
            {
                "run_id": "s-a0-repeat-1",
                "scenario_id": "s",
                "family": "F1",
                "repeat": 1,
                "policy": "A0",
                "status": "VALID",
                "request_outcomes": request_outcome,
                "unmapped_physical_eviction_count": 0,
                "physical_eviction_count": 0,
            },
            {
                "run_id": "s-a2-repeat-1",
                "scenario_id": "s",
                "family": "F1",
                "repeat": 1,
                "policy": "A2",
                "status": "VALID",
                "request_outcomes": request_outcome,
                "decision_rows": [
                    {
                        "event_index": 2,
                        "legal_identity_states": {"7": "HASHED_PROVEN"},
                    }
                ],
                "unmapped_physical_eviction_count": 0,
                "physical_eviction_count": 0,
            },
        ],
        "pairs": [{"selection_diverged": None}],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result, decisions = audit(run_root=root, campaign_report=report_path)

    assert result["fallback_reason_counts"] == {"content_unverified": 1}
    assert result["forced_a0_actual_equals_a2_reference_counts"] == {"True": 1}
    assert result["not_realized_decomposition"][
        "pair_selection_unobservable_count"
    ] == 1
    assert result["request_metrics_by_policy"]["A2"]["recomputed"]["sum"] == 8
    assert decisions[0]["selected_equals_native_lru"] is True
