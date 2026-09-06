# Phase 1B Continuum Implementation Decision Record

## Purpose

This document supplements `docs/baseline-freeze.md` with implementation-level decisions required to complete the frozen Phase 1B Continuum-style baseline on vLLM 0.27.1.

The baseline scope itself is unchanged: explicit program/session identity, dynamic TTL retention, soft protection, deterministic pressure release, program-level waiting/admission scheduling, and native vLLM BlockPool bookkeeping.

If this document and `docs/baseline-freeze.md` appear to conflict, `docs/baseline-freeze.md` remains authoritative unless that freeze is explicitly updated.

This record resolves implementation details that were previously open. It does **not** change the project research hierarchy: the primary proposed contribution remains Cost-Aware KV-cache eviction / victim selection; Continuum retention and scheduling are implemented because they are intrinsic to the strong baseline.

---

## 1. Dynamic TTL estimator

### Decision

Use the Continuum-style dynamic TTL mechanism rather than the older simplified Related-Work description.

The implementation must preserve the following structure:

```text
observed gap-duration distribution
+ queueing-delay benefit
+ program memoryfulness / continuity signal
+ estimated prefill-reload cost
-> choose a TTL that maximizes expected net benefit
```

A fixed TTL, arbitrary timeout, or mean/std-only heuristic is not an acceptable primary estimator.

### 1.1 Gap-history source

Maintain separate histories for:

```text
server_inter_request_gap
external_tool_duration
```

Do not mix them into one distribution.

The primary Continuum baseline uses:

```text
server_inter_request_gap
= previous turn server finish
  -> next turn request arrival
```

External tool duration remains observable metadata for analysis and possible later ablation.

Tool-specific history is preferred. If no tool-specific samples exist, fall back to global history.

If neither tool-specific nor global duration history exists, use:

```text
TTL = 0
```

This cold-start fallback is deterministic and conservative; do not insert an arbitrary constant timeout.

### 1.2 Queueing-delay term T

Use the rolling mean of the most recent admitted requests:

```text
K = 100
waiting_delay = admission_time - request_arrival_time
T = mean(last up to K waiting_delay samples)
```

Cold start:

```text
no waiting-delay history -> T = 0
```

Input source classification: `OBSERVED`.

### 1.3 Memoryfulness eta

Estimate the program-level memoryfulness/continuity signal from completed-program history.

If online completed-program samples are not yet sufficient, a workload warm-up estimate may be used, provided that:

- the warm-up trace and sample rule are frozen before formal evaluation;
- the implementation logs that the value is warm-up-derived;
- the value is not silently replaced by an arbitrary constant.

Input source classification: `OBSERVED` when online-derived, otherwise `APPROXIMATED`.

### 1.4 PrefillReload

Use an offline profile on the target model/hardware to estimate prefill recomputation latency as a function of reusable/prefix token count.

The first implementation may use a lightweight lookup/interpolation model. It does not need a complex learned predictor.

Input source classification: `APPROXIMATED`.

### 1.5 Candidate TTLs and tie-breaking

Use a discrete candidate set derived from observed duration history, including zero. Do not introduce a separate continuous optimizer in Phase 1B.

For equal objective values, use a deterministic tie-break and document it in the implementation file. Prefer the smaller TTL unless a paper-faithfulness check later requires a different exact tie-break.

---

## 2. Lifecycle semantics

### 2.1 Follow-up already waiting when TTL expires

If a retention deadline has passed but a follow-up request for the same program is already in the waiting queue, do not immediately drop that program's protection.

Protection may remain until the follow-up is admitted or the program is explicitly terminated/completed.

This prevents expiration at exactly the point where reuse is imminent.

### 2.2 Program completion

The workload/orchestrator must support an explicit lifecycle indication such as:

```text
program_completed
or
is_last_turn
```

After the final turn completes, release that program's retention/protection state immediately rather than waiting for the TTL to expire naturally.

---

## 3. Memory-pressure release

Keep the existing frozen project adaptation.

When pressure requires reclamation:

```text
1. expire entries whose deadlines have been reached
2. use eligible/unprotected cached blocks first
3. if insufficient, release protected retention entries
4. release protected entries by:
      earliest retention deadline
      -> native LRU rank tie-break
5. actual eviction/removal still uses the existing Phase 1A/native BlockPool path
```

This rule is a **PROJECT ADAPTATION**, not a claim about Continuum's native pressure rule.

Do not switch Phase 1B to a different pressure rule without updating `docs/baseline-freeze.md` first.

---

## 4. Shared-block protection

### 4.1 Protection aggregation

Use `any-protected` semantics.

If one physical block is associated with multiple logical `(program_id, prefix_id)` retention entries:

```text
if any associated live entry is protected
-> the physical block is protected
```

Releasing one program/prefix entry must not make a block eligible if another live protected entry still depends on it.

### 4.2 Release and eligibility units

Logical release unit:

```text
(program_id, prefix_id) retention entry
```

Physical eviction-eligibility unit:

```text
block
```

Therefore the retention manager aggregates logical entry state into block eligibility before victim selection.

### 4.3 Partial-prefix behavior

Partial-prefix semantics remain intentionally OPEN pending a real vLLM 0.27.1 observation spike.

Do not assume that suffix blocks remain useful after an earlier prefix block is lost, and do not assume the entire suffix is automatically useless without evidence.

The first controlled Phase 1B validation workloads should avoid depending on partial-prefix retention behavior.

A later freeze update is required if formal experiments need explicit partial-prefix policy semantics.

---

## 5. Retention-aware free-queue coordination

Introduce a retention-aware coordinator around the existing Phase 1A decision path rather than rewriting the adapter.

Conceptual structure:

```text
native free-queue snapshot
        -> RetentionAwareSelectionCoordinator
        -> expiry / protection aggregation / pressure release
        -> existing VLLMEvictionBridge
        -> EvictionPolicyAdapter
        -> selected block IDs
        -> native BlockPool bookkeeping
```

The existing `EvictionPolicyAdapter` and `VLLMEvictionBridge` basic contracts remain unchanged.

### 5.1 Meaning of `unprotected first`

For retention-sensitive **cached blocks**, actual controlled selection must consume eligible/unprotected cached blocks before pressure-released protected cached blocks.

This is stronger than merely changing a metadata flag before one global selection pass.

### 5.2 Unhashed free blocks

Free blocks without cache hash metadata:

- are not retention-protected;
- keep their native free-queue relative ordering;
- must not be artificially moved to the front or back merely because the retention coordinator exists.

### 5.3 Selection plan

Before enabling controlled retention-aware queue behavior, define and test a deterministic `SelectionPlan` (or equivalent contract) that explains:

- how many physical blocks are required;
- which native free blocks remain untouched;
- which cached blocks are eligible;
- which protected entries, if any, were released;
- the final block order passed to the existing native/Phase 1A path.

Do not silently change Phase 1A victim-selection semantics to implement retention.

---

## 6. Scheduler ordering

The first controlled scheduler implementation changes only waiting/admission order.

Do not change running-request preemption victim selection.

### 6.1 Waiting priority

Use the following deterministic priority classes:

```text
1. request that was preempted and is now back in waiting
2. follow-up request belonging to a still-protected / within-TTL program
3. all other waiting requests ordered by program-level FCFS
```

The first class applies only to requests already returned to waiting. It does not authorize changing which running request is preempted.

### 6.2 Program FCFS key

Define:

```text
program_arrival_time
= server arrival time of the program's first request/turn
```

All later turns of the same program keep this stable key.

### 6.3 Deterministic tie-break

Use:

```text
priority class
-> program_arrival_time
-> request arrival_time
-> request_id
```

### 6.4 Integration sequence

Implementation sequence:

```text
observation-only integration
-> shadow ordering
-> native-equivalence validation
-> controlled waiting/admission ordering
```

The scheduler policy continues to return ordered request IDs; native vLLM remains responsible for queue mutation, status changes, allocation, and bookkeeping.

---

## 7. Input-source classification

Every dynamic-TTL input must be logged/classified as one of:

```text
NATIVE
OBSERVED
EXTERNAL
APPROXIMATED
UNAVAILABLE
```

At minimum, the implementation documentation must identify the source for:

- server inter-request gap history;
- external tool duration if recorded;
- rolling queueing-delay estimate;
- memoryfulness estimate;
- prefill-reload estimate;
- program/session identity;
- prefix/block observation.

No unavailable input may be silently replaced by an arbitrary constant and then described as faithful reproduction.

---

## 8. Work that is now unblocked

Member 3 may now implement:

- runtime-neutral identity/lifecycle types;
- `InputSource` classification;
- lifecycle event handling;
- program/prefix/block many-to-many indexes;
- stale mapping cleanup;
- injectable monotonic clock;
- formal dynamic TTL estimator;
- prefill-reload profiler interface;
- `RetentionStateManager`;
- lazy expiry;
- `any-protected` aggregation;
- retention-aware pressure planning / `SelectionPlan`;
- retention-aware coordinator around Phase 1A;
- scheduler native/shadow/controlled modes;
- controlled multi-turn validation.

Partial-prefix policy semantics remain open but do not block the first Phase 1B implementation.

---

## 9. Documentation boundary

Older Related-Work notes may still contain historical simplifications, including descriptions of Continuum as retention-only or simplified TTL summaries.

Those files are literature notes, not implementation specifications.

Member 3 should implement according to:

```text
docs/baseline-freeze.md
+ docs/phase1b-continuum-implementation-decisions.md
```

Member 3 should not edit Member 2's literature notes as part of the baseline implementation unless explicitly assigned.

---

## 10. Research-scope reminder

Phase 1B implements a strong Continuum-style system baseline.

Its retention and scheduling components are baseline mechanisms, not the project's primary claimed contribution.

The project research hierarchy remains:

```text
Primary contribution:
    Cost-Aware KV Cache Eviction / Victim Selection

Supporting mechanism:
    Retention / Protection

System coordination:
    Scheduling
```

Do not add Cost-Aware-only signals or scoring logic to the Continuum implementation.
