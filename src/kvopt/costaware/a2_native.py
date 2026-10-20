"""Native adapter for the frozen Phase 2G A2 block selector.

The adapter is intentionally narrow: Continuum has already fixed the legal block
set and the number of blocks that must be released.  This module only translates
that immutable decision-time snapshot into the reviewed A2 contract and returns a
victim order.  It never mutates a vLLM queue, block, hash table, or refcount.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from kvopt.continuum.selection import EligibilityPreparation
from kvopt.continuum.snapshots import RetentionEntrySnapshot
from kvopt.continuum.types import ProgramIdentity
from kvopt.runtime.vllm.adapter import EvictionPolicyAdapter, NativeLRUAdapter
from kvopt.runtime.vllm.types import EvictionCandidate, EvictionContext

from .a2_contract import BlockDecisionInput, DecisionOutcome, DecisionRequest, decide
from .a2_geometry import Membership, reuse_proxy
from .a2_selector import A2Config

DecisionRequestFactory = Callable[
    [Sequence[EvictionCandidate], EvictionContext], DecisionRequest
]
AuditSink = Callable[["A2NativeDecisionAudit"], None]


@dataclass(frozen=True, slots=True)
class A2NativeChainSnapshot:
    """Latest proved live content chain for one retention entry."""

    chain_id: str
    block_ids: tuple[int, ...]
    content_hashes: tuple[str, ...]
    native_hash_process_id: str

    def __post_init__(self) -> None:
        if not self.chain_id:
            raise ValueError("chain_id must be non-empty")
        if not self.native_hash_process_id:
            raise ValueError("native_hash_process_id must be non-empty")
        if not self.block_ids or len(self.block_ids) != len(self.content_hashes):
            raise ValueError("block_ids and content_hashes must be aligned and non-empty")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("block_ids must not contain duplicates")
        if any(not value for value in self.content_hashes):
            raise ValueError("content_hashes must be non-empty")


@dataclass(frozen=True, slots=True)
class A2NativeContentIdentity:
    """Current content proof for one physical slot in one hash process."""

    block_id: int
    content_hash: str
    native_hash_process_id: str


@dataclass(frozen=True, slots=True)
class A2NativeChainState:
    """Original chain geometry plus its current contiguous reusable boundary."""

    snapshot: A2NativeChainSnapshot
    resident_depths: tuple[int, ...]
    reusable_prefix_blocks: int


@dataclass(frozen=True, slots=True)
class A2NativeReuseState:
    """Lifecycle-qualified future reuse fact for one content chain."""

    deadline_timestamp: float | None
    lifecycle: str

    @property
    def has_future_demand(self) -> bool:
        return self.lifecycle == "TRACKED_FUTURE" and self.deadline_timestamp is not None

    @property
    def is_inactive(self) -> bool:
        return self.lifecycle in {"FOLLOWUP_ADMITTED", "PROGRAM_COMPLETED"}


@dataclass(frozen=True, slots=True)
class A2NativeEvidenceAudit:
    """Decision-time evidence reconstruction without changing selector semantics."""

    problem_counts: tuple[tuple[str, int], ...] = ()
    identity_state_counts: tuple[tuple[str, int], ...] = ()
    resident_chain_count: int = 0
    broken_chain_count: int = 0
    unknown_weight_chain_count: int = 0
    chain_states: tuple[tuple[str, int, tuple[int, ...], int, str], ...] = ()


class A2NativeSnapshotRegistry:
    """Read-only Native content and chain proofs used at decision time.

    Chain geometry is retained independently from current slot residency. Evicting
    one block removes only that slot's proof, while the original depths of the
    remaining blocks stay available. A later observation of reused slots replaces
    their content identity, so new content cannot inherit old membership.
    """

    def __init__(self) -> None:
        self._chains: dict[str, A2NativeChainSnapshot] = {}
        self._content_by_block: dict[int, A2NativeContentIdentity] = {}
        self._memberships_by_content: dict[
            tuple[str, str], set[tuple[str, int]]
        ] = {}
        self._reuse_by_chain: dict[str, A2NativeReuseState] = {}
        self.last_evidence_audit = A2NativeEvidenceAudit()

    def observe(self, snapshot: A2NativeChainSnapshot) -> None:
        if not isinstance(snapshot, A2NativeChainSnapshot):
            raise TypeError("snapshot must be A2NativeChainSnapshot")
        previous = self._chains.get(snapshot.chain_id)
        if previous is not None:
            self._remove_chain_memberships(previous)
        self._chains[snapshot.chain_id] = snapshot
        for depth, (block_id, content_hash) in enumerate(
            zip(snapshot.block_ids, snapshot.content_hashes, strict=True), start=1
        ):
            self._content_by_block[block_id] = A2NativeContentIdentity(
                block_id, content_hash, snapshot.native_hash_process_id
            )
            key = (snapshot.native_hash_process_id, content_hash)
            self._memberships_by_content.setdefault(key, set()).add(
                (snapshot.chain_id, depth)
            )

    def _remove_chain_memberships(self, snapshot: A2NativeChainSnapshot) -> None:
        for depth, content_hash in enumerate(snapshot.content_hashes, start=1):
            key = (snapshot.native_hash_process_id, content_hash)
            memberships = self._memberships_by_content.get(key)
            if memberships is None:
                continue
            memberships.discard((snapshot.chain_id, depth))
            if not memberships:
                del self._memberships_by_content[key]

    def observe_retention_entries(
        self,
        entries: Sequence[RetentionEntrySnapshot],
        *,
        activate_admitted: bool = False,
    ) -> None:
        """Refresh proved future-demand facts without changing content residency."""
        for entry in entries:
            chain = f"{entry.program_id.value}:{entry.prefix_id.canonical_value}"
            current = self._reuse_by_chain.get(chain)
            if (
                current is not None
                and current.lifecycle == "FOLLOWUP_ADMITTED"
                and not activate_admitted
            ):
                continue
            self._reuse_by_chain[chain] = A2NativeReuseState(
                deadline_timestamp=entry.deadline_timestamp,
                lifecycle="TRACKED_FUTURE",
            )

    def observe_followup_admitted(self, program_id: ProgramIdentity) -> None:
        """Consume the previously tracked future demand for one program."""
        for chain in tuple(self._chains):
            if chain.startswith(f"{program_id.value}:"):
                self._reuse_by_chain[chain] = A2NativeReuseState(
                    deadline_timestamp=None,
                    lifecycle="FOLLOWUP_ADMITTED",
                )

    def observe_program_completed(self, program_id: ProgramIdentity) -> None:
        """Retire demand, while retaining resident content and chain geometry."""
        for chain in tuple(self._chains):
            if chain.startswith(f"{program_id.value}:"):
                self._reuse_by_chain[chain] = A2NativeReuseState(
                    deadline_timestamp=None,
                    lifecycle="PROGRAM_COMPLETED",
                )

    def reuse_state(self, chain_id: str) -> A2NativeReuseState | None:
        return self._reuse_by_chain.get(chain_id)

    def content_memberships(
        self, identity: A2NativeContentIdentity
    ) -> tuple[tuple[str, int], ...]:
        """Return all proved chains for the current content identity."""
        return tuple(
            sorted(
                self._memberships_by_content.get(
                    (identity.native_hash_process_id, identity.content_hash), ()
                )
            )
        )

    def nonresident_block_ids(self, program_id: ProgramIdentity) -> tuple[int, ...]:
        """Return slots from proved chains whose original content is no longer live."""
        missing: set[int] = set()
        for chain, snapshot in self._chains.items():
            if not chain.startswith(f"{program_id.value}:"):
                continue
            for block_id, content_hash in zip(
                snapshot.block_ids, snapshot.content_hashes, strict=True
            ):
                expected = A2NativeContentIdentity(
                    block_id, content_hash, snapshot.native_hash_process_id
                )
                if self._content_by_block.get(block_id) != expected:
                    missing.add(block_id)
        return tuple(sorted(missing))

    def observe_eviction(
        self,
        block_id: int,
        *,
        content_hash: str | None = None,
        native_hash_process_id: str | None = None,
    ) -> None:
        """Invalidate only a matching slot identity, never the whole chain."""
        current = self._content_by_block.get(block_id)
        if current is None:
            return
        if content_hash is not None and current.content_hash != content_hash:
            return
        if (
            native_hash_process_id is not None
            and current.native_hash_process_id != native_hash_process_id
        ):
            return
        del self._content_by_block[block_id]

    def snapshot(self, chain_id: str) -> A2NativeChainSnapshot | None:
        return self._chains.get(chain_id)

    def content_identity(self, block_id: int) -> A2NativeContentIdentity | None:
        return self._content_by_block.get(block_id)

    def chain_state(self, chain_id: str) -> A2NativeChainState | None:
        snapshot = self.snapshot(chain_id)
        if snapshot is None:
            return None
        resident_depths = tuple(
            depth
            for depth, (block_id, content_hash) in enumerate(
                zip(snapshot.block_ids, snapshot.content_hashes, strict=True), start=1
            )
            if self._content_by_block.get(block_id)
            == A2NativeContentIdentity(
                block_id, content_hash, snapshot.native_hash_process_id
            )
        )
        boundary = 0
        for depth in resident_depths:
            if depth != boundary + 1:
                break
            boundary = depth
        return A2NativeChainState(snapshot, resident_depths, boundary)

    def build_request(
        self,
        candidates: Sequence[EvictionCandidate],
        context: EvictionContext,
        retention_entries: Sequence[RetentionEntrySnapshot],
        *,
        tau_seconds: float,
    ) -> DecisionRequest:
        """Build the frozen contract from live candidates and current entries."""
        chain_length: dict[str, int] = {}
        reuse_weight: dict[str, float] = {}
        memberships_by_block: dict[int, list[Membership]] = {
            candidate.block_id: [] for candidate in candidates
        }
        candidates_by_id = {candidate.block_id: candidate for candidate in candidates}
        unverified_legal_ids: set[int] = set()
        problems: Counter[str] = Counter()
        broken_chain_count = 0
        unknown_weight_chain_count = 0
        chain_states: list[tuple[str, int, tuple[int, ...], int, str]] = []

        entries_by_chain = {
            f"{entry.program_id.value}:{entry.prefix_id.canonical_value}": entry
            for entry in retention_entries
        }
        self.observe_retention_entries(retention_entries)
        relevant_chains = set(entries_by_chain)
        relevant_chains.update(
            chain_id
            for chain_id, snapshot in self._chains.items()
            if any(block_id in candidates_by_id for block_id in snapshot.block_ids)
        )

        for chain in sorted(relevant_chains):
            entry = entries_by_chain.get(chain)
            state = self.chain_state(chain)
            snapshot = None if state is None else state.snapshot
            entry_ids = (
                ()
                if entry is None
                else tuple(block.block_id for block in entry.block_ids)
            )
            resident_ids = (
                ()
                if state is None
                else tuple(
                    snapshot.block_ids[depth - 1] for depth in state.resident_depths
                )
            )
            if snapshot is None or (entry is not None and entry_ids != resident_ids):
                problems[
                    "chain_snapshot_missing"
                    if snapshot is None
                    else "retention_registry_residency_mismatch"
                ] += 1
                unverified_legal_ids.update(
                    block_id
                    for block_id in set(entry_ids).union(resident_ids)
                    if block_id in candidates_by_id
                    and candidates_by_id[block_id].has_block_hash
                )
                continue
            if state.reusable_prefix_blocks < len(snapshot.block_ids):
                broken_chain_count += 1
                problems["chain_prefix_broken"] += 1
            reuse_state = self.reuse_state(chain)
            inactive = reuse_state is not None and reuse_state.is_inactive
            if state.reusable_prefix_blocks > 0 and not inactive:
                chain_length[chain] = state.reusable_prefix_blocks
            if (
                reuse_state is not None
                and reuse_state.has_future_demand
                and state.reusable_prefix_blocks > 0
            ):
                reuse_weight[chain] = reuse_proxy(
                    float(reuse_state.deadline_timestamp),
                    context.timestamp,
                    tau_seconds,
                )
            elif (
                state.reusable_prefix_blocks > 0
                and not inactive
            ):
                unknown_weight_chain_count += 1
                problems["reuse_weight_unknown"] += 1
            chain_states.append(
                (
                    chain,
                    len(snapshot.block_ids),
                    state.resident_depths,
                    state.reusable_prefix_blocks,
                    (
                        "KNOWN"
                        if chain in reuse_weight
                        else "INACTIVE"
                        if inactive
                        else "UNKNOWN"
                    ),
                )
            )
            if inactive:
                continue
            for depth, (block_id, content_hash) in enumerate(
                zip(snapshot.block_ids, snapshot.content_hashes, strict=True),
                start=1,
            ):
                if depth > state.reusable_prefix_blocks:
                    continue
                candidate = candidates_by_id.get(block_id)
                identity = self.content_identity(block_id)
                if candidate is None:
                    continue
                if identity is None:
                    problems["native_content_not_resident"] += 1
                    if candidate.has_block_hash:
                        unverified_legal_ids.add(block_id)
                    continue
                if candidate.content_hash is None:
                    problems["candidate_content_hash_missing"] += 1
                    unverified_legal_ids.add(block_id)
                    continue
                if candidate.content_hash != content_hash:
                    problems["candidate_content_hash_mismatch"] += 1
                    unverified_legal_ids.add(block_id)
                    continue
                if (
                    identity.content_hash != content_hash
                    or identity.native_hash_process_id
                    != snapshot.native_hash_process_id
                ):
                    problems["native_content_identity_mismatch"] += 1
                    unverified_legal_ids.add(block_id)
                    continue
                memberships_by_block[block_id].append(
                    Membership(chain, depth, content_hash)
                )

        for candidate in candidates:
            if candidate.has_block_hash and not memberships_by_block[candidate.block_id]:
                unverified_legal_ids.add(candidate.block_id)
                problems["legal_hashed_candidate_without_membership"] += 1

        identity_states: Counter[str] = Counter()
        for candidate in candidates:
            memberships = memberships_by_block[candidate.block_id]
            if candidate.block_id in unverified_legal_ids:
                state_name = "CONTENT_UNVERIFIED"
            elif memberships and all(
                membership.chain in reuse_weight for membership in memberships
            ):
                state_name = "CONTENT_VERIFIED_CHAIN_WEIGHTED"
            elif memberships:
                state_name = "CONTENT_VERIFIED_WEIGHT_UNKNOWN"
            elif candidate.has_block_hash:
                state_name = "CONTENT_VERIFIED_CHAIN_UNUSABLE"
            else:
                state_name = "HASHLESS_NO_CONTENT"
            identity_states[state_name] += 1

        self.last_evidence_audit = A2NativeEvidenceAudit(
            problem_counts=tuple(sorted(problems.items())),
            identity_state_counts=tuple(sorted(identity_states.items())),
            resident_chain_count=sum(
                self.chain_state(chain_id).reusable_prefix_blocks > 0
                for chain_id in relevant_chains
                if self.chain_state(chain_id) is not None
            ),
            broken_chain_count=broken_chain_count,
            unknown_weight_chain_count=unknown_weight_chain_count,
            chain_states=tuple(chain_states),
        )

        blocks = tuple(
            BlockDecisionInput(
                block_id=candidate.block_id,
                native_rank=candidate.lru_rank,
                has_block_hash=candidate.has_block_hash,
                memberships=(
                    ()
                    if candidate.block_id in unverified_legal_ids
                    else tuple(memberships_by_block[candidate.block_id])
                ),
            )
            for candidate in candidates
        )
        return DecisionRequest(
            required_blocks=context.required_blocks,
            timestamp=context.timestamp,
            blocks=blocks,
            chain_length=chain_length,
            reuse_weight=reuse_weight,
        )


@dataclass(frozen=True, slots=True)
class A2NativeDecisionAudit:
    """One adapter decision, including fail-closed provenance."""

    required_blocks: int
    legal_block_ids: tuple[int, ...]
    native_lru_victims: tuple[int, ...]
    selected_victims: tuple[int, ...]
    selector: str
    proxy_weighted_loss: float | None
    cost_known: bool
    fallbacks: tuple[str, ...]
    contract_problems: tuple[str, ...]
    adapter_problems: tuple[str, ...] = ()
    search_truncated: bool = False
    step_costs: tuple[float, ...] = ()
    chain_count: int = 0
    shared_block_count: int = 0
    identified_hashed_block_count: int = 0
    legal_content_hashes: tuple[tuple[int, str | None], ...] = ()
    evidence_problem_counts: tuple[tuple[str, int], ...] = ()
    identity_state_counts: tuple[tuple[str, int], ...] = ()
    resident_chain_count: int = 0
    broken_chain_count: int = 0
    unknown_weight_chain_count: int = 0
    chain_states: tuple[tuple[str, int, tuple[int, ...], int, str], ...] = ()
    effective_chain_lengths: tuple[tuple[str, int], ...] = ()
    decision_reuse_weights: tuple[tuple[str, float], ...] = ()
    block_memberships: tuple[
        tuple[int, tuple[tuple[str, int, str], ...]], ...
    ] = ()

    @property
    def used_fallback(self) -> bool:
        return bool(self.fallbacks or self.contract_problems or self.adapter_problems)


class A2NativeBlockAdapter(EvictionPolicyAdapter):
    """Opt-in A2 policy over the exact candidate set supplied by vLLM.

    ``request_factory`` is the only runtime-specific seam.  It must construct the
    reviewed :class:`DecisionRequest` from live decision-time evidence.  The adapter
    checks that the factory did not change the legal set, LRU ranks, hash-presence
    flags, pressure target, or timestamp.  A mismatch falls back to Native LRU and is
    recorded; it never reaches cost scoring.
    """

    def __init__(
        self,
        request_factory: DecisionRequestFactory,
        *,
        config: A2Config | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        if not callable(request_factory):
            raise TypeError("request_factory must be callable")
        if audit_sink is not None and not callable(audit_sink):
            raise TypeError("audit_sink must be callable or None")
        self._request_factory = request_factory
        self._config = config or A2Config()
        self._audit_sink = audit_sink
        self.last_audit: A2NativeDecisionAudit | None = None

    def select_victims(
        self,
        candidates: Sequence[EvictionCandidate],
        context: EvictionContext,
    ) -> Sequence[int]:
        native = tuple(NativeLRUAdapter().select_victims(candidates, context))
        adapter_problems: list[str] = []
        outcome: DecisionOutcome | None = None
        request: DecisionRequest | None = None

        try:
            request = self._request_factory(candidates, context)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            adapter_problems.append(
                f"request_factory_failed:{type(error).__name__}:{error}"
            )
        else:
            adapter_problems.extend(self._adapter_contract_problems(request, candidates, context))
            if not adapter_problems:
                outcome = decide(request, config=self._config)

        if outcome is None:
            selected = native
            selector = "native_lru_fallback"
            proxy_weighted_loss = None
            cost_known = False
            fallbacks = ("adapter_contract_invalid",)
            contract_problems: tuple[str, ...] = ()
            search_truncated = False
            step_costs: tuple[float, ...] = ()
        else:
            selected = tuple(outcome.selection.blocks)
            selector = outcome.selection.selector
            proxy_weighted_loss = outcome.selection.proxy_weighted_loss
            cost_known = outcome.selection.cost_known
            fallbacks = outcome.selection.fallbacks
            contract_problems = outcome.problems
            search_truncated = outcome.selection.search_truncated
            step_costs = outcome.selection.step_costs

        audit = A2NativeDecisionAudit(
            required_blocks=context.required_blocks,
            legal_block_ids=tuple(candidate.block_id for candidate in candidates),
            native_lru_victims=native,
            selected_victims=selected,
            selector=selector,
            proxy_weighted_loss=proxy_weighted_loss,
            cost_known=cost_known,
            fallbacks=fallbacks,
            contract_problems=contract_problems,
            adapter_problems=tuple(adapter_problems),
            search_truncated=search_truncated,
            step_costs=step_costs,
            chain_count=(0 if request is None else len(request.chain_length)),
            shared_block_count=(
                0
                if request is None
                else sum(
                    len({membership.chain for membership in block.memberships}) > 1
                    for block in request.blocks
                )
            ),
            identified_hashed_block_count=(
                0
                if request is None
                else sum(
                    block.has_block_hash and bool(block.memberships)
                    for block in request.blocks
                )
            ),
            legal_content_hashes=tuple(
                (candidate.block_id, candidate.content_hash) for candidate in candidates
            ),
            effective_chain_lengths=(
                () if request is None else tuple(sorted(request.chain_length.items()))
            ),
            decision_reuse_weights=(
                () if request is None else tuple(sorted(request.reuse_weight.items()))
            ),
            block_memberships=(
                ()
                if request is None
                else tuple(
                    (
                        block.block_id,
                        tuple(
                            (
                                membership.chain,
                                membership.depth,
                                membership.content_hash,
                            )
                            for membership in block.memberships
                        ),
                    )
                    for block in request.blocks
                )
            ),
        )
        self.last_audit = audit
        if self._audit_sink is not None:
            self._audit_sink(audit)
        return list(selected)

    @staticmethod
    def _adapter_contract_problems(
        request: DecisionRequest,
        candidates: Sequence[EvictionCandidate],
        context: EvictionContext,
    ) -> tuple[str, ...]:
        problems: list[str] = []
        expected = tuple(
            (candidate.block_id, candidate.lru_rank, candidate.has_block_hash)
            for candidate in candidates
        )
        actual = tuple(
            (block.block_id, block.native_rank, block.has_block_hash)
            for block in request.blocks
        )
        if actual != expected:
            problems.append("request blocks do not match the live legal candidate snapshot")
        if request.required_blocks != context.required_blocks:
            problems.append("request required_blocks differs from the frozen pressure target")
        if request.timestamp != context.timestamp:
            problems.append("request timestamp differs from the live decision timestamp")
        return tuple(problems)


class A2NativeSelectionCoordinator:
    """Apply A2 after frozen Continuum entry release has fixed eligibility."""

    def __init__(
        self,
        registry: A2NativeSnapshotRegistry,
        *,
        tau_seconds: float,
        config: A2Config | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        if not isinstance(registry, A2NativeSnapshotRegistry):
            raise TypeError("registry must be A2NativeSnapshotRegistry")
        if tau_seconds <= 0:
            raise ValueError("tau_seconds must be positive")
        self._registry = registry
        self._tau_seconds = float(tau_seconds)
        self._config = config or A2Config()
        self._audit_sink = audit_sink

    def _observe_decision(self, audit: A2NativeDecisionAudit) -> None:
        if self._audit_sink is None:
            return
        evidence = self._registry.last_evidence_audit
        self._audit_sink(
            replace(
                audit,
                evidence_problem_counts=evidence.problem_counts,
                identity_state_counts=evidence.identity_state_counts,
                resident_chain_count=evidence.resident_chain_count,
                broken_chain_count=evidence.broken_chain_count,
                unknown_weight_chain_count=evidence.unknown_weight_chain_count,
                chain_states=evidence.chain_states,
            )
        )

    def select_victims(
        self,
        candidates: Sequence[EvictionCandidate],
        preparation: EligibilityPreparation,
        retention_entries: Sequence[RetentionEntrySnapshot],
        *,
        required_blocks: int,
        timestamp: float,
    ) -> tuple[int, ...]:
        eligible = {block.block_id for block in preparation.virtual_eligible_order}
        legal = tuple(
            candidate for candidate in candidates if candidate.block_id in eligible
        )
        context = EvictionContext(
            required_blocks=required_blocks,
            free_blocks=len(candidates),
            total_blocks=len(candidates),
            timestamp=timestamp,
        )

        def factory(
            live_candidates: Sequence[EvictionCandidate],
            live_context: EvictionContext,
        ) -> DecisionRequest:
            return self._registry.build_request(
                live_candidates,
                live_context,
                retention_entries,
                tau_seconds=self._tau_seconds,
            )

        adapter = A2NativeBlockAdapter(
            factory,
            config=self._config,
            audit_sink=self._observe_decision,
        )
        return tuple(adapter.select_victims(legal, context))

