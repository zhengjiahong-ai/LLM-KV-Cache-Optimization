"""Materialize exact four-Program replay and controller-timer schedules."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path

from .phase5_replay import (
    ArrivalMode,
    ArrivalPlan,
    ProgramStart,
    canonical_sha256,
    materialize_n_session_plan,
)


class CalibrationReplayError(ValueError):
    """A Calibration run cannot be bound to exact request timing."""


def _load_object(path: object, label: str) -> dict[str, object]:
    if not isinstance(path, str) or not path:
        raise CalibrationReplayError(f"{label} path is missing")
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationReplayError(f"{label} must contain an object")
    return value


def _turn_calls(trace: Mapping[str, object]) -> list[dict[str, object]]:
    turns = trace.get("turns")
    if not isinstance(turns, list) or not turns:
        raise CalibrationReplayError("normalized trace has no Turns")
    rows: list[dict[str, object]] = []
    for ordinal, value in enumerate(turns, start=1):
        if not isinstance(value, Mapping):
            raise CalibrationReplayError("normalized Turn is malformed")
        rows.append(
            {
                "request_id": value.get("request_id"),
                "turn_index": ordinal,
                "model_submit_monotonic_seconds": value.get("submitted_at_seconds"),
                "model_completion_monotonic_seconds": value.get("completed_at_seconds"),
            }
        )
    return rows


def materialize_calibration_run_replay(run: Mapping[str, object]) -> dict[str, object]:
    """Bind one execution-manifest row to all requests and empirical gaps."""

    programs = run.get("programs")
    starts = run.get("program_start_offsets")
    if not isinstance(programs, list) or len(programs) != 4:
        raise CalibrationReplayError("Calibration run must contain four Programs")
    if not isinstance(starts, list) or len(starts) != 4:
        raise CalibrationReplayError("Calibration run lacks four frozen starts")
    sessions: dict[str, Sequence[Mapping[str, object]]] = {}
    session_by_program: dict[str, str] = {}
    ordered_programs: list[str] = []
    for program in programs:
        if not isinstance(program, Mapping):
            raise CalibrationReplayError("Calibration Program binding is malformed")
        program_id = str(program.get("program_id"))
        trace = _load_object(program.get("normalized_trace_path"), "normalized trace")
        if trace.get("program_id") != program_id:
            raise CalibrationReplayError("normalized trace Program identity differs")
        session_id = str(program.get("session_id"))
        if trace.get("session_id") != session_id:
            raise CalibrationReplayError("normalized trace Session identity differs")
        sessions[program_id] = _turn_calls(trace)
        session_by_program[program_id] = session_id
        ordered_programs.append(program_id)
    start_rows = []
    for ordinal, value in enumerate(starts, start=1):
        if not isinstance(value, Mapping) or value.get("program_id") != ordered_programs[ordinal - 1]:
            raise CalibrationReplayError("frozen start order differs from Program order")
        start_rows.append(
            ProgramStart(
                program_id=ordered_programs[ordinal - 1],
                start_offset_seconds=float(value["start_offset_seconds"]),
                ordinal=ordinal,
            )
        )
    arrival = ArrivalPlan(
        mode=ArrivalMode.FROZEN_POISSON,
        starts=tuple(start_rows),
        fixed_stagger_seconds=None,
        poisson_rate_per_second=0.1,
        seed=20261201,
        generator="PYTHON_RANDOM_MT19937_EXPONENTIAL_V1",
    )
    plan = materialize_n_session_plan(sessions=sessions, arrival_plan=arrival)
    arrival_by_request = {
        str(row.request_id): float(row.logical_timestamp)
        for row in plan.events
        if row.kind.value == "ARRIVAL" and row.request_id is not None
    }
    timers = []
    for program_id in ordered_programs:
        calls = sessions[program_id]
        for current, successor in pairwise(calls):
            completed = float(current["model_completion_monotonic_seconds"])
            submitted = float(successor["model_submit_monotonic_seconds"])
            gap = submitted - completed
            if gap < 0:
                raise CalibrationReplayError("empirical tool gap is negative")
            predecessor_id = str(current["request_id"])
            successor_id = str(successor["request_id"])
            timers.append(
                {
                    "candidate_id": program_id,
                    "chain_id": f"{predecessor_id}->{successor_id}",
                    "program_id": program_id,
                    "session_id": session_by_program[program_id],
                    "predecessor_request_id": predecessor_id,
                    "successor_request_id": successor_id,
                    "arm_boundary": "OBSERVED_PREDECESSOR_TERMINAL",
                    "timeout_seconds": gap,
                    "successor_logical_arrival_seconds": arrival_by_request[
                        successor_id
                    ],
                    "engine_core_command": "CONTROLLER_ARM_TIMER",
                    "future_content_available": False,
                    "future_reuse_outcome_available": False,
                }
            )
    payload = {
        "schema_version": "phase5.swe_calibration_run_replay.v1",
        "status": "PASS",
        "group_id": run.get("group_id"),
        "system_scope": "ALL_SIX_SYSTEMS_AND_REPEATS",
        "arrival_plan_sha256": arrival.sha256,
        "replay_plan": plan.to_dict(),
        "request_count": len(plan.expected_native_enqueue_order),
        "controller_timer_count": len(timers),
        "controller_timers": timers,
        "timer_information_boundary": (
            "ARM_ONLY_AFTER_OBSERVED_PREDECESSOR_TERMINAL; "
            "ENGINE_CORE_SAMPLES_ARMED_TIMESTAMP"
        ),
    }
    return {**payload, "replay_sha256": canonical_sha256(payload)}


def materialize_calibration_replay_templates(
    execution_manifest: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Build one shared replay template for each of the four frozen Groups."""

    runs = execution_manifest.get("runs")
    if not isinstance(runs, list) or len(runs) != 72:
        raise CalibrationReplayError("execution manifest is not the 72-run inventory")
    first_by_group: dict[str, Mapping[str, object]] = {}
    for row in runs:
        if not isinstance(row, Mapping):
            raise CalibrationReplayError("execution run is malformed")
        first_by_group.setdefault(str(row.get("group_id")), row)
    if set(first_by_group) != {"SWE_G01", "SWE_G02", "SWE_G03", "SWE_G04"}:
        raise CalibrationReplayError("execution manifest lacks four frozen Groups")
    return {
        group_id: materialize_calibration_run_replay(row)
        for group_id, row in sorted(first_by_group.items())
    }


def bind_calibration_replay_templates(
    execution_manifest: Mapping[str, object],
    templates: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Bind every run to its shared Group template without duplicating payloads."""

    expected_groups = {"SWE_G01", "SWE_G02", "SWE_G03", "SWE_G04"}
    if set(templates) != expected_groups:
        raise CalibrationReplayError("replay template set differs from frozen Groups")
    template_index = {
        group_id: {
            "file": f"replay-templates/{group_id}.json",
            "replay_sha256": value.get("replay_sha256"),
            "request_count": value.get("request_count"),
            "controller_timer_count": value.get("controller_timer_count"),
        }
        for group_id, value in sorted(templates.items())
    }
    payload = dict(execution_manifest)
    payload.pop("execution_manifest_sha256", None)
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise CalibrationReplayError("execution manifest run list is malformed")
    payload["runs"] = [
        {
            **dict(row),
            "replay_template_file": template_index[str(row["group_id"])]["file"],
            "replay_sha256": template_index[str(row["group_id"])]["replay_sha256"],
            "expected_enqueue_sequence_sha256": canonical_sha256(
                templates[str(row["group_id"])]["replay_plan"][
                    "expected_native_enqueue_order"
                ]
            ),
        }
        for row in runs
        if isinstance(row, Mapping)
    ]
    if len(payload["runs"]) != 72:
        raise CalibrationReplayError("execution manifest lost runs during replay binding")
    payload["replay_templates"] = template_index
    payload["replay_template_index_sha256"] = canonical_sha256(template_index)
    return {**payload, "execution_manifest_sha256": canonical_sha256(payload)}
