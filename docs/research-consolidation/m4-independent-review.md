# M4 Independent Review — PR #108 Cross-Phase Research Synthesis

**Reviewer:** M4  
**Date:** 2026-11-14  
**Object:** PR #108, `docs/research-consolidation/research-results-and-contributions.md` plus the R1 ledger, consolidation README, and `docs/research-status.md`  
**Review mode:** read-only evidence review; no frozen protocol, archive, or historical result is modified. No new GPU run, Native smoke, algorithm implementation, or Protocol v5 is authorized.

---

## 0. Overall assessment

This is a strong and unusually careful synthesis. It correctly refuses the easy stories:

- it does not turn A0−N0 mechanism evidence into proof that Cost-Aware ordering works;
- it does not turn the Phase 3 zero into “Cost-Aware is universally invalid”;
- it separates W1-B, PR #82, A1 Gate 2, A2 Gate 2 v3, A2 bounded-value, and Phase 3 campaigns;
- it keeps Phase 2D's local headroom distinct from Stage 0's zero avoidable-loss upper bound;
- it distinguishes `N−C` from `E−C`, and logical release from physical eviction;
- it states the Phase 3 replay-order deviation and the pending M1/M4 adjudication instead of silently normalizing them.

The research content is therefore credible enough to serve as a basis for a paper narrative. However, **the current version should not yet be treated as the canonical final synthesis**. There are four substantive issues that affect what the document claims, plus several scope/omission issues that should be corrected in the same editing pass:

1. **Phase 4's actual result is under-reported**: the synthesis mentions only “Session Continuation not identifiable” and omits the right-censoring correction and the one positive proxy signal (`TOOL_GAP`, 60s Brier ≈ 0.079, AUC ≈ 0.594).
2. **`research-status.md` contains an internal status contradiction**: a section labelled “Current” says main is `f005...`, while the R1 ledger says main is `18a0a9...`.
3. **`research-status.md` overstates A1's standing**: “Native evidence of some beneficial entry-release differences” is not equivalent to a demonstrated A1 benefit and conflicts with the synthesis's own A1 conclusion.
4. **The Phase 3 exposure paragraph conflates decision events with Entry-choice opportunities and omits the 39-cell clustering**: A2 does not choose an Entry, and 127 decisions are not 127 independent samples.

My recommendation is **major revision of the synthesis document, not of the research**: fix the factual/status issues, tighten the units and decision-layer wording, and add the omitted Phase 2C/Phase 4 evidence. No new experiment is needed.

---

## 1. What the synthesis gets right

### 1.1 The central diagnosis is correct

The document's strongest conclusion is:

> KV Cache cost-aware eviction is not only a cost-estimation problem; it is also a candidate-exposure and evidence-identifiability problem.

This is supported by multiple independent records:

- 120/127 Phase 3 forced-release decisions had only one legal Entry candidate; only 7/127 were genuine two-candidate choices;
- A3's seven dual-candidate decisions had identical Cost and Deadline rankings;
- A2 had 53 cost-known decisions and 74 `content_unverified` fallbacks, with 127/127 victim sequences equal to Native LRU;
- Stage 0 found zero avoidable-prefix-loss upper bound on the seven real competitive decisions;
- P2's predictors produced zero positive-gain flips on the five valid REAL decisions.

The synthesis does not overstate these as universal impossibility. It correctly limits them to the frozen cohort and tested implementations.

### 1.2 The campaign separation is mostly excellent

The document explicitly distinguishes:

- W1-B's 4-group, one-repeat descriptive smoke from PR #82's 9-group bounded evaluation;
- A1 Gate 2's provisional 144-run record from A2 Gate 2 v3 and A2 bounded-value;
- Phase 2E's 36-draw, 144-run synthetic campaign from Phase 3's 18-group Native campaign;
- Phase 2D's local shared-protected fixture from H2-M4's single-prefix comparator;
- Phase 3's primary 18-group population from H3-0's 20-group/38-cell population and H3-R's 9-group/16-cell population.

This directly addresses the “same arm names, different campaigns” risk. The document should preserve this structure.

### 1.3 The metric discipline is correct

The `N/E/C` definitions and the `R=E−C`, `W=N−C`, `S=N−E`, `W=R+S` identities are correct for Protocol v4. The Phase 2D caveat — its 64-token result is an `N−C` local prefill-work difference, not a Protocol v4 `E−C` absolute value — is exactly the kind of qualification that prevents a false cross-phase merge.

### 1.4 The Phase 3 replay-order treatment is honest

The synthesis keeps both facts:

- frozen enqueue-order conformance failed (only 8/40 cells exactly matched; 32/40 cells shared a common non-frozen order; no cell had cross-arm-different order);
- the actual-order audit rebuilt 5,760 request-arm E values with no changes and reproduced the fixed-population effects.

It does not retroactively convert the frozen-order FAIL into PASS. That is the correct evidentiary posture.

---

## 2. Must-fix issues

### R-01 — Phase 4 is under-reported: missing right-censoring and TOOL_GAP proxy result

**Location:** `research-results-and-contributions.md` §1.9, lines 218–222; also the Phase 4 row in §2 (line 247) and the contribution section §3.

**Current text:** Phase 4 is summarized only as:

> 40 Sessions、480 C1 request rows; event stream has no independent session_id; program_id == session instance_id; no program has multiple sessions; Session Continuation and Program Continuation are observationally equivalent; only a Program Continuation proxy is available.

**Problem:** This is true but incomplete. It omits two results that M1 explicitly recognized in the PR #107 review:

1. the right-censoring correction (requests with less than W seconds of observable time are CENSORED, not negative);
2. the only positive proxy signal in the phase: `TOOL_GAP` at 60s, Brier ≈ 0.0788, AUC ≈ 0.594, with 422 valid rows out of 480 after censoring; 300s is 54.2% censored and has only 4 negatives, so it must not be used as a stable result.

**Evidence:** `phase4-session-continuation-report.md` §3–§4 (current report): censored rates 5s 4.8%, 15s 8.1%, 60s 12.1%, 300s 54.2%; `TOOL_GAP` 60s Brier 0.0788, AUC 0.594; 300s valid 220, negative 4. The R1 ledger §4.3 also omits both.

**Why it matters:** The synthesis currently makes Phase 4 look like a pure negative identity audit. In fact it also contains a weak but real program-level proxy signal and a methodological correction that prevents tail requests from being mislabeled as negatives. Omitting them under-credits the phase and weakens the evidence ledger's claim to be a complete cross-phase synthesis.

**Suggested fix:** Add a short paragraph to §1.9:

> Phase 4 reconstructed 40 sessions / 480 C1 request rows. The event stream has no independent `session_id`; every session's `instance_id` equals the request `program_id`, and no program has multiple sessions. Session Continuation is therefore not independently identifiable. The report's continuation results are program-level proxies only. With right-censoring at the replay-window end, censored shares are 4.8%/8.1%/12.1%/54.2% for 5/15/60/300s; the 60s `TOOL_GAP` proxy has Brier 0.0788 and AUC 0.594, while 300s has only 4 negatives among 220 valid rows. Neither result establishes Session Continuation or a validated continuation-cost model.

Also add a contribution bullet under §3 for **session/program identity auditing and right-censoring**, or at minimum reference it in §3.3.

---

### R-02 — `research-status.md` has a contradictory “Current main” snapshot

**Location:** `docs/research-status.md`, lines 22–24.

**Current text:**

```text
## Current Phase 3 status (M1 reconciliation, 2026-11-10)

Current main: `f005ecf239c1a982d0a751f430e24fa8ca47e46e`.
```

**Problem:** The R1 ledger's source snapshot says main is `18a0a9198403af735350cbbfd9aae20e7b2b39bd` (ledger line 5; also §7 line 402). The status file labels its older hash as “Current”. A reader cannot tell which is authoritative, and the PR is supposed to update the canonical status.

**Evidence:** `r1-experiment-evidence-ledger.md` line 5 and §7; `research-results-and-contributions.md` uses the ledger's snapshot.

**Suggested fix:** Either:

- update the status line to the actual current main hash, or
- relabel the section as a historical 2026-11-10 snapshot and add a separate “current main as of 2026-11-14” line.

Do not leave two different hashes both presented as current.

---

### R-03 — `research-status.md` overstates A1's standing

**Location:** `docs/research-status.md`, line 145.

**Current text:**

> Phase 2G A1 | BOUNDED EVALUATION COMPLETED | Native evidence of some beneficial entry-release differences; prior Gate 2 decision analysis found 54/54 A1 selections reproduced by simple sufficient-first heuristic; independent cost-model signal unproven

**Problem:** “Native evidence of some beneficial entry-release differences” is too broad. It can be read as A1 having a demonstrated benefit, which contradicts the synthesis's own conclusion:

- W1-B's 4-group, one-repeat descriptive A1−A0 deltas are negative (`−1056, 0, −1616, −1232`), but the document itself correctly calls this a bounded smoke;
- PR #82's 9-group A1 result is 0 better / 1 worse / 8 tied, mean +412.44 tokens (worse);
- Phase 2H's only A1 divergence increased recomputation by 6,320 tokens;
- Phase 3 showed no A1/A0 difference, with only 7 dual-candidate decisions.

**Evidence:** `research-results-and-contributions.md` §1.6–§1.7 and §3.7; R1 ledger §2.7 and §2.8; PR #82 bounded results; Phase 2H smoke report.

**Suggested fix:** Replace the row with a statement that distinguishes the descriptive W1-B observation from the later negative/inconclusive campaigns, e.g.:

> Phase 2G A1 | BOUNDED EVALUATION COMPLETED | W1-B's 4-group smoke had descriptive A1−A0 reductions, but PR #82's 9-group evaluation found no group-level A1 benefit (0 better / 1 worse / 8 tied, mean +412.44), Phase 2H's sole divergence increased recomputation by 6,320, and Phase 3 had no A1/A0 difference with sparse competition. No independent A1 benefit is demonstrated.

This is a must-fix because `research-status.md` is the canonical status index.

---

### R-04 — Phase 3 exposure paragraph conflates decision events with Entry choices and omits 39-cell clustering

**Location:** `research-results-and-contributions.md` §1.8, lines 193–197.

**Current text:**

> A0/A1/A2/A3/E0 每臂均有 127 次 forced Entry Release decisions；其中 120 次只有一个 legal Entry candidate；只有 7/127（5.5%）是真正的双候选竞争机会；A3 的七次多候选决策中...

**Problem:** Two distinct issues:

1. **Decision-layer conflation.** A2 does not choose an Entry. It keeps A0's Entry Release and chooses physical Block victims. Saying every arm has 127 “forced Entry Release decisions” can be read as A2 participating in Entry choice. The correct statement is: every arm experiences 127 forced-release **decision events**; A1/A3/E0 make Entry choices at those events, while A2 makes Block-victim choices.
2. **Missing clustering.** The 127 decisions occur across 39 cells, not 127 independent samples. The synthesis should state “127 decision events across 39 cells” and treat the 5.5% as a descriptive exposure count, not an independent statistical estimate.

**Evidence:** `research-results-and-contributions.md` §0.1 already defines A2 as Block-level; R1 ledger §3.3 says “127 forced Entry Release decisions across 39 cells”; Phase 3 exposure audit.

**Suggested fix:** Rewrite as:

> A0/A1/A2/A3/E0 each experienced 127 forced-release decision events across 39 cells. For the Entry-choice arms (A1/A3/E0), 120 events had only one legal Entry candidate and 7/127 (5.5%) had two; A2's 127 events are Block-victim decisions (53 cost-known, 74 fallback), not Entry choices. These are descriptive exposure counts, not 127 independent samples.

This directly addresses the review's decision-layer and statistical-unit requirements.

---

## 3. Recommended corrections (not necessarily blocking)

### R-05 — A1 Gate 2's statistical unit is ambiguous

**Location:** `research-results-and-contributions.md` §1.6, line 153.

**Current text:** “A1 Gate 2 的 144-run 历史记录。早期报告给出 12 BETTER / 1 WORSE / 22 TIED / 1 INCONCLUSIVE...”

**Problem:** The reader may interpret the 12/1/22/1 as 144 outcomes. They are 36 scenario-draw outcomes from a 144-run campaign. The same document explicitly uses “36 draws” for A2 Gate 2 v3, so A1 should match.

**Evidence:** `phase2g-gate2-review/README.md` reports the 36-draw distribution and 144-run archive; R1 ledger §2.7.

**Suggested fix:** “A1 Gate 2 的 36-draw / 144-run 历史记录...” and state that repeat-level aggregation produces the 36 outcomes.

### R-06 — Phase 2C's actual APC hit distribution is omitted

**Location:** `research-results-and-contributions.md` §1.3, lines 95–100.

**Current text:** Phase 2C is summarized by 1,068 rows, 495 eligible turn prefixes, same-program chain stability, and 0/771 cross-program first-chain equality.

**Problem:** The audit also found 288 full hits / 48 partial hits / 159 misses among 495 eligible turn prefixes, with 408 first eligible predecessors correctly classified as no prior eligible prefix. That distribution is an important positive finding: same-program APC reuse was real, while cross-program sharing was absent. Without it, the reader may infer that the workload had no meaningful APC reuse at all.

**Evidence:** R1 ledger §2.4 (lines 124–128); Phase 2C audit report.

**Suggested fix:** Add one sentence with the 288/48/159 and 408 figures; this strengthens the distinction between reuse fidelity and content-topology fidelity.

### R-07 — P2/Phase 4 fail-closed evidence work is under-credited

**Location:** `research-results-and-contributions.md` §1.9 (P2 lines 211–216) and §3.2–§3.3.

**Current text:** P2 is summarized as five valid REAL decisions with 0 positive gain; the 18 excluded candidates and the fail-closed suffix rule are not mentioned. Phase 4's identity audit is also not reflected in the contributions section.

**Problem:** The synthesis's method contribution “separate evidence layers” should include the concrete fail-closed rules:

- P2 excluded 18 candidate audits because victim hashes could not be proven a contiguous suffix of any prior same-program chain; two real decisions (g10-c1, g10-c2) were excluded rather than defaulted;
- Phase 4 established that `session_id` is absent from the event stream, `program_id == session instance_id`, and no program has multiple sessions; this is a data-identifiability result, not a model failure.

**Evidence:** P2 report §2 and evidence `exclusions`; Phase 4 report §1; PR #107.

**Suggested fix:** Add a short “data identifiability / fail-closed joins” contribution bullet under §3.2 or §3.3, citing P2's suffix rule and Phase 4's session/program audit. This is one of the project's more transferable methodological lessons.

### R-08 — A0 baseline definition is under-specified

**Location:** `research-results-and-contributions.md` §0.1, line 30, and §1.8.

**Current text:** A0 is “冻结的项目侧 Continuum-style Entry Release,” but its sort key is not stated.

**Problem:** A0 is not pure deadline-first. The project's frozen A0 key is:

```text
(Entry deadline, minimum Native LRU rank over newly eligible blocks, deterministic Entry identity)
```

with Native LRU still selecting physical victims. Without this, a reader may think A1/A3 only had to beat a simple deadline rule; in fact A0 already uses a Native-rank secondary key, which is central to why the tested A1/A3 variants did not separate.

**Evidence:** `docs/Background-RelatedWork-Motivation/专业术语表.md` lines 71–76; `docs/Background-RelatedWork-Motivation/项目动机文档.md`; `docs/experiments/phase2i-entry-marginal-cost-design.md` (A0 semantics).

**Suggested fix:** Add one sentence in §0.1 or §1.8 giving A0's exact sort key and noting that physical victim selection remains Native LRU.

### R-09 — “Phase 2B/2C prove” should be scope-limited

**Location:** `research-results-and-contributions.md` §3.3, lines 286–291.

**Current text:** “Phase 2B/2C 证明 workload compiler 的逻辑 ownership_group 不能替代真实 submitted token identity 与 Native hash chain.”

**Problem:** The empirical result is from one audited H1 workload (1,068 rows; 0/771 different-program first-chain equality). The methodological principle is general, but “prove” can be read as universal. The ledger is more careful (“in that historical workload”).

**Evidence:** R1 ledger §2.4 and §9.2; Phase 2C audit.

**Suggested fix:** “在审计的 H1 workload 中显示...；这支持一个一般方法原则，但不构成对所有 workload 的普遍证明。”

### R-10 — §3.7 aggregates across campaigns without a no-pooling disclaimer

**Location:** `research-results-and-contributions.md` §3.7, lines 326–334.

**Current text:** A1/A2/A3/P2 are summarized in one negative-result section.

**Problem:** The section is a pattern-level synthesis, but it does not explicitly say that the bullet evidence comes from distinct campaigns with different units and cannot be pooled. The document's earlier sections are careful; this section should carry the same warning.

**Evidence:** The campaign separation in §1.6–§1.8 and the R1 ledger's lineage table.

**Suggested fix:** Add: “These are recurring patterns across distinct campaigns; no sample counts or effect sizes are pooled here.”

### R-11 — §4 claim matrix should make Phase 2E/Phase 3 estimand difference explicit

**Location:** `research-results-and-contributions.md` §4, lines 340–353.

**Current text:** The “Continuum-style Entry Release reduces eligible-prefix recomputation” row cites Phase 2E and Phase 3 and says the campaigns are not combined.

**Problem:** The row is correct but could be clearer that Phase 2E is a 36-draw synthetic scenario-level campaign and Phase 3 is an 18-group Native campaign with different arms/estimands. “Both show reduction” is not a pooled estimate.

**Suggested fix:** Add one clause: “Phase 2E: scenario-level synthetic; Phase 3: group-level Native; different cohorts/estimands; no pooled effect.”

---

## 4. Hypothesis verdicts: are they correctly stated?

The verdict table is largely correct. Specific notes:

| Hypothesis | Review judgment |
|---|---|
| **H1-R1 reverse-deadline** | Correct as `DIAGNOSTIC_ONLY`: 29 paired draws below 30, 13/14/2, mean −0.00833, CI crosses zero, family agreement 3/6. The document correctly says this is not proof of ineffectiveness. |
| **H2-M1–M3** | Correctly PASS within their measurement gates; the document does not promote them to policy benefit. |
| **H2-M4** | Correctly FAIL for the frozen single-prefix comparator, with the Phase 2D scope distinction. |
| **Phase 2A proxy signals** | Correctly `PROXY_SUPPORTED`, not runtime-stable: 10/174 label flips and `runtime_replicated=false`. |
| **Shared-protected multi-Entry headroom** | Correctly supported only in the Phase 2D fixture; the document says online predictability and generality are not established. |
| **Continuum-style Entry Release** | Correctly supported within Phase 2E/Phase 3 cohorts, with no claim of full-system or production benefit. |
| **A1 Cost-Aware Entry Release** | Correctly “not proven”; the q/deadline same-order, history threshold, Minimum Overshoot reproduction, and adverse HR02 divergence are the right evidence. |
| **A2 Cost-Aware Block Victim Selection** | Correctly “not proven”; fallback, no marginal signal, Greedy not changing the set, and incomplete physical attribution are distinct causes. |
| **A3 suffix-cost-aware Entry Release** | Correctly “not proven”; 7 dual decisions, Cost/Deadline rank agreement, A3/E0 no difference. |
| **Stage 0 loss-only oracle** | Correctly bounded: A0 optimal on 7 real decisions, upper bound 0, capacity `NOT_EVALUATED`; does not terminate the whole route. |
| **P2 future prefix-demand predictor** | Correctly not supported for positive decision value; 5 valid REAL decisions, 0 positive-gain flips; MAE/ranking separated from gain. |
| **Phase 4 Session Continuation** | Correctly `NOT_IDENTIFIABLE`; session/program equality and missing session lifecycle fields. But see R-01: add censoring and TOOL_GAP. |

The verdict table's main omission is **Phase 4's quantitative proxy result**; otherwise its `PASS/FAIL/INCONCLUSIVE/DIAGNOSTIC_ONLY/NOT_IDENTIFIABLE` usage is disciplined and does not turn “no observed effect” into “theoretically impossible.”

---

## 5. Method-contribution assessment

### 5.1 What is a genuine methodological contribution?

**Strongest: the N/E/C evidence chain and fail-closed joins.**

The project independently derives `E` rather than filling it from `C`, requires Native evidence for `N`, `E`, `C`, and preserves `NOT_OBSERVABLE/INDETERMINATE` instead of treating missingness as zero. This is a real evaluator/method contribution because it prevents:

- logical release being counted as physical eviction;
- APC eligibility being counted as a hit;
- a partial Native observation being silently completed into a full result;
- `N−C` being called `E−C`.

The P2 victim-suffix fail-closed rule and Phase 4 session-identity audit belong in this same contribution family. The synthesis should say so.

**Second strongest: decision-exposure analysis.**

The separation of **resource pressure** from **algorithm decision exposure** is the most transferable experimental-method insight in the project. The 127 events / 7 dual-candidate / 120 single-candidate result explains why a zero effect can be a design-exposure result rather than a model-quality result. This is a plausible paper core, especially combined with the explicit reporting checklist in §3.4.

**Third: local headroom vs online predictability vs downstream outcome.**

The three-question decomposition — is there local headroom? can an online signal identify it? does the choice change Native recomputation? — is a useful conceptual framework. It synthesizes Phase 2D, Phase 3, Stage 0, and P2 without conflating them.

### 5.2 What is an empirical finding rather than a method?

- **Phase 2E's token/TTFT dissociation** is an empirical finding, not a method. It is valuable but bounded to a queue-dominated synthetic prefill workload.
- **A1/A2/A3 negative results** are empirical findings; the method contribution is the decomposition of their failure mechanisms, not the observation that they lost.
- **Phase 2C's 0/771 cross-program equality** is an empirical workload-audit finding; its methodological value is the audit procedure, not a universal law.

### 5.3 What is engineering/infrastructure?

The Native ownership-boundary adapter (Phase 1A/1B) is an engineering/integration contribution: it lets project-side policies operate while vLLM retains BlockPool, refcount, free-queue, and APC cleanup ownership. It is a prerequisite for the research and a legitimate system contribution, but it is not by itself a scientific novelty. The document correctly calls it “system engineering” and denies byte-for-byte Continuum reproduction. Keep that boundary.

### 5.4 What needs Related Work before being called novel?

All seven candidate contributions need a Related Work check, but the most urgent are:

- N/E/C evidence-chain methodology vs existing KV-cache observability/evaluator work;
- decision-exposure analysis vs existing eviction-policy evaluation methodology;
- Native token identity/hash-chain auditing vs workload-fidelity work;
- token-to-TTFT dissociation vs serving-level KV-cache studies;
- session/program identity auditing vs agent-workload trace work.

The document already says “candidate contributions, not first claims”; that is the right posture. Do not upgrade any of them to “first” or “novel” without the Related Work pass.

### 5.5 What could be a paper core?

If the paper is about the **scientific finding**, the core should be:

> Candidate exposure and evidence identifiability, not cost-model accuracy alone, determine whether cost-aware KV-cache eviction can produce downstream benefit.

The N/E/C evidence chain and the exposure analysis are the methodological backbone; Phase 2D, Phase 3, Stage 0, and P2 are the empirical arc. The system adapter is supporting infrastructure, not the headline.

If the paper is about the **system**, the adapter is a contribution but needs a full-system comparison, which the project explicitly has not done. The current document correctly avoids that claim.

---

## 6. Missing findings / under-credited results

1. **Phase 4 right-censoring and TOOL_GAP** — must add; see R-01.
2. **Phase 2C's 288 full / 48 partial / 159 miss distribution** — recommended; see R-06.
3. **P2's 18 excluded candidate audits and two excluded REAL decisions** — recommended; see R-07.
4. **A0's exact sort key** — recommended; see R-08.
5. **Phase 2D E4 bounded in-flight overlap** — the document mentions E4 only in §1.4 in one line; the ledger has more detail. Not essential, but it would strengthen the “local headroom” claim if the reader needs to know the two-arm overlap was real.
6. **Phase 2B 7 requests / peak 3** — not essential; the synthesis is not a full Phase 2B report.
7. **Phase 3 actual-order 48/240 runs** — the document uses 8/40 cells; both are consistent (48 = 8×6), but adding “48/240 runs” would help readers who know the run-level count.

---

## 7. Future direction: what is actually supported vs what is a proposal

### 7.1 Current most valuable conclusion

The strongest current conclusion is not “we built a better eviction algorithm.” It is:

> The project has a credible Native integration and measurement chain, a demonstrated local mechanism effect, and a well-diagnosed failure of the tested Cost-Aware variants. The failure is primarily about candidate exposure, signal discrimination, and evidence identifiability, not a universal proof that Cost-Aware eviction is impossible.

### 7.2 Directions already negated or low-ROI

- **Further A1/A2/A3 score tuning on the frozen cohort**: not supported; the zero is explained by sparse competition, aligned signals, fallback, and no victim-set divergence.
- **P2 depth-only predictor iterations**: P2-A/B/C already show zero positive-gain flips; better MAE did not create decision value.
- **Session Continuation on the current Archive**: not identifiable; no session_id, no multi-session program, no switch events.
- **Partial-tail Entry unpinning as a short-term implementation**: high correctness/engineering risk; not justified by current headroom.
- **New large GPU campaign before exposure**: would likely repeat the same sparse-competition result.
- **Full four-system ranking claim**: no complete Native/Continuum Official/Continuum Adapted/Cost-Aware campaign.

### 7.3 What remains worth studying

1. **Natural candidate exposure**: use W1-C or another natural Agent trace pool for a CPU-only pre-screen of windows with multiple long-lived/growing prefixes; then a minimal Native audit of actual candidate count, legality, content identity, refcount, need, and victim set.
2. **Downstream victim-loss estimation**: only after exposure is confirmed; compare A0, simple deadline/sufficient-first comparator, and downstream-cost ordering on the same states.
3. **Evidence-aware LRU fallback**: determine whether there is any safe-divergence state at all; if zero, stop.
4. **Token-to-serving transfer**: keep TTFT/queueing as a separate estimand; do not infer serving benefit from token savings.
5. **Static TTL / scheduler** only with separate designs; Phase 3 cannot answer them.

### 7.4 If only one more experiment is allowed

Do the **W1-C natural exposure audit**, not another algorithm campaign:

- pre-register features available before the decision;
- freeze a small subset by repo/task, not by oracle gain;
- run a minimal Native audit that only counts legal multi-candidate states and victim-set divergence;
- success: enough natural `candidate_count ≥ 2` states with distinct victim sets to justify downstream-cost ordering;
- failure: still mostly single-candidate or no victim divergence → stop Entry-ordering algorithm work and write the exposure/evidence paper.

This is the highest-information, lowest-cost next step because it tests the **gate** on which every Entry-ordering claim depends. It also matches the synthesis's own conclusion that exposure, not score complexity, is the bottleneck.

### 7.5 Is there a better direction than current Cost-Aware design?

The evidence supports **decision-exposure-first and downstream-cost-aware** designs over another score. A better next design would:

- operate only on genuine multi-candidate states;
- use deterministic downstream victim-set simulation rather than a learned reuse score alone;
- compare against A0 and a simple Sufficient-first/earliest-deadline rule;
- report candidate count, signal validity, selection divergence, and downstream coverage;
- treat token savings and serving metrics as separate outcomes.

This is a research proposal, not a current result. The synthesis should keep that distinction explicit.

---

## 8. Final review opinion

**Recommendation: major revision of the synthesis before merge; no new experiment required.**

The document is scientifically sound in its main judgments and much better than a typical “positive results” summary. Its strongest contributions — N/E/C evidence discipline, decision-exposure analysis, and the separation of local headroom from online predictability and downstream gain — are real and worth preserving.

But it is not yet the canonical cross-phase record because:

- Phase 4's actual result is under-reported (R-01);
- the status file contradicts the ledger on the current main hash (R-02);
- the status file overstates A1 (R-03);
- the Phase 3 exposure paragraph conflates decision events with Entry choices and omits 39-cell clustering (R-04).

The recommended corrections R-05–R-11 are scope/clarity improvements; they do not require new data.

If R-01–R-04 are fixed, I would accept the synthesis as the basis for the paper narrative, with the explicit caveat that Related Work and the final Phase 3 M1/M4 adjudication remain open.
