# Phase 2A V5 Observation Capability Contract

Status: FROZEN

Every formal Phase 2 run must persist an explicit capability declaration for
all required observation capabilities.  Missing keys are a data-contract
violation.

Each capability entry has:

- status: AVAILABLE, UNAVAILABLE, or ERROR
- reason: required for UNAVAILABLE and ERROR; optional for AVAILABLE

Canonical required capabilities:

1. runtime_identity
2. logical_lifecycle
3. prefix_block_mapping
4. forced_release_snapshot
5. native_block_eviction
6. native_block_content_identity
7. native_block_logical_owners
8. native_block_lru_position
9. generated_token_count
10. native_apc_hit_miss
11. recomputed_prefill_tokens
12. native_first_token_timestamp
13. native_scheduler_admission_timestamp
14. hardware_counters

The registry intentionally includes physical-eviction enrichment capabilities
as separate keys.  This avoids treating a basic BLOCK_EVICTED callback as if
content identity, owner attribution, or eviction-time LRU position were also
available.

Runner behavior:

- initialize all required keys explicitly;
- let the backend override keys it can actually observe;
- preserve runner/provider-owned hardware capability when a telemetry provider
  is available;
- fail the run if a backend declaration has an invalid status or an unavailable
  capability lacks a reason;
- persist observation_capability_contract.complete=true only after validation.

Formal analysis must fail closed if the required key set is incomplete.

Legacy pre-V5 runs may be retained as diagnostic evidence but must not be
silently upgraded by mutating their raw run.json manifests.
