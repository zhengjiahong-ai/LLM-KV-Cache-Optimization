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

### Task 0: run the full P0-P3 pilot suite

Run the entire first profiling round in one batch.

From the repository root:

```bash
git checkout feature/phase2a-profiling-protocol
git pull

PYTHONPATH=src:. \
python benchmarks/run_phase2a_full_pilot.py
```

If the pinned vLLM-Metal source checkout is available:

```bash
PYTHONPATH=src:. \
python benchmarks/run_phase2a_full_pilot.py \
  --vllm-metal-source-checkout /absolute/path/to/vllm-metal
```

The frozen suite contains 10 concrete scenarios:

```text
P0
  1 equal-cost sanity scenario

P1
  2 recomputation-cost heterogeneity scenarios

P2
  3 reuse / return-pattern scenarios

P3
  4 mixed cost x return-pattern scenarios
```

Each scenario runs seeds:

```text
11
23
37
```

for exactly 30 runs.

This intentionally reaches the minimum 30-decision diagnostic volume in the Empirical Gap Gate in one release. Do not insert an artificial P0/P1 checkpoint before P2/P3 unless the suite encounters an actual execution or data-integrity failure.

P2/P3 configs enable real planned timing. Preserve both planned timing and observed monotonic timing; do not overwrite either.

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

### Task B: validate all four scenario families

For all 30 runs check:

- forced release occurred
- candidate_count >= 2
- logical selected release is joinable
- actual physical eviction is joinable
- future program/prefix lifecycle is joinable
- materialized prefix size matches the scenario
- P2/P3 planned timing and observed timing are both retained
- no provenance was lost

Interpret the families separately:

P0:
- equal-cost sanity, 256 vs 256

P1:
- cost heterogeneity, 128 vs 256 and 256 vs 512

P2:
- equal-size candidates with A-early, B-early, and outside-horizon return patterns

P3:
- 512 vs 128 and 128 vs 512 crossed with A-early / B-early return patterns

Do not collapse all 30 runs into one average before checking per-family behavior.

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

Return for review after the full 30-run P0-P3 suite has completed, or earlier only if there is a real execution/data-integrity blocker.

Bring back:

- the full artifact directory for all runs
- decision_candidates
- logical_releases
- physical_evictions
- request_outcomes
- decision_outcomes
- a run-validity table

At that checkpoint we run the frozen Empirical Gap Gate directly. There is no additional staged release between P0/P1 and P2/P3.
