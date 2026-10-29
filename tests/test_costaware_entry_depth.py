"""Tests for the Phase 2I chain depth proof: identity, freshness, and drift.

Coverage required by M1 (section B of the implementation authorisation):

- middle-block eviction does not drift depth;
- block id recycling and content change;
- cross-chain and cross-process queries;
- future and stale proofs;
- missing or mismatched content hashes;
- latest valid snapshot and full chain length;
- a single unresolvable candidate makes the whole decision fall back
  (the strategy-level half of that requirement lives in
  ``test_costaware_a3_suffix.py``).
"""

from __future__ import annotations

import pytest

from kvopt.costaware.entry_depth import (
    DEFAULT_MAX_AGE_SECONDS,
    ChainDepthIndex,
    ChainDepthProof,
    DepthQuery,
    DepthStatus,
    DepthVerificationMode,
    index_from_events,
)

CHAIN = ("proj__repo-1", "prefix-a")
PROCESS = "pid-1299"


def _proof(
    block_ids: tuple[int, ...] = (10, 11, 12, 13),
    *,
    chain_id: tuple[str, str] = CHAIN,
    process_id: str = PROCESS,
    observation_index: int = 5,
    observed_at: float = 100.0,
    clock_domain: str = "system_monotonic",
    content_hashes: tuple[str, ...] | None = None,
) -> ChainDepthProof:
    hashes = (
        tuple(f"key-{block_id}" for block_id in block_ids)
        if content_hashes is None
        else content_hashes
    )
    return ChainDepthProof.from_observation(
        chain_id,
        process_id,
        block_ids,
        content_hashes=hashes,
        observation_index=observation_index,
        observed_at=observed_at,
        clock_domain=clock_domain,
    )


def _query(
    *,
    chain_id: tuple[str, str] = CHAIN,
    process_id: str = PROCESS,
    decision_index: int = 50,
    decision_time: float = 150.0,
    decision_clock_domain: str = "system_monotonic",
    expected_observation_index: int | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    verification_mode: DepthVerificationMode = DepthVerificationMode.HISTORICAL_REPLAY,
) -> DepthQuery:
    return DepthQuery(
        chain_id=chain_id,
        native_hash_process_id=process_id,
        decision_index=decision_index,
        decision_time=decision_time,
        decision_clock_domain=decision_clock_domain,
        expected_observation_index=expected_observation_index,
        max_age_seconds=max_age_seconds,
        verification_mode=verification_mode,
    )


# --- depth does not drift --------------------------------------------------


def test_interior_eviction_does_not_drift_depth() -> None:
    """Each survivor keeps its original depth after a hole is left in the chain."""

    proof = _proof(tuple(range(10, 20)))
    query = _query()
    # Depth 3 (block 12) is evicted, so the live entry now holds nine blocks.
    survivors = (10, 11, 13, 14, 15, 16, 17, 18, 19)
    expected = {10: 1, 11: 2, 13: 4, 14: 5, 15: 6, 16: 7, 17: 8, 18: 9, 19: 10}

    for block_id in survivors:
        depth, status = proof.depth_of(query, block_id, f"key-{block_id}")
        assert status is DepthStatus.OK
        assert depth == expected[block_id], f"block {block_id} drifted to {depth}"

    # The check only has teeth if the survivors really differ from their index.
    drifted = [b for b in survivors if expected[b] != survivors.index(b) + 1]
    assert drifted == [13, 14, 15, 16, 17, 18, 19]


def test_chain_length_survives_eviction() -> None:
    """``m`` is the recorded chain length, not the number of live blocks."""

    proof = _proof(tuple(range(10, 20)))
    assert proof.chain_length == 10
    # A live entry after four evictions would report six; the proof must not.
    live = (10, 11, 15, 16, 17, 18, 19)
    assert len(live) != proof.chain_length
    assert proof.chain_length - 1 + 1 == 10


def test_suffix_uses_recorded_length_not_live_count() -> None:
    proof = _proof(tuple(range(10, 20)))
    query = _query()
    victims = (15, 16)
    resolution = proof.resolve(query, victims)
    assert resolution.resolved
    assert resolution.depths == {15: 6, 16: 7}
    d_min = min(resolution.depths.values())
    assert proof.chain_length - d_min + 1 == 5
    # A live-count suffix would be computed from seven blocks and be wrong.
    assert len((10, 11, 15, 16, 17, 18, 19)) - d_min + 1 != 5


# --- recycling and content identity ---------------------------------------


def test_recycled_block_id_cannot_inherit_depth() -> None:
    proof = _proof()
    query = _query()
    # Slot 12 now holds different content.
    depth, status = proof.depth_of(query, 12, "key-something-else")
    assert depth is None
    assert status is DepthStatus.CONTENT_MISMATCH
    # With its recorded content the same slot still resolves.
    assert proof.depth_of(query, 12, "key-12") == (3, DepthStatus.OK)


def test_content_mismatch_is_reported_per_block_not_silently_dropped() -> None:
    proof = _proof()
    query = _query()
    resolution = proof.resolve(query, (10, 12), live_hashes={10: "key-10", 12: "recycled"})
    assert resolution.resolved is False
    assert resolution.depths == {10: 1}
    assert resolution.failures == {12: DepthStatus.CONTENT_MISMATCH}


def test_missing_content_identity_is_unverified_not_trusted() -> None:
    proof = _proof(content_hashes=())
    assert proof.identity_verified is False
    query = _query()
    depth, status = proof.depth_of(query, 10, "anything")
    assert depth is None
    assert status is DepthStatus.IDENTITY_UNVERIFIED
    resolution = proof.resolve(query, (10, 11))
    assert resolution.resolved is False
    assert set(resolution.failures.values()) == {DepthStatus.IDENTITY_UNVERIFIED}


def test_unknown_block_is_reported() -> None:
    proof = _proof()
    depth, status = proof.depth_of(_query(), 999, "key-999")
    assert depth is None
    assert status is DepthStatus.UNKNOWN_BLOCK


# --- identity of chain and process ---------------------------------------


def test_cross_chain_query_is_rejected() -> None:
    proof = _proof()
    depth, status = proof.depth_of(_query(chain_id=("other", "prefix-b")), 10, "key-10")
    assert depth is None
    assert status is DepthStatus.WRONG_CHAIN


def test_cross_process_query_is_rejected() -> None:
    proof = _proof()
    depth, status = proof.depth_of(_query(process_id="pid-other"), 10, "key-10")
    assert depth is None
    assert status is DepthStatus.WRONG_PROCESS


# --- freshness ------------------------------------------------------------


def test_future_observation_is_rejected() -> None:
    proof = _proof(observation_index=50)
    depth, status = proof.depth_of(_query(decision_index=50), 10, "key-10")
    assert depth is None
    assert status is DepthStatus.FUTURE_OBSERVATION


def test_stale_observation_is_rejected_in_the_same_clock_domain() -> None:
    proof = _proof(observed_at=100.0)
    query = _query(decision_time=100.0 + DEFAULT_MAX_AGE_SECONDS + 1.0)
    depth, status = proof.depth_of(query, 10, "key-10")
    assert depth is None
    assert status is DepthStatus.STALE_OBSERVATION


def test_boundary_cases_still_resolve() -> None:
    """Exact-boundary cases must not be rejected; only strictly older is stale."""

    proof = _proof(observed_at=100.0)
    at_zero_age = _query(decision_time=100.0)
    assert proof.depth_of(at_zero_age, 10, "key-10") == (1, DepthStatus.OK)
    at_limit = _query(decision_time=100.0 + DEFAULT_MAX_AGE_SECONDS)
    assert proof.depth_of(at_limit, 10, "key-10") == (1, DepthStatus.OK)


def test_cross_clock_domain_does_not_apply_the_auxiliary_age_check() -> None:
    """Different clock domains make timestamp subtraction meaningless.

    The archive records prefix snapshots on ``system_monotonic`` and forced
    releases on ``continuum_pressure``. Comparing those two numbers would reject
    every proof, so freshness falls back to the binding ordering checks and the
    auxiliary age bound is skipped rather than misapplied.
    """

    proof = _proof(observed_at=49_949_695.0, clock_domain="system_monotonic")
    query = _query(decision_time=158.4, decision_clock_domain="continuum_pressure")
    depth, status = proof.depth_of(query, 10, "key-10")
    assert (depth, status) == (1, DepthStatus.OK)

    # The binding check still applies in the same situation.
    future = _query(
        decision_index=5,
        decision_time=158.4,
        decision_clock_domain="continuum_pressure",
    )
    blocked, blocked_status = proof.depth_of(future, 10, "key-10")
    assert blocked is None
    assert blocked_status is DepthStatus.FUTURE_OBSERVATION


def test_superseded_proof_is_rejected() -> None:
    """A newer observation of the same chain invalidates the older proof."""

    older = _proof(observation_index=5)
    query = _query(expected_observation_index=9)
    depth, status = older.depth_of(query, 10, "key-10")
    assert depth is None
    assert status is DepthStatus.SUPERSEDED
    # Pinned to itself it is still usable.
    assert older.depth_of(_query(expected_observation_index=5), 10, "key-10") == (1, DepthStatus.OK)


# --- index ----------------------------------------------------------------


def test_index_returns_the_latest_observation_before_the_decision() -> None:
    index = ChainDepthIndex()
    index.observe(_proof(block_ids=(10, 11), observation_index=5))
    index.observe(_proof(block_ids=(10, 11, 12), observation_index=20))

    early = index.latest_before(CHAIN, 10)
    assert early is not None
    assert early.observation_index == 5
    late = index.latest_before(CHAIN, 30)
    assert late is not None
    assert late.observation_index == 20
    assert late.chain_length == 3
    # Nothing preceded the first observation.
    assert index.latest_before(CHAIN, 5) is None


def test_index_query_pins_the_current_observation() -> None:
    index = ChainDepthIndex()
    index.observe(_proof(observation_index=5))
    index.observe(_proof(observation_index=20))
    pinned = index.query_for(CHAIN, PROCESS, decision_index=30, decision_time=150.0)
    assert pinned is not None
    proof, query = pinned
    assert query.expected_observation_index == 20
    assert proof.depth_of(query, 10, "key-10") == (1, DepthStatus.OK)
    assert index.query_for(CHAIN, PROCESS, decision_index=1, decision_time=1.0) is None


def test_observations_must_be_appended_in_order() -> None:
    index = ChainDepthIndex()
    index.observe(_proof(observation_index=5))
    with pytest.raises(ValueError):
        index.observe(_proof(observation_index=5))


# --- verification modes (RC1) --------------------------------------------


def test_historical_replay_resolution_is_not_content_verified() -> None:
    """Offline replay may use the recorded identity, but must say so.

    The result is usable for replay and simultaneously flagged as *not* validated
    against current content, so it cannot be reported as native verification.
    """

    proof = _proof()
    resolution = proof.resolve(_query(), (10, 11))
    assert resolution.resolved is True
    assert resolution.depths == {10: 1, 11: 2}
    assert resolution.live_identity_checked is False
    assert resolution.content_verified is False


def test_live_identity_makes_a_resolution_content_verified() -> None:
    proof = _proof()
    resolution = proof.resolve(
        _query(),
        (10, 11),
        live_hashes={10: "key-10", 11: "key-11"},
    )
    assert resolution.content_verified is True


def test_native_live_mode_requires_live_identity() -> None:
    """A recorded proof is not a substitute for the slots' current content."""

    proof = _proof()
    resolution = proof.resolve(
        _query(verification_mode=DepthVerificationMode.NATIVE_LIVE),
        (10, 11),
    )
    assert resolution.resolved is False
    assert resolution.content_verified is False
    assert set(resolution.failures.values()) == {DepthStatus.LIVE_IDENTITY_REQUIRED}


def test_native_live_mode_rejects_a_partially_supplied_identity() -> None:
    proof = _proof()
    resolution = proof.resolve(
        _query(verification_mode=DepthVerificationMode.NATIVE_LIVE),
        (10, 11),
        live_hashes={10: "key-10"},
    )
    assert resolution.resolved is False
    assert resolution.depths == {10: 1}
    assert resolution.failures == {11: DepthStatus.LIVE_IDENTITY_REQUIRED}


def test_recycled_block_after_observation_is_rejected_without_a_new_snapshot() -> None:
    """RC1's core case: no later snapshot ever appears for the old chain.

    The proof says slot 12 holds ``key-12`` at depth 3. The slot is then recycled
    for unrelated content, and the old chain is never observed again, so nothing
    supersedes the proof. Only the live content comparison can catch it -- and in
    native mode it must, instead of returning depth 3.
    """

    proof = _proof()
    native = _query(verification_mode=DepthVerificationMode.NATIVE_LIVE)
    depth, status = proof.depth_of(native, 12, "key-something-else")
    assert depth is None
    assert status is DepthStatus.CONTENT_MISMATCH

    resolution = proof.resolve(native, (12,), live_hashes={12: "key-something-else"})
    assert resolution.resolved is False
    assert resolution.failures == {12: DepthStatus.CONTENT_MISMATCH}

    # The same query in replay mode (no live identity) would have been accepted,
    # which is exactly why the two modes are kept apart.
    replay = proof.resolve(_query(), (12,))
    assert replay.resolved is True
    assert replay.content_verified is False


def test_native_live_mode_still_enforces_every_other_check() -> None:
    """Turning on live identity must not relax chain, process or ordering checks."""

    proof = _proof()
    live = {block: f"key-{block}" for block in proof.block_ids}
    native = DepthVerificationMode.NATIVE_LIVE

    depth, status = (
        proof.resolve(_query(process_id="pid-other", verification_mode=native), (10,), live).depths,
        proof.depth_of(_query(process_id="pid-other", verification_mode=native), 10, "key-10"),
    )
    assert depth == {}
    assert status == (None, DepthStatus.WRONG_PROCESS)

    future = proof.resolve(_query(decision_index=5, verification_mode=native), (10,), live)
    assert future.failures == {10: DepthStatus.FUTURE_OBSERVATION}


# --- archive-shaped construction -----------------------------------------


def _snapshot_event(
    *,
    event_index: int,
    block_ids: list[int],
    keys: list[str] | None,
    process_id: str = PROCESS,
    chain: tuple[str, str] = CHAIN,
    clock_domain: str = "system_monotonic",
    timestamp: float = 100.0,
) -> dict:
    payload: dict[str, object] = {
        "block_ids": block_ids,
        "native_hash_process_id": process_id,
    }
    if keys is not None:
        payload["ordered_native_cache_keys"] = keys
    return {
        "event_type": "VLLM_PREFIX_SNAPSHOT",
        "event_index": event_index,
        "timestamp": timestamp,
        "clock_domain": clock_domain,
        "program_id": chain[0],
        "prefix_id": chain[1],
        "payload": payload,
    }


def test_index_from_events_uses_snapshot_order_as_depth() -> None:
    events = [
        {"event_type": "BLOCK_EVICTED", "event_index": 1, "payload": {}},
        _snapshot_event(
            event_index=10,
            block_ids=[1, 2, 3, 84, 85],
            keys=[f"k{i}" for i in range(5)],
            timestamp=100.0,
        ),
    ]
    index = index_from_events(events)
    proof = index.latest_before(CHAIN, 20)
    assert proof is not None
    assert proof.chain_length == 5
    query = _query(decision_index=20, decision_time=110.0, expected_observation_index=10)
    # Depth is the observation-time position, so block 84 is depth 4.
    assert proof.depth_of(query, 84, "k3") == (4, DepthStatus.OK)
    assert proof.depth_of(query, 85, "k4") == (5, DepthStatus.OK)


def test_index_from_events_treats_misaligned_keys_as_unverified() -> None:
    events = [_snapshot_event(event_index=10, block_ids=[1, 2, 3], keys=["only-one"])]
    index = index_from_events(events)
    proof = index.latest_before(CHAIN, 20)
    assert proof is not None
    assert proof.identity_verified is False
    query = _query(decision_index=20, expected_observation_index=10)
    assert proof.depth_of(query, 1, "only-one")[1] is DepthStatus.IDENTITY_UNVERIFIED


def test_index_from_events_skips_snapshots_without_a_process_id() -> None:
    events = [_snapshot_event(event_index=10, block_ids=[1, 2], keys=["a", "b"], process_id="")]
    index = index_from_events(events)
    assert index.latest_before(CHAIN, 20) is None
