# Phase 2A M6 Formal Profiling Results

Status: FORMAL RESULT / M4 HANDOFF

## 1. Decision

The frozen Empirical Gap Gate outcome is:

```text
HEADROOM-BUT-NO-ONLINE-SIGNAL
```

The formal campaign shows heterogeneous candidate loss and substantial
Continuum baseline headroom under the supported proxy loss. It does not show a
stable association between any evaluated decision-time feature and that loss
across scenario families and seeds.

M4 should not begin Cost-Aware policy implementation from this evidence. The
next method step requires either a newly approved decision-time observation or
a revised hypothesis. Future-derived labels and hindsight choices must remain
offline-only.

## 2. Authoritative artifacts and provenance

Only the following artifacts are inputs to this result:

- campaign: `artifacts/phase2a-formal-campaign-v4/campaign.json`;
- raw runs: `artifacts/phase2a-formal-v4-final/`;
- execution summary:
  `artifacts/phase2a-formal-v4-final/formal-execution-d2d92156d205.json`;
- final derived bundle: `artifacts/phase2a-formal-v4-derived-v3/`;
- M4 handoff data:
  `artifacts/phase2a-formal-v4-derived-v3/method_support_pack.json`.

The campaign manifest SHA-256 is
`088fc4c7f874ea1b17be1606fc04fb653a61ff2f3bd3cf1cf7564d0086d571fb`.
All 54 raw runs report project Git SHA
`f402cff097764ecead840690fff266fa736f9322` and `git_dirty=false`. The
final derived bundle was produced with analysis Git SHA `f40a3bb`.

The qualified runtime evidence records:

- vLLM distribution `0.27.1+cpu` and module release `0.27.1`;
- vLLM-Metal `0.3.0`;
- clean vLLM-Metal source commit
  `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`;
- the Metal platform plugin active with MLX configured on GPU;
- Qwen/Qwen2.5-0.5B-Instruct model and tokenizer revision
  `7ae557604adf67be50417f59c2c2f167def9a775`;
- macOS arm64 execution with in-process engine observation and paged Metal KV
  enabled.

The final execution ran from `2026-10-04T07:06:11Z` to
`2026-10-04T07:18:58Z`. Every run used a fresh child process so Metal memory
was reclaimed between repetitions.

## 3. Campaign and validity

The campaign contains 18 scenarios across F1-F6 and three predeclared seeds
(`101`, `211`, and `307`), for 54 runs.

| Check | Result |
| --- | ---: |
| Planned / executed runs | 54 / 54 |
| Successful / failed runs | 54 / 0 |
| Runs valid for candidate analysis | 54 / 54 |
| Forced-release decisions | 60 |
| Multi-candidate decisions | 60 (100%) |
| Candidate rows | 174 |
| Logical-release rows | 69 |
| Physical-eviction rows | 870 |
| Request-outcome rows | 384 |
| Decision join coverage | 100% |

The derived statistics use 2,000 deterministic bootstrap resamples, bootstrap
seed 0, and 95% confidence intervals.

## 4. Baseline prevalence

Across all runs, forced release occurred at a rate of `0.15625` decisions per
request. Candidate sets contained 2-5 candidates, with mean size 2.9. Required
pressure was 4-48 blocks, with mean 19.2 blocks. The baseline selected a mean
of 1.15 logical releases per decision.

F4 and F6 contributed repeated-pressure coverage. Six runs contained repeated
pressure, or 11.1% of all runs. No logical object was counted as repeatedly
released without becoming eligible again.

## 5. Candidate and outcome heterogeneity

The decision-time candidates vary in footprint and measured PrefillReload cost
in 60% of decisions. Timing since the TTL decision and the retention deadline
vary in every decision. `eta`, queue delay, and `waiting_followup` have no
within-decision spread in this campaign and therefore cannot rank candidates.

The only loss view that supports complete candidate comparison is
`trace_return_weighted_prefill_proxy`. It is explicitly a trace-derived proxy,
not direct recomputation or serving impact.

For this view:

- 43 of 60 decisions have positive within-decision loss spread (71.7%);
- mean spread is `0.07379` seconds;
- bootstrap 95% CI for mean spread is `[0.06113, 0.08616]`.

Observed physical eviction is available for 57 candidate outcomes and is
classified as block-slot proxy evidence. It is unavailable for the other 117
candidate outcomes. Observed recomputed-token loss is unavailable for all 174
candidates. Native APC hit/miss and hardware-counter capabilities are also
unavailable. Missingness is explicit in the derived tables.

## 6. Baseline headroom

Under `trace_return_weighted_prefill_proxy`:

- 31 decisions are non-tied;
- Continuum selects a strictly worse release set in 17 of them;
- non-tied misselection rate is `54.84%`;
- mean absolute regret is `0.04170` seconds, with 95% CI
  `[0.02943, 0.05486]`;
- mean normalized regret is `0.45215`, with 95% CI
  `[0.33707, 0.57482]`.

Representative high-regret cases include:

| Run / decision | Absolute regret | Normalized regret |
| --- | ---: | ---: |
| `f6-shared-ownership-audit-seed-101`, event 40 | 0.17106 | 1.00000 |
| `f1-five-contention-deep-seed-101`, event 64 | 0.13848 | 0.73568 |
| `f4-deep-multi-release-seed-101`, event 40 | 0.08873 | 0.64072 |

These are offline hindsight comparisons. They demonstrate headroom but do not
provide an online policy input.

## 7. Decision-time signal analysis

Signal analysis keeps only decisions where both the feature and loss
differentiate candidates, normalizes ranks within each decision, and then
checks direction stability across six families and three seeds. Numeric
features are evaluated directly. `next_tool_type` is evaluated as three
predeclared one-hot features so no artificial category ordering is imposed.

Support requires absolute overall Spearman rho of at least 0.2, at least three
evaluable family and seed groups, and direction agreement of at least 2/3.
None of the 11 evaluated representations pass.

| Feature | Overall rho | Family agreement | Supported |
| --- | ---: | ---: | --- |
| block count | 0.073 | 0.500 | no |
| initially reclaimable blocks | 0.073 | 0.500 | no |
| PrefillReload | 0.073 | 0.500 | no |
| elapsed since TTL decision | 0.101 | 0.833 | no |
| retention deadline | -0.101 | 0.833 | no |
| next tool = search | -0.110 | 0.667 | no |
| next tool = database | 0.007 | 0.500 | no |
| next tool = code | 0.097 | 0.500 | no |
| eta | unavailable: no within-decision spread | - | no |
| queue delay | unavailable: no within-decision spread | - | no |
| waiting follow-up | unavailable: no within-decision spread | - | no |

The signal result is `NO_STABLE_SIGNAL`. Seed direction agreement alone is not
sufficient because the family-held checks fail or the effect size is below the
predeclared threshold.

## 8. Empirical Gap Gate

| Gate | Status | Evidence |
| --- | --- | --- |
| Data integrity | PASS | decision join coverage = 1.000 |
| Event volume | PASS | 60 decisions, 6 families, 3 seeds |
| Loss heterogeneity | PASS | proxy view passes spread thresholds |
| Baseline headroom | PASS | proxy view passes regret thresholds |
| Decision-time signal | FAIL | no stable online signal supported |

The overall result is therefore `HEADROOM-BUT-NO-ONLINE-SIGNAL`, not
`GAP-PASS`. The strongest supported loss remains a proxy, so the result also
does not justify claims about direct recomputation or serving impact.

## 9. Handoff and constraints

### M4

- Hold Cost-Aware policy implementation.
- Do not convert the offline hindsight loss or future return labels into online
  features.
- Do not select a score merely because baseline regret is large; the evaluated
  online fields do not generalize across families.
- Preserve support for multiple releases, repeated pressure, block-slot reuse,
  shared ownership, no-return candidates, return-order reversal, and tied
  losses in any future design.

### M1 / observation review

- Decide whether an additional safe decision-time observation is justified,
  such as the already-listed native LRU position or a reviewed reuse-history
  summary.
- If the research claim requires direct realized loss, approve only the
  narrow observation seam needed for recomputed work or serving impact.
- Do not redefine runtime event semantics or change the live baseline decision
  path solely to make the gate pass.

### Remaining limitations

- unselected-victim counterfactual outcomes require controlled replay;
- serving-impact loss is not constructed;
- direct recomputed-token evidence is unavailable;
- physical eviction is incomplete candidate-level block-slot proxy evidence;
- native APC hit/miss and hardware counters are unavailable;
- the workload matrix is controlled and diagnostic, not a final production
  benchmark.

## 10. Excluded diagnostic artifacts

The following directories are retained for debugging and must not be pooled
with the formal result:

- `artifacts/phase2a-formal-v4-runs/`: same-process Metal-memory accumulation;
- `artifacts/phase2a-formal-v4-runs-isolated/`: interrupted/resumed run plus
  SSL and pre-fix context-length failures;
- `artifacts/phase2a-interrupted-runs/`: preserved Control-C partial run;
- `artifacts/phase2a-formal-v4-context-check/`: one-run fix validation;
- `artifacts/phase2a-formal-v4-derived/`: pre-fix rank-confounded signal result;
- `artifacts/phase2a-formal-v4-derived-v2/`: numeric-only signal analysis.

The authoritative formal conclusion must be regenerated only from
`phase2a-formal-v4-final` into `phase2a-formal-v4-derived-v3` or a byte- and
code-equivalent successor.
