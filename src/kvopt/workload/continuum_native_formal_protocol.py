"""Freeze and validate the W1-C-derived formal Native comparison protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROTOCOL_SCHEMA = "continuum.native_costaware_formal_protocol.v1"
FREEZE_SCHEMA = "continuum.native_costaware_formal_freeze_candidate.v1"
EXPECTED_ARMS = ["A0", "A1", "A2"]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _token_digest(tokens: list[int]) -> str:
    payload = json.dumps(tokens, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _checkpoint_indexes(count: int, requested: int) -> list[int]:
    if count < 2:
        raise ValueError("formal replay requires at least two successful model calls")
    if requested < 2:
        raise ValueError("checkpoint count must be at least two")
    if count <= requested:
        return list(range(count))
    # Integer quantiles include both endpoints and never depend on policy outcomes.
    return sorted({index * (count - 1) // (requested - 1) for index in range(requested)})


def _validate_protocol(protocol: dict[str, Any]) -> None:
    if protocol.get("schema_version") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported formal protocol schema")
    if protocol.get("native_policy_arms") != EXPECTED_ARMS:
        raise ValueError("formal Native arms must be exactly A0, A1 and A2")
    if protocol.get("runtime_repeats") != 2:
        raise ValueError("formal protocol freezes two runtime repeats")
    if protocol.get("simple_rule_comparators") != [
        "SUFFICIENT_FIRST_EARLIEST_DEADLINE",
        "SUFFICIENT_FIRST_MINIMUM_OVERSHOOT",
    ]:
        raise ValueError("formal protocol must freeze both simple-rule comparators")
    if protocol.get("formal_execution_authorized") is not False:
        raise ValueError("protocol candidate cannot authorize formal execution")
    groups = protocol.get("workload_groups")
    if not isinstance(groups, list) or len(groups) != 9:
        raise ValueError("formal protocol requires nine disjoint workload groups")
    tasks = [task for group in groups for task in group.get("task_ids", [])]
    if len(tasks) != 18 or len(set(tasks)) != 18:
        raise ValueError("formal cohort must contain 18 unique tasks exactly once")
    regimes = protocol.get("pressure_regimes")
    if not isinstance(regimes, list) or [row.get("id") for row in regimes] != [
        "moderate",
        "deep",
    ]:
        raise ValueError("formal protocol must freeze moderate and deep pressure regimes")
    if protocol.get("planned_run_count") != 108:
        raise ValueError("formal protocol must freeze 108 Native runs")
    if protocol.get("statistical_unit") != "DISJOINT_TWO_TASK_WORKLOAD_GROUP":
        raise ValueError("runtime runs and requests cannot be statistical units")


def freeze_protocol(
    *, protocol_path: Path, source_report_path: Path, output_path: Path
) -> dict[str, Any]:
    protocol = _load(protocol_path)
    _validate_protocol(protocol)
    report = _load(source_report_path)
    if report.get("schema_version") != "continuum.w1c_feasibility_report.v1":
        raise ValueError("source is not the accepted W1-C feasibility report")
    if report.get("valid_pair_count") != 18:
        raise ValueError("formal source cohort requires exactly 18 full-payload pairs")
    comparable = {
        row["instance_id"]: row
        for row in report.get("pairs", [])
        if row.get("comparable") is True
    }
    expected = {
        task for group in protocol["workload_groups"] for task in group["task_ids"]
    }
    if set(comparable) != expected:
        raise ValueError("protocol cohort does not equal the 18 W1-C comparable tasks")
    if len({row["repository"] for row in comparable.values()}) != 11:
        raise ValueError("full-payload cohort must cover exactly 11 repositories")

    runs_root = Path(protocol["source_runs_root"])
    frozen_groups: list[dict[str, Any]] = []
    maximum_tokens = 0
    selected_request_count = 0
    for group in protocol["workload_groups"]:
        sessions: list[dict[str, Any]] = []
        for instance_id in group["task_ids"]:
            run_dir = runs_root / "S100" / instance_id
            run_path = run_dir / "run.json"
            sidecar_path = run_dir / "acquisition-sidecar.json"
            trajectory_path = run_dir / f"{instance_id}.traj.json"
            for path in (run_path, sidecar_path, trajectory_path):
                if not path.is_file():
                    raise FileNotFoundError(f"missing W1-C source evidence: {path}")
            run = _load(run_path)
            sidecar = _load(sidecar_path)
            if run.get("instance_id") != instance_id or sidecar.get("program_id") != instance_id:
                raise ValueError("W1-C source identity mismatch")
            if run.get("sidecar_sha256") != _sha256(sidecar_path):
                raise ValueError("W1-C sidecar SHA-256 binding mismatch")
            if run.get("trajectory_sha256") != _sha256(trajectory_path):
                raise ValueError("W1-C trajectory SHA-256 binding mismatch")
            calls = [row for row in sidecar.get("model_calls", []) if row.get("status") == "SUCCESS"]
            indexes = _checkpoint_indexes(
                len(calls), int(protocol["replay_selection"]["checkpoints_per_session"])
            )
            selected: list[dict[str, Any]] = []
            previous_turn = 0
            for index in indexes:
                call = calls[index]
                tokens = call.get("submitted_token_ids")
                if not isinstance(tokens, list) or not tokens or any(
                    not isinstance(token, int) for token in tokens
                ):
                    raise ValueError("selected W1-C call lacks deterministic token IDs")
                turn = int(call["turn_index"])
                if turn <= previous_turn:
                    raise ValueError("selected W1-C requests are not ordered")
                previous_turn = turn
                digest = _token_digest(tokens)
                selected.append(
                    {
                        "request_id": call["request_id"],
                        "source_turn_index": turn,
                        "token_count": len(tokens),
                        "token_ids_sha256": digest,
                        "rendered_prompt_sha256": call["rendered_prompt_sha256"],
                    }
                )
                maximum_tokens = max(maximum_tokens, len(tokens))
            selected_request_count += len(selected)
            sessions.append(
                {
                    "instance_id": instance_id,
                    "repository": comparable[instance_id]["repository"],
                    "source_outcome": comparable[instance_id]["s100_outcome"],
                    "run_path": str(run_path),
                    "run_sha256": _sha256(run_path),
                    "sidecar_path": str(sidecar_path),
                    "sidecar_sha256": _sha256(sidecar_path),
                    "trajectory_path": str(trajectory_path),
                    "trajectory_sha256": _sha256(trajectory_path),
                    "selected_requests": selected,
                }
            )
        frozen_groups.append(
            {
                "group_id": group["group_id"],
                "pairing_basis": group["pairing_basis"],
                "sessions": sessions,
            }
        )

    run_plan = [
        {
            "run_id": f"{group['group_id']}-{regime['id']}-{arm.lower()}-repeat-{repeat}",
            "group_id": group["group_id"],
            "pressure_regime": regime["id"],
            "arm": arm,
            "repeat": repeat,
        }
        for group in protocol["workload_groups"]
        for regime in protocol["pressure_regimes"]
        for arm in protocol["native_policy_arms"]
        for repeat in range(1, protocol["runtime_repeats"] + 1)
    ]
    if len(run_plan) != protocol["planned_run_count"]:
        raise ValueError("planned run count does not match the frozen design")
    freeze = {
        "schema_version": FREEZE_SCHEMA,
        "scope": "FORMAL_PROTOCOL_CANDIDATE_NO_NATIVE_OUTCOMES",
        "protocol_path": str(protocol_path),
        "protocol_sha256": _sha256(protocol_path),
        "source_report_path": str(source_report_path),
        "source_report_sha256": _sha256(source_report_path),
        "cohort": {
            "full_payload_task_count": 18,
            "repository_count": 11,
            "excluded_task_ids": ["astropy__astropy-8872", "sympy__sympy-21596"],
            "source_condition": "S100",
        },
        "groups": frozen_groups,
        "group_count": len(frozen_groups),
        "selected_request_count": selected_request_count,
        "maximum_selected_prompt_tokens": maximum_tokens,
        "pressure_regimes": protocol["pressure_regimes"],
        "native_policy_arms": protocol["native_policy_arms"],
        "simple_rule_comparators": protocol["simple_rule_comparators"],
        "runtime_repeats": protocol["runtime_repeats"],
        "planned_run_count": len(run_plan),
        "run_plan": run_plan,
        "statistical_unit": protocol["statistical_unit"],
        "profile_coverage_requirement": {
            "maximum_query_tokens_must_cover": maximum_tokens // 16 * 16,
            "status": "PENDING_MEASURED_PROFILE_COVERAGE_AUDIT",
        },
        "m1_protocol_freeze_status": "PENDING",
        "formal_execution_authorized": False,
        "outcomes_materialized": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    freeze = freeze_protocol(
        protocol_path=args.protocol,
        source_report_path=args.source_report,
        output_path=args.output,
    )
    print(
        f"froze formal protocol candidate: {freeze['group_count']} groups, "
        f"{freeze['planned_run_count']} planned runs -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
