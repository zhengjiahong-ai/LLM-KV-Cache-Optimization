# Phase 5C Pinned vLLM API Feasibility Report

**Status:** CPU interface proof and pinned vLLM 0.27.1 source inventory complete;
GPU Conformance, Trace Acquisition, and effect experiments were not executed.

**Base commit:** `2867c63` (PR #117 merge)

## 1. Scope

Phase 5C asks whether vLLM 0.27.1 can support incremental request completion
without replacing the Native scheduler, changing KV ownership, or disguising an
all-request drain as asynchronous execution. This report combines:

1. the behavior already observed in the project's pinned 0.27.1 environment;
2. the corresponding official vLLM 0.27.0 source documentation (the closest
   published source reference); and
3. a CPU-only output-pump and arrival-timing contract.

The exact installed 0.27.1 source is not present in the local macOS environment.
`scripts/spikes/audit_phase5c_vllm_api.py` therefore performs a read-only,
version-locked source inventory on the existing server environment. It creates no
engine and performs no GPU work. The audit was executed successfully in no-GPU mode
on 2026-11-16.

## 2. Source and behavior evidence

### 2.1 Top-level offline `LLM`

The pinned project currently calls `LLM.enqueue()` followed by
`LLM.wait_for_completion()`. Official v0.27.0 documentation states that `enqueue`
adds requests but does not start processing, while `wait_for_completion` processes
all currently queued requests and returns after all complete:

- <https://docs.vllm.ai/en/v0.27.0/api/vllm/>
- source module: `vllm/entrypoints/llm.py`
- relevant methods: `LLM.enqueue`, `LLM.wait_for_completion`

Conclusion: this interface cannot implement Phase 5B incremental capacity release.
It remains useful for batch/offline inference but not for N-session event-driven
replay.

### 2.2 Synchronous `LLMEngine`

The synchronous path is:

1. `LLMEngine.add_request()` processes input;
2. registers RequestState in `OutputProcessor`;
3. sends the request to `EngineCoreClient.add_request()`;
4. `LLMEngine.step()` calls blocking `engine_core.get_output()`;
5. passes incremental Core outputs through `OutputProcessor.process_outputs()`;
6. aborts requests that finished through frontend stop-string handling; and
7. returns processed `RequestOutput` objects.

References:

- <https://docs.vllm.ai/en/v0.27.0/api/vllm/v1/engine/llm_engine/>
- <https://docs.vllm.ai/en/v0.27.0/api/vllm/v1/engine/output_processor/>

`SyncMPClient.get_output()` consumes a blocking queue. Calling it from the replay
thread would block future planned arrivals. Concurrently calling `step()` from a
second consumer is also invalid because `OutputProcessor` and the Core output stream
require a single owner.

Conclusion: a custom SyncMP background consumer is technically possible only if it
owns the entire `step()` pipeline and thread safety of concurrent submission is
proven. This is a high-risk private adaptation and is not the recommended path.

### 2.3 Async Core and `AsyncLLM`

The asynchronous Core client provides `add_request_async()` and
`get_output_async()`. `AsyncLLM` starts one background output handler, registers a
per-request `RequestOutputCollector`, adds the request to the same OutputProcessor,
and awaits Core submission. The background handler retains full OutputProcessor,
detokenization, stop-string and abort semantics.

References:

- <https://docs.vllm.ai/en/v0.27.0/api/vllm/v1/engine/core_client/>
- <https://docs.vllm.ai/en/v0.27.0/api/vllm/v1/engine/async_llm/>
- `AsyncMPClient.add_request_async`
- `AsyncMPClient.get_output_async`
- `AsyncLLM.add_request`
- `AsyncLLM._run_output_handler`
- `RequestOutputCollector.get` / `get_nowait`

Conclusion: `AsyncLLM` is the preferred feasibility path. It provides incremental,
per-request processed outputs while preserving one Core-output consumer and the
native OutputProcessor lifecycle.

## 3. Completion semantics

The following landmarks are not interchangeable:

| Landmark | What it proves | What it does not prove |
|---|---|---|
| Client dispatch returned | Input was accepted by the client transport/API | Scheduler admission or GPU start |
| EngineCore output observed | Incremental Core progress was received | Request terminal state |
| OutputProcessor partial output | A processed partial result exists | Capacity may be released |
| OutputProcessor terminal output | Frontend request lifecycle is terminal | Exact physical GPU completion time |
| Scheduler queued/scheduled event | Native scheduler timing, if emitted | It cannot be inferred from dispatch return |

Phase 5 uses `OutputProcessor terminal` as its proposed Native completion landmark.
Partial results never release inflight capacity. EngineCore batch timestamps remain
batch observations and do not manufacture strict per-request hardware completion
ordering.

## 4. Recommended adapter design

The recommended adapter is version-locked to vLLM 0.27.1 and built around
`AsyncLLM` rather than `LLM.enqueue()/wait_for_completion()`.

1. The Phase 5 controller freezes the planned arrival and waits until its mapped
   Native target.
2. The adapter records `ADAPTER_DISPATCH_STARTED`.
3. It calls `AsyncLLM.add_request()` with explicit token IDs and the project request
   identity.
4. When that await returns, it records `ADAPTER_DISPATCH_RETURNED`. This is labelled
   client-dispatched, not scheduler-admitted.
5. One vLLM-owned output handler consumes Core outputs and applies OutputProcessor
   semantics.
6. One adapter task per RequestOutputCollector observes partial and terminal outputs.
7. Only terminal processed outputs enter the Phase 5B local completion queue.
8. Existing Native queued/scheduled hooks, if present, remain the only evidence for
   scheduler timing.
9. Adapter failure, Core death, abort, timeout and cancellation atomically fail and
   clean every outstanding request.

The adapter may observe but must not replace the scheduler, BlockPool, prefix cache,
KV allocation, eviction, request priority, or OutputProcessor. Native cache ownership
therefore remains with vLLM.

## 5. CPU interface proof

`src/kvopt/workload/phase5_vllm_api.py` implements two narrow contracts.

### 5.1 `VLLMOutputProcessorPump`

- exactly one bound output owner;
- accepts only outputs after OutputProcessor semantics;
- distinguishes partial and terminal outputs;
- exposes terminal completions through a local incremental queue;
- rejects unknown, duplicate and identity-mismatched outputs;
- supports registration rollback after dispatch failure; and
- broadcasts pump failure to all outstanding requests exactly once.

### 5.2 `NativeArrivalTimingLedger`

The ledger records, without conflation:

- frozen planned offset and mapped Native target;
- dispatch start and return;
- optional Native queued/scheduled events;
- first processed output;
- terminal processed output; and
- all EngineCore batch timestamps.

It computes only within-domain values:

- arrival lateness = dispatch start minus mapped planned target;
- client dispatch duration = dispatch return minus dispatch start.

It prohibits direct arithmetic between adapter Native monotonic and EngineCore
monotonic timestamps.

CPU tests cover partial output, incremental terminal collection, same-batch terminal
observation, single-owner enforcement, unknown/duplicate outputs, dispatch rollback,
pump failure and deterministic arrival mapping.

## 6. Pinned-server source inventory

The read-only audit was executed under the existing pinned Python environment. It
required exactly `vLLM 0.27.1` and recorded method signatures, source paths, first
lines, method-source SHA-256 and complete source-file SHA-256 for:

- `LLM.enqueue` and `wait_for_completion`;
- `LLMEngine.add_request` and `step`;
- SyncMP and AsyncMP completion/submission methods;
- `AsyncLLM.add_request` and `_run_output_handler`; and
- OutputProcessor and RequestOutputCollector methods.

Observed result:

- audit status: `PASS`;
- output: `artifacts/phase5c-vllm-api-source-audit-v1.json`;
- audit SHA-256:
  `bb7e222bd2f0f20c66b6a9d358b78fa00fe50153858ceec286247c4d851e1fb0`;
- engine created: `false`;
- GPU execution: `false`.

The no-GPU process reported that Triton had no active driver and that no CUDA runtime
was available. These messages are expected for no-GPU mode and do not affect Python
source inspection. Any missing method, version drift, or signature drift would have
failed closed. This source inventory is not itself GPU Conformance.

## 7. Arrival Timing fidelity

One run freezes a Native monotonic epoch and maps each logical offset to:

`native_target = run_epoch_native_monotonic + frozen_logical_offset`

The dispatcher must not start before this target. Capacity waiting may make dispatch
late; that lateness is recorded rather than changing the frozen plan. Requests in the
same frozen tie class retain deterministic tie ordering.

Actual timing evidence must include:

- planned target;
- dispatch start/return;
- queued/scheduled when truly emitted by vLLM;
- first processed output;
- OutputProcessor terminal; and
- logical completion.

Identical enqueue order alone is insufficient. Conformance must demonstrate that a
later request was dispatched before an earlier request reached terminal state and
that peak actual inflight is at least two.

## 8. Risks

1. `AsyncLLM` is a lower-level integration surface and must be signature-locked.
2. Existing retention instrumentation was built around the synchronous offline LLM;
   hooks must be shown to observe the same EngineCore/Scheduler/BlockPool instance.
3. Submission failure after OutputProcessor registration may leak frontend state
   unless rollback/abort is verified in pinned 0.27.1.
4. Stop-string completion may be frontend-terminal before Core abort acknowledgement.
5. EngineCore batch timestamp is not exact per-request GPU completion time.
6. Missing queued/scheduled metrics must be reported `NOT_OBSERVABLE`, never inferred.
7. A CPU output-pump proof does not establish pinned CUDA thread/task safety.

## 9. GPU Conformance entry conditions and estimate

GPU Conformance remains unauthorized. A later request should require:

- exact 0.27.1 source inventory PASS;
- AsyncLLM adapter implementation with no `wait_for_completion` or global drain;
- all partial/terminal/abort/error CPU paths passing;
- no leaked OutputProcessor RequestState after dispatch failure or shutdown;
- frozen fixture with at least four Programs, one arrival tie, actual peak inflight
  at least two and one explicit Pressure contract;
- complete planned/dispatch/scheduler/output/terminal/logical event archive;
- at least one later dispatch before an earlier request terminal;
- no active adapter task, engine child or GPU process after shutdown; and
- Candidate Exposure evaluated separately from adapter conformance.

Provisional resource estimate for a separately approved mechanism-only validation:

- one RTX 4090D 24 GB;
- the existing 1.5B model and frozen runtime;
- two bounded conformance runs (normal and injected failure), not an effect campaign;
- approximately 10–20 minutes expected, 30-minute hard execution ceiling;
- 60-second termination grace.

These values are planning estimates, not execution authorization.

## 10. Conclusion

`TOP_LEVEL_LLM_INCREMENTAL_COMPLETION = NOT_SUPPORTED`

`SYNC_MP_PRIVATE_PUMP = POSSIBLE_HIGH_RISK_NOT_RECOMMENDED`

`ASYNC_LLM_OUTPUT_COLLECTOR_PATH = FEASIBLE_SOURCE_PROOF_COMPLETE`

`PINNED_VLLM_0_27_1_SOURCE_INVENTORY = PASS`

`NATIVE_SCHEDULER_AND_KV_OWNERSHIP = UNCHANGED_BY_PROPOSED_ADAPTER`

`PHASE5C_GPU_CONFORMANCE_READY = NOT_YET`

`TRACE_ACQUISITION = NOT_AUTHORIZED`
