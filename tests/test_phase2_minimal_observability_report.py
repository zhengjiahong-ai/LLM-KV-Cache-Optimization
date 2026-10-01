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
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
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


def test_report_accepts_complete_minimum_chain(tmp_path: Path) -> None:
    events = [
        _event("REAL_RUNTIME_READY", 0),
        _event(
            "BLOCKS_OBSERVED", 1,
            program_id="agent-a", request_id="a1", prefix_id="pa",
            payload={"block_ids": [1, 2]},
        ),
        _event(
            "BLOCKS_OBSERVED", 2,
            program_id="agent-b", request_id="b1", prefix_id="pb",
            payload={"block_ids": [3, 4]},
        ),
        _event(
            "FORCED_RELEASE_DECISION", 3,
            payload={
                "candidates": [
                    {"program_id": "agent-a", "prefix_id": "pa"},
                    {"program_id": "agent-b", "prefix_id": "pb"},
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
        _event("BLOCK_EVICTED", 3.1, payload={"block_id": 1}),
        _event("REQUEST_ARRIVED", 4, program_id="agent-a", request_id="a2"),
        _event(
            "VLLM_PREFIX_SNAPSHOT", 4.1,
            program_id="agent-a", request_id="a2", prefix_id="pa",
            payload={"block_ids": [5, 6], "reusable_token_count": 256},
        ),
        _event(
            "VLLM_REQUEST_COMPLETED", 4.2,
            program_id="agent-a", request_id="a2",
            payload={"output_token_count": 1},
        ),
    ]
    report = build_observation_report(_write_run(tmp_path, events))
    assert report["status"] == "PASS"
    assert all(
        check["status"] == "PASS"
        for check in report["checks"].values()
    )


def test_report_rejects_logical_release_without_physical_eviction(tmp_path: Path) -> None:
    events = [
        _event("REAL_RUNTIME_READY", 0),
        _event(
            "BLOCKS_OBSERVED", 1,
            program_id="agent-a", request_id="a1", prefix_id="pa",
            payload={"block_ids": [1]},
        ),
        _event(
            "BLOCKS_OBSERVED", 2,
            program_id="agent-b", request_id="b1", prefix_id="pb",
            payload={"block_ids": [2]},
        ),
        _event(
            "FORCED_RELEASE_DECISION", 3,
            payload={
                "candidates": [
                    {"program_id": "agent-a", "prefix_id": "pa"},
                    {"program_id": "agent-b", "prefix_id": "pb"},
                ],
                "selected_releases": [
                    {
                        "program_id": "agent-a",
                        "prefix_id": "pa",
                        "newly_eligible_block_ids": [1],
                    }
                ],
            },
        ),
        _event("REQUEST_ARRIVED", 4, program_id="agent-a", request_id="a2"),
        _event(
            "VLLM_PREFIX_SNAPSHOT", 4.1,
            program_id="agent-a", request_id="a2", prefix_id="pa",
            payload={"block_ids": [3]},
        ),
    ]
    report = build_observation_report(_write_run(tmp_path, events))
    assert report["status"] == "FAIL"
    assert report["checks"]["physical_eviction_join"]["status"] == "FAIL"
