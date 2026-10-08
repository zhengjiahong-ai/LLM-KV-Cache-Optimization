"""Minimal real-runtime Phase 2A observability backend for the pinned Metal stack.

This module is a deployment/test adapter, not a formal experiment backend.  It
reuses the already-qualified Phase 1B native observation hooks so the Phase 2
runner can be exercised against a real vLLM 0.27.1 + vLLM-Metal process without
adding a second private-state inspection path.
"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import time
from collections.abc import Mapping
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any

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
    experiment_event_from_lifecycle,
)
from kvopt.runtime.vllm.h2_intervention import (
    NativeBlockPoolCapture,
    invalidate_prefix_positions,
)
from kvopt.runtime.vllm.observer import install_retention_hook
from kvopt.runtime.vllm.prefill_timing import IsolatedPrefillTimingHook
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
        if not 16 <= size <= 30_720:
            raise ValueError(
                "profiling prefix size must be between 16 and 30720 tokens"
            )
        if size % _BLOCK_SIZE != 0:
            raise ValueError("profiling prefix size must align to the KV block size")
        sizes[program_id] = size
    return sizes


def _expected_profiling_block_override(
    program_prefix_tokens: Mapping[str, int],
    pressure_tokens: int,
    initial_shortage_blocks: int = 1,
) -> int:
    if not program_prefix_tokens:
        raise ValueError("program_prefix_tokens must not be empty")
    if pressure_tokens % _BLOCK_SIZE != 0:
        raise ValueError("pressure token count must align to the KV block size")
    pressure_blocks = pressure_tokens // _BLOCK_SIZE
    if not 1 <= initial_shortage_blocks <= pressure_blocks:
        raise ValueError(
            "initial pressure shortage must be within pressure demand"
        )
    return (
        sum(size // _BLOCK_SIZE for size in program_prefix_tokens.values())
        + pressure_blocks
        + 1
        - initial_shortage_blocks
    )


def _pressure_stage_sizes(options: Mapping[str, object]) -> dict[str, int]:
    raw = options.get("pressure_stage_prompt_tokens")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError("backend_options.pressure_stage_prompt_tokens must be an object")
    sizes: dict[str, int] = {}
    for stage_id, value in raw.items():
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise ValueError(
                "pressure_stage_prompt_tokens keys must be non-empty stage IDs"
            )
        size = _positive_int(
            value,
            f"backend_options.pressure_stage_prompt_tokens[{stage_id!r}]",
        )
        if size % _BLOCK_SIZE != 0:
            raise ValueError(
                "pressure-stage token count must align to the KV block size"
            )
        sizes[stage_id] = size
    return sizes


def _h2_native_prefix_interventions(
    options: Mapping[str, object],
) -> dict[str, tuple[str, int]]:
    raw = options.get("h2_native_prefix_interventions", {})
    if not isinstance(raw, Mapping):
        raise TypeError(
            "backend_options.h2_native_prefix_interventions must be an object"
        )
    interventions: dict[str, tuple[str, int]] = {}
    for request_id, value in raw.items():
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("H2 intervention keys must be non-empty request IDs")
        if not isinstance(value, Mapping):
            raise TypeError(f"H2 intervention {request_id!r} must be an object")
        if set(value) != {"position", "count"}:
            raise ValueError(
                f"H2 intervention {request_id!r} must contain only position and count"
            )
        position = value["position"]
        count = value["count"]
        if position not in {"leading", "trailing"}:
            raise ValueError("H2 intervention position must be leading or trailing")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("H2 intervention count must be a non-negative integer")
        interventions[request_id] = (position, count)
    return interventions


def _required_max_model_len(
    program_prefix_tokens: Mapping[str, int],
    pressure_tokens: int,
    pressure_stage_tokens: Mapping[str, int],
    max_new_tokens: int,
) -> int:
    """Cover the largest materialized prompt and align to a KV block."""

    largest_prompt = max(
        pressure_tokens,
        *(pressure_stage_tokens.values()),
        *(tokens + 1 for tokens in program_prefix_tokens.values()),
    )
    required_tokens = largest_prompt + max_new_tokens
    aligned_tokens = math.ceil(required_tokens / _BLOCK_SIZE) * _BLOCK_SIZE
    return max(_DEFAULT_MAX_MODEL_LEN, aligned_tokens)


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


def _latest_native_apc_hash_chain(
    observations: list[dict[str, object]],
    native_request_id: str,
) -> tuple[str, ...] | None:
    for observation in reversed(observations):
        request_records = observation.get("request_blocks")
        if not isinstance(request_records, list):
            continue
        for request_record in request_records:
            if (
                not isinstance(request_record, Mapping)
                or request_record.get("request_id") != native_request_id
            ):
                continue
            chain = request_record.get("native_apc_hash_chain")
            if not isinstance(chain, Mapping) or chain.get("availability") != "AVAILABLE":
                continue
            hashes = chain.get("native_apc_block_hashes")
            if not isinstance(hashes, list) or not all(
                isinstance(value, str) and value for value in hashes
            ):
                continue
            return tuple(hashes)
    return None


def _validate_native_hash_views(
    request_hashes: tuple[str, ...] | None,
    cache_keys: tuple[bytes, ...],
) -> tuple[str, ...]:
    """Validate request BlockHash values against group-qualified cache keys."""

    if request_hashes is None or len(request_hashes) != len(cache_keys):
        raise RuntimeError(
            "native request hash chain and cache-key chain do not align"
        )
    for position, (request_hash, cache_key) in enumerate(
        zip(request_hashes, cache_keys, strict=True)
    ):
        try:
            request_bytes = bytes.fromhex(request_hash)
        except ValueError as error:
            raise RuntimeError(
                f"native request hash {position} is not hexadecimal"
            ) from error
        if len(cache_key) < 5 or cache_key[:-4] != request_bytes:
            raise RuntimeError(
                "native request hash does not match its group-qualified cache key"
            )
    return request_hashes


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
        self._pressure_stage_tokens = _pressure_stage_sizes(options)
        timing = options.get("execute_planned_timing", False)
        if not isinstance(timing, bool):
            raise TypeError("backend_options.execute_planned_timing must be bool")
        self._execute_planned_timing = timing
        isolated_prefill_timing = options.get(
            "isolated_native_prefill_timing", False
        )
        if not isinstance(isolated_prefill_timing, bool):
            raise TypeError(
                "backend_options.isolated_native_prefill_timing must be bool"
            )
        self._isolated_prefill_timing_enabled = isolated_prefill_timing
        self._isolated_prefill_timings: dict[str, float] = {}
        self._isolated_prefill_timing_hook: IsolatedPrefillTimingHook | None = None
        terminal_snapshot = options.get("capture_terminal_prefix_snapshot", True)
        if not isinstance(terminal_snapshot, bool):
            raise TypeError(
                "backend_options.capture_terminal_prefix_snapshot must be bool"
            )
        self._capture_terminal_prefix_snapshot = terminal_snapshot
        mechanism_only = options.get("h2_native_mechanism_only", False)
        if not isinstance(mechanism_only, bool):
            raise TypeError("backend_options.h2_native_mechanism_only must be bool")
        self._h2_native_mechanism_only = mechanism_only
        self._h2_interventions = _h2_native_prefix_interventions(options)
        self._applied_h2_interventions: set[str] = set()
        if self._h2_interventions and config.get("campaign_kind") not in {
            "h2_formal_measurement",
            "h2_intervention_validation",
        }:
            raise ValueError(
                "native H2 interventions are restricted to H2 measurement campaigns"
            )
        if self._h2_native_mechanism_only and config.get("campaign_kind") not in {
            "h2_formal_measurement",
            "h2_intervention_validation",
        }:
            raise ValueError(
                "native H2 mechanism-only mode is restricted to H2 campaigns"
            )
        block_override = _positive_int(
            config["cache"]["block_override"],  # type: ignore[index]
            "config.cache.block_override",
        )
        if self._program_prefix_tokens:
            initial_shortage_blocks = _positive_int(
                config["pressure"].get("initial_shortage_blocks", 1),  # type: ignore[index,union-attr]
                "config.pressure.initial_shortage_blocks",
            )
            expected_override = _expected_profiling_block_override(
                self._program_prefix_tokens,
                self._pressure_tokens,
                initial_shortage_blocks,
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
            import mlx.core as mx
            import vllm
            import vllm_metal
            from vllm import LLM, SamplingParams
            from vllm.platforms import current_platform
            from vllm.v1.core.block_pool import BlockPool
            from vllm.v1.core.kv_cache_utils import FreeKVCacheBlockQueue
            from vllm.v1.core.sched.scheduler import Scheduler
            from vllm_metal import MetalPlatform, get_config
            from vllm_metal.v1.model_runner import MetalModelRunner
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
        max_new_tokens = _positive_int(
            config["generation"]["max_new_tokens"],  # type: ignore[index]
            "config.generation.max_new_tokens",
        )
        max_model_len = _required_max_model_len(
            self._program_prefix_tokens,
            self._pressure_tokens,
            self._pressure_stage_tokens,
            max_new_tokens,
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
            "max_model_len": max_model_len,
            "max_num_batched_tokens": max_model_len,
            "disable_log_stats": False,
            "prefix_caching_hash_algo": "sha256",
        }
        self._llm = LLM(**llm_kwargs)
        if self._isolated_prefill_timing_enabled:
            self._isolated_prefill_timing_hook = IsolatedPrefillTimingHook(
                MetalModelRunner,
                mx.eval,
                self._record_isolated_prefill_timing,
            )
            self._isolated_prefill_timing_hook.__enter__()
        self._sampling_params = SamplingParams(
            max_tokens=max_new_tokens,
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
        self._native_pool_capture = NativeBlockPoolCapture(recorder)
        bindings = observation_helpers.build_vllm_hook_bindings(Scheduler, BlockPool)
        self._observation_hooks = observation_helpers.ObservationHookSet(
            bindings,
            self._native_pool_capture,
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
        self._level_b_request_count = 0
        self._level_b_raw_complete = True
        self._level_b_first_token_complete = True
        self._level_b_scheduler_timing_complete = True
        self._isolated_prefill_timing_complete = True
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
                "reason": "no request-scoped native observation has completed",
            },
            "recomputed_prefill_tokens": {
                "status": "UNAVAILABLE",
                "reason": "no native hash/cached-token evidence has completed",
            },
            "native_first_token_timestamp": {
                "status": "UNAVAILABLE",
                "reason": "no native request metrics have completed",
            },
            "native_scheduler_admission_timestamp": {
                "status": "UNAVAILABLE",
                "reason": "no native request metrics have completed",
            },
            "isolated_native_prefill_elapsed_seconds": {
                "status": "UNAVAILABLE",
                "reason": (
                    "profiling-only isolated prefill timing has not completed"
                    if self._isolated_prefill_timing_enabled
                    else "profiling-only isolated prefill timing is disabled"
                ),
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
                    "pressure_stage_prompt_tokens": self._pressure_stage_tokens,
                    "execute_planned_timing": self._execute_planned_timing,
                    "h2_native_prefix_intervention_count": len(
                        self._h2_interventions
                    ),
                    "h2_native_mechanism_only": self._h2_native_mechanism_only,
                    "gpu_memory_utilization": gpu_memory_utilization,
                },
            )
        )

    def _update_level_b_capabilities(
        self,
        *,
        raw_complete: bool,
        first_token_complete: bool,
        scheduler_timing_complete: bool,
        isolated_prefill_complete: bool,
    ) -> None:
        self._level_b_request_count += 1
        self._level_b_raw_complete &= raw_complete
        self._level_b_first_token_complete &= first_token_complete
        self._level_b_scheduler_timing_complete &= scheduler_timing_complete
        self._isolated_prefill_timing_complete &= isolated_prefill_complete

        raw_status = "AVAILABLE" if self._level_b_raw_complete else "UNAVAILABLE"
        raw_reason = (
            "all completed requests exposed native prompt, APC hash, and cached-token facts"
            if self._level_b_raw_complete
            else "one or more requests lacked native prompt, APC hash, or cached-token facts"
        )
        self.observation_capabilities["native_apc_hit_miss"] = {
            "status": raw_status,
            "reason": raw_reason,
        }
        self.observation_capabilities["recomputed_prefill_tokens"] = {
            "status": raw_status,
            "reason": raw_reason,
        }
        self.observation_capabilities["native_first_token_timestamp"] = {
            "status": (
                "AVAILABLE"
                if self._level_b_first_token_complete
                else "UNAVAILABLE"
            ),
            "reason": (
                "all completed requests exposed EngineCore first-token timestamps"
                if self._level_b_first_token_complete
                else "one or more requests lacked EngineCore first-token timestamps"
            ),
        }
        self.observation_capabilities[
            "native_scheduler_admission_timestamp"
        ] = {
            "status": (
                "AVAILABLE"
                if self._level_b_scheduler_timing_complete
                else "UNAVAILABLE"
            ),
            "reason": (
                "all completed requests exposed EngineCore queued and first-scheduled timestamps"
                if self._level_b_scheduler_timing_complete
                else "one or more requests lacked EngineCore queued or first-scheduled timestamps"
            ),
        }
        self.observation_capabilities[
            "isolated_native_prefill_elapsed_seconds"
        ] = {
            "status": (
                "AVAILABLE"
                if self._isolated_prefill_timing_complete
                else "UNAVAILABLE"
            ),
            "reason": (
                "all completed requests exposed profiling-only synchronized prefill timing"
                if self._isolated_prefill_timing_complete
                else "one or more requests lacked profiling-only synchronized prefill timing"
            ),
        }

    def _record_isolated_prefill_timing(
        self,
        native_request_id: str,
        elapsed_seconds: float,
    ) -> None:
        if native_request_id in self._isolated_prefill_timings:
            raise RuntimeError("duplicate isolated prefill timing observation")
        self._isolated_prefill_timings[native_request_id] = elapsed_seconds

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
        prompt_token_ids = getattr(output, "prompt_token_ids", None)
        native_prompt_tokens = (
            len(prompt_token_ids)
            if isinstance(prompt_token_ids, (list, tuple))
            else None
        )
        raw_cached_tokens = getattr(output, "num_cached_tokens", None)
        native_cached_prefix_tokens = (
            raw_cached_tokens
            if isinstance(raw_cached_tokens, int)
            and not isinstance(raw_cached_tokens, bool)
            and raw_cached_tokens >= 0
            else None
        )
        metrics = getattr(output, "metrics", None)

        def metric_timestamp(name: str) -> float | None:
            value = None if metrics is None else getattr(metrics, name, None)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            result = float(value)
            return result if math.isfinite(result) and result > 0 else None

        native_queued = metric_timestamp("queued_ts")
        native_scheduled = metric_timestamp("scheduled_ts")
        native_first_token = metric_timestamp("first_token_ts")
        isolated_native_prefill = self._isolated_prefill_timings.pop(
            native_id,
            None,
        )
        native_hashes = _latest_native_apc_hash_chain(
            self._native_observations,
            native_id,
        )
        native_event_timestamp = next(
            (
                value
                for value in (
                    native_first_token,
                    native_scheduled,
                    native_queued,
                )
                if value is not None
            ),
            0.0,
        )
        self._update_level_b_capabilities(
            raw_complete=(
                native_prompt_tokens is not None
                and native_cached_prefix_tokens is not None
                and native_hashes is not None
            ),
            first_token_complete=native_first_token is not None,
            scheduler_timing_complete=(
                native_queued is not None and native_scheduled is not None
            ),
            isolated_prefill_complete=(
                self._isolated_prefill_timing_enabled
                and isolated_native_prefill is not None
            ),
        )
        self._sink.emit(
            ExperimentEvent.create(
                event_type="VLLM_NATIVE_REQUEST_OBSERVATION",
                timestamp=native_event_timestamp,
                clock_domain="engine_core_monotonic",
                source="phase2.minimal_metal",
                native_request_id=native_id,
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload={
                    "native_prompt_tokens": native_prompt_tokens,
                    "native_cached_prefix_tokens": (
                        native_cached_prefix_tokens
                    ),
                    "native_apc_block_hashes": (
                        None if native_hashes is None else native_hashes
                    ),
                    "native_hash_block_size": _BLOCK_SIZE,
                    "native_hash_process_id": str(os.getpid()),
                    "native_hash_function": "sha256",
                    "native_queued_timestamp": native_queued,
                    "native_scheduler_admission_timestamp": (
                        native_scheduled
                    ),
                    "native_first_token_timestamp": native_first_token,
                    "isolated_native_prefill_elapsed_seconds": (
                        isolated_native_prefill
                    ),
                },
            )
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
    ) -> tuple[
        PrefixIdentity,
        int,
        tuple[BlockIdentity, ...],
        tuple[int, ...],
        tuple[bytes, ...],
    ]:
        prefix_value, token_count, block_ids, hashes = self._coherent_snapshot(
            self._native_observations,
            native_id,
            expected_token_count=expected_token_count,
        )
        request_hashes = _validate_native_hash_views(
            _latest_native_apc_hash_chain(
                self._native_observations,
                native_id,
            ),
            hashes,
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
                    "ordered_native_hashes": request_hashes,
                    "ordered_native_cache_keys": tuple(
                        native_hash.hex() for native_hash in hashes
                    ),
                    "hash_num_tokens": token_count,
                    "native_hash_block_size": _BLOCK_SIZE,
                    "native_hash_process_id": str(os.getpid()),
                    "native_hash_function": "sha256",
                },
            )
        )
        return prefix, token_count, blocks, tuple(block_ids), tuple(hashes)

    def _apply_h2_intervention(
        self,
        request: PlannedRequest,
        prefix: PrefixIdentity,
        block_ids: tuple[int, ...],
        cache_keys: tuple[bytes, ...],
    ) -> None:
        spec = self._h2_interventions.get(request.request_id)
        if spec is None:
            return
        if request.request_id in self._applied_h2_interventions:
            raise RuntimeError("H2 native prefix intervention was applied twice")
        if request.is_terminal:
            raise ValueError("H2 native prefix intervention requires a return request")
        pool = self._native_pool_capture.pool
        if pool is None:
            raise RuntimeError("native BlockPool was not observed before H2 intervention")
        position, count = spec
        result = invalidate_prefix_positions(
            pool,
            block_ids,
            cache_keys,
            position=position,
            count=count,
        )
        self._applied_h2_interventions.add(request.request_id)
        self._sink.emit(
            ExperimentEvent.create(
                event_type="H2_NATIVE_PREFIX_INTERVENTION",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                prefix_id=prefix,
                payload=result,
            )
        )

    def _handle_lifecycle(self, event: object) -> None:
        if self._h2_native_mechanism_only:
            self._sink.emit(experiment_event_from_lifecycle(event))
            return
        self._runtime.handle(event)

    def _execute_turn(self, request: PlannedRequest) -> None:
        self._wait_for_planned_arrival(request)
        program = ProgramIdentity(request.program_id)
        logical_request = RequestIdentity(request.request_id)
        now = float(self._clock.now())
        if request.program_id not in self._started_programs:
            self._handle_lifecycle(ProgramStarted(program, now))
            self._started_programs.add(request.program_id)

        pending_tool = self._pending_tool_gaps.pop(request.program_id, None)
        if pending_tool is not None:
            self._handle_lifecycle(ToolGapEnded(program, pending_tool, now))

        self._handle_lifecycle(RequestArrived(program, logical_request, now))
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
        self._handle_lifecycle(RequestAdmitted(program, logical_request, submitted_at))
        finished_at = self._complete(request, native_id, external_id)
        if request.is_terminal and not self._capture_terminal_prefix_snapshot:
            self._handle_lifecycle(
                TurnFinished(
                    program,
                    logical_request,
                    finished_at,
                    is_terminal=True,
                )
            )
            self._handle_lifecycle(ProgramCompleted(program, finished_at))
            return
        prefix, token_count, blocks, block_ids, cache_keys = self._prefix_snapshot(
            request,
            native_id,
            expected_token_count=prefix_tokens,
        )

        if request.is_terminal:
            self._handle_lifecycle(
                TurnFinished(
                    program,
                    logical_request,
                    finished_at,
                    is_terminal=True,
                )
            )
            self._handle_lifecycle(ProgramCompleted(program, finished_at))
            return

        if not self._h2_native_mechanism_only:
            self._runtime.record_prefill_context_token_count(
                PrefillContextTokenCountRecord(
                    program_id=program,
                    request_id=logical_request,
                    prefix_id=prefix,
                    token_count=token_count,
                    provenance=InputProvenance(InputSource.OBSERVED),
                )
            )
        self._handle_lifecycle(
            BlocksObserved(
                program,
                logical_request,
                prefix,
                blocks,
                finished_at,
            )
        )
        self._apply_h2_intervention(
            request,
            prefix,
            block_ids,
            cache_keys,
        )
        self._handle_lifecycle(
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
        self._handle_lifecycle(FollowupWaiting(program, followup_id, finished_at))
        assert request.next_tool_type is not None
        self._handle_lifecycle(
            ToolGapStarted(program, request.next_tool_type, finished_at)
        )
        self._pending_tool_gaps[request.program_id] = request.next_tool_type

    def _execute_pressure(self, request: PlannedRequest) -> None:
        self._wait_for_planned_arrival(request)
        stage_id = request.program_id.removeprefix("pressure:")
        pressure_tokens = self._pressure_stage_tokens.get(
            stage_id,
            self._pressure_tokens,
        )
        token_ids = _pressure_token_ids(
            request,
            vocabulary_size=self._vocabulary_size,
            token_count=pressure_tokens,
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
            try:
                if self._isolated_prefill_timing_hook is not None:
                    self._isolated_prefill_timing_hook.__exit__(None, None, None)
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
