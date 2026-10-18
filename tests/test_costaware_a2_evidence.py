"""Tests for reconstructing A2 geometry from recorded events.

The point of these tests is that identity and depth come from
``VLLM_PREFIX_SNAPSHOT`` content, and that a block shared by two chains keeps both
memberships instead of being assigned to whichever chain was iterated last.
"""

from __future__ import annotations

import json
from pathlib import Path

from kvopt.costaware.a2_evidence import (
    BLOCK_EVICTED_BEFORE_DECISION,
    CANDIDATE_BLOCKS_DIFFER,
    NO_PRIOR_SNAPSHOT,
    PROVED,
    SEQUENCE_LENGTH_MISMATCH,
    build_geometry,
    candidate_row,
    decisions_for_run,
    prove_chain,
    read_run_events,
)
from kvopt.costaware.a2_geometry import evaluate


def _snapshot(
    *,
    index: int,
    program: str,
    prefix: str,
    blocks: list[int],
    hashes: list[str],
    process: str = "pid-1",
) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": "VLLM_PREFIX_SNAPSHOT",
        "program_id": program,
        "prefix_id": prefix,
        "payload": {
            "block_ids": blocks,
            "ordered_native_hashes": hashes,
            "ordered_native_cache_keys": [f"{value}-key" for value in hashes],
            "native_hash_process_id": process,
            "native_hash_block_size": 16,
        },
    }


def _eviction(
    *, index: int, block_id: int, process: str = "pid-1"
) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
        "program_id": "a",
        "prefix_id": "p1",
        "payload": {
            "block_id": block_id,
            "native_hash_process_id": process,
            "native_cache_key_before": "before",
        },
    }


def _candidate(
    program: str, prefix: str, blocks: list[int], *, deadline: float
) -> dict[str, object]:
    return {
        "program_id": program,
        "prefix_id": prefix,
        "block_ids": blocks,
        "initially_reclaimable_block_ids": [],
        "retention_deadline_timestamp": deadline,
    }


def _decision(
    *,
    index: int,
    required: int,
    queue: list[tuple[int, int, bool]],
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": "FORCED_RELEASE_DECISION",
        "timestamp": 100.0,
        "payload": {
            "required_blocks": required,
            "original_free_queue": [
                {"block_id": block_id, "native_lru_rank": rank, "has_block_hash": hashed}
                for block_id, rank, hashed in queue
            ],
            "candidates": candidates,
            # A2 holds the entry layer fixed, so the observed release set is only
            # carried for fidelity; it does not steer the block comparison.
            "selected_releases": [],
        },
    }


def _write(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    run = tmp_path / "run-1"
    run.mkdir()
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    return run


def test_shared_block_keeps_every_chain_membership(tmp_path: Path) -> None:
    """Blocks 1 and 2 are in both prefixes; the depth differs per chain."""
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        _snapshot(
            index=2, program="b", prefix="p2", blocks=[1, 2, 3], hashes=["h1", "h2", "h3"]
        ),
        _decision(
            index=3,
            # 3 forces both entries to be released, so every block becomes legal.
            required=3,
            queue=[(1, 0, True), (2, 1, True), (3, 2, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 130.0,
                },
                {
                    "program_id": "b",
                    "prefix_id": "p2",
                    "block_ids": [1, 2, 3],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 70.0,
                },
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=1)

    shared = geometry.blocks[1]
    assert shared.is_shared
    assert shared.chains == ("a:p1", "b:p2")
    assert {(m.chain, m.depth) for m in shared.memberships} == {("a:p1", 1), ("b:p2", 1)}
    # Content identity is the hash, not the block id.
    assert shared.content_hash == "h1"

    deeper = geometry.blocks[3]
    assert not deeper.is_shared
    assert deeper.memberships[0].depth == 3


def test_depth_comes_from_snapshot_position_not_from_rank(tmp_path: Path) -> None:
    """Ranks are deliberately the reverse of the content order."""
    events = [
        _snapshot(
            index=1,
            program="a",
            prefix="p1",
            blocks=[10, 11, 12],
            hashes=["x10", "x11", "x12"],
        ),
        _decision(
            index=2,
            required=1,
            queue=[(12, 0, True), (11, 1, True), (10, 2, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [10, 11, 12],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 100.0,
                }
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=1)

    assert geometry.blocks[10].memberships[0].depth == 1
    assert geometry.blocks[12].memberships[0].depth == 3
    # Block 12 has rank 0 but depth 3: the two are not interchangeable.
    assert geometry.blocks[12].native_rank == 0


def test_hashless_block_is_not_a_gap_and_hashed_unknown_is(tmp_path: Path) -> None:
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1], hashes=["h1"]),
        _decision(
            index=2,
            required=2,
            queue=[(1, 0, True), (2, 1, True), (3, 2, False)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1],
                    "initially_reclaimable_block_ids": [1],
                    "retention_deadline_timestamp": 90.0,
                }
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=1)

    # Block 2 carries a hash but appears in no snapshot: unobserved.
    assert 2 in geometry.gaps
    # Block 3 is hashless: it costs nothing, so it is not a gap.
    assert 3 not in geometry.gaps
    assert not geometry.scorable


def test_geometry_is_scorable_when_every_hashed_block_is_mapped(tmp_path: Path) -> None:
    events = [
        _snapshot(
            index=1, program="a", prefix="p1", blocks=[1, 2, 3], hashes=["h1", "h2", "h3"]
        ),
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True), (2, 1, True), (3, 2, True), (4, 3, False)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2, 3],
                    "initially_reclaimable_block_ids": [1, 2, 3],
                    "retention_deadline_timestamp": 90.0,
                }
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=1)
    assert geometry.scorable
    assert geometry.gaps == {}


def test_mismatched_hash_alignment_is_skipped_not_guessed(tmp_path: Path) -> None:
    """Without positional alignment there is no depth, so the chain is dropped."""
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2, 3], hashes=["h1", "h2"]),
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True), (2, 1, True), (3, 2, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2, 3],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 90.0,
                }
            ],
        ),
    ]
    run = _write(tmp_path, events)
    decision = decisions_for_run(run)[0]
    assert decision.proofs["a:p1"].status == SEQUENCE_LENGTH_MISMATCH
    assert not decision.proofs["a:p1"].proved
    geometry = build_geometry(decision, need=1)
    assert set(geometry.gaps) == {1, 2, 3}
    assert not geometry.scorable


def test_decisions_only_see_snapshots_that_precede_them(tmp_path: Path) -> None:
    events = [
        _snapshot(index=5, program="a", prefix="p1", blocks=[1], hashes=["h1"]),
        _decision(
            index=10,
            required=1,
            queue=[(1, 0, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 90.0,
                }
            ],
        ),
        _snapshot(index=20, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        _decision(
            index=30,
            required=1,
            queue=[(1, 0, True), (2, 1, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 90.0,
                }
            ],
        ),
    ]
    decisions = decisions_for_run(_write(tmp_path, events))
    assert len(decisions) == 2

    first = build_geometry(decisions[0], need=1)
    assert first.blocks[1].memberships[0].depth == 1
    assert 2 not in first.blocks

    second = build_geometry(decisions[1], need=1)
    assert second.blocks[2].memberships[0].depth == 2


def test_q_proxy_uses_the_retention_deadline(tmp_path: Path) -> None:
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True), (2, 1, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2],
                    "initially_reclaimable_block_ids": [],
                    "retention_deadline_timestamp": 130.0,
                }
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=1, tau_seconds=30.0)
    # deadline is 30 s past the decision timestamp, so q = sigmoid(1)
    assert geometry.q_by_chain["a:p1"] > 0.5


def test_candidate_row_never_invents_a_native_position() -> None:
    row = candidate_row(
        "run",
        0,
        {
            "program_id": "a",
            "prefix_id": "p1",
            "block_ids": [1, 2],
            "initially_reclaimable_block_ids": [2],
            "retention_deadline_timestamp": 50.0,
        },
    )
    # The entry layer is held fixed for A2; no recency is invented for it.
    assert row.decision_native_lru_position is None
    assert row.block_count == 2
    assert row.initially_reclaimable_block_count == 1


def test_missing_events_file_raises(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        read_run_events(tmp_path)


def test_evaluate_on_reconstructed_geometry_reports_no_freedom_case(tmp_path: Path) -> None:
    events = [
        _snapshot(
            index=1, program="a", prefix="p1", blocks=[1, 2, 3], hashes=["h1", "h2", "h3"]
        ),
        _decision(
            index=2,
            required=3,
            queue=[(1, 0, True), (2, 1, True), (3, 2, True)],
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2, 3],
                    "initially_reclaimable_block_ids": [1, 2, 3],
                    "retention_deadline_timestamp": 90.0,
                }
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=3)
    row = evaluate(
        run_id="run-1",
        decision_event_index=2,
        geometry=geometry,
        need=min(decision.snapshot.target, len(geometry.blocks)),
    )
    assert row.legal_count == row.need
    assert not row.victim_set_differs


# --- RC1: slot identity must be proved, never assumed ---------------------


def test_slot_reuse_invalidates_the_mapping(tmp_path: Path) -> None:
    """snapshot(slot X, hash A) -> eviction -> decision must NOT be proved.

    This is the regression M1 asked for. A block id is a slot, not a content
    identity: after the slot is evicted it may hold different content, so the old
    hash must not be attached to it.
    """
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[7, 8], hashes=["A7", "A8"]),
        _eviction(index=2, block_id=7),
        _decision(
            index=3,
            required=1,
            queue=[(7, 0, True), (8, 1, True)],
            candidates=[_candidate("a", "p1", [7, 8], deadline=90.0)],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    proof = decision.proofs["a:p1"]

    assert proof.status == BLOCK_EVICTED_BEFORE_DECISION
    assert not proof.proved
    # No depth may be borrowed from the stale snapshot.
    assert proof.depth_of(7) is None

    geometry = build_geometry(decision, need=1)
    assert set(geometry.gaps) == {7, 8}
    assert not geometry.scorable


def test_eviction_from_a_other_process_does_not_invalidate(tmp_path: Path) -> None:
    """Only evictions by the same hash process can reuse these slots."""
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[7], hashes=["A7"], process="pid-1"),
        _eviction(index=2, block_id=7, process="pid-2"),
        _decision(
            index=3,
            required=1,
            queue=[(7, 0, True)],
            candidates=[_candidate("a", "p1", [7], deadline=90.0)],
        ),
    ]
    proof = decisions_for_run(_write(tmp_path, events))[0].proofs["a:p1"]
    assert proof.status == PROVED


def test_invalid_later_snapshot_does_not_fall_back_to_an_older_one(tmp_path: Path) -> None:
    """An invalid later snapshot must invalidate the mapping, not leave it active."""
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        # Later snapshot for the same chain describes a different block list.
        _snapshot(index=2, program="a", prefix="p1", blocks=[1, 2, 3], hashes=["h1", "h2", "h3"]),
        _decision(
            index=3,
            required=1,
            queue=[(1, 0, True), (2, 1, True)],
            candidates=[_candidate("a", "p1", [1, 2], deadline=90.0)],
        ),
    ]
    proof = decisions_for_run(_write(tmp_path, events))[0].proofs["a:p1"]
    assert proof.status == CANDIDATE_BLOCKS_DIFFER
    assert not proof.proved
    assert proof.snapshot_event_index is None


def test_no_prior_snapshot_is_not_proved(tmp_path: Path) -> None:
    events = [
        _decision(
            index=3,
            required=1,
            queue=[(1, 0, True)],
            candidates=[_candidate("a", "p1", [1], deadline=90.0)],
        ),
    ]
    proof = decisions_for_run(_write(tmp_path, events))[0].proofs["a:p1"]
    assert proof.status == NO_PRIOR_SNAPSHOT


def test_snapshot_without_process_id_is_not_proved(tmp_path: Path) -> None:
    snapshot = _snapshot(index=1, program="a", prefix="p1", blocks=[1], hashes=["h1"])
    snapshot["payload"].pop("native_hash_process_id")  # type: ignore[union-attr]
    events = [
        snapshot,
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True)],
            candidates=[_candidate("a", "p1", [1], deadline=90.0)],
        ),
    ]
    proof = decisions_for_run(_write(tmp_path, events))[0].proofs["a:p1"]
    assert not proof.proved


def test_ordered_equality_is_required_not_just_same_set(tmp_path: Path) -> None:
    """A reordered block list is a different prefix, so it cannot be proved."""
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True), (2, 1, True)],
            candidates=[_candidate("a", "p1", [2, 1], deadline=90.0)],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    proof = prove_chain(
        events, candidate=_candidate("a", "p1", [2, 1], deadline=90.0), decision_index=2
    )
    assert proof.status == CANDIDATE_BLOCKS_DIFFER
    assert not decision.proofs["a:p1"].proved


# --- RC2: unknown cost stays unknown --------------------------------------


def test_missing_reuse_weight_makes_the_decision_unscorable(tmp_path: Path) -> None:
    """A proved chain with no deadline is not a zero-cost chain."""
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True), (2, 1, True)],
            # No retention_deadline_timestamp: the weight cannot be obtained.
            candidates=[
                {
                    "program_id": "a",
                    "prefix_id": "p1",
                    "block_ids": [1, 2],
                    "initially_reclaimable_block_ids": [],
                }
            ],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    assert decision.proofs["a:p1"].proved

    geometry = build_geometry(decision, need=1)
    assert geometry.unknown_weight_chains == ("a:p1",)
    assert not geometry.scorable

    row = evaluate(
        run_id="run-1", decision_event_index=2, geometry=geometry, need=1
    )
    # The selection is kept as a diagnostic, but the loss is not reported.
    assert row.native is None
    assert row.cost_aware is None
    assert not row.verified
    assert row.cost_aware_blocks  # a choice is still visible


def test_verified_decision_reports_both_losses(tmp_path: Path) -> None:
    events = [
        _snapshot(index=1, program="a", prefix="p1", blocks=[1, 2], hashes=["h1", "h2"]),
        _decision(
            index=2,
            required=1,
            queue=[(1, 0, True), (2, 1, True)],
            candidates=[_candidate("a", "p1", [1, 2], deadline=130.0)],
        ),
    ]
    decision = decisions_for_run(_write(tmp_path, events))[0]
    geometry = build_geometry(decision, need=1)
    row = evaluate(run_id="run-1", decision_event_index=2, geometry=geometry, need=1)

    assert geometry.scorable
    assert row.verified
    assert row.native is not None and row.cost_aware is not None
