from __future__ import annotations

import pytest

from kvopt.continuum import RetentionMode
from kvopt.workload.phase2 import PlannedRequest
from scripts.spikes.phase2_minimal_observability_metal import (
    _expected_profiling_block_override,
    _phase2g_a1_campaign_allowed,
    _phase2g_a2_campaign_allowed,
    _phase2g_unique_protected_block_campaign_allowed,
    _pressure_stage_sizes,
    _program_prefix_sizes,
    _required_max_model_len,
    _retention_mode_for_config,
    _turn_token_ids,
    _validate_formal_profile_cache_capacity,
)


def test_phase2h_campaign_is_exactly_allowlisted_for_a1_and_a2() -> None:
    campaign = "phase2h_history_rich_native_smoke"
    assert _phase2g_a1_campaign_allowed(campaign)
    assert _phase2g_a2_campaign_allowed(campaign)


@pytest.mark.parametrize(
    "campaign",
    ["phase2h_history_rich", "phase2h_history_rich_native", "phase2h-smoke"],
)
def test_similar_phase2h_names_are_not_policy_allowlisted(campaign: str) -> None:
    assert not _phase2g_a1_campaign_allowed(campaign)
    assert not _phase2g_a2_campaign_allowed(campaign)


@pytest.mark.parametrize(
    "campaign_kind",
    ["phase2g_a2_native_gate1", "phase2g_a2_gate2_bounded_evaluation"],
)
def test_a2_block_policy_accepts_only_authorized_campaigns(campaign_kind: str) -> None:
    assert _phase2g_a2_campaign_allowed(campaign_kind)


@pytest.mark.parametrize(
    "campaign_kind",
    [None, "formal", "phase2g_a1_bounded_evaluation", "phase2e_measured_campaign"],
)
def test_a2_block_policy_rejects_other_campaigns(campaign_kind: object) -> None:
    assert not _phase2g_a2_campaign_allowed(campaign_kind)


@pytest.mark.parametrize(
    "campaign_kind",
    [
        "phase2g_a1_bounded_evaluation",
        "phase2g_a2_native_gate1",
        "phase2g_a2_gate2_bounded_evaluation",
    ],
)
def test_unique_protected_blocks_accept_authorized_campaigns(campaign_kind: str) -> None:
    assert _phase2g_unique_protected_block_campaign_allowed(campaign_kind)


def test_unique_protected_blocks_reject_unrelated_campaign() -> None:
    assert not _phase2g_unique_protected_block_campaign_allowed("formal")


def test_phase2e_can_select_real_native_or_continuum_baseline() -> None:
    common = {"campaign_kind": "phase2e_non_holdout_research_discovery"}

    assert _retention_mode_for_config({**common, "policy": "native-lru"}) is (RetentionMode.NATIVE)
    assert (
        _retention_mode_for_config({**common, "policy": "continuum-baseline"})
        is RetentionMode.CONTROLLED
    )


def test_native_lru_switch_is_restricted_to_phase2e() -> None:
    with pytest.raises(ValueError, match="restricted to Phase 2E"):
        _retention_mode_for_config({"policy": "native-lru"})


def test_legacy_config_keeps_controlled_retention_default() -> None:
    assert _retention_mode_for_config({"policy": "continuum-baseline"}) is (
        RetentionMode.CONTROLLED
    )


def test_expected_block_budget_matches_controlled_scarcity_rule() -> None:
    assert _expected_profiling_block_override({"agent-a": 256, "agent-b": 256}, 512) == 64
    assert _expected_profiling_block_override({"agent-a": 128, "agent-b": 256}, 512) == 56
    assert _expected_profiling_block_override({"agent-a": 256, "agent-b": 512}, 512) == 80
    assert (
        _expected_profiling_block_override(
            {"agent-a": 128, "agent-b": 256, "agent-c": 512},
            512,
            20,
        )
        == 69
    )


def test_formal_profile_uses_full_runtime_pool_with_reachable_eviction() -> None:
    _validate_formal_profile_cache_capacity(
        block_override=2048,
        max_model_len=32768,
        program_prefix_tokens={"formal-profile": 1024},
        pressure_tokens=512,
        maximum_pressure_requests=64,
    )

    with pytest.raises(ValueError, match="max-model-length runtime pool"):
        _validate_formal_profile_cache_capacity(
            block_override=96,
            max_model_len=32768,
            program_prefix_tokens={"formal-profile": 1024},
            pressure_tokens=512,
            maximum_pressure_requests=64,
        )

    with pytest.raises(ValueError, match="cannot evict"):
        _validate_formal_profile_cache_capacity(
            block_override=2048,
            max_model_len=32768,
            program_prefix_tokens={"formal-profile": 1024},
            pressure_tokens=512,
            maximum_pressure_requests=1,
        )
    assert (
        _expected_profiling_block_override(
            {"agent-a": 256, "agent-b": 256},
            320,
            4,
            protected_prefix_blocks_override=20,
        )
        == 37
    )


def test_program_prefix_sizes_accept_h2_grid_points_only_when_aligned() -> None:
    assert _program_prefix_sizes(
        {"program_prefix_tokens": {"agent-a": 192, "agent-b": 32_256}}
    ) == {"agent-a": 192, "agent-b": 32_256}

    with pytest.raises(ValueError, match="align to the KV block size"):
        _program_prefix_sizes({"program_prefix_tokens": {"agent-a": 191}})

    with pytest.raises(ValueError, match="between 16 and 32256 tokens"):
        _program_prefix_sizes({"program_prefix_tokens": {"agent-a": 32_272}})


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
    assert _pressure_stage_sizes(
        {
            "pressure_stage_prompt_tokens": {
                "pressure-1": 256,
                "pressure-2": 512,
            }
        }
    ) == {"pressure-1": 256, "pressure-2": 512}

    with pytest.raises(ValueError, match="align to the KV block size"):
        _pressure_stage_sizes({"pressure_stage_prompt_tokens": {"pressure-1": 255}})


def test_max_model_len_covers_largest_pressure_stage() -> None:
    assert (
        _required_max_model_len(
            {"agent-a": 256, "agent-b": 512},
            512,
            {"pressure-1": 512},
            1,
        )
        == 528
    )
    assert (
        _required_max_model_len(
            {"agent-a": 256, "agent-b": 512},
            512,
            {"pressure-1": 512, "pressure-2": 768},
            1,
        )
        == 784
    )


def test_max_model_len_accepts_only_pressure_prompt_candidate() -> None:
    assert _required_max_model_len({}, 512, {}, 1) == 528
