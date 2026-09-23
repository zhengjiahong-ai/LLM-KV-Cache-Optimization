import math
from dataclasses import FrozenInstanceError

import pytest

from kvopt.continuum import (
    BlockIdentity,
    EvictedRequestQueueDelayRecord,
    InputProvenance,
    InputSource,
    PrefixAssociationSnapshot,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionEntrySnapshot,
    SchedulingCandidate,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)

PROGRAM_ID = ProgramIdentity("program-1")
REQUEST_ID = RequestIdentity("request-1")
PREFIX_ID = PrefixIdentity("prefix-1")
BLOCK_ID = BlockIdentity(1)
OBSERVED = InputProvenance(InputSource.OBSERVED)
APPROXIMATED = InputProvenance(InputSource.APPROXIMATED, "offline profile")


def _ttl_input(**overrides) -> TTLInput:
    values = {
        "program_id": PROGRAM_ID,
        "request_id": REQUEST_ID,
        "prefix_id": PREFIX_ID,
        "decision_timestamp": 10.0,
        "next_tool_type": "search",
        "global_server_gap_samples_seconds": [1.0, 2.0],
        "tool_server_gap_samples_seconds": [1.5],
        "queue_delay_t_seconds": 0.25,
        "eta": -0.5,
        "prefill_reload_seconds": 0.4,
        "default_ttl_seconds": 0.8,
        "server_gap_history_provenance": OBSERVED,
        "queue_delay_provenance": OBSERVED,
        "eta_provenance": OBSERVED,
        "prefill_reload_provenance": APPROXIMATED,
        "default_ttl_provenance": APPROXIMATED,
    }
    values.update(overrides)
    return TTLInput(**values)


def _scheduling_candidate(**overrides) -> SchedulingCandidate:
    values = {
        "program_id": PROGRAM_ID,
        "request_id": REQUEST_ID,
        "program_arrival_timestamp": 1.0,
        "request_arrival_timestamp": 2.0,
        "snapshot_timestamp": 5.0,
        "turn_index": 1,
        "is_preempted_waiting": False,
        "is_followup": True,
        "program_is_protected": True,
        "native_priority": 0,
        "retention_deadline_timestamp": 8.0,
    }
    values.update(overrides)
    return SchedulingCandidate(**values)


def test_evicted_request_queue_delay_is_observed_and_derived() -> None:
    record = EvictedRequestQueueDelayRecord(PROGRAM_ID, REQUEST_ID, 2, 5)

    assert record.arrival_timestamp == 2.0
    assert record.admission_timestamp == 5.0
    assert record.duration_seconds == 3.0
    assert record.source is InputSource.OBSERVED


def test_evicted_request_queue_delay_rejects_wrong_identity_or_order() -> None:
    with pytest.raises(TypeError, match="program_id must be ProgramIdentity"):
        EvictedRequestQueueDelayRecord(REQUEST_ID, REQUEST_ID, 1.0, 2.0)
    with pytest.raises(TypeError, match="request_id must be RequestIdentity"):
        EvictedRequestQueueDelayRecord(PROGRAM_ID, PROGRAM_ID, 1.0, 2.0)
    with pytest.raises(ValueError, match="must not precede"):
        EvictedRequestQueueDelayRecord(PROGRAM_ID, REQUEST_ID, 2.0, 1.0)


def test_prefix_association_defensively_freezes_ordered_blocks() -> None:
    blocks = [BlockIdentity(2), BLOCK_ID]
    snapshot = PrefixAssociationSnapshot(PROGRAM_ID, PREFIX_ID, blocks, 3)
    blocks.append(BlockIdentity(3))

    assert snapshot.block_ids == (BlockIdentity(2), BLOCK_ID)
    assert snapshot.observation_timestamp == 3.0
    assert snapshot.source is InputSource.OBSERVED


def test_prefix_association_rejects_wrong_or_duplicate_identities() -> None:
    with pytest.raises(TypeError, match="program_id must be ProgramIdentity"):
        PrefixAssociationSnapshot(REQUEST_ID, PREFIX_ID, [BLOCK_ID], 1.0)
    with pytest.raises(TypeError, match="prefix_id must be PrefixIdentity"):
        PrefixAssociationSnapshot(PROGRAM_ID, PROGRAM_ID, [BLOCK_ID], 1.0)
    with pytest.raises(TypeError, match="block_ids item must be BlockIdentity"):
        PrefixAssociationSnapshot(PROGRAM_ID, PREFIX_ID, [1], 1.0)
    with pytest.raises(ValueError, match="must not contain duplicates"):
        PrefixAssociationSnapshot(PROGRAM_ID, PREFIX_ID, [BLOCK_ID, BLOCK_ID], 1.0)


def test_retention_snapshot_preserves_expired_but_waiting_protection_state() -> None:
    decision = TTLDecision(_ttl_input(decision_timestamp=2.0), 2.0, TTLHistoryMode.GLOBAL)
    snapshot = RetentionEntrySnapshot(
        decision,
        protected=True,
        waiting_followup=True,
        block_ids=[BLOCK_ID],
    )

    assert snapshot.deadline_timestamp == 4.0
    assert snapshot.protected is True
    assert snapshot.waiting_followup is True
    assert snapshot.block_ids == (BLOCK_ID,)
    assert snapshot.ttl_decision is decision
    assert snapshot.ttl_decision.ttl_input.eta_provenance is OBSERVED


@pytest.mark.parametrize("field_name", ["protected", "waiting_followup"])
@pytest.mark.parametrize("invalid", [0, 1, None, "true"])
def test_retention_snapshot_requires_boolean_flags(field_name, invalid) -> None:
    values = {
        "ttl_decision": TTLDecision(_ttl_input(), 1.0, TTLHistoryMode.GLOBAL),
        "protected": True,
        "waiting_followup": False,
        "block_ids": [],
    }
    values[field_name] = invalid
    with pytest.raises(TypeError, match=f"{field_name} must be bool"):
        RetentionEntrySnapshot(**values)


def test_ttl_input_freezes_only_server_gap_histories_and_preserves_negative_eta() -> None:
    global_samples = [2, 1, 2]
    tool_samples = [1.5]
    snapshot = _ttl_input(
        global_server_gap_samples_seconds=global_samples,
        tool_server_gap_samples_seconds=tool_samples,
        eta=-0.75,
    )
    global_samples.append(9)
    tool_samples.append(9)

    assert snapshot.global_server_gap_samples_seconds == (2.0, 1.0, 2.0)
    assert snapshot.tool_server_gap_samples_seconds == (1.5,)
    assert snapshot.eta == -0.75
    assert not hasattr(snapshot, "external_tool_duration_samples_seconds")


@pytest.mark.parametrize(
    "field_name",
    [
        "decision_timestamp",
        "queue_delay_t_seconds",
        "prefill_reload_seconds",
        "default_ttl_seconds",
    ],
)
@pytest.mark.parametrize("invalid", [-1.0, math.inf, -math.inf, math.nan, True, "1"])
def test_ttl_input_rejects_invalid_non_negative_numeric_fields(
    field_name, invalid
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _ttl_input(**{field_name: invalid})


@pytest.mark.parametrize("invalid", [math.inf, -math.inf, math.nan, True, "-1"])
def test_ttl_input_requires_finite_numeric_eta_but_allows_negative(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        _ttl_input(eta=invalid)


@pytest.mark.parametrize(
    "field_name",
    ["global_server_gap_samples_seconds", "tool_server_gap_samples_seconds"],
)
@pytest.mark.parametrize("invalid", [[-1.0], [math.inf], [True], ["1"], {1.0}])
def test_ttl_input_rejects_invalid_server_gap_sample_sequences(
    field_name, invalid
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _ttl_input(**{field_name: invalid})


@pytest.mark.parametrize(
    "field_name",
    [
        "server_gap_history_provenance",
        "queue_delay_provenance",
        "eta_provenance",
        "prefill_reload_provenance",
        "default_ttl_provenance",
    ],
)
def test_ttl_input_requires_typed_provenance(field_name) -> None:
    with pytest.raises(TypeError, match=f"{field_name} must be InputProvenance"):
        _ttl_input(**{field_name: InputSource.OBSERVED})


@pytest.mark.parametrize(
    ("field_name", "invalid_provenance"),
    [
        ("server_gap_history_provenance", APPROXIMATED),
        ("queue_delay_provenance", APPROXIMATED),
        ("eta_provenance", InputProvenance(InputSource.EXTERNAL)),
        ("prefill_reload_provenance", OBSERVED),
        ("default_ttl_provenance", OBSERVED),
    ],
)
def test_ttl_input_enforces_frozen_provenance_sources(
    field_name, invalid_provenance
) -> None:
    with pytest.raises(ValueError, match=r"\.source must be one of"):
        _ttl_input(**{field_name: invalid_provenance})


def test_ttl_input_allows_missing_upcoming_tool_but_not_invalid_tool_text() -> None:
    snapshot = _ttl_input(
        next_tool_type=None,
        tool_server_gap_samples_seconds=[],
    )

    assert snapshot.next_tool_type is None
    with pytest.raises(ValueError, match="next_tool_type must not be empty"):
        _ttl_input(next_tool_type=" ")
    with pytest.raises(ValueError, match="require next_tool_type"):
        _ttl_input(next_tool_type=None)


def test_ttl_decision_derives_deadline_and_is_immutable() -> None:
    decision = TTLDecision(
        _ttl_input(decision_timestamp=10),
        2.5,
        TTLHistoryMode.TOOL_SPECIFIC,
    )

    assert decision.decision_timestamp == 10.0
    assert decision.ttl_seconds == 2.5
    assert decision.deadline_timestamp == 12.5
    with pytest.raises(FrozenInstanceError):
        decision.ttl_seconds = 4.0


def test_ttl_decision_rejects_invalid_values_and_deadline_overflow() -> None:
    with pytest.raises(ValueError, match="ttl_seconds must be non-negative"):
        TTLDecision(_ttl_input(), -1.0, TTLHistoryMode.GLOBAL)
    with pytest.raises(ValueError, match="deadline_timestamp must be finite"):
        TTLDecision(
            _ttl_input(decision_timestamp=1.7e308),
            1.7e308,
            TTLHistoryMode.GLOBAL,
        )


def test_ttl_decision_records_history_mode_and_optional_reason() -> None:
    decision = TTLDecision(
        _ttl_input(decision_timestamp=1.0),
        2.0,
        TTLHistoryMode.COLD_START,
        "global history below threshold",
    )

    assert decision.history_mode is TTLHistoryMode.COLD_START
    assert decision.reason == "global history below threshold"
    assert decision.ttl_input is not None
    with pytest.raises(TypeError, match="history_mode must be TTLHistoryMode"):
        TTLDecision(_ttl_input(), 2.0, "global")
    with pytest.raises(ValueError, match="reason must not be empty"):
        TTLDecision(
            _ttl_input(),
            2.0,
            TTLHistoryMode.GLOBAL,
            " ",
        )
    with pytest.raises(ValueError, match="requires reason"):
        TTLDecision(_ttl_input(), 2.0, TTLHistoryMode.COLD_START)
    with pytest.raises(TypeError, match="ttl_input must be TTLInput"):
        TTLDecision(PROGRAM_ID, 2.0, TTLHistoryMode.GLOBAL)


def test_ttl_decision_rejects_tool_specific_history_without_next_tool() -> None:
    ttl_input = _ttl_input(
        next_tool_type=None,
        tool_server_gap_samples_seconds=[],
    )

    with pytest.raises(ValueError, match="tool-specific history requires"):
        TTLDecision(ttl_input, 2.0, TTLHistoryMode.TOOL_SPECIFIC, "fallback")


def test_ttl_decision_requires_reason_when_next_tool_is_missing() -> None:
    ttl_input = _ttl_input(
        next_tool_type=None,
        tool_server_gap_samples_seconds=[],
    )

    with pytest.raises(ValueError, match="fallback requires reason"):
        TTLDecision(ttl_input, 2.0, TTLHistoryMode.GLOBAL)

    decision = TTLDecision(
        ttl_input,
        2.0,
        TTLHistoryMode.GLOBAL,
        "next tool type unavailable",
    )
    assert decision.reason == "next tool type unavailable"


def test_scheduling_candidate_derives_waiting_age_without_cost_aware_fields() -> None:
    candidate = _scheduling_candidate()

    assert candidate.waiting_age_seconds == 3.0
    assert not hasattr(candidate, "recomputation_cost_estimate")
    assert not hasattr(candidate, "cost_aware_score")


def test_scheduling_candidate_accepts_absent_native_metadata() -> None:
    candidate = _scheduling_candidate(
        native_priority=None,
        retention_deadline_timestamp=None,
        program_is_protected=False,
    )

    assert candidate.native_priority is None
    assert candidate.retention_deadline_timestamp is None


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("turn_index", -1),
        ("turn_index", True),
        ("native_priority", True),
        ("native_priority", 1.5),
        ("retention_deadline_timestamp", -1.0),
        ("retention_deadline_timestamp", math.nan),
    ],
)
def test_scheduling_candidate_rejects_invalid_numeric_metadata(
    field_name, invalid
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _scheduling_candidate(**{field_name: invalid})


@pytest.mark.parametrize(
    "field_name", ["is_preempted_waiting", "is_followup", "program_is_protected"]
)
def test_scheduling_candidate_requires_boolean_classification(field_name) -> None:
    with pytest.raises(TypeError, match=f"{field_name} must be bool"):
        _scheduling_candidate(**{field_name: 1})


def test_scheduling_candidate_rejects_impossible_timestamp_order() -> None:
    with pytest.raises(ValueError, match="request_arrival_timestamp"):
        _scheduling_candidate(
            program_arrival_timestamp=3.0,
            request_arrival_timestamp=2.0,
        )
    with pytest.raises(ValueError, match="snapshot_timestamp"):
        _scheduling_candidate(
            request_arrival_timestamp=4.0,
            snapshot_timestamp=3.0,
        )


def test_all_snapshots_are_hashable() -> None:
    snapshots = [
        EvictedRequestQueueDelayRecord(PROGRAM_ID, REQUEST_ID, 1.0, 2.0),
        PrefixAssociationSnapshot(PROGRAM_ID, PREFIX_ID, [BLOCK_ID], 1.0),
        RetentionEntrySnapshot(
            TTLDecision(_ttl_input(), 2.0, TTLHistoryMode.GLOBAL),
            True,
            False,
            [BLOCK_ID],
        ),
        _ttl_input(),
        TTLDecision(
            _ttl_input(decision_timestamp=1.0),
            2.0,
            TTLHistoryMode.GLOBAL,
        ),
        _scheduling_candidate(),
    ]

    assert all(isinstance(hash(snapshot), int) for snapshot in snapshots)
