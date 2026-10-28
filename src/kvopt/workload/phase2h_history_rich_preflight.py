"""Materialize the frozen Phase 2H execution preflight without using a GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .phase2h_history_rich_proposal import materialize_history_rich_mock_timeline

SCENARIOS = {
    "hr01-balanced-gap": {
        "tasks": (
            "django__django-13023",
            "sympy__sympy-15017",
            "mwaskom__seaborn-3069",
        ),
        "pressure_tokens": 12_256,
        "target_shortage_blocks": 32,
    },
    "hr02-short-gap-long-context": {
        "tasks": (
            "pylint-dev__pylint-6386",
            "pytest-dev__pytest-7982",
            "pydata__xarray-3993",
        ),
        "pressure_tokens": 6_064,
        "target_shortage_blocks": 128,
    },
}
ARMS = ("A0", "A1", "A2")
PRESSURE_ROUNDS = (40, 50, 55)
BLOCK_SIZE = 16
CAPACITY_BLOCKS = 2048


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _canonical_sha(value: object) -> str:
    return _sha_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _pressure_token_ids(seed: str, token_count: int) -> tuple[int, ...]:
    values: list[int] = []
    counter = 0
    while len(values) < token_count:
        digest = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        for offset in range(0, len(digest), 4):
            values.append(100 + int.from_bytes(digest[offset : offset + 4], "big") % 99_900)
            if len(values) == token_count:
                break
        counter += 1
    return tuple(values)


def _chain_blocks(token_ids: list[int]) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(token_ids[offset : offset + BLOCK_SIZE])
        for offset in range(0, len(token_ids) // BLOCK_SIZE * BLOCK_SIZE, BLOCK_SIZE)
    )


def _unique_chain_nodes(chains: list[tuple[tuple[int, ...], ...]]) -> int:
    nodes: set[tuple[tuple[int, ...], ...]] = set()
    for chain in chains:
        for depth in range(1, len(chain) + 1):
            nodes.add(chain[:depth])
    return len(nodes)


def _load_calls(source_root: Path, task: str) -> tuple[dict[str, Any], ...]:
    path = source_root / task / "acquisition-sidecar.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    calls = tuple(row for row in value["model_calls"] if row.get("status") == "SUCCESS")
    if len(calls) < 60:
        raise ValueError(f"{task} lacks 60 successful calls")
    selected = calls[:60]
    if any(not isinstance(row.get("submitted_token_ids"), list) for row in selected):
        raise ValueError(f"{task} lacks explicit token IDs")
    return selected


def build_preflight(source_root: Path) -> dict[str, object]:
    scenarios: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    for scenario_id, spec in SCENARIOS.items():
        tasks = tuple(spec["tasks"])
        sessions = tuple(_load_calls(source_root, task) for task in tasks)
        timeline = materialize_history_rich_mock_timeline(
            sessions=sessions,
            pressure_after_rounds=PRESSURE_ROUNDS,
        )
        boundary_payload = [
            {
                "boundary_id": row.boundary_id,
                "logical_timestamp": row.logical_timestamp,
                "kind": row.kind.value,
                "session_index": row.session_index,
                "round_index": row.round_index,
                "request_id": row.request_id,
                "source": row.source,
            }
            for row in timeline.boundaries
        ]
        timeline_sha = _canonical_sha(boundary_payload)
        pressure_rows = []
        for round_index in PRESSURE_ROUNDS:
            seed = f"phase2h:{scenario_id}:after-round-{round_index}:pressure-v1"
            token_ids = _pressure_token_ids(seed, int(spec["pressure_tokens"]))
            pressure_rows.append(
                {
                    "round_index": round_index,
                    "boundary_id": f"pressure:after-round-{round_index}",
                    "content_seed": seed,
                    "token_count": len(token_ids),
                    "block_count": len(token_ids) // BLOCK_SIZE,
                    "token_ids_sha256": _canonical_sha(token_ids),
                }
            )
        pressure_sha = _canonical_sha(pressure_rows)
        capacity_rows = []
        for round_index in (*PRESSURE_ROUNDS, 60):
            chains = [
                _chain_blocks(session[round_index - 1]["submitted_token_ids"])
                for session in sessions
            ]
            joint = sum(len(chain) for chain in chains)
            unique = _unique_chain_nodes(chains)
            pressure_blocks = int(spec["pressure_tokens"]) // BLOCK_SIZE
            capacity_rows.append(
                {
                    "round_index": round_index,
                    "session_prefix_blocks": [len(chain) for chain in chains],
                    "joint_blocks_before_sharing": joint,
                    "shared_prefix_saving_blocks": joint - unique,
                    "unique_chain_blocks": unique,
                    "capacity_margin_blocks": CAPACITY_BLOCKS - unique,
                    "fixed_pressure_blocks": pressure_blocks,
                    "nominal_shortage_without_prior_eviction_blocks": max(
                        0, unique + pressure_blocks - CAPACITY_BLOCKS
                    ),
                    "largest_single_request_fits": max(
                        len(chain) for chain in chains
                    ) <= CAPACITY_BLOCKS,
                    "native_inflight_at_barrier": 0,
                }
            )
        sources = []
        for task in tasks:
            task_root = source_root / task
            sources.append(
                {
                    "task_id": task,
                    "sidecar_sha256": _sha(task_root / "acquisition-sidecar.json"),
                    "trajectory_sha256": _sha(task_root / f"{task}.traj.json"),
                    "run_sha256": _sha(task_root / "run.json"),
                }
            )
        scenario = {
            "scenario_id": scenario_id,
            "tasks": list(tasks),
            "request_count": timeline.request_count,
            "boundary_count": len(timeline.boundaries),
            "global_gap_count_before_first_pressure": (
                timeline.global_gap_count_before_first_pressure
            ),
            "timeline_sha256": timeline_sha,
            "pressure_input_sha256": pressure_sha,
            "pressure": pressure_rows,
            "target_shortage_blocks": spec["target_shortage_blocks"],
            "capacity": capacity_rows,
            "sources": sources,
            "static_checks": {
                "request_count_is_180": timeline.request_count == 180,
                "boundary_count_is_363": len(timeline.boundaries) == 363,
                "history_before_first_pressure_reaches_117": (
                    timeline.global_gap_count_before_first_pressure >= 117
                ),
                "all_single_requests_fit_capacity": all(
                    row["largest_single_request_fits"] for row in capacity_rows
                ),
                "first_pressure_nominal_shortage_matches_freeze": (
                    capacity_rows[0][
                        "nominal_shortage_without_prior_eviction_blocks"
                    ]
                    == spec["target_shortage_blocks"]
                ),
                "later_joint_demand_may_exceed_capacity_after_prior_eviction": True,
            },
        }
        scenarios.append(scenario)
        for arm in ARMS:
            runs.append(
                {
                    "run_id": f"{scenario_id}-{arm.lower()}-repeat-1",
                    "scenario_id": scenario_id,
                    "arm": arm,
                    "repeat": 1,
                    "timeline_sha256": timeline_sha,
                    "pressure_input_sha256": pressure_sha,
                    "capacity_blocks": CAPACITY_BLOCKS,
                    "max_run_wall_seconds": 1800,
                }
            )
    passed = all(
        all(value is True for value in scenario["static_checks"].values())
        for scenario in scenarios
    )
    return {
        "schema_version": "phase2h.history_rich_native_preflight.v1",
        "status": "PASS_STATIC_PREFLIGHT" if passed else "FAIL_STATIC_PREFLIGHT",
        "native_execution_status": "NOT_RUN_GPU_EXECUTION_NOT_AUTHORIZED",
        "scenario_count": len(scenarios),
        "planned_run_count": len(runs),
        "capacity_blocks": CAPACITY_BLOCKS,
        "block_size": BLOCK_SIZE,
        "pressure_rounds": list(PRESSURE_ROUNDS),
        "scenarios": scenarios,
        "runs": runs,
        "stop_controls": {
            "max_run_wall_seconds": 1800,
            "max_total_gpu_wall_seconds": 14_400,
            "dynamic_pressure_compensation": False,
        },
        "expected_gpu_wall_seconds_range": [3600, 10_800],
        "gate_reporting": "PER_RUN_H_AND_D_WITH_PASS_FAIL_NOT_OBSERVABLE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_preflight(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{result['status']}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

