"""Minimal real-runtime Phase 2A observability backend for the pinned Metal stack.

This module is a deployment/test adapter, not a formal experiment backend.  It
reuses the already-qualified Phase 1B native observation hooks so the Phase 2
runner can be exercised against a real vLLM 0.27.1 + vLLM-Metal process without
adding a second private-state inspection path.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import time
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, Mapping

from kvopt.continuum import (
    BlockEvicted,
    BlockIdentity,
    BlocksObserved,
    ContinuumConfig,
    FollowupWaiting,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramCompleted,
    ProgramIdentity,
    ProgramStarted,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    RetentionMode,
    SystemMonotonicClock,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)
from kvopt.continuum.composition import build_runtime_from_config
from kvopt.profiling.experiment_events import (
    ExperimentEvent,
    ExperimentEventSink,
    ExperimentForcedReleaseObserver,
)
from kvopt.runtime.vllm.observer import install_retention_hook
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration
from kvopt.workload.phase2 import PlannedRequest


_TARGET_PREFIX_TOKENS = 256
_PRESSURE_TOKENS = 512
_BLOCK_SIZE = 16
_DEFAULT_BLOCK_OVERRIDE = 64
_DEFAULT_MAX_MODEL_LEN = _PRESSURE_TOKENS + _BLOCK_SIZE


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_options(config: Mapping[str, object]) -> Mapping[str, object]:
    value = config.get("backend_options", {})
    if not isinstance(value, Mapping):
        raise TypeError("config.backend_options must be an object")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _positive_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not (0.0 < result <= 1.0):
        raise ValueError(f"{field} must be in (0, 1]")
    return result


def _resolve_repo_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    path = Path(value)
    if not path.is_absolute():
        path = _repo_root() / path
    return path.resolve()


def _program_prefix_sizes(options: Mapping[str, object]) -> dict[str, int]:
    raw = options.get("program_prefix_tokens")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError("backend_options.program_prefix_tokens must be an object")
    sizes: dict[str, int] = {}
    for program_id, value in raw.items():
        if not isinstance(program_id, str) or not program_id.strip():
            raise ValueError("program_prefix_tokens keys must be non-empty program IDs")
        size = _positive_int(
            value,
            f"backend_options.program_prefix_tokens[{program_id!r}]",
        )
        if size not in {128, 256, 512}:
            raise ValueError("profiling prefix size must be one of 128, 256, 512")
        if size % _BLOCK_SIZE != 0:
            raise ValueError("profiling prefix size must align to the KV block size")
        sizes[program_id] = size
    return sizes


def _expected_profiling_block_override(
    program_prefix_tokens: Mapping[str, int],
    pressure_tokens: int,
) -> int:
    if not program_prefix_tokens:
        raise ValueError("program_prefix_tokens must not be empty")
    if pressure_tokens % _BLOCK_SIZE != 0:
        raise ValueError("pressure token count must align to the KV block size")
    return (
        sum(size // _BLOCK_SIZE for size in program_prefix_tokens.values())
        + pressure_tokens // _BLOCK_SIZE
    )


def _program_prefix_token_ids(
    program_id: str, *, vocabulary_size: int, token_count: int
) -> tuple[int, ...]:
    """Create a deterministic full-block prefix distinct for each program."""
    if vocabulary_size <= 40_000:
        raise RuntimeError("qualified observability adapter requires vocabulary > 40000")
    digest = hashlib.sha256(program_id.encode("utf-8")).digest()
    namespace = int.from_bytes(digest[:4], "big")
    base = 1_000 + namespace % 20_000
    return tuple((base + index * 37) % vocabulary_size for index in range(token_count))


def _turn_token_ids(
    request: PlannedRequest, *, vocabulary_size: int, prefix_tokens: int
) -> tuple[int, ...]:
    prefix = _program_prefix_token_ids(
        request.program_id,
        vocabulary_size=vocabulary_size,
        token_count=prefix_tokens,
    )
    digest = hashlib.sha256(request.request_id.encode("utf-8")).digest()
    suffix = 30_000 + int.from_bytes(digest[:2], "big") % 5_000
    return (*prefix, suffix % vocabulary_size)


def _pressure_token_ids(request: PlannedRequest, *, vocabulary_size: int, token_count: int) -> tuple[int, ...]:
    digest = hashlib.sha256(request.request_id.encode("utf-8")).digest()
    namespace = int.from_bytes(digest[:4], "big")
    base = 13_000 + namespace % 5_000
    return tuple((base + index * 29) % vocabulary_size for index in range(token_count))


class _CountingForcedReleaseObserver:
    def __init__(self, sink: ExperimentEventSink) -> None:
        self._delegate = ExperimentForcedReleaseObserver(sink)
        self.count = 0

    def observe(self, snapshot: Any) -> None:
        self._delegate.observe(snapshot)
        if tuple(snapshot.selected_releases):
            self.count += 1


class _ObservedRetentionIntegration:
    """Expose control-plane counts and physical evictions without changing policy."""

    def __init__(
        self,
        runtime: Any,
        clock: SystemMonotonicClock,
        forced_release_observer: _CountingForcedReleaseObserver,
    ) -> None:
        self._runtime = runtime
        self._clock = clock
        self._delegate = RetentionRuntimeIntegration(
            runtime.retention,
            forced_release_observer,
        )
        self.last_selected_block_ids: tuple[int, ...] = ()

    def apply_pressure(self, **kwargs: object) -> Any:
        result = self._delegate.apply_pressure(**kwargs)
        self.last_selected_block_ids = tuple(result.selected_block_ids)
        return result

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        # Runtime.handle() owns both retention cleanup and raw BLOCK_EVICTED
        # emission; do not call delegate.observe_native_eviction() as well.
        self._runtime.handle(BlockEvicted(block_id, self._clock.now()))


class MinimalMetalObservabilityBackend:
    """Run a tiny two-prefix real-runtime scenario through the Phase 2 contract."""

    def __init__(self, config: dict[str, object], sink: ExperimentEventSink) -> None:
        if config.get("runtime_mode") != "vllm-metal-observability":
            raise ValueError("runtime_mode must be vllm-metal-observability")
        if not callable(getattr(sink, "emit", None)):
            raise TypeError("sink must provide emit")
        if os.environ.get("VLLM_ENABLE_V1_MULTIPROCESSING") != "0":
            raise RuntimeError(
                "minimal Metal observation requires VLLM_ENABLE_V1_MULTIPROCESSING=0"
            )

        self._sink = sink
        self._clock = SystemMonotonicClock()
        options = _backend_options(config)
        profile_path = _resolve_repo_path(
            options.get(
                "prefill_profile_path",
                "docs/experiments/phase1b-continuum/artifacts/"
                "prefill-reload-profile-formal-20260920T045859Z-6183d106.json",
            ),
            "backend_options.prefill_profile_path",
        )
        if not profile_path.is_file():
            raise FileNotFoundError(f"PrefillReload profile not found: {profile_path}")

        self._prefix_tokens = _positive_int(
            options.get("target_prefix_tokens", _TARGET_PREFIX_TOKENS),
            "backend_options.target_prefix_tokens",
        )
        self._program_prefix_tokens = _program_prefix_sizes(options)
        self._pressure_tokens = _positive_int(
            options.get("pressure_prompt_tokens", _PRESSURE_TOKENS),
            "backend_options.pressure_prompt_tokens",
        )
        timing = options.get("execute_planned_timing", False)
        if not isinstance(timing, bool):
            raise TypeError("backend_options.execute_planned_timing must be bool")
        self._execute_planned_timing = timing
        block_override = _positive_int(
            config["cache"]["block_override"],  # type: ignore[index]
            "config.cache.block_override",
        )
        if self._program_prefix_tokens:
            expected_override = _expected_profiling_block_override(
                self._program_prefix_tokens,
                self._pressure_tokens,
            )
            if block_override != expected_override:
                raise ValueError(
                    "profiling cache.block_override must equal protected-prefix blocks "
                    "+ pressure-demand blocks"
                )
        else:
            if block_override != _DEFAULT_BLOCK_OVERRIDE:
                raise ValueError(
                    "minimal two-candidate observability test requires cache.block_override=64"
                )
            if (
                self._prefix_tokens != _TARGET_PREFIX_TOKENS
                or self._pressure_tokens != _PRESSURE_TOKENS
            ):
                raise ValueError(
                    "qualified minimal test requires 256-prefix / 512-pressure tokens"
                )

        continuum_config = ContinuumConfig(
            enabled=True,
            prefill_profile_path=str(profile_path),
            prefill_profile_version="v1",
        )
        self._runtime = build_runtime_from_config(
            config=continuum_config,
            clock=self._clock,
            experiment_event_sink=sink,
        )
        self._forced_release_observer = _CountingForcedReleaseObserver(sink)
        self._retention_integration = _ObservedRetentionIntegration(
            self._runtime,
            self._clock,
            self._forced_release_observer,
        )

        try:
            from vllm import LLM, SamplingParams
            import mlx.core as mx
            import vllm
            import vllm_metal
            from vllm.platforms import current_platform
            from vllm.v1.core.block_pool import BlockPool
            from vllm.v1.core.kv_cache_utils import FreeKVCacheBlockQueue
            from vllm.v1.core.sched.scheduler import Scheduler
            from vllm_metal import MetalPlatform, get_config
        except ImportError as error:
            raise RuntimeError(
                "minimal real-runtime test requires the pinned vLLM/Metal environment"
            ) from error

        observation_helpers = importlib.import_module(
            "scripts.spikes.run_continuum_vllm_observation"
        )
        validation_helpers = importlib.import_module(
            "scripts.spikes.run_continuum_phase1b_validation_metal"
        )
        self._coherent_snapshot = validation_helpers._coherent_child_request_snapshot

        topology = observation_helpers.require_observation_topology(os.environ)
        metal_config = get_config()
        platform_plugin_class = (
            f"{type(current_platform).__module__}.{type(current_platform).__qualname__}"
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

        source_identity: dict[str, object]
        checkout = os.environ.get("VLLM_METAL_SOURCE_CHECKOUT")
        if checkout:
            source_identity = observation_helpers.inspect_vllm_metal_source_identity(
                Path(checkout),
                Path(vllm_metal.__file__),
            )
        else:
            source_identity = {
                "source_identity_availability": "unavailable",
                "source_identity_reason": "VLLM_METAL_SOURCE_CHECKOUT not provided",
            }

        model = config["model"]
        tokenizer_config = config["tokenizer"]
        if not isinstance(model, Mapping) or not isinstance(tokenizer_config, Mapping):
            raise TypeError("model/tokenizer config must be objects")
        gpu_memory_utilization = _positive_float(
            options.get("gpu_memory_utilization", 0.8),
            "backend_options.gpu_memory_utilization",
        )
        llm_kwargs = {
            "model": model["name"],
            "revision": model["revision"],
            "tokenizer": tokenizer_config["name"],
            "tokenizer_revision": tokenizer_config["revision"],
            "enable_prefix_caching": True,
            "gpu_memory_utilization": gpu_memory_utilization,
            "seed": int(config["seed"]),
            "num_gpu_blocks_override": block_override,
            "max_model_len": _DEFAULT_MAX_MODEL_LEN,
            "max_num_batched_tokens": _DEFAULT_MAX_MODEL_LEN,
        }
        self._llm = LLM(**llm_kwargs)
        self._sampling_params = SamplingParams(
            max_tokens=int(config["generation"]["max_new_tokens"]),  # type: ignore[index]
            temperature=float(config["generation"]["temperature"]),  # type: ignore[index]
            seed=int(config["seed"]),
        )
        tokenizer = self._llm.get_tokenizer()
        try:
            self._vocabulary_size = len(tokenizer)
        except TypeError as error:
            raise RuntimeError("tokenizer did not expose vocabulary size") from error
        if self._vocabulary_size <= 40_000:
            raise RuntimeError("tokenizer vocabulary is too small for qualified token patterns")

        self._registry = observation_helpers.ProgramRequestRegistry()
        self._external_ids = observation_helpers._external_request_ids_for_internal
        self._native_observations: list[dict[str, object]] = []
        recorder = observation_helpers.NativeObservationRecorder(
            self._registry,
            self._native_observations.append,
        )
        bindings = observation_helpers.build_vllm_hook_bindings(Scheduler, BlockPool)
        self._observation_hooks = observation_helpers.ObservationHookSet(
            bindings,
            recorder,
            enabled=True,
        )
        self._observation_hooks.__enter__()

        if getattr(FreeKVCacheBlockQueue, "_kvopt_policy_installed", False):
            self._observation_hooks.__exit__(None, None, None)
            raise RuntimeError("real-runtime observability backend requires a fresh process")
        install_retention_hook(
            mode=RetentionMode.CONTROLLED,
            integration=self._retention_integration,
            clock=self._clock,
        )

        self._started_programs: set[str] = set()
        self._pending_tool_gaps: dict[str, str] = {}
        self._closed = False
        self._run_start_timestamp = float(self._clock.now())
        self.observation_capabilities = {
            "runtime_identity": {
                "status": "AVAILABLE",
                "reason": "REAL_RUNTIME_READY records pinned vLLM/Metal runtime identity",
            },
            "logical_lifecycle": {
                "status": "AVAILABLE",
                "reason": "approved lifecycle events are persisted",
            },
            "prefix_block_mapping": {
                "status": "AVAILABLE",
                "reason": "BLOCKS_OBSERVED and VLLM_PREFIX_SNAPSHOT map prefixes to blocks",
            },
            "forced_release_snapshot": {
                "status": "AVAILABLE",
                "reason": "FORCED_RELEASE_DECISION is emitted by the approved observer",
            },
            "native_block_eviction": {
                "status": "AVAILABLE",
                "reason": "native eviction callback is bridged to BLOCK_EVICTED",
            },
            "native_block_content_identity": {
                "status": "UNAVAILABLE",
                "reason": "current approved eviction callback does not persist pre-eviction content identity",
            },
            "native_block_logical_owners": {
                "status": "UNAVAILABLE",
                "reason": "current approved eviction callback does not persist logical owner attribution",
            },
            "native_block_lru_position": {
                "status": "UNAVAILABLE",
                "reason": "current approved eviction callback does not persist eviction-time native LRU position",
            },
            "generated_token_count": {
                "status": "AVAILABLE",
                "reason": "VLLM_REQUEST_COMPLETED records output_token_count",
            },
            "native_apc_hit_miss": {
                "status": "UNAVAILABLE",
                "reason": "current approved backend boundary has no stable per-request APC hit/miss event",
            },
            "recomputed_prefill_tokens": {
                "status": "UNAVAILABLE",
                "reason": "current approved backend boundary has no direct recomputation-token event",
            },
            "native_first_token_timestamp": {
                "status": "UNAVAILABLE",
                "reason": "wait_for_completion does not expose a first-token timestamp",
            },
            "native_scheduler_admission_timestamp": {
                "status": "UNAVAILABLE",
                "reason": "REQUEST_ADMITTED is a logical retention boundary, not native scheduler timing",
            },
            "hardware_counters": {
                "status": "UNAVAILABLE",
                "reason": "device counters are intentionally outside the low-configuration Metal backend",
            },
        }

        self._sink.emit(
            ExperimentEvent.create(
                event_type="REAL_RUNTIME_READY",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                payload={
                    **topology,
                    **runtime_identity,
                    **source_identity,
                    "cache_block_override": block_override,
                    "block_size": _BLOCK_SIZE,
                    "target_prefix_tokens": self._prefix_tokens,
                    "program_prefix_tokens": self._program_prefix_tokens,
                    "pressure_prompt_tokens": self._pressure_tokens,
                    "execute_planned_timing": self._execute_planned_timing,
                    "gpu_memory_utilization": gpu_memory_utilization,
                },
            )
        )

    @property
    def forced_release_count(self) -> int:
        return self._forced_release_observer.count

    @property
    def last_selected_block_ids(self) -> tuple[int, ...]:
        return self._retention_integration.last_selected_block_ids

    def _prefix_tokens_for(self, request: PlannedRequest) -> int:
        return self._program_prefix_tokens.get(
            request.program_id,
            self._prefix_tokens,
        )

    def _wait_for_planned_arrival(self, request: PlannedRequest) -> None:
        if not self._execute_planned_timing:
            return
        planned_offset = request.planned_arrival_offset_seconds
        target = self._run_start_timestamp + planned_offset
        now = float(self._clock.now())
        if target > now:
            time.sleep(target - now)
        observed = float(self._clock.now())
        self._sink.emit(
            ExperimentEvent.create(
                event_type="PLANNED_ARRIVAL_REACHED",
                timestamp=observed,
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload={
                    "planned_arrival_offset_seconds": planned_offset,
                    "run_start_timestamp": self._run_start_timestamp,
                    "planned_arrival_timestamp": target,
                    "observed_arrival_boundary_timestamp": observed,
                    "lateness_seconds": max(0.0, observed - target),
                },
            )
        )

    def _emit_materialization(
        self,
        request: PlannedRequest,
        token_ids: tuple[int, ...],
        *,
        reusable_prefix_tokens: int | None = None,
    ) -> None:
        self._sink.emit(
            ExperimentEvent.create(
                event_type="BACKEND_INPUT_MATERIALIZED",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload={
                    "kind": request.kind,
                    "token_count": len(token_ids),
                    "reusable_prefix_token_count": reusable_prefix_tokens,
                    "materialization": "deterministic_token_ids",
                },
            )
        )

    def _enqueue(
        self,
        request: PlannedRequest,
        token_ids: tuple[int, ...],
        *,
        reusable_prefix_tokens: int | None = None,
    ) -> tuple[str, str, float]:
        self._emit_materialization(
            request,
            token_ids,
            reusable_prefix_tokens=reusable_prefix_tokens,
        )
        native_ids = tuple(
            self._llm.enqueue(
                [{"prompt_token_ids": list(token_ids)}],
                self._sampling_params,
                use_tqdm=False,
            )
        )
        if len(native_ids) != 1 or not isinstance(native_ids[0], str):
            raise RuntimeError("native enqueue did not return one request ID")
        native_id = native_ids[0]
        self._registry.register_batch((request.program_id,), native_ids)
        external_ids = self._external_ids(self._llm, native_ids)
        if len(external_ids) != 1 or not isinstance(external_ids[0], str):
            raise RuntimeError("native request did not expose one external request ID")
        external_id = external_ids[0]
        self._registry.register_external_batch(native_ids, external_ids)
        submitted_at = float(self._clock.now())
        self._sink.emit(
            ExperimentEvent.create(
                event_type="VLLM_REQUEST_SUBMITTED",
                timestamp=submitted_at,
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload={
                    "native_request_id": native_id,
                    "external_request_id": external_id,
                },
            )
        )
        return native_id, external_id, submitted_at

    def _complete(
        self,
        request: PlannedRequest,
        native_id: str,
        external_id: str,
    ) -> float:
        outputs = tuple(self._llm.wait_for_completion(use_tqdm=False))
        if len(outputs) != 1:
            raise RuntimeError("native request did not produce exactly one completion")
        output = outputs[0]
        if getattr(output, "request_id", None) != external_id:
            raise RuntimeError("completion external request ID does not match submission")
        completions = tuple(getattr(output, "outputs", ()))
        output_token_count = sum(
            len(tuple(getattr(completion, "token_ids", ())))
            for completion in completions
        )
        finished_at = float(self._clock.now())
        self._sink.emit(
            ExperimentEvent.create(
                event_type="VLLM_REQUEST_COMPLETED",
                timestamp=finished_at,
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload={
                    "native_request_id": native_id,
                    "external_request_id": external_id,
                    "finished": bool(getattr(output, "finished", False)),
                    "output_token_count": output_token_count,
                },
            )
        )
        return finished_at

    def _prefix_snapshot(
        self,
        request: PlannedRequest,
        native_id: str,
        *,
        expected_token_count: int,
    ) -> tuple[PrefixIdentity, int, tuple[BlockIdentity, ...]]:
        prefix_value, token_count, block_ids, _hashes = self._coherent_snapshot(
            self._native_observations,
            native_id,
            expected_token_count=expected_token_count,
        )
        prefix = PrefixIdentity(prefix_value)
        blocks = tuple(BlockIdentity(block_id) for block_id in block_ids)
        self._sink.emit(
            ExperimentEvent.create(
                event_type="VLLM_PREFIX_SNAPSHOT",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                prefix_id=prefix,
                payload={
                    "reusable_token_count": token_count,
                    "block_ids": tuple(block.block_id for block in blocks),
                },
            )
        )
        return prefix, token_count, blocks

    def _execute_turn(self, request: PlannedRequest) -> None:
        self._wait_for_planned_arrival(request)
        program = ProgramIdentity(request.program_id)
        logical_request = RequestIdentity(request.request_id)
        now = float(self._clock.now())
        if request.program_id not in self._started_programs:
            self._runtime.handle(ProgramStarted(program, now))
            self._started_programs.add(request.program_id)

        pending_tool = self._pending_tool_gaps.pop(request.program_id, None)
        if pending_tool is not None:
            self._runtime.handle(ToolGapEnded(program, pending_tool, now))

        self._runtime.handle(RequestArrived(program, logical_request, now))
        prefix_tokens = self._prefix_tokens_for(request)
        token_ids = _turn_token_ids(
            request,
            vocabulary_size=self._vocabulary_size,
            prefix_tokens=prefix_tokens,
        )
        native_id, external_id, submitted_at = self._enqueue(
            request,
            token_ids,
            reusable_prefix_tokens=prefix_tokens,
        )
        # This is the framework's logical admission boundary (engine enqueue
        # accepted), not a claim of native scheduler-admission timestamp.
        self._runtime.handle(RequestAdmitted(program, logical_request, submitted_at))
        finished_at = self._complete(request, native_id, external_id)
        prefix, token_count, blocks = self._prefix_snapshot(
            request,
            native_id,
            expected_token_count=prefix_tokens,
        )

        if request.is_terminal:
            self._runtime.handle(
                TurnFinished(
                    program,
                    logical_request,
                    finished_at,
                    is_terminal=True,
                )
            )
            self._runtime.handle(ProgramCompleted(program, finished_at))
            return

        self._runtime.record_prefill_context_token_count(
            PrefillContextTokenCountRecord(
                program_id=program,
                request_id=logical_request,
                prefix_id=prefix,
                token_count=token_count,
                provenance=InputProvenance(InputSource.OBSERVED),
            )
        )
        self._runtime.handle(
            BlocksObserved(
                program,
                logical_request,
                prefix,
                blocks,
                finished_at,
            )
        )
        self._runtime.handle(
            TurnFinished(
                program,
                logical_request,
                finished_at,
                is_terminal=False,
                next_tool_type=request.next_tool_type,
            )
        )
        followup_id = RequestIdentity(
            f"{request.program_id}:turn:{request.turn_index + 1}"
        )
        self._runtime.handle(FollowupWaiting(program, followup_id, finished_at))
        assert request.next_tool_type is not None
        self._runtime.handle(
            ToolGapStarted(program, request.next_tool_type, finished_at)
        )
        self._pending_tool_gaps[request.program_id] = request.next_tool_type

    def _execute_pressure(self, request: PlannedRequest) -> None:
        self._wait_for_planned_arrival(request)
        token_ids = _pressure_token_ids(
            request,
            vocabulary_size=self._vocabulary_size,
            token_count=self._pressure_tokens,
        )
        native_id, external_id, _submitted_at = self._enqueue(request, token_ids)
        finished_at = self._complete(request, native_id, external_id)
        self._sink.emit(
            ExperimentEvent.create(
                event_type="PRESSURE_REQUEST_COMPLETED",
                timestamp=finished_at,
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload={
                    "forced_release_count": self.forced_release_count,
                    "last_selected_block_ids": self.last_selected_block_ids,
                },
            )
        )

    def execute(self, request: PlannedRequest) -> None:
        if not isinstance(request, PlannedRequest):
            raise TypeError("request must be PlannedRequest")
        if request.kind == "pressure":
            self._execute_pressure(request)
        else:
            self._execute_turn(request)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._observation_hooks.__exit__(None, None, None)
        finally:
            engine = getattr(self._llm, "llm_engine", None)
            shutdown = getattr(engine, "shutdown", None)
            if callable(shutdown):
                shutdown()


def build_phase2_metal_observability_backend(
    config: dict[str, object],
    sink: ExperimentEventSink,
) -> MinimalMetalObservabilityBackend:
    return MinimalMetalObservabilityBackend(config, sink)
