"""CPU orchestration contract for a frozen Phase 5 six-system plan."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from .phase5_replay import canonical_sha256
from .phase5_six_system_runner import (
    SYSTEM_IDS,
    SixSystemRunSpec,
    run_six_system_cell,
)
from .phase5_system_adapters import (
    SystemAdapterBinding,
    route_system_execution,
    validate_system_adapter_registry,
)


class FormalOrchestrationError(RuntimeError):
    """Raised when a frozen plan cannot be mapped to paired six-system cells."""


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise FormalOrchestrationError(f"run row has invalid {field}")
    return value


def _execution_position(row: Mapping[str, object]) -> int:
    value = row.get("execution_order_index")
    if isinstance(value, bool) or not isinstance(value, int):
        raise FormalOrchestrationError("execution_order_index must be an integer")
    return value


def validate_campaign_plan_identity(plan: Mapping[str, object]) -> None:
    """Validate immutable plan identity without granting execution authority."""

    payload = dict(plan)
    supplied_sha = payload.pop("plan_sha256", None)
    if supplied_sha != canonical_sha256(payload):
        raise FormalOrchestrationError("campaign plan SHA-256 binding is invalid")
    if payload.get("execution_authorized") is not False:
        raise FormalOrchestrationError(
            "engineering plan must remain execution_authorized=false"
        )
    if tuple(payload.get("systems", ())) != SYSTEM_IDS:
        raise FormalOrchestrationError("campaign plan system order is not frozen")
    rows = payload.get("runs")
    if not isinstance(rows, list) or payload.get("run_count") != len(rows):
        raise FormalOrchestrationError("campaign plan run matrix is incomplete")


def run_campaign_plan_cpu_contract(
    *,
    plan: Mapping[str, object],
    expected_enqueue_sequence_sha256_by_group: Mapping[str, str],
    bindings: Sequence[SystemAdapterBinding],
) -> dict[str, object]:
    """Exercise all paired cells in CPU/Mock mode; never authorize GPU execution."""

    validate_campaign_plan_identity(plan)
    registry = validate_system_adapter_registry(bindings)
    raw_rows = plan["runs"]
    assert isinstance(raw_rows, list)
    cells: dict[tuple[str, str, int], list[Mapping[str, object]]] = defaultdict(list)
    run_ids: set[str] = set()
    for value in raw_rows:
        if not isinstance(value, Mapping):
            raise FormalOrchestrationError("campaign run row must be an object")
        run_id = _text(value, "run_id")
        if run_id in run_ids:
            raise FormalOrchestrationError("campaign contains duplicate run_id")
        run_ids.add(run_id)
        repeat = value.get("repeat_index")
        if isinstance(repeat, bool) or not isinstance(repeat, int):
            raise FormalOrchestrationError("repeat_index must be an integer")
        cells[(_text(value, "stratum"), _text(value, "group_id"), repeat)].append(
            value
        )
    group_ids = {group_id for _, group_id, _ in cells}
    if set(expected_enqueue_sequence_sha256_by_group) != group_ids:
        raise FormalOrchestrationError(
            "expected enqueue identity set differs from campaign Groups"
        )

    cell_results = []
    for (stratum, group_id, repeat), rows in sorted(cells.items()):
        specs = [
            SixSystemRunSpec(
                run_id=_text(row, "run_id"),
                group_id=group_id,
                stratum=stratum,
                repeat_index=repeat,
                system_id=_text(row, "system_id"),
                execution_position=_execution_position(row),
                workload_seal_sha256=_text(row, "workload_seal_sha256"),
                arrival_realization_sha256=_text(
                    row, "arrival_realization_sha256"
                ),
                expected_enqueue_sequence_sha256=(
                    expected_enqueue_sequence_sha256_by_group[group_id]
                ),
            )
            for row in rows
        ]
        result = run_six_system_cell(
            specs,
            executor=lambda spec: route_system_execution(registry, spec),
        )
        cell_results.append(
            {
                "stratum": stratum,
                "group_id": group_id,
                "repeat_index": repeat,
                "status": result.status,
                "failure_reason": result.failure_reason,
                "run_ids": [row.run_id for row in result.observations],
            }
        )
        if result.status != "PASS":
            break

    status = (
        "CPU_CONTRACT_PASS"
        if len(cell_results) == len(cells)
        and all(row["status"] == "PASS" for row in cell_results)
        else "FAIL_CLOSED"
    )
    payload = {
        "schema_version": "phase5.formal_cpu_orchestration.v1",
        "status": status,
        "plan_sha256": plan["plan_sha256"],
        "cell_count_expected": len(cells),
        "cell_count_evaluated": len(cell_results),
        "cells": cell_results,
        "execution_mode": "CPU_MOCK",
        "gpu_execution_authorized": False,
        "native_conformance_claim": "NOT_ESTABLISHED",
    }
    return {**payload, "report_sha256": canonical_sha256(payload)}
