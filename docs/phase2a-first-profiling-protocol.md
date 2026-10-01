# Phase 2A First Profiling Protocol

Status: FROZEN FOR PILOT PROFILING

## 1. Objective

The first profiling round answers three questions:

1. Do forced-release decisions with at least two meaningful candidates occur reproducibly under controlled real-runtime pressure?
2. How different are logical release, physical eviction, eventual recomputation, and serving impact?
3. Does Continuum's current forced-release ordering leave measurable hindsight headroom that could plausibly be reduced using decision-time information?

This round is diagnostic. It is not the final paper benchmark and it does not test a Cost-Aware implementation.

## 2. Backend

Use the already validated low-configuration environment first:

- vLLM 0.27.1
- vLLM-Metal / Apple Silicon Metal
- paged KV + APC enabled
- single in-process EngineCore
- Qwen/Qwen2.5-0.5B-Instruct
- max_new_tokens = 1 unless a timing capability requires otherwise

Reuse the same environment class already validated by the minimal real-runtime observability test.

## 3. Controlled scarcity rule

Do not create pressure by approaching physical OOM.

For protected prefix block counts p_1 ... p_k and one pressure request requiring D blocks, use:

num_gpu_blocks_override = sum(p_i) + D

Under the currently validated topology, one null block is reserved. After all protected prefixes are present, ordinary supply is D - 1, so one additional eligible block is required and protected release is forced.

Every run must verify the observed free queue rather than assuming the algebra held.

## 4. Pilot scenario families

Keep the first round small. The purpose is to expose structure, not cover the full paper design space.

### P0 — equal-cost sanity

Two protected candidates with equal prefix size.

Suggested:
- 256 vs 256 tokens

Purpose:
- verify repeated candidate-set / logical-release / physical-eviction joins
- estimate baseline event variability
- detect bookkeeping artifacts

### P1 — recomputation-cost heterogeneity

Two candidates with different reusable-prefix sizes while holding future return pattern similar.

Suggested:
- 128 vs 256 tokens
- 256 vs 512 tokens

Purpose:
- test whether logical size / PrefillReload differences translate into physical eviction and eventual recomputation differences

The backend must materialize requested per-program prefix size rather than pretending all prefixes are 256 tokens.

### P2 — reuse heterogeneity

Equal-size candidates, different future return pattern.

At minimum include:
- A returns before B
- B returns before A
- one candidate does not return within the analysis horizon

Purpose:
- separate reuse likelihood/timing from recomputation size

Planned timing and actual timing must both be retained. If the current backend does not execute planned offsets/tool gaps, extend that backend before P2 data are interpreted as timing evidence.

### P3 — mixed heterogeneity

Combine size/cost and future return differences, for example:
- large prefix + early return
- small prefix + late/no return
- reversed assignment

Purpose:
- create decisions where coarse forced-release ordering can be compared with realized future cost

## 5. Repetitions

Pilot minimum:
- 3 independent run seeds per concrete scenario

A concrete scenario fixes:
- candidate count
- prefix sizes
- future return pattern
- pressure demand
- policy/runtime mode

If a run fails to produce candidate_count >= 2 or does not trigger forced release, it is an invalid scenario realization, not a zero-loss sample.

Do not silently replace invalid runs.

## 6. Runtime mode

First profiling target:
- Continuum CONTROLLED

Native LRU is useful later as a system baseline, but the Empirical Gap Gate asks whether Continuum's forced-release decision has exploitable headroom.

Do not implement or run Cost-Aware in this round.

## 7. Required outputs

Raw:
- run.json
- trace.json
- replay.jsonl
- events.jsonl
- capability report or equivalent manifest fields

M6 derived:
- decision_candidates
- physical_evictions
- request_outcomes
- decision_outcomes

Every derived row retains:
- run_id
- decision_event_index
- candidate program_id
- candidate prefix_id
- source event_index references

## 8. First analysis views

For each decision, report all candidates, not only the selected one.

At minimum compute:
- candidate count
- logical prefix size / block count
- logical release indicator
- newly eligible block count
- physical eviction count before each candidate returns
- return/no-return within horizon
- time to return
- recomputed/prefill tokens if AVAILABLE
- serving timing outcomes if AVAILABLE

Then compare without collapsing them prematurely:
- logical release
- physical eviction
- recompute
- serving impact

## 9. Timing rule

The observability smoke proved ordering, not real arrival-gap execution.

Therefore:
- P0/P1 may proceed using deterministic order even if planned offsets are not slept, provided timing is not used as an outcome
- P2/P3 require actual arrival/tool-gap execution or another approved timing mechanism before return-time results are treated as empirical timing evidence

This is a protocol boundary, not a reason to reopen M5.

## 10. Stop condition

After the pilot, stop and review before expanding the matrix.

The pilot is complete when M6 can produce:

1. one decision-candidate table covering attempted P0-P3 scenarios
2. a logical-vs-physical divergence summary
3. a future-return/recompute summary
4. the Empirical Gap Gate report
