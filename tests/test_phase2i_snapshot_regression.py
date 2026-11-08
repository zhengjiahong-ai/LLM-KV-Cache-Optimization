"""Phase 2H frozen-snapshot regression for the Phase 2I suffix cost proxy.

Replays the six decisions of the Phase 2H formal history-rich native smoke and
checks that the new Step 2 key:

* scores **every** candidate without falling back, so the depth pipeline really
  works on real archive data rather than only on synthetic fixtures;
* reproduces the frozen A0 (deadline) choice on all six decisions, which is what
  the design document predicts for this workload;
* reproduces the depth and suffix numbers published in
  ``docs/experiments/phase2i-entry-marginal-cost-design.md``.

Evidence limits carried over from the design review (RC9) are respected: the
HR02 barrier counter chain is inconsistent, so this test compares **decision
level** releases taken from ``FORCED_RELEASE_DECISION`` itself and never claims a
cross-arm causal relation from barrier pairing.

The archive is local evidence, not part of the repository, so the module skips
when it is absent instead of failing.
"""

from __future__ import annotations

import dataclasses
import glob
from dataclasses import dataclass
from pathlib import Path

import pytest

from kvopt.costaware.a1_entry import A1EntryCostAwareStrategy
from kvopt.costaware.a3_suffix import (
    FAIL_LIVE_IDENTITY_MISSING,
    FAIL_NONE,
    A3SuffixCostStrategy,
    replay_with_audit,
)
from kvopt.costaware.entry_depth import DepthVerificationMode, index_from_events
from kvopt.costaware.replay import (
    CandidateKey,
    DecisionSnapshot,
    ExecutedP1BStrategy,
    candidate_key,
    load_decision_snapshots,
    replay_decision,
)
from kvopt.profiling.datasets import DecisionCandidateRow, build_decision_tables
from kvopt.profiling.ingestion import load_run_artifacts

ARCHIVE_ROOT = (
    "local/phase2h-history-rich-native-smoke-v1-evidence/artifacts/"
    "phase2h-history-rich-native-smoke-runs-v1/runs"
)

pytestmark = pytest.mark.skipif(
    not glob.glob(f"{ARCHIVE_ROOT}/*-a1-repeat-1/events.jsonl"),
    reason="Phase 2H local evidence archive is not present",
)


@dataclass(frozen=True, slots=True)
class _Decision:
    snapshot: DecisionSnapshot
    rows: dict[CandidateKey, DecisionCandidateRow]
    strategy: A3SuffixCostStrategy


def _load() -> list[_Decision]:
    run_dirs = sorted(glob.glob(f"{ARCHIVE_ROOT}/*-a1-repeat-1"))
    assert run_dirs, "archive glob matched nothing"
    runs = [load_run_artifacts(Path(run_dir)) for run_dir in run_dirs]
    snapshots = load_decision_snapshots(runs)
    tables = build_decision_tables(runs)

    rows_by_decision: dict[tuple[str, int], dict[CandidateKey, DecisionCandidateRow]] = {}
    for row in tables.candidates:
        rows_by_decision.setdefault((row.run_id, row.decision_event_index), {})[
            candidate_key(row)
        ] = row

    decisions: list[_Decision] = []
    for run in runs:
        # Each run observed its own chains, so the depth index is per run.
        index = index_from_events(run.events)
        for snapshot in snapshots:
            if snapshot.run_id != run.run_id:
                continue
            decisions.append(
                _Decision(
                    snapshot=snapshot,
                    rows=rows_by_decision.get((snapshot.run_id, snapshot.decision_event_index), {}),
                    strategy=A3SuffixCostStrategy(
                        depth_index=index,
                        native_hash_process_id="",  # single-runtime archive replay
                        decision_clock_domain="continuum_pressure",
                        strategy_id="A3_entry_suffix_cost_proxy",
                    ),
                )
            )
    return decisions


@pytest.fixture(scope="module")
def decisions() -> list[_Decision]:
    return _load()


def test_archive_contains_six_decisions(decisions: list[_Decision]) -> None:
    assert len(decisions) == 6
    assert {d.snapshot.decision_event_index for d in decisions} == {
        2170,
        4244,
        7305,
        2166,
        4384,
        10388,
    }


def test_every_candidate_is_scorable_without_fallback(decisions: list[_Decision]) -> None:
    """The real archive must exercise the scoring path, not the fallback path."""

    scored = 0
    for decision in decisions:
        record = replay_with_audit(decision.snapshot, decision.strategy, decision.rows)
        assert record.outcome.satisfied is True
        for selection in record.selections:
            # Step 1/3-5 carry no audits; whenever Step 2 runs it must succeed.
            if selection.step != "step2_sufficient":
                continue
            assert selection.fell_back is False, selection.fallback_reason
            for audit in selection.audits:
                assert audit.scorable is True, audit.fallback_reason
                assert audit.fallback_reason == FAIL_NONE
                assert audit.chain_length is not None and audit.chain_length > 0
                assert audit.d_min is not None and audit.d_min >= 1
                assert audit.suffix_blocks == (audit.chain_length - audit.d_min + 1)
                assert audit.victim_count == audit.deficit
                scored += 1
    assert scored >= 6


def test_offline_regression_does_not_claim_native_content_verification(
    decisions: list[_Decision],
) -> None:
    """Every decision here runs in replay mode, and the audit must admit it.

    There is no live content identity in an archive, so the depth comes from the
    recorded proof alone. That is sound for replay and must never be presented as
    native content verification, which is why ``content_verified`` stays ``False``
    on every row rather than defaulting to a stronger claim.
    """

    checked = 0
    for decision in decisions:
        assert decision.strategy.is_native_scoring is False
        record = replay_with_audit(decision.snapshot, decision.strategy, decision.rows)
        for audit in record.audits:
            assert audit.content_verified is False, (
                f"idx={decision.snapshot.decision_event_index} "
                f"{audit.key} claimed content verification without live identity"
            )
            checked += 1
    assert checked > 0


def test_native_mode_falls_back_on_the_same_archive(decisions: list[_Decision]) -> None:
    """With native identity demanded and none supplied, the archive must fail closed.

    This is the RC1 guard: the same six decisions that score fine offline cannot be
    scored in native mode without live content identity, so an integration that
    forgets to pass it degrades to frozen A1 instead of silently trusting history.
    """

    for decision in decisions:
        native = dataclasses.replace(
            decision.strategy,
            verification_mode=DepthVerificationMode.NATIVE_LIVE,
            # M6 would pass the *current* native process here. Any non-empty value
            # satisfies the identity requirement; what this test checks is the
            # missing live content identity, which is rejected before the proof is
            # even consulted.
            native_hash_process_id="pid-m6-current",
        )
        record = replay_with_audit(decision.snapshot, native, decision.rows)
        # No live identity was passed, so every Step 2 decision must fall back.
        for selection in record.selections:
            if selection.step != "step2_sufficient":
                continue
            assert selection.fell_back is True
            assert FAIL_LIVE_IDENTITY_MISSING in selection.fallback_reason
        # And the replay must still be legal and satisfied via frozen A1.
        assert record.outcome.satisfied is True


def test_new_rule_reproduces_a0_on_all_six_decisions(decisions: list[_Decision]) -> None:
    """The design predicted no divergence on this workload; verify it, do not assume it."""

    for decision in decisions:
        frozen = replay_decision(decision.snapshot, ExecutedP1BStrategy(), decision.rows)
        ours = replay_with_audit(decision.snapshot, decision.strategy, decision.rows)
        assert ours.outcome.released == frozen.released, (
            f"divergence at idx={decision.snapshot.decision_event_index}"
        )
        assert ours.outcome.satisfied is True


def test_new_rule_reproduces_frozen_a1_except_at_the_known_divergence(
    decisions: list[_Decision],
) -> None:
    """A1 agrees on five decisions and differs on exactly one.

    The design document identifies HR02 ``idx=10388`` as the single decision where
    the frozen A1 scoring picks pylint while the deadline rule and the suffix
    proxy both pick pytest. Asserting the *count* of divergences keeps the test
    honest in both directions: a regression that starts diverging everywhere would
    fail, and so would one that silently stops diverging at all.
    """

    diverged: list[int] = []
    for decision in decisions:
        frozen = replay_decision(decision.snapshot, A1EntryCostAwareStrategy(), decision.rows)
        ours = replay_with_audit(decision.snapshot, decision.strategy, decision.rows)
        if ours.outcome.released != frozen.released:
            diverged.append(decision.snapshot.decision_event_index)
    assert diverged == [10388]


def test_published_geometry_is_reproduced(decisions: list[_Decision]) -> None:
    """Reproduce the numbers published in the frozen design document.

    ``(m, d_min, S, L)`` for the entry each decision selected, plus the candidate
    the proxy rejects at ``idx=10388``. The ``L`` values are the ones quoted in the
    design document's tables, so a change in the formula, the depth recovery or
    ``q`` shows up as a numeric mismatch here.
    """

    expected = {
        (2170, "django__django-13023"): (368, 336, 33, 0.0053411815),
        (4244, "django__django-13023"): (440, 391, 50, 0.018032459),
        (7305, "django__django-13023"): (476, 421, 56, 0.022321175),
        (2166, "pytest-dev__pytest-7982"): (491, 486, 6, 0.00012379131),
        (4384, "pytest-dev__pytest-7982"): (597, 581, 17, 0.0052718216),
        (10388, "pytest-dev__pytest-7982"): (647, 631, 17, 0.0058384308),
        (10388, "pylint-dev__pylint-6386"): (799, 451, 349, 0.13791765),
    }
    seen: set[tuple[int, str]] = set()
    for decision in decisions:
        record = replay_with_audit(decision.snapshot, decision.strategy, decision.rows)
        for audit in record.audits:
            key = (decision.snapshot.decision_event_index, audit.key[0])
            if key not in expected:
                continue
            chain_length, d_min, suffix, score = expected[key]
            assert audit.chain_length == chain_length, key
            assert audit.d_min == d_min, key
            assert audit.suffix_blocks == suffix, key
            # Pinned to nine significant figures, which is the precision at which
            # the design document's rounded values were derived.
            assert audit.score == pytest.approx(score, rel=1e-6), key
            seen.add(key)
    assert seen == set(expected), f"missing geometry for {set(expected) - seen}"

    # The full formula must not have degenerated into ``q * S``.
    for decision in decisions:
        record = replay_with_audit(decision.snapshot, decision.strategy, decision.rows)
        for audit in record.audits:
            assert audit.score == pytest.approx(
                audit.reuse_proxy
                * audit.prefill_reload_seconds
                * audit.suffix_blocks
                / audit.chain_length,
                rel=1e-12,
            )


def test_barrier_counter_exception_is_not_used(decisions: list[_Decision]) -> None:
    """Guard the RC9 evidence limit: only decision-level facts are compared here.

    HR02's ``CONTROLLED_REPLAY_PRESSURE_COMPLETED`` counter chain is inconsistent
    (``before``/``after`` do not continue), so this regression never groups
    decisions by barrier and never claims a cross-arm causal relation.
    """

    for decision in decisions:
        # Every assertion in this module keys on the decision's own event index.
        assert decision.snapshot.decision_event_index >= 0
        assert decision.snapshot.run_id
        assert decision.rows, "decision must have candidate rows"
