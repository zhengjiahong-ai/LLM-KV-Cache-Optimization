"""Phase 2I: entry-level prefix-suffix-aware marginal cost-aware release.

This implements the algorithm frozen by ``docs/experiments/phase2i-entry-marginal-cost-design.md``
(design authority: M1 ``APPROVED_FOR_BOUNDED_IMPLEMENTATION`` on PR #87):

    L(X) = q_X * prefill_X * S_X / m_X
    S_X  = m_X - d_min(X) + 1

with

``q_X``      the frozen A1 deadline-based reuse proxy ``sigmoid((deadline - t)/tau)``,
             reused verbatim from :mod:`kvopt.costaware.a1_entry` -- tau and the
             definition of ``q`` are not touched here;
``prefill_X`` the prefill reload cost already available at decision time;
``m_X``      the **full** original prefix chain length from a ``ChainDepthProof``;
``V_X``      the blocks that would become evictable after releasing ``X``, taken
             from the frozen eligibility rule and ordered by native LRU rank;
``d_min(X)`` the shallowest **original** prefix depth among ``V_X``.

It is a **cost proxy**: ``q`` is not a calibrated reuse probability and ``L`` is
not an exact expected recompute time. The full formula is implemented as frozen;
the ``q * S`` reading is an analysis aid only and must not replace it.

Scope: exactly one branch of the frozen ladder
----------------------------------------------
``A1EntryCostAwareStrategy`` is composed, not rewritten. Its ``select()`` runs
first and supplies the branch, the per-candidate scores and, for every branch
other than Step 2, the choice itself:

===============  ==================================================  =============
step             condition                                           this module
===============  ==================================================  =============
Step 1           ``need <= 0``                                       frozen A1
Step 2           some candidate has ``N_i >= need``                  ``(L, deadline, identity)``
Step 3           per-unit relief is scarce                           frozen A1
Step 4           two-entry joint unlock                              frozen A1
Step 5           deadline fallback                                   frozen A1
===============  ==================================================  =============

``need``, ``N_i``, candidate legality, tie-break and native eligibility keep
their frozen meaning. ``deficit`` is the frozen residual need, i.e. the number of
blocks that must still become eligible, which is the same quantity the design
document writes as ``max(0, need - |Tier 1|)`` because ``need`` is already
measured against the currently eligible set.

Fail closed, and say why
------------------------
If **any** Step-2 candidate cannot be scored -- no observation, unusable depth,
missing prefill, short victim set -- the whole Step 2 decision falls back to the
frozen A1 ordering and every audit row records a reason code. Partial scoring is
never accepted: an under-counted victim set produces a smaller ``S``, which makes
an entry whose geometry is unknown look cheap.

Predicted victims are not physical evictions
-------------------------------------------
``V_X`` is a **prediction** derived from the frozen eligibility rule. It is not
the native ``SelectionPlan``, not a confirmed physical eviction, not content
ownership and not a downstream recompute. Those five things stay separate in the
audit record and must not be substituted for one another.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum

from kvopt.profiling.datasets import DecisionCandidateRow

from .a1_entry import (
    BRANCH_DEADLINE_FALLBACK,
    BRANCH_PAIR_LOOKAHEAD,
    BRANCH_PER_UNIT,
    BRANCH_SINGLE_STEP,
    A1EntryCostAwareStrategy,
    default_tau_seconds,
)
from .entry_depth import (
    CHAIN_PROCESS_UNSET,
    CLOCK_DOMAIN_UNKNOWN,
    ChainDepthIndex,
    DepthQuery,
)
from .replay import (
    CandidateKey,
    DecisionSnapshot,
    ReplayOutcome,
    ReplayState,
    candidate_key,
)

#: Strategy id for explicit enablement. Nothing else in the codebase may select
#: this behaviour by accident: it must be requested by this id.
STRATEGY_ID = "A3_entry_suffix_cost_proxy"

#: Ladder steps, recorded so a reader can see which branch produced a choice.
STEP_NO_NEED = "step1_no_need"
STEP_SUFFICIENT = "step2_sufficient"
STEP_PER_UNIT = "step3_per_unit"
STEP_PAIR_LOOKAHEAD = "step4_pair_lookahead"
STEP_FALLBACK = "step5_deadline_fallback"

#: Reason codes for a candidate that cannot be scored. An empty string means the
#: candidate was scored normally.
FAIL_NONE = ""
FAIL_NO_OBSERVATION = "NO_OBSERVATION"
FAIL_DEPTH_UNAVAILABLE = "DEPTH_UNAVAILABLE"
FAIL_PREFILL_MISSING = "PREFILL_MISSING"
FAIL_VICTIM_SHORTFALL = "VICTIM_SHORTFALL"
FAIL_INVALID_GEOMETRY = "INVALID_GEOMETRY"

#: Selection-level fallback reason: emitted only when Step 2 handed the decision
#: back to frozen A1.
FALLBACK_STEP2_UNSCORABLE = "STEP2_UNSCORABLE"


class VictimEvidence(str, Enum):
    """How strong the evidence behind a victim set is.

    Only :attr:`PREDICTED` is ever produced here. The other members exist so the
    audit record cannot be misread as containing stronger evidence than it does.
    """

    PREDICTED = "predicted"
    NATIVE_SELECTION = "native_selection"
    PHYSICAL_EVICTION = "physical_eviction"
    CONTENT_IDENTITY = "content_identity"
    DOWNSTREAM_RECOMPUTE = "downstream_recompute"


def predict_victims(
    newly_eligible_block_ids: Sequence[int],
    ranking_by_block: Mapping[int, int],
    deficit: int,
) -> tuple[int, ...]:
    """Predicted victim set: first ``deficit`` newly eligible blocks by native rank.

    The frozen eligibility rule consumes Tier 1 (already eligible) blocks first and
    then takes the surplus from the released entry. ``newly_eligible_block_ids`` is
    the set the release would unlock, so ordering it by original native LRU rank
    reproduces the frozen order exactly.

    ``N_i`` is **not** the number of evicted blocks; this function is what turns
    the marginal relief into an ordered victim set, and it truncates at
    ``deficit``.
    """

    if deficit < 0:
        raise ValueError("deficit must be non-negative")
    ordered = sorted(
        (ranking_by_block[block_id], block_id)
        for block_id in newly_eligible_block_ids
        if block_id in ranking_by_block
    )
    return tuple(block_id for _rank, block_id in ordered[:deficit])


@dataclass(frozen=True, slots=True)
class CandidateCostAudit:
    """Per-candidate record making the score reproducible from frozen inputs.

    Every field the design document promised is here, including ``need``,
    ``deficit``, ``N``, ``V_X``, ``m``, ``d_min``, ``S``, ``q``, ``prefill``,
    ``score``, ``selected`` and ``fallback_reason``.
    """

    key: CandidateKey
    need: int
    deficit: int
    new_blocks: int
    deadline: float
    victim_block_ids: tuple[int, ...]
    victim_depths: tuple[int, ...]
    chain_length: int | None
    d_min: int | None
    suffix_blocks: int | None
    reuse_proxy: float
    prefill_reload_seconds: float | None
    score: float | None
    evidence: VictimEvidence = VictimEvidence.PREDICTED
    selected: bool = False
    fallback_reason: str = FAIL_NONE

    @property
    def scorable(self) -> bool:
        return self.score is not None and self.fallback_reason == FAIL_NONE

    @property
    def victim_count(self) -> int:
        """``|V_X|``: the predicted victim count, never the evicted count."""

        return len(self.victim_block_ids)


@dataclass(frozen=True, slots=True)
class A3SuffixSelection:
    """What the ladder chose on one iteration, with the whole audit trail."""

    key: CandidateKey
    step: str
    branch: str
    need: int
    deficit: int
    audits: tuple[CandidateCostAudit, ...]
    a1_key: CandidateKey
    a1_branch: str
    fell_back: bool = False
    fallback_reason: str = FAIL_NONE

    def audit_for(self, key: CandidateKey) -> CandidateCostAudit | None:
        for audit in self.audits:
            if audit.key == key:
                return audit
        return None


def step_for_branch(branch: str) -> str:
    """Map a frozen A1 branch label to the ladder step it represents.

    Step 2 does not use this: it is reported directly as
    :data:`STEP_SUFFICIENT` because its ordering key is the only thing this module
    replaces. Steps 3-5 delegate to the frozen implementation and are labelled
    from the branch the frozen ladder actually took, so the record cannot claim a
    step that did not run.

    Step 5 (deadline fallback) is unreachable for a snapshot produced by
    :func:`kvopt.costaware.replay.load_decision_snapshots` for the same reason the
    frozen engine documents: if every candidate owns nothing in the queue then all
    queue blocks are already eligible and Step 1 applies instead. The mapping is
    still total so that a malformed state is labelled rather than crashing.
    """

    if branch == BRANCH_PER_UNIT:
        return STEP_PER_UNIT
    if branch == BRANCH_PAIR_LOOKAHEAD:
        return STEP_PAIR_LOOKAHEAD
    if branch == BRANCH_DEADLINE_FALLBACK:
        return STEP_FALLBACK
    return STEP_NO_NEED


@dataclass(frozen=True, slots=True)
class A3SuffixCostStrategy:
    """Step 2 of the frozen A1 ladder, re-keyed on the suffix cost proxy.

    Composes :class:`A1EntryCostAwareStrategy` so that Steps 1 and 3-5 are the
    frozen implementation by construction rather than by resemblance.
    """

    depth_index: ChainDepthIndex
    native_hash_process_id: str = CHAIN_PROCESS_UNSET
    decision_clock_domain: str = CLOCK_DOMAIN_UNKNOWN
    max_age_seconds: float | None = None
    lambda_: float = 0.5
    tau_seconds: float = default_tau_seconds()
    strategy_id: str = STRATEGY_ID

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not 0.0 <= self.lambda_ <= 1.0:
            raise ValueError("lambda_ must lie in [0, 1]")
        if self.tau_seconds <= 0.0:
            raise ValueError("tau_seconds must be positive")
        if self.max_age_seconds is not None and self.max_age_seconds <= 0.0:
            raise ValueError("max_age_seconds must be positive when given")

    # -- delegation ------------------------------------------------------

    def _frozen_a1(self) -> A1EntryCostAwareStrategy:
        """The frozen ladder, constructed with this strategy's knobs only.

        Reusing the frozen object is deliberate: it guarantees Steps 1 and 3-5
        cannot drift, and it reuses the frozen ``reuse_proxy`` values rather than
        recomputing ``q``, so ``tau`` cannot silently diverge.
        """

        return A1EntryCostAwareStrategy(
            lambda_=self.lambda_,
            tau_seconds=self.tau_seconds,
            strategy_id=f"{self.strategy_id}:frozen_a1_ladder",
        )

    # -- scoring ---------------------------------------------------------

    def _query(
        self,
        chain_id: CandidateKey,
        *,
        decision_index: int,
        decision_time: float,
        recorded_process_id: str,
        expected_observation_index: int,
    ) -> DepthQuery:
        """Pin the query to the observation the caller is about to use.

        ``expected_observation_index`` is what turns a stale proof into an
        explicit ``SUPERSEDED`` failure instead of a silently accepted number.
        """

        process_id = (
            self.native_hash_process_id if self.native_hash_process_id else recorded_process_id
        )
        kwargs: dict[str, object] = {
            "chain_id": chain_id,
            "native_hash_process_id": process_id,
            "decision_index": decision_index,
            "decision_time": decision_time,
            "decision_clock_domain": self.decision_clock_domain,
            "expected_observation_index": expected_observation_index,
        }
        if self.max_age_seconds is not None:
            kwargs["max_age_seconds"] = self.max_age_seconds
        return DepthQuery(**kwargs)  # type: ignore[arg-type]

    def _audit(
        self,
        row: DecisionCandidateRow,
        *,
        new_blocks: int,
        need: int,
        deficit: int,
        reuse_proxy: float,
        state: ReplayState,
    ) -> CandidateCostAudit:
        key = candidate_key(row)
        snapshot = state.snapshot
        prefill = row.prefill_reload_seconds
        victims = predict_victims(
            state.newly_eligible_after(key), snapshot.ranking_by_block, deficit
        )

        common = {
            "key": key,
            "need": need,
            "deficit": deficit,
            "new_blocks": new_blocks,
            "deadline": row.retention_deadline_timestamp,
            "victim_block_ids": victims,
            "reuse_proxy": reuse_proxy,
        }

        if len(victims) < deficit:
            return CandidateCostAudit(
                **common,
                victim_depths=(),
                chain_length=None,
                d_min=None,
                suffix_blocks=None,
                prefill_reload_seconds=prefill,
                score=None,
                fallback_reason=FAIL_VICTIM_SHORTFALL,
            )

        if not math.isfinite(prefill) or prefill <= 0.0:
            return CandidateCostAudit(
                **common,
                victim_depths=(),
                chain_length=None,
                d_min=None,
                suffix_blocks=None,
                prefill_reload_seconds=prefill,
                score=None,
                fallback_reason=FAIL_PREFILL_MISSING,
            )

        proof = self.depth_index.latest_before(key, snapshot.decision_event_index)
        if proof is None:
            return CandidateCostAudit(
                **common,
                victim_depths=(),
                chain_length=None,
                d_min=None,
                suffix_blocks=None,
                prefill_reload_seconds=prefill,
                score=None,
                fallback_reason=FAIL_NO_OBSERVATION,
            )

        query = self._query(
            key,
            decision_index=snapshot.decision_event_index,
            decision_time=snapshot.timestamp,
            recorded_process_id=proof.native_hash_process_id,
            expected_observation_index=proof.observation_index,
        )

        resolution = proof.resolve(query, victims)
        if not resolution.resolved:
            return CandidateCostAudit(
                **common,
                victim_depths=(),
                chain_length=proof.chain_length,
                d_min=None,
                suffix_blocks=None,
                prefill_reload_seconds=prefill,
                score=None,
                fallback_reason=(
                    f"{FAIL_DEPTH_UNAVAILABLE}:"
                    + ",".join(
                        f"{block}:{status.value}"
                        for block, status in sorted(resolution.failures.items())
                    )
                ),
            )

        victim_depths = tuple(resolution.depths[block] for block in victims)
        m = proof.chain_length
        d_min = min(victim_depths)
        suffix = m - d_min + 1
        if m <= 0 or d_min < 1 or suffix < 1 or suffix > m:
            return CandidateCostAudit(
                **common,
                victim_depths=victim_depths,
                chain_length=m,
                d_min=d_min,
                suffix_blocks=None,
                prefill_reload_seconds=prefill,
                score=None,
                fallback_reason=FAIL_INVALID_GEOMETRY,
            )

        score = reuse_proxy * prefill * suffix / m
        return CandidateCostAudit(
            **common,
            victim_depths=victim_depths,
            chain_length=m,
            d_min=d_min,
            suffix_blocks=suffix,
            prefill_reload_seconds=prefill,
            score=score,
        )

    @staticmethod
    def _order(audit: CandidateCostAudit) -> tuple[float, float, CandidateKey]:
        """Total order ``(L, deadline, identity)`` -- deterministic, no ties left."""

        return (
            audit.score if audit.score is not None else math.inf,
            audit.deadline,
            audit.key,
        )

    # -- the ladder ------------------------------------------------------

    def select(
        self,
        remaining: Sequence[DecisionCandidateRow],
        state: ReplayState,
    ) -> A3SuffixSelection:
        """Choose one entry to release. Pure function of the frozen inputs."""

        base = self._frozen_a1().select(remaining, state)
        need = base.need

        if need <= 0:
            return A3SuffixSelection(
                key=base.key,
                step=STEP_NO_NEED,
                branch=base.branch,
                need=need,
                deficit=0,
                audits=(),
                a1_key=base.key,
                a1_branch=base.branch,
            )

        sufficient = tuple(score for score in base.scores if score.new_blocks >= need)
        if not sufficient:
            # Steps 3-5 are the frozen implementation, untouched.
            return A3SuffixSelection(
                key=base.key,
                step=step_for_branch(base.branch),
                branch=base.branch,
                need=need,
                deficit=need,
                audits=(),
                a1_key=base.key,
                a1_branch=base.branch,
            )

        audits = tuple(
            self._audit(
                _row_for(remaining, score.key),
                new_blocks=score.new_blocks,
                need=need,
                deficit=need,
                reuse_proxy=score.reuse_proxy,
                state=state,
            )
            for score in sufficient
        )

        unscorable = tuple(audit for audit in audits if not audit.scorable)
        if unscorable:
            # Fail closed for the *whole* Step 2 decision, not just this candidate.
            reason = f"{FALLBACK_STEP2_UNSCORABLE}:" + ",".join(
                f"{audit.key[0]}:{audit.fallback_reason}" for audit in unscorable
            )
            return A3SuffixSelection(
                key=base.key,
                step=STEP_SUFFICIENT,
                branch=BRANCH_SINGLE_STEP,
                need=need,
                deficit=need,
                audits=audits,
                a1_key=base.key,
                a1_branch=base.branch,
                fell_back=True,
                fallback_reason=reason,
            )

        chosen = min(audits, key=self._order)
        marked = tuple(replace(audit, selected=audit.key == chosen.key) for audit in audits)
        return A3SuffixSelection(
            key=chosen.key,
            step=STEP_SUFFICIENT,
            branch=BRANCH_SINGLE_STEP,
            need=need,
            deficit=need,
            audits=marked,
            a1_key=base.key,
            a1_branch=base.branch,
        )

    # -- ReleaseStrategy protocol ---------------------------------------

    def pick_next(
        self, remaining: Sequence[DecisionCandidateRow], state: ReplayState
    ) -> CandidateKey:
        return self.select(remaining, state).key


def _row_for(remaining: Sequence[DecisionCandidateRow], key: CandidateKey) -> DecisionCandidateRow:
    for row in remaining:
        if candidate_key(row) == key:
            return row
    raise ValueError(f"candidate {key!r} is not among the remaining candidates")


@dataclass(frozen=True, slots=True)
class A3ReplayRecord:
    """A replayed decision plus the audit trail of every release iteration."""

    outcome: ReplayOutcome
    selections: tuple[A3SuffixSelection, ...]

    @property
    def audits(self) -> tuple[CandidateCostAudit, ...]:
        return tuple(audit for selection in self.selections for audit in selection.audits)

    @property
    def fallback_reasons(self) -> tuple[str, ...]:
        return tuple(
            selection.fallback_reason for selection in self.selections if selection.fell_back
        )


def replay_with_audit(
    snapshot: DecisionSnapshot,
    strategy: A3SuffixCostStrategy,
    rows_by_key: Mapping[CandidateKey, DecisionCandidateRow],
) -> A3ReplayRecord:
    """Replay the frozen loop while keeping every iteration's audit trail.

    Mirrors :func:`kvopt.costaware.replay.replay_decision` exactly -- same stop
    condition, same legality check, same re-ranking -- so the recorded decision is
    the one the frozen loop would take, only with the audit records attached.
    """

    state = ReplayState(snapshot)
    initial = len(state.eligible_block_ids())
    selections: list[A3SuffixSelection] = []
    iterations = 0
    while len(state.eligible_block_ids()) < snapshot.target:
        remaining = [
            rows_by_key[key]
            for key in snapshot.candidate_keys
            if key not in state.released and key in rows_by_key
        ]
        if not remaining:
            break
        selection = strategy.select(remaining, state)
        allowed = {candidate_key(row) for row in remaining}
        if selection.key not in allowed:
            raise ValueError(
                f"strategy {strategy.strategy_id!r} selected {selection.key!r}, "
                "which is not one of the still-protected decision candidates"
            )
        selections.append(selection)
        state.release(selection.key)
        iterations += 1

    final = len(state.eligible_block_ids())
    outcome = ReplayOutcome(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        strategy_id=strategy.strategy_id,
        target=snapshot.target,
        eligible_blocks_initial=initial,
        eligible_blocks_final=final,
        released=state.release_order,
        satisfied=final >= snapshot.target,
        exhausted=final < snapshot.target,
        iterations=iterations,
    )
    return A3ReplayRecord(outcome=outcome, selections=tuple(selections))


def build_strategy(
    strategy_id: str,
    *,
    depth_index: ChainDepthIndex,
    native_hash_process_id: str = CHAIN_PROCESS_UNSET,
    decision_clock_domain: str = CLOCK_DOMAIN_UNKNOWN,
    lambda_: float = 0.5,
    tau_seconds: float = default_tau_seconds(),
) -> A3SuffixCostStrategy:
    """Construct the strategy **only** for its explicit strategy id.

    Explicit enablement is the point: A0, A1 and A2 keep their own selectors, and
    nothing can opt into this behaviour by merely passing a plausible name.
    """

    if strategy_id != STRATEGY_ID:
        raise ValueError(
            f"unknown strategy id {strategy_id!r}; Phase 2I is enabled only by {STRATEGY_ID!r}"
        )
    return A3SuffixCostStrategy(
        depth_index=depth_index,
        native_hash_process_id=native_hash_process_id,
        decision_clock_domain=decision_clock_domain,
        lambda_=lambda_,
        tau_seconds=tau_seconds,
        strategy_id=strategy_id,
    )
