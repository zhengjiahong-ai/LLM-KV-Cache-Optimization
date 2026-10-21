"""Minimal counterexample: uniform q does NOT make every legal set cost equal.

M1 (RC1) requires distinguishing two non-equivalent statements:
  (i)  native already reaches the optimum on a decision;
  (ii) every legal victim set has the same proxy loss.

This script exhibits a decision where (i) holds and (ii) is false, using only
uniform q, no depth inversion, and one shared block.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
)
from kvopt.costaware.a2_selector import chain_loss, native_lru_order, select_victims


def _loss(geometry, blocks):
    evicted = {}
    for block_id in blocks:
        for membership in geometry.blocks[block_id].memberships:
            evicted.setdefault(membership.chain, set()).add(membership.depth)
    return chain_loss(evicted, geometry)


def _inverted(geometry):
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


def build():
    """Two 3-block chains sharing one block at depth 2. Uniform q, no inversion."""
    # Native order (rank 0 coldest): a@3, b@3 are the deepest and coldest.
    # The shared block at depth 2 is warmer than them, so native never picks it.
    blocks = {
        1: LegalBlock(1, 4, (Membership("a", 1, "a#1"),)),
        2: LegalBlock(2, 1, (Membership("a", 2, "s#2"), Membership("b", 2, "s#2"))),
        3: LegalBlock(3, 0, (Membership("a", 3, "a#3"),)),
        4: LegalBlock(4, 5, (Membership("b", 1, "b#1"),)),
        5: LegalBlock(5, 0, (Membership("b", 3, "b#3"),)),
    }
    return DecisionGeometry(
        blocks=blocks,
        chain_length={"a": 3, "b": 3},
        q_by_chain={"a": 0.5, "b": 0.5},
    )


def main() -> int:
    geometry = build()
    print("uniform q = 0.5 on both chains")
    print(f"depth-inverted chain present: {_inverted(geometry)}")
    print()

    print("every legal singleton as a victim set (need = 1):")
    rows = []
    for block_id in sorted(geometry.blocks):
        loss = _loss(geometry, (block_id,))
        members = " + ".join(
            f"{m.chain}@{m.depth}" for m in geometry.blocks[block_id].memberships
        )
        rows.append((loss, block_id, members))
    for loss, block_id, members in sorted(rows):
        print(f"  block {block_id:>2}  [{members:<16}]  L = {loss:.4f}")

    values = {round(loss, 12) for loss, _, _ in rows}
    print()
    print(f"distinct loss values: {sorted(values)}")
    print(f"all legal sets cost the same: {len(values) == 1}")

    native = native_lru_order(geometry)[:1]
    aware = select_victims(geometry, 1).blocks
    best = min(rows)[0]
    print()
    print(f"native picks {native}, L = {_loss(geometry, native):.4f}")
    print(f"cost-aware picks {aware}, L = {_loss(geometry, aware):.4f}")
    print(f"optimal L = {best:.4f}")
    print(f"native already optimal: {abs(_loss(geometry, native) - best) < 1e-12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
