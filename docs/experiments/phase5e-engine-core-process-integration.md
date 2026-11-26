# Phase 5 EngineCore-Process Production Integration

**Status:** CPU/interface implementation complete; Native Runtime Conformance not run

**Pinned runtime:** vLLM 0.27.1, standard `AsyncLLM` / `AsyncMPClient`

## Source audit and selected path

The failed P5E-A-01 attempt established that the standard asynchronous runtime
does not expose an in-process EngineCore to the frontend. The pinned source
audit found three supported seams:

1. `EngineCore.__init__` loads `vllm.general_plugins` inside the EngineCore
   process before constructing its Scheduler;
2. `SchedulerConfig.scheduler_cls` supports a custom class, although this
   implementation does not need to replace the scheduler;
3. `AsyncMPClient.call_utility_async()` routes a serializable Utility request
   to a named method on the actual EngineCore and returns a serializable result.

The implementation therefore uses a general plugin plus Utility RPC. The
alternative in-process async client was rejected: pinned vLLM explicitly does
not support asyncio EngineCore operation without multiprocessing. No custom
async engine client is introduced.

## Responsibilities and call chain

Frontend responsibilities remain:

- frozen replay, arrival and request submission;
- logical/external identity and output collection;
- lifecycle proxy observations;
- experiment control, archive construction and shutdown.

EngineCore-process responsibilities are:

- binding the real internal Request identity when `EngineCore.add_request`
  receives the request;
- terminal BlockTable/Native hash observation before `_free_request`;
- Retention/TTL state and Controller-Armed Timer registration;
- DVA-ER provider reads from the owned Scheduler/KVCacheManager/BlockPool;
- G9 generation, Pressure decision, SelectionPlan and Physical Outcome;
- append-only Native event indices and detached evidence export.

The production call chain is:

```text
AsyncLLM frontend
  -> AsyncMPClient Utility RPC
  -> EngineCoreProc input queue
  -> kvopt_phase5_* EngineCore method
  -> same EngineCore Scheduler / KVCacheManager / BlockPool
  -> serialized result and immutable evidence prefix
  -> frontend archive
```

The frontend never reads or mirrors a Native BlockPool. It also never performs
the unsafe read/compute/write RPC sequence. One Pressure Utility call performs
current-state validation, policy selection, Native allocation, physical outcome
observation and evidence export in the EngineCore execution context.

## Pressure safety and time semantics

Utility calls are dispatched by the EngineCore input loop. The Pressure call is
therefore serialized with request admission and EngineCore steps rather than
running from an external frontend thread. Before allocation it verifies:

- the frozen Boundary and frontend inflight identity set;
- the current per-request allocation watermark;
- the current free-block watermark;
- ownership of `scheduler.kv_cache_manager.block_pool` by the called EngineCore;
- current Retention, TTL, prefix, refcount, protection and owner evidence.

Native EngineCore event indices establish ordering. Frontend and EngineCore
timestamps retain separate clock domains and are not subtracted. Controller
timers are accepted only through an observed controller-event RPC; the
EngineCore assigns the source event index on receipt. Future trace rows are not
preloaded.

## Cross-process evidence contract

Only JSON/msgpack-compatible commands and detached evidence cross the boundary.
The returned installation report must state:

```text
execution_process = ENGINE_CORE
control_transport = ASYNCMPLCLIENT_UTILITY_RPC
native_objects_cross_process = false
```

The evidence stream must have contiguous, unique EngineCore-assigned indices.
Installation, G9, Pressure and final evidence export all fail closed on missing
methods, identities, state, ordering or malformed serialized results. Failure
archives retain whatever EngineCore evidence can still be exported before
shutdown.

## Six-system impact

The EngineCore bridge is shared infrastructure, not a P5E-only shadow backend.
Formal adapter registration now requires
`native_execution_architecture=ENGINE_CORE_PLUGIN_UTILITY_RPC_V1`. Every system
must use a fresh EngineCore but the same transport and evidence foundation, so
cross-process overhead is not selectively attributed to one algorithm. The
current six-system runner remains CPU/Mock orchestration until Native
Conformance establishes this runtime architecture.

## Evidence boundary

CPU tests cover Utility routing, child-process identity binding, serialized
Pressure evidence, malformed installation claims, non-frozen request identity,
event-index continuity and formal-adapter architecture enforcement. They do not
establish that the plugin loads in the real GPU process or that Native object
shapes and events satisfy the contract:

```text
NATIVE_RUNTIME_CONFORMANCE = NOT_RUN
GPU_EXECUTION_AUTHORIZED = false
```

The earlier failed run, consumed authorization and source-audit evidence remain
immutable. A new clean HEAD and regenerated Freeze Package are required before
requesting a new Native Conformance authorization.
