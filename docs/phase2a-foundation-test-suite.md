# Phase 2A Foundation Test Suite

Status: READY

This suite is a low-cost real-runtime validation layer for the Phase 2A experiment stack.
It is NOT the formal profiling dataset and must not be used by itself to decide the Cost-Aware method.

## Purpose

The suite validates that the experiment machinery can express and observe the basic dimensions M6 will later study:
- equal-cost candidates;
- heterogeneous reusable-prefix / recomputation size;
- heterogeneous future return order;
- mixed cost x return behavior;
- planned timing versus observed timing;
- logical release -> physical eviction -> future lifecycle joins.

## Scenarios

P0:
- 256 vs 256 equal-cost sanity.

P1:
- 128 vs 256;
- 256 vs 512.

P2:
- A returns earlier;
- B returns earlier;
- one candidate returns outside the analysis horizon.

P3:
- 512 vs 128 crossed with A/B early return;
- 128 vs 512 crossed with A/B early return.

Each concrete scenario currently has seeds 11, 23, 37.
The resulting 30 runs are foundation evidence only.

## What a PASS means

A foundation PASS establishes:
1. scenario materialization matches requested prefix sizes / timing;
2. controlled scarcity triggers multi-candidate forced release;
3. decision-time candidate facts are persisted;
4. logical releases join to physical eviction evidence;
5. future program/prefix lifecycle can be joined;
6. planned and observed timing remain distinguishable.

It does not establish:
- representative workload prevalence;
- final forced-release frequency;
- final candidate-set distribution;
- statistical headroom;
- online predictability;
- Cost-Aware objective or score;
- paper-level performance conclusions.

## Running

Command:
PYTHONPATH=src:. python benchmarks/run_phase2a_full_pilot.py

The historical launcher/file name contains 'pilot'; semantically this command is now the Phase 2A foundation suite.

## Handoff

M6 owns the formal experiment suite that follows this foundation layer.
