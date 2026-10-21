"""Entry-level gap on frozen evidence, with the frozen A1 replayed strictly.

Corrections required by M1's PR #70 review (RC1-RC3):

RC1  The frozen A1 is replayed through the repository's own strategy and replay
     machinery (``A1EntryCostAwareStrategy`` + ``replay_decision``), so the
     single-step / per-unit / pair-lookahead / deadline-fallback ladder is
     reproduced rather than approximated by "lowest score first".
     The loader is validated by first reproducing the observed A0 decision with
     ``ExecutedP1BStrategy``; anything that fails that check is not analysed.

RC2  Five distinct quantities are reported separately and are never substituted
     for one another:
       (1) newly eligible blocks          -- what A1's N_i counts
       (2) actual native victim blocks    -- what the frozen rule evicts
       (3) verified content chain depth   -- from ChainProof, never from slot order
       (4) proxy-weighted model loss      -- only over (3)
       (5) native actual recomputed tokens -- NOT measured here, see config note
     Candidate ``block_ids`` order is never used as content depth; depth comes
     from ``a2_evidence.prove_chain``.

RC3  Every decision is classified as replay-valid / content-verified or
     undecidable, and the comparison is restricted to the valid subset. No claim
     is made about native workload headroom.

Read-only: no src/ change, no native run, no algorithm change.
"""

from __future__ import annotations

import itertools
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, "src")

from kvopt.costaware.a1_entry import A1EntryCostAwareStrategy
from kvopt.costaware.a2_evidence import decisions_for_run
from kvopt.costaware.replay import (
    DecisionSnapshot,
    ExecutedP1BStrategy,
    ReplayState,
    candidate_key,
    load_decision_snapshots,
    replay_decision,
    validate_replay_fidelity,
)
from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.pipeline import (
    build_derived_dataset_bundle,
    discover_run_artifacts,
)

#: Release sets larger than this are not enumerated for the "best alternative".
EXHAUSTIVE_LIMIT = 8
MAX_ALTERNATIVE_SIZE = 3


@dataclass(frozen=True)
class VerifiedChain:
    """A chain whose content identity was proved, with 1-based content depths."""

    depth_of: dict[int, int]
    length: int


@dataclass
class DecisionRecord:
    snapshot: DecisionSnapshot
    rows: dict[tuple[str, str], DecisionCandidateRow]
    chains: dict[tuple[str, str], VerifiedChain]
    q: dict[tuple[str, str], float]

    @property
    def key(self) -> tuple[str, int]:
        return (self.snapshot.run_id, self.snapshot.decision_event_index)


# --------------------------------------------------------------------------
# the three quantities, computed only from frozen state
# --------------------------------------------------------------------------


def eligible_ids(snapshot: DecisionSnapshot, released: frozenset) -> frozenset[int]:
    """Frozen eligibility: identical to ``ReplayState.eligible_block_ids``."""
    state = _state_with(snapshot, released)
    return state.eligible_block_ids()


def _state_with(snapshot: DecisionSnapshot, released: frozenset) -> ReplayState:
    state = ReplayState(snapshot)
    for key in snapshot.candidate_keys:
        if key in released:
            state.release(key)
    return state


def victim_ids(snapshot: DecisionSnapshot, released: frozenset) -> frozenset[int]:
    """(2) Actual native victims: tier-ordered, rank-truncated to the target."""
    state = _state_with(snapshot, released)
    eligible = state.eligible_block_ids()
    ranked = sorted(
        (block for block in snapshot.queue if block.block_id in eligible),
        key=lambda b: (0 if not b.has_block_hash else 1, b.native_lru_rank),
    )
    return frozenset(block.block_id for block in ranked[: snapshot.target])


def newly_eligible(snapshot: DecisionSnapshot, released: frozenset, add) -> frozenset[int]:
    """(1) Blocks that become eligible when ``add`` joins ``released``."""
    before = eligible_ids(snapshot, released)
    after = eligible_ids(snapshot, released | {add})
    return frozenset(after - before)


def model_loss(record: DecisionRecord, released: frozenset) -> float | None:
    """(4) Proxy-weighted loss over (3) verified depths.

    ``None`` when any chain that the eviction touches has no verified depth, which
    keeps unverifiable decisions out of every comparison instead of silently
    scoring them.
    """
    dead = victim_ids(record.snapshot, released)
    if not dead:
        return 0.0
    total = 0.0
    for key, chain in record.chains.items():
        depths = [chain.depth_of[block_id] for block_id in dead if block_id in chain.depth_of]
        if not depths:
            continue
        total += record.q.get(key, 0.5) * (chain.length - min(depths) + 1)
    if not _all_touched_are_verified(record, dead):
        return None
    return total


def _all_touched_are_verified(record: DecisionRecord, dead: frozenset[int]) -> bool:
    for block_id in dead:
        owners = record.snapshot.owners_by_block.get(block_id, frozenset())
        for owner in owners:
            chain = record.chains.get(owner)
            if chain is None or block_id not in chain.depth_of:
                return False
    return True


# --------------------------------------------------------------------------
# loading, with the A0 fidelity gate
# --------------------------------------------------------------------------


def load_decisions(
    root: Path, *, tau: float = 30.0, q_mode: str = "deadline"
) -> tuple[list[DecisionRecord], dict]:
    raw_runs = discover_run_artifacts(root)
    bundle = build_derived_dataset_bundle(raw_runs, formal_campaign=False)
    snapshots = load_decision_snapshots(raw_runs)

    rows_by_decision: dict[tuple[str, int], dict] = {}
    for row in bundle.decision_candidates:
        rows_by_decision.setdefault((row.run_id, row.decision_event_index), {})[
            candidate_key(row)
        ] = row

    # RC1 gate: the loader must reproduce the observed A0 decision exactly.
    fidelity = validate_replay_fidelity(snapshots, rows_by_decision, ExecutedP1BStrategy())
    gate = {
        "raw_runs": len(raw_runs),
        "snapshots": len(snapshots),
        "a0_decisions_compared": fidelity.decisions_compared,
        "a0_set_match_rate": fidelity.release_set_match_rate,
        "a0_sequence_match_rate": fidelity.release_sequence_match_rate,
    }

    # (3) verified content depth, per run, keyed by chain and by decision.
    proofs_by_run: dict[str, dict[int, dict]] = {}
    unreadable_runs: list[str] = []
    for run_dir in sorted({path.parent for path in root.rglob("events.jsonl")}):
        try:
            inputs = decisions_for_run(run_dir)
        except Exception:  # noqa: BLE001 - an unreadable run is excluded, not guessed
            unreadable_runs.append(run_dir.name)
            continue
        for decision in inputs:
            proofs_by_run.setdefault(run_dir.name, {})[
                decision.snapshot.decision_event_index
            ] = decision.proofs
    gate["unreadable_runs"] = len(unreadable_runs)

    records: list[DecisionRecord] = []
    for snapshot in snapshots:
        rows = rows_by_decision.get(
            (snapshot.run_id, snapshot.decision_event_index), {}
        )
        if not rows:
            continue
        proofs = proofs_by_run.get(snapshot.run_id, {}).get(
            snapshot.decision_event_index, {}
        )
        chains: dict = {}
        for key, proof in proofs.items():
            if not proof.proved:
                continue
            entry_key = _entry_key_from_chain(key, snapshot)
            if entry_key is None:
                continue
            depth_of = {
                block_id: position
                for position, block_id in enumerate(proof.block_ids, start=1)
            }
            chains[entry_key] = VerifiedChain(depth_of=depth_of, length=len(proof.block_ids))
        q = {
            key: (
                0.5
                if q_mode == "uniform"
                else _deadline_proxy(
                    rows[key].retention_deadline_timestamp, snapshot.timestamp, tau
                )
            )
            for key in rows
        }
        records.append(
            DecisionRecord(snapshot=snapshot, rows=rows, chains=chains, q=q)
        )
    return records, gate


def _entry_key_from_chain(chain: str, snapshot: DecisionSnapshot):
    """``program:prefix`` proof key back to a candidate key, when unambiguous."""
    for key in snapshot.candidate_keys:
        if f"{key[0]}:{key[1]}" == chain:
            return key
    return None


def _deadline_proxy(deadline: float, timestamp: float, tau: float) -> float:
    x = (deadline - timestamp) / tau
    x = max(-60.0, min(60.0, x))
    return 1.0 / (1.0 + math.exp(-x))


# --------------------------------------------------------------------------
# A1 replay through the frozen ladder
# --------------------------------------------------------------------------


def a1_replay(record: DecisionRecord) -> tuple[tuple, tuple[str, ...]]:
    """(RC1) Replay the frozen A1 ladder, returning its release sequence and branches."""
    strategy = A1EntryCostAwareStrategy()
    outcome = replay_decision(record.snapshot, strategy, record.rows)
    branches = _trace_branches(record, strategy)
    return outcome.released, branches


def _trace_branches(record: DecisionRecord, strategy: A1EntryCostAwareStrategy):
    state = ReplayState(record.snapshot)
    branches: list[str] = []
    for _ in range(len(record.snapshot.candidate_keys) + 1):
        if len(state.eligible_block_ids()) >= record.snapshot.target:
            break
        remaining = [
            record.rows[key]
            for key in record.snapshot.candidate_keys
            if key not in state.released and key in record.rows
        ]
        if not remaining:
            break
        selection = strategy.select(remaining, state)
        branches.append(selection.branch)
        state.release(selection.key)
    return tuple(branches)


def best_alternative(record: DecisionRecord) -> tuple[tuple, float] | None:
    """Lowest model loss over feasible release sets up to ``MAX_ALTERNATIVE_SIZE``."""
    keys = list(record.snapshot.candidate_keys)
    if len(keys) > EXHAUSTIVE_LIMIT:
        return None
    best: tuple[tuple, float] | None = None
    for size in range(min(MAX_ALTERNATIVE_SIZE, len(keys)) + 1):
        for combo in itertools.combinations(keys, size):
            released = frozenset(combo)
            if len(eligible_ids(record.snapshot, released)) < record.snapshot.target:
                continue
            value = model_loss(record, released)
            if value is None:
                continue
            if best is None or value < best[1] - 1e-12:
                best = (combo, value)
    return best


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv[1:] if not arg.startswith("--")]
    tau = 30.0
    q_mode = "deadline"
    for arg in argv[1:]:
        if arg.startswith("--tau="):
            tau = float(arg.split("=", 1)[1])
        elif arg.startswith("--q="):
            q_mode = arg.split("=", 1)[1]
    if not roots:
        print("usage: a1_real_gap.py [--q=deadline|uniform] [--tau=30] <root> [...]")
        return 2
    print(f"loss weights: {'uniform 0.5' if q_mode == 'uniform' else f'deadline proxy, tau={tau}'}")
    print()

    records: list[DecisionRecord] = []
    gates = []
    for root in roots:
        loaded, gate = load_decisions(root, tau=tau, q_mode=q_mode)
        records.extend(loaded)
        gates.append((root, gate))

    print("== RC1 loader gate: A0 must reproduce the observed decision ==")
    for root, gate in gates:
        print(f"  {root}")
        for key, value in gate.items():
            print(f"    {key:24s} {value}")
        if gate["a0_set_match_rate"] != 1.0 or gate["a0_sequence_match_rate"] != 1.0:
            print("    ABORT: baseline replay does not reproduce observed A0")
            return 1

    branches = Counter()
    replay_valid = 0
    content_verified = 0
    undecidable = Counter()
    comparisons = 0
    a1_better = 0
    a1_worse = 0
    cardinality = Counter()
    gaps: list[float] = []
    examples = []

    for record in records:
        released, trace = a1_replay(record)
        branches.update(trace)
        replay_valid += 1

        a1_loss = model_loss(record, frozenset(released))
        if a1_loss is None:
            undecidable["a1_set_touches_unverified_chain"] += 1
            continue
        if len(record.chains) < len(record.snapshot.candidate_keys):
            undecidable["not_every_candidate_chain_proved"] += 1
            continue
        content_verified += 1

        best = best_alternative(record)
        if best is None:
            undecidable["too_many_candidates_to_enumerate"] += 1
            continue
        comparisons += 1
        gap = a1_loss - best[1]
        gaps.append(gap)
        delta_size = len(best[0]) - len(released)
        if gap > 1e-9:
            a1_worse += 1
            cardinality[("worse", delta_size)] += 1
            if len(examples) < 3:
                examples.append((record, released, a1_loss, best[0], best[1]))
        elif gap < -1e-9:
            a1_better += 1
            cardinality[("better", delta_size)] += 1
        else:
            cardinality[("tie", delta_size)] += 1

    print()
    print("== RC3 decision accounting ==")
    print(f"  replay-valid decisions              {replay_valid}")
    print(f"  content-verified decisions          {content_verified}")
    print(f"  decisions compared against best     {comparisons}")
    for reason, count in sorted(undecidable.items()):
        print(f"  undecidable: {reason:32s} {count}")

    print()
    print("== frozen A1 branch usage (RC1) ==")
    for branch, count in sorted(branches.items()):
        print(f"  {branch:24s} {count}")

    print()
    print("== A1 vs best feasible alternative (proxy-weighted model loss) ==")
    print(f"  A1 worse than the best alternative  {a1_worse}")
    print(f"  A1 better than the best alternative {a1_better}")
    if gaps:
        print(f"  mean (A1 - best)                    {sum(gaps) / len(gaps):.6f}")
        print(f"  max  (A1 - best)                    {max(gaps):.6f}")

    print()
    print("== cardinality of the best alternative vs A1's set ==")
    print("  outcome   size(best)-size(A1)   decisions")
    for (outcome, delta), count in sorted(cardinality.items()):
        print(f"  {outcome:8s}  {delta:+d}                {count}")
    print("  (delta 0 means the improvement, if any, needs no extra release)")
    for record, released, a1_loss, best_set, best_loss in examples:
        print()
        print(f"  {record.key} target={record.snapshot.target}")
        print(f"    A1   {released} -> {a1_loss:.4f}")
        print(f"    best {best_set} -> {best_loss:.4f}")

    print()
    print("== not measured here (RC2) ==")
    print("  (5) native actual recomputed tokens: not present in this corpus;")
    print("      aggregate_recomputed_tokens needs the (E, C) request-level pair.")
    print("  Every loss above is (4) proxy-weighted model loss over (3) verified")
    print("  content depths. It is not converted to tokens and no token bound is")
    print("  claimed. Candidate block_ids order is never used as content depth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
