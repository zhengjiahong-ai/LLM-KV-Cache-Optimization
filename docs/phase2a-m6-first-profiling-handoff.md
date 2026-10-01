# Phase 2A First Profiling Handoff

Status: READY TO START

## Goal

Do not implement Cost-Aware yet.

The immediate goal is to collect enough real-runtime evidence to decide whether Continuum forced release has exploitable, online-predictable headroom.

Read together:

- phase2a-profiling-data-contract.md
- phase2a-first-profiling-protocol.md
- phase2a-empirical-gap-gate.md

## M6 — start now

### Task A: build the derived dataset pipeline

Input source of truth:

- run.json
- trace.json
- replay.jsonl
- events.jsonl

Construct:

1. runs
2. decisions
3. decision_candidates
4. logical_releases
5. physical_evictions
6. request_outcomes
7. decision_outcomes

The minimum decision_candidates key is:

(run_id, decision_event_index, program_id, prefix_id)

Every derived row must retain raw source event indexes.

Do not put oracle/regret into runtime code.

### Task B: collect P0 first

P0 is equal-cost sanity:

- 2 protected candidates
- 256 vs 256 reusable tokens
- controlled pressure
- at least 3 seeds

Check:

- candidate_count >= 2
- logical selected release
- actual physical evictions
- future program/prefix return
- no lost provenance

### Task C: collect P1 after per-program prefix sizing is available

P1 targets cost heterogeneity:

- 128 vs 256
- 256 vs 512
- at least 3 seeds per concrete case

Do not emulate size differences only in analysis; the backend must materialize the actual requested reusable-token sizes.

### Task D: do not interpret P2/P3 timing yet

P2/P3 require actual arrival/tool-gap execution.

The current minimal observability backend proves ordering, not planned real-time gaps.

Until the profiling backend executes planned timing, P2/P3 may be prepared but not used as timing evidence.

## M1 — immediate implementation work

### I1: per-program prefix-size materialization

Generalize the Metal profiling backend so each program can request an explicit reusable prefix token count.

Required measured sizes for first pilot:

- 128
- 256
- 512

The materialized runtime input and persisted event must agree on actual token count.

### I2: actual workload timing

For profiling runs that use return timing:

- preserve planned_arrival_offset_seconds as input
- execute against a run-relative monotonic schedule
- preserve actual request-arrival timestamp
- preserve actual tool-gap start/end

Do not rewrite planned timing after the run.

### I3: physical eviction enrichment, if safe

At the already-approved native eviction boundary, attempt to preserve pre-eviction:

- block_id
- native hash/content identity
- known logical owners

Only add fields that can be read reliably without changing eviction behavior.

If content identity or owner mapping cannot be exposed safely, leave explicit UNAVAILABLE rather than delaying P0.

### I4: capability audit

Investigate whether the pinned vLLM stack can safely expose:

- cached/APC-hit token count
- recomputed/prefill token count
- first-token timestamp
- native scheduler-admission timestamp

These are useful but are not all blockers for P0.

## M4

Hold.

Do not implement a score, oracle approximation, policy, or victim-ranking change before the Empirical Gap Gate.

## M5

No action unless a generic substrate bug is discovered.

M5 substrate remains CLOSED.

## First checkpoint

Return for review when either:

A. M6 has at least 3 valid P0 runs and the first decision_candidates / physical_evictions join; or

B. M1 has the profiling backend ready for per-program prefix sizes and real planned timing.

At that checkpoint we verify the data shape before scaling to the 30-decision pilot target.
