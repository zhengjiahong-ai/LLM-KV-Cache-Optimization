"""Pressure-feasible hindsight oracle for M4 method selection.

Why this exists
---------------

The canonical M6 ``build_decision_regret_table`` picks a **size-matched** set of
lowest-loss candidates and never checks whether that set would actually relieve
the pressure. That was a reasonable comparator when every rule released the same
number of entries. It no longer is, now that release count is an outcome of the
frozen pressure loop.

This module adds a second, feasibility-aware comparator **at the evaluator
layer**. The canonical M6 table is left untouched and keeps its provenance role;
the two are reported separately and never merged into one field.

Oracle definition
-----------------

For one decision and one loss view, among every release set that satisfies the
same ``required_blocks`` target::

    primary    minimize total canonical proxy loss
    secondary  minimize the number of released entries   (loss ties only)
    tertiary   stable logical identity order             (deterministic)

Search is exact. The formal campaign has 2-5 candidates per decision, so
enumeration is cheap and approximation would be unjustified.

Why subset enumeration equals the loop's outcome
-----------------------------------------------

The frozen loop stops at the first prefix of the release order that satisfies the
target, so its released set is always a *feasible* set. Conversely, for any
feasible set ``S`` some ordering of ``S`` makes the loop stop at a prefix
``P subseteq S`` which is feasible with ``loss(P) <= loss(S)`` and
``|P| <= |S|``, because proxy loss is non-negative. The lexicographic minimum
over feasible sets is therefore attained by a set the loop can actually produce,
so enumerating feasible subsets finds the same optimum as enumerating release
orders - at a fraction of the cost.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from .replay import CandidateKey, DecisionSnapshot, ReplayState

#: Above this candidate count exhaustive enumeration stops being cheap. The
#: formal campaign uses 2-5, so this is a large safety margin. Exceeding it
#: raises rather than silently approximating, because a silently different
#: comparator would corrupt every downstream comparison.
MAX_EXACT_CANDIDATES = 16

#: Matches the canonical M6 tolerance so both comparators treat ties alike.
_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class FeasibleOracleRow:
    """The oracle's optimum for one decision and one loss view."""

    run_id: str
    decision_event_index: int
    loss_view: str
    target: int
    candidate_count: int
    feasible_set_count: int
    oracle_released: tuple[CandidateKey, ...]
    oracle_loss: float
    oracle_entry_count: int
    worst_feasible_loss: float
    """Largest loss among feasible sets, for tie detection. NaN when unreachable."""
    unreachable: bool
    """True only for a degenerate snapshot where no subset reaches the target."""

    @property
    def full_candidate_set_is_required(self) -> bool:
        """True when the optimum needs every candidate released.

        A useful diagnostic: those decisions have no proper feasible subset, so
        no ordering can reach the target more cheaply.
        """
        return self.oracle_entry_count == self.candidate_count

    @property
    def loss_choices_matter(self) -> bool:
        """True when feasible sets disagree on loss, so the choice matters.

        The feasible-comparator analogue of M6's candidate-loss tie: when every
        feasible set costs the same, no rule can be penalised for which one it
        picked.
        """
        if self.unreachable:
            return False
        return not math.isclose(
            self.oracle_loss,
            self.worst_feasible_loss,
            abs_tol=_EPSILON,
            rel_tol=0,
        )


@dataclass(frozen=True, slots=True)
class PressureFeasibleRegretRow:
    """One rule's distance from the feasibility-aware optimum."""

    rule_id: str
    run_id: str
    decision_event_index: int
    loss_view: str
    target: int
    selected_released: tuple[CandidateKey, ...]
    selected_loss: float
    oracle_loss: float
    oracle_released: tuple[CandidateKey, ...]
    absolute_regret: float
    normalized_regret: float
    selected_is_oracle_best: bool
    entry_count_delta: int
    """Released entries relative to the oracle; positive means less efficient."""


def _identity_sort_key(keys: Sequence[CandidateKey]) -> tuple[CandidateKey, ...]:
    return tuple(sorted(keys))


def _subset_eligible_count(
    snapshot: DecisionSnapshot, released: frozenset[CandidateKey]
) -> int:
    """Eligible block count after releasing exactly ``released``.

    Reuses :class:`~kvopt.costaware.replay.ReplayState` so the eligibility model
    cannot diverge from the one the pressure replay uses.
    """
    state = ReplayState(snapshot)
    for key in released:
        state.release(key)
    return len(state.eligible_block_ids())


def build_feasible_oracle(
    snapshots: Sequence[DecisionSnapshot],
    losses: Mapping[tuple[str, int, CandidateKey], float],
    *,
    loss_view: str,
    included_runs: frozenset[str] | None = None,
) -> tuple[FeasibleOracleRow, ...]:
    """Compute the pressure-feasible optimum for every decision.

    ``losses`` is keyed by ``(run_id, decision_event_index, candidate_key)`` and
    must provide an entry for every candidate of every included decision, so a
    partially labelled decision is skipped rather than compared on a subset.
    """
    rows: list[FeasibleOracleRow] = []
    for snapshot in snapshots:
        if included_runs is not None and snapshot.run_id not in included_runs:
            continue
        decision_losses = _losses_for(
            snapshot, losses, loss_view=loss_view
        )
        if decision_losses is None:
            continue
        rows.append(_oracle_for(snapshot, decision_losses, loss_view=loss_view))
    return tuple(rows)


def _losses_for(
    snapshot: DecisionSnapshot,
    losses: Mapping[tuple[str, int, CandidateKey], float],
    *,
    loss_view: str,
) -> dict[CandidateKey, float] | None:
    """Return complete per-candidate losses, or None when evidence is missing."""
    found: dict[CandidateKey, float] = {}
    for key in snapshot.candidate_keys:
        value = losses.get((snapshot.run_id, snapshot.decision_event_index, key))
        if value is None:
            return None
        found[key] = float(value)
    return found


def _oracle_for(
    snapshot: DecisionSnapshot,
    candidate_losses: Mapping[CandidateKey, float],
    *,
    loss_view: str,
) -> FeasibleOracleRow:
    keys = tuple(sorted(candidate_losses))
    if len(keys) > MAX_EXACT_CANDIDATES:
        raise ValueError(
            f"decision {snapshot.run_id} event {snapshot.decision_event_index} has "
            f"{len(keys)} candidates, above the exact-search cap of "
            f"{MAX_EXACT_CANDIDATES}; refusing to approximate the comparator"
        )
    target = snapshot.target

    best_key: tuple[float, int, tuple[CandidateKey, ...]] | None = None
    best_set: tuple[CandidateKey, ...] = ()
    best_loss = 0.0
    worst_loss = 0.0
    feasible_count = 0

    for size in range(1, len(keys) + 1):
        for combination in combinations(keys, size):
            released = frozenset(combination)
            if _subset_eligible_count(snapshot, released) < target:
                continue
            feasible_count += 1
            ordered = _identity_sort_key(combination)
            total_loss = sum(candidate_losses[key] for key in ordered)
            if math.isclose(total_loss, 0.0, abs_tol=_EPSILON, rel_tol=0):
                total_loss = 0.0
            worst_loss = max(worst_loss, total_loss)
            candidate_key_tuple = (total_loss, size, ordered)
            if best_key is None or candidate_key_tuple < best_key:
                best_key = candidate_key_tuple
                best_set = ordered
                best_loss = total_loss

    if best_key is None:
        return FeasibleOracleRow(
            run_id=snapshot.run_id,
            decision_event_index=snapshot.decision_event_index,
            loss_view=loss_view,
            target=target,
            candidate_count=len(keys),
            feasible_set_count=0,
            oracle_released=(),
            oracle_loss=float("nan"),
            oracle_entry_count=0,
            worst_feasible_loss=float("nan"),
            unreachable=True,
        )

    return FeasibleOracleRow(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        loss_view=loss_view,
        target=target,
        candidate_count=len(keys),
        feasible_set_count=feasible_count,
        oracle_released=best_set,
        oracle_loss=best_loss,
        oracle_entry_count=len(best_set),
        worst_feasible_loss=worst_loss,
        unreachable=False,
    )


def pressure_feasible_regret(
    *,
    oracle_rows: Sequence[FeasibleOracleRow],
    selections: Mapping[str, Mapping[tuple[str, int], tuple[CandidateKey, ...]]],
    losses: Mapping[tuple[str, int, CandidateKey], float],
    loss_view: str,
) -> tuple[PressureFeasibleRegretRow, ...]:
    """Compare each rule's realised release set against the feasible optimum.

    Normalization matches the canonical M6 formula
    ``absolute_regret / max(abs(selected_loss), epsilon)`` so the two comparators
    are read the same way, even though they answer different questions.
    """
    oracle_by_decision = {
        (row.run_id, row.decision_event_index): row for row in oracle_rows
    }
    rows: list[PressureFeasibleRegretRow] = []
    for rule_id in sorted(selections):
        for decision_key in sorted(selections[rule_id]):
            oracle = oracle_by_decision.get(decision_key)
            if oracle is None or oracle.unreachable:
                continue
            run_id, decision_event_index = decision_key
            released = selections[rule_id][decision_key]
            selected_loss = 0.0
            for key in released:
                value = losses.get((run_id, decision_event_index, key))
                if value is None:
                    selected_loss = float("nan")
                    break
                selected_loss += float(value)
            if math.isnan(selected_loss):
                continue
            if math.isclose(selected_loss, 0.0, abs_tol=_EPSILON, rel_tol=0):
                selected_loss = 0.0
            absolute = selected_loss - oracle.oracle_loss
            if math.isclose(absolute, 0.0, abs_tol=_EPSILON, rel_tol=0):
                absolute = 0.0
            rows.append(
                PressureFeasibleRegretRow(
                    rule_id=rule_id,
                    run_id=run_id,
                    decision_event_index=decision_event_index,
                    loss_view=loss_view,
                    target=oracle.target,
                    selected_released=released,
                    selected_loss=selected_loss,
                    oracle_loss=oracle.oracle_loss,
                    oracle_released=oracle.oracle_released,
                    absolute_regret=absolute,
                    normalized_regret=(
                        absolute / max(abs(selected_loss), _EPSILON)
                    ),
                    selected_is_oracle_best=set(released) == set(oracle.oracle_released),
                    entry_count_delta=len(released) - oracle.oracle_entry_count,
                )
            )
    return tuple(rows)
