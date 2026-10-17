"""Controlled pressure scenarios for the A1 offline comparison.

Why these exist
---------------
The H1 corpus cannot separate A0 from A1 in the way this round needs: it has no
shared prefix structure at all (0/81 decisions with two entries sharing a block),
so the co-ownership cases that motivate the entry layer never occur. Rather than
pretend H1 is evidence of effectiveness, this module builds a small number of
hand-checkable decisions and states exactly what each one is for.

These are **synthetic controlled scenarios**, not measured workloads. They are
used to prove the mechanism works and is deterministic; they are not evidence of
runtime benefit. That distinction is enforced by the comparison runner, which
reports them under a separate heading from any real corpus.

Ground truth
------------
Each scenario may carry ``returns_after_decision``, recording which entries would
have come back had they been kept. That is a post-decision fact, so it is
**evaluation-only** and never passed to a strategy; the runner asserts this by
never putting it in a ``DecisionCandidateRow``. Scenario C needs it in order to
show a case where A1's choice is worse than A0's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kvopt.profiling.datasets import DecisionCandidateRow

from .replay import CandidateKey, DecisionSnapshot, QueueBlock

#: Fixed decision timestamp shared by every scenario, so ``q`` is reproducible.
DECISION_TIMESTAMP = 100.0


@dataclass(frozen=True, slots=True)
class ControlledScenario:
    """One hand-built decision plus the notes a reader needs to check it."""

    name: str
    purpose: str
    expectation: str
    snapshot: DecisionSnapshot
    rows: dict[CandidateKey, DecisionCandidateRow]
    returns_after_decision: dict[CandidateKey, bool] = field(default_factory=dict)
    notes: str = ""


def _build(
    *,
    name: str,
    purpose: str,
    expectation: str,
    entries: dict[str, tuple[int, ...]],
    deadlines: dict[str, float],
    required_blocks: int,
    queue_order: tuple[int, ...],
    notes: str = "",
    returns_after_decision: dict[str, bool] | None = None,
) -> ControlledScenario:
    """Assemble one decision from entry ownership, deadlines and queue order."""
    ranking = {block_id: rank for rank, block_id in enumerate(queue_order)}

    owners: dict[int, set[CandidateKey]] = {}
    for program_id, blocks in entries.items():
        for block_id in blocks:
            owners.setdefault(block_id, set()).add((program_id, "p"))

    rows: dict[CandidateKey, DecisionCandidateRow] = {}
    for position, (program_id, blocks) in enumerate(entries.items()):
        key: CandidateKey = (program_id, "p")
        reclaimable = tuple(
            block_id
            for block_id in blocks
            if owners.get(block_id) == {key}
        )
        rows[key] = DecisionCandidateRow(
            run_id=f"controlled-{name}",
            decision_event_index=0,
            source_event_index=0,
            candidate_position=position,
            program_id=program_id,
            prefix_id="p",
            selected=False,
            release_order=None,
            retention_deadline_timestamp=deadlines[program_id],
            waiting_followup=True,
            block_ids=blocks,
            block_count=len(blocks),
            initially_reclaimable_block_ids=reclaimable,
            initially_reclaimable_block_count=len(reclaimable),
            next_tool_type="search",
            elapsed_since_ttl_decision_seconds=1.0,
            prefill_reload_seconds=1.0,
            eta=1.0,
            queue_delay_t_seconds=0.5,
            decision_native_lru_position=position,
        )

    snapshot = DecisionSnapshot(
        run_id=f"controlled-{name}",
        decision_event_index=0,
        timestamp=DECISION_TIMESTAMP,
        required_blocks=required_blocks,
        queue=tuple(
            QueueBlock(
                block_id=block_id,
                has_block_hash=True,
                native_lru_rank=ranking[block_id],
            )
            for block_id in queue_order
        ),
        candidate_keys=tuple((program_id, "p") for program_id in entries),
        owners_by_block={
            block_id: frozenset(keys) for block_id, keys in owners.items()
        },
        observed_selected=(),
        observed_initial_reclaimable={
            key: row.initially_reclaimable_block_ids for key, row in rows.items()
        },
        ranking_by_block=ranking,
    )
    return ControlledScenario(
        name=name,
        purpose=purpose,
        expectation=expectation,
        snapshot=snapshot,
        rows=rows,
        returns_after_decision={
            (program_id, "p"): flag
            for program_id, flag in (returns_after_decision or {}).items()
        },
        notes=notes,
    )


def scenario_a_divergent() -> ControlledScenario:
    """A0 and A1 disagree, both legal.

    Shared root p1..p8 owned by {A, B}; A privately owns p9..p16 (8 blocks),
    B privately owns p17..p18 (2 blocks). ``required_blocks = 2``.

    A0 releases the earlier deadline, which is A, exposing A's eight private
    blocks to reach a target of two. A1 releases B: B's private tail is exactly
    the two blocks needed, so nothing beyond the requirement is exposed.

    Deadlines are chosen so the proxies are the ones quoted in the design:
    ``q_A = 0.5`` at ``deadline_A = t``, and ``q_B = 0.9`` at
    ``deadline_B = t + tau * ln 9``.
    """
    return _build(
        name="a_divergent",
        purpose="A0 and A1 choose different, both-legal entries",
        expectation="A0 releases A; A1 releases B",
        entries={
            "A": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16),
            "B": (1, 2, 3, 4, 5, 6, 7, 8, 17, 18),
        },
        deadlines={"A": 100.0, "B": 100.0 + 30.0 * 2.1972245773362196},
        required_blocks=2,
        queue_order=tuple(range(1, 19)),
        notes=(
            "N_A = 8, N_B = 2, need = 2. Both clear the target alone, so the "
            "decision is settled by expected cost: "
            "R_A = 0.5*(2 + 0.5*6) = 2.5, R_B = 0.9*(2 + 0) = 1.8."
        ),
    )


def scenario_b_identical() -> ControlledScenario:
    """A0 and A1 agree: the degenerate case.

    Two disjoint entries of equal size, so ``N_A = N_B``. The bracket of the cost
    score is then a common constant, the score is proportional to ``q``, and
    ``q`` is monotone in the deadline, so A1 reproduces the deadline order.
    """
    return _build(
        name="b_identical",
        purpose="A0 and A1 choose the same entry (no cost signal to exploit)",
        expectation="both release A",
        entries={"A": (1, 2, 3, 4), "B": (5, 6, 7, 8)},
        deadlines={"A": 100.0, "B": 200.0},
        required_blocks=2,
        queue_order=(1, 2, 3, 4, 5, 6, 7, 8),
        notes=(
            "N_A = N_B = 4, need = 2, so Rhat is proportional to q. A has the "
            "earlier deadline hence the smaller q, so A1 also picks A."
        ),
    )


def scenario_c_a1_worse() -> ControlledScenario:
    """A1 is worse than A0 because the reuse proxy is wrong.

    X has a long private tail and an early deadline; Y has a short private tail
    and a late deadline. A1 minimises the estimated cost, so it sacrifices Y -- the
    entry whose estimate is cheap because its exposure is small. If Y is in fact
    the program that returns immediately, A1 has just made Y recompute three
    blocks, while A0's choice (X) never returns and costs nothing.

    The point is the failure mode, not a defect: the model cannot see the future,
    and this scenario states exactly which assumption breaks.
    """
    return _build(
        name="c_a1_worse",
        purpose="A1 can be worse than A0 when q mis-ranks the two programs",
        expectation="A0 releases X (0 blocks recomputed); A1 releases Y (3 blocks)",
        entries={"X": tuple(range(1, 11)), "Y": (11, 12, 13)},
        deadlines={"X": 100.0, "Y": 300.0},
        required_blocks=3,
        queue_order=tuple(range(1, 14)),
        returns_after_decision={"X": False, "Y": True},
        notes=(
            "N_X = 10, N_Y = 3, need = 3. R_X = 0.5*(3 + 0.5*7) = 3.25, "
            "R_Y = 0.9987*(3 + 0) = 2.996, so A1 picks Y. Ground truth says only "
            "Y returns, so A1 loses and A0 wins. This is the 'q is a heuristic' "
            "failure, recorded rather than hidden."
        ),
    )


def all_scenarios() -> tuple[ControlledScenario, ...]:
    """Every controlled scenario, in reporting order."""
    return (
        scenario_a_divergent(),
        scenario_b_identical(),
        scenario_c_a1_worse(),
    )
