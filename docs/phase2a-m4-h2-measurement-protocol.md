# Phase 2A M4 — H2 Measurement Protocol

Status: **PROPOSED / criteria frozen on approval** (M1 ruling item 1, 2026-10-07)
Executor: M6 (compliant Metal runtime)
Owner of the protocol: M4
Scope: **measurement only** — no policy, no retention implementation, no score

---

## 0. Purpose and boundary

H2 exists to decide whether the block-level path (B1) is worth designing. M1
authorized it as a **measurement / mechanism probe only** and kept B1
**lock-in place**:

```text
B1 = DESIGN PATH PRESERVED / IMPLEMENTATION LOCKED
```

H2 explicitly does **not** authorize:

```text
B1 runtime policy
partial-prefix retention implementation
a new block victim score
any change to BlockPool ownership
```

**The comparison shape is frozen before measurement; the numeric thresholds are
not.** Each condition is stated as PASS / FAIL / INCONCLUSIVE so a negative
outcome is reportable rather than reinterpreted, and `INCONCLUSIVE` is never
treated as a weak yes.

```text
frozen now   : the shape of every comparison, the controls, the grid design,
               the observation priority, and the requirement that tolerances
               come from measured jitter
NOT frozen   : the exact pass thresholds (a fraction, an R^2-style improvement,
               a confidence level). These are frozen by M6 + M4 AFTER the
               measurable resolution is known and BEFORE any verdict is read.
```

Rationale, from the M1 ruling: a threshold proposed by M4 with no basis in
measurement resolution is not a frozen criterion, it is a placeholder. Freezing a
round number in advance is how an unfalsifiable criterion gets written.

---

## 1. Why this probe exists at all

The block-level route rests on two structural claims and one empirical claim:

**Structural (no measurement needed):**

```text
vLLM APC reuse requires a prefix cached contiguously from position 0.
Evicting LEADING blocks breaks contiguity and invalidates everything behind them.
Evicting TRAILING blocks only shortens the cached interval.
```

⇒ the loss caused by evicting a block is a function of its **position within the
prefix**, which a request-level `single cost × block count` score cannot express.

**Empirical (this is what H2 measures):** the curvature of the real `C(r)` curve,
without which the position term can vanish (§3, M1).

---

## 2. The four unlock conditions

B1 becomes eligible for a method-design request only if **all four** return PASS.
Any FAIL ⇒ B1 remains closed. Any INCONCLUSIVE ⇒ B1 remains closed.

| # | Condition | Verdict required |
| --- | --- | --- |
| M1 | Real `C(r)` is meaningfully non-linear in the service range | PASS |
| M2 | Partial-prefix APC behaves as "keep leading contiguous prefix, recompute suffix only" | PASS |
| M3 | Block position (leading vs trailing) changes the **realized** recompute outcome | PASS |
| M4 | Block-level choice has headroom that entry-level ordering cannot express | PASS |

Each PASS requires its condition's **threshold to have been frozen first** from
the measured resolution (§3.2, §5.2, §6.2). A verdict read before its threshold is
frozen is not a verdict.

M2's controls are already fully specified and need no threshold calibration, so
it is the only condition that can be judged immediately.

---

## 3. M1 — real `C(r)` curve

### 3.1 What to measure

`C(r)` = realized prefill/reload cost for a reusable-prefix span of `r` tokens,
over a grid that must **include the long-context region**.

```text
required grid: r in {16, 32, 64, 128, 256, 512, 1024, 2048,
                     4096, 8192, 12288, 16384, 20480, 24576}
             + at least 3 points above 24576 if the model context allows
```

⚠️ **The current profile grid is `(16, 32, 128, 256, 512)` — three to four
orders of magnitude below the predicted curvature onset.** Measuring again on the
same short grid cannot answer this question. The predicted cross-over for
Qwen2.5-0.5B (`P ≈ 0.5B`, `d = 896`, `L = 24`) is `N* ≈ 23k` tokens, where the
`2N²dL` attention term catches the `2NP` linear term.

#### Observation priority (M1 ruling)

`TTFT_MISS − TTFT_HIT` is a **contaminated** estimator: it folds admission,
queueing and scheduling into a quantity meant to represent prefill work. The
preference order is therefore:

```text
1  isolated native prefill/reload elapsed time            <- preferred, if directly observable
2  controlled TTFT miss/hit delta                          <- fallback, with contamination controlled
```

If TTFT deltas are used, the report **must** state that admission / queue state
was held equivalent across the miss and hit measurements, or else label the
result **sensitivity only**. A TTFT delta measured with uncontrolled queueing
cannot be the primary input to the M1 verdict.

### 3.2 Verdict shape (frozen) — thresholds NOT yet frozen

**The protocol is frozen; the numeric thresholds are not.** The boundary values
below were proposed by M4 and have **no** basis in measurement resolution or
jitter, so they cannot be called frozen. M1 requires:

```text
shape / comparison protocol   : frozen now (this document)
exact pass thresholds         : frozen AFTER M6 confirms the grid and the
                                measurable resolution, and DERIVED from the
                                measured baseline jitter
```

Fit three nested models to the measured curve by least squares over the grid:

```text
L0  linear, no intercept      C(r) = beta * r
L1  affine                    C(r) = a + beta * r
L2  quadratic                 C(r) = a + beta * r + gamma * r^2
```

The **shape** of the decision, frozen now:

```text
PASS         L2 fits the measured curve materially better than L1 on the
             long-context region AND its convexity term is positive and
             distinguishable from zero at the frozen confidence level

FAIL         L0 or L1 is adequate across the whole grid: convexity is either
             absent or below the resolution the measurement can support

INCONCLUSIVE the grid does not span a region where the fit is interpretable,
             or the jitter is large enough to swamp the improvement
```

TBD before measurement by M6 + M4 together:

- the material-improvement statistic and its critical value, expressed in the
  measured resolution rather than a round number such as `R^2 >= 0.02`;
- the confidence level and resampling scheme for `gamma`;
- the exact per-point repeat count that makes the jitter small enough to resolve
  the effect.

⚠️ A round threshold chosen in advance is how an unfalsifiable criterion gets
written. The number must come **from** the measurement's resolution, not be
compared against it.

If **FAIL**, the practical consequence is recorded as: block-level cost structure
collapses to `Δk = βB` for every `k` (design draft §4 property 2), i.e. the model
degenerates to native LRU at block level. **That is a publishable negative result
and B1 stays closed.**

### 3.3 Required reporting

- the raw grid points, with per-point repeat count and dispersion;
- all three fitted models with coefficients and `R²`;
- the bootstrap interval for `gamma`;
- the measured jitter, because it sets the resolution floor for the comparison.

---

## 4. M2 — partial-prefix APC semantics

### 4.1 What to measure

For one prefix of `n` blocks of `B` tokens, with the **leading** contiguous region
retained and a **trailing** region evicted, measure whether the next request that
needs the full prefix:

```text
hits the retained leading region (partial APC hit)
recomputes only the evicted suffix
```

⚠️ **This must not be inferred from logical prefix identity.** The design draft
states it is a backend behaviour assertion. M1 restated it: "Do not infer this
from logical prefix identity alone."

### 4.2 Frozen verdict rule

Construct `k` variants of the same prefix: retain blocks `1..k`, evict `k+1..n`,
for at least three values of `k` spanning the prefix.

```text
PASS         for each k, the measured recomputed token count equals the evicted
             suffix length (n - k) * B within a pre-declared tolerance, and the
             measured cached-prefix token count equals k * B
             Tolerance is derived from measurement jitter, not chosen by hand.

FAIL         recomputed tokens equal the FULL prefix length for some k
             (i.e. eviction of trailing blocks invalidates the leading region), or
             the cached amount does not scale with k at all

INCONCLUSIVE the observation seam cannot distinguish hit from miss for a partial
             prefix, or the retained range cannot be controlled precisely enough
```

**If FAIL, the entire position-dependence argument collapses**: if trailing
eviction invalidates the whole prefix, then position carries no information and
B1 has no mechanism. This is the single highest-risk result for the block-level
route.

### 4.3 Sanity controls

- a **full-retain** control (`k = n`) must show a full hit;
- a **full-evict** control (`k = 0`) must show a full miss;
- a **re-request without any eviction** must show a full hit.

If any control fails, the probe is `INCONCLUSIVE` — not `FAIL` — because the
instrument is then unvalidated.

---

## 5. M3 — position changes the realized outcome

### 5.1 What to measure

For the same **number** of evicted blocks, compare realized recompute at two
positions:

```text
trailing eviction  (blocks n-j+1 .. n)
leading eviction   (blocks 1 .. j)
```

### 5.2 Verdict shape (frozen) — thresholds NOT yet frozen

```text
PASS         leading eviction costs strictly more realized recompute than
             trailing eviction, for the same j, in a majority of the tested
             (prefix, j) combinations, with the difference exceeding the
             measured jitter

FAIL         the two are indistinguishable within jitter across the tested
             combinations

INCONCLUSIVE results are directionally mixed without a clean majority, or the
             jitter exceeds the effect
```

⚠️ **The "majority" threshold is deliberately not a number here.** An earlier
draft used `>= 2/3`, borrowing the family-agreement convention, but that value
was M4's invention and has no basis in this measurement's resolution. The exact
fraction is frozen by M6 + M4 **before** measurement, once the jitter is known,
and must be justified by the number of combinations that the jitter allows to be
resolved at all.

---

## 6. M4 — headroom beyond entry-level ordering

### 6.1 What to measure

The question is whether a block-level choice can express something an
entry-level ordering cannot. Concretely: within a single prefix, the entry-level
model can only choose **how many** blocks to release (or rank entries by a scalar);
the block-level model can choose **which positions**.

```text
Best entry-level achievable loss  (releasing j blocks from the entry)
Best block-level achievable loss  (choosing which j blocks)
```

### 6.2 Verdict shape (frozen) — thresholds NOT yet frozen

```text
PASS         for a majority of tested (prefix, j) combinations,
             best_block_level_loss < best_entry_level_loss,
             with the gap exceeding the measured jitter

FAIL         the two coincide within jitter for every combination tested
             (position carries no exploitable information at block level
              given the current per-entry aggregation)

INCONCLUSIVE the cross-entry aggregation question (design draft §9.3) is
             undefined, so the comparison cannot be stated fairly
```

⚠️ Same caveat as §5.2: the majority fraction is M4's proposal, not an approved
number, and is frozen from the measured resolution before measurement.

⚠️ **Known open dependency**: comparing a large prefix's 3-block suffix against a
complete small prefix is not yet well-defined (design draft §9.3). If M4 cannot
be stated fairly, it must return `INCONCLUSIVE`, and B1 stays closed. **Do not
invent an aggregation just to make the comparison possible.**

---

## 7. Verdict and consequence

```text
ALL FOUR PASS
   -> M4 may request B1 method-design authorization
   -> still NOT runtime implementation
   -> and M2 must first complete the block-level / partial-prefix novelty audit

ANY FAIL or INCONCLUSIVE
   -> B1 remains closed
   -> the negative result is recorded as the answer
```

```text
B1 method-design request  !=  B1 implementation authorization
```

---

## 8. Instrumentation

| Item | Requirement |
| --- | --- |
| Runtime | Compliant Metal, same backend family as the frozen campaign |
| Observation | Raw native facts only (request identity, token counts, measured TTFT); no derived semantics on the runtime side |
| Repeated measurement | **≥ 3 repeats per grid point** so jitter is measurable and sets the tolerance floor |
| Provenance | Run id, model revision, tokenizer revision, and clean git sha recorded per point |
| Sealing | The `C(r)` grid and the `k` / `j` values are fixed **before** measurement, so the verdict cannot be steered by dropping points |

Tolerances must be **derived from the measured jitter** and reported, never
chosen by hand — the same discipline the acceptance protocol applies to
`epsilon_latency`.

---

## 9. Traceability

| Statement | Source |
| --- | --- |
| H2 approved as measurement / mechanism probe only | M1 ruling, item 1 |
| B1 remains locked; H2 is its unlock condition | M1 ruling, item 6 |
| Four unlock conditions | M1 ruling, item 6 |
| Novelty audit by M2 after positive H2 | M1 ruling, item 6 |
| Request B1 *method-design*, not implementation | M1 ruling, item 6 |
| Do not infer APC behaviour from prefix identity | M1 ruling, item 4 / input §11 Q2 |
| Raw native facts only; derived semantics offline | M1 ruling, item 2 |
| APC contiguity argument and cost model | `docs/phase2a-m4-block-level-design-draft.md` §3, §4 |
| Predicted curvature onset `N* ≈ 23k` | same, §2.2 |
| Current grid is `(16, 32, 128, 256, 512)` | `docs/experiments/phase1b-continuum/final-report.md` §3 |
| Open aggregation question | `docs/phase2a-m4-method-design-input.md` §11 Q3 |
| `2/3` threshold convention | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| Never hand-pick a tolerance | M1 ruling, item 4 |
