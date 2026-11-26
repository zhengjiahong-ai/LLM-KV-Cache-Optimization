from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from kvopt.workload.phase5_campaign_plan import (
    balanced_latin_square,
    materialize_campaign_plan,
)
from kvopt.workload.phase5_formal_orchestrator import (
    FormalOrchestrationError,
    run_campaign_plan_cpu_contract,
)
from kvopt.workload.phase5_six_system_runner import (
    SYSTEM_IDS,
    SixSystemRunObservation,
)
from kvopt.workload.phase5_system_adapters import SystemAdapterBinding


def _digest(character: str) -> str:
    return character * 64


def _plan():
    groups = {"SWE_BENCH": [f"s{index}" for index in range(4)]}
    square = balanced_latin_square()
    orders = {}
    ordinal = 0
    for stratum, group_ids in groups.items():
        for group_id in group_ids:
            for repeat in range(1, 4):
                orders[f"{stratum}:{group_id}:r{repeat}"] = square[
                    ordinal % len(square)
                ]
                ordinal += 1
    all_groups = [group_id for values in groups.values() for group_id in values]
    return materialize_campaign_plan(
        phase="CALIBRATION",
        groups=groups,
        repeats=3,
        execution_orders=orders,
        workload_seal_sha256_by_group={row: _digest("a") for row in all_groups},
        arrival_sha256_by_group={row: _digest("b") for row in all_groups},
        protocol_sha256=_digest("c"),
    )


def _bindings(*, fail_system: str | None = None):
    def executor(spec):
        status = "FAIL_CLOSED" if spec.system_id == fail_system else "PASS"
        return SixSystemRunObservation(
            run_id=spec.run_id,
            status=status,
            process_identity=f"process:{spec.run_id}",
            engine_identity=f"engine:{spec.run_id}",
            process_was_new=True,
            engine_was_new=True,
            empty_cache_preflight_passed=True,
            preheat_performed=False,
            retry_count=0,
            actual_enqueue_sequence_sha256=spec.expected_enqueue_sequence_sha256,
            failure_reason=None if status == "PASS" else "injected failure",
        )

    return [
        SystemAdapterBinding(
            system_id=system_id,
            implementation_revision=f"revision:{system_id}",
            executor=executor,
            implementation_status="READY",
            cpu_correctness_status="PASS",
            native_compatibility_status="PASS",
            algorithm_frozen=True,
            native_execution_architecture="ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
        )
        for system_id in SYSTEM_IDS
    ]


def _enqueue_map(plan):
    return {row["group_id"]: _digest("d") for row in plan["runs"]}


def test_full_72_run_cpu_orchestration_contract_passes() -> None:
    plan = _plan()
    report = run_campaign_plan_cpu_contract(
        plan=plan,
        expected_enqueue_sequence_sha256_by_group=_enqueue_map(plan),
        bindings=_bindings(),
    )
    assert report["status"] == "CPU_CONTRACT_PASS"
    assert report["cell_count_evaluated"] == 12
    assert report["gpu_execution_authorized"] is False
    assert report["native_conformance_claim"] == "NOT_ESTABLISHED"
    assert report["formal_system_readiness"] == "READY"


def test_provisional_dva_cpu_integration_does_not_claim_formal_readiness() -> None:
    plan = _plan()
    bindings = _bindings()
    index = next(
        index
        for index, binding in enumerate(bindings)
        if binding.system_id == "DVA_ER_V1"
    )
    bindings[index] = replace(
        bindings[index],
        algorithm_frozen=False,
        native_compatibility_status="NOT_RUN",
    )
    report = run_campaign_plan_cpu_contract(
        plan=plan,
        expected_enqueue_sequence_sha256_by_group=_enqueue_map(plan),
        bindings=bindings,
    )
    assert report["status"] == "CPU_CONTRACT_PASS"
    assert report["formal_system_readiness"] == "BLOCKED"
    assert "not frozen" in report["formal_system_readiness_reason"]


def test_first_failed_run_stops_remaining_cells_without_retry() -> None:
    plan = _plan()
    report = run_campaign_plan_cpu_contract(
        plan=plan,
        expected_enqueue_sequence_sha256_by_group=_enqueue_map(plan),
        bindings=_bindings(fail_system="A1_ORIGINAL"),
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["cell_count_evaluated"] == 1


def test_plan_hash_and_enqueue_group_set_fail_closed() -> None:
    plan = _plan()
    changed = deepcopy(plan)
    changed["runs"][0]["group_id"] = "substituted"
    with pytest.raises(FormalOrchestrationError, match="SHA-256"):
        run_campaign_plan_cpu_contract(
            plan=changed,
            expected_enqueue_sequence_sha256_by_group=_enqueue_map(plan),
            bindings=_bindings(),
        )
    with pytest.raises(FormalOrchestrationError, match="enqueue identity set"):
        run_campaign_plan_cpu_contract(
            plan=plan,
            expected_enqueue_sequence_sha256_by_group={},
            bindings=_bindings(),
        )
