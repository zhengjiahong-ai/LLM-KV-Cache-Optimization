from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from kvopt.profiling.datasets import build_runs_table
from kvopt.profiling.ingestion import (
    ArtifactValidationError,
    RawRunArtifacts,
)


def _raw_run() -> RawRunArtifacts:
    return RawRunArtifacts(
        run_dir=Path("/artifacts/run-a"),
        run_id="run-a",
        manifest={
            "schema_version": "phase2.run.v1",
            "run_id": "run-a",
            "status": "success",
            "failure_reason": None,
            "git_sha": "abc123",
            "git_dirty": False,
            "trace_id": "trace-a",
            "trace_sha256": "trace-hash",
            "config_sha256": "config-hash",
            "seed": 11,
            "backend": "example.module:build_backend",
            "backend_revision": "backend-v1",
            "model": {
                "name": "example/model",
                "revision": "model-revision",
            },
            "tokenizer": {
                "name": "example/tokenizer",
                "revision": "tokenizer-revision",
            },
            "platform": "test-platform",
            "started_at_utc": "2026-10-02T00:00:00+00:00",
            "ended_at_utc": "2026-10-02T00:01:00+00:00",
            "event_count": 8,
            "persisted_forced_release_event_count": 2,
            "config": {
                "policy": "continuum-baseline",
                "runtime_mode": "vllm-metal-observability",
                "profiling_scenario_id": "F1-candidates-2",
            },
            "observation_availability": {
                "forced_release": "available",
                "native_apc_hit_miss": "unavailable",
            },
        },
        trace={
            "schema_version": "phase2.trace.v1",
            "trace_id": "trace-a",
        },
        replay=(),
        events=(),
    )


def test_build_runs_table_preserves_provenance() -> None:
    rows = build_runs_table((_raw_run(),))

    assert len(rows) == 1
    row = rows[0]

    assert row.run_id == "run-a"
    assert row.source_run_dir == "/artifacts/run-a"
    assert row.status == "success"
    assert row.git_sha == "abc123"
    assert row.git_dirty is False
    assert row.trace_id == "trace-a"
    assert row.trace_sha256 == "trace-hash"
    assert row.config_sha256 == "config-hash"
    assert row.seed == 11
    assert row.policy == "continuum-baseline"
    assert row.runtime_mode == "vllm-metal-observability"
    assert row.scenario_id == "F1-candidates-2"


def test_build_runs_table_preserves_runtime_identity() -> None:
    row = build_runs_table((_raw_run(),))[0]

    assert row.backend == "example.module:build_backend"
    assert row.backend_revision == "backend-v1"
    assert row.model_name == "example/model"
    assert row.model_revision == "model-revision"
    assert row.tokenizer_name == "example/tokenizer"
    assert row.tokenizer_revision == "tokenizer-revision"
    assert row.platform == "test-platform"


def test_build_runs_table_preserves_counts_and_capabilities() -> None:
    row = build_runs_table((_raw_run(),))[0]

    assert row.event_count == 8
    assert row.forced_release_event_count == 2
    assert row.scenario_family_id is None
    assert row.observation_availability == {
        "forced_release": "available",
        "native_apc_hit_miss": "unavailable",
    }


def test_build_runs_table_rejects_duplicate_run_id() -> None:
    run = _raw_run()

    with pytest.raises(
        ArtifactValidationError,
        match="duplicate run_id: run-a",
    ):
        build_runs_table((run, run))


def test_build_runs_table_rejects_missing_required_provenance() -> None:
    run = _raw_run()
    manifest = dict(run.manifest)
    manifest.pop("trace_sha256")
    incomplete_run = replace(run, manifest=manifest)

    with pytest.raises(
        ArtifactValidationError,
        match="run.json trace_sha256 must be non-empty text",
    ):
        build_runs_table((incomplete_run,))


def test_build_runs_table_rejects_missing_capability_summary() -> None:
    run = _raw_run()
    manifest = dict(run.manifest)
    manifest.pop("observation_availability")
    incomplete_run = replace(run, manifest=manifest)

    with pytest.raises(
        ArtifactValidationError,
        match="run.json observation_availability must be an object",
    ):
        build_runs_table((incomplete_run,))


def test_build_runs_table_preserves_unavailable_capability_reason() -> None:
    run = _raw_run()
    manifest = dict(run.manifest)
    manifest["observation_availability"] = {
        "native_apc_hit_miss": {
            "status": "unavailable",
            "reason": "backend does not expose this observation",
        }
    }
    run_with_missing_capability = replace(
        run,
        manifest=manifest,
    )

    row = build_runs_table((run_with_missing_capability,))[0]

    assert row.observation_availability == {
        "native_apc_hit_miss": {
            "status": "unavailable",
            "reason": "backend does not expose this observation",
        }
    }
