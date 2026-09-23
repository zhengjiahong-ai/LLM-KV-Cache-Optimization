import json
import math
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from enum import Enum

import pytest

from kvopt.continuum import (
    BlockIdentity,
    EligibilityTier,
    FrozenJsonObject,
    InMemoryEventSink,
    InputSource,
    LifecycleEventType,
    NullEventSink,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionMode,
    SchedulerMode,
    StructuredEventSink,
    StructuredLogEvent,
    StructuredLogRecord,
    TTLHistoryMode,
)

PROGRAM_ID = ProgramIdentity("program-1")
REQUEST_ID = RequestIdentity("request-1")
PREFIX_ID = PrefixIdentity("prefix-1")


def _record(**overrides) -> StructuredLogRecord:
    values = {
        "event": StructuredLogEvent.TTL_DECIDED,
        "timestamp": 1.0,
        "mode": RetentionMode.SHADOW,
        "program_id": PROGRAM_ID,
        "request_id": REQUEST_ID,
        "prefix_id": PREFIX_ID,
        "source": InputSource.OBSERVED,
        "reason": None,
        "fields": {"ttl_seconds": 2.0},
    }
    values.update(overrides)
    return StructuredLogRecord(**values)


def test_project_log_event_names_are_explicit_and_stable() -> None:
    assert {event.value for event in StructuredLogEvent} == {
        "PROGRAM_REQUEST_ASSOCIATED",
        "TOOL_GAP_STARTED",
        "TOOL_GAP_ENDED",
        "SERVER_GAP_OBSERVED",
        "PREFIX_BLOCKS_ASSOCIATED",
        "RETENTION_PROTECTED",
        "RETENTION_EXPIRED",
        "RETENTION_EXPIRY_DEFERRED",
        "RETENTION_RELEASED_PRESSURE",
        "RETENTION_SELECTION_PLANNED",
        "TTL_DECIDED",
        "QUEUE_DELAY_OBSERVED",
        "BLOCK_EVICTED",
        "STALE_ASSOCIATION_REMOVED",
        "SCHEDULER_SHADOW",
        "SCHEDULER_CONTROLLED",
    }


def test_record_exposes_all_stable_top_level_fields() -> None:
    payload = _record().to_dict()

    assert set(payload) == {
        "event",
        "timestamp",
        "mode",
        "program_id",
        "request_id",
        "prefix_id",
        "source",
        "reason",
        "fields",
    }


@pytest.mark.parametrize("invalid", [-1.0, math.inf, -math.inf, math.nan, True, "1"])
def test_record_rejects_invalid_timestamp(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        _record(timestamp=invalid)


@pytest.mark.parametrize(
    ("field_name", "invalid", "expected"),
    [
        ("program_id", REQUEST_ID, "ProgramIdentity"),
        ("request_id", PROGRAM_ID, "RequestIdentity"),
        ("prefix_id", PROGRAM_ID, "PrefixIdentity"),
    ],
)
def test_record_runtime_checks_optional_identities(field_name, invalid, expected) -> None:
    with pytest.raises(TypeError, match=expected):
        _record(**{field_name: invalid})


def test_record_runtime_checks_event_mode_and_source() -> None:
    with pytest.raises(TypeError, match="event must be StructuredLogEvent"):
        _record(event="TTL_DECIDED")
    with pytest.raises(TypeError, match="mode must be"):
        _record(mode="shadow")
    with pytest.raises(TypeError, match="source must be"):
        _record(source="OBSERVED")
    assert _record(mode=SchedulerMode.CONTROLLED).mode is SchedulerMode.CONTROLLED


@pytest.mark.parametrize("mode", [RetentionMode.SHADOW, RetentionMode.CONTROLLED])
def test_retention_selection_plan_event_supports_observation_modes(mode) -> None:
    record = _record(
        event=StructuredLogEvent.RETENTION_SELECTION_PLANNED,
        mode=mode,
    )

    assert record.event is StructuredLogEvent.RETENTION_SELECTION_PLANNED
    assert record.mode is mode


def test_approximation_and_unavailable_sources_require_reason() -> None:
    for source in (InputSource.APPROXIMATED, InputSource.UNAVAILABLE):
        with pytest.raises(ValueError, match="reason is required"):
            _record(source=source)
        assert _record(source=source, reason="explicit fallback").reason == "explicit fallback"


def test_fields_are_deeply_frozen_and_detached_from_original_containers() -> None:
    nested = {"items": [1, {"block": BlockIdentity(3)}]}
    fields = {"nested": nested}
    record = _record(fields=fields)
    nested["items"].append(4)
    fields["new"] = True

    assert isinstance(record.fields, FrozenJsonObject)
    assert record.to_dict()["fields"] == {"nested": {"items": [1, {"block": 3}]}}
    with pytest.raises(TypeError):
        record.fields["new"] = True
    nested_value = record.fields["nested"]
    assert isinstance(nested_value, FrozenJsonObject)
    with pytest.raises(TypeError):
        nested_value["new"] = True


def test_cycle_detection_tracks_current_path_not_global_visited_objects() -> None:
    cyclic_list = []
    cyclic_list.append(cyclic_list)
    with pytest.raises(ValueError, match="cyclic JSON sequence"):
        _record(fields={"cycle": cyclic_list})

    cyclic_dict = {}
    cyclic_dict["self"] = cyclic_dict
    with pytest.raises(ValueError, match="cyclic JSON mapping"):
        _record(fields=cyclic_dict)

    shared = {"value": [1, 2]}
    record = _record(fields={"first": shared, "second": shared})
    assert record.to_dict()["fields"] == {
        "first": {"value": [1, 2]},
        "second": {"value": [1, 2]},
    }


@pytest.mark.parametrize("invalid_key", ["", "   ", 1, None])
def test_fields_reject_non_string_empty_or_whitespace_mapping_keys(invalid_key) -> None:
    with pytest.raises((TypeError, ValueError)):
        _record(fields={invalid_key: "value"})


@pytest.mark.parametrize(
    "invalid",
    [math.nan, math.inf, -math.inf, b"bytes", {1, 2}, object()],
)
def test_fields_reject_non_json_or_non_finite_values(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        _record(fields={"invalid": invalid})


def test_supported_identities_and_project_enums_are_explicitly_encoded() -> None:
    record = _record(
        fields={
            "program": PROGRAM_ID,
            "request": REQUEST_ID,
            "prefix": PREFIX_ID,
            "block": BlockIdentity(7),
            "input_source": InputSource.EXTERNAL,
            "lifecycle": LifecycleEventType.TOOL_GAP_STARTED,
            "retention_mode": RetentionMode.CONTROLLED,
            "scheduler_mode": SchedulerMode.SHADOW,
            "ttl_history": TTLHistoryMode.GLOBAL,
            "tier": EligibilityTier.TIER_2,
            "log_event": StructuredLogEvent.BLOCK_EVICTED,
        }
    )

    assert record.to_dict()["fields"] == {
        "block": 7,
        "input_source": "EXTERNAL",
        "lifecycle": "TOOL_GAP_STARTED",
        "log_event": "BLOCK_EVICTED",
        "prefix": "prefix-1",
        "program": "program-1",
        "request": "request-1",
        "retention_mode": "controlled",
        "scheduler_mode": "shadow",
        "tier": 1,
        "ttl_history": "global",
    }


def test_unknown_enum_is_rejected_instead_of_generically_serialized() -> None:
    class UnknownEnum(str, Enum):
        VALUE = "value"

    with pytest.raises(TypeError, match="unsupported JSON enum type"):
        _record(fields={"unknown": UnknownEnum.VALUE})


def test_direct_frozen_json_object_construction_cannot_bypass_validation() -> None:
    with pytest.raises(TypeError, match="entries must be tuple"):
        FrozenJsonObject([])
    with pytest.raises(ValueError, match="must not be empty"):
        FrozenJsonObject(((" ", 1),))
    with pytest.raises(ValueError, match="lexical order"):
        FrozenJsonObject((("z", 1), ("a", 2)))
    with pytest.raises(TypeError, match="unsupported frozen JSON value type"):
        FrozenJsonObject((("bad", object()),))


def test_json_is_deterministic_across_mapping_insertion_order() -> None:
    first = _record(fields={"z": 1, "a": {"y": 2, "b": 3}})
    second = _record(fields={"a": {"b": 3, "y": 2}, "z": 1})

    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json()) == first.to_dict()


def test_records_and_sink_snapshots_are_immutable() -> None:
    record = _record()
    sink = InMemoryEventSink()
    sink.emit(record)
    snapshot = sink.snapshot()

    assert isinstance(sink, StructuredEventSink)
    assert snapshot == (record,)
    with pytest.raises(FrozenInstanceError):
        record.timestamp = 2.0
    with pytest.raises(AttributeError):
        snapshot.append(record)
    assert sink.snapshot() == (record,)


def test_null_sink_discards_any_value_and_memory_sink_rejects_other_values() -> None:
    null_sink = NullEventSink()
    memory_sink = InMemoryEventSink()

    assert isinstance(null_sink, StructuredEventSink)
    assert null_sink.emit(_record()) is None
    assert null_sink.emit("anything") is None
    with pytest.raises(TypeError, match="record must be StructuredLogRecord"):
        memory_sink.emit("not a record")


def test_logging_module_import_has_no_runtime_side_effects() -> None:
    script = """
import logging
import os
import sys

handlers_before = tuple(logging.getLogger().handlers)
environment_before = dict(os.environ)
import kvopt.continuum.logging
assert tuple(logging.getLogger().handlers) == handlers_before
assert dict(os.environ) == environment_before
assert "kvopt.runtime.vllm.observer" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
