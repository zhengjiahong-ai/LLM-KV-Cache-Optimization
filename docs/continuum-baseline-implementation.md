# Continuum Baseline Implementation Record

## 1. Purpose and authority

This document records the implementation status and engineering choices of the
Continuum-style Phase 1B baseline adapted to vLLM 0.27.1.

Current status:

```text
Phase 1B core contracts implemented; Continuum runtime integration pending.
```

This is a living implementation record. It does not replace the frozen
specifications and does not claim an exact source-level reproduction of
Continuum.

Implementation authority, in descending order, is:

```text
1. docs/baseline-freeze.md
2. docs/phase1b-continuum-implementation-decisions.md
3. docs/experiment-plan.md
4. docs/architecture.md
5. docs/continuum-vllm-mapping.md
```

Older Related-Work notes are research references, not implementation
specifications. Cost-Aware-only scoring features and signals are outside this
baseline package.

## 2. Phase 1A and Phase 1B status boundary

The existing Phase 1A native-LRU bridge, observer integration, and real-vLLM
GPU validation remain implemented and unchanged. In particular, Phase 1A has
already validated the native APC eviction path and the project bridge's ability
to preserve native-LRU ordering and native BlockPool cleanup.

The following statements apply only to the Phase 1B Continuum work:

```text
No Phase 1B Continuum-specific runtime integration yet.
No Continuum retention/TTL/scheduler hook yet.
No Phase 1B controlled multi-turn GPU validation yet.
No evidence of Continuum-managed retained-prefix APC reuse yet.
```

The data contracts completed so far must not be described as an active
retention system or a completed Continuum baseline.

## 3. Current implementation status

| Component | Status | Current evidence |
| --- | --- | --- |
| Identity and input provenance | Implemented contract | `src/kvopt/continuum/types.py` |
| Separate duration records | Implemented contract | `ServerInterRequestGapRecord` and `ExternalToolDurationRecord` |
| Lifecycle events | Implemented contract | `src/kvopt/continuum/events.py` |
| Injectable monotonic clocks | Implemented | `src/kvopt/continuum/clock.py` |
| Runtime configuration | Implemented contract | `src/kvopt/continuum/config.py` |
| TTL, retention, and scheduling snapshots | Implemented contract | `src/kvopt/continuum/snapshots.py` |
| Eligibility preparation and selection plans | Implemented contract | `src/kvopt/continuum/selection.py` |
| Deterministic structured logging | Implemented contract | `src/kvopt/continuum/logging.py` |
| Runtime history stores | Pending | No store implementation yet |
| Dynamic TTL computation | Pending | Input/output contracts only |
| Eta and prefill-profile providers | Pending | No provider or profile loader yet |
| Live retention state manager | Pending | Snapshot contract only |
| Prefix/block observation index | Pending production integration | PR 3 provides only session-local observation associations and eviction cleanup; no retention reverse index |
| Pressure coordinator and retention-aware adapter | Pending | Immutable plan contracts only |
| Continuum scheduler adapter | Pending | Candidate snapshot contract only |
| Phase 1B vLLM hooks | Pending | No Continuum-specific hook yet |
| Phase 1B GPU validation | Pending | No controlled multi-turn result yet |

Here, “implemented contract” means that a validated, immutable boundary exists
and has unit tests. It does not mean that the corresponding live runtime
algorithm is already active.

## 4. Core package structure

The current package contains:

```text
src/kvopt/continuum/
├── types.py
├── clock.py
├── config.py
├── events.py
├── snapshots.py
├── selection.py
├── logging.py
└── __init__.py
```

The current Python module import relationship is:

```text
types
├── clock
├── config
├── events
├── snapshots
└── selection

logging
└── types + config + events + snapshots + selection

__init__
└── public re-exports only
```

This describes module dependencies, not a runtime execution pipeline.

### Module responsibilities

- `types.py` defines identities, input provenance, and the two non-interchangeable
  duration record types.
- `events.py` defines external and observed lifecycle facts accepted by a
  future observation layer.
- `clock.py` supplies production and deterministic test clocks.
- `config.py` validates modes and fixed runtime parameters without performing
  I/O.
- `snapshots.py` defines immutable TTL, retention, prefix-association, queue
  delay, and scheduling-policy inputs.
- `selection.py` keeps native LRU rank separate from retention eligibility
  and records auditable selection plans.
- `logging.py` defines deterministic, deeply immutable structured log records
  and sink boundaries.
- `__init__.py` re-exports the public Core contract surface.

## 5. Identity contracts

The Core defines four distinct runtime-checked identities:

- `ProgramIdentity`: the explicit logical program/session identity shared by
  multiple turns;
- `RequestIdentity`: the identity of one request lifetime;
- `PrefixIdentity`: an opaque canonical identity for reusable prefix content
  within the correct native cache namespace;
- `BlockIdentity`: an ephemeral physical block identity.

The frozen invariants are:

```text
request_id is not program_id
block_id is not logical prefix identity
prefix identity must be stable across request lifetimes
prefix identity must respect every native APC isolation dimension
real eviction or reassignment must invalidate stale reverse associations
observation metadata must not affect inference correctness
```

The current `PrefixIdentity` stores an opaque canonical string. For the
evidence-approved PR 3 profile, its construction is:

```text
schema: continuum.prefix.native_hash.v1
canonical value: "continuum.prefix.native_hash.v1:" + native_hash_hex
included field: native_hash_hex only
```

`native_hash_hex` is the lowercase-hex encoding of the complete native
`KVCacheBlock.block_hash` bytes, including any encoded group material. The
adapter constructs it only for a non-null group-0 block with a positive,
block-size-16-aligned `hash_num_tokens`; that value is an admissibility guard,
not an identity field. The approved profile is vLLM 0.27.1 on MLX/Metal with
`prefix_caching_hash_algo=sha256`, one live in-process EngineCore, one cache
group, and block size 16. It accepts ordinary token-ID text input only and
excludes LoRA, multimodal, and prompt-embedding inputs. It does not claim
cross-process or restart persistence. See
`docs/continuum-vllm-observation-evidence.md` for the committed runtime
evidence and scope.

The observation adapter also removes a session-local prefix association when a
corresponding native block eviction is observed. This is not a production
retention reverse index and does not infer physical block reassignment.

Partial-prefix semantics remain OPEN. The first controlled workload must not
depend on suffix usefulness after an earlier prefix block is evicted.

## 6. Duration-history separation

The Core deliberately uses two different record types:

```text
ServerInterRequestGapRecord
ExternalToolDurationRecord
```

The primary TTL sample is:

```text
server_inter_request_gap
= next-turn server arrival - previous-turn server finish
```

External tool duration is independently supplied by the workload/orchestrator
through explicit `TOOL_GAP_STARTED` and `TOOL_GAP_ENDED` events. It is
diagnostic or ablation metadata and is not part of the primary TTL duration
distribution.

The runtime must therefore maintain separate history stores. It must never:

- synthesize `TOOL_GAP_STARTED` from `TURN_FINISHED`;
- treat a pending server gap as external tool duration;
- merge the two record types into one untyped history;
- use external tool duration as the primary Phase 1B TTL history.

The records and events exist now. Their separate store implementations remain
pending.

## 7. Lifecycle contracts

The current immutable events represent:

- program start and completion;
- request arrival, admission, and preemption;
- non-terminal or terminal turn completion;
- follow-up waiting and cancellation;
- external tool-gap start and end;
- request-to-prefix/block observation;
- real block eviction observation.

For a non-terminal completion:

```text
TURN_FINISHED(next_tool_type = f, is_terminal = false)
-> calculate TTL using history available for f
-> create the retention deadline
-> begin retention immediately
-> begin pending server_inter_request_gap observation at finish_timestamp
```

This sequence must not wait for or manufacture an external tool event. A
terminal turn instead performs program cleanup and creates no new retention
interval.

These objects currently validate facts and preserve their types. No event
dispatcher, observation runtime, or live state-transition engine is implemented
yet.

## 8. TTL inputs, provenance, and decisions

The only allowed `InputSource` values are:

```text
NATIVE
OBSERVED
EXTERNAL
APPROXIMATED
UNAVAILABLE
```

Cold-start information is represented as `APPROXIMATED` with a non-empty
reason. There is no sixth `APPROXIMATED_COLD_START` source.

The immutable audit chain is:

```text
TTLInput
-> TTLDecision
-> RetentionEntrySnapshot
```

Current contract guarantees include:

- `queue_delay_t_seconds` is the aggregated queue-delay term (T), not one
  raw queue-delay sample;
- `eta` must be finite but may be negative and is not clipped;
- tool-specific history requires a known `next_tool_type`;
- missing tool identity cannot silently select an arbitrary tool history and
  requires a logged fallback reason;
- cold-start decisions require a reason;
- `deadline_timestamp` is derived from
  `decision_timestamp + ttl_seconds`, not independently supplied;
- duration samples, queue delay, prefill reload, and TTL are finite and
  non-negative.

The formal Equation (2), empirical CDF, candidate enumeration, tie-break,
cold-start hierarchy, eta construction, and PrefillReload rules are frozen in
`docs/phase1b-continuum-implementation-decisions.md`. The current Core does
not yet implement that estimator.

## 9. Clock and configuration

`SystemMonotonicClock` wraps `time.monotonic()`.
`FakeClock` supplies deterministic time for tests and cannot move backwards.
Core timestamps must be finite, non-negative, and must reject booleans.
Consumers of any third-party `Clock` implementation must still validate the
value at their own boundary.

The configuration keeps these two parameters separate:

```text
duration_history_threshold = 100
queue_delay_window_size = 100
```

They have different meanings and must not be collapsed into a shared constant.

The default configuration is disabled and native-only. A disabled configuration
cannot request shadow or controlled retention/scheduler modes. Configuration
construction does not read an environment variable or file and does not install
a runtime hook.

`prefill_profile_path` and `prefill_profile_version` are validated
configuration fields only. The profile loader is pending.

## 10. Retention-state contract

`RetentionEntrySnapshot` is the read-only state of one logical
`(program_id, prefix_id)` retention entry. It contains:

- the complete `TTLDecision` that produced its deadline;
- whether it is currently protected;
- whether a same-program follow-up is waiting;
- the observed physical block IDs.

This snapshot is not a live retention table. The following runtime behavior is
still pending:

- program/prefix state ownership;
- prefix-to-block and block-to-prefix indexes;
- `any-protected` aggregation for shared physical blocks;
- ordinary lazy expiry;
- waiting-follow-up expiry deferral;
- terminal cleanup;
- stale-association cleanup after eviction/reassignment;
- protected-entry release under real allocation pressure.

Future observation metadata must remain advisory and must never participate in
vLLM inference correctness.

## 11. Eligibility and selection contracts

Phase 1B preserves the distinction:

```text
native_lru_rank != eligibility_tier
```

`native_lru_rank` is the block's position in the complete original native
free-queue snapshot. `eligibility_tier` is separate Phase 1B metadata:

```text
Tier 1 = ordinarily eligible
Tier 2 = made eligible by a planned protected-entry release
None   = still protected
```

The virtual adapter key is:

```text
(eligibility_tier, native_lru_rank)
```

It must never overwrite native LRU rank or be simulated by passing a reordered
iterable into `VLLMEvictionBridge.build_candidates()`.

The current contracts enforce:

- native ranks must be contiguous and match positions in the supplied
  `original_free_queue`; future runtime integration must ensure that this
  supplied snapshot is the complete original native free queue;
- an unhashed free block is always eligible in Tier 1;
- a protected cached queue head cannot block a later unhashed free block;
- pressure-release effects exactly explain Tier 2 physical blocks;
- a zero-marginal logical release may occur only while the physical target is
  still unmet;
- release planning stops once the target is satisfied;
- one indivisible logical entry may expose more blocks than the remaining
  requirement;
- selected block IDs follow the explicit virtual eligible order;
- selected block count must equal
  `min(required_blocks, supplied original-free-queue size)`;
- `SelectionPlan` stores the declared adapter identity and selected block IDs,
  and validates those IDs against the virtual order and required target;
  production of those IDs by the real Phase 1B adapter remains pending.

These are immutable planning contracts only. The
`RetentionAwareSelectionCoordinator`,
`RetentionAwareLRUAdapter`, and Phase 1B vLLM retention integration remain
pending. The Phase 1A bridge and `NativeLRUAdapter` are unchanged.

When implemented, native and shadow modes must not commit hypothetical pressure
releases. Controlled mode may commit a prepared plan only after final victim
IDs have been produced and validated through the defined bridge/adapter
boundary.

## 12. Scheduling snapshot contract

`SchedulingCandidate` supplies only the immutable state required by the
frozen first scheduler adaptation. In particular,
`is_preempted_waiting` means that the request is currently a preempted request
returned to waiting; it is not a permanent “was ever preempted” marker.

The frozen priority classes remain:

```text
1. preempted request already returned to waiting
2. follow-up of a currently protected/within-TTL program
3. all other waiting requests
```

The deterministic within-class order remains:

```text
program_arrival_timestamp
-> request_arrival_timestamp
-> request_id
```

No Phase 1B Continuum scheduling policy or hook is implemented yet. The first
Phase 1B scheduler integration is limited to waiting/admission order. Changing
running-request preemption remains outside the frozen first implementation.

## 13. Structured logging

`StructuredLogRecord` has stable top-level fields:

```text
event
timestamp
mode
program_id
request_id
prefix_id
source
reason
fields
```

The event names are frozen by this project for reproducible Phase 1B
experiments. They are not claimed to be a native event enumeration from the
Continuum paper.

The logging contract provides:

- runtime checks for non-null identities, modes, and sources;
- explicit encoding only for supported project identities and enum types;
- deeply detached and immutable nested fields;
- non-empty, non-whitespace string mapping keys;
- rejection of non-finite floats, bytes, sets, cycles, unknown objects, and
  unknown enums;
- current-recursion-path cycle detection, so a shared non-cyclic object may
  appear in more than one location;
- deterministic JSON with sorted keys and `allow_nan=False`;
- an `InMemoryEventSink` whose snapshots do not expose its mutable list;
- a `NullEventSink` that unconditionally discards any supplied value.

`RETENTION_SELECTION_PLANNED` may describe either a shadow or controlled
retention plan. A shadow record remains hypothetical and must not imply that a
live release or queue mutation occurred.

No handler is installed on import. No file-backed sink or automatic runtime
emission is implemented yet.

## 14. Project adaptations and concretizations

### 14.1 Queue-delay window

```text
queue_delay_window_size = 100
Status: PROJECT ADAPTATION
```

Continuum specifies a sliding-window queue-delay mean for requests whose
reusable GPU KV state was evicted, but does not publish this window length. This
parameter is distinct from `duration_history_threshold = 100`.

### 14.2 Startup default TTL

```text
RepresentativePrefillReload-based T_default
Status: PROJECT ADAPTATION / CONCRETIZATION
```

The paper-derived portion is the cold-start optimization under an exponential
duration model with one-second mean, `eta = 1`, and `T = 0`. Selecting one
fixed representative prefill value per frozen model/hardware/profile
configuration is the project's concretization.

Current implementation record:

```text
RepresentativePrefillReload value: PENDING
Representative context/prefix size: PENDING
Prefill profile loader: PENDING
```

No numeric value is assumed by the current Core. PR 4 must record the measured
representative value, context/prefix size, model, hardware, and profile version
before formal Phase 1B evaluation.

### 14.3 Pressure-release order

```text
earliest retention deadline
-> entry native-LRU key
-> stable (program_id, prefix_id) identity
Status: PROJECT ADAPTATION
```

The logical release unit is one `(program_id, prefix_id)` entry. Its native-LRU
key is the minimum native rank among physical cached blocks that would become
newly eligible if the entry were released at that point; a zero-marginal entry
uses positive infinity. Physical eviction remains delegated to the Phase 1A and
native BlockPool path.

This deterministic fallback must not be described as Continuum's
latest-program-arrival rule.

## 15. Native runtime safety boundary

The current Core package:

- has no vLLM import;
- does not modify `BlockPool`, the native free queue, APC hash metadata, or
  reference counts;
- does not install a scheduler, allocation, completion, or eviction hook;
- does not mutate a vLLM `Request`;
- does not read environment configuration at import;
- does not change the existing Phase 1A bridge or `NativeLRUAdapter`.

The eventual Phase 1B integration must preserve native ownership of allocation,
eviction, APC metadata cleanup, request status, and scheduler bookkeeping.

## 16. Validation checkpoints

Historical Core checkpoint:

```text
Commit: adeabf2
Continuum logging tests: 34 passed
Full test suite: 315 passed
Changed-file Ruff: passed
Python compilation: passed
```

PR 3 Commit 5 pre-commit verification:

```text
Focused observation tests: 46 passed
Full test suite: 410 passed
Changed-file Ruff: passed
AST parse: passed
In-memory compile: passed
Filesystem py_compile: not used because the existing __pycache__ is protected
```

The full-repository Ruff cleanup is not claimed here. Pre-existing import-order
findings outside this Core work are deferred under the team workflow.

## 17. Known Phase 1B limitations

At this checkpoint:

- partial-prefix semantics remain OPEN;
- LoRA, multimodal, and prompt-embedding namespaces remain outside the
  evidence-approved text-only profile;
- cross-process and restart-persistent prefix identity remain unsupported;
- runtime history stores do not exist;
- the Equation (2) estimator and its providers do not exist;
- the live retention manager and reverse indexes do not exist;
- the pressure coordinator and retention-aware adapter do not exist;
- the Phase 1B scheduler adapter does not exist;
- no Continuum-specific observation or mutation hook is installed;
- no Phase 1B controlled multi-turn workload has been validated;
- no Continuum-managed retained-prefix APC reuse has been demonstrated;
- no Phase 1B production GPU integration is claimed; PR 3 runtime evidence is
  recorded separately in `docs/continuum-vllm-observation-evidence.md`.

These limitations do not remove or supersede the completed Phase 1A integration
and validation.

## 18. Remaining PR sequence

After the Core PR is merged, work proceeds in this order:

```text
PR 3
vLLM observation spike and prefix-identity evidence

PR 4
Histories, TTL estimator/providers, and retention manager

PR 5
Pressure coordinator, retention-aware adapter,
and vLLM retention integration

PR 6
Scheduler adapter and controlled multi-turn validation

PR 7
Real GPU validation and final implementation documentation
```

Each PR should still contain small, reviewable commits. The PR 3 observation
spike comes first so that prefix identity, APC namespace, block reassignment,
and partial-prefix facts are based on real vLLM 0.27.1 behavior rather than
guessed semantics.

If the real backend cannot satisfy the frozen identity invariants without
changing the Phase 1A/native runtime boundary, M3 must report a blocker to M1.

## 19. Branch boundary

This Core branch ends after this document:

```text
complete Commit 6
-> review and push feature/baseline-continuum-core
-> create and complete PR 2
-> wait for M1 review and merge
-> synchronize the latest main
-> create the PR 3 observation branch from that main
```

History stores, the TTL estimator, the retention manager, and vLLM observation
work must not continue directly on `feature/baseline-continuum-core`.
No merge is performed by M3.
