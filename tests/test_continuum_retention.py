import pytest

from kvopt.continuum.clock import FakeClock
from kvopt.continuum.retention import RetentionManager
from kvopt.continuum.selection import RetentionEntryKey
from kvopt.continuum.snapshots import (
    RetentionEntrySnapshot,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.continuum.types import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)

OBSERVED = InputProvenance(InputSource.OBSERVED)
APPROXIMATED = InputProvenance(InputSource.APPROXIMATED, "test profile")


def _entry(
    program: str,
    prefix: str,
    block_ids: tuple[int, ...],
    ttl_seconds: float = 5.0,
    *,
    protected: bool = True,
    waiting_followup: bool = False,
) -> RetentionEntrySnapshot:
    program_id = ProgramIdentity(program)
    ttl_input = TTLInput(
        program_id=program_id,
        request_id=RequestIdentity(f"request-{program}-{prefix}"),
        prefix_id=PrefixIdentity(prefix),
        decision_timestamp=0.0,
        next_tool_type="search",
        global_server_gap_samples_seconds=(2.0,),
        tool_server_gap_samples_seconds=(2.0,),
        queue_delay_t_seconds=0.0,
        eta=1.0,
        prefill_reload_seconds=1.0,
        default_ttl_seconds=ttl_seconds,
        server_gap_history_provenance=OBSERVED,
        queue_delay_provenance=OBSERVED,
        eta_provenance=OBSERVED,
        prefill_reload_provenance=APPROXIMATED,
        default_ttl_provenance=APPROXIMATED,
    )
    decision = TTLDecision(ttl_input, ttl_seconds, TTLHistoryMode.GLOBAL)
    return RetentionEntrySnapshot(
        decision,
        protected=protected,
        waiting_followup=waiting_followup,
        block_ids=tuple(BlockIdentity(block_id) for block_id in block_ids),
    )


def _key(program: str, prefix: str) -> RetentionEntryKey:
    return RetentionEntryKey(ProgramIdentity(program), PrefixIdentity(prefix))


def test_retention_manager_tracks_logical_ownership_and_reverse_associations() -> None:
    manager = RetentionManager(FakeClock())
    snapshot = _entry("program-a", "prefix-a", (7, 8))
    key = _key("program-a", "prefix-a")

    manager.upsert(snapshot)

    assert manager.snapshot(key) == snapshot
    assert manager.entries_for_block(BlockIdentity(7)) == (key,)
    assert manager.entries_for_block(BlockIdentity(8)) == (key,)


def test_upsert_replaces_stale_reverse_associations_for_same_entry() -> None:
    manager = RetentionManager(FakeClock())
    key = _key("program-a", "prefix-a")

    manager.upsert(_entry("program-a", "prefix-a", (7, 8)))
    manager.upsert(_entry("program-a", "prefix-a", (8, 9)))

    assert manager.snapshot(key).block_ids == (BlockIdentity(8), BlockIdentity(9))
    assert manager.entries_for_block(BlockIdentity(7)) == ()
    assert manager.entries_for_block(BlockIdentity(8)) == (key,)
    assert manager.entries_for_block(BlockIdentity(9)) == (key,)


def test_shared_block_remains_protected_until_all_entries_release_it() -> None:
    manager = RetentionManager(FakeClock())
    manager.upsert(_entry("program-a", "prefix-a", (7, 8)))
    manager.upsert(_entry("program-b", "prefix-b", (7,)))

    manager.admit_followup(ProgramIdentity("program-a"))

    assert manager.snapshot(_key("program-a", "prefix-a")).protected is False
    assert manager.is_block_protected(BlockIdentity(7)) is True
    assert manager.is_block_protected(BlockIdentity(8)) is False


def test_expiry_is_lazy_and_makes_entry_ordinary_unprotected() -> None:
    clock = FakeClock()
    manager = RetentionManager(clock)
    key = _key("program-a", "prefix-a")
    manager.upsert(_entry("program-a", "prefix-a", (7,), ttl_seconds=5.0))

    clock.set(4.9)
    manager.expire_due()
    assert manager.snapshot(key).protected is True

    clock.set(5.0)
    manager.expire_due()
    assert manager.snapshot(key).protected is False
    assert manager.entries_for_block(BlockIdentity(7)) == (key,)


def test_waiting_followup_defers_ordinary_expiry() -> None:
    clock = FakeClock()
    manager = RetentionManager(clock)
    key = _key("program-a", "prefix-a")
    manager.upsert(_entry("program-a", "prefix-a", (7,), ttl_seconds=5.0))

    manager.mark_followup_waiting(ProgramIdentity("program-a"))
    clock.set(6.0)
    manager.expire_due()

    snapshot = manager.snapshot(key)
    assert snapshot.protected is True
    assert snapshot.waiting_followup is True


def test_followup_waiting_is_program_scoped_across_entries() -> None:
    clock = FakeClock()
    manager = RetentionManager(clock)
    key_a = _key("program-a", "prefix-a")
    key_b = _key("program-a", "prefix-b")
    manager.upsert(_entry("program-a", "prefix-a", (7,), ttl_seconds=5.0))
    manager.upsert(_entry("program-a", "prefix-b", (8,), ttl_seconds=5.0))

    manager.mark_followup_waiting(ProgramIdentity("program-a"))
    clock.set(6.0)
    manager.expire_due()

    assert manager.snapshot(key_a).protected is True
    assert manager.snapshot(key_a).waiting_followup is True
    assert manager.snapshot(key_b).protected is True
    assert manager.snapshot(key_b).waiting_followup is True


def test_cancelled_followup_rechecks_expiry_at_current_clock_time() -> None:
    clock = FakeClock()
    manager = RetentionManager(clock)
    key = _key("program-a", "prefix-a")
    manager.upsert(_entry("program-a", "prefix-a", (7,), ttl_seconds=5.0))

    manager.mark_followup_waiting(ProgramIdentity("program-a"))
    clock.set(6.0)
    manager.cancel_followup(ProgramIdentity("program-a"))

    snapshot = manager.snapshot(key)
    assert snapshot.protected is False
    assert snapshot.waiting_followup is False


def test_admitted_followup_ends_prior_idle_retention_interval() -> None:
    manager = RetentionManager(FakeClock())
    key = _key("program-a", "prefix-a")
    manager.upsert(_entry("program-a", "prefix-a", (7,)))

    manager.mark_followup_waiting(ProgramIdentity("program-a"))
    manager.admit_followup(ProgramIdentity("program-a"))

    snapshot = manager.snapshot(key)
    assert snapshot.protected is False
    assert snapshot.waiting_followup is False


def test_terminal_program_cleanup_removes_owned_entries_and_reverse_edges() -> None:
    manager = RetentionManager(FakeClock())
    key_a = _key("program-a", "prefix-a")
    key_b = _key("program-a", "prefix-b")
    manager.upsert(_entry("program-a", "prefix-a", (7,)))
    manager.upsert(_entry("program-a", "prefix-b", (8,)))

    manager.complete_program(ProgramIdentity("program-a"))

    assert manager.snapshot(key_a) is None
    assert manager.snapshot(key_b) is None
    assert manager.entries_for_block(BlockIdentity(7)) == ()
    assert manager.entries_for_block(BlockIdentity(8)) == ()


def test_eviction_removes_only_stale_physical_association() -> None:
    manager = RetentionManager(FakeClock())
    key = _key("program-a", "prefix-a")
    manager.upsert(_entry("program-a", "prefix-a", (7, 8)))

    manager.observe_eviction(BlockIdentity(7))

    snapshot = manager.snapshot(key)
    assert snapshot is not None
    assert snapshot.block_ids == (BlockIdentity(8),)
    assert manager.entries_for_block(BlockIdentity(7)) == ()
    assert manager.entries_for_block(BlockIdentity(8)) == (key,)


def test_shared_eviction_clears_all_edges_but_keeps_logical_entries() -> None:
    manager = RetentionManager(FakeClock())
    key_a = _key("program-a", "prefix-a")
    key_b = _key("program-b", "prefix-b")
    manager.upsert(_entry("program-a", "prefix-a", (7,)))
    manager.upsert(_entry("program-b", "prefix-b", (7,)))

    manager.observe_eviction(BlockIdentity(7))

    assert manager.snapshot(key_a) is not None
    assert manager.snapshot(key_a).block_ids == ()
    assert manager.snapshot(key_b) is not None
    assert manager.snapshot(key_b).block_ids == ()
    assert manager.entries_for_block(BlockIdentity(7)) == ()


def test_retention_manager_rejects_wrong_snapshot_type() -> None:
    manager = RetentionManager(FakeClock())

    with pytest.raises(TypeError, match="RetentionEntrySnapshot"):
        manager.upsert(object())
