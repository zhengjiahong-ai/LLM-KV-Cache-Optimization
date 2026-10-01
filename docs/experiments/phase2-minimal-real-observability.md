# Phase 2A Minimal Real-Runtime Observability Test

## Purpose

This test answers one narrow question:

> Can the merged Phase 2 experimental substrate drive the already-qualified
> real vLLM runtime and persist the raw evidence required to study a
> forced-release decision?

It is **not** a performance benchmark and it is **not** Phase 2A's formal
experimental protocol.

The acceptance target is the causal evidence chain:

```text
two protected reusable prefixes
        ->
controlled native KV pressure
        ->
FORCED_RELEASE_DECISION
        ->
selected logical release
        ->
native physical eviction
        ->
later follow-up of the selected program/prefix
```

No oracle, regret, future-use label, Cost-Aware score, throughput conclusion,
or latency claim is produced here.

## Why the configuration is small

The test reuses the Phase 1B qualified environment:

- vLLM 0.27.1;
- vLLM-Metal / Apple Silicon Metal;
- paged KV and APC enabled;
- Qwen/Qwen2.5-0.5B-Instruct at revision
  `7ae557604adf67be50417f59c2c2f167def9a775`;
- one process / one EngineCore;
- generation length 1.

The original Phase 1B cleanup validation used 48 configured blocks for one
protected 256-token prefix.  This test needs **two** protected candidates, so it
uses 64 configured blocks:

```text
configured native blocks              64
reserved null block                    1
usable blocks                          63

agent-a reusable prefix: 256 / 16      16 blocks
agent-b reusable prefix: 256 / 16      16 blocks
protected total                        32 blocks

ordinary eligible supply              31 blocks
one 512-token pressure prefill         32 blocks
```

Therefore:

```text
31 < 32 <= 63
```

A single pressure prefill cannot be satisfied from ordinary eligible supply
alone, but it can be satisfied after protected fallback.  This creates a real
choice between at least two protected candidates without filling the physical
device to OOM.

The pressure stage has a safety ceiling of two requests.  The expected path is
one pressure request; the second is only a bounded fallback.

## Workload

The logical trace is deliberately tiny:

```text
agent-a turn 1  -> 256-token reusable prefix A -> waiting follow-up
agent-b turn 1  -> 256-token reusable prefix B -> waiting follow-up
pressure        -> 512-token unique prefill
agent-a turn 2  -> return after the decision
agent-b turn 2  -> return after the decision
```

The deployment adapter materializes deterministic token IDs so the number of
full reusable blocks is controlled.  The text in the trace is still the
logical workload description; `BACKEND_INPUT_MATERIALIZED` records the actual
token count used by the real backend.

## Required evidence

The generated `observation-report.json` is PASS only when all of the following
are observed:

1. the normal M5 artifacts exist and `run.json` reports success;
2. at least two programs have non-empty `BLOCKS_OBSERVED` mappings;
3. the lifecycle contract exposes program/request arrival, admission, turn
   completion, follow-up waiting, tool-gap boundaries, prefix/block mapping,
   native eviction, and program completion;
4. a `FORCED_RELEASE_DECISION` contains selected releases;
5. the decision payload exposes `required_blocks`, `original_free_queue`,
   `ordinary_expired_entries`, the complete `candidates`, and
   `selected_releases`;
6. every candidate exposes the Phase 2A decision-time raw fields:
   `program_id`, `prefix_id`, retention deadline, waiting-follow-up state,
   full block IDs, initially reclaimable block IDs, next tool type, elapsed
   time since TTL decision, PrefillReload, eta, and queue-delay input;
7. its candidate set contains at least two distinct
   `(program_id, prefix_id)` identities, and each selected release is drawn
   from that set with explicit `newly_eligible_block_ids`;
8. at least one `BLOCK_EVICTED` block is one of the selected release's
   `newly_eligible_block_ids`;
9. a selected program later produces a `REQUEST_ARRIVED`;
10. a later `VLLM_PREFIX_SNAPSHOT` rejoins the same selected
    `(program_id, prefix_id)`.

This deliberately tests both logical and physical boundaries.  Merely
generating `events.jsonl` is not sufficient.

## Capability audit

The report also records useful backend capabilities without making them PASS
requirements.

Expected AVAILABLE in this first Metal adapter:

- runtime identity;
- logical program/request lifecycle;
- prefix -> native block mapping;
- forced-release candidate/selection snapshot;
- native block eviction callback;
- generated token count.

Expected UNAVAILABLE until a separate approved observation seam exists:

- per-request native APC hit/miss;
- direct recomputed/prefill token count;
- native first-token timestamp;
- native scheduler-admission timestamp;
- hardware performance counters.

An unavailable optional capability is not converted into an approximation.

## Running

From the repository root, in the same kind of pinned environment previously
used for the Phase 1B Metal validation:

```bash
PYTHONPATH=src:. python -m scripts.spikes.run_phase2_minimal_observability_metal
```

Optional source-revision provenance:

```bash
PYTHONPATH=src:. python -m scripts.spikes.run_phase2_minimal_observability_metal \
  --vllm-metal-source-checkout /absolute/path/to/vllm-metal
```

The launcher supplies the low-level environment switches already required by
the qualified Phase 1B in-process Metal observation path:

```text
VLLM_ENABLE_V1_MULTIPROCESSING=0
VLLM_METAL_USE_PAGED_ATTENTION=1
VLLM_METAL_MEMORY_FRACTION=auto
VLLM_MLX_DEVICE=gpu
VLLM_HOST_IP=127.0.0.1
```

Default outputs are written under:

```text
artifacts/phase2-observability/<run_id>/
    run.json
    trace.json
    replay.jsonl
    events.jsonl
    observation-report.json
    stderr.log              # only when the runner catches an execution failure
```

A nonzero launcher exit means the minimum observation chain is incomplete.  It
does **not** by itself imply that vLLM inference is broken; inspect
`observation-report.json` and `run.json.failure_reason` to identify the
missing boundary.

## Interpretation

PASS means the M5 substrate is capable of carrying the first Phase 2A
forced-release evidence on a real runtime with a small configuration.

PASS does not validate:

- performance neutrality of instrumentation;
- formal repetition counts;
- cross-machine timing comparability;
- the final Phase 2A scenario matrix;
- an oracle or regret definition;
- the Cost-Aware policy.

Those remain later integration / M6 experimental work.
