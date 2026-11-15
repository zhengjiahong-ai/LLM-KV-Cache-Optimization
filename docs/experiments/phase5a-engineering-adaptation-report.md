# Phase 5A Engineering Adaptation and Trace Acquisition Planning

**Status:** CPU-only engineering prototype complete; Native integration and GPU validation not authorized

**Baseline:** `c083a60` (`main` after PR #115)

**Stage:** Engineering Adaptation & Trace Acquisition Planning

**Date:** 2026-11-15

## 1. Outcome

Phase 5A establishes a fail-closed contract for workload-driven candidate
exposure without modifying A0/A1/A2/A3/E0, Protocol v4, the historical cohort,
or sealed results.

The CPU implementation now provides:

- deterministic N-session replay plans for 2, 4, 8 and 16 programs;
- fixed and one-time-sampled Frozen-Poisson program starts;
- preservation and validation of within-program turn order and relative gaps;
- a self-bound Phase 5 Workload Seal covering provenance, request token hashes,
  replay events and expected Native enqueue order;
- an actual `VLLM_REQUEST_SUBMITTED` order gate with per-program and cross-arm
  checks;
- a fail-closed Candidate Exposure Evaluator that separates legal candidates,
  logical selections, physical victim sets, physical outcomes and descriptive
  future-reuse opportunities.

This is not yet a production Native runner. The N-session implementation
materializes and validates an event-driven plan and its capacity envelope. A
future authorized step must adapt the asynchronous Native backend and prove
that actual vLLM execution conforms to the plan.

## 2. Existing modules reused

| Existing capability | Reuse in Phase 5A | Boundary |
| --- | --- | --- |
| `Phase2Trace` / `PlannedRequest` | Program, request, turn, arrival and tool-gap model | Generic schema is retained; historical formats are not rewritten |
| W1-A acquisition recorder | Messages, model clocks, tool clocks and source hashes | Local tokenization remains distinct from runtime submission |
| W1-B explicit token replay | Request-to-token map and expected submission hashes | Phase 5 seal binds digests; Native verification is later |
| Controlled replay boundaries | Logical arrival/completion vocabulary | Existing implementation remains two-session and unchanged |
| Phase 3 cohort/freeze patterns | Canonical JSON/SHA-256 and fail-closed validation | Phase 5 uses a new schema; it does not modify the old seal |
| Phase 3 actual-order audit | Observed Native submission evidence | Phase 5 promotes it into a predeclared execution gate |
| Forced release evidence | Legal candidates and selected releases | Candidate fields must be complete or evaluation fails |
| SelectionPlan/physical outcome | Planned and observed victim blocks | Downstream recompute causality remains separate |

## 3. New CPU-only modules

### 3.1 `kvopt.workload.phase5_replay`

The module defines four independent contracts.

#### Arrival plan

`phase5.arrival_plan.v1` binds:

- ordered program identities;
- realized start offsets;
- `FIXED` or `FROZEN_POISSON` mode;
- fixed stagger, or Poisson rate and integer seed;
- exact generator identity.

Fixed arrivals use equal program-start stagger. Frozen-Poisson uses Python's
MT19937 PRNG and exponential inter-arrivals. Sampling happens once; the realized
offsets and their canonical SHA-256 become the compared input. Policies may not
resample the process independently.

#### N-session replay plan

`phase5.n_session_replay_plan.v1` accepts any matching set of non-empty program
sessions and an Arrival Plan. For each program it preserves:

- original model submit/completion intervals relative to that program's first
  submission;
- contiguous turn indexes;
- request identity and within-program order.

All events are merged with the explicit tie rule:

`timestamp → completion-before-arrival → program → turn → request`.

The merged arrival order is the expected Native enqueue order. The plan also
stores every per-program request order so an execution cannot pass merely by
containing the right request set. Source requests must have strictly positive
duration; equal submit/completion timestamps fail closed before event sorting.

#### CPU event-driven capacity proof

`phase5.event_driven_capacity.v1` walks the merged arrival/completion events,
tracks active requests and reports the planned peak and every over-capacity
event. Tests cover 2/4/8/16 programs. The result explicitly says
`NOT_EXECUTED_CPU_PLANNING_ONLY`; it cannot be cited as Native concurrency
evidence.

#### Workload Seal and enqueue gate

`phase5.workload_seal.v1` binds:

- workload and public-source provenance;
- source content SHA-256;
- all program IDs;
- exact request token-ID digests;
- complete N-session plan and its digest;
- expected Native enqueue sequence and its digest;
- `execution_authorized=false`.

The seal validates its own canonical content hash. The enqueue gate then reads
actual `VLLM_REQUEST_SUBMITTED` evidence and checks:

- exact global sequence;
- exact request set and uniqueness;
- each program's frozen request order;
- rejection of unknown non-pressure submissions;
- cross-arm equality after every individual arm has passed.

Pressure requests are excluded only by the reserved `pressure:` identity.
Unknown normal requests fail closed.

### 3.2 `kvopt.profiling.phase5_candidate_exposure`

The run-level evaluator requires every forced Entry Release decision to have:

- a candidate list and selected releases;
- selected releases contained in the legal candidate set;
- a Native decision binding;
- a SelectionPlan with explicit physical block IDs;
- a physical outcome with matched, unmatched and hashless sets.

It reports:

- legal and multi-candidate decision counts;
- scored-candidate and complete-physical-identity counts;
- selected program identities;
- selected, matched, unmatched and hashless blocks;
- later observations of candidate programs as a descriptive downstream reuse
  opportunity.

The last item is deliberately not causal. Every report retains
`downstream_recompute_attribution=NOT_ESTABLISHED`.

The cross-arm comparator aligns decisions by a common frozen decision-boundary
identity, requires every arm to expose the same identity set, and reports
separately:

- logical Entry-selection divergence;
- physical victim-set divergence;
- exposure counts per arm.

Duplicate event indexes, decision bindings, SelectionPlans or Physical Outcomes
fail closed. Scores count as valid only when they are finite non-Boolean numeric
values; invalid scores remain explicit unscored candidates. Different decision
identity sets, missing arms, missing plans or incomplete physical outcomes fail
closed.

## 4. Data and evidence contract

### 4.1 Source acquisition record

Every acquired program must bind:

| Field | Requirement |
| --- | --- |
| Source kind | SWE-Bench/mini-swe-agent or BFCL v4 Web Search |
| Source revision | Immutable dataset/repository revision |
| License | Recorded verbatim; upstream repository licenses remain separate |
| Task identity | Stable benchmark ID and repository/base revision where applicable |
| Agent identity | Agent implementation/configuration revision |
| Model call | Program, turn and request IDs; complete submitted messages |
| Model clocks | Monotonic submit and completion timestamps in named domain |
| Tool call | Name/input/result, start/end clocks, errors and truncation |
| Token identity | Model, tokenizer, chat template revisions, rendered prompt and IDs |
| Outcome | Completed, failed or right-censored without filtering by policy result |

### 4.2 Replay seal

The later materialization step must add:

- exact token-ID digest for every request;
- per-program source order;
- realized fixed/Poisson program-start plan;
- merged event list and expected Native enqueue order;
- context admission result;
- terminal/right-censored requests;
- any deterministic truncation rule applied before policy execution.

### 4.3 Native execution evidence

Entry to a performance evaluation requires:

- all expected submissions, in exact order;
- one clock-domain declaration for each timing source;
- Native prompt/hash identity observations;
- complete Prefix Snapshots required for candidate block mapping;
- all forced decisions, bindings, plans and physical outcomes;
- explicit missingness and no inferred physical success.

The same seal and realized arrival plan must be reused across every compared
arm.

## 5. Trace acquisition plan

No acquisition is performed in Phase 5A. The proposed bounded next step is:

### 5.1 SWE-Bench/mini-swe-agent

1. Pin SWE-Bench Verified revision, mini-swe-agent revision, agent YAML, model,
   tokenizer and chat template.
2. Pre-register a small task list without inspecting policy outcomes.
3. Run the existing acquisition recorder around every model and tool call.
4. Preserve successes, failures and right-censoring.
5. Convert only traces with complete message/tool evidence.
6. Retokenize deterministically, then verify the same exact IDs at Native
   submission.

Suggested planning batch: 8 primary + 4 reserve tasks. This is a planning
number, not an authorized acquisition or formal cohort.

### 5.2 BFCL v4 Web Search

1. Pin the 200-case Web Search source revision and choose snippet/no-snippet
   strata before execution.
2. Freeze the search tool contract. Prefer captured search responses so web
   drift cannot alter prompts or tool gaps across arms.
3. Record each model/tool boundary using the same sidecar schema as SWE-Bench.
4. Label captured-result replay separately from live web search.
5. Reject cases whose full prompt cannot enter the frozen context policy.

Suggested planning batch: 8 primary + 4 reserve cases balanced across the two
official Web Search categories.

### 5.3 Qualification

A trace is eligible only if it has at least four model turns, complete tool
observations, exact identities, reproducible tokenization, a sealed timing plan
and no request violating the context rule. Qualification cannot depend on A1,
A2 or A3 decisions. Reserve promotion may use only predeclared evidence-quality
rules.

## 6. Required Native engineering after Phase 5A

The CPU plan is intentionally not connected to the accepted Native runner.
The next implementation review must decide how to provide an asynchronous
backend with at least:

- immediate single-request submission;
- non-blocking completion polling;
- bounded wait-for-capacity without draining all requests;
- completion identity and failure propagation;
- pressure execution against live state;
- scheduler-iteration and actual submission evidence.

The existing `ControlledSparseReplayClock` prohibits logical time advancement
while any Native request is inflight. Reusing it unchanged would recreate the
wave/drain behavior. A production N-session executor therefore needs an
explicitly reviewed clock/state-machine contract rather than a hidden change to
that class.

## 7. CPU test plan and results

The new tests cover:

- 2/4/8/16-program event materialization and peak overlap;
- deterministic Fixed and Frozen-Poisson reproduction;
- changed Poisson seed changing the seal;
- program-set, turn-order and source-timestamp rejection;
- token-map coverage, self-hash and tamper rejection;
- exact Native enqueue pass;
- global/per-program reorder, unknown request and cross-arm failure;
- multi-candidate/scored/physical/reuse-opportunity output;
- missing decision binding, SelectionPlan or outcome failure;
- selected Entry outside the legal candidate set;
- logical and physical divergence detection.

Actual CPU validation on this branch:

- focused Phase 5A tests: **31 passed**;
- Phase 5A plus related historical Replay/acquisition/token/physical/order tests:
  **80 passed**;
- full CPU suite excluding the historical test whose purpose is to reject a
  dirty worktree: **1,987 passed, 15 skipped, 1 deselected**;
- Ruff on all new Python and test files: **PASS**;
- `git diff --check`: **PASS**.

The clean-worktree authorization test is deferred until the changes are
committed; it tests repository cleanliness rather than Phase 5A behavior.

## 8. GPU entry conditions

GPU validation remains locked until M1 approves all of the following:

1. source tasks and acquisition identities are pinned;
2. the selected traces pass the Phase 5 Workload Seal;
3. the asynchronous Native adapter passes CPU/Mock lifecycle tests;
4. 2/4/8/16 plans demonstrate the intended overlap without silent full drain;
5. actual enqueue order is an execution-time fail-closed gate;
6. compared arms bind the same token, arrival and request-order hashes;
7. context admission and KV capacity are frozen;
8. candidate exposure evidence is complete for the intended decision class;
9. one bounded 4090 D validation budget and stop rule are approved;
10. no formal effect campaign begins until exposure is shown without selecting
    tasks based on policy outcomes.

The first authorized GPU step should validate mechanism and execution
conformance, not estimate algorithm benefit.

## 9. Work and resource estimate

| Work item | Estimate | GPU need |
| --- | ---: | --- |
| Asynchronous Native adapter + state machine | 3--5 engineering days | None for implementation |
| Mock/fail-closed regression | 2--3 days | None |
| SWE/BFCL sidecar/schema adapters | 2--4 days | None unless live acquisition is approved |
| Workload seal/materializer integration | 2--3 days | None |
| Candidate exposure archive evaluator | 1--2 days beyond current prototype | None |
| Bounded Native conformance validation | To be budgeted after review | RTX 4090 D required |

The CPU prototype reduces design risk but does not establish those calendar
estimates as commitments. BFCL search-backend reproducibility and the Native
async API are the largest uncertainties.

## 10. Risks and open decisions

- Whether logical time may advance while Native requests are inflight must be
  specified explicitly; current accepted clock forbids it.
- Same-timestamp arrivals need the frozen tie rule across every arm.
- A queue cap may delay actual submission and violate the planned arrival
  order; this must fail or use a predeclared equivalence rule.
- Candidate list completeness depends on current live snapshots and content
  identity, not only program count.
- Later observation of a candidate program is a reuse opportunity, not proof
  that one victim caused recomputation.
- BFCL captured search results improve repeatability but change the evidence
  label from live web interaction to controlled replay.
- Small-model behavior can truncate or fail Agent trajectories generated by a
  stronger model; failures must remain in the acquisition ledger.

## 11. Stage verdict

`PHASE5A_CPU_CONTRACT_PROTOTYPE = PASS`

`N_SESSION_PLAN_2_4_8_16 = SUPPORTED_CPU_ONLY`

`FIXED_AND_FROZEN_POISSON_PLAN = SUPPORTED_CPU_ONLY`

`WORKLOAD_SEAL_AND_ENQUEUE_GATE = SUPPORTED_CPU_ONLY`

`CANDIDATE_EXPOSURE_EVALUATOR = SUPPORTED_CPU_ONLY`

`ASYNC_NATIVE_INTEGRATION = NOT_IMPLEMENTED`

`TRACE_ACQUISITION = NOT_STARTED`

`GPU_VALIDATION = NOT_AUTHORIZED`

`PHASE5_FORMAL_PROTOCOL = NOT_FROZEN`

