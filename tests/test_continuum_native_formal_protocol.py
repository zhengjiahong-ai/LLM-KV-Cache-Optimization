import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_native_formal_protocol import _validate_protocol


def _protocol() -> dict:
    tasks = [f"repo__task-{index}" for index in range(18)]
    return {
        "schema_version": "continuum.native_costaware_formal_protocol.v1",
        "native_policy_arms": ["A0", "A1", "A2"],
        "simple_rule_comparators": [
            "SUFFICIENT_FIRST_EARLIEST_DEADLINE",
            "SUFFICIENT_FIRST_MINIMUM_OVERSHOOT",
        ],
        "runtime_repeats": 2,
        "statistical_unit": "DISJOINT_TWO_TASK_WORKLOAD_GROUP",
        "planned_run_count": 108,
        "pressure_regimes": [{"id": "moderate"}, {"id": "deep"}],
        "workload_groups": [
            {"group_id": f"g{index}", "task_ids": tasks[index * 2 : index * 2 + 2]}
            for index in range(9)
        ],
        "formal_execution_authorized": False,
    }


def test_protocol_accepts_frozen_design() -> None:
    _validate_protocol(_protocol())


@pytest.mark.parametrize("field,value", [("runtime_repeats", 3), ("planned_run_count", 54)])
def test_protocol_rejects_design_drift(field: str, value: object) -> None:
    protocol = _protocol()
    protocol[field] = value
    with pytest.raises(ValueError):
        _validate_protocol(protocol)


def test_protocol_rejects_task_reuse_across_groups() -> None:
    protocol = _protocol()
    protocol["workload_groups"][1]["task_ids"][0] = protocol["workload_groups"][0][
        "task_ids"
    ][0]
    with pytest.raises(ValueError, match="18 unique tasks"):
        _validate_protocol(protocol)


def test_checked_in_protocol_remains_execution_locked() -> None:
    path = Path("configs/phase2/continuum-native-cost-aware-formal-protocol-v1.json")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    _validate_protocol(protocol)
    assert protocol["formal_execution_authorized"] is False
    assert all(value == "PENDING" for value in protocol["pre_execution_gates"].values())
