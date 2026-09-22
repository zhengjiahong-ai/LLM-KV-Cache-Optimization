"""Validation-only execution adapter for the final Continuum baseline.

The module deliberately keeps vLLM and MLX imports behind an explicit,
deployment-owned execution factory. The factory supplies facts observed from
the pinned native runtime; this module owns only lifecycle orchestration,
evidence recording, and claim derivation.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    ContinuumConfig,
    FollowupWaiting,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    SystemMonotonicClock,
    TurnFinished,
)
from kvopt.continuum.composition import build_runtime_from_config

SCHEMA = "continuum.phase1b.validation.v1"
PRESSURE_BATCH_SIZE = 32
PRESSURE_TOKEN_COUNT = 512
PRESSURE_SAFETY_CEILING = 64
TARGET_TOKEN_COUNT = 256
_PINNED_BLOCK_SIZE = 16
SCENARIOS = ("controlled_multiturn", "pressure_native_cleanup")
MODES = ("NATIVE", "SHADOW", "CONTROLLED")
DEFAULT_EXECUTION_FACTORY = (
    "scripts.spikes.run_continuum_phase1b_validation_metal:"
    "build_pinned_metal_validation_boundary"
)
DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
DEFAULT_MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
DEFAULT_TOKENIZER = DEFAULT_MODEL
DEFAULT_TOKENIZER_REVISION = DEFAULT_MODEL_REVISION
REQUIRED_CLAIMS = frozenset({
    "program_continuity",
    "nonterminal_retention",
    "scheduler_coordination",
    "native_cleanup",
    "terminal_cleanup",
    "mode_boundaries",
})
_LIFECYCLE_EVENTS = frozenset({
    "REQUEST_ARRIVED",
    "REQUEST_ADMITTED",
    "BLOCKS_OBSERVED",
    "TURN_FINISHED_NON_TERMINAL",
    "TURN_FINISHED_TERMINAL",
    "FOLLOWUP_WAITING",
    "FOLLOWUP_CANCELLED",
})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_finite_non_negative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return number


@dataclass(frozen=True, slots=True)
class PressureResult:
    """Outcome of one bounded, evidence-driven pressure loop."""

    passed: bool
    batches: int
    pressure_requests: int
    stop_reason: str
    observations: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class RequestExecutionEvidence:
    """Facts returned by one real request execution boundary.

    ``request_id`` is the canonical native/internal ID used by Continuum and
    the vLLM scheduler.  ``external_request_id`` is caller/output metadata
    only; it is never sent to ``RuntimeCoordinator`` as its request identity.
    """

    program_id: str
    request_id: str
    native_request_id: str | None
    token_count: int
    prefix_id: str
    block_ids: tuple[int, ...]
    arrival_timestamp: float
    admission_timestamp: float
    finish_timestamp: float
    terminal: bool
    next_tool_type: str | None = None
    external_request_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.program_id, "program_id")
        _require_text(self.request_id, "request_id")
        if self.native_request_id is not None:
            _require_text(self.native_request_id, "native_request_id")
            if self.native_request_id != self.request_id:
                raise ValueError("native_request_id must match canonical request_id")
        if self.external_request_id is not None:
            _require_text(self.external_request_id, "external_request_id")
        _require_positive_int(self.token_count, "token_count")
        _require_text(self.prefix_id, "prefix_id")
        if not isinstance(self.block_ids, tuple):
            raise TypeError("block_ids must be a tuple")
        if any(
            isinstance(block_id, bool) or not isinstance(block_id, int)
            for block_id in self.block_ids
        ):
            raise TypeError("block_ids must contain ints")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("block_ids must be unique")
        arrival = _require_finite_non_negative(
            self.arrival_timestamp, "arrival_timestamp"
        )
        admission = _require_finite_non_negative(
            self.admission_timestamp, "admission_timestamp"
        )
        finish = _require_finite_non_negative(
            self.finish_timestamp, "finish_timestamp"
        )
        if admission < arrival or finish < admission:
            raise ValueError("request timestamps must be monotonic")
        if not isinstance(self.terminal, bool):
            raise TypeError("terminal must be bool")
        if self.terminal and self.next_tool_type is not None:
            raise ValueError("terminal request must not declare next_tool_type")
        object.__setattr__(self, "arrival_timestamp", arrival)
        object.__setattr__(self, "admission_timestamp", admission)
        object.__setattr__(self, "finish_timestamp", finish)


class ValidationExecutionError(RuntimeError):
    """Raised when a real execution boundary cannot prove a frozen claim."""


def _as_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be an observed bool")
    return value


def _required_mapping_field(
    mapping: Mapping[str, object], field_name: str
) -> object:
    if field_name not in mapping:
        raise ValidationExecutionError(
            f"validation evidence is missing required field: {field_name}"
        )
    return mapping[field_name]


def _require_real_pressure_batch(
    completed_request_ids_factory: Callable[[], Sequence[object]],
) -> tuple[str, ...]:
    """Validate one concrete native pressure batch before recording evidence."""
    if not callable(completed_request_ids_factory):
        raise TypeError("completed_request_ids_factory must be callable")
    request_ids = tuple(completed_request_ids_factory())
    if len(request_ids) != PRESSURE_BATCH_SIZE:
        raise ValueError("real pressure batch must complete exactly 32 requests")
    if any(not isinstance(request_id, str) or not request_id for request_id in request_ids):
        raise TypeError("real pressure batch IDs must be non-empty strings")
    if len(set(request_ids)) != PRESSURE_BATCH_SIZE:
        raise ValueError("real pressure batch request IDs must be unique")
    return request_ids


def _qualified_target_token_ids(
    token_count: int, vocabulary_size: int
) -> tuple[int, ...]:
    """Build the deterministic ``r + 1`` target request used by validation."""
    if token_count not in (16, 32, 128, 256, 512):
        raise ValueError("target token count must be a frozen measured point")
    if isinstance(vocabulary_size, bool) or not isinstance(vocabulary_size, int):
        raise TypeError("vocabulary_size must be int")
    if vocabulary_size <= 30_000 + token_count:
        raise ValueError("vocabulary is too small for the qualified target pattern")
    prefix = tuple(
        (1_000 + token_count + index * 37) % vocabulary_size
        for index in range(token_count)
    )
    return prefix + ((30_000 + token_count) % vocabulary_size,)


def _qualified_pressure_token_ids(
    pressure_index: int, vocabulary_size: int
) -> tuple[int, ...]:
    """Build one fresh, deterministic 512-token pressure request."""
    if isinstance(pressure_index, bool) or not isinstance(pressure_index, int):
        raise TypeError("pressure_index must be int")
    if pressure_index < 0:
        raise ValueError("pressure_index must be non-negative")
    if isinstance(vocabulary_size, bool) or not isinstance(vocabulary_size, int):
        raise TypeError("vocabulary_size must be int")
    if vocabulary_size <= 13_000 + PRESSURE_TOKEN_COUNT:
        raise ValueError("vocabulary is too small for the qualified pressure pattern")
    token_ids = (
        0,
        pressure_index % vocabulary_size,
        (pressure_index // vocabulary_size) % vocabulary_size,
        *(
            (13_000 + offset) % vocabulary_size
            for offset in range(PRESSURE_TOKEN_COUNT - 3)
        ),
    )
    if len(token_ids) != PRESSURE_TOKEN_COUNT:
        raise AssertionError("qualified pressure pattern has the wrong length")
    return token_ids


def _controlled_pressure_llm_kwargs(
    base_kwargs: Mapping[str, object],
) -> dict[str, object]:
    """Create native scarcity that requires the protected fallback.

    Pinned vLLM reserves one null block from the configured BlockPool.  The
    override therefore leaves 47 usable blocks: 16 held by R1's protected
    reusable prefix and at most 31 ordinary candidates.  A 512-token pressure
    prefill requires 32 blocks, so a completed ordinary request cannot be
    recycled indefinitely in place of releasing R1.
    """
    protected_target_blocks = TARGET_TOKEN_COUNT // _PINNED_BLOCK_SIZE
    pressure_demand_blocks = PRESSURE_TOKEN_COUNT // _PINNED_BLOCK_SIZE
    kwargs = dict(base_kwargs)
    kwargs.update({
        "num_gpu_blocks_override": protected_target_blocks + pressure_demand_blocks,
        "max_model_len": PRESSURE_TOKEN_COUNT + _PINNED_BLOCK_SIZE,
        "max_num_batched_tokens": PRESSURE_TOKEN_COUNT + _PINNED_BLOCK_SIZE,
    })
    return kwargs


class ValidationExecutionAdapter:
    """Translate real runtime boundary facts into validation lifecycle evidence.

    The adapter deliberately owns orchestration and claim derivation only.  A
    deployment-specific factory supplies request, pressure, and mode callables
    backed by the pinned Metal/vLLM runtime; no native state is synthesized in
    this module.
    """

    def __init__(
        self,
        *,
        run: ValidationRun,
        runtime: Any,
        clock: Any,
        request_executor: Callable[[str, str, bool], RequestExecutionEvidence],
        pressure_batch_executor: Callable[[int], Mapping[str, object]],
        pressure_observer: Callable[[], Mapping[str, object]],
        mode_executor: Callable[[str], Mapping[str, object]],
        scheduler_executor: Callable[[Any, tuple[RequestIdentity, ...]], Mapping[str, object]],
        followup_request_executor: Callable[[str, str], RequestExecutionEvidence]
        | None = None,
        ordinary_request_executor: Callable[[str, str], RequestExecutionEvidence]
        | None = None,
    ) -> None:
        if not isinstance(run, ValidationRun):
            raise TypeError("run must be ValidationRun")
        if not callable(getattr(runtime, "handle", None)):
            raise TypeError("runtime must provide handle")
        if not callable(request_executor):
            raise TypeError("request_executor must be callable")
        for callback, name in (
            (pressure_batch_executor, "pressure_batch_executor"),
            (pressure_observer, "pressure_observer"),
            (mode_executor, "mode_executor"),
            (scheduler_executor, "scheduler_executor"),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if followup_request_executor is not None and not callable(
            followup_request_executor
        ):
            raise TypeError("followup_request_executor must be callable")
        if ordinary_request_executor is not None and not callable(
            ordinary_request_executor
        ):
            raise TypeError("ordinary_request_executor must be callable")
        self.run = run
        self.runtime = runtime
        self.clock = clock
        self._request_executor = request_executor
        self._pressure_batch_executor = pressure_batch_executor
        self._pressure_observer = pressure_observer
        self._mode_executor = mode_executor
        self._scheduler_executor = scheduler_executor
        self._followup_request_executor = followup_request_executor
        self._ordinary_request_executor = ordinary_request_executor
        self._actual_pressure_requests = 0
        self._pressure_seen_request_ids: set[str] = set()
        self._pressure_batches_seen: set[int] = set()

    def _record_request(
        self, evidence: RequestExecutionEvidence, *, complete: bool = True
    ) -> None:
        program = ProgramIdentity(evidence.program_id)
        request = RequestIdentity(evidence.request_id)
        self.run.record_request(
            evidence.program_id,
            evidence.request_id,
            native_request_id=evidence.native_request_id,
            external_request_id=evidence.external_request_id,
        )
        self.runtime.handle(
            RequestArrived(program, request, evidence.arrival_timestamp)
        )
        self.run.record_lifecycle(
            evidence.program_id, evidence.request_id, "REQUEST_ARRIVED"
        )
        if not complete:
            return
        self.runtime.handle(
            RequestAdmitted(program, request, evidence.admission_timestamp)
        )
        self.run.record_lifecycle(
            evidence.program_id, evidence.request_id, "REQUEST_ADMITTED"
        )

        if evidence.terminal:
            self.runtime.handle(
                TurnFinished(
                    program,
                    request,
                    evidence.finish_timestamp,
                    is_terminal=True,
                )
            )
            self.run.record_lifecycle(
                evidence.program_id,
                evidence.request_id,
                "TURN_FINISHED_TERMINAL",
            )
            return

        prefix = PrefixIdentity(evidence.prefix_id)
        blocks = tuple(BlockIdentity(block_id) for block_id in evidence.block_ids)
        self.run.record_actual_token_count(
            evidence.program_id, evidence.request_id, evidence.token_count
        )
        self.runtime.record_prefill_context_token_count(
            PrefillContextTokenCountRecord(
                program_id=program,
                request_id=request,
                prefix_id=prefix,
                token_count=evidence.token_count,
                provenance=InputProvenance(InputSource.OBSERVED),
            )
        )
        self.runtime.handle(
            BlocksObserved(
                program,
                request,
                prefix,
                blocks,
                evidence.finish_timestamp,
            )
        )
        self.run.record_prefix_observation(
            program_id=evidence.program_id,
            request_id=evidence.request_id,
            prefix_id=evidence.prefix_id,
            block_ids=evidence.block_ids,
        )
        self.run.record_lifecycle(
            evidence.program_id, evidence.request_id, "BLOCKS_OBSERVED"
        )
        self.runtime.handle(
            TurnFinished(
                program,
                request,
                evidence.finish_timestamp,
                is_terminal=False,
                next_tool_type=evidence.next_tool_type,
            )
        )
        self.run.record_lifecycle(
            evidence.program_id,
            evidence.request_id,
            "TURN_FINISHED_NON_TERMINAL",
        )

    def _retention_entry(
        self, evidence: RequestExecutionEvidence
    ) -> Any | None:
        for entry in self.runtime.retention.planning_snapshots():
            if (
                entry.program_id.value == evidence.program_id
                and entry.prefix_id.canonical_value == evidence.prefix_id
                and entry.ttl_decision.request_id.value == evidence.request_id
            ):
                return entry
        return None

    def run_controlled_multiturn(
        self,
        *,
        program_id: str = "program-validation",
        retention_observer: Callable[[Any, RequestExecutionEvidence], bool]
        | None = None,
        terminal_observer: Callable[[Any, RequestExecutionEvidence], bool]
        | None = None,
    ) -> bool:
        """Execute one retained turn, staged competition, and terminal cleanup."""
        program_name = _require_text(program_id, "program_id")
        retention_observer = retention_observer or (
            lambda _runtime, evidence: self._retention_entry(evidence) is not None
            and any(
                entry.protected
                for entry in self.runtime.retention.planning_snapshots()
                if entry.program_id.value == evidence.program_id
                and entry.prefix_id.canonical_value == evidence.prefix_id
            )
        )
        terminal_observer = terminal_observer or (
            lambda _runtime, evidence: not any(
                entry.program_id.value == evidence.program_id
                for entry in self.runtime.retention.planning_snapshots()
            )
        )
        evidence = [self._request_executor(program_name, "request-1", False)]
        if len({item.request_id for item in evidence}) != 1 or any(
            item.program_id != program_name or item.terminal for item in evidence
        ):
            self.run.record_claim(
                "program_continuity",
                False,
                failure_reason="two distinct requests for one program were not observed",
            )
            self.run.record_scenario(
                "controlled_multiturn", passed=False, evidence={}
            )
            raise ValueError("program continuity evidence is incomplete")

        try:
            for item in evidence:
                self._record_request(item)
                entry = self._retention_entry(item)
                if entry is None or not retention_observer(self.runtime, item):
                    raise ValueError("nonterminal retention evidence was not observed")
                ttl_input = entry.ttl_decision.ttl_input
                self.run.record_ttl_decision(
                    item.program_id,
                    item.request_id,
                    token_count=item.token_count,
                    prefill_reload_seconds=ttl_input.prefill_reload_seconds,
                    provenance=ttl_input.prefill_reload_provenance.source.value,
                )
                self.run.record_retention_transition(
                    program_id=item.program_id,
                    request_id=item.request_id,
                    protected=entry.protected,
                    deadline_timestamp=entry.deadline_timestamp,
                    observed=True,
                )

            waiting = (
                self._request_executor(program_name, "request-followup", False)
                if self._followup_request_executor is None
                else self._followup_request_executor(program_name, "request-followup")
            )
            if waiting.program_id != program_name or waiting.terminal:
                raise ValueError("waiting follow-up evidence is invalid")
            if waiting.request_id in {item.request_id for item in evidence}:
                raise ValueError("waiting follow-up must use a new native request ID")
            self._record_request(waiting, complete=False)
            waiting_request = RequestIdentity(waiting.request_id)
            self.runtime.handle(
                FollowupWaiting(
                    ProgramIdentity(program_name),
                    waiting_request,
                    waiting.arrival_timestamp,
                )
            )
            self.run.record_lifecycle(
                program_name, waiting.request_id, "FOLLOWUP_WAITING"
            )
            ordinary = (
                self._request_executor("ordinary-program", "request-ordinary", False)
                if self._ordinary_request_executor is None
                else self._ordinary_request_executor(
                    "ordinary-program", "request-ordinary"
                )
            )
            if ordinary.program_id == program_name or ordinary.terminal:
                raise ValueError("ordinary competing request evidence is invalid")
            if ordinary.request_id in {item.request_id for item in evidence} | {
                waiting.request_id
            }:
                raise ValueError("ordinary request must use a new native request ID")
            self._record_request(ordinary, complete=False)
            ordinary_request = RequestIdentity(ordinary.request_id)
            # The native FCFS snapshot is intentionally ordinary-first; the
            # Continuum policy must produce the protected follow-up first.
            request_ids = (ordinary_request, waiting_request)
            candidates = tuple(self.runtime.scheduler_candidates(request_ids))
            candidate_by_id = {candidate.request_id: candidate for candidate in candidates}
            followup_candidate = candidate_by_id.get(waiting_request)
            ordinary_candidate = candidate_by_id.get(ordinary_request)
            if (
                followup_candidate is None
                or followup_candidate.is_followup is not True
                or followup_candidate.program_is_protected is not True
                or ordinary_candidate is None
                or ordinary_candidate.is_followup is not False
                or ordinary_candidate.program_is_protected is not False
            ):
                raise ValueError("scheduler candidate protection evidence is incomplete")
            scheduler_evidence = self._scheduler_executor(self.runtime, request_ids)
            if not isinstance(scheduler_evidence, Mapping):
                raise TypeError("scheduler hook evidence must be a mapping")
            scheduler_values = dict(scheduler_evidence)
            required_scheduler_evidence = {
                "hook_boundary": "vllm.scheduler.schedule",
                "hook_installed": True,
                "real_runtime_observed": True,
                "hook_exercised": True,
            }
            if any(
                scheduler_values.get(field) != expected
                for field, expected in required_scheduler_evidence.items()
            ):
                raise ValueError("scheduler hook evidence is incomplete")
            required_fields = (
                "waiting_request_ids",
                "ordered_request_ids",
                "completed_native_request_ids",
                "completed_external_request_ids",
                "followup_request_id",
                "ordinary_request_id",
                "completion_ordering",
            )
            if any(field not in scheduler_values for field in required_fields):
                raise ValidationExecutionError(
                    "scheduler hook evidence is missing required fields"
                )
            waiting_ids = tuple(scheduler_values["waiting_request_ids"])
            ordered_ids = tuple(scheduler_values["ordered_request_ids"])
            completed_ids = tuple(scheduler_values["completed_native_request_ids"])
            for ids, field_name in (
                (waiting_ids, "waiting_request_ids"),
                (ordered_ids, "ordered_request_ids"),
                (completed_ids, "completed_native_request_ids"),
            ):
                if any(not isinstance(request_id, str) or not request_id for request_id in ids):
                    raise TypeError(f"scheduler {field_name} must contain native IDs")
            if not waiting_ids or len(waiting_ids) != len(set(waiting_ids)):
                raise ValueError("scheduler hook waiting IDs are incomplete")
            if set(waiting_ids) != {waiting.request_id, ordinary.request_id}:
                raise ValueError("scheduler hook waiting IDs do not match staged requests")
            if set(completed_ids) != set(waiting_ids):
                raise ValueError("scheduler hook completion evidence is incomplete")
            if set(ordered_ids) != set(waiting_ids) or len(ordered_ids) != len(waiting_ids):
                raise ValueError("scheduler hook ordering evidence is incomplete")
            if waiting_ids[0] != ordinary.request_id:
                raise ValueError("scheduler native input was not ordinary-first")
            if ordered_ids[0] != waiting.request_id:
                raise ValueError("scheduler hook output was not follow-up-first")
            if scheduler_values["followup_request_id"] != waiting.request_id:
                raise ValueError("scheduler hook used the wrong follow-up request ID")
            if scheduler_values["ordinary_request_id"] != ordinary.request_id:
                raise ValueError("scheduler hook used the wrong ordinary request ID")
            completed_external_ids = scheduler_values[
                "completed_external_request_ids"
            ]
            if not isinstance(completed_external_ids, (tuple, list)):
                raise TypeError("scheduler completion external IDs are incomplete")
            if len(completed_external_ids) != len(completed_ids) or any(
                not isinstance(request_id, str) or not request_id
                for request_id in completed_external_ids
            ):
                raise ValueError("scheduler completion ID normalization is incomplete")
            self.run.record_scheduler_order(
                **scheduler_values,
                observed=True,
            )

            terminal = self._request_executor(program_name, "request-3", True)
            if terminal.program_id != program_name or not terminal.terminal:
                raise ValueError("terminal request evidence is invalid")
            self._record_request(terminal)
            if not terminal_observer(self.runtime, terminal):
                raise ValueError("terminal cleanup evidence was not observed")

            distinct_request_ids = [item.request_id for item in (*evidence, terminal)]
            self.run.record_claim(
                "program_continuity",
                len(set(distinct_request_ids)) >= 2,
                evidence={"distinct_request_ids": distinct_request_ids},
                failure_reason="request IDs were not distinct"
                if len(set(distinct_request_ids)) < 2
                else None,
            )
            self.run.record_claim(
                "nonterminal_retention",
                True,
                evidence={"observed_nonterminal_turns": len(evidence)},
            )
            self.run.record_claim(
                "scheduler_coordination",
                True,
                evidence={"ordered_ids": list(ordered_ids), **scheduler_values},
            )
            self.run.record_claim(
                "terminal_cleanup",
                True,
                evidence={"program_id": terminal.program_id},
            )
            self.run.record_scenario(
                "controlled_multiturn",
                passed=True,
                evidence={
                    "request_ids": distinct_request_ids,
                    "staged_followup_request_id": waiting.request_id,
                    "staged_ordinary_request_id": ordinary.request_id,
                    "terminal_cleanup_observed": True,
                },
            )
            return True
        except Exception as error:
            message = str(error)
            if "retention evidence" in message:
                claim = "nonterminal_retention"
            elif "terminal cleanup" in message:
                claim = "terminal_cleanup"
            elif "scheduler" in message:
                claim = "scheduler_coordination"
            else:
                claim = "program_continuity"
            self.run.record_claim(claim, False, failure_reason=message)
            self.run.record_scenario(
                "controlled_multiturn", passed=False, evidence={"error": message}
            )
            raise


    def run_pressure_native_cleanup(self) -> bool:
        """Run evidence-driven serial pressure with a strict 32-request batch."""
        actual_batches: list[dict[str, object]] = []

        def run_batch(batch_number: int) -> None:
            result = self._pressure_batch_executor(batch_number)
            if not isinstance(result, Mapping):
                raise TypeError("pressure batch must return a mapping")
            if batch_number in self._pressure_batches_seen:
                raise ValidationExecutionError("pressure batch was executed twice")
            self._pressure_batches_seen.add(batch_number)
            request_ids = _required_mapping_field(
                result, "completed_native_request_ids"
            )
            if not isinstance(request_ids, (tuple, list)):
                raise TypeError("pressure batch must expose completed request IDs")
            completed = _require_real_pressure_batch(lambda: tuple(request_ids))
            if self._pressure_seen_request_ids.intersection(completed):
                raise ValidationExecutionError(
                    "pressure batches must use fresh native request IDs"
                )
            self._pressure_seen_request_ids.update(completed)
            self._actual_pressure_requests += len(completed)
            actual_batches.append({
                "batch": batch_number,
                "completed_request_count": len(completed),
                "completed_native_request_ids": list(completed),
            })

        def observe() -> Mapping[str, object]:
            observation = self._pressure_observer()
            if not isinstance(observation, Mapping):
                raise TypeError("pressure observer must return a mapping")
            copied = dict(observation)
            copied["actual_pressure_requests"] = self._actual_pressure_requests
            self.run.record_pressure_observation(**copied)
            return copied

        def evidence_ready(observation: Mapping[str, object]) -> bool:
            target_present = _as_bool(
                _required_mapping_field(observation, "target_present"),
                "target_present",
            )
            release_observed = _as_bool(
                _required_mapping_field(observation, "retention_release_observed"),
                "retention_release_observed",
            )
            plan_validated = _as_bool(
                _required_mapping_field(observation, "plan_validated"),
                "plan_validated",
            )
            native_eviction = _as_bool(
                _required_mapping_field(
                    observation, "native_eviction_callback_observed"
                ),
                "native_eviction_callback_observed",
            )
            block_id = _required_mapping_field(observation, "evicted_block_id")
            if not (not target_present and release_observed and plan_validated):
                return False
            if native_eviction:
                if isinstance(block_id, int) and not isinstance(block_id, bool):
                    self.run.record_native_cleanup(block_id, evicted=True)
                return True
            return False

        try:
            result = run_adaptive_pressure(
                run_batch=run_batch,
                observe=observe,
                evidence_ready=evidence_ready,
            )
        except Exception as error:
            message = str(error)
            self.run.record_claim("native_cleanup", False, failure_reason=message)
            self.run.record_scenario(
                "pressure_native_cleanup",
                passed=False,
                evidence={
                    "actual_pressure_requests": self._actual_pressure_requests,
                    "batches": actual_batches,
                    "error": message,
                },
            )
            raise

        if not result.passed:
            reason = "native cleanup evidence was not observed before safety ceiling"
            self.run.record_claim("native_cleanup", False, failure_reason=reason)
            self.run.record_scenario(
                "pressure_native_cleanup",
                passed=False,
                evidence={
                    "actual_pressure_requests": self._actual_pressure_requests,
                    "batches": actual_batches,
                    "stop_reason": result.stop_reason,
                },
            )
            return False

        self.run.record_claim(
            "native_cleanup",
            True,
            evidence={
                "actual_pressure_requests": self._actual_pressure_requests,
                "batches": actual_batches,
                "pressure_requests": result.pressure_requests,
            },
        )
        self.run.record_scenario(
            "pressure_native_cleanup",
            passed=True,
            evidence={
                "actual_pressure_requests": self._actual_pressure_requests,
                "batches": actual_batches,
            },
        )
        return True

    def run_mode_smokes(self) -> bool:
        """Run isolated mode boundaries and validate mode-specific predicates."""
        try:
            for mode in MODES:
                evidence = self._mode_executor(mode)
                if not isinstance(evidence, Mapping):
                    raise TypeError("mode evidence must be a mapping")
                values = dict(evidence)
                reported_mode = values.pop("mode", None)
                if reported_mode is not None and reported_mode != mode:
                    raise ValueError(
                        f"mode evidence reported {reported_mode!r} for {mode}"
                    )
                real_runtime_observed = values.get("real_runtime_observed") is True
                if mode == "NATIVE":
                    valid = (
                        values.get("queue_mutated") is False
                        and values.get("continuum_invoked") is False
                        and values.get("native_path_succeeded") is True
                        and values.get("hook_installed") is False
                        and values.get("hook_exercised") is False
                        and real_runtime_observed
                    )
                elif mode == "SHADOW":
                    valid = (
                        values.get("hypothetical_plan_available") is True
                        and values.get("queue_mutated") is False
                        and values.get("hook_installed") is True
                        and values.get("hook_exercised") is True
                        and values.get("continuum_invoked") is True
                        and real_runtime_observed
                    )
                else:
                    valid = (
                        values.get("queue_mutated") is True
                        and values.get("hook_installed") is True
                        and values.get("hook_exercised") is True
                        and values.get("ordering_outcome") == "followup_before_ordinary"
                        and real_runtime_observed
                    )
                if not valid:
                    raise ValueError(f"mode evidence is incomplete for {mode}")
                self.run.record_mode_evidence(mode, **values)
            self.run.record_claim(
                "mode_boundaries", True, evidence={"modes": list(MODES)}
            )
            return True
        except Exception as error:
            message = str(error)
            self.run.record_claim("mode_boundaries", False, failure_reason=message)
            raise

    def execute(
        self,
        *,
        artifact_path: str | Path | None = None,
        scenario_executor: Callable[[], object] | None = None,
        scenarios: tuple[str, ...] = SCENARIOS,
        modes: tuple[str, ...] = MODES,
    ) -> bool:
        """Execute selected scenarios and write incomplete artifacts on failure."""
        if artifact_path is not None:
            self.run.write_artifact(artifact_path)
        try:
            if scenario_executor is not None:
                scenario_executor()
            else:
                if "controlled_multiturn" in scenarios:
                    self.run_controlled_multiturn()
                if "pressure_native_cleanup" in scenarios:
                    self.run_pressure_native_cleanup()
            if set(scenarios) == set(SCENARIOS) and set(modes) == set(MODES):
                self.run_mode_smokes()
            else:
                raise ValueError("complete validation requires both scenarios and all modes")
            artifact = self.run.finalize()
            if artifact_path is not None:
                self.run.write_artifact(artifact_path)
            return artifact["status"] == "complete"
        except Exception as error:
            self.run.record_claim(
                "mode_boundaries",
                False,
                failure_reason=f"execution failed: {type(error).__name__}: {error}",
            )
            self.run.finalize()
            if artifact_path is not None:
                self.run.write_artifact(artifact_path)
            raise


def _parse_execution_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--execution-factory",
        default=DEFAULT_EXECUTION_FACTORY,
        help="optional test/deployment override for the pinned Metal boundary",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    parser.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    parser.add_argument(
        "--tokenizer-revision", default=DEFAULT_TOKENIZER_REVISION
    )
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.8)
    parser.add_argument(
        "--vllm-metal-source-checkout", type=Path, required=True
    )
    parser.add_argument(
        "--scenario", choices=("all", *SCENARIOS), default="all"
    )
    parser.add_argument("--mode", choices=("all", *MODES), default="all")
    parser.add_argument("--child-mode", choices=MODES, default=None)
    return parser.parse_args(argv)


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ("git", "rev-parse", "HEAD"),
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValidationExecutionError("unable to resolve validation Git SHA") from error


def _load_factory(specification: str) -> Callable[..., object]:
    module_name, separator, function_name = specification.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError("execution-factory must have module:function form")
    module = importlib.import_module(module_name)
    factory = getattr(module, function_name, None)
    if not callable(factory):
        raise TypeError("execution-factory must resolve to a callable")
    return factory


def _build_execution_adapter(
    *,
    factory: Callable[..., object],
    run: ValidationRun,
    runtime: Any,
    clock: Any,
    arguments: argparse.Namespace,
) -> ValidationExecutionAdapter:
    """Build the adapter from one explicit deployment-owned real boundary."""
    # These modules are intentionally imported only after explicit execution.
    observation_helpers = importlib.import_module(
        "scripts.spikes.run_continuum_vllm_observation"
    )
    prefill_helpers = importlib.import_module(
        "scripts.spikes.run_continuum_prefill_profile_metal"
    )
    boundary = factory(
        runtime=runtime,
        clock=clock,
        run=run,
        arguments=arguments,
        observation_helpers=observation_helpers,
        prefill_helpers=prefill_helpers,
    )
    if isinstance(boundary, ValidationExecutionAdapter):
        return boundary
    if not isinstance(boundary, Mapping):
        raise TypeError("execution factory must return a boundary mapping")
    required = {
        "request_executor",
        "pressure_batch_executor",
        "pressure_observer",
        "mode_executor",
    }
    missing = sorted(required - set(boundary))
    if missing:
        raise ValueError("execution boundary is missing: " + ", ".join(missing))
    scheduler_executor = boundary.get("scheduler_executor")
    if not callable(scheduler_executor):
        raise TypeError("execution boundary is missing: scheduler_executor")
    return ValidationExecutionAdapter(
        run=run,
        runtime=runtime,
        clock=clock,
        request_executor=boundary["request_executor"],
        pressure_batch_executor=boundary["pressure_batch_executor"],
        pressure_observer=boundary["pressure_observer"],
        mode_executor=boundary["mode_executor"],
        scheduler_executor=scheduler_executor,
        followup_request_executor=boundary.get("followup_request_executor"),
        ordinary_request_executor=boundary.get("ordinary_request_executor"),
    )


def _child_command(
    mode: str, arguments: argparse.Namespace
) -> list[str]:
    """Build the repository-owned command used for one isolated mode child."""
    command = [
        sys.executable,
        "-m",
        "scripts.spikes.run_continuum_phase1b_validation_metal",
        "--child-mode",
        mode,
        "--profile-path",
        str(arguments.profile_path),
        "--output-dir",
        str(arguments.output_dir),
        "--run-id",
        arguments.run_id,
        "--model",
        arguments.model,
        "--model-revision",
        arguments.model_revision,
        "--tokenizer",
        arguments.tokenizer,
        "--tokenizer-revision",
        arguments.tokenizer_revision,
        "--gpu-memory-utilization",
        str(arguments.gpu_memory_utilization),
        "--vllm-metal-source-checkout",
        str(arguments.vllm_metal_source_checkout),
    ]
    return command


def _run_mode_child(
    mode: str,
    *,
    arguments: argparse.Namespace,
    runner: Callable[..., Any] | None = None,
) -> Mapping[str, object]:
    """Run one mode in a fresh interpreter and decode its evidence payload."""
    mode_name = _require_text(mode, "mode").upper()
    if mode_name not in MODES:
        raise ValueError(f"unsupported mode: {mode_name}")
    run_process = subprocess.run if runner is None else runner
    completed = run_process(
        _child_command(mode_name, arguments),
        check=False,
        capture_output=True,
        text=True,
    )
    if getattr(completed, "returncode", 1) != 0:
        stderr = str(getattr(completed, "stderr", "")).strip()
        raise ValidationExecutionError(
            f"{mode_name} child failed"
            + (f": {stderr}" if stderr else "")
        )
    stdout = str(getattr(completed, "stdout", "")).strip()
    if not stdout:
        raise ValidationExecutionError(f"{mode_name} child returned no evidence")
    try:
        evidence = json.loads(stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise ValidationExecutionError(
            f"{mode_name} child returned invalid evidence"
        ) from error
    if not isinstance(evidence, Mapping):
        raise ValidationExecutionError(f"{mode_name} child evidence is not a mapping")
    if evidence.get("mode") != mode_name or evidence.get("status") != "PASS":
        raise ValidationExecutionError(f"{mode_name} child evidence is incomplete")
    return dict(evidence)


class _PinnedMetalValidationBoundary:
    """Lazy, validation-only boundary for the pinned Metal runtime.

    Construction is intentionally side-effect free.  The first real callback
    lazily imports and boots the pinned vLLM runtime.  The parent process uses
    fresh child interpreters for mode hooks; no uninstall/reset protocol is
    required or implemented here.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        clock: Any,
        run: ValidationRun,
        arguments: argparse.Namespace,
        observation_helpers: Any,
        prefill_helpers: Any,
    ) -> None:
        self.runtime = runtime
        self.clock = clock
        self.run = run
        self.arguments = arguments
        self.observation_helpers = observation_helpers
        self.prefill_helpers = prefill_helpers
        self._real_runtime: Any | None = None
        self._controlled_child: Mapping[str, object] | None = None
        self._registry: Any | None = None
        self._native_observations: list[dict[str, object]] = []
        self._request_counter = 0
        self._observation_hook_set: Any | None = None
        self._controlled_runtime_id: str | None = None
        self._last_pressure_batch: int | None = None

    def _ensure_real_runtime(self) -> Any:
        if self._real_runtime is not None:
            return self._real_runtime
        try:
            from vllm import LLM
        except ImportError as error:  # pragma: no cover - deployment-only path.
            raise ValidationExecutionError(
                "pinned Metal validation requires the pinned vLLM runtime"
            ) from error
        kwargs = self.observation_helpers.build_llm_kwargs(self.arguments)
        self._real_runtime = LLM(**kwargs)
        self._registry = self.observation_helpers.ProgramRequestRegistry()
        from vllm.v1.core.block_pool import BlockPool
        from vllm.v1.core.sched.scheduler import Scheduler

        recorder = self.observation_helpers.NativeObservationRecorder(
            self._registry, self._native_observations.append
        )
        bindings = self.observation_helpers.build_vllm_hook_bindings(
            Scheduler, BlockPool
        )
        self._observation_hook_set = self.observation_helpers.ObservationHookSet(
            bindings, recorder, enabled=True
        )
        self._observation_hook_set.__enter__()
        return self._real_runtime

    def _request_executor(
        self, program_id: str, external_request_id: str, terminal: bool
    ) -> RequestExecutionEvidence:
        """Submit through the deployment runtime and return native-ID evidence.

        The pinned runtime adapter is deliberately strict: a deployment that
        cannot expose a native/internal ID and a read-only block observation
        must fail rather than infer either fact from an external ID.
        """
        staged_index = {
            "request-1": 0,
            "request-followup": 1,
            "request-ordinary": 2,
            "request-3": 3,
        }.get(external_request_id)
        if staged_index is not None:
            child = self._ensure_controlled_child()
            records = _required_mapping_field(child, "lifecycle_request_evidence")
            if not isinstance(records, (tuple, list)) or staged_index >= len(records):
                raise ValidationExecutionError(
                    "controlled child lifecycle request evidence is incomplete"
                )
            record = records[staged_index]
            if not isinstance(record, Mapping):
                raise ValidationExecutionError(
                    "controlled child lifecycle request evidence is invalid"
                )
            if record.get("program_id") != program_id or record.get("terminal") is not terminal:
                raise ValidationExecutionError(
                    "controlled child lifecycle request identity is inconsistent"
                )
            return RequestExecutionEvidence(
                program_id=record["program_id"],
                request_id=record["request_id"],
                native_request_id=record["native_request_id"],
                external_request_id=record["external_request_id"],
                token_count=record["token_count"],
                prefix_id=record["prefix_id"],
                block_ids=tuple(record["block_ids"]),
                arrival_timestamp=record["arrival_timestamp"],
                admission_timestamp=record["admission_timestamp"],
                finish_timestamp=record["finish_timestamp"],
                terminal=record["terminal"],
                next_tool_type=record["next_tool_type"],
            )
        llm = self._ensure_real_runtime()
        try:
            from vllm import SamplingParams
        except ImportError as error:  # pragma: no cover - deployment-only path.
            raise ValidationExecutionError(
                "pinned runtime requires vLLM SamplingParams"
            ) from error
        prompt = f"continuum phase1b {program_id} {self._request_counter}"
        self._request_counter += 1
        submitted_at = float(self.clock.now())
        native_ids = tuple(
            llm.enqueue(
                [prompt],
                SamplingParams(max_tokens=1, temperature=0.0, seed=0),
                use_tqdm=False,
            )
        )
        if len(native_ids) != 1 or not isinstance(native_ids[0], str):
            raise ValidationExecutionError("native enqueue did not return one ID")
        native_id = native_ids[0]
        self._registry.register_batch((program_id,), native_ids)
        external_ids = self.observation_helpers._external_request_ids_for_internal(
            llm, native_ids
        )
        if len(external_ids) != 1 or not isinstance(external_ids[0], str):
            raise ValidationExecutionError(
                "native request did not expose one external correlation ID"
            )
        self._registry.register_external_batch(native_ids, external_ids)
        outputs = tuple(llm.wait_for_completion(use_tqdm=False))
        if not outputs:
            raise ValidationExecutionError("native request produced no completion")
        finish_timestamp = max(submitted_at, float(self.clock.now()))
        prefix_id, token_count, block_ids, _hashes = _coherent_child_request_snapshot(
            self._native_observations,
            native_id,
        )
        return RequestExecutionEvidence(
            program_id=program_id,
            request_id=native_id,
            native_request_id=native_id,
            external_request_id=external_ids[0],
            token_count=token_count,
            prefix_id=prefix_id,
            block_ids=block_ids,
            arrival_timestamp=submitted_at,
            admission_timestamp=submitted_at,
            finish_timestamp=finish_timestamp,
            terminal=terminal,
            next_tool_type=None if terminal else "search",
        )

    def _scheduler_executor(
        self, _runtime: Any, request_ids: tuple[RequestIdentity, ...]
    ) -> Mapping[str, object]:
        """Delegate scheduler ordering to the installed native hook boundary."""
        child = self._ensure_controlled_child()
        waiting = tuple(
            _required_mapping_field(child, "waiting_request_ids")  # type: ignore[arg-type]
        )
        ordered = tuple(
            _required_mapping_field(child, "ordered_request_ids")  # type: ignore[arg-type]
        )
        completed_native = tuple(
            _required_mapping_field(child, "completed_native_request_ids")  # type: ignore[arg-type]
        )
        for field in (
            "hook_exercised",
            "hook_installed",
            "real_runtime_observed",
            "followup_request_id",
            "ordinary_request_id",
            "completion_ordering",
        ):
            _required_mapping_field(child, field)  # type: ignore[arg-type]
        return {
            **child,
            "hook_boundary": "vllm.scheduler.schedule",
            "hook_installed": child["hook_installed"],
            "hook_exercised": child["hook_exercised"],
            "real_runtime_observed": child["real_runtime_observed"],
            "waiting_request_ids": waiting,
            "ordered_request_ids": ordered,
            "completed_native_request_ids": completed_native,
        }

    def _ensure_controlled_child(self) -> Mapping[str, object]:
        if self._controlled_child is None:
            self._controlled_child = _run_mode_child(
                "CONTROLLED", arguments=self.arguments
            )
        return self._controlled_child

    def _pressure_batch_executor(self, batch: int) -> Mapping[str, object]:
        child = self._ensure_controlled_child()
        batches = _required_mapping_field(child, "pressure_batches")
        if not isinstance(batches, (tuple, list)):
            raise ValidationExecutionError(
                "controlled child did not return pressure batches"
            )
        if batch < 1 or batch > len(batches):
            raise ValidationExecutionError("controlled child pressure batch is unavailable")
        batch_record = batches[batch - 1]
        if not isinstance(batch_record, Mapping):
            raise ValidationExecutionError("controlled child pressure batch is invalid")
        request_ids = _required_mapping_field(
            batch_record, "completed_native_request_ids"
        )
        runtime_id = _required_mapping_field(
            batch_record, "controlled_runtime_id"
        )
        if not isinstance(runtime_id, str) or not runtime_id:
            raise ValidationExecutionError("controlled child runtime identity is missing")
        if self._controlled_runtime_id is None:
            self._controlled_runtime_id = runtime_id
        elif self._controlled_runtime_id != runtime_id:
            raise ValidationExecutionError(
                "pressure batches did not use one persistent controlled runtime"
            )
        if not isinstance(request_ids, (tuple, list)):
            raise ValidationExecutionError(
                "controlled child did not return native pressure request IDs"
            )
        self._last_pressure_batch = batch
        return {
            "completed_native_request_ids": tuple(request_ids),
            "controlled_runtime_id": runtime_id,
        }

    def _pressure_observer(self) -> Mapping[str, object]:
        child = self._ensure_controlled_child()
        observations = _required_mapping_field(child, "pressure_observations")
        if not isinstance(observations, (tuple, list)):
            raise ValidationExecutionError(
                "controlled child did not return pressure observations"
            )
        if self._last_pressure_batch is None:
            raise ValidationExecutionError(
                "controlled child pressure observation requested before a batch"
            )
        index = self._last_pressure_batch - 1
        if index < 0 or index >= len(observations):
            raise ValidationExecutionError(
                "controlled child pressure observation is unavailable"
            )
        observation = observations[index]
        if not isinstance(observation, Mapping):
            raise ValidationExecutionError("controlled child pressure observation is invalid")
        if observation.get("batch") != self._last_pressure_batch:
            raise ValidationExecutionError(
                "controlled child pressure observation does not match selected batch"
            )
        required = (
            "target_present",
            "retention_release_observed",
            "plan_validated",
            "native_eviction_callback_observed",
            "evicted_block_id",
        )
        for field in required:
            _required_mapping_field(observation, field)
        return dict(observation)

    def _mode_executor(self, mode: str) -> Mapping[str, object]:
        if mode == "CONTROLLED":
            return self._ensure_controlled_child()
        return _run_mode_child(mode, arguments=self.arguments)

    def as_mapping(self) -> Mapping[str, object]:
        return {
            "request_executor": self._request_executor,
            "followup_request_executor": lambda program_id, external_id: self._request_executor(
                program_id, external_id, False
            ),
            "ordinary_request_executor": lambda program_id, external_id: self._request_executor(
                program_id, external_id, False
            ),
            "pressure_batch_executor": self._pressure_batch_executor,
            "pressure_observer": self._pressure_observer,
            "mode_executor": self._mode_executor,
            "scheduler_executor": self._scheduler_executor,
        }


class _EvictionEvidenceProxy:
    """Record the existing native eviction callback without changing behavior."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.block_ids: list[int] = []
        self.apply_pressure_calls = 0
        self.remove_selected_calls = 0
        self.shadow_plan_count = 0
        self.release_entry_keys: list[tuple[str, str]] = []
        self.release_effects: list[dict[str, object]] = []

    def apply_pressure(self, **kwargs: object) -> Any:
        self.apply_pressure_calls += 1
        remove_selected = kwargs.get("remove_selected")
        if callable(remove_selected):
            def recording_remove_selected(block_ids: object) -> Any:
                self.remove_selected_calls += 1
                return remove_selected(block_ids)

            kwargs = {**kwargs, "remove_selected": recording_remove_selected}
        result = self._delegate.apply_pressure(**kwargs)
        selection_plan = getattr(result, "selection_plan", None)
        if selection_plan is not None:
            self.shadow_plan_count += 1
            preparation = selection_plan.preparation
            release_keys = tuple(preparation.ordinary_expired_entries) + tuple(
                effect.entry_key for effect in preparation.pressure_releases
            )
            for entry_key in release_keys:
                self.release_entry_keys.append(
                    (
                        entry_key.program_id.value,
                        entry_key.prefix_id.canonical_value,
                    )
                )
            for effect in preparation.pressure_releases:
                self.release_effects.append({
                    "program_id": effect.entry_key.program_id.value,
                    "prefix_id": effect.entry_key.prefix_id.canonical_value,
                    "newly_eligible_block_ids": [
                        block_id.block_id
                        for block_id in effect.newly_eligible_block_ids
                    ],
                })
        return result

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        self.block_ids.append(block_id.block_id)
        self._delegate.observe_native_eviction(block_id)


def build_pinned_metal_validation_boundary(
    *,
    runtime: Any,
    clock: Any,
    run: ValidationRun,
    arguments: argparse.Namespace,
    observation_helpers: Any,
    prefill_helpers: Any,
) -> Mapping[str, object]:
    """Return the repository-owned pinned Metal validation boundary.

    This symbol is intentionally concrete and lazy.  It does not import or
    execute Metal at module import; real execution begins only when a child
    callback is invoked by the validation CLI.
    """
    boundary = _PinnedMetalValidationBoundary(
        runtime=runtime,
        clock=clock,
        run=run,
        arguments=arguments,
        observation_helpers=observation_helpers,
        prefill_helpers=prefill_helpers,
    )
    return boundary.as_mapping()


def _coherent_child_request_snapshot(
    observations: Sequence[Mapping[str, object]],
    native_request_id: str,
    *,
    expected_token_count: int | None = None,
) -> tuple[str, int, tuple[int, ...], tuple[bytes, ...]]:
    """Extract prefix identity, reusable count, blocks and hashes from one record."""
    from kvopt.runtime.vllm.continuum_observation import (
        NativeBlockSnapshot,
        prefix_identity_from_block,
    )

    for record in reversed(observations):
        request_records = record.get("request_blocks", ())
        if not isinstance(request_records, (tuple, list)):
            continue
        for request_record in request_records:
            if not isinstance(request_record, Mapping):
                continue
            if request_record.get("request_id") != native_request_id:
                continue
            if request_record.get("availability") != "AVAILABLE":
                continue
            groups = request_record.get("block_groups", ())
            if not isinstance(groups, (tuple, list)) or len(groups) != 1:
                continue
            if not isinstance(groups[0], (tuple, list)):
                continue
            if any(not isinstance(block, Mapping) for block in groups[0]):
                continue
            group_blocks = tuple(groups[0])
            blocks_list: list[Mapping[str, object]] = []
            for block in group_blocks:
                block_hash = block.get("native_hash_hex")
                block_tokens = block.get("hash_num_tokens")
                if (
                    block.get("is_null") is True
                    or not isinstance(block_hash, str)
                    or not block_hash
                    or isinstance(block_tokens, bool)
                    or not isinstance(block_tokens, int)
                    or block_tokens <= 0
                    or block_tokens % 16 != 0
                ):
                    break
                blocks_list.append(block)
            if not blocks_list or len(blocks_list) != len(group_blocks):
                # A trailing partial block is not part of the reusable prefix;
                # allow it only when it is the final native block in the group.
                trailing = group_blocks[len(blocks_list):]
                if len(blocks_list) == 0 or len(trailing) != 1:
                    continue
            blocks = tuple(blocks_list)
            block_ids = tuple(block.get("block_id") for block in blocks)
            if not blocks or any(
                isinstance(block_id, bool) or not isinstance(block_id, int)
                for block_id in block_ids
            ) or len(block_ids) != len(set(block_ids)):
                continue
            first = blocks[-1]
            try:
                snapshot = NativeBlockSnapshot(
                    block_id=first["block_id"],
                    ref_count=first["ref_count"],
                    native_hash_hex=first["native_hash_hex"],
                    hash_num_tokens=first["hash_num_tokens"],
                    cache_group_id=first["cache_group_id"],
                    is_null=first["is_null"],
                )
            except (KeyError, TypeError, ValueError):
                continue
            prefix = prefix_identity_from_block(snapshot)
            token_counts = tuple(block.get("hash_num_tokens") for block in blocks)
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value % 16 != 0
                for value in token_counts
            ):
                continue
            # Native ``hash_num_tokens`` is cumulative at each hashed block
            # boundary, so the final complete block carries the reusable
            # prefix length for this snapshot.
            token_count = token_counts[-1]
            hashes = tuple(
                block.get("native_hash_hex")
                for block in blocks
            )
            if prefix is None or not 16 <= token_count <= 512:
                continue
            if expected_token_count is not None and token_count != expected_token_count:
                continue
            if any(not isinstance(native_hash, str) or not native_hash for native_hash in hashes):
                continue
            if len(hashes) != len(set(hashes)):
                continue
            return prefix.canonical_value, token_count, block_ids, tuple(
                bytes.fromhex(native_hash) for native_hash in hashes
            )
    raise ValidationExecutionError(
        "native child did not expose one coherent reusable prefix snapshot; "
        f"{_snapshot_rejection_diagnostics(observations, native_request_id, expected_token_count)}"
    )


def _snapshot_rejection_diagnostics(
    observations: Sequence[Mapping[str, object]],
    native_request_id: str,
    expected_token_count: int | None,
) -> str:
    """Summarize matching native snapshots without changing acceptance semantics."""
    candidates: list[dict[str, object]] = []
    for record in reversed(observations):
        request_records = record.get("request_blocks", ())
        if not isinstance(request_records, (tuple, list)):
            continue
        for request_record in request_records:
            if not isinstance(request_record, Mapping):
                continue
            if request_record.get("request_id") != native_request_id:
                continue
            groups = request_record.get("block_groups", ())
            group_counts = (
                [len(group) if isinstance(group, (tuple, list)) else None for group in groups]
                if isinstance(groups, (tuple, list))
                else None
            )
            block_records: list[dict[str, object]] = []
            if isinstance(groups, (tuple, list)):
                for group in groups:
                    if not isinstance(group, (tuple, list)):
                        continue
                    for block in group:
                        if not isinstance(block, Mapping):
                            block_records.append({"type": type(block).__name__})
                            continue
                        block_records.append(
                            {
                                "block_id": block.get("block_id"),
                                "is_null": block.get("is_null"),
                                "native_hash_present": bool(block.get("native_hash_hex")),
                                "hash_num_tokens": block.get("hash_num_tokens"),
                                "cache_group_id": block.get("cache_group_id"),
                                "ref_count": block.get("ref_count"),
                            }
                        )
            reasons: list[str] = []
            availability = request_record.get("availability")
            if availability != "AVAILABLE":
                reasons.append(f"availability={availability!r}")
            if not isinstance(groups, (tuple, list)):
                reasons.append("block_groups_not_sequence")
            elif len(groups) != 1:
                reasons.append(f"expected_one_cache_group actual={len(groups)}")
            elif not isinstance(groups[0], (tuple, list)):
                reasons.append("cache_group_blocks_not_sequence")
            else:
                group = tuple(groups[0])
                if any(not isinstance(block, Mapping) for block in group):
                    reasons.append("cache_group_contains_non_mapping_block")
                valid_prefix_blocks = []
                for block in group:
                    if not isinstance(block, Mapping):
                        break
                    block_hash = block.get("native_hash_hex")
                    block_tokens = block.get("hash_num_tokens")
                    if (
                        block.get("is_null") is True
                        or not isinstance(block_hash, str)
                        or not block_hash
                        or isinstance(block_tokens, bool)
                        or not isinstance(block_tokens, int)
                        or block_tokens <= 0
                        or block_tokens % 16 != 0
                    ):
                        break
                    valid_prefix_blocks.append(block)
                trailing = group[len(valid_prefix_blocks):]
                if not valid_prefix_blocks:
                    reasons.append("no_complete_hashed_prefix_block")
                elif len(trailing) > 1:
                    reasons.append(f"more_than_one_trailing_block count={len(trailing)}")
                block_ids = tuple(
                    block.get("block_id")
                    for block in valid_prefix_blocks
                    if isinstance(block, Mapping)
                )
                if len(block_ids) != len(set(block_ids)):
                    reasons.append("duplicate_block_ids")
                token_count = valid_prefix_blocks[-1].get("hash_num_tokens", 0)
                if not 16 <= token_count <= 512:
                    reasons.append(f"reusable_token_count_out_of_range actual={token_count}")
                if expected_token_count is not None and token_count != expected_token_count:
                    reasons.append(
                        "expected_token_count_mismatch "
                        f"expected={expected_token_count} actual={token_count}"
                    )
            candidates.append(
                {
                    "request_id": native_request_id,
                    "availability": availability,
                    "group_count": len(groups) if isinstance(groups, (tuple, list)) else None,
                    "group_block_counts": group_counts,
                    "blocks": block_records,
                    "rejection": reasons or ["coherence_predicate_failed"],
                }
            )
    if not candidates:
        return f"snapshot_diagnostics={{requested_request_id={native_request_id!r}, matching_records=0}}"
    return f"snapshot_diagnostics={json.dumps({'requested_request_id': native_request_id, 'expected_token_count': expected_token_count, 'candidates': candidates}, sort_keys=True)}"


def _normalize_child_completion_ids(
    outputs: Sequence[object], registry: Any
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Normalize output-facing IDs to the registered canonical native IDs."""
    external_ids: list[str] = []
    native_ids: list[str] = []
    for output in outputs:
        external_id = getattr(output, "request_id", None)
        if not isinstance(external_id, str) or not external_id:
            raise ValidationExecutionError("completion output has no external request ID")
        native_id = registry.internal_for_external(external_id)
        if not isinstance(native_id, str) or not native_id:
            raise ValidationExecutionError(
                "completion output external ID has no registered native ID"
            )
        external_ids.append(external_id)
        native_ids.append(native_id)
    if len(native_ids) != len(set(native_ids)):
        raise ValidationExecutionError("completion output contains duplicate native IDs")
    return tuple(external_ids), tuple(native_ids)


def _capture_live_block_pool(
    captured_block_pools: list[object], receiver: object | None
) -> None:
    """Keep the exact native BlockPool observed by the existing hook."""
    if receiver is None:
        return
    if not any(receiver is captured for captured in captured_block_pools):
        captured_block_pools.append(receiver)


def _build_observation_phase_gate(
    recorder: Callable[[object], None],
    captured_block_pools: list[object],
) -> tuple[Callable[[object], None], Callable[[], None]]:
    """Gate heavy observation recording after early target evidence is frozen."""
    if not callable(recorder):
        raise TypeError("recorder must be callable")
    pressure_phase = False

    def enter_pressure_phase() -> None:
        nonlocal pressure_phase
        pressure_phase = True

    def observe_native(context: object) -> None:
        if getattr(context, "target", None) == "BlockPool.get_new_blocks":
            _capture_live_block_pool(
                captured_block_pools, getattr(context, "receiver", None)
            )
        if not pressure_phase:
            recorder(context)

    return observe_native, enter_pressure_phase


def _read_target_presence(
    captured_block_pools: Sequence[object], target_hashes: Sequence[bytes]
) -> bool:
    """Read exact target hashes from one captured native BlockPool."""
    if len(captured_block_pools) != 1:
        raise ValidationExecutionError(
            "controlled child did not expose one live native BlockPool"
        )
    block_pool = captured_block_pools[0]
    lookup = getattr(block_pool, "cached_block_hash_to_block", None)
    get_one_block = getattr(lookup, "get_one_block", None)
    if not callable(get_one_block):
        raise ValidationExecutionError(
            "controlled child has no approved read-only target presence surface"
        )
    return all(get_one_block(native_hash) is not None for native_hash in target_hashes)


def _controlled_request_roles(
    *, followup_request_id: str, ordinary_request_id: str
) -> tuple[str, str]:
    """Return semantic staged roles independently of native submission order."""
    return followup_request_id, ordinary_request_id


def _admit_ordinary_and_defer_followup(
    runtime: Any,
    *,
    ordinary_program: ProgramIdentity,
    ordinary_request: RequestIdentity,
    followup_program: ProgramIdentity,
    followup_request: RequestIdentity,
    ordinary_timestamp: float,
) -> Callable[[float], None]:
    """Keep a waiting follow-up protected until the pressure phase finishes."""
    runtime.handle(
        RequestAdmitted(
            ordinary_program,
            ordinary_request,
            ordinary_timestamp,
        )
    )

    def admit_followup(timestamp: float) -> None:
        runtime.handle(RequestAdmitted(followup_program, followup_request, timestamp))

    return admit_followup


def _deferred_followup_finish_timestamp(
    staged_finish_timestamp: float, admission_timestamp: float
) -> float:
    """Keep parent-facing deferred follow-up timestamps monotonic."""
    return max(staged_finish_timestamp, admission_timestamp)


def _execute_mode_child(arguments: argparse.Namespace) -> Mapping[str, object]:
    """Execute the deliberately small real-runtime child smoke.

    This is the only place where the child imports vLLM.  Parent construction
    and all unit tests remain import-safe.  The child registers native IDs
    before ``wait_for_completion`` so the installed production scheduler hook
    observes IDs already known to ``RuntimeCoordinator``.
    """
    if arguments.child_mode is None:  # pragma: no cover - defensive guard.
        raise ValueError("child mode is required")
    pinned_inputs = (
        (arguments.model, DEFAULT_MODEL, "model"),
        (arguments.model_revision, DEFAULT_MODEL_REVISION, "model_revision"),
        (arguments.tokenizer, DEFAULT_TOKENIZER, "tokenizer"),
        (arguments.tokenizer_revision, DEFAULT_TOKENIZER_REVISION, "tokenizer_revision"),
    )
    for actual, expected, field_name in pinned_inputs:
        if actual != expected:
            raise ValidationExecutionError(
                f"pinned validation requires the frozen {field_name}"
            )
    try:
        from vllm import LLM, SamplingParams
    except ImportError as error:  # pragma: no cover - deployment-only path.
        raise ValidationExecutionError(
            "the mode child requires the pinned vLLM/Metal runtime"
        ) from error

    mode = arguments.child_mode
    clock = SystemMonotonicClock()
    config = ContinuumConfig(
        enabled=True,
        prefill_profile_path=str(arguments.profile_path),
        prefill_profile_version="v1",
    )
    runtime = build_runtime_from_config(config=config, clock=clock)
    registry = importlib.import_module(
        "scripts.spikes.run_continuum_vllm_observation"
    ).ProgramRequestRegistry()
    observation_helpers = importlib.import_module(
        "scripts.spikes.run_continuum_vllm_observation"
    )
    topology = observation_helpers.require_observation_topology(os.environ)
    from importlib.metadata import version as distribution_version

    import mlx.core as mx
    import vllm
    import vllm_metal
    from vllm.platforms import current_platform
    from vllm_metal import MetalPlatform, get_config

    metal_config = get_config()
    platform_plugin_class = (
        f"{type(current_platform).__module__}."
        f"{type(current_platform).__qualname__}"
    )

    runtime_identity = observation_helpers.verify_runtime_identity(
        vllm_distribution_version=distribution_version("vllm"),
        vllm_module_version=vllm.__version__,
        vllm_metal_distribution_version=distribution_version("vllm-metal"),
        platform_plugin_class=platform_plugin_class,
        metal_platform_available=MetalPlatform.is_available(),
        mlx_metal_available=bool(mx.metal.is_available()),
        mlx_configured_device=metal_config.mlx_device,
        metal_paged_kv_enabled=metal_config.use_paged_attention,
    )
    source_identity = observation_helpers.inspect_vllm_metal_source_identity(
        arguments.vllm_metal_source_checkout,
        Path(vllm_metal.__file__),
    )
    llm_kwargs = observation_helpers.build_llm_kwargs(arguments)
    if mode == "CONTROLLED":
        llm_kwargs = _controlled_pressure_llm_kwargs(llm_kwargs)
    llm = LLM(**llm_kwargs)
    tokenizer = llm.get_tokenizer()
    try:
        vocabulary_size = len(tokenizer)
    except TypeError as error:
        raise ValidationExecutionError(
            "pinned tokenizer did not expose a vocabulary size"
        ) from error
    if vocabulary_size <= 0:
        raise ValidationExecutionError("pinned tokenizer vocabulary is empty")
    native_observations: list[dict[str, object]] = []
    captured_block_pools: list[object] = []
    from vllm.v1.core.block_pool import BlockPool
    from vllm.v1.core.sched.scheduler import Scheduler

    recorder = observation_helpers.NativeObservationRecorder(
        registry, native_observations.append
    )
    observe_native, enter_pressure_phase = _build_observation_phase_gate(
        recorder, captured_block_pools
    )

    observation_bindings = observation_helpers.build_vllm_hook_bindings(
        Scheduler, BlockPool
    )
    observation_hook_set = observation_helpers.ObservationHookSet(
        observation_bindings, observe_native, enabled=True
    )
    observation_hook_set.__enter__()
    eviction_proxy: _EvictionEvidenceProxy | None = None
    scheduler_state: dict[str, object] = {
        "hook_installed": False,
        "hook_exercised": False,
        "queue_mutated": False,
    }
    if mode != "NATIVE":
        from kvopt.continuum import RetentionMode, SchedulerMode
        from kvopt.continuum.scheduler import ContinuumSchedulingPolicy
        from kvopt.runtime.vllm.observer import (
            install_retention_hook,
            install_scheduler_hook,
        )
        from kvopt.runtime.vllm.retention_integration import (
            RetentionRuntimeIntegration,
        )

        class _ObservedPolicy:
            def __init__(self) -> None:
                self._policy = ContinuumSchedulingPolicy()
                self.calls: list[dict[str, tuple[str, ...]]] = []

            def order(self, candidates: Sequence[Any]) -> tuple[RequestIdentity, ...]:
                input_ids = tuple(candidate.request_id.value for candidate in candidates)
                ordered = self._policy.order(candidates)
                output_ids = tuple(request_id.value for request_id in ordered)
                self.calls.append({
                    "input_native_ids": input_ids,
                    "output_native_ids": output_ids,
                })
                scheduler_state["hook_exercised"] = True
                scheduler_state["queue_mutated"] = (
                    scheduler_state["queue_mutated"]
                    or input_ids != output_ids
                )
                return ordered

        observed_policy = _ObservedPolicy()
        install_scheduler_hook(
            mode=SchedulerMode[mode],
            runtime=runtime,
            policy=observed_policy,
        )
        scheduler_state["hook_installed"] = True
        eviction_proxy = _EvictionEvidenceProxy(
            RetentionRuntimeIntegration(runtime.retention)
        )
        install_retention_hook(
            mode=RetentionMode[mode],
            integration=eviction_proxy,
            clock=clock,
        )

    sampling_params = SamplingParams(max_tokens=1, temperature=0.0, seed=0)
    submitted_native_ids: list[str] = []
    submitted_external_ids: list[str] = []

    def enqueue_registered(program_id: str, prompt: object) -> tuple[str, str, float]:
        native_ids = tuple(llm.enqueue([prompt], sampling_params, use_tqdm=False))
        if len(native_ids) != 1 or not isinstance(native_ids[0], str):
            raise ValidationExecutionError("native enqueue did not return one ID")
        native_id = native_ids[0]
        registry.register_batch((program_id,), native_ids)
        external_ids = observation_helpers._external_request_ids_for_internal(
            llm, native_ids
        )
        if len(external_ids) != 1 or not isinstance(external_ids[0], str):
            raise ValidationExecutionError("native enqueue did not expose one external ID")
        registry.register_external_batch(native_ids, external_ids)
        submitted_native_ids.append(native_id)
        submitted_external_ids.append(external_ids[0])
        arrival_timestamp = float(clock.now())
        runtime.handle(
            RequestArrived(
                ProgramIdentity(program_id),
                RequestIdentity(native_id),
                arrival_timestamp,
            )
        )
        return native_id, external_ids[0], arrival_timestamp

    def complete_outputs() -> tuple[tuple[str, ...], tuple[str, ...]]:
        outputs = tuple(llm.wait_for_completion(use_tqdm=False))
        return _normalize_child_completion_ids(outputs, registry)

    def record_nonterminal(
        program_id: str,
        native_id: str,
        external_id: str,
        timestamp: float,
    ) -> tuple[str, int, tuple[int, ...], tuple[bytes, ...]]:
        prefix_id, token_count, block_ids, hashes = _coherent_child_request_snapshot(
            native_observations,
            native_id,
            expected_token_count=TARGET_TOKEN_COUNT,
        )
        program = ProgramIdentity(program_id)
        request = RequestIdentity(native_id)
        prefix = PrefixIdentity(prefix_id)
        runtime.handle(RequestAdmitted(program, request, timestamp))
        runtime.record_prefill_context_token_count(
            PrefillContextTokenCountRecord(
                program_id=program,
                request_id=request,
                prefix_id=prefix,
                token_count=token_count,
                provenance=InputProvenance(InputSource.OBSERVED),
            )
        )
        runtime.handle(
            BlocksObserved(
                program,
                request,
                prefix,
                tuple(BlockIdentity(block_id) for block_id in block_ids),
                timestamp,
            )
        )
        runtime.handle(
            TurnFinished(
                program,
                request,
                timestamp,
                is_terminal=False,
                next_tool_type="search",
            )
        )
        return prefix_id, token_count, block_ids, hashes

    completed_external_ids: tuple[str, ...] = ()
    completed_native_ids: tuple[str, ...] = ()
    scheduler_completed_external_ids: tuple[str, ...] = ()
    scheduler_completed_native_ids: tuple[str, ...] = ()
    scheduler_completion_ordering: str | None = None
    scheduler_ordering_outcome: str | None = None
    controlled_followup_request_id: str | None = None
    controlled_ordinary_request_id: str | None = None
    staged_waiting_ids: tuple[str, ...] = ()
    staged_ordered_ids: tuple[str, ...] = ()
    pressure_batches: list[dict[str, object]] = []
    pressure_observations: list[dict[str, object]] = []
    lifecycle_request_evidence: list[dict[str, object]] = []
    target_present: bool | None = None
    target_hashes: tuple[bytes, ...] = ()
    retention_release_observed = False
    plan_validated = False

    if mode == "CONTROLLED":
        r1_native, _r1_external, _r1_timestamp = enqueue_registered(
            "program-validation",
            {
                "prompt_token_ids": list(
                    _qualified_target_token_ids(TARGET_TOKEN_COUNT, vocabulary_size)
                )
            },
        )
        r1_external_ids, r1_completed_ids = complete_outputs()
        if r1_native not in r1_completed_ids:
            raise ValidationExecutionError("initial retained request did not complete")
        r1_finish_timestamp = float(clock.now())
        _prefix_id, _token_count, _block_ids, target_hashes = record_nonterminal(
            "program-validation", r1_native, r1_external_ids[0], r1_finish_timestamp
        )
        lifecycle_request_evidence.append({
            "program_id": "program-validation",
            "request_id": r1_native,
            "native_request_id": r1_native,
            "external_request_id": r1_external_ids[0],
            "token_count": _token_count,
            "prefix_id": _prefix_id,
            "block_ids": tuple(_block_ids),
            "arrival_timestamp": _r1_timestamp,
            "admission_timestamp": r1_finish_timestamp,
            "finish_timestamp": r1_finish_timestamp,
            "terminal": False,
            "next_tool_type": "search",
        })
        entry = tuple(runtime.retention.planning_snapshots())
        if not entry or not any(item.protected for item in entry):
            raise ValidationExecutionError(
                "controlled child did not establish protected retention"
            )
        if not target_hashes:
            raise ValidationExecutionError("retained request has no native target hashes")

        # Enqueue ordinary first so the real native FCFS snapshot is O, F.
        r3_native, _r3_external, r3_timestamp = enqueue_registered(
            "ordinary-program", "continuum phase1b ordinary competitor"
        )
        r2_native, _r2_external, r2_timestamp = enqueue_registered(
            "program-validation", "continuum phase1b staged follow-up"
        )
        (
            controlled_followup_request_id,
            controlled_ordinary_request_id,
        ) = _controlled_request_roles(
            followup_request_id=r2_native,
            ordinary_request_id=r3_native,
        )
        runtime.handle(
            FollowupWaiting(
                ProgramIdentity("program-validation"),
                RequestIdentity(r2_native),
                r2_timestamp,
            )
        )
        scheduler_completed_external_ids, scheduler_completed_native_ids = complete_outputs()
        if set(scheduler_completed_native_ids) != {r2_native, r3_native}:
            raise ValidationExecutionError(
                "staged scheduler requests did not complete exactly once"
            )
        if not scheduler_state["hook_exercised"]:
            raise ValidationExecutionError("controlled scheduler hook was not exercised")
        staged_calls = [
            call
            for call in observed_policy.calls
            if call["input_native_ids"] == (r3_native, r2_native)
        ]
        if len(staged_calls) != 1:
            raise ValidationExecutionError(
                "controlled scheduler did not expose one staged ordinary/follow-up call"
            )
        staged_waiting_ids = staged_calls[0]["input_native_ids"]
        staged_ordered_ids = staged_calls[0]["output_native_ids"]
        if staged_ordered_ids != (r2_native, r3_native):
            raise ValidationExecutionError(
                "controlled scheduler did not reorder follow-up before ordinary"
            )
        scheduler_ordering_outcome = (
            "followup_before_ordinary"
            if staged_ordered_ids == (r2_native, r3_native)
            else "ordinary_before_followup"
        )
        scheduler_completion_ordering = (
            "followup_before_ordinary"
            if scheduler_completed_native_ids.index(r2_native)
            < scheduler_completed_native_ids.index(r3_native)
            else "ordinary_before_followup"
        )

        staged_finish_timestamp = float(clock.now())
        admit_followup = _admit_ordinary_and_defer_followup(
            runtime,
            ordinary_program=ProgramIdentity("ordinary-program"),
            ordinary_request=RequestIdentity(r3_native),
            followup_program=ProgramIdentity("program-validation"),
            followup_request=RequestIdentity(r2_native),
            ordinary_timestamp=staged_finish_timestamp,
        )

        def read_target_presence() -> bool:
            return _read_target_presence(captured_block_pools, target_hashes)

        if not read_target_presence():
            raise ValidationExecutionError(
                "controlled child target prefix was not present before pressure"
            )
        enter_pressure_phase()
        for batch_number in range(1, PRESSURE_SAFETY_CEILING + 1):
            batch_native: list[str] = []
            batch_external: list[str] = []
            for index in range(PRESSURE_BATCH_SIZE):
                pressure_program = f"pressure-program-{batch_number:04d}-{index:02d}"
                native_id, external_id, _timestamp = enqueue_registered(
                    pressure_program,
                    {
                        "prompt_token_ids": list(
                            _qualified_pressure_token_ids(
                                (batch_number - 1) * PRESSURE_BATCH_SIZE + index,
                                vocabulary_size,
                            )
                        )
                    },
                )
                batch_native.append(native_id)
                batch_external.append(external_id)
                external, native = complete_outputs()
                if native != (native_id,) or external != (external_id,):
                    raise ValidationExecutionError(
                        "pressure request completion IDs were not normalized"
                    )
                completion_timestamp = float(clock.now())
                runtime.handle(
                    RequestAdmitted(
                        ProgramIdentity(pressure_program),
                        RequestIdentity(native_id),
                        completion_timestamp,
                    )
                )
                runtime.handle(
                    TurnFinished(
                        ProgramIdentity(pressure_program),
                        RequestIdentity(native_id),
                        completion_timestamp,
                        is_terminal=True,
                    )
                )
            target_present = read_target_presence()
            if eviction_proxy is None:
                raise ValidationExecutionError("controlled retention proxy is unavailable")
            retention_release_observed = bool(eviction_proxy.release_entry_keys)
            plan_validated = eviction_proxy.shadow_plan_count > 0
            observation = {
                "batch": batch_number,
                "target_present": target_present,
                "retention_release_observed": retention_release_observed,
                "plan_validated": plan_validated,
                "native_eviction_callback_observed": bool(eviction_proxy.block_ids),
                "released_entry_keys": list(eviction_proxy.release_entry_keys),
                "release_effects": list(eviction_proxy.release_effects),
                "evicted_block_id": (
                    eviction_proxy.block_ids[-1] if eviction_proxy.block_ids else None
                ),
            }
            pressure_batches.append({
                "batch": batch_number,
                "controlled_runtime_id": str(id(llm)),
                "completed_native_request_ids": tuple(batch_native),
                "completed_external_request_ids": tuple(batch_external),
            })
            pressure_observations.append(observation)
            observation["controlled_runtime_id"] = str(id(llm))
            if (
                not target_present
                and retention_release_observed
                and plan_validated
                and bool(eviction_proxy.block_ids)
            ):
                break
        if target_present is not False:
            raise ValidationExecutionError(
                "controlled pressure safety ceiling left target material present"
            )
        followup_admission_timestamp = float(clock.now())
        admit_followup(followup_admission_timestamp)
        # Keep the parent-facing order stable even though the native enqueue
        # order above is deliberately ordinary-first.  The follow-up
        # admission is recorded after pressure so its waiting retention entry
        # remains protected throughout the pressure phase.
        lifecycle_request_evidence.extend((
            {
                "program_id": "program-validation",
                "request_id": r2_native,
                "native_request_id": r2_native,
                "external_request_id": _r2_external,
                "token_count": _token_count,
                "prefix_id": _prefix_id,
                "block_ids": tuple(_block_ids),
                "arrival_timestamp": r2_timestamp,
                "admission_timestamp": followup_admission_timestamp,
                "finish_timestamp": _deferred_followup_finish_timestamp(
                    staged_finish_timestamp, followup_admission_timestamp
                ),
                "terminal": False,
                "next_tool_type": "search",
            },
            {
                "program_id": "ordinary-program",
                "request_id": r3_native,
                "native_request_id": r3_native,
                "external_request_id": _r3_external,
                "token_count": _token_count,
                "prefix_id": _prefix_id,
                "block_ids": tuple(_block_ids),
                "arrival_timestamp": r3_timestamp,
                "admission_timestamp": staged_finish_timestamp,
                "finish_timestamp": staged_finish_timestamp,
                "terminal": False,
                "next_tool_type": "search",
            },
        ))
        completed_external_ids = scheduler_completed_external_ids
        completed_native_ids = scheduler_completed_native_ids
        terminal_native, terminal_external, terminal_timestamp = enqueue_registered(
            "program-validation", "continuum phase1b terminal request"
        )
        terminal_external_ids, terminal_native_ids = complete_outputs()
        if terminal_native_ids != (terminal_native,) or terminal_external_ids != (
            terminal_external,
        ):
            raise ValidationExecutionError("terminal request completion evidence is incomplete")
        terminal_finish_timestamp = float(clock.now())
        runtime.handle(
            RequestAdmitted(
                ProgramIdentity("program-validation"),
                RequestIdentity(terminal_native),
                terminal_finish_timestamp,
            )
        )
        runtime.handle(
            TurnFinished(
                ProgramIdentity("program-validation"),
                RequestIdentity(terminal_native),
                terminal_finish_timestamp,
                is_terminal=True,
            )
        )
        lifecycle_request_evidence.append({
            "program_id": "program-validation",
            "request_id": terminal_native,
            "native_request_id": terminal_native,
            "external_request_id": terminal_external,
            "token_count": _token_count,
            "prefix_id": _prefix_id,
            "block_ids": tuple(_block_ids),
            "arrival_timestamp": terminal_timestamp,
            "admission_timestamp": terminal_finish_timestamp,
            "finish_timestamp": terminal_finish_timestamp,
            "terminal": True,
            "next_tool_type": None,
        })
    else:
        native_id, external_id, _timestamp = enqueue_registered(
            "program-validation", f"continuum phase1b {mode.lower()}"
        )
        completed_external_ids, completed_native_ids = complete_outputs()
        if completed_native_ids != (native_id,) or completed_external_ids != (external_id,):
            raise ValidationExecutionError("mode child completion evidence is incomplete")
        mode_finish_timestamp = float(clock.now())
        runtime.handle(
            RequestAdmitted(
                ProgramIdentity("program-validation"),
                RequestIdentity(native_id),
                mode_finish_timestamp,
            )
        )
        runtime.handle(
            TurnFinished(
                ProgramIdentity("program-validation"),
                RequestIdentity(native_id),
                mode_finish_timestamp,
                is_terminal=True,
            )
        )

    if eviction_proxy is not None:
        continuum_invoked = eviction_proxy.apply_pressure_calls > 0
        hypothetical_plan_available = eviction_proxy.shadow_plan_count > 0
        native_eviction_callback_observed = bool(eviction_proxy.block_ids)
        evicted_block_id = (
            eviction_proxy.block_ids[-1] if eviction_proxy.block_ids else None
        )
    else:
        continuum_invoked = False
        hypothetical_plan_available = False
        native_eviction_callback_observed = False
        evicted_block_id = None
    return {
        "mode": mode,
        "status": "PASS",
        "git_sha": _git_head(),
        "real_runtime_observed": bool(completed_native_ids),
        "hook_installed": scheduler_state["hook_installed"],
        "hook_exercised": scheduler_state["hook_exercised"],
        "native_path_succeeded": bool(completed_native_ids),
        "continuum_invoked": continuum_invoked,
        "hypothetical_plan_available": hypothetical_plan_available,
        "queue_mutated": scheduler_state["queue_mutated"],
        "ordering_outcome": scheduler_ordering_outcome,
        "completion_ordering": scheduler_completion_ordering,
        "submitted_native_request_ids": tuple(submitted_native_ids),
        "external_request_ids": tuple(submitted_external_ids),
        "completed_native_request_ids": (
            tuple(scheduler_completed_native_ids)
            if mode == "CONTROLLED"
            else tuple(completed_native_ids)
        ),
        "completed_external_request_ids": (
            tuple(scheduler_completed_external_ids)
            if mode == "CONTROLLED"
            else tuple(completed_external_ids)
        ),
        "waiting_request_ids": staged_waiting_ids,
        "ordered_request_ids": staged_ordered_ids,
        "followup_request_id": (
            controlled_followup_request_id if mode == "CONTROLLED" else None
        ),
        "ordinary_request_id": (
            controlled_ordinary_request_id if mode == "CONTROLLED" else None
        ),
        "pressure_batches": tuple(pressure_batches),
        "pressure_observations": tuple(pressure_observations),
        "controlled_runtime_id": str(id(llm)) if mode == "CONTROLLED" else None,
        "lifecycle_request_evidence": tuple(lifecycle_request_evidence),
        "target_present": target_present,
        "retention_release_observed": retention_release_observed,
        "plan_validated": plan_validated,
        "native_eviction_callback_observed": native_eviction_callback_observed,
        "evicted_block_id": evicted_block_id,
        "runtime_preflight": {**topology, **runtime_identity, **source_identity},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Execute explicit PR7 validation through a real boundary factory."""
    arguments = _parse_execution_args(argv)
    if arguments.child_mode is not None:
        try:
            print(json.dumps(_execute_mode_child(arguments), sort_keys=True))
            return 0
        except Exception as error:  # noqa: BLE001 -- child failure is serialized.
            print(f"error: {error}", file=sys.stderr)
            return 1
    if (
        Path(arguments.run_id).name != arguments.run_id
        or arguments.run_id in {".", ".."}
    ):
        raise ValueError("run-id must be one safe path component")
    if not arguments.profile_path.is_file():
        raise ValueError("profile-path must point to an existing profile")

    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = arguments.output_dir / arguments.run_id / "validation.json"
    run = ValidationRun(
        run_id=arguments.run_id,
        git_sha=_git_head(),
        provenance={
            **collect_local_provenance(),
            "prefill_profile_path": str(arguments.profile_path),
            "execution_factory": arguments.execution_factory,
        },
    )
    run.write_artifact(artifact_path)
    try:
        clock = SystemMonotonicClock()
        config = ContinuumConfig(
            enabled=True,
            prefill_profile_path=str(arguments.profile_path),
            prefill_profile_version="v1",
        )
        runtime = build_runtime_from_config(config=config, clock=clock)
        adapter = _build_execution_adapter(
            factory=_load_factory(arguments.execution_factory),
            run=run,
            runtime=runtime,
            clock=clock,
            arguments=arguments,
        )
        scenarios = (
            SCENARIOS if arguments.scenario == "all" else (arguments.scenario,)
        )
        modes = MODES if arguments.mode == "all" else (arguments.mode,)
        passed = adapter.execute(
            artifact_path=artifact_path,
            scenarios=scenarios,
            modes=modes,
        )
        return 0 if passed else 1
    except Exception as error:  # noqa: BLE001 -- artifact must remain auditable.
        run.record_claim(
            "mode_boundaries",
            False,
            failure_reason=f"execution failed: {type(error).__name__}: {error}",
        )
        run.finalize()
        run.write_artifact(artifact_path)
        print(f"error: {error}", file=sys.stderr)
        return 1


def run_adaptive_pressure(
    *,
    run_batch: Callable[[int], None],
    observe: Callable[[], Mapping[str, object]],
    evidence_ready: Callable[[Mapping[str, object]], bool],
    safety_ceiling: int = PRESSURE_SAFETY_CEILING,
) -> PressureResult:
    """Run serial pressure batches until native evidence or a safety ceiling."""

    _require_positive_int(safety_ceiling, "safety_ceiling")
    if not callable(run_batch) or not callable(observe):
        raise TypeError("run_batch and observe must be callable")
    if not callable(evidence_ready):
        raise TypeError("evidence_ready must be callable")

    observations: list[Mapping[str, object]] = []
    for batch_number in range(1, safety_ceiling + 1):
        run_batch(batch_number)
        observation = observe()
        if not isinstance(observation, Mapping):
            raise TypeError("observe must return a mapping")
        observations.append(dict(observation))
        if evidence_ready(observation):
            return PressureResult(
                passed=True,
                batches=batch_number,
                pressure_requests=batch_number * PRESSURE_BATCH_SIZE,
                stop_reason="evidence",
                observations=tuple(observations),
            )

    return PressureResult(
        passed=False,
        batches=safety_ceiling,
        pressure_requests=safety_ceiling * PRESSURE_BATCH_SIZE,
        stop_reason="safety_ceiling",
        observations=tuple(observations),
    )


class ValidationRun:
    """Small recorder for the two PR7 validation scenarios and their claims."""

    def __init__(
        self,
        *,
        run_id: str,
        git_sha: str,
        provenance: Mapping[str, object],
    ) -> None:
        self.run_id = _require_text(run_id, "run_id")
        self.git_sha = _require_text(git_sha, "git_sha")
        self._started_at = _now()
        self._completed_at: str | None = None
        self._provenance = dict(provenance)
        self._status = "incomplete"
        self._explicit_failure_reasons: list[str] = []
        self._failure_reasons: list[str] = []
        self._requests: list[dict[str, str | None]] = []
        self._request_programs: dict[str, str] = {}
        self._native_requests: set[str] = set()
        self._lifecycle: dict[str, list[str]] = {}
        self._actual_token_counts: dict[tuple[str, str], int] = {}
        self._prefix_observations: list[dict[str, object]] = []
        self._ttl_decisions: list[dict[str, object]] = []
        self._retention_transitions: list[dict[str, object]] = []
        self._scheduler_orders: list[dict[str, object]] = []
        self._pressure_observations: list[dict[str, object]] = []
        self._native_cleanup: list[dict[str, object]] = []
        self._mode_boundaries: dict[str, dict[str, object]] = {}
        self._scenarios: dict[str, dict[str, object]] = {}
        self._claims: dict[str, dict[str, object]] = {}

    def record_request(
        self,
        program_id: str,
        request_id: str,
        *,
        native_request_id: str | None = None,
        external_request_id: str | None = None,
    ) -> None:
        program = _require_text(program_id, "program_id")
        request = _require_text(request_id, "request_id")
        if request in self._request_programs:
            raise ValueError("request_id must be unique within a validation run")
        native = (
            None
            if native_request_id is None
            else _require_text(native_request_id, "native_request_id")
        )
        external = (
            None
            if external_request_id is None
            else _require_text(external_request_id, "external_request_id")
        )
        if native is not None and native in self._native_requests:
            raise ValueError("native_request_id must be unique")
        if native is not None and native != request:
            raise ValueError(
                "request_id must be the canonical native/internal request ID"
            )
        self._request_programs[request] = program
        if native is not None:
            self._native_requests.add(native)
        request_record: dict[str, str | None] = {
            "program_id": program,
            "request_id": request,
            "native_request_id": native,
        }
        if external is not None:
            request_record["external_request_id"] = external
        self._requests.append(request_record)
        self._lifecycle[request] = []

    def record_lifecycle(self, program_id: str, request_id: str, event: str) -> None:
        program = _require_text(program_id, "program_id")
        request = _require_text(request_id, "request_id")
        event_name = _require_text(event, "event")
        if event_name not in _LIFECYCLE_EVENTS:
            raise ValueError(f"unsupported lifecycle event: {event_name}")
        if self._request_programs.get(request) != program:
            raise ValueError("lifecycle request does not belong to program")
        history = self._lifecycle[request]
        previous = history[-1] if history else None
        if event_name == "REQUEST_ARRIVED" and previous is not None:
            raise ValueError("request arrival must be the first lifecycle event")
        if event_name == "REQUEST_ADMITTED" and previous != "REQUEST_ARRIVED":
            raise ValueError("request admission requires request arrival")
        if event_name == "BLOCKS_OBSERVED" and previous not in {
            "REQUEST_ADMITTED", "BLOCKS_OBSERVED",
        }:
            raise ValueError("block observation requires an admitted request")
        if event_name.startswith("TURN_FINISHED") and previous not in {
            "REQUEST_ADMITTED", "BLOCKS_OBSERVED",
        }:
            raise ValueError("turn completion requires an admitted request")
        history.append(event_name)

    def record_actual_token_count(
        self, program_id: str, request_id: str, token_count: int
    ) -> None:
        program = _require_text(program_id, "program_id")
        request = _require_text(request_id, "request_id")
        count = _require_positive_int(token_count, "token_count")
        if self._request_programs.get(request) != program:
            raise ValueError("token count request does not belong to program")
        key = (program, request)
        if key in self._actual_token_counts:
            raise ValueError("actual token count already recorded for request")
        self._actual_token_counts[key] = count

    def record_prefix_observation(
        self,
        *,
        program_id: str,
        request_id: str,
        prefix_id: str,
        block_ids: tuple[int, ...],
    ) -> None:
        program = _require_text(program_id, "program_id")
        request = _require_text(request_id, "request_id")
        prefix = _require_text(prefix_id, "prefix_id")
        if self._request_programs.get(request) != program:
            raise ValueError("prefix observation request does not belong to program")
        if not isinstance(block_ids, tuple) or any(
            isinstance(block_id, bool) or not isinstance(block_id, int)
            for block_id in block_ids
        ):
            raise TypeError("block_ids must be a tuple of ints")
        self._prefix_observations.append(
            {
                "program_id": program,
                "request_id": request,
                "prefix_id": prefix,
                "block_ids": list(block_ids),
            }
        )

    def record_ttl_decision(
        self,
        program_id: str,
        request_id: str,
        *,
        token_count: int,
        prefill_reload_seconds: float,
        provenance: str | None = None,
    ) -> None:
        key = (
            _require_text(program_id, "program_id"),
            _require_text(request_id, "request_id"),
        )
        actual = self._actual_token_counts.get(key)
        if actual is None:
            raise ValueError("TTL evidence requires actual token count")
        count = _require_positive_int(token_count, "token_count")
        if count != actual:
            raise ValueError("TTL token count differs from observed actual count")
        entry: dict[str, object] = {
            "program_id": key[0],
            "request_id": key[1],
            "token_count": count,
            "prefill_reload_seconds": _require_finite_non_negative(
                prefill_reload_seconds, "prefill_reload_seconds"
            ),
        }
        if provenance is not None:
            entry["prefill_reload_provenance"] = _require_text(
                provenance, "provenance"
            )
        self._ttl_decisions.append(entry)

    def record_retention_transition(self, **evidence: object) -> None:
        self._retention_transitions.append(dict(evidence))

    def record_scheduler_order(self, **evidence: object) -> None:
        self._scheduler_orders.append(dict(evidence))

    def record_pressure_observation(self, **evidence: object) -> None:
        self._pressure_observations.append(dict(evidence))

    def record_native_cleanup(self, block_id: int, *, evicted: bool) -> None:
        if isinstance(block_id, bool) or not isinstance(block_id, int):
            raise TypeError("block_id must be int")
        if not isinstance(evicted, bool):
            raise TypeError("evicted must be bool")
        self._native_cleanup.append({"block_id": block_id, "evicted": evicted})

    def record_mode_evidence(self, mode: str, **evidence: object) -> None:
        mode_name = _require_text(mode, "mode").upper()
        if mode_name not in MODES:
            raise ValueError(f"unsupported mode: {mode_name}")
        if mode_name in self._mode_boundaries:
            raise ValueError(f"mode already recorded: {mode_name}")
        self._mode_boundaries[mode_name] = dict(evidence)

    def record_scenario(
        self, scenario: str, *, passed: bool, evidence: Mapping[str, object]
    ) -> None:
        scenario_name = _require_text(scenario, "scenario")
        if scenario_name not in SCENARIOS:
            raise ValueError(f"unsupported scenario: {scenario_name}")
        self._scenarios[scenario_name] = {
            "status": "PASS" if passed else "FAIL",
            "evidence": dict(evidence),
        }

    def record_claim(
        self,
        claim: str,
        passed: bool,
        *,
        evidence: Mapping[str, object] | None = None,
        failure_reason: str | None = None,
    ) -> None:
        claim_name = _require_text(claim, "claim")
        if claim_name not in REQUIRED_CLAIMS:
            raise ValueError(f"unsupported required claim: {claim_name}")
        if not isinstance(passed, bool):
            raise TypeError("passed must be bool")
        record: dict[str, object] = {
            "status": "PASS" if passed else "FAIL",
            "evidence": {} if evidence is None else dict(evidence),
        }
        if failure_reason is not None:
            record["failure_reason"] = _require_text(
                failure_reason, "failure_reason"
            )
            if not passed:
                self._explicit_failure_reasons.append(
                    str(record["failure_reason"])
                )
        self._claims[claim_name] = record

    def _complete_if_valid(self) -> None:
        failure_reasons = list(self._explicit_failure_reasons)
        missing = sorted(
            claim for claim in REQUIRED_CLAIMS
            if self._claims.get(claim, {}).get("status") != "PASS"
        )
        if missing:
            failure_reasons.append(
                "missing or failed claims: " + ", ".join(missing)
            )
        if set(self._mode_boundaries) != set(MODES):
            failure_reasons.append("mode boundary evidence is incomplete")
        if set(self._scenarios) != set(SCENARIOS) or any(
            self._scenarios[name]["status"] != "PASS" for name in SCENARIOS
        ):
            failure_reasons.append("scenario evidence is incomplete")
        if (
            self._claims.get("native_cleanup", {}).get("status") == "PASS"
            and not any(item["evicted"] is True for item in self._native_cleanup)
        ):
            failure_reasons.append("native cleanup requires a native eviction signal")
        self._failure_reasons = list(dict.fromkeys(failure_reasons))
        if self._failure_reasons:
            self._status = "incomplete"
            return
        self._status = "complete"

    def finalize(self) -> dict[str, object]:
        self._failure_reasons = list(dict.fromkeys(self._failure_reasons))
        self._complete_if_valid()
        self._completed_at = _now()
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        failure_reason: str | None = None
        if self._failure_reasons:
            failure_reason = "; ".join(dict.fromkeys(self._failure_reasons))
        return {
            "schema": SCHEMA,
            "status": self._status,
            "run_id": self.run_id,
            "started_at": self._started_at,
            "completed_at": self._completed_at,
            "git_sha": self.git_sha,
            "provenance": dict(self._provenance),
            "scenarios": dict(self._scenarios),
            "claims": dict(self._claims),
            "requests": list(self._requests),
            "lifecycle_transitions": [
                {"request_id": request_id, "events": list(events)}
                for request_id, events in self._lifecycle.items()
            ],
            "actual_token_counts": [
                {
                    "program_id": program_id,
                    "request_id": request_id,
                    "token_count": token_count,
                }
                for (program_id, request_id), token_count in self._actual_token_counts.items()
            ],
            "prefix_observations": list(self._prefix_observations),
            "ttl_decisions": list(self._ttl_decisions),
            "retention_transitions": list(self._retention_transitions),
            "scheduler_orders": list(self._scheduler_orders),
            "pressure_observations": list(self._pressure_observations),
            "native_cleanup_observations": list(self._native_cleanup),
            "mode_boundaries": dict(self._mode_boundaries),
            "failure_reason": failure_reason,
            "limitations": [],
        }

    def write_artifact(self, path: str | Path) -> None:
        artifact_path = Path(path)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(
                self.snapshot(),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def collect_local_provenance() -> dict[str, str]:
    """Collect only local facts; vLLM facts stay at the runtime boundary."""

    return {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
    }


__all__ = [
    "PRESSURE_BATCH_SIZE",
    "PRESSURE_SAFETY_CEILING",
    "PRESSURE_TOKEN_COUNT",
    "REQUIRED_CLAIMS",
    "TARGET_TOKEN_COUNT",
    "PressureResult",
    "RequestExecutionEvidence",
    "ValidationExecutionAdapter",
    "ValidationExecutionError",
    "ValidationRun",
    "_qualified_pressure_token_ids",
    "_qualified_target_token_ids",
    "build_pinned_metal_validation_boundary",
    "collect_local_provenance",
    "main",
    "run_adaptive_pressure",
]


if __name__ == "__main__":
    raise SystemExit(main())
