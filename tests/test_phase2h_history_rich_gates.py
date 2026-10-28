import json
from pathlib import Path

from kvopt.profiling.phase2h_history_rich import evaluate_run


def _write_run(path: Path, arm: str) -> None:
    path.mkdir()
    (path / "run.json").write_text(
        json.dumps({"run_id": f"run-{arm.lower()}", "status": "success"}),
        encoding="utf-8",
    )
    samples = [0.25] * 101
    rows = [
        {
            "event_type": "TTL_HISTORY_INPUT_OBSERVED",
            "program_id": "program-a",
            "request_id": "request-a",
            "prefix_id": "prefix-a",
            "timestamp": 10.0,
            "payload": {
                "server_gap_history_provenance_source": "OBSERVED",
                "server_gap_history_provenance_reason": None,
                "global_server_gap_samples_seconds": samples,
                "tool_server_gap_samples_seconds": [],
                "queue_delay_t_seconds": 0.0,
                "eta": 1.0,
                "eta_provenance_source": "APPROXIMATED",
                "eta_provenance_reason": "FULLY_MEMORYFUL_COLD_START",
                "prefill_reload_seconds": 1.0,
                "prefill_reload_provenance_source": "APPROXIMATED",
                "prefill_reload_provenance_reason": "test profile",
                "default_ttl_seconds": 0.0,
                "duration_history_threshold": 100,
                "next_tool_type": None,
            },
        },
        {
            "event_type": "TTL_DECISION_OBSERVED",
            "program_id": "program-a",
            "request_id": "request-a",
            "prefix_id": "prefix-a",
            "timestamp": 10.0,
            "payload": {
                "history_mode": "global",
                "ttl_seconds": 0.25,
                "deadline_timestamp": 10.25,
            },
        },
        {
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "candidates": [{"program_id": "a"}, {"program_id": "b"}],
            },
        },
        {
            "event_type": "COST_AWARE_RELEASE_DECISION",
            "payload": {
                "selection_trace": [
                    {
                        "key": ["a", "pa"],
                        "need": 3,
                        "scores": [
                            {
                                "key": ["a", "pa"],
                                "new_blocks": 4,
                                "deadline": 10.25,
                                "reuse_proxy": 0.5,
                                "expected_recompute": 1.75,
                            },
                            {
                                "key": ["b", "pb"],
                                "new_blocks": 5,
                                "deadline": 11.0,
                                "reuse_proxy": 0.6,
                                "expected_recompute": 2.4,
                            },
                        ],
                    }
                ]
            },
        },
    ]
    (path / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_gate_h_recomputes_ttl_and_gate_d_uses_actual_a1(tmp_path: Path) -> None:
    run = tmp_path / "a1"
    _write_run(run, "A1")

    report = evaluate_run(run, arm="A1")

    assert report["gate_h"]["status"] == "PASS"
    assert report["gate_d"]["status"] == "PASS"
    assert report["gate_d"]["scoring_evidence_scope"] == "ACTUAL_A1_EXECUTION"


def test_a0_does_not_claim_shadow_a1_scoring_as_gate_d(tmp_path: Path) -> None:
    run = tmp_path / "a0"
    _write_run(run, "A0")

    report = evaluate_run(run, arm="A0")

    assert report["gate_d"]["candidate_opportunity_status"] == "PASS"
    assert report["gate_d"]["status"] == "NOT_APPLICABLE_SHADOW_ONLY"
    assert report["gate_d"]["scoring_evidence_scope"] == (
        "SHADOW_DIAGNOSTIC_NOT_EXECUTED"
    )
