"""Measure how often incremental greedy is suboptimal, over random geometries.

This backs the claim in ``docs/experiments/phase2g-a2-algorithm/README.md`` that the
exact selector earns its place rather than being defensive padding: greedy *is*
suboptimal sometimes, and the document quotes the rate and the worst gap.

Runs on synthetic geometries only -- no artifacts needed.

Usage::

    python scripts/probes/a2_greedy_gap.py [--trials 4000] [--seed 20261018]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
)
from kvopt.costaware.a2_selector import (
    chain_loss,
    exact_select,
    greedy_select,
)

#: Documented figures, asserted under --strict.
DOCUMENTED_SUBOPTIMAL = 25
DOCUMENTED_TESTED = 3684


def _build(rng: random.Random) -> DecisionGeometry:
    n_chains = rng.randint(1, 3)
    chains = [f"c{i}" for i in range(n_chains)]
    lengths = {c: rng.randint(2, 4) for c in chains}
    q = {c: round(rng.choice([0.1, 0.3, 0.5, 0.9]), 3) for c in chains}

    blocks: dict[int, LegalBlock] = {}
    bid = 0
    for chain in chains:
        for depth in range(1, lengths[chain] + 1):
            bid += 1
            blocks[bid] = LegalBlock(
                block_id=bid,
                native_rank=rng.randint(0, 50),
                memberships=(Membership(chain, depth, f"{chain}#{depth}"),),
            )

    if n_chains >= 2 and rng.random() < 0.6:
        first, second = rng.sample(chains, 2)
        depth = min(lengths[first], lengths[second])
        for chain in (first, second):
            for block_id, block in list(blocks.items()):
                only = block.memberships[0]
                if only.chain == chain and only.depth == depth:
                    del blocks[block_id]
                    break
        bid += 1
        blocks[bid] = LegalBlock(
            block_id=bid,
            native_rank=rng.randint(0, 50),
            memberships=(
                Membership(first, depth, f"shared#{depth}"),
                Membership(second, depth, f"shared#{depth}"),
            ),
        )

    return DecisionGeometry(blocks=blocks, chain_length=lengths, q_by_chain=q)


def _loss(geometry: DecisionGeometry, blocks) -> float:
    evicted: dict[str, set[int]] = {}
    for block_id in blocks:
        for membership in geometry.blocks[block_id].memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return chain_loss(evicted, geometry)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    tested = suboptimal = 0
    worst_gap = 0.0
    first: dict[str, object] | None = None

    for _ in range(args.trials):
        geometry = _build(rng)
        n = len(geometry.blocks)
        if n < 2 or n > 9:
            continue
        need = rng.randint(1, min(3, n))
        greedy, _steps = greedy_select(geometry, need)
        exact = exact_select(geometry, need, budget=10**9)
        if exact is None:
            continue
        exact_blocks, exact_loss = exact
        greedy_loss = _loss(geometry, greedy)
        tested += 1
        if exact_loss < greedy_loss - 1e-12:
            suboptimal += 1
            gap = greedy_loss - exact_loss
            worst_gap = max(worst_gap, gap)
            if first is None:
                first = {
                    "need": need,
                    "q": dict(geometry.q_by_chain),
                    "lengths": dict(geometry.chain_length),
                    "greedy": greedy,
                    "greedy_loss": greedy_loss,
                    "exact": exact_blocks,
                    "exact_loss": exact_loss,
                }

    print(f"geometries tested          : {tested}")
    print(f"greedy suboptimal in       : {suboptimal}"
          f"  = {100 * suboptimal / max(1, tested):.2f}%")
    print(f"worst greedy-exact gap     : {worst_gap:.6f}")
    if first:
        print(f"first counterexample       : {first}")

    if args.strict:
        assert tested == DOCUMENTED_TESTED, tested
        assert suboptimal == DOCUMENTED_SUBOPTIMAL, suboptimal
        print("\nSTRICT: documented counts reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
