"""Trace schema for the Phase 2F agent APC simulation (``phase2f.trace.v1``).

A trace is the complete, deterministic, replayable input of one scenario draw:
every request's prompt (as content segments), arrival time, tool gaps,
termination outcome, and the warmup/measured split. Traces are generated once,
hashed, and shared verbatim by every experiment arm.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .content import Segment, prompt_block_content_ids

TRACE_SCHEMA = "phase2f.trace.v1"
GENERATOR_VERSION = "phase2f.workload_gen.v1"


@dataclass(frozen=True, slots=True)
class TraceRequest:
    """One LLM request inside a program lifecycle."""

    request_id: str
    program_id: str
    turn_index: int
    arrival_offset_seconds: float
    segments: tuple[Segment, ...]
    is_terminal: bool
    next_tool_type: str | None
    tool_gap_seconds: float | None
    outcome: str  # "COMPLETED" | "CANCELLED"
    window: str  # "warmup" | "measured"

    @property
    def total_tokens(self) -> int:
        return sum(segment.tokens for segment in self.segments)

    @property
    def cacheable_blocks(self) -> int:
        return len(prompt_block_content_ids(self.segments, 16))


@dataclass(frozen=True, slots=True)
class SimulationTrace:
    """One scenario draw: requests plus capacity and policy-neutral knobs."""

    schema_version: str
    trace_id: str
    family: str
    draw: int
    seed: int
    generator_version: str
    total_blocks: int
    block_size_tokens: int
    free_order: str
    extrapolate_prefill_profile: bool
    requests: tuple[TraceRequest, ...]

    def measured_requests(self) -> tuple[TraceRequest, ...]:
        return tuple(request for request in self.requests if request.window == "measured")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "family": self.family,
            "draw": self.draw,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "total_blocks": self.total_blocks,
            "block_size_tokens": self.block_size_tokens,
            "free_order": self.free_order,
            "extrapolate_prefill_profile": self.extrapolate_prefill_profile,
            "requests": [
                {
                    "request_id": request.request_id,
                    "program_id": request.program_id,
                    "turn_index": request.turn_index,
                    "arrival_offset_seconds": request.arrival_offset_seconds,
                    "segments": [[segment.key, segment.tokens] for segment in request.segments],
                    "is_terminal": request.is_terminal,
                    "next_tool_type": request.next_tool_type,
                    "tool_gap_seconds": request.tool_gap_seconds,
                    "outcome": request.outcome,
                    "window": request.window,
                }
                for request in self.requests
            ],
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def trace_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_trace(trace: SimulationTrace) -> None:
    """Structural validation; the simulator assumes every invariant here."""
    _require(trace.schema_version == TRACE_SCHEMA, "unsupported trace schema")
    _require(trace.block_size_tokens == 16, "Phase 2F pins block size 16")
    _require(trace.total_blocks > 0, "total_blocks must be positive")
    _require(trace.free_order in {"head_first", "tail_first"}, "bad free_order")
    seen: set[str] = set()
    turns: dict[str, list[int]] = {}
    arrivals: dict[str, list[float]] = {}
    max_blocks = 0
    for request in trace.requests:
        _require(request.request_id not in seen, f"duplicate request_id {request.request_id}")
        seen.add(request.request_id)
        _require(request.window in {"warmup", "measured"}, "bad window")
        _require(request.outcome in {"COMPLETED", "CANCELLED"}, "bad outcome")
        _require(request.turn_index >= 1, "turn_index must be >= 1")
        _require(request.arrival_offset_seconds >= 0.0, "arrival must be >= 0")
        if request.is_terminal:
            _require(request.next_tool_type is None, "terminal turn cannot declare a tool")
            _require(request.tool_gap_seconds is None, "terminal turn cannot declare a gap")
            _require(
                request.outcome in {"COMPLETED", "CANCELLED"},
                "terminal turn needs an explicit outcome",
            )
        else:
            _require(request.next_tool_type is not None, "non-terminal turn needs next_tool_type")
            _require(
                request.tool_gap_seconds is not None and request.tool_gap_seconds > 0.0,
                "non-terminal turn needs a positive tool gap",
            )
            _require(request.outcome == "COMPLETED", "only terminal turns may be cancelled")
        total = request.total_tokens
        _require(total > 0, "empty prompt")
        _require(total % 16 == 0, "prompt must be block aligned")
        _require(
            (total - 1) // 16 + 1 <= trace.total_blocks,
            f"request {request.request_id} exceeds cache capacity",
        )
        max_blocks = max(max_blocks, (total - 1) // 16 + 1)
        turns.setdefault(request.program_id, []).append(request.turn_index)
        arrivals.setdefault(request.program_id, []).append(request.arrival_offset_seconds)
    for program_id, indices in turns.items():
        _require(indices == list(range(1, len(indices) + 1)), f"turn_index gap in {program_id}")
        _require(indices[-1] >= 1, "program needs at least one turn")
    for program_id, times in arrivals.items():
        _require(times == sorted(times), f"arrival order violated in {program_id}")
    _require(
        max_blocks <= trace.total_blocks,
        "some request needs more blocks than the pool provides",
    )


def trace_from_dict(payload: dict[str, object]) -> SimulationTrace:
    """Rebuild a trace from its serialized form (used by the loader/tests)."""
    raw_requests = payload["requests"]
    _require(isinstance(raw_requests, list), "requests must be a list")
    requests = []
    for item in raw_requests:
        _require(isinstance(item, dict), "request must be an object")
        raw_segments = item["segments"]
        _require(isinstance(raw_segments, list), "segments must be a list")
        segments = tuple(
            Segment(key=str(entry[0]), tokens=int(entry[1])) for entry in raw_segments
        )
        next_tool = item["next_tool_type"]
        gap = item["tool_gap_seconds"]
        requests.append(
            TraceRequest(
                request_id=str(item["request_id"]),
                program_id=str(item["program_id"]),
                turn_index=int(item["turn_index"]),
                arrival_offset_seconds=float(item["arrival_offset_seconds"]),
                segments=segments,
                is_terminal=bool(item["is_terminal"]),
                next_tool_type=None if next_tool is None else str(next_tool),
                tool_gap_seconds=None if gap is None else float(gap),
                outcome=str(item["outcome"]),
                window=str(item["window"]),
            )
        )
    trace = SimulationTrace(
        schema_version=str(payload["schema_version"]),
        trace_id=str(payload["trace_id"]),
        family=str(payload["family"]),
        draw=int(payload["draw"]),
        seed=int(payload["seed"]),
        generator_version=str(payload["generator_version"]),
        total_blocks=int(payload["total_blocks"]),
        block_size_tokens=int(payload["block_size_tokens"]),
        free_order=str(payload["free_order"]),
        extrapolate_prefill_profile=bool(payload["extrapolate_prefill_profile"]),
        requests=tuple(requests),
    )
    validate_trace(trace)
    return trace
