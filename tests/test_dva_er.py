"""CPU correctness tests for DVA-ER v1."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.continuum.selection import (
    BlockEligibilitySnapshot,
    EligibilityPreparation,
    EligibilityTier,
    PressureReleaseEffect,
    RetentionEntryKey,
)
from kvopt.continuum.types import BlockIdentity, PrefixIdentity, ProgramIdentity
from kvopt.costaware.dva_er import (
    DEFAULT_H_SECONDS,
    DVAERDecisionInput,
    DVAEREvidenceError,
    DVAERReplayStrategy,
    DVAERStrategy,
    FollowupGapSource,
    FollowupObservation,
    NativeBlock,
    NativePoolSnapshot,
    build_decision_input,
)
from kvopt.costaware.replay import ExecutedP1BStrategy
from kvopt.runtime.vllm.adapter import RetentionAwareLRUAdapter
from kvopt.runtime.vllm.types import EvictionCandidate, EvictionContext

ROOT = Path(__file__).resolve().parents[1]

A = ("p1", "a")
B = ("p2", "b")
C = ("p3", "c")


def _block(
    block_id: int,
    rank: int,
    *,
    owners: frozenset[tuple[str, str]] = frozenset(),
    protected: frozenset[tuple[str, str]] | None = None,
    refcount: int = 0,
    has_hash: bool = True,
) -> NativeBlock:
    return NativeBlock(
        block_id=block_id,
        has_hash=has_hash,
        refcount=refcount,
        native_lru_rank=rank,
        owners=owners,
        protected_owners=owners if protected is None else protected,
    )


def _followup(
    key: tuple[str, str],
    *,
    active: bool = False,
    gap: float | None = None,
    chain: str | None = None,
) -> FollowupObservation:
    return FollowupObservation(
        candidate_key=key,
        chain_id=chain or f"chain:{key[0]}:{key[1]}",
        active=active,
        pending_tool_gap_seconds=gap,
        observed_at_timestamp=9.0,
        chain_established_at_timestamp=5.0,
        pending_tool_gap_source=(FollowupGapSource.CONTROLLER_ARMED_TIMER if active else None),
    )


def _input(
    *,
    blocks: tuple[NativeBlock, ...],
    candidates: tuple[tuple[str, str], ...] = (A, B, C),
    followups: dict[tuple[str, str], FollowupObservation] | None = None,
    a0_order: tuple[tuple[str, str], ...] | None = None,
    required: int = 1,
    h: float = DEFAULT_H_SECONDS,
    free_queue: tuple[int, ...] | None = None,
) -> DVAERDecisionInput:
    keys = tuple(candidates)
    observations = followups or {key: _followup(key) for key in keys}
    if free_queue is None:
        free_queue = tuple(
            block.block_id
            for block in sorted(blocks, key=lambda row: row.native_lru_rank)
            if block.refcount == 0
        )
    return DVAERDecisionInput(
        decision_id="dva-test",
        timestamp=10.0,
        required_blocks=required,
        pool=NativePoolSnapshot(
            blocks=blocks,
            free_queue_order=free_queue,
            candidate_keys=keys,
        ),
        followups=observations,
        a0_order=tuple(keys if a0_order is None else a0_order),
        h_seconds=h,
    )


def test_multiple_legal_candidates_can_change_selection() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A, B}), protected=frozenset({A})),
        _block(2, 1, owners=frozenset({B, C}), protected=frozenset({B})),
        _block(3, 2, owners=frozenset({C, A}), protected=frozenset({C})),
    )
    decision = _input(
        blocks=blocks,
        followups={
            A: _followup(A),
            B: _followup(B, active=True, gap=10.0),
            C: _followup(C),
        },
        a0_order=(A, B, C),
    )
    result = DVAERStrategy().choose(decision)
    assert result.selected == B
    assert result.a0_tiebreak_used is True
    losses = {row.candidate_key: row for row in result.candidate_losses}
    assert {key: row.loss for key, row in losses.items()} == {A: 1, B: 0, C: 0}
    assert losses[A].risk_chain_ids == ("chain:p2:b",)


def test_same_entry_order_can_have_different_victim_risk() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A, B}), protected=frozenset({A})),
        _block(2, 1, owners=frozenset({B}), protected=frozenset({B})),
    )
    decision = _input(
        blocks=blocks,
        candidates=(A, B),
        followups={A: _followup(A), B: _followup(B, active=True, gap=5.0)},
        a0_order=(A, B),
    )
    result = DVAERStrategy().choose(decision)
    assert result.selected == B
    assert result.a0_tiebreak_used is False


def test_different_candidates_have_different_victim_sets() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({B})),
    )
    decision = _input(blocks=blocks, candidates=(A, B))
    a = decision.pool.victim_sequence_after(A, 1)
    b = decision.pool.victim_sequence_after(B, 1)
    assert a.victim_block_ids == (1,)
    assert b.victim_block_ids == (2,)
    assert a.victim_block_ids != b.victim_block_ids


def test_native_lru_sequence_is_ordered_and_full() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({A})),
        _block(3, 2, owners=frozenset({A})),
    )
    decision = _input(
        blocks=blocks,
        candidates=(A,),
        followups={A: _followup(A)},
        required=2,
    )
    sequence = decision.pool.victim_sequence_after(A, 2)
    assert sequence.full_eligible_sequence == (1, 2, 3)
    assert sequence.victim_block_ids == (1, 2)
    assert sequence.shortfall == 0


def test_shortfall_is_explicit_not_imputed() -> None:
    blocks = (_block(1, 0, owners=frozenset({A})),)
    decision = _input(
        blocks=blocks,
        candidates=(A,),
        followups={A: _followup(A)},
        required=2,
    )
    sequence = decision.pool.victim_sequence_after(A, 2)
    assert sequence.victim_block_ids == (1,)
    assert sequence.shortfall == 1


def test_a0_tie_break_is_reproduced() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({B})),
    )
    decision = _input(blocks=blocks, candidates=(A, B), a0_order=(B, A))
    result = DVAERStrategy().choose(decision)
    assert result.selected == B
    assert result.a0_tiebreak_used is True


def test_h_sensitivity_changes_weight() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A, B}), protected=frozenset({A})),
        _block(2, 1, owners=frozenset({B}), protected=frozenset({B})),
    )
    followups = {A: _followup(A), B: _followup(B, active=True, gap=90.0)}
    decision60 = _input(
        blocks=blocks,
        candidates=(A, B),
        followups=followups,
        a0_order=(A, B),
        h=60.0,
    )
    decision120 = replace(decision60, h_seconds=120.0)
    assert DVAERStrategy(60.0).choose(decision60).selected == A
    assert DVAERStrategy(120.0).choose(decision120).selected == B


def test_released_candidate_does_not_count_as_its_own_downstream_risk() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A}), protected=frozenset({A})),
        _block(2, 1, owners=frozenset({B}), protected=frozenset({B})),
    )
    decision = _input(
        blocks=blocks,
        candidates=(A, B),
        followups={
            A: _followup(A, active=True, gap=5.0),
            B: _followup(B, active=True, gap=5.0),
        },
        a0_order=(A, B),
    )
    result = DVAERStrategy().choose(decision)
    losses = {row.candidate_key: row.loss for row in result.candidate_losses}
    assert losses == {A: 0, B: 0}
    assert result.selected == A


def test_refcount_zero_with_protected_owner_is_eligible_only_after_release() -> None:
    blocks = (
        _block(
            1,
            0,
            owners=frozenset({A, B}),
            protected=frozenset({A}),
            refcount=0,
        ),
        _block(2, 1, owners=frozenset({B}), protected=frozenset({B}), refcount=0),
    )
    decision = _input(
        blocks=blocks,
        candidates=(A, B),
        required=1,
        free_queue=(1, 2),
    )
    a = decision.pool.victim_sequence_after(A, 1)
    b = decision.pool.victim_sequence_after(B, 1)
    assert a.physical_victim_block_ids == (1,)
    assert b.physical_victim_block_ids == (2,)
    assert decision.pool.blocks[0].refcount == 0
    assert decision.pool.blocks[0].protected_owners == frozenset({A})


def test_hashed_and_unprotected_block_is_eligible_without_release() -> None:
    blocks = (
        _block(
            1,
            0,
            owners=frozenset({A}),
            protected=frozenset(),
            refcount=0,
        ),
        _block(2, 1, owners=frozenset({A}), protected=frozenset({A}), refcount=1),
    )
    decision = _input(
        blocks=blocks,
        candidates=(A,),
        followups={A: _followup(A)},
        free_queue=(1,),
        required=1,
    )
    sequence = decision.pool.victim_sequence_after(A, 1)
    assert sequence.shortfall == 0
    assert sequence.physical_victim_block_ids == (1,)
    assert 1 in sequence.virtual_eligible_order


def test_missing_followup_fails_closed() -> None:
    with pytest.raises(DVAEREvidenceError, match="follow-up"):
        _input(
            blocks=(_block(1, 0, owners=frozenset({A})),),
            candidates=(A, B),
            followups={A: _followup(A)},
        )


def test_missing_active_gap_fails_closed() -> None:
    with pytest.raises(DVAEREvidenceError, match="pending tool gap"):
        _followup(A, active=True)


def test_incomplete_free_queue_fails_closed() -> None:
    blocks = (
        _block(
            1,
            0,
            owners=frozenset({A}),
            protected=frozenset(),
            refcount=0,
        ),
    )
    with pytest.raises(DVAEREvidenceError, match="free queue"):
        _input(blocks=blocks, candidates=(A,), followups={A: _followup(A)}, free_queue=())


def test_missing_a0_order_fails_closed() -> None:
    blocks = (_block(1, 0, owners=frozenset({A})),)
    with pytest.raises(DVAEREvidenceError, match="A0 order"):
        _input(
            blocks=blocks,
            candidates=(A,),
            followups={A: _followup(A)},
            a0_order=(),
        )


def test_unknown_owner_fails_closed() -> None:
    blocks = (_block(1, 0, owners=frozenset({A, B}), refcount=2),)
    with pytest.raises(DVAEREvidenceError, match="owner"):
        _input(blocks=blocks, candidates=(A,), followups={A: _followup(A)}, free_queue=())


def test_deterministic_selection() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({B})),
    )
    decision = _input(blocks=blocks, candidates=(A, B))
    strategy = DVAERStrategy()
    first = strategy.choose(decision)
    second = strategy.choose(decision)
    assert first == second


def test_decision_input_adapter() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({B})),
    )
    snapshot = SimpleNamespace(
        run_id="run",
        decision_event_index=4,
        timestamp=10.0,
        required_blocks=1,
        queue=(SimpleNamespace(block_id=1), SimpleNamespace(block_id=2)),
        candidate_keys=(A, B),
    )
    decision = build_decision_input(
        snapshot=snapshot,
        blocks=blocks,
        followups={A: _followup(A), B: _followup(B)},
        a0_order=(B, A),
    )
    assert decision.decision_id == "run:4"
    assert DVAERStrategy().choose(decision).selected == B


def test_dva_selection_changes_physical_victim_set_vs_a0() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A, B}), protected=frozenset({A})),
        _block(2, 1, owners=frozenset({B, C}), protected=frozenset({B})),
        _block(3, 2, owners=frozenset({C, A}), protected=frozenset({C})),
    )
    decision = _input(
        blocks=blocks,
        followups={
            A: _followup(A),
            B: _followup(B, active=True, gap=10.0),
            C: _followup(C),
        },
        a0_order=(A, B, C),
    )
    result = DVAERStrategy().choose(decision)
    a0_victims = decision.pool.victim_sequence_after(A, 1).victim_block_ids
    dva_victims = decision.pool.victim_sequence_after(result.selected, 1).victim_block_ids
    assert result.selected == B
    assert a0_victims == (1,)
    assert dva_victims == (2,)
    assert a0_victims != dva_victims


def test_future_fields_are_not_in_the_input_contract() -> None:
    fields = tuple(DVAERDecisionInput.__dataclass_fields__)
    assert not any("future" in field_name or "oracle" in field_name for field_name in fields)


def test_replay_strategy_adapter_uses_evidence_provider() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({B})),
    )
    decision = _input(blocks=blocks, candidates=(A, B), a0_order=(B, A))

    class Provider:
        def build(self, remaining: object, state: object) -> DVAERDecisionInput:
            del remaining, state
            return decision

    adapter = DVAERReplayStrategy(Provider())
    assert adapter.strategy_id == "DVA_ER_v1"
    assert adapter.pick_next((), object()) == B


def test_free_queue_position_must_equal_native_lru_rank() -> None:
    blocks = (_block(1, 1, owners=frozenset({A}), refcount=0),)
    with pytest.raises(DVAEREvidenceError, match="position"):
        NativePoolSnapshot(
            blocks=blocks,
            free_queue_order=(1,),
            candidate_keys=(A,),
        )


def test_a0_tie_break_uses_frozen_a0_strategy() -> None:
    blocks = (
        _block(1, 0, owners=frozenset({A})),
        _block(2, 1, owners=frozenset({B})),
    )
    rows = [
        SimpleNamespace(
            program_id=A[0],
            prefix_id=A[1],
            retention_deadline_timestamp=20.0,
        ),
        SimpleNamespace(
            program_id=B[0],
            prefix_id=B[1],
            retention_deadline_timestamp=10.0,
        ),
    ]

    class _State:
        snapshot = SimpleNamespace(ranking_by_block={})

        @staticmethod
        def newly_eligible_after(key: tuple[str, str]) -> tuple[int, ...]:
            del key
            return ()

    strategy = ExecutedP1BStrategy()
    remaining = list(rows)
    order: list[tuple[str, str]] = []
    while remaining:
        selected = strategy.pick_next(remaining, _State())
        order.append(selected)
        remaining = [row for row in remaining if (row.program_id, row.prefix_id) != selected]
    assert order == [B, A]
    decision = _input(
        blocks=blocks,
        candidates=(A, B),
        a0_order=tuple(order),
    )
    result = DVAERStrategy().choose(decision)
    assert result.selected == B
    assert result.a0_tiebreak_used is True


def test_prediction_matches_real_a0_eligibility_and_adapter() -> None:
    entry = RetentionEntryKey(ProgramIdentity("p1"), PrefixIdentity("a"))
    queue = (
        BlockEligibilitySnapshot(BlockIdentity(1), 0, True, EligibilityTier.TIER_1),
        BlockEligibilitySnapshot(BlockIdentity(2), 1, True, EligibilityTier.TIER_2),
        BlockEligibilitySnapshot(BlockIdentity(3), 2, True, None),
    )
    effect = PressureReleaseEffect(entry, (BlockIdentity(2),))
    preparation = EligibilityPreparation(
        required_blocks=2,
        original_free_queue=queue,
        ordinary_expired_entries=(),
        pressure_releases=(effect,),
        preparation_timestamp=10.0,
    )
    candidates = tuple(
        EvictionCandidate(
            block_id=block_id,
            ref_cnt=0,
            has_block_hash=True,
            lru_rank=block_id - 1,
        )
        for block_id in (1, 2, 3)
    )
    context = EvictionContext(
        required_blocks=2,
        free_blocks=3,
        total_blocks=3,
        timestamp=10.0,
    )
    actual = tuple(RetentionAwareLRUAdapter(preparation).select_victims(candidates, context))

    blocks = (
        _block(1, 0, refcount=0),
        _block(2, 1, owners=frozenset({A}), protected=frozenset({A}), refcount=0),
        _block(3, 2, owners=frozenset({B}), protected=frozenset({B}), refcount=0),
    )
    decision = _input(
        blocks=blocks,
        candidates=(A, B),
        required=2,
        free_queue=(1, 2, 3),
        followups={A: _followup(A), B: _followup(B)},
    )
    predicted = decision.pool.victim_sequence_after(A, 2)
    assert predicted.original_eligible_block_ids == (1,)
    assert predicted.newly_eligible_block_ids == (2,)
    assert predicted.virtual_eligible_order == (1, 2)
    assert predicted.physical_victim_block_ids == actual == (1, 2)


def test_observation_after_decision_fails_closed() -> None:
    blocks = (_block(1, 0, owners=frozenset({A})),)
    observation = FollowupObservation(
        candidate_key=A,
        chain_id="chain:a",
        active=False,
        observed_at_timestamp=11.0,
        chain_established_at_timestamp=5.0,
    )
    with pytest.raises(DVAEREvidenceError, match="observation is after"):
        _input(
            blocks=blocks,
            candidates=(A,),
            followups={A: observation},
        )


def test_chain_established_after_decision_fails_closed() -> None:
    blocks = (_block(1, 0, owners=frozenset({A})),)
    observation = FollowupObservation(
        candidate_key=A,
        chain_id="chain:a",
        active=False,
        observed_at_timestamp=11.0,
        chain_established_at_timestamp=11.0,
    )
    with pytest.raises(DVAEREvidenceError, match="established after"):
        _input(
            blocks=blocks,
            candidates=(A,),
            followups={A: observation},
        )


def test_future_arrival_source_is_rejected() -> None:
    with pytest.raises(DVAEREvidenceError, match="controller-armed"):
        FollowupObservation(
            candidate_key=A,
            chain_id="chain:a",
            active=True,
            pending_tool_gap_seconds=5.0,
            observed_at_timestamp=9.0,
            chain_established_at_timestamp=5.0,
            pending_tool_gap_source="FUTURE_TRACE_ARRIVAL",  # type: ignore[arg-type]
        )


def test_a1_a3_are_not_imported_by_dva_er() -> None:
    source = (ROOT / "src/kvopt/costaware/dva_er.py").read_text(encoding="utf-8")
    assert "from .a1_entry" not in source
    assert "from .a3_suffix" not in source
