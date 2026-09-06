# Phase 1B Continuum Implementation Decision Record

## Purpose

This document supplements `docs/baseline-freeze.md` with implementation-level decisions for the frozen Phase 1B Continuum-style baseline on vLLM 0.27.1.

If this document and `docs/baseline-freeze.md` conflict, `docs/baseline-freeze.md` remains authoritative unless that freeze is explicitly updated.

The project research hierarchy is unchanged: the primary proposed contribution remains **Cost-Aware KV-cache eviction / victim selection**. Continuum retention and scheduling are implemented because they are intrinsic to the strong baseline.

---

## 1. Dynamic TTL — final Phase 1B semantics

### 1.1 Paper objective

Phase 1B accepts Continuum v6 Equation (2) as the primary TTL objective:

```text
tau* = argmax_tau P(tau, f) * (T * eta + PrefillReload(r)) - tau
```

where all time-valued quantities are represented internally in **seconds**.

The empirical CDF is:

```text
P(tau, f)
= (1 / |S[f]|) * sum_{t in S[f]} I[t <= tau]
```

When a global history is used, `S[f]` is replaced by the global duration sample set.

For empirical-history modes, enumerate:

```text
{0} union unique(observed durations)
```

as TTL candidates and choose the candidate with maximum objective value.

Tie-break:

```text
equal objective -> smaller tau
```

Do not replace this objective with a mean/std heuristic or a fixed TTL in the steady-state estimator.

### 1.2 Duration-history source

Maintain separate histories for:

```text
server_inter_request_gap
external_tool_duration
```

Do not mix them into one distribution.

The primary Continuum baseline uses:

```text
server_inter_request_gap
= next-turn server arrival
  - previous-turn server finish
```

as the duration samples used by the TTL estimator.

External tool duration remains separately recorded metadata for diagnostics/ablation only.

### 1.3 Cold-start hierarchy and K=100

Correct the previous decision: `K=100` is **not** the queue-delay window length.

Use:

```text
duration_history_threshold = 100
```

for the Continuum history-reliability hierarchy:

```text
if |global duration history| <= 100:
    use T_default
else if |tool-specific duration history| <= 100:
    use global empirical CDF
else:
    use tool-specific empirical CDF
```

This follows the paper-level three-stage structure.

`T` is initialized to zero at serving cold start.

#### T_default

`T_default` is a **paper-derived cold-start mechanism with a project-level concretization**.

For the pinned model/hardware configuration, compute one deterministic startup `T_default` from the same TTL objective under:

```text
ToolCallDuration ~ Exp(mean = 1 second)
eta = 1
T = 0
```

using a frozen representative `PrefillReload` value obtained from the Phase 1B prefill profile for the controlled baseline configuration.

The representative context/prefix size used to obtain that value must be written into `docs/continuum-baseline-implementation.md` and kept fixed for all compared Phase 1B baseline runs using the same model/hardware configuration.

Classification: `APPROXIMATED` because vLLM 0.27.1 does not expose Continuum's original complete deployment context and the project must choose a representative profiled context size.

Do not use the previous `TTL=0 when no history` rule as the formal baseline cold-start behavior.

### 1.4 Queueing-delay term T

Accept the paper semantics:

```text
T = sliding-window mean queueing delay
    for historical requests whose reusable GPU KV state was evicted
```

A Phase 1B sample is eligible only when the project can establish, from its observation/eviction records, that the returning/follow-up request lost the relevant reusable GPU-resident KV state before admission.

For an eligible sample:

```text
queueing_delay = admission_time - request_arrival_time
```

Use:

```text
queue_delay_window_size = 100
```

as a **PROJECT ADAPTATION** because Continuum v6 specifies a sliding window but does not publish its length.

This constant must remain separately named from:

```text
duration_history_threshold = 100
```

so the two concepts cannot be confused in code, logs, or slides.

If there are no eligible queue-delay samples:

```text
T = 0
```

Classification: `OBSERVED`.

The queue-delay history is maintained per running baseline instance/model configuration, not pooled across unrelated model/hardware runs.

### 1.5 Memoryfulness eta

Use the paper definition without clipping:

```text
eta = -PearsonCorr(k, N-k)
```

Negative eta values are valid and must be preserved.

Executable Phase 1B sample construction:

- only **completed programs with known final turn count N** contribute;
- for each completed program, emit one pair for every non-terminal served turn:

```text
(k, N-k), for k = 1 .. N-1
```

- compute Pearson correlation across the accumulated turn-level pairs from completed programs;
- update eta when a program completes;
- keep the complete Phase 1B run history in the first implementation rather than applying an additional eta window.

If Pearson correlation is undefined because there are fewer than two usable pairs or either axis has zero variance:

```text
eta = 1
source = APPROXIMATED_COLD_START
```

This fallback matches the fully-memoryful assumption used by Continuum's cold-start model; it must be logged explicitly.

Otherwise:

```text
source = OBSERVED
```

Do not clamp eta to `[0,1]`.

### 1.6 PrefillReload

Use offline profiling on each model/hardware pair.

At minimum profile:

```text
prefix/context token count -> prefill recomputation latency
```

and use deterministic interpolation/fitted prediction for online lookup.

CPU-offload-specific reload profiling is not required because CPU offload is outside the Phase 1B primary configuration.

Classification: `APPROXIMATED`.

---

## 2. Lifecycle / expiry — final semantics

### 2.1 Waiting-follow-up exception

Ordinary lazy expiry is:

```text
expire entry if deadline reached
AND no follow-up of the same program is currently waiting
```

If the deadline is reached but a same-program follow-up is already waiting, the entry stays protected during ordinary expiry.

### 2.2 Interaction with memory pressure

The waiting-follow-up exception does **not** make protection absolute.

Under actual allocation pressure:

```text
1. expire ordinary expired entries
2. reclaim ordinary eligible/unprotected cached blocks
3. if still insufficient, waiting-follow-up entries remain protected candidates
   but may be released by the frozen protected-fallback planner
```

Thus the exception protects against premature lazy expiry but cannot deadlock allocation.

### 2.3 Admission, cancellation, new turn, terminal cleanup

Use the following transitions:

```text
follow-up admitted
-> consume/end the prior idle-retention interval for that program

waiting follow-up cancelled/removed
-> immediately re-evaluate expiry against current time

new non-terminal turn finishes
-> incorporate the newly observed inter-request history when available
-> create the next retention deadline using the current TTL estimator

program terminal / last turn finishes
-> immediately release all retention/protection state owned only by that program
```

Shared blocks remain protected if another live protected entry still references them.

---

## 3. Memory-pressure release — project adaptation remains frozen

Do **not** switch to Continuum's latest-program-arrival victim rule in Phase 1B.

The project adaptation remains:

```text
1. ordinary expiry
2. eligible/unprotected cached blocks first
3. if insufficient, release protected logical entries by:
      earliest retention deadline
      -> entry native-LRU key
      -> deterministic entry identity
4. physical eviction still flows through Phase 1A/native BlockPool bookkeeping
```

This must be labeled **PROJECT ADAPTATION** in implementation docs and results.

### 3.1 Entry native-LRU key

Logical release unit:

```text
(program_id, prefix_id) entry
```

Physical eligibility unit:

```text
block
```

For two protected entries with equal retention deadline, define the entry native-LRU key as:

```text
minimum native lru_rank among physical cached blocks
that would become newly eligible if this entry were released now
```

If releasing the entry alone would make no physical block newly eligible because every associated block remains protected by another entry:

```text
entry_lru_key = +infinity
```

Final deterministic tie-break after deadline and entry LRU key:

```text
(program_id, prefix_id) lexical/stable ordering
```

The planner must continue releasing subsequent protected entries until the number of **newly reclaimable physical blocks** is sufficient. Releasing a logical entry that produces zero newly eligible physical blocks does not count toward the required physical-block target.

---

## 4. Shared-block protection

Use `any-protected` semantics:

```text
if any associated live retention entry is protected
-> physical block is protected
```

Releasing one program/prefix entry must not expose a shared block that is still protected by another entry.

Logical release and physical block eligibility remain separate layers.

### Partial prefix

Partial-prefix behavior remains the only intentionally OPEN cache-semantic question in the first Phase 1B implementation.

M3 must perform a real vLLM 0.27.1 observation spike before defining suffix usefulness after an earlier prefix block is evicted.

The first controlled validation workload must not depend on partial-prefix semantics.

---

## 5. Retention-aware free-queue SelectionPlan — final merge contract

Keep `EvictionPolicyAdapter` and `VLLMEvictionBridge` basic Phase 1A semantics unchanged.

Add a retention-aware coordinator / `SelectionPlan` around that path.

For one native free-queue snapshot:

1. classify cached blocks by retention state;
2. perform ordinary expiry;
3. release protected entries only if required by pressure;
4. reconstruct the controlled physical selection order using the following rule.

### Final queue-merge rule

Only reorder the **retention-sensitive cached-block subsequence**.

Unhashed/free blocks:

- are never retention-protected;
- stay in their original queue slots;
- keep their native relative order.

For the cached-block subsequence, use:

```text
eligible/unprotected cached blocks
-> pressure-released protected cached blocks
```

Within each cached group, preserve native LRU order.

Then place that reordered cached subsequence back into the original cached-block slots, leaving unhashed-block positions unchanged.

The first `required_blocks` of the resulting physical order define the controlled selection plan.

This contract makes `unprotected first` a real selection guarantee for cached blocks without arbitrarily moving unhashed free blocks.

The `SelectionPlan` must log at least:

- `required_blocks`;
- original physical free-queue order;
- ordinary expired entries;
- protected entries released for pressure;
- newly eligible physical blocks per released entry;
- final physical selection order.

---

## 6. Scheduler ordering — unchanged and frozen

First implementation changes waiting/admission order only.

Do not change running-request preemption victim selection.

Priority classes:

```text
1. preempted request already returned to waiting
2. follow-up belonging to a currently protected/within-TTL program
3. all other requests
```

Within category:

```text
program_arrival_time
-> request arrival_time
-> request_id
```

where:

```text
program_arrival_time
= server arrival time of the program's first request
```

Implementation sequence:

```text
observation
-> shadow
-> native-equivalence validation
-> controlled waiting/admission ordering
```

---

## 7. Input-source classification

Every TTL input must be logged as one of:

```text
NATIVE
OBSERVED
EXTERNAL
APPROXIMATED
UNAVAILABLE
```

Required classifications include:

- program/session identity: `EXTERNAL`;
- server inter-request gap: `OBSERVED`;
- external tool duration when provided: `EXTERNAL`;
- empirical duration history/CDF: `OBSERVED`;
- queue-delay T: `OBSERVED`;
- eta: `OBSERVED` or explicit `APPROXIMATED_COLD_START`;
- PrefillReload: `APPROXIMATED` from offline profile;
- T_default: `APPROXIMATED` project concretization of the paper cold-start model;
- prefix/block mapping: `OBSERVED`.

Unavailable values may not be silently replaced by arbitrary constants.

---

## 8. M1 vs M3 decision boundary

The following semantics are now frozen at project level:

- TTL objective/CDF/cold-start hierarchy;
- duration-history threshold;
- queue-delay sample population and window size;
- eta sample construction/fallback/no clipping;
- waiting-follow-up vs pressure behavior;
- entry-level protected-release ordering;
- full free-queue merge contract;
- scheduler priority semantics.

M3 owns the internal implementation design that satisfies those invariants, including:

- `prefix_id` encoding/tuple/hash representation;
- reverse-index container choices;
- stale-association cleanup mechanism;
- helper/class decomposition;
- generation/version tracking if useful;
- exact internal APIs and test organization.

For `prefix_id`, the project-level correctness invariants are only:

```text
1. stable identity for the same reusable prefix across request lifetimes
2. never use request_id as prefix identity
3. prefer native vLLM content/block-hash identity over prompt-text inference
4. respect every native cache namespace/isolation dimension relevant to APC reuse
5. block_id is ephemeral physical identity, not logical prefix identity
6. real eviction/reassignment must invalidate stale reverse associations
7. observation metadata must never affect inference correctness
```

If vLLM 0.27.1 model/cache_salt/LoRA or other hash-namespace behavior prevents these invariants from being implemented without changing a frozen runtime boundary, M3 must report a blocker. Otherwise the concrete `prefix_id` construction is M3's implementation decision and must be documented in `docs/continuum-baseline-implementation.md`.

---

## 9. Work now unblocked

M3 may proceed with the formal Phase 1B implementation, including:

- identity/lifecycle types;
- `InputSource`;
- program/request observation;
- prefix/block many-to-many index;
- stale mapping cleanup;
- injectable monotonic clock;
- formal Continuum TTL estimator;
- cold-start hierarchy;
- eta provider;
- prefill profile interface;
- retention manager;
- `any-protected` aggregation;
- `SelectionPlan` and pressure coordinator;
- scheduler native/shadow/controlled modes;
- controlled multi-turn validation;
- real vLLM 0.27.1 GPU validation.

Only explicit partial-prefix policy semantics remain open, and they do not block the first Phase 1B implementation.

---

## 10. Documentation boundary

Implementation authority:

```text
1. docs/baseline-freeze.md
2. docs/phase1b-continuum-implementation-decisions.md
3. docs/experiment-plan.md
4. docs/architecture.md
5. docs/continuum-vllm-mapping.md
```

Older Related-Work notes are not implementation specifications.

Do not add Cost-Aware-only scoring/signals to this baseline.
