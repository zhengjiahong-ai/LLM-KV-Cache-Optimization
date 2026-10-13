from kvopt.workload.phase2 import PlannedRequest
from kvopt.workload.phase2b_fidelity import (
    phase2b_turn_token_ids,
    prefix_content_token_ids,
    token_ids_sha256,
    validate_distinct_content_keys,
)
from scripts.spikes.phase2_minimal_observability_metal import (
    _phase2b_content_keys,
)

VOCABULARY_SIZE = 151_936


def _request(program: str, request_id: str) -> PlannedRequest:
    return PlannedRequest(
        program_id=program,
        request_id=request_id,
        turn_index=1,
        planned_arrival_offset_seconds=0.0,
        prompt="prompt",
        prefix_prompt="prefix",
        is_terminal=True,
        next_tool_type=None,
        tool_gap_seconds=None,
    )


def test_same_content_key_is_program_independent_and_length_stable() -> None:
    short = prefix_content_token_ids(
        "shared-group-0", vocabulary_size=VOCABULARY_SIZE, token_count=128
    )
    long = prefix_content_token_ids(
        "shared-group-0", vocabulary_size=VOCABULARY_SIZE, token_count=256
    )

    assert short == long[:128]
    assert len(short) == 128


def test_request_suffix_does_not_change_shared_prefix() -> None:
    first = phase2b_turn_token_ids(
        _request("agent-a", "agent-a:turn:1"),
        content_key="shared-group-0",
        vocabulary_size=VOCABULARY_SIZE,
        prefix_tokens=256,
    )
    second = phase2b_turn_token_ids(
        _request("agent-b", "agent-b:turn:1"),
        content_key="shared-group-0",
        vocabulary_size=VOCABULARY_SIZE,
        prefix_tokens=256,
    )

    assert first[:256] == second[:256]
    assert first[-1] != second[-1]
    assert token_ids_sha256(first[:256]) == token_ids_sha256(second[:256])


def test_different_content_keys_have_distinct_first_native_block() -> None:
    left = prefix_content_token_ids(
        "shared-group-0", vocabulary_size=VOCABULARY_SIZE, token_count=16
    )
    right = prefix_content_token_ids(
        "exclusive-agent-c", vocabulary_size=VOCABULARY_SIZE, token_count=16
    )

    assert left != right
    validate_distinct_content_keys(
        ("shared-group-0", "exclusive-agent-c"),
        vocabulary_size=VOCABULARY_SIZE,
        block_size=16,
    )


def test_legacy_mode_does_not_accept_phase2b_fields_without_opt_in() -> None:
    options = {
        "prefix_content_key_by_program": {"agent-a": "shared"},
        "prefix_generator_version": "phase2b-prefix-v1",
    }

    try:
        _phase2b_content_keys(options)
    except ValueError as error:
        assert "phase2b_fidelity_mode" in str(error)
    else:
        raise AssertionError("Phase 2B fields silently entered legacy mode")
