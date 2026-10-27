# Bounded Native Cost-Aware evaluation results

Status: **EXECUTION COMPLETE / PENDING M1 RESULT REVIEW**

This report closes execution of the M1-authorized low-cost bounded evaluation.
It is an exploratory paired comparison on nine predefined two-task workload
groups, not a population-level performance claim.

## Frozen execution

- Model and tokenizer: `Qwen/Qwen2.5-Coder-1.5B-Instruct` at
  `d18ecad881a290f0c792f1c2b5dbee1820d4a424`.
- Runtime: vLLM 0.27.1 on one RTX 4090D, 32,768-token context, 2,048-token
  chunked-prefill budget, eager execution, and a 2,048-block KV pool.
- Workload: all 18 frozen W1-C tasks in nine disjoint groups.
- Cells: moderate/deep pressure by A0/A1/A2, one runtime execution per cell.
- Completion: 54/54 Native runs succeeded; all nine statistical units are
  complete; integrated Native fidelity and campaign validation passed.
- Execution wall time for the final end-to-end v10 continuation was 38m53.541s.

The seven-point PrefillReload profile retained its raw measurements. Per M1's
bounded interpretation, the 1,024-token median was preserved as
`INDISTINGUISHABLE_FROM_ZERO`, while its effective non-negative cost
representation was zero. No Profile point was remeasured after observing an
outcome.

## Paired recomputation results

The primary metric is `aggregate_recomputed_tokens = sum(E - C)`, and deltas
are policy minus A0, so a negative delta is an improvement.

| Arm | Better | Worse | Tied | Mean delta | Median delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 | 0 | 1 | 8 | +412.44 | 0 |
| A2 | 0 | 3 | 6 | +321.78 | 0 |

The nonzero group effects were:

- A1: `g05-low-high` +3,712 tokens.
- A2: `g02-low-high` +1,824, `g08-mid-high` +816, and
  `g09-near-matched` +256 tokens.

No group showed a recomputation-token improvement for A1 or A2.

## Decision and mechanism evidence

All 54 runs were classified `REALIZED`, meaning that the frozen pressure path
exposed a release decision and corresponding physical eviction evidence.

A1 produced 29 release-selection steps. Twenty-seven matched the
Sufficient-first + Earliest Deadline comparator and 25 matched
Sufficient-first + Minimum Overshoot. Eighteen decisions had a positive q span,
11 had a zero q span, and the maximum observed span was approximately 0.5.
A1's entry-release sequence differed from A0 in two of 18 pressure cells, both
in `g05-low-high`; only the moderate cell was followed by a nonzero paired
recomputation delta.

A2 emitted 601 Cost-Aware Block Decision events. Three of nine workload groups
had positive recomputation deltas and none had a negative delta.

The report records cross-arm physical-signature differences, but these are not
treated as per-block causal attribution. Runs execute in independent Native
processes, and the approved evaluator labels the physical-to-downstream link as
temporal association unless the complete content-identity chain establishes a
stronger claim. The final report therefore retains
`content_level_causal_attribution = NOT_ESTABLISHED`.

## Interpretation

The expanded workload created more varied decision states: A1 was not always
reproducible by either simple comparator, and q was nonconstant in 18 of 29
selection steps. That variation did not produce an observed token benefit in
this bounded execution. The only A1 token change was adverse, and A2 was
adverse in three groups.

These observations do not establish universal algorithm inferiority. There is
only one runtime execution per cell, no run-to-run noise estimate, and only
nine independent workload groups. They do establish that this predefined grid
provides no positive recomputation evidence for the frozen A1 or A2 policies.
Any next algorithm revision or larger campaign requires a new M1 decision and
must not reinterpret this sealed execution.

## Evidence identity

- Authoritative offline report: `analysis/campaign-report-v2.json` inside the
  external archive.
- Evidence archive SHA-256:
  `ac2b910ef3550f8f8a35ceb2e3227aabb2f4f63820993d311e38a4c8b4e009a9`.
- Internal SHA manifest SHA-256:
  `26d9dc51345a302f504e7f894e16ae2a20c0cfe0e32f5b7a143d0f0d06a25fb4`.
- Final evaluator code revision at evidence recomputation:
  `4211b05` (`test: tolerate floating point q span`) and its preceding
  identity-matching fix `38930b1`.

The large archive remains external to Git. Native run data were not modified
by the offline A1 diagnostics correction; the original report is retained
beside the authoritative v2 report.
