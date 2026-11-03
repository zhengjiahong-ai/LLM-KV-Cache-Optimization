# Phase 3 Workload & Execution Feasibility Report

Status: **M1 AUTHORIZED: FORMAL DATASET SELECTION/ACQUISITION; 310-RUN CAMPAIGN MAY PROCEED AFTER COHORT FREEZE AND PROTOCOL GATES**

Protocol dependency: M4 Phase 3 Final Evaluation Protocol v3, PR #90,
reviewed HEAD `3a8c3882ad248715b2f5ea90e34baa3875ea0226`, merged/frozen by M1
on 2026-11-03 as `27249ab93953f531544ec8e226fc891adda60457`. This M6 report
assesses workload and execution feasibility; it does not redefine protocol
semantics.

## M1 execution decision addendum (2026-11-03)

- The formal cohort remains 40 **new qualified tasks** in 20 independent
  Workload Groups, two tasks per group from different repositories, with at
  least **10 repositories overall**. This is the frozen requirement in
  Protocol v3 and the original M6 feasibility report; it is not relaxed.
- M6 is authorized to select, acquire and qualify the formal cohort within the
  existing 80 unacquired W1-C candidate IDs. The working sampling plan remains
  40 Primary + 24 pre-registered Reserve candidates, deterministically
  selected before acquisition/outcome observation.
- The 18 historical W1-C full-payload-comparable pilot tasks remain excluded
  from formal effect estimates. The remaining 80 IDs are candidates, not
  acquired Agent traces.
- M6 must produce the qualified 40-task / 20-group / 10-repository cohort and
  a SHA-256-bound dataset/run manifest. It must bind task/source identities,
  trace/sidecar/profile hashes, Primary/Reserve roles, group pairing, request
  subsets, Frozen Request Order, Native Enqueue Order, Replay Timeline,
  Session pairing and per-request History Predecessors.
- Stage 1 (PR #93) and Stage 2 (PR #94) are complete. No separate Stage 3
  code-engineering milestone is required; the cohort seal itself remains a
  mandatory M6 data-selection and pre-run freeze deliverable.
- Once the cohort is complete and frozen, M6 is authorized to proceed with the
  40-run A0 Load Calibration and 30-run A0 Noise Calibration. The 240-run
  six-arm Main Campaign is authorized after the applicable frozen protocol
  gates pass. G0–G4, G3-CM and all fail-closed conditions remain mandatory.
- Any failure to meet 40 qualified tasks, 20 legal groups or 10 repositories,
  any prohibited substitution, or any protocol deviation must stop and return
  to M1. Do not expand the frozen 80-candidate frame or retune the protocol.
- The PR #92 estimate of 3–5 RTX 4090D GPU-hours with a 6-hour ceiling is a
  planning estimate; M6 must reconfirm it against the qualified cohort.


## 1. Executive finding

The six-arm, 20-group Phase 3 design is feasible on the existing RTX 4090D
stack without a new Agent framework. The repository already provides the
replay clock, fixed pressure, Native observations, policy hooks, evidence
archive, and paired evaluator substrate. The remaining material work is:

1. prepare a deterministic seal for 40 new qualified W1-C tasks and 24
   pre-registered reserves from the 80 unacquired candidates;
2. implement and test E0 and N0 campaign integration under M4's frozen
   semantics;
3. prepare independent A0 load/noise calibration for later authorization; and
4. harden the evaluator around the corrected request-level N/E/C contract.

The current evidence supports neither a public Continuum reproduction claim
nor ownership-level physical attribution. Phase 3 can still answer the effect
question using request-level Aggregate Recomputed Tokens.

## 2. Frozen comparison boundary

| Arm | Frozen meaning | M6 integration consequence |
| --- | --- | --- |
| N0 | no-op forced Entry Release; pressure request, barrier, timeline, Native LRU and APC remain active | inject a no-op at the forced Entry Release decision, not by deleting pressure stages |
| A0 | project-side Continuum-style Entry Release + Native LRU | internal baseline; **not** a reproduction of public Continuum |
| A1 | frozen Cost-Aware Entry Release + Native LRU | reuse frozen runtime path |
| A2 | A0 Entry Release + frozen block selector | reuse frozen runtime path |
| A3 | suffix cost-aware Entry Release + Native LRU | reuse accepted A3 decision path; physical causality remains unestablished |
| E0 | A1 branch ladder with deadline-only Step 2 + Native LRU | M4 owns semantics; M6 owns materialization, runtime wiring and evidence |

E0 uses the same candidates, `need`, `N_i`, sufficient-set construction and
fallback ladder as A1/A3. In S2A it orders by `(deadline, identity)` and never
reads q or the cost profile. S2B uses the same fallback determination as A3
and then frozen A1 Step 2. S2C uses frozen A1 Steps 3/4/5. Only S2A may differ
from A3. CPU/mock acceptance must prove E0/A3 equality in S2B and E0/A1
equality in S2C.

The campaign materializer must create one immutable cell plan with the same
requests, Explicit Token IDs, pressure inputs, logical-time boundaries,
model/runtime configuration and resource limits for all six arms. Arm-specific
configuration is limited to the frozen policy selector.

## 3. Existing workload inventory

### 3.1 W1-A

| Property | Audited value |
| --- | ---: |
| Independent tasks | 10 |
| Repositories | 1 (`astropy/astropy`) |
| Successful request records | 453 |
| Requests per task | 3–50 |
| Prompt token range | 1,463–20,782 |
| Median prompt tokens | 7,868 |
| Adjacent server-gap samples | 443 |

W1-A has authentic trajectories, sidecars, Explicit Token IDs and timing. Its
single-repository population and historical 3B identity make it suitable for
history/regression checks, not the Phase 3 population.

### 3.2 W1-B

W1-B is a replay/profile layer over W1-A. It contributes PrefillReload,
pressure and APC machinery but no independent tasks. Constructed checkpoints
must not be counted as new Agent observations.

### 3.3 W1-C

| Property | S50 | S100 |
| --- | ---: | ---: |
| Frozen candidate frame | 100 tasks | 100 tasks |
| Acquired tasks | 20 | 20 |
| Repositories represented | 12 | 12 |
| Successful model calls | 1,000 | 1,800 |
| Failed model calls | 0 | 3 |
| Tool calls | 464 | 943 |
| Median prompt tokens | 5,836 | 9,245 |
| Maximum admitted prompt tokens | 19,726 | 32,223 |
| Median adjacent exact-token LCP | 5,773 | 9,209 |
| Median adjacent reuse ratio | 0.9709 | 0.9829 |

The acquisition produced 20 paired tasks. Eighteen are full-payload comparable;
all 20 retain lifecycle evidence. The remaining 80 frozen candidates are
unacquired. W1-C preserves request order, logical gaps, Explicit Token IDs,
tool observations, failures and sidecars, so it is the only currently local
cross-repository source suitable for Phase 3.

Phase 2H/2I reuse six W1-C tasks and do not add an independent population.
Their value is execution feasibility: 180-request, three-session Native replay,
three pressure barriers, empirical TTL history and A3 execution were observed.

## 4. Public source and trace availability

| Source | Task descriptions | Complete replayable Agent traces | Phase 3 role |
| --- | --- | --- | --- |
| Continuum public repository | yes, via SWE-bench loader | audited checkout does not publish paper-run exact trajectories | provenance/implementation reference only |
| SWE-bench Verified | 500 verified task rows | no conversations, Explicit Token IDs or Agent timing | frozen acquisition frame |
| Mini-SWE-Agent | agent and trajectory writer | yes only after pinned execution with this project's sidecar capture | preferred acquisition scaffold |
| Existing W1-C | yes | yes for acquired tasks | immediate seed |

Issue descriptions are not traces. Aggregate benchmark results cannot recover
messages, exact submissions, tool gaps, failures or timing. New qualified data
therefore require pinned Mini-SWE-Agent acquisition through the existing W1-C
capture and validation path.

## 5. Cohort acquisition and deterministic seal

Twenty independent groups require 40 **new** qualified tasks, two tasks from
different repositories per group, and at least ten repositories overall. M1
has rejected reuse of the 18 historical full-payload-comparable tasks in the
formal cohort. They remain available only for engineering regression,
evaluator tests and non-formal validation; they do not enter Phase 3 effect
estimates.

The deterministic sampling plan contains 64 ordered IDs from the remaining 80
frozen candidates:

- 40 Primary candidates;
- 24 Reserve candidates.

The complete Primary/Reserve assignment, acquisition order, qualification
rules and pairing rules must be frozen before acquisition. Reserve promotion
may occur only under those pre-registered qualification rules, never because
of Native policy outcomes. If the list cannot yield 40 qualified tasks and 20
legal groups, execution stops for M1 review; M6 must not expand the frame.

Engineering preparation must materialize this deterministic task list while
excluding all previously acquired task IDs and stratifying by repository and
static issue length. Bind its ordered IDs, roles and strata to SHA-256. Actual
Agent acquisition is not authorized by this report. Once authorized, preserve every success,
failure, context-limit event, incomplete sidecar and right-censored trajectory;
do not replace a task after observing runtime or policy outcomes. Qualification
and pair construction use only pre-Native trace properties. Freeze membership,
request subsets and pairing before any formal Native outcome.

The final cohort report must include repository count, per-repository tasks,
request counts, prompt length/LCP distributions, source gaps, failure classes,
right-censoring and source/sidecar hashes.

## 6. Load and replay feasibility

The default cell is two sessions, 12 checkpoints per session, 24 requests,
maximum Native inflight 2, a 0.25-second cross-session start stagger and
`ControlledSparseReplayClock`. Source gaps remain logical lifecycle data; no
wall-clock idle is introduced.

Load is defined by independent A0-only calibration, not by session count:

- L-low: baseline recompute ratio `rho0` in 5–15%;
- L-high: baseline recompute ratio `rho0` in 25–45%;
- `rho0 = R0 / W0`, `R0 = sum(E-C)`, `W0 = sum(N-C)`.

Calibration may adjust only pre-registered pressure inputs before the main
campaign. Any affected A0 calibration must be rerun, and the final inputs must
be frozen without reference to other arms. An eligible headroom cell has
`rho0 >= 5%` and `R0 >= 512`; the headroom list is SHA-bound. The main campaign
still executes all 40 group/load cells and reports both the full set and the
pre-frozen headroom subset.

The existing W1-C distribution and 32,768-token model boundary make 24
requests/cell feasible. The permitted degradation is six checkpoints/session
(12 requests/cell) only after M1 reviews concrete pre-execution feasibility
evidence and explicitly approves the degradation. It must be frozen before
Calibration or Main Campaign begins. This halves request work
and decision exposure and therefore weakens APC/recompute and S2A opportunity;
it does not reduce the number of engine initializations or planned runs.

N0 must preserve the identical pressure request, `boundary_id`, logical time
and barrier while returning `NO_FORCED_RELEASE = VALID`. Tests must prove zero
N0 forced Entry Releases and no change to Native ownership behavior.

## 7. Request-level effect evidence

### 7.1 Correct N/E/C contract

For every evaluated request:

- `N` is the length of Native `prompt_token_ids` returned by vLLM;
- `C` is Native `num_cached_tokens`;
- `E` is **offline derived**, not a Native raw field. It is reconstructed at
  the request's observation boundary from the Native APC hash chain and the
  matching historical `VLLM_PREFIX_SNAPSHOT` identity/time evidence.

The Phase 3 evaluator must compute E independently from the frozen request
history and content-identity chain. It must not reuse the existing
`runtime_evidence.py::_eligible_prefix_tokens` behavior that uses C as a
fallback or lower bound. C is arm-dependent execution evidence and cannot
define or complete an arm-invariant E. Missing independent evidence makes E
unavailable and fails the affected comparison closed.

The derivation must bind run/group/load/arm/request/program, hash function,
block size, ordered hash chain, snapshot event index and clock boundary. If no
unique prior matching snapshot exists, or chain length/content/time is
inconsistent, E is missing and the request cannot contribute to the primary
metric. It is forbidden to substitute `N-C` for recomputation.

Required per-request checks are `0 <= C <= E <= N` and strict cross-arm E
equality for the same frozen request. Required aggregate identity is:

`sum(N-C) = sum(E-C) + sum(N-E)`.

Primary outcome is Aggregate Recomputed Tokens `sum(E-C)`. Auxiliary measures
are total prefill `sum(N-C)`, new suffix `sum(N-E)`, APC reuse ratio and
recompute ratio. APC labels are derived from N/E/C when no stable Native
per-request APC outcome event exists: no eligible prefix, full hit, partial hit
or miss. `16 * |refetched blocks|` is not a primary metric.

### 7.2 Native timing

Static inspection confirms the CUDA adapter reads
`output.metrics.first_token_ts`, together with `queued_ts` and `scheduled_ts`,
and persists it as `native_first_token_timestamp` in the
`engine_core_monotonic` domain. Before formal execution, CPU/mock fixtures must
verify type/missingness handling and a minimal authorized configuration check
must verify the target vLLM path populates it. It remains an auxiliary metric.
Logical `REQUEST_ADMITTED` must never be treated as Native admission or used in
a cross-clock subtraction.

### 7.3 Physical evidence limitation

Phase 2I closed with Gate O failed. Hashed evictions and physical outcomes may
be reported diagnostically, but they do not establish that a policy-owned
selection caused a later recomputation. Phase 3 effect attribution therefore
uses L4 request-level N/E/C only. Every final summary must state:

`ownership_level_attribution = NOT_ESTABLISHED`.

The optional `last_selected_block_ids` repair is not a prerequisite and must
not reopen Phase 2I runtime engineering.

## 8. Evaluator and hypothesis support

The independent evaluator must reconstruct the six-arm cell from persisted
artifacts and reject mismatched plan/input/model/runtime/trace/pressure hashes.
It must support:

- G0 — Freeze: verify that the Cohort, six arms, metrics, loads, Headroom,
  Profile and Replay rules are frozen and SHA-256 bound;
- G1 — Isolation: verify cross-arm input, configuration, E and N0 Boundary
  consistency;
- G2 — A3 Branch Composition: report S2A/S2B/S2C over the complete campaign
  and separately for each Load;
- G3-CM — Cost-model Discriminability: verify S2A decisions, actual A3/E0
  selection differences and Profile Robustness;
- G4 — Headroom: freeze the Headroom subset from the independent A0 Load
  Calibration results.

Hypothesis Evaluation is independent of G0–G4: H1 is A3 versus A0 (full
strategy), H2 is A3 versus E0 (cost-model contribution), and H3 is A0 versus
N0 (forced-release contribution). Record S2A/B/C for every relevant decision.
The G2 decision applies to H2, not H1. If `S2B / (S2A + S2B) >= 20%`
over the full campaign, or `S2A_count == 0`, then `H2 = NOT_EVALUABLE`.
H1 remains evaluable under its independent sample-size and Headroom
conditions, regardless of the S2B proportion.

For H2, persist uncertainty-envelope reordering as `PROFILE_ROBUST` or
`PROFILE_SENSITIVE`. Only robust decisions count as discriminable; fewer than
eight robust discriminable decisions makes H2 `NOT_EVALUABLE`. Loads and
parameters must not be changed to manufacture differences.

Native Timing and Physical Diagnostics are separate auxiliary evidence
outputs. They do not define G4 or replace any frozen Gate criterion.

The statistical unit is the Workload Group. Analyze each load separately at
`n=20`; do not combine loads into `n=40`. Report paired group effects and a
10,000-resample group bootstrap as exploratory estimates, without a
confirmatory significance claim.

## 9. Scale and budget

| Stage | Runs |
| --- | ---: |
| A0 load calibration: 20 Groups × 2 loads | 40 |
| A0 noise calibration: 5 Groups × 2 loads × 3 repeats | 30 |
| Main: 20 Groups × 2 loads × 6 arms | 240 |
| **Total** | **310** |

The former 600/720-run and 15–40 GPU-hour estimates are obsolete.

Observed RTX 4090D history provides the planning basis. Six Phase 2H formal
180-request runs took approximately 64, 65, 100, 77, 81 and 125 seconds
(mean about 85 seconds/run), including roughly 20–30 seconds of engine
initialization. The 54-run bounded pipeline completed in 38m54s (about 43
seconds/run end to end). A 24-request Phase 3 run should therefore remain
initialization-dominated and is conservatively budgeted at 30–50 seconds;
failures and archive work add contingency.

For 310 runs this yields 2.6–4.3 GPU-hours of direct execution. A planning
envelope of **3–5 GPU-hours** is credible, with a **6 GPU-hour hard ceiling**
recommended until calibration replaces the estimate. At 2 CNY/hour this is
approximately 6–10 CNY planned, 12 CNY at the ceiling. The 12-request fallback
can reduce Native request work but will save much less than 50% because engine
initialization remains per-run.

Budget categories must remain separate:

- Agent acquisition: CPU/network/container time and SWE-bench validation;
- data conversion/static qualification: CPU only;
- 310 Native runs: RTX 4090D billable wall time;
- evaluator/bootstrap/archive verification: CPU only;
- failed runs: retained and charged; retry only under a pre-frozen rule.

Cross-run engine reuse is not recommended because it risks cache contamination
and introduces unvalidated infrastructure.

## 10. Fail-closed conditions and recommendation

**GO for engineering preparation only; Agent acquisition, calibration, smoke
and formal GPU execution remain unauthorized.** Stop or exclude the affected
unit, with explicit missingness,
when any of the following occurs:

- source task, sidecar, Explicit Token IDs or frozen request subset changes;
- fewer than 40 qualified tasks, 20 disjoint groups or ten repositories;
- cross-arm plan/input/trace/pressure/model/runtime hashes differ;
- 24-to-12 request degradation is made after outcome inspection;
- load target is changed using non-A0 results;
- E is missing/non-unique, N/E/C invariants fail or E differs across arms;
- E was completed, bounded or replaced using C;
- N0 alters pressure timing/ownership or produces a forced Entry Release;
- E0 reads q/profile data or violates the frozen S2 ladder;
- formal runtime exceeds the frozen GPU ceiling or a request is not legal in
  the 2,048-block, 32,768-token configuration.

The authorized engineering-preparation deliverables are: the deterministic
64-ID Primary/Reserve sampling plan and cohort-seal tooling; six-arm
materializer tests; E0/N0 CPU/mock
acceptance; N/E/C evaluator and negative tests; static first-token capability
record; A0 calibration specification; and immutable run-plan tooling. Actual
Agent acquisition, the 40-run Load Calibration, 30-run Noise Calibration,
240-run Main Campaign and any GPU Smoke require later M1 authorization. No
additional Phase 2I repair is required by this feasibility assessment.
