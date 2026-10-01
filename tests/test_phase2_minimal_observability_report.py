from __future__ import annotations

import json
from pathlib import Path

from scripts.spikes.run_phase2_minimal_observability_metal import (
    build_observation_report,
)


def _write_run(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps({"status": "success", "run_id": "test"}) + "\n",
        encoding="utf-8",
    )
    (run / "trace.json").write_text("{}\n", encoding="utf-8")
    (run / "replay.jsonl").write_text("{}\n", encoding="utf-8")
    indexed_events = [
        {**event, "event_index": index}
        for index, event in enumerate(events)
    ]
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in indexed_events),
        encoding="utf-8",
    )
    return run


def _event(
    event_type: str,
    timestamp: float,
    *,
    program_id: str | None = None,
    request_id: str | None = None,
    prefix_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "event_type": event_type,
        "timestamp": timestamp,
        "clock_domain": "test",
        "source": "test",
        "payload": payload or {},
    }
    if program_id is not None:
        value["program_id"] = program_id
    if request_id is not None:
        value["request_id"] = request_id
    if prefix_id is not None:
        value["prefix_id"] = prefix_id
    return value


def _candidate(
    program_id: str,
    prefix_id: str,
    block_ids: list[int],
    *,
    tool: str,
) -> dict[str, object]:
    return {
        "program_id": program_id,
        "prefix_id": prefix_id,
        "retention_deadline_timestamp": 10.0,
        "waiting_followup": True,
        "block_ids": block_ids,
        "initially_reclaimable_block_ids": block_ids,
        "next_tool_type": tool,
        "elapsed_since_ttl_decision_seconds": 1.0,
        "prefill_reload_seconds": 0.1,
        "eta": 1.0,
        "queue_delay_t_seconds": 0.0,
    }


def _complete_events(*, include_physical_eviction: bool) -> list[dict[str, object]]:
    events = [
        _event("REAL_RUNTIME_READY", 0),
        _event("PROGRAM_STARTED", 0.1, program_id="agent-a"),
        _event("REQUEST_ARRIVED", 0.2, program_id="agent-a", request_id="a1"),
        _event("REQUEST_ADMITTED", 0.3, program_id="agent-a", request_id="a1"),
        _event(
            "BLOCKS_OBSERVED",
            1,
            program_id="agent-a",
            request_id="a1",
            prefix_id="pa",
            payload={"block_ids": [1, 2]},
        ),
        _event("TURN_FINISHED", 1.1, program_id="agent-a", request_id="a1"),
        _event("FOLLOWUP_WAITING", 1.2, program_id="agent-a", request_id="a2"),
        _event("TOOL_GAP_STARTED", 1.3, program_id="agent-a"),
        _event("PROGRAM_STARTED", 1.4, program_id="agent-b"),
        _event("REQUEST_ARRIVED", 1.5, program_id="agent-b", request_id="b1"),
        _event("REQUEST_ADMITTED", 1.6, program_id="agent-b", request_id="b1"),
        _event(
            "BLOCKS_OBSERVED",
            2,
            program_id="agent-b",
            request_id="b1",
            prefix_id="pb",
            payload={"block_ids": [3, 4]},
        ),
        _event("TURN_FINISHED", 2.1, program_id="agent-b", request_id="b1"),
        _event("FOLLOWUP_WAITING", 2.2, program_id="agent-b", request_id="b2"),
        _event("TOOL_GAP_STARTED", 2.3, program_id="agent-b"),
        _event(
            "FORCED_RELEASE_DECISION",
            3,
            payload={
                "required_blocks": 2,
                "original_free_queue": [
                    {
                        "block_id": 1,
                        "native_lru_rank": 0,
                        "has_block_hash": True,
                        "eligibility_tier": "protected",
                    }
                ],
                "ordinary_expired_entries": [],
                "candidates": [
                    _candidate("agent-a", "pa", [1, 2], tool="search"),
                    _candidate("agent-b", "pb", [3, 4], tool="database"),
                ],
                "selected_releases": [
                    {
                        "program_id": "agent-a",
                        "prefix_id": "pa",
                        "newly_eligible_block_ids": [1, 2],
                    }
                ],
            },
        ),
        _event("TOOL_GAP_ENDED", 3.9, program_id="agent-a"),
        _event("REQUEST_ARRIVED", 4, program_id="agent-a", request_id="a2"),
        _event(
            "VLLM_PREFIX_SNAPSHOT",
            4.1,
            program_id="agent-a",
            request_id="a2",
            prefix_id="pa",
            payload={"block_ids": [5, 6], "reusable_token_count": 256},
        ),
        _event(
            "VLLM_REQUEST_COMPLETED",
            4.2,
            program_id="agent-a",
            request_id="a2",
            payload={"output_token_count": 1},
        ),
        _event("PROGRAM_COMPLETED", 4.3, program_id="agent-a"),
    ]
    if include_physical_eviction:
        events.insert(16, _event("BLOCK_EVICTED", 3.1, payload={"block_id": 1}))
    return events


def test_report_accepts_complete_minimum_chain(tmp_path: Path) -> None:
    report = build_observation_report(
        _write_run(tmp_path, _complete_events(include_physical_eviction=True))
    )
    assert report["status"] == "PASS"
    assert all(check["status"] == "PASS" for check in report["checks"].values())


def test_report_rejects_logical_release_without_physical_eviction(tmp_path: Path) -> None:
    report = build_observation_report(
        _write_run(tmp_path, _complete_events(include_physical_eviction=False))
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["physical_eviction_join"]["status"] == "FAIL"
