from dataclasses import dataclass

import pytest

from kvopt.continuum import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionEntryKey,
    RetentionEntrySnapshot,
    RetentionMode,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.continuum.clock import FakeClock
from kvopt.continuum.retention import RetentionManager
from kvopt.runtime.vllm.adapter import RetentionAwareLRUAdapter
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration


@dataclass(frozen=True, slots=True)
class _NativeBlock:
    block_id: int
    ref_cnt: int = 0
    block_hash: object | None = object()


def _block(block_id: int, *, hashed: bool = True) -> _NativeBlock:
    return _NativeBlock(block_id, block_hash=object() if hashed else None)


def _entry(
    program: str,
    prefix: str,
    block_ids: tuple[int, ...],
    *,
    protected: bool = True,
    deadline: float = 10.0,
) -> RetentionEntrySnapshot:
    program_id = ProgramIdentity(program)
    prefix_id = PrefixIdentity(prefix)
    ttl_input = TTLInput(
        program_id=program_id,
        request_id=RequestIdentity(f"request-{program}-{prefix}"),
        prefix_id=prefix_id,
        decision_timestamp=0.0,
        next_tool_type="search",
        global_server_gap_samples_seconds=(2.0,),
        tool_server_gap_samples_seconds=(2.0,),
        queue_delay_t_seconds=0.0,
        eta=1.0,
        prefill_reload_seconds=1.0,
        default_ttl_seconds=deadline,
        server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=InputProvenance(InputSource.OBSERVED),
        prefill_reload_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test profile"
        ),
        default_ttl_provenance=InputProvenance(
            InputSource.APPROXIMATED, "test default"
        ),
    )
    return RetentionEntrySnapshot(
        ttl_decision=TTLDecision(
            ttl_input=ttl_input,
            ttl_seconds=deadline,
            history_mode=TTLHistoryMode.GLOBAL,
        ),
        protected=protected,
        waiting_followup=False,
        block_ids=tuple(BlockIdentity(block_id) for block_id in block_ids),
    )


def _key(entry: RetentionEntrySnapshot) -> RetentionEntryKey:
    return RetentionEntryKey(entry.program_id, entry.prefix_id)


def test_native_mode_leaves_retention_unchanged_and_uses_native_callback() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    result = RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.NATIVE,
        blocks=(_block(7), _block(8, hashed=False)),
        required_blocks=1,
        timestamp=1.0,
        remove_selected=lambda ids: removed.append(tuple(ids)),
    )

    assert result.selected_block_ids == (7,)
    assert result.selection_plan is None
    assert manager.snapshot(_key(entry)).protected is True
    assert removed == [(7,)]


def test_shadow_keeps_hypothetical_release_out_of_live_state() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    result = RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.SHADOW,
        blocks=(_block(7), _block(8, hashed=False)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda ids: removed.append(tuple(ids)),
    )

    assert result.selection_plan is not None
    assert result.selection_plan.preparation.pressure_releases
    assert manager.snapshot(_key(entry)).protected is True
    assert manager.is_block_protected(BlockIdentity(7)) is True
    assert removed == []


def test_controlled_commits_release_and_passes_final_validated_ids() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    result = RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_block(7), _block(8, hashed=False)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda ids: removed.append(tuple(ids)),
    )

    assert result.selected_block_ids == (8, 7)
    assert removed == [(8, 7)]
    assert manager.snapshot(_key(entry)).protected is False
    assert result.selection_plan.selected_block_ids == (BlockIdentity(8), BlockIdentity(7))


def test_shadow_plans_ordinary_expiry_without_committing_live_state() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,), deadline=5.0)
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    result = RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.SHADOW,
        blocks=(_block(7),),
        required_blocks=1,
        timestamp=5.0,
        remove_selected=lambda ids: removed.append(tuple(ids)),
    )

    assert result.selection_plan is not None
    assert result.selection_plan.preparation.ordinary_expired_entries == (_key(entry),)
    assert manager.snapshot(_key(entry)).protected is True
    assert removed == []


def test_controlled_commits_ordinary_expiry_before_native_removal() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,), deadline=5.0)
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    result = RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_block(7),),
        required_blocks=1,
        timestamp=5.0,
        remove_selected=lambda ids: removed.append(tuple(ids)),
    )

    assert result.selection_plan is not None
    assert result.selection_plan.preparation.ordinary_expired_entries == (_key(entry),)
    assert manager.snapshot(_key(entry)).protected is False
    assert removed == [(7,)]


def test_controlled_validation_failure_does_not_commit_or_remove(monkeypatch) -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,), deadline=5.0)
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    def invalid_selection(self, candidates, context):
        return [7, 999]

    monkeypatch.setattr(RetentionAwareLRUAdapter, "select_victims", invalid_selection)

    with pytest.raises(ValueError, match="non-candidate"):
        RetentionRuntimeIntegration(manager).apply_pressure(
            mode=RetentionMode.CONTROLLED,
            blocks=(_block(7), _block(8, hashed=False)),
            required_blocks=2,
            timestamp=5.0,
            remove_selected=lambda ids: removed.append(tuple(ids)),
        )

    assert manager.snapshot(_key(entry)).protected is True
    assert removed == []


def test_selection_plan_failure_does_not_commit_or_remove(monkeypatch) -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)
    removed: list[tuple[int, ...]] = []

    def wrong_order_selection(self, candidates, context):
        return [7, 8]

    monkeypatch.setattr(RetentionAwareLRUAdapter, "select_victims", wrong_order_selection)

    with pytest.raises(ValueError, match="eligibility_tier"):
        RetentionRuntimeIntegration(manager).apply_pressure(
            mode=RetentionMode.CONTROLLED,
            blocks=(_block(7), _block(8, hashed=False)),
            required_blocks=2,
            timestamp=1.0,
            remove_selected=lambda ids: removed.append(tuple(ids)),
        )

    assert manager.snapshot(_key(entry)).protected is True
    assert removed == []


def test_controlled_order_is_validate_then_commit_then_remove(monkeypatch) -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)
    calls: list[str] = []
    original_commit = manager.commit_pressure_releases

    def commit(keys) -> None:
        calls.append("commit")
        original_commit(keys)

    monkeypatch.setattr(manager, "commit_pressure_releases", commit)

    def remove_selected(ids) -> None:
        calls.append("remove")

    RetentionRuntimeIntegration(manager).apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_block(7), _block(8, hashed=False)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=remove_selected,
    )

    assert calls == ["commit", "remove"]


def test_native_removal_failure_propagates_without_logical_rollback() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)

    class RemovalFailure(RuntimeError):
        pass

    failure = RemovalFailure("native removal failed")

    def remove_selected(ids) -> None:
        raise failure

    with pytest.raises(RemovalFailure) as raised:
        RetentionRuntimeIntegration(manager).apply_pressure(
            mode=RetentionMode.CONTROLLED,
            blocks=(_block(7), _block(8, hashed=False)),
            required_blocks=2,
            timestamp=1.0,
            remove_selected=remove_selected,
        )

    assert raised.value is failure
    assert manager.snapshot(_key(entry)).protected is False


def test_native_removal_failure_does_not_create_eviction_observation() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7,))
    manager.upsert(entry)

    def remove_selected(ids) -> None:
        raise RuntimeError("native removal failed")

    with pytest.raises(RuntimeError, match="native removal failed"):
        RetentionRuntimeIntegration(manager).apply_pressure(
            mode=RetentionMode.CONTROLLED,
            blocks=(_block(7), _block(8, hashed=False)),
            required_blocks=2,
            timestamp=1.0,
            remove_selected=remove_selected,
        )

    key = _key(entry)
    assert manager.snapshot(key).block_ids == (BlockIdentity(7),)
    assert manager.entries_for_block(BlockIdentity(7)) == (key,)


def test_observed_native_eviction_removes_only_stale_physical_edge() -> None:
    manager = RetentionManager(FakeClock())
    entry = _entry("program-a", "prefix-a", (7, 8))
    manager.upsert(entry)

    RetentionRuntimeIntegration(manager).observe_native_eviction(BlockIdentity(7))

    key = _key(entry)
    assert manager.snapshot(key).block_ids == (BlockIdentity(8),)
    assert manager.entries_for_block(BlockIdentity(7)) == ()
    assert manager.entries_for_block(BlockIdentity(8)) == (key,)


def test_pressure_release_preserves_any_protected_shared_block() -> None:
    manager = RetentionManager(FakeClock())
    first = _entry("program-a", "prefix-a", (7,))
    second = _entry("program-b", "prefix-b", (7,))
    manager.upsert(first)
    manager.upsert(second)

    manager.commit_pressure_releases((_key(first),))

    assert manager.snapshot(_key(first)).protected is False
    assert manager.snapshot(_key(second)).protected is True
    assert manager.is_block_protected(BlockIdentity(7)) is True
