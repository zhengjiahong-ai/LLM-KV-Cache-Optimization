"""Append-only serialization of Phase 2 raw observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from .experiment_events import ExperimentEvent


class JsonlExperimentEventSink:
    def __init__(self, path: str | Path, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be non-empty")
        self._file: TextIO = Path(path).open("x", encoding="utf-8", newline="\n")
        self._run_id = run_id
        self.event_count = 0
        self.forced_release_count = 0

    def emit(self, event: ExperimentEvent) -> None:
        if not isinstance(event, ExperimentEvent):
            raise TypeError("event must be ExperimentEvent")
        record: dict[str, object] = {
            "schema_version": "phase2.event.v1",
            "run_id": self._run_id,
            "event_index": self.event_count,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "clock_domain": event.clock_domain,
            "source": event.source,
            "payload": event.payload.to_dict(),
        }
        if event.program_id is not None:
            record["program_id"] = event.program_id.value
        if event.request_id is not None:
            record["request_id"] = event.request_id.value
        if event.prefix_id is not None:
            record["prefix_id"] = event.prefix_id.canonical_value
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self._file.write(line + "\n")
        self._file.flush()
        self.event_count += 1
        if event.event_type == "FORCED_RELEASE_DECISION":
            self.forced_release_count += 1

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "JsonlExperimentEventSink":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
