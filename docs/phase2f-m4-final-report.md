# Phase 2F Final Report — Agent APC Eviction x Retention Offline Simulation Study

**Submitter**: M4 **Reviewer**: M1 **Date**: 2026-10-16 (revised after the
Member-2 audit; see §10)
**Branch**: `sim/phase2f-agent-apc-eviction-retention`
**Nature**: CPU-only offline simulation (no GPU, no real model, no native run).
**Not claimed**: real GPU, real vLLM serving, TTFT/TPOT/throughput, or
production workload performance.

---

## 0. Headline

> In agent-like multi-turn tool-calling cache workloads, the independent
> in-band deep-first victim rule (Ours-Evict `simulation candidate v0`)
> produces a large, regression-free reduction in recomputed tokens where
> long-lived or shared prefixes come under pressure (paired −1658.5
> tokens/draw overall; −11465.6 in family S5; 0 regressions in 2088
> request-level comparisons). Continuum Retention's increment is real but
> strongly conditional: in burst and slow-return scenarios it acts mainly by
> **shrinking the legal candidate set** (S4: −190.4/draw) and there it
> **subsumes** the eviction rule (A3 ≡ A1); in long-session scenarios it does
> nothing while the eviction rule does all the work; where recency already
> protects the valuable content neither mechanism helps. Against an already
> strong victim rule, retention is a pure constraint (oracle-like reference
> with retention is 645.8 tokens/draw *worse* than without).

---

## 1. Deliverables and reproduction

| Deliverable | Location |
| --- | --- |
| Combined algorithm design | `docs/phase2f-m4-combined-algorithm-design.md` |
| Simulator design | `docs/phase2f-m4-simulator-design.md` |
| This report | `docs/phase2f-m4-final-report.md` |
| Implementation | `src/kvopt/agent_sim/` (content / pool / trace / workload_gen / retention_bridge / policies / simulator / experiments / report / cli) |
| Tests | `tests/test_agent_sim_micro.py` (4 core micro-benchmarks), `test_agent_sim_mechanics.py` (13), `test_agent_sim_invariants.py` (3), `test_agent_sim_audit.py` (12) |
| One-command reproduction | `python scripts/phase2f_run_simulation.py --out results/phase2f` (≈75 s, CPU-only) |
| Machine-readable results | `results/phase2f/campaign.json`, `report.md`, 3 PNG charts (regenerated locally; `results/*` is git-ignored by repo convention) |

Scale: 7 families x 10 draws = **70 independent scenario draws** (statistical
unit); 8 arms per draw (A0–A3, A4, O1, O2, D1). Seed `20261016`; per-trace
SHA-256 recorded in `results/phase2f/traces.json` and in `campaign.json`.

---

## 2. Setup (summary)

- **Arms**: A0 native LRU; A1 retention + native LRU (the frozen
  `RetentionAwareLRUAdapter` is instantiated directly); A2 candidate v0 without
  retention; A3 candidate v0 + retention; A4 system reference (A1 plus the
  frozen `ContinuumSchedulingPolicy` admission order); O1/O2 oracle-like
  references (Belady-style next-use, **not proven optimal**, with/without
  retention); D1 direction-reversal diagnostic.
- **candidate v0**: eligible candidates ordered by
  `(tier, band_min_rank, −depth, lru_rank)` (retention on) or
  `(band_min_rank, −depth, lru_rank)` (off). Zero hyperparameters;
  `depth`/`band` are **simulation-observable, runtime-unextended** signals;
  with the signals removed the policy degrades to native LRU bit-for-bit
  (asserted).
- **Physical semantics**: fixed block pool (block size 16); chained content
  hashes (prefix trie); strict prefix truncation; vLLM-style free queue;
  eviction really removes hash mappings and immediately reuses the slot.
- **Retention**: frozen components only (`RuntimeCoordinator`,
  `RetentionManager`, `RetentionAwareSelectionCoordinator`), unmodified.
- **Statistics**: per-draw pairing; mean/median; 10,000-resample paired
  bootstrap 95% CI (seed 20261016); improved/tied/degraded draw counts; NGR.

---

## 3. Main results

### 3.1 Arm-level summary (70 draws, measured window)

| Arm | Mean recomputed tokens/draw | Hashed evictions | Forced releases | Non-trivial window share |
| --- | ---: | ---: | ---: | ---: |
| A0 native LRU | 4981.0 | 23893 | 0 | 100.0% |
| A1 retention + native | 4925.9 | 23624 | 503 | 98.2% |
| **A2 Ours-Evict** | **3322.5** | 16630 | 0 | 100.0% |
| **A3 Ours-Evict + retention** | **3275.2** | 16402 | 503 | 98.2% |
| A4 full-system reference | 4891.7 | 23474 | 477 | 98.1% |
| O1 oracle-like reference | 2039.5 | 11537 | 0 | 100.0% |
| O2 oracle-like + retention | 2685.3 | 14362 | 503 | 98.2% |
| D1 direction reversal | 4981.0 | 23893 | 0 | 100.0% |

### 3.2 Paired comparisons (negative = challenger recomputes less)

| Family | A2 vs A0 | A1 vs A0 | A3 vs A1 | A3 vs A2 | A4 vs A1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| S1 continuous tool calls | 0 | 0 | 0 | 0 | 0 |
| S2 heterogeneous waits | −11.2 | **−19.2** | 0 | −8.0 | 0 |
| S3 shared roots | **−96.0** | −108.8 | −76.8 | −89.6 | 0 |
| S4 burst pressure | 0 | **−190.4** | 0 | −190.4 | **−240.0** |
| S5 long sessions | **−11465.6** | 0 | **−11465.6** | 0 | 0 |
| S6 cold/warm + drift | 0 | 0 | 0 | 0 | 0 |
| S7 negative controls | −36.8 | −67.2 | −12.8 | −43.2 | 0 |
| **ALL** | **−1658.5** | −55.1 | −1650.7 | −47.3 | −34.3 |

Full CIs, medians, improved/tied/degraded counts and NGR are in
`results/phase2f/report.md` §2. Every main comparison has `dR = 0` except
A4 vs A1 (mean +4.8): no policy causes per-request extra recomputation relative
to its baseline, while A4 redistributes a small amount (aggregate improves,
some requests recompute more).

### 3.3 Mechanism chain (task §7)

```text
L1 legality    enforced per decision (unique, subset of candidates, exact
                count); 560 arm x draw combinations, 0 failures
L2 real difference   A2 vs A0 victim-set divergence 36.9% of decisions with
                100% of decisions in the non-trivial window; A3 vs A1 36.6%
L3 physical change  eviction removes cache mappings (micro-benchmarks a/b)
L4 recomputation    same-trace replay changes aggregate recomputed tokens (§3.2)
increment attribution four-way contrast (§3.2)
```

**Counterfactual (first divergence).** In 60 of 70 draws the two arms first
choose different victim sets. Substituting the challenger's victims at that
single decision avoids on average **74.7 tokens** of future recomputation
(max 688) with **zero reverse damage** — consistent with the dominance theorem.
Divergence is index-aligned and descriptive after the first divergence; the
counterfactual is the clean causal estimate.

**Mechanism invariants (campaign-level test assertions).**

1. D1 (explicit shallow-first) is **bit-identical to A0** on all 70 draws —
   the simulated native band order *is* shallow-first, i.e. candidate v0
   reverses exactly the native direction (the RC-B signal, confirmed
   in-simulation).
2. candidate v0 shows **0 per-request hit-depth regressions** in 2088
   request-level comparisons against native LRU.
3. Negative-control draws (no reuse / no pressure) recompute **exactly 0**
   under every arm.

---

## 4. Gain attribution (direct answer to the research question)

| Channel | Evidence | Magnitude |
| --- | --- | --- |
| **Better physical victim choice** | A2 vs A0 (retention off; only the in-band direction differs) | −1658.5/draw overall; S5 −11465.6; S3 −96.0; 0 per-request regressions; counterfactual +74.7 tokens at the first divergent decision |
| **Candidate-set change** | A1 vs A0 (same native victim rule; only retention eligibility and pressure release differ) | −55.1/draw overall; S4 −190.4; S3 −108.8; 503 forced releases; 41180 of 52648 protected blocks (78%) survive their protection window |
| **Extended effective reuse** | blocks re-acquired while still protected; window survival | 1540 blocks reused while protected; 6316 protected block-token-seconds per draw |

**Key interaction: retention and the victim rule substitute rather than purely add.**

- **S2/S4**: `A3 ≡ A1` (10/10 draws each). Once retention removes the valuable
  shallow blocks from the candidate set, the victim choice among the remainder
  no longer changes recomputation — the benefit comes entirely from the
  candidate-set restriction.
- **S5**: `A1 ≡ A0` (retention ineffective) while `A2/A3` improve enormously.
  Frozen retention protects only each program's **latest** prefix (older
  entries lose protection at the next admission), so it cannot protect
  accumulated session history; only the eviction rule preserves the chain head.
- **S3**: partial addition (A3 − A0 = −185.6/draw, larger than either alone at
  −108.8 / −96.0 but smaller than their sum −204.8; the overlap is the same
  shallow shared blocks).
- **Oracle constraint experiment**: O2 (2685.3) is **worse** than O1 (2039.5)
  by 645.8/draw, and 53% of oracle decisions face a restricted candidate set.
  Retention's protection is blind to victim quality: for a perfect rule it is
  pure constraint; for a rule that would destroy shallow prefixes it is
  valuable.

### Where the benefit exists and disappears

| Condition | Family | Outcome |
| --- | --- | --- |
| accumulated long-session prefixes under sustained pressure | S5 | eviction-rule benefit is very large; retention ineffective |
| shared root prefixes under pressure | S3 | both effective, partially additive |
| burst concurrency / slow returns under pressure | S2, S4 | retention dominates (candidate-set mechanism) and subsumes the eviction rule |
| recency already protects the valuable content | S1, S6 | neither mechanism helps (native LRU already keeps hot blocks at the queue tail) |
| no subsequent reuse / no pressure | S7 draws 1–6 | exactly 0 by construction |
| victim rule already strong | O1 vs O2 | retention is harmful |

---

## 5. Retention-specific metrics (A1 and A3 share the retention path)

| Metric | Value (70 draws) |
| --- | ---: |
| Forced releases | 503 (zero-marginal releases: 0 in the campaign; the mechanism is pinned by micro-benchmark c) |
| Natural TTL expiries | **0** — scoped finding, see §6.1 |
| Protected block-token-seconds | 6316 per draw |
| Blocks reused while protected (cross-program) | 1540 |
| Protected blocks surviving their window / destroyed | 41180 / 11468 (78% / 22%) |
| Protected blocks never re-acquired (end-of-run) | A1 12740; **A3 7381** (candidate v0 reduces wasted protected capacity by 42%) |
| Shared blocks blocked by another protected owner | observable in S3/S4 decisions; pinned per-event by micro-benchmark c |
| Cold vs warm (S6) | recomputed 0 in both; evictions 7 → 41; TTL history mode cold_start → global |

Per-agent tails (I view): worst-agent cumulative recomputed 1793.6 (A0) →
1164.8 (A2); top-1 agent share 0.229 → 0.246; per-draw p95 185.3 → 169.4
(oracle-like reference: 785.4 / 0.237 / 140.7).

---

## 6. Structural and sensitivity findings

### 6.1 The frozen TTL estimator collapses at the simulated scales

With the simulator's degenerate queue-delay term (`T = 0`; no queueing model)
and reload cost `R ≈ 0.02–0.3 s` against tool gaps of 0.05–20 s, the frozen
objective `argmax_tau F(tau)*(T*eta + R) - tau` selects **TTL = 0 in 2253/2253
decisions**. The TTL sensitivity probe (frozen estimator, same recorded
samples, queue delay swept) yields non-zero TTLs in 0/2253 decisions at
T = 0.05 s and 37/2253 at T = 0.65 s. The claim is scoped accordingly: **at the
Phase-2E cost and gap scales, and with a degenerate queue-delay input, the TTL
dimension carries no discriminative power in this simulator**; protection is
delivered by the `waiting_followup` window instead. This is consistent with
Phase 2A finding F.2 and is not a statement about TTL in general. Natural
expiry is reachable in principle (a cancelled program with a positive TTL
keeps protection until the deadline; a bridge-level regression test exercises
this path), but the campaign contains no cancelled program, so the
campaign-level count is 0.

### 6.2 Dependence on the band-direction assumption (A1)

Re-running the campaign with the free-order assumption flipped
(`tail_first`) makes candidate v0 and native select **identical victim sets in
every family** (identical-victim rate 1.0). The benefit's existence therefore
depends entirely on assumption A1, which is derived from the pinned vLLM
source (`append_n(blocks_with_hash)` preserves block-table order) plus the
Phase 2C 87/87 contiguous-band evidence, but is **not** measured in this
project's runtime (P5 `(depth, native_lru_rank)` is `NOT_OBSERVABLE`). D1 ≡ A0
confirms the direction *inside the simulation*; the runtime direction remains
an open validation item.

### 6.3 Correspondence with PR #50 / M1 review

| M1 point | Handling |
| --- | --- |
| RC-A (hashless preference is native) | candidate v0 claims nothing for hashless-first; hashless blocks keep native priority; the change is only the within-hashed-band direction |
| RC-B (lru_rank direction) | measured in-simulation: D1 ≡ A0 bit-for-bit confirms native evicts shallow blocks first; `(depth, lru_rank)` statistics are emitted by the simulator (§ simulator design §7) |
| RC-C (shared prefixes) | the dominance theorem covers sharing through the free-event band structure (a shared root is at the head of every band containing it); micro-benchmark c verifies it |
| RC-D (dR formula) | `dR = sum_r B * max(0, j_old(r) - j_new(r))` throughout; the report also gives the signed aggregate delta and NGR with explicit directions |
| RC-E (interface not pre-authorized) | `depth`/`band` are labelled simulation-observable only; no adapter field change requested |

---

## 7. Audit outcomes (Member-2 review, this revision)

Confirmed defects found and fixed:

1. **No-lookahead interface leak.** `DecisionContext` carried
   `future_index`/`current_request_index` for *all* policies. The engine now
   populates those fields only for policies declaring
   `requires_future_trace` (the oracle-like references); ordinary policies
   always receive `None`. Regression tests: recording-policy assertion plus a
   decision-invariance test.
2. **Per-program gap mirror bug (probe instrumentation).** The bridge's
   server-gap mirror was a single pending slot, so interleaved programs
   mis-attributed each other's gaps and tool types. The TTL probe therefore
   ran on wrong samples. The mirror is now per-program and matches the frozen
   runtime history exactly (regression test). Effect: the probe's non-zero TTL
   count at T = 0 corrected from 286/4506 to **0/2253** — the "TTL is not
   always zero" observation in the previous revision was an instrumentation
   artifact and is withdrawn.
3. **Protection-time integral mis-attribution.** The in-place integration
   attributed an interval to the count sampled at its end whenever a
   tool-gap-end sample landed between two arrivals. The integral now records
   `(timestamp, count)` samples and integrates in time order (last sample wins
   at equal timestamps). Effect: protected block-token-seconds per draw
   corrected from 6005 to **6316**; no other metric changed.
4. **Entry-window measurement timing.** Protection payoff (reuse, survival at
   window end) is now measured at the moment protection ends — at admission
   before the returning request's own allocation, at group-start expiry, and
   after each decision (pressure release / cancellation) — instead of after
   the next request's evictions. Counts were unchanged in this campaign.
5. **Defensive hardening.** `BlockPool.check_invariants()` (queue/ownership
   disjointness, mapping consistency, no duplicate content, queue size) is
   asserted once per run; duplicate content assignment is rejected.
6. **Reporting cleanups.** TTL probe decisions were double-counted (A1 and A3
   records are identical; now counted once, and the equality is asserted by a
   test); dead code removed from the CLI; oracle-like arms relabeled
   "not proven optimal".

No defect was confirmed in: strict prefix truncation, phantom-hit safety,
shared-ownership release ordering, eviction legality, determinism, or the
metric direction definitions.

---

## 8. Conclusion tiers

### 8.1 Verified in simulation (mechanism facts for this simulator)

1. The simulated native free queue evicts shallow blocks first inside a band
   (D1 ≡ A0, 70/70 draws).
2. In-band deep-first selection is weakly dominant over shallow-first: 0
   per-request regressions in 2088 comparisons; zero reverse damage at the
   first divergent decision.
3. The selection changes victim sets (36.9% divergence) and physical cache
   state, and lowers aggregate recomputed tokens on the same future trace.
4. Retention adds an independent increment through candidate-set restriction
   (A1 vs A0), with forced releases observably destroying protected content
   (11468 blocks).
5. Retention constrains an already strong victim rule (O2 > O1).
6. Negative controls (no reuse / no pressure) are exactly zero under all arms.

### 8.2 Approximation-based inference (declared assumptions)

1. Effect sizes depend on assumption A1 (band-internal head-first insertion,
   source-derived); the sensitivity arm shows candidate v0 becomes identical
   to native if the assumption is flipped.
2. Queue delay degenerates to 0 (no queueing model), which bounds the TTL
   dimension; the probe quantifies the threshold.
3. Block size 16, block-aligned segments, instantaneous execution, and the
   frozen last-block cap are modeling choices (simulator design §9).
4. Synthetic workloads do not extrapolate to production distributions.

### 8.3 Still requiring real vLLM validation

1. The runtime band direction: `(block depth, native_lru_rank, same-free-event
   identity)` correspondence (the P5 gap).
2. Partial-hit behavior matching the truncation assumption.
3. Any latency or throughput conclusion (NOT_MEASURED here).
4. Runtime deployment of candidate v0 would need the minimal read-only
   interface extension (`depth` plus free-event grouping), which requires M1
   approval and is outside this round.

---

## 9. GO / NO-GO and the minimal real-runtime validation plan

### 9.1 Recommendation

```text
Ours-Evict (candidate v0) mechanism      CONDITIONAL GO — strong in-simulation
   evidence (zero regressions, large effect where pressure destroys shallow
   prefixes, clean physical mechanism, counterfactual support), but the
   benefit's existence depends on unmeasured assumption A1.
Continuum Retention as a complement       CONDITIONAL — real increments in
   burst / slow-return / shared-root scenarios; ineffective in long sessions;
   harmful on top of a strong victim rule. It substitutes for, rather than
   purely complements, a strong eviction rule.
Dynamic TTL dimension                      NO-GO at these scales — collapses to
   0 with a degenerate queue-delay input; not discriminative in this regime
   (probe quantifies the queue-delay threshold at which it would matter).
```

### 9.2 Minimal real-runtime validation (4 steps, within existing authorization)

1. **Measure A1 read-only**: on pinned vLLM 0.27.1, use the existing observer
   snapshot capability to record, at several `get_new_blocks` decisions,
   `(block_id, has_block_hash, native_lru_rank, same-free-event batch
   identity, prefix depth)`, and report the within-band
   `(depth, lru_rank)` rank correlation and direction. **Criterion**: if the
   hashed band order is head-first with a significant proportion, A1 holds and
   step 2 follows; if tail-first, candidate v0 has no gain — record the
   negative result and close the direction.
2. **Minimal interface extension request** (only after step 1 passes): an
   optional read-only `EvictionCandidate.depth: int | None` plus free-event
   grouping (or an equivalent batch + position encoding), defaulting to `None`
   where the adapter degrades to `NativeLRUAdapter` bit-for-bit. This is the
   post-hoc minimal request RC-E calls for; it is deliberately **not**
   pre-requested here.
3. **Controlled A/B** (Phase 1A controlled mode): one shared-root plus
   long-session pressure fixture, native LRU vs candidate v0, primary metric
   `aggregate_recomputed_tokens`, paired repeats, with `FORCED_RELEASE_DECISION`
   and the real hash-eviction ledger recorded.
4. **Retention increment re-test**: A1/A3 on the same fixture to check whether
   the candidate-set vs victim-selection separation reproduces at runtime.

---

## 10. Failures and limitations register

- No arm x draw execution failure (560 combinations; `campaign.json` failures
  section is empty).
- Known platform test failures: 33 on the full suite, identical to the main
  baseline (Windows artifacts); zero regressions introduced by this branch.
- Statistical power: 10 draws per family give wide intervals; this report makes
  directional and effect-size statements only, no P99 inference (Phase 2E §1.5
  boundary respected).
- The counterfactual covers the **first** divergent decision only; cumulative
  effects of later divergences are covered by the end-to-end paired deltas.
- Audit corrections (§7) changed two reported measurements (protection-time
  integral, TTL probe) and withdrew one observation ("TTL is not always zero");
  all effect estimates are unchanged.
