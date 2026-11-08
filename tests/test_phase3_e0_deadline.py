from __future__ import annotations

from kvopt.costaware.a1_entry import BRANCH_SINGLE_STEP
from kvopt.costaware.a3_suffix import (
    FALLBACK_STEP2_UNSCORABLE,
    STEP_PER_UNIT,
    STEP_SUFFICIENT,
    A3SuffixSelection,
    CandidateCostAudit,
)
from kvopt.costaware.e0_deadline import deadline_step2_selection


def _audit(
    key: tuple[str, str], *, deadline: float, score: float, selected: bool = False
) -> CandidateCostAudit:
    return CandidateCostAudit(
        key=key,
        need=2,
        deficit=2,
        new_blocks=3,
        deadline=deadline,
        victim_block_ids=(1, 2),
        victim_depths=(1, 2),
        chain_length=3,
        d_min=1,
        suffix_blocks=3,
        reuse_proxy=0.9,
        prefill_reload_seconds=1.0,
        score=score,
        selected=selected,
    )


def _selection(*, fell_back: bool = False) -> A3SuffixSelection:
    return A3SuffixSelection(
        key=("cost-winner", "p"),
        step=STEP_SUFFICIENT,
        branch=BRANCH_SINGLE_STEP,
        need=2,
        deficit=2,
        audits=(
            _audit(("cost-winner", "p"), deadline=9.0, score=0.1, selected=True),
            _audit(("deadline-winner", "p"), deadline=1.0, score=9.0),
        ),
        a1_key=("a1", "p"),
        a1_branch=BRANCH_SINGLE_STEP,
        fell_back=fell_back,
        fallback_reason=FALLBACK_STEP2_UNSCORABLE if fell_back else "",
    )


def test_e0_s2a_uses_deadline_identity_and_ignores_cost_order() -> None:
    result = deadline_step2_selection(_selection())

    assert result.key == ("deadline-winner", "p")
    assert [row.key for row in result.audits if row.selected] == [result.key]


def test_e0_s2b_is_bitwise_aligned_with_a3_fallback() -> None:
    selection = _selection(fell_back=True)
    assert deadline_step2_selection(selection) is selection


def test_e0_s2c_is_bitwise_aligned_with_frozen_a1_delegation() -> None:
    selection = A3SuffixSelection(
        key=("delegated", "p"),
        step=STEP_PER_UNIT,
        branch="per_unit_relief",
        need=3,
        deficit=3,
        audits=(),
        a1_key=("delegated", "p"),
        a1_branch="per_unit_relief",
    )
    assert deadline_step2_selection(selection) is selection
