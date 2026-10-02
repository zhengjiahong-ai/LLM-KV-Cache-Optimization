from __future__ import annotations

from pathlib import Path

import pytest

from kvopt.profiling.datasets import build_decision_tables
from kvopt.profiling.ingestion import ArtifactValidationError, RawRunArtifacts


def _candidate(
    program_id: str,
    prefix_id: str,
    block_ids: list[int],
    *,
    prefill_reload_seconds: float,
) -> dict[str, object]:
    return {
        "program_id": program_id,
        "prefix_id": prefix_id,
        "retention_deadline_timestamp": 20.0,
        "waiting_followup": True,
        "block_ids": block_ids,
        "initially_reclaimable_block_ids": block_ids[:1],
        "next_tool_type": "search",
        "elapsed_since_ttl_decision_seconds": 2.0,
        "prefill_reload_seconds": prefill_reload_seconds,
        "eta": 1.0,
        "queue_delay_t_seconds": 0.25,
    }


def _raw_run_with_decision() -> RawRunArtifacts:
    decision_event = {
        "schema_version": "phase2.event.v1",
        "run_id": "run-a",
        "event_index": 7,
        "event_type": "FORCED_RELEASE_DECISION",
        "timestamp": 10.0,
        "clock_domain": "continuum_pressure",
        "source": "continuum.forced_release",
        "payload": {
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
                _candidate(
                    "agent-a",
                    "prefix-a",
                    [1, 2],
                    prefill_reload_seconds=0.1,
                ),
                _candidate(
                    "agent-b",
                    "prefix-b",
                    [3, 4, 5],
                    prefill_reload_seconds=0.2,
                ),
            ],
            "selected_releases": [
                {
                    "program_id": "agent-b",
                    "prefix_id": "prefix-b",
                    "newly_eligible_block_ids": [3],
                }
            ],
        },
    }

    return RawRunArtifacts(
        run_dir=Path("/artifacts/run-a"),
        run_id="run-a",
        manifest={
            "schema_version": "phase2.run.v1",
            "run_id": "run-a",
        },
        trace={
            "schema_version": "phase2.trace.v1",
            "trace_id": "trace-a",
        },
        replay=(),
        events=(decision_event,),
    )


def test_build_decision_tables_creates_one_decision_row() -> None:
    tables = build_decision_tables((_raw_run_with_decision(),))

    assert len(tables.decisions) == 1
    decision = tables.decisions[0]

    assert decision.run_id == "run-a"
    assert decision.decision_event_index == 7
    assert decision.source_event_index == 7
    assert decision.timestamp == 10.0
    assert decision.clock_domain == "continuum_pressure"
    assert decision.required_blocks == 2
    assert decision.candidate_count == 2
    assert decision.selected_release_count == 1
    assert decision.original_free_queue_count == 1
    assert decision.ordinary_expired_entry_count == 0


def test_build_decision_tables_creates_one_row_per_candidate() -> None:
    tables = build_decision_tables((_raw_run_with_decision(),))

    assert len(tables.candidates) == 2

    first = tables.candidates[0]
    assert first.run_id == "run-a"
    assert first.decision_event_index == 7
    assert first.program_id == "agent-a"
    assert first.prefix_id == "prefix-a"
    assert first.candidate_position == 0
    assert first.selected is False
    assert first.release_order is None
    assert first.block_ids == (1, 2)
    assert first.block_count == 2
    assert first.initially_reclaimable_block_ids == (1,)
    assert first.prefill_reload_seconds == 0.1

    second = tables.candidates[1]
    assert second.program_id == "agent-b"
    assert second.prefix_id == "prefix-b"
    assert second.candidate_position == 1
    assert second.selected is True
    assert second.release_order == 1
    assert second.block_ids == (3, 4, 5)
    assert second.block_count == 3
    assert second.initially_reclaimable_block_ids == (3,)
    assert second.prefill_reload_seconds == 0.2


def test_candidate_key_is_unique_within_decision() -> None:
    tables = build_decision_tables((_raw_run_with_decision(),))

    keys = {
        (
            row.run_id,
            row.decision_event_index,
            row.program_id,
            row.prefix_id,
        )
        for row in tables.candidates
    }

    assert len(keys) == len(tables.candidates)


def test_build_decision_tables_rejects_duplicate_candidate() -> None:
    run = _raw_run_with_decision()
    payload = run.events[0]["payload"]
    assert isinstance(payload, dict)
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidates[1] = dict(candidates[0])

    with pytest.raises(
        ArtifactValidationError,
        match="decision 7 contains duplicate candidate",
    ):
        build_decision_tables((run,))


def test_build_decision_tables_rejects_unknown_selected_release() -> None:
    run = _raw_run_with_decision()
    payload = run.events[0]["payload"]
    assert isinstance(payload, dict)
    releases = payload["selected_releases"]
    assert isinstance(releases, list)
    release = releases[0]
    assert isinstance(release, dict)
    release["program_id"] = "unknown-agent"

    with pytest.raises(
        ArtifactValidationError,
        match="decision 7 selected release is not a candidate",
    ):
        build_decision_tables((run,))


def test_build_decision_tables_rejects_foreign_reclaimable_block() -> None:
    run = _raw_run_with_decision()
    payload = run.events[0]["payload"]
    assert isinstance(payload, dict)
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    candidate["initially_reclaimable_block_ids"] = [999]

    with pytest.raises(
        ArtifactValidationError,
        match="reclaimable blocks must belong to candidate",
    ):
        build_decision_tables((run,))
