from kvopt.profiling.phase2g_a2_fidelity import (
    _program_completion_checks,
    _slot_reuse_proved,
)


def test_slot_reuse_requires_eviction_between_different_content() -> None:
    events = [
        {
            "event_index": 1,
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "payload": {
                "block_ids": [7],
                "ordered_native_cache_keys": ["old"],
            },
        },
        {
            "event_index": 2,
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {"block_id": 7, "native_cache_key_before": "old"},
        },
        {
            "event_index": 3,
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "payload": {
                "block_ids": [7],
                "ordered_native_cache_keys": ["new"],
            },
        },
    ]

    assert _slot_reuse_proved(events) is True


def test_slot_reuse_rejects_same_content_or_missing_eviction() -> None:
    same_content = [
        {
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "payload": {"block_ids": [7], "ordered_native_cache_keys": ["same"]},
        },
        {
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {"block_id": 7, "native_cache_key_before": "same"},
        },
        {
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "payload": {"block_ids": [7], "ordered_native_cache_keys": ["same"]},
        },
    ]
    no_eviction = [same_content[0], {**same_content[2], "payload": {
        "block_ids": [7], "ordered_native_cache_keys": ["new"]
    }}]

    assert _slot_reuse_proved(same_content) is False
    assert _slot_reuse_proved(no_eviction) is False


def test_program_completion_requires_inactive_chain_without_stale_cost() -> None:
    decisions = [
        {
            "chain_states": [
                {"chain_id": "done:p", "reuse_weight_state": "INACTIVE"},
                {"chain_id": "live:p", "reuse_weight_state": "KNOWN"},
            ],
            "effective_chain_lengths": {"live:p": 4},
            "decision_reuse_weights": {"live:p": 0.5},
        }
    ]

    assert _program_completion_checks(decisions) == {
        "completed_chain_marked_inactive": True,
        "active_peer_reuse_preserved": True,
        "completed_chain_stale_weight_absent": True,
    }


def test_program_completion_rejects_stale_weight_for_inactive_chain() -> None:
    decisions = [
        {
            "chain_states": [
                {"chain_id": "done:p", "reuse_weight_state": "INACTIVE"},
                {"chain_id": "live:p", "reuse_weight_state": "KNOWN"},
            ],
            "effective_chain_lengths": {"done:p": 4, "live:p": 4},
            "decision_reuse_weights": {"done:p": 0.2, "live:p": 0.5},
        }
    ]

    assert _program_completion_checks(decisions)[
        "completed_chain_stale_weight_absent"
    ] is False
