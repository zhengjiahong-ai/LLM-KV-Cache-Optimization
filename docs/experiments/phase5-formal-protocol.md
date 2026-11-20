# Phase 5 Formal Experiment Protocol — Six-System Trace-Driven Replay

**Protocol ID:** `phase5.formal_protocol.v1`  
**Status:** `DESIGN_FROZEN_CANDIDATE` — M1 freeze required; no execution authorized.  
**Owner:** M4 (research design); M6 (engineering implementation); M1 (scope and freeze authority).  
**Base main:** `af33bc380e360582c7de9b8a5062ce7ec434d02e`.  
**Phase 3 Protocol v4 and all historical results remain unchanged.**

---

## M1 status addendum (2026-11-19)

M1 accepts this six-system research design and separately approves the limited Dataset Acquisition & Construction work package for SWE-bench Verified and BFCL v4 Web Search. See [M1 Dataset Acquisition & Construction decision](phase5-dataset-acquisition-and-construction.md).

This M1 decision supersedes the original design-stage statements below that Trace Acquisition itself is not authorized. It does **not** supersede the protocol's execution gates or authorize Native/GPU Conformance, Calibration or Formal Campaign. The machine-readable protocol remains `DESIGN_FROZEN_CANDIDATE` with `execution_authorized=false`; system freeze, qualified Cohort/Seal, Native conformance, Calibration, resource authorization and final manifests remain mandatory.

The documentation synchronization PR #125 was merged on 2026-11-19 (merge commit `5e453a6926e3c1092235b2ec2e8b6227a22362f3`); the temporary documentation pause is lifted. The M1 dataset decision permits acquisition and qualification only. It does not change the protocol's six systems, metrics, statistical model, Group definition, sample plan or claim boundaries.

---

## 0. Purpose and non-goals

This protocol defines one formal, trace-driven replay campaign comparing **six systems** on representative multi-turn Agent workloads:

1. **Native vLLM**;
2. **Continuum Official** — the authors' pinned public implementation;
3. **Continuum Adapted (A0)** — the project-side full-system adaptation;
4. **A1 Original Cost-Aware** — the complete original A1 decision ladder;
5. **A3 Suffix-Cost-Aware** — A3's suffix-cost replacement of A1 Step 2, with all other A1 branches retained;
6. **DVA-ER v1** — Downstream-Victim-Aware Entry Release, provisional.

The research question is:

> Under representative multi-turn Agent workloads, which Cost-Aware candidate (A1, A3 or DVA-ER), evaluated against the same A0 reference, produces a distinguishable decision space, changes the Native LRU victim set, reduces eviction-induced recomputation, and improves measured serving metrics?

This protocol does **not**:

- reproduce the original Continuum paper exactly;
- treat the official public preview as the complete paper implementation;
- pool Phase 3 fixed-pressure results with Phase 5 trace-driven results;
- claim isolated mechanism causality from a whole-system comparison;
- use the same formal data to select a winner and then confirm it;
- authorize GPU, Native, or Formal Campaign execution. Trace Acquisition is separately governed by the dated M1 status addendum above.

The first formal campaign is **trace-driven replay only**. Closed-loop Agent execution is excluded and requires a separate protocol.

---

## 1. Fixed definitions

### 1.1 Workload hierarchy

| Unit | Definition | Independence / pairing |
|---|---|---|
| **Program** | One logical Agent task/workflow identity (repository task or BFCL task). | Programs are the sampling units within a Group; not independent across systems. |
| **Session** | One replay execution of a Program, with a frozen source trace, token IDs, tool gaps and identity. | One Session per Program in this campaign. Multiple Sessions would be a separate design. |
| **Turn** | One model request within a Session; one Program request boundary. | Not an independent sample. |
| **Workload Group** | A frozen bundle of **4 independent Programs** with their Sessions and one frozen program-arrival realization. | **Primary independent statistical unit.** |
| **Stratum** | Workload family: `SWE_BENCH` or `BFCL_WEB_SEARCH`. | Pre-registered; analyzed separately and combined only by the frozen weighting rule. |

A request row, turn, tool call, runtime repeat or pressure event is **never** an independent sample.

### 1.2 Six systems

| ID | System | Exact definition | Allowed differences |
|---|---|---|---|
| `NATIVE` | Native vLLM | Unmodified vLLM `0.27.1`; Native APC/LRU, scheduler, BlockPool, no project hooks; same model/tokenizer/pool/block size/`max_num_seqs` as A0/A1/A3/DVA-ER. | Only passive evidence instrumentation; no behavior-changing patch. |
| `CONTINUUM_OFFICIAL` | Continuum Official Public Implementation | Pinned authors' public repository at `316a58794a6ff86b216e579b74fd56ed0c5a911f` (M1 must re-freeze if a newer reviewed snapshot is chosen); run as released, with its own documented environment. | Its own upstream vLLM base and scheduler; **not** the full paper estimator. If the base differs, it is a separate environment stratum and a documented confound. |
| `CONTINUUM_ADAPTED` | Continuum Adapted (A0) | A0-derived **full-system** adaptation: project Dynamic TTL, retention/Entry Release, native physical victim path, and project program-aware scheduler enabled only after scheduler conformance. Common reference for A1/A3/DVA-ER. | Project-side scheduler/TTL implementation; no Cost-Aware policy. If scheduler conformance is not accepted, rename `CONTINUUM_ADAPTED_CACHE_ONLY`. |
| `A1_ORIGINAL` | A1 Original Cost-Aware | Exact frozen Phase 3 A1: complete original decision ladder, original cost and reuse-probability proxies; no simplification; only Entry Release policy differs from A0. | A1 policy only. Physical victim path remains Native LRU. |
| `A3_SUFFIX` | A3 Suffix-Cost-Aware | Exact frozen Phase 3 A3: replaces only A1 Step 2 with `L(X)=q_X*prefill_X*S_X/m_X`; all other A1 branches retained. Not an independent decision system. | A3 Step 2 only; other branches identical to A1. Physical victim path remains Native LRU. |
| `DVA_ER_V1` | DVA-ER v1 | Downstream-Victim-Aware Entry Release: simulate the actual Native LRU victim set for each legal Entry candidate, score victim-set risk, select lowest risk, tie-break to A0. | New Entry policy only; requires CPU candidate-selection gate and M1 freeze before formal. |

**Official boundary:** the public repository is a released Continuum-style implementation without the full paper estimator/experiment bundle. Results are a system-level comparison, not exact paper reproduction or isolated mechanism comparison.

**Candidate family boundary:** A1/A3 are frozen legacy implementations; DVA-ER is a provisional new hypothesis. The three are not a winner-selection pool. They are pre-registered independent comparison objects under one decision snapshot, one legal candidate set, one Native LRU state and one Workload Trace. The DVA-ER CPU gate must pass before it is frozen; if it fails, the six-system campaign does not silently drop to five arms — M1 decides.

### 1.3 Control variables

Within a comparison stratum, the following must be identical or explicitly declared as a system-specific confound:

- model and tokenizer revision;
- chat template and exact prompt token IDs;
- generation configuration (`temperature`, `top_p`, `top_k`, `seed`, `max_new_tokens`, stop conditions);
- KV capacity, block size, `max_model_len`, `max_num_seqs`;
- request identities, Program/Turn order, tool gaps, arrival realization;
- GPU class and driver/runtime versions where possible;
- timeout, failure, right-censoring and cleanup rules;
- evidence evaluator and metric definitions.

Official-specific environment differences are allowed but must be recorded as `ENVIRONMENT_CONFOUND`; they cannot be attributed to Continuum logic alone.

---

## 2. Workload design

### 2.1 Sources and strata

Primary source families:

- **SWE-Bench Verified** — coding Agent Sessions acquired with the pinned mini-swe-agent path; source task revision `c104f840cc67f8b6eec6f759ebc8b2693d585d4a` (or a frozen newer revision).
- **BFCL v4 Web Search** — tool-use Agent Sessions whose search results are frozen as deterministic fixtures; live web search is not admissible because content and latency drift.

Optional secondary source (not part of the primary six-system estimand unless separately frozen): Multi-SWE-Bench/OpenHands public trajectories after schema/license audit.

Each source must be sealed with:

- dataset/repository identifier and immutable revision;
- task row identifier and source content hash;
- license identifier and redistribution/reference terms;
- agent/model/tokenizer versions used to acquire the trace;
- exact prompt/token IDs and chat template hash;
- tool implementation and fixture hashes;
- observed submit/completion/tool-gap clocks and time domain;
- natural-terminal or right-censoring status.

A public benchmark row is **L0 task input**, not a trace. A paper aggregate is not a trace. A generated Poisson arrival is a controlled load, not an observed production arrival.

### 2.2 Trace qualification contract

A Session is eligible for the formal cohort only if all hold:

1. source messages and tool calls are complete and reconstructable;
2. exact rendered prompt token IDs are reproducible under the pinned model/tokenizer/chat template;
3. Program, Session, Turn and request identities are unique and monotone;
4. within-Session Turn order and tool gaps are preserved;
5. the Session ends in a natural accepted terminal or is explicitly right-censored; no context-limit failure is converted into a successful request;
6. no request exceeds the frozen context limit (`32,768` tokens) and the Session has at most the frozen turn cap;
7. all tool outputs used by the trace are frozen and hash-bound;
8. source license/provenance passes review;
9. no A0/A1/A2/A3/Cost-Aware outcome was used to include or exclude the Session.

Qualification is outcome-blind. The full field contract is in `phase5-workload-qualification-contract-v1.json`.

### 2.3 Group construction and sample plan

- **4 Programs per Group**, one Session per Program.
- Programs are selected before any system outcome is observed, with repository/task diversity constraints.
- Each Group is a matched bundle: the same 4 Sessions, prompt IDs, turn order and arrival realization are replayed in every system and repeat.
- Strata: SWE-Bench and BFCL Web Search.
- Planned independent Groups per stratum: **min 8, target 12, max 16**.
- Calibration Groups per stratum: **4**, disjoint from the formal Groups and never reused.
- Formal repeats per Group/System: **2**; calibration repeats: **3**.
- Six systems per Group; formal runs = **6 × N × 2 × 2 = 24N** (192 at min, 288 at target, 384 at max). Calibration runs = **6 × 4 × 3 × 2 = 144**.
- A Group is `COMPLETE` only if all 4 Sessions and all required requests produce valid evidence in every system/repeat.
- Every qualified Session has **at least 4 Turns and at most 16 Turns**. This preserves the Phase 5A minimum multi-turn qualification and avoids single-turn task rows.
- The frozen generation configuration is: `temperature=0.0`, `top_p=1.0`, `top_k=0`, `seed=20261201`, `max_new_tokens=128`, `stop=[]`, `ignore_eos=false`. It is identical across systems and repeats.
- Every request must satisfy `prompt_tokens + max_new_tokens <= max_model_len (32,768)`. A request that cannot satisfy this is excluded at qualification; it is never truncated into a valid request.
- A right-censored source Session is included in the primary analysis if every observed Turn is valid; its unobserved future Turns are not imputed and do not create synthetic requests. A system failure is never relabeled as source right-censoring.

The target sample size is not fixed at design time; it is selected by the pre-registered calibration algorithm in §5. The max cap prevents an unbounded campaign. If the required N exceeds the cap, the campaign is explicitly underpowered; no mid-campaign extension.

### 2.4 Arrival and tool-gap preservation

- Within each Session, preserve the source Turn order and observed tool gaps. Do not resample a Session's internal timing.
- Across the 4 Programs in a Group, program starts use **Frozen-Poisson** arrival:
  - one pre-sampled realization per Group;
  - fixed rate λ per stratum, fixed integer seed and generator identity;
  - the realized offsets and their SHA-256 are frozen before any system runs;
  - all systems and repeats use the **same** realization.
- Primary design: `FROZEN_POISSON` program starts with within-Session empirical tool gaps.
- Sensitivity: `EMPIRICAL_ALIGNED` starts when a qualified multi-session source exists; `FIXED_STAGGER` as a controlled negative-style comparison.
- The default λ is a design parameter, not an observed production rate. It must be frozen by M1; a provisional value is recorded in JSON and must not be presented as natural concurrency.

### 2.5 Cost-Aware candidate family and unified evaluation

Phase 5 evaluates **three pre-registered Cost-Aware candidates**, not one winner-selected arm:

- **A1 — Original Cost-Aware Entry Release:** preserves the complete original A1 decision ladder, original cost estimates and reuse-probability proxies. No simplification.
- **A3 — Suffix-Cost-Aware Entry Release:** preserves the implemented `L(X)=q_X×prefill_X×S_X/m_X`; it replaces only A1 Step 2, and all other A1 branches remain identical. It is not an independent decision system.
- **DVA-ER v1 — Downstream-Victim-Aware Entry Release:** a new hypothesis that simulates the actual Native LRU victim set and scores the victim set's downstream reuse risk.

A0 is the common reference. All three candidates use the **same Decision Snapshot, legal candidate set, Native LRU state and Workload Trace**. No candidate-specific data selection, no separately favorable trace subset.

#### Candidate comparison matrix

| Dimension | A1 | A3 | DVA-ER |
|---|---|---|---|
| Input signals | original A1 cost, reuse-probability proxy, full A1 branch state | `q_X`, `prefill_X`, `S_X`, `m_X`, plus A1 state for non-Step-2 branches | A0 candidates, complete BlockPool/FreeKVCacheBlockQueue, refcount/eligibility/protection, active follow-up chains, pending tool gap |
| Scoring objective | original frozen A1 cost | suffix cost `L(X)` | downstream Native LRU victim-set risk |
| Source of decision difference | original model and full A1 ladder | A1 Step 2 replacement by suffix depth | actual victim sequence, not Entry-local cost |
| Victim Set modeling | none; Native LRU follows Entry release | none; Native LRU follows Entry release | full Native LRU victim sequence simulation |
| Evidence requirements | A1 branch inputs, scores, legal set, Native outcome | suffix components, A1 branch state, Native outcome | complete pool/free-queue/refcount/protection, active chains, full victim sequence, A0 tie-break |
| Main applicability | original cost/reuse proxies discriminate among legal candidates | suffix depth varies and is measurable | victim set and active follow-ups are observable and diverge |
| Failure/fallback | original A1 fallback branch; fail closed on missing evidence | A1 branch fallback; fail closed on missing depth | A0 tie-break only on equal loss/no legal candidate; fail closed on missing state |

#### Unified evaluation stages

**Stage 1 — Decision Space Evaluation.** On the same snapshot, record:
`Legal Candidate Count Distribution`, `Multi-candidate Decision Rate`, `Candidate Score Distribution`, `Pairwise Rank Inversion`, `Selection Divergence`, `Victim Set Divergence`, `Decision Branch Coverage`, `Evidence Coverage`, `Fallback Rate`.
It must answer: whether all three have a distinguishable decision space; which score factors explain A1-vs-A3; whether DVA-ER selects differently; whether Entry selection divergence changes the Native victim set; and when missing evidence prevents a valid decision. **Entry Selection Divergence alone is insufficient**; the Native Physical Victim Set Divergence is mandatory.

**Stage 2 — Full-Trajectory Counterfactual Replay.** Each candidate is replayed over the full trajectory, recording `Recomputed Tokens`, `Eligible Prefix Tokens`, `Native Cached Prefix Tokens`, `Physical Victim Sequence`, `Downstream Reuse` and `Policy Overhead`. Every counterfactual is a complete replay. Local decision gains are never summed into a trajectory result, because a decision changes later state, candidates and victim outcomes.

**Stage 3 — Mechanism and Correctness Validation.** Separate validation of:
A1 full implementation/historical reproduction; A3 suffix calculation and non-Step-2 A1 branch consistency; DVA-ER victim simulation and online-input legality; A0 comparability; determinism, tie-break and fail-closed behavior.

**CPU fixtures** cover: multiple legal candidates; score rank inversion; different victim set under different releases; same Entry ranking but different victim risk; missing evidence; unavailable future information; Native LRU tie-break. These are contract fixtures for correctness, not workload-benefit evidence. The executable fixture set is `configs/phase5/fixtures/phase5-candidate-evaluation-cases.json`; it must be expanded into M6 unit tests before formal execution.

#### Data partitions and confirmation boundary

| Partition | Permitted use | Prohibited use |
|---|---|---|
| Phase 3/4 historical archive | historical reproduction, mechanism diagnosis, exploratory analysis | independent confirmatory proof; the seven old competitive decisions cannot establish effect |
| CPU fixtures | correctness, ranking ability, mechanism boundaries | workload-benefit claim |
| New formal cohort | independent confirmatory evaluation; sealed before unblinding | algorithm modification after results; selecting a winner then reusing the same data to confirm it |

The three algorithms' implementations, parameters/H, input field set and hash must be frozen before the formal cohort is unblinded. No post-unblinding algorithm change. If all three enter the GPU campaign, they are pre-registered independent comparison objects; multiplicity, sample size and budget are recalculated below.

#### DVA-ER mandatory requirements

- `H = 60 s` lookahead for a pending tool gap; sensitivity `30/120 s`. `H` weights only blocks on an active follow-up chain whose pending gap is observable in the already-armed controller state.
- Active follow-up chain identity is known before the decision; no future Turn content or future reuse outcome.
- Pending tool gap is the armed timer/next-arrival state at decision time, not a future label.
- Complete Native BlockPool / FreeKVCacheBlockQueue state, refcount, eligibility and protection changes.
- Full Native LRU victim sequence, not only a selected victim set.
- A0 tie-break and Native LRU simulation must be reproduced.
- Missing evidence → fail closed; no silent zero fallback.

DVA-ER remains `PROVISIONAL_NOT_FROZEN` until a **correctness-only CPU gate** passes:

- Native LRU victim sequence simulation is correct;
- A0 tie-break/selection is reproduced;
- no future Turn or future reuse information is used;
- every required input is observable and complete;
- fail-closed behavior is correct;
- independent fixtures reproduce the expected decision differences and mechanism boundaries.

Historical Phase 3/4 full-trajectory gain **may be reported**, but a positive historical gain is **not** a gate. The seven historical decisions are exploratory/reproduction material, not confirmatory evidence for DVA-ER. If a separate development dataset is used, it must be disjoint from the formal cohort and may inform implementation only. If the correctness gate fails, do not freeze it; M1 decides whether to run a five-arm campaign or stop. The protocol does not silently drop an arm.

---

## 3. Replay protocol

### 3.1 Trace-driven semantics

1. Materialize the frozen Session prompts and token IDs.
2. Build the frozen N-Session replay plan from the Group.
3. Dispatch requests at the frozen logical offsets; preserve within-Session order and tool gaps.
4. Record planned, dispatch, Native submission, EngineCore queue/schedule, first output, frontend terminal, Native terminal, and adapter completion in separate clock domains.
5. Do not infer one from another.
6. Do not create a second EngineCore output consumer or a full drain.
7. Do not replace Native scheduler/BlockPool/APC semantics.

Closed-loop Agent behavior (where output determines the next request) is out of scope. The replayed next Turn is exogenous and frozen, even if the model's generated text would differ.

### 3.2 Actual enqueue order gate

For every run, compare the **complete actual `VLLM_REQUEST_SUBMITTED` sequence** against the Workload Seal, not a prefix, set, or event-log adjacency:

- exact global sequence;
- exact request set and uniqueness;
- exact per-Program order;
- no unknown or missing business request;
- pressure identities excluded only by the reserved pressure namespace;
- cross-system equality of the actual sequence for the same Group/arrival realization.

Dispatch must be serialized in frozen order (or an equivalent barrier must prove the order is the only admissible one). Planned offsets alone do not guarantee actual enqueue order.

### 3.3 Right-censoring, failure and truncation

- Source right-censoring is a property of the trace, not a system failure. It is preserved as a Session-level flag; no synthetic continuation is invented.
- A run that times out, loses Native identity, produces ambiguous terminal evidence, or fails the enqueue gate is `FAIL_CLOSED`; the artifact is archived, not replaced.
- A truncated prompt or context-limit attempt is excluded at qualification; it is never converted to a successful request or a zero.
- No automatic retry. A replacement run requires a new M1 decision.
- Missing data is not imputed from another system, repeat, or request.

### 3.4 Execution order, isolation and timing

- **Arm order:** six systems within each Group are executed in a pre-registered **balanced Latin-square** order. The order is seeded before outcomes, balanced by Group/System/position, and recorded in the manifest. Calibration uses a fixed random permutation; no outcome-based reordering is allowed.
- **Per-run isolation:** every run uses the same unified initialization/cleanup procedure: new process, new EngineCore, `VLLM_ENABLE_V1_MULTIPROCESSING=0`, GPU memory reset, empty-cache preflight, no cross-run KV/APC reuse. A failure to isolate the run is `FAIL_CLOSED`.
- **Preheat:** **NONE**. No system receives a warmup and no warmup state may be reused. `warmup_evidence_required=false`; the recorded evidence is the empty-cache preflight and the absence of warmup, not a warmup log.
- **Unified environment:** all six systems use the same GPU, driver, CUDA, model/tokenizer cache, engine initialization sequence and archive path; official-specific environment differences are allowed only as declared `ENVIRONMENT_CONFOUND` and never as an implicit preheat advantage.
- **Unique TTFT origin:** TTFT is measured from `CLIENT_DISPATCH_ACCEPTED` to `FIRST_OUTPUT_TOKEN`. Arrival-to-first-token and queue delay are separate metrics; they are not substituted for TTFT.
- **Right-censored throughput/completion:** throughput uses completed observed requests over the observed window (`first arrival` to `last observed terminal`). Completion time is reported only if every scheduled request has a terminal; otherwise it is `CENSORED_INCOMPLETE`, not imputed. Right-censored Sessions do not add future requests to the run.

---

## 4. Metrics

### 4.1 Primary metric

**Primary:** `recomputed_tokens_E_minus_C = Σ_r (E_r - C_r)` per run/Group, in tokens.

- `N_r`: Native prompt tokens;
- `E_r`: independently derived eligible reusable-prefix tokens;
- `C_r`: Native cached-prefix tokens;
- `E-C` is the Protocol v4 recomputation metric;
- `N-C` is actual prefill work and is secondary/descriptive only;
- `E` is never filled from `C`; missing/indeterminate evidence fails the request/run.

### 4.2 Secondary metrics

- TTFT: `FIRST_OUTPUT_TOKEN - CLIENT_DISPATCH_ACCEPTED`; arrival-to-first-token and queue delay are separate; P50/P95 per Group.
- End-to-end request latency: terminal minus dispatch/arrival; P50/P95.
- Throughput: requests/second and generated tokens/second over the run window.
- Completion time: first arrival to last terminal.
- Cache reuse: `C/E` (primary reuse ratio) and `C/N` separately; zero denominators are `NOT_APPLICABLE`.
- GPU memory: peak allocated and reserved MiB, sampling interval and source.
- Admission/concurrency: queue length, peak Native inflight, queued-to-scheduled delay.
- Policy overhead: policy CPU wall time per decision and total; `ms/decision` and `s/run`.
- Capacity: peak KV blocks used, evictions, admission rejects, if observable.

### 4.3 Mechanism diagnostics

- Candidate Exposure: decision count, multi-candidate count, fully scored candidate count, missing evidence count.
- Decision Divergence: pairwise system selection disagreement on identical decision states.
- Physical Eviction: matched/unmatched/hashless victim blocks, per decision.
- Downstream Reuse Opportunity: later requests that touch a candidate chain; **descriptive only**; not causal.
- `physical_causal_attribution` and `downstream_recompute_attribution` remain `NOT_ESTABLISHED` unless the complete per-decision chain is observed.

**Candidate evaluation layers (details in `phase5.candidate_evaluation.v1`):**

- **Stage 1:** legal-candidate count distribution, multi-candidate decision rate, candidate score distribution, pairwise rank inversion, selection divergence, victim-set divergence, decision-branch coverage, evidence coverage, fallback rate. Entry selection divergence alone is not sufficient; the Native Physical Victim Set must also be compared.
- **Stage 2:** full-trajectory recomputed tokens, eligible prefix tokens, Native cached prefix tokens, physical victim sequence, downstream reuse, policy overhead. No summation of local decision gains.
- **Stage 3:** A1 historical reproduction, A3 suffix/A1 branch consistency, DVA-ER victim simulation/input legality, A0 comparability, determinism/tie-break/fail-closed. CPU fixtures are correctness evidence only, not workload benefit.

### 4.4 Units and missingness

- Statistical unit: Workload Group (not request, turn, repeat, or pressure event).
- Per-run metrics aggregate requests within the run; repeats aggregate within Group/System; Systems compare within Group.
- Missing/indeterminate primary evidence: Group/System is `INCOMPLETE`; no imputation or zero substitution.
- Secondary timing metrics are reported only from observed timestamps with comparable semantics.

The full contract is in `phase5-metrics-contract-v1.json`.

---

## 5. Calibration and sample size

### 5.1 Calibration and variance components

- 4 Groups per stratum (8 total), disjoint from formal Groups.
- 6 Systems × 4 Groups × 3 repeats × 2 strata = **144 calibration runs** (plus startup).
- Calibration estimates **two distinct variance components**:
  - `σ_between²`: Group-level variability of the paired difference;
  - `σ_repeat²`: within-Group run-to-run noise.
- **Fixed pre-registered model:** `d_{g,r,s} = μ + τ_s + b_{g(s)} + ε_{g,r,s}`, with stratum fixed effect `τ_s`, Group random effect `b_{g(s)}` and repeat residual `ε_{g,r,s}`. Variance components are common across strata; there is **no homogeneity test and no dynamic pooling switch**. Repeats are never independent Groups.
- With only 4 Groups per stratum, the per-stratum Group-level variance has df=3; the common model has 8 Groups and df=7. Both are small-sample estimates and are reported with uncertainty.
- For a future formal Group mean with 2 repeats, `σ_d² = σ_between² + σ_repeat² / 2`. The calibration repeat count (3) is not substituted for the formal repeat count (2).
- **Two strata:** the common mixed model includes a fixed stratum effect; **no homogeneity test is used to choose a pooling rule**. For sizing, the variance for each stratum/contrast is the larger of (a) the common-model variance upper bound and (b) that stratum's own one-sided 80% bootstrap upper bound. This is fixed before calibration and is conservative.
- **Negative variance components:** a negative method-of-moments point estimate is truncated at zero for reporting only; the bootstrap upper bound is retained for sizing. A zero point estimate is never treated as proof of no variance.
- **Small samples:** no normal approximation; use noncentral t with the relevant df and bootstrap uncertainty. If the upper-bound variance makes `n_required > 16`, the campaign is underpowered/stop; do not select a smaller variance to rescue N.
- **Eight contrasts** share arms: six candidate contrasts (`A1−A0`, `A3−A0`, `DVA−A0`, `A3−A1`, `DVA−A1`, `DVA−A3`) plus two system-context contrasts (`Native−A0`, `Official−A0`). Calibration estimates the full **8×8 covariance** of Group-level paired differences, projected to positive semidefinite if needed. Candidate-family sizing uses the maximum candidate-contrast upper-bound variance; the covariance is used for simulation/interval sensitivity.

### 5.2 MDE, power and primary multiplicity families

- **Candidate mechanism family (6 per stratum):**
  `A1−A0`, `A3−A0`, `DVA−A0`, `A3−A1`, `DVA−A1`, `DVA−A3`.
- **System context family (2 per stratum):**
  `Native−A0`, `Official−A0`.
- The two families are pre-registered separately. Holm is applied **within each family and within each stratum** at family-wise α=0.05. Candidate claims and system-context claims are not pooled into one significance claim.
- For sample size, the conservative candidate-family per-test α is `0.05/6 ≈ 0.008333`; the system family has only two tests and does not drive N. N is the maximum required across the six candidate contrasts.
- Power = 0.80.
- **MDE order:**
  1. freeze the MDE formula and 512-token floor before calibration;
  2. compute the MDE value from the calibration Native Group mean;
  3. freeze that numeric MDE before formal execution.
  The MDE is not chosen or changed after seeing formal outcomes.
- `MDE = max(512 tokens, 5% × calibration Native Group mean recomputed tokens)`.
- Sample size uses the **noncentral t distribution**, not a z approximation:
  `n_required = min n such that power(n, α_per_test, σ_d, MDE) ≥ 0.80`, df = n−1.
- `N_stratum = clamp(ceil(max_contrast_n_required), 8, 16)`.
- If `max_contrast_n_required > 16`, the campaign is `UNDERPOWERED`; M1 must either accept that status, authorize a larger budget, or stop. It is not silently extended.
- If `n_required < 8`, N remains 8 and the variance-estimate uncertainty is reported; the 8-Group minimum is a design floor, not a claim that 8 is sufficient.
- If calibration is unavailable/incomplete, formal execution is not authorized.
- No optional stopping, no peeking, no sample-size change after formal data collection begins.

### 5.3 Resource budget

- Planned runs: calibration **144** + formal **192–384** (6 systems × N × 2 repeats × 2 strata, N=8..16; total **336–528** runs). The run count is unchanged.
- Per-run hard timeout 600s, shutdown grace 60s; reservation window 1800s.
- `336 × 600s = 56.0 GPU-hours` before startup/restart/archive/evaluator; `528 × 600s = 88.0 GPU-hours`.
- Resource forecast is **per system**, with explicit timing boundaries:
  - `Tcal_s`, `Tformal_s`: first dispatch to last terminal; excludes process start, engine init and archive;
  - `startup_s`: process start + engine init + model load (preheat NONE);
  - `restart_s`: teardown + relaunch per run when applicable;
  - `archive_s`: evidence write/hash close;
  - `evaluator_s`: metric/gate evaluation.
  Each is measured per system and archived with the calibration report.
- Formula:
  ```text
  projected_hours =
    (1 + 0.10) × Σ_s [
      (24×Tcal_s + 4N×Tformal_s
       + (24+4N)×(startup_s + restart_s + archive_s + evaluator_s)) / 3600
    ]
  ```
  where `s` is the six systems, 24 is calibration runs/system, `4N` is formal runs/system, and 0.10 is the **only** failure reserve. There is no second 1.20 overhead factor.
- At the 600s ceiling, the formula gives **61.6–96.8 GPU-hours** including the 10% reserve.
- The **72–112 GPU-hour figure is an M1 authorization/ reservation ceiling, not the direct formula output**. It adds contingency for measured startup/restart/archive/evaluator uncertainty; the measured projection must fit ≤112h before authorization.
- If the forecast cannot support N=8 per stratum within the available budget, the campaign is `NOT_FEASIBLE`; **do not run below minimum N**. If the formula requires more than the available budget, stop and return to M1; do not automatically reduce N.
- If projected >112h, stop and return to M1 for a new budget authorization; do not silently exceed or compress the sample.

The full contract is in `phase5-calibration-sample-size-contract-v1.json`.

---

## 6. Statistical analysis

### 6.1 Primary analysis

For each stratum and contrast:

1. aggregate requests to run totals;
2. average repeats within Group/System;
3. compute paired Group difference for the contrast, e.g. `d_g = metric(A1,g) - metric(A0,g)`;
4. report mean difference, median, 95% CI, and relative effect vs the contrast reference;
5. use Group-level paired bootstrap (10,000 resamples, fixed seed), paired permutation and paired t as pre-registered analyses; report all three consistently and do not select the test by result;
6. use the calibration-derived 8×8 contrast covariance as a simulation/interval input, not as a substitute for the Group-level paired analysis;
7. report stratum-specific results; no combined-stratum primary estimate and never pool requests.

### 6.2 Multiplicity

- Candidate mechanism family: **6 contrasts × 2 strata**; Holm within each stratum at family-wise 0.05.
- System context family: **2 contrasts × 2 strata**; Holm within each stratum at family-wise 0.05.
- The two families are separate pre-registered claim families. No combined 8-test significance claim and no winner-selection-then-confirmation.
- Secondary metrics: BH-FDR 0.05, explicitly exploratory; confidence intervals are descriptive.
- Mechanism diagnostics: descriptive, no multiplicity-adjusted causal claim.
- The combined-stratum estimate is a secondary summary; it does not add a primary test or rescue a failed stratum.

### 6.3 Failure/missing/censoring

- Complete-case Groups only for the primary; report incomplete Groups and reasons.
- Source right-censored Sessions remain in the Group if all observed requests are valid; censoring is a Session-level covariate/sensitivity stratum. The primary includes them; the sensitivity analysis repeats the estimate without censored Sessions. Unobserved future Turns are never imputed or counted as missing system requests.
- Failed/truncated runs are archived and do not trigger retries.
- No imputation across systems or repeats.

### 6.4 Sensitivity

- SWE-Bench vs BFCL separately.
- Censored vs non-censored Sessions.
- Arrival realization seeds/rates.
- Official environment-compatible vs incompatible subgroup.
- Excluding any Group with policy/failure evidence anomalies.
- Effect of repeat aggregation (first repeat vs mean) as a noise diagnostic.

---

## 7. Claim boundaries

### 7.1 Mechanism claims

Supported only if all of the following are observed:

- a system selects a different legal candidate;
- the physical victim set changes;
- a downstream request demonstrably reuses/needs the affected chain;
- the recomputation measurement attributes the change through a complete identity chain.

The current Phase 3/Phase 5 evidence does **not** establish the per-decision physical→downstream causal chain. Diagnostics may show association; they must not be written as established causality.

### 7.2 System claims

The six-system comparison supports **whole-system differences** under the frozen workload and environments. It does not isolate which mechanism caused a difference. A1/A3/DVA-ER are compared on the A0 foundation, but official-vs-adapted and Native-vs-adapted comparisons remain confounded by implementation, software base, estimator scope and scheduler.

### 7.3 Token vs serving claims

A recomputation-token improvement does not by itself prove TTFT/throughput/completion-time improvement. Serving claims require the measured serving metrics and comparable clocks. Token counts are not FLOPs or hardware performance.

### 7.4 Descriptive-only cases

- official environment incompatibility;
- underpowered or incomplete Groups;
- right-censored-only subgroups;
- constructed/controlled arrival realizations;
- candidate exposure without divergence;
- any result where per-decision causality is incomplete.

---

## 8. Campaign manifest and evidence

Every formal run must produce a manifest binding:

- protocol ID/version/hash;
- system ID and exact source/environment revision;
- workload seal hash;
- arrival realization hash;
- model/tokenizer/generation/engine configuration hashes;
- execution-order index, engine instance identity, isolation preflight and preheat mode;
- run ID, Group/Session/Trace IDs, repeat index;
- actual enqueue sequence hash;
- lifecycle/terminal/pressure/exposure evidence hashes;
- metric record and evaluator version;
- status (`PASS`, `FAIL_CLOSED`, `INCOMPLETE`, `UNDERPOWERED`);
- archive SHA-256 and timestamp.

The manifest schema is `phase5-campaign-manifest-v1.schema.json`.

---

## 9. Entry gates before any GPU run

Formal execution is blocked until all are accepted:

1. **G0 — Protocol freeze:** M1 accepts this protocol and its JSON/contracts.
2. **G1 — Workload acquisition:** qualified traces/Seals exist; BFCL search fixture frozen; licenses/provenance accepted.
3. **G2 — System freeze:** six exact system revisions/configs (A1/A3/DVA-ER included), official compatibility audit, and DVA-ER CPU candidate-selection gate.
4. **G3 — Replay conformance:** N-Session event-driven replay, actual enqueue gate, serialized dispatch, pressure and terminal evidence validated; Phase 5E Part A must pass or be explicitly superseded.
5. **G4 — Calibration:** 144 six-arm calibration runs complete and analyzed with the pre-registered algorithm.
6. **G5 — Resource authorization:** GPU budget, run count, timeout, archive and no-retry rules accepted.
7. **G6 — Manifest/evaluator dry run:** CPU validation of manifest, metrics and evidence joins.

No formal run may start while any gate is unresolved.

---

## 10. Compatibility with Phase 5A–5E and M6 interface

### 10.1 Existing assets reused

- Phase 5A `phase5_replay.py`: N-Session plan, Workload Seal, enqueue gate, capacity proof, Candidate Exposure contract.
- Phase 5B `phase5_native_async.py`: event-driven controller, async backend contract, pressure contract, dual lifecycle.
- Phase 5C `phase5_vllm_api.py`: API feasibility and identity/terminal semantics.
- Phase 5D `phase5_asyncllm_adapter.py`: pinned AsyncLLM adapter, dual-terminal lifecycle, EngineCore proxy, pressure executor, identity binding.
- Phase 5E plan: four-Program conformance fixture, Part A/Part B split, exact order/pressure/lifecycle gates.
- Phase 3 Protocol v4/evaluator: N/E/C definitions, missing/fail-closed semantics, group-level statistical conventions.

### 10.2 M6 interfaces to implement

1. `Phase5FormalProtocolLoader` — load JSON, validate schema/contract hashes, reject non-frozen/unauthorized.
2. `WorkloadAcquisition/Seal` — produce qualified traces and `phase5.workload_seal.v1`.
3. `SixSystemRunner` — instantiate Native/Official/A0/A1/A3/DVA-ER under the manifest; no self-authorization.
4. `CandidateEvaluation` — unified Decision Snapshot, Stage 1/2/3 metrics, divergence and victim-sequence joins.
5. `SystemAdapter` — `prepare`, `submit`, `poll`, `execute_pressure`, `native_events`; no full drain.
6. `EvidenceRecorder` — planned/dispatch/Native/scheduler/output/terminal/pressure/exposure events with clock domains.
7. `MetricEvaluator` — N/E/C, recomputation, TTFT/latency/throughput/memory/overhead; fail closed.
8. `CalibrationAnalyzer` — 6-arm variance, 8×8 contrast covariance, MDE, N; immutable output.
9. `CampaignManifestWriter` — schema-conformant manifest and archive hashes.
10. `AnalysisPipeline` — Group-level paired statistics, two Holm families, bootstrap and sensitivity; no request-level inference.

### 10.3 Current blockers against Phase 5A–5E

- N-Session Native runner and incremental polling are not yet GPU-proven.
- PR #124 integrates the production-shaped Phase 5E Part A runner and CPU/Mock execute→gate→archive path. Part A Native/GPU conformance remains `NOT_RUN`; Part B remains `NOT_READY`.
- M1 has approved the limited BFCL acquisition work package; the exact immutable revision, third-party terms, acquired traces and frozen fixture evidence remain outstanding.
- DVA-ER v1 is provisional and has not passed the CPU candidate-selection gate; A1/A3 are frozen legacy implementations; no three-candidate formal arm set is fully frozen.
- Candidate-family evaluation contracts and the six-system CPU/Mock campaign path are integrated by PR #124; live Native replay and GPU evidence remain unverified.
- Official compatibility/environment audit is not complete.
- Calibration/formal GPU budget is not authorized.

These are explicit entry gates, not assumptions.

---

## 11. Remaining freeze decisions and execution gates

| ID | Decision | Options / cost | Effect if unresolved |
|---|---|---|---|
| U1 | DVA-ER formal candidate selection | A1/A3 remain frozen legacy; DVA-ER v1 has 28 focused CPU correctness tests, but the separate candidate-selection gate and formal M1 freeze remain outstanding. If it fails, M1 decides whether to stop or revise the arm set. | DVA-ER cannot enter the formal six-system campaign |
| U2 | Continuum Adapted scheduler conformance | Scope is defined as the full A0 system with program-aware scheduler enabled only after conformance; if it fails, the arm must be relabelled `CONTINUUM_ADAPTED_CACHE_ONLY`. | Final A0 identity/label depends on conformance evidence |
| U3 | Continuum Official compatibility | Use the pinned public implementation and its documented environment; audit actual compatibility and record any upstream environment difference as a system-level confound. | Official comparison may be descriptive-only if compatibility is not established |
| U4 | BFCL source and fixture acceptance | Acquisition direction is M1-approved; exact immutable revision, third-party content terms, raw search responses and fixture hashes must be reviewed and sealed. | BFCL stratum remains unqualified until evidence is accepted |
| U5 | Arrival parameter freeze | The design candidate specifies `FROZEN_POISSON`, λ=0.1 Program/s and seed `20261201`; JSON still marks λ provisional and requires explicit M1 freeze before Workload Seal. | Arrival realization cannot be formally sealed |
| U6 | GPU resource authorization | The 72–112 GPU-hour envelope is a requested ceiling, not a reservation or authorization; measured projection and available allocation must be reviewed by M1. | Calibration/Formal remain unauthorized |
| U7 | Right-censored Session handling | RESOLVED IN DESIGN: include Sessions with valid observed Turns in the primary analysis; never impute future Turns; repeat sensitivity analysis excluding censored Sessions. | No open design decision; apply the frozen rule |

---

## 12. Final protocol status

```text
PHASE5_FORMAL_PROTOCOL = DESIGN_FROZEN_CANDIDATE
M1_PROTOCOL_FREEZE = REQUIRED
COST_AWARE_FAMILY = A1_ORIGINAL_FROZEN_LEGACY / A3_SUFFIX_FROZEN_LEGACY / DVA_ER_V1_PROVISIONAL
DVA_ER_SELECTION_GATE = NOT_EXECUTED
CONTINUUM_OFFICIAL_COMPATIBILITY = AUDIT_REQUIRED
BFCL_TRACE_ACQUISITION = M1_APPROVED_LIMITED_WORK_PACKAGE; FIXTURE_NOT_ACQUIRED
N_SESSION_NATIVE_RUNNER = INTEGRATED; NATIVE_GPU_CONFORMANCE = NOT_PROVEN
PHASE5E_PART_A_RUNNER = INTEGRATED_CPU_MOCK; NATIVE_GPU_CONFORMANCE = NOT_RUN
PHASE5E_PART_B = NOT_READY
GPU_SIX_ARM_CAMPAIGN = NOT_AUTHORIZED
REQUESTED_GPU_BUDGET = 72_TO_112_GPU_HOURS
```

This protocol records the accepted research design and remaining freeze/compatibility gates, but it is not an execution authorization. M6 must not change the research design; implementation conflicts return to M4/M1.
