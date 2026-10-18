"""Tests for the A2 screening gate, cause stratification, and corpus labelling.

RC3 raised three things and all three are pinned here:

1. the gate must not hard-AND depth inversion with q-versus-rank disagreement, because
   a single inverted chain can produce a different victim set with no q comparison;
2. denominators must be recomputed after strict filtering without silently dropping
   the excluded decisions;
3. a legacy-corpus report must never be presentable as the Gate 2 verdict.
"""

from __future__ import annotations

from kvopt.costaware.a2_compare import (
    CAUSE_DEPTH_INVERSION,
    CAUSE_Q_REORDER,
    LABEL_GATE2,
    LABEL_LEGACY,
    divergence_causes,
    gate2_status,
    summarise,
)
from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
    evaluate,
)


def _member(chain: str, depth: int) -> Membership:
    return Membership(chain=chain, depth=depth, content_hash=f"{chain}#{depth}")


def _inverted_single_chain(q: float = 1.0) -> DecisionGeometry:
    """One chain, shallower blocks colder, so native takes the shallowest first."""
    blocks = {
        10 + depth: LegalBlock(
            block_id=10 + depth,
            native_rank=depth - 1,
            memberships=(_member("a", depth),),
        )
        for depth in range(1, 5)
    }
    return DecisionGeometry(
        blocks=blocks, chain_length={"a": 4}, q_by_chain={"a": q}
    )


def _pair(geometry: DecisionGeometry, need: int):
    row = evaluate(run_id="r", decision_event_index=1, geometry=geometry, need=need)
    return row, geometry


# --- RC3: the gate must not require a q comparison ------------------------


def test_single_inverted_chain_qualifies_without_any_q_disagreement() -> None:
    """No second chain means q-vs-rank is not comparable, yet a real difference exists.

    Rev.2's gate required both signals, which would have discarded exactly this case.
    """
    geometry = _inverted_single_chain()
    row, _ = _pair(geometry, 2)

    assert row.q_order_agrees_with_rank is None  # nothing to compare
    assert row.victim_set_differs
    assert row.verified
    assert row.native is not None and row.cost_aware is not None
    assert row.cost_aware.proxy_weighted_loss < row.native.proxy_weighted_loss

    summary = summarise([_pair(geometry, 2)])
    assert summary["screening_gate"]["qualifying_decisions"] == 1
    assert summary["screening_gate"]["passed"] is True


def test_gate_requires_a_lower_modelled_loss_not_just_a_difference() -> None:
    """A set difference with no cost benefit must not qualify."""
    # Same chain, ordered, so the two rules agree -- no difference at all.
    blocks = {
        10 + depth: LegalBlock(
            block_id=10 + depth,
            native_rank=4 - depth,
            memberships=(_member("a", depth),),
        )
        for depth in range(1, 5)
    }
    geometry = DecisionGeometry(
        blocks=blocks, chain_length={"a": 4}, q_by_chain={"a": 1.0}
    )
    row, _ = _pair(geometry, 2)
    assert not row.victim_set_differs
    summary = summarise([_pair(geometry, 2)])
    assert summary["screening_gate"]["qualifying_decisions"] == 0
    assert summary["screening_gate"]["passed"] is False


# --- RC3: denominators after strict filtering -----------------------------


def test_unverified_decisions_are_counted_not_dropped() -> None:
    verified = _pair(_inverted_single_chain(), 2)
    # Degraded geometry: an unknown reuse weight.
    blocks = {
        10 + depth: LegalBlock(
            block_id=10 + depth,
            native_rank=depth,
            memberships=(_member("a", depth),),
        )
        for depth in range(1, 3)
    }
    degraded = DecisionGeometry(
        blocks=blocks,
        chain_length={"a": 2},
        q_by_chain={},
        unknown_weight_chains=("a",),
    )
    summary = summarise([verified, _pair(degraded, 1)])

    assert summary["decisions"] == 2
    assert summary["verified_decisions"] == 1
    assert summary["excluded_decisions"] == 1
    assert summary["exclusions"]["reuse_weight_unknown"] == 1


def test_unverified_difference_is_reported_as_diagnostic_only() -> None:
    """Chain a has no reuse weight; chain b does and is colder.

    Native follows rank and takes b. The diagnostic ordering treats a's unknown
    weight as zero, so it takes a. The choice therefore differs, but the loss cannot
    be computed, and the difference must stay a diagnostic.
    """
    blocks: dict[int, LegalBlock] = {}
    for depth in range(1, 5):
        blocks[10 + depth] = LegalBlock(
            block_id=10 + depth,
            native_rank=10 + depth,  # warmer
            memberships=(_member("a", depth),),
        )
        blocks[20 + depth] = LegalBlock(
            block_id=20 + depth,
            native_rank=depth - 1,  # colder
            memberships=(_member("b", depth),),
        )
    geometry = DecisionGeometry(
        blocks=blocks,
        chain_length={"a": 4, "b": 4},
        q_by_chain={"b": 0.1},
        unknown_weight_chains=("a",),
    )
    row, _ = _pair(geometry, 2)
    assert row.victim_set_differs  # the choice still differs ...
    assert not row.verified  # ... but it cannot be scored
    assert row.native is None and row.cost_aware is None

    summary = summarise([_pair(geometry, 2)])
    assert summary["diagnostic"]["victim_set_differs"] == 1
    assert summary["diagnostic"]["victim_set_differs_verified"] == 0
    assert summary["diagnostic"]["victim_set_differs_unverified"] == 1
    assert summary["screening_gate"]["qualifying_decisions"] == 0


# --- RC3: divergence causes are stratified --------------------------------


def test_depth_inversion_cause_is_identified() -> None:
    row, geometry = _pair(_inverted_single_chain(), 2)
    assert CAUSE_DEPTH_INVERSION in divergence_causes(row, geometry)


def test_no_cause_is_reported_when_the_sets_match() -> None:
    blocks = {
        10 + depth: LegalBlock(
            block_id=10 + depth,
            native_rank=4 - depth,
            memberships=(_member("a", depth),),
        )
        for depth in range(1, 5)
    }
    geometry = DecisionGeometry(
        blocks=blocks, chain_length={"a": 4}, q_by_chain={"a": 1.0}
    )
    row, _ = _pair(geometry, 2)
    assert divergence_causes(row, geometry) == ()


def test_cause_list_records_both_signals_when_both_hold() -> None:
    """Two chains, inverted depth on one and q disagreeing with rank."""
    blocks: dict[int, LegalBlock] = {}
    # chain a: shallow colder (inverted)
    for depth in range(1, 4):
        blocks[10 + depth] = LegalBlock(
            block_id=10 + depth,
            native_rank=depth - 1,
            memberships=(_member("a", depth),),
        )
    # chain b: also inverted, but with a much lower q
    for depth in range(1, 4):
        blocks[20 + depth] = LegalBlock(
            block_id=20 + depth,
            native_rank=2 + depth,
            memberships=(_member("b", depth),),
        )
    geometry = DecisionGeometry(
        blocks=blocks, chain_length={"a": 3, "b": 3}, q_by_chain={"a": 0.9, "b": 0.1}
    )
    row, _ = _pair(geometry, 2)
    causes = divergence_causes(row, geometry)
    assert CAUSE_Q_REORDER in causes
    assert CAUSE_DEPTH_INVERSION in causes


def test_causes_are_counted_only_for_verified_differences() -> None:
    verified = _pair(_inverted_single_chain(), 2)
    summary = summarise([verified])
    assert summary["diagnostic"]["divergence_causes_verified"] == {
        CAUSE_DEPTH_INVERSION: 1
    }


# --- RC3: corpus labelling ------------------------------------------------


def test_legacy_corpus_is_never_a_gate2_verdict() -> None:
    status = gate2_status(None, LABEL_LEGACY)
    assert status["computable"] is False
    assert status["corpus"] == LABEL_LEGACY
    assert "must not be reported as the Gate 2 verdict" in status["reason"]


def test_gate2_without_an_archive_is_not_computable() -> None:
    status = gate2_status(None, LABEL_GATE2)
    assert status["computable"] is False
    assert "no Gate 2 archive" in status["reason"]


def test_gate2_with_an_archive_is_computable(tmp_path) -> None:
    status = gate2_status(tmp_path, LABEL_GATE2)
    assert status["computable"] is True


def test_unspecified_corpus_is_not_treated_as_gate2() -> None:
    status = gate2_status(None, "")
    assert status["computable"] is False
