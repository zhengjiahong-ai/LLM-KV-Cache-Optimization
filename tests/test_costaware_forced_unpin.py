from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from kvopt.continuum import (
    BlockIdentity,
    FakeClock,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionMode,
)
from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.continuum.retention import RetentionManager
from kvopt.continuum.snapshots import (
    RetentionEntrySnapshot,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.costaware import (
    CostAwareForcedUnpinCoordinator,
    ForcedUnpinConfig,
    estimate_conditional_return_probability,
    estimate_eviction_loss,
)
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration


def _ttl_input(
    *,
    prefix: str = "prefix-x",
    decision_timestamp: float = 0.0,
    next_tool_type: str | None = "search",
    global_samples: tuple[float, ...] = (),
    tool_samples: tuple[float, ...] = (),
    queue_delay: float = 0.0,
    prefill: float = 0.1,
) -> TTLInput:
    return TTLInput(
        program_id=ProgramIdentity("program-x"),
        request_id=RequestIdentity("request-x"),
        prefix_id=PrefixIdentity(prefix),
        decision_timestamp=decision_timestamp,
        next_tool_type=next_tool_type,
        global_server_gap_samples_seconds=global_samples,
        tool_server_gap_samples_seconds=tool_samples,
        queue_delay_t_seconds=queue_delay,
        eta=1.0,
        prefill_reload_seconds=prefill,
        default_ttl_seconds=5.0,
        server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=InputProvenance(InputSource.OBSERVED),
        prefill_reload_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
        default_ttl_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
    )


def _entry(
    *,
    prefix: str,
    ttl_seconds: float,
    block_ids: tuple[int, ...],
    prefill: float = 0.1,
    queue_delay: float = 0.0,
    global_samples: tuple[float, ...] = (),
    tool_samples: tuple[float, ...] = (),
    mode: TTLHistoryMode = TTLHistoryMode.COLD_START,
    decision_timestamp: float = 0.0,
    next_tool_type: str | None = "search",
) -> RetentionEntrySnapshot:
    ttl_input = _ttl_input(
        prefix=prefix,
        decision_timestamp=decision_timestamp,
        next_tool_type=next_tool_type,
        global_samples=global_samples,
        tool_samples=tool_samples,
        queue_delay=queue_delay,
        prefill=prefill,
    )
    reason = "insufficient global server gap history" if mode is TTLHistoryMode.COLD_START else None
    decision = TTLDecision(ttl_input, ttl_seconds, mode, reason)
    return RetentionEntrySnapshot(
        ttl_decision=decision,
        protected=True,
        waiting_followup=False,
        block_ids=tuple(BlockIdentity(block_id) for block_id in block_ids),
    )


@dataclass
class _Candidate:
    block_id: int
    has_block_hash: bool
    lru_rank: int


def _hashed_candidates(count: int) -> list[_Candidate]:
    return [_Candidate(index, True, index) for index in range(count)]


def _probability_entry(
    *,
    samples: tuple[float, ...],
    tool_samples: tuple[float, ...] = (),
    mode: TTLHistoryMode,
    ttl_seconds: float,
    timestamp: float,
) -> float:
    entry = _entry(
        prefix="prefix-p",
        ttl_seconds=ttl_seconds,
        block_ids=(1,),
        global_samples=samples,
        tool_samples=tool_samples,
        mode=mode,
    )
    return estimate_conditional_return_probability(entry, timestamp)


def test_conditional_probability_matches_hand_computed_cdf() -> None:
    probability = _probability_entry(
        samples=(2.0, 4.0, 6.0, 8.0),
        mode=TTLHistoryMode.GLOBAL,
        ttl_seconds=6.0,
        timestamp=3.0,
    )
    # F(3) = 0.25, F(6) = 0.75, survived = 0.75 -> (0.75 - 0.25) / 0.75.
    assert probability == pytest.approx(2.0 / 3.0)


def test_conditional_probability_zero_when_history_fully_elapsed() -> None:
    probability = _probability_entry(
        samples=(2.0, 3.0),
        mode=TTLHistoryMode.GLOBAL,
        ttl_seconds=8.0,
        timestamp=5.0,
    )
    assert probability == 0.0


def test_conditional_probability_zero_past_deadline() -> None:
    probability = _probability_entry(
        samples=(2.0, 4.0, 6.0, 8.0),
        mode=TTLHistoryMode.GLOBAL,
        ttl_seconds=6.0,
        timestamp=7.0,
    )
    assert probability == 0.0


def test_conditional_probability_full_uncertainty_without_history() -> None:
    probability = _probability_entry(
        samples=(),
        mode=TTLHistoryMode.COLD_START,
        ttl_seconds=6.0,
        timestamp=3.0,
    )
    assert probability == 1.0


def test_tool_specific_history_selected_for_tool_specific_decisions() -> None:
    probability = _probability_entry(
        samples=(1.0, 2.0),
        tool_samples=(4.0, 6.0),
        mode=TTLHistoryMode.TOOL_SPECIFIC,
        ttl_seconds=6.0,
        timestamp=2.0,
    )
    # Tool samples: F(2) = 0, F(6) = 1 -> 1.0; global samples would give 0.0.
    assert probability == 1.0


def test_eviction_loss_matches_formula() -> None:
    entry = _entry(
        prefix="prefix-s",
        ttl_seconds=6.0,
        block_ids=(1, 2, 3),
        prefill=0.4,
        queue_delay=0.2,
        global_samples=(2.0, 4.0, 6.0, 8.0),
        mode=TTLHistoryMode.GLOBAL,
    )
    # P(4s) = (F(6) - F(4)) / (1 - F(4)) = (0.75 - 0.5) / 0.5 = 0.5.
    loss = estimate_eviction_loss(entry, 4.0, ForcedUnpinConfig(1.0))
    assert loss == pytest.approx(0.5 * (0.4 + 0.2) / 3)


def test_eviction_loss_infinite_without_observed_blocks() -> None:
    entry = _entry(prefix="prefix-e", ttl_seconds=6.0, block_ids=())
    assert estimate_eviction_loss(entry, 1.0) == math.inf


def test_eviction_loss_ignores_queue_delay_with_zero_lambda() -> None:
    entry = _entry(
        prefix="prefix-l",
        ttl_seconds=6.0,
        block_ids=(1,),
        prefill=0.4,
        queue_delay=10.0,
    )
    loss = estimate_eviction_loss(entry, 1.0, ForcedUnpinConfig(0.0))
    assert loss == pytest.approx(0.4)


def test_eviction_loss_rejects_invalid_config() -> None:
    entry = _entry(prefix="prefix-v", ttl_seconds=6.0, block_ids=(1,))
    with pytest.raises(ValueError):
        ForcedUnpinConfig(-1.0)
    with pytest.raises(TypeError):
        estimate_eviction_loss(entry, 1.0, "not a config")  # type: ignore[arg-type]


def test_coordinator_releases_lowest_loss_instead_of_earliest_deadline() -> None:
    # A: earliest deadline but the expensive per-block prefix.
    entry_a = _entry(
        prefix="prefix-a",
        ttl_seconds=2.0,
        block_ids=(0, 1),
        prefill=1.0,
    )
    # B: latest deadline but nearly worthless per block.
    entry_b = _entry(
        prefix="prefix-b",
        ttl_seconds=20.0,
        block_ids=(2, 3, 4, 5, 6, 7),
        prefill=0.06,
    )
    entries = (entry_a, entry_b)

    baseline = RetentionAwareSelectionCoordinator().prepare(
        _hashed_candidates(8), entries, required_blocks=2, timestamp=1.0
    )
    ours = CostAwareForcedUnpinCoordinator().prepare(
        _hashed_candidates(8), entries, required_blocks=2, timestamp=1.0
    )
    assert [release.entry_key.prefix_id.canonical_value for release in baseline.pressure_releases] == [
        "prefix-a"
    ]
    assert [release.entry_key.prefix_id.canonical_value for release in ours.pressure_releases] == [
        "prefix-b"
    ]


def test_coordinator_breaks_score_ties_by_earliest_deadline() -> None:
    entry_a = _entry(
        prefix="prefix-a",
        ttl_seconds=2.0,
        block_ids=(0, 1),
        prefill=1.0,
    )
    entry_b = _entry(
        prefix="prefix-b",
        ttl_seconds=20.0,
        block_ids=(2, 3),
        prefill=1.0,
    )
    preparation = CostAwareForcedUnpinCoordinator().prepare(
        _hashed_candidates(4), (entry_a, entry_b), required_blocks=2, timestamp=1.0
    )
    assert [
        release.entry_key.prefix_id.canonical_value for release in preparation.pressure_releases
    ] == ["prefix-a"]


def test_zero_block_entry_is_released_last() -> None:
    entry_empty = _entry(prefix="prefix-empty", ttl_seconds=1.5, block_ids=())
    entry_a = _entry(
        prefix="prefix-a",
        ttl_seconds=2.0,
        block_ids=(0, 1),
        prefill=1.0,
    )
    entry_b = _entry(
        prefix="prefix-b",
        ttl_seconds=3.0,
        block_ids=(2, 3),
        prefill=1.0,
    )
    entries = (entry_empty, entry_a, entry_b)
    baseline = RetentionAwareSelectionCoordinator().prepare(
        _hashed_candidates(4), entries, required_blocks=2, timestamp=1.0
    )
    ours = CostAwareForcedUnpinCoordinator().prepare(
        _hashed_candidates(4), entries, required_blocks=2, timestamp=1.0
    )
    # The baseline wastes its first release on the block-less entry.
    assert [
        release.entry_key.prefix_id.canonical_value for release in baseline.pressure_releases
    ] == ["prefix-empty", "prefix-a"]
    assert [
        release.entry_key.prefix_id.canonical_value for release in ours.pressure_releases
    ] == ["prefix-a"]


def _retention_manager_with_entries(
    *entries: RetentionEntrySnapshot,
) -> RetentionManager:
    manager = RetentionManager(FakeClock())
    for entry in entries:
        manager.upsert(entry)
    return manager


@dataclass
class _Block:
    block_id: int
    block_hash: object | None
    ref_cnt: int = 0


def _integration_blocks() -> tuple[_Block, ...]:
    return tuple(_Block(index, object()) for index in range(8))


def _reject_remove(_block_ids: tuple[int, ...]) -> None:
    raise AssertionError("shadow integration must not remove blocks")


def test_integration_injection_swaps_release_victim() -> None:
    entry_a = _entry(
        prefix="prefix-a",
        ttl_seconds=2.0,
        block_ids=(0, 1),
        prefill=1.0,
    )
    entry_b = _entry(
        prefix="prefix-b",
        ttl_seconds=20.0,
        block_ids=(2, 3, 4, 5, 6, 7),
        prefill=0.06,
    )
    manager = _retention_manager_with_entries(entry_a, entry_b)

    baseline_result = RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.SHADOW,
        blocks=_integration_blocks(),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=_reject_remove,
    )
    cost_aware_result = RetentionRuntimeIntegration(
        manager, CostAwareForcedUnpinCoordinator()
    ).apply_pressure(
        mode=RetentionMode.SHADOW,
        blocks=_integration_blocks(),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=_reject_remove,
    )

    assert baseline_result.selection_plan is not None
    assert cost_aware_result.selection_plan is not None
    assert [
        release.entry_key.prefix_id.canonical_value
        for release in baseline_result.selection_plan.preparation.pressure_releases
    ] == ["prefix-a"]
    assert [
        release.entry_key.prefix_id.canonical_value
        for release in cost_aware_result.selection_plan.preparation.pressure_releases
    ] == ["prefix-b"]
    # Both plans stay valid: selection follows the virtual tier/LRU order.
    assert baseline_result.selected_block_ids == (0, 1)
    assert cost_aware_result.selected_block_ids == (2, 3)


def test_integration_rejects_invalid_coordinator() -> None:
    manager = _retention_manager_with_entries(
        _entry(prefix="prefix-a", ttl_seconds=2.0, block_ids=(0,))
    )
    with pytest.raises(TypeError):
        RetentionRuntimeIntegration(manager, object())


def test_marginal_denominator_is_rejected_by_co_protection() -> None:
    # A is alone on its blocks; B shares every block with C, so releasing B
    # alone frees nothing while the B+C pair releases the shared blocks.
    entry_a = _entry(
        prefix="prefix-a",
        ttl_seconds=2.0,
        block_ids=(0, 1),
        prefill=1.0,
    )
    entry_b = _entry(
        prefix="prefix-b",
        ttl_seconds=20.0,
        block_ids=(2, 3),
        prefill=0.1,
    )
    entry_c = _entry(
        prefix="prefix-c",
        ttl_seconds=30.0,
        block_ids=(2, 3),
        prefill=0.1,
    )
    entries = (entry_a, entry_b, entry_c)
    candidates = _hashed_candidates(4)

    total_denominator = CostAwareForcedUnpinCoordinator(
        ForcedUnpinConfig(0.0, marginal_block_denominator=False)
    ).prepare(candidates, entries, required_blocks=2, timestamp=1.0)
    marginal_denominator = CostAwareForcedUnpinCoordinator(
        ForcedUnpinConfig(0.0, marginal_block_denominator=True)
    ).prepare(candidates, entries, required_blocks=2, timestamp=1.0)

    # The total-block form sequences the two cheap co-owner releases and
    # frees the shared blocks at a combined loss of ~0.2 s.
    assert [
        release.entry_key.prefix_id.canonical_value
        for release in total_denominator.pressure_releases
    ] == ["prefix-b", "prefix-c"]
    # The marginal form refuses to release a co-protected entry at all and
    # falls back to the expensive single-owner entry (~1.0 s loss) instead.
    assert [
        release.entry_key.prefix_id.canonical_value
        for release in marginal_denominator.pressure_releases
    ] == ["prefix-a"]


def test_forced_unpin_config_validates_denominator_flag() -> None:
    with pytest.raises(TypeError):
        ForcedUnpinConfig(1.0, "yes")  # type: ignore[arg-type]
