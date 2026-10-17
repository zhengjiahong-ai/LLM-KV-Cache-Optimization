"""Verify the two cost-metric claims in section 3.5 of the joint design document.

C1. "C(r)/r decreasing" implies SUBADDITIVITY, and the proof in 3.5.1 holds
    numerically. It does NOT imply concavity: C2 exhibits a function whose
    average cost strictly decreases while one increment rises.
C3. Under the token metric the loss is linear per chain, so at equal q
    concentrating the damage and spreading it are exactly equal in tokens.
    Hence the token metric supplies no argument for concentration at all, and
    the only discriminating signal is q.
"""

from __future__ import annotations


def check_subadditive() -> None:
    print("=== C1: decreasing average cost => subadditive ===")
    # increments chosen so each new increment stays below the running average,
    # which is exactly the condition for the average to keep falling.
    increments = [100.0, 1.0, 1.5, 2.0]
    c = [0.0]
    for d in increments:
        c.append(c[-1] + d)
    print("C(r)      :", [round(c[r], 3) for r in range(1, 5)])
    print("C(r)/r    :", [round(c[r] / r, 3) for r in range(1, 5)])

    avg = [c[r] / r for r in range(1, 5)]
    assert all(avg[i] >= avg[i + 1] - 1e-12 for i in range(len(avg) - 1)), \
        "average must be non-increasing"

    violations = []
    for r1 in range(1, 5):
        for r2 in range(1, 5):
            s = r1 + r2
            if s <= 4 and c[r1] + c[r2] < c[s] - 1e-12:
                violations.append((r1, r2, c[r1] + c[r2], c[s]))
    print("subadditivity violations:", violations)
    assert not violations
    print("  -> C(r1)+C(r2) >= C(r1+r2) holds for every pair in range")

    print("\n=== C2: decreasing average does NOT imply concavity ===")
    print("increments:", increments)
    concave = all(
        increments[i] >= increments[i + 1] - 1e-12
        for i in range(len(increments) - 1)
    )
    print("increments non-increasing (concavity on integers)?", concave)
    assert not concave, "need a non-concave counterexample"
    print("  -> average strictly decreases while an increment rises: non-concave")
    print("     so 'C(r)/r decreasing => C concave' is invalid")


def _chain_loss(m: int, k: int, q: float, b: float = 1.0) -> float:
    """Evicting the k deepest blocks of an m-block chain."""
    if k == 0:
        return 0.0
    j = m - k + 1
    return q * (m - j + 1) * b


def check_token_linearity() -> None:
    print("\n=== C3: token metric is linear per chain; equal q ties===")
    m_alpha, m_beta, d, q = 12, 6, 4, 0.5

    concentrated = _chain_loss(m_alpha, d, q) + _chain_loss(m_beta, 0, q)
    spread = _chain_loss(m_alpha, 2, q) + _chain_loss(m_beta, 2, q)
    print(f"concentrate {d} in alpha      : {concentrated:.3f}B")
    print(f"spread 2 + 2 across chains  : {spread:.3f}B")
    assert abs(concentrated - spread) < 1e-12, (concentrated, spread)
    print("  -> exactly equal at equal q; no nonlinearity can separate them")

    qa, qb = 0.9, 0.3
    hot = _chain_loss(m_alpha, d, qa) + _chain_loss(m_beta, 0, qa)
    mix = _chain_loss(m_alpha, 2, qa) + _chain_loss(m_beta, 2, qb)
    print(f"unequal q: concentrate in hot alpha = {hot:.3f}B, spread = {mix:.3f}B")
    assert mix < hot, "only q can discriminate"
    print("  -> the discriminating signal is q, not the shape of C(r)")


def main() -> int:
    check_subadditive()
    check_token_linearity()
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
