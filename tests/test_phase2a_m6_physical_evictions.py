from __future__ import annotations

from pathlib import Path

from kvopt.profiling.datasets import build_physical_evictions_table
from kvopt.profiling.ingestion import RawRunArtifacts


def _event(
    event_index: int,
    event_type: str,
    *,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "phase2.event.v1",
        "run_id": "run-a",
        "event_index": event_index,
        "event_type": event_type,
        "timestamp": float(event_index),
        "clock_domain": "continuum_lifecycle",
        "source": "continuum.lifecycle",
        "payload": payload,
    }


def _raw_run(*events: dict[str, object]) -> RawRunArtifacts:
    return RawRunArtifacts(
        run_dir=Path("/artifacts/run-a"),
        run_id="run-a",
        manifest={"run_id": "run-a"},
        trace={"trace_id": "trace-a"},
        replay=(),
        events=events,
    )


def test_physical_eviction_preserves_raw_event_and_prior_decision() -> None:
    run = _raw_run(
        _event(7, "FORCED_RELEASE_DECISION", payload={}),
        _event(8, "BLOCK_EVICTED", payload={"block_id": 3}),
    )

    rows = build_physical_evictions_table((run,))

    assert len(rows) == 1
    row = rows[0]
    assert row.run_id == "run-a"
    assert row.eviction_event_index == 8
    assert row.source_event_index == 8
    assert row.block_id == 3
    assert row.preceding_decision_event_index == 7
    assert row.native_hash_hex is None
    assert row.identity_kind == "block_slot_only"


def test_physical_eviction_before_any_decision_remains_unattributed() -> None:
    run = _raw_run(
        _event(2, "BLOCK_EVICTED", payload={"block_id": 4}),
    )

    row = build_physical_evictions_table((run,))[0]

    assert row.preceding_decision_event_index is None


def test_reused_block_slot_produces_distinct_eviction_rows() -> None:
    run = _raw_run(
        _event(7, "FORCED_RELEASE_DECISION", payload={}),
        _event(8, "BLOCK_EVICTED", payload={"block_id": 3}),
        _event(11, "BLOCKS_OBSERVED", payload={"block_ids": [3]}),
        _event(
            12,
            "BLOCK_EVICTED",
            payload={"block_id": 3, "native_hash_hex": "aabb"},
        ),
    )

    rows = build_physical_evictions_table((run,))

    assert [row.eviction_event_index for row in rows] == [8, 12]
    assert [row.block_id for row in rows] == [3, 3]
    assert rows[0].identity_kind == "block_slot_only"
    assert rows[1].identity_kind == "native_hash"
    assert rows[1].native_hash_hex == "aabb"
