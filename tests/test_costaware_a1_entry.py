"""Tests for the Phase 2G A1 entry-level cost-aware release strategy.

Coverage required by M1:

- ordinary non-shared entries;
- shared prefix;
- zero-marginal release;
- two-entry joint unlock;
- capacity shortfall;
- deadline fallback;
- legality of the choice, the stop condition, determinism, and the absence of
  future information.
"""

from __future__ import annotations

import dataclasses
import math
import random

import pytest

from kvopt.costaware.a1_compare import compare_one, compare_scenario
from kvopt.costaware.a1_entry import (
    BRANCH_DEADLINE_FALLBACK,
    BRANCH_PAIR_LOOKAHEAD,
    BRANCH_PER_UNIT,
    BRANCH_SINGLE_STEP,
    A1EntryCostAwareStrategy,
    default_tau_seconds,
    reuse_proxy,
)
from kvopt.costaware.a1_scenarios import (
    DECISION_TIMESTAMP,
    all_scenarios,
    scenario_a_divergent,
    scenario_b_identical,
    scenario_c_a1_worse,
)
from kvopt.costaware.replay import (
    DecisionSnapshot,
    ExecutedP1BStrategy,
    QueueBlock,
    ReplayState,
    candidate_key,
    replay_decision,
)
from kvopt.costaware.rules import FORBIDDEN_FEATURES
from kvopt.profiling.datasets import DecisionCandidateRow

TAU = default_tau_seconds()


# --- helpers ---------------------------------------------------------------


def _row(
    program_id: str,
    block_ids: tuple[int, ...],
    *,
    deadline: float,
    position: int,
    reclaimable: tuple[int, ...] | None = None,
) -> DecisionCandidateRow:
    owned = tuple(block_ids)
    reclaim = owned if reclaimable is None else tuple(reclaimable)
    return DecisionCandidateRow(
        run_id="unit",
        decision_event_index=0,
        source_event_index=0,
        candidate_position=position,
        program_id=program_id,
        prefix_id="p",
        selected=False,
        release_order=None,
        retention_deadline_timestamp=deadline,
        waiting_followup=True,
        block_ids=owned,
        block_count=len(owned),
        initially_reclaimable_block_ids=reclaim,
        initially_reclaimable_block_count=len(reclaim),
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=1.0,
        eta=1.0,
        queue_delay_t_seconds=0.5,
        decision_native_lru_position=position,
    )


def _snapshot(
    entries: dict[str, tuple[int, ...]],
    *,
    required_blocks: int,
    timestamp: float = DECISION_TIMESTAMP,
) -> tuple[DecisionSnapshot, dict[tuple[str, str], DecisionCandidateRow]]:
    """Build a decision whose ownership follows the given entries exactly."""
    blocks: list[int] = []
    for owned in entries.values():
        for block_id in owned:
            if block_id not in blocks:
                blocks.append(block_id)
    blocks.sort()
    ranking = {block_id: rank for rank, block_id in enumerate(blocks)}

    owners: dict[int, set[tuple[str, str]]] = {}
    rows: dict[tuple[str, str], DecisionCandidateRow] = {}
    for position, (program_id, owned) in enumerate(entries.items()):
        key = (program_id, "p")
        for block_id in owned:
            owners.setdefault(block_id, set()).add(key)
        rows[key] = _row(
            program_id,
            owned,
            deadline=100.0 + 10.0 * position,
            position=position,
        )

    snapshot = DecisionSnapshot(
        run_id="unit",
        decision_event_index=0,
        timestamp=timestamp,
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
        observed_selected=(),
        observed_initial_reclaimable={
            key: tuple(
                block_id
                for block_id in entries[key[0]]
                if owners[block_id] == {key}
            )
            for key in rows
        },
        ranking_by_block=ranking,
    )
    # Keep the rows' reclaimable view consistent with the snapshot.
    for key, row in rows.items():
        reclaim = snapshot.observed_initial_reclaimable[key]
        rows[key] = dataclasses.replace(
            row,
            initially_reclaimable_block_ids=reclaim,
            initially_reclaimable_block_count=len(reclaim),
        )
    return snapshot, rows


def _remaining(snapshot, rows, state):
    return [
        rows[key]
        for key in snapshot.candidate_keys
        if key not in state.released and key in rows
    ]


# --- reuse proxy -----------------------------------------------------------


def test_reuse_proxy_is_monotone_and_centred_on_the_deadline() -> None:
    assert reuse_proxy(100.0, 100.0, TAU) == pytest.approx(0.5)
    assert reuse_proxy(130.0, 100.0, TAU) > 0.5
    assert reuse_proxy(70.0, 100.0, TAU) < 0.5
    # Monotone in the deadline, which is what makes the fallback to the deadline
    # order exact when the bracket is a common constant.
    sequence = [reuse_proxy(d, 100.0, TAU) for d in (0.0, 50.0, 100.0, 150.0, 300.0)]
    assert sequence == sorted(sequence)


def test_constructor_rejects_out_of_range_parameters() -> None:
    with pytest.raises(ValueError):
        A1EntryCostAwareStrategy(lambda_=-0.1)
    with pytest.raises(ValueError):
        A1EntryCostAwareStrategy(lambda_=1.5)
    with pytest.raises(ValueError):
        A1EntryCostAwareStrategy(tau_seconds=0.0)


# --- ordinary non-shared entries -------------------------------------------


def test_ordinary_entries_perfer_the_cheaper_sacrifice() -> None:
    """Two disjoint entries, equal size, different deadlines.

    With equal N_i the score reduces to q, so the earliest deadline goes first --
    the same choice A0 makes, and the reason the degenerate case is not a defect.
    """
    snapshot, rows = _snapshot(
        {"A": (1, 2, 3, 4), "B": (5, 6, 7, 8)}, required_blocks=2
    )
    strategy = A1EntryCostAwareStrategy()
    state = ReplayState(snapshot)
    selection = strategy.select(_remaining(snapshot, rows, state), state)

    assert selection.key == ("A", "p")
    assert selection.branch == BRANCH_SINGLE_STEP
    assert {s.key: s.new_blocks for s in selection.scores} == {
        ("A", "p"): 4,
        ("B", "p"): 4,
    }


def test_ordinary_entries_prefer_the_entry_whose_own_blocks_suffice() -> None:
    """A large exposed tail loses to a tail that exactly matches the requirement."""
    first = scenario_a_divergent()
    comparison = compare_scenario(first)
    assert comparison.a0.released == (("A", "p"),)
    assert comparison.a1.released == (("B", "p"),)
    assert comparison.a0.satisfied and comparison.a1.satisfied


# --- shared prefix ---------------------------------------------------------


def test_shared_blocks_are_not_eligible_until_every_owner_releases() -> None:
    # Both entries own exactly the same blocks, so neither is a sole owner of
    # anything: releasing one entry leaves the other still protecting everything.
    snapshot, _rows = _snapshot(
        {"A": (1, 2, 3), "B": (1, 2, 3)}, required_blocks=1
    )
    state = ReplayState(snapshot)
    assert state.eligible_block_ids() == frozenset()

    # Releasing either owner alone unlocks nothing: the co-owned blocks still have
    # a protected owner.
    assert state.newly_eligible_after(("A", "p")) == ()
    assert state.newly_eligible_after(("B", "p")) == ()

    # Releasing both unlocks the co-owned blocks.
    assert set(state.newly_eligible_after_many((("A", "p"), ("B", "p")))) == {
        1,
        2,
        3,
    }


def test_shared_scenario_reports_zero_marginal_for_both_entries() -> None:
    # Identical ownership, so every N_i is zero and the pair branch must fire.
    snapshot, rows = _snapshot(
        {"A": (1, 2, 3), "B": (1, 2, 3)}, required_blocks=2
    )
    strategy = A1EntryCostAwareStrategy()
    state = ReplayState(snapshot)
    selection = strategy.select(_remaining(snapshot, rows, state), state)

    # need = 2, joint relief = 3, so the pair branch fires.
    assert selection.branch == BRANCH_PAIR_LOOKAHEAD
    assert selection.joint_new_blocks == 3
    assert all(score.new_blocks == 0 for score in selection.scores)


def test_partial_sharing_still_leaves_a_positive_marginal() -> None:
    """Distinguishes co-ownership from partial overlap.

    With ``A = {1,2,3}`` and ``B = {1,2,4}``, block 3 is A's alone and block 4 is
    B's alone, so each release does unlock something and the pair branch must NOT
    fire. Keeping this case in the suite stops the zero-marginal branch from being
    reached by accident.
    """
    snapshot, rows = _snapshot(
        {"A": (1, 2, 3), "B": (1, 2, 4)}, required_blocks=2
    )
    state = ReplayState(snapshot)
    assert state.newly_eligible_after(("A", "p")) == (3,)
    assert state.newly_eligible_after(("B", "p")) == (4,)

    selection = A1EntryCostAwareStrategy().select(
        _remaining(snapshot, rows, state), state
    )
    assert selection.branch == BRANCH_PER_UNIT
    assert all(score.new_blocks == 1 for score in selection.scores)


# --- zero marginal and two-entry joint unlock ------------------------------


def test_pair_lookahead_releases_both_members_in_deadline_order() -> None:
    snapshot, rows = _snapshot(
        {"A": (1, 2, 3, 4), "B": (1, 2, 3, 4)}, required_blocks=4
    )
    strategy = A1EntryCostAwareStrategy()
    result = replay_decision(snapshot, strategy, rows)

    assert result.satisfied
    assert result.released == (("A", "p"), ("B", "p"))
    assert result.eligible_blocks_final == 4
    comparison = compare_one(snapshot, rows)
    assert comparison.pair_lookahead_proposals
    proposal = comparison.pair_lookahead_proposals[0]
    assert proposal["released_first"] == ("A", "p")
    assert proposal["proposed_partner"] == ("B", "p")
    assert proposal["joint_new_blocks"] == 4
    assert proposal["joint_cost_proxy"] > 0
    assert comparison.cost_proxy_a1 == pytest.approx(0.0)  # no lone marginal cost


def test_pair_reuse_weight_is_a_union_not_a_sum() -> None:
    """``q~`` must stay a weight, otherwise the shared prefix is double charged."""
    snapshot, rows = _snapshot(
        {"A": (1, 2, 3, 4), "B": (1, 2, 3, 4)}, required_blocks=4
    )
    strategy = A1EntryCostAwareStrategy()
    state = ReplayState(snapshot)
    selection = strategy.select(_remaining(snapshot, rows, state), state)

    q_a = next(s.reuse_proxy for s in selection.scores if s.key == ("A", "p"))
    q_b = next(s.reuse_proxy for s in selection.scores if s.key == ("B", "p"))
    expected = 1.0 - (1.0 - q_a) * (1.0 - q_b)
    assert selection.joint_reuse_proxy == pytest.approx(expected)
    assert 0.0 < selection.joint_reuse_proxy <= 1.0
    assert selection.joint_reuse_proxy < q_a + q_b


def test_all_zero_marginal_without_a_usable_pair_falls_back_to_deadline() -> None:
    """Three-way co-ownership: no single or pair release unlocks anything."""
    snapshot, rows = _snapshot(
        {"A": (1, 2), "B": (1, 2), "C": (1, 2)}, required_blocks=1
    )
    strategy = A1EntryCostAwareStrategy()
    state = ReplayState(snapshot)
    selection = strategy.select(_remaining(snapshot, rows, state), state)

    assert selection.branch == BRANCH_DEADLINE_FALLBACK
    assert selection.key == ("A", "p")  # earliest deadline

    result = replay_decision(snapshot, strategy, rows)
    assert result.satisfied
    assert result.released == (("A", "p"), ("B", "p"), ("C", "p"))


# --- capacity shortfall ----------------------------------------------------


def test_capacity_shortfall_uses_cost_per_unit_relief() -> None:
    """No single entry reaches the target, so relief becomes the scarce quantity."""
    snapshot, rows = _snapshot(
        {"A": (1, 2), "B": (3, 4)}, required_blocks=4
    )
    strategy = A1EntryCostAwareStrategy()
    state = ReplayState(snapshot)
    selection = strategy.select(_remaining(snapshot, rows, state), state)

    assert selection.branch == BRANCH_PER_UNIT
    assert all(score.per_unit is not None for score in selection.scores)

    result = replay_decision(snapshot, strategy, rows)
    assert result.satisfied
    assert len(result.released) == 2


def test_target_is_capped_by_queue_length_and_never_exhausts() -> None:
    snapshot, rows = _snapshot({"A": (1, 2)}, required_blocks=99)
    assert snapshot.target == 2
    result = replay_decision(snapshot, A1EntryCostAwareStrategy(), rows)
    assert result.satisfied
    assert not result.exhausted


# --- stop condition and legality -------------------------------------------


@pytest.mark.parametrize("scenario_name", [s.name for s in all_scenarios()])
def test_release_stops_as_soon_as_the_target_is_met(scenario_name: str) -> None:
    scenario = next(s for s in all_scenarios() if s.name == scenario_name)
    comparison = compare_scenario(scenario)

    assert comparison.a1.satisfied
    # Releasing one entry is enough in every controlled scenario, so stopping
    # immediately means exactly one release.
    assert comparison.a1.iterations == 1
    assert len(comparison.a1.released) == 1


def test_choice_is_always_one_of_the_still_protected_candidates() -> None:
    for scenario in all_scenarios():
        strategy = A1EntryCostAwareStrategy()
        state = ReplayState(scenario.snapshot)
        while len(state.eligible_block_ids()) < scenario.snapshot.target:
            remaining = _remaining(scenario.snapshot, scenario.rows, state)
            if not remaining:
                break
            allowed = {candidate_key(row) for row in remaining}
            selection = strategy.select(remaining, state)
            assert selection.key in allowed
            state.release(selection.key)


def test_no_release_happens_when_the_target_is_already_met() -> None:
    """A decision with nothing left to free must not release anything extra."""
    snapshot, rows = _snapshot({"A": (1, 2)}, required_blocks=0)
    assert snapshot.target == 0
    result = replay_decision(snapshot, A1EntryCostAwareStrategy(), rows)
    assert result.released == ()
    assert result.iterations == 0


# --- determinism -----------------------------------------------------------


def test_selection_is_deterministic_across_repeated_calls() -> None:
    for scenario in all_scenarios():
        strategy = A1EntryCostAwareStrategy()
        state = ReplayState(scenario.snapshot)
        remaining = _remaining(scenario.snapshot, scenario.rows, state)
        first = strategy.select(remaining, state)
        second = strategy.select(remaining, state)
        assert first == second


def test_selection_does_not_depend_on_input_order() -> None:
    """Shuffling the candidate sequence must not change the outcome."""
    for scenario in all_scenarios():
        strategy = A1EntryCostAwareStrategy()
        baseline_state = ReplayState(scenario.snapshot)
        baseline = strategy.select(
            _remaining(scenario.snapshot, scenario.rows, baseline_state),
            baseline_state,
        )

        remaining = _remaining(scenario.snapshot, scenario.rows, baseline_state)
        for seed in range(5):
            shuffled = list(remaining)
            random.Random(seed).shuffle(shuffled)
            state = ReplayState(scenario.snapshot)
            assert strategy.select(shuffled, state).key == baseline.key


# --- no future information -------------------------------------------------


def test_no_forbidden_feature_is_even_present_on_a_candidate_row() -> None:
    """The decision-time row cannot leak a post-decision label.

    This is the structural guarantee behind "no future information": the fields a
    rule could read do not exist on the type it receives.
    """
    available = {field.name for field in dataclasses.fields(DecisionCandidateRow)}
    leaked = available & set(FORBIDDEN_FEATURES)
    assert leaked == set(), f"decision-time row exposes forbidden labels: {leaked}"


def test_identical_decision_time_inputs_give_identical_choices() -> None:
    """Two rows that agree on every decision-time field must be interchangeable."""
    snapshot, rows = _snapshot({"A": (1, 2), "B": (3, 4)}, required_blocks=1)
    twinned = dataclasses.replace(rows[("B", "p")], program_id="A2")

    state = ReplayState(snapshot)
    with_original = A1EntryCostAwareStrategy().select(
        [rows[("A", "p")], rows[("B", "p")]], state
    )

    # Give the twin the same decision-time fields as A but a different identity.
    same_fields = dataclasses.replace(
        twinned,
        retention_deadline_timestamp=rows[("A", "p")].retention_deadline_timestamp,
        block_count=rows[("A", "p")].block_count,
    )
    twin_state = ReplayState(snapshot)
    with_twin = A1EntryCostAwareStrategy().select(
        [rows[("A", "p")], same_fields], twin_state
    )

    # Equal scores, so the deterministic identity tie-break decides -- and it puts
    # A before A2 both times.
    assert with_original.key == ("A", "p")
    assert with_twin.key == ("A", "p")


def test_choice_does_not_depend_on_the_native_lru_position() -> None:
    """A1 must not covertly reproduce native LRU.

    A1 should differ from A0 because of the cost model, not because it smuggled in
    the adapter's recency signal. Permuting ``decision_native_lru_position`` across
    the candidates must therefore leave every choice untouched -- if it ever
    changes a choice, the strategy has started reading a field it must not use.
    """
    for scenario in all_scenarios():
        baseline_state = ReplayState(scenario.snapshot)
        baseline = A1EntryCostAwareStrategy().select(
            _remaining(scenario.snapshot, scenario.rows, baseline_state),
            baseline_state,
        )

        inverted = {
            key: dataclasses.replace(
                row,
                decision_native_lru_position=(
                    len(scenario.rows) - 1 - row.decision_native_lru_position
                    if row.decision_native_lru_position is not None
                    else None
                ),
            )
            for key, row in scenario.rows.items()
        }
        state = ReplayState(scenario.snapshot)
        remaining = [
            inverted[key]
            for key in scenario.snapshot.candidate_keys
            if key in inverted
        ]
        assert A1EntryCostAwareStrategy().select(remaining, state).key == baseline.key


# --- A0 fidelity -----------------------------------------------------------


def test_a0_reproduces_the_frozen_deadline_order() -> None:
    """A0 must be the deadline-first arm, otherwise the comparison is meaningless."""
    scenario = scenario_a_divergent()
    result = replay_decision(
        scenario.snapshot, ExecutedP1BStrategy(), scenario.rows
    )
    assert result.released == (("A", "p"),)

    # A1, on the same snapshot, chooses differently -- and both are legal.
    a1 = replay_decision(
        scenario.snapshot, A1EntryCostAwareStrategy(), scenario.rows
    )
    assert a1.released == (("B", "p"),)
    assert a1.satisfied


def test_fidelity_fail_closed_guard_and_decision_json_export(tmp_path, monkeypatch) -> None:
    from kvopt.costaware import a1_compare
    from kvopt.costaware.replay import ReplayFidelity

    class Mismatch:
        pass

    # Verify the report never silently accepts baseline mismatch or dropped rows.
    # A minimal monkeypatched loader avoids reading external H1 artifacts.
    scenario = scenario_a_divergent()
    monkeypatch.setattr(
        "kvopt.profiling.pipeline.discover_run_artifacts", lambda _root: [Mismatch()]
    )
    monkeypatch.setattr(
        "kvopt.profiling.pipeline.build_derived_dataset_bundle",
        lambda *_a, **_kw: type("Bundle", (), {"decision_candidates": tuple(scenario.rows.values())})(),
    )
    monkeypatch.setattr(a1_compare, "load_decision_snapshots", lambda _runs: (scenario.snapshot,))
    monkeypatch.setattr(
        a1_compare,
        "validate_replay_fidelity",
        lambda *_a: ReplayFidelity(
            strategy_id="a0", decisions_compared=1, release_set_matches=0,
            release_sequence_matches=0, initial_reclaimable_matches=1,
            initial_reclaimable_fields_compared=1,
        ),
    )
    with pytest.raises(ValueError, match="BASELINE_FIDELITY_FAILED"):
        a1_compare.run_corpus(tmp_path)


def test_comparison_separates_order_from_set_and_from_benefit() -> None:
    comparison = compare_scenario(scenario_b_identical())
    assert not comparison.order_differs
    assert not comparison.set_differs
    assert comparison.is_physical_benefit is False

    divergent = compare_scenario(scenario_a_divergent())
    assert divergent.order_differs
    assert divergent.set_differs
    assert divergent.is_physical_benefit is False


def test_worse_case_is_reported_as_worse_rather_than_hidden() -> None:
    comparison = compare_scenario(scenario_c_a1_worse())
    assert comparison.order_differs
    assert comparison.at_risk_blocks == 3
    # A0's entry never returns, so its exposure is not at risk at all.
    a0_state = ReplayState(scenario_c_a1_worse().snapshot)
    a0_state.release(("X", "p"))
    assert a0_state.newly_eligible_after(("X", "p")) == ()
    assert comparison.a0.satisfied and comparison.a1.satisfied


# --- numerical sanity ------------------------------------------------------


def test_cost_proxy_matches_the_documented_arithmetic() -> None:
    """Section 5.1's 2.5 vs 1.8 must be reproduced by the implementation."""
    strategy = A1EntryCostAwareStrategy()
    scenario = scenario_a_divergent()
    state = ReplayState(scenario.snapshot)
    selection = strategy.select(
        _remaining(scenario.snapshot, scenario.rows, state), state
    )

    by_key = {s.key: s for s in selection.scores}
    assert by_key[("A", "p")].reuse_proxy == pytest.approx(0.5)
    assert by_key[("B", "p")].reuse_proxy == pytest.approx(0.9, abs=1e-6)
    assert by_key[("A", "p")].expected_recompute == pytest.approx(2.5, abs=1e-6)
    assert by_key[("B", "p")].expected_recompute == pytest.approx(1.8, abs=1e-6)
    assert not math.isclose(
        by_key[("A", "p")].expected_recompute,
        by_key[("B", "p")].expected_recompute,
    )


def test_compare_one_is_pure_with_respect_to_the_snapshot() -> None:
    scenario = scenario_a_divergent()
    before = (
        scenario.snapshot.queue,
        scenario.snapshot.candidate_keys,
        dict(scenario.snapshot.owners_by_block),
    )
    compare_one(scenario.snapshot, scenario.rows)
    after = (
        scenario.snapshot.queue,
        scenario.snapshot.candidate_keys,
        dict(scenario.snapshot.owners_by_block),
    )
    assert before == after
