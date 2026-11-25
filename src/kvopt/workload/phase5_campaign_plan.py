"""Six-system Calibration/Formal run-matrix materialization contracts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from .phase5_calibration import SYSTEM_IDS
from .phase5_replay import canonical_sha256


def balanced_latin_square() -> tuple[tuple[str, ...], ...]:
    """Return the frozen six-system even-order balanced Latin square."""

    size = len(SYSTEM_IDS)
    first = [0]
    for index in range(1, size):
        first.append((index + 1) // 2 if index % 2 else size - index // 2)
    return tuple(
        tuple(SYSTEM_IDS[(value + shift) % size] for value in first)
        for shift in range(size)
    )


def _validate_groups(groups: Mapping[str, Sequence[str]], expected_per_stratum: int) -> None:
    if set(groups) != {"SWE_BENCH"}:
        raise ValueError("campaign Groups must cover the sole formal SWE stratum")
    all_groups: list[str] = []
    for stratum, identities in groups.items():
        if len(identities) != expected_per_stratum or len(set(identities)) != len(
            identities
        ):
            raise ValueError(f"{stratum} Group count or identity is invalid")
        if any(not isinstance(row, str) or not row for row in identities):
            raise ValueError("campaign Group identities must be non-empty strings")
        all_groups.extend(identities)
    if len(all_groups) != len(set(all_groups)):
        raise ValueError("campaign Group identities must be globally unique")


def _validate_orders(
    *,
    groups: Mapping[str, Sequence[str]],
    repeats: int,
    execution_orders: Mapping[str, Sequence[str]],
) -> None:
    expected_keys = {
        f"{stratum}:{group_id}:r{repeat_index}"
        for stratum, group_ids in groups.items()
        for group_id in group_ids
        for repeat_index in range(1, repeats + 1)
    }
    if set(execution_orders) != expected_keys:
        raise ValueError("execution-order key set differs from the run matrix")
    position_counts = {system: Counter() for system in SYSTEM_IDS}
    allowed_orders = set(balanced_latin_square())
    for key, order in execution_orders.items():
        if tuple(sorted(order)) != tuple(sorted(SYSTEM_IDS)):
            raise ValueError(f"execution order {key} is not a six-system permutation")
        if tuple(order) not in allowed_orders:
            raise ValueError(f"execution order {key} is not in the frozen Latin square")
        for position, system_id in enumerate(order):
            position_counts[system_id][position] += 1
    for system_id, counts in position_counts.items():
        if max(counts.values()) - min(counts.values()) > 1:
            raise ValueError(
                f"execution position is not balanced for {system_id}"
            )


def materialize_campaign_plan(
    *,
    phase: str,
    groups: Mapping[str, Sequence[str]],
    repeats: int,
    execution_orders: Mapping[str, Sequence[str]],
    workload_seal_sha256_by_group: Mapping[str, str],
    arrival_sha256_by_group: Mapping[str, str],
    protocol_sha256: str,
) -> dict[str, object]:
    """Materialize exact run identities without granting execution authority."""

    if phase not in {"CALIBRATION", "FORMAL"}:
        raise ValueError("campaign phase must be CALIBRATION or FORMAL")
    if phase == "CALIBRATION":
        if repeats != 3:
            raise ValueError("Calibration repeats must equal three")
        expected_groups = 4
    else:
        if repeats != 2:
            raise ValueError("Formal repeats must equal two")
        expected_groups = len(groups.get("SWE_BENCH", ()))
        if not 8 <= expected_groups <= 16:
            raise ValueError("Formal N must be an integer in 8..16")
    _validate_groups(groups, expected_groups)
    _validate_orders(
        groups=groups, repeats=repeats, execution_orders=execution_orders
    )
    group_ids = {row for rows in groups.values() for row in rows}
    if set(workload_seal_sha256_by_group) != group_ids:
        raise ValueError("workload Seal set differs from campaign Groups")
    if set(arrival_sha256_by_group) != group_ids:
        raise ValueError("arrival realization set differs from campaign Groups")
    runs: list[dict[str, object]] = []
    for stratum, stratum_groups in groups.items():
        for group_id in stratum_groups:
            for repeat_index in range(1, repeats + 1):
                key = f"{stratum}:{group_id}:r{repeat_index}"
                for position, system_id in enumerate(execution_orders[key]):
                    runs.append(
                        {
                            "run_id": (
                                f"phase5-{phase.lower()}-{stratum.lower()}-"
                                f"{group_id}-r{repeat_index}-{system_id.lower()}"
                            ),
                            "phase": phase,
                            "stratum": stratum,
                            "group_id": group_id,
                            "repeat_index": repeat_index,
                            "system_id": system_id,
                            "execution_order_index": position,
                            "workload_seal_sha256": workload_seal_sha256_by_group[
                                group_id
                            ],
                            "arrival_realization_sha256": arrival_sha256_by_group[
                                group_id
                            ],
                        }
                    )
    run_ids = [str(row["run_id"]) for row in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("campaign run IDs are not unique")
    payload = {
        "schema_version": "phase5.six_system_campaign_plan.v1",
        "phase": phase,
        "protocol_sha256": protocol_sha256,
        "systems": list(SYSTEM_IDS),
        "repeats": repeats,
        "groups_per_stratum": expected_groups,
        "run_count": len(runs),
        "runs": runs,
        "execution_authorized": False,
    }
    return {**payload, "plan_sha256": canonical_sha256(payload)}


def assert_calibration_formal_disjoint(
    calibration_plan: Mapping[str, object], formal_plan: Mapping[str, object]
) -> None:
    def group_ids(plan: Mapping[str, object]) -> set[str]:
        rows = plan.get("runs")
        if not isinstance(rows, list):
            raise TypeError("campaign plan lacks run rows")
        return {
            str(row["group_id"])
            for row in rows
            if isinstance(row, Mapping) and "group_id" in row
        }

    if group_ids(calibration_plan) & group_ids(formal_plan):
        raise ValueError("Calibration and Formal Groups must be disjoint")
