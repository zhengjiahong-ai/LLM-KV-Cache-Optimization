"""Tests for the H1-R1 reverse-deadline preregistration.

The point of these tests is that a preregistered hypothesis is *data*: the rule
exists, its frozen record is complete, and the record cannot silently drift away
from the rule it describes.
"""

from __future__ import annotations

import pytest

from kvopt.costaware.acceptance import (
    PROXY_LOSS_VIEW,
    RUNTIME_LOSS_VIEW,
    TIER_PROXY,
    TIER_RUNTIME,
)
from kvopt.costaware.preregistrations import (
    H1_FREEZE_DATE,
    H1_R1_PREREGISTRATION,
    PREREGISTRATIONS,
    preregistration_for,
)
from kvopt.costaware.rules import (
    CANDIDATE_RULES,
    DECISION_TIME_FEATURES,
    H1_R1_REVERSE_DEADLINE_ID,
    PREREGISTERED_H1_RULES,
    rule_by_id,
)
from kvopt.profiling.datasets import DecisionCandidateRow


def _candidate(
    program_id: str,
    *,
    deadline: float,
    prefill_reload_seconds: float = 0.1,
) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id="run-1",
        decision_event_index=10,
        source_event_index=10,
        candidate_position=0,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        selected=program_id == "a",
        release_order=1 if program_id == "a" else None,
        retention_deadline_timestamp=deadline,
        waiting_followup=True,
        block_ids=(0,),
        block_count=1,
        initially_reclaimable_block_ids=(),
        initially_reclaimable_block_count=0,
        next_tool_type="code",
        elapsed_since_ttl_decision_seconds=1.0,
        prefill_reload_seconds=prefill_reload_seconds,
        eta=1.0,
        queue_delay_t_seconds=1.0,
    )


# --- the rule is separate from the closed study ---------------------------


def test_the_hypothesis_is_not_part_of_the_frozen_rule_set() -> None:
    """The M0-M3 study is closed; its published numbers must not move."""
    assert len(CANDIDATE_RULES) == 9
    assert H1_R1_REVERSE_DEADLINE_ID not in {
        rule.rule_id for rule in CANDIDATE_RULES
    }


def test_the_hypothesis_is_registered_and_lookup_able() -> None:
    assert H1_R1_REVERSE_DEADLINE_ID in {
        rule.rule_id for rule in PREREGISTERED_H1_RULES
    }
    assert rule_by_id(H1_R1_REVERSE_DEADLINE_ID).family == "H1"


def test_rule_reads_only_the_decision_time_allowlist() -> None:
    rule = rule_by_id(H1_R1_REVERSE_DEADLINE_ID)
    assert rule.features == ("retention_deadline_timestamp",)
    assert set(rule.features) <= set(DECISION_TIME_FEATURES)


def test_unknown_rule_lookup_still_refuses() -> None:
    with pytest.raises(KeyError, match="unknown rule_id"):
        rule_by_id("H1_R1_does_not_exist")


# --- the ordering is the exact negation of the baseline primary key -------


def test_latest_deadline_is_released_first() -> None:
    rule = rule_by_id(H1_R1_REVERSE_DEADLINE_ID)
    earliest = _candidate("a", deadline=10.0)
    latest = _candidate("b", deadline=90.0)
    middle = _candidate("c", deadline=50.0)
    ordered = rule.order((earliest, middle, latest))
    assert [row.program_id for row in ordered] == ["b", "c", "a"]


def test_ordering_is_the_reverse_of_the_baseline_primary_key() -> None:
    """Byte-for-byte the negation of the frozen P1B primary term."""
    rule = rule_by_id(H1_R1_REVERSE_DEADLINE_ID)
    candidates = (
        _candidate("a", deadline=10.0),
        _candidate("b", deadline=90.0),
        _candidate("c", deadline=50.0),
        _candidate("d", deadline=10.0),
    )
    forward = sorted(
        candidates,
        key=lambda row: (
            row.retention_deadline_timestamp,
            (row.program_id, row.prefix_id),
        ),
    )
    reversed_deadline = sorted(
        candidates,
        key=lambda row: (
            -row.retention_deadline_timestamp,
            (row.program_id, row.prefix_id),
        ),
    )
    assert list(rule.order(candidates)) == reversed_deadline
    assert [row.program_id for row in reversed_deadline] == ["b", "c", "a", "d"]
    # And it is genuinely the reverse ordering of the baseline primary key.
    assert [row.program_id for row in forward] == ["a", "d", "c", "b"]


def test_deadline_ties_fall_back_to_stable_identity() -> None:
    rule = rule_by_id(H1_R1_REVERSE_DEADLINE_ID)
    tied = (
        _candidate("b", deadline=50.0),
        _candidate("a", deadline=50.0),
    )
    assert [row.program_id for row in rule.order(tied)] == ["a", "b"]


# --- the frozen record ----------------------------------------------------


def test_a_frozen_record_exists_for_the_registered_rule() -> None:
    record = preregistration_for(H1_R1_REVERSE_DEADLINE_ID)
    assert record is H1_R1_PREREGISTRATION
    assert record.rule_id in {rule.rule_id for rule in PREREGISTERED_H1_RULES}


def test_every_hypothesis_rule_has_a_frozen_record() -> None:
    assert {rule.rule_id for rule in PREREGISTERED_H1_RULES} == set(
        PREREGISTRATIONS
    )


def test_unregistered_hypothesis_lookup_refuses() -> None:
    with pytest.raises(KeyError, match="no frozen preregistration"):
        preregistration_for("M0_p1b_executed_ordering")


def test_record_freezes_every_required_field() -> None:
    """M1 requires formula, direction, tie-break, fallback and boundary."""
    payload = H1_R1_PREREGISTRATION.as_payload()
    for field in (
        "formula",
        "direction",
        "tie_break",
        "fallback",
        "boundary",
        "frozen_at",
        "frozen_commit",
    ):
        assert isinstance(payload[field], str)
        assert payload[field].strip()
    # And both metric tiers, which are frozen together rather than one per run.
    assert set(payload["metrics"]) == {TIER_PROXY, TIER_RUNTIME}
    for metric in payload["metrics"].values():
        assert isinstance(metric, str) and metric.strip()


def test_record_declares_both_frozen_metric_tiers() -> None:
    """Both tiers are frozen now, so a runtime holdout cannot be judged as A."""
    assert H1_R1_PREREGISTRATION.proxy_primary_metric == PROXY_LOSS_VIEW
    assert H1_R1_PREREGISTRATION.runtime_primary_metric == RUNTIME_LOSS_VIEW
    payload = H1_R1_PREREGISTRATION.as_payload()
    assert payload["metrics"][TIER_PROXY] == PROXY_LOSS_VIEW
    assert payload["metrics"][TIER_RUNTIME] == RUNTIME_LOSS_VIEW


def test_metric_for_tier_returns_the_frozen_metric_only() -> None:
    assert H1_R1_PREREGISTRATION.metric_for_tier(TIER_PROXY) == PROXY_LOSS_VIEW
    assert (
        H1_R1_PREREGISTRATION.metric_for_tier(TIER_RUNTIME)
        == RUNTIME_LOSS_VIEW
    )
    with pytest.raises(ValueError, match="unknown metric tier"):
        H1_R1_PREREGISTRATION.metric_for_tier("whatever_is_best")


def test_record_is_anchored_to_a_freeze_date_and_commit() -> None:
    assert H1_R1_PREREGISTRATION.frozen_at == H1_FREEZE_DATE
    assert H1_R1_PREREGISTRATION.frozen_commit


def test_record_states_the_derived_signal_caveat() -> None:
    """The deadline is a TTL-estimator output, not an independent observation."""
    boundary = H1_R1_PREREGISTRATION.boundary.lower()
    assert "derived" in boundary
    assert "ttl" in boundary
    # And that the discovery campaign can never be its holdout.
    assert "holdout" in boundary


def test_record_wording_does_not_overclaim_a_full_inversion() -> None:
    """Only the primary deadline term is inverted, never the whole frozen key."""
    combined = (
        H1_R1_PREREGISTRATION.formula + " " + H1_R1_PREREGISTRATION.boundary
    ).lower()
    assert "primary" in combined
    # The unqualified phrasing M1 rejected must not reappear.
    assert "invert the baseline's own keep decision" not in combined
    assert "exact negation of the frozen phase 1b primary key" not in combined


def test_record_states_the_fallback_is_the_frozen_baseline() -> None:
    fallback = H1_R1_PREREGISTRATION.fallback.lower()
    assert "frozen baseline" in fallback
    assert "never fabricate" in fallback


def test_record_declares_the_tie_break_as_untested() -> None:
    """Deadlines are tied in 0 of 60 discovery decisions, so say so."""
    tie_break = H1_R1_PREREGISTRATION.tie_break.lower()
    assert "0 of 60" in tie_break
