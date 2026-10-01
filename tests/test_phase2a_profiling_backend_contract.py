from __future__ import annotations

import pytest

from scripts.spikes.phase2_minimal_observability_metal import (
    _expected_profiling_block_override,
    _program_prefix_sizes,
    _turn_token_ids,
)
from kvopt.workload.phase2 import PlannedRequest


def test_expected_block_budget_matches_controlled_scarcity_rule() -> None:
    assert _expected_profiling_block_override(
        {"agent-a": 256, "agent-b": 256}, 512
    ) == 64
    assert _expected_profiling_block_override(
        {"agent-a": 128, "agent-b": 256}, 512
    ) == 56
    assert _expected_profiling_block_override(
        {"agent-a": 256, "agent-b": 512}, 512
    ) == 80


def test_program_prefix_sizes_accept_only_measured_points() -> None:
    assert _program_prefix_sizes({
        "program_prefix_tokens": {"agent-a": 128, "agent-b": 512}
    }) == {"agent-a": 128, "agent-b": 512}

    with pytest.raises(ValueError, match="one of 128, 256, 512"):
        _program_prefix_sizes({
            "program_prefix_tokens": {"agent-a": 192}
        })


def test_materialized_turn_uses_requested_prefix_size() -> None:
    request = PlannedRequest(
        program_id="agent-a",
        request_id="agent-a:turn:1",
        turn_index=1,
        planned_arrival_offset_seconds=0.0,
        prompt="logical prompt",
        prefix_prompt="logical prefix",
        is_terminal=False,
        next_tool_type="search",
        tool_gap_seconds=1.0,
    )

    token_ids = _turn_token_ids(
        request,
        vocabulary_size=50_000,
        prefix_tokens=128,
    )

    assert len(token_ids) == 129
    assert len(set(token_ids[:128])) == 128
