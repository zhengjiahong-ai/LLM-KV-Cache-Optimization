import math
from dataclasses import FrozenInstanceError

import pytest

from kvopt.continuum import (
    BlockIdentity,
    ExternalToolDurationRecord,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    ServerInterRequestGapRecord,
)


@pytest.mark.parametrize(
    ("identity_type", "field_name"),
    [
        (ProgramIdentity, "value"),
        (RequestIdentity, "value"),
        (PrefixIdentity, "canonical_value"),
    ],
)
def test_text_identities_are_non_empty_immutable_and_hashable(identity_type, field_name) -> None:
    identity = identity_type("stable-id")

    assert hash(identity) == hash(identity_type("stable-id"))
    with pytest.raises(FrozenInstanceError):
        setattr(identity, field_name, "changed")
    with pytest.raises(ValueError, match="must not be empty"):
        identity_type("")
    with pytest.raises(ValueError, match="must not be empty"):
        identity_type("   ")
    with pytest.raises(TypeError, match="must be str"):
        identity_type(123)


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "1"])
def test_block_identity_rejects_invalid_physical_ids(invalid) -> None:
    expected_error = ValueError if invalid == -1 else TypeError

    with pytest.raises(expected_error):
        BlockIdentity(invalid)


def test_input_source_contains_exactly_the_five_frozen_categories() -> None:
    assert {source.value for source in InputSource} == {
        "NATIVE",
        "OBSERVED",
        "EXTERNAL",
        "APPROXIMATED",
        "UNAVAILABLE",
    }


@pytest.mark.parametrize("source", [InputSource.APPROXIMATED, InputSource.UNAVAILABLE])
def test_provenance_requires_reason_for_non_direct_sources(source) -> None:
    with pytest.raises(ValueError, match="reason is required"):
        InputProvenance(source)

    provenance = InputProvenance(source, reason="explicit reason")
    assert provenance.reason == "explicit reason"


def test_provenance_rejects_untyped_source_and_empty_reason() -> None:
    with pytest.raises(TypeError, match="source must be InputSource"):
        InputProvenance("OBSERVED")
    with pytest.raises(ValueError, match="reason must not be empty"):
        InputProvenance(InputSource.OBSERVED, reason=" ")


def test_server_gap_record_derives_duration_and_fixes_source() -> None:
    record = ServerInterRequestGapRecord(
        program_id=ProgramIdentity("program-1"),
        previous_request_id=RequestIdentity("request-1"),
        next_request_id=RequestIdentity("request-2"),
        previous_finish_timestamp=10,
        next_arrival_timestamp=12.5,
        tool_type="search",
    )

    assert record.previous_finish_timestamp == 10.0
    assert record.next_arrival_timestamp == 12.5
    assert record.duration_seconds == 2.5
    assert record.source is InputSource.OBSERVED


def test_external_duration_record_derives_duration_and_fixes_source() -> None:
    record = ExternalToolDurationRecord(
        program_id=ProgramIdentity("program-1"),
        tool_type="search",
        start_timestamp=20,
        end_timestamp=20,
    )

    assert record.duration_seconds == 0.0
    assert record.source is InputSource.EXTERNAL


def test_completed_duration_records_are_immutable_and_hashable() -> None:
    server_record = ServerInterRequestGapRecord(
        program_id=ProgramIdentity("program-1"),
        previous_request_id=RequestIdentity("request-1"),
        next_request_id=RequestIdentity("request-2"),
        previous_finish_timestamp=1.0,
        next_arrival_timestamp=2.0,
    )
    external_record = ExternalToolDurationRecord(
        program_id=ProgramIdentity("program-1"),
        tool_type="search",
        start_timestamp=1.0,
        end_timestamp=2.0,
    )

    assert isinstance(hash(server_record), int)
    assert isinstance(hash(external_record), int)
    with pytest.raises(FrozenInstanceError):
        server_record.next_arrival_timestamp = 3.0
    with pytest.raises(FrozenInstanceError):
        external_record.end_timestamp = 3.0


@pytest.mark.parametrize("field_name", ["start_timestamp", "end_timestamp"])
@pytest.mark.parametrize(
    "invalid",
    [-1.0, math.inf, -math.inf, math.nan, True, "1.0", 10**400],
)
def test_external_duration_rejects_invalid_timestamps(field_name, invalid) -> None:
    timestamps = {"start_timestamp": 1.0, "end_timestamp": 2.0}
    timestamps[field_name] = invalid

    with pytest.raises((TypeError, ValueError)):
        ExternalToolDurationRecord(
            program_id=ProgramIdentity("program-1"),
            tool_type="search",
            **timestamps,
        )


@pytest.mark.parametrize(
    "field_name",
    ["previous_finish_timestamp", "next_arrival_timestamp"],
)
@pytest.mark.parametrize(
    "invalid",
    [-1.0, math.inf, -math.inf, math.nan, True, "1.0", 10**400],
)
def test_server_gap_rejects_invalid_timestamps(field_name, invalid) -> None:
    timestamps = {
        "previous_finish_timestamp": 1.0,
        "next_arrival_timestamp": 2.0,
    }
    timestamps[field_name] = invalid

    with pytest.raises((TypeError, ValueError)):
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity("program-1"),
            previous_request_id=RequestIdentity("request-1"),
            next_request_id=RequestIdentity("request-2"),
            **timestamps,
        )


def test_duration_records_reject_reversed_time_ranges() -> None:
    with pytest.raises(ValueError, match="must not precede"):
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity("program-1"),
            previous_request_id=RequestIdentity("request-1"),
            next_request_id=RequestIdentity("request-2"),
            previous_finish_timestamp=2.0,
            next_arrival_timestamp=1.0,
        )
    with pytest.raises(ValueError, match="must not precede"):
        ExternalToolDurationRecord(
            program_id=ProgramIdentity("program-1"),
            tool_type="search",
            start_timestamp=2.0,
            end_timestamp=1.0,
        )


def test_duration_records_enforce_runtime_identity_types() -> None:
    with pytest.raises(TypeError, match="program_id must be ProgramIdentity"):
        ServerInterRequestGapRecord(
            program_id=RequestIdentity("request-1"),
            previous_request_id=RequestIdentity("request-1"),
            next_request_id=RequestIdentity("request-2"),
            previous_finish_timestamp=1.0,
            next_arrival_timestamp=2.0,
        )
    with pytest.raises(TypeError, match="previous_request_id must be RequestIdentity"):
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity("program-1"),
            previous_request_id=ProgramIdentity("program-1"),
            next_request_id=RequestIdentity("request-2"),
            previous_finish_timestamp=1.0,
            next_arrival_timestamp=2.0,
        )
    with pytest.raises(TypeError, match="next_request_id must be RequestIdentity"):
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity("program-1"),
            previous_request_id=RequestIdentity("request-1"),
            next_request_id=ProgramIdentity("program-1"),
            previous_finish_timestamp=1.0,
            next_arrival_timestamp=2.0,
        )
    with pytest.raises(TypeError, match="program_id must be ProgramIdentity"):
        ExternalToolDurationRecord(
            program_id=RequestIdentity("request-1"),
            tool_type="search",
            start_timestamp=1.0,
            end_timestamp=2.0,
        )


@pytest.mark.parametrize("tool_type", ["", "   ", 1])
def test_duration_records_validate_tool_type(tool_type) -> None:
    with pytest.raises((TypeError, ValueError)):
        ExternalToolDurationRecord(
            program_id=ProgramIdentity("program-1"),
            tool_type=tool_type,
            start_timestamp=1.0,
            end_timestamp=2.0,
        )
    with pytest.raises((TypeError, ValueError)):
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity("program-1"),
            previous_request_id=RequestIdentity("request-1"),
            next_request_id=RequestIdentity("request-2"),
            previous_finish_timestamp=1.0,
            next_arrival_timestamp=2.0,
            tool_type=tool_type,
        )


def test_duration_record_sources_cannot_be_supplied_by_callers() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'source'"):
        ExternalToolDurationRecord(
            program_id=ProgramIdentity("program-1"),
            tool_type="search",
            start_timestamp=1.0,
            end_timestamp=2.0,
            source=InputSource.OBSERVED,
        )
    with pytest.raises(TypeError, match="unexpected keyword argument 'source'"):
        ServerInterRequestGapRecord(
            program_id=ProgramIdentity("program-1"),
            previous_request_id=RequestIdentity("request-1"),
            next_request_id=RequestIdentity("request-2"),
            previous_finish_timestamp=1.0,
            next_arrival_timestamp=2.0,
            source=InputSource.EXTERNAL,
        )


def test_server_and_external_duration_records_remain_distinct_types() -> None:
    server_record = ServerInterRequestGapRecord(
        program_id=ProgramIdentity("program-1"),
        previous_request_id=RequestIdentity("request-1"),
        next_request_id=RequestIdentity("request-2"),
        previous_finish_timestamp=1.0,
        next_arrival_timestamp=2.0,
    )
    external_record = ExternalToolDurationRecord(
        program_id=ProgramIdentity("program-1"),
        tool_type="search",
        start_timestamp=1.0,
        end_timestamp=2.0,
    )

    assert type(server_record) is not type(external_record)
