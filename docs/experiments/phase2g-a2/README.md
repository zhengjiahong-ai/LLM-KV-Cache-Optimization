# Phase 2G · A2 Block-level Mechanism Study

**Scope: offline mechanism study only.** No native policy implemented, no native
experiment run. Every number here is selection-level evidence.

Comparison: **A0** = Continuum entry release + native LRU versus **A2** = the same
entry release + cost-aware block selection. Entry release is held fixed, and both
rules choose from the *same* legal candidate set.

---

## 1. Headline result

**On the recorded corpus the two rules never pick a different block set, and the
expected loss is identical in all 120 decisions.**

```text
decisions analysed                                  120
  decisions with >=2 chains                          39
  order differs                                      33
  set differs                                         0   <-- no block-level choice at all
  expected loss tied                                120
  cost-aware lower / higher expected loss          0 / 0
mean / median expected-loss delta                  0.00
```

Order differs in 33 decisions while the set never does. That is exactly the trap
M1 flagged for A1: **different order is not a different decision outcome.** Under a
linear token metric, reordering the same victim set changes nothing.

---

## 2. Why there is no decision space here (measured, not assumed)

Two independent causes, both measured.

### 2.1 Inside a chain, native LRU is already depth-ordered

Depth is reconstructed by reading a candidate's `block_ids` as ascending prefix
depth. That reading is verified against the recorded ranks:

```text
entries with >=3 queue-visible blocks               294
  native rank strictly DECREASING as index increases 294  = 100.0%
  strictly increasing / neither                      0 / 0
```

So deeper blocks always have smaller `native_lru_rank`: **native LRU already evicts
deepest-first within a chain.** A defect here would have made every A2 comparison
meaningless, so it is asserted (`scripts/probes/a2_block_geometry.py --strict`).

Additionally, `87/87` decisions expose every candidate block in
`original_free_queue`, so the legal candidate set itself is fully reconstructible.

### 2.2 Across chains, the reuse proxy never disagrees with recency

The only remaining freedom is *which chain to drain*. That requires `q_c` to
reorder chains relative to native rank order:

```text
decisions with >1 distinct q among chains            39
  of those, native's coldest chain != cheapest chain   0
```

In every one of the 39 decisions the chain that native drains first is also the
chain with the lowest reuse proxy. The two orderings are perfectly aligned, so the
cost-aware rule has nothing to exploit.

**This is a corpus property, not a claim about block-level optima in general.**
The same caveat that applies to the H1 range limits applies here: on H1, deadlines
and LRU recency are both driven by the same agent ordering, so they cannot diverge.

---

## 3. What a real decision space would require (controlled scenarios)

Since the corpus cannot exhibit divergence, four hand-built scenarios define the
conditions. Each is scored by the same expected-loss function for both rules.

| Scenario | Native | Cost-aware | Set differs | Expected loss (native / aware) |
|---|---|---|---|---|
| `q_reorders_chains` | drains A | drains B | yes | **1.8 / 0.2** |
| `equal_q_degenerate` | drains A | drains A | no | 1.0 / 1.0 |
| `q_wrong` | drains A | drains B | yes | 1.8 / 0.2 (estimate); **0.0 / 2.0 realised** |
| `single_chain_no_freedom` | A@6..A@3 | A@6..A@3 | no | 3.6 / 3.6 |

**Positive example (`q_reorders_chains`).** Chain A holds the coldest blocks
(`q_A = 0.9`), chain B is unlikely to return (`q_B = 0.1`), and the target is two
blocks. Native takes A's two coldest, `j_A = 3`, expected loss `0.9 × 2 = 1.8`.
Cost-aware takes B's two deepest, `j_B = 3`, expected loss `0.1 × 2 = 0.2`.
Same target, nine times lower expected recomputation. The gain comes entirely from
`q_c`, not from block geometry.

**Degenerate case (`equal_q_degenerate`).** With `q_A = q_B` both rules cost the
same. The token metric is linear, so concentration and dispersion are equivalent at
equal `q` — this is the design document's §3.5.2 result reappearing as a scenario.

**Failure case (`q_wrong`).** The geometry and therefore the *choice* are identical
to the positive case; only the ground truth differs. B is the chain that actually
returns, so cost-aware's realised loss is `2.0` against native's `0.0`. The rule
cannot tell a correct `q` from a lucky one, which is why `q` reliability has to be
measured rather than assumed. This is the realistic downside risk.

**Vacuous case (`single_chain_no_freedom`).** One legal chain means no freedom, and
"no divergence" here says nothing about the rule.

---

## 4. Minimal interface gap for an A2 native opt-in

The current adapter is:

```text
EvictionCandidate = {block_id, ref_cnt, has_block_hash, lru_rank}
EvictionContext   = {required_blocks, free_blocks, total_blocks, timestamp}
```

`Delta(b) = q_c · B · max(0, j_c − d_c(b))` needs three things the interface does
not carry:

| Needed | Present? | Note |
|---|---|---|
| `depth` of the block on its chain | ❌ | Not derivable from `lru_rank` alone in general; it happens to coincide within a chain on H1, but only because rank is depth-ordered there |
| `chain` membership of the block | ❌ | Required to evaluate `j_c` and to look up `q_c` |
| `q_c` per chain (reuse proxy) | ❌ | Lives in the Continuum retention state, not in `EvictionContext` |
| block token size `B` | ✅ | Engine `block_size`, constant |
| legal candidate set | ✅ | Caller already restricts to `E(R)` |

Minimum change: attach an opaque **chain identity** and its **depth** to each
candidate, plus a way to look up the chain's current reuse proxy. Nothing about
eviction, ref-counting, hashing or LRU needs to change. Depth and chain identity
are **derivable inside the engine** (a block's position in a request prefix), which
is why this is an exposure gap rather than a missing-information gap — unlike the
offline path, where they must be reconstructed from `block_ids` order.

---

## 5. Recommendation

**Do not authorise A2 native implementation on the current evidence.** Block-level
selection has no measurable value on the only corpus available: the two signal
sources it depends on (`q_c` order and native rank order) are perfectly aligned, so
the rule cannot differ from native LRU.

A2 would become worth implementing only after a corpus is shown where
`q_c`-order and rank-order **disagree** on a non-trivial fraction of decisions.
That is a corpus requirement, and it can be checked cheaply and offline before any
native work. Concretely, the gate is:

```text
share of multi-chain decisions where cheapest-q chain != coldest-rank chain  > 0
```

On the current corpus that share is `0 / 39`.

This is not a judgement that block-level optimisation has no headroom. It is the
narrower, measured statement that **this corpus cannot express the difference.**

---

## 6. Reproduce

```bash
# geometry feasibility (needs an artifact root)
python scripts/probes/a2_block_geometry.py <runs-dir> --strict

# real-corpus divergence study
PYTHONPATH=src python -m kvopt.costaware.a2_compare --corpus <runs-dir> --json out.json

# controlled scenarios and unit tests
python -m pytest tests/test_costaware_a2_mechanism.py -q
```
