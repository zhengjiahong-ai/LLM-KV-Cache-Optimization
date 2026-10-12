"""Opt-in contracts and fail-closed preflight for Phase 2B fidelity repair.

This module deliberately does not alter the Phase 2 v1 trace or synchronous
runner.  It validates the additional claims made by non-holdout fidelity
fixtures before a backend is allowed to execute them.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .phase2 import Phase2Trace, PlannedRequest

FIDELITY_CONTRACT_SCHEMA = "phase2b.fidelity_contract.v1"
FIDELITY_RUN_KIND = "NON_HOLDOUT_FIDELITY_REPAIR"
PREFIX_GENERATOR_VERSION = "phase2b-prefix-v1"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_DEMONSTRATED = "NOT_DEMONSTRATED"
STATUS_NOT_OBSERVABLE = "NOT_OBSERVABLE"
STATUS_BLOCKED = "BLOCKED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
FIDELITY_STATUSES = frozenset(
    {
        STATUS_PASS,
        STATUS_FAIL,
        STATUS_NOT_DEMONSTRATED,
        STATUS_NOT_OBSERVABLE,
        STATUS_BLOCKED,
        STATUS_NOT_APPLICABLE,
    }
)

CAPABILITY_PREFIX_CONTENT = "prefix_content_identity"
CAPABILITY_NATIVE_APC_HASHES = "native_apc_hashes"
CAPABILITY_TRUE_OVERLAP = "true_request_overlap"
CAPABILITY_NATIVE_QUEUE_TIMESTAMPS = "native_queue_timestamps"
CAPABILITY_TTL_HISTORY = "ttl_history_provenance"
CAPABILITY_NATIVE_HASHED_EVICTION = "native_hashed_eviction"
KNOWN_CAPABILITIES = frozenset(
    {
        CAPABILITY_PREFIX_CONTENT,
        CAPABILITY_NATIVE_APC_HASHES,
        CAPABILITY_TRUE_OVERLAP,
        CAPABILITY_NATIVE_QUEUE_TIMESTAMPS,
        CAPABILITY_TTL_HISTORY,
        CAPABILITY_NATIVE_HASHED_EVICTION,
    }
)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


@dataclass(frozen=True, slots=True)
class FidelityConstraints:
    max_in_flight: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class FidelityContract:
    case_id: str
    required_capabilities: tuple[str, ...]
    constraints: FidelityConstraints
    schema_version: str = FIDELITY_CONTRACT_SCHEMA
    run_kind: str = FIDELITY_RUN_KIND

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FidelityGateResult:
    gate: str
    requested: object
    observed: object
    status: str
    source_event_indices: tuple[int, ...]
    scope: str
    runtime_identity: Mapping[str, object]
    reason: str
    clock_domain: str | None = None

    def __post_init__(self) -> None:
        if self.status not in FIDELITY_STATUSES:
            raise ValueError(f"unsupported fidelity status: {self.status}")
        _text(self.gate, "gate")
        _text(self.scope, "scope")
        _text(self.reason, "reason")
        if any(
            isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in self.source_event_indices
        ):
            raise ValueError("source_event_indices must be non-negative integers")
        if any(not isinstance(key, str) for key in self.runtime_identity):
            raise TypeError("runtime_identity must have string keys")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HistoryObservation:
    eta: float
    eta_provenance_source: str
    eta_provenance_reason: str | None
    eta_history_sample_count: int
    queue_delay_history_sample_count: int
    queue_delay_t_seconds: float
    native_queue_duration_seconds: float | None
    sampled_candidate_targets_present: bool = False


def build_history_gate(
    observation: HistoryObservation,
    *,
    require_observed_eta: bool,
    require_eligible_queue_history: bool,
    source_event_indices: Sequence[int],
    runtime_identity: Mapping[str, object],
) -> FidelityGateResult:
    """Evaluate frozen history provenance without manufacturing variation."""
    status = STATUS_PASS
    reason = "runtime values follow the frozen eligible history sources"
    if (
        observation.sampled_candidate_targets_present
        and observation.eta_history_sample_count == 0
        and observation.queue_delay_history_sample_count == 0
    ):
        status = STATUS_NOT_DEMONSTRATED
        reason = (
            "scenario targets exist but no eligible runtime history supports "
            "native signal variation"
        )
    elif require_observed_eta and observation.eta_provenance_source != "OBSERVED":
        status = STATUS_NOT_DEMONSTRATED
        reason = "eta remained a cold-start approximation rather than observed history"
    elif (
        require_eligible_queue_history
        and observation.queue_delay_history_sample_count == 0
    ):
        status = STATUS_NOT_OBSERVABLE
        reason = (
            "native queue timing does not qualify as an "
            "EvictedRequestQueueDelayRecord"
        )
    return FidelityGateResult(
        gate="G-HISTORY",
        requested={
            "observed_eta": require_observed_eta,
            "eligible_queue_history": require_eligible_queue_history,
        },
        observed=asdict(observation),
        status=status,
        source_event_indices=tuple(source_event_indices),
        scope="frozen_continuum_history_inputs",
        runtime_identity=runtime_identity,
        reason=reason,
        clock_domain=None,
    )


class FidelityPreflightError(ValueError):
    """The fixture cannot legally make its requested runtime claims."""


def prefix_content_token_ids(
    content_key: str,
    *,
    vocabulary_size: int,
    token_count: int,
) -> tuple[int, ...]:
    """Materialize a length-stable content prefix independent of program ID."""
    key = _text(content_key, "content_key")
    _positive_int(token_count, "token_count")
    if vocabulary_size <= 40_000:
        raise ValueError("vocabulary_size must exceed 40000")
    return tuple(
        1_000
        + int.from_bytes(
            hashlib.sha256(
                f"{PREFIX_GENERATOR_VERSION}:{key}:{index}".encode()
            ).digest()[:4],
            "big",
        )
        % 20_000
        for index in range(token_count)
    )


def phase2b_turn_token_ids(
    request: PlannedRequest,
    *,
    content_key: str,
    vocabulary_size: int,
    prefix_tokens: int,
) -> tuple[int, ...]:
    """Add a request-specific suffix without perturbing shared content."""
    prefix = prefix_content_token_ids(
        content_key,
        vocabulary_size=vocabulary_size,
        token_count=prefix_tokens,
    )
    suffix_digest = hashlib.sha256(
        f"phase2b-suffix-v1:{request.request_id}".encode()
    ).digest()
    suffix = 30_000 + int.from_bytes(suffix_digest[:4], "big") % 5_000
    return (*prefix, suffix % vocabulary_size)


def token_ids_sha256(token_ids: Sequence[int]) -> str:
    """Stable digest of the exact integer token sequence submitted natively."""
    digest = hashlib.sha256()
    for token_id in token_ids:
        if isinstance(token_id, bool) or not isinstance(token_id, int) or token_id < 0:
            raise ValueError("token IDs must be non-negative integers")
        digest.update(token_id.to_bytes(8, "big"))
    return digest.hexdigest()


def validate_distinct_content_keys(
    content_keys: Sequence[str],
    *,
    vocabulary_size: int,
    block_size: int,
) -> None:
    """Fail closed if distinct keys collide in their first materialized block."""
    _positive_int(block_size, "block_size")
    first_blocks: dict[tuple[int, ...], str] = {}
    for key in sorted(set(content_keys)):
        block = prefix_content_token_ids(
            key,
            vocabulary_size=vocabulary_size,
            token_count=block_size,
        )
        previous = first_blocks.setdefault(block, key)
        if previous != key:
            raise RuntimeError(
                f"content keys {previous!r} and {key!r} collide in the first block"
            )


def load_fidelity_contract(path: str | Path) -> FidelityContract:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("fidelity contract must be an object")
    if raw.get("schema_version") != FIDELITY_CONTRACT_SCHEMA:
        raise ValueError("unsupported fidelity contract schema_version")
    if raw.get("run_kind") != FIDELITY_RUN_KIND:
        raise ValueError("fidelity contract run_kind must be non-holdout repair")
    case_id = _text(raw.get("case_id"), "case_id")
    capabilities = raw.get("required_capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("required_capabilities must be a non-empty list")
    if not all(isinstance(value, str) and value for value in capabilities):
        raise TypeError("required_capabilities entries must be non-empty text")
    if len(capabilities) != len(set(capabilities)):
        raise ValueError("required_capabilities must not contain duplicates")
    unknown = sorted(set(capabilities) - KNOWN_CAPABILITIES)
    if unknown:
        raise ValueError(f"unknown required capabilities: {', '.join(unknown)}")
    constraints = raw.get("constraints")
    if not isinstance(constraints, dict):
        raise TypeError("constraints must be an object")
    return FidelityContract(
        case_id=case_id,
        required_capabilities=tuple(capabilities),
        constraints=FidelityConstraints(
            max_in_flight=_positive_int(
                constraints.get("max_in_flight"), "constraints.max_in_flight"
            ),
            timeout_seconds=_positive_number(
                constraints.get("timeout_seconds"), "constraints.timeout_seconds"
            ),
        ),
    )


def validate_phase2b_preflight(
    *,
    contract: FidelityContract,
    config: Mapping[str, object],
    trace: Phase2Trace,
    supported_capabilities: Sequence[str],
    platform_ready: bool,
) -> None:
    """Reject fixtures that would silently degrade a required fidelity claim."""
    if not platform_ready:
        raise FidelityPreflightError("qualified vLLM/Metal platform is not ready")
    unsupported = sorted(
        set(contract.required_capabilities) - set(supported_capabilities)
    )
    if unsupported:
        raise FidelityPreflightError(
            "backend does not support required capabilities: "
            + ", ".join(unsupported)
        )
    options = config.get("backend_options")
    if not isinstance(options, Mapping):
        raise FidelityPreflightError("config.backend_options must be an object")
    if options.get("phase2b_fidelity_mode") is not True:
        raise FidelityPreflightError("phase2b_fidelity_mode must be explicitly enabled")
    if options.get("prefix_generator_version") != PREFIX_GENERATOR_VERSION:
        raise FidelityPreflightError(
            f"prefix_generator_version must be {PREFIX_GENERATOR_VERSION}"
        )
    if "ownership_group_by_program" in options:
        raise FidelityPreflightError(
            "ownership_group_by_program is not an authoritative content mapping"
        )
    mapping = options.get("prefix_content_key_by_program")
    if not isinstance(mapping, Mapping):
        raise FidelityPreflightError(
            "prefix_content_key_by_program must be an object"
        )
    programs = {
        request.program_id for request in trace.requests if request.kind == "turn"
    }
    missing = sorted(programs - set(mapping))
    extra = sorted(set(mapping) - programs)
    if missing or extra:
        raise FidelityPreflightError(
            f"content-key mapping mismatch; missing={missing}, extra={extra}"
        )
    if any(not isinstance(mapping[program], str) or not mapping[program].strip() for program in programs):
        raise FidelityPreflightError("content keys must be non-empty text")
    prefix_sizes = options.get("program_prefix_tokens")
    if not isinstance(prefix_sizes, Mapping):
        raise FidelityPreflightError("program_prefix_tokens must be an object")
    if set(prefix_sizes) != programs:
        raise FidelityPreflightError("program_prefix_tokens must cover exactly the turn programs")
    cache = config.get("cache")
    if not isinstance(cache, Mapping):
        raise FidelityPreflightError("config.cache must be an object")
    block_size = cache.get("block_size")
    if isinstance(block_size, bool) or not isinstance(block_size, int) or block_size < 1:
        raise FidelityPreflightError("cache.block_size must be a positive integer")
    for program in sorted(programs):
        size = prefix_sizes[program]
        if isinstance(size, bool) or not isinstance(size, int) or size < block_size:
            raise FidelityPreflightError(
                f"prefix size for {program} must contain at least one full block"
            )
        if size % block_size:
            raise FidelityPreflightError(
                f"prefix size for {program} must align to block_size"
            )

    batching = config.get("batching")
    if not isinstance(batching, Mapping):
        raise FidelityPreflightError("config.batching must be an object")
    configured_cap = batching.get("max_concurrent_requests")
    if configured_cap != contract.constraints.max_in_flight:
        raise FidelityPreflightError(
            "batching.max_concurrent_requests must equal the frozen contract cap"
        )
    if CAPABILITY_TRUE_OVERLAP in contract.required_capabilities:
        if contract.constraints.max_in_flight < 2:
            raise FidelityPreflightError("true overlap requires max_in_flight >= 2")
        if options.get("executor_mode") != "submit_collect":
            raise FidelityPreflightError(
                "true overlap requires the opt-in submit_collect executor"
            )

    if CAPABILITY_NATIVE_HASHED_EVICTION in contract.required_capabilities:
        if not trace.pressure_stages:
            raise FidelityPreflightError("native eviction fixture requires pressure")
        first_pressure = min(
            stage.planned_arrival_offset_seconds for stage in trace.pressure_stages
        )
        if not any(
            request.kind == "turn"
            and request.planned_arrival_offset_seconds <= first_pressure
            for request in trace.requests
        ):
            raise FidelityPreflightError(
                "pressure fixture requires a target warmup before pressure"
            )
