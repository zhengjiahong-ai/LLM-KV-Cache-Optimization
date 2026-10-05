"""Tests for the M4 decision-time candidate ranking rules."""

from __future__ import annotations

import pytest

from kvopt.costaware.rules import (
    CANDIDATE_RULES,
    DECISION_TIME_FEATURES,
    FORBIDDEN_FEATURES,
    CandidateRule,
    rule_by_id,
)
from kvopt.profiling.datasets import DecisionCandidateRow


def _candidate(
    *,
    program_id: str,
    prefix_id: str = "prefix",
    prefill_reload_seconds: float = 0.1,
    block_count: int = 16,
    initially_reclaimable_block_count: int = 16,
    retention_deadline_timestamp: float = 100.0,
    decision_native_lru_position: int | None = 0,
    next_tool_type: str | None = "search",
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id="run-1",
        decision_event_index=10,
        source_event_index=10,
        candidate_position=0,
        program_id=program_id,
        prefix_id=prefix_id,
        selected=False,
        release_order=None,
        retention_deadline_timestamp=retention_deadline_timestamp,
        waiting_followup=True,
        block_ids=tuple(range(block_count)),
        block_count=block_count,
        initially_reclaimable_block_ids=tuple(range(initially_reclaimable_block_count)),
        initially_reclaimable_block_count=initially_reclaimable_block_count,
        next_tool_type=next_tool_type,
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=prefill_reload_seconds,
        eta=1.0,
        queue_delay_t_seconds=0.5,
        decision_native_lru_position=decision_native_lru_position,
    )


def test_registry_ids_are_unique_and_complete() -> None:
    ids = [rule.rule_id for rule in CANDIDATE_RULES]
    assert len(ids) == len(set(ids))
    assert {rule.family for rule in CANDIDATE_RULES} == {"M0", "M1", "M2", "M3"}


def test_every_registered_rule_declares_only_decision_time_features() -> None:
    for rule in CANDIDATE_RULES:
        assert set(rule.features) <= set(DECISION_TIME_FEATURES)


def test_rule_rejects_forbidden_future_feature() -> None:
    with pytest.raises(ValueError, match="forbidden future-derived features"):
        CandidateRule(
            rule_id="bad",
            family="M1",
            description="reads a future label",
            features=(FORBIDDEN_FEATURES[0],),
            key=lambda candidates, candidate: (0.0,),
        )


def test_rule_rejects_undeclared_feature() -> None:
    with pytest.raises(ValueError, match="undeclared features"):
        CandidateRule(
            rule_id="bad",
            family="M1",
            description="reads an undeclared field",
            features=("not_a_real_field",),
            key=lambda candidates, candidate: (0.0,),
        )


def test_rule_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="rule_id"):
        CandidateRule(
            rule_id="  ",
            family="M1",
            description="no id",
            features=(),
            key=lambda candidates, candidate: (0.0,),
        )
    with pytest.raises(ValueError, match="description"):
        CandidateRule(
            rule_id="ok",
            family="M1",
            description="   ",
            features=(),
            key=lambda candidates, candidate: (0.0,),
        )


def test_rule_by_id_rejects_unknown_rule() -> None:
    with pytest.raises(KeyError, match="unknown rule_id"):
        rule_by_id("does-not-exist")


def test_order_releases_smallest_key_first_with_identity_tie_break() -> None:
    rule = rule_by_id("M1_prefill_reload_ascending")
    cheap = _candidate(program_id="pg-b", prefill_reload_seconds=0.1)
    dear = _candidate(program_id="pg-a", prefill_reload_seconds=0.9)
    ordered = rule.order([dear, cheap])
    assert [candidate.program_id for candidate in ordered] == ["pg-b", "pg-a"]


def test_order_breaks_ties_by_stable_identity() -> None:
    rule = rule_by_id("M1_prefill_reload_ascending")
    first = _candidate(program_id="pg-a", prefill_reload_seconds=0.5)
    second = _candidate(program_id="pg-b", prefill_reload_seconds=0.5)
    ordered = rule.order([second, first])
    assert [candidate.program_id for candidate in ordered] == ["pg-a", "pg-b"]


def test_selection_returns_exactly_the_requested_count() -> None:
    rule = rule_by_id("M1_prefill_reload_ascending")
    group = [
        _candidate(program_id="pg-a", prefill_reload_seconds=0.9),
        _candidate(program_id="pg-b", prefill_reload_seconds=0.1),
        _candidate(program_id="pg-c", prefill_reload_seconds=0.5),
    ]
    assert rule.selection(group, 0) == ()
    assert rule.selection(group, 1) == (("pg-b", "prefix"),)
    assert rule.selection(group, 3) == (
        ("pg-b", "prefix"),
        ("pg-c", "prefix"),
        ("pg-a", "prefix"),
    )
    assert len(rule.selection(group, 5)) == 3


def test_selection_rejects_negative_count() -> None:
    rule = rule_by_id("M1_prefill_reload_ascending")
    with pytest.raises(ValueError, match="non-negative"):
        rule.selection([_candidate(program_id="pg-a")], -1)


def test_order_of_empty_group_is_empty() -> None:
    assert rule_by_id("M2_non_code_first").order([]) == ()


def test_p1b_rule_uses_deadline_before_lru_position() -> None:
    rule = rule_by_id("M0_p1b_executed_ordering")
    later_deadline_earlier_queue = _candidate(
        program_id="pg-a",
        retention_deadline_timestamp=200.0,
        decision_native_lru_position=0,
    )
    earlier_deadline_later_queue = _candidate(
        program_id="pg-b",
        retention_deadline_timestamp=100.0,
        decision_native_lru_position=9,
    )
    ordered = rule.order([later_deadline_earlier_queue, earlier_deadline_later_queue])
    assert [candidate.program_id for candidate in ordered] == ["pg-b", "pg-a"]


def test_p1b_rule_sorts_unknown_lru_position_last() -> None:
    rule = rule_by_id("M0_p1b_executed_ordering")
    unknown = _candidate(program_id="pg-a", decision_native_lru_position=None)
    known = _candidate(program_id="pg-b", decision_native_lru_position=5)
    ordered = rule.order([unknown, known])
    assert [candidate.program_id for candidate in ordered] == ["pg-b", "pg-a"]


def test_non_code_rule_releases_non_code_candidates_first() -> None:
    rule = rule_by_id("M2_non_code_first")
    code = _candidate(program_id="pg-a", next_tool_type="code")
    search = _candidate(program_id="pg-b", next_tool_type="search")
    ordered = rule.order([code, search])
    assert [candidate.program_id for candidate in ordered] == ["pg-b", "pg-a"]


def test_size_cluster_rules_are_rank_identical_on_linear_cost_data() -> None:
    """Linear recompute cost makes the size cluster degenerate, as predicted."""
    by_prefill = rule_by_id("M1_prefill_reload_ascending")
    by_blocks = rule_by_id("M1_block_count_ascending")
    by_reclaimable = rule_by_id("M1_reclaimable_ascending")
    group = [
        _candidate(
            program_id="pg-a", prefill_reload_seconds=0.2, block_count=16,
            initially_reclaimable_block_count=16,
        ),
        _candidate(
            program_id="pg-b", prefill_reload_seconds=0.4, block_count=32,
            initially_reclaimable_block_count=32,
        ),
        _candidate(
            program_id="pg-c", prefill_reload_seconds=0.1, block_count=8,
            initially_reclaimable_block_count=8,
        ),
    ]
    expected = [candidate.program_id for candidate in by_prefill.order(group)]
    assert [candidate.program_id for candidate in by_blocks.order(group)] == expected
    assert [candidate.program_id for candidate in by_reclaimable.order(group)] == expected


def test_size_score_is_within_decision_normalized() -> None:
    """The additive score must be scale-free, not a raw unit sum."""
    rule = rule_by_id("M3_size_score_only")
    small_scale = [
        _candidate(program_id="pg-a", prefill_reload_seconds=0.9, block_count=16,
                   initially_reclaimable_block_count=16),
        _candidate(program_id="pg-b", prefill_reload_seconds=0.1, block_count=8,
                   initially_reclaimable_block_count=8),
    ]
    large_scale = [
        _candidate(program_id="pg-a", prefill_reload_seconds=900.0, block_count=1600,
                   initially_reclaimable_block_count=1600),
        _candidate(program_id="pg-b", prefill_reload_seconds=100.0, block_count=800,
                   initially_reclaimable_block_count=800),
    ]
    assert [candidate.program_id for candidate in rule.order(small_scale)] == [
        candidate.program_id for candidate in rule.order(large_scale)
    ]


def test_marginal_rule_divides_cost_by_reclaimable_blocks() -> None:
    """The re-tested ratio must actually use the reclaimable denominator."""
    rule = rule_by_id("M1_marginal_cost_per_reclaimable")
    # Both have equal cost, but pg-a frees fewer blocks, so its ratio is larger.
    pg_a = _candidate(
        program_id="pg-a", prefill_reload_seconds=0.4,
        initially_reclaimable_block_count=4,
    )
    pg_b = _candidate(
        program_id="pg-b", prefill_reload_seconds=0.4,
        initially_reclaimable_block_count=16,
    )
    ordered = rule.order([pg_a, pg_b])
    assert [candidate.program_id for candidate in ordered] == ["pg-b", "pg-a"]
