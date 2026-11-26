from __future__ import annotations

import pytest

from kvopt.workload.phase5e_native_evidence_source import (
    Phase5ENativeEvidenceError,
    RuntimeEventEvidenceSource,
    resolve_runtime_event_reader,
)


def _event(index, event_type, payload):
    return {"event_index": index, "event_type": event_type, "payload": payload}


def _pressure_rows() -> list[dict[str, object]]:
    return [
        _event(
            0,
            "PHASE5E_G9_ACTUAL_PRESSURE_BINDING",
            {"boundary_id": "boundary", "validation_status": "PASS"},
        ),
        _event(
            1,
            "FORCED_RELEASE_DECISION",
            {
                "decision_id": "decision",
                "frozen_decision_boundary_id": "boundary",
            },
        ),
        _event(
            2,
            "FORCED_RELEASE_DECISION_BINDING",
            {
                "boundary_id": "boundary",
                "decision_id": "decision",
                "forced_release_event_index": 1,
            },
        ),
        _event(
            3,
            "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
            {"decision_id": "decision", "frozen_decision_boundary_id": "boundary"},
        ),
        _event(
            4,
            "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
            {
                "decision_id": "decision",
                "frozen_decision_boundary_id": "boundary",
                "matched_physical_block_ids": [2],
            },
        ),
    ]


def test_pressure_requires_bound_plan_and_physical_outcome() -> None:
    rows = _pressure_rows()
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
    rows = _pressure_rows()
    rows[-1]["payload"]["matched_physical_block_ids"] = [9]
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="outside"):
        source.pressure_outcome("boundary", (1, 2, 3))


def test_pressure_rejects_event_index_pointing_to_wrong_event_type() -> None:
    rows = _pressure_rows()
    rows[2]["payload"]["forced_release_event_index"] = 0
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="does not reference"):
        source.pressure_outcome("boundary", (1, 2, 3))


def test_pressure_rejects_forced_decision_identity_mismatch() -> None:
    rows = _pressure_rows()
    rows[1]["payload"]["decision_id"] = "other"
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="identity differs"):
        source.pressure_outcome("boundary", (1, 2, 3))


def test_pressure_rejects_boundary_mismatch() -> None:
    rows = _pressure_rows()
    rows[1]["payload"]["frozen_decision_boundary_id"] = "other-boundary"
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="boundary differs"):
        source.pressure_outcome("boundary", (1, 2, 3))


@pytest.mark.parametrize("event_offset", [3, 4])
def test_pressure_rejects_plan_or_outcome_decision_mismatch(event_offset: int) -> None:
    rows = _pressure_rows()
    rows[event_offset]["payload"]["decision_id"] = "other"
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="lacks Selection Plan or Physical Outcome"):
        source.pressure_outcome("boundary", (1, 2, 3))


def test_pressure_rejects_out_of_order_physical_outcome() -> None:
    rows = _pressure_rows()
    rows[3], rows[4] = rows[4], rows[3]
    rows[3]["event_index"] = 3
    rows[4]["event_index"] = 4
    source = RuntimeEventEvidenceSource(run_id="P5E-A-01", event_reader=lambda: rows)
    with pytest.raises(Phase5ENativeEvidenceError, match="order is invalid"):
        source.pressure_outcome("boundary", (1, 2, 3))


def test_runtime_reader_requires_one_explicit_source() -> None:
    with pytest.raises(Phase5ENativeEvidenceError, match="exactly one"):
        resolve_runtime_event_reader(object())


def test_runtime_reader_rejects_unverified_source() -> None:
    source = type(
        "Source",
        (),
        {
            "snapshot": lambda self: (),
            "installation_report": lambda self: {
                "status": "PASS",
                "mode": "NATIVE",
                "same_engine_core": True,
            },
        },
    )()
    core = type("Core", (), {"kvopt_phase5_event_source": source})()
    delegate = type("Delegate", (), {"engine_core": core})()
    proxy = type("Proxy", (), {"_delegate": delegate})()
    engine = type("Engine", (), {"engine_core": proxy})()
    with pytest.raises(Phase5ENativeEvidenceError, match="not controlled A3"):
        resolve_runtime_event_reader(engine)
