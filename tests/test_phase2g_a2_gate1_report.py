import json
from pathlib import Path

from kvopt.profiling.phase2g_a2_gate1 import build_gate1_report


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _write_run(
    root: Path,
    *,
    fallback: bool,
    eviction_key: str = "native-key-1",
    selected_victims: list[int] | None = None,
) -> None:
    root.mkdir()
    _write_json(root / "run.json", {"execution_status": "success"})
    events = [
        {
            "event_index": 1,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "original_free_queue": [
                    {"block_id": 1, "has_block_hash": True},
                    {"block_id": 2, "has_block_hash": False},
                ]
            },
        },
        {
            "event_index": 2,
            "event_type": "COST_AWARE_BLOCK_DECISION",
            "payload": {
                "required_blocks": 2,
                "legal_block_ids": [1, 2],
                "native_lru_victims": [1, 2],
                "selected_victims": selected_victims or [1, 2],
                "selector": "native_lru_fallback" if fallback else "incremental_greedy",
                "cost_known": not fallback,
                "fallbacks": ["content_unverified"] if fallback else [],
                "adapter_problems": [],
                "contract_problems": [],
                "chain_count": 0 if fallback else 1,
                "shared_block_count": 0,
                "identified_hashed_block_count": 0 if fallback else 1,
                "legal_content_hashes": [
                    {"block_id": 1, "content_hash": "native-key-1"},
                    {"block_id": 2, "content_hash": None},
                ],
                "native_hash_process_id": "process-1",
            },
        },
        {
            "event_index": 3,
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {
                "block_id": 1,
                "native_cache_key_before": eviction_key,
                "native_hash_process_id": "process-1",
                "hash_removed_after": True,
            },
        },
    ]
    (root / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )


def test_gate1_report_keeps_no_divergence_and_fallback_visible(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign.json"
    _write_json(
        campaign,
        {
            "planned_run_count": 4,
            "runs": [
                {
                    "run_id": "control-a2-repeat-1",
                    "policy": "A2",
                    "expected_relation": "SAME",
                },
                {
                    "run_id": "fallback-a2-repeat-1",
                    "policy": "A2",
                    "expected_relation": "FALLBACK_SAME",
                },
            ],
        },
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(runs / "control-a2-repeat-1", fallback=False)
    _write_run(runs / "fallback-a2-repeat-1", fallback=True)

    report = build_gate1_report(campaign_manifest=campaign, run_root=runs)

    assert report["outcome"] == "MECHANISM_INTEGRATION_DEMONSTRATED_WITH_LIMITATIONS"
    assert report["native_selection_divergence"] == "NOT_REALIZED"
    assert report["status_counts"] == {"AGREED": 1, "FALLBACK": 1}
    assert report["physical_eviction_correlation"] == "DEMONSTRATED"
    assert report["gate2_execution_authorized"] is False


def test_gate1_report_matches_victim_sets_and_rejects_wrong_content_identity(
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign.json"
    _write_json(
        campaign,
        {
            "planned_run_count": 2,
            "runs": [
                {
                    "run_id": "identity-a2-repeat-1",
                    "policy": "A2",
                    "expected_relation": "AUDIT",
                }
            ],
        },
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(
        runs / "identity-a2-repeat-1",
        fallback=False,
        eviction_key="wrong-native-key",
        selected_victims=[2, 1],
    )

    report = build_gate1_report(campaign_manifest=campaign, run_root=runs)

    assert report["outcome"] == "INVALID"
    assert report["status_counts"] == {"INVALID": 1}
    assert report["runs"][0]["observed_relation"] == "SAME"
    assert report["runs"][0]["physical_evidence_complete"] is False
