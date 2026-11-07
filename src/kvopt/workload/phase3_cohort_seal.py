"""Build the deterministic Phase 3 qualification report and Cohort Seal."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kvopt.profiling.continuum_w1c_report import _run_row

from .continuum_bounded_timeline import (
    BoundaryKind,
    materialize_request_boundaries,
)
from .continuum_w1a_runner import _tokenizer_observer

ARMS = ("N0", "A0", "A1", "A2", "A3", "E0")
CHECKPOINTS_PER_SESSION = 12
CROSS_SESSION_STAGGER_SECONDS = 0.25
PROFILE_MEMBER = (
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/profile/"
    "prefill-reload-profile-interpreted.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _checkpoint_indexes(count: int, requested: int = CHECKPOINTS_PER_SESSION) -> list[int]:
    if count < requested:
        raise ValueError("qualified task has fewer than twelve successful requests")
    return sorted({index * (count - 1) // (requested - 1) for index in range(requested)})


def _profile_binding(archive: Path) -> dict[str, object]:
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember(PROFILE_MEMBER)
        source = bundle.extractfile(member)
        if source is None:
            raise ValueError("interpreted Profile member is not readable")
        payload = source.read()
    return {
        "archive_path": str(archive),
        "archive_sha256": _sha256(archive),
        "member_path": PROFILE_MEMBER,
        "member_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _qualification_rows(
    *,
    repository: Path,
    plan: Mapping[str, object],
    config_path: Path,
    runs_root: Path,
) -> tuple[list[dict[str, object]], str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    tokenizer = _tokenizer_observer(config["model"])
    candidates = plan.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("candidate plan candidates must be an array")
    manifests: list[dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, dict):
            raise TypeError("candidate must be an object")
        path = runs_root / str(row["instance_id"]) / "run.json"
        if path.is_file():
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
    git_shas = {str(row.get("repository_git_sha")) for row in manifests}
    if len(git_shas) != 1:
        raise ValueError("acquisition attempts do not share one execution Git SHA")
    execution_git_sha = next(iter(git_shas))
    results: list[dict[str, object]] = []
    for candidate in candidates:
        instance_id = str(candidate["instance_id"])
        run_dir = runs_root / instance_id
        if not (run_dir / "run.json").is_file():
            continue
        row = _run_row(
            run_dir,
            instance_id,
            "S100",
            config=config,
            config_path=config_path,
            execution_git_sha=execution_git_sha,
            tokenize_messages=tokenizer,
        )
        tool_evidence = int(row["tool_call_count"]) > 0
        checkpoint_eligible = int(row["successful_model_call_count"]) >= CHECKPOINTS_PER_SESSION
        qualified = row["status"] == "VALID" and tool_evidence and checkpoint_eligible
        problems = list(row["problems"])
        if not tool_evidence:
            problems.append("formal Agent Trace has no Tool Observation")
        if not checkpoint_eligible:
            problems.append("formal Agent Trace has fewer than twelve successful requests")
        results.append(
            {
                "instance_id": instance_id,
                "repository": candidate["repository"],
                "candidate_role": candidate["role"],
                "candidate_role_rank": candidate["role_rank"],
                "acquisition_rank": candidate["acquisition_rank"],
                "status": "QUALIFIED" if qualified else "DISQUALIFIED",
                "outcome": row["outcome"],
                "model_call_count": row["model_call_count"],
                "successful_model_call_count": row["successful_model_call_count"],
                "tool_call_count": row["tool_call_count"],
                "max_prompt_tokens": row["max_prompt_tokens"],
                "problems": problems,
                "run_path": str((run_dir / "run.json").relative_to(repository)),
                "run_sha256": _sha256(run_dir / "run.json"),
                "sidecar_path": str(
                    (run_dir / "acquisition-sidecar.json").relative_to(repository)
                )
                if (run_dir / "acquisition-sidecar.json").is_file()
                else None,
                "sidecar_sha256": _sha256(run_dir / "acquisition-sidecar.json")
                if (run_dir / "acquisition-sidecar.json").is_file()
                else None,
                "trajectory_path": str(
                    (run_dir / f"{instance_id}.traj.json").relative_to(repository)
                )
                if (run_dir / f"{instance_id}.traj.json").is_file()
                else None,
                "trajectory_sha256": _sha256(run_dir / f"{instance_id}.traj.json")
                if (run_dir / f"{instance_id}.traj.json").is_file()
                else None,
            }
        )
    return results, execution_git_sha


def resolve_final_cohort(
    plan: Mapping[str, object], rows: Sequence[Mapping[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Replay deterministic promotion rounds until every Primary slot qualifies."""

    candidates = [dict(row) for row in plan["candidates"]]  # type: ignore[index]
    by_id = {str(row["instance_id"]): row for row in candidates}
    status = {str(row["instance_id"]): row["status"] for row in rows}
    primary = sorted(
        (row for row in candidates if row["role"] == "PRIMARY"),
        key=lambda row: int(row["role_rank"]),
    )
    reserves = sorted(
        (row for row in candidates if row["role"] == "RESERVE"),
        key=lambda row: int(row["role_rank"]),
    )
    final = {str(row["instance_id"]): str(row["instance_id"]) for row in primary}
    chains = {str(row["instance_id"]): [] for row in primary}
    pending = [str(row["instance_id"]) for row in primary if status.get(str(row["instance_id"])) != "QUALIFIED"]
    used: set[str] = set()
    while pending:
        next_pending: list[str] = []
        for primary_id in pending:
            repository_name = str(by_id[primary_id]["repository"])
            available = [row for row in reserves if str(row["instance_id"]) not in used]
            same = [row for row in available if row["repository"] == repository_name]
            attempted = [row for row in (same or available) if str(row["instance_id"]) in status]
            if not attempted:
                raise ValueError(f"no acquired Reserve can replace {primary_id}")
            selected = attempted[0]
            selected_id = str(selected["instance_id"])
            used.add(selected_id)
            chains[primary_id].append(selected_id)
            if status[selected_id] == "QUALIFIED":
                final[primary_id] = selected_id
            else:
                next_pending.append(primary_id)
        pending = next_pending
    tasks: list[dict[str, object]] = []
    promotions: list[dict[str, object]] = []
    for slot, row in enumerate(primary, start=1):
        primary_id = str(row["instance_id"])
        final_id = final[primary_id]
        selected = by_id[final_id]
        tasks.append({**selected, "cohort_slot": slot, "primary_instance_id": primary_id})
        if chains[primary_id]:
            promotions.append(
                {
                    "primary_instance_id": primary_id,
                    "attempted_reserve_chain": chains[primary_id],
                    "selected_instance_id": final_id,
                }
            )
    return tasks, promotions


def pair_tasks(tasks: Sequence[Mapping[str, object]]) -> list[tuple[dict[str, object], dict[str, object]]]:
    remaining = [dict(row) for row in tasks]
    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    while remaining:
        counts = Counter(str(row["repository"]) for row in remaining)
        repository_name = min(counts, key=lambda key: (-counts[key], key))
        left = next(row for row in remaining if row["repository"] == repository_name)
        right = next((row for row in remaining if row["repository"] != repository_name), None)
        if right is None:
            raise ValueError("cannot form different-repository workload groups")
        remaining.remove(left)
        remaining.remove(right)
        pairs.append((left, right))
    return pairs


def _session(
    *, repository: Path, row: Mapping[str, object], runs_root: Path
) -> tuple[dict[str, object], list[dict[str, Any]]]:
    instance_id = str(row["instance_id"])
    run_dir = runs_root / instance_id
    manifest_path = run_dir / "run.json"
    sidecar_path = run_dir / "acquisition-sidecar.json"
    trajectory_path = run_dir / f"{instance_id}.traj.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    calls = [call for call in sidecar["model_calls"] if call.get("status") == "SUCCESS"]
    indexes = _checkpoint_indexes(len(calls))
    selected = [calls[index] for index in indexes]
    requests = []
    for call in selected:
        tokens = call.get("submitted_token_ids")
        if not isinstance(tokens, list) or not tokens or any(type(value) is not int for value in tokens):
            raise ValueError("selected request lacks exact integer Token IDs")
        requests.append(
            {
                "request_id": call["request_id"],
                "source_turn_index": call["turn_index"],
                "token_count": len(tokens),
                "token_ids_sha256": _canonical_sha256(tokens),
                "rendered_prompt_sha256": call["rendered_prompt_sha256"],
                "model_submit_monotonic_seconds": call["model_submit_monotonic_seconds"],
                "model_completion_monotonic_seconds": call["model_completion_monotonic_seconds"],
            }
        )
    return (
        {
            "instance_id": instance_id,
            "repository": row["repository"],
            "cohort_slot": row["cohort_slot"],
            "run_path": str(manifest_path.relative_to(repository)),
            "run_sha256": _sha256(manifest_path),
            "sidecar_path": str(sidecar_path.relative_to(repository)),
            "sidecar_sha256": _sha256(sidecar_path),
            "trajectory_path": str(trajectory_path.relative_to(repository)),
            "trajectory_sha256": _sha256(trajectory_path),
            "selected_requests": requests,
        },
        selected,
    )


def build_seal(
    *, repository: Path, plan_path: Path, config_path: Path, runs_root: Path, profile_archive: Path
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows, acquisition_git_sha = _qualification_rows(
        repository=repository, plan=plan, config_path=config_path, runs_root=runs_root
    )
    tasks, promotions = resolve_final_cohort(plan, rows)
    if len(tasks) != 40 or len({str(row["instance_id"]) for row in tasks}) != 40:
        raise ValueError("formal cohort does not contain forty unique tasks")
    if len({str(row["repository"]) for row in tasks}) < 10:
        raise ValueError("formal cohort does not cover ten repositories")
    groups = []
    maximum_tokens = 0
    for group_index, (left, right) in enumerate(pair_tasks(tasks), start=1):
        sessions = []
        raw_calls = []
        for row in (left, right):
            session, calls = _session(repository=repository, row=row, runs_root=runs_root)
            sessions.append(session)
            raw_calls.append(calls)
            maximum_tokens = max(
                maximum_tokens,
                max(int(request["token_count"]) for request in session["selected_requests"]),
            )
        boundaries = materialize_request_boundaries(
            sessions=raw_calls,
            cross_session_start_stagger_seconds=CROSS_SESSION_STAGGER_SECONDS,
        )
        selected_order = {
            str(session["instance_id"]): [
                str(request["request_id"]) for request in session["selected_requests"]
            ]
            for session in sessions
        }
        completed: dict[str, list[str]] = defaultdict(list)
        predecessors: dict[str, list[str]] = {}
        enqueue_order: list[str] = []
        request_to_program = {
            request_id: program_id
            for program_id, request_ids in selected_order.items()
            for request_id in request_ids
        }
        timeline = []
        for boundary in boundaries:
            timeline.append(
                {
                    "boundary_id": boundary.boundary_id,
                    "logical_timestamp": boundary.logical_timestamp,
                    "source": boundary.source,
                    "kind": boundary.kind.value,
                    "request_id": boundary.request_id,
                }
            )
            if boundary.kind is BoundaryKind.ARRIVAL:
                request_id = str(boundary.request_id)
                program_id = request_to_program[request_id]
                enqueue_order.append(request_id)
                predecessors[request_id] = list(completed[program_id])
            elif boundary.kind is BoundaryKind.COMPLETION:
                request_id = str(boundary.request_id)
                completed[request_to_program[request_id]].append(request_id)
        if len(enqueue_order) != 24 or len(set(enqueue_order)) != 24:
            raise ValueError("group does not freeze exactly 24 unique requests")
        groups.append(
            {
                "group_id": f"g{group_index:02d}",
                "sessions": sessions,
                "frozen_request_order": enqueue_order,
                "native_enqueue_order": enqueue_order,
                "history_predecessors": predecessors,
                "replay_timeline": timeline,
                "replay_timeline_sha256": _canonical_sha256(timeline),
            }
        )
    qualification = {
        "schema_version": "phase3.cohort_qualification_report.v1",
        "candidate_plan_sha256": _sha256(plan_path),
        "acquisition_config_sha256": _sha256(config_path),
        "acquisition_git_sha": acquisition_git_sha,
        "attempted_task_count": len(rows),
        "qualified_attempt_count": sum(row["status"] == "QUALIFIED" for row in rows),
        "disqualified_attempt_count": sum(row["status"] != "QUALIFIED" for row in rows),
        "final_task_count": len(tasks),
        "promotion_chains": promotions,
        "tasks": rows,
    }
    profile = _profile_binding(profile_archive)
    seal = {
        "schema_version": "phase3.cohort_seal.v1",
        "readiness": "READY_WITH_LIMITATIONS",
        "limitations": [
            "TARGET_1P5B_TOKENIZER_EXACT_REPLAY_COMPATIBILITY_PENDING",
            "TARGET_CUDA_NATIVE_REPLAY_EXECUTABILITY_PENDING",
            "A0_LOAD_CALIBRATION_AND_HEADROOM_FREEZE_PENDING",
        ],
        "candidate_plan_sha256": _sha256(plan_path),
        "qualification_report_sha256": _canonical_sha256(qualification),
        "profile": profile,
        "task_count": 40,
        "group_count": 20,
        "repository_count": len({str(row["repository"]) for row in tasks}),
        "requests_per_session": CHECKPOINTS_PER_SESSION,
        "requests_per_group": 24,
        "maximum_inflight": 2,
        "cross_session_start_stagger_seconds": CROSS_SESSION_STAGGER_SECONDS,
        "maximum_selected_prompt_tokens": maximum_tokens,
        "tasks": tasks,
        "groups": groups,
    }
    seal["cohort_content_sha256"] = _canonical_sha256(
        {"tasks": tasks, "groups": groups, "profile": profile}
    )
    run_manifest = {
        "schema_version": "phase3.run_input_manifest.v1",
        "cohort_content_sha256": seal["cohort_content_sha256"],
        "arms": list(ARMS),
        "load_levels": ["L_LOW", "L_HIGH"],
        "groups": [row["group_id"] for row in groups],
        "main_campaign_run_count": 240,
        "load_calibration_run_count": 40,
        "noise_calibration_run_count": 30,
        "total_planned_run_count": 310,
        "main_campaign_authorized": False,
    }
    return qualification, seal, run_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--profile-archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repository = Path.cwd().resolve()
    qualification, seal, run_manifest = build_seal(
        repository=repository,
        plan_path=args.plan.resolve(),
        config_path=args.config.resolve(),
        runs_root=args.runs_root.resolve(),
        profile_archive=args.profile_archive.resolve(),
    )
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    outputs = {
        "qualification-report.json": qualification,
        "cohort-seal.json": seal,
        "run-input-manifest.json": run_manifest,
    }
    hashes = []
    for name, value in outputs.items():
        path = args.output_dir / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        hashes.append(f"{_sha256(path)}  {name}")
    (args.output_dir / "sha256-manifest.txt").write_text("\n".join(hashes) + "\n")
    print(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
