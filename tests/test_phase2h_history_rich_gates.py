import json
from pathlib import Path

from kvopt.profiling.phase2h_history_rich import _recompute_a1, evaluate_run


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
            "event_index": 3,
            "timestamp": 10.0,
            "payload": {
                "required_blocks": 3,
                "original_free_queue": [
                    {
                        "block_id": block_id,
                        "has_block_hash": True,
                        "native_lru_rank": block_id,
                    }
                    for block_id in range(1, 10)
                ],
                "candidates": [
                    {
                        "program_id": "a",
                        "prefix_id": "pa",
                        "retention_deadline_timestamp": 10.25,
                        "waiting_followup": True,
                        "block_ids": [1, 2, 3, 4],
                        "initially_reclaimable_block_ids": [1, 2, 3, 4],
                        "next_tool_type": None,
                        "elapsed_since_ttl_decision_seconds": 1.0,
                        "prefill_reload_seconds": 1.0,
                        "eta": 1.0,
                        "queue_delay_t_seconds": 0.0,
                    },
                    {
                        "program_id": "b",
                        "prefix_id": "pb",
                        "retention_deadline_timestamp": 11.0,
                        "waiting_followup": True,
                        "block_ids": [5, 6, 7, 8, 9],
                        "initially_reclaimable_block_ids": [5, 6, 7, 8, 9],
                        "next_tool_type": None,
                        "elapsed_since_ttl_decision_seconds": 1.0,
                        "prefill_reload_seconds": 1.0,
                        "eta": 1.0,
                        "queue_delay_t_seconds": 0.0,
                    },
                ],
                "selected_releases": [
                    {
                        "program_id": "a",
                        "prefix_id": "pa",
                        "newly_eligible_block_ids": [1, 2, 3, 4],
                    }
                ],
            },
        },
    ]
    trace, _releases = _recompute_a1(rows[-1], 0.5, 30.0)
    rows.append(
        {
            "event_type": "COST_AWARE_RELEASE_DECISION",
            "timestamp": 10.0,
            "payload": {
                "lambda": 0.5,
                "tau_seconds": 30.0,
                "selection_trace": trace,
            },
        }
    )
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
    assert report["gate_d"]["scoring_evidence_scope"] == ("SHADOW_DIAGNOSTIC_NOT_EXECUTED")


def test_gate_d_rejects_tampered_score_need_and_selection(tmp_path: Path) -> None:
    for field in ("score", "need", "selection"):
        run = tmp_path / field
        _write_run(run, "A1")
        rows = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        cost = next(row for row in rows if row["event_type"] == "COST_AWARE_RELEASE_DECISION")
        if field == "score":
            cost["payload"]["selection_trace"][0]["scores"][0]["expected_recompute"] += 1.0
        elif field == "need":
            cost["payload"]["selection_trace"][0]["need"] += 1
        else:
            cost["payload"]["selection_trace"][0]["key"] = ["b", "pb"]
        (run / "events.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        assert evaluate_run(run, arm="A1")["gate_d"]["status"] == "FAIL"


def test_gate_h_rejects_tampered_history_mode(tmp_path: Path) -> None:
    run = tmp_path / "mode"
    _write_run(run, "A1")
    rows = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    decision = next(row for row in rows if row["event_type"] == "TTL_DECISION_OBSERVED")
    decision["payload"]["history_mode"] = "tool_specific"
    (run / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    assert evaluate_run(run, arm="A1")["gate_h"]["status"] == "FAIL"
