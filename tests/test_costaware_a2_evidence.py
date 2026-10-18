"""Tests for reconstructing A2 geometry from recorded events.

The point of these tests is that identity and depth come from
``VLLM_PREFIX_SNAPSHOT`` content, and that a block shared by two chains keeps both
memberships instead of being assigned to whichever chain was iterated last.
"""

from __future__ import annotations

import json
from pathlib import Path

from kvopt.costaware.a2_evidence import (
    build_geometry,
    candidate_row,
    decisions_for_run,
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
) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": "VLLM_PREFIX_SNAPSHOT",
        "program_id": program,
        "prefix_id": prefix,
        "payload": {
            "block_ids": blocks,
            "ordered_native_hashes": hashes,
            "native_hash_block_size": 16,
        },
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
    assert decision.chains == {}
    geometry = build_geometry(decision, need=1)
    assert set(geometry.gaps) == {1, 2, 3}


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
