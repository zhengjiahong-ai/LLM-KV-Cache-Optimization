# Phase 2A M4 — H1 Evidence Request

Status: **SUBMITTED FOR M1 REVIEW** (ruling item 1, 2026-10-07)
Requester: M4
Recipients: M1 (approval), M6 (formal campaign and analysis), M5 (substrate only)
Authority for ownership: `docs/phase2a-m6-formal-profiling-plan.md`
Blocking: any rule-level claim about entry-level information, including `H1_R1`

---

## 0. The question H1 answers

```text
当前 negative result
到底是 controlled workload 的限制，
还是 entry-level decision-time information ceiling？
```

M1 authorized H1 as an **evidence expansion**, not a retune of PR #32's nine
rules. This document specifies the evidence required to answer the question.

Both possible answers are useful. "The workload was the limit" means the entry-level
hypothesis deserves a re-test on realistic data. "It is an information ceiling"
means the project should move to H2 (block-level mechanism) with a documented
reason. The request below is designed so that either answer is reachable.

---

## 1. Why a new campaign is required (measured, not asserted)

### 1.1 The independent sample is far smaller than the row count

| Level | Count | Note |
| --- | ---: | --- |
| Raw decision rows | 60 | what a row-based statistic would assume |
| Clusters (`scenario group × decision position`) | **20** | seeds averaged, so not inflated |
| **Independent scenario draws** | **18** | a second decision in the same scenario shares its workload |
| Unique decision patterns | **9** | identical candidate-loss multisets pose the same problem |

The acceptance protocol requires **≥ 30 independent clusters**, so the current
campaign cannot support a rule-level claim at all.

Two further collapses worth recording:

- `f4-repeated-pressure` and `f6-repeated-block-reuse` each contribute two
  decisions, and those two decisions have **identical loss structure**
  (`ev40: n=3 (0, 0, 0.08873)`; `ev47: n=2 (0.08873, 0.17106)`). So the 20
  clusters overstate diversity as well.
- Seeds are near-replicas: per-seed aggregates are bit-identical, and
  **20/20** clusters have identical loss profiles across seeds. Seed repetition
  currently carries no independent information.

### 1.2 The cost dimension has only three levels

`prefill_reload_seconds` takes exactly **3** distinct values in the whole campaign:

```text
0.049754646  (r = 128 tokens)
0.088730125  (r = 256 tokens)
0.171057042  (r = 512 tokens)
```

The measured profile grid is `(16, 32, 128, 256, 512)` tokens, so the campaign
uses only the three largest points. **A cost-ordering rule is therefore a
three-way bucket sort.** Cardinality comparisons between cost rules are close to
meaningless at this resolution — which is a plausible partial explanation for the
recorded degeneracy where the cost/size cluster was rank-identical to the baseline.

### 1.3 The loss dimension has only four levels

The canonical loss takes exactly **4** distinct values across all 174 candidate rows:

| Loss | Rows | Meaning |
| ---: | ---: | --- |
| 0.0 | 36 | no return inside the horizon |
| 0.049754646 | 30 | PrefillReload(128) |
| 0.088730125 | 84 | PrefillReload(256) |
| 0.171057042 | 24 | PrefillReload(512) |

So the entire "regret" apparatus operates on a 4-valued outcome. Mean and median
absolute regret are computed over a signal with four possible levels.

### 1.4 The TTL benefit term is degenerate

The frozen TTL estimator maximizes `P(return ≤ t) · benefit − t` where
`benefit = queue_delay · eta + prefill_reload`. Measured across the whole campaign:

```text
eta               : 1 distinct value   (1.0 everywhere, constant within every decision)
queue_delay_t     : 1 distinct value   (0.0 everywhere, constant within every decision)
```

⇒ `benefit = prefill_reload` exactly, so TTL selection varies **only** with cost
and tool-specific return samples. The mechanism finding in
`docs/phase2a-m4-h1-r1-preregistration.md` §4 is a direct consequence, and it
means the current campaign **cannot** distinguish "deadline ordering works"
from "the TTL estimator orders by cost".

### 1.5 Dimension coverage is thin

| Dimension | Current coverage (20 seed-101 decisions) |
| --- | --- |
| `candidate_count` | 2 → 7, **3 → 10**, **4 → 1**, **5 → 2** |
| `next_tool_type` | database 22, search 21, code 15 (3 categories only) |
| Decisions with a zero-loss candidate | 8 / 20 |
| Loss spread | min 0.0, median 0.088730, max 0.171057 |

`n = 4` is covered by a single decision, so the report's per-bucket claim about
`n = 4` rests on one observation per seed.

---

## 2. Requested campaign

### 2.1 Scale

| Requirement | Value | Reason |
| --- | --- | --- |
| **Independent scenarios** | **≥ 40** | Must yield ≥ 30 **independent scenario draws** with margin, after the collapses in §1.1 |
| **Scenarios per family** | **≥ 6** | Six families must each support a family-level mean; 3 is too few |
| **Decisions per scenario** | 1–2 | More decisions in one scenario do **not** add independence |
| **Seeds** | 3 | Retained for runtime-noise estimation only; explicitly **not** counted as independent samples |
| Resulting clusters | expected ≥ 45 | Headroom above the 30 floor |

⚠️ **The single most important requirement: independence must come from new
scenarios, not from more seeds and not from extra decisions inside an existing
scenario.** Adding seeds multiplies rows without adding information, which is
exactly the situation §1.1 documents.

### 2.2 Dimensions that must vary

Each of these is currently degenerate or thin, and each directly limits what a
rule can express.

| Dimension | Current state | Requested |
| --- | --- | --- |
| **Prefix / cost resolution** | 3 values (128/256/512) | Use the **full** measured grid `(16, 32, 128, 256, 512)` **plus** intermediate lengths, so cost is not a 3-way bucket |
| **`eta`** | constant 1.0 | **Vary across decisions**, ideally within a decision |
| **`queue_delay_t_seconds`** | constant 0.0 | **Vary across decisions**, ideally within a decision |
| **`candidate_count`** | skewed, `n=4` nearly absent | Cover 2–6+ with a reasonable count in each bucket |
| **`next_tool_type`** | 3 categories | Add more tool categories if the workload model supports them |
| **Return-window diversity** | 4 loss levels, 2 scenarios structurally duplicated | Draw return behaviour independently per scenario rather than reusing one template |
| **Shared ownership / multi-release / repeated pressure** | present but rare | Keep them represented; they are the corner cases the method must not break |

The `eta` / `queue_delay` request is the sharpest one: because they are constant,
the TTL `benefit` term is a pure cost term, and a whole class of hypotheses about
lifetime-versus-affinity tradeoffs is **currently untestable**.

### 2.3 Independence requirements

| Requirement | Reason |
| --- | --- |
| Scenarios drawn from a **distribution**, not hand-authored one-by-one | Hand-authored scenarios let the workload author's expectations leak into the result |
| **No duplicate scenario structures** | `f4-repeated-pressure` and `f6-repeated-block-reuse` are currently structural duplicates |
| Return-time distribution **not reused** across scenarios | Otherwise the tool-specific TTL component repeats |
| **Sealed holdout**: freeze the scenario list before M4 sees any outcome | The acceptance protocol requires the rule to be frozen before the holdout is read |

### 2.4 Observation seam (Level B)

Level B requires the primary metric to be `actual recomputed_prefill_tokens`.
M1 approved a narrow native cache/recompute observation seam, recording **raw
native facts only**:

```text
request identity
prompt / prefix token count
native cached-prefix token count  (or a semantically equivalent native fact)
actual prompt/prefill work executed  (or a semantically equivalent token count)
```

Derived semantics (`full hit` / `partial hit` / `miss` / `hit ratio` /
`recomputed_prefill_tokens`) stay **M6-side**. Inference from `prefix identity`,
`logical release` or `planned return` is forbidden.

### 2.5 Baseline repeat runs (for `epsilon_latency`)

**≥ 3 repeated runs of the identical baseline**, so the latency
non-inferiority margin can be calibrated from run-to-run jitter instead of being
chosen by hand. Without this data Level B cannot be awarded at all.

---

## 3. What M4 will produce from it

| Output | Depends on |
| --- | --- |
| Verdict for `H1_R1` under the frozen acceptance protocol | §2.1–§2.3 |
| Machine-readable preregistration record per new hypothesis | This work's `preregistrations.py` |
| A documented answer to the H1 question in §0 | §2.1–§2.4 |
| Cluster-level statistics with reproducible bootstrap intervals | §2.1 |
| If Level B is reachable: a runtime-candidate verdict with a calibrated latency margin | §2.4–§2.5 |

M4 will **not** implement a runtime policy, and will not read the holdout before
the rule set is frozen.

---

## 4. Ownership

Ownership follows `docs/phase2a-m6-formal-profiling-plan.md` §1, which is the
authoritative task definition for this stage: **M6 owns scenario generation,
workload/scenario test writing, profiling and data collection, derived-dataset
construction, and statistical analysis.** M5 owns the reusable substrate. An
earlier draft of this document assigned scenario design to M5, which is the wrong
split.

| Item | Owner |
| --- | --- |
| Independent workload / scenario **distribution design** (§2.1–§2.3) | **M6** |
| Scenario generator and formal campaign | **M6** |
| Campaign execution | **M6** |
| Sealed holdout custody | **M6** |
| Derived runtime outcomes (recompute / APC labels) and statistics | **M6** |
| Reusable workload / benchmark substrate | **M5** |
| Filling a missing **raw** observation seam or provider | **M5 / M1 runtime-integration side** |
| Observation-seam **collection, joins, derived labels** (§2.4) | **M6** |
| Baseline repeat runs (§2.5) | **M6** |
| Formal rule analysis and verdicts | **M4** |
| Approval of observation semantics and H1 execution | **M1** |

M5 is deliberately not in the analysis path: M5 provides substrate and a raw
seam if one is genuinely missing, and does **not** perform formal rule analysis.
An earlier draft listed the seam under "M6" wholesale; the correct split is that
the **raw native fact** side is a substrate/runtime-integration concern (M5/M1)
while **collection, joins, derived recompute/APC labels and formal analysis** are
M6's.

---

## 5. Acceptance of this request

Nothing in this document authorizes a rule claim. The verdict on any hypothesis
is produced by `src/kvopt/costaware/acceptance.py` under the frozen protocol
(`docs/phase2a-m4-rule-acceptance-protocol.md`), applied to the sealed holdout.

If the campaign cannot meet §2.1, the honest label remains `DIAGNOSTIC_ONLY`, and
that is a legitimate outcome to report.

---

## 6. Traceability

| Statement | Source |
| --- | --- |
| H1 approved as evidence expansion, not a retune | M1 ruling, item 1 |
| Current campaign reclassified DISCOVERY / CHARACTERIZATION DATA | M1 ruling, item 1 |
| Narrow cache/recompute seam approved, raw facts only | M1 ruling, item 2 |
| Evidence priority: recompute tokens → cached prefix → latency → counters | M1 ruling, item 2 |
| ≥ 30 independent scenario draws, all 6 families; seeds are noise only | M1 ruling, items 4 and the 2026-10-07 unit correction |
| `epsilon_latency` from baseline repeats | M1 ruling, item 4 |
| Cluster / unique-pattern counts | `offline_eval.scenario_clusters`, report §5.2.1 |
| Three-level cost, four-level loss, constant eta/queue_delay | local probe over the canonical derived bundle (method: distinct-value count over `candidate_loss_evidence` and `decision_candidates`) |
| TTL benefit mechanism | `src/kvopt/continuum/ttl.py::_choose_empirical_ttl` |
| Measured cost grid | `docs/experiments/phase1b-continuum/final-report.md` §3 |
| Workload responsibilities | `docs/phase2a-m6-formal-profiling-plan.md` §1 (authoritative for this stage) |
| Owner charters | `docs/team-responsibilities.md` (coarser; used only where the profiling plan is silent) |
