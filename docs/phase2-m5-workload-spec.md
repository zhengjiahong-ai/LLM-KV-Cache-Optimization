# Phase 2 Member 5 Spec — Experimental Harness, Workload, and Observability Infrastructure

## 1. Role

Member 5 owns the reusable **experimental substrate** for Phase 2.

The goal is not to decide what the Phase 2 result should be. The goal is to make later experiments easy to run, reproducible, and sufficiently observable that Member 6 does not need to patch runtime internals just to obtain raw data.

The responsibility can be summarized as:

```text
M5:
    can the experiment be reproduced?
    can the workload be replayed?
    can the runtime facts be observed?
    can the raw artifacts be trusted?

M6:
    which runs should be collected?
    which raw facts should be joined?
    which metrics / labels / oracle / regret should be derived?
    what do the results mean?
```

Phase 2A forced-release profiling is the first consumer of this infrastructure, not the definition of Member 5's role.

Authoritative project context:

- `docs/phase2-plan.md`
- `docs/experiment-plan.md`
- `docs/team-responsibilities.md`
- `src/kvopt/profiling/forced_release.py`

## 2. Ownership boundary

### Member 5 owns

- benchmark / experiment runner infrastructure;
- workload and trace representation;
- deterministic replay;
- program/session and multi-turn workload support;
- configurable arrival, tool-gap, follow-up, prefix, and pressure inputs;
- runtime configuration loading;
- run identity and provenance capture;
- raw runtime event exposure;
- raw artifact persistence;
- experiment failure/status recording;
- observability availability reporting;
- infrastructure-level smoke tests and reproducibility tests.

### Member 5 does not own

- the final Phase 2A experiment protocol;
- deciding which scenario combinations are scientifically important;
- formal sampling/sweep design;
- oracle definitions;
- counterfactual loss definitions;
- regret calculations;
- derived analysis tables;
- statistics or plots;
- research conclusions;
- Cost-Aware score design;
- modifications to baseline decision semantics.

If a required raw fact is not observable through an approved boundary, Member 5 reports the missing boundary to Member 1. Member 5 must not silently inspect or mutate private runtime state to manufacture the fact.

## 3. Design principle — expose raw facts, do not pre-analyze them

Member 5 should make useful runtime facts available in a stable machine-readable form whenever they can be observed without changing baseline semantics.

Prefer:

```text
request_arrival_timestamp
request_admission_timestamp
first_token_timestamp
request_finish_timestamp
```

over:

```text
queue_delay = ...
TTFT = ...
end_to_end_latency = ...
```

Prefer:

```text
forced-release candidate set
selected release entry
native eviction event
later request lifecycle
```

over:

```text
bad eviction
candidate loss
oracle regret
```

Derived values belong to Member 6 unless they are already native runtime facts.

## 4. Phase 2 experiment runner

Provide one reusable Phase 2 benchmark entry point rather than extending Phase 1B spike scripts indefinitely.

The runner must support at least:

- selecting a workload/trace;
- selecting a runtime/policy mode;
- loading model/backend configuration;
- setting seed;
- configuring cache/memory pressure;
- configuring generation/batching parameters;
- choosing output directory / run ID;
- enabling approved observation sinks;
- bounded termination / safety ceilings where pressure loops are used;
- explicit success/failure status.

The runner should be reusable by later Phase 2 experiments, not hard-coded to one forced-release hypothesis.

A suitable repository direction is:

```text
src/kvopt/workload/
benchmarks/
configs/phase2/
tests/
```

For example:

```text
benchmarks/run_phase2.py
src/kvopt/workload/phase2.py
configs/phase2/
tests/test_phase2_benchmark.py
```

Exact filenames are not frozen.

## 5. Workload / trace representation

The workload layer must support deterministic multi-program, multi-turn traces.

It should be possible to describe, without changing runner code:

```text
program/session identity
turn order
prompt or token construction
planned arrival offset
terminal / non-terminal turn
next tool type
tool-gap / follow-up timing
prefix/reuse construction
pressure-generating requests
generation parameters
```

The same logical trace/config must be replayable across different policies or experimental references.

Important separation:

- planned workload values are inputs;
- actual runtime timestamps, block IDs, prefix identities, cache hits/misses, and eviction effects are observations.

Do not hard-code observed runtime identities into trace definitions.

## 6. Deterministic replay

The framework must make reproducibility a first-class property.

For the same:

```text
git SHA
trace/config
seed
model revision
tokenizer revision
runtime/backend version
cache/memory settings
generation/batching settings
```

the framework should reproduce the same logical request/program sequence and workload inputs.

Runtime scheduling/timing may still differ because the backend is a real system. Those differences must be recorded rather than hidden or corrected after the fact.

Member 5 must provide tests for deterministic trace construction independent of the live GPU runtime.

## 7. Canonical run provenance

Every run must persist a run manifest with enough provenance to reproduce or reject the run.

At minimum expose:

```text
run_id
schema_version
git_sha
trace_id / workload_id
config snapshot or config hash
seed

backend/runtime identity
backend/runtime revision when available
model and revision
tokenizer and revision
hardware/platform identity

cache/block configuration
memory-pressure configuration
generation/batching parameters

start time
completion time
run status
failure reason if any
```

Do not silently fall back when required provenance is unavailable. Mark the field unavailable or fail the run when the missing fact would make the result non-reproducible.

## 8. Raw event stream

Provide a stable append-only raw event/artifact path for experiment observations.

A raw event should have a common envelope such as:

```text
schema_version
run_id
event_index
event_type
timestamp
clock_domain
source
program_id? 
request_id?
prefix_id?
payload
```

Requirements:

- `event_index` must provide deterministic ordering within the recorded stream;
- timestamps must identify their clock domain/source;
- unavailable fields remain absent/explicitly unavailable rather than guessed;
- raw events are append-only for one run;
- analysis must not rewrite raw artifacts.

JSONL is a reasonable first raw format, but the exact serialization is not frozen as long as it is stable and machine-readable.

## 9. Hardware / backend boundary

Member 5 is **not** responsible for making low-level GPU telemetry work identically on every team member's machine.

Different machines may use different:

- GPU vendors / models;
- CUDA / Metal / other backend stacks;
- driver/runtime versions;
- supported profiling APIs;
- counters exposed by the backend.

Member 5's responsibility is to define and preserve a stable observation boundary, for example:

```text
HardwareObservationProvider / BackendMetricProvider
    -> capability / availability description
    -> optional raw measurements
    -> explicit unavailable reason
```

The Phase 2 harness should be able to run even when a hardware-specific provider is absent.

Hardware/backend-specific implementations may be supplied by the member running the experiment on that machine, or by Member 1 when integration with the pinned runtime is required.

Member 5 must not:

- hard-code one developer's GPU device path or profiler;
- make a specific GPU vendor mandatory for generic workload/replay tests;
- fabricate unavailable hardware counters;
- block the whole experiment harness because optional device-level telemetry is unavailable.

Generic experiment infrastructure should therefore depend on an interface/capability contract, not on one concrete GPU collector.

## 19. Raw facts to expose

Member 5 should expose the following categories as far as the current backend and approved interfaces make them available.

The list is deliberately broader than the first Phase 2A analysis so later experiments do not require repeated instrumentation work.

### 9.1 Program / request lifecycle

Expose raw lifecycle facts such as:

- program/session ID;
- request ID;
- program first-request arrival observation;
- request arrival;
- request admission;
- request preemption if applicable;
- request completion;
- turn index where known;
- terminal vs. non-terminal state;
- follow-up waiting/cancel/admit transitions.

### 9.2 Tool / inter-turn lifecycle

Expose:

- tool-gap start;
- tool-gap end;
- tool type;
- follow-up arrival;
- observed server inter-request gap inputs where already available.

Do not derive a future return probability in the infrastructure layer.

### 9.3 Prefix / KV mapping

Expose where observable:

- prefix identity;
- observed prefix token/context length;
- block IDs associated with the reusable prefix;
- block count;
- cache group where relevant;
- native free-queue position/rank when already exposed;
- block hash presence / cacheability facts already available through the adapter.

Do not invent logical prefix ownership for blocks that cannot be attributed safely.

### 9.4 Retention / Continuum state

Expose raw baseline state/decisions already available through approved contracts:

- TTL decision timestamp;
- TTL seconds / deadline;
- next tool type used by the TTL input;
- PrefillReload input/value and provenance;
- eta input/value and provenance;
- queue-delay input/value;
- protected state;
- waiting-followup state;
- ordinary expiry transition;
- pressure-release transition.

These are baseline facts, not Member 5 analysis features.

### 9.5 Forced-release decision

Consume the existing `ForcedReleaseDecisionSnapshot` boundary and persist enough information to reconstruct the event:

- decision timestamp;
- required blocks;
- complete protected candidate set visible to the decision;
- candidate entry key;
- protected block IDs;
- immediately reclaimable block IDs;
- retention deadline;
- waiting-followup state;
- next tool type;
- elapsed time since TTL decision;
- PrefillReload;
- eta;
- queue-delay input;
- actual P1B pressure-release effects.

Member 5 must not compute an oracle or alternative victim ranking here.

### 9.6 Native cache / eviction facts

Expose where observable:

- native cached-block eviction callback/event;
- physical block ID evicted;
- native cleanup completion/evidence;
- cache hit/miss or prefix-cache reuse facts if the backend exposes them reliably;
- recomputation/prefill token work if directly observable.

If a quantity is only inferable rather than directly observed, persist the underlying raw facts and leave the inference to Member 6.

### 9.7 Scheduler / queue facts

Expose where approved and available:

- waiting set / admission event;
- native/request priority when already exposed;
- preemption event;
- queue timestamps;
- scheduling order observations already available through the Phase 1B scheduler boundary.

Do not implement a new scheduler profiler by reading private structures unless Member 1 approves the interface.

### 9.8 Serving timing facts

Prefer raw timing landmarks:

- request arrival;
- admission/start;
- first-token timestamp if observable;
- completion timestamp;
- generated token count if available.

Member 6 may derive:

- queue delay;
- TTFT;
- TPOT;
- end-to-end latency;
- throughput summaries.

### 9.9 Availability / provenance

For observation categories that are backend-dependent, expose availability explicitly.

For example:

```text
metric/fact: apc_hit
availability: unavailable
reason: backend does not expose a stable callback
```

Do not replace unavailable native evidence with an undocumented approximation.

## 10. Artifact layout

The framework should keep raw execution evidence separate from later analysis outputs.

A recommended run layout is:

```text
artifacts/phase2/<run_id>/
    run.json
    trace.json
    events.jsonl
    stdout.log / stderr.log   # optional
    backend/                  # optional native evidence
```

Member 6 may create separate processed/analysis artifacts from these raw files.

Member 5 should not define Member 6's final dataset/table layout.

## 11. Cache-pressure support

The framework must support configurable, bounded cache pressure because Phase 2A forced release is the first use case.

Requirements:

- cache budget / block override is explicit configuration;
- pressure request construction is deterministic;
- pressure loops have a safety ceiling;
- OOM is not the intended mechanism;
- pressure requests can be generated without accidentally reusing the target prefixes;
- the runner can report whether a forced-release observation occurred.

This is infrastructure capability, not a requirement for Member 5 to define the final scientific pressure matrix.

## 12. Smoke workloads

Member 5 should provide small infrastructure-validation traces, not the formal experimental matrix.

Smoke traces only need to prove that the framework can express and observe:

1. a simple request lifecycle;
2. a multi-turn program with tool gap/follow-up;
3. reusable prefix/KV observation;
4. controlled cache pressure;
5. at least one forced-release event;
6. subsequent request execution after pressure.

These smoke traces are not formal research scenarios and must not be used as the final experiment protocol by default.

## 13. Policy neutrality and fairness

The experimental substrate must remain policy-agnostic.

The workload generator and raw recorder must not change behavior based on which eviction/forced-release policy is active.

For a replay comparison, the framework must make it possible to hold fixed:

- trace/workload;
- seed;
- model/tokenizer revision;
- cache budget;
- generation/batching configuration;
- pressure input;
- runtime configuration.

Policy identity must be recorded in provenance, but must not alter the workload definition unless the experiment configuration explicitly says so.

## 14. Interaction with the current Phase 2 profiling interface

The current branch already provides:

```text
ForcedReleaseObserver
ForcedReleaseDecisionSnapshot
RetentionRuntimeIntegration(..., forced_release_observer=...)
```

Member 5 should wire approved observations into the general raw artifact path.

Member 5 should not:

- change `ForcedReleaseDecisionSnapshot` semantics;
- add future outcome fields to a decision-time snapshot;
- change `RetentionAwareSelectionCoordinator` ordering;
- modify Phase 1A physical block-selection semantics.

If more raw runtime facts are required, raise the missing boundary to Member 1.

## 15. Testing requirements

Infrastructure tests should cover at least:

### Determinism

- same trace/config/seed -> same logical workload inputs;
- stable serialization of trace/run metadata.

### Identity continuity

- program/request identities remain joinable across lifecycle events;
- prefix/block observations retain their source identities.

### Event integrity

- event indices are monotonic;
- timestamps identify a clock domain;
- malformed events fail loudly;
- unavailable facts are not fabricated.

### Observer neutrality

- enabling raw observation does not change baseline selection or runtime policy decisions.

### Bounded execution

- pressure loops terminate at evidence or safety ceiling;
- failed runs preserve partial raw artifacts and failure reason.

## 16. First delivery

The first Member 5 PR should focus on the reusable substrate.

It should contain:

1. Phase 2 benchmark runner skeleton;
2. trace/workload configuration model;
3. deterministic replay support;
4. run/provenance manifest;
5. raw event/artifact writer;
6. wiring for existing lifecycle / forced-release observations that are already available;
7. configurable bounded pressure support;
8. infrastructure smoke traces;
9. unit tests for determinism, identity, artifact integrity, and observer neutrality;
10. one small smoke artifact demonstrating the end-to-end plumbing.

It does **not** need:

- the final Phase 2A scenario matrix;
- bulk experiment collection;
- oracle/regret code;
- analysis DataFrames;
- statistical tests;
- formal plots;
- Cost-Aware algorithm code;
- paper-quality performance results.

## 17. Definition of done

Member 5's Phase 2 substrate is ready for Member 6 when:

- [ ] Phase 2 experiments have one reusable runner/config path;
- [ ] deterministic workload/trace replay works;
- [ ] multi-program and multi-turn Agent traces are expressible;
- [ ] cache pressure can be configured and bounded;
- [ ] run provenance is persisted automatically;
- [ ] raw events are persisted in a stable machine-readable form;
- [ ] program/request/tool/prefix/KV/retention/pressure facts are exposed where currently observable;
- [ ] forced-release candidate/selection observations are persisted through the approved observer;
- [ ] serving/runtime timestamps are exposed rather than prematurely summarized;
- [ ] unavailable native facts are explicitly marked rather than guessed;
- [ ] enabling observability does not change baseline behavior;
- [ ] Member 6 can consume raw artifacts without modifying the runtime to obtain ordinary Phase 2 measurements.

## 18. Escalation to Member 1

Stop and request an interface decision rather than working around the architecture if:

- a needed raw fact requires private vLLM state inspection;
- instrumentation would change scheduler/cache behavior;
- program/request/prefix identities cannot be joined reliably;
- clocks cannot be related or identified safely;
- native cache hit/miss or recomputation evidence is ambiguous;
- current approved observers omit a fact that is necessary for later analysis;
- a proposed instrumentation change would alter the frozen Phase 1A/Phase 1B semantics.
