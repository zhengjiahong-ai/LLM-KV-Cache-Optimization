from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.profiling.ingestion import (
    ArtifactValidationError,
    load_run_artifacts,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_valid_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()

    _write_json(
        run_dir / "run.json",
        {
            "schema_version": "phase2.run.v1",
            "run_id": "run-a",
            "status": "success",
        },
    )
    _write_json(
        run_dir / "trace.json",
        {
            "schema_version": "phase2.trace.v1",
            "trace_id": "trace-a",
            "requests": [],
            "pressure_stages": [],
        },
    )
    _write_jsonl(
        run_dir / "replay.jsonl",
        [
            {
                "program_id": "agent-a",
                "request_id": "agent-a:turn:1",
            }
        ],
    )
    _write_jsonl(
        run_dir / "events.jsonl",
        [
            {
                "schema_version": "phase2.event.v1",
                "run_id": "run-a",
                "event_index": 0,
                "event_type": "REQUEST_ARRIVED",
                "timestamp": 1.0,
                "clock_domain": "test",
                "source": "test",
                "payload": {},
            },
            {
                "schema_version": "phase2.event.v1",
                "run_id": "run-a",
                "event_index": 1,
                "event_type": "FORCED_RELEASE_DECISION",
                "timestamp": 2.0,
                "clock_domain": "test",
                "source": "test",
                "payload": {
                    "required_blocks": 1,
                    "original_free_queue": [],
                    "ordinary_expired_entries": [],
                    "candidates": [],
                    "selected_releases": [],
                },
            },
        ],
    )
    return run_dir


def test_load_run_artifacts_reads_all_four_raw_sources(tmp_path: Path) -> None:
    artifacts = load_run_artifacts(_write_valid_run(tmp_path))

    assert artifacts.run_id == "run-a"
    assert artifacts.manifest["status"] == "success"
    assert artifacts.trace["trace_id"] == "trace-a"
    assert len(artifacts.replay) == 1
    assert [event["event_index"] for event in artifacts.events] == [0, 1]


def test_load_run_artifacts_rejects_duplicate_event_index(
    tmp_path: Path,
) -> None:
    run_dir = _write_valid_run(tmp_path)
    events_path = run_dir / "events.jsonl"

    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    events[1]["event_index"] = 0
    _write_jsonl(events_path, events)

    with pytest.raises(
        ArtifactValidationError,
        match="event_index must be unique and strictly increasing",
    ):
        load_run_artifacts(run_dir)


def test_load_run_artifacts_rejects_missing_required_file(
    tmp_path: Path,
) -> None:
    run_dir = _write_valid_run(tmp_path)
    (run_dir / "events.jsonl").unlink()

    with pytest.raises(
        ArtifactValidationError,
        match="required artifact is missing: events.jsonl",
    ):
        load_run_artifacts(run_dir)


def test_load_run_artifacts_rejects_mismatched_event_run_id(
    tmp_path: Path,
) -> None:
    run_dir = _write_valid_run(tmp_path)
    events_path = run_dir / "events.jsonl"

    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    events[0]["run_id"] = "another-run"
    _write_jsonl(events_path, events)

    with pytest.raises(
        ArtifactValidationError,
        match="mismatched run_id",
    ):
        load_run_artifacts(run_dir)


def test_load_run_artifacts_rejects_unsupported_run_schema(
    tmp_path: Path,
) -> None:
    run_dir = _write_valid_run(tmp_path)
    manifest_path = run_dir / "run.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "unknown"
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ArtifactValidationError,
        match="unsupported run schema_version",
    ):
        load_run_artifacts(run_dir)


def test_load_run_artifacts_rejects_missing_event_field(
    tmp_path: Path,
) -> None:
    run_dir = _write_valid_run(tmp_path)
    events_path = run_dir / "events.jsonl"

    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    events[0].pop("event_type")
    _write_jsonl(events_path, events)

    with pytest.raises(
        ArtifactValidationError,
        match="missing required field: event_type",
    ):
        load_run_artifacts(run_dir)