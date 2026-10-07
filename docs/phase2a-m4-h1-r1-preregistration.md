# Phase 2A M4 — H1-R1 Preregistration: reverse retention-deadline ordering

Status: **PREREGISTERED / POST-HOC DISCOVERY HYPOTHESIS**
Rule id: `H1_R1_reverse_deadline`
Frozen: `2026-10-07`, anchored to `72c462b`
Authority: M1 ruling 2026-10-07, item 3

```text
可以正式进入 H1
但它目前只能叫 POST-HOC DISCOVERY HYPOTHESIS，不能叫结果
```

The hypothesis was found *after* the canonical campaign was analysed. It is
therefore a **hypothesis**, and every number below is **motivation**, never an
effectiveness result. It may only be judged on a new independent holdout.

---

## 1. Hypothesis

```text
Releasing the candidate with the LATEST retention deadline first
reduces realized canonical loss relative to the frozen ordering,
which releases the EARLIEST deadline first.
```

---

## 2. Frozen specification

Registered in code as `PREREGISTERED_H1_RULES` (`src/kvopt/costaware/rules.py`)
and as a frozen record in `PREREGISTRATIONS`
(`src/kvopt/costaware/preregistrations.py`).

| Element | Frozen value |
| --- | --- |
| **Formula** | Release the candidate with the **largest** `retention_deadline_timestamp` first: descending on `retention_deadline_timestamp`, equivalently negating the frozen Phase 1B **primary** key |
| **Direction** | Descending on `retention_deadline_timestamp` |
| **Tie-break** | Stable logical identity `(program_id, prefix_id)`, applied by the standard rule ladder |
| **Fallback** | The frozen baseline ordering; never a fabricated value |
| **Primary metric** | `cluster_mean_proxy_loss` (Level A) |
| **Boundary** | Forced-release candidate sets of ≥ 2 logical retention entries, under the frozen TTL estimator |

### 2.1 Two exactness caveats, stated rather than implied

⚠️ **It negates the primary term only.** The frozen Phase 1B key is

```text
(deadline, min native rank over newly eligible, identity)
```

The middle term is *dynamic* — recomputed against the currently released set — so
no static candidate key can negate the whole key. This rule negates the
**primary** (`deadline`) term and inherits the ladder's identity tie-break. It is
therefore not a literal reversal of the frozen loop.

⚠️ **The tie-break is untested.** Deadlines are tied in **0 of 60** discovery
decisions (each decision's deadline values are distinct — see §4.1), so the
identity tie-break never fires on the discovery data. Its behaviour is defined
but unexercised.

---

## 3. Motivation (not results)

Measured on the canonical campaign. **These numbers may not be cited as
effectiveness evidence** — they are why the hypothesis is worth testing, nothing
more.

| View | Baseline | H1-R1 |
| --- | ---: | ---: |
| Cluster-level paired, better / worse / tied | — | **24 / 15 / 21** |
| Mean paired loss delta | — | **+0.014797 s** |
| Cluster-level paired (20 clusters) | — | 8 / 5 / 7 |
| Feasible-oracle mean absolute regret | 0.041225 | **0.026428** |
| Feasible zero-regret rate | 0.600 | **0.750** |
| Mean entry count delta vs oracle | +0.15 | **+0.00** |
| Canonical mean normalized regret | 0.368820 | **0.154498** |
| Canonical misselection rate | 0.4444 | **0.625 (worse)** |

Per-family mean loss delta: F1 −0.0223, **F2 +0.0238 (worse)**, F3 −0.0166,
F4 −0.0362, F5 −0.0166, F6 −0.0140 → **5 of 6 families improve**.

Three honest observations about this table:

1. **15 of 60 decisions regress.** It is not a clean win.
2. **The two comparators disagree in direction.** The canonical size-matched
   comparator calls it *worse* (misselection 0.625 vs 0.4444) while the
   feasibility-aware comparator calls it much better. This is exactly the
   divergence the report already documented for the marginal-denominator rule,
   and it is unresolved here too.
3. **The effect is not a monotone ranking effect.** Within-decision
   `spearman(deadline, loss)` averages **−0.005** (15 positive, 24 negative,
   n=39). The gain lives in the extremes of the candidate set, not in a
   consistent per-candidate direction.

---

## 4. Mechanism

Measured with a local probe over the canonical derived bundle. Method: for each
decision, average-rank the listed quantities and take the within-decision
Spearman correlation; report the mean across decisions.

### 4.1 Why the ordering is a *derived* signal

```text
retention_deadline_timestamp = decision_timestamp + ttl_seconds
```

and `ttl_seconds` is the output of the frozen estimator
(`src/kvopt/continuum/ttl.py`), which maximises

```text
P(return <= t) * benefit - t        where  benefit = queue_delay * eta + prefill_reload
```

Within one decision, `decision_timestamp`, `queue_delay` and `eta` are constant
(queue delay and eta have **zero** within-decision spread in this campaign), so
the optimal TTL varies only through `prefill_reload` and the tool-specific
return-time samples. Hence:

| Within-decision relation | Mean Spearman | n | Split |
| --- | ---: | ---: | --- |
| `prefill_reload` ↔ `deadline` | **+0.938** | 36 | 36 positive, 0 negative |
| `next_tool_type=code` ↔ `deadline` | **+0.728** | 45 | 39 positive, 0 negative |
| `prefill_reload` ↔ `loss` | +0.192 | 36 | 18 positive, 18 negative |
| `deadline` ↔ `loss` | **−0.005** | 39 | 15 positive, 24 negative |

⇒ **`deadline` is essentially the TTL estimator's own cost ordering**, with a
tool component on top. It is a **model output, not an independent observation.**

This also explains a previously recorded degeneracy: the M1 cost/size cluster
was rank-identical to the baseline on all 60 decisions. It is identical because
`prefill_reload` ↔ `deadline` is **+0.938** — the deadline order *is* the cost
order, so a cost-ascending rule reproduces the baseline almost exactly.

### 4.2 The necessary negative control: it is **not** simply "cost descending"

Because `cost` ↔ `deadline` is +0.938 but not 1.000, the hypothesis must be
distinguished from the obvious cost-reversal. Measured:

```text
reverse-deadline and prefill_reload-descending select the SAME set in 27 / 60 decisions
```

| Rule | Feasible mean abs regret | paired (b/w/t) | mean delta |
| --- | ---: | --- | ---: |
| `H1_R1_reverse_deadline` | **0.026428** | 24 / 15 / 21 | **+0.014797** |
| `prefill_reload` **descending** | 0.043534 | 18 / 18 / 24 | **−0.002308** |

⇒ They agree on only 27/60 decisions, and plain cost-descending is **worse**, not
better. So the hypothesis is **not** a restatement of an inverted cost rule; the
`next_tool_type` ↔ `deadline` component (+0.728) carries information that cost
alone does not. This also means the M1 family was only ever registered in the
**ascending** direction; the descending direction is a distinct, previously
untested rule.

### 4.3 The artifact question, answered honestly

**Is the `deadline` ↔ return-time anti-correlation a workload-generator artifact?**

**Partly, and the honest answer is that it does not matter for whether this is
legitimate — it matters for what the result would mean.**

- The **`cost` ↔ `deadline` coupling (+0.938) is entirely a property of the
  frozen TTL estimator**, not of any serving system. The estimator sorts by cost
  because `benefit ∝ prefill_reload`.
- Therefore H1-R1 is best described as **"invert the baseline's own keep
  decision"**. That is a legitimate and auditable online rule — it reads only
  decision-time fields and no future label — but it is not "a discovered serving
  truth about deadlines".
- Whether the gain **transfers** depends on whether a new workload reproduces
  the same interaction: the same cost-driven TTL ordering, the same tool
  component, and the same relation between the TTL model's expected benefit and
  the realized loss. That is precisely what the independent holdout must test,
  and it is why the hypothesis cannot be accepted on the discovery campaign.

⚠️ Two further generator-dependency risks, both unresolved:

1. `eta` and `queue_delay` have **zero** within-decision spread. The TTL `benefit`
   term therefore reduces to `queue_delay·eta + prefill_reload` with a constant
   leading term. If a new workload varies them, the TTL optimum — and hence the
   deadline ordering — changes.
2. The tool-specific return-time samples that drive the TTL optimum are supplied
   by the scenario definitions. If they are hand-authored, the tool component of
   the ordering inherits that authorship.

---

## 5. Why the current campaign cannot judge this

```text
The rule was discovered on the canonical campaign.
```

M1 reclassified that campaign as **DISCOVERY / CHARACTERIZATION DATA**, and it
must never serve as the final holdout for a rule found on it. Using it would be
in-sample selection.

Independently, the campaign fails the acceptance protocol's sample floor anyway:

```text
clusters         : 20      (floor is 30)
families present : 6 / 6   ✓
```

⇒ Any verdict computed here is `DIAGNOSTIC_ONLY` by construction. See
`docs/phase2a-m4-rule-acceptance-protocol.md`.

---

## 6. What the new holdout must contain

| Requirement | Reason |
| --- | --- |
| **≥ 30 independent decision clusters** | Frozen holdout floor |
| **All 6 formal families (F1–F6)** | Family direction agreement ≥ 2/3 is unjudgeable otherwise |
| **Independent workload draw** | The discovery campaign's seeds are near-replicas (60 rows → 20 clusters → **9 unique decision patterns**) |
| **Variation in `eta` / `queue_delay`** | Currently zero within-decision spread, so the TTL `benefit` term is degenerate (§4.3) |
| **Different return-time distributions** | The tool component of the ordering depends on them (§4.3) |
| **Baseline-vs-baseline repeat measurements** | Required to calibrate `epsilon_latency` for Level B; see §7 |

The rule, its formula, direction, tie-break, fallback and primary metric are
**frozen as of this document**. If the holdout is judged on a different metric,
that is a new preregistration, not an edit to this one.

---

## 7. How it will be judged

Strictly by the frozen acceptance protocol, applied unchanged:

```text
Level A (proxy outcome):
  cluster-level paired mean loss improvement > 0
  cluster-level 95% CI lower bound > 0
  better decisions > worse decisions
  family improvement direction agreement >= 2/3
  -> earns PROXY_CANDIDATE only; no runtime claim

Level B (if direct recompute observation is available):
  same four conditions on actual recomputed_prefill_tokens
  + TTFT / serving latency no material regression
```

`epsilon_latency` must be calibrated from **baseline-vs-baseline repeated-run
jitter** before the holdout is read; it is not chosen by hand. That calibration
data does not exist yet and is a request to M6.

**Falsification is a legitimate outcome.** If the rule fails, the finding is that
the estimator's own ordering is not invertible-as-a-serving-rule, which is
itself the answer to "is the negative result a controlled-workload limit or an
entry-level information ceiling?".

---

## 8. Traceability

| Statement | Source |
| --- | --- |
| H1-R1 approved for preregistration, not as a result | M1 ruling, item 3 |
| Freeze exact ordering, tie-break, applicability boundary | M1 ruling, item 3 |
| Judge only on a new independent holdout | M1 ruling, item 3 |
| 24/15/21 is motivation only | M1 ruling, item 3 |
| Canonical campaign = DISCOVERY / CHARACTERIZATION DATA | M1 ruling, item 1 |
| Signal Gate is not a rule filter (why this may enter H1) | M1 ruling, item 3 |
| Acceptance conditions, ≥ 30 clusters, ≥ 2/3 families | M1 ruling, item 4 |
| `epsilon_latency` from baseline jitter | M1 ruling, item 4 |
| Frozen binding term is the deadline (primary key) | `src/kvopt/costaware/replay.py`, `ExecutedP1BStrategy` |
| TTL estimator mechanism (`benefit ∝ prefill_reload`) | `src/kvopt/continuum/ttl.py`, `_choose_empirical_ttl` |
| Runtime fallback must not fabricate a value | `docs/phase2a-m4-missingness-semantics.md` |
| Rule and record | `src/kvopt/costaware/rules.py`, `preregistrations.py` |
| Tests | `tests/test_costaware_h1_preregistration.py` |
