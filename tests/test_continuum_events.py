import math
from dataclasses import FrozenInstanceError

import pytest

from kvopt.continuum import (
    BlockEvicted,
    BlockIdentity,
    BlocksObserved,
    FollowupCancelled,
    FollowupWaiting,
    LifecycleEvent,
    LifecycleEventType,
    PrefixIdentity,
    ProgramCompleted,
    ProgramIdentity,
    ProgramStarted,
    RequestAdmitted,
    RequestArrived,
    RequestIdentity,
    RequestPreempted,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)

PROGRAM_ID = ProgramIdentity("program-1")
REQUEST_ID = RequestIdentity("request-1")
PREFIX_ID = PrefixIdentity("prefix-1")
BLOCK_ID = BlockIdentity(1)


def _event_cases(timestamp=1.0):
    return [
        (ProgramStarted(PROGRAM_ID, timestamp), LifecycleEventType.PROGRAM_STARTED),
        (RequestArrived(PROGRAM_ID, REQUEST_ID, timestamp), LifecycleEventType.REQUEST_ARRIVED),
        (
            RequestAdmitted(PROGRAM_ID, REQUEST_ID, timestamp),
            LifecycleEventType.REQUEST_ADMITTED,
        ),
        (
            RequestPreempted(PROGRAM_ID, REQUEST_ID, timestamp),
            LifecycleEventType.REQUEST_PREEMPTED,
        ),
        (
            TurnFinished(PROGRAM_ID, REQUEST_ID, timestamp, False, "search"),
            LifecycleEventType.TURN_FINISHED,
        ),
        (
            FollowupWaiting(PROGRAM_ID, REQUEST_ID, timestamp),
            LifecycleEventType.FOLLOWUP_WAITING,
        ),
        (
            FollowupCancelled(PROGRAM_ID, REQUEST_ID, timestamp),
            LifecycleEventType.FOLLOWUP_CANCELLED,
        ),
        (ToolGapStarted(PROGRAM_ID, "search", timestamp), LifecycleEventType.TOOL_GAP_STARTED),
        (ToolGapEnded(PROGRAM_ID, "search", timestamp), LifecycleEventType.TOOL_GAP_ENDED),
        (ProgramCompleted(PROGRAM_ID, timestamp), LifecycleEventType.PROGRAM_COMPLETED),
        (
            BlocksObserved(PROGRAM_ID, REQUEST_ID, PREFIX_ID, [BLOCK_ID], timestamp),
            LifecycleEventType.BLOCKS_OBSERVED,
        ),
        (BlockEvicted(BLOCK_ID, timestamp), LifecycleEventType.BLOCK_EVICTED),
    ]


def test_event_type_contains_exactly_the_frozen_lifecycle_names() -> None:
    assert {event_type.value for event_type in LifecycleEventType} == {
        "PROGRAM_STARTED",
        "REQUEST_ARRIVED",
        "REQUEST_ADMITTED",
        "REQUEST_PREEMPTED",
        "TURN_FINISHED",
        "FOLLOWUP_WAITING",
        "FOLLOWUP_CANCELLED",
        "TOOL_GAP_STARTED",
        "TOOL_GAP_ENDED",
        "PROGRAM_COMPLETED",
        "BLOCKS_OBSERVED",
        "BLOCK_EVICTED",
    }


def test_each_event_exposes_a_fixed_type_and_is_in_the_lifecycle_union() -> None:
    for event, expected_type in _event_cases():
        assert event.event_type is expected_type
        assert isinstance(event, LifecycleEvent)


def test_events_are_immutable_and_hashable() -> None:
    event = ProgramStarted(PROGRAM_ID, 1.0)

    assert isinstance(hash(event), int)
    with pytest.raises(FrozenInstanceError):
        event.start_timestamp = 2.0


@pytest.mark.parametrize(
    "factory",
    [
        lambda value: ProgramStarted(value, 1.0),
        lambda value: RequestArrived(value, REQUEST_ID, 1.0),
        lambda value: RequestAdmitted(value, REQUEST_ID, 1.0),
        lambda value: RequestPreempted(value, REQUEST_ID, 1.0),
        lambda value: TurnFinished(value, REQUEST_ID, 1.0, False),
        lambda value: FollowupWaiting(value, REQUEST_ID, 1.0),
        lambda value: FollowupCancelled(value, REQUEST_ID, 1.0),
        lambda value: ToolGapStarted(value, "search", 1.0),
        lambda value: ToolGapEnded(value, "search", 1.0),
        lambda value: ProgramCompleted(value, 1.0),
        lambda value: BlocksObserved(value, REQUEST_ID, PREFIX_ID, [BLOCK_ID], 1.0),
    ],
)
def test_events_reject_non_program_identity(factory) -> None:
    with pytest.raises(TypeError, match="program_id must be ProgramIdentity"):
        factory(REQUEST_ID)


@pytest.mark.parametrize(
    "factory",
    [
        lambda value: RequestArrived(PROGRAM_ID, value, 1.0),
        lambda value: RequestAdmitted(PROGRAM_ID, value, 1.0),
        lambda value: RequestPreempted(PROGRAM_ID, value, 1.0),
        lambda value: TurnFinished(PROGRAM_ID, value, 1.0, False),
        lambda value: FollowupWaiting(PROGRAM_ID, value, 1.0),
        lambda value: FollowupCancelled(PROGRAM_ID, value, 1.0),
        lambda value: BlocksObserved(PROGRAM_ID, value, PREFIX_ID, [BLOCK_ID], 1.0),
    ],
)
def test_request_events_reject_non_request_identity(factory) -> None:
    with pytest.raises(TypeError, match="request_id must be RequestIdentity"):
        factory(PROGRAM_ID)


@pytest.mark.parametrize(
    "invalid",
    [-1.0, math.inf, -math.inf, math.nan, True, "1.0", 10**400],
)
def test_every_event_rejects_invalid_timestamp(invalid) -> None:
    factories = [
        lambda: ProgramStarted(PROGRAM_ID, invalid),
        lambda: RequestArrived(PROGRAM_ID, REQUEST_ID, invalid),
        lambda: RequestAdmitted(PROGRAM_ID, REQUEST_ID, invalid),
        lambda: RequestPreempted(PROGRAM_ID, REQUEST_ID, invalid),
        lambda: TurnFinished(PROGRAM_ID, REQUEST_ID, invalid, False),
        lambda: FollowupWaiting(PROGRAM_ID, REQUEST_ID, invalid),
        lambda: FollowupCancelled(PROGRAM_ID, REQUEST_ID, invalid),
        lambda: ToolGapStarted(PROGRAM_ID, "search", invalid),
        lambda: ToolGapEnded(PROGRAM_ID, "search", invalid),
        lambda: ProgramCompleted(PROGRAM_ID, invalid),
        lambda: BlocksObserved(PROGRAM_ID, REQUEST_ID, PREFIX_ID, [BLOCK_ID], invalid),
        lambda: BlockEvicted(BLOCK_ID, invalid),
    ]

    for factory in factories:
        with pytest.raises((TypeError, ValueError)):
            factory()


def test_event_timestamps_are_normalized_to_float() -> None:
    for event, _ in _event_cases(timestamp=1):
        timestamp_fields = [
            field
            for field in event.__dataclass_fields__
            if field.endswith("_timestamp")
        ]
        assert len(timestamp_fields) == 1
        assert isinstance(getattr(event, timestamp_fields[0]), float)


def test_turn_finished_validates_terminal_and_optional_tool_fields() -> None:
    event = TurnFinished(PROGRAM_ID, REQUEST_ID, 1.0, False, None)
    terminal = TurnFinished(PROGRAM_ID, REQUEST_ID, 2.0, True, None)

    assert event.next_tool_type is None
    assert terminal.is_terminal is True
    with pytest.raises(TypeError, match="is_terminal must be bool"):
        TurnFinished(PROGRAM_ID, REQUEST_ID, 1.0, 0)
    with pytest.raises(ValueError, match="next_tool_type must not be empty"):
        TurnFinished(PROGRAM_ID, REQUEST_ID, 1.0, False, " ")
    with pytest.raises(TypeError, match="next_tool_type must be str"):
        TurnFinished(PROGRAM_ID, REQUEST_ID, 1.0, False, 1)
    with pytest.raises(ValueError, match="terminal turn"):
        TurnFinished(PROGRAM_ID, REQUEST_ID, 1.0, True, "search")


def test_tool_gap_events_are_explicit_and_separate_from_turn_finished() -> None:
    turn = TurnFinished(PROGRAM_ID, REQUEST_ID, 1.0, False, "search")
    started = ToolGapStarted(PROGRAM_ID, "search", 2.0)
    ended = ToolGapEnded(PROGRAM_ID, "search", 3.0)

    assert turn.event_type is LifecycleEventType.TURN_FINISHED
    assert started.event_type is LifecycleEventType.TOOL_GAP_STARTED
    assert ended.event_type is LifecycleEventType.TOOL_GAP_ENDED
    assert not isinstance(turn, (ToolGapStarted, ToolGapEnded))


@pytest.mark.parametrize("event_type", [ToolGapStarted, ToolGapEnded])
@pytest.mark.parametrize("tool_type", ["", "   ", 1])
def test_tool_gap_events_require_non_empty_tool_type(event_type, tool_type) -> None:
    with pytest.raises((TypeError, ValueError)):
        event_type(PROGRAM_ID, tool_type, 1.0)


def test_blocks_observed_normalizes_an_ordered_list_to_tuple() -> None:
    blocks = [BlockIdentity(3), BlockIdentity(1)]
    event = BlocksObserved(PROGRAM_ID, REQUEST_ID, PREFIX_ID, blocks, 1.0)
    blocks.append(BlockIdentity(2))

    assert event.block_ids == (BlockIdentity(3), BlockIdentity(1))


def test_blocks_observed_validates_prefix_and_block_identities() -> None:
    with pytest.raises(TypeError, match="prefix_id must be PrefixIdentity"):
        BlocksObserved(PROGRAM_ID, REQUEST_ID, PROGRAM_ID, [BLOCK_ID], 1.0)
    with pytest.raises(TypeError, match="block_ids item must be BlockIdentity"):
        BlocksObserved(PROGRAM_ID, REQUEST_ID, PREFIX_ID, [1], 1.0)
    with pytest.raises(ValueError, match="must not contain duplicates"):
        BlocksObserved(PROGRAM_ID, REQUEST_ID, PREFIX_ID, [BLOCK_ID, BLOCK_ID], 1.0)
    with pytest.raises(TypeError, match="ordered list or tuple"):
        BlocksObserved(PROGRAM_ID, REQUEST_ID, PREFIX_ID, {BLOCK_ID}, 1.0)


def test_block_evicted_requires_block_identity() -> None:
    with pytest.raises(TypeError, match="block_id must be BlockIdentity"):
        BlockEvicted(1, 1.0)
