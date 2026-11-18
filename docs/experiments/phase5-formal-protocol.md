# Phase 5 Formal Experiment Protocol — Four-System Trace-Driven Replay

**Protocol ID:** `phase5.formal_protocol.v1`  
**Status:** `DESIGN_FROZEN_CANDIDATE` — M1 freeze required; no execution authorized.  
**Owner:** M4 (research design); M6 (engineering implementation); M1 (scope and freeze authority).  
**Base main:** `af33bc380e360582c7de9b8a5062ce7ec434d02e`.  
**Phase 3 Protocol v4 and all historical results remain unchanged.**

---

## 0. Purpose and non-goals

This protocol defines one formal, trace-driven replay campaign comparing four systems on representative multi-turn Agent workloads:

1. **Native** — unmodified Native vLLM;
2. **Continuum Official** — the authors' pinned public implementation;
3. **Continuum Adapted** — the project-side A0-derived full-system adaptation;
4. **Cost-Aware** — the M1-frozen Cost-Aware candidate built on the same project foundation.

The research question is:

> Under a representative multi-turn Agent workload, can Cost-Aware KV-cache management reduce recomputation caused by cache eviction relative to Native and Continuum-style systems, and does that mechanism benefit transfer to measured serving metrics?

This protocol does **not**:

- reproduce the original Continuum paper exactly;
- treat the official public preview as the complete paper implementation;
- pool Phase 3 fixed-pressure results with Phase 5 trace-driven results;
- claim isolated mechanism causality from a whole-system comparison;
- authorize GPU, Native, or Trace Acquisition execution.

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

### 1.2 Four systems

| ID | System | Exact definition | Allowed differences |
|---|---|---|---|
| `NATIVE` | Native vLLM | Unmodified vLLM `0.27.1`; Native APC/LRU, scheduler, BlockPool, no project hooks; same model/tokenizer/pool/block size/`max_num_seqs` as Adapted/Cost-Aware. | Only passive evidence instrumentation; no behavior-changing patch. |
| `CONTINUUM_OFFICIAL` | Continuum Official Public Implementation | Pinned authors' public repository at `316a58794a6ff86b216e579b74fd56ed0c5a911f` (M1 must re-freeze if a newer reviewed snapshot is chosen); run as released, with its own documented environment. | Its own upstream vLLM base and scheduler; **not** the full paper estimator. If the base differs, it is a separate environment stratum and a documented confound. |
| `CONTINUUM_ADAPTED` | Continuum Adapted | A0-derived **full-system** adaptation on the project side: project Dynamic TTL, retention/Entry Release, native physical victim path, and project program-aware scheduler enabled only after scheduler conformance. Same model/tokenizer/pool/block/max_num_seqs as Cost-Aware. | Project-side scheduler/TTL implementation; no Cost-Aware policy. If scheduler conformance is not accepted, the system must be renamed `CONTINUUM_ADAPTED_CACHE_ONLY`; it cannot be presented as full-system Continuum. |
| `COST_AWARE` | Cost-Aware | **M1-frozen Phase 4 candidate**, built on the exact `CONTINUUM_ADAPTED` foundation. One candidate only; no fallback arm, no mid-campaign substitution. | Only the frozen cost-aware policy; all other configuration identical to Adapted. |

**Official boundary:** the public repository is a released Continuum-style implementation without the full paper estimator/experiment bundle. Results must be reported as a system-level comparison, not as an exact paper reproduction or an isolated mechanism comparison.

**Cost-Aware freeze:** no Phase 4 candidate has been promoted. `COST_AWARE_CANDIDATE` is an explicit unresolved freeze item. Until M1 selects and hashes one candidate, the formal campaign is `NOT_EXECUTABLE`.

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

Optional secondary source (not part of the primary four-system estimand unless separately frozen): Multi-SWE-Bench/OpenHands public trajectories after schema/license audit.

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
- A Group is `COMPLETE` only if all 4 Sessions and all required requests produce valid evidence in every system/repeat.

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

- TTFT: first-token time minus request dispatch/arrival, with clock domain recorded; P50/P95 per Group.
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

### 4.4 Units and missingness

- Statistical unit: Workload Group (not request, turn, repeat, or pressure event).
- Per-run metrics aggregate requests within the run; repeats aggregate within Group/System; Systems compare within Group.
- Missing/indeterminate primary evidence: Group/System is `INCOMPLETE`; no imputation or zero substitution.
- Secondary timing metrics are reported only from observed timestamps with comparable semantics.

The full contract is in `phase5-metrics-contract-v1.json`.

---

## 5. Calibration and sample size

### 5.1 Calibration

- 4 Groups per stratum (8 total), disjoint from formal Groups.
- 4 Systems × 4 Groups × 3 repeats = **96 calibration runs** (plus startup).
- Calibration estimates run-to-run variance of paired Group/System differences; it does not estimate the treatment effect for the formal verdict.
- Calibration data may not be reused as formal evidence.

### 5.2 MDE and power

- Primary family: 3 paired contrasts (`COST_AWARE` vs `NATIVE`, `CONTINUUM_ADAPTED`, `CONTINUUM_OFFICIAL`).
- Family-wise α = 0.05, two-sided; Holm correction.
- Power = 0.80.
- MDE = `max(512 tokens, 5% of Native Group mean recomputed tokens)`, frozen before calibration analysis.
- Per-stratum paired difference SD `σ_d` estimated from calibration with Group-level aggregation.
- `n_stratum = ceil((z_{1-α/2} + z_power)^2 * σ_d^2 / MDE^2)`, using the Holm-adjusted per-contrast α for the initial conservative calculation.
- Final N = `min(16, max(8, n_stratum))` per stratum.
- If `n_stratum > 16`, the campaign proceeds at 16 only if M1 accepts `UNDERPOWERED`; otherwise it stops.
- If calibration is unavailable/incomplete, formal execution is not authorized.
- No optional stopping, no peeking, no sample-size change after formal data collection begins.

### 5.3 Resource budget

- Planned runs: calibration 96 + formal 8N per stratum (N=8..16) → 224–352 runs for two strata.
- Per-run hard timeout 600s, shutdown grace 60s; reservation window 1800s.
- Max campaign GPU budget: **36 GPU-hours** including startup/archive; if projected >36h, reduce N within [8,16] and record the power consequence; do not silently reduce below 8.
- If the budget cannot support 8 Groups/stratum, the campaign is `NOT_FEASIBLE` rather than underpowered.

The full contract is in `phase5-calibration-sample-size-contract-v1.json`.

---

## 6. Statistical analysis

### 6.1 Primary analysis

For each stratum and contrast:

1. aggregate requests to run totals;
2. average repeats within Group/System;
3. compute paired Group difference `d_g = metric(Cost-Aware, g) - metric(baseline, g)`;
4. report mean difference, median, 95% CI, and relative effect vs baseline;
5. use Group-level paired bootstrap (10,000 resamples, fixed seed) and a paired permutation/sign test as robustness;
6. combine strata only by a pre-registered equal-stratum weight (or report separately); never pool requests.

### 6.2 Multiplicity

- Three primary contrasts: Holm family-wise error 0.05.
- Secondary metrics: BH-FDR 0.05, explicitly exploratory; confidence intervals are descriptive.
- Mechanism diagnostics: descriptive, no multiplicity-adjusted causal claim.

### 6.3 Failure/missing/censoring

- Complete-case Groups only for the primary; report incomplete Groups and reasons.
- Source right-censored Sessions remain in the Group if all observed requests are valid; censoring is a Session-level covariate/sensitivity stratum.
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

The four-system comparison supports **whole-system differences** under the frozen workload and environments. It does not isolate which mechanism caused a difference. Official vs Adapted differences are confounded by implementation, software base, estimator scope and scheduler.

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
3. **G2 — System freeze:** four exact system revisions/configs, including Cost-Aware candidate and official compatibility audit.
4. **G3 — Replay conformance:** N-Session event-driven replay, actual enqueue gate, serialized dispatch, pressure and terminal evidence validated; Phase 5E Part A must pass or be explicitly superseded.
5. **G4 — Calibration:** 96 calibration runs complete and analyzed with the pre-registered algorithm.
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
3. `FourSystemRunner` — instantiate Native/Official/Adapted/Cost-Aware under the manifest; no self-authorization.
4. `SystemAdapter` — `prepare`, `submit`, `poll`, `execute_pressure`, `native_events`; no full drain.
5. `EvidenceRecorder` — planned/dispatch/Native/scheduler/output/terminal/pressure/exposure events with clock domains.
6. `MetricEvaluator` — N/E/C, recomputation, TTFT/latency/throughput/memory/overhead; fail closed.
7. `CalibrationAnalyzer` — variance, MDE, N; immutable output.
8. `CampaignManifestWriter` — schema-conformant manifest and archive hashes.
9. `AnalysisPipeline` — Group-level paired statistics, Holm, bootstrap, sensitivity; no request-level inference.

### 10.3 Current blockers against Phase 5A–5E

- N-Session Native runner and incremental polling are not yet GPU-proven.
- Phase 5E Part A conformance is not authorized/passed; Part B remains `NOT_READY`.
- BFCL trace acquisition/frozen search fixture is not authorized/complete.
- Cost-Aware candidate is not frozen; no Phase 4 promotion.
- Official compatibility/environment audit is not complete.
- Calibration/formal GPU budget is not authorized.

These are explicit entry gates, not assumptions.

---

## 11. Unresolved M1 decisions

| ID | Decision | Options / cost | Effect if unresolved |
|---|---|---|---|
| U1 | Cost-Aware candidate | freeze A1/A2/A3/downstream candidate; each has different implementation cost and prior evidence | formal campaign not executable |
| U2 | Continuum Adapted scheduler scope | full scheduler vs cache-only; full needs scheduler conformance, cache-only needs rename | cannot define four-system comparison |
| U3 | Official environment | same vLLM base vs separate base; same base may require patches, separate base is a confound | official arm may be descriptive only |
| U4 | BFCL search fixture | freeze results vs exclude BFCL; exclusion reduces workload diversity | stratum incomplete |
| U5 | Arrival rate/seed | provisional λ and seed must be frozen before acquisition | arrival realization cannot be sealed |
| U6 | Calibration/formal budget | 36 GPU-hour cap; lower cap → N<8 or underpowered | campaign may be infeasible |
| U7 | Censored-session policy | include with covariate vs exclude; include preserves workload but complicates primary | population ambiguity |

---

## 12. Final protocol status

```text
PHASE5_FORMAL_PROTOCOL = DESIGN_FROZEN_CANDIDATE
M1_PROTOCOL_FREEZE = REQUIRED
COST_AWARE_CANDIDATE = NOT_FROZEN
CONTINUUM_OFFICIAL_COMPATIBILITY = AUDIT_REQUIRED
BFCL_TRACE_ACQUISITION = NOT_AUTHORIZED
N_SESSION_NATIVE_RUNNER = NOT_GPU_PROVEN
PHASE5E_PART_A_CONFORMANCE = NOT_AUTHORIZED / NOT_PASSED
GPU_FORMAL_CAMPAIGN = NOT_AUTHORIZED
```

This protocol is complete as a design, but it is not an execution authorization. M6 must not change the research design; implementation conflicts return to M4/M1.
