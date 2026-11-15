from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.profiling.phase5_native_evidence import evaluate_phase5_native_evidence


def _events() -> list[dict[str, object]]:
    return [
        {
            "event_index": 1,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "boundary_id": "pressure:b1",
                "candidates": [
                    {
                        "program_id": "p1",
                        "block_ids": [1],
                        "initially_reclaimable_block_ids": [1],
                        "native_hash_process_id": "proc",
                        "score": 1.0,
                    }
                ],
                "selected_releases": [{"program_id": "p1"}],
            },
        },
        {
            "event_index": 2,
            "event_type": "FORCED_RELEASE_DECISION_BINDING",
            "payload": {
                "forced_release_event_index": 1,
                "decision_id": "d1",
                "boundary_id": "pressure:b1",
                "execution_context": "PHASE5_PRESSURE",
            },
        },
        {
            "event_index": 3,
            "event_type": "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
            "payload": {"decision_id": "d1", "selected_native_block_ids": [1]},
        },
        {
            "event_index": 4,
            "event_type": "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
            "payload": {
                "decision_id": "d1",
                "matched_physical_block_ids": [1],
                "unmatched_physical_block_ids": [],
                "hashless_physical_block_ids": [],
            },
        },
    ]


def _execution() -> dict[str, object]:
    return {
        "status": "PASS",
        "pressure_boundary_ids": ["pressure:b1"],
        "enqueue_gate": {"status": "PASS"},
    }


def test_native_evidence_joins_decision_to_executed_pressure() -> None:
    report = evaluate_phase5_native_evidence(
        run_id="run", arm="A3", events=_events(), execution_report=_execution()
    )
    assert report["status"] == "PASS"
    assert report["candidate_exposure"]["decision_count"] == 1
    assert report["physical_causal_attribution"] == "NOT_ESTABLISHED"


def test_native_evidence_rejects_unknown_boundary_and_block() -> None:
    execution = _execution()
    execution["pressure_boundary_ids"] = ["pressure:other"]
    with pytest.raises(ValueError, match="executed pressure boundary"):
        evaluate_phase5_native_evidence(
            run_id="run", arm="A3", events=_events(), execution_report=execution
        )

    events = deepcopy(_events())
    events[3]["payload"]["matched_physical_block_ids"] = [99]
    with pytest.raises(ValueError, match="outside the selection plan"):
        evaluate_phase5_native_evidence(
            run_id="run", arm="A3", events=events, execution_report=_execution()
        )


def test_native_evidence_rejects_overlapping_physical_sets() -> None:
    events = deepcopy(_events())
    events[3]["payload"]["unmatched_physical_block_ids"] = [1]
    with pytest.raises(ValueError, match="must be disjoint"):
        evaluate_phase5_native_evidence(
            run_id="run", arm="A3", events=events, execution_report=_execution()
        )
