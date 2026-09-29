"""Validated, deterministic logical inputs for Phase 2 replay."""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _offset(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be an object with string keys")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


@dataclass(frozen=True, slots=True)
class PlannedRequest:
    program_id: str
    request_id: str
    turn_index: int
    planned_arrival_offset_seconds: float
    prompt: str
    prefix_prompt: str
    is_terminal: bool
    next_tool_type: str | None
    tool_gap_seconds: float | None
    kind: str = "turn"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PressureStage:
    stage_id: str
    planned_arrival_offset_seconds: float
    prompt: str
    max_requests: int
    stop_on_forced_release: bool

    def request(self, attempt: int, seed: int) -> PlannedRequest:
        if attempt < 1 or attempt > self.max_requests:
            raise ValueError("pressure attempt exceeds stage ceiling")
        # The seeded suffix keeps pressure prompts distinct from target prefixes.
        nonce = random.Random(f"{seed}:{self.stage_id}:{attempt}").getrandbits(64)
        return PlannedRequest(
            program_id=f"pressure:{self.stage_id}",
            request_id=f"pressure:{self.stage_id}:{attempt}",
            turn_index=attempt,
            planned_arrival_offset_seconds=self.planned_arrival_offset_seconds,
            prompt=f"{self.prompt} {nonce:016x}",
            prefix_prompt="",
            is_terminal=True,
            next_tool_type=None,
            tool_gap_seconds=None,
            kind="pressure",
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Phase2Trace:
    trace_id: str
    requests: tuple[PlannedRequest, ...]
    pressure_stages: tuple[PressureStage, ...]

    def actions(self) -> tuple[PlannedRequest | PressureStage, ...]:
        actions: list[PlannedRequest | PressureStage] = [*self.requests, *self.pressure_stages]
        return tuple(sorted(actions, key=lambda item: item.planned_arrival_offset_seconds))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase2.trace.v1",
            "trace_id": self.trace_id,
            "requests": [request.to_dict() for request in self.requests],
            "pressure_stages": [stage.to_dict() for stage in self.pressure_stages],
        }


def load_phase2_trace(path: str | Path) -> Phase2Trace:
    raw = _object(json.loads(Path(path).read_text(encoding="utf-8")), "trace")
    if raw.get("schema_version") != "phase2.trace.v1":
        raise ValueError("unsupported trace schema_version")
    trace_id = _text(raw.get("trace_id"), "trace_id")
    pressure = _list(raw.get("pressure_stages", []), "pressure_stages")
    requests: list[PlannedRequest] = []
    if "requests" in raw:
        for request_data in _list(raw.get("requests"), "requests"):
            item = _object(request_data, "request")
            program_id = _text(item.get("program_id"), "program_id")
            request_id = _text(item.get("request_id"), "request_id")
            turn_index = _positive_int(item.get("turn_index"), "turn_index")
            terminal = item.get("is_terminal")
            if not isinstance(terminal, bool):
                raise TypeError("is_terminal must be bool")
            tool = item.get("next_tool_type")
            gap = item.get("tool_gap_seconds")
            if terminal:
                if tool is not None or gap is not None:
                    raise ValueError("terminal request cannot declare a tool gap")
            else:
                tool = _text(tool, "next_tool_type")
                gap = _offset(gap, "tool_gap_seconds")
            kind = item.get("kind", "turn")
            if kind not in {"turn", "pressure"}:
                raise ValueError("request kind must be turn or pressure")
            if kind == "pressure" and not program_id.startswith("pressure:"):
                raise ValueError("pressure request must use reserved program identity")
            if kind == "turn" and program_id.startswith("pressure:"):
                raise ValueError("turn request cannot use reserved program identity")
            requests.append(PlannedRequest(
                program_id=program_id,
                request_id=request_id,
                turn_index=turn_index,
            planned_arrival_offset_seconds=_offset(
                    item.get(
                        "planned_arrival_offset_seconds",
                        item.get("arrival_offset_seconds"),
                    ),
                    "planned_arrival_offset_seconds",
                ),
                prompt=_text(item.get("prompt"), "prompt"),
                prefix_prompt=_text(item.get("prefix_prompt", ""), "prefix_prompt")
                if item.get("prefix_prompt", "")
                else "",
                is_terminal=terminal,
                next_tool_type=tool,
                tool_gap_seconds=gap,
                kind=kind,
            ))
        by_program: dict[str, list[PlannedRequest]] = {}
        identities: set[str] = set()
        for request in requests:
            if request.request_id in identities:
                raise ValueError("duplicate request_id")
            identities.add(request.request_id)
            if request.kind == "turn":
                by_program.setdefault(request.program_id, []).append(request)
        for program_requests in by_program.values():
            program_requests.sort(key=lambda request: request.turn_index)
            if tuple(request.turn_index for request in program_requests) != tuple(
                range(1, len(program_requests) + 1)
            ):
                raise ValueError("turn indexes must be contiguous within each program")
            if any(
                later.planned_arrival_offset_seconds < earlier.planned_arrival_offset_seconds
                for earlier, later in zip(program_requests, program_requests[1:])
            ):
                raise ValueError("planned arrival offsets must be non-decreasing within a program")
            if any(request.is_terminal for request in program_requests[:-1]) or not (
                program_requests[-1].is_terminal
            ):
                raise ValueError("only the final program turn may be terminal")
    else:
        programs = _list(raw.get("programs"), "programs")
        requests, identities = [], set()
        seen_programs: set[str] = set()
        for program_data in programs:
            program = _object(program_data, "program")
            program_id = _text(program.get("program_id"), "program_id")
            if program_id.startswith("pressure:") or program_id in seen_programs:
                raise ValueError("program_id is duplicate or reserved")
            seen_programs.add(program_id)
            turns = _list(program.get("turns"), "turns")
            if not turns:
                raise ValueError("program must have turns")
            previous_arrival = -1.0
            for index, turn_data in enumerate(turns, start=1):
                turn = _object(turn_data, "turn")
                arrival = _offset(turn.get("arrival_offset_seconds"), "arrival_offset_seconds")
                if arrival < previous_arrival:
                    raise ValueError("program turns must have ordered planned arrivals")
                previous_arrival = arrival
                terminal = turn.get("terminal")
                if not isinstance(terminal, bool) or terminal != (index == len(turns)):
                    raise ValueError("only the final turn may be terminal")
                tool = turn.get("next_tool_type")
                gap = turn.get("tool_gap_seconds")
                if terminal:
                    if tool is not None or gap is not None:
                        raise ValueError("terminal turn cannot declare a tool gap")
                else:
                    tool = _text(tool, "next_tool_type")
                    gap = _offset(gap, "tool_gap_seconds")
                prefix = turn.get("prefix_prompt", "")
                if not isinstance(prefix, str):
                    raise TypeError("prefix_prompt must be text")
                request = PlannedRequest(
                    program_id=program_id,
                    request_id=f"{program_id}:turn:{index}",
                    turn_index=index,
                    planned_arrival_offset_seconds=arrival,
                    prompt=_text(turn.get("prompt"), "prompt"),
                    prefix_prompt=prefix,
                    is_terminal=terminal,
                    next_tool_type=tool,
                    tool_gap_seconds=gap,
                )
                if request.request_id in identities:
                    raise ValueError("duplicate request_id")
                identities.add(request.request_id)
                requests.append(request)
    stages: list[PressureStage] = []
    seen_stages: set[str] = set()
    for stage_data in pressure:
        stage = _object(stage_data, "pressure stage")
        stage_id = _text(stage.get("stage_id"), "stage_id")
        if stage_id in seen_stages:
            raise ValueError("duplicate pressure stage_id")
        seen_stages.add(stage_id)
        stop = stage.get("stop_on_forced_release", True)
        if not isinstance(stop, bool):
            raise TypeError("stop_on_forced_release must be bool")
        stages.append(PressureStage(
            stage_id=stage_id,
            planned_arrival_offset_seconds=_offset(
                stage.get(
                    "planned_arrival_offset_seconds",
                    stage.get("arrival_offset_seconds"),
                ),
                "planned_arrival_offset_seconds",
            ),
            prompt=_text(stage.get("prompt"), "pressure prompt"),
            max_requests=_positive_int(stage.get("max_requests"), "max_requests"),
            stop_on_forced_release=stop,
        ))
    if not requests and not stages:
        raise ValueError("trace must contain requests or pressure stages")
    return Phase2Trace(trace_id, tuple(requests), tuple(stages))
