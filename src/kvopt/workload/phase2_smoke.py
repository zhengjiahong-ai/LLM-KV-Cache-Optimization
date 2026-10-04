"""Explicitly synthetic backend for infrastructure smoke runs only."""

from __future__ import annotations

from dataclasses import dataclass

from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    FakeClock,
    FollowupWaiting,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    ProgramCompleted,
    ProgramStarted,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    RetentionMode,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.profiling.experiment_events import (
    ExperimentEvent,
    ExperimentEventSink,
    ExperimentForcedReleaseObserver,
)
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration

from .phase2 import PlannedRequest


class _SyntheticPrefillProvider:
    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        return 0.1, InputProvenance(InputSource.APPROXIMATED, "synthetic smoke profile")


@dataclass(frozen=True, slots=True)
class _SyntheticBlock:
    block_id: int
    ref_cnt: int = 0
    block_hash: str = "synthetic"


class SyntheticSmokeBackend:
    """Exercises approved contracts without claiming to measure vLLM or a GPU."""

    def __init__(self, config: dict[str, object], sink: ExperimentEventSink) -> None:
        self._sink = sink
        self._clock = FakeClock()
        self._runtime = build_runtime(
            clock=self._clock,
            prefill_reload_provider=_SyntheticPrefillProvider(),
            default_ttl_seconds=100.0,
            experiment_event_sink=sink,
        )
        self._pressure = RetentionRuntimeIntegration(
            self._runtime.retention, ExperimentForcedReleaseObserver(sink)
        )
        self._blocks: list[_SyntheticBlock] = []
        self._next_block = 1
        self._config = config
        self.selected_block_ids: list[tuple[int, ...]] = []
        self.pressure_request_count = 0
        self.forced_release_observed = False
        self.forced_release_count = 0
        self.observation_capabilities = {
            "runtime_identity": {
                "status": "AVAILABLE",
                "reason": "synthetic backend identity is fixed and explicit",
            },
            "logical_lifecycle": {
                "status": "AVAILABLE",
                "reason": "synthetic backend emits approved lifecycle events",
            },
            "prefix_block_mapping": {
                "status": "AVAILABLE",
                "reason": "synthetic BlocksObserved events include block identities",
            },
            "forced_release_snapshot": {
                "status": "AVAILABLE",
                "reason": "synthetic pressure uses ExperimentForcedReleaseObserver",
            },
            "native_block_eviction": {
                "status": "UNAVAILABLE",
                "reason": "synthetic backend has no native block eviction callback",
            },
            "native_block_content_identity": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke does not model native cache content identity",
            },
            "native_block_logical_owners": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke does not expose native owner attribution",
            },
            "native_block_lru_position": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke has no native eviction-time LRU observation",
            },
            "generated_token_count": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke does not execute model generation",
            },
            "native_apc_hit_miss": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke has no native APC",
            },
            "recomputed_prefill_tokens": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke does not execute native prefill",
            },
            "native_first_token_timestamp": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke does not stream native generation",
            },
            "native_scheduler_admission_timestamp": {
                "status": "UNAVAILABLE",
                "reason": "synthetic RequestAdmitted is a logical boundary",
            },
            "hardware_counters": {
                "status": "UNAVAILABLE",
                "reason": "synthetic smoke has no hardware telemetry",
            },
        }

    def execute(self, request: PlannedRequest) -> None:
        self._clock.set(max(self._clock.now(), request.planned_arrival_offset_seconds))
        if request.kind == "pressure":
            self.pressure_request_count += 1
            self._execute_pressure(request)
            return
        program = ProgramIdentity(request.program_id)
        identity = RequestIdentity(request.request_id)
        if request.turn_index == 1:
            self._runtime.handle(ProgramStarted(program, self._clock.now()))
        arrived = self._clock.now()
        self._runtime.handle(RequestArrived(program, identity, arrived))
        admitted = self._clock.advance(0.01)
        self._runtime.handle(RequestAdmitted(program, identity, admitted))
        if not request.is_terminal:
            block = _SyntheticBlock(self._next_block)
            self._next_block += 1
            self._blocks.append(block)
            prefix = PrefixIdentity(f"synthetic:{request.program_id}:{request.turn_index}")
            self._runtime.record_prefill_context_token_count(PrefillContextTokenCountRecord(
                program, identity, prefix, max(1, len(request.prefix_prompt + request.prompt)),
                InputProvenance(InputSource.EXTERNAL),
            ))
            self._runtime.handle(BlocksObserved(
                program, identity, prefix, (BlockIdentity(block.block_id),),
                self._clock.now(),
            ))
        finished = self._clock.advance(0.1)
        self._runtime.handle(TurnFinished(
            program, identity, finished, request.is_terminal, request.next_tool_type
        ))
        if request.is_terminal:
            self._runtime.handle(ProgramCompleted(program, finished))
        if not request.is_terminal:
            assert request.next_tool_type is not None
            assert request.tool_gap_seconds is not None
            followup_request_id = RequestIdentity(
                f"{request.program_id}:turn:{request.turn_index + 1}"
            )
            self._runtime.handle(FollowupWaiting(program, followup_request_id, finished))
            self._runtime.handle(ToolGapStarted(program, request.next_tool_type, finished))
            ended = self._clock.advance(request.tool_gap_seconds)
            self._runtime.handle(ToolGapEnded(program, request.next_tool_type, ended))

    def _execute_pressure(self, request: PlannedRequest) -> None:
        now = self._clock.now()
        self._sink.emit(ExperimentEvent.create(
            event_type="SYNTHETIC_PRESSURE_REQUEST",
            timestamp=now,
            clock_domain="synthetic_monotonic",
            source="phase2.synthetic_smoke",
            payload={"request_id": request.request_id, "prompt": request.prompt},
        ))
        if not self._blocks:
            return
        pressure = self._config["pressure"]
        required = pressure.get("required_blocks", 1)
        if isinstance(required, bool) or not isinstance(required, int) or required < 1:
            raise ValueError("pressure.required_blocks must be positive")
        result = self._pressure.apply_pressure(
            mode=RetentionMode.CONTROLLED,
            blocks=tuple(self._blocks),
            required_blocks=min(required, len(self._blocks)),
            timestamp=now,
            remove_selected=lambda ids: self._remove(ids),
        )
        self.forced_release_observed = self.forced_release_observed or bool(
            result.selection_plan and result.selection_plan.preparation.pressure_releases
        )
        if result.selection_plan and result.selection_plan.preparation.pressure_releases:
            self.forced_release_count += 1
        self.selected_block_ids.append(result.selected_block_ids)
        self._sink.emit(ExperimentEvent.create(
            event_type="SYNTHETIC_PRESSURE_SELECTION",
            timestamp=now,
            clock_domain="synthetic_monotonic",
            source="phase2.synthetic_smoke",
            payload={"selected_block_ids": result.selected_block_ids},
        ))

    def _remove(self, block_ids: tuple[int, ...]) -> None:
        self._blocks = [block for block in self._blocks if block.block_id not in block_ids]

    def close(self) -> None:
        pass

    @property
    def last_selected_block_ids(self) -> tuple[int, ...]:
        return self.selected_block_ids[-1] if self.selected_block_ids else ()


def build_synthetic_smoke_backend(
    config: dict[str, object], sink: ExperimentEventSink
) -> SyntheticSmokeBackend:
    return SyntheticSmokeBackend(config, sink)
