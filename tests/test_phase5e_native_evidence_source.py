from __future__ import annotations

import pytest

from kvopt.workload.phase5e_native_evidence_source import (
    Phase5ENativeEvidenceError,
    RuntimeEventEvidenceSource,
    resolve_runtime_event_reader,
)


def _event(index, event_type, payload):
    return {"event_index": index, "event_type": event_type, "payload": payload}


def test_pressure_requires_bound_plan_and_physical_outcome() -> None:
    rows = [
        _event(
            0,
            "FORCED_RELEASE_DECISION_BINDING",
            {"boundary_id": "boundary", "decision_id": "decision"},
        ),
        _event(
            1,
            "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
            {"decision_id": "decision"},
        ),
        _event(
            2,
            "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
            {"decision_id": "decision", "matched_physical_block_ids": [2]},
        ),
    ]
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    assert source.pressure_outcome("boundary", (1, 2, 3)) == {
        "forced_release_decision_ids": ["decision"],
        "native_evicted_block_ids": [2],
    }


def test_pressure_never_infers_decision_from_allocation() -> None:
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: ())
    with pytest.raises(Phase5ENativeEvidenceError, match="no A3 Forced Decision"):
        source.pressure_outcome("boundary", (1, 2, 3))


def test_rejects_physical_victim_outside_pressure_allocation() -> None:
    rows = [
        _event(0, "FORCED_RELEASE_DECISION_BINDING", {"boundary_id": "b", "decision_id": "d"}),
        _event(1, "NATIVE_ENTRY_RELEASE_SELECTION_PLAN", {"decision_id": "d"}),
        _event(
            2,
            "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
            {"decision_id": "d", "matched_physical_block_ids": [9]},
        ),
    ]
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="outside"):
        source.pressure_outcome("b", (1, 2, 3))


def test_runtime_reader_requires_one_explicit_source() -> None:
    with pytest.raises(Phase5ENativeEvidenceError, match="exactly one"):
        resolve_runtime_event_reader(object())
