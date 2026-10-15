# Phase 2E M6 Measured Campaign Report

## Scope and frozen execution

This report records the authorized exploratory Native LRU / Continuum baseline
characterization. It does not authorize or evaluate a new Cost-Aware policy.

- Execution code: `main@9f9de3199f21f45b1c283f62422ab0f85b074a48`
- Design: 36 predefined balanced-grid scenarios, F1–F6 with six scenarios each
- Arms: Native LRU and frozen Continuum baseline
- Repeats: two runtime-noise repeats per scenario and arm
- Planned and successful measured runs: 144 / 144
- Statistical unit: scenario draw; repeats are averaged before cross-scenario summaries
- Generation scope: prefill-focused, `max_new_tokens=1`
- Comparison direction below: Continuum minus Native LRU
- Inferential thresholds, confidence intervals, and significance claims: none

One network-failed attempt and one interrupted attempt were preserved separately.
Neither is silently included in the 144 successful measured runs.

## Gate C and pairing

| Check | Result |
| --- | ---: |
| Valid measured runs | 144 / 144 |
| Comparable scenario-repeat pairs | 72 / 72 |
| Request-metric computable runs | 144 / 144 |
| Excluded successful runs | 0 |
| Family mechanism realized | 132 / 144 |
| Family mechanism not realized | 12 / 144 |

All 12 `NOT_REALIZED` runs are the F4 shared-root cases (draws 01, 03, and
05; both arms and both repeats). They executed successfully and remain valid
for request-level measurement, but did not produce a physical eviction with
pre-eviction identity. They are therefore not eligible for the corresponding
mechanism claim. They were retained rather than deleted or relabeled.

## A1 aggregate efficiency

The values below are means of scenario-level values after repeat aggregation.
They are I-view exploratory summaries, not request-pooled inference.

| Metric | Native LRU | Continuum |
| --- | ---: | ---: |
| Aggregate recomputed tokens | 326.67 | 134.67 |
| Aggregate actual prefill tokens | 1325.89 | 1133.89 |
| Mean TTFT (s) | 0.729370 | 0.729779 |
| Mean queue delay (s) | 0.656917 | 0.657290 |
| Cache reuse efficiency | 0.304998 | 0.400488 |
| Per-draw P99 recomputed tokens | 122.44 | 86.73 |
| Per-draw P99 TTFT (s) | 1.660795 | 1.655004 |

The mean paired aggregate recomputation difference was **−192 tokens per
scenario**. Of 36 scenario draws, 29 were negative, seven were zero, and none
were positive. The mean gross request-level change was 192 tokens. Every
nonzero pair had `NGR=1`; seven zero-gross pairs correctly report NGR as not
applicable rather than zero or one.

This is a paired policy-level observation. It does not identify which physical
eviction caused a later miss, and it is not a formal policy acceptance result.

### Family-level paired aggregate delta

| Family | Mean Continuum − Native LRU tokens | Negative / zero / positive draws |
| --- | ---: | ---: |
| F1 | −266.67 | 6 / 0 / 0 |
| F2 | −128.00 | 6 / 0 / 0 |
| F3 | −357.33 | 6 / 0 / 0 |
| F4 | −133.33 | 3 / 3 / 0 |
| F5 | −208.00 | 6 / 0 / 0 |
| F6 | −58.67 | 2 / 4 / 0 |

F4's three zero draws coincide with the shared-root cases whose required
physical-eviction mechanism was not realized. F6 also contains four zero
draws. These observations remain part of the result rather than being removed.

## A2 tails and token-to-latency transfer

The request-pooled D view is descriptive only:

| Metric | Native LRU | Continuum |
| --- | ---: | ---: |
| P95 recomputed tokens | 176.0 | 128.8 |
| P99 recomputed tokens | 208.0 | 192.0 |
| P95 TTFT (s) | 2.004494 | 2.003531 |
| P99 TTFT (s) | 2.176790 | 2.177563 |
| Spearman recomputation/TTFT | 0.1679 | 0.2359 |

The token-tail difference did not translate into a comparable TTFT-tail
difference. Queue delay dominates the reported queued-to-first-token interval
in this workload. The pooled Spearman associations are weak and descriptive.
`tail_transfer_ratio` is not applicable because the median recomputation is
zero in every run; no value is imputed.

## Missingness and capability limits

- No required A1/A2 field is missing and no metric is marked `LOW_COVERAGE`.
- Twenty zero-recomputation runs make agent concentration and request-level
  recomputation/TTFT correlation mathematically not applicable.
- `tail_transfer_ratio` is not applicable in all 144 runs because its required
  recomputation median is zero.
- P5 remains only partially demonstrated.
- Physical logical-owner attribution remains `NOT_OBSERVABLE`.
- Eviction-to-recomputation causality remains `NOT_ESTABLISHED`; temporal or
  spatial co-occurrence must not be reported as a specific eviction cause.
- F6 demonstrates native request-lifecycle overlap, not GPU-kernel concurrency;
  pressure remains a post-completion barrier rather than in-flight pressure.
- The workload is a predefined synthetic balanced parameter grid, not a random
  sample from a production distribution.
- The prefill-focused one-token generation setting does not characterize
  multi-token decode lifetime or decode concurrency.

## Interpretation

The measured campaign provides reproducible evidence that, in this frozen
synthetic workload, the Continuum baseline retained more reusable prefix work
than Native LRU at the scenario level. It does **not** provide evidence of a
corresponding queued-to-first-token improvement, a specific physical-eviction
causal pathway, production-distribution generality, or the effectiveness of a
new Cost-Aware policy.

The machine-readable Gate C, pair records, run-level metrics, scenario-level
metrics, D/I views, missingness states, and family summaries are generated from
the raw evidence by `kvopt.profiling.phase2e_analysis`.
