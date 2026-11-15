# Phase 5B Async Native Integration Report

**Status:** CPU/Mock engineering contract implemented; GPU conformance and Trace
Acquisition are not authorized and not executed.

**Base commit:** `1ee0f4e64af3da7009d66dd3a965dfc19a4ce8fa`

## 1. Scope and non-goals

This stage maps the accepted Phase 5A N-session replay and candidate-exposure
contracts onto an incremental Native lifecycle. It does not change A0/A1/A2/A3/E0,
Protocol v4, historical cohorts, or effect metrics. No trace acquisition, GPU run,
or formal effect experiment was performed.

## 2. Reused components

- `phase5_replay.py`: frozen arrivals, N-session event plan, workload seal, actual
  `VLLM_REQUEST_SUBMITTED` order gate, and cross-arm order comparison.
- `phase2.py`: immutable `PlannedRequest` input.
- `phase2b_fidelity_runner.py`: `RequestHandle` and `RequestCompletion` identities.
- `phase5_candidate_exposure.py`: stable decision-boundary alignment and unique
  Decision/Binding/SelectionPlan/PhysicalOutcome joins.

The legacy `drain_native()` path is intentionally not used. It waits for every
pending request and would silently turn an event-driven workload into waves.

## 3. Async Native adapter contract

`Phase5AsyncNativeBackend` requires six operations:

1. prepare a frozen logical arrival;
2. submit that prepared request without waiting for generation;
3. incrementally poll terminal completions, optionally waiting for at least one;
4. finish the Continuum logical lifecycle at the frozen completion boundary;
5. execute one explicitly typed pressure boundary; and
6. expose the persisted Native event stream for independent enqueue-order review.

`CallbackPhase5NativeAdapter` is the concrete injection surface for a future
pinned-vLLM binding. It deliberately accepts no full-drain callback. The current
vLLM-backed implementation only exposes an all-pending drain, so real Native
integration remains blocked until an incremental completion primitive is proven.

## 4. Event-driven state machine

Each request follows:

`PLANNED -> PREPARED -> SUBMITTED -> NATIVE_COMPLETED -> LOGICAL_COMPLETED`

`FAILED` is terminal. Unknown, duplicate, identity-mismatched, cancelled, timed-out,
or reasonless failed completions fail closed. Capacity backpressure calls incremental
polling and accepts one or more completed requests; it never asks the backend to
empty all work. Native completions may be out of submission order and are buffered
until their frozen logical completion boundary.

Planned/logical timestamps and Native timestamps are recorded in separate fields.
They are not subtracted or globally sorted across clock domains. Actual submission
order must independently pass the Phase 5 Workload Seal gate after execution.

## 5. Pressure semantics

Every pressure boundary predeclares exactly one contract:

- `QUIESCENT_BARRIER`: the controller incrementally waits until Native inflight is
  empty before executing pressure.
- `LIVE_STATE`: the exact expected inflight request-ID set is frozen and must match
  both controller state and the backend's Native pressure snapshot.

The two modes cannot be inferred or mixed at runtime. Pressure evidence carries a
Native snapshot timestamp and inflight IDs, while its planned boundary retains the
logical timestamp.

## 6. Candidate-exposure evidence association

The Phase 5B join requires a passing async execution report, a passing actual-enqueue
gate, and a Decision identity that equals an executed pressure boundary. Binding
context must be Pressure-compatible. Selection-plan and physical-outcome block sets
must be unique, mutually disjoint, and cannot contain blocks outside the plan.

This is an evidence-topology check, not a causal result. Block reuse, content
generation identity, pending-plan validity windows, and downstream recomputation are
not yet fully observable in the CPU contract. Reports therefore retain:

- `physical_causal_attribution = NOT_ESTABLISHED`
- `downstream_recompute_attribution = NOT_ESTABLISHED`

## 7. CPU/Mock verification

The focused suite covers:

- 2/4/8/16 Programs;
- frozen submission order and per-Program order;
- capacity two with incremental one-at-a-time completion collection;
- out-of-order Native completions;
- exact live-pressure inflight binding and mismatch rejection;
- completion identity mismatch and no-progress timeout behavior;
- controller order versus persisted Native submission evidence;
- Decision-to-pressure association; and
- overlapping or out-of-plan physical block evidence.

The Phase 5A replay and exposure suites are run together with the Phase 5B tests.
The actual command and result belong in the PR validation record; historical test
results must not be substituted.

## 8. Remaining integration risks

1. **P0 incremental polling:** pinned vLLM 0.27.1 has not yet been proven to expose a
   nonblocking or bounded one-or-more completion collector. A wrapper around
   `drain_native()` is unacceptable.
2. **P0 pressure behavior:** real pressure execution must preserve the chosen
   quiescent/live contract and persist the Native inflight snapshot.
3. **P1 time domains:** source completion, logical completion, Native completion,
   and wall time must remain distinct in the archive.
4. **P1 physical attribution:** block-ID reuse, content identity, registry freshness,
   intervening allocation, and right censoring require additional runtime evidence.
5. **P1 failure cleanup:** GPU integration must demonstrate cancellation and bounded
   shutdown without leaked Native requests.

## 9. Proposed GPU conformance entry conditions

GPU conformance remains `NOT_AUTHORIZED` and `NOT_READY`. A separate request should
be submitted only after all of the following are available:

- a verified incremental vLLM completion API with no full drain;
- a pre-frozen, non-effect fixture with at least four Programs, one arrival tie,
  peak Native inflight at least two, and one explicit pressure contract;
- archiveable planned-arrival, actual-submit, Native-completion, logical-completion,
  and pressure-snapshot streams;
- identical seal/token/timeline/capacity/pressure hashes across arms;
- a timeout and failure-archive plan; and
- acceptance criteria limited to conformance, not algorithm benefit.

Suggested first authorization, if the interface blocker is closed: one bounded run
per required integration arm, 10-minute per-run ceiling, plus a 60-second termination
grace. The exact arm set and GPU budget require M1 approval before execution.

## 10. Trace acquisition planning boundary

Trace Acquisition remains `NOT_AUTHORIZED`. Its later proposal must separately bind
source license/revision, full payload, token identity, Program/Session identity,
tool gaps, arrival generation, qualification rules, and deterministic replacement.
No candidate may be selected using policy outcomes or candidate-exposure results.

## 11. Stage conclusion

`PHASE5B_CPU_ASYNC_CONTRACT = IMPLEMENTED`

`PHASE5B_INCREMENTAL_NATIVE_BINDING = BLOCKED_PENDING_PINNED_VLLM_API_PROOF`

`TRACE_ACQUISITION = NOT_AUTHORIZED`

`GPU_CONFORMANCE = NOT_AUTHORIZED_NOT_READY`
