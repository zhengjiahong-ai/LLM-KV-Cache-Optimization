# Continuum → vLLM 0.27.1 architecture mapping

## Scope and evidence

This document is a feasibility spike for freezing the minimum Phase 1B
implementation scope. It is not a Continuum implementation, a benchmark, or a
new eviction policy. Continuum's TTL/retention mechanism is mapped to the
validated vLLM 0.27.1 GPU APC runtime; the existing block-level
`EvictionPolicyAdapter` remains unchanged.

The vLLM facts below were inspected from the `vllm/vllm-openai:v0.27.1`
image (Python 3.12, vLLM 0.27.1). Paths are relative to
`/usr/local/lib/python3.12/dist-packages` inside that image.

## 1. vLLM request lifecycle

### Arrival and admission

| Stage | vLLM location | State/data that matters |
| --- | --- | --- |
| API/engine request arrival | `vllm/v1/engine/llm_engine.py`: `LLMEngine.add_request()` | Creates/processes a `Request`, assigns its request ID, registers output state, then calls `EngineCore.add_request()`. |
| Engine-core admission | `vllm/v1/engine/core.py`: `EngineCore.add_request()` | Validates the string `request.request_id` and delegates to `scheduler.add_request()`. |
| Waiting admission | `vllm/v1/core/sched/scheduler.py`: `Scheduler.add_request()`, `_enqueue_waiting_request()` | Stores the object in `self.requests: dict[str, Request]`; puts it in `waiting` or `skipped_waiting`. `request.resumable` creates a streaming queue. |
| Queue representation | `vllm/v1/core/sched/request_queue.py` | FCFS uses `FCFSRequestQueue(deque[Request])`; priority uses `PriorityRequestQueue(heapq)`. |
| Scheduling step | `vllm/v1/engine/core.py`: `EngineCore.step()` | Calls `Scheduler.schedule()`, executes the model, then calls `Scheduler.update_from_output()`. |

`Request` (`vllm/v1/request.py`) has the following native identity and timing
fields: `request_id`, `client_index`, `arrival_time`, `priority`, `status`,
`trace_headers`, `cache_salt`, and `resumable`. It also retains
`prompt_token_ids`, `_all_token_ids`, `_output_token_ids`, `num_tokens`,
`num_computed_tokens`, `num_in_flight_tokens`, `num_preemptions`, and
`block_hashes`. There is no native `session_id`, `program_id`, tool ID, or
tool-gap timestamp in `Request`.

### Running, waiting, and admission order

`Scheduler` (`vllm/v1/core/sched/scheduler.py`) owns:

```text
self.requests: dict[str, Request]
self.waiting: RequestQueue
self.skipped_waiting: RequestQueue
self.running: list[Request]
self.finished_req_ids: set[str]
self.reset_preempted_req_ids: set[str]
```

`Scheduler.schedule()` first scans `self.running`, then scans waiting queues
while `token_budget > 0`. For each waiting request with
`num_computed_tokens == 0`, it calls
`KVCacheManager.get_computed_blocks(request)` before allocation. The selected
request is admitted only after `KVCacheManager.allocate_slots()` returns a
non-`None` result; it is then popped from its waiting queue and appended to
`self.running`.

The waiting-queue selection helper is
`Scheduler._select_waiting_queue_for_scheduling()`. In FCFS mode it chooses
`skipped_waiting` before `waiting`; in priority mode it compares the two queue
heads. `Request.__lt__()` orders priority requests by `(priority,
arrival_time, request_id, object identity)`, with smaller values first.

### Prefix hit and block allocation

`KVCacheManager.get_computed_blocks(request)` calls the coordinator's
`find_longest_cache_hit(request.block_hashes, max_cache_hit_length)` and returns
`(KVCacheBlocks, num_new_computed_tokens, shared_prefix_boundary)`. The lookup
is by the request's content-derived hash chain, not by a previous logical
request/session. `KVCacheManager.allocate_slots()` computes the number of
blocks needed, calls the coordinator to allocate them, then calls
`coordinator.cache_blocks(request, num_tokens_to_cache)` for finalized tokens.

The allocation path for GPU APC is:

```text
KVCacheManager.allocate_slots()
  -> KV cache coordinator / BlockPool.get_new_blocks()
  -> FreeKVCacheBlockQueue.popleft_n()
  -> BlockPool._maybe_evict_cached_block()
```

`BlockPool` (`vllm/v1/core/block_pool.py`) owns `blocks`,
`free_block_queue`, `cached_block_hash_to_block`, and
`cached_block_hashes_by_block`. `KVCacheBlock` (`vllm/v1/core/kv_cache_utils.py`)
contains `block_id`, `ref_cnt`, `_block_hash`,
`_block_hash_num_tokens`, doubly-linked free-list pointers, and `is_null`.

The queue (`FreeKVCacheBlockQueue`) is a doubly-linked list. Its documented
order is LRU at the front; `popleft_n()` removes the first N blocks, while
`remove()` removes an arbitrary linked block in O(1). `BlockPool.free_blocks()`
decrements references and appends hashed blocks in eviction order. On the next
allocation, `_maybe_evict_cached_block()` removes all hash metadata from a
selected cached block via `_remove_cached_block_hashes()`.

### Output, completion, and reuse

`Scheduler.update_from_output()` processes model output and
`_update_request_with_output()` appends output token IDs. When a stop condition
is reached, `_handle_stopped_request()` either moves a resumable request to
`WAITING_FOR_STREAMING_REQ` or reports it finished. Finished requests go
through `_free_request()` → `_free_request_blocks()` → `KVCacheManager.free()`;
normal completion then deletes the request from `Scheduler.requests`.

`KVCacheManager.free()` delegates to the coordinator, which returns the
request's blocks to `BlockPool.free_blocks()` while retaining full-block hash
metadata for APC. A later request with the same token prefix can therefore hit
the hash cache, but the hit result contains blocks and token counts, not the
logical request/session that originally populated them.

### Preemption and resume

When `allocate_slots()` returns `None` during the running-request pass,
`Scheduler.schedule()` preempts either the last running request (FCFS) or the
maximum `(priority, arrival_time)` request (priority mode). It calls
`_preempt_request()`, which frees the request's blocks, sets
`RequestStatus.PREEMPTED`, resets `num_computed_tokens` to zero, increments
`num_preemptions`, and prepends the same `Request` object to `waiting`.

On a later scheduling step, the preempted request follows the normal waiting
path and performs a new prefix-cache lookup. Thus preemption preserves the
request object and ID, but ordinary completed API requests do not automatically
become resumable sessions.

## 2. Scheduler decision point and adapter feasibility

There are two native choices, not one universal sort:

1. `Scheduler._select_waiting_queue_for_scheduling()` chooses which waiting
   queue to inspect, and the body of `Scheduler.schedule()` repeatedly peeks
   and pops that queue while admitting requests.
2. When KV capacity is insufficient, the same `schedule()` method chooses a
   running request to preempt using FCFS tail order or the priority key.

The smallest safe adapter boundary is therefore:

```text
read-only scheduler snapshot
  -> SchedulingCandidate records
  -> SchedulingPolicyAdapter.order()/select()
  -> native queue pop, running-list updates, allocation, and bookkeeping
```

The adapter should return an ordered list (or a priority map) of request IDs;
it should not mutate `Request`, queue, status, KV blocks, or scheduler sets.
The native scheduler remains responsible for popping, appending, preempting,
token-budget accounting, and all downstream output bookkeeping. A shadow mode
can compare adapter order with native order before enabling controlled ordering.

A useful immutable `SchedulingCandidate` needs at least:

```text
request_id                 # native stable ID
session_id / program_id    # external observer input; absent natively
status                     # RequestStatus
arrival_time, priority
waiting_age                # now - arrival_time or queue-observed age
num_tokens, num_computed_tokens, num_output_tokens
num_in_flight_tokens, num_preemptions
cached_tokens / cached_blocks  # KVCacheManager.estimate_cached_tokens()
recompute_cost_estimate     # project-side estimate, not native vLLM state
retention_deadline / protected
```

The adapter should not directly rewrite `Scheduler.waiting` or
`Scheduler.running`. For a first implementation, a wrapper may produce an
ordered ID list and let a very small scheduler hook perform the corresponding
native queue operations. This keeps native scheduling as the baseline and makes
the policy boundary testable.

## 3. Retention, pin/unpin, and TTL feasibility

### What vLLM already preserves

Free cached blocks remain in `FreeKVCacheBlockQueue` with `ref_cnt == 0` and
their hash metadata intact. `BlockPool._maybe_evict_cached_block()` is only
called when a free block is selected for a new allocation. This means APC
metadata can remain reusable after request completion without changing native
cache correctness.

### Minimum protection design

The least disruptive design is **soft protection in an independent runtime
table while leaving protected blocks in the native free queue**:

```text
free queue (unchanged linked-list ownership and ref_cnt)
        + protected block/prefix ID set consulted by the policy boundary
```

Keeping a protected block out of the queue would make
`get_num_free_blocks()` and allocation accounting lie unless a second pool were
implemented. A separate protected queue would duplicate BlockPool semantics.
Leaving the block in the queue but filtering it from the policy candidate set
preserves the native metadata and reference-count rules. The existing
Phase 1A bridge is the natural extension point: retention eligibility is a
filter before `EvictionPolicyAdapter` sees candidates.

Protection must remain soft, not a hard promise. Before allocation, the
retention layer should:

1. expire entries whose deadline is past;
2. if unprotected candidates are insufficient, release the least valuable
   protected entries deterministically until the requested allocation fits;
3. delegate the resulting candidate order to the existing block eviction path.

The release operation changes only the runtime protection table. It must not
edit `ref_cnt`, block hashes, or queue links except for the normal selected
block operation already owned by the eviction bridge/native path. This ensures
allocation cannot deadlock because of protection.

TTL expiry can be checked lazily at the scheduler step and again immediately
before a pressure allocation. A background timer is unnecessary for correctness
and would introduce a new synchronization path. The expiry timestamp should be
monotonic-clock based and the check must be deterministic for a supplied
`now` in tests.

### Metadata ownership

Retention metadata belongs in an independent runtime table keyed by an
application-provided `session_id`/`program_id` and a content-derived
`prefix_id`. It should contain tool-call history, TTL/deadline, protection
state, and the currently observed block IDs. It should not be stored only on a
`Request` (the object is deleted after completion), nor only on a block (a
hashed prefix can be reused by multiple requests). A many-to-many association
is safest:

```text
session/program -> prefix IDs -> block IDs
block ID -> prefix IDs (reverse index for eviction cleanup)
```

Block IDs are ephemeral and must be removed from the table when
`_maybe_evict_cached_block()` clears their hash metadata. Prefix IDs should be
content/hash identities, never an assumed request identity.

## 4. Request/session ↔ KV block mapping

### Native information

While a request is alive, `KVCacheManager`/its coordinator stores the request's
`KVCacheBlocks`. `KVCacheManager.get_blocks(request_id)`,
`get_block_ids(request_id)`, and `get_block_ids_for_computed_tokens()` expose
the current block IDs. `Scheduler` also places block IDs into
`NewRequestData.block_ids` and `CachedRequestData.new_block_ids` in
`vllm/v1/core/sched/output.py`.

The scheduler can estimate cached amount with
`KVCacheManager.estimate_cached_tokens(request)`, which reads each active
block's `block_hash_num_tokens`.

### Information lost after completion

`Scheduler._free_request()` ultimately calls `KVCacheManager.free()` and
`_free_blocks()` deletes `Scheduler.requests[request.request_id]`. The free
block remains in the APC hash map, but the block metadata has no request ID or
session ID. `BlockPool.cache_full_blocks(request, ...)` uses the Request to
derive content hashes; it does not store that logical owner in the hash map.

### Prefix hit association

`KVCacheManager.get_computed_blocks()` and the coordinator's
`find_longest_cache_hit()` can recover the matching block objects and hit
length for a new request. They cannot recover which previous request or session
populated those blocks. The hash chain identifies token content (plus cache
group), not application workflow identity.

### Minimum observation needed

An observation layer should record, before completion frees the request:

```text
request_id, external session/program ID, prefix/hash ID,
current block IDs, block-hash token length, admission/hit time,
tool-gap start/end and completion/preemption events
```

The safe hook is adjacent to scheduler allocation/completion and
`KVCacheManager.get_blocks()`/`free()`, or an engine-level observer receiving
immutable snapshots. It must tolerate block reuse and eviction and must never
make correctness depend on the table. If native request metadata is unavailable
at a later hit, the association is explicitly an observation-derived
best-effort mapping, not a vLLM guarantee.

## 5. Continuum mechanism mapping

The project notes describe Continuum as tool-aware TTL plus program-level
scheduling: `CalcTTL` uses historical tool duration and runtime impact; a
program's KV remains pinned through a tool gap; expiry unpins it; pressure may
selectively unpin to avoid deadlock. The table below maps those mechanisms
without silently substituting a fixed TTL or SAGA/WA-LRU behavior.

| Continuum mechanism | Needed state | vLLM hook | Mapping quality | Required change |
| --- | --- | --- | --- | --- |
| Reuse/tool-gap history | session/program ID, tool type, gap start/end, reuse outcome | `Request` lifecycle observer around `Scheduler.update_from_output()`, `_handle_stopped_request()`, `finish_requests()`; tool events must come from the orchestrator | `ADAPTABLE` | External lifecycle/event input and an online history table |
| Dynamic TTL / `CalcTTL` | per-tool history, program round, cache occupancy, recompute/queue estimates | scheduler-step clock plus retention manager; `KVCacheManager.usage` and request snapshots provide partial signals | `APPROXIMATION` | Implement the paper-defined estimator only after scope freeze; explicitly document unavailable estimates |
| Pin/unpin | protected prefix/session state and block membership | retention filter before the existing `EvictionPolicyAdapter`/`BlockPool` selection | `ADAPTABLE` | Independent protection table and queue-candidate filtering; no hard pin in native BlockPool |
| Expiration | monotonic deadline and expiry transition | start of `Scheduler.schedule()` and pressure-time reconciliation | `ADAPTABLE` | Lazy expiry pass plus deterministic tests |
| Memory-pressure handling | free-block requirement, protected candidates, release order | `KVCacheManager.allocate_slots()` returning `None`, then BlockPool allocation pressure | `ADAPTABLE` | Release enough soft protection to make allocation possible; never deadlock or hide free blocks |
| Scheduling priority / program-level FCFS | session/program identity, pin state, arrival/round order | `_select_waiting_queue_for_scheduling()` and the running preemption branch inside `Scheduler.schedule()` | `APPROXIMATION` | A scheduler adapter and external program ordering; native vLLM has request FCFS/priority, not program-level FCFS |
| Resumed request/session identification | stable session ID across tool gaps and new requests | `resumable` streaming keeps one `Request`; ordinary API re-entry goes through a new `Request` | `APPROXIMATION` | Require an external session/program ID or trace header; correlate new requests explicitly |
| Request/session → cached blocks | active `KVCacheBlocks`, persistent prefix/block observation | `KVCacheManager.get_blocks()`, `cache_blocks()`, `free()`, BlockPool eviction | `APPROXIMATION` | Many-to-many observation table; native hash cache alone cannot restore logical ownership |

`DIRECT` is intentionally absent for the session-level Continuum mechanisms:
vLLM exposes the necessary block/request primitives, but not Continuum's
program identity or tool timing. The block-level APC eviction path itself is
already directly validated by Phase 1A and is not being reimplemented here.

## 6. Proposed minimum architecture

```text
orchestrator/session events + vLLM request lifecycle
                    |
                    v
        Request/Session Observation Layer
                    |
                    v
        Retention State Manager
        (history, dynamic deadline, soft protection,
         prefix↔block observation, expiry/release)
             |                         |
             | retention eligibility  | immutable scheduling snapshot
             v                         v
  existing EvictionPolicyAdapter   SchedulingPolicyAdapter
             |                         |
             +-----------+-------------+
                         v
                 native vLLM Scheduler
                         |
                 KVCacheManager/coordinator
                         |
                   BlockPool + free queue
```

The retention manager should connect to eviction by supplying an eligibility
view (protected/expired/released) to the existing bridge. It should not call
`_maybe_evict_cached_block()` itself. The scheduler need not know individual
block IDs for the first scope; it needs only aggregate cached-token/block
signals and the retention/session fields. Conversely, block eviction needs the
retention eligibility of a block/prefix but not the complete scheduler policy.

To avoid cycles, define narrow immutable protocols in project code:

```text
SchedulerPolicyAdapter -> SchedulingCandidate snapshot
RetentionStateManager  -> RetentionView(prefix/block eligibility)
EvictionPolicyAdapter  -> EvictionCandidate snapshot
```

The vLLM integration layer constructs snapshots and performs native downstream
bookkeeping. Policy modules depend on protocols, not on vLLM Scheduler or
BlockPool classes.

## 7. Required code changes (after scope freeze)

The smallest implementation would be:

1. Add project-side `RetentionStateManager` and immutable retention records;
2. add an observation hook for external session/tool events and active
   request-to-block snapshots;
3. extend the existing vLLM bridge with a retention eligibility filter before
   `EvictionPolicyAdapter.select_victims()`;
4. add a scheduler snapshot/adapter boundary at the waiting-queue choice and,
   only if required by the frozen baseline, the preemption choice;
5. preserve native queue removal, ref-count changes, hash cleanup, and output
   bookkeeping downstream;
6. add deterministic unit tests with synthetic requests/blocks, then a small
   real-GPU smoke test. No CUDA, model, or vLLM source fork is required for the
   feasibility design itself.

Phase 1A files and interfaces are extension points, not rewrite targets:
`src/kvopt/runtime/vllm/types.py`, `adapter.py`, `bridge.py`, and
`observer.py`, including `EvictionPolicyAdapter`, `VLLMEvictionBridge`, and
`NativeLRUAdapter`, remain the validated block-level foundation.

## 8. Risks and blockers

- **No native session/program identity.** A faithful resumed-session mapping
  requires an orchestrator-provided ID (for example a trace header); request ID
  reuse cannot be assumed.
- **No native pin API.** Protection must be soft and policy-side. A hard pin
  implemented by removing blocks from the free queue would break free-block
  accounting or require a second BlockPool.
- **Block sharing is many-to-many.** One content prefix can be reused by many
  requests, and one request can contain many blocks. A request-only owner field
  is incorrect.
- **Dynamic TTL inputs are incomplete.** Tool timing and program rounds are
  outside vLLM; recompute/queue impact estimates also need project-defined
  measurement. Calling a fixed timeout “Continuum” would be invalid.
- **Scheduler coupling.** Continuum's program-level FCFS is not the same as
  vLLM's request-level FCFS/priority queue. Any scheduler adaptation must be
  measured and documented as an approximation.
- **Pressure safety.** Protected state must never make `allocate_slots()` fail
  indefinitely. Release-before-allocation and a deterministic fallback are
  mandatory.
- **Async/deferred frees.** With KV connectors or overlapping batches,
  `_free_request_blocks()` may defer return of blocks. Observation code must
  honor these fences and not infer immediate reuse from completion alone.

## 9. Recommended minimum Phase 1B scope

Before writing implementation code, Member 1 should freeze the following
minimum that still represents Continuum's defining behavior:

1. require an explicit external `program_id/session_id` and tool-gap events;
2. implement online tool-duration history and the paper-defined dynamic TTL
   estimator, with unavailable runtime terms recorded as documented
   approximations;
3. retain completed/idle prefixes using soft protection in an independent
   table, with lazy expiry;
4. on pressure, release expired/protected entries deterministically until the
   native allocation can proceed;
5. include a narrow scheduler adapter only if program-level FCFS is frozen as
   part of the baseline; otherwise label the result retention-only rather than
   full-system Continuum;
6. keep the existing Phase 1A eviction adapter and native BlockPool cleanup
   path as the common backend;
7. validate request/session↔prefix/block observation separately from policy
   correctness, and report it as approximate where native association is lost.

This scope is explicitly not Continuum baseline code, Cost-Aware code, SAGA
WA-LRU, a fixed-TTL substitute, or a formal performance benchmark.

## 10. Questions Member 1 must freeze

1. Is program-level scheduling part of the Baseline 2 reproduction, or is the
   first implementation retention-only with an explicit limitation?
2. What external event/API supplies `session_id`, program round, tool type, and
   tool-gap start/end?
3. Which exact paper inputs are available for `CalcTTL`, and which are marked
   approximation rather than silently imputed?
4. What deterministic protected-entry release order is used when pressure
   exceeds all unprotected capacity?
5. Is retention keyed by session, content prefix, or both, and what is the
   lifetime/cleanup rule for the many-to-many block index?
6. What scheduler adapter contract is frozen: priority map, ordered request
   IDs, or selected IDs for one step?
7. How are async/deferred frees and connector-backed requests excluded or
   represented in the first scope?
8. What evidence is required to claim “Continuum-style” rather than
   “retention-inspired” adaptation?

## Inspected vLLM 0.27.1 source index

- `vllm/v1/request.py`: `Request`, `RequestStatus`, `Request.__lt__()`,
  `update_block_hashes()`, token and status fields.
- `vllm/v1/engine/llm_engine.py`: `LLMEngine.add_request()`, `step()`.
- `vllm/v1/engine/core.py`: `EngineCore.add_request()`, `step()`,
  `_process_engine_step()`.
- `vllm/v1/core/sched/request_queue.py`: `SchedulingPolicy`,
  `RequestQueue`, `FCFSRequestQueue`, `PriorityRequestQueue`.
- `vllm/v1/core/sched/scheduler.py`: `Scheduler.__init__()`, `schedule()`,
  `_select_waiting_queue_for_scheduling()`, `_preempt_request()`,
  `update_from_output()`, `_handle_stopped_request()`, `finish_requests()`,
  `_free_request()`, `_free_request_blocks()`.
- `vllm/v1/core/sched/output.py`: `NewRequestData`, `CachedRequestData`,
  `SchedulerOutput` block/request fields.
- `vllm/v1/core/kv_cache_manager.py`: `KVCacheBlocks`,
  `KVCacheManager.get_computed_blocks()`, `allocate_slots()`, `free()`,
  `get_blocks()`, `get_block_ids()`, `estimate_cached_tokens()`,
  `cache_blocks()`.
- `vllm/v1/core/block_pool.py`: `BlockPool`, `get_cached_block()`,
  `cache_full_blocks()`, `get_new_blocks()`,
  `_maybe_evict_cached_block()`, `touch()`, `free_blocks()`.
- `vllm/v1/core/kv_cache_utils.py`: `KVCacheBlock`,
  `FreeKVCacheBlockQueue.popleft_n()`, `remove()`, `append_n()`,
  `prepend_n()`.

