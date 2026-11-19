from __future__ import annotations

import asyncio
from pathlib import Path

from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle
from kvopt.workload.phase5_gpu_conformance import build_phase5e_review_candidate
from kvopt.workload.phase5_native_async import PressureExecutionEvidence
from kvopt.workload.phase5e_mock_runner import run_phase5e_part_a_mock_pipeline
from kvopt.workload.phase5e_part_a import PartARequestInput


class _Adapter:
    def __init__(self, plan) -> None:
        self.plan = plan
        self.inflight = []
        self.events = []
        self.index = 0
        self.closed = False

    def _event(self, request_id, kind):
        self.index += 1
        self.events.append(
            {"index": self.index, "request_id": request_id, "kind": kind}
        )

    async def submit(self, spec):
        self._event(spec.logical_request_id, "ADAPTER_DISPATCH_STARTED")
        self._event(spec.logical_request_id, "NATIVE_SUBMISSION_OBSERVED")
        self.inflight.append(spec.logical_request_id)
        return RequestHandle(
            spec.logical_request_id,
            f"native:{spec.logical_request_id}",
            spec.external_request_id,
            1.0,
        )

    async def collect_completed(self, **_kwargs):
        rows = []
        for request_id in tuple(self.inflight):
            self.inflight.remove(request_id)
            self._event(request_id, "NATIVE_TERMINAL_CONFIRMED")
            rows.append(
                RequestCompletion(
                    request_id,
                    f"native:{request_id}",
                    f"P5E-A-01:{request_id}",
                    10.0,
                )
            )
        return tuple(rows)

    async def execute_native_pressure(self, request, *, expected_inflight_request_ids):
        assert tuple(self.inflight) == expected_inflight_request_ids
        expected = self.plan.pressure.expected_allocated_blocks_by_request
        return PressureExecutionEvidence(
            boundary_id=request.boundary_id,
            native_snapshot_timestamp=5.0,
            inflight_request_ids=expected_inflight_request_ids,
            pressure_token_ids_sha256=request.pressure_token_ids_sha256,
            required_blocks=request.required_blocks,
            allocated_block_ids=tuple(range(request.required_blocks)),
            free_blocks_before=request.required_blocks,
            free_blocks_after_allocation=0,
            free_blocks_after_release=request.required_blocks,
            allocation_source="PINNED_BLOCK_POOL_GET_NEW_BLOCKS",
            engine_core_identity_verified=True,
            forced_release_decision_ids=("decision-1",),
            native_evicted_block_ids=(1,),
            allocation_watermark_source=(
                "PINNED_KV_CACHE_MANAGER_REQUEST_BLOCK_TABLE"
            ),
            observed_allocated_blocks_by_request=expected,
        )

    async def shutdown(self, **_kwargs):
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


def test_mock_execute_gate_archive_round_trip(tmp_path: Path) -> None:
    async def scenario():
        plan = build_phase5e_review_candidate("a" * 40)
        result = await run_phase5e_part_a_mock_pipeline(
            plan=plan,
            run_id="P5E-A-01",
            requests={
                request_id: PartARequestInput(
                    request_id, [1, 2], {"max_tokens": 64}
                )
                for request_id in plan.frozen_native_enqueue_order
            },
            adapter=_Adapter(plan),
            candidate_exposure_evaluator=lambda: {
                "status": "PASS",
                "downstream_recompute_attribution": "NOT_ESTABLISHED",
            },
            run_epoch_monotonic=0.0,
            monotonic=lambda: 10.0,
            sleep=lambda _delay: asyncio.sleep(0),
            output_root=tmp_path / "run",
            archive_path=tmp_path / "evidence.tar.gz",
        )
        assert result["status"] == "PASS"
        assert result["archive_validation"]["status"] == "PASS"
        assert result["gpu_conformance_claim"] == "NOT_ESTABLISHED"

    asyncio.run(scenario())


def test_mock_runner_is_exclusive(tmp_path: Path) -> None:
    async def scenario():
        plan = build_phase5e_review_candidate("a" * 40)
        output = tmp_path / "run"
        output.mkdir()
        try:
            await run_phase5e_part_a_mock_pipeline(
                plan=plan,
                run_id="P5E-A-01",
                requests={},
                adapter=_Adapter(plan),
                candidate_exposure_evaluator=dict,
                run_epoch_monotonic=0.0,
                monotonic=lambda: 10.0,
                sleep=lambda _delay: asyncio.sleep(0),
                output_root=output,
                archive_path=tmp_path / "evidence.tar.gz",
            )
        except FileExistsError:
            return
        raise AssertionError("existing output root was not rejected")

    asyncio.run(scenario())
