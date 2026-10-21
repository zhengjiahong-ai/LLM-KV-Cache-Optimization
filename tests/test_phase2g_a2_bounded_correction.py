from kvopt.profiling.phase2g_a2_bounded_correction import (
    HASHLESS,
    _a2_decisions,
    _candidate_semantics,
    _decision_semantics,
    _forced_rows,
    _semantic_set,
    _semantic_state,
)


def test_semantic_identity_does_not_depend_on_physical_block_id() -> None:
    a0 = _candidate_semantics({"candidates": [{"program_id": "p", "block_ids": [7, 8]}]})
    payload = {
        "block_memberships": [
            {
                "block_id": 41,
                "memberships": [
                    {"chain_id": "p:native-prefix-a", "depth": 1, "content_hash": "hash-a"}
                ],
            },
            {
                "block_id": 42,
                "memberships": [
                    {"chain_id": "p:native-prefix-b", "depth": 2, "content_hash": "hash-b"}
                ],
            },
        ],
        "legal_content_hashes": [
            {"block_id": 41, "content_hash": "hash-a"},
            {"block_id": 42, "content_hash": "hash-b"},
        ],
    }
    a2 = _decision_semantics(
        payload,
        {
            "original_free_queue": [
                {"block_id": 41, "has_block_hash": True},
                {"block_id": 42, "has_block_hash": True},
            ]
        },
    )

    assert _semantic_set([7, 8], a0) == _semantic_set([41, 42], a2)


def test_hashless_candidate_is_explicit_not_unknown() -> None:
    state = _decision_semantics(
        {
            "block_memberships": [{"block_id": 9, "memberships": []}],
            "legal_content_hashes": [{"block_id": 9, "content_hash": None}],
        },
        {"original_free_queue": [{"block_id": 9, "has_block_hash": False}]},
    )

    assert state[9] == HASHLESS
    assert _semantic_set([9], state) == [HASHLESS]


def test_missing_membership_remains_unobservable() -> None:
    assert _semantic_set([99], {}) is None


def test_hashed_but_unverified_is_not_treated_as_hashless() -> None:
    state = _decision_semantics(
        {
            "block_memberships": [{"block_id": 9, "memberships": []}],
            "legal_content_hashes": [{"block_id": 9, "content_hash": None}],
        },
        {"original_free_queue": [{"block_id": 9, "has_block_hash": True}]},
    )

    assert 9 not in state


def test_slot_reuse_does_not_keep_old_membership() -> None:
    states = _semantic_state(
        [
            {
                "event_index": 1,
                "event_type": "VLLM_PREFIX_SNAPSHOT",
                "program_id": "old",
                "payload": {
                    "block_ids": [7],
                    "ordered_native_cache_keys": ["old-hash"],
                },
            },
            {
                "event_index": 2,
                "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                "payload": {"block_id": 7},
            },
            {
                "event_index": 3,
                "event_type": "VLLM_PREFIX_SNAPSHOT",
                "program_id": "new",
                "payload": {
                    "block_ids": [7],
                    "ordered_native_cache_keys": ["new-hash"],
                },
            },
            {"event_index": 4, "event_type": "OTHER", "payload": {}},
        ]
    )

    assert states[4][7] == (("new", 0),)


def test_actual_a0_selection_uses_selected_event_and_excludes_protected() -> None:
    queue = [
        {"block_id": 1, "eligibility_tier": None, "has_block_hash": True, "native_lru_rank": 0},
        {"block_id": 2, "eligibility_tier": 1, "has_block_hash": True, "native_lru_rank": 1},
        {"block_id": 3, "eligibility_tier": 0, "has_block_hash": False, "native_lru_rank": 2},
    ]
    events = [
        {
            "event_index": 1,
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "program_id": "p",
            "payload": {
                "block_ids": [1, 2],
                "ordered_native_cache_keys": ["hash-1", "hash-2"],
            },
        },
        {
            "event_index": 2,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "required_blocks": 2,
                "original_free_queue": queue,
                "selected_releases": [],
                "candidates": [{"program_id": "p", "block_ids": [1, 2]}],
            },
        },
        {
            "event_index": 3,
            "event_type": "PRESSURE_REQUEST_COMPLETED",
            "payload": {"last_selected_block_ids": [3, 2]},
        },
    ]

    row = _forced_rows(events, policy="A0")[0]

    assert row["selection_observable"] is True
    assert row["actual_selected_block_count"] == 2
    assert row["actual_victim_semantics"] == [HASHLESS, (("p", 1),)]


def test_actual_a0_selection_rejects_protected_selected_block() -> None:
    events = [
        {
            "event_index": 1,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "required_blocks": 1,
                "original_free_queue": [
                    {
                        "block_id": 1,
                        "eligibility_tier": None,
                        "has_block_hash": True,
                        "native_lru_rank": 0,
                    },
                    {
                        "block_id": 2,
                        "eligibility_tier": 1,
                        "has_block_hash": True,
                        "native_lru_rank": 1,
                    },
                ],
                "selected_releases": [],
                "candidates": [{"program_id": "p", "block_ids": [1, 2]}],
            },
        },
        {
            "event_index": 2,
            "event_type": "PRESSURE_REQUEST_COMPLETED",
            "payload": {"last_selected_block_ids": [1]},
        },
    ]

    row = _forced_rows(events, policy="A0")[0]

    assert row["selection_observable"] is False
    assert row["unobservable_reasons"] == ["selected_blocks_do_not_match_tier_aware_lru"]


def test_full_a2_path_does_not_fallback_to_candidate_membership() -> None:
    events = [
        {
            "event_index": 1,
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "required_blocks": 1,
                "selected_releases": [],
                "candidates": [{"program_id": "p", "block_ids": [7]}],
                "original_free_queue": [
                    {
                        "block_id": 7,
                        "eligibility_tier": 1,
                        "has_block_hash": True,
                        "native_lru_rank": 0,
                    }
                ],
            },
        },
        {
            "event_index": 2,
            "event_type": "COST_AWARE_BLOCK_DECISION",
            "payload": {
                "required_blocks": 1,
                "legal_block_ids": [7],
                "selected_victims": [7],
                "native_lru_victims": [7],
                "legal_content_hashes": [{"block_id": 7, "content_hash": None}],
                "block_memberships": [
                    {
                        "block_id": 7,
                        "memberships": [
                            {
                                "chain_id": "p:logical-chain",
                                "depth": 1,
                                "content_hash": None,
                            }
                        ],
                    }
                ],
                "selector": "native_lru_fallback",
                "fallbacks": ["content_unverified"],
            },
        },
    ]

    rows, ordinary = _a2_decisions(events)

    assert ordinary == 0
    assert rows[0]["legal_semantics"] is None
    assert rows[0]["selected_semantics"] is None
    assert rows[0]["internal_lru_semantics"] is None
