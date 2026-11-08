import json
from pathlib import Path

import pytest

from kvopt.continuum import (
    FakeClock,
    InputProvenance,
    InputSource,
    ProgramIdentity,
    RequestArrived,
    RequestIdentity,
    ServerInterRequestGapRecord,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.workload.continuum_native_history import load_history


def _manifest(count: int = 101) -> dict:
    return {
        "schema_version": "continuum.w1a_server_gap_history.v1",
        "duration_history_threshold": 100,
        "server_gap_sample_count": count,
        "server_gap_records": [
            {
                "program_id": "p",
                "previous_request_id": f"r{index}",
                "next_request_id": f"r{index + 1}",
                "previous_finish_timestamp": float(index),
                "next_arrival_timestamp": float(index) + 0.5,
                "duration_seconds": 0.5,
                "tool_type": "shell",
                "timestamp_provenance": "WRAPPER_BOUNDARY_MONOTONIC_OBSERVED",
            }
            for index in range(count)
        ],
    }


def test_load_history_requires_more_than_frozen_threshold(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert len(load_history(path)) == 101


def test_load_history_rejects_synthetic_or_changed_duration(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["server_gap_records"][0]["timestamp_provenance"] = "SYNTHETIC"
    path = tmp_path / "history.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        load_history(path)

    manifest = _manifest()
    manifest["server_gap_records"][0]["duration_seconds"] = 3.0
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duration"):
        load_history(path)


def test_runtime_history_seed_is_isolated_and_pre_lifecycle_only() -> None:
    class Provider:
        def estimate(self, _token_count: int) -> tuple[float, InputProvenance]:
            return 1.0, InputProvenance(InputSource.APPROXIMATED, "test")

    runtime = build_runtime(
        clock=FakeClock(),
        prefill_reload_provider=Provider(),
        default_ttl_seconds=1.0,
        duration_history_threshold=100,
    )
    records = (
        ServerInterRequestGapRecord(
            ProgramIdentity("history-program"),
            RequestIdentity("history-1"),
            RequestIdentity("history-2"),
            1.0,
            2.0,
            "shell",
        ),
    )
    runtime.seed_server_gap_history(records)
    assert runtime.server_gap_history.global_samples() == (1.0,)

    with pytest.raises(ValueError, match="already initialized"):
        runtime.seed_server_gap_history(records)

    fresh = build_runtime(
        clock=FakeClock(),
        prefill_reload_provider=Provider(),
        default_ttl_seconds=1.0,
        duration_history_threshold=100,
    )
    fresh.handle(RequestArrived(ProgramIdentity("tested"), RequestIdentity("r"), 0.0))
    with pytest.raises(ValueError, match="before tested lifecycle"):
        fresh.seed_server_gap_history(records)
