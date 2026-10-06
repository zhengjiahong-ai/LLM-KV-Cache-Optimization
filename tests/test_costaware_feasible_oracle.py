"""Tests for the pressure-feasible hindsight oracle."""

from __future__ import annotations

from pathlib import Path

import pytest

from kvopt.costaware.feasible_oracle import (
    MAX_EXACT_CANDIDATES,
    FeasibleOracleRow,
    build_feasible_oracle,
    pressure_feasible_regret,
)
from kvopt.costaware.offline_eval import evaluate_rules
from kvopt.costaware.replay import DecisionSnapshot, QueueBlock
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.loss_views import CandidateLossEvidenceRow

_EXEMPLARS = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "experiments"
    / "phase2a-m6-formal"
    / "curated-evidence"
    / "exemplars"
)
_VIEW = "planned_return_weighted_prefill_proxy"


def _snapshot(
    *,
    entries: dict[str, tuple[int, ...]],
    required_blocks: int,
    run_id: str = "run-1",
    decision_event_index: int = 40,
    shared_hashes: bool = True,
) -> DecisionSnapshot:
    blocks: list[int] = []
    for owned in entries.values():
        for block_id in owned:
            if block_id not in blocks:
                blocks.append(block_id)
    blocks.sort()
    ranking = {block_id: rank for rank, block_id in enumerate(blocks)}
    owners: dict[int, set[tuple[str, str]]] = {}
    for program_id, owned in entries.items():
        for block_id in owned:
            owners.setdefault(block_id, set()).add((program_id, "p"))
    return DecisionSnapshot(
        run_id=run_id,
        decision_event_index=decision_event_index,
        timestamp=1.0,
        required_blocks=required_blocks,
        queue=tuple(
            QueueBlock(
                block_id=block_id,
                has_block_hash=shared_hashes,
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
            (program_id, "p"): owned for program_id, owned in entries.items()
        },
        ranking_by_block=ranking,
    )


def _losses(
    snapshot: DecisionSnapshot, values: dict[str, float]
) -> dict[tuple[str, int, tuple[str, str]], float]:
    return {
        (snapshot.run_id, snapshot.decision_event_index, (program_id, "p")): loss
        for program_id, loss in values.items()
    }


def _oracle(
    snapshot: DecisionSnapshot, values: dict[str, float]
) -> FeasibleOracleRow:
    rows = build_feasible_oracle(
        [snapshot], _losses(snapshot, values), loss_view=_VIEW
    )
    assert len(rows) == 1
    return rows[0]


# --- oracle invariant -------------------------------------------------------


def test_oracle_result_actually_satisfies_the_target() -> None:
    """The oracle must be feasible, not just cheap."""
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3,), "c": (4, 5)}, required_blocks=4
    )
    row = _oracle(snapshot, {"a": 0.9, "b": 0.1, "c": 0.2})
    assert row.unreachable is False
    from kvopt.costaware.feasible_oracle import _subset_eligible_count

    assert (
        _subset_eligible_count(snapshot, frozenset(row.oracle_released))
        >= snapshot.target
    )


def test_oracle_prefers_the_cheapest_feasible_set() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5, 6), "c": (7, 8)},
        required_blocks=4,
    )
    # a alone satisfies 4 blocks for 0.3; b+c would satisfy 4 but costs 0.4.
    row = _oracle(snapshot, {"a": 0.3, "b": 0.2, "c": 0.2})
    assert row.oracle_released == (("a", "p"),)
    assert row.oracle_loss == pytest.approx(0.3)
    assert row.oracle_entry_count == 1


def test_oracle_prefers_two_cheap_entries_over_one_expensive_entry() -> None:
    """The primary criterion is loss, not the number of entries."""
    snapshot = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5, 6), "c": (7, 8)},
        required_blocks=4,
    )
    # a alone costs 0.5; b+c cost 0.4, so the two-entry set wins.
    row = _oracle(snapshot, {"a": 0.5, "b": 0.2, "c": 0.2})
    assert set(row.oracle_released) == {("b", "p"), ("c", "p")}
    assert row.oracle_loss == pytest.approx(0.4)
    assert row.oracle_entry_count == 2


def test_oracle_picks_a_multi_entry_set_when_that_is_cheaper() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5, 6), "c": (7, 8)},
        required_blocks=4,
    )
    row = _oracle(snapshot, {"a": 9.0, "b": 0.1, "c": 0.1})
    assert set(row.oracle_released) == {("b", "p"), ("c", "p")}
    assert row.oracle_loss == pytest.approx(0.2)
    assert row.oracle_entry_count == 2


# --- shared ownership -------------------------------------------------------


def test_shared_ownership_blocks_need_every_owner_released() -> None:
    """A co-owned block only counts once all of its owners are released."""
    snapshot = _snapshot(
        entries={"a": (1, 2, 3), "b": (3, 4, 5)}, required_blocks=3
    )
    # Releasing a alone frees {1,2} = 2 < 3; b alone frees {4,5} = 2 < 3;
    # together they free {1,2,3,4,5} = 5 >= 3.
    row = _oracle(snapshot, {"a": 0.1, "b": 0.1})
    assert set(row.oracle_released) == {("a", "p"), ("b", "p")}
    assert row.oracle_entry_count == 2
    assert row.full_candidate_set_is_required is True


def test_shared_ownership_does_not_double_count_the_co_owned_block() -> None:
    """Releasing one owner of a co-owned block does not free that block.

    ``a`` owns {1,2} and ``b`` owns {2}. Releasing ``a`` frees only block 1,
    because block 2 still has the protected owner ``b``. Summing the two
    entries' reported reclaimable counts would wrongly suggest 3 blocks.
    """
    snapshot = _snapshot(entries={"a": (1, 2), "b": (2,)}, required_blocks=2)
    from kvopt.costaware.feasible_oracle import _subset_eligible_count

    assert _subset_eligible_count(snapshot, frozenset({("a", "p")})) == 1
    assert _subset_eligible_count(snapshot, frozenset({("b", "p")})) == 0
    assert _subset_eligible_count(
        snapshot, frozenset({("a", "p"), ("b", "p")})
    ) == 2
    # Only the pair reaches the target, so the oracle must release both.
    row = _oracle(snapshot, {"a": 0.3, "b": 0.0})
    assert set(row.oracle_released) == {("a", "p"), ("b", "p")}
    assert row.oracle_loss == pytest.approx(0.3)


# --- multiple feasible sets and tie semantics -------------------------------


def test_multiple_feasible_sets_are_all_counted() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3, 4), "c": (5, 6)}, required_blocks=2
    )
    row = _oracle(snapshot, {"a": 0.1, "b": 0.2, "c": 0.3})
    # Every single entry satisfies 2 blocks, plus every pair and the triple.
    assert row.feasible_set_count == 3 + 3 + 1


def test_different_release_counts_are_compared_by_loss_first() -> None:
    """A two-entry set can beat a one-entry set, so count is not primary."""
    snapshot = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5, 6), "c": (7, 8)},
        required_blocks=4,
    )
    row = _oracle(snapshot, {"a": 1.0, "b": 0.1, "c": 0.1})
    assert row.oracle_entry_count == 2
    assert row.oracle_loss == pytest.approx(0.2)


def test_zero_loss_tie_is_broken_by_fewest_entries() -> None:
    """Secondary criterion: among equal-loss sets prefer the smallest."""
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3, 4), "c": (5, 6)}, required_blocks=2
    )
    row = _oracle(snapshot, {"a": 0.0, "b": 0.0, "c": 0.0})
    assert row.oracle_loss == pytest.approx(0.0)
    assert row.oracle_entry_count == 1
    # Tertiary criterion picks the lowest identity among the tied single entries.
    assert row.oracle_released == (("a", "p"),)


def test_stable_tie_semantics_use_identity_order() -> None:
    """Two entries that both satisfy and both cost the same resolve by identity."""
    snapshot = _snapshot(entries={"z": (1, 2), "a": (3, 4)}, required_blocks=2)
    row = _oracle(snapshot, {"z": 0.5, "a": 0.5})
    assert row.oracle_released == (("a", "p"),)


def test_oracle_is_deterministic_across_calls() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3, 4), "c": (5, 6)}, required_blocks=2
    )
    values = {"a": 0.2, "b": 0.2, "c": 0.2}
    first = _oracle(snapshot, values)
    for _ in range(3):
        assert _oracle(snapshot, values) == first


def test_loss_choices_matter_detects_a_flat_decision() -> None:
    """Flat means every feasible set costs the same, not every rule is tied."""
    # Only the pair reaches 4 blocks, so there is exactly one feasible set.
    single = _snapshot(
        entries={"a": (1, 2), "b": (3, 4)}, required_blocks=4
    )
    assert _oracle(single, {"a": 0.5, "b": 0.5}).loss_choices_matter is False

    # Two feasible sets with different costs make the choice matter.
    varied = _snapshot(
        entries={"a": (1, 2), "b": (3, 4)}, required_blocks=2
    )
    assert _oracle(varied, {"a": 0.5, "b": 0.0}).loss_choices_matter is True


# --- no feasible proper subset ---------------------------------------------


def test_no_feasible_proper_subset_reports_the_full_set() -> None:
    snapshot = _snapshot(entries={"a": (1,), "b": (2,)}, required_blocks=2)
    row = _oracle(snapshot, {"a": 0.1, "b": 0.2})
    assert row.oracle_entry_count == 2
    assert row.full_candidate_set_is_required is True
    assert row.oracle_loss == pytest.approx(0.3)


def test_full_candidate_set_is_not_required_when_a_subset_suffices() -> None:
    snapshot = _snapshot(entries={"a": (1, 2), "b": (3,)}, required_blocks=2)
    row = _oracle(snapshot, {"a": 0.1, "b": 0.2})
    assert row.full_candidate_set_is_required is False


def test_unreachable_snapshot_is_flagged_not_silently_zero() -> None:
    """No candidates can never satisfy a positive target."""
    snapshot = _snapshot(entries={}, required_blocks=2)
    snapshot = DecisionSnapshot(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        timestamp=snapshot.timestamp,
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
    row = _oracle(snapshot, {})
    assert row.unreachable is True
    assert row.feasible_set_count == 0
    assert row.loss_choices_matter is False


def test_unlabelled_decision_is_skipped() -> None:
    snapshot = _snapshot(entries={"a": (1,), "b": (2,)}, required_blocks=1)
    losses = _losses(snapshot, {"a": 0.1})
    assert build_feasible_oracle([snapshot], losses, loss_view=_VIEW) == ()


def test_included_runs_restricts_the_oracle() -> None:
    snapshot = _snapshot(entries={"a": (1,)}, required_blocks=1)
    rows = build_feasible_oracle(
        [snapshot],
        _losses(snapshot, {"a": 0.1}),
        loss_view=_VIEW,
        included_runs=frozenset({"other-run"}),
    )
    assert rows == ()


def test_candidate_cap_refuses_to_approximate() -> None:
    entries = {f"pg-{index:02d}": (index,) for index in range(MAX_EXACT_CANDIDATES + 1)}
    snapshot = _snapshot(entries=entries, required_blocks=1)
    with pytest.raises(ValueError, match="refusing to approximate"):
        _oracle(snapshot, {key: 0.1 for key in entries})


# --- pressure-feasible regret ----------------------------------------------


def test_pressure_feasible_regret_matches_hand_computed_values() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3, 4), "c": (5, 6)}, required_blocks=2
    )
    losses = _losses(snapshot, {"a": 0.5, "b": 0.1, "c": 0.0})
    oracle = build_feasible_oracle([snapshot], losses, loss_view=_VIEW)
    rows = pressure_feasible_regret(
        oracle_rows=oracle,
        selections={"rule": {("run-1", 40): (("a", "p"),)}},
        losses=losses,
        loss_view=_VIEW,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.selected_loss == pytest.approx(0.5)
    assert row.oracle_loss == pytest.approx(0.0)
    assert row.absolute_regret == pytest.approx(0.5)
    # Canonical M6 formula: absolute / max(|selected|, epsilon).
    assert row.normalized_regret == pytest.approx(1.0)
    assert row.selected_is_oracle_best is False
    assert row.entry_count_delta == 0


def test_pressure_feasible_regret_is_zero_for_the_oracle_set() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3, 4), "c": (5, 6)}, required_blocks=2
    )
    losses = _losses(snapshot, {"a": 0.5, "b": 0.1, "c": 0.0})
    oracle = build_feasible_oracle([snapshot], losses, loss_view=_VIEW)
    rows = pressure_feasible_regret(
        oracle_rows=oracle,
        selections={"rule": {("run-1", 40): (("c", "p"),)}},
        losses=losses,
        loss_view=_VIEW,
    )
    assert rows[0].absolute_regret == pytest.approx(0.0)
    assert rows[0].normalized_regret == pytest.approx(0.0)
    assert rows[0].selected_is_oracle_best is True


def test_pressure_feasible_regret_reports_entry_count_delta() -> None:
    snapshot = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5, 6), "c": (7, 8)},
        required_blocks=4,
    )
    losses = _losses(snapshot, {"a": 0.1, "b": 0.1, "c": 0.1})
    oracle = build_feasible_oracle([snapshot], losses, loss_view=_VIEW)
    # Oracle takes one entry; the rule takes three.
    rows = pressure_feasible_regret(
        oracle_rows=oracle,
        selections={
            "rule": {("run-1", 40): (("a", "p"), ("b", "p"), ("c", "p"))}
        },
        losses=losses,
        loss_view=_VIEW,
    )
    assert rows[0].entry_count_delta == 2


def test_pressure_feasible_regret_skips_unreachable_oracles() -> None:
    snapshot = _snapshot(entries={"a": (1,)}, required_blocks=1)
    losses = _losses(snapshot, {"a": 0.1})
    unreachable = FeasibleOracleRow(
        run_id="run-1",
        decision_event_index=40,
        loss_view=_VIEW,
        target=1,
        candidate_count=1,
        feasible_set_count=0,
        oracle_released=(),
        oracle_loss=float("nan"),
        oracle_entry_count=0,
        worst_feasible_loss=float("nan"),
        unreachable=True,
    )
    rows = pressure_feasible_regret(
        oracle_rows=(unreachable,),
        selections={"rule": {("run-1", 40): (("a", "p"),)}},
        losses=losses,
        loss_view=_VIEW,
    )
    assert rows == ()


# --- integration with the evaluator ----------------------------------------


def _row(
    *,
    run_id: str,
    decision_event_index: int,
    program_id: str,
    block_ids: tuple[int, ...],
    prefill_reload_seconds: float,
    selected: bool,
    retention_deadline_timestamp: float = 100.0,
    decision_native_lru_position: int = 0,
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id=run_id,
        decision_event_index=decision_event_index,
        source_event_index=decision_event_index,
        candidate_position=decision_native_lru_position,
        program_id=program_id,
        prefix_id="p",
        selected=selected,
        release_order=1 if selected else None,
        retention_deadline_timestamp=retention_deadline_timestamp,
        waiting_followup=True,
        block_ids=block_ids,
        block_count=len(block_ids),
        initially_reclaimable_block_ids=block_ids,
        initially_reclaimable_block_count=len(block_ids),
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=prefill_reload_seconds,
        eta=1.0,
        queue_delay_t_seconds=0.5,
        decision_native_lru_position=decision_native_lru_position,
    )


def test_evaluator_exposes_both_comparators_separately() -> None:
    """Canonical M6 regret and the feasible oracle must not be merged."""
    snapshot = _snapshot(
        entries={"a": (1, 2), "b": (3, 4), "c": (5, 6)}, required_blocks=2
    )
    candidates = (
        _row(run_id="run-1", decision_event_index=40, program_id="a",
             block_ids=(1, 2), prefill_reload_seconds=0.5, selected=True),
        _row(run_id="run-1", decision_event_index=40, program_id="b",
             block_ids=(3, 4), prefill_reload_seconds=0.1, selected=False),
        _row(run_id="run-1", decision_event_index=40, program_id="c",
             block_ids=(5, 6), prefill_reload_seconds=0.0, selected=False),
    )
    evidence = tuple(
        CandidateLossEvidenceRow(
            run_id="run-1",
            decision_event_index=40,
            program_id=program_id,
            prefix_id="p",
            selected=False,
            loss_view=_VIEW,
            evidence_kind="trace_derived_proxy",
            unit="seconds",
            loss=loss,
            availability="available",
            unavailable_reason=None,
            source_event_indexes=(40,),
        )
        for program_id, loss in (("a", 0.5), ("b", 0.1), ("c", 0.0))
    )
    evaluation = evaluate_rules(
        candidates=candidates,
        evidence=evidence,
        snapshots=(snapshot,),
    )
    assert evaluation.oracle_rows
    assert evaluation.pressure_feasible_aggregates
    # Both comparators present, and they are distinct objects.
    assert evaluation.for_rule("M0_p1b_executed_ordering")
    assert evaluation.feasible_for_rule("M0_p1b_executed_ordering")
    baseline_feasible = evaluation.feasible_for_rule("M0_p1b_executed_ordering")
    # The baseline loses 0.5 where 0.0 was reachable, so no decision is zero
    # regret and the normalised regret is the degenerate maximum of 1.0.
    assert baseline_feasible.zero_regret_rate == pytest.approx(0.0)
    assert baseline_feasible.positive_regret_decisions == 1
    assert baseline_feasible.mean_normalized_regret == pytest.approx(1.0)
    assert baseline_feasible.mean_absolute_regret == pytest.approx(0.5)
    assert baseline_feasible.median_absolute_regret == pytest.approx(0.5)
    # Compared with itself one entry short of the oracle, the baseline is tied on
    # loss but never better.
    assert baseline_feasible.better_than_baseline_decisions == 0
    assert baseline_feasible.worse_than_baseline_decisions == 0
    assert baseline_feasible.tied_with_baseline_decisions == 1
    assert baseline_feasible.mean_paired_loss_delta_vs_baseline == pytest.approx(
        0.0
    )


def test_evaluator_feasible_aggregate_reports_entry_delta() -> None:
    """The baseline needs two releases where the oracle needs one."""
    snapshot = _snapshot(
        entries={"a": (1, 2, 3, 4), "b": (5, 6), "c": (7, 8)},
        required_blocks=4,
    )
    # Deadlines force the baseline (earliest deadline first) onto b then c,
    # while the oracle only needs a.
    candidates = (
        _row(run_id="run-1", decision_event_index=40, program_id="a",
             block_ids=(1, 2, 3, 4), prefill_reload_seconds=0.1, selected=False,
             retention_deadline_timestamp=300.0),
        _row(run_id="run-1", decision_event_index=40, program_id="b",
             block_ids=(5, 6), prefill_reload_seconds=0.1, selected=True,
             retention_deadline_timestamp=100.0),
        _row(run_id="run-1", decision_event_index=40, program_id="c",
             block_ids=(7, 8), prefill_reload_seconds=0.1, selected=True,
             retention_deadline_timestamp=200.0),
    )
    evidence = tuple(
        CandidateLossEvidenceRow(
            run_id="run-1",
            decision_event_index=40,
            program_id=program_id,
            prefix_id="p",
            selected=False,
            loss_view=_VIEW,
            evidence_kind="trace_derived_proxy",
            unit="seconds",
            loss=0.1,
            availability="available",
            unavailable_reason=None,
            source_event_indexes=(40,),
        )
        for program_id in ("a", "b", "c")
    )
    evaluation = evaluate_rules(
        candidates=candidates, evidence=evidence, snapshots=(snapshot,)
    )
    oracle = evaluation.oracle_rows[0]
    assert oracle.oracle_entry_count == 1
    assert set(oracle.oracle_released) == {("a", "p")}
    aggregate = evaluation.feasible_for_rule("M0_p1b_executed_ordering")
    # The baseline releases b and c: one entry more than the oracle, at the cost
    # of an extra 0.1 of reload loss.
    assert aggregate.mean_entry_count_delta == pytest.approx(1.0)
    assert aggregate.zero_regret_rate == pytest.approx(0.0)
    assert aggregate.positive_regret_decisions == 1
    assert aggregate.mean_absolute_regret == pytest.approx(0.1)


def test_zero_regret_is_not_a_misselection() -> None:
    """Q9/Q11: another equally optimal set still counts as zero regret.

    Every release set satisfies the target at the same total loss, so the
    lexicographic oracle picks one specific set but the baseline's different
    choice costs nothing. It must not be scored as a misselection.
    """
    snapshot = _snapshot(entries={"a": (1,), "b": (2,)}, required_blocks=1)
    candidates = (
        _row(run_id="run-1", decision_event_index=40, program_id="a",
             block_ids=(1,), prefill_reload_seconds=0.1, selected=True,
             retention_deadline_timestamp=100.0),
        _row(run_id="run-1", decision_event_index=40, program_id="b",
             block_ids=(2,), prefill_reload_seconds=0.1, selected=False,
             retention_deadline_timestamp=200.0),
    )
    evidence = tuple(
        CandidateLossEvidenceRow(
            run_id="run-1",
            decision_event_index=40,
            program_id=program_id,
            prefix_id="p",
            selected=False,
            loss_view=_VIEW,
            evidence_kind="trace_derived_proxy",
            unit="seconds",
            loss=0.2,
            availability="available",
            unavailable_reason=None,
            source_event_indexes=(40,),
        )
        for program_id in ("a", "b")
    )
    evaluation = evaluate_rules(
        candidates=candidates, evidence=evidence, snapshots=(snapshot,)
    )
    aggregate = evaluation.feasible_for_rule("M0_p1b_executed_ordering")
    assert aggregate.zero_regret_rate == pytest.approx(1.0)
    assert aggregate.positive_regret_decisions == 0
    assert aggregate.mean_absolute_regret == pytest.approx(0.0)
    assert aggregate.median_absolute_regret == pytest.approx(0.0)


def test_evaluator_feasible_aggregate_rejects_unknown_rule() -> None:
    candidates = (
        _row(run_id="run-1", decision_event_index=40, program_id="a",
             block_ids=(1,), prefill_reload_seconds=0.1, selected=True),
    )
    evidence = (
        CandidateLossEvidenceRow(
            run_id="run-1",
            decision_event_index=40,
            program_id="a",
            prefix_id="p",
            selected=False,
            loss_view=_VIEW,
            evidence_kind="trace_derived_proxy",
            unit="seconds",
            loss=0.1,
            availability="available",
            unavailable_reason=None,
            source_event_indexes=(40,),
        ),
    )
    # Single candidate decisions are skipped by the evaluator, so build a
    # two-candidate one to get a populated aggregate, then probe the lookup.
    snapshot2 = _snapshot(entries={"a": (1,), "b": (2,)}, required_blocks=2)
    evaluation = evaluate_rules(
        candidates=candidates
        + (
            _row(run_id="run-1", decision_event_index=40, program_id="b",
                 block_ids=(2,), prefill_reload_seconds=0.1, selected=False),
        ),
        evidence=evidence
        + (
            CandidateLossEvidenceRow(
                run_id="run-1",
                decision_event_index=40,
                program_id="b",
                prefix_id="p",
                selected=False,
                loss_view=_VIEW,
                evidence_kind="trace_derived_proxy",
                unit="seconds",
                loss=0.1,
                availability="available",
                unavailable_reason=None,
                source_event_indexes=(40,),
            ),
        ),
        snapshots=(snapshot2,),
    )
    with pytest.raises(KeyError, match="pressure-feasible"):
        evaluation.feasible_for_rule("not_a_rule")


# --- against the real in-repo artifacts ------------------------------------


def test_oracle_over_real_exemplars_finds_zero_loss_feasible_sets() -> None:
    """The in-repo exemplars all admit a single zero-loss feasible release.

    This is the reason the feasible comparator is stricter than the canonical
    size-matched one on this sample. Recorded as an observation, not a result:
    the sample is 3 decisions and seed 101 only.
    """
    from kvopt.costaware.replay import load_decision_snapshots
    from kvopt.profiling.pipeline import (
        build_derived_dataset_bundle,
        discover_run_artifacts,
    )

    raw_runs = discover_run_artifacts(_EXEMPLARS)
    bundle = build_derived_dataset_bundle(raw_runs)
    snapshots = load_decision_snapshots(raw_runs)
    losses = {
        (row.run_id, row.decision_event_index, (row.program_id, row.prefix_id)): float(
            row.loss
        )
        for row in bundle.candidate_loss_evidence
        if row.loss_view == _VIEW
        and row.availability == "available"
        and row.loss is not None
    }
    rows = build_feasible_oracle(snapshots, losses, loss_view=_VIEW)
    assert len(rows) == 3
    for row in rows:
        assert row.unreachable is False
        assert row.oracle_entry_count == 1
        assert row.oracle_loss == pytest.approx(0.0)
        assert row.loss_choices_matter is True
