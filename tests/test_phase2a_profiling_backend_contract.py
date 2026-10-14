from __future__ import annotations

import pytest

from kvopt.continuum import RetentionMode
from kvopt.workload.phase2 import PlannedRequest
from scripts.spikes.phase2_minimal_observability_metal import (
    _expected_profiling_block_override,
    _pressure_stage_sizes,
    _program_prefix_sizes,
    _required_max_model_len,
    _retention_mode_for_config,
    _turn_token_ids,
)


def test_phase2e_can_select_real_native_or_continuum_baseline() -> None:
    common = {"campaign_kind": "phase2e_non_holdout_research_discovery"}

    assert _retention_mode_for_config({**common, "policy": "native-lru"}) is (
        RetentionMode.NATIVE
    )
    assert _retention_mode_for_config(
        {**common, "policy": "continuum-baseline"}
    ) is RetentionMode.CONTROLLED


def test_native_lru_switch_is_restricted_to_phase2e() -> None:
    with pytest.raises(ValueError, match="restricted to Phase 2E"):
        _retention_mode_for_config({"policy": "native-lru"})


def test_legacy_config_keeps_controlled_retention_default() -> None:
    assert _retention_mode_for_config({"policy": "continuum-baseline"}) is (
        RetentionMode.CONTROLLED
    )


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
    assert _expected_profiling_block_override(
        {"agent-a": 128, "agent-b": 256, "agent-c": 512},
        512,
        20,
    ) == 69


def test_program_prefix_sizes_accept_h2_grid_points_only_when_aligned() -> None:
    assert _program_prefix_sizes({
        "program_prefix_tokens": {"agent-a": 192, "agent-b": 30_720}
    }) == {"agent-a": 192, "agent-b": 30_720}

    with pytest.raises(ValueError, match="align to the KV block size"):
        _program_prefix_sizes({
            "program_prefix_tokens": {"agent-a": 191}
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


def test_pressure_stage_sizes_accept_aligned_overrides() -> None:
    assert _pressure_stage_sizes({
        "pressure_stage_prompt_tokens": {
            "pressure-1": 256,
            "pressure-2": 512,
        }
    }) == {"pressure-1": 256, "pressure-2": 512}

    with pytest.raises(ValueError, match="align to the KV block size"):
        _pressure_stage_sizes({
            "pressure_stage_prompt_tokens": {"pressure-1": 255}
        })


def test_max_model_len_covers_largest_pressure_stage() -> None:
    assert _required_max_model_len(
        {"agent-a": 256, "agent-b": 512},
        512,
        {"pressure-1": 512},
        1,
    ) == 528
    assert _required_max_model_len(
        {"agent-a": 256, "agent-b": 512},
        512,
        {"pressure-1": 512, "pressure-2": 768},
        1,
    ) == 784
