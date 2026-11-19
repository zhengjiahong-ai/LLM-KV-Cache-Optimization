# Phase 5E GPU Conformance Plan

**Status:** plan and CPU-only validation complete; GPU execution is not
authorized.

**Base commit:** `af33bc380e360582c7de9b8a5062ce7ec434d02e`

## 1. Purpose and decision boundary

This plan defines one bounded GPU conformance validation for the Phase 5D
`AsyncLLM + RequestOutputCollector` adapter on the pinned vLLM 0.27.1 runtime.
It tests whether the accepted CPU contracts map to a real Native lifecycle. It
does not estimate algorithm benefit and does not change A0/A1/A2/A3/E0,
Protocol v4, a historical Cohort, or a sealed result.

Conformance is split into two independently adjudicated parts:

- **Part A -- Natural Completion:** ready for M1 authorization review.
- **Part B -- Stop String / Explicit Abort:** `NOT_READY`. The pinned runtime
  has no accepted independent per-request Native abort-confirmation source.

An abort API return or `NATIVE_ABORT_DISPATCHED` event is never treated as
Native terminal confirmation. Part B is excluded from the proposed GPU run and
does not block Part A.

## 2. Proposed execution matrix

The requested future authorization is deliberately small:

| Run | Programs | Requests | Policy | Pressure | Terminal path | Purpose |
|---|---:|---:|---|---|---|---|
| P5E-A-01 | 4 | 8 (2 each) | A3, unchanged | one frozen live boundary | natural only | lifecycle, concurrency, enqueue, pressure and exposure conformance |

There is no effect comparison, repeat-based estimator, or post-result workload
selection. If the run fails, the evidence is archived and the run stops. A
replacement run requires a new M1 decision; the runner cannot self-authorize a
retry.

## 3. Four-Program fixture

The review candidate uses stable identities `p1`--`p4`, two requests per
Program, explicit token IDs, and this frozen arrival schedule:

| Request | Offset (s) | Program ordinal | Request ordinal |
|---|---:|---:|---:|
| p1:r1 | 0.00 | 1 | 1 |
| p2:r1 | 0.05 | 2 | 1 |
| p3:r1 | 0.10 | 3 | 1 |
| p4:r1 | 0.15 | 4 | 1 |
| p1:r2 | 2.00 | 1 | 2 |
| p2:r2 | 2.00 | 2 | 2 |
| p3:r2 | 2.00 | 3 | 2 |
| p4:r2 | 2.00 | 4 | 2 |

The frozen tie rule is
`LOGICAL_TIME_PROGRAM_ORDINAL_REQUEST_ORDINAL_V1`. The expected Native enqueue
order is therefore:

```text
p1:r1, p2:r1, p3:r1, p4:r1,
p1:r2, p2:r2, p3:r2, p4:r2
```

The fixture reuses Phase 5A `create_phase5_workload_seal()` and
`validate_phase5_workload_seal()`; it does not introduce a second Seal format.
The Seal binds the prompt-token-ID hashes, Program and request identities,
per-Program request order, arrival offsets, tie rule and expected enqueue order.
The Phase 5E plan then hash-binds that Seal together with the pinned
model/tokenizer revision, sampling parameters, Engine/KV configuration and
Pressure input. Materialization must fail if a prompt is retokenized, a binding
is absent, or either layer's SHA-256 changes.

The controlled input generator materializes all 1,984 IDs per request. The
first 512 IDs are common to all Programs, the next 512 are Program-specific,
and the remaining 960 are request-specific. Thus each Program has a frozen
1,024-token reusable prefix while request identity remains distinct. The Seal
stores the SHA-256 of each complete ID array. The Pressure hash is likewise
computed from its complete deterministic 24,576-ID array rather than a label.

The expected order is independently derived from
`(arrival_offset, program_ordinal, request_ordinal)` and then compared with the
sequence stored in the Seal. It is not accepted merely because a supplied list
contains all eight identities.

For tied arrivals, the controller performs serial dispatch initiation in the
frozen order without awaiting request completion. A dispatch call must bind its
external/internal identity before the controller initiates the next tied
request. This guarantees deterministic dispatch order while still allowing the
requests to coexist in Native inflight state. The actual EngineCore submission
sequence remains independently gated after execution.

This is a controlled Native Adapter Conformance fixture, not an acquired Agent
Trace. Its observations cannot be generalized to Agent workload quality or
Cost-Aware algorithm effectiveness.

The fixture is non-executable until M1 approves its final sealed manifest. The
CPU candidate in `phase5_gpu_conformance.py` intentionally sets
`execution_authorized=false`.

## 4. Arrival and enqueue conformance

Planned arrival is a logical schedule. Dispatch and Native timestamps are
separate observations. The run must persist, for every request:

1. frozen planned arrival offset;
2. adapter dispatch start and return;
3. vLLM external and randomized internal request IDs;
4. EngineCore queued and scheduled timestamps;
5. first output and frontend terminal;
6. natural Native terminal; and
7. adapter completion emission.

The gate compares the complete actual `VLLM_REQUEST_SUBMITTED` request-ID
sequence with the frozen order, including tie positions. Missing, duplicate,
unknown or reordered requests fail closed. Per-Program order is checked
independently. Event-log index is not substituted for EngineCore admission or
scheduler time.

Arrival timing acceptance uses the adapter monotonic domain only. For each
request, dispatch may be late but never precede its frozen epoch-plus-offset.
The report records lateness rather than rewriting the schedule. EngineCore
queued/scheduled timestamps remain in their own clock domain and are not
subtracted from adapter timestamps.

## 5. Native concurrency acceptance

Three different overlap claims are reported separately:

- **client dispatch overlap:** adapter submit operations coexist;
- **Native inflight overlap:** independently bound internal requests coexist
  between Native submission and natural Native terminal;
- **GPU execution overlap:** kernel/stream overlap, diagnostic only and not
  required for adapter conformance.

Part A passes concurrency only if:

1. observed peak Native inflight is at least two;
2. at least one later frozen request has a verified Native submission before
   an earlier request's natural Native terminal;
3. both identities are simultaneously present in the Native lifecycle ledger;
4. no frontend terminal is used as a substitute for Native terminal; and
5. the capacity controller never exceeds the frozen maximum of four.

GPU utilization, adjacent log lines, overlapping client coroutines or equal
scheduler timestamps do not by themselves prove Native inflight overlap.
Nsight or CUPTI profiling is not required for this bounded conformance run;
GPU-kernel overlap is outside its acceptance decision.

## 6. Natural-completion lifecycle acceptance

Every request must traverse the approved dual-terminal contract:

```text
PLANNED_ARRIVAL
  -> ADAPTER_DISPATCH_STARTED
  -> NATIVE_SUBMISSION_OBSERVED
  -> OUTPUT_PROCESSOR_PARTIAL (zero or more)
  -> OUTPUT_PROCESSOR_TERMINAL
  +  NATIVE_TERMINAL_CONFIRMED(reason=NATURAL_FINISH)
  -> ADAPTER_COMPLETION_EMITTED
```

The two terminal facts may arrive in either order. Native inflight capacity is
released only after both exist. Duplicate terminal evidence, identity mismatch,
unbound internal IDs or cross-domain time arithmetic fail closed.

After the eighth completion, bounded shutdown must demonstrate:

- no OutputProcessor RequestState for any internal ID;
- no live collector-consumer task;
- no adapter submit or cleanup task;
- no unbound Core evidence;
- no unfinished EngineCore request visible through the approved query; and
- no active model-engine child task owned by the fixture.

If any state surface is unavailable, the corresponding check is
`NOT_OBSERVABLE` and Part A fails rather than reporting an empty leak set.

## 7. Pressure and candidate-exposure acceptance

The fixture uses one frozen `LIVE_STATE` boundary named
`phase5e-pressure-01`. The four `r1` requests are the cache-seeding wave and
must naturally complete before the tied `r2` wave. The boundary fires at
logical offset 2.001 after `p4:r2` has a verified Native submission. No ninth
business request follows. The first measured Pressure wave therefore contains
four Native-inflight `r2` requests while completed `r1` content provides real
cached history. Its complete expected inflight set is exactly:

```text
p1:r2, p2:r2, p3:r2, p4:r2
```

The controller set and a snapshot from the same Native EngineCore instance must
both equal this set. Merely having four outstanding client coroutines is not
sufficient.

The controlled Pressure input contains and passes all 24,576 explicit token IDs
to the Native pressure executor. They freeze the allocation identity and exact
geometry: 24,576 / 16 = 1,536 blocks. They are not claimed to be model-executed
prompt tokens. The executor calls the same EngineCore BlockPool's
`get_new_blocks(1536)`, holds the returned Native block objects while collecting
Forced Release and physical eviction evidence, and releases them through the
same BlockPool. Calling policy-layer `apply_pressure()` without this allocation
does not satisfy the contract.

The Boundary also freezes `expected_free_blocks_before=1536`. The executor
checks this value before calling `get_new_blocks(1536)`. Any different runtime
free count fails closed before allocation, ensuring the request cannot be
satisfied solely from an unplanned surplus or silently exceed available blocks.

This controlled path requires pinned in-process EngineCore mode
(`VLLM_ENABLE_V1_MULTIPROCESSING=0`). A multiprocess `AsyncMPClient` does not
expose the owned Scheduler/BlockPool object to the frontend, so attempting to
run this executor in that mode fails preflight rather than crossing process
ownership unsafely. The executor verifies by object identity that its BlockPool
is exactly `EngineCore.scheduler.kv_cache_manager.block_pool` and that Adapter,
Scheduler and KV evidence instrumentation name that same EngineCore.

The boundary passes only if:

1. all `r1` seeding requests naturally completed, all four `r2` requests have
   Native submissions, and no ninth business request exists;
2. controller and Native snapshots equal the sealed inflight set;
3. the pressure-completed event is present exactly once;
4. at least one forced Entry Release decision is emitted;
5. every Decision has exactly one Binding, at most one Selection Plan and at
   most one Physical Outcome;
6. candidate scores are finite and invalid scores are not counted as scored;
7. legal, multi-candidate and successfully scored candidate counts are
   reported independently;
8. Selection Plan block identities are unique; and
9. every attributed physical victim belongs to the plan and has unambiguous
   block/content identity.

The primary exposure outputs are descriptive counts:

- forced-decision count;
- legal-candidate distribution;
- decisions with at least two legal candidates;
- successfully scored candidate distribution;
- branch composition;
- Selection Plan / physical victim-set identity agreement; and
- observable downstream reuse opportunities.

There is no minimum multi-candidate count required to claim algorithm success.
Zero exposure is a valid conformance observation but cannot support a later
effect experiment. Physical victim agreement and reuse opportunity are not
interpreted as recomputation savings or causal algorithm benefit.

## 8. Resource budget

Target environment:

| Item | Frozen proposal |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 D, 24 GiB |
| Model | Qwen/Qwen2.5-Coder-1.5B-Instruct, pinned revision at seal time |
| vLLM | 0.27.1 |
| EngineCore mode | in-process (`VLLM_ENABLE_V1_MULTIPROCESSING=0`) |
| PyTorch / CUDA | record exact installed versions in preflight |
| KV pool | 2,048 blocks |
| Block size | 16 tokens |
| Max model context | 32,768 tokens |
| Request prompt limit | 1,984 tokens each |
| Request generation limit | 64 tokens each |
| Engine `max_num_seqs` | 4 |
| Adapter Native-inflight capacity | 4 |
| Pressure prompt | 24,576 explicit tokens / 1,536 blocks |
| Bounded pressure reserve | 128 blocks |
| Run timeout | 600 seconds |
| Shutdown grace | 60 seconds |
| Resource reservation | 1,800 seconds |
| Authorized GPU runs | 0 at Phase 5E plan-review time |

For the Qwen2.5-Coder 1.5B configuration (28 layers, two KV heads, 128 head
dimension, FP16/BF16 KV), a 16-token block is approximately 448 KiB and 2,048
blocks are approximately 896 MiB. Model weights are approximately 3 GiB in
FP16/BF16. Runtime workspaces, CUDA graphs, activations and allocator
fragmentation are expected to dominate the remaining allocation. A preflight
must demonstrate at least 2 GiB free after engine initialization and before
fixture submission; this estimate is not a substitute for observed allocation.

The static worst-case measured-wave footprint is
`4 × (ceil(1984/16) + ceil(64/16)) = 512` blocks. Adding the 1,536-block
Native allocation consumes exactly the frozen 2,048-block pool. Thus the
configuration reaches the allocation boundary without exceeding it; the
128-block reserve is a fail-closed ceiling for observed runtime geometry drift,
not permission to change the frozen request. GPU preflight must still verify the actual BlockPool capacity,
free-block count before the boundary, required allocation, and that the
pressure action reaches Native allocation. If runtime geometry does not match,
the run fails closed; parameters are not adjusted in place.

Expected wall time is under five minutes after model initialization, with a
ten-minute run timeout and a separate 60-second shutdown grace. These execution
bounds are distinct from the 30-minute GPU reservation window, which also
covers environment validation, initialization, evaluation and archival. No
extra smoke is included.

## 9. Preflight and execution flow

If separately authorized, the runner must execute this sequence:

1. verify clean Git HEAD and approved authorization binding;
2. verify GPU UUID/model, no active compute process, driver, vLLM, PyTorch,
   CUDA and cached model revision;
3. verify the reused Phase 5A Workload Seal, plan, model/tokenizer revision,
   sampling, Engine/KV configuration, Pressure input and all hashes;
4. verify output root does not exist and create it with exclusive semantics;
5. initialize one AsyncLLM instance with `max_num_seqs=4`, install the lifecycle
   proxy before the output handler starts, and prove the Adapter observer,
   Scheduler instrumentation and KV/BlockPool instrumentation reference the
   same EngineCore instance;
6. execute exactly `P5E-A-01`; naturally complete the four `r1` seed requests,
   dispatch the four tied `r2` requests, and invoke the bound BlockPool pressure
   executor under the bounded parent;
7. run enqueue, lifecycle, concurrency, pressure, exposure and cleanup gates;
8. write the execution envelope and immutable evidence archive; and
9. stop regardless of PASS or FAIL_CLOSED.

No retry is automatic. Initialization failure, timeout, forced kill, missing
evidence or any gate failure produces `FAIL_CLOSED` and an archive. A retry or
fixture change requires a new authorization and a new run identity.

## 10. Gate matrix

| Gate | PASS condition |
|---|---|
| P5E-G0 Freeze | approved HEAD, reused Phase 5A Seal, model/tokenizer, sampling, Engine/KV, Pressure, in-process EngineCore environment and run ID all hash-bound |
| P5E-G1 Arrival | order independently derived; every dispatch respects frozen arrival; serial tied-dispatch rule and per-Program order preserved |
| P5E-G2 Enqueue | complete actual Native enqueue sequence exactly equals the seal |
| P5E-G3 Concurrency | peak Native inflight >=2 and later Native submission precedes earlier natural terminal |
| P5E-G4 Lifecycle | all eight requests have independent frontend and natural Native terminal evidence |
| P5E-G5 Pressure | exact four-request measured-wave set, same-Engine BlockPool `get_new_blocks(1536)`, accounting restoration, Forced Release and physical eviction evidence |
| P5E-G6 Exposure | unique, finite and identity-consistent candidate/plan/outcome evidence |
| P5E-G7 Cleanup | zero observable RequestState, collector, adapter and Engine leftovers |
| P5E-G8 Archive | envelope, events, reports and manifest verify against archive SHA-256 |

All applicable gates are conjunctive. `NOT_OBSERVABLE` is not PASS. Part B has
its own readiness result and is not silently included in Part A.

## 11. Required artifacts

The archive must contain:

- approved plan and authorization record;
- Workload Seal and SHA-256 manifest;
- exact materialized config, trace, explicit token IDs and pressure IDs;
- environment and resource preflight;
- ordered adapter, EngineCore, scheduler, pressure, decision, plan and physical
  outcome events;
- execution envelope and shutdown report;
- actual enqueue-order and arrival-timing reports;
- lifecycle/concurrency report;
- candidate-exposure report;
- gate report;
- stdout/stderr; and
- an internal SHA-256 manifest plus the outer archive digest.

Raw evidence is immutable. Offline evaluators write to a separate output root
and never modify the run directory.

## 12. Risks and bounded mitigations

| Risk | Handling |
|---|---|
| Abort confirmation unavailable | Part B remains `NOT_READY`; excluded from Part A |
| Proxy bound to wrong engine | preflight identity check and fail closed |
| Frozen arrival missed by initialization | epoch starts only after engine readiness |
| Client overlap mistaken for Native overlap | require internal-ID submission and natural-terminal interval evidence |
| Pressure does not create decisions | record zero exposure; do not claim effect or alter pressure after launch |
| Physical block identity ambiguous | mark attribution unavailable and fail P5E-G6 |
| Cleanup surface unavailable | `NOT_OBSERVABLE`, fail P5E-G7 |
| OOM/runtime failure | bounded stop, immutable archive, no automatic retry |

Part A finish reasons are frozen as follows:

- EOS or stop-token natural EngineCore completion: PASS category
  `EOS_OR_STOP_TOKEN`;
- generation-limit completion: PASS category `LENGTH`, reported separately;
- frontend Stop String path: `ABORT`, excluded from Part A success;
- explicit abort: `ABORT`, excluded from Part A success;
- dispatch, model, collector or Engine error: `ERROR`, fail closed.

Sampling is frozen at temperature 0, `max_tokens=64`, no frontend stop strings,
and `include_stop_str_in_output=false`. Part A reports EOS/STOP-token and LENGTH
counts separately even though both are accepted natural EngineCore terminals.

## 13. CPU-only preparation result

`src/kvopt/workload/phase5_gpu_conformance.py` provides a non-executable plan
contract. It enforces:

- exactly four Programs, two requests each and globally unique identities;
- enqueue order independently derived from arrival and ordinal fields;
- complete frozen enqueue coverage and serial tied-dispatch semantics;
- reuse and validation of the Phase 5A Workload Seal;
- Prompt, sampling, Engine/KV and Pressure SHA-256 bindings;
- exact Pressure trigger position and four-request measured-wave Native inflight set;
- bounded real BlockPool allocation with Engine/Adapter capacity equality;
- explicit Natural finish-reason classification; and
- Abort Conformance fixed to `NOT_READY`; and
- `execution_authorized=false` at this stage.

CPU tests cover the valid candidate and negative cases for request count,
derived enqueue order, Seal/hash drift, Pressure boundary/inflight mismatch,
non-pressure and unsafe KV budgets, Engine/Adapter capacity mismatch, Abort
readiness, finish-reason classification and self-authorization.

## 14. M1/M4 closure matrix

| Review group | Closure |
|---|---|
| F1/F2/F8 -- frozen inputs and order | Exactly 4x2 requests; order derived from arrival/program/request ordinals; serial tied dispatch; reused Phase 5A Seal plus model/tokenizer/sampling/Engine/Pressure hashes. |
| F3/F4/F5 -- Pressure and resources | `r1` cache-seeding wave completes; boundary follows four tied `r2` Native submissions; complete `r2` inflight set; 24,576 IDs passed into same-Engine BlockPool allocation of 1,536 blocks; returned blocks held then released; 2,048-block pool; `max_num_seqs=4`; Adapter capacity 4; dynamic Forced Release/eviction gates retained. |
| F6/F7 -- terminal and Abort boundary | EOS/STOP-token and LENGTH accepted but separately reported; Stop String, explicit abort and error excluded; sampling frozen; Part B structurally fixed to `NOT_READY`. |
| N1--N5 related items | same-EngineCore observer/scheduler/KV preflight; run timeout, shutdown grace and reservation separated; controlled fixture explicitly not an Agent Trace or effect result; negative tests added. |

## 15. Stage conclusion

```text
PHASE5E_GPU_CONFORMANCE_PLAN = READY_FOR_M1_M4_REVIEW
PART_A_NATURAL_COMPLETION = READY_FOR_AUTHORIZATION_REVIEW
PART_B_STOP_STRING_ABORT = NOT_READY_MISSING_NATIVE_ABORT_CONFIRMATION
GPU_CONFORMANCE_EXECUTION = NOT_AUTHORIZED
TRACE_ACQUISITION = NOT_AUTHORIZED
ALGORITHM_EFFECT_EXPERIMENT = NOT_AUTHORIZED
```

The next decision is limited to whether M1 accepts and authorizes the single
bounded Part A run. This report does not start that run or broaden Phase 5 into
a new replay framework.
