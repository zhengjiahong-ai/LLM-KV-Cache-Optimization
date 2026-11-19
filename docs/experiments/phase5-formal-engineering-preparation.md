# Phase 5 Formal Campaign Engineering Preparation

**Status:** merged six-system Protocol integrated; CPU engineering in progress

**GPU execution:** not started and not authorized by this document

## 1. Scope and ownership

This work prepares reusable execution and evidence infrastructure while GPU
resources are unavailable. M4 remains the owner of arm definitions, workload
qualification, formal cohort selection, metrics, statistical rules and sample
size. No code in this change freezes those research decisions.

The implementation currently covers:

- Phase 5E Part A lifecycle and Pressure controller contracts;
- actual EngineCore submission observation and in-process identity resolution;
- a source-preserving normalized Agent Trace schema;
- a protocol-independent workload identity seal;
- deterministic evidence archive creation and verification; and
- CPU fail-closed tests.

M4's merged six-system Formal Protocol from PR #122 is now integrated. The Protocol
Validator, mechanical workload-qualification checks and Calibration analysis
contract are implemented. The
protocol remains `DESIGN_FROZEN_CANDIDATE`, has
`execution_authorized=false`, and retains U1--U7; therefore Calibration,
six-system execution and formal cohort freezing remain fail-closed.

### 1.1 Pinned-runtime no-GPU validation

The protocol-independent implementation was checked on the intended server
Python environment in no-GPU mode on 2026-11-18:

- code HEAD: `345a20d4dd31213dd09a5ac94d1a8c9ce98fbbbd`;
- Python: `/root/bayes-tmp/kvopt/.venv-cuda/bin/python`;
- vLLM: `0.27.1`;
- pytest: `9.1.1`;
- pinned identity/API audit: `PASS`;
- targeted server tests: `29 passed`;
- raw audit path:
  `artifacts/phase5-formal-vllm-identity-audit-v1.json`;
- raw audit SHA-256:
  `6a5a7431149aa1aedee95db43a4be0e4649872afcab1308ee3a4f84f0490a81c`.

The Triton/CUDA import warnings were expected because the instance was started
without a GPU. This validation establishes the pinned Python API and request
identity contract only. It does not initialize an EngineCore, resolve a live
BlockPool, execute Pressure, prove Native concurrency or satisfy any GPU
Conformance gate.

## 2. Trace data-source investigation

### 2.1 SWE-bench and mini-SWE-agent

[SWE-bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/tree/main)
contains 500 human-validated task instances. Its rows describe repository,
base revision, problem statement, patch and test information. The
[official dataset guide](https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/datasets.md)
does not define these rows as Agent trajectories. They do not contain complete
model messages, tool inputs/results, timing or Prompt Token IDs.

The [official SWE-bench experiments repository](https://github.com/swe-bench/experiments)
links public leaderboard artifacts that may contain predictions, execution
logs and trajectories. Artifact ownership and formats vary by submission, so
each submission and instance needs its own schema, completeness and license
qualification. Presence on the leaderboard is not sufficient evidence of a
replayable trace.

mini-SWE-agent v2 uses append-only messages and supports serialization of its
trajectory. Its
[v2 migration documentation](https://github.com/SWE-agent/mini-swe-agent/blob/main/docs/advanced/v2_migration.md)
also records that v2 has breaking format changes from v1. The project is
[MIT licensed](https://github.com/SWE-agent/mini-swe-agent/blob/main/LICENSE.md).
The [SWE-bench CLI documentation](https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/cli.md)
describes per-instance trajectory output.

A complete, pinned mini-SWE-agent run can normally retain messages, tool calls,
tool observations, configuration, exit state and model statistics. Timing,
provider request identity and usage fields depend on the model adapter and
version. Public trajectories generally do not contain exact Prompt Token ID
arrays or a natural cross-session arrival timeline.

Evidence classification:

| Source | Classification | Permitted use before qualification |
| --- | --- | --- |
| SWE-bench task row / patch / result | `SUMMARY_ONLY` | task pool and source identity |
| Public leaderboard trajectory | `PARTIAL_MESSAGES` by default | adapter development and candidate audit |
| Pinned, self-acquired complete mini trajectory | eligible for `FULL_REPLAYABLE` after field and license review | later formal qualification |

### 2.2 BFCL V4 Web Search

The official [BFCL data documentation](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/bfcl_eval/data/README.md)
describes 200 Web Search tests: 100 base/snippet and 100 no-snippet. Gorilla is
[Apache-2.0 licensed](https://github.com/ShishirPatil/gorilla/blob/main/LICENSE).
The task JSONL contains questions, tool definitions and answer/source metadata;
it is not an executed Agent trace.

The [BFCL log guide](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/LOG_GUIDE.md)
defines user, assistant, tool, state, optional `inference_input` and handler
records. A self-run acquisition with input logging can therefore retain a much
more complete message/tool chain. The public contract does not guarantee a
stable timestamp, provider request identity or Prompt Token IDs for every
event.

Web Search results also have a live-data boundary. Search provider results and
no-snippet page retrieval can change. Third-party page content does not inherit
the BFCL repository's Apache-2.0 license. Acquisition must bind provider,
collection time, source URLs, raw hashes, errors and redistribution status. An
[official issue](https://github.com/ShishirPatil/gorilla/issues/1310) also
documents a page-fetch dependency failure mode, reinforcing the need to retain
raw tool failures rather than filtering them.

Evidence classification:

| Source | Classification | Permitted use before qualification |
| --- | --- | --- |
| BFCL question / ground truth | `SUMMARY_ONLY` | task template only |
| Existing result with incomplete inference log | `PARTIAL_MESSAGES` | format testing only |
| Pinned self-run with input log and complete tool results | eligible for `FULL_REPLAYABLE` after timing and license review | later formal qualification |

### 2.3 Common conclusion

No reviewed public package can be accepted wholesale as a complete,
time-faithful Agent Trace. Both workloads require per-artifact qualification.
Token IDs must normally be materialized later with frozen model, tokenizer and
chat-template revisions. A synthetic Fixed or Frozen-Poisson arrival is a
frozen replay realization over real message content; it must not be described
as the source system's original online arrival process.

## 3. Normalized Trace contract

`phase5_trace_contract.py` separates immutable raw artifacts from normalized
records. `TraceSourceProvenance` binds source kind, dataset, revision, URI,
license expression, raw artifact identity and SHA-256. It never embeds or
rewrites the raw source.

`RawTraceArtifact` verifies the bytes against that identity before an adapter
runs. The common `TraceAdapter` boundary then verifies that an adapter did not
change provenance, adapter identity or version while normalizing the source.
Source-specific mini-SWE-agent and BFCL parsers remain separate future modules;
the common contract does not pretend their formats are interchangeable.

The normalized hierarchy is:

`Program → Session → Turn → Message → ToolCall`

It preserves:

- source task, session, request, turn, message and tool-call identities;
- arbitrary structured message content and tool arguments/results;
- model and tool clock domains when actually observed;
- completed, failed, truncated and right-censored states;
- failure reasons and missing tool results; and
- adapter identity/version.

Evidence levels are explicit:

- `FULL_REPLAYABLE` requires complete request/model identity, model timing and
  tool results;
- `PARTIAL_MESSAGES` requires an explicit limitation list; and
- `SUMMARY_ONLY` requires an explicit limitation list.

Incomplete records cannot be promoted to `FULL_REPLAYABLE`. The schema does not
select a formal cohort.

`TokenMaterialization` is deliberately separate. It binds rendered Prompt
hash, complete Token IDs, Token-ID hash, model revision, tokenizer revision and
chat-template hash. This permits later M4-defined prompt rules without changing
raw or normalized traces.

## 4. Protocol-independent Workload Seal

`phase5_formal_seal.py` reuses the existing N-session replay plan and canonical
SHA-256 implementation. The new seal binds:

- raw and normalized trace identities;
- program, session, task and request identities;
- complete Token-ID identities;
- model, tokenizer and chat-template revisions;
- replay events and expected Native enqueue order; and
- one cross-system workload identity.

It is intentionally marked:

- `formal_cohort_status=NOT_SELECTED`;
- `protocol_binding=null`;
- `arm_binding=null`; and
- `execution_authorized=false`.

Only `FULL_REPLAYABLE` traces may enter this seal. Formal qualification and
cohort selection remain later, protocol-owned steps.

## 5. Phase 5E engineering closure

### 5.1 Native submission evidence

The pinned lifecycle proxy now observes the actual
`EngineCoreClient.add_request_async()` path. Internal vLLM request identity is
captured at the Core call and reconciled with logical/external identity after
the collector returns. A Core submission that arrives before the collector
binding is held as unbound evidence and must later join exactly once.

The wrapper observation uses the Adapter process monotonic clock. Native
queue/schedule/terminal timestamps retain the EngineCore clock label. The
concurrency gate uses the serialized lifecycle-event order to prove that the
last measured-wave Core submission observation precedes every measured-wave
natural terminal; it does not subtract timestamps across clock domains.

Adapter dispatch is not used as a substitute for Native submission.

### 5.2 EngineCore and Pressure identity

The in-process resolver requires the installed lifecycle proxy and resolves
exactly one object that owns:

`EngineCore → Scheduler → KVCacheManager → BlockPool`

The returned objects are identity references for the GPU preflight. Missing or
ambiguous resolution fails closed. This does not itself prove the server's
pinned layout; the authorized GPU preflight must run against vLLM 0.27.1 with
`VLLM_ENABLE_V1_MULTIPROCESSING=0`.

### 5.3 Part A / Part B readiness

Adapter reporting now separates:

- `part_a_natural_completion_readiness`; and
- `part_b_abort_readiness`.

Missing independent Abort Confirmation continues to keep Part B `NOT_READY`,
but does not by itself invalidate Natural Completion Part A. The compatibility
aggregate remains false unless both parts are ready.

### 5.4 Part A controller and gates

The bounded async controller enforces the frozen two-wave sequence:

1. dispatch and naturally complete four seed requests;
2. serially dispatch four tied measured requests without waiting for
   completion;
3. execute the single same-Engine Native BlockPool Pressure boundary;
4. collect all measured requests; and
5. require observable, complete shutdown.

The independent pre-archive evaluator covers P5E-G1 through P5E-G7. P5E-G0
remains the external freeze/authorization gate and P5E-G8 remains the archive
gate. Candidate exposure is explicitly not Algorithmic Benefit, and lifecycle
overlap is explicitly not GPU kernel overlap.

The remaining GPU-only integration risk is the production A3 event reader that
must join Forced Decision, Binding, SelectionPlan and Physical Outcome from the
same live runtime. CPU tests use injected evidence and do not claim this GPU
path has passed.

## 6. Archive and reproducibility

`phase5_archive.py` creates an exclusive, deterministic gzip/tar archive from
an immutable run directory. It:

- rejects symlinks and empty sources;
- requires declared files;
- writes a complete internal SHA-256 manifest into the archive without
  modifying the source directory;
- verifies member uniqueness, type, set and hashes before atomic rename; and
- returns the outer archive SHA-256.

An existing archive is never overwritten. A failed temporary archive is
removed, while the source evidence remains untouched.

`phase5_formal_archive.py` extends this to a complete Calibration or Formal
Campaign. It requires the exact frozen Run set, validates every Input/Result
binding, verifies all four raw-evidence hashes and every derived-metric hash,
and performs an independent archive round trip. Failed Runs remain indexed
and archived; the external envelope has no authorization effect.

## 7. Formal Protocol integration and mapping

Every protocol field is mapped using:

`Protocol Field → Implementation → Evidence → Evaluator → Test`

`phase5_protocol_mapping.py` implements the neutral mapping validator. It
requires exact coverage of the field list supplied by the future protocol. An
implemented field must name all four engineering references; an unresolved
field is reported as `BLOCKED_REQUIRES_M4` with a concrete blocker and cannot
produce a passing mapping. The module does not invent the field list.

`phase5_formal_protocol_validator.py` now validates the M4-owned protocol and
three referenced contracts against their JSON Schemas, computes byte-exact
SHA-256 identities, verifies the ordered six-system definition and checks
protocol/contract references. Execution code must supply the frozen hashes.
The validator separately verifies one paired six-system Campaign Manifest
set, including protocol, workload, arrival, runtime, system revision and
Group/stratum/repeat identity.

A structurally valid protocol candidate is deliberately not executable. The
validator rejects execution unless the protocol has the M1-frozen status,
explicit authorization, no unresolved decisions and fully frozen six-system
identities. The current PR #122 candidate therefore remains blocked rather
than acquiring implicit defaults from M6 code.

`phase5_workload_qualification.py` implements the mechanical Q1--Q9 checks
against normalized traces and Token Materializations. License acceptance,
outcome blindness, right-censor reasons and tool-fixture hashes remain
explicit acquisition inputs; they are never inferred. Qualification never
selects a cohort or authorizes execution. Formal Groups require exactly four
distinct qualified Programs and one distinct Session per Program.

`phase5_calibration.py` validates the exact 144-cell Calibration matrix (two
strata × four Groups × six Systems × three repeats), rejecting failed,
duplicated, missing or Formal-reused cells. `phase5_calibration_backend.py`
implements M4's frozen method-of-moments model with Stratum fixed effects:
common `df=6/16`, total `df=22`, descriptive per-Stratum `df=3/8`, 8×8
`df=6` covariance with PSD projection, the seeded one-sided 80% parametric
bootstrap upper bound, and iterative noncentral-t sizing with `df=n-1`.
`pooled_df=7` and z approximations are prohibited. Calibration output never
self-authorizes Formal execution.

`phase5_campaign_plan.py` materializes the exact six-system matrices: 144
Calibration runs and 192/288/384 Formal runs for N=8/12/16 per stratum. It
requires the frozen six-system balanced Latin-square rows, exact Workload Seal
and Arrival identities, unique Run IDs, and disjoint Calibration/Formal Group
sets. Plans remain `execution_authorized=false`.

`phase5_formal_manifests.py` separates the immutable Run Input identity from
post-run evidence and from the external Archive Envelope. This avoids an
archive containing its own hash and prevents execution results from rewriting
frozen inputs. The input binds all five M4 contracts, six-system identity,
generation/engine configuration, execution position, engine instance and the
required no-preheat/new-process/new-engine isolation evidence.

`phase5_formal_gate_ledger.py` evaluates G0--G6 independently. Missing,
unobservable, unhashed or non-PASS evidence fails closed, and unresolved
protocol items keep the aggregate closed even if every supplied Gate claims
PASS. The ledger has no authorization effect.

`phase5_candidate_evaluation.py` provides the Stage 1 adapter boundary for
A1 Original, A3 Suffix and DVA-ER v1. All candidates receive one immutable
snapshot, legal set, Native LRU state and workload identity. Future outcome
fields, non-finite scores, ranking drift and an unpassed DVA CPU correctness
gate fail closed. Selection/victim divergence remains diagnostic and does not
create an algorithmic-benefit claim.

The following protocol-owned decisions remain deliberately unresolved:

- U1 DVA-ER v1 CPU gate has passed, but M1/M4 formal freeze remains unresolved;
- U2 Continuum Adapted scheduler scope;
- U3 Continuum Official environment compatibility;
- U4 BFCL acquisition authorization and frozen fixture;
- U5 final Arrival rate and seed;
- U6 Calibration/Formal GPU budget authorization; and
- U7 censored-session population policy.

The Protocol defines the metrics, statistical unit and failure policy. The
current CPU implementation now includes the following protocol-bound pieces:

- `phase5_six_system_runner.py` enforces an exact six-system cell, one shared
  Workload/Arrival/enqueue identity, a fresh process and EngineCore for every
  run, empty-cache preflight, no preheat, no automatic retry and exact actual
  Native enqueue order;
- `phase5_formal_metrics.py` records a unique raw event stream and independently
  derives N/E/C, recomputation, TTFT, latency, throughput and missingness. E is
  derived from frozen predecessors and Native content identity without a C
  fallback, and incompatible clock domains are never subtracted;
- `phase5_formal_analysis.py` averages the two repeats within each
  Group/System before forming paired Group contrasts, applies complete-case
  Group handling, separate Holm families per stratum, exact paired sign-flip
  tests, paired Group t tests and reproducible Group bootstrap intervals; and
- `phase5e_mock_runner.py` exercises the bounded Part A controller through
  gate evaluation and independently validated evidence archive creation.
- `phase5_system_adapters.py` requires exactly the six frozen systems and
  blocks execution when any implementation revision, CPU correctness gate,
  Native compatibility gate or algorithm freeze is unresolved. In particular,
  Continuum Official compatibility and the DVA-ER v1 CPU gate cannot be
  replaced by a generic Mock PASS;
- `phase5_formal_orchestrator.py` maps a hash-bound Campaign Plan into paired
  six-system cells, routes each Run only to its declared adapter and stops at
  the first failed Run without retrying or silently dropping later cells; and
- `phase5_formal_freeze.py` binds the immutable Calibration plan, exact
  noncentral-t analysis, Calibration evidence archive and size-matched Formal
  plan. Its output is only a candidate for M1 authorization and always retains
  `execution_authorized=false` and `authorization_effect=NONE`.
- the merged DVA-ER v1 implementation from PR #123 is now connected through
  `phase5_dva_candidate_adapter.py`. The adapter reconstructs the complete
  decision-time Native pool, FreeQueue, refcount/protection, follow-up and A0
  tie-break evidence, invokes the real `DVAERStrategy`, and returns candidate
  loss, selected Entry and simulated Native victim sequence through the common
  Candidate Evaluation contract. Nested future-evidence fields fail closed.

DVA status remains deliberately split: CPU correctness is `PASS`, candidate
freeze is `PROVISIONAL_NOT_FROZEN`, and Native Conformance is `NOT_RUN`. CPU
six-system integration accepts this provisional state for interface testing,
while Formal execution readiness continues to fail closed until both the
algorithm freeze and Native compatibility gate pass.

`phase5_candidate_physical_evidence.py` joins each candidate loss vector and
selected Entry to the SelectionPlan and observed physical victim classes.
Identity drift, planned-victim drift, unobservable outcomes and overlapping
physical classes fail closed. Downstream attribution and Algorithmic Benefit
remain `NOT_ESTABLISHED`.

These are CPU/Mock engineering contracts. They do not close U1--U7, freeze
DVA-ER v1, qualify BFCL, authorize execution or establish Native/GPU PASS.

Any protocol field that lacks an observable Native fact will be returned to M4
for research-design adjudication. Engineering code will not replace missing
evidence with policy-reported aggregates.

## 8. GPU entry conditions and remaining risks

Before any continuous GPU window begins, the final bundle must demonstrate:

1. the M4 Protocol hash and schema pass;
2. every Protocol field has a complete implementation/evidence/evaluator/test
   mapping;
3. P5E final Seal and execution authorization match the code HEAD;
4. one in-process EngineCore owns Scheduler, KV instrumentation and BlockPool;
5. the production A3 Pressure evidence reader is present;
6. formal workload qualification and Token identity pass;
7. all arms consume one Workload Seal and Arrival realization;
8. Calibration outputs are accepted only by a hash-bound formal runner; and
9. archive validation is executable independently.

Current GPU-only risks are live Core/BlockPool layout confirmation, real
Pressure exposure, Candidate/Physical evidence availability, actual Native
concurrency, model memory headroom and complete cleanup. None is reported as
PASS by this CPU work.

The P5E contract now requires a per-request Native allocation watermark before
Pressure and independently verifies that all four r1 Native natural terminals
precede the first r2 Native submission. A free-block count or submission event
alone is insufficient. The end-to-end CPU/Mock runner now wires execute → gates
→ archive and explicitly reports `gpu_conformance_claim=NOT_ESTABLISHED`. The
remaining P5E blocker is the production GPU runner and evidence reader that
must obtain these facts from the live pinned EngineCore; the Mock path cannot
be promoted to a Native Conformance result.

The earlier `P5E-A-01` freeze generated at `7b03b57` is not an execution freeze
for this changed code. Before GPU execution, the final bundle must regenerate
the Workload Seal, Execution Manifest and confirmation request against the
eventual reviewed HEAD. Historical freeze files remain unchanged and must not
be silently reused.
