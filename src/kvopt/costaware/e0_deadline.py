"""Phase 3 E0: the frozen A1 ladder with deadline-only Step 2.

E0 is a control arm, not a new cost model.  It shares A3's evidence-availability
decision so S2B falls back to frozen A1 exactly as A3 does, and it delegates
S2C to the same frozen A1 result.  Only a fully scorable S2A decision is
re-keyed, using ``(deadline, identity)`` and ignoring every cost value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from kvopt.profiling.datasets import DecisionCandidateRow

from .a3_suffix import (
    STEP_SUFFICIENT,
    A3SuffixCostStrategy,
    A3SuffixSelection,
)
from .replay import CandidateKey, ReplayState

STRATEGY_ID = "E0_entry_deadline_step2"


def deadline_step2_selection(selection: A3SuffixSelection) -> A3SuffixSelection:
    """Apply E0's sole policy difference to an A3-classified decision.

    A3's classification is used only to keep S2B evidence failure and S2C
    delegation bit-for-bit aligned.  Cost scores and reuse proxies never enter
    the E0 ordering key.
    """

    if (
        selection.step != STEP_SUFFICIENT
        or selection.fell_back
        or not selection.audits
    ):
        return selection
    chosen = min(selection.audits, key=lambda row: (row.deadline, row.key))
    audits = tuple(
        replace(row, selected=row.key == chosen.key) for row in selection.audits
    )
    return replace(selection, key=chosen.key, audits=audits)


@dataclass(frozen=True, slots=True)
class E0DeadlineStrategy:
    """Compose the reviewed A3 classifier and replace only S2A ordering."""

    classifier: A3SuffixCostStrategy
    strategy_id: str = STRATEGY_ID

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")

    def select(
        self,
        remaining: Sequence[DecisionCandidateRow],
        state: ReplayState,
    ) -> A3SuffixSelection:
        return deadline_step2_selection(self.classifier.select(remaining, state))

    def pick_next(
        self,
        remaining: Sequence[DecisionCandidateRow],
        state: ReplayState,
    ) -> CandidateKey:
        return self.select(remaining, state).key
