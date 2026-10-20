from kvopt.profiling.phase2g_a2_fidelity import _slot_reuse_proved


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
