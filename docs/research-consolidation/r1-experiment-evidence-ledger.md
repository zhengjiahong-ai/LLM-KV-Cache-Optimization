# R1 — Cross-Phase Experiment and Evidence Ledger

**Status:** INITIAL INVENTORY / DRAFT — not a final M1 research adjudication  
**As of:** 2026-11-14  
**Prepared from:** `research/phase3-stage0-oracle` @ `69acd43b59eed73484a8538b9836e4cd752aea32`  
**Main snapshot:** `main` @ `18a0a9198403af735350cbbfd9aae20e7b2b39bd`

> This document is a navigation and evidence-classification layer. It does not replace frozen protocols, accepted verdicts, primary reports, immutable archives, or M1 approvals. It does not pool results across phases, recompute raw outcomes, amend historical verdicts, or authorize new GPU work.

## 1. Purpose and reading rules

R1 consolidates the project's Phase 0–4 evidence so that later research claims can be traced to their actual source, experimental unit, runtime, and limitations.

### 1.1 Source precedence

When records disagree, use this order:

1. Immutable raw evidence archive and its SHA-256 manifest, interpreted under the protocol frozen for that campaign.
2. Accepted final experiment report and explicit M1 verdict.
3. M1 canonical research-status ledger.
4. Experiment navigation index.
5. PR descriptions, discussion comments, and historical planning documents.

A PR being merged means its code or documentation was integrated; it does not mean the tested hypothesis passed. A campaign being accepted means the experiment was accepted within its scope; it does not imply rule acceptance, method promotion, or a performance benefit.

### 1.2 Evidence tiers

The ledger distinguishes the following claims. Evidence at one tier does not automatically establish a stronger tier.

| Tier | Evidence question | Example |
|---|---|---|
| T0 — Implementation | Does the code implement the declared contract? | Adapter and policy unit tests |
| T1 — Runtime mechanism | Does the mechanism execute on the pinned Native runtime? | Entry Release, BlockPool cleanup, APC observation |
| T2 — Decision exposure | Did the policy receive a genuine choice between legal candidates? | Multi-candidate decision count |
| T3 — Selection effect | Did the policy select a different logical Entry or physical victim set? | A1/A2 versus baseline |
| T4 — Cache outcome | Did eligible-prefix recomputation change? | `Σ(E-C)` |
| T5 — Serving outcome | Did TTFT, throughput, or job completion improve? | End-to-end latency |
| T6 — Generality | Does the effect persist across independent workloads, runs, and environments? | Representative independent cohort |

### 1.3 Common metric vocabulary

For Native request evidence:

- `N`: Native prompt tokens.
- `E`: independently established eligible reusable-prefix tokens.
- `C`: Native cached-prefix tokens.
- Recomputed prefix tokens: `R = E - C`.
- Actual prefill tokens: `W = N - C`.
- New suffix tokens: `S = N - E`.

Do not call `N-C` recomputed tokens. Do not infer `E) from `C`. Entry Release, physical Block eviction, APC residency, and downstream recomputation are separate evidence layers.

## 2. Cross-phase inventory

### 2.1 Phase 0 / Phase 1A — Native adapter and ownership boundary

**Record:** system implementation and adapter validation, not one standalone performance campaign.

- The project-side adapter was designed to select legal victim block IDs while retaining Native vLLM ownership of BlockPool, FreeKVCacheBlockQueue, reference counts, APC hash cleanup, allocation, request lifecycle, and physical eviction bookkeeping.
- The frozen Native baseline is vLLM 0.27.1 with GPU APC.
- The Phase 1A adapter's role is the physical block-victim boundary. It must not be conflated with logical Entry Release.

**Supported:** the project can insert a narrow policy boundary while preserving Native cache ownership within the validated implementation scope.

**Not established:** a policy performance benefit, an end-to-end Continuum comparison, or exact reproduction of the original Continuum source implementation.

**Primary references:** [Architecture](../architecture.md), [Baseline Freeze](../baseline-freeze.md), [Research Motivation and Contributions](../research-motivation-and-contributions.md).

### 2.2 Phase 1B — Continuum-style baseline adaptation

**Record:** [Phase 1B final report](experiments/phase1b-continuum/final-report.md).

- Runtime: vLLM 0.27.1, pinned vLLM-Metal revision, Apple Silicon / Metal, Qwen2.5-0.5B-Instruct.
- Formal PrefillReload profile: 125 real MISS/HIT pairs, five prefix lengths (16, 32, 128, 256, 512 tokens), 2,125 pressure batches.
- Final real-runtime validation: completed; mode boundaries, native cleanup, nonterminal retention, program continuity, scheduler coordination, and terminal cleanup passed.
- The controlled pressure validation demonstrated the sequence: protected retained state → real GPU KV pressure → logical release → eligibility → Native eviction callback / BlockPool cleanup.

**Supported:** the project-side Continuum-style lifecycle, retention, pressure-release, and narrow scheduling adaptation operated on the validated profile.

**Not established:** byte-for-byte reproduction of the paper's system, original-paper workload reproduction, or a serving-performance advantage. The constrained 48-block validation pool is a correctness fixture, not a production operating point.

### 2.3 Phase 2A — H1 / H2 hypothesis campaigns

**Primary reference:** [H1/H2 closeout verdict](phase2a-h1-h2-closeout-verdict-record.md).

**H1:**

- 126 planned runs; 96 successful.
- 42 sealed scenario draws; 29 paired-evaluable draws, below the frozen threshold of 30.
- Final rule verdict: `DIAGNOSTIC_ONLY`.
- The campaign was accepted and closed, but H1-R1 was not promoted to a proxy candidate.
- This is not a statistical proof that the rule is ineffective; it is a failure to obtain the required independent validation support.
- Phase 2C later identified content-topology fidelity limitations in the historical workload. The H1 verdict itself was not rewritten.

**H2:**

- M1/M2/M3 passed their registered measurement gates.
- M4 (block-level extra headroom) failed: supporting cells = 0; resolved headroom cells = 0; pairwise headroom = 0 tokens.
- B1 method design and runtime implementation remained locked.
- M1's nonlinear isolated prefill-cost measurement does not by itself prove a runtime-serving benefit for a cost-aware eviction strategy.

**Separate Phase 2A M6 formal profiling record:** [Phase 2A M6 formal results](phase2a-m6-formal-results.md).

- 54/54 runs; 18 scenarios across F1–F6 and three seeds; 60 forced-release decisions.
- The canonical Empirical Gap Gate is `GAP-PROVISIONAL`, based on the preregistered planned-return-weighted prefill proxy.
- Four decision-time features met the proxy-support thresholds.
- Planned versus observed strict-horizon labels differed in 10/174 candidate outcomes.
- The report explicitly says `runtime_replicated=false`; these are proxy-supported signals, not runtime-stable predictors or direct recomputation/serving-impact evidence.

**R1 reconciliation note:** H1's 126-run campaign, H2's measurement campaign, and the 54-run M6 formal profiling report are retained as distinct source records until their exact archive lineage is verified. Their run counts and verdicts must not be merged by phase label alone.

### 2.4 Phase 2B / Phase 2C — Native fidelity and content-reuse audit

**Phase 2B reference:** [Final fidelity repair submission](phase2b-m6-final-review-submission.md).

- Seven Native requests completed with peak in-flight = 3.
- Prefix-input identity, Native prefix reuse, in-flight lifecycle, Native queue observation, pressure temporal ordering, negative controls, and provenance passed.
- TTL-history evidence remained `NOT_OBSERVABLE`.
- The pressure evidence was explicitly classified as layered temporal sequence, not per-block causal attribution.
- This was a fidelity repair, not a method-benefit experiment.

**Phase 2C reference:** [Workload content and APC reuse audit](phase2c-m6-workload-reuse-audit.md).

- Reproduced 1,068 request rows: 903 turn requests and 165 pressure requests.
- Of 495 eligible turn prefixes: 288 full hits, 48 partial hits, 159 misses.
- The 408 first eligible-turn predecessors were correctly classified as no prior eligible prefix, not misses.
- Same-program hash-chain identity reproduced; different-program first chains had 0/771 equal.
- The audit found that logical ownership labels did not create the intended cross-program Native token-content sharing in that historical workload.

**Supported:** replay order and logical ownership are not substitutes for actual submitted token identity, Native APC hashes, residency, and cached-token observations.

**Not established:** that the historical H1 verdict should be retroactively changed, or that all Agent workloads lack cross-program sharing.

### 2.5 Phase 2D — Victim-selection headroom

**Reference:** [Phase 2D headroom investigation](phase2d-m6-headroom-investigation.md).

- E1: accepted historical pressure runs exposed only one legal protected candidate per decision.
- E2: a Native fixture materialized two protected logical entries sharing eight real Native blocks.
- E3: four valid paired comparisons showed a repeatable 64-token recomputation difference; the direction reversed with the designated future-return target.
- E4: bounded in-flight overlap was demonstrated with two real Native request lifecycles.

**Supported:** local victim-selection headroom exists in the tested shared-prefix fixture; two legal logical-release choices can produce different Native recomputation outcomes.

**Not established:** online predictability, a general Cost-Aware policy benefit, end-to-end latency improvement, or generalization beyond the fixture. The four paired observations are not a population estimate.

### 2.6 Phase 2E — Native LRU versus Continuum baseline characterization

**Reference:** [Phase 2E measured campaign](phase2e-m6-measured-campaign-report.md).

- 36 predefined synthetic scenario draws across F1–F6.
- Native LRU and frozen Continuum baseline; two runtime repeats per scenario and arm.
- 144/144 successful measured runs; 72/72 comparable scenario-repeat pairs.
- Mechanism realized in 132/144 runs; 12 F4 shared-root runs did not realize the required physical-eviction identity mechanism and were retained as such.
- Mean paired aggregate recomputation difference: Continuum minus Native LRU = **−192 tokens per scenario**; 29 negative, 7 tied, 0 positive.
- The token reduction did not translate into a comparable TTFT-tail improvement. Queue delay dominated the reported queued-to-first-token interval in this workload.

**Supported:** on this predefined prefill-focused synthetic grid, the frozen Continuum baseline reduced scenario-level recomputation relative to Native LRU.

**Not established:** production-distribution generality, multi-token decode behavior, per-eviction causal attribution, or an equivalent TTFT/serving improvement.

### 2.7 Phase 2G — Cost-Aware Entry Release and Block Victim Selection

This phase contains several distinct campaigns and post-hoc audits. They must not be collapsed into one A1/A2 result.

#### A1 offline selection study

**Reference:** [A1 original report](experiments/phase2g-a1/README.md).

- On the H1 formal Level-A 120 decisions, A1 differed from A0 in 48 decisions at the selection level.
- Controlled examples included both a beneficial selection difference and a deliberately retained adverse example.
- These are logical selection observations, not Native recomputation benefit.

#### A1 Native Gate 2

**Reference:** [A1 Gate 2 review](experiments/phase2g-gate2-review/README.md).

- The reported 36-draw distribution was 12 BETTER / 1 WORSE / 22 TIED / 1 INCONCLUSIVE, mean delta −24.23, median 0.
- The original evaluator used `N-C` where the frozen recomputation metric is `E-C), and could silently omit requests lacking Native observations.
- A corrected evaluator path and fail-closed completeness checks were implemented, but the M1 closeout record says the corrected evaluator was not run against the same packaged 144-run archive in the review environment. The historical numeric result therefore remained provisional in that closeout.
- The experiment index also records that a simple Sufficient-first comparator reproduced 54/54 A1 Gate 2 selections; the independent contribution of q/λ was not established.

**Interpretation:** retain the reported distribution as historical/provisional evidence with its metric and archive-access caveats. Do not present it as a fully reverified final token result.

#### A2 Native Gate 2 v3

**Reference:** [A2 Gate 2 v3 final report](experiments/phase2g-a2-gate2-v3/final-report.md).

- 144/144 successful Native runs across 36 predefined scenario draws.
- Token outcome: 0 better / 0 worse / 36 tied; mean and median delta = 0.
- However, 72/72 repeat-level selection comparisons were `SELECTION_NOT_OBSERVABLE`; zero token difference does not prove equal decisions.
- The strict physical-event mapping also left substantial events unmapped.

**Interpretation:** execution completeness and token equality are established for this frozen grid; A2-versus-LRU selection equivalence is not.

#### Separate A2 bounded-value evaluation

**Reference:** [A2 bounded Native value evaluation](experiments/phase2g-a2-bounded-value-evaluation.md).

- Separate 144-run campaign, 36 scenario draws, two repeats.
- 0 BETTER / 3 WORSE / 33 TIED; mean scenario delta +26.2222 tokens.
- Overall research judgment: `INCONCLUSIVE`, because selection pairing and strict physical identity attribution were incomplete.
- This result is not merged with Gate 2 v3.

#### Bounded Native Cost-Aware evaluation — PR #82

**Reference:** [Bounded Native results](continuum-native-cost-aware-bounded-results.md), [PR #82](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/82).

- 18 W1-C tasks in nine groups; A0/A1/A2; one run per arm and group.
- 54/54 successful Native runs; nine complete statistical units.
- A1: 0 BETTER / 1 WORSE / 8 TIED; mean delta +412.44 tokens.
- A2: 0 BETTER / 3 WORSE / 6 TIED; mean delta +321.78 tokens.
- No group showed a recomputation-token improvement for either frozen policy.
- M1 accepted this as a bounded exploratory negative finding, not universal inferiority or run-to-run stability.
- Content-level per-block causal attribution remained `NOT_ESTABLISHED`.

#### Post-hoc Phase 2G comprehensive analysis

**Reference:** [Phase 2G comprehensive judgment](experiments/phase2g-costaware-comprehensive-judgment.md).

- For the 54-run PR #82 archive, A1 had 29 release-selection steps; the only two A1/A0 divergences were in g05, and the one nonzero downstream recomputation change was adverse (+3,712 tokens).
- A2 produced 601 block-decision events: 434 cost-known incremental-greedy decisions and 167 fallbacks.
- In the 434 cost-known decisions, the greedy selected set never differed from the rank-LRU set. Of these, 368 had zero marginal-cost signal; 66 had signal but the greedy set still did not change. Exact optimality was not computed for those 66 due to search budget.
- Cold-start TTL and history thresholds explain important parts of the observed signal geometry. The W1-A warm-start path exists in the codebase but was not enabled in the bounded campaign; its use would require a separate, symmetric design.

**Supported:** in these frozen workloads, additional cost scoring did not yield a demonstrated improvement over the relevant simple/native selection behavior.

**Not established:** universal inferiority, exact optimality of every A2 decision, or the absence of all future decision geometries where Cost-Aware can help.

### 2.8 W0 / W1 workload acquisition and bounded Native comparisons

**Canonical summary:** [Research Status](research-status.md), [Experiment Index](experiments/README.md).

- W0 public-source audit found that the authors' public Continuum repository did not provide the original paper's complete per-request serving trajectories.
- W1-A acquired ten SWE-bench Verified Agent tasks; the recorded traces include 453 model calls and 271 tool calls, with one submitted task and nine right-censored at the configured step limit.
- W1-B completed a 12-run bounded Native comparability smoke across four selected groups and A0/A1/A2. The reported A1−A0 recomputation deltas were −1,056, 0, −1,616, and −1,232 tokens; A2 tied A0 in all four groups. These are descriptive one-repeat observations, not formal population effects or per-eviction causal attribution.
- W1-C completed a 20-task S50/S100 feasibility pilot; 18 full-payload-comparable task pairs entered the later 54-run PR #82 evaluation.
- The W1 workload path is a controlled/sparse replay, not a reconstruction of the original paper's serving arrival distribution.

### 2.9 Phase 2H — History-Rich Native Replay Smoke

**References:** [Preflight status](experiments/phase2h-history-rich-native-preflight-status.md), [measured smoke report](experiments/phase2h-history-rich-native-smoke-results.md).

- Four diagnostic preflight runs and six formal Smoke runs are separate records.
- The six-run Smoke covered two frozen scenarios and A0/A1/A2, one observation per arm/scenario.
- Gate H passed in all six runs; history and TTL decisions were independently reproducible.
- All six A1 multi-candidate decisions were reconstructed. A1 differed from A0 once, but the divergence was also reproduced by Minimum Overshoot; the HR02 outcome increased recomputation by 6,320 tokens.
- A2 had 54 effective incremental-greedy decisions, all matching the Native LRU victim sequence; other allocation decisions explicitly fell back.
- Two scenarios and one repeat do not support population-level performance claims.

### 2.10 Phase 2I — A3 Native integration and CUDA preflight

**References:** [Static integration preflight](experiments/phase2i-a3-native-integration-preflight.md), [target CUDA preflight plan and failure record](experiments/phase2i-a3-target-cuda-native-preflight-plan.md).

- CPU/Mock integration and static gates were implemented and validated.
- The target CUDA preflight used a 180-request HR02 replay.
- Gate I/C/D passed; Gate O failed because physical evictions could not be uniquely attributed to the required A3 decision/SelectionPlan/content identity chain.
- The failure was retained as `FAIL_CLOSED`; it is not a successful A3 Native value campaign.
- No replacement GPU run is recorded in the current evidence set.

## 3. Phase 3 — Option F formal component campaign

### 3.1 Frozen cohort and calibration

**References:** [Load calibration](experiments/phase3-load-calibration.md), [G0 v3 bundle](experiments/phase3-option-f-g0-v3/README.md), [Protocol v4](../phase3-final-evaluation-protocol-v4.md).

- Existing A0 Load Calibration: 40 runs, 20 sealed Groups × C1/C2, A0 only, one repeat.
- This 40-run set was reused by G0 v3; it is not part of the 270 new runs and must not be rerun.
- G0 v3 binds 40 qualified tasks, 20 Groups, and 10 repositories.
- The G0 bundle's original `execution_authorized=false` is preserved; the separate M1 authorization is the operative authority.

### 3.2 270-run execution

**Reference:** [Phase 3 Option F final results](experiments/phase3-option-f-final-results.md).

- Execution code: `00a512111f15abddcad329572f6e50ccaaa76775`.
- Runtime: RTX 4090D, vLLM 0.27.1, PyTorch 2.13.0+cu130, CUDA 13.0.
- 30 A0 Noise runs + 240 Main runs = 270/270 successful.
- Main: 20 Groups × C1/C2 × six arms (N0/A0/A1/A2/A3/E0).
- Primary estimand: arm minus A0 aggregate recomputed tokens; Workload Group is the statistical unit; primary paired population = 18 Groups.

Primary results:

| Contrast | Groups | Mean delta (tokens) | Supported interpretation |
|---|---:|---:|---|
| A1 − A0 | 18 | 0.0 | No observed incremental recomputation benefit |
| A2 − A0 | 18 | 0.0 | No observed incremental recomputation benefit |
| A3 − A0 | 18 | 0.0 | No observed incremental recomputation benefit |
| E0 − A0 | 18 | 0.0 | Deadline-only comparator tied A0 |
| N0 − A0 | 18 | +1,918.22 | N0 recomputed more than A0 |

Registered forced-release contrasts:

- H3-0: mean A0 − N0 = −3,123.2 tokens over 20 Groups / 38 cells.
- H3-R: mean A0 − N0 = −6,435.56 tokens over 9 RESPONSIVE Groups / 16 cells.

These are component-level contrasts within the project-side Continuum-style cache-management adaptation. They are not a full-system Continuum-versus-Vanilla-vLLM comparison.

### 3.3 Decision exposure and mechanism limits

**Reference:** [Algorithm exposure audit](experiments/phase3-algorithm-exposure-audit.md).

- 127 forced Entry Release decisions across 39 cells.
- 120 decisions had one candidate; seven had two candidates.
- Thus 7/127 (5.5%) were genuine multi-candidate Entry ordering opportunities.
- A2 had 53 cost-known decisions and 74 `content_unverified` fallbacks; no observed A2 victim-sequence divergence from Native LRU.
- A3 executed its registered path, but selected the same Entry as A1 in all 127 decisions.
- The campaign's zero incremental effects are not evidence of universal algorithm equivalence; they are results under sparse decision exposure and the frozen cohort.

### 3.4 Process deviation and actual-order recovery

**References:** [Final gate/process audit](experiments/phase3-final-gate-audit.md), [actual Native order and E audit](experiments/phase3-actual-order-audit.md).

- Frozen replay enqueue-order conformance: FAIL; only 48/240 Main runs matched the frozen order.
- The 192 mismatching runs form 32 cells where all six arms shared the same non-frozen actual order; no cell had cross-arm-different order.
- Actual-order E was determinate in 40/40 cells and unchanged for 5,760/5,760 request-arm observations.
- Re-running the unchanged Protocol v4 evaluator on the fixed population reproduced the registered effects exactly.
- The historical transition record did not persist a complete G1/G4/Cohort ledger before Main dispatch. Retrospective audits are not execution-time gate passes.

**Required wording:** the replay-conformance deviation remains a FAIL/deviation. The later audits support a bounded paired-effect interpretation under the common observed order; they do not retroactively turn the frozen execution contract into PASS.

**Current adjudication:** the research-branch status remains pending final M1/M4 adjudication. Do not present Phase 3 as fully execution-conformant or M1-final-accepted until that decision is recorded.

## 4. Post-campaign CPU-only research

### 4.1 Stage 0 — A0-Anchored Prefix-State Loss Oracle

**Reference:** [Stage 0 report](experiments/phase3-stage0-oracle-data/stage0-report.md).

- CPU-only, read-only Archive analysis; not a Native cache-state replay.
- 18 Primary Groups / 36 cells complete.
- Seven real competitive decisions were evaluable.
- Avoidable-prefix-loss upper bound = 0 tokens on the current cohort.
- Gate: `STOP_AVOIDABLE_LOSS_MODEL_ON_CURRENT_COHORT`.
- Capacity gains from switching the released chain remain `NOT_EVALUATED`.

**Supported:** the current Archive's seven competitive decisions do not expose positive avoidable-prefix-loss opportunity under this loss-only model.

**Not established:** zero capacity benefit, or that the entire Entry Ordering research direction has no future opportunity.

### 4.2 P2 — future prefix-demand depth predictors

**Reference:** [P2 depth report](experiments/phase3-p2-depth-data/p2-depth-report.md).

- CPU-only offline study; real and constructed-historical scenarios are kept separate.
- Five valid REAL decisions and 106 valid CONSTRUCTED_HISTORICAL scenarios.
- P2-A/B MAE = 134.3 blocks; all five valid REAL decisions flipped, with zero positive-gain flips.
- P2-C MAE = 460.1 blocks; zero flips and zero gain.
- Independent single-decision counterfactual increments are not a joint deployed-policy effect.
- Prefix-demand overlap is not Native APC hit evidence.

**Supported:** prediction error and ranking accuracy do not substitute for positive downstream decision value.

**Not established:** a validated online P2 policy or general real-workload benefit.

### 4.3 Phase 4 Task 1 — Session Continuation identifiability

**Reference:** [Phase 4 session-continuation report](experiments/phase4-session-continuation-data/phase4-session-continuation-report.md).

- 40 Sessions and 480 C1 request rows were reconstructed.
- Event stream has no independent `session_id`; each Program maps to exactly one Session.
- Session Continuation and Program Continuation are therefore observationally equivalent in this Archive.
- The report's continuation results are Program-level proxies, not independent Session Continuation evidence.
- A new study would require explicit session identity, multiple sessions per program (or multiple programs per session), and explicit session-switch lifecycle events.

**Supported:** the current Archive cannot independently identify Session Continuation.

**Not established:** that Session Continuation is unlearnable or unimportant in real Agent workloads.

## 5. Candidate research contributions (not yet final claims)

The following are candidates for the later synthesis. Each requires a separate claim/evidence audit before being promoted into a paper or final report.

1. **System adaptation:** a real-runtime-validated project-side Continuum-style lifecycle/retention adaptation that preserves Native vLLM cache ownership.
2. **Evidence methodology:** separation of logical Entry Release, physical victim selection, APC eligibility/residency, and downstream recomputation, with independent N/E/C derivation and fail-closed evidence joins.
3. **Decision-opportunity analysis:** evidence that nominal policy invocation counts can substantially overstate true multi-candidate decision opportunities.
4. **Local headroom versus online predictability:** Phase 2D demonstrates local headroom in a controlled shared-prefix fixture, while later campaigns show that this opportunity may be sparse or not predictable by the tested signals.
5. **Token-to-serving transfer:** Phase 2E shows that a reduction in recomputation tokens does not automatically produce a corresponding TTFT improvement in a queue-dominated workload.
6. **Data identifiability:** Phase 2C and Phase 4 show why logical labels and incomplete lifecycle identity are insufficient for claims about Native content reuse or Session Continuation.

These are candidate research narratives, not yet accepted contributions. In particular, no current evidence supports claiming that the Cost-Aware algorithms outperform the relevant baseline.

## 6. Evidence gaps and unresolved items

| ID | Gap | Consequence for R1 |
|---|---|---|
| G-01 | Original Continuum paper-run trajectories are not available in the audited public repository | Do not claim exact workload reproduction |
| G-02 | No completed four-system Native / Continuum Official / Continuum Adapted / Cost-Aware campaign | No full-system ranking claim |
| G-03 | Phase 3 has no Static-TTL arm | No Dynamic-TTL versus Static-TTL causal claim |
| G-04 | Phase 3 uses the Native scheduler in all arms | No Phase 3 scheduler-effect estimate |
| G-05 | Physical victim to downstream recomputation attribution remains incomplete in several historical campaigns | Do not claim per-eviction causality without a complete identity chain |
| G-06 | A1 Gate 2 corrected evaluator was not rerun against its same packaged 144-run archive in the M1 closeout environment | Preserve its reported numerical distribution as provisional |
| G-07 | Phase 3 frozen replay enqueue order and transition ledger have recorded deviations | Preserve the FAIL/deviation and pending M1/M4 adjudication |
| G-08 | Phase 4 Archive has no independent session identity | Session Continuation remains not identifiable |
| G-09 | Archive integrity, SHA-256, and evaluator/reproduction checks were already performed during the original campaign closeouts | Reuse and cite those existing audit records; do not repeat completed checks as an R1 workstream. Reopen only a specifically identified conflict or missing artifact |
| G-10 | Main's README/status snapshot is stale relative to the completed Phase 3 research branch | Use branch/commit-specific status, not README alone, as the current record |

## 7. Repository lineage and status snapshot

As checked on 2026-11-14:

- `main`: `18a0a9198403af735350cbbfd9aae20e7b2b39bd`.
- `research/phase3-stage0-oracle`: `69acd43b59eed73484a8538b9836e4cd752aea32`, 16 commits ahead of main and zero commits behind.
- PR #104 (270-run execution) remains open against main.
- PR #105 (Phase 3 null-mechanism analysis) remains open against the Phase 3 execution branch.
- PR #106 (P2 depth study) and PR #107 (Session Continuation feasibility) are merged into the research branch, not main.
- The research branch descends from the PR #104/#105 work and contains the #106/#107 follow-up analyses.

The README and canonical status file on main still carry the earlier 2026-11-10 pre-execution snapshot. The research branch's status file records 270/270 complete and final M1/M4 adjudication pending. This discrepancy must be resolved through an explicit integration/merge sequence; do not silently copy the later status over historical records.

## 8. R1 next actions

1. **Complete the evidence register:** for each campaign, record protocol SHA/version, code SHA, archive SHA, archive availability, environment, independent statistical unit, run count, evaluator revision, final verdict, and exact reproduction command.
2. **Resolve campaign lineage:** especially the separate Phase 2A records and the distinct Phase 2G A1/A2 144-run and 54-run campaigns. Do not infer lineage from phase labels.
3. **Reference completed reproducibility audits:** cite the existing campaign-level archive integrity, SHA-256, and evaluator validation records. Do not rerun them. Only perform a narrow follow-up if R1 identifies a concrete contradiction, missing record, or previously untested evaluator path.
4. **Create a claim matrix:** map each candidate contribution to its direct evidence, inference, hypothesis, and prohibited overclaim.
5. **Write the cross-phase synthesis:** explain the progression from local mechanism headroom to sparse decision exposure and the observed gap between token savings and serving latency.
6. **Only after R1/R2 review:** decide whether any new algorithm experiment is justified. No GPU run, Native smoke, Protocol v5, or production algorithm change is authorized by this ledger.

---

**R1 initial inventory complete only at the document-index level.** Raw-archive independent reproduction, final M1 adjudication, and contribution promotion remain open work.
