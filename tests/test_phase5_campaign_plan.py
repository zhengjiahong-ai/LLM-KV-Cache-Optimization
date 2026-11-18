from __future__ import annotations

import hashlib

import pytest

from kvopt.workload.phase5_calibration import SYSTEM_IDS
from kvopt.workload.phase5_campaign_plan import (
    assert_calibration_formal_disjoint,
    balanced_latin_square,
    materialize_campaign_plan,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _groups(prefix: str, count: int):
    return {
        "SWE_BENCH": [f"{prefix}-swe-{i}" for i in range(count)],
        "BFCL_WEB_SEARCH": [f"{prefix}-bfcl-{i}" for i in range(count)],
    }


def _orders(groups, repeats):
    result = {}
    square = balanced_latin_square()
    ordinal = 0
    for stratum, rows in groups.items():
        for group_id in rows:
            for repeat in range(1, repeats + 1):
                result[f"{stratum}:{group_id}:r{repeat}"] = square[
                    ordinal % len(square)
                ]
                ordinal += 1
    return result


def _plan(phase: str, prefix: str, count: int, repeats: int):
    groups = _groups(prefix, count)
    all_groups = [row for rows in groups.values() for row in rows]
    return materialize_campaign_plan(
        phase=phase,
        groups=groups,
        repeats=repeats,
        execution_orders=_orders(groups, repeats),
        workload_seal_sha256_by_group={row: _sha(f"seal:{row}") for row in all_groups},
        arrival_sha256_by_group={row: _sha(f"arrival:{row}") for row in all_groups},
        protocol_sha256=_sha("protocol"),
    )


def test_materializes_exact_144_calibration_runs() -> None:
    plan = _plan("CALIBRATION", "cal", 4, 3)
    assert plan["run_count"] == 144
    assert plan["execution_authorized"] is False
    assert {row["system_id"] for row in plan["runs"]} == set(SYSTEM_IDS)


@pytest.mark.parametrize(("groups", "runs"), [(8, 192), (12, 288), (16, 384)])
def test_materializes_formal_bounds(groups: int, runs: int) -> None:
    assert _plan("FORMAL", "formal", groups, 2)["run_count"] == runs


def test_rejects_unbalanced_or_incomplete_six_system_order() -> None:
    groups = _groups("cal", 4)
    orders = _orders(groups, 3)
    first = next(iter(orders))
    orders[first] = SYSTEM_IDS[:-1]
    all_groups = [row for rows in groups.values() for row in rows]
    with pytest.raises(ValueError, match="six-system permutation"):
        materialize_campaign_plan(
            phase="CALIBRATION",
            groups=groups,
            repeats=3,
            execution_orders=orders,
            workload_seal_sha256_by_group={row: _sha(row) for row in all_groups},
            arrival_sha256_by_group={row: _sha(f"a:{row}") for row in all_groups},
            protocol_sha256=_sha("protocol"),
        )


def test_calibration_and_formal_groups_are_disjoint() -> None:
    calibration = _plan("CALIBRATION", "cal", 4, 3)
    formal = _plan("FORMAL", "formal", 8, 2)
    assert_calibration_formal_disjoint(calibration, formal)
    formal["runs"][0]["group_id"] = calibration["runs"][0]["group_id"]
    with pytest.raises(ValueError, match="disjoint"):
        assert_calibration_formal_disjoint(calibration, formal)
