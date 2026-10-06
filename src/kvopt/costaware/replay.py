"""Faithful dynamic replay of the Phase 1B forced-release pressure loop.

Why this module exists
----------------------

The first evaluator version compared a baseline that released ``N`` entries
against alternatives that also released exactly ``N`` entries. That is **not**
the constraint the runtime actually faces. The frozen Phase 1B loop is:

```text
while eligible_blocks < required_blocks:
    rank the still-protected entries
    release the lowest-ranked one
    recompute how many blocks the release makes eligible
```

Two consequences the fixed-count comparison cannot express:

1. different entries free different numbers of blocks, so a rule may reach the
   same target with a **different number of releases**;
2. under shared ownership the marginal newly-eligible set changes as earlier
   releases unblock co-owned blocks, so ``initially_reclaimable_block_count``
   **cannot** be summed independently.

The replay here reproduces the real constraint: the same ``required_blocks``,
re-ranked each iteration, with the eligible set recomputed from ownership after
every release.

Block eligibility semantics are copied from the frozen implementation in
``kvopt.continuum.pressure``:

```text
unhashed free block              -> always eligible
hashed free block                -> eligible iff NO protected owner remains
```

An owner stops being protected when its entry has been released. Entries that
already lost protection before this decision (the observed
``ordinary_expired_entries``) are excluded from the owner set entirely, matching
``released_keys`` being pre-seeded with them in the frozen loop.

Fidelity is verified, not assumed: :func:`validate_replay_fidelity` checks that
the executed P1B ordering reproduces both the observed release set and the
observed per-entry ``initially_reclaimable_block_ids``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.ingestion import ArtifactValidationError, RawRunArtifacts

from .rules import CANDIDATE_RULES, CandidateRule

CandidateKey = tuple[str, str]


def candidate_key(row: DecisionCandidateRow) -> CandidateKey:
    """Stable logical identity of one candidate entry."""
    return (row.program_id, row.prefix_id)


def _require_mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{field_name} must be an object")
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{field_name} must be a list")
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{field_name} must be non-empty text")
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactValidationError(f"{field_name} must be int")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    number = _require_int(value, field_name)
    if number < 0:
        raise ArtifactValidationError(f"{field_name} must be non-negative")
    return number


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactValidationError(f"{field_name} must be bool")
    return value


def _block_id_list(value: object, field_name: str) -> tuple[int, ...]:
    raw = _require_list(value, field_name)
    block_ids = tuple(_require_non_negative_int(item, f"{field_name} item") for item in raw)
    if len(block_ids) != len(set(block_ids)):
        raise ArtifactValidationError(f"{field_name} must not contain duplicates")
    return block_ids


@dataclass(frozen=True, slots=True)
class QueueBlock:
    """One free-queue block as observed at the decision boundary."""

    block_id: int
    has_block_hash: bool
    native_lru_rank: int


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    """Everything the pressure loop needs to replay one forced-release decision."""

    run_id: str
    decision_event_index: int
    timestamp: float
    required_blocks: int
    queue: tuple[QueueBlock, ...]
    candidate_keys: tuple[CandidateKey, ...]
    owners_by_block: Mapping[int, frozenset[CandidateKey]]
    observed_selected: tuple[CandidateKey, ...]
    observed_initial_reclaimable: Mapping[CandidateKey, tuple[int, ...]]
    ranking_by_block: Mapping[int, int]

    @property
    def target(self) -> int:
        """The frozen loop's target: ``min(required_blocks, queue length)``."""
        return min(self.required_blocks, len(self.queue))

    @property
    def unhashed_block_count(self) -> int:
        return sum(1 for block in self.queue if not block.has_block_hash)


class ReplayState:
    """Mutable state of one in-progress decision replay."""

    def __init__(self, snapshot: DecisionSnapshot) -> None:
        self._snapshot = snapshot
        self._order: list[CandidateKey] = []
        self._hashed_owners: dict[int, frozenset[CandidateKey]] = {
            block_id: owners
            for block_id, owners in snapshot.owners_by_block.items()
            if owners
        }
        self._cached_eligible: frozenset[int] | None = None

    @property
    def snapshot(self) -> DecisionSnapshot:
        return self._snapshot

    @property
    def released(self) -> frozenset[CandidateKey]:
        return frozenset(self._order)

    @property
    def release_order(self) -> tuple[CandidateKey, ...]:
        """Released entries in the order they were actually released.

        Order matters: it is what the artifacts persist, and comparing only sets
        would hide a strategy that releases the right entries in the wrong
        sequence.
        """
        return tuple(self._order)

    def eligible_block_ids(self) -> frozenset[int]:
        """Recompute eligibility from current ownership, as the frozen loop does."""
        if self._cached_eligible is not None:
            return self._cached_eligible
        still_protected = set(self._snapshot.candidate_keys) - self.released
        eligible: set[int] = set()
        for block in self._snapshot.queue:
            if not block.has_block_hash:
                eligible.add(block.block_id)
                continue
            owners = self._hashed_owners.get(block.block_id, frozenset())
            if not (owners & still_protected):
                eligible.add(block.block_id)
        self._cached_eligible = frozenset(eligible)
        return self._cached_eligible

    def newly_eligible_after(self, key: CandidateKey) -> tuple[int, ...]:
        """Blocks that would become eligible if ``key`` were released now."""
        before = self.eligible_block_ids()
        candidates_after = set(self._snapshot.candidate_keys) - self.released - {key}
        eligible_after: set[int] = set()
        for block in self._snapshot.queue:
            if not block.has_block_hash:
                eligible_after.add(block.block_id)
                continue
            owners = self._hashed_owners.get(block.block_id, frozenset())
            if not (owners & candidates_after):
                eligible_after.add(block.block_id)
        return tuple(
            block.block_id
            for block in self._snapshot.queue
            if block.block_id in eligible_after and block.block_id not in before
        )

    def release(self, key: CandidateKey) -> None:
        if key in self.released:
            raise ValueError("candidate already released")
        self._order.append(key)
        self._cached_eligible = None


class ReleaseStrategy(Protocol):
    """Selects the next entry to release, re-evaluated every iteration."""

    strategy_id: str

    def pick_next(
        self, remaining: Sequence[DecisionCandidateRow], state: ReplayState
    ) -> CandidateKey: ...


@dataclass(frozen=True, slots=True)
class RuleStrategy:
    """Adapts an offline :class:`~kvopt.costaware.rules.CandidateRule`."""

    rule: CandidateRule

    @property
    def strategy_id(self) -> str:
        return self.rule.rule_id

    def pick_next(
        self, remaining: Sequence[DecisionCandidateRow], state: ReplayState
    ) -> CandidateKey:
        del state
        return self.rule.selection(remaining, 1)[0]


@dataclass(frozen=True, slots=True)
class ExecutedP1BStrategy:
    """Replicates the frozen ``_release_sort_key`` including its dynamic tie-break.

    The frozen key is ``(deadline, min native rank over newly eligible, identity)``
    where the middle term is recomputed against the *current* released set. That
    is why this cannot be expressed as a plain candidate key.
    """

    strategy_id: str = "M0_executed_p1b_replay"

    def pick_next(
        self, remaining: Sequence[DecisionCandidateRow], state: ReplayState
    ) -> CandidateKey:
        ranking = state.snapshot.ranking_by_block

        def sort_key(row: DecisionCandidateRow) -> tuple[float, float, CandidateKey]:
            marginal = state.newly_eligible_after(candidate_key(row))
            native = min((ranking[bid] for bid in marginal), default=math.inf)
            return (row.retention_deadline_timestamp, native, candidate_key(row))

        return candidate_key(min(remaining, key=sort_key))


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """Result of replaying one decision under one strategy."""

    run_id: str
    decision_event_index: int
    strategy_id: str
    target: int
    eligible_blocks_initial: int
    eligible_blocks_final: int
    released: tuple[CandidateKey, ...]
    satisfied: bool
    exhausted: bool
    iterations: int


def replay_decision(
    snapshot: DecisionSnapshot,
    strategy: ReleaseStrategy,
    rows_by_key: Mapping[CandidateKey, DecisionCandidateRow],
) -> ReplayOutcome:
    """Replay the pressure loop until the shared ``required_blocks`` target is met.

    Re-ranking happens every iteration on the still-protected entries, matching
    the frozen loop. If every candidate is released and the target is still
    unmet, the outcome is reported as ``exhausted`` and ``satisfied = False``
    rather than being silently accepted.

    Note that exhaustion is **unreachable** for a snapshot produced by
    :func:`load_decision_snapshots`: the target is capped at the queue length,
    and releasing every candidate leaves no protected owner for any queued
    block, so every block becomes eligible. The guard is defensive, so that a
    malformed snapshot fails loudly instead of yielding a truncated release set.
    """
    state = ReplayState(snapshot)
    initial = len(state.eligible_block_ids())
    iterations = 0
    while len(state.eligible_block_ids()) < snapshot.target:
        remaining = [
            rows_by_key[key]
            for key in snapshot.candidate_keys
            if key not in state.released
        ]
        if not remaining:
            break
        chosen = strategy.pick_next(remaining, state)
        allowed = {candidate_key(row) for row in remaining}
        if chosen not in allowed:
            raise ValueError(
                f"strategy {strategy.strategy_id!r} selected {chosen!r}, which is "
                "not one of the still-protected decision candidates"
            )
        state.release(chosen)
        iterations += 1
    final = len(state.eligible_block_ids())
    return ReplayOutcome(
        run_id=snapshot.run_id,
        decision_event_index=snapshot.decision_event_index,
        strategy_id=strategy.strategy_id,
        target=snapshot.target,
        eligible_blocks_initial=initial,
        eligible_blocks_final=final,
        released=state.release_order,
        satisfied=final >= snapshot.target,
        exhausted=final < snapshot.target,
        iterations=iterations,
    )


@dataclass(frozen=True, slots=True)
class ReplayFidelity:
    """How well a strategy reproduces the observed decision."""

    strategy_id: str
    decisions_compared: int
    release_set_matches: int
    release_sequence_matches: int
    initial_reclaimable_matches: int
    initial_reclaimable_fields_compared: int

    @property
    def release_set_match_rate(self) -> float | None:
        if not self.decisions_compared:
            return None
        return self.release_set_matches / self.decisions_compared

    @property
    def release_sequence_match_rate(self) -> float | None:
        if not self.decisions_compared:
            return None
        return self.release_sequence_matches / self.decisions_compared

    @property
    def initial_reclaimable_match_rate(self) -> float | None:
        if not self.initial_reclaimable_fields_compared:
            return None
        return (
            self.initial_reclaimable_matches / self.initial_reclaimable_fields_compared
        )


def validate_replay_fidelity(
    snapshots: Sequence[DecisionSnapshot],
    rows_by_key: Mapping[tuple[str, int], Mapping[CandidateKey, DecisionCandidateRow]],
    strategy: ReleaseStrategy,
) -> ReplayFidelity:
    """Prove the replay engine reproduces the observed decision.

    Compares three things against the raw artifacts:

    - the released entry **set**;
    - the released entry **order**;
    - each entry's ``initially_reclaimable_block_ids`` as computed by the frozen
      implementation, which validates the ownership and eligibility model
      independently of any strategy.
    """
    compared = 0
    set_matches = 0
    sequence_matches = 0
    reclaimable_matches = 0
    reclaimable_compared = 0

    for snapshot in snapshots:
        rows = rows_by_key.get(
            (snapshot.run_id, snapshot.decision_event_index), {}
        )
        if not rows:
            continue
        compared += 1
        outcome = replay_decision(snapshot, strategy, rows)
        if set(outcome.released) == set(snapshot.observed_selected):
            set_matches += 1
        if outcome.released == snapshot.observed_selected:
            sequence_matches += 1

        state = ReplayState(snapshot)
        for key, observed in snapshot.observed_initial_reclaimable.items():
            reclaimable_compared += 1
            computed = state.newly_eligible_after(key)
            if set(computed) == set(observed):
                reclaimable_matches += 1

    return ReplayFidelity(
        strategy_id=strategy.strategy_id,
        decisions_compared=compared,
        release_set_matches=set_matches,
        release_sequence_matches=sequence_matches,
        initial_reclaimable_matches=reclaimable_matches,
        initial_reclaimable_fields_compared=reclaimable_compared,
    )


def load_decision_snapshots(
    runs: Sequence[RawRunArtifacts],
) -> tuple[DecisionSnapshot, ...]:
    """Reconstruct every forced-release decision from the raw decision payloads.

    Only the persisted ``FORCED_RELEASE_DECISION`` fact set is read. No derived
    label, oracle, or future outcome is consulted.
    """
    snapshots: list[DecisionSnapshot] = []
    for artifacts in runs:
        for event in artifacts.events:
            if event.get("event_type") != "FORCED_RELEASE_DECISION":
                continue
            snapshots.append(_snapshot_from_event(artifacts.run_id, event))
    return tuple(snapshots)


def _snapshot_from_event(run_id: str, event: Mapping[str, object]) -> DecisionSnapshot:
    event_index = _require_non_negative_int(event.get("event_index"), "event_index")
    timestamp = event.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ArtifactValidationError("timestamp must be a number")
    payload = _require_mapping(event.get("payload"), "payload")

    queue: list[QueueBlock] = []
    ranking: dict[int, int] = {}
    for index, raw in enumerate(
        _require_list(payload.get("original_free_queue"), "original_free_queue")
    ):
        entry = _require_mapping(raw, "original_free_queue item")
        block_id = _require_non_negative_int(entry.get("block_id"), "block_id")
        rank = _require_non_negative_int(
            entry.get("native_lru_rank"), "native_lru_rank"
        )
        if rank != index:
            raise ArtifactValidationError(
                "native_lru_rank must equal position in the free queue"
            )
        queue.append(
            QueueBlock(
                block_id=block_id,
                has_block_hash=_require_bool(
                    entry.get("has_block_hash"), "has_block_hash"
                ),
                native_lru_rank=rank,
            )
        )
        ranking[block_id] = rank

    queue_ids = {block.block_id for block in queue}

    candidate_keys: list[CandidateKey] = []
    owners: dict[int, set[CandidateKey]] = {}
    observed_initial: dict[CandidateKey, tuple[int, ...]] = {}
    for raw in _require_list(payload.get("candidates"), "candidates"):
        entry = _require_mapping(raw, "candidate")
        key: CandidateKey = (
            _require_text(entry.get("program_id"), "candidate program_id"),
            _require_text(entry.get("prefix_id"), "candidate prefix_id"),
        )
        if key in candidate_keys:
            raise ArtifactValidationError("candidates must not repeat an entry key")
        candidate_keys.append(key)
        for block_id in _block_id_list(entry.get("block_ids"), "candidate block_ids"):
            if block_id in queue_ids:
                owners.setdefault(block_id, set()).add(key)
        observed_initial[key] = _block_id_list(
            entry.get("initially_reclaimable_block_ids"),
            "candidate initially_reclaimable_block_ids",
        )

    observed_selected: list[CandidateKey] = []
    for raw in _require_list(payload.get("selected_releases"), "selected_releases"):
        entry = _require_mapping(raw, "selected release")
        key = (
            _require_text(entry.get("program_id"), "selected program_id"),
            _require_text(entry.get("prefix_id"), "selected prefix_id"),
        )
        if key not in candidate_keys:
            raise ArtifactValidationError(
                "a selected release must be one of the decision candidates"
            )
        observed_selected.append(key)

    return DecisionSnapshot(
        run_id=run_id,
        decision_event_index=event_index,
        timestamp=float(timestamp),
        required_blocks=_require_non_negative_int(
            payload.get("required_blocks"), "required_blocks"
        ),
        queue=tuple(queue),
        candidate_keys=tuple(candidate_keys),
        owners_by_block={
            block_id: frozenset(keys) for block_id, keys in owners.items()
        },
        observed_selected=tuple(observed_selected),
        observed_initial_reclaimable=observed_initial,
        ranking_by_block=ranking,
    )


def all_rule_strategies() -> tuple[RuleStrategy, ...]:
    """Every registered candidate rule as a replay strategy."""
    return tuple(RuleStrategy(rule) for rule in CANDIDATE_RULES)
