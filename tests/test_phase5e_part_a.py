from __future__ import annotations

import asyncio

from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_gpu_conformance import build_phase5e_review_candidate
from kvopt.workload.phase5_native_async import PressureExecutionEvidence
from kvopt.workload.phase5e_part_a import (
    PartARequestInput,
    evaluate_part_a_prearchive_gates,
    execute_phase5e_part_a,
)


def _pressure(plan) -> PressureExecutionEvidence:
    return PressureExecutionEvidence(
        boundary_id=plan.pressure.boundary_id,
        native_snapshot_timestamp=20.0,
        inflight_request_ids=plan.pressure.expected_inflight_request_ids,
        pressure_token_ids_sha256=plan.pressure.pressure_prompt_token_ids_sha256,
        required_blocks=1536,
        allocated_block_ids=tuple(range(1536)),
        free_blocks_before=1536,
        free_blocks_after_allocation=0,
        free_blocks_after_release=1536,
        allocation_source="PINNED_BLOCK_POOL_GET_NEW_BLOCKS",
        engine_core_identity_verified=True,
        forced_release_decision_ids=("decision-1",),
        native_evicted_block_ids=(1,),
    )


def _adapter_report(plan, *, closed: bool = True):
    events = []
    index = 1
    for ordinal, request_id in enumerate(plan.frozen_native_enqueue_order):
        events.append(
            {
                "index": index,
                "request_id": request_id,
                "kind": "ADAPTER_DISPATCH_STARTED",
                "timestamp": float(ordinal),
            }
        )
        index += 1
        events.append(
            {
                "index": index,
                "request_id": request_id,
                "kind": "NATIVE_SUBMISSION_OBSERVED",
                "timestamp": 10.0 + ordinal,
            }
        )
        index += 1
    for ordinal, request_id in enumerate(plan.frozen_native_enqueue_order):
        events.append(
            {
                "index": index,
                "request_id": request_id,
                "kind": "NATIVE_TERMINAL_CONFIRMED",
                "timestamp": 30.0 + ordinal,
            }
        )
        index += 1
    return {
        "state": "CLOSED" if closed else "OPEN",
        "request_state_observability": "OBSERVABLE",
        "active_submit_count": 0,
        "fatal_error": None,
        "events": events,
        "requests": [
            {
                "logical_request_id": request_id,
                "output_processor_terminal": True,
                "native_terminal_confirmed": True,
                "native_terminal_kind": "NATURAL_CORE_TERMINAL",
                "abort_dispatched": False,
                "failure_reason": None,
                "collector_task_done": True,
            }
            for request_id in plan.frozen_native_enqueue_order
        ],
    }


def _exposure():
    return {
        "status": "PASS",
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
    }


def test_part_a_prearchive_gates_pass_without_claiming_algorithmic_benefit() -> None:
    plan = build_phase5e_review_candidate("a" * 40)
    report = evaluate_part_a_prearchive_gates(
        plan=plan,
        run_id="P5E-A-01",
        controller_submission_order=plan.frozen_native_enqueue_order,
        peak_controller_inflight=4,
        pressure=_pressure(plan),
        adapter_report=_adapter_report(plan),
        candidate_exposure_report=_exposure(),
    )

    assert report["status"] == "PASS"
    assert report["gates"]["P5E-G3"]["gpu_kernel_overlap_claim"] == "NOT_CLAIMED"
    assert report["gates"]["P5E-G6"]["algorithmic_benefit_claim"] == "NOT_ESTABLISHED"
    assert report["gates"]["P5E-G8"]["status"] == "EXTERNAL_ARCHIVE_GATE_REQUIRED"


def test_part_a_gates_fail_closed_on_order_lifecycle_or_cleanup_drift() -> None:
    plan = build_phase5e_review_candidate("a" * 40)
    wrong_order = tuple(reversed(plan.frozen_native_enqueue_order))
    report = evaluate_part_a_prearchive_gates(
        plan=plan,
        run_id="P5E-A-01",
        controller_submission_order=wrong_order,
        peak_controller_inflight=4,
        pressure=_pressure(plan),
        adapter_report=_adapter_report(plan, closed=False),
        candidate_exposure_report=_exposure(),
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["gates"]["P5E-G1"]["status"] == "FAIL_CLOSED"
    assert report["gates"]["P5E-G7"]["status"] == "FAIL_CLOSED"


class _Adapter:
    def __init__(self, plan) -> None:
        self.plan = plan
        self.inflight: list[str] = []
        self.events = []
        self.closed = False
        self.index = 0

    def _event(self, request_id: str, kind: str, timestamp: float) -> None:
        self.index += 1
        self.events.append(
            {
                "index": self.index,
                "request_id": request_id,
                "kind": kind,
                "timestamp": timestamp,
            }
        )

    async def submit(self, spec):
        request_id = spec.logical_request_id
        self._event(request_id, "ADAPTER_DISPATCH_STARTED", 1.0 + self.index)
        self._event(request_id, "NATIVE_SUBMISSION_OBSERVED", 2.0 + self.index)
        self.inflight.append(request_id)
        return RequestHandle(request_id, f"native:{request_id}", spec.external_request_id, 1.0)

    async def collect_completed(self, *, timeout_seconds, wait_for_one):
        del timeout_seconds, wait_for_one
        rows = []
        for request_id in tuple(self.inflight):
            self.inflight.remove(request_id)
            self._event(request_id, "NATIVE_TERMINAL_CONFIRMED", 100.0 + self.index)
            rows.append(
                RequestCompletion(
                    request_id,
                    f"native:{request_id}",
                    f"P5E-A-01:{request_id}",
                    100.0,
                )
            )
        return tuple(rows)

    async def execute_native_pressure(self, request, *, expected_inflight_request_ids):
        assert tuple(self.inflight) == expected_inflight_request_ids
        return _pressure(self.plan)

    async def shutdown(self, **kwargs):
        assert kwargs == {
            "require_native_confirmation": True,
            "require_frontend_observability": True,
        }
        self.closed = True

    def report(self):
        return {
            "state": "CLOSED" if self.closed else "OPEN",
            "request_state_observability": "OBSERVABLE",
            "active_submit_count": 0,
            "fatal_error": None,
            "events": self.events,
            "requests": [
                {
                    "logical_request_id": request_id,
                    "output_processor_terminal": True,
                    "native_terminal_confirmed": True,
                    "native_terminal_kind": "NATURAL_CORE_TERMINAL",
                    "abort_dispatched": False,
                    "failure_reason": None,
                    "collector_task_done": True,
                }
                for request_id in self.plan.frozen_native_enqueue_order
            ],
        }


def test_part_a_controller_executes_two_waves_and_one_pressure_boundary() -> None:
    async def scenario() -> None:
        plan = build_phase5e_review_candidate("a" * 40)
        adapter = _Adapter(plan)
        inputs = {
            request_id: PartARequestInput(request_id, [1, 2], {"max_tokens": 64})
            for request_id in plan.frozen_native_enqueue_order
        }
        result = await execute_phase5e_part_a(
            plan=plan,
            run_id="P5E-A-01",
            requests=inputs,
            adapter=adapter,
            candidate_exposure_evaluator=_exposure,
            run_epoch_monotonic=0.0,
            monotonic=lambda: 10.0,
        )
        assert result.status == "PASS"
        assert result.controller_submission_order == plan.frozen_native_enqueue_order
        assert result.peak_controller_inflight == 4
        assert result.pressure.boundary_id == "phase5e-pressure-01"

    asyncio.run(scenario())
