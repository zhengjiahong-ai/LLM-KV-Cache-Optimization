"""Tests for the dynamic forced-release pressure replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from kvopt.costaware.replay import (
    DecisionSnapshot,
    ExecutedP1BStrategy,
    QueueBlock,
    ReplayState,
    RuleStrategy,
    candidate_key,
    load_decision_snapshots,
    replay_decision,
    validate_replay_fidelity,
)
from kvopt.costaware.rules import rule_by_id
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.ingestion import ArtifactValidationError, load_run_artifacts

_EXEMPLARS = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "experiments"
    / "phase2a-m6-formal"
    / "curated-evidence"
    / "exemplars"
)


def _row(
    *,
    run_id: str,
    decision_event_index: int,
    program_id: str,
    block_ids: tuple[int, ...],
    prefill_reload_seconds: float,
    retention_deadline_timestamp: float,
    decision_native_lru_position: int,
    block_count: int | None = None,
    prefix_id: str = "p",
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id=run_id,
        decision_event_index=decision_event_index,
        source_event_index=decision_event_index,
        candidate_position=decision_native_lru_position,
        program_id=program_id,
        prefix_id=prefix_id,
        selected=False,
        release_order=None,
        retention_deadline_timestamp=retention_deadline_timestamp,
        waiting_followup=True,
        block_ids=block_ids,
        block_count=len(block_ids) if block_count is None else block_count,
        initially_reclaimable_block_ids=block_ids,
        initially_reclaimable_block_count=len(block_ids),
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=prefill_reload_seconds,
        eta=1.0,
        queue_delay_t_seconds=0.5,
        decision_native_lru_position=decision_native_lru_position,
    )


def _snapshot(
    *,
    entries: dict[str, tuple[int, ...]],
    required_blocks: int,
    costs: dict[str, float] | None = None,
    deadlines: dict[str, float] | None = None,
    observed_selected: tuple[str, ...] = (),
    observed_initial: dict[str, tuple[int, ...]] | None = None,
    run_id: str = "run-1",
    decision_event_index: int = 40,
) -> tuple[DecisionSnapshot, dict[tuple[str, str], DecisionCandidateRow]]:
    costs = costs or {key: 0.1 for key in entries}
    deadlines = deadlines or {
        key: 100.0 + index for index, key in enumerate(entries)
    }
    blocks: list[int] = []
    for owned in entries.values():
        for block_id in owned:
            if block_id not in blocks:
                blocks.append(block_id)
    blocks.sort()
    ranking = {block_id: rank for rank, block_id in enumerate(blocks)}

    rows: dict[tuple[str, str], DecisionCandidateRow] = {}
    owners: dict[int, set[tuple[str, str]]] = {}
    for index, (program_id, owned) in enumerate(entries.items()):
        key = (program_id, "p")
        rows[key] = _row(
            run_id=run_id,
            decision_event_index=decision_event_index,
            program_id=program_id,
            block_ids=owned,
            prefill_reload_seconds=costs[program_id],
            retention_deadline_timestamp=deadlines[program_id],
            decision_native_lru_position=index,
        )
        for block_id in owned:
            owners.setdefault(block_id, set()).add(key)

    snapshot = DecisionSnapshot(
        run_id=run_id,
        decision_event_index=decision_event_index,
        timestamp=100.0,
        required_blocks=required_blocks,
        queue=tuple(
            QueueBlock(
                block_id=block_id,
                has_block_hash=True,
                native_lru_rank=ranking[block_id],
            )
            for block_id in blocks
        ),
        candidate_keys=tuple((program_id, "p") for program_id in entries),
        owners_by_block={
            block_id: frozenset(keys) for block_id, keys in owners.items()
        },
        observed_selected=tuple((program_id, "p") for program_id in observed_selected),
        observed_initial_reclaimable={
            (program_id, "p"): owned
            for program_id, owned in (
                observed_initial
                if observed_initial is not None
                else {key: entries[key] for key in entries}
            ).items()
        },
        ranking_by_block=ranking,
    )
    return snapshot, rows


# --- eligibility semantics -------------------------------------------------


def test_unhashed_blocks_are_always_eligible() -> None:
    snapshot, _rows = _snapshot(entries={"a": (1,)}, required_blocks=1)
    unhashed = DecisionSnapshot(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        timestamp=snapshot.timestamp,
        required_blocks=1,
        queue=(QueueBlock(block_id=1, has_block_hash=False, native_lru_rank=0),),
        candidate_keys=snapshot.candidate_keys,
        owners_by_block=snapshot.owners_by_block,
        observed_selected=(),
        observed_initial_reclaimable={("a", "p"): ()},
        ranking_by_block={1: 0},
    )
    state = ReplayState(unhashed)
    assert state.eligible_block_ids() == frozenset({1})
    assert ReplayState(unhashed).newly_eligible_after(("a", "p")) == ()


def test_shared_block_stays_blocked_until_every_protected_owner_releases() -> None:
    snapshot, _rows = _snapshot(
        entries={"a": (1, 2), "b": (2, 3), "c": (4,)},
        required_blocks=2,
    )
    state = ReplayState(snapshot)
    assert state.eligible_block_ids() == frozenset()

    state.release(("a", "p"))
    # Block 1 unblocks; block 2 is still owned by the protected entry b.
    assert state.eligible_block_ids() == frozenset({1})
    assert state.newly_eligible_after(("b", "p")) == (2, 3)


def test_marginal_set_changes_between_iterations() -> None:
    """A co-owned block only appears in the marginal once its co-owner is gone.

    This is the property that makes the frozen loop non-decomposable: the same
    entry frees a different number of blocks depending on what was released
    before it, so per-entry reclaimable counts cannot be summed independently.
    """
    snapshot, _rows = _snapshot(
        entries={"a": (1, 2), "b": (2, 3), "c": (4,)},
        required_blocks=2,
    )
    state = ReplayState(snapshot)
    first = state.newly_eligible_after(("b", "p"))
    state.release(("a", "p"))
    second = state.newly_eligible_after(("b", "p"))
    # While a is protected, b alone unblocks only its unshared block 3.
    assert first == (3,)
    # After a is released, b also unblocks the co-owned block 2.
    assert second == (2, 3)
    assert len(first) != len(second)


def test_required_blocks_is_capped_by_the_queue_length() -> None:
    snapshot, _rows = _snapshot(entries={"a": (1, 2)}, required_blocks=99)
    assert snapshot.target == 2


# --- the frozen loop -------------------------------------------------------


def test_p1b_replay_reproduces_a_hand_computed_release_set() -> None:
    snapshot, rows = _snapshot(
        entries={"a": (1, 2, 3), "b": (4,)},
        required_blocks=3,
        deadlines={"a": 200.0, "b": 100.0},
    )
    outcome = replay_decision(snapshot, ExecutedP1BStrategy(), rows)
    # b has the earliest deadline and alone frees 1 < 3, so a is released next.
    assert outcome.released == (("b", "p"), ("a", "p"))
    assert outcome.satisfied is True
    assert outcome.exhausted is False
    assert outcome.iterations == 2


def test_cost_rule_can_need_more_releases_than_the_baseline() -> None:
    """The defect the fixed-count comparison could not represent."""
    snapshot, rows = _snapshot(
        entries={"a": (1, 2, 3), "b": (4,), "c": (5,)},
        required_blocks=3,
        costs={"a": 0.9, "b": 0.1, "c": 0.2},
        deadlines={"a": 100.0, "b": 200.0, "c": 300.0},
    )
    baseline = replay_decision(snapshot, ExecutedP1BStrategy(), rows)
    cost = replay_decision(
        snapshot, RuleStrategy(rule_by_id("M1_prefill_reload_ascending")), rows
    )
    assert baseline.released == (("a", "p"),)
    assert len(cost.released) == 3
    assert set(cost.released) == {("a", "p"), ("b", "p"), ("c", "p")}


def test_exhaustion_is_unreachable_for_the_frozen_target_rule() -> None:
    """The ``exhausted`` guard cannot fire: ``target = min(required, queue)``.

    Eligibility is "no protected owner remains". With no candidates every queued
    block is therefore immediately eligible, and with candidates the target is
    capped at the queue length, so the loop always terminates satisfied. The
    guard is kept as a defensive assertion rather than a live branch; see
    ``test_every_rule_satisfies_every_observed_target``.
    """
    no_candidates = DecisionSnapshot(
        run_id="run-1",
        decision_event_index=40,
        timestamp=1.0,
        required_blocks=2,
        queue=(
            QueueBlock(block_id=1, has_block_hash=True, native_lru_rank=0),
            QueueBlock(block_id=2, has_block_hash=True, native_lru_rank=1),
        ),
        candidate_keys=(),
        owners_by_block={},
        observed_selected=(),
        observed_initial_reclaimable={},
        ranking_by_block={1: 0, 2: 1},
    )
    outcome = replay_decision(no_candidates, ExecutedP1BStrategy(), {})
    assert outcome.satisfied is True
    assert outcome.exhausted is False
    assert outcome.iterations == 0


def test_every_rule_satisfies_every_observed_target() -> None:
    """The release count must always be sufficient, never truncated.

    This is the property the fixed-count comparison silently skipped: it assumed
    the alternative could match the baseline's release count, without checking
    whether that count reaches the same pressure target.
    """
    run_dirs = sorted(path for path in _EXEMPLARS.iterdir() if path.is_dir())
    snapshots = load_decision_snapshots(
        [load_run_artifacts(path) for path in run_dirs]
    )
    checked = 0
    for snapshot in snapshots:
        rows = {
            key: _row(
                run_id=snapshot.run_id,
                decision_event_index=snapshot.decision_event_index,
                program_id=key[0],
                prefix_id=key[1],
                block_ids=snapshot.observed_initial_reclaimable.get(key, ()),
                prefill_reload_seconds=0.0,
                retention_deadline_timestamp=0.0,
                decision_native_lru_position=0,
            )
            for key in snapshot.candidate_keys
        }
        for strategy in (
            ExecutedP1BStrategy(),
            RuleStrategy(rule_by_id("M1_prefill_reload_ascending")),
            RuleStrategy(rule_by_id("M2_non_code_first")),
            RuleStrategy(rule_by_id("M1_marginal_cost_per_reclaimable")),
        ):
            outcome = replay_decision(snapshot, strategy, rows)
            assert outcome.satisfied is True
            assert outcome.eligible_blocks_final >= outcome.target
            checked += 1
    assert checked == 12


def test_consistent_snapshots_are_always_satisfiable() -> None:
    """The loop reaches its target whenever the snapshot is self-consistent."""
    snapshot, rows = _snapshot(
        entries={"a": (1, 2), "b": (2, 3)}, required_blocks=3
    )
    for strategy in (
        ExecutedP1BStrategy(),
        RuleStrategy(rule_by_id("M1_prefill_reload_ascending")),
        RuleStrategy(rule_by_id("M2_non_code_first")),
    ):
        outcome = replay_decision(snapshot, strategy, rows)
        assert outcome.satisfied is True
        assert outcome.exhausted is False
        assert outcome.eligible_blocks_final >= outcome.target


def test_strategy_returning_a_foreign_candidate_is_rejected() -> None:
    """Wrong-prefix or stale keys must fail loudly, not silently loop."""

    class Rogue:
        strategy_id = "rogue"

        def pick_next(
            self,
            remaining: object,
            state: object,
        ) -> tuple[str, str]:
            del remaining, state
            return ("not-a-candidate", "p")

    snapshot, rows = _snapshot(entries={"a": (1,)}, required_blocks=1)
    with pytest.raises(ValueError, match="not one of the still-protected"):
        replay_decision(snapshot, Rogue(), rows)


def test_strategy_is_re_ranked_every_iteration() -> None:
    """A rule whose relative order changes must be re-evaluated, not frozen.

    Normalized size scores change as candidates leave the pool, so the second
    pick can differ from a one-shot ordering of the original set.
    """
    snapshot, rows = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5,), "c": (6,)},
        required_blocks=6,
        costs={"a": 0.5, "b": 0.6, "c": 0.7},
    )
    strategy = RuleStrategy(rule_by_id("M3_size_score_only"))
    outcome = replay_decision(snapshot, strategy, rows)
    assert outcome.satisfied is True
    assert len(outcome.released) == 3


# --- fidelity against the real artifacts -----------------------------------


def test_load_decision_snapshots_reads_only_observed_facts() -> None:
    run_dirs = sorted(path for path in _EXEMPLARS.iterdir() if path.is_dir())
    artifacts = [load_run_artifacts(path) for path in run_dirs]
    snapshots = load_decision_snapshots(artifacts)
    assert len(snapshots) == len(artifacts) == 3
    for snapshot in snapshots:
        assert snapshot.target == min(snapshot.required_blocks, len(snapshot.queue))
        assert snapshot.candidate_keys
        assert snapshot.observed_selected
        assert set(snapshot.observed_selected) <= set(snapshot.candidate_keys)
        assert snapshot.ranking_by_block


def test_replay_reproduces_every_observed_decision() -> None:
    """The strongest available check that the replay semantics are faithful."""
    run_dirs = sorted(path for path in _EXEMPLARS.iterdir() if path.is_dir())
    artifacts = [load_run_artifacts(path) for path in run_dirs]
    snapshots = load_decision_snapshots(artifacts)

    rows_by_decision: dict[tuple[str, int], dict[tuple[str, str], object]] = {}
    for snapshot in snapshots:
        rows_by_decision[(snapshot.run_id, snapshot.decision_event_index)] = {
            key: _row(
                run_id=snapshot.run_id,
                decision_event_index=snapshot.decision_event_index,
                program_id=key[0],
                prefix_id=key[1],
                block_ids=snapshot.observed_initial_reclaimable.get(key, ()),
                prefill_reload_seconds=0.0,
                retention_deadline_timestamp=0.0,
                decision_native_lru_position=0,
            )
            for key in snapshot.candidate_keys
        }

    fidelity = validate_replay_fidelity(
        snapshots, rows_by_decision, ExecutedP1BStrategy()
    )
    assert fidelity.decisions_compared == 3
    assert fidelity.release_set_match_rate == pytest.approx(1.0)
    assert fidelity.release_sequence_match_rate == pytest.approx(1.0)


def test_replay_reproduces_every_observed_marginal_block_set() -> None:
    """Validates the ownership model independently of any strategy."""
    run_dirs = sorted(path for path in _EXEMPLARS.iterdir() if path.is_dir())
    snapshots = load_decision_snapshots(
        [load_run_artifacts(path) for path in run_dirs]
    )
    checked = 0
    for snapshot in snapshots:
        state = ReplayState(snapshot)
        for key, observed in snapshot.observed_initial_reclaimable.items():
            assert set(state.newly_eligible_after(key)) == set(observed)
            checked += 1
    assert checked == 11


def test_load_decision_snapshots_rejects_a_missing_payload_field() -> None:
    run_dir = next(path for path in _EXEMPLARS.iterdir() if path.is_dir())
    artifacts = load_run_artifacts(run_dir)
    tampered_events = tuple(
        {
            **event,
            "payload": {
                key: value
                for key, value in event["payload"].items()  # type: ignore[union-attr]
                if key != "required_blocks"
            },
        }
        if event.get("event_type") == "FORCED_RELEASE_DECISION"
        else event
        for event in artifacts.events
    )
    broken = type(artifacts)(
        run_dir=artifacts.run_dir,
        run_id=artifacts.run_id,
        manifest=artifacts.manifest,
        trace=artifacts.trace,
        replay=artifacts.replay,
        events=tampered_events,
    )
    with pytest.raises(ArtifactValidationError, match="required_blocks"):
        load_decision_snapshots([broken])


def test_candidate_key_is_the_logical_identity() -> None:
    row = _row(
        run_id="r",
        decision_event_index=1,
        program_id="agent-a",
        block_ids=(1,),
        prefill_reload_seconds=0.1,
        retention_deadline_timestamp=1.0,
        decision_native_lru_position=0,
    )
    assert candidate_key(row) == ("agent-a", "p")
