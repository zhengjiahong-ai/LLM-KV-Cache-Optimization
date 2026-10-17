"""Phase 2G A1: entry-level cost-aware pressure release.

This is the ``ReleaseStrategy`` authorised by M1 for the first implementation
round. It replaces only *which protected entry* the frozen pressure loop releases
first; the block layer still evicts through native LRU, and the loop still stops
as soon as the frozen target is met.

Design authority
----------------
``docs/phase2-cost-aware-joint-design.md`` §3.3 (entry scoring), §3.3.4 (release
procedure incl. ``N_i = 0``), and §1.3 (constraints C1-C4). Deviations from that
document are listed under "Scope notes" below and nowhere else.

Decision rule
-------------
Let ``need = target - |E(R)|``, ``N_i = |E(R u {i})| - |E(R)|`` and

    Rhat_i = q_i * [ min(need, N_i) + lambda * (N_i - min(need, N_i))^+ ]

with the reuse proxy ``q_i = sigmoid((deadline_i - t) / tau)``. The block token
size ``B`` is a positive constant and cancels in every comparison, so it is not
carried.

Branch ladder, evaluated fresh on every iteration:

``3a`` the *single-step sufficient* set ``{i : N_i >= need}`` is non-empty:
        pick ``argmin Rhat_i``;
``3b`` otherwise, among ``{i : N_i > 0}``: pick ``argmin Rhat_i / N_i``, because
        relief itself becomes the scarce quantity;
``3c`` otherwise every ``N_i`` is zero (entries co-own everything): two-entry
        lookahead over pairs with positive joint relief, scored by
        ``Rhat_ij / N_ij`` with ``q~ = 1 - (1-q_i)(1-q_j)``; release the
        sooner-deadline member first. This is a *one-step proposal*, not a
        binding two-release batch: the replay re-ranks after every release;
``fallback`` no pair unlocks anything: release the soonest deadline.

Every branch is deterministic: the total order is ``(score, deadline, identity)``
with identity = ``(program_id, prefix_id)``.

Scope notes
-----------
- Only two-entry lookahead is implemented. A ``k``-entry search is explicitly out
  of scope in §3.3.4.2; on H1 no decision needs it (0/81 with all ``N_i = 0``).
- ``lambda_`` and ``tau_seconds`` are configuration knobs standing in for
  heuristic proxies, not calibrated probabilities. They are recorded in every
  outcome so a reader can see which values produced a given choice.
- ``q_i`` reads only ``retention_deadline_timestamp`` and the decision timestamp;
  nothing here touches future-derived or post-decision fields.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from kvopt.profiling.datasets import DecisionCandidateRow

from .replay import CandidateKey, ReplayState, candidate_key

#: Branch labels, persisted so a reader can tell *why* a choice was made.
BRANCH_SINGLE_STEP = "single_step"
BRANCH_PER_UNIT = "per_unit"
BRANCH_PAIR_LOOKAHEAD = "pair_lookahead"
BRANCH_DEADLINE_FALLBACK = "deadline_fallback"

#: Sentinel score used by the runner when a candidate cannot be scored at all.
UNSCOREABLE = math.inf


def default_tau_seconds() -> float:
    """Time scale used when the caller does not supply one.

    30 s is a stated default, not a fitted constant: it sets how sharply ``q``
    saturates around the retention deadline. Exposed as a function so tests and
    the runner cannot drift to different literals.
    """
    return 30.0


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Per-candidate diagnostics for one iteration of the ladder.

    Exposed so the comparison runner can report the cost proxy without
    re-deriving the formula, which would let the two implementations drift.
    """

    key: CandidateKey
    new_blocks: int
    deadline: float
    reuse_proxy: float
    expected_recompute: float
    per_unit: float | None


@dataclass(frozen=True, slots=True)
class A1Selection:
    """What the ladder chose on one iteration, with its justification."""

    key: CandidateKey
    branch: str
    scores: tuple[CandidateScore, ...]
    joint_new_blocks: int | None = None
    joint_reuse_proxy: float | None = None
    proposed_partner: CandidateKey | None = None
    joint_cost_proxy: float | None = None


def reuse_proxy(deadline: float, timestamp: float, tau: float) -> float:
    """``sigmoid((deadline - t) / tau)``.

    ``> 0.5`` means the retention deadline has not passed; ``< 0.5`` means it has
    passed but the entry has not been released yet, which is the normal state of
    an entry the pressure loop is about to sacrifice.
    """
    return 1.0 / (1.0 + math.exp(-(deadline - timestamp) / tau))


@dataclass(frozen=True, slots=True)
class A1EntryCostAwareStrategy:
    """Entry-level cost-aware release with native LRU left untouched.

    Implements the ``ReleaseStrategy`` protocol from
    :mod:`kvopt.costaware.replay`, so it can be dropped into the existing replay
    loop without any change to that loop's semantics.
    """

    lambda_: float = 0.5
    tau_seconds: float = default_tau_seconds()
    strategy_id: str = "A1_entry_cost_aware"

    def __post_init__(self) -> None:
        if not 0.0 <= self.lambda_ <= 1.0:
            raise ValueError("lambda_ must lie in [0, 1]")
        if self.tau_seconds <= 0.0:
            raise ValueError("tau_seconds must be positive")

    # -- scoring ---------------------------------------------------------

    def _score(
        self,
        row: DecisionCandidateRow,
        new_blocks: int,
        need: int,
        timestamp: float,
    ) -> CandidateScore:
        q = reuse_proxy(row.retention_deadline_timestamp, timestamp, self.tau_seconds)
        forced = min(need, new_blocks)
        residual = max(0, new_blocks - forced)
        expected = q * (forced + self.lambda_ * residual)
        per_unit = (expected / new_blocks) if new_blocks > 0 else None
        return CandidateScore(
            key=candidate_key(row),
            new_blocks=new_blocks,
            deadline=row.retention_deadline_timestamp,
            reuse_proxy=q,
            expected_recompute=expected,
            per_unit=per_unit,
        )

    @staticmethod
    def _order(score: CandidateScore) -> tuple[float, float, CandidateKey]:
        return (score.expected_recompute, score.deadline, score.key)

    @staticmethod
    def _per_unit_order(score: CandidateScore) -> tuple[float, float, CandidateKey]:
        # ``per_unit`` is not None on this path by construction.
        return (score.per_unit if score.per_unit is not None else UNSCOREABLE, score.deadline, score.key)

    # -- the ladder ------------------------------------------------------

    def select(
        self,
        remaining: Sequence[DecisionCandidateRow],
        state: ReplayState,
    ) -> A1Selection:
        """Choose one entry to release, with diagnostics. Pure function of state."""
        if not remaining:
            raise ValueError("select requires at least one remaining candidate")

        snapshot = state.snapshot
        target = snapshot.target
        eligible = len(state.eligible_block_ids())
        need = target - eligible

        scores = tuple(
            self._score(
                row,
                len(state.newly_eligible_after(candidate_key(row))),
                max(need, 0),
                snapshot.timestamp,
            )
            for row in remaining
        )

        if need <= 0:
            # The frozen loop would not be iterating at all; choose the cheapest
            # so the caller still gets a well-defined answer.
            best = min(scores, key=self._order)
            return A1Selection(best.key, BRANCH_SINGLE_STEP, scores)

        sufficient = tuple(s for s in scores if s.new_blocks >= need)
        if sufficient:
            best = min(sufficient, key=self._order)
            return A1Selection(best.key, BRANCH_SINGLE_STEP, scores)

        positive = tuple(s for s in scores if s.new_blocks > 0)
        if positive:
            best = min(positive, key=self._per_unit_order)
            return A1Selection(best.key, BRANCH_PER_UNIT, scores)

        # Every N_i is zero: no lone release unlocks anything.
        pair = self._best_pair(scores, remaining, state, need)
        if pair is None:
            best = min(scores, key=lambda s: (s.deadline, s.key))
            return A1Selection(best.key, BRANCH_DEADLINE_FALLBACK, scores)

        (first, second), joint_blocks, joint_q, joint_cost = pair
        return A1Selection(
            key=first,
            branch=BRANCH_PAIR_LOOKAHEAD,
            scores=scores,
            joint_new_blocks=joint_blocks,
            joint_reuse_proxy=joint_q,
            proposed_partner=second,
            joint_cost_proxy=joint_cost,
        )

    def _best_pair(
        self,
        scores: tuple[CandidateScore, ...],
        remaining: Sequence[DecisionCandidateRow],
        state: ReplayState,
        need: int,
    ) -> tuple[tuple[CandidateKey, CandidateKey], int, float, float] | None:
        """Best (first, second) pair by cost per unit relief, or ``None``."""
        by_key = {candidate_key(row): row for row in remaining}
        best: tuple[
            tuple[float, float, CandidateKey, CandidateKey],
            tuple[CandidateKey, CandidateKey],
            int,
            float,
        ] | None = None

        ordered = sorted(scores, key=lambda s: s.key)
        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                joint = len(
                    state.newly_eligible_after_many((first.key, second.key))
                )
                if joint <= 0:
                    continue
                joint_q = 1.0 - (1.0 - first.reuse_proxy) * (1.0 - second.reuse_proxy)
                forced = min(need, joint)
                residual = max(0, joint - forced)
                cost = joint_q * (forced + self.lambda_ * residual)
                # Release the sooner-deadline member first; it is the one the
                # frozen order would have taken, so the pair never reorders more
                # than the lookahead requires.
                row_a, row_b = by_key[first.key], by_key[second.key]
                if row_a.retention_deadline_timestamp <= (
                    row_b.retention_deadline_timestamp
                ):
                    pair = (first.key, second.key)
                else:
                    pair = (second.key, first.key)
                rank = (cost / joint, joint_q, pair[0], pair[1])
                if best is None or rank < best[0]:
                    best = (rank, pair, joint, joint_q)

        if best is None:
            return None
        # This pair is a lookahead proposal, not an atomic release commitment.
        # After the first entry is released, the next pick_next call may choose
        # a different partner because the frozen replay re-ranks every step.
        return best[1], best[2], best[3], best[0][0] * best[2]

    # -- ReleaseStrategy protocol ---------------------------------------

    def pick_next(
        self, remaining: Sequence[DecisionCandidateRow], state: ReplayState
    ) -> CandidateKey:
        return self.select(remaining, state).key
