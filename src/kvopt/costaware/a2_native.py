"""Native adapter for the frozen Phase 2G A2 block selector.

The adapter is intentionally narrow: Continuum has already fixed the legal block
set and the number of blocks that must be released.  This module only translates
that immutable decision-time snapshot into the reviewed A2 contract and returns a
victim order.  It never mutates a vLLM queue, block, hash table, or refcount.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kvopt.continuum.selection import EligibilityPreparation
from kvopt.continuum.snapshots import RetentionEntrySnapshot
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


class A2NativeSnapshotRegistry:
    """Ephemeral read-only identity proofs used only at the current decision.

    An eviction invalidates every snapshot containing that physical slot.  A later
    snapshot replaces the earlier chain proof.  Thus slot reuse can never inherit an
    old chain identity.
    """

    def __init__(self) -> None:
        self._chains: dict[str, A2NativeChainSnapshot] = {}

    def observe(self, snapshot: A2NativeChainSnapshot) -> None:
        if not isinstance(snapshot, A2NativeChainSnapshot):
            raise TypeError("snapshot must be A2NativeChainSnapshot")
        self._chains[snapshot.chain_id] = snapshot

    def observe_eviction(self, block_id: int) -> None:
        invalid = [
            chain
            for chain, snapshot in self._chains.items()
            if block_id in snapshot.block_ids
        ]
        for chain in invalid:
            del self._chains[chain]

    def snapshot(self, chain_id: str) -> A2NativeChainSnapshot | None:
        return self._chains.get(chain_id)

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

        for entry in retention_entries:
            chain = f"{entry.program_id.value}:{entry.prefix_id.canonical_value}"
            snapshot = self.snapshot(chain)
            expected_ids = tuple(block.block_id for block in entry.block_ids)
            if snapshot is None or snapshot.block_ids != expected_ids:
                unverified_legal_ids.update(
                    block_id
                    for block_id in expected_ids
                    if block_id in candidates_by_id
                    and candidates_by_id[block_id].has_block_hash
                )
                continue
            chain_length[chain] = len(snapshot.block_ids)
            reuse_weight[chain] = reuse_proxy(
                entry.deadline_timestamp,
                context.timestamp,
                tau_seconds,
            )
            for depth, (block_id, content_hash) in enumerate(
                zip(snapshot.block_ids, snapshot.content_hashes, strict=True),
                start=1,
            ):
                candidate = candidates_by_id.get(block_id)
                if candidate is None or candidate.content_hash != content_hash:
                    if candidate is not None and candidate.has_block_hash:
                        unverified_legal_ids.add(block_id)
                    continue
                memberships_by_block[block_id].append(
                    Membership(chain, depth, content_hash)
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
            audit_sink=self._audit_sink,
        )
        return tuple(adapter.select_victims(legal, context))

