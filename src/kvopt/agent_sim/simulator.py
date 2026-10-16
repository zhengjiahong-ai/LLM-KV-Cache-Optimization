"""Deterministic event-driven engine for the Phase 2F agent APC simulation.

The engine owns the physical block pool, drives the frozen Continuum retention
runtime (when the arm enables it), and applies one victim-selection policy per
arm. Requests execute instantaneously at their arrival time (serialized
execution, matching the Phase 2E ``max_concurrent_requests = 1`` regimes); the
timeline, cache state and every policy decision are deterministic functions of
the trace.

Eligible-prefix tokens (``E``) are precomputed from the trace alone (longest
common prefix against any earlier request), so the metric is identical across
arms and cannot be confounded by admission order.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from kvopt.continuum.clock import FakeClock
from kvopt.continuum.scheduler import ContinuumSchedulingPolicy
from kvopt.continuum.selection import EligibilityTier
from kvopt.continuum.types import BlockIdentity, RequestIdentity

from .content import prompt_block_content_ids
from .policies import DecisionContext, SimCandidate
from .pool import BlockPool
from .retention_bridge import RetentionBridge
from .trace import SimulationTrace, TraceRequest


@dataclass(slots=True)
class RequestRecord:
    """Per-request measurement (Phase 2E token semantics)."""

    request_id: str
    program_id: str
    turn_index: int
    arrival: float
    window: str
    prompt_tokens: int
    cacheable_blocks: int
    eligible_prefix_tokens: int
    hit_depth: int
    cached_prefix_tokens: int
    recomputed_tokens: int
    actual_prefill_tokens: int
    new_suffix_tokens: int
    protected_reuse_blocks: int
    evicted_block_ids: tuple[int, ...]


@dataclass(slots=True)
class DecisionRecord:
    """One victim-selection decision (auditable mechanism evidence)."""

    decision_index: int
    request_id: str
    timestamp: float
    required_blocks: int
    candidate_count: int
    eligible_count: int
    nontrivial: bool
    victim_block_ids: tuple[int, ...]
    victim_bands: tuple[int, ...]
    victim_depths: tuple[int, ...]
    forced_release_count: int
    forced_release_effects: tuple[tuple[str, str, tuple[int, ...]], ...]
    shared_owner_blocked_count: int


@dataclass(slots=True)
class EntryLifecycleRecord:
    """Retention entry creation, for the protected-capacity metrics."""

    key: tuple[str, str]
    created_at: float
    block_ids: tuple[int, ...]
    content_ids: tuple[str, ...]
    unprotected_at: float | None = None
    reused_blocks: int = 0
    survived_window_blocks: int = 0
    never_reused_blocks: int = 0


@dataclass(slots=True)
class ScenarioResult:
    """Everything one arm produced for one scenario draw."""

    arm_id: str
    trace_id: str
    family: str
    draw: int
    requests: list[RequestRecord] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    entries: list[EntryLifecycleRecord] = field(default_factory=list)
    hashed_eviction_count: int = 0
    hashless_reuse_count: int = 0
    live_cached_blocks: int = 0
    protected_block_token_seconds: float = 0.0
    policy_seconds: float = 0.0
    protected_reuse_blocks: int = 0
    protected_unused_blocks: int = 0
    protected_survived_blocks: int = 0
    protected_destroyed_blocks: int = 0
    natural_ttl_expiry_count: int = 0
    forced_release_count: int = 0
    zero_marginal_release_count: int = 0
    shared_owner_blocked_decisions: int = 0
    ttl_probe_records: tuple[object, ...] = ()
    error: str | None = None


def _lcp_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


class AgentSimulator:
    """Runs one arm over one trace and records auditable evidence."""

    def __init__(
        self,
        trace: SimulationTrace,
        policy,
        *,
        arm_id: str,
        retention: bool,
        scheduler: str = "native",
        future_index: dict[str, tuple[int, ...]] | None = None,
        forced_release_observer=None,
        shadow_policy=None,
        intervention: dict[int, tuple[int, ...]] | None = None,
    ) -> None:
        if scheduler not in {"native", "continuum"}:
            raise ValueError("scheduler must be 'native' or 'continuum'")
        self.trace = trace
        self.policy = policy
        self.arm_id = arm_id
        self.retention = retention
        self.scheduler = scheduler
        self.pool = BlockPool(trace.total_blocks, free_order=trace.free_order)
        self.clock = FakeClock()
        self.bridge = (
            RetentionBridge(
                clock=self.clock,
                extrapolate_prefill_profile=trace.extrapolate_prefill_profile,
                forced_release_observer=forced_release_observer,
            )
            if retention
            else None
        )
        self._scheduler_policy = (
            ContinuumSchedulingPolicy() if scheduler == "continuum" else None
        )
        self.future_index = future_index
        # Optional analysis hooks (never used by the campaign arms themselves):
        # ``shadow_policy`` records the first decision where a second policy
        # would choose a different victim set from identical state;
        # ``intervention`` forces one decision's victims (counterfactual branch).
        self._shadow_policy = shadow_policy
        self._intervention = intervention or {}
        self.first_divergence: dict[str, object] | None = None
        self._policy_seconds = 0.0
        self._trace_index = {
            request.request_id: index for index, request in enumerate(trace.requests)
        }
        # Arm-independent eligible prefix (blocks) per request, from the trace.
        self._eligible_blocks: dict[str, int] = {}
        seen: list[tuple[str, ...]] = []
        for request in trace.requests:
            content_ids = prompt_block_content_ids(
                request.segments, trace.block_size_tokens
            )
            best = 0
            for previous in seen:
                best = max(best, _lcp_length(content_ids, previous))
            self._eligible_blocks[request.request_id] = best
            seen.append(content_ids)
        self._block_acquire_time: dict[int, float] = {}
        self._entries: dict[tuple[str, str], EntryLifecycleRecord] = {}
        self._last_sample_time = 0.0
        self._free_event_counter = 0
        self.result = ScenarioResult(
            arm_id=arm_id, trace_id=trace.trace_id, family=trace.family, draw=trace.draw
        )

    # ------------------------------------------------------------------
    def run(self) -> ScenarioResult:
        try:
            self._run()
            self._finalize()
        except Exception as error:  # noqa: BLE001 -- surfaced, never dropped
            self.result.error = f"{type(error).__name__}: {error}"
        return self.result

    def _run(self) -> None:
        requests = list(self.trace.requests)
        index = 0
        while index < len(requests):
            arrival = requests[index].arrival_offset_seconds
            group: list[TraceRequest] = []
            while index < len(requests) and requests[index].arrival_offset_seconds == arrival:
                group.append(requests[index])
                index += 1
            self.clock.set(arrival)
            if self.bridge is not None:
                self.bridge.expire_due_and_count()
            for request in group:
                if self.bridge is not None:
                    self.bridge.request_arrived(
                        request.program_id, request.request_id, arrival
                    )
            for request in self._admission_order(group):
                self._process_request(request)
            self._sample_protection(arrival)

    def _admission_order(self, group: list[TraceRequest]) -> list[TraceRequest]:
        if self._scheduler_policy is None or len(group) == 1:
            return group
        assert self.bridge is not None
        request_ids = tuple(
            RequestIdentity(request.request_id) for request in group
        )
        candidates = self.bridge.runtime.scheduler_candidates(request_ids)
        ordered_ids = self._scheduler_policy.order(candidates)
        by_id = {request.request_id: request for request in group}
        return [by_id[identity.value] for identity in ordered_ids]

    # ------------------------------------------------------------------
    def _process_request(self, request: TraceRequest) -> None:
        arrival = request.arrival_offset_seconds
        self.clock.set(arrival)
        if self.bridge is not None:
            self.bridge.request_admitted(request.program_id, request.request_id, arrival)

        content_ids = prompt_block_content_ids(
            request.segments, self.trace.block_size_tokens
        )
        cacheable = len(content_ids)
        # Strict prefix-truncated hit depth: stop at the first missing block.
        hit_depth = 0
        while hit_depth < cacheable and content_ids[hit_depth] in self.pool.cache_mapping:
            hit_depth += 1

        matched_blocks = []
        protected_reuse = 0
        for position in range(hit_depth):
            block = self.pool.acquire(content_ids[position])
            if block is None:  # defensive: the mapping claimed a hit
                raise RuntimeError("cache mapping lost a matched block")
            if (
                self.bridge is not None
                and self.bridge.manager.is_block_protected(BlockIdentity(block.block_id))
            ):
                protected_reuse += 1
            matched_blocks.append(block)
            self._block_acquire_time[block.block_id] = arrival

        needed = (cacheable - hit_depth) + 1  # unmatched full blocks + hashless tail
        if needed > self.pool.free_blocks:
            raise RuntimeError(
                f"request {request.request_id} needs {needed} blocks but only "
                f"{self.pool.free_blocks} are free; workload exceeds capacity"
            )

        evicted_ids: list[int] = []
        if needed > 0:
            evicted_ids = self._select_and_evict(
                request, content_ids, hit_depth, needed, arrival
            )

        owned = matched_blocks + [self.pool.blocks[block_id] for block_id in evicted_ids]
        if len(owned) != cacheable + 1:
            raise RuntimeError("request block list is inconsistent")

        # Observation while the request is alive (baseline freeze §5).
        prefix_id = f"phase2f:{request.request_id}"
        if self.bridge is not None:
            self.bridge.blocks_observed(
                request.program_id,
                request.request_id,
                prefix_id,
                tuple(block.block_id for block in owned),
                arrival,
            )
            self.bridge.record_prefill_tokens(
                request.program_id, request.request_id, prefix_id, request.total_tokens
            )
            self.bridge.turn_finished(
                program_id=request.program_id,
                request_id=request.request_id,
                timestamp=arrival,
                is_terminal=request.is_terminal and request.outcome == "COMPLETED",
                next_tool_type=request.next_tool_type,
            )
            self._entries[(request.program_id, prefix_id)] = EntryLifecycleRecord(
                key=(request.program_id, prefix_id),
                created_at=arrival,
                block_ids=tuple(block.block_id for block in owned),
                content_ids=content_ids,
            )
            if request.is_terminal and request.outcome == "CANCELLED":
                self.bridge.followup_cancelled(
                    request.program_id, request.request_id, arrival
                )
            elif not request.is_terminal:
                self.bridge.followup_waiting(
                    request.program_id, request.request_id, arrival
                )
                self.bridge.tool_gap_started(
                    request.program_id, request.next_tool_type or "", arrival
                )
                # The tool-gap events carry their own timestamps; the monotonic
                # clock only advances at request arrivals (the next request's
                # arrival is the gap end for TTL/deadline purposes).
                self.bridge.tool_gap_ended(
                    request.program_id,
                    request.next_tool_type or "",
                    arrival + (request.tool_gap_seconds or 0.0),
                )
                self._sample_protection(arrival + (request.tool_gap_seconds or 0.0))

        # Release the request's blocks back to the free queue (one free event).
        self._free_event_counter += 1
        self.pool.release(tuple(owned), event_id=self._free_event_counter)

        eligible_tokens = (
            self._eligible_blocks[request.request_id] * self.trace.block_size_tokens
        )
        cached_tokens = hit_depth * self.trace.block_size_tokens
        self.result.requests.append(
            RequestRecord(
                request_id=request.request_id,
                program_id=request.program_id,
                turn_index=request.turn_index,
                arrival=arrival,
                window=request.window,
                prompt_tokens=request.total_tokens,
                cacheable_blocks=cacheable,
                eligible_prefix_tokens=eligible_tokens,
                hit_depth=hit_depth,
                cached_prefix_tokens=cached_tokens,
                recomputed_tokens=eligible_tokens - cached_tokens,
                actual_prefill_tokens=request.total_tokens - cached_tokens,
                new_suffix_tokens=request.total_tokens - eligible_tokens,
                protected_reuse_blocks=protected_reuse,
                evicted_block_ids=tuple(evicted_ids),
            )
        )
        self._track_entry_unprotection()

    # ------------------------------------------------------------------
    def _select_and_evict(
        self,
        request: TraceRequest,
        content_ids: tuple[str, ...],
        hit_depth: int,
        needed: int,
        timestamp: float,
    ) -> list[int]:
        candidates, context, eligible_count, shared_blocked, preparation = (
            self._build_decision(request, needed, timestamp)
        )
        decision_index = context.decision_index
        if decision_index in self._intervention:
            victims = self._intervention[decision_index]
            candidate_ids = {candidate.block_id for candidate in candidates}
            if set(victims) > candidate_ids or len(set(victims)) != len(victims):
                raise ValueError("intervention victims are not legal candidates")
            if len(victims) != min(needed, len(candidates)):
                raise ValueError("intervention victim count mismatch")
        else:
            decision_started = time.perf_counter()
            victims = self.policy.select(candidates, context)
            self._policy_seconds += time.perf_counter() - decision_started
            if self._shadow_policy is not None and self.first_divergence is None:
                shadow_victims = self._shadow_policy.select(candidates, context)
                if set(shadow_victims) != set(victims):
                    self.first_divergence = {
                        "decision_index": decision_index,
                        "request_id": request.request_id,
                        "baseline_victims": tuple(victims),
                        "challenger_victims": tuple(shadow_victims),
                    }

        by_id = {candidate.block_id: candidate for candidate in candidates}
        self.result.decisions.append(
            DecisionRecord(
                decision_index=decision_index,
                request_id=request.request_id,
                timestamp=timestamp,
                required_blocks=needed,
                candidate_count=len(candidates),
                eligible_count=eligible_count,
                nontrivial=eligible_count > needed,
                victim_block_ids=tuple(victims),
                victim_bands=tuple(by_id[block_id].band_id for block_id in victims),
                victim_depths=tuple(by_id[block_id].depth for block_id in victims),
                forced_release_count=(
                    0 if preparation is None else len(preparation.pressure_releases)
                ),
                forced_release_effects=(
                    ()
                    if preparation is None
                    else tuple(
                        (
                            effect.entry_key.program_id.value,
                            effect.entry_key.prefix_id.canonical_value,
                            tuple(
                                block.block_id for block in effect.newly_eligible_block_ids
                            ),
                        )
                        for effect in preparation.pressure_releases
                    )
                ),
                shared_owner_blocked_count=shared_blocked,
            )
        )

        # Execute: victims are assigned head-to-tail to the unmatched full
        # blocks first, then to the hashless tail block (vLLM pop-order
        # semantics); hash status follows the position, not the slot history.
        evicted: list[int] = []
        full_positions = list(range(hit_depth, len(content_ids)))
        for position, block_id in enumerate(victims):
            if position < len(full_positions):
                content = content_ids[full_positions[position]]
                depth = full_positions[position] + 1
                hashed = True
            else:
                content = ""
                depth = len(content_ids) + 1
                hashed = False
            if hashed and self.bridge is not None:
                # Mirrors the frozen hook: only real hashed evictions notify
                # the retention manager (``_maybe_evict_cached_block``).
                self.bridge.block_evicted(block_id, timestamp)
            self.pool.evict_and_take(block_id, content, depth, hashed=hashed)
            evicted.append(block_id)
        return evicted

    def _build_decision(
        self,
        request: TraceRequest,
        needed: int,
        timestamp: float,
    ) -> tuple[list[SimCandidate], DecisionContext, int, int, object]:
        """Snapshot the free queue, run retention eligibility, build context."""
        queue = self.pool.queue_blocks()
        preparation = None
        tiers: dict[int, EligibilityTier | None] = {}
        shared_blocked = 0
        if self.bridge is not None:
            # Decision-time shared-owner blocking, measured BEFORE any release:
            # a queued hashed block with >= 2 logical owners of which at least
            # one is still protected cannot be reclaimed yet.
            for block in queue:
                if not block.has_block_hash:
                    continue
                owners = self.bridge.manager.entries_for_block(BlockIdentity(block.block_id))
                if len(owners) < 2:
                    continue
                if any(
                    self.bridge.manager.snapshot(owner) is not None
                    and self.bridge.manager.snapshot(owner).protected
                    for owner in owners
                ):
                    shared_blocked += 1
            outcome = self.bridge.prepare_eligibility(
                [
                    SimCandidate(
                        block_id=block.block_id,
                        lru_rank=rank,
                        has_block_hash=block.has_block_hash,
                        tier=EligibilityTier.TIER_1,
                        depth=block.depth,
                        band_id=block.band_id,
                        band_hashless=block.band_hashless,
                        band_pos=block.band_pos,
                        content_id=block.content_id,
                    )
                    for rank, block in enumerate(queue)
                ],
                required_blocks=needed,
                timestamp=timestamp,
            )
            preparation = outcome.preparation
            self.bridge.commit_releases(outcome.release_keys)
            tiers = {
                snapshot.block_id.block_id: snapshot.eligibility_tier
                for snapshot in preparation.original_free_queue
            }

        candidates = [
            SimCandidate(
                block_id=block.block_id,
                lru_rank=rank,
                has_block_hash=block.has_block_hash,
                tier=tiers.get(block.block_id, EligibilityTier.TIER_1),
                depth=block.depth,
                band_id=block.band_id,
                band_hashless=block.band_hashless,
                band_pos=block.band_pos,
                content_id=block.content_id,
            )
            for rank, block in enumerate(queue)
        ]
        eligible_count = sum(1 for candidate in candidates if candidate.eligible)
        context = DecisionContext(
            required_blocks=needed,
            free_blocks=self.pool.free_blocks,
            total_blocks=self.pool.total_blocks,
            timestamp=timestamp,
            decision_index=len(self.result.decisions),
            request_id=request.request_id,
            preparation=preparation,
            future_index=self.future_index,
            current_request_index=self._trace_index[request.request_id],
        )
        return candidates, context, eligible_count, shared_blocked, preparation

    # ------------------------------------------------------------------
    def _sample_protection(self, timestamp: float) -> None:
        if self.bridge is None or timestamp <= self._last_sample_time:
            return
        protected = sum(
            1
            for block in self.pool.blocks
            if block.has_block_hash
            and self.bridge.manager.is_block_protected(BlockIdentity(block.block_id))
        )
        self.result.protected_block_token_seconds += (
            protected
            * self.trace.block_size_tokens
            * (timestamp - self._last_sample_time)
        )
        self._last_sample_time = timestamp

    def _track_entry_unprotection(self) -> None:
        """Detect entries that lost protection; measure reused vs unused."""
        if self.bridge is None:
            return
        snapshots = {
            (entry.program_id.value, entry.prefix_id.canonical_value): entry
            for entry in self.bridge.manager.planning_snapshots()
        }
        for key, record in self._entries.items():
            if record.unprotected_at is not None:
                continue
            entry = snapshots.get(key)
            if entry is None or not entry.protected:
                record.unprotected_at = self.clock.now()
                record.reused_blocks = sum(
                    1
                    for block_id in record.block_ids
                    if self._block_acquire_time.get(block_id, -1.0) > record.created_at
                )
                # Protection payoff: of the entry's content blocks, how many
                # are still cache-resident when the protection window ends
                # (i.e. were not destroyed by a forced release plus eviction)?
                record.survived_window_blocks = sum(
                    1
                    for content_id in record.content_ids
                    if content_id in self.pool.cache_mapping
                )

    def _finalize(self) -> None:
        result = self.result
        result.policy_seconds = self._policy_seconds
        result.hashed_eviction_count = self.pool.hashed_eviction_count
        result.hashless_reuse_count = self.pool.hashless_reuse_count
        result.live_cached_blocks = self.pool.cached_content_blocks()
        result.protected_reuse_blocks = sum(
            request.protected_reuse_blocks for request in result.requests
        )
        if self.bridge is not None:
            result.natural_ttl_expiry_count = self.bridge.natural_expiry_count
            result.forced_release_count = self.bridge.forced_release_count
            result.zero_marginal_release_count = self.bridge.zero_marginal_release_count
            result.ttl_probe_records = tuple(self.bridge.ttl_probe_records)
        result.shared_owner_blocked_decisions = sum(
            1 for decision in result.decisions if decision.shared_owner_blocked_count > 0
        )
        for record in self._entries.values():
            # Blocks never re-acquired after the entry was created are pure
            # protected-capacity waste (computed at end of run).
            record.never_reused_blocks = sum(
                1
                for block_id in record.block_ids
                if self._block_acquire_time.get(block_id, -1.0) <= record.created_at
            )
            result.protected_unused_blocks += record.never_reused_blocks
            result.protected_survived_blocks += record.survived_window_blocks
            result.protected_destroyed_blocks += len(record.block_ids) - (
                record.survived_window_blocks
            )
        result.entries.extend(self._entries.values())
