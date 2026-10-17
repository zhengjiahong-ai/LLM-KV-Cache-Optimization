"""Back section 3.3.4.2: the two-entry lookahead used when every N_i is zero.

Zero marginal happens when several entries jointly protect the same blocks: with
O(b) = {i, j}, releasing either alone unlocks nothing, so
N_i = |E(R u {i})| - |E(R)| = 0 and Rhat_i / N_i is undefined rather than infinite.

This probe checks the stated fallback chain on three hand-built cases:

  case 1  every N_i = 0, but one PAIR unlocks blocks  -> that pair is chosen
  case 2  no pair unlocks anything (three-way sharing) -> deadline fallback
  case 3  the union weight tilde_q stays below 1, unlike q_i + q_j

Run: python scripts/probes/probe_zero_marginal.py
"""

from __future__ import annotations

from itertools import combinations

B = 1.0


def eligible(owners: dict[int, set[str]], released: set[str]) -> set[int]:
    """Blocks with no still-protected owner, matching the frozen semantics."""
    return {bid for bid, own in owners.items() if not (own - released)}


def relief(owners: dict[int, set[str]], released: set[str], key: str) -> int:
    before = eligible(owners, released)
    after = eligible(owners, released | {key})
    return len(after) - len(before)


def joint_relief(owners: dict[int, set[str]], released: set[str], keys: tuple[str, ...]) -> int:
    before = eligible(owners, released)
    after = eligible(owners, released | set(keys))
    return len(after) - len(before)


def union_weight(qs: list[float]) -> float:
    """P(at least one of them returns), so the shared prefix is charged once."""
    product = 1.0
    for q in qs:
        product *= 1.0 - q
    return 1.0 - product


def pair_score(
    owners: dict[int, set[str]],
    released: set[str],
    pair: tuple[str, str],
    q_of: dict[str, float],
    required: int,
    lam: float,
) -> tuple[float, float]:
    n_ij = joint_relief(owners, released, pair)
    if n_ij <= 0:
        return (float("inf"), 0.0)
    q_tilde = union_weight([q_of[k] for k in pair])
    bracket = min(required, n_ij) + lam * max(0, n_ij - min(required, n_ij))
    cost = q_tilde * B * bracket
    return (cost / n_ij, cost)


def main() -> int:
    required, lam = 4, 0.5

    # ---------------- case 1: two-way sharing, pair unlocks ----------------
    owners_1 = {11: {"i", "j"}, 12: {"i", "j"}, 13: {"i", "j"}, 14: {"i", "j"}}
    released: set[str] = set()
    q_of_1 = {"i": 0.8, "j": 0.55}

    n_i = relief(owners_1, released, "i")
    n_j = relief(owners_1, released, "j")
    print("=== case 1: two-way sharing ===")
    print(f"  N_i = {n_i}   N_j = {n_j}   (both zero => Rhat/N is undefined)")
    assert (n_i, n_j) == (0, 0)

    usable = [
        (pair, *pair_score(owners_1, released, pair, q_of_1, required, lam))
        for pair in combinations(sorted(q_of_1), 2)
    ]
    usable = [u for u in usable if u[1] != float("inf")]
    print(f"  pairs with N_ij > 0 : {[(p, round(n, 3)) for p, n, _ in usable]}")
    assert len(usable) == 1, "only the single pair can unlock anything"

    (pair, per_unit, cost) = usable[0]
    q_tilde = union_weight([q_of_1[k] for k in pair])
    print(f"  selected pair       : {pair}")
    print(f"  N_ij = {joint_relief(owners_1, released, pair)}"
          f"  q_tilde = {q_tilde:.3f}  cost = {cost:.3f}B  per-unit = {per_unit:.3f}B")
    assert joint_relief(owners_1, released, pair) == 4
    assert abs(cost - q_tilde * 1.0 * 4) < 1e-9

    after = eligible(owners_1, released | set(pair))
    print(f"  |E(R u pair)| = {len(after)} >= required = {required}")
    assert len(after) >= required

    # ---------------- case 2: three-way sharing, no pair suffices ----------
    owners_2 = {21: {"i", "j", "k"}, 22: {"i", "j", "k"}}
    released_2: set[str] = set()
    q_of_2 = {"i": 0.8, "j": 0.7, "k": 0.6}
    print("\n=== case 2: three-way sharing, no pair unlocks anything ===")
    singles = {k: relief(owners_2, released_2, k) for k in q_of_2}
    pairs = {
        p: joint_relief(owners_2, released_2, p) for p in combinations(sorted(q_of_2), 2)
    }
    print(f"  single reliefs : {singles}")
    print(f"  pair reliefs   : {pairs}")
    assert all(v == 0 for v in singles.values())
    assert all(v == 0 for v in pairs.values())
    print("  -> no pair has N_ij > 0, so the fallback is deadline-ascending release")
    fallback = sorted(q_of_2, key=lambda k: -q_of_2[k])  # higher q = later deadline
    print(f"  -> deadline order (q descending) = {fallback}")
    assert fallback == ["i", "j", "k"]

    # releasing all of them does reach the upper bound, which is why progress holds
    everything = eligible(owners_2, set(q_of_2))
    print(f"  |E(release all)| = {len(everything)}  (upper bound reached)")
    assert len(everything) == len(owners_2)

    # ---------------- case 3: union weight stays a weight ------------------
    print("\n=== case 3: tilde_q is a union weight, not a sum ===")
    q_tilde_2 = union_weight([0.8, 0.7, 0.6])
    print(f"  q_i + q_j      = {0.8 + 0.7:.3f}  (> 1, not a probability)")
    print(f"  1-(1-.8)(1-.7) = {union_weight([0.8, 0.7]):.3f}")
    print(f"  1-(1-.8)(1-.7)(1-.6) = {q_tilde_2:.3f}")
    assert 0.0 < q_tilde_2 < 1.0
    assert union_weight([0.8, 0.7]) < 1.0 < 0.8 + 0.7

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
