"""Tests for the Phase 2I suffix cost proxy strategy.

Coverage required by M1 (sections A, C and D of the implementation authorisation):

- A  frozen behaviour compatibility: A1's Steps 1 and 3-5 are reproduced exactly,
     missing cost information falls back, Step 2 uses the frozen formula with a
     deterministic tie-break;
- C  victim prediction matches the frozen eligibility ordering;
- D  at least one synthetic decision where the new rule and A0 provably differ,
     with every input and both choices recomputable.

``L(X) = q_X * prefill_X * S_X / m_X`` with ``S_X = m_X - d_min(X) + 1`` is the
only formula under test; nothing here reads or writes native state.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from kvopt.costaware.a1_entry import (
    BRANCH_DEADLINE_FALLBACK,
    BRANCH_PAIR_LOOKAHEAD,
    BRANCH_PER_UNIT,
    BRANCH_SINGLE_STEP,
    A1EntryCostAwareStrategy,
    default_tau_seconds,
    reuse_proxy,
)
from kvopt.costaware.a1_scenarios import DECISION_TIMESTAMP, all_scenarios
from kvopt.costaware.a3_suffix import (
    FAIL_NO_OBSERVATION,
    FAIL_PREFILL_MISSING,
    STEP_FALLBACK,
    STEP_NO_NEED,
    STEP_PAIR_LOOKAHEAD,
    STEP_PER_UNIT,
    STEP_SUFFICIENT,
    STRATEGY_ID,
    A3SuffixCostStrategy,
    CandidateCostAudit,
    build_strategy,
    predict_victims,
    replay_with_audit,
    step_for_branch,
)
from kvopt.costaware.entry_depth import ChainDepthIndex, DepthQuery
from kvopt.costaware.replay import (
    DecisionSnapshot,
    ExecutedP1BStrategy,
    QueueBlock,
    ReplayState,
    replay_decision,
)
from kvopt.profiling.datasets import DecisionCandidateRow

TAU = default_tau_seconds()
PREFIX = "p"
PROCESS = "pid-1"


# --- helpers ---------------------------------------------------------------


def _row(
    program_id: str,
    block_ids: tuple[int, ...],
    *,
    deadline: float,
    position: int,
    prefill: float = 1.0,
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id="unit",
        decision_event_index=0,
        source_event_index=0,
        candidate_position=position,
        program_id=program_id,
        prefix_id=PREFIX,
        selected=False,
        release_order=None,
        retention_deadline_timestamp=deadline,
        waiting_followup=True,
        block_ids=tuple(block_ids),
        block_count=len(block_ids),
        initially_reclaimable_block_ids=tuple(block_ids),
        initially_reclaimable_block_count=len(block_ids),
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=prefill,
        eta=1.0,
        queue_delay_t_seconds=0.5,
        decision_native_lru_position=position,
    )


def _snapshot(
    entries: dict[str, tuple[int, ...]],
    *,
    deadlines: dict[str, float],
    prefills: dict[str, float] | None = None,
    required_blocks: int,
    unhashed: tuple[int, ...] = (),
    timestamp: float = DECISION_TIMESTAMP,
    decision_index: int = 1000,
) -> tuple[DecisionSnapshot, dict[tuple[str, str], DecisionCandidateRow]]:
    """Build a decision whose queue ranks follow sorted block id order."""

    blocks: list[int] = []
    for owned in entries.values():
        for block_id in owned:
            if block_id not in blocks and block_id not in unhashed:
                blocks.append(block_id)
    blocks.extend(b for b in unhashed if b not in blocks)
    blocks.sort()
    ranking = {block_id: rank for rank, block_id in enumerate(blocks)}
    unhashed_set = set(unhashed)

    owners: dict[int, set[tuple[str, str]]] = {}
    rows: dict[tuple[str, str], DecisionCandidateRow] = {}
    for position, (program_id, owned) in enumerate(entries.items()):
        key = (program_id, PREFIX)
        for block_id in owned:
            if block_id in ranking:
                owners.setdefault(block_id, set()).add(key)
        rows[key] = _row(
            program_id,
            owned,
            deadline=deadlines[program_id],
            position=position,
            prefill=(prefills or {}).get(program_id, 1.0),
        )

    reclaimable = {
        key: tuple(
            block_id
            for block_id in entries[key[0]]
            if block_id in ranking and owners.get(block_id) == {key}
        )
        for key in rows
    }
    snapshot = DecisionSnapshot(
        run_id="unit",
        decision_event_index=decision_index,
        timestamp=timestamp,
        required_blocks=required_blocks,
        queue=tuple(
            QueueBlock(
                block_id=block_id,
                has_block_hash=block_id not in unhashed_set,
                native_lru_rank=ranking[block_id],
            )
            for block_id in blocks
        ),
        candidate_keys=tuple((program_id, PREFIX) for program_id in entries),
        owners_by_block={b: frozenset(v) for b, v in owners.items()},
        observed_selected=(),
        observed_initial_reclaimable=reclaimable,
        ranking_by_block=ranking,
    )
    for key, ids in reclaimable.items():
        rows[key] = dataclasses.replace(
            rows[key],
            initially_reclaimable_block_ids=ids,
            initially_reclaimable_block_count=len(ids),
        )
    return snapshot, rows


def _index(
    chains: dict[tuple[str, str], tuple[int, ...]],
    *,
    observation_index: int = 10,
    observed_at: float = 50.0,
    clock_domain: str = "continuum_pressure",
) -> ChainDepthIndex:
    """Record one observation per chain, all strictly before the decision."""

    index = ChainDepthIndex()
    for position, (key, chain) in enumerate(chains.items()):
        index.observe_chain(
            key,
            PROCESS,
            chain,
            content_hashes=tuple(f"key-{block_id}" for block_id in chain),
            observation_index=observation_index + position,
            observed_at=observed_at,
            clock_domain=clock_domain,
        )
    return index


def _strategy(index: ChainDepthIndex, **overrides: object) -> A3SuffixCostStrategy:
    kwargs: dict[str, object] = {
        "depth_index": index,
        "native_hash_process_id": PROCESS,
        "decision_clock_domain": "continuum_pressure",
    }
    kwargs.update(overrides)
    return A3SuffixCostStrategy(**kwargs)  # type: ignore[arg-type]


def _state(snapshot: DecisionSnapshot) -> ReplayState:
    return ReplayState(snapshot)


def _remaining(snapshot, rows, state):
    return [
        rows[key] for key in snapshot.candidate_keys if key not in state.released and key in rows
    ]


# --- C: victim prediction -------------------------------------------------


def test_predict_victims_takes_the_shallowest_native_ranks() -> None:
    ranking = {10: 0, 11: 1, 12: 2, 13: 3}
    # Deliberately out of order: the rule is rank order, not input order.
    assert predict_victims((13, 10, 12, 11), ranking, 2) == (10, 11)
    assert predict_victims((13, 10, 12, 11), ranking, 4) == (10, 11, 12, 13)


def test_predict_victims_truncates_at_deficit_not_at_relief() -> None:
    """``N_i`` is not the evicted count: relief 4 with deficit 2 kills 2 blocks."""

    ranking = {10: 0, 11: 1, 12: 2, 13: 3}
    victims = predict_victims((10, 11, 12, 13), ranking, 2)
    assert victims == (10, 11)
    assert len(victims) < 4


def test_predict_victims_ignores_blocks_outside_the_queue() -> None:
    ranking = {10: 0, 11: 1}
    assert predict_victims((10, 11, 999), ranking, 3) == (10, 11)


def test_predict_victims_rejects_negative_deficit() -> None:
    with pytest.raises(ValueError):
        predict_victims((10,), {10: 0}, -1)


def test_tier_one_blocks_are_not_victims() -> None:
    """Already-eligible blocks are released, never evicted, so they never appear."""

    snapshot, _rows = _snapshot(
        {"a": (1, 2, 3, 4)},
        deadlines={"a": 120.0},
        required_blocks=3,
        unhashed=(90,),
    )
    state = _state(snapshot)
    # The unhashed block is Tier 1: eligible before any release.
    assert state.eligible_block_ids() == frozenset({90})
    newly = state.newly_eligible_after(("a", PREFIX))
    assert 90 not in newly
    assert set(newly) == {1, 2, 3, 4}
    assert predict_victims(newly, snapshot.ranking_by_block, 3) == (1, 2, 3)


def test_shared_prefix_blocks_are_not_initially_newly_eligible() -> None:
    snapshot, _rows = _snapshot(
        {"a": (1, 2, 3, 4), "b": (1, 2, 5, 6)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=2,
    )
    state = _state(snapshot)
    newly_a = set(state.newly_eligible_after(("a", PREFIX)))
    assert newly_a == {3, 4}
    assert predict_victims(tuple(sorted(newly_a)), snapshot.ranking_by_block, 2) == (3, 4)


# --- A: frozen behaviour compatibility -----------------------------------


def test_steps_one_three_four_five_match_frozen_a1() -> None:
    """With no depth evidence at all, the strategy must be A1, release for release."""

    for scenario in all_scenarios():
        frozen = replay_decision(
            scenario.snapshot,
            A1EntryCostAwareStrategy(),
            scenario.rows,
        )
        ours = replay_with_audit(
            scenario.snapshot,
            _strategy(ChainDepthIndex(), decision_clock_domain=""),
            scenario.rows,
        )
        assert ours.outcome.released == frozen.released, scenario.name
        assert ours.outcome.satisfied == frozen.satisfied, scenario.name
        assert ours.outcome.iterations == frozen.iterations, scenario.name


def test_fallback_records_a_reason_for_every_unscorable_candidate() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4), "b": (5, 6, 7, 8)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=3,
    )
    state = _state(snapshot)
    selection = _strategy(ChainDepthIndex(), decision_clock_domain="").select(
        _remaining(snapshot, rows, state), state
    )
    assert selection.fell_back is True
    assert selection.step == STEP_SUFFICIENT
    assert selection.key == selection.a1_key
    assert FAIL_NO_OBSERVATION in selection.fallback_reason
    assert all(audit.scorable is False for audit in selection.audits)
    assert {audit.fallback_reason for audit in selection.audits} == {FAIL_NO_OBSERVATION}


def test_missing_prefill_falls_back_to_frozen_a1() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4), "b": (5, 6, 7, 8)},
        deadlines={"a": 120.0, "b": 130.0},
        prefills={"a": 0.0},
        required_blocks=3,
    )
    index = _index({("a", PREFIX): (1, 2, 3, 4), ("b", PREFIX): (5, 6, 7, 8)})
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    assert selection.fell_back is True
    assert selection.key == selection.a1_key
    audit = selection.audit_for(("a", PREFIX))
    assert audit is not None
    assert audit.fallback_reason == FAIL_PREFILL_MISSING


def test_one_unscorable_candidate_falls_back_the_whole_step_two() -> None:
    """A single missing proof must not be papered over by scoring the others."""

    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4), "b": (5, 6, 7, 8)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=3,
    )
    # Only chain "a" was ever observed, so "b" cannot be scored.
    index = _index({("a", PREFIX): (1, 2, 3, 4)})
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    assert selection.fell_back is True
    assert selection.key == selection.a1_key
    scorable = [a for a in selection.audits if a.scorable]
    unscorable = [a for a in selection.audits if not a.scorable]
    assert len(scorable) == 1 and len(unscorable) == 1
    assert unscorable[0].key == ("b", PREFIX)
    assert selection.fallback_reason.startswith("STEP2_UNSCORABLE")


def test_strategy_uses_the_latest_observation_of_a_chain() -> None:
    """A newer observation of the same chain replaces the older one.

    The strategy always asks the index for the newest observation before the
    decision, so a stale proof cannot be used by accident. ``SUPERSEDED`` is the
    proof-level guard that catches a caller who holds one anyway; it is covered
    in ``test_costaware_entry_depth.py``.
    """

    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4)},
        deadlines={"a": 120.0},
        required_blocks=3,
    )
    index = ChainDepthIndex()
    index.observe_chain(
        ("a", PREFIX),
        PROCESS,
        (1, 2, 3, 4),
        content_hashes=tuple(f"key-{b}" for b in (1, 2, 3, 4)),
        observation_index=10,
        observed_at=50.0,
        clock_domain="continuum_pressure",
    )
    index.observe_chain(
        ("a", PREFIX),
        PROCESS,
        (1, 2, 3, 4, 101, 102, 103, 104),
        content_hashes=tuple(f"key-{b}" for b in (1, 2, 3, 4, 101, 102, 103, 104)),
        observation_index=20,
        observed_at=51.0,
        clock_domain="continuum_pressure",
    )
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    assert selection.fell_back is False
    audit = selection.audits[0]
    # Only the newer observation has eight blocks, so m = 8 and S = 8.
    assert audit.chain_length == 8
    assert audit.suffix_blocks == 8


def test_step_two_uses_the_frozen_formula() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4, 5), "b": (6, 7, 8, 9)},
        deadlines={"a": 120.0, "b": 130.0},
        prefills={"a": 2.0, "b": 1.0},
        required_blocks=3,
    )
    index = _index(
        {
            ("a", PREFIX): (1, 2, 3, 4, 5, 101, 102, 103, 104, 105),
            ("b", PREFIX): (201, 202, 203, 6, 7, 8, 9),
        }
    )
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    assert selection.fell_back is False
    assert selection.step == STEP_SUFFICIENT

    audit = selection.audit_for(("a", PREFIX))
    assert audit is not None
    # m = 10, victims are depths 1..3, so S = 10.
    assert audit.chain_length == 10
    assert audit.d_min == 1
    assert audit.suffix_blocks == 10
    assert audit.victim_count == 3
    q = reuse_proxy(120.0, DECISION_TIMESTAMP, TAU)
    assert audit.reuse_proxy == pytest.approx(q)
    assert audit.score == pytest.approx(q * 2.0 * 10 / 10)

    audit_b = selection.audit_for(("b", PREFIX))
    assert audit_b is not None
    # m = 7, victims are depths 4..6, so S = 7 - 4 + 1 = 4.
    assert audit_b.chain_length == 7
    assert audit_b.d_min == 4
    assert audit_b.suffix_blocks == 4
    q_b = reuse_proxy(130.0, DECISION_TIMESTAMP, TAU)
    assert audit_b.score == pytest.approx(q_b * 1.0 * 4 / 7)

    # Exactly one audit is marked selected, and it is the returned key.
    selected = [a.key for a in selection.audits if a.selected]
    assert selected == [selection.key]


def test_tie_break_is_deadline_then_identity() -> None:
    """Equal scores must resolve deterministically, never by dict order."""

    chains = {
        ("zzz", PREFIX): (1, 2, 3, 4),
        ("aaa", PREFIX): (5, 6, 7, 8),
    }
    snapshot, rows = _snapshot(
        {"zzz": (1, 2, 3, 4), "aaa": (5, 6, 7, 8)},
        deadlines={"zzz": 120.0, "aaa": 120.0},
        required_blocks=3,
    )
    index = _index(chains)
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    scores = {a.key: a.score for a in selection.audits}
    assert scores[("zzz", PREFIX)] == pytest.approx(scores[("aaa", PREFIX)])
    # Identical geometry and deadlines, so identity decides.
    assert selection.key == ("aaa", PREFIX)

    # A sooner deadline wins before identity is consulted.
    snapshot2, rows2 = _snapshot(
        {"zzz": (1, 2, 3, 4), "aaa": (5, 6, 7, 8)},
        deadlines={"zzz": 110.0, "aaa": 120.0},
        required_blocks=3,
    )
    # Different deadlines give different q, so restore equality by using chains
    # whose suffix ratio compensates it exactly is overkill; instead assert the
    # ordering function honours the deadline field directly.
    audits = (
        CandidateCostAudit(
            key=("zzz", PREFIX),
            need=3,
            deficit=3,
            new_blocks=4,
            deadline=110.0,
            victim_block_ids=(1, 2, 3),
            victim_depths=(1, 2, 3),
            chain_length=4,
            d_min=1,
            suffix_blocks=4,
            reuse_proxy=0.5,
            prefill_reload_seconds=1.0,
            score=0.5,
        ),
        CandidateCostAudit(
            key=("aaa", PREFIX),
            need=3,
            deficit=3,
            new_blocks=4,
            deadline=120.0,
            victim_block_ids=(5, 6, 7),
            victim_depths=(1, 2, 3),
            chain_length=4,
            d_min=1,
            suffix_blocks=4,
            reuse_proxy=0.5,
            prefill_reload_seconds=1.0,
            score=0.5,
        ),
    )
    assert min(audits, key=A3SuffixCostStrategy._order).key == ("zzz", PREFIX)
    assert snapshot2 is not None and rows2  # builders stay exercised


def test_step_one_returns_without_scoring() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2), "b": (3, 4)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=1,
        unhashed=(90, 91),
    )
    state = _state(snapshot)
    # Two Tier 1 blocks already satisfy the target, so need <= 0.
    selection = _strategy(ChainDepthIndex(), decision_clock_domain="").select(
        _remaining(snapshot, rows, state), state
    )
    assert selection.step == STEP_NO_NEED
    assert selection.need == 0
    assert selection.audits == ()
    assert selection.fell_back is False


def test_per_unit_branch_is_delegated_unchanged() -> None:
    # Neither entry alone satisfies the need, so Step 3 applies.
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3), "b": (4, 5, 6)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=4,
    )
    state = _state(snapshot)
    remaining = _remaining(snapshot, rows, state)
    frozen = A1EntryCostAwareStrategy().select(remaining, state)
    assert frozen.branch == BRANCH_PER_UNIT
    ours = _strategy(ChainDepthIndex(), decision_clock_domain="").select(remaining, state)
    assert ours.key == frozen.key
    assert ours.step == STEP_PER_UNIT
    assert ours.audits == ()


def test_pair_lookahead_branch_is_delegated_unchanged() -> None:
    # Every block is co-owned, so no single release unlocks anything.
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3), "b": (1, 2, 3)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=3,
    )
    state = _state(snapshot)
    remaining = _remaining(snapshot, rows, state)
    frozen = A1EntryCostAwareStrategy().select(remaining, state)
    assert frozen.branch == BRANCH_PAIR_LOOKAHEAD
    ours = _strategy(ChainDepthIndex(), decision_clock_domain="").select(remaining, state)
    assert ours.key == frozen.key
    assert ours.step == STEP_PAIR_LOOKAHEAD
    assert ours.audits == ()


def test_step_labels_cover_every_frozen_branch() -> None:
    assert step_for_branch(BRANCH_SINGLE_STEP) == STEP_NO_NEED
    assert step_for_branch(BRANCH_PER_UNIT) == STEP_PER_UNIT
    assert step_for_branch(BRANCH_PAIR_LOOKAHEAD) == STEP_PAIR_LOOKAHEAD
    assert step_for_branch(BRANCH_DEADLINE_FALLBACK) == STEP_FALLBACK


# --- D: independent discriminative case ---------------------------------


def test_new_rule_and_a0_make_recomputably_different_choices() -> None:
    """A0 takes the earliest deadline; the proxy takes the shorter suffix.

    Entry ``a`` has the earliest deadline and a deep 1 MiB-scale suffix; entry
    ``b`` is slightly later but keeps almost all of its chain alive. Both are
    single-step sufficient, so this is a pure Step 2 comparison and the whole
    decision is reproducible from the numbers below.

    This proves independent decision logic. It is **not** evidence of a
    performance improvement.
    """

    # a: chain of 10, victims are depths 1..3, so S = 10 (kills 10 blocks of suffix).
    # b: chain of 7, victims are depths 4..6, so S = 4 (kills 4 blocks of suffix).
    chains = {
        ("aaa", PREFIX): (1, 2, 3, 4, 5, 101, 102, 103, 104, 105),
        ("bbb", PREFIX): (201, 202, 203, 6, 7, 8, 9),
    }
    snapshot, rows = _snapshot(
        {"aaa": (1, 2, 3, 4, 5), "bbb": (6, 7, 8, 9)},
        deadlines={"aaa": 120.0, "bbb": 120.0},
        prefills={"aaa": 1.0, "bbb": 1.0},
        required_blocks=4,
    )
    state = _state(snapshot)

    a0 = ExecutedP1BStrategy().pick_next(_remaining(snapshot, rows, state), state)
    assert a0 == ("aaa", PREFIX), "A0 should take the earliest deadline entry"

    index = _index(chains)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    assert selection.fell_back is False
    assert selection.key == ("bbb", PREFIX)
    assert selection.key != a0

    q = reuse_proxy(120.0, DECISION_TIMESTAMP, TAU)
    audit_a = selection.audit_for(("aaa", PREFIX))
    audit_b = selection.audit_for(("bbb", PREFIX))
    assert audit_a is not None and audit_b is not None
    # Recompute both scores from the published inputs.
    assert audit_a.score == pytest.approx(q * 1.0 * 10 / 10)
    assert audit_b.score == pytest.approx(q * 1.0 * 4 / 7)
    assert audit_b.score < audit_a.score
    # Same q on both sides, so the divergence is entirely the suffix geometry.
    assert audit_a.reuse_proxy == pytest.approx(audit_b.reuse_proxy)
    assert audit_a.suffix_blocks > audit_b.suffix_blocks


# --- audit trail ----------------------------------------------------------


def test_audit_record_carries_every_field_the_authorisation_requires() -> None:
    names = {field.name for field in dataclasses.fields(CandidateCostAudit)}
    required = {
        "need",
        "deficit",
        "new_blocks",
        "victim_block_ids",
        "chain_length",
        "d_min",
        "suffix_blocks",
        "reuse_proxy",
        "prefill_reload_seconds",
        "score",
        "selected",
        "fallback_reason",
    }
    assert required <= names


def test_audit_record_never_claims_stronger_victim_evidence() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4)},
        deadlines={"a": 120.0},
        required_blocks=3,
    )
    index = _index({("a", PREFIX): (1, 2, 3, 4)})
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    assert selection.audits
    assert all(audit.evidence.value == "predicted" for audit in selection.audits)


def test_replay_with_audit_records_every_release_iteration() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3), "b": (4, 5, 6)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=5,
    )
    record = replay_with_audit(
        snapshot,
        _strategy(ChainDepthIndex(), decision_clock_domain=""),
        rows,
    )
    assert len(record.selections) == record.outcome.iterations
    assert record.outcome.released
    assert record.outcome.satisfied is True


def test_build_strategy_requires_the_explicit_id() -> None:
    index = ChainDepthIndex()
    strategy = build_strategy(STRATEGY_ID, depth_index=index)
    assert strategy.strategy_id == STRATEGY_ID
    for wrong in ("A1_entry_cost_aware", "A2", ""):
        with pytest.raises(ValueError):
            build_strategy(wrong, depth_index=index)


def test_strategy_signature_is_a_release_strategy() -> None:
    strategy = _strategy(ChainDepthIndex())
    assert hasattr(strategy, "strategy_id")
    assert callable(strategy.pick_next)


def test_strategy_rejects_unusable_knobs() -> None:
    with pytest.raises(ValueError):
        A3SuffixCostStrategy(depth_index=ChainDepthIndex(), lambda_=1.5)
    with pytest.raises(ValueError):
        A3SuffixCostStrategy(depth_index=ChainDepthIndex(), tau_seconds=0.0)
    with pytest.raises(ValueError):
        A3SuffixCostStrategy(depth_index=ChainDepthIndex(), strategy_id="")


def test_process_mismatch_falls_back_when_the_runtime_pins_another_process() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4)},
        deadlines={"a": 120.0},
        required_blocks=3,
    )
    index = _index({("a", PREFIX): (1, 2, 3, 4)})
    state = _state(snapshot)
    selection = _strategy(index, native_hash_process_id="pid-other").select(
        _remaining(snapshot, rows, state), state
    )
    assert selection.fell_back is True
    assert "WRONG_PROCESS" in selection.audits[0].fallback_reason


def test_score_is_finite_for_every_scored_candidate() -> None:
    snapshot, rows = _snapshot(
        {"a": (1, 2, 3, 4, 5), "b": (6, 7, 8, 9)},
        deadlines={"a": 120.0, "b": 130.0},
        required_blocks=3,
    )
    index = _index(
        {
            ("a", PREFIX): (1, 2, 3, 4, 5),
            ("b", PREFIX): (6, 7, 8, 9),
        }
    )
    state = _state(snapshot)
    selection = _strategy(index).select(_remaining(snapshot, rows, state), state)
    for audit in selection.audits:
        assert audit.scorable
        assert math.isfinite(audit.score or 0.0)
        assert audit.suffix_blocks is not None and audit.suffix_blocks >= 1


def test_depth_query_is_not_part_of_the_public_strategy_api() -> None:
    """Guard against the strategy being handed a pre-built query by mistake."""

    index = ChainDepthIndex()
    index.observe_chain(
        ("a", PREFIX),
        PROCESS,
        (1, 2, 3),
        content_hashes=("k1", "k2", "k3"),
        observation_index=10,
        observed_at=50.0,
        clock_domain="continuum_pressure",
    )
    proof, query = index.query_for(("a", PREFIX), PROCESS, decision_index=1000, decision_time=60.0)
    assert isinstance(query, DepthQuery)
    assert proof.depth_of(query, 1, "k1")[0] == 1
