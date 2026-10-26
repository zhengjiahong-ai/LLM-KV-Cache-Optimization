from __future__ import annotations

import json
from pathlib import Path

from kvopt.continuum import ControlledSparseReplayClock, LogicalTimeBoundary
from kvopt.workload import phase2_runner
from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from scripts.spikes.phase2_minimal_observability_metal import (
    _requires_retention_snapshot,
)


def test_right_censored_return_does_not_require_retention_snapshot() -> None:
    right_censored = frozenset({"return-request"})

    assert not _requires_retention_snapshot("return-request", right_censored)
    assert _requires_retention_snapshot("retained-request", right_censored)


class _Backend:
    forced_release_count = 1
    last_selected_block_ids = (1,)

    def __init__(self, config: dict[str, object]) -> None:
        self.observation_capabilities: dict[str, object] = {}
        boundaries = config["backend_options"]["controlled_sparse_replay_boundaries"]
        self.controlled_replay_clock = ControlledSparseReplayClock(
            boundaries=tuple(LogicalTimeBoundary(**row) for row in boundaries)
        )
        self.prepared: dict[str, object] = {}
        self.submitted: list[str] = []

    def execute(self, request: object) -> None:
        raise AssertionError("controlled replay must not use synchronous execute")

    def record_logical_time_advance(self, advance: object) -> None:
        return None

    def prepare_arrival(self, request: object) -> None:
        self.prepared[request.request_id] = request

    def submit_prepared(self, request_id: str) -> RequestHandle:
        self.submitted.append(request_id)
        return RequestHandle(request_id, f"n-{request_id}", f"e-{request_id}", 1.0)

    def drain_native(self, *, timeout_seconds: float):
        del timeout_seconds
        rows = tuple(
            RequestCompletion(item, f"n-{item}", f"e-{item}", 2.0)
            for item in self.submitted
        )
        self.submitted.clear()
        return rows

    def finish_logical_completion(self, request_id: str) -> None:
        self.prepared.pop(request_id)

    def execute_prepared_pressure(self, boundary_id: str) -> None:
        assert boundary_id == "pressure"

    def close(self) -> None:
        return None


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_phase2_runner_executes_controlled_timeline(monkeypatch, tmp_path: Path) -> None:
    boundaries = [
        {
            "boundary_id": "arrival:a",
            "logical_timestamp": 0.0,
            "source": "SOURCE",
            "kind": "ARRIVAL",
            "request_id": "a",
        },
        {
            "boundary_id": "completion:a",
            "logical_timestamp": 1.0,
            "source": "SOURCE",
            "kind": "COMPLETION",
            "request_id": "a",
        },
        {
            "boundary_id": "pressure",
            "logical_timestamp": 2.0,
            "source": "FROZEN",
            "kind": "PRESSURE",
            "request_id": None,
        },
    ]
    trace = tmp_path / "trace.json"
    config = tmp_path / "config.json"
    _write(
        trace,
        {
            "schema_version": "phase2.trace.v1",
            "trace_id": "controlled",
            "allow_incomplete_programs": False,
            "requests": [
                {
                    "program_id": "p",
                    "request_id": "a",
                    "turn_index": 1,
                    "planned_arrival_offset_seconds": 0.0,
                    "prompt": "x",
                    "prefix_prompt": "",
                    "is_terminal": True,
                    "next_tool_type": None,
                    "tool_gap_seconds": None,
                    "kind": "turn",
                }
            ],
            "pressure_stages": [],
        },
    )
    _write(
        config,
        {
            "schema_version": "phase2.config.v1",
            "trace": "trace.json",
            "seed": 1,
            "policy": "test",
            "runtime_mode": "test",
            "backend_factory": "test:factory",
            "backend_revision": "test",
            "model": {"name": "m", "revision": "r"},
            "tokenizer": {"name": "m", "revision": "r"},
            "cache": {"block_override": 1},
            "generation": {"max_new_tokens": 1},
            "batching": {"max_concurrent_requests": 1},
            "pressure": {"safety_ceiling": 1},
            "observe": True,
            "controlled_sparse_replay": {
                "maximum_concurrent_requests": 1,
                "native_timeout_seconds": 10.0,
                "boundaries": boundaries,
            },
            "backend_options": {
                "controlled_sparse_replay_boundaries": [
                    {key: row[key] for key in ("boundary_id", "logical_timestamp", "source")}
                    for row in boundaries
                ]
            },
        },
    )
    monkeypatch.setattr(
        phase2_runner,
        "_load_factory",
        lambda _reference: lambda backend_config, _sink: _Backend(backend_config),
    )

    output = phase2_runner.run_phase2(
        config, output_root=tmp_path / "runs", run_id="controlled-run"
    )
    manifest = json.loads((output / "run.json").read_text())

    assert manifest["status"] == "success"
    assert manifest["controlled_sparse_replay"]["native_completion_count"] == 1
    assert manifest["controlled_sparse_replay"]["replay_idle_seconds"] == 0.0
    assert manifest["execution_telemetry"]["engine_initialization_seconds"] >= 0.0
