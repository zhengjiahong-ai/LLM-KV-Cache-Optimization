"""Minimal real-runtime Phase 2A observability backend for the pinned Metal stack.

This module is a deployment/test adapter, not a formal experiment backend.  It
reuses the already-qualified Phase 1B native observation hooks so the Phase 2
runner can be exercised against a real vLLM 0.27.1 + vLLM-Metal process without
adding a second private-state inspection path.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import signal
import threading
import time
from bisect import bisect_right
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
from kvopt.continuum.runtime import build_runtime
from kvopt.costaware.a1_native import A1NativeSelectionCoordinator
from kvopt.costaware.a2_native import (
    A2NativeChainSnapshot,
    A2NativeDecisionAudit,
    A2NativeSelectionCoordinator,
    A2NativeSnapshotRegistry,
)
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
from kvopt.runtime.vllm.observer import (
    NativeHashedEvictionObservation,
    install_retention_hook,
)
from kvopt.runtime.vllm.prefill_timing import IsolatedPrefillTimingHook
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration
from kvopt.workload.phase2 import PlannedRequest
from kvopt.workload.phase2b_fidelity import (
    KNOWN_CAPABILITIES,
    PREFIX_GENERATOR_VERSION,
    phase2b_turn_token_ids,
    token_ids_sha256,
    validate_distinct_content_keys,
)
from kvopt.workload.phase2b_fidelity_runner import (
    RequestCompletion,
    RequestHandle,
)
from kvopt.workload.phase2c_native_pilot import (
    PILOT_PREFIX_GENERATOR_VERSION,
    segmented_turn_token_ids,
)

_TARGET_PREFIX_TOKENS = 256
_PRESSURE_TOKENS = 512
_PHASE2G_A2_CAMPAIGN_KINDS = frozenset(
    {
        "phase2g_a2_native_gate1",
        "phase2g_a2_gate2_bounded_evaluation",
        "phase2g_a2_native_evidence_fidelity",
    }
)
_PHASE2G_UNIQUE_PROTECTED_BLOCK_CAMPAIGN_KINDS = frozenset(
    {
        "phase2g_a1_bounded_evaluation",
        "phase2g_a2_prefill_profile_bridge_control",
        *_PHASE2G_A2_CAMPAIGN_KINDS,
    }
)


def _phase2g_a2_campaign_allowed(campaign_kind: object) -> bool:
    return campaign_kind in _PHASE2G_A2_CAMPAIGN_KINDS


def _phase2g_unique_protected_block_campaign_allowed(campaign_kind: object) -> bool:
    return campaign_kind in _PHASE2G_UNIQUE_PROTECTED_BLOCK_CAMPAIGN_KINDS


class _H2M4MeasuredPrefillProvider:
    """M1-backed TTL input used only to execute the frozen M4 entry path."""

    def __init__(self, token_counts: tuple[int, ...], seconds: tuple[float, ...]) -> None:
        self._token_counts = token_counts
        self._seconds = seconds

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        if token_count < self._token_counts[0] or token_count > self._token_counts[-1]:
            raise ValueError("H2 M4 token count is outside the measured M1 grid")
        index = bisect_right(self._token_counts, token_count)
        if index and self._token_counts[index - 1] == token_count:
            seconds = self._seconds[index - 1]
        else:
            lower = index - 1
            upper = index
            fraction = (token_count - self._token_counts[lower]) / (
                self._token_counts[upper] - self._token_counts[lower]
            )
            seconds = self._seconds[lower] + fraction * (
                self._seconds[upper] - self._seconds[lower]
            )
        return seconds, InputProvenance(
            InputSource.APPROXIMATED,
            "formal H2 M1 isolated native-prefill median curve",
        )


def _h2_m4_prefill_provider(
    options: Mapping[str, object],
) -> _H2M4MeasuredPrefillProvider | None:
    raw_path = options.get("h2_m4_prefill_curve_path")
    raw_sha = options.get("h2_m4_prefill_curve_sha256")
    if raw_path is None and raw_sha is None:
        return None
    if not isinstance(raw_path, str) or not raw_path or not isinstance(raw_sha, str):
        raise TypeError("H2 M4 prefill curve path and SHA-256 must be non-empty text")
    path = _resolve_repo_path(raw_path, "backend_options.h2_m4_prefill_curve_path")
    if hashlib.sha256(path.read_bytes()).hexdigest() != raw_sha:
        raise ValueError("H2 M4 prefill curve SHA-256 mismatch")
    outcome = json.loads(path.read_text(encoding="utf-8"))
    if (
        outcome.get("schema_version") != "phase2a.h2_formal_m1_outcome.v1"
        or outcome.get("primary_observation") != "isolated_native_prefill_elapsed_seconds"
        or outcome.get("candidate_outcome") != "PASS_PENDING_REVIEW"
    ):
        raise ValueError("H2 M4 requires the sealed formal M1 candidate outcome")
    points = outcome.get("point_summaries")
    if not isinstance(points, list) or len(points) != 17:
        raise ValueError("H2 M4 prefill curve must contain the frozen 17-point grid")
    tokens = tuple(point["prefix_tokens"] for point in points)
    seconds = tuple(float(point["isolated_native_prefill"]["median_seconds"]) for point in points)
    return _H2M4MeasuredPrefillProvider(tokens, seconds)


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


def _retention_mode_for_config(config: Mapping[str, object]) -> RetentionMode:
    """Select a real baseline while keeping every legacy caller controlled."""
    policy = config.get("policy")
    campaign_kind = config.get("campaign_kind")
    if policy == "native-lru":
        if campaign_kind != "phase2e_non_holdout_research_discovery":
            raise ValueError("native-lru baseline is restricted to Phase 2E discovery")
        return RetentionMode.NATIVE
    if campaign_kind == "phase2e_non_holdout_research_discovery" and policy != (
        "continuum-baseline"
    ):
        raise ValueError("Phase 2E policy must be native-lru or continuum-baseline")
    return RetentionMode.CONTROLLED


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _positive_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if result <= 0.0:
        raise ValueError(f"{field} must be positive")
    return result


def _unit_float(value: object, field: str) -> float:
    result = _positive_float(value, field)
    if result > 1.0:
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
            raise ValueError("profiling prefix size must be between 16 and 30720 tokens")
        if size % _BLOCK_SIZE != 0:
            raise ValueError("profiling prefix size must align to the KV block size")
        sizes[program_id] = size
    return sizes


def _phase2b_content_keys(options: Mapping[str, object]) -> dict[str, str] | None:
    enabled = options.get("phase2b_fidelity_mode", False)
    if not isinstance(enabled, bool):
        raise TypeError("backend_options.phase2b_fidelity_mode must be bool")
    raw = options.get("prefix_content_key_by_program")
    generator = options.get("prefix_generator_version")
    if not enabled:
        if raw is not None or generator is not None:
            raise ValueError("Phase 2B content fields require phase2b_fidelity_mode")
        return None
    if generator != PREFIX_GENERATOR_VERSION:
        raise ValueError(f"prefix_generator_version must be {PREFIX_GENERATOR_VERSION}")
    if "ownership_group_by_program" in options:
        raise ValueError("ownership_group_by_program cannot define content identity")
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("prefix_content_key_by_program must be a non-empty object")
    parsed: dict[str, str] = {}
    for program_id, content_key in raw.items():
        if not isinstance(program_id, str) or not program_id.strip():
            raise ValueError("content-key mapping requires non-empty program IDs")
        if not isinstance(content_key, str) or not content_key.strip():
            raise ValueError("content-key mapping requires non-empty content keys")
        parsed[program_id] = content_key
    return parsed


def _phase2c_request_segments(
    options: Mapping[str, object],
) -> dict[str, tuple[tuple[str, int], ...]] | None:
    enabled = options.get("phase2c_native_pilot_mode", False)
    if not isinstance(enabled, bool):
        raise TypeError("backend_options.phase2c_native_pilot_mode must be bool")
    raw = options.get("prefix_segments_by_request")
    generator = options.get("phase2c_prefix_generator_version")
    if not enabled:
        if raw is not None or generator is not None:
            raise ValueError("Phase 2C content fields require phase2c_native_pilot_mode")
        return None
    if options.get("phase2b_fidelity_mode", False) is not False:
        raise ValueError("Phase 2B and Phase 2C content modes are mutually exclusive")
    if generator != PILOT_PREFIX_GENERATOR_VERSION:
        raise ValueError(
            f"phase2c_prefix_generator_version must be {PILOT_PREFIX_GENERATOR_VERSION}"
        )
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("prefix_segments_by_request must be a non-empty object")
    parsed: dict[str, tuple[tuple[str, int], ...]] = {}
    for request_id, raw_segments in raw.items():
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("segment mapping requires non-empty request IDs")
        if not isinstance(raw_segments, list) or not raw_segments:
            raise ValueError("each request must define non-empty segments")
        segments: list[tuple[str, int]] = []
        for raw_segment in raw_segments:
            if (
                not isinstance(raw_segment, list)
                or len(raw_segment) != 2
                or not isinstance(raw_segment[0], str)
                or not raw_segment[0]
            ):
                raise TypeError("Phase 2C segment must be [content key, token count]")
            tokens = _positive_int(raw_segment[1], "Phase 2C segment token count")
            if tokens % _BLOCK_SIZE:
                raise ValueError("Phase 2C reusable segments must be block aligned")
            segments.append((raw_segment[0], tokens))
        parsed[request_id] = tuple(segments)
    return parsed


def _expected_profiling_block_override(
    program_prefix_tokens: Mapping[str, int],
    pressure_tokens: int,
    initial_shortage_blocks: int = 1,
    protected_prefix_blocks_override: int | None = None,
) -> int:
    if not program_prefix_tokens:
        raise ValueError("program_prefix_tokens must not be empty")
    if pressure_tokens % _BLOCK_SIZE != 0:
        raise ValueError("pressure token count must align to the KV block size")
    pressure_blocks = pressure_tokens // _BLOCK_SIZE
    if not 1 <= initial_shortage_blocks <= pressure_blocks:
        raise ValueError("initial pressure shortage must be within pressure demand")
    protected_blocks = (
        sum(size // _BLOCK_SIZE for size in program_prefix_tokens.values())
        if protected_prefix_blocks_override is None
        else _positive_int(
            protected_prefix_blocks_override,
            "protected_prefix_blocks_override",
        )
    )
    return protected_blocks + pressure_blocks + 1 - initial_shortage_blocks


def _pressure_stage_sizes(options: Mapping[str, object]) -> dict[str, int]:
    raw = options.get("pressure_stage_prompt_tokens")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError("backend_options.pressure_stage_prompt_tokens must be an object")
    sizes: dict[str, int] = {}
    for stage_id, value in raw.items():
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise ValueError("pressure_stage_prompt_tokens keys must be non-empty stage IDs")
        size = _positive_int(
            value,
            f"backend_options.pressure_stage_prompt_tokens[{stage_id!r}]",
        )
        if size % _BLOCK_SIZE != 0:
            raise ValueError("pressure-stage token count must align to the KV block size")
        sizes[stage_id] = size
    return sizes


def _h2_native_prefix_interventions(
    options: Mapping[str, object],
) -> dict[str, tuple[str, int]]:
    raw = options.get("h2_native_prefix_interventions", {})
    if not isinstance(raw, Mapping):
        raise TypeError("backend_options.h2_native_prefix_interventions must be an object")
    interventions: dict[str, tuple[str, int]] = {}
    for request_id, value in raw.items():
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("H2 intervention keys must be non-empty request IDs")
        if not isinstance(value, Mapping):
            raise TypeError(f"H2 intervention {request_id!r} must be an object")
        if set(value) != {"position", "count"}:
            raise ValueError(f"H2 intervention {request_id!r} must contain only position and count")
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


def _pressure_token_ids(
    request: PlannedRequest, *, vocabulary_size: int, token_count: int
) -> tuple[int, ...]:
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
        raise RuntimeError("native request hash chain and cache-key chain do not align")
    for position, (request_hash, cache_key) in enumerate(
        zip(request_hashes, cache_keys, strict=True)
    ):
        try:
            request_bytes = bytes.fromhex(request_hash)
        except ValueError as error:
            raise RuntimeError(f"native request hash {position} is not hexadecimal") from error
        if len(cache_key) < 5 or cache_key[:-4] != request_bytes:
            raise RuntimeError("native request hash does not match its group-qualified cache key")
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
        diagnostic_first_release_program_id: str | None = None,
        *,
        phase2g_release_policy: str = "A0",
        phase2g_a1_lambda: float = 0.5,
        phase2g_a1_tau_seconds: float = 30.0,
        phase2g_block_policy: str = "A0",
        phase2g_a2_tau_seconds: float = 30.0,
        phase2g_a2_registry: A2NativeSnapshotRegistry | None = None,
        sink: ExperimentEventSink | None = None,
    ) -> None:
        self._runtime = runtime
        self._clock = clock
        if phase2g_release_policy not in {"A0", "A1"}:
            raise ValueError("phase2g_release_policy must be A0 or A1")
        self._phase2g_release_policy = phase2g_release_policy
        self._sink = sink
        self._a1_coordinator = (
            A1NativeSelectionCoordinator(
                forced_release_observer,
                lambda_=phase2g_a1_lambda,
                tau_seconds=phase2g_a1_tau_seconds,
            )
            if phase2g_release_policy == "A1"
            else None
        )
        if phase2g_block_policy not in {"A0", "A2"}:
            raise ValueError("phase2g_block_policy must be A0 or A2")
        if phase2g_block_policy == "A2" and phase2g_a2_registry is None:
            raise ValueError("A2 block policy requires a native snapshot registry")
        self._a2_coordinator = (
            A2NativeSelectionCoordinator(
                phase2g_a2_registry,
                tau_seconds=phase2g_a2_tau_seconds,
                audit_sink=self._observe_a2_decision,
            )
            if phase2g_block_policy == "A2" and phase2g_a2_registry is not None
            else None
        )
        self._delegate = RetentionRuntimeIntegration(
            runtime.retention,
            forced_release_observer,
            diagnostic_first_release_program_id=(
                None
                if diagnostic_first_release_program_id is None
                else ProgramIdentity(diagnostic_first_release_program_id)
            ),
            selection_coordinator=self._a1_coordinator,
            block_selection_coordinator=self._a2_coordinator,
        )
        self.last_selected_block_ids: tuple[int, ...] = ()

    def _observe_a2_decision(self, audit: A2NativeDecisionAudit) -> None:
        if self._sink is None:
            return
        self._sink.emit(
            ExperimentEvent.create(
                event_type="COST_AWARE_BLOCK_DECISION",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2g.a2_native",
                payload={
                    "policy": "A2",
                    "required_blocks": audit.required_blocks,
                    "legal_block_ids": audit.legal_block_ids,
                    "native_lru_victims": audit.native_lru_victims,
                    "selected_victims": audit.selected_victims,
                    "selector": audit.selector,
                    "proxy_weighted_loss": audit.proxy_weighted_loss,
                    "cost_known": audit.cost_known,
                    "fallbacks": audit.fallbacks,
                    "contract_problems": audit.contract_problems,
                    "adapter_problems": audit.adapter_problems,
                    "search_truncated": audit.search_truncated,
                    "step_costs": audit.step_costs,
                    "chain_count": audit.chain_count,
                    "shared_block_count": audit.shared_block_count,
                    "identified_hashed_block_count": (
                        audit.identified_hashed_block_count
                    ),
                    "evidence_problem_counts": dict(audit.evidence_problem_counts),
                    "identity_state_counts": dict(audit.identity_state_counts),
                    "resident_chain_count": audit.resident_chain_count,
                    "broken_chain_count": audit.broken_chain_count,
                    "unknown_weight_chain_count": audit.unknown_weight_chain_count,
                    "chain_states": [
                        {
                            "chain_id": chain_id,
                            "original_length_blocks": original_length,
                            "resident_depths": resident_depths,
                            "reusable_prefix_blocks": reusable_prefix_blocks,
                            "reuse_weight_state": reuse_weight_state,
                        }
                        for (
                            chain_id,
                            original_length,
                            resident_depths,
                            reusable_prefix_blocks,
                            reuse_weight_state,
                        ) in audit.chain_states
                    ],
                    "effective_chain_lengths": dict(audit.effective_chain_lengths),
                    "decision_reuse_weights": dict(audit.decision_reuse_weights),
                    "block_memberships": [
                        {
                            "block_id": block_id,
                            "memberships": [
                                {
                                    "chain_id": chain_id,
                                    "depth": depth,
                                    "content_hash": content_hash,
                                }
                                for chain_id, depth, content_hash in memberships
                            ],
                        }
                        for block_id, memberships in audit.block_memberships
                    ],
                    "legal_content_hashes": [
                        {"block_id": block_id, "content_hash": content_hash}
                        for block_id, content_hash in audit.legal_content_hashes
                    ],
                    "native_hash_process_id": str(os.getpid()),
                    "claim_boundary": (
                        "proxy-weighted victim selection; not expected recomputed tokens"
                    ),
                },
            )
        )

    def apply_pressure(self, **kwargs: object) -> Any:
        result = self._delegate.apply_pressure(**kwargs)
        self.last_selected_block_ids = tuple(result.selected_block_ids)
        if self._a1_coordinator is not None and self._sink is not None:
            self._sink.emit(
                ExperimentEvent.create(
                    event_type="COST_AWARE_RELEASE_DECISION",
                    timestamp=self._clock.now(),
                    clock_domain="system_monotonic",
                    source="phase2g.a1_native",
                    payload={
                        "policy": "A1",
                        "strategy_id": self._a1_coordinator.strategy.strategy_id,
                        "lambda": self._a1_coordinator.strategy.lambda_,
                        "tau_seconds": self._a1_coordinator.strategy.tau_seconds,
                        "selection_trace": self._a1_coordinator.selection_trace(),
                        "selected_native_block_ids": self.last_selected_block_ids,
                    },
                )
            )
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
        self._retention_mode = _retention_mode_for_config(config)
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
        self._phase2b_content_keys = _phase2b_content_keys(options)
        self._phase2c_request_segments = _phase2c_request_segments(options)
        self._content_evidence_enabled = (
            self._phase2b_content_keys is not None or self._phase2c_request_segments is not None
        )
        if self._phase2b_content_keys is not None and (
            set(self._phase2b_content_keys) != set(self._program_prefix_tokens)
        ):
            raise ValueError(
                "Phase 2B content keys and program_prefix_tokens must cover the same programs"
            )
        self._pressure_tokens = _positive_int(
            options.get("pressure_prompt_tokens", _PRESSURE_TOKENS),
            "backend_options.pressure_prompt_tokens",
        )
        self._pressure_stage_tokens = _pressure_stage_sizes(options)
        timing = options.get("execute_planned_timing", False)
        if not isinstance(timing, bool):
            raise TypeError("backend_options.execute_planned_timing must be bool")
        self._execute_planned_timing = timing
        h2_m4_prefill_provider = _h2_m4_prefill_provider(options)
        if h2_m4_prefill_provider is not None and config.get("campaign_kind") != (
            "h2_formal_measurement"
        ):
            raise ValueError("H2 M4 measured prefill curve is restricted to formal H2")
        isolated_prefill_timing = options.get("isolated_native_prefill_timing", False)
        if not isinstance(isolated_prefill_timing, bool):
            raise TypeError("backend_options.isolated_native_prefill_timing must be bool")
        self._isolated_prefill_timing_enabled = isolated_prefill_timing
        self._isolated_prefill_timings: dict[str, float] = {}
        self._isolated_prefill_timing_hook: IsolatedPrefillTimingHook | None = None
        terminal_snapshot = options.get("capture_terminal_prefix_snapshot", True)
        if not isinstance(terminal_snapshot, bool):
            raise TypeError("backend_options.capture_terminal_prefix_snapshot must be bool")
        self._capture_terminal_prefix_snapshot = terminal_snapshot
        mechanism_only = options.get("h2_native_mechanism_only", False)
        if not isinstance(mechanism_only, bool):
            raise TypeError("backend_options.h2_native_mechanism_only must be bool")
        self._h2_native_mechanism_only = mechanism_only
        self._h2_interventions = _h2_native_prefix_interventions(options)
        self._applied_h2_interventions: set[str] = set()
        diagnostic_release = options.get("phase2d_diagnostic_first_release_program_id")
        if diagnostic_release is not None and (
            not isinstance(diagnostic_release, str) or not diagnostic_release.strip()
        ):
            raise ValueError("phase2d_diagnostic_first_release_program_id must be non-empty text")
        if diagnostic_release is not None and config.get("campaign_kind") != (
            "phase2d_non_holdout_research_pilot"
        ):
            raise ValueError("Phase 2D diagnostic release is restricted to its pilot")
        self._phase2d_diagnostic_release_program = diagnostic_release
        phase2g_release_policy = options.get("phase2g_release_policy", "A0")
        if phase2g_release_policy not in {"A0", "A1"}:
            raise ValueError("backend_options.phase2g_release_policy must be A0 or A1")
        if phase2g_release_policy == "A1" and config.get("campaign_kind") not in {
            "phase2g_a1_native_gate1",
            "phase2g_a1_bounded_evaluation",
        }:
            raise ValueError("A1 native release is restricted to authorized Phase 2G campaigns")
        phase2g_a1_lambda = float(options.get("phase2g_a1_lambda", 0.5))
        phase2g_a1_tau_seconds = float(options.get("phase2g_a1_tau_seconds", 30.0))
        phase2g_block_policy = options.get("phase2g_block_policy", "A0")
        if phase2g_block_policy not in {"A0", "A2"}:
            raise ValueError("backend_options.phase2g_block_policy must be A0 or A2")
        if phase2g_block_policy == "A2" and not _phase2g_a2_campaign_allowed(
            config.get("campaign_kind")
        ):
            raise ValueError("A2 native block selection is restricted to authorized campaigns")
        if phase2g_block_policy == "A2" and not self._content_evidence_enabled:
            raise ValueError("A2 native block selection requires content evidence mode")
        phase2g_a2_tau_seconds = _positive_float(
            options.get("phase2g_a2_tau_seconds", 30.0),
            "backend_options.phase2g_a2_tau_seconds",
        )
        self._phase2g_a2_registry = A2NativeSnapshotRegistry()
        phase2g_a2_identity_mode = options.get("phase2g_a2_identity_mode", "normal")
        if phase2g_a2_identity_mode not in {"normal", "missing", "stale"}:
            raise ValueError(
                "backend_options.phase2g_a2_identity_mode must be normal, missing, or stale"
            )
        if phase2g_a2_identity_mode != "normal" and phase2g_block_policy != "A2":
            raise ValueError("A2 identity controls require the A2 block policy")
        self._phase2g_a2_identity_mode = str(phase2g_a2_identity_mode)
        if self._h2_interventions and config.get("campaign_kind") not in {
            "h2_formal_measurement",
            "h2_intervention_validation",
            "phase2g_a2_native_evidence_fidelity",
        }:
            raise ValueError("native H2 interventions are restricted to H2 measurement campaigns")
        if self._h2_native_mechanism_only and config.get("campaign_kind") not in {
            "h2_formal_measurement",
            "h2_intervention_validation",
        }:
            raise ValueError("native H2 mechanism-only mode is restricted to H2 campaigns")
        block_override = _positive_int(
            config["cache"]["block_override"],  # type: ignore[index]
            "config.cache.block_override",
        )
        if self._program_prefix_tokens:
            initial_shortage_blocks = _positive_int(
                config["pressure"].get("initial_shortage_blocks", 1),  # type: ignore[index,union-attr]
                "config.pressure.initial_shortage_blocks",
            )
            protected_blocks_override = options.get("phase2g_unique_protected_blocks")
            if (
                protected_blocks_override is not None
                and not _phase2g_unique_protected_block_campaign_allowed(
                    config.get("campaign_kind")
                )
            ):
                raise ValueError(
                    "unique protected-block accounting is restricted to the "
                    "Phase 2G bounded campaign"
                )
            expected_override = _expected_profiling_block_override(
                self._program_prefix_tokens,
                self._pressure_tokens,
                initial_shortage_blocks,
                protected_prefix_blocks_override=(
                    int(protected_blocks_override)
                    if protected_blocks_override is not None
                    else None
                ),
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
                raise ValueError("qualified minimal test requires 256-prefix / 512-pressure tokens")

        continuum_config = ContinuumConfig(
            enabled=True,
            prefill_profile_path=str(profile_path),
            prefill_profile_version="v1",
        )
        self._runtime = (
            build_runtime(
                clock=self._clock,
                prefill_reload_provider=h2_m4_prefill_provider,
                default_ttl_seconds=30.0,
                experiment_event_sink=sink,
                history_observation_enabled=(self._content_evidence_enabled),
            )
            if h2_m4_prefill_provider is not None
            else build_runtime_from_config(
                config=continuum_config,
                clock=self._clock,
                experiment_event_sink=sink,
                history_observation_enabled=(self._content_evidence_enabled),
            )
        )
        self._forced_release_observer = _CountingForcedReleaseObserver(sink)
        self._retention_integration = _ObservedRetentionIntegration(
            self._runtime,
            self._clock,
            self._forced_release_observer,
            self._phase2d_diagnostic_release_program,
            phase2g_release_policy=str(phase2g_release_policy),
            phase2g_a1_lambda=phase2g_a1_lambda,
            phase2g_a1_tau_seconds=phase2g_a1_tau_seconds,
            phase2g_block_policy=str(phase2g_block_policy),
            phase2g_a2_tau_seconds=phase2g_a2_tau_seconds,
            phase2g_a2_registry=self._phase2g_a2_registry,
            sink=sink,
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
        gpu_memory_utilization = _unit_float(
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
        if self._phase2b_content_keys is not None:
            validate_distinct_content_keys(
                tuple(self._phase2b_content_keys.values()),
                vocabulary_size=self._vocabulary_size,
                block_size=_BLOCK_SIZE,
            )
        if self._phase2c_request_segments is not None:
            validate_distinct_content_keys(
                tuple(
                    f"{PILOT_PREFIX_GENERATOR_VERSION}:{key}"
                    for segments in self._phase2c_request_segments.values()
                    for key, _tokens in segments
                ),
                vocabulary_size=self._vocabulary_size,
                block_size=_BLOCK_SIZE,
            )

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
            mode=self._retention_mode,
            integration=self._retention_integration,
            clock=self._clock,
            hashed_eviction_observer=(
                self._observe_phase2b_native_hashed_eviction
                if self._content_evidence_enabled
                else None
            ),
        )

        self._started_programs: set[str] = set()
        self._pending_tool_gaps: dict[str, str] = {}
        self._phase2b_pending: dict[str, tuple[PlannedRequest, str, int]] = {}
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
                "status": ("AVAILABLE" if self._content_evidence_enabled else "UNAVAILABLE"),
                "reason": (
                    "Phase 2B read-only hook persists the pre-eviction native hash"
                    if self._content_evidence_enabled
                    else "legacy mode does not persist pre-eviction content identity"
                ),
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
                    "phase2b_fidelity_mode": self._phase2b_content_keys is not None,
                    "phase2c_native_pilot_mode": self._phase2c_request_segments is not None,
                    "prefix_generator_version": (
                        PREFIX_GENERATOR_VERSION
                        if self._phase2b_content_keys is not None
                        else (
                            PILOT_PREFIX_GENERATOR_VERSION
                            if self._phase2c_request_segments is not None
                            else None
                        )
                    ),
                    "pressure_prompt_tokens": self._pressure_tokens,
                    "pressure_stage_prompt_tokens": self._pressure_stage_tokens,
                    "execute_planned_timing": self._execute_planned_timing,
                    "h2_native_prefix_intervention_count": len(self._h2_interventions),
                    "h2_native_mechanism_only": self._h2_native_mechanism_only,
                    "h2_m4_prefill_curve_bound": h2_m4_prefill_provider is not None,
                    "gpu_memory_utilization": gpu_memory_utilization,
                    "retention_mode": self._retention_mode.value,
                    "phase2g_release_policy": phase2g_release_policy,
                    "phase2g_a1_lambda": (
                        phase2g_a1_lambda if phase2g_release_policy == "A1" else None
                    ),
                    "phase2g_a1_tau_seconds": (
                        phase2g_a1_tau_seconds if phase2g_release_policy == "A1" else None
                    ),
                    "phase2g_block_policy": phase2g_block_policy,
                    "phase2g_a2_tau_seconds": (
                        phase2g_a2_tau_seconds if phase2g_block_policy == "A2" else None
                    ),
                    "phase2g_a2_identity_mode": (
                        self._phase2g_a2_identity_mode
                        if phase2g_block_policy == "A2"
                        else None
                    ),
                },
            )
        )

    def _observe_phase2b_native_hashed_eviction(
        self,
        observation: NativeHashedEvictionObservation,
    ) -> None:
        """Persist native hash cleanup without inferring logical ownership."""
        self._phase2g_a2_registry.observe_eviction(
            observation.block_id,
            content_hash=observation.native_cache_key_before,
            native_hash_process_id=str(os.getpid()),
        )
        self._sink.emit(
            ExperimentEvent.create(
                event_type="VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2b.native_block_pool",
                payload={
                    "block_id": observation.block_id,
                    "native_cache_key_before": (observation.native_cache_key_before),
                    "native_hash_process_id": str(os.getpid()),
                    "ref_count_before": observation.ref_count_before,
                    "hash_removed_after": observation.hash_removed_after,
                    "mechanism": observation.mechanism,
                    "logical_owner_attribution": None,
                    "attribution_reason": ("native hash identity does not prove logical ownership"),
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
            "status": ("AVAILABLE" if self._level_b_first_token_complete else "UNAVAILABLE"),
            "reason": (
                "all completed requests exposed EngineCore first-token timestamps"
                if self._level_b_first_token_complete
                else "one or more requests lacked EngineCore first-token timestamps"
            ),
        }
        self.observation_capabilities["native_scheduler_admission_timestamp"] = {
            "status": ("AVAILABLE" if self._level_b_scheduler_timing_complete else "UNAVAILABLE"),
            "reason": (
                "all completed requests exposed EngineCore queued and first-scheduled timestamps"
                if self._level_b_scheduler_timing_complete
                else "one or more requests lacked EngineCore queued or first-scheduled timestamps"
            ),
        }
        self.observation_capabilities["isolated_native_prefill_elapsed_seconds"] = {
            "status": ("AVAILABLE" if self._isolated_prefill_timing_complete else "UNAVAILABLE"),
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
    def phase2b_supported_capabilities(self) -> tuple[str, ...]:
        """Capabilities implemented by the explicit non-holdout path."""
        if self._phase2b_content_keys is None:
            return ()
        return tuple(sorted(KNOWN_CAPABILITIES))

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
        payload: dict[str, object] = {
            "kind": request.kind,
            "token_count": len(token_ids),
            "reusable_prefix_token_count": reusable_prefix_tokens,
            "materialization": "deterministic_token_ids",
            "submitted_token_ids_sha256": token_ids_sha256(token_ids),
        }
        if self._phase2b_content_keys is not None and request.kind == "turn":
            payload.update(
                {
                    "prefix_content_key": self._phase2b_content_keys[request.program_id],
                    "prefix_generator_version": PREFIX_GENERATOR_VERSION,
                    "submitted_prefix_token_ids_sha256": token_ids_sha256(
                        token_ids[:reusable_prefix_tokens]
                    ),
                    "suffix_token_count": len(token_ids) - int(reusable_prefix_tokens or 0),
                }
            )
        if self._phase2c_request_segments is not None and request.kind == "turn":
            segments = self._phase2c_request_segments[request.request_id]
            payload.update(
                {
                    "prefix_segments": [list(segment) for segment in segments],
                    "prefix_segment_content_keys": [key for key, _tokens in segments],
                    "prefix_segment_token_counts": [tokens for _key, tokens in segments],
                    "prefix_generator_version": PILOT_PREFIX_GENERATOR_VERSION,
                    "submitted_prefix_token_ids_sha256": token_ids_sha256(
                        token_ids[:reusable_prefix_tokens]
                    ),
                    "suffix_token_count": len(token_ids) - int(reusable_prefix_tokens or 0),
                }
            )
        self._sink.emit(
            ExperimentEvent.create(
                event_type="BACKEND_INPUT_MATERIALIZED",
                timestamp=self._clock.now(),
                clock_domain="system_monotonic",
                source="phase2.minimal_metal",
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                payload=payload,
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
        return self._observe_completed_output(
            request,
            native_id,
            external_id,
            output,
        )

    def _observe_completed_output(
        self,
        request: PlannedRequest,
        native_id: str,
        external_id: str,
        output: object,
    ) -> float:
        """Persist one already-joined native completion and its raw metrics."""
        completions = tuple(getattr(output, "outputs", ()))
        output_token_count = sum(
            len(tuple(getattr(completion, "token_ids", ()))) for completion in completions
        )
        prompt_token_ids = getattr(output, "prompt_token_ids", None)
        native_prompt_tokens = (
            len(prompt_token_ids) if isinstance(prompt_token_ids, (list, tuple)) else None
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
            scheduler_timing_complete=(native_queued is not None and native_scheduled is not None),
            isolated_prefill_complete=(
                self._isolated_prefill_timing_enabled and isolated_native_prefill is not None
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
                    "native_cached_prefix_tokens": (native_cached_prefix_tokens),
                    "native_apc_block_hashes": (None if native_hashes is None else native_hashes),
                    "native_hash_block_size": _BLOCK_SIZE,
                    "native_hash_process_id": str(os.getpid()),
                    "native_hash_function": "sha256",
                    "native_queued_timestamp": native_queued,
                    "native_scheduler_admission_timestamp": (native_scheduled),
                    "native_first_token_timestamp": native_first_token,
                    "isolated_native_prefill_elapsed_seconds": (isolated_native_prefill),
                },
            )
        )
        if (
            self._content_evidence_enabled
            and native_queued is not None
            and native_scheduled is not None
            and request.kind == "turn"
        ):
            self._runtime.record_native_queue_observation(
                program_id=ProgramIdentity(request.program_id),
                request_id=RequestIdentity(request.request_id),
                queued_timestamp=native_queued,
                scheduled_timestamp=native_scheduled,
                clock_domain="engine_core_monotonic",
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
                    "ordered_native_cache_keys": tuple(native_hash.hex() for native_hash in hashes),
                    "hash_num_tokens": token_count,
                    "native_hash_block_size": _BLOCK_SIZE,
                    "native_hash_process_id": str(os.getpid()),
                    "native_hash_function": "sha256",
                },
            )
        )
        if self._phase2g_a2_identity_mode != "missing":
            self._phase2g_a2_registry.observe(
                A2NativeChainSnapshot(
                    chain_id=f"{request.program_id}:{prefix.canonical_value}",
                    block_ids=tuple(block_ids),
                    content_hashes=tuple(native_hash.hex() for native_hash in hashes),
                    native_hash_process_id=str(os.getpid()),
                )
            )
            if self._phase2g_a2_identity_mode == "stale":
                self._phase2g_a2_registry.observe_eviction(block_ids[0])
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
        selected_ids = tuple(int(value) for value in result["selected_block_ids"])
        selected_keys = tuple(
            str(result["native_cache_keys_before"][index])
            for index in result["selected_positions"]
        )
        for block_id, content_hash in zip(selected_ids, selected_keys, strict=True):
            self._phase2g_a2_registry.observe_eviction(
                block_id,
                content_hash=content_hash,
                native_hash_process_id=str(os.getpid()),
            )
            self._runtime.handle(BlockEvicted(BlockIdentity(block_id), self._clock.now()))
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
        if isinstance(event, RequestAdmitted):
            self._phase2g_a2_registry.observe_followup_admitted(event.program_id)
        elif isinstance(event, ProgramCompleted):
            self._phase2g_a2_registry.observe_program_completed(event.program_id)
        elif isinstance(event, TurnFinished):
            self._phase2g_a2_registry.observe_retention_entries(
                self._runtime.retention.planning_snapshots(),
                activate_admitted=True,
            )
        elif isinstance(event, FollowupWaiting):
            self._phase2g_a2_registry.observe_retention_entries(
                self._runtime.retention.planning_snapshots(),
            )

    def _start_turn(self, request: PlannedRequest) -> tuple[str, str, float, int]:
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
        if self._phase2c_request_segments is not None:
            segments = self._phase2c_request_segments.get(request.request_id)
            if segments is None:
                raise ValueError(f"missing Phase 2C segments for request {request.request_id}")
            prefix_tokens = sum(tokens for _key, tokens in segments)
            token_ids = segmented_turn_token_ids(
                request.request_id,
                segments,
                vocabulary_size=self._vocabulary_size,
            )
        elif self._phase2b_content_keys is not None:
            token_ids = phase2b_turn_token_ids(
                request,
                content_key=self._phase2b_content_keys[request.program_id],
                vocabulary_size=self._vocabulary_size,
                prefix_tokens=prefix_tokens,
            )
        else:
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
        return native_id, external_id, submitted_at, prefix_tokens

    def _finish_turn(
        self,
        request: PlannedRequest,
        native_id: str,
        finished_at: float,
        prefix_tokens: int,
    ) -> None:
        program = ProgramIdentity(request.program_id)
        logical_request = RequestIdentity(request.request_id)
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
        followup_id = RequestIdentity(f"{request.program_id}:turn:{request.turn_index + 1}")
        self._handle_lifecycle(FollowupWaiting(program, followup_id, finished_at))
        assert request.next_tool_type is not None
        self._handle_lifecycle(ToolGapStarted(program, request.next_tool_type, finished_at))
        self._pending_tool_gaps[request.program_id] = request.next_tool_type

    def _execute_turn(self, request: PlannedRequest) -> None:
        self._wait_for_planned_arrival(request)
        native_id, external_id, _submitted_at, prefix_tokens = self._start_turn(request)
        finished_at = self._complete(request, native_id, external_id)
        self._finish_turn(request, native_id, finished_at, prefix_tokens)

    def _start_pressure(self, request: PlannedRequest) -> tuple[str, str, float]:
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
        return self._enqueue(request, token_ids)

    def _finish_pressure(self, request: PlannedRequest, finished_at: float) -> None:
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

    def _execute_pressure(self, request: PlannedRequest) -> None:
        self._wait_for_planned_arrival(request)
        native_id, external_id, _submitted_at = self._start_pressure(request)
        finished_at = self._complete(request, native_id, external_id)
        self._finish_pressure(request, finished_at)

    def execute(self, request: PlannedRequest) -> None:
        if not isinstance(request, PlannedRequest):
            raise TypeError("request must be PlannedRequest")
        if request.kind == "pressure":
            self._execute_pressure(request)
        else:
            self._execute_turn(request)

    def submit(self, request: PlannedRequest) -> RequestHandle:
        """Enqueue one request without waiting; Phase 2B opt-in only."""
        if not self._content_evidence_enabled:
            raise RuntimeError("submit requires an opt-in fidelity or native-pilot mode")
        if self._execute_planned_timing:
            raise RuntimeError(
                "Phase 2B runner owns absolute timing; backend timing must be disabled"
            )
        if not isinstance(request, PlannedRequest):
            raise TypeError("request must be PlannedRequest")
        if request.kind == "pressure":
            native_id, external_id, submitted_at = self._start_pressure(request)
            prefix_tokens = 0
        else:
            native_id, external_id, submitted_at, prefix_tokens = self._start_turn(request)
        if external_id in self._phase2b_pending:
            raise RuntimeError("duplicate pending external request ID")
        self._phase2b_pending[external_id] = (
            request,
            native_id,
            prefix_tokens,
        )
        return RequestHandle(
            logical_request_id=request.request_id,
            native_request_id=native_id,
            external_request_id=external_id,
            submitted_at=submitted_at,
        )

    def collect_completed(self, *, until: float | None = None) -> tuple[RequestCompletion, ...]:
        """Report no completions without falsely claiming a native poll API.

        Pinned ``LLM.enqueue`` does not start processing, and the public API has
        no non-blocking poll.  Processing therefore happens only in ``drain``.
        """
        del until
        return ()

    def _wait_for_completion_bounded(self, timeout_seconds: float) -> tuple[object, ...]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("bounded Metal drain must run on the main thread")

        def timed_out(_signum: int, _frame: object) -> None:
            raise TimeoutError("native wait_for_completion exceeded timeout")

        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, timed_out)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        try:
            return tuple(self._llm.wait_for_completion(use_tqdm=False))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous)

    def drain(self, *, timeout_seconds: float) -> tuple[RequestCompletion, ...]:
        """Process every currently enqueued request and join outputs by ID."""
        if not self._phase2b_pending:
            return ()
        outputs = self._wait_for_completion_bounded(timeout_seconds)
        rows: list[RequestCompletion] = []
        for output in outputs:
            external_id = getattr(output, "request_id", None)
            if not isinstance(external_id, str):
                raise TypeError("native completion lacks external request ID")
            pending = self._phase2b_pending.pop(external_id, None)
            if pending is None:
                raise RuntimeError(f"native completion has no pending request: {external_id}")
            request, native_id, prefix_tokens = pending
            finished_at = self._observe_completed_output(
                request,
                native_id,
                external_id,
                output,
            )
            if request.kind == "pressure":
                self._finish_pressure(request, finished_at)
            else:
                self._finish_turn(
                    request,
                    native_id,
                    finished_at,
                    prefix_tokens,
                )
            rows.append(
                RequestCompletion(
                    logical_request_id=request.request_id,
                    native_request_id=native_id,
                    external_request_id=external_id,
                    completed_at=finished_at,
                )
            )
        if self._phase2b_pending:
            missing = ", ".join(sorted(self._phase2b_pending))
            raise RuntimeError(f"native drain omitted pending external request IDs: {missing}")
        return tuple(rows)

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
