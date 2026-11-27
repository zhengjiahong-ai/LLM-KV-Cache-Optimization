from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from kvopt.workload.phase5_gpu_conformance import (
    NaturalFinishClass,
    Readiness,
    build_phase5e_review_candidate,
    classify_part_a_finish,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _plan():
    return build_phase5e_review_candidate("a" * 40)


def test_phase5e_candidate_freezes_fixture_seal_pressure_and_budget() -> None:
    plan = _plan()

    assert sum(len(row.request_ids) for row in plan.programs) == 8
    assert plan.frozen_native_enqueue_order[:4] == (
        "p1:r1",
        "p2:r1",
        "p3:r1",
        "p4:r1",
    )
    assert plan.pressure.expected_inflight_request_ids == (
        "p1:r2",
        "p2:r2",
        "p3:r2",
        "p4:r2",
    )
    assert plan.resource_budget.engine_max_num_seqs == 4
    assert plan.resource_budget.engine_max_num_batched_tokens == 8192
    assert plan.resource_budget.adapter_maximum_native_inflight == 4
    assert plan.pressure.required_blocks == 1536
    assert plan.resource_budget.kv_pool_blocks == 2048
    assert plan.resource_budget.reserved_null_blocks == 1
    assert plan.resource_budget.allocatable_kv_blocks == 2047
    assert plan.pressure.expected_free_blocks_before == 1535
    boundary = plan.pressure.to_native_boundary(
        plan.resource_budget.block_size_tokens
    )
    assert boundary.allocation_request.required_blocks == 1536
    assert len(boundary.allocation_request.pressure_token_ids) == 24576
    assert boundary.expected_inflight_request_ids == plan.pressure.expected_inflight_request_ids
    assert plan.execution_authorized is False
    assert plan.abort_readiness is Readiness.NOT_READY
    assert len(plan.sha256) == 64


def test_phase5e_requires_exactly_four_by_two_requests() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="exactly 4x2"):
        replace(plan, programs=plan.programs[:3])


def test_phase5e_rejects_order_not_derived_from_arrivals_and_ordinals() -> None:
    plan = _plan()
    wrong = list(plan.frozen_native_enqueue_order)
    wrong[0], wrong[1] = wrong[1], wrong[0]

    with pytest.raises(ValueError, match="independently derived"):
        replace(plan, frozen_native_enqueue_order=tuple(wrong))


def test_phase5e_rejects_missing_or_inconsistent_workload_seal() -> None:
    plan = _plan()
    changed = dict(plan.workload_seal)
    changed["workload_id"] = "tampered"

    with pytest.raises(ValueError, match="seal content hash mismatch"):
        replace(plan, workload_seal=changed)

    with pytest.raises(ValueError, match="workload seal hash mismatch"):
        replace(plan, workload_seal_sha256="0" * 64)


def test_phase5e_rejects_pressure_boundary_position_and_inflight_set() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="all eight submissions"):
        replace(
            plan,
            pressure=replace(
                plan.pressure,
                trigger_after_native_submission_request_id="p3:r2",
            ),
        )
    with pytest.raises(ValueError, match="inflight set"):
        replace(
            plan,
            pressure=replace(
                plan.pressure,
                expected_inflight_request_ids=("p1:r2", "p2:r2"),
            ),
        )


def test_phase5e_rejects_pressure_hash_and_non_pressure_budget() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="pressure input hash mismatch"):
        replace(plan, pressure_input_sha256="0" * 64)

    tiny_ids = tuple(range(16))
    pressure = replace(
        plan.pressure,
        pressure_prompt_token_ids=tiny_ids,
        pressure_prompt_token_ids_sha256=canonical_sha256(list(tiny_ids)),
        pressure_prompt_tokens=16,
        required_blocks=1,
    )
    with pytest.raises(ValueError, match="cannot create observable pressure"):
        replace(
            plan,
            pressure=pressure,
            pressure_input_sha256=canonical_sha256(asdict(pressure)),
        )

    unsafe_ids = tuple(20000 + index % 8192 for index in range(28800))
    unsafe = replace(
        plan.pressure,
        pressure_prompt_token_ids=unsafe_ids,
        pressure_prompt_token_ids_sha256=canonical_sha256(list(unsafe_ids)),
        pressure_prompt_tokens=28800,
        required_blocks=1800,
    )
    with pytest.raises(ValueError, match="exceeds the bounded reserve"):
        replace(
            plan,
            pressure=unsafe,
            pressure_input_sha256=canonical_sha256(asdict(unsafe)),
        )


def test_phase5e_rejects_engine_adapter_capacity_mismatch() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="Adapter capacity"):
        replace(
            plan,
            resource_budget=replace(
                plan.resource_budget,
                adapter_maximum_native_inflight=3,
            ),
        )


def test_phase5e_abort_readiness_cannot_be_enabled_by_string() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="must remain NOT_READY"):
        replace(
            plan,
            abort_readiness=Readiness.READY_FOR_AUTHORIZATION_REVIEW,
        )


@pytest.mark.parametrize(
    ("reason", "stop_string", "error", "expected"),
    [
        ("eos", False, False, NaturalFinishClass.EOS_OR_STOP_TOKEN),
        ("stop", False, False, NaturalFinishClass.EOS_OR_STOP_TOKEN),
        ("length", False, False, NaturalFinishClass.LENGTH),
        ("stop", True, False, NaturalFinishClass.ABORT),
        ("abort", False, False, NaturalFinishClass.ABORT),
        ("length", False, True, NaturalFinishClass.ERROR),
        ("unknown", False, False, NaturalFinishClass.ERROR),
    ],
)
def test_phase5e_natural_finish_classification(
    reason: str,
    stop_string: bool,
    error: bool,
    expected: NaturalFinishClass,
) -> None:
    assert (
        classify_part_a_finish(
            finish_reason=reason,
            stop_string_triggered=stop_string,
            error_present=error,
        )
        is expected
    )


def test_phase5e_cannot_self_authorize_execution() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="must not authorize"):
        replace(plan, execution_authorized=True)
