"""CPU-only contract for a future Phase 5 GPU conformance run.

The module reuses the Phase 5A Workload Seal. It validates a review plan; it
does not authorize or launch GPU work.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum

from .phase5_native_async import (
    NativePressureAllocationRequest,
    PressureBoundary,
    PressureContract,
)
from .phase5_replay import (
    EventKind,
    NSessionReplayPlan,
    ReplayEvent,
    canonical_sha256,
    create_phase5_workload_seal,
    validate_phase5_workload_seal,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_TIE_RULE = "LOGICAL_TIME_PROGRAM_ORDINAL_REQUEST_ORDINAL_V1"
_DISPATCH_RULE = "SERIAL_DISPATCH_IN_FROZEN_ORDER_WITHOUT_COMPLETION_WAIT_V1"


class ConformancePart(StrEnum):
    NATURAL_COMPLETION = "NATURAL_COMPLETION"
    STOP_STRING_AND_ABORT = "STOP_STRING_AND_ABORT"


class Readiness(StrEnum):
    READY_FOR_AUTHORIZATION_REVIEW = "READY_FOR_AUTHORIZATION_REVIEW"
    NOT_READY = "NOT_READY"


class NaturalFinishClass(StrEnum):
    EOS_OR_STOP_TOKEN = "EOS_OR_STOP_TOKEN"
    LENGTH = "LENGTH"
    ABORT = "ABORT"
    ERROR = "ERROR"


def _sha(value: str, name: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ProgramFixture:
    program_id: str
    program_ordinal: int
    request_ids: tuple[str, str]
    request_ordinals: tuple[int, int]
    arrival_offsets_seconds: tuple[float, float]
    prompt_token_ids_sha256: tuple[str, str]
    maximum_prompt_tokens: int
    maximum_generation_tokens: int

    def __post_init__(self) -> None:
        if not self.program_id or self.program_ordinal <= 0:
            raise ValueError("Program identity and ordinal must be positive")
        if self.request_ordinals != (1, 2):
            raise ValueError("each Program must contain request ordinals 1 and 2")
        if len(set(self.request_ids)) != 2 or any(not row for row in self.request_ids):
            raise ValueError("each Program must contain two unique requests")
        previous = -math.inf
        for value in self.arrival_offsets_seconds:
            if not math.isfinite(value) or value < 0 or value < previous:
                raise ValueError("arrival offsets must be finite, non-negative and ordered")
            previous = value
        for value in self.prompt_token_ids_sha256:
            _sha(value, "prompt_token_ids_sha256")
        if self.maximum_prompt_tokens <= 0 or self.maximum_generation_tokens <= 0:
            raise ValueError("prompt and generation token limits must be positive")


@dataclass(frozen=True, slots=True)
class PressureFixture:
    boundary_id: str
    logical_trigger_offset_seconds: float
    trigger_after_native_submission_request_id: str
    trigger_before_request_id: str
    expected_inflight_request_ids: tuple[str, ...]
    pressure_prompt_token_ids: tuple[int, ...]
    pressure_prompt_token_ids_sha256: str
    pressure_prompt_tokens: int
    required_blocks: int
    expected_free_blocks_before: int

    def __post_init__(self) -> None:
        if not self.boundary_id:
            raise ValueError("pressure boundary identity is required")
        if (
            not math.isfinite(self.logical_trigger_offset_seconds)
            or self.logical_trigger_offset_seconds < 0
        ):
            raise ValueError("pressure logical trigger must be finite and non-negative")
        if not self.trigger_after_native_submission_request_id:
            raise ValueError("pressure trigger-after identity is required")
        if not self.trigger_before_request_id:
            raise ValueError("pressure trigger-before identity is required")
        if not self.expected_inflight_request_ids or len(
            set(self.expected_inflight_request_ids)
        ) != len(self.expected_inflight_request_ids):
            raise ValueError("pressure inflight identities must be non-empty and unique")
        _sha(self.pressure_prompt_token_ids_sha256, "pressure token identity")
        if canonical_sha256(list(self.pressure_prompt_token_ids)) != (
            self.pressure_prompt_token_ids_sha256
        ):
            raise ValueError("pressure token identity does not bind the full input")
        if (
            self.pressure_prompt_tokens <= 0
            or self.required_blocks <= 0
            or self.expected_free_blocks_before <= 0
        ):
            raise ValueError("pressure token and block counts must be positive")
        if len(self.pressure_prompt_token_ids) != self.pressure_prompt_tokens:
            raise ValueError("pressure token input length changed")

    def to_native_allocation_request(self, block_size_tokens: int) -> NativePressureAllocationRequest:
        return NativePressureAllocationRequest(
            boundary_id=self.boundary_id,
            pressure_token_ids=self.pressure_prompt_token_ids,
            pressure_token_ids_sha256=self.pressure_prompt_token_ids_sha256,
            block_size_tokens=block_size_tokens,
            required_blocks=self.required_blocks,
            expected_free_blocks_before=self.expected_free_blocks_before,
        )

    def to_native_boundary(self, block_size_tokens: int) -> PressureBoundary:
        return PressureBoundary(
            boundary_id=self.boundary_id,
            logical_timestamp=self.logical_trigger_offset_seconds,
            contract=PressureContract.LIVE_STATE,
            allocation_request=self.to_native_allocation_request(block_size_tokens),
            expected_inflight_request_ids=self.expected_inflight_request_ids,
        )


@dataclass(frozen=True, slots=True)
class GPUResourceBudget:
    gpu_model: str
    minimum_vram_gib: int
    model_id: str
    kv_pool_blocks: int
    block_size_tokens: int
    maximum_context_tokens: int
    engine_max_num_seqs: int
    adapter_maximum_native_inflight: int
    pressure_reserve_blocks: int
    minimum_post_init_free_vram_gib: int
    run_timeout_seconds: int
    shutdown_grace_seconds: int
    reservation_window_seconds: int

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
            "engine_max_num_seqs",
            "adapter_maximum_native_inflight",
            "pressure_reserve_blocks",
            "minimum_post_init_free_vram_gib",
            "run_timeout_seconds",
            "shutdown_grace_seconds",
            "reservation_window_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.engine_max_num_seqs != 4:
            raise ValueError("Engine max_num_seqs must be exactly four")
        if self.adapter_maximum_native_inflight != self.engine_max_num_seqs:
            raise ValueError("Adapter capacity must equal Engine max_num_seqs")
        if self.run_timeout_seconds + self.shutdown_grace_seconds >= (
            self.reservation_window_seconds
        ):
            raise ValueError("resource reservation must exceed run and shutdown bounds")


def derive_native_enqueue_order(
    programs: tuple[ProgramFixture, ...],
) -> tuple[str, ...]:
    """Derive the enqueue contract without trusting a supplied sequence."""

    rows = []
    for program in programs:
        for index, request_id in enumerate(program.request_ids):
            rows.append(
                (
                    program.arrival_offsets_seconds[index],
                    program.program_ordinal,
                    program.request_ordinals[index],
                    request_id,
                )
            )
    rows.sort()
    return tuple(row[3] for row in rows)


def classify_part_a_finish(
    *, finish_reason: str, stop_string_triggered: bool, error_present: bool
) -> NaturalFinishClass:
    """Classify one terminal result without promoting abort/error to success."""

    if error_present:
        return NaturalFinishClass.ERROR
    if stop_string_triggered or finish_reason == "abort":
        return NaturalFinishClass.ABORT
    if finish_reason == "length":
        return NaturalFinishClass.LENGTH
    if finish_reason in {"stop", "eos"}:
        return NaturalFinishClass.EOS_OR_STOP_TOKEN
    return NaturalFinishClass.ERROR


def materialize_phase5e_prompt_token_ids(
    program_ordinal: int, request_ordinal: int
) -> tuple[int, ...]:
    """Materialize 1,984 valid-range IDs with a 1,024-token Program prefix."""

    common = tuple(1000 + index % 97 for index in range(512))
    program = tuple(
        2000 + program_ordinal * 128 + index % 101 for index in range(512)
    )
    request = tuple(
        4000
        + program_ordinal * 2048
        + request_ordinal * 1024
        + index % 509
        for index in range(960)
    )
    return common + program + request


def _pressure_token_ids() -> tuple[int, ...]:
    """Materialize the frozen 24,576-token controlled-pressure input."""

    return tuple(20000 + index % 8192 for index in range(24576))


@dataclass(frozen=True, slots=True)
class Phase5GPUConformancePlan:
    git_sha: str
    vllm_version: str
    programs: tuple[ProgramFixture, ...]
    frozen_native_enqueue_order: tuple[str, ...]
    tie_break_rule: str
    tied_dispatch_rule: str
    workload_seal: Mapping[str, object]
    workload_seal_sha256: str
    model_revision: str
    tokenizer_revision: str
    sampling_parameters: Mapping[str, object]
    sampling_parameters_sha256: str
    engine_configuration_sha256: str
    pressure: PressureFixture
    pressure_input_sha256: str
    resource_budget: GPUResourceBudget
    natural_completion_readiness: Readiness
    abort_readiness: Readiness
    abort_confirmation_source: None
    execution_authorized: bool = False

    def __post_init__(self) -> None:
        if len(self.programs) != 4 or any(
            len(program.request_ids) != 2 for program in self.programs
        ):
            raise ValueError("GPU conformance fixture must contain exactly 4x2 requests")
        if tuple(program.program_ordinal for program in self.programs) != (1, 2, 3, 4):
            raise ValueError("Program ordinals must be exactly 1..4")
        request_ids = tuple(row for program in self.programs for row in program.request_ids)
        if len(set(request_ids)) != 8:
            raise ValueError("request identities must be globally unique")
        derived = derive_native_enqueue_order(self.programs)
        if self.frozen_native_enqueue_order != derived:
            raise ValueError("frozen enqueue order differs from independently derived order")
        arrivals = [
            arrival for program in self.programs for arrival in program.arrival_offsets_seconds
        ]
        if len(arrivals) == len(set(arrivals)):
            raise ValueError("fixture must contain at least one Frozen Arrival tie")
        if self.tie_break_rule != _TIE_RULE or self.tied_dispatch_rule != _DISPATCH_RULE:
            raise ValueError("unsupported arrival ordering or dispatch rule")

        validate_phase5_workload_seal(self.workload_seal)
        if canonical_sha256(self.workload_seal) != self.workload_seal_sha256:
            raise ValueError("workload seal hash mismatch")
        replay = self.workload_seal["replay_plan"]
        assert isinstance(replay, Mapping)
        if tuple(replay["expected_native_enqueue_order"]) != derived:
            raise ValueError("workload seal enqueue order differs from fixture")
        sealed_tokens = self.workload_seal["request_token_ids_sha256"]
        assert isinstance(sealed_tokens, Mapping)
        expected_tokens = {
            request_id: program.prompt_token_ids_sha256[index]
            for program in self.programs
            for index, request_id in enumerate(program.request_ids)
        }
        if dict(sealed_tokens) != expected_tokens:
            raise ValueError("workload seal prompt-token identities differ from fixture")

        if not self.model_revision or not self.tokenizer_revision:
            raise ValueError("model and tokenizer revisions must be frozen")
        _sha(self.sampling_parameters_sha256, "sampling parameters hash")
        if canonical_sha256(dict(self.sampling_parameters)) != (
            self.sampling_parameters_sha256
        ):
            raise ValueError("sampling parameter hash mismatch")
        if self.sampling_parameters.get("max_tokens") != 64:
            raise ValueError("generation max_tokens must be frozen at 64")
        if self.sampling_parameters.get("stop") not in ([], None):
            raise ValueError("Part A cannot contain frontend stop strings")
        _sha(self.engine_configuration_sha256, "Engine configuration hash")
        if self.vllm_version != "0.27.1":
            raise ValueError("GPU conformance is pinned to vLLM 0.27.1")

        pressure = self.pressure
        if pressure.trigger_after_native_submission_request_id != derived[7]:
            raise ValueError("pressure must trigger after all eight submissions")
        if pressure.trigger_before_request_id != "NO_FURTHER_BUSINESS_REQUEST":
            raise ValueError("pressure cannot introduce a ninth business request")
        if pressure.expected_inflight_request_ids != derived[4:]:
            raise ValueError("pressure expected inflight set must equal the second wave")
        if pressure.logical_trigger_offset_seconds <= max(
            program.arrival_offsets_seconds[1] for program in self.programs
        ):
            raise ValueError("pressure must occur after second-wave dispatch")
        if pressure.pressure_prompt_tokens != (
            pressure.required_blocks * self.resource_budget.block_size_tokens
        ):
            raise ValueError("pressure tokens and required blocks are inconsistent")
        _sha(self.pressure_input_sha256, "pressure input hash")
        if canonical_sha256(asdict(pressure)) != self.pressure_input_sha256:
            raise ValueError("pressure input hash mismatch")

        max_prompt = max(program.maximum_prompt_tokens for program in self.programs)
        max_generation = max(
            program.maximum_generation_tokens for program in self.programs
        )
        if max_generation != self.sampling_parameters["max_tokens"]:
            raise ValueError("request and sampling generation limits differ")
        blocks_per_request = math.ceil(max_prompt / self.resource_budget.block_size_tokens)
        blocks_per_request += math.ceil(
            max_generation / self.resource_budget.block_size_tokens
        )
        active_upper = self.resource_budget.engine_max_num_seqs * blocks_per_request
        expected_free = self.resource_budget.kv_pool_blocks - active_upper
        if pressure.expected_free_blocks_before != expected_free:
            raise ValueError("frozen free-block geometry differs from request budget")
        allocation_demand = active_upper + pressure.required_blocks
        oversubscription = allocation_demand - self.resource_budget.kv_pool_blocks
        if active_upper >= self.resource_budget.kv_pool_blocks:
            raise ValueError("active request upper bound leaves no safe KV capacity")
        if allocation_demand < self.resource_budget.kv_pool_blocks:
            raise ValueError("static KV budget cannot create observable pressure")
        if oversubscription > self.resource_budget.pressure_reserve_blocks:
            raise ValueError("static KV pressure exceeds the bounded reserve")

        if self.execution_authorized:
            raise ValueError("Phase 5E plan must not authorize GPU execution")
        if self.natural_completion_readiness is not Readiness.READY_FOR_AUTHORIZATION_REVIEW:
            raise ValueError("natural completion plan is not ready for review")
        if self.abort_readiness is not Readiness.NOT_READY:
            raise ValueError("Phase 5E Abort Conformance must remain NOT_READY")
        if self.abort_confirmation_source is not None:
            raise ValueError("Phase 5E cannot claim an Abort Confirmation source")

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.gpu_conformance_plan.v2",
            "git_sha": self.git_sha,
            "vllm_version": self.vllm_version,
            "programs": [asdict(program) for program in self.programs],
            "frozen_native_enqueue_order": list(self.frozen_native_enqueue_order),
            "tie_break_rule": self.tie_break_rule,
            "tied_dispatch_rule": self.tied_dispatch_rule,
            "workload_seal": dict(self.workload_seal),
            "workload_seal_sha256": self.workload_seal_sha256,
            "model_revision": self.model_revision,
            "tokenizer_revision": self.tokenizer_revision,
            "sampling_parameters": dict(self.sampling_parameters),
            "sampling_parameters_sha256": self.sampling_parameters_sha256,
            "engine_configuration_sha256": self.engine_configuration_sha256,
            "pressure": asdict(self.pressure),
            "pressure_input_sha256": self.pressure_input_sha256,
            "resource_budget": asdict(self.resource_budget),
            "parts": {
                ConformancePart.NATURAL_COMPLETION.value: self.natural_completion_readiness.value,
                ConformancePart.STOP_STRING_AND_ABORT.value: self.abort_readiness.value,
            },
            "abort_confirmation_source": self.abort_confirmation_source,
            "execution_authorized": self.execution_authorized,
        }


def _build_workload_seal(
    programs: tuple[ProgramFixture, ...], order: tuple[str, ...]
) -> Mapping[str, object]:
    events = []
    per_program = {}
    token_hashes = {}
    for program in programs:
        per_program[program.program_id] = program.request_ids
        for index, request_id in enumerate(program.request_ids):
            arrival = program.arrival_offsets_seconds[index]
            token_hashes[request_id] = program.prompt_token_ids_sha256[index]
            events.extend(
                (
                    ReplayEvent(
                        event_id=f"arrival:{request_id}",
                        logical_timestamp=arrival,
                        kind=EventKind.ARRIVAL,
                        program_id=program.program_id,
                        request_id=request_id,
                        turn_index=program.request_ordinals[index],
                        source="PHASE5E_CONTROLLED_FIXTURE",
                    ),
                    ReplayEvent(
                        event_id=f"completion:{request_id}",
                        logical_timestamp=arrival + 1.0,
                        kind=EventKind.COMPLETION,
                        program_id=program.program_id,
                        request_id=request_id,
                        turn_index=program.request_ordinals[index],
                        source="PHASE5E_FROZEN_LOGICAL_COMPLETION_BOUND",
                    ),
                )
            )
    replay = NSessionReplayPlan(
        arrival_plan_sha256=canonical_sha256(
            [
                [program.program_id, list(program.arrival_offsets_seconds)]
                for program in programs
            ]
        ),
        events=tuple(events),
        expected_native_enqueue_order=order,
        per_program_request_order=per_program,
        tie_break_rule=_TIE_RULE,
    )
    return create_phase5_workload_seal(
        workload_id="phase5e-four-program-controlled-conformance-v1",
        source={
            "kind": "CONTROLLED_NATIVE_ADAPTER_CONFORMANCE_FIXTURE",
            "revision": "v1",
            "license": "PROJECT_INTERNAL_TEST_FIXTURE",
            "content_sha256": canonical_sha256(
                [program.program_id for program in programs]
            ),
        },
        request_token_sha256=token_hashes,
        replay_plan=replay,
    )


def build_phase5e_review_candidate(git_sha: str) -> Phase5GPUConformancePlan:
    """Build the non-executable four-Program review candidate."""

    programs = tuple(
        ProgramFixture(
            program_id=f"p{index}",
            program_ordinal=index,
            request_ids=(f"p{index}:r1", f"p{index}:r2"),
            request_ordinals=(1, 2),
            arrival_offsets_seconds=(0.05 * (index - 1), 2.0),
            prompt_token_ids_sha256=(
                canonical_sha256(list(materialize_phase5e_prompt_token_ids(index, 1))),
                canonical_sha256(list(materialize_phase5e_prompt_token_ids(index, 2))),
            ),
            maximum_prompt_tokens=1984,
            maximum_generation_tokens=64,
        )
        for index in range(1, 5)
    )
    order = derive_native_enqueue_order(programs)
    seal = _build_workload_seal(programs, order)
    sampling = {
        "temperature": 0.0,
        "max_tokens": 64,
        "stop": [],
        "include_stop_str_in_output": False,
    }
    pressure_ids = _pressure_token_ids()
    pressure = PressureFixture(
        boundary_id="phase5e-pressure-01",
        logical_trigger_offset_seconds=2.001,
        trigger_after_native_submission_request_id="p4:r2",
        trigger_before_request_id="NO_FURTHER_BUSINESS_REQUEST",
        expected_inflight_request_ids=order[4:],
        pressure_prompt_token_ids=pressure_ids,
        pressure_prompt_token_ids_sha256=canonical_sha256(
            list(pressure_ids)
        ),
        pressure_prompt_tokens=24576,
        required_blocks=1536,
        expected_free_blocks_before=1536,
    )
    return Phase5GPUConformancePlan(
        git_sha=git_sha,
        vllm_version="0.27.1",
        programs=programs,
        frozen_native_enqueue_order=order,
        tie_break_rule=_TIE_RULE,
        tied_dispatch_rule=_DISPATCH_RULE,
        workload_seal=seal,
        workload_seal_sha256=canonical_sha256(seal),
        model_revision="d18ecad881a290f0c792f1c2b5dbee1820d4a424",
        tokenizer_revision="d18ecad881a290f0c792f1c2b5dbee1820d4a424",
        sampling_parameters=sampling,
        sampling_parameters_sha256=canonical_sha256(sampling),
        engine_configuration_sha256=canonical_sha256(
            {
                "max_num_seqs": 4,
                "block_size": 16,
                "kv_pool_blocks": 2048,
                "max_model_len": 32768,
            }
        ),
        pressure=pressure,
        pressure_input_sha256=canonical_sha256(asdict(pressure)),
        resource_budget=GPUResourceBudget(
            gpu_model="NVIDIA GeForce RTX 4090 D",
            minimum_vram_gib=24,
            model_id="Qwen/Qwen2.5-Coder-1.5B-Instruct",
            kv_pool_blocks=2048,
            block_size_tokens=16,
            maximum_context_tokens=32768,
            engine_max_num_seqs=4,
            adapter_maximum_native_inflight=4,
            pressure_reserve_blocks=128,
            minimum_post_init_free_vram_gib=2,
            run_timeout_seconds=600,
            shutdown_grace_seconds=60,
            reservation_window_seconds=1800,
        ),
        natural_completion_readiness=Readiness.READY_FOR_AUTHORIZATION_REVIEW,
        abort_readiness=Readiness.NOT_READY,
        abort_confirmation_source=None,
    )
