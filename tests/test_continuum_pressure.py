import pytest

from kvopt.continuum import (
    BlockIdentity,
    EligibilityPreparation,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    PressureReleaseEffect,
    ProgramIdentity,
    RequestIdentity,
    RetentionEntryKey,
    RetentionEntrySnapshot,
    SelectionPlan,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.runtime.vllm.adapter import NativeLRUAdapter, RetentionAwareLRUAdapter
from kvopt.runtime.vllm.types import EvictionCandidate, EvictionContext


def _candidate(
    block_id: int,
    rank: int,
    *,
    has_block_hash: bool = True,
) -> EvictionCandidate:
    return EvictionCandidate(
        block_id=block_id,
        ref_cnt=0,
        has_block_hash=has_block_hash,
        lru_rank=rank,
    )


def _entry(
    program: str,
    prefix: str,
    block_ids: tuple[int, ...],
    *,
    deadline: float = 10.0,
    protected: bool = True,
    waiting_followup: bool = False,
) -> RetentionEntrySnapshot:
    program_id = ProgramIdentity(program)
    prefix_id = PrefixIdentity(prefix)
    ttl_input = TTLInput(
        program_id=program_id,
        request_id=RequestIdentity(f"request-{program}-{prefix}"),
        prefix_id=prefix_id,
        decision_timestamp=0.0,
        next_tool_type=None,
        global_server_gap_samples_seconds=(),
        tool_server_gap_samples_seconds=(),
        queue_delay_t_seconds=0.0,
        eta=1.0,
        prefill_reload_seconds=1.0,
        default_ttl_seconds=deadline,
        server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test eta"
        ),
        prefill_reload_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test prefill"
        ),
        default_ttl_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test default"
        ),
    )
    decision = TTLDecision(
        ttl_input=ttl_input,
        ttl_seconds=deadline,
        history_mode=TTLHistoryMode.COLD_START,
        reason="test cold start",
    )
    return RetentionEntrySnapshot(
        ttl_decision=decision,
        protected=protected,
        waiting_followup=waiting_followup,
        block_ids=tuple(BlockIdentity(block_id) for block_id in block_ids),
    )


def _key(entry: RetentionEntrySnapshot) -> RetentionEntryKey:
    return RetentionEntryKey(entry.program_id, entry.prefix_id)


def _select_block_ids(
    preparation: EligibilityPreparation,
    candidates: list[EvictionCandidate],
    required_blocks: int,
) -> tuple[int, ...]:
    context = EvictionContext(
        required_blocks=required_blocks,
        free_blocks=len(candidates),
        total_blocks=len(candidates),
        timestamp=1.0,
    )
    return tuple(
        RetentionAwareLRUAdapter(preparation).select_victims(candidates, context)
    )


def test_coordinator_preserves_complete_native_queue_and_ranks() -> None:
    queue = [
        _candidate(7, 0),
        _candidate(8, 1, has_block_hash=False),
        _candidate(9, 2),
    ]

    preparation = RetentionAwareSelectionCoordinator().prepare(
        queue,
        (),
        required_blocks=2,
        timestamp=1.0,
    )

    assert preparation.original_block_order == (
        BlockIdentity(7),
        BlockIdentity(8),
        BlockIdentity(9),
    )
    assert tuple(
        candidate.native_lru_rank
        for candidate in preparation.original_free_queue
    ) == (0, 1, 2)


def test_protected_head_does_not_block_later_unhashed_free_block() -> None:
    protected_entry = _entry("program-a", "prefix-a", (7,))
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0), _candidate(8, 1, has_block_hash=False)],
        (protected_entry,),
        required_blocks=1,
        timestamp=1.0,
    )
    assert preparation.still_protected_block_ids == (BlockIdentity(7),)
    assert _select_block_ids(
        preparation,
        [_candidate(7, 0), _candidate(8, 1, has_block_hash=False)],
        1,
    ) == (8,)


def test_no_protected_block_matches_native_lru_selection() -> None:
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(20, 0), _candidate(21, 1), _candidate(22, 2)],
        (),
        required_blocks=2,
        timestamp=1.0,
    )
    candidates = [_candidate(20, 0), _candidate(21, 1), _candidate(22, 2)]
    context = EvictionContext(
        required_blocks=2,
        free_blocks=3,
        total_blocks=3,
        timestamp=1.0,
    )
    native_ids = NativeLRUAdapter().select_victims(candidates, context)
    retention_ids = RetentionAwareLRUAdapter(preparation).select_victims(
        candidates, context
    )

    assert retention_ids == native_ids


def test_tier_priority_changes_order_without_rewriting_native_rank() -> None:
    entry = _entry("program-a", "prefix-a", (7,))
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0), _candidate(8, 1, has_block_hash=False)],
        (entry,),
        required_blocks=2,
        timestamp=1.0,
    )

    # The protected entry is released only for the unsatisfied target.
    assert preparation.pressure_releases == (
        PressureReleaseEffect(_key(entry), (BlockIdentity(7),)),
    )
    assert preparation.virtual_eligible_order == (
        BlockIdentity(8),
        BlockIdentity(7),
    )
    assert preparation.original_free_queue[0].native_lru_rank == 0
    assert preparation.original_free_queue[1].native_lru_rank == 1
    assert _select_block_ids(
        preparation,
        [_candidate(7, 0), _candidate(8, 1, has_block_hash=False)],
        2,
    ) == (8, 7)


def test_pressure_release_order_uses_earlier_deadline_first() -> None:
    later_deadline = _entry("program-a", "prefix-a", (8,), deadline=5.0)
    earlier_deadline = _entry("program-b", "prefix-b", (7,), deadline=4.0)
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0), _candidate(8, 1), _candidate(9, 2, has_block_hash=False)],
        (later_deadline, earlier_deadline),
        required_blocks=3,
        timestamp=1.0,
    )

    assert tuple(
        release.entry_key for release in preparation.pressure_releases
    ) == (_key(earlier_deadline), _key(later_deadline))


def test_pressure_release_order_uses_native_rank_for_equal_deadlines() -> None:
    rank_one_entry = _entry("program-a", "prefix-a", (8,), deadline=5.0)
    rank_zero_entry = _entry("program-b", "prefix-b", (7,), deadline=5.0)
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0), _candidate(8, 1), _candidate(9, 2, has_block_hash=False)],
        (rank_one_entry, rank_zero_entry),
        required_blocks=3,
        timestamp=1.0,
    )

    assert tuple(
        release.entry_key for release in preparation.pressure_releases
    ) == (_key(rank_zero_entry), _key(rank_one_entry))


def test_shared_block_release_has_zero_marginal_effect_until_last_owner() -> None:
    first = _entry("program-a", "prefix-a", (7,), deadline=5.0)
    second = _entry("program-b", "prefix-b", (7,), deadline=5.0)
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0), _candidate(8, 1, has_block_hash=False)],
        (second, first),
        required_blocks=2,
        timestamp=1.0,
    )

    assert preparation.pressure_releases == (
        PressureReleaseEffect(_key(first), ()),
        PressureReleaseEffect(_key(second), (BlockIdentity(7),)),
    )


def test_expired_entry_is_ordinary_tier_one_without_pressure_release() -> None:
    expired = _entry("program-a", "prefix-a", (7,), deadline=5.0)
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0)],
        (expired,),
        required_blocks=1,
        timestamp=5.0,
    )

    assert preparation.ordinary_expired_entries == (_key(expired),)
    assert preparation.tier_1_block_ids == (BlockIdentity(7),)
    assert preparation.pressure_releases == ()


def test_waiting_followup_is_not_ordinary_expiry_but_can_be_released_under_pressure() -> None:
    waiting = _entry(
        "program-a",
        "prefix-a",
        (7,),
        deadline=5.0,
        waiting_followup=True,
    )
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0)],
        (waiting,),
        required_blocks=1,
        timestamp=5.0,
    )

    assert preparation.ordinary_expired_entries == ()
    assert preparation.pressure_releases == (
        PressureReleaseEffect(_key(waiting), (BlockIdentity(7),)),
    )


def test_selection_plan_rejects_output_that_does_not_follow_virtual_order() -> None:
    entry = _entry("program-a", "prefix-a", (7,))
    preparation = RetentionAwareSelectionCoordinator().prepare(
        [_candidate(7, 0), _candidate(8, 1, has_block_hash=False)],
        (entry,),
        required_blocks=2,
        timestamp=1.0,
    )
    with pytest.raises(ValueError, match="eligibility_tier"):
        SelectionPlan(
            preparation,
            "RetentionAwareLRUAdapter",
            [BlockIdentity(7), BlockIdentity(8)],
        )
