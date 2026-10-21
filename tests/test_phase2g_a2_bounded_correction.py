from kvopt.profiling.phase2g_a2_bounded_correction import (
    HASHLESS,
    _candidate_semantics,
    _decision_semantics,
    _semantic_set,
)


def test_semantic_identity_does_not_depend_on_physical_block_id() -> None:
    a0 = _candidate_semantics({"candidates": [{"program_id": "p", "block_ids": [7, 8]}]})
    a2 = _decision_semantics(
        {
            "block_memberships": [
                {
                    "block_id": 41,
                    "memberships": [{"chain_id": "p:native-prefix-a", "depth": 1}],
                },
                {
                    "block_id": 42,
                    "memberships": [{"chain_id": "p:native-prefix-b", "depth": 2}],
                },
            ],
            "legal_content_hashes": [
                {"block_id": 41, "content_hash": "hash-a"},
                {"block_id": 42, "content_hash": "hash-b"},
            ],
        }
    )

    assert _semantic_set([7, 8], a0) == _semantic_set([41, 42], a2)


def test_hashless_candidate_is_explicit_not_unknown() -> None:
    state = _decision_semantics(
        {
            "block_memberships": [{"block_id": 9, "memberships": []}],
            "legal_content_hashes": [{"block_id": 9, "content_hash": None}],
        }
    )

    assert state[9] == HASHLESS
    assert _semantic_set([9], state) == [HASHLESS]


def test_missing_membership_remains_unobservable() -> None:
    assert _semantic_set([99], {}) is None
