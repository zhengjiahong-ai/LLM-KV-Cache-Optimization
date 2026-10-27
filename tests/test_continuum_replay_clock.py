from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.continuum import (
    BlockIdentity,
    ControlledSparseReplayClock,
    FakeClock,
    InputProvenance,
    InputSource,
    LogicalTimeBoundary,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionEntrySnapshot,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
    assert_identical_time_sequences,
)
from kvopt.continuum.retention import RetentionManager


def _boundaries(second: float = 20.0) -> tuple[LogicalTimeBoundary, ...]:
    return (
        LogicalTimeBoundary("a:arrived", 10.0, "W1C_MODEL_SUBMIT"),
        LogicalTimeBoundary("a:completed", second, "W1C_MODEL_COMPLETION"),
    )


def _entry(deadline: float) -> RetentionEntrySnapshot:
    program = ProgramIdentity("a")
    request = RequestIdentity("a:1")
    prefix = PrefixIdentity("prefix-a")
    provenance = InputProvenance(InputSource.OBSERVED)
    approximated = InputProvenance(InputSource.APPROXIMATED, "test input")
    ttl_input = TTLInput(
        program_id=program,
        request_id=request,
        prefix_id=prefix,
        decision_timestamp=10.0,
        next_tool_type=None,
        global_server_gap_samples_seconds=(),
        tool_server_gap_samples_seconds=(),
        queue_delay_t_seconds=0.0,
        eta=1.0,
        prefill_reload_seconds=1.0,
        default_ttl_seconds=deadline - 10.0,
        server_gap_history_provenance=provenance,
        queue_delay_provenance=provenance,
        eta_provenance=approximated,
        prefill_reload_provenance=approximated,
        default_ttl_provenance=approximated,
    )
    return RetentionEntrySnapshot(
        ttl_decision=TTLDecision(
            ttl_input=ttl_input,
            ttl_seconds=deadline - 10.0,
            history_mode=TTLHistoryMode.COLD_START,
            reason="test",
        ),
        protected=True,
        waiting_followup=False,
        block_ids=(BlockIdentity(1),),
    )


def test_logical_time_advances_without_sleeping_or_changing_native_time() -> None:
    native = FakeClock(100.0)
    wall = FakeClock(1_000.0)
    replay = ControlledSparseReplayClock(
        boundaries=_boundaries(), native_clock=native, wall_timer=wall
    )

    first = replay.advance("a:arrived")
    assert first.logical_timestamp == 10.0
    assert first.native_monotonic_timestamp == 100.0
    assert first.wall_elapsed_seconds == 0.0

    replay.native_submitted("a:1")
    native.advance(4.0)
    wall.advance(4.0)
    replay.native_completed("a:1")
    second = replay.advance("a:completed")

    assert second.logical_timestamp == 20.0
    assert second.native_monotonic_timestamp == 104.0
    assert second.wall_elapsed_seconds == 4.0
    replay.assert_complete()


def test_logical_time_fails_closed_while_native_request_is_inflight() -> None:
    replay = ControlledSparseReplayClock(boundaries=_boundaries())
    replay.advance("a:arrived")
    replay.native_submitted("a:1")

    with pytest.raises(RuntimeError, match="inflight"):
        replay.advance("a:completed")
    with pytest.raises(RuntimeError, match="inflight"):
        replay.assert_complete()


def test_boundary_order_and_monotonicity_fail_closed() -> None:
    with pytest.raises(ValueError, match="monotonic"):
        ControlledSparseReplayClock(boundaries=_boundaries(9.0))

    replay = ControlledSparseReplayClock(boundaries=_boundaries())
    with pytest.raises(ValueError, match="order mismatch"):
        replay.advance("a:completed")


def test_retention_expiry_uses_logical_not_native_time() -> None:
    native = FakeClock(100.0)
    replay = ControlledSparseReplayClock(boundaries=_boundaries(), native_clock=native)
    manager = RetentionManager(replay.logical_clock)
    manager.upsert(_entry(15.0))

    replay.advance("a:arrived")
    native.advance(100.0)
    manager.expire_due()
    assert manager.planning_snapshots()[0].protected is True

    replay.advance("a:completed")
    manager.expire_due()
    assert manager.planning_snapshots()[0].protected is False


def test_policy_arms_require_identical_frozen_time_sequences() -> None:
    a0 = ControlledSparseReplayClock(boundaries=_boundaries())
    a1 = ControlledSparseReplayClock(boundaries=_boundaries())
    assert assert_identical_time_sequences((a0, a1)) == a0.sequence_sha256

    changed = ControlledSparseReplayClock(
        boundaries=(
            LogicalTimeBoundary("a:arrived", 10.0, "W1C_MODEL_SUBMIT"),
            LogicalTimeBoundary("a:completed", 21.0, "W1C_MODEL_COMPLETION"),
        )
    )
    with pytest.raises(ValueError, match="one frozen logical-time sequence"):
        assert_identical_time_sequences((a0, changed))


def test_bounded_candidate_freezes_clock_contract_and_retains_profile_counts() -> None:
    root = Path(__file__).resolve().parents[1]
    protocol = json.loads(
        (
            root
            / "configs/phase2/continuum-native-cost-aware-bounded-protocol-v1.json"
        ).read_text(encoding="utf-8")
    )
    replay = protocol["replay"]
    contract = replay["logical_time_contract"]

    assert replay["timing_claim"] == (
        "CONTROLLED_SPARSE_REPLAY_WITH_LOGICAL_LIFECYCLE_TIME"
    )
    assert contract["advance_boundary"] == "ONLY_WITH_ZERO_NATIVE_INFLIGHT_REQUESTS"
    assert contract["cross_arm_sequence"] == "IDENTICAL_SHA256_REQUIRED"
    assert protocol["profile"]["warmup_pairs_per_point"] == 2
    assert protocol["profile"]["measured_pairs_per_point"] == 8
    assert protocol["profile"]["total_pair_count"] == 70
    assert protocol["planned_native_run_count"] == 54
    assert protocol["execution_authorized"] is False
    assert protocol["bounded_54_run_campaign_status"] == "PENDING_FINAL_FREEZE"
