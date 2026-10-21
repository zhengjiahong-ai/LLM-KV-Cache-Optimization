"""Does A1's entry scoring predict the loss that will actually be incurred?

M1 asks whether independent per-entry cost ranking is sufficient. This probe tests
the cost side against the frozen eviction rule.

Frozen rule (src/kvopt/continuum/selection.py):
    selected = virtual_eligible_order[:target]
    virtual_eligible_order = sorted(eligible, key=(eligibility_tier, native_lru_rank))
    TIER_1 = hashless (always eligible), TIER_2 = hashed and fully unlocked.

A1 scores entry i as
    Rhat_i = q_i * [min(need, N_i) + lambda * (N_i - min(need, N_i))^+]
where N_i is the number of blocks that *become eligible*. It never looks at rank.

Two quantities are therefore different:
  (a) relief   -- how many blocks become eligible (what A1 optimises);
  (b) realised -- which blocks are actually evicted, and hence what content dies.

This probe measures the gap between them. Analysis only; no algorithm change.
"""

from __future__ import annotations

import itertools
import random
import sys
from dataclasses import dataclass, field

sys.path.insert(0, "src")

TIER_HASHLESS = 1
TIER_HASHED = 2


@dataclass(frozen=True)
class Block:
    block_id: int
    rank: int
    has_hash: bool
    owners: frozenset[str] = frozenset()


@dataclass
class Decision:
    """One pressure decision: a free queue, the candidate entries, and the targets."""

    queue: tuple[Block, ...]
    entries: tuple[str, ...]
    target: int
    q: dict[str, float]
    #: program -> its prefix as a list of block ids, shallowest first
    prefixes: dict[str, tuple[int, ...]]
    #: program -> the entry that represents it (which entry release covers it)
    program_entry: dict[str, str] = field(default_factory=dict)


def _tier(block: Block, released: frozenset[str]) -> int | None:
    if not block.has_hash:
        return TIER_HASHLESS
    if block.owners <= released:
        return TIER_HASHED
    return None  # still protected


def eligible_blocks(decision: Decision, released: frozenset[str]) -> tuple[Block, ...]:
    """Blocks the frozen rule could take, in its own selection order."""
    rows = []
    for block in decision.queue:
        tier = _tier(block, released)
        if tier is None:
            continue
        rows.append((tier, block.rank, block))
    rows.sort(key=lambda row: (row[0], row[1]))
    return tuple(block for _, _, block in rows)


def evicted_blocks(decision: Decision, released: frozenset[str]) -> tuple[Block, ...]:
    """Exactly what the frozen rule evicts: the coldest ``target`` of the eligible set."""
    return eligible_blocks(decision, released)[: decision.target]


def realised_loss(decision: Decision, released: frozenset[str]) -> float:
    """APC loss of the blocks that are actually evicted.

    Per program: the shallowest evicted depth decides, and everything from there on
    must be recomputed.
    """
    dead = {block.block_id for block in evicted_blocks(decision, released)}
    total = 0.0
    for program, prefix in decision.prefixes.items():
        depths = [index + 1 for index, block_id in enumerate(prefix) if block_id in dead]
        if not depths:
            continue
        total += decision.q[program] * (len(prefix) - min(depths) + 1)
    return total


def relief(decision: Decision, released: frozenset[str]) -> int:
    return len(eligible_blocks(decision, released))


# --------------------------------------------------------------------------
# A1's decision, reproduced from src/kvopt/costaware/a1_entry.py
# --------------------------------------------------------------------------


def a1_score(
    decision: Decision, released: frozenset[str], entry: str, *, lambda_: float = 0.5
) -> float:
    before = relief(decision, released)
    after = relief(decision, released | {entry})
    new_blocks = after - before
    need = max(0, decision.target - before)
    forced = min(need, new_blocks)
    residual = max(0, new_blocks - forced)
    q = decision.q.get(entry, 0.5)
    return q * (forced + lambda_ * residual)


def a1_sequence(decision: Decision, *, lambda_: float = 0.5) -> tuple[str, ...]:
    """A1's ladder reduced to its scoring core: repeatedly take the cheapest entry."""
    released: frozenset[str] = frozenset()
    order: list[str] = []
    while relief(decision, released) < decision.target:
        remaining = [e for e in decision.entries if e not in released]
        if not remaining:
            break
        best = min(remaining, key=lambda e: (a1_score(decision, released, e), e))
        released = released | {best}
        order.append(best)
    return tuple(order)


def optimal_set(decision: Decision) -> tuple[tuple[str, ...], float]:
    """Exhaustive: the release set with the lowest realised loss meeting the target.

    All sizes are searched, because realised loss is **not** monotone in the release
    set: adding an entry can make a colder block eligible, which displaces a warmer
    block from the evicted set and can therefore *lower* the loss.
    """
    best: tuple[tuple[str, ...], float] | None = None
    for size in range(len(decision.entries) + 1):
        for combo in itertools.combinations(decision.entries, size):
            released = frozenset(combo)
            if relief(decision, released) < decision.target:
                continue
            loss = realised_loss(decision, released)
            if best is None or loss < best[1] - 1e-12:
                best = (combo, loss)
    return best if best is not None else ((), float("inf"))


def a1_set(decision: Decision) -> tuple[str, ...]:
    return a1_sequence(decision)


# --------------------------------------------------------------------------
# counterexample: relief says "free", the eviction says otherwise
# --------------------------------------------------------------------------


def relief_not_eviction() -> None:
    """An entry whose blocks become eligible but are too warm to be evicted.

    Queue ranks 0..5. Blocks 0..2 are hashless (tier 1, taken first). Blocks 3..5
    are hashed and owned by entry ``e`` alone. target = 3, so the hashless blocks
    already satisfy the target: releasing ``e`` changes nothing at all, yet A1
    charges q_e * N_e for it because N_e = 3.
    """
    blocks = tuple(
        [Block(i, i, False) for i in range(3)]
        + [Block(3 + i, 3 + i, True, frozenset({"e"})) for i in range(3)]
    )
    decision = Decision(
        queue=blocks,
        entries=("e",),
        target=3,
        q={"e": 0.9, "p": 0.9},
        prefixes={"p": (3, 4, 5)},
    )

    print("== case: release whose blocks are never evicted ==")
    print(f"  before: eligible={relief(decision, frozenset())} target={decision.target}")
    print("  N_e (blocks unlocked by e)      = 3")
    print(f"  actually evicted after releasing e = "
          f"{[b.block_id for b in evicted_blocks(decision, frozenset({'e'}))]}")
    print(f"  realised loss of releasing e = {realised_loss(decision, frozenset({'e'})):.4f}")
    print(f"  realised loss of releasing nothing = "
          f"{realised_loss(decision, frozenset()):.4f}")
    print(f"  A1 charge for e = q_e * N_e = {0.9 * 3:.4f}")
    print("  -> A1 pays for 3 blocks that are not evicted and whose content survives")


def warm_vs_cold() -> None:
    """Same N_i, different realised loss: the entry's own depth decides the cost.

    ``target = 1``, so exactly one block dies: whichever became eligible. Releasing
    ``cold`` unlocks a block at depth 1 of a 3-block prefix (the whole prefix must be
    recomputed); releasing ``warm`` unlocks a block at depth 3 of a 3-block prefix
    (one block). Both unlock exactly one block, so A1 scores them identically.
    """
    queue = (
        Block(10, 0, True, frozenset({"cold"})),
        Block(11, 1, True, frozenset({"warm"})),
    )
    decision = Decision(
        queue=queue,
        entries=("cold", "warm"),
        target=1,
        q={"cold": 0.5, "warm": 0.5, "pc": 0.5, "pw": 0.5},
        # cold block sits at depth 1 of pc; warm block at depth 3 of pw
        prefixes={"pc": (10, 90, 91), "pw": (92, 93, 11)},
    )
    print()
    print("== case: equal relief, different realised loss ==")
    for entry in ("cold", "warm"):
        released = frozenset({entry})
        print(
            f"  release {entry:>4}: N = 1,  evicted = "
            f"{[b.block_id for b in evicted_blocks(decision, released)]},  "
            f"loss = {realised_loss(decision, released):.4f}"
        )
    print(f"  A1 score cold = {a1_score(decision, frozenset(), 'cold'):.4f}, "
          f"warm = {a1_score(decision, frozenset(), 'warm'):.4f}  -> identical")
    print("  -> A1 cannot separate them; the ranking that matters is created by the")
    print("     interaction of eligibility with native rank, which A1 does not read")


# --------------------------------------------------------------------------
# random sweep
# --------------------------------------------------------------------------


def _random_decision(rng: random.Random, *, share_probability: float = 0.25) -> Decision:
    programs = ["p0", "p1", "p2"][: rng.randint(1, 3)]
    entries = list(programs)
    # each program has a prefix; entries own their prefix, shared blocks may occur
    prefixes: dict[str, tuple[int, ...]] = {}
    owners: dict[int, set[str]] = {}
    next_id = 0
    for program in programs:
        length = rng.randint(1, 4)
        prefix = []
        for _depth in range(length):
            # occasionally reuse a block from another program (shared prefix)
            if prefixes and rng.random() < share_probability:
                donor = rng.choice([p for p in prefixes if prefixes[p]])
                block_id = rng.choice(prefixes[donor])
            else:
                block_id = next_id
                next_id += 1
            owners.setdefault(block_id, set()).add(program)
            prefix.append(block_id)
        prefixes[program] = tuple(prefix)

    hashless = {block_id for block_id in owners if rng.random() < 0.2}
    ids = sorted(owners)
    ranks = list(range(len(ids)))
    rng.shuffle(ranks)
    queue = tuple(
        Block(
            block_id,
            ranks[index],
            block_id not in hashless,
            frozenset(owners[block_id]),
        )
        for index, block_id in enumerate(ids)
    )
    target = rng.randint(1, max(1, len(queue) // 2 + 1))
    q = {name: round(rng.uniform(0.2, 0.9), 3) for name in entries}
    q.update({program: q[program] for program in programs})
    return Decision(
        queue=queue, entries=tuple(entries), target=target, q=q, prefixes=prefixes
    )


def sweep(trials=3000, seed=7) -> dict[str, int]:
    rng = random.Random(seed)
    stats = dict.fromkeys(
        [
            "decisions",
            "a1_suboptimal",
            "a1_over_releases",
            "singleton_ranking_disagrees",
            "loss_not_monotone_in_release_set",
        ],
        0,
    )
    worst = 0.0
    example = None
    for _ in range(trials):
        decision = _random_decision(rng)
        chosen = a1_set(decision)
        _best_set, best_loss = optimal_set(decision)
        if best_loss == float("inf"):
            continue
        stats["decisions"] += 1
        chosen_loss = realised_loss(decision, frozenset(chosen))
        if chosen_loss > best_loss + 1e-9:
            stats["a1_suboptimal"] += 1
            gap = chosen_loss - best_loss
            if gap > worst:
                worst = gap
                example = (decision, chosen, chosen_loss, _best_set, best_loss)
        if len(chosen) > len(_best_set):
            stats["a1_over_releases"] += 1

        # does A1's own singleton ranking agree with the realised loss ranking?
        singletons = [
            (
                a1_score(decision, frozenset(), entry),
                realised_loss(decision, frozenset({entry})),
                entry,
            )
            for entry in decision.entries
        ]
        if singletons:
            by_score = min(singletons, key=lambda row: (row[0], row[2]))[2]
            by_loss = min(singletons, key=lambda row: (row[1], row[2]))[2]
            if by_score != by_loss and abs(
                realised_loss(decision, frozenset({by_score}))
                - realised_loss(decision, frozenset({by_loss}))
            ) > 1e-9:
                stats["singleton_ranking_disagrees"] += 1

        # is realised loss monotone under adding an entry to the release set?
        for size in (1, 2):
            for combo in itertools.combinations(decision.entries, size):
                released = frozenset(combo)
                if relief(decision, released) < decision.target:
                    continue
                base = realised_loss(decision, released)
                for extra in decision.entries:
                    if extra in released:
                        continue
                    bigger = released | {extra}
                    if relief(decision, bigger) < decision.target:
                        continue
                    if realised_loss(decision, bigger) < base - 1e-9:
                        stats["loss_not_monotone_in_release_set"] += 1
                        break
                else:
                    continue
                break
    return stats, worst, example


def lambda_sensitivity(trials=2000, seed=13):
    """Does A1's residual-penalty term help or hurt realised loss?

    ``Rhat_i = q_i [min(need, N_i) + lambda (N_i - min(need, N_i))^+]``.
    When ``N_i`` exceeds what the decision needs, A1 multiplies the excess by
    ``lambda``. The excess blocks are exactly the ones that will NOT be evicted, so
    charging for them pushes A1 away from entries whose relief is simply larger than
    necessary -- which may be the right choice. Compare lambda = 0 (pure relief
    preference, i.e. prefer smaller N_i) with lambda = 1 and the production 0.5.
    """
    rng = random.Random(seed)
    results = {}
    for lambda_ in (0.0, 0.5, 1.0):
        total = 0.0
        worse = 0
        for _ in range(trials):
            decision = _random_decision(rng)
            released: frozenset[str] = frozenset()
            order: list[str] = []
            while relief(decision, released) < decision.target:
                remaining = [e for e in decision.entries if e not in released]
                if not remaining:
                    break
                best = min(
                    remaining,
                    key=lambda e: (a1_score(decision, released, e, lambda_=lambda_), e),
                )
                released = released | {best}
                order.append(best)
            _best_set, best_loss = optimal_set(decision)
            if best_loss == float("inf"):
                continue
            loss = realised_loss(decision, released)
            total += loss
            if loss > best_loss + 1e-9:
                worse += 1
        results[lambda_] = (total / trials, worse)
    return results


def sharing_sensitivity():
    """How does the gap depend on how much prefixes overlap?

    A1's blind spot is that eligibility relief does not determine which blocks die.
    With no shared blocks, releasing one entry unlocks only its own prefix, so relief
    and eviction are more tightly coupled. With heavy sharing, unlocking is a joint
    property and the coupling weakens. Report the gap per sharing level rather than
    one aggregate number.
    """
    rng = random.Random(29)
    print("  sharing   decisions   a1 suboptimal   mean gap   worst gap")
    for share_probability in (0.0, 0.25, 0.5, 0.75):
        suboptimal = 0
        gaps = []
        for _ in range(1200):
            decision = _random_decision(rng, share_probability=share_probability)
            chosen = a1_set(decision)
            _best_set, best_loss = optimal_set(decision)
            if best_loss == float("inf"):
                continue
            loss = realised_loss(decision, frozenset(chosen))
            gaps.append(loss - best_loss)
            if loss > best_loss + 1e-9:
                suboptimal += 1
        if not gaps:
            continue
        print(
            f"  {share_probability:7.2f}   {len(gaps):9d}   {suboptimal:13d}   "
            f"{sum(gaps) / len(gaps):8.4f}   {max(gaps):9.4f}"
        )


def main() -> int:
    relief_not_eviction()
    warm_vs_cold()

    stats, worst, example = sweep()
    print()
    print("== random sweep (3000 synthetic decisions) ==")
    for key, value in stats.items():
        print(f"  {key:34s} {value}")
    print(f"  worst A1-vs-optimal realised-loss gap: {worst:.4f}")
    if example is not None:
        decision, chosen, chosen_loss, best_set, best_loss = example
        print()
        print("  worst example:")
        print(f"    target={decision.target}  entries={decision.entries}")
        print(
            "    queue="
            f"{[(b.block_id, b.rank, b.has_hash, sorted(b.owners)) for b in decision.queue]}"
        )
        print(f"    A1   {chosen} -> loss {chosen_loss:.4f}")
        print(f"    best {best_set} -> loss {best_loss:.4f}")
        print(
            "    evicted by A1   = "
            f"{[b.block_id for b in evicted_blocks(decision, frozenset(chosen))]}"
        )
        print(
            "    evicted by best = "
            f"{[b.block_id for b in evicted_blocks(decision, frozenset(best_set))]}"
        )

    print()
    print("== lambda sensitivity (mean realised loss, A1-worse count) ==")
    for lambda_, (mean_loss, worse) in lambda_sensitivity().items():
        print(f"  lambda={lambda_:.1f}  mean realised loss {mean_loss:8.4f}   worse {worse}")

    print()
    print("== gap vs prefix sharing ==")
    sharing_sensitivity()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
