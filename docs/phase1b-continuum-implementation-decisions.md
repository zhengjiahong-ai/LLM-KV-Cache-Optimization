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

### 1.3 Upcoming tool identity at TTL-decision time

The TTL decision for a completed non-terminal turn must use the identity of the
tool that the turn is about to invoke. The completion observation must therefore
carry, when available:

```text
next_tool_type
is_terminal
finish_timestamp
```

The required ordering is:

```text
TURN_FINISHED(next_tool_type = f, is_terminal = false)
-> calculate TTL using the currently available history for f
-> create the retention deadline
-> begin pending server_inter_request_gap observation from finish_timestamp
```

Do not wait for an external tool-gap event before beginning retention, because
that would leave an unprotected interval after request completion.

If `next_tool_type` is unavailable, do not select an arbitrary tool-specific
history. Follow the cold-start hierarchy with tool-specific selection disabled:

```text
|global duration history| > duration_history_threshold
    -> use global empirical CDF
otherwise
    -> use T_default
```

The fallback and its reason must be logged. A terminal turn does not create a
new TTL or tool-gap interval and instead follows terminal cleanup.

`TOOL_GAP_STARTED` and `TOOL_GAP_ENDED` are explicit lifecycle events supplied
independently by the workload/orchestrator. They carry `program_id`,
`tool_type`, and a timestamp, and update `external_tool_duration` only. The
runtime must not synthesize `TOOL_GAP_STARTED` from `TURN_FINISHED`, or use the
pending server-side gap as an external tool duration. The external duration
remains separate from `server_inter_request_gap` and does not become the primary
TTL history.

### 1.4 Cold-start hierarchy and K=100

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

There is exactly one startup `T_default` for each frozen
model/hardware/profile configuration. It is computed from
`RepresentativePrefillReload`, not from the current request's
`PrefillReload(r)`, and therefore must not vary across requests in that
configuration.

With `mu = 1 second`, the fixed startup value is:

```text
T_default
= max(0, mu * ln(RepresentativePrefillReload / mu))
```

The ratio inside `ln` is dimensionless. A non-positive or non-finite profile
value is invalid configuration input rather than a request-time fallback.

The representative context/prefix size used to obtain that value must be written into `docs/continuum-baseline-implementation.md` and kept fixed for all compared Phase 1B baseline runs using the same model/hardware configuration.

Classification: `APPROXIMATED` because vLLM 0.27.1 does not expose Continuum's original complete deployment context and the project must choose a representative profiled context size.

Do not use the previous `TTL=0 when no history` rule as the formal baseline cold-start behavior.

After the estimator enters a global or tool-specific empirical-CDF mode, the
objective uses the current request's `PrefillReload(r)` as specified by
Equation (2).

### 1.5 Queueing-delay term T

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

### 1.6 Memoryfulness eta

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
source = APPROXIMATED
reason = FULLY_MEMORYFUL_COLD_START
```

This fallback matches the fully-memoryful assumption used by Continuum's cold-start model; it must be logged explicitly.

Otherwise:

```text
source = OBSERVED
```

Do not clamp eta to `[0,1]`.

### 1.7 PrefillReload

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
-> obtain next_tool_type from the completion observation when available
-> create the next retention deadline using history available at completion
-> begin retention immediately
-> begin pending server_inter_request_gap observation at finish_timestamp
-> do not wait for or synthesize an external TOOL_GAP_STARTED event

program terminal / last turn finishes
-> immediately release all retention/protection state owned only by that program
```

Shared blocks remain protected if another live protected entry still references them.

When the next request for the same program arrives, the observation layer
records both the follow-up arrival and the newly completed
`server_inter_request_gap`. Explicit `TOOL_GAP_STARTED` / `TOOL_GAP_ENDED`
events independently record `external_tool_duration`; the two histories must
not be mixed.

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

Add a retention-aware coordinator around that path. Responsibilities are split
as follows:

```text
RetentionAwareSelectionCoordinator
-> ordinary-expiry planning
-> protection aggregation
-> protected-entry release planning
-> ordered eligible block snapshot

VLLMEvictionBridge + EvictionPolicyAdapter
-> final victim-ID selection from that snapshot
-> existing Phase 1A output validation

SelectionPlan
-> records the coordinator decisions
-> records the adapter's actual validated victim IDs
```

The coordinator must not independently choose a final victim list and then ask
the adapter to choose a second time. For the Continuum baseline, the ordered
eligible snapshot is passed through `NativeLRUAdapter`, so the adapter preserves
the coordinator's Tier 1 then Tier 2 ordering while remaining the final
victim-selection boundary.

For one native free-queue snapshot:

1. classify free blocks by hash and retention state;
2. plan ordinary expiry;
3. build Tier 1 by skipping still-protected cached blocks;
4. plan protected-entry releases only if Tier 1 cannot satisfy `required_blocks`;
5. build Tier 2 from blocks made newly eligible by those releases;
6. pass the ordered eligible snapshot to the bridge/adapter for final selection.

### Final queue-merge rule

Unhashed/free blocks:

- are never retention-protected;
- may be selected even when an earlier cached block is still protected;
- keep their native relative order with every other Tier 1 block.

Tier 1 contains every ordinarily eligible block in its original native
free-queue relative order:

```text
unhashed free blocks
+ eligible/unprotected cached blocks
+ cached blocks made eligible by ordinary expiry
```

Still-protected cached blocks are omitted from Tier 1 rather than left in an
absolute queue slot that could block a later eligible block.

If Tier 1 is insufficient, release protected logical entries using the frozen
pressure order. Physical cached blocks that become newly eligible form Tier 2
in native LRU order. A release with zero marginally eligible physical blocks
does not count toward the target, and release planning continues until the
ordered eligible snapshot can satisfy `required_blocks`.

The bridge/adapter receives:

```text
ordered eligible snapshot = Tier 1 + Tier 2
```

The adapter's validated output defines the final selected block IDs. Unselected
blocks remain in the native free queue with their relative order unchanged.

Required edge case:

```text
native queue = [protected cached P, unhashed free E]
required_blocks = 1
-> Tier 1 = [E]
-> selected = [E]
-> P remains protected
```

When no block is protected, Tier 1 is the complete native free queue in native
order, preserving Phase 1A native-LRU equivalence.

The `SelectionPlan` must log at least:

- `required_blocks`;
- original physical free-queue order;
- ordinary expired entries;
- protected entries released for pressure;
- newly eligible physical blocks per released entry;
- Tier 1 and Tier 2 block order;
- adapter identity;
- adapter's actual validated selected block IDs;
- still-protected block IDs.

### Native, shadow, and controlled state transitions

Selection preparation is a pure computation over immutable queue and retention
snapshots. It must not mutate the native queue or the live retention manager.

```text
native
-> use the native selection path
-> do not apply a retention selection plan

shadow
-> compute and log a hypothetical selection/release plan
-> do not commit protected-entry releases
-> do not mutate live retention state
-> do not mutate the native free queue or APC metadata

controlled
-> prepare the eligibility/release plan
-> obtain and validate final victim IDs through the bridge/adapter
-> only then commit the planned logical release transitions
-> remove the validated selected blocks through the existing integration hook
-> retain native BlockPool ownership of eviction and metadata cleanup
```

Ordinary lifecycle observations may continue in shadow mode, but hypothetical
pressure releases must operate on a snapshot or an isolated shadow state and
must not contaminate live/controlled retention state. Shadow-mode tests must
therefore assert both native-queue and live-retention-state non-mutation.

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
- eta: `OBSERVED`, or `APPROXIMATED` with reason
  `FULLY_MEMORYFUL_COLD_START`;
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
