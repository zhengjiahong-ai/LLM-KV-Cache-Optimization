from __future__ import annotations

import pytest

from kvopt.workload.phase5_vllm_api import (
    NativeArrivalTimingLedger,
    ProcessedRequestOutput,
    VLLMOutputProcessorPump,
)


def _ledger(*request_ids: str) -> NativeArrivalTimingLedger:
    ledger = NativeArrivalTimingLedger(run_epoch_native_monotonic=100.0)
    for index, request_id in enumerate(request_ids):
        ledger.add_planned_request(request_id, planned_offset_seconds=float(index))
        ledger.dispatch_started(request_id, timestamp=100.0 + index + 0.1)
        ledger.dispatch_returned(request_id, timestamp=100.0 + index + 0.2)
    return ledger


def _pump(*request_ids: str):
    ledger = _ledger(*request_ids)
    pump = VLLMOutputProcessorPump(timing=ledger)
    pump.bind_output_owner("output-handler")
    for request_id in request_ids:
        pump.register_request(
            logical_request_id=request_id,
            native_request_id=f"native:{request_id}",
            external_request_id=f"external:{request_id}",
        )
    return ledger, pump


def _output(request_id: str, *, finished: bool, timestamp: float = 200.0):
    return ProcessedRequestOutput(
        logical_request_id=request_id,
        external_request_id=f"external:{request_id}",
        finished=finished,
        engine_core_batch_timestamp=timestamp,
    )


def test_partial_output_does_not_release_inflight_capacity() -> None:
    ledger, pump = _pump("r1")
    pump.process_output_batch(
        owner_id="output-handler",
        outputs=(_output("r1", finished=False),),
        adapter_receive_timestamp=101.0,
    )
    assert pump.collect_completed(timeout_seconds=0, wait_for_one=False) == ()
    assert pump.state_report()["outstanding_request_ids"] == ["r1"]
    assert ledger.report()["requests"][0]["partial_output_count"] == 1


def test_output_processor_terminal_is_incrementally_collectable() -> None:
    ledger, pump = _pump("r1", "r2")
    pump.process_output_batch(
        owner_id="output-handler",
        outputs=(_output("r2", finished=True),),
        adapter_receive_timestamp=103.0,
    )
    rows = pump.collect_completed(timeout_seconds=0, wait_for_one=False)
    assert [row.logical_request_id for row in rows] == ["r2"]
    assert pump.state_report()["outstanding_request_ids"] == ["r1"]
    timing = {row["request_id"]: row for row in ledger.report()["requests"]}
    assert timing["r2"]["state"] == "TERMINAL"
    assert timing["r1"]["state"] == "CLIENT_DISPATCHED"


def test_same_batch_terminals_share_observation_time_without_fake_order() -> None:
    ledger, pump = _pump("r1", "r2")
    pump.process_output_batch(
        owner_id="output-handler",
        outputs=(
            _output("r1", finished=True, timestamp=500.0),
            _output("r2", finished=True, timestamp=500.0),
        ),
        adapter_receive_timestamp=103.0,
    )
    rows = pump.collect_completed(timeout_seconds=0, wait_for_one=False)
    assert len(rows) == 2
    assert {row.completed_at for row in rows} == {103.0}
    report = ledger.report()
    assert {
        row["engine_core_batch_timestamps"][0] for row in report["requests"]
    } == {500.0}


def test_output_pump_rejects_second_owner_unknown_and_duplicate_output() -> None:
    _ledger_row, pump = _pump("r1")
    with pytest.raises(RuntimeError, match="already has an owner"):
        pump.bind_output_owner("second")
    with pytest.raises(RuntimeError, match="bound owner"):
        pump.process_output_batch(
            owner_id="second",
            outputs=(_output("r1", finished=False),),
            adapter_receive_timestamp=101.0,
        )
    with pytest.raises(KeyError, match="unknown request"):
        pump.process_output_batch(
            owner_id="output-handler",
            outputs=(_output("unknown", finished=False),),
            adapter_receive_timestamp=101.0,
        )
    with pytest.raises(ValueError, match="duplicate request IDs"):
        pump.process_output_batch(
            owner_id="output-handler",
            outputs=(
                _output("r1", finished=False),
                _output("r1", finished=False),
            ),
            adapter_receive_timestamp=101.0,
        )


def test_dispatch_registration_can_be_rolled_back_after_send_failure() -> None:
    ledger = NativeArrivalTimingLedger(run_epoch_native_monotonic=100.0)
    ledger.add_planned_request("r1", planned_offset_seconds=0.0)
    ledger.dispatch_started("r1", timestamp=100.1)
    pump = VLLMOutputProcessorPump(timing=ledger)
    pump.bind_output_owner("owner")
    pump.register_request(
        logical_request_id="r1",
        native_request_id="native:r1",
        external_request_id="external:r1",
    )
    pump.rollback_registration("r1")
    ledger.dispatch_failed("r1")
    assert pump.state_report()["outstanding_request_ids"] == []
    assert ledger.report()["requests"][0]["state"] == "DISPATCH_FAILED"


def test_pump_failure_fails_every_outstanding_request_once() -> None:
    _ledger_row, pump = _pump("r1", "r2")
    pump.fail_pump(RuntimeError("engine died"), timestamp=104.0)
    rows = pump.collect_completed(timeout_seconds=0, wait_for_one=False)
    assert {row.logical_request_id for row in rows} == {"r1", "r2"}
    assert {row.status for row in rows} == {"failed"}
    assert all("OUTPUT_PUMP_FAILED" in str(row.failure_reason) for row in rows)
    with pytest.raises(RuntimeError, match="twice"):
        pump.fail_pump(RuntimeError("again"), timestamp=105.0)


def test_arrival_timing_keeps_clock_domains_and_landmarks_separate() -> None:
    ledger = NativeArrivalTimingLedger(run_epoch_native_monotonic=100.0)
    ledger.add_planned_request("r1", planned_offset_seconds=2.0)
    ledger.dispatch_started("r1", timestamp=102.25)
    ledger.dispatch_returned("r1", timestamp=102.30)
    ledger.scheduler_observed(
        "r1",
        queued_engine_monotonic=700.0,
        scheduled_engine_monotonic=700.5,
    )
    ledger.processed_output_observed(
        "r1",
        adapter_timestamp=103.0,
        engine_core_batch_timestamp=701.0,
        finished=True,
    )
    report = ledger.report()
    row = report["requests"][0]
    assert row["arrival_lateness_seconds"] == pytest.approx(0.25)
    assert row["client_dispatch_duration_seconds"] == pytest.approx(0.05)
    assert row["native_queued_engine_monotonic"] == 700.0
    assert report["clock_contract"]["cross_domain_subtraction"] == "PROHIBITED"


def test_arrival_timing_rejects_early_dispatch_and_partial_after_terminal() -> None:
    ledger = NativeArrivalTimingLedger(run_epoch_native_monotonic=100.0)
    ledger.add_planned_request("r1", planned_offset_seconds=2.0)
    with pytest.raises(ValueError, match="before the frozen arrival"):
        ledger.dispatch_started("r1", timestamp=101.9)

    ledger.dispatch_started("r1", timestamp=102.0)
    ledger.dispatch_returned("r1", timestamp=102.1)
    ledger.processed_output_observed(
        "r1",
        adapter_timestamp=103.0,
        engine_core_batch_timestamp=500.0,
        finished=True,
    )
    with pytest.raises(RuntimeError, match="invalid predecessor"):
        ledger.processed_output_observed(
            "r1",
            adapter_timestamp=104.0,
            engine_core_batch_timestamp=501.0,
            finished=False,
        )
