"""CPU-only contract for a future Phase 5 GPU conformance run.

This module validates an execution *plan*.  It does not authorize or launch GPU
work and deliberately keeps natural-completion and abort conformance separate.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum

from .phase5_replay import canonical_sha256


class ConformancePart(StrEnum):
    NATURAL_COMPLETION = "NATURAL_COMPLETION"
    STOP_STRING_AND_ABORT = "STOP_STRING_AND_ABORT"


class Readiness(StrEnum):
    READY_FOR_AUTHORIZATION_REVIEW = "READY_FOR_AUTHORIZATION_REVIEW"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True, slots=True)
class ProgramFixture:
    program_id: str
    request_ids: tuple[str, ...]
    arrival_offsets_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.program_id:
            raise ValueError("program_id must be non-empty")
        if not self.request_ids or len(self.request_ids) != len(
            self.arrival_offsets_seconds
        ):
            raise ValueError("fixture requests and arrivals must be non-empty and aligned")
        if len(set(self.request_ids)) != len(self.request_ids):
            raise ValueError("request IDs must be unique within a Program")
        if any(not request_id for request_id in self.request_ids):
            raise ValueError("request IDs must be non-empty")
        previous = -math.inf
        for value in self.arrival_offsets_seconds:
            if not math.isfinite(value) or value < 0 or value < previous:
                raise ValueError("arrival offsets must be finite, non-negative and ordered")
            previous = value


@dataclass(frozen=True, slots=True)
class GPUResourceBudget:
    gpu_model: str
    minimum_vram_gib: int
    model_id: str
    kv_pool_blocks: int
    block_size_tokens: int
    maximum_context_tokens: int
    maximum_native_inflight: int
    timeout_seconds: int
    termination_grace_seconds: int

    def __post_init__(self) -> None:
        if self.gpu_model != "NVIDIA GeForce RTX 4090 D":
            raise ValueError("Phase 5E target GPU must be RTX 4090 D")
        if self.minimum_vram_gib != 24:
            raise ValueError("Phase 5E requires the frozen 24 GiB GPU class")
        if not self.model_id:
            raise ValueError("model_id must be non-empty")
        for name in (
            "kv_pool_blocks",
            "block_size_tokens",
            "maximum_context_tokens",
            "maximum_native_inflight",
            "timeout_seconds",
            "termination_grace_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.maximum_native_inflight < 2:
            raise ValueError("Native inflight capacity must permit at least two requests")


@dataclass(frozen=True, slots=True)
class Phase5GPUConformancePlan:
    git_sha: str
    vllm_version: str
    programs: tuple[ProgramFixture, ...]
    frozen_native_enqueue_order: tuple[str, ...]
    tie_break_rule: str
    pressure_boundary_id: str
    pressure_required_blocks: int
    resource_budget: GPUResourceBudget
    natural_completion_readiness: Readiness
    abort_readiness: Readiness
    abort_confirmation_source: str | None
    execution_authorized: bool = False

    def __post_init__(self) -> None:
        if len(self.programs) != 4:
            raise ValueError("GPU conformance fixture must contain exactly four Programs")
        if len({program.program_id for program in self.programs}) != 4:
            raise ValueError("Program identities must be unique")
        request_ids = tuple(
            request_id
            for program in self.programs
            for request_id in program.request_ids
        )
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("request identities must be globally unique")
        if len(self.frozen_native_enqueue_order) != len(request_ids) or set(
            self.frozen_native_enqueue_order
        ) != set(request_ids):
            raise ValueError("frozen enqueue order must cover every request exactly once")
        arrivals = [
            arrival
            for program in self.programs
            for arrival in program.arrival_offsets_seconds
        ]
        if len(arrivals) == len(set(arrivals)):
            raise ValueError("fixture must contain at least one Frozen Arrival tie")
        if self.tie_break_rule != "LOGICAL_TIME_PROGRAM_ORDINAL_REQUEST_ORDINAL_V1":
            raise ValueError("unsupported Frozen Arrival tie-break rule")
        if not self.pressure_boundary_id or self.pressure_required_blocks <= 0:
            raise ValueError("a positive, identified pressure boundary is required")
        if self.vllm_version != "0.27.1":
            raise ValueError("GPU conformance is pinned to vLLM 0.27.1")
        if self.execution_authorized:
            raise ValueError("Phase 5E plan must not authorize GPU execution")
        if self.natural_completion_readiness is not Readiness.READY_FOR_AUTHORIZATION_REVIEW:
            raise ValueError("natural completion plan is not ready for review")
        if self.abort_readiness is Readiness.READY_FOR_AUTHORIZATION_REVIEW:
            if not self.abort_confirmation_source:
                raise ValueError("abort readiness requires an independent confirmation source")
        elif self.abort_confirmation_source is not None:
            raise ValueError("NOT_READY abort plan cannot claim a confirmation source")

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.gpu_conformance_plan.v1",
            "git_sha": self.git_sha,
            "vllm_version": self.vllm_version,
            "programs": [asdict(program) for program in self.programs],
            "frozen_native_enqueue_order": list(self.frozen_native_enqueue_order),
            "tie_break_rule": self.tie_break_rule,
            "pressure_boundary_id": self.pressure_boundary_id,
            "pressure_required_blocks": self.pressure_required_blocks,
            "resource_budget": asdict(self.resource_budget),
            "parts": {
                ConformancePart.NATURAL_COMPLETION.value: self.natural_completion_readiness.value,
                ConformancePart.STOP_STRING_AND_ABORT.value: self.abort_readiness.value,
            },
            "abort_confirmation_source": self.abort_confirmation_source,
            "execution_authorized": self.execution_authorized,
        }


def build_phase5e_review_candidate(git_sha: str) -> Phase5GPUConformancePlan:
    """Build the non-executable four-Program review candidate."""

    programs = tuple(
        ProgramFixture(
            program_id=f"p{index}",
            request_ids=(f"p{index}:r1", f"p{index}:r2"),
            arrival_offsets_seconds=(0.0 if index <= 2 else 0.05 * (index - 2), 0.4),
        )
        for index in range(1, 5)
    )
    order = (
        "p1:r1",
        "p2:r1",
        "p3:r1",
        "p4:r1",
        "p1:r2",
        "p2:r2",
        "p3:r2",
        "p4:r2",
    )
    return Phase5GPUConformancePlan(
        git_sha=git_sha,
        vllm_version="0.27.1",
        programs=programs,
        frozen_native_enqueue_order=order,
        tie_break_rule="LOGICAL_TIME_PROGRAM_ORDINAL_REQUEST_ORDINAL_V1",
        pressure_boundary_id="phase5e-pressure-01",
        pressure_required_blocks=128,
        resource_budget=GPUResourceBudget(
            gpu_model="NVIDIA GeForce RTX 4090 D",
            minimum_vram_gib=24,
            model_id="Qwen/Qwen2.5-Coder-1.5B-Instruct",
            kv_pool_blocks=2048,
            block_size_tokens=16,
            maximum_context_tokens=32768,
            maximum_native_inflight=4,
            timeout_seconds=600,
            termination_grace_seconds=60,
        ),
        natural_completion_readiness=Readiness.READY_FOR_AUTHORIZATION_REVIEW,
        abort_readiness=Readiness.NOT_READY,
        abort_confirmation_source=None,
    )
