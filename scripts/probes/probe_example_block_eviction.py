"""Reproduce every number asserted in section 5.2 of the joint design document.

Backs the block-layer rule ``Delta(b) = q_c * B * max(0, j_c - d)`` and compares
three rules on one scenario:

  chain alpha: m=12, legal depths 9..12, q=0.9  (hot)
  chain beta : m=6,  legal depths 1..6,  q=0.3  (cold)
  D = 4, B = 1

Also asserts the two properties the document relies on:

  * a block deeper than the current gap costs nothing (free block);
  * at equal q the new rule and the withdrawn WRR both score q * 4B, so no
    superiority may be claimed there.
"""

from __future__ import annotations

CHAINS = {
    "alpha": {"m": 12, "depths": list(range(9, 13)), "q": 0.9},
    "beta": {"m": 6, "depths": list(range(1, 7)), "q": 0.3},
}
D, B = 4, 1.0


def gap(evicted: list[int], m: int) -> int:
    return min(evicted) if evicted else m + 1


def loss(chain: str, evicted: list[int]) -> float:
    if not evicted:
        return 0.0
    j = min(evicted)
    return CHAINS[chain]["q"] * B * (CHAINS[chain]["m"] - j + 1)


def total(ev: dict[str, list[int]]) -> float:
    return sum(loss(ch, ev[ch]) for ch in CHAINS)


def delta(chain: str, depth: int, ev: dict[str, list[int]]) -> float:
    j = gap(ev[chain], CHAINS[chain]["m"])
    return CHAINS[chain]["q"] * B * max(0, j - depth)


def run_new_rule() -> tuple[dict[str, list[int]], float]:
    print("=== rule: new (per-block minimum marginal) ===")
    ev: dict[str, list[int]] = {ch: [] for ch in CHAINS}
    for step in range(1, D + 1):
        cands = sorted(
            (delta(ch, d, ev), ch, d)
            for ch, spec in CHAINS.items()
            for d in spec["depths"]
            if d not in ev[ch]
        )
        dv, ch, d = cands[0]
        ev[ch].append(d)
        label = "\u03b1" if ch == "alpha" else "\u03b2"
        print(f"  step {step}  {label}@{d}  delta={dv:.3f}"
              f"  j_alpha={gap(ev['alpha'], 12)}  j_beta={gap(ev['beta'], 6)}")
    value = total(ev)
    print(f"  expected loss = {value:.3f}B")
    return ev, value


def run_withdrawn_wrr() -> tuple[dict[str, list[int]], float]:
    print("\n=== rule: withdrawn WRR argmax q*rho ===")
    ev: dict[str, list[int]] = {ch: [] for ch in CHAINS}
    for step in range(1, D + 1):
        best = None
        for ch, spec in CHAINS.items():
            d_min = min(spec["depths"])
            s = len(ev[ch])
            rho = spec["m"] - (d_min + s - 1)
            score = spec["q"] * rho
            if best is None or score > best[0]:
                best = (score, ch, rho)
        score, ch, rho = best  # type: ignore[misc]
        remaining = [d for d in sorted(CHAINS[ch]["depths"], reverse=True)
                     if d not in ev[ch]]
        ev[ch].append(remaining[0])
        label = "\u03b1" if ch == "alpha" else "\u03b2"
        print(f"  step {step}  pick {label}  score={score:.2f}  rho={rho}")
    value = total(ev)
    print(f"  j_alpha={gap(ev['alpha'], 12)}  j_beta={gap(ev['beta'], 6)}")
    print(f"  expected loss = {value:.3f}B")
    return ev, value


def main() -> int:
    ev_new, loss_new = run_new_rule()
    assert abs(loss_new - 1.2) < 1e-9, loss_new
    assert ev_new["alpha"] == [], "new rule must leave the hot chain untouched"
    assert sorted(ev_new["beta"]) == [3, 4, 5, 6]

    _, loss_wrr = run_withdrawn_wrr()
    assert abs(loss_wrr - 3.0) < 1e-9, loss_wrr

    print("\n=== rule: native LRU, two regimes ===")
    # (a) lru agrees with q: the cold chain's blocks are the oldest
    loss_native_a = total({"alpha": [], "beta": [3, 4, 5, 6]})
    print(f"  (a) lru consistent with q -> beta tail : loss={loss_native_a:.3f}B")
    assert abs(loss_native_a - 1.2) < 1e-9
    # (b) lru diverges: alpha's blocks happen to be the oldest
    loss_native_b = total({"alpha": [9, 10, 11, 12], "beta": []})
    print(f"  (b) lru diverges from q   -> alpha tail: loss={loss_native_b:.3f}B")
    assert abs(loss_native_b - 3.6) < 1e-9

    assert abs(loss_native_a - loss_new) < 1e-12, "regime (a) ties with native"
    assert loss_new < loss_wrr < loss_native_b

    print("\n=== ordering in regime (b): new 1.2B < withdrawn 3.0B < native 3.6B ===")

    print("\n=== free-block property (deeper than the gap costs nothing) ===")
    probe = {"alpha": [9], "beta": []}
    for d in (10, 11, 12):
        value = delta("alpha", d, probe)
        print(f"  alpha@{d} with gap at 9: delta = {value:.3f}")
        assert value == 0.0
    value = delta("alpha", 8, probe)
    print(f"  alpha@8 with gap at 9: delta = {value:.3f}  (>0, extends the gap)")
    assert value > 0

    print("\n=== symmetry: equal q removes any advantage ===")
    saved = CHAINS["beta"]["q"]
    CHAINS["beta"]["q"] = 0.9
    ev: dict[str, list[int]] = {ch: [] for ch in CHAINS}
    for _ in range(D):
        cands = sorted(
            (delta(ch, d, ev), ch, d)
            for ch, spec in CHAINS.items()
            for d in spec["depths"]
            if d not in ev[ch]
        )
        _, ch, d = cands[0]
        ev[ch].append(d)
    value = total(ev)
    CHAINS["beta"]["q"] = saved
    print(f"  with q equal, loss = {value:.3f}B (= 4B*q, draining either chain)")
    assert abs(value - 3.6) < 1e-9

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
