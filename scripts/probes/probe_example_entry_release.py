"""Reproduce every number asserted in section 5.1 of the joint design document.

Backs the example-entry-release rule: ``Rhat_i = q_i * B * [min(D, N_i)
+ lambda * (N_i - min(D, N_i))^+]``.

Layout: shared root p1..p8 owned by {A, B}; A tail p9..p16 (m_A = 16);
B tail p17..p18 (m_B = 10). ``required_blocks D = 2``.

Verifies:
  N_A, N_B                     relief from releasing each entry
  single-event recompute       both 2B, so one decision cannot separate them
  residual exposure            6 vs 0
  cost under lambda = 0.5      2.5B vs 1.8B -> B selected
  break-even lambda            0.2666..., i.e. 0.2 recurring 6
  withdrawn old key            share ascending would have picked A
"""

from __future__ import annotations

B = 1.0  # per-block token count; kept at 1.0 so totals read in units of B
D = 2  # required_blocks

m_A, m_B = 16, 10
tail_A, tail_B = 8, 2


def recompute(m: int, n_evicted: int) -> float:
    """Evicting the n deepest blocks of an m-block chain: j = m - n + 1."""
    j = m - n_evicted + 1
    return (m - j + 1) * B


def cost(q: float, n: int, required: int, lam: float) -> float:
    return q * (min(required, n) + lam * max(0, n - min(required, n)))


def main() -> int:
    # ---- 1. relief -----------------------------------------------------
    e_empty = 0
    n_A, n_B = tail_A - e_empty, tail_B - e_empty
    print(f"N_A = {n_A}   N_B = {n_B}   D = {D}")
    assert (n_A, n_B) == (8, 2)
    assert n_A >= D and n_B >= D, "both must be single-step sufficient"

    # ---- 2. single-event damage ----------------------------------------
    k_A, k_B = min(D, n_A), min(D, n_B)
    print(f"single-event recompute: A={recompute(m_A, k_A)}B  B={recompute(m_B, k_B)}B")
    assert recompute(m_A, k_A) == recompute(m_B, k_B) == 2.0

    # ---- 3. residual exposure ------------------------------------------
    res_A, res_B = n_A - k_A, n_B - k_B
    print(f"residual exposure:     A={res_A}B  B={res_B}B")
    assert (res_A, res_B) == (6, 0)

    # ---- 4. cost model --------------------------------------------------
    q_A, q_B, lam = 0.5, 0.9, 0.5
    c_A, c_B = cost(q_A, n_A, D, lam), cost(q_B, n_B, D, lam)
    print(f"cost at lambda=0.5:    A={c_A}B  B={c_B}B  -> chooses "
          f"{'A' if c_A < c_B else 'B'}")
    assert abs(c_A - 2.5) < 1e-9 and abs(c_B - 1.8) < 1e-9
    assert c_B < c_A, "the example must select B"

    # ---- 5. break-even lambda -------------------------------------------
    break_even = (q_B * min(D, n_B) - q_A * min(D, n_A)) / (q_A * res_A)
    print(f"break-even lambda = {break_even:.6f}  (= 0.2 recurring 6)")
    assert abs(break_even - 8 / 30) < 1e-12
    for lam_probe in (0.0, 0.30):
        print(f"  lambda={lam_probe:.2f} -> A: {cost(q_A, n_A, D, lam_probe):.2f}B"
              f" vs B: {cost(q_B, n_B, D, lam_probe):.2f}B")

    # ---- 6. the withdrawn key picked A (RC2 erratum) --------------------
    share_A = 8 / 16  # 8 of A's 16 blocks stay protected by B
    share_B = 8 / 10  # 8 of B's 10 blocks stay protected by A
    winner = "A" if share_A < share_B else "B"
    print(f"withdrawn share key: share_A={share_A:.2f} share_B={share_B:.2f}"
          f" ascending -> {winner}")
    assert share_A < share_B, "old key selects A, contradicting the old claim of B"

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
