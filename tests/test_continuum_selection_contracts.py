import math
from dataclasses import FrozenInstanceError

import pytest

from kvopt.continuum import (
    BlockEligibilitySnapshot,
    BlockIdentity,
    EligibilityPreparation,
    EligibilityTier,
    PrefixIdentity,
    PressureReleaseEffect,
    ProgramIdentity,
    RetentionEntryKey,
    SelectionPlan,
)

PROGRAM_ID = ProgramIdentity("program-1")
PREFIX_ID = PrefixIdentity("prefix-1")
ENTRY_KEY = RetentionEntryKey(PROGRAM_ID, PREFIX_ID)


def _block(
    block_id: int,
    native_lru_rank: int,
    *,
    has_block_hash: bool = True,
    eligibility_tier: EligibilityTier | None = EligibilityTier.TIER_1,
) -> BlockEligibilitySnapshot:
    return BlockEligibilitySnapshot(
        BlockIdentity(block_id),
        native_lru_rank,
        has_block_hash,
        eligibility_tier,
    )


def _preparation(**overrides) -> EligibilityPreparation:
    values = {
        "required_blocks": 1,
        "original_free_queue": [_block(10, 0), _block(11, 1)],
        "ordinary_expired_entries": [],
        "pressure_releases": [],
        "preparation_timestamp": 1.0,
    }
    values.update(overrides)
    return EligibilityPreparation(**values)


def test_tier_values_are_the_explicit_virtual_order_contract() -> None:
    assert EligibilityTier.TIER_1 == 0
    assert EligibilityTier.TIER_2 == 1


def test_retention_entry_key_exposes_stable_lexical_tie_break() -> None:
    keys = [
        RetentionEntryKey(ProgramIdentity("program-b"), PrefixIdentity("prefix-a")),
        RetentionEntryKey(ProgramIdentity("program-a"), PrefixIdentity("prefix-b")),
        RetentionEntryKey(ProgramIdentity("program-a"), PrefixIdentity("prefix-a")),
    ]

    ordered = sorted(keys, key=lambda key: key.sort_key)

    assert [key.sort_key for key in ordered] == [
        ("program-a", "prefix-a"),
        ("program-a", "prefix-b"),
        ("program-b", "prefix-a"),
    ]


def test_block_snapshot_keeps_native_rank_separate_from_tier() -> None:
    block = _block(10, 0, eligibility_tier=EligibilityTier.TIER_2)

    assert block.native_lru_rank == 0
    assert block.eligibility_tier is EligibilityTier.TIER_2
    assert block.selection_key == (1, 0)


def test_unhashed_free_block_must_remain_eligible_in_tier_1() -> None:
    with pytest.raises(ValueError, match="unhashed free block must be eligible"):
        _block(10, 0, has_block_hash=False, eligibility_tier=None)
    with pytest.raises(ValueError, match="must remain in Tier 1"):
        _block(
            10,
            0,
            has_block_hash=False,
            eligibility_tier=EligibilityTier.TIER_2,
        )


def test_protected_cached_head_does_not_block_later_unhashed_free_block() -> None:
    protected = _block(10, 0, eligibility_tier=None)
    unhashed = _block(11, 1, has_block_hash=False)
    preparation = _preparation(
        original_free_queue=[protected, unhashed],
        required_blocks=1,
    )
    plan = SelectionPlan(preparation, "RetentionAwareLRUAdapter", [BlockIdentity(11)])

    assert preparation.original_block_order == (BlockIdentity(10), BlockIdentity(11))
    assert protected.native_lru_rank == 0
    assert unhashed.native_lru_rank == 1
    assert preparation.tier_1_block_ids == (BlockIdentity(11),)
    assert preparation.still_protected_block_ids == (BlockIdentity(10),)
    assert plan.selected_block_ids == (BlockIdentity(11),)


def test_tier_priority_changes_virtual_order_without_changing_native_ranks() -> None:
    tier_2_head = _block(10, 0, eligibility_tier=EligibilityTier.TIER_2)
    tier_1_later = _block(11, 1)
    release = PressureReleaseEffect(ENTRY_KEY, [BlockIdentity(10)])
    preparation = _preparation(
        original_free_queue=[tier_2_head, tier_1_later],
        required_blocks=2,
        pressure_releases=[release],
    )

    assert preparation.virtual_eligible_order == (BlockIdentity(11), BlockIdentity(10))
    assert tier_2_head.native_lru_rank == 0
    assert tier_1_later.native_lru_rank == 1


def test_no_protection_virtual_order_is_native_lru_order() -> None:
    queue = [_block(20, 0), _block(21, 1), _block(22, 2, has_block_hash=False)]
    preparation = _preparation(original_free_queue=queue, required_blocks=2)
    plan = SelectionPlan(
        preparation,
        "RetentionAwareLRUAdapter",
        [BlockIdentity(20), BlockIdentity(21)],
    )

    assert preparation.virtual_eligible_order == preparation.original_block_order
    assert plan.selected_block_ids == (BlockIdentity(20), BlockIdentity(21))


def test_native_ranks_must_match_complete_original_queue_positions() -> None:
    with pytest.raises(ValueError, match="complete original free queue"):
        _preparation(original_free_queue=[_block(10, 1), _block(11, 0)])
    with pytest.raises(ValueError, match="complete original free queue"):
        _preparation(original_free_queue=[_block(10, 0), _block(11, 2)])


def test_preparation_rejects_duplicate_block_ids() -> None:
    with pytest.raises(ValueError, match="duplicate block IDs"):
        _preparation(original_free_queue=[_block(10, 0), _block(10, 1)])


def test_pressure_effects_exactly_explain_tier_2_blocks() -> None:
    tier_2 = _block(10, 0, eligibility_tier=EligibilityTier.TIER_2)
    tier_1 = _block(11, 1)

    with pytest.raises(ValueError, match="exactly explain"):
        _preparation(
            required_blocks=2,
            original_free_queue=[tier_2, tier_1],
            pressure_releases=[],
        )
    with pytest.raises(ValueError, match="exactly explain"):
        _preparation(
            required_blocks=2,
            original_free_queue=[tier_2, tier_1],
            pressure_releases=[
                PressureReleaseEffect(ENTRY_KEY, [BlockIdentity(12)])
            ],
        )


def test_zero_marginal_release_is_allowed_but_does_not_satisfy_target() -> None:
    other_entry = RetentionEntryKey(PROGRAM_ID, PrefixIdentity("prefix-2"))
    tier_2 = _block(10, 0, eligibility_tier=EligibilityTier.TIER_2)
    tier_1 = _block(11, 1)
    preparation = _preparation(
        required_blocks=2,
        original_free_queue=[tier_2, tier_1],
        pressure_releases=[
            PressureReleaseEffect(ENTRY_KEY, []),
            PressureReleaseEffect(other_entry, [BlockIdentity(10)]),
        ],
    )

    assert preparation.pressure_releases[0].newly_eligible_block_ids == ()
    assert preparation.tier_2_block_ids == (BlockIdentity(10),)


def test_pressure_release_is_forbidden_when_tier_1_is_sufficient() -> None:
    release = PressureReleaseEffect(ENTRY_KEY, [BlockIdentity(10)])
    with pytest.raises(ValueError, match="target is satisfied"):
        _preparation(
            required_blocks=1,
            original_free_queue=[
                _block(10, 0, eligibility_tier=EligibilityTier.TIER_2),
                _block(11, 1),
            ],
            pressure_releases=[release],
        )


def test_pressure_releases_stop_after_the_target_is_satisfied() -> None:
    second_entry = RetentionEntryKey(PROGRAM_ID, PrefixIdentity("prefix-2"))
    with pytest.raises(ValueError, match="target is satisfied"):
        _preparation(
            required_blocks=2,
            original_free_queue=[
                _block(10, 0, eligibility_tier=EligibilityTier.TIER_2),
                _block(11, 1),
                _block(12, 2, eligibility_tier=EligibilityTier.TIER_2),
            ],
            pressure_releases=[
                PressureReleaseEffect(ENTRY_KEY, [BlockIdentity(10)]),
                PressureReleaseEffect(second_entry, [BlockIdentity(12)]),
            ],
        )


def test_one_indivisible_release_may_exceed_the_remaining_target() -> None:
    preparation = _preparation(
        required_blocks=2,
        original_free_queue=[
            _block(10, 0, eligibility_tier=EligibilityTier.TIER_2),
            _block(11, 1),
            _block(12, 2, eligibility_tier=EligibilityTier.TIER_2),
        ],
        pressure_releases=[
            PressureReleaseEffect(
                ENTRY_KEY,
                [BlockIdentity(10), BlockIdentity(12)],
            )
        ],
    )

    assert preparation.virtual_eligible_order == (
        BlockIdentity(11),
        BlockIdentity(10),
        BlockIdentity(12),
    )


def test_preparation_rejects_insufficient_eligibility_when_blocks_exist() -> None:
    with pytest.raises(ValueError, match="cannot satisfy"):
        _preparation(
            required_blocks=2,
            original_free_queue=[
                _block(10, 0),
                _block(11, 1, eligibility_tier=None),
            ],
        )


def test_expiry_and_pressure_entry_sets_are_unique_and_disjoint() -> None:
    release = PressureReleaseEffect(ENTRY_KEY, [])
    with pytest.raises(ValueError, match="both ordinarily expired"):
        _preparation(
            ordinary_expired_entries=[ENTRY_KEY],
            pressure_releases=[release],
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        _preparation(ordinary_expired_entries=[ENTRY_KEY, ENTRY_KEY])
    with pytest.raises(ValueError, match="repeat an entry key"):
        _preparation(
            pressure_releases=[
                release,
                PressureReleaseEffect(ENTRY_KEY, [BlockIdentity(11)]),
            ]
        )


def test_selection_plan_rejects_unknown_protected_duplicate_or_reordered_output() -> None:
    preparation = _preparation(required_blocks=1)

    with pytest.raises(ValueError, match="must follow"):
        SelectionPlan(preparation, "adapter", [BlockIdentity(99)])
    with pytest.raises(ValueError, match="must follow"):
        SelectionPlan(preparation, "adapter", [BlockIdentity(11)])
    with pytest.raises(ValueError, match="duplicates"):
        SelectionPlan(preparation, "adapter", [BlockIdentity(10), BlockIdentity(10)])


def test_selection_plan_rejects_too_few_victims() -> None:
    preparation = _preparation(required_blocks=2)

    with pytest.raises(ValueError, match="too few"):
        SelectionPlan(preparation, "adapter", [BlockIdentity(10)])


@pytest.mark.parametrize("invalid", [-1, True, 1.0])
def test_preparation_rejects_invalid_required_blocks(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        _preparation(required_blocks=invalid)


@pytest.mark.parametrize("invalid", [-1.0, math.inf, math.nan, True, "1"])
def test_preparation_rejects_invalid_timestamp(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        _preparation(preparation_timestamp=invalid)


def test_selection_contracts_defensively_freeze_inputs() -> None:
    queue = [_block(10, 0)]
    expired = [ENTRY_KEY]
    preparation = _preparation(
        original_free_queue=queue,
        ordinary_expired_entries=expired,
    )
    selected = [BlockIdentity(10)]
    plan = SelectionPlan(preparation, "adapter", selected)
    queue.append(_block(11, 1))
    expired.clear()
    selected.clear()

    assert preparation.original_block_order == (BlockIdentity(10),)
    assert preparation.ordinary_expired_entries == (ENTRY_KEY,)
    assert plan.selected_block_ids == (BlockIdentity(10),)
    with pytest.raises(FrozenInstanceError):
        plan.adapter_identity = "changed"
