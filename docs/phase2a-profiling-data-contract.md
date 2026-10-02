# Phase 2A Profiling Data Contract

Status: FROZEN FOR FIRST PROFILING ROUND

This document defines the raw facts preserved before any Cost-Aware method is implemented.

## 1. Principle

Phase 2A records the full causal chain instead of choosing one loss definition too early:

decision-time state
-> logical release
-> physical eviction/reuse
-> future cache/recompute facts
-> serving outcome

Runtime/backend code exposes facts. M6 owns joins, derived labels, oracle construction, regret, statistics, and plots.

Runtime components must not emit oracle, regret, future_reused, optimal_victim, or any equivalent future-derived label.

## 2. Canonical identities

Every persisted record belongs to one run and has append-only event_index.

Canonical join keys:

- run: run_id
- decision: (run_id, decision_event_index), where decision_event_index is the FORCED_RELEASE_DECISION event index
- logical cache object: (program_id, prefix_id)
- request: (run_id, request_id)
- physical slot: block_id, only within a bounded state interval

A bare block_id is not a persistent content identity because native block slots can be reused. When the approved backend can expose it, physical eviction records should also persist pre-eviction native hash/content identity.

Ordering inside one artifact stream uses event_index. Timestamps are compared only when clock_domain compatibility is known.

## 3. Layer A — decision-time state and logical release

Source of truth: FORCED_RELEASE_DECISION.

Required decision fields:

- event_index
- timestamp
- clock_domain
- required_blocks
- original_free_queue
- ordinary_expired_entries
- candidates
- selected_releases

Required per candidate:

- program_id
- prefix_id
- retention_deadline_timestamp
- waiting_followup
- block_ids
- initially_reclaimable_block_ids
- next_tool_type
- elapsed_since_ttl_decision_seconds
- prefill_reload_seconds
- eta
- queue_delay_t_seconds

Required per selected logical release:

- program_id
- prefix_id
- newly_eligible_block_ids

selected_releases means the retention layer removed protection. It does not mean every newly eligible block was immediately evicted.

## 4. Layer B — physical cache action

Minimum required raw fact:

BLOCK_EVICTED:
- event_index
- timestamp
- block_id

Desired enrichment, when reliably available from the already-approved native hook before mutation:

- native_hash_hex or equivalent content identity
- known logical owners [(program_id, prefix_id), ...]
- native LRU position if observed at that exact boundary

The enrichment is observation only. If a field cannot be captured without a new unsafe/private inference path, record it as unavailable rather than fabricating it.

M6 must distinguish:

- logical released blocks
- physical blocks actually evicted
- physical block slots later reused

These are not interchangeable quantities.

## 5. Layer C — future cache and recomputation facts

Always preserve future lifecycle:

- REQUEST_ARRIVED
- REQUEST_ADMITTED, with its semantic boundary documented
- BLOCKS_OBSERVED / VLLM_PREFIX_SNAPSHOT
- TURN_FINISHED
- PROGRAM_COMPLETED

Preserve both the old logical identity and newly observed physical mapping whenever a program returns.

Additional backend facts are capability-gated:

- native APC hit/miss
- cached-token count
- computed/recomputed/prefill-token count
- native cache lookup result

Every capability must be either AVAILABLE or UNAVAILABLE + reason.

Do not infer native hit/miss or recompute-token count from prefix identity alone.

## 6. Layer D — timing and serving outcome

Keep workload intent and runtime reality separate.

Planned inputs:

- planned_arrival_offset_seconds
- tool_gap_seconds
- turn order
- generation parameters
- pressure-stage parameters

Observed runtime landmarks, when available:

- request arrival
- backend submission
- native scheduler admission
- first token
- completion
- tool-gap start/end
- output token count

The current Phase 2 REQUEST_ADMITTED boundary must not be silently relabelled as native scheduler-admission timing.

M6 derives queue delay, TTFT, E2E latency, and throughput only from compatible raw landmarks.

## 7. Provenance

Every run preserves at least:

- repository SHA + dirty state
- trace/config hash
- policy/runtime mode
- backend identity/revision
- model/tokenizer + immutable revision
- cache/block settings
- seed
- generation/batching settings
- hardware capability description
- observation capability availability

Raw artifacts remain source of truth:

- run.json
- trace.json
- replay.jsonl
- events.jsonl

## 8. M6 derived datasets

M6 may construct:

- runs
- decisions
- decision_candidates
- logical_releases
- physical_evictions
- request_outcomes
- decision_outcomes

Recommended decision_candidates grain: one row per candidate per forced-release decision.

Recommended decision_outcomes grain: one row per candidate per decision after joining only events that occur after that decision.

Derived columns may include:

- logical_blocks_released
- physical_blocks_evicted_before_return
- returned_within_horizon
- time_to_return
- recomputed_tokens
- serving_impact
- hindsight_loss
- oracle_candidate
- regret

These belong to M6 processing, not runtime event schema.

## 9. Multiple loss views are intentional

Phase 2A retains enough evidence to compare:

LogicalReleaseCost:
whole logical entry whose protection was removed

PhysicalEvictionCost:
actual cache content physically displaced

RecomputeCost:
work actually redone when future requests arrive

ServingImpact:
observed request-level latency / service effect

The first profiling round must not assume these are equivalent.

## 10. Ownership

M1:
- freezes observation semantics and safe backend seams
- approves any additional native observation hook

M5:
- substrate remains CLOSED
- no new generic substrate feature is required for this round

M6:
- selects raw fields
- constructs datasets
- joins events
- derives outcomes/oracles/regret
- performs statistics and plots

M4:
- does not implement Cost-Aware before the Empirical Gap Gate
