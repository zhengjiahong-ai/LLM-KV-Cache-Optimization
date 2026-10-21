"""A2 decision-space structure: when can cost-aware selection differ from LRU?

Analysis only -- no algorithm change, no native run. The frozen objective is

    L(S) = sum_c q_c * (m_c - j_c(S) + 1),   j_c = min evicted depth

Two candidate sources of divergence from native LRU:
  (D) depth inversion -- a shallower block is colder than a deeper one, so native
      evicts a shallow block while deeper free blocks exist;
  (Q) cross-chain reordering -- q reorders chains against native recency.

This probe checks: is divergence contained in (D) or in (multi-chain AND (Q))?
"""

from __future__ import annotations

import random
import sys

sys.path.insert(0, "src")

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
)
from kvopt.costaware.a2_selector import (
    chain_loss,
    native_lru_order,
    select_victims,
)


def _rng_ranks(chains, rng, invert_probability):
    """Coldest-first depth order per chain -> rank of each depth."""
    ranks = {}
    for name, length in chains.items():
        coldest_first = list(range(1, length + 1))
        rng.shuffle(coldest_first)
        if rng.random() < invert_probability:
            coldest_first = sorted(coldest_first)  # shallowest is coldest
        ranks[name] = {depth: rank for rank, depth in enumerate(coldest_first)}
    return ranks


def _geometry(chains, ranks, q):
    blocks = {}
    next_id = 100
    for name, length in chains.items():
        for depth in range(1, length + 1):
            blocks[next_id] = LegalBlock(
                next_id,
                ranks[name][depth],
                (Membership(name, depth, f"{name}#{depth}"),),
            )
            next_id += 1
    return DecisionGeometry(
        blocks=blocks,
        chain_length=dict(chains),
        q_by_chain=dict(q),
    )


def _inverted(geometry):
    """True when a shallower block is colder than a deeper one in some chain."""
    for name in geometry.chain_length:
        by_depth = {}
        for block in geometry.blocks.values():
            for membership in block.memberships:
                if membership.chain == name:
                    by_depth[membership.depth] = block.native_rank
        ordered = [by_depth[d] for d in sorted(by_depth)]
        if any(ordered[i] < ordered[i + 1] for i in range(len(ordered) - 1)):
            return True
    return False


def _touched(geometry, blocks):
    return {m.chain for b in blocks for m in geometry.blocks[b].memberships}


def _loss(geometry, blocks):
    evicted = {}
    for block_id in blocks:
        for membership in geometry.blocks[block_id].memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return chain_loss(evicted, geometry)


def decide(chains, ranks, q, need):
    geometry = _geometry(chains, ranks, q)
    native = native_lru_order(geometry)[:need]
    aware = select_victims(geometry, need).blocks
    return geometry, native, aware


def survey(trials=4000, seed=11):
    rng = random.Random(seed)
    counts = dict.fromkeys(
        [
            "decisions",
            "inverted",
            "multi_chain",
            "differs",
            "differs_neither_inverted_nor_multi_chain",
            "differs_with_no_inverted_chain",
        ],
        0,
    )
    unexplained = []
    for _ in range(trials):
        names = [f"c{i}" for i in range(rng.choice([1, 1, 2, 3]))]
        chains = {name: rng.randint(2, 5) for name in names}
        ranks = _rng_ranks(chains, rng, invert_probability=0.30)
        q = {name: 0.5 for name in names}

        need = rng.randint(1, min(3, sum(chains.values())))
        geometry, native, aware = decide(chains, ranks, q, need)

        counts["decisions"] += 1
        inverted = _inverted(geometry)
        multi = len(_touched(geometry, geometry.blocks)) > 1
        counts["inverted"] += int(inverted)
        counts["multi_chain"] += int(multi)
        if set(native) != set(aware):
            counts["differs"] += 1
            if not inverted and not multi:
                counts["differs_neither_inverted_nor_multi_chain"] += 1
                unexplained.append((chains, need, native, aware))
            if not inverted:
                counts["differs_with_no_inverted_chain"] += 1
    return counts, unexplained


def shared_vs_inversion(rounds=1500, seed=3):
    """Separate the shared-block effect from the depth-inversion effect.

    A shared block can only help if native picks it. If it is shallow while deeper
    private blocks are colder, that pick *is* a depth inversion, so the two effects
    are confounded by construction. This function classifies each decision by
    (inversion present, shared block present) and reports the gain per cell, so a
    reader can see that there is no cell with sharing and no inversion.
    """
    rng = random.Random(seed)
    cells = {}
    for _ in range(rounds):
        chains = {"a": rng.randint(3, 6), "b": rng.randint(3, 6)}
        ranks = {}
        for name, length in chains.items():
            # every chain strictly deepest-first: depth d gets rank length - d
            ranks[name] = {d: length - d for d in range(1, length + 1)}
        q = {name: 0.5 for name in chains}
        geometry = _geometry(chains, ranks, q)

        share = rng.random() < 0.5
        if share:
            geometry = _with_shared_tail(geometry, chains, ranks)

        need = rng.randint(1, min(2, len(geometry.blocks)))
        native = native_lru_order(geometry)[:need]
        aware = select_victims(geometry, need).blocks
        gain = _loss(geometry, native) - _loss(geometry, aware)
        key = (share, _inverted(geometry))
        cell = cells.setdefault(key, {"n": 0, "gain": 0, "best": 0.0})
        cell["n"] += 1
        cell["gain"] += int(gain > 1e-12)
        cell["best"] = max(cell["best"], gain)
    return cells


def canonical_flatness():
    """Lemma B applies to canonical sets only: no shared block, deepest suffix per chain.

    A canonical set takes, for each chain, a contiguous run of the deepest blocks and
    never evicts a shared block. Under uniform q every such set scores ``q * k``.
    Sets outside that family need not, which is what the counterexample shows.
    """
    geometry = _geometry(
        {"a": 4, "b": 4},
        {"a": {d: 4 - d for d in range(1, 5)}, "b": {d: 4 - d for d in range(1, 5)}},
        {"a": 0.5, "b": 0.5},
    )
    by_depth = {"a": {}, "b": {}}
    for block_id, block in geometry.blocks.items():
        member = block.memberships[0]
        by_depth[member.chain][member.depth] = block_id

    print("  k   canonical choices (suffix depth per chain)            loss")
    for k in (1, 2):
        rows = []
        for ka in range(k + 1):
            kb = k - ka
            if ka > 4 or kb > 4:
                continue
            picks = [by_depth["a"][d] for d in range(5 - ka, 5)] if ka else []
            picks += [by_depth["b"][d] for d in range(5 - kb, 5)] if kb else []
            rows.append((ka, kb, _loss(geometry, picks)))
        for ka, kb, loss in rows:
            print(f"  {k}   a gets {ka}, b gets {kb}{'':32} {loss:.4f}")
        distinct = {round(loss, 12) for _, _, loss in rows}
        print(f"      -> distinct losses {sorted(distinct)}  "
              f"flat={len(distinct) == 1}")


def exhaustive_non_inverted(limit=6):
    """Enumerate small non-inverted geometries with a shared block, exhaustively.

    If sharing could pay off without a depth inversion, some of these must diverge.
    Stronger than a random search because the space is enumerated.
    """
    import itertools

    checked = 0
    divergent = 0
    for length_a, length_b in itertools.product([2, 3, 4], [2, 3, 4]):
        for shared_depth in range(1, min(length_a, length_b) + 1):
            private = [("a", d) for d in range(1, length_a + 1) if d != shared_depth]
            private += [("b", d) for d in range(1, length_b + 1) if d != shared_depth]
            if len(private) + 1 > limit:
                continue
            for perm in itertools.permutations(range(len(private) + 1)):
                blocks = {}
                for index, (chain, depth) in enumerate(private):
                    blocks[index + 1] = LegalBlock(
                        index + 1,
                        perm[index],
                        (Membership(chain, depth, f"{chain}#{depth}"),),
                    )
                shared_id = len(private) + 1
                blocks[shared_id] = LegalBlock(
                    shared_id,
                    perm[len(private)],
                    (
                        Membership("a", shared_depth, "shared"),
                        Membership("b", shared_depth, "shared"),
                    ),
                )
                geometry = DecisionGeometry(
                    blocks=blocks,
                    chain_length={"a": length_a, "b": length_b},
                    q_by_chain={"a": 0.5, "b": 0.5},
                )
                if _inverted(geometry):
                    continue
                checked += 1
                for need in (1, 2):
                    if need > len(blocks):
                        continue
                    native = native_lru_order(geometry)[:need]
                    aware = select_victims(geometry, need).blocks
                    gained = _loss(geometry, native) - _loss(geometry, aware)
                    if set(native) != set(aware) and gained > 1e-12:
                        divergent += 1
    return checked, divergent


def uniform_q_gain(trials=3000, seed=5, *, shared=False):
    """Uniform q, every chain already deepest-first: can A2 strictly improve?"""
    rng = random.Random(seed)
    better = 0
    worst = 0.0
    for _ in range(trials):
        names = [f"c{i}" for i in range(rng.choice([1, 2, 3]))]
        chains = {name: rng.randint(3, 6) for name in names}
        ranks = {}
        for name in names:
            # true deepest-first: deepest depth gets rank 0
            ranks[name] = {d: chains[name] - d for d in range(1, chains[name] + 1)}
        q = {name: 0.5 for name in names}

        geometry = _geometry(chains, ranks, q)
        if shared and len(names) > 1 and len(names) >= 2:
            geometry = _with_shared_tail(geometry, chains, ranks)
        need = rng.randint(1, min(3, len(geometry.blocks)))
        native = native_lru_order(geometry)[:need]
        aware = select_victims(geometry, need).blocks
        gain = _loss(geometry, native) - _loss(geometry, aware)
        if gain > 1e-12:
            better += 1
            worst = max(worst, gain)
    return better, worst


def _with_shared_tail(geometry, chains, ranks):
    """Replace depth-2 of two chains with one shared block ranked coldest.

    Sharing only creates room when the shared block sits *above* the deepest
    positions: evicting it then moves the gap in two chains at once, while a private
    deep block moves one gap by one block.
    """
    names = list(chains)
    left, right = names[0], names[-1]
    blocks = {}
    for bid, block in geometry.blocks.items():
        member = block.memberships[0]
        if member.chain in (left, right) and member.depth == 2:
            continue  # dropped; the shared block replaces both
        blocks[bid] = block
    next_id = max(geometry.blocks) + 1
    blocks[next_id] = LegalBlock(
        next_id,
        0,  # coldest: native takes it first
        (
            Membership(left, 2, "shared#2"),
            Membership(right, 2, "shared#2"),
        ),
    )
    return DecisionGeometry(
        blocks=blocks,
        chain_length=dict(geometry.chain_length),
        q_by_chain=dict(geometry.q_by_chain),
    )


def spread_linearity():
    """Non-inverted geometry: gain must scale with the q spread, vanishing at zero."""
    chains = {"a": 4, "b": 4}
    ranks = {
        "a": {4: 3, 3: 4, 2: 6, 1: 7},
        "b": {4: 0, 3: 1, 2: 2, 1: 8},
    }
    print("   q_a    q_b   native     cost_aware   L(native)  L(aware)    gain  2*(qb-qa)")
    for q_a, q_b in ((0.5, 0.5), (0.48, 0.52), (0.4, 0.6), (0.2, 0.8), (0.01, 0.99)):
        geometry, native, aware = decide(chains, ranks, {"a": q_a, "b": q_b}, 2)
        l_native = _loss(geometry, native)
        l_aware = _loss(geometry, aware)
        print(
            f"  {q_a:5.2f}  {q_b:5.2f}  {native!s:>9}  {aware!s:>10}   "
            f"{l_native:9.4f}  {l_aware:8.4f}  {l_native - l_aware:6.4f}  "
            f"{2 * (q_b - q_a):8.4f}"
        )


def main() -> int:
    counts, unexplained = survey()
    print("== structural survey: 4000 random decisions, uniform q ==")
    for key, value in counts.items():
        print(f"  {key:46s} {value}")
    print()
    print("  divergence with neither an inverted chain nor a multi-chain set: "
          f"{counts['differs_neither_inverted_nor_multi_chain']}")
    print("  divergence with no inverted chain at all: "
          f"{counts['differs_with_no_inverted_chain']}")
    if unexplained:
        print(f"  first unexplained: {unexplained[0]}")

    better, worst = uniform_q_gain()
    print()
    print("== uniform q, every chain deepest-first, no shared block ==")
    print(f"  3000 random decisions: cost-aware strictly better in {better}, "
          f"worst gain {worst:.6f}")

    shared_better, shared_worst = uniform_q_gain(shared=True)
    print()
    print("== uniform q, every chain deepest-first, shared block above the deepest ==")
    print(f"  3000 random decisions: cost-aware strictly better in {shared_better}, "
          f"worst gain {shared_worst:.6f}")

    cells = shared_vs_inversion()
    print()
    print("== shared effect vs inversion effect (uniform q) ==")
    print("  shared  inverted   decisions   strictly better   best gain")
    for (share, inverted), cell in sorted(cells.items()):
        print(
            f"  {share!s:>6}  {inverted!s:>8}   {cell['n']:9d}   "
            f"{cell['gain']:15d}   {cell['best']:9.4f}"
        )

    print()
    print("== lemma B scope: canonical (no shared, deepest suffix) sets only ==")
    canonical_flatness()

    print()
    print("== exhaustive small non-inverted geometries WITH a shared block ==")
    checked, divergent = exhaustive_non_inverted()
    print(f"  geometries checked: {checked}")
    print(f"  divergences with a positive proxy gain: {divergent}")

    print()
    print("== gain vs q spread on a non-inverted geometry (need = 2) ==")
    spread_linearity()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
