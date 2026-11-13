# Phase 3 Algorithm Exposure & Zero-Effect Investigation

**Status:** M6 read-only offline audit; pending M1 review

**Source archive SHA-256:** `d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8`

**Frozen classification SHA-256:** `82b23d68a0af0fa715dca6886250aee395f308ce1882a0416096f4ebfc029ec6`

This audit investigates why the completed Option F campaign observed no
incremental recomputation benefit for A1/A2/A3/E0 over A0. It changes neither
the sealed evidence nor the Protocol v4 estimands. Facts, interpretations, and
evidence gaps are separated explicitly.

## 1. Executive summary

The campaign provided substantial **resource-pressure exposure**, but sparse
**algorithm-decision exposure**.

- Every one of the 40 Main cells issued the same frozen pressure request in all
  six arms. A0/A1/A2/A3/E0 each produced 127 forced Entry Release decisions;
  N0 correctly produced none.
- Of the 127 release decisions, 120 had one Entry candidate and only 7 had two.
  Thus only **7/127 (5.5%)** were genuine A1/A3/E0 multi-candidate ordering
  opportunities.
- All 134 A3 candidate audits had verified content, positive Prefill evidence,
  complete victim depths, nonempty victim geometry, and a finite score. The
  issue was not missing A3 evidence.
- In all seven multi-candidate A3 decisions, Cost ordering and Deadline ordering
  selected the same Entry. A3 also selected the same program as frozen A1 in
  all 127 decisions. Numerically distinct scores existed, but their ordering
  did not create selection divergence.
- A2 executed cost-known incremental greedy selection in 53/127 decisions and
  fell back to Native LRU for `content_unverified` in 74/127. In all 127
  decisions, including the 53 cost-known cases, its selected victim sequence
  equaled Native LRU. No bounded-exhaustive branch was observed.
- All 635 forced decisions across the five release-enabled arms have a recorded
  `PHYSICAL_EVICTION_OBSERVED` outcome. Each arm records 14,241 matched physical
  blocks and zero unmatched blocks. This establishes runtime execution records,
  but not unique per-decision downstream recomputation causality.
- No case was found where a registered policy produced a different effective
  selection and the runtime later erased that difference. The dominant classes
  are (A) no selection space and (B) selection space with the same ordering.

The zero incremental effect is therefore primarily explained by candidate
construction and signal alignment, not by insufficient pressure and not by an
obvious missing A3 runtime connection. A2 additionally suffered substantial
content-evidence fallback.

## 2. Experimental evidence inventory

The analyzer reads all 240 Main `events.jsonl` members directly from the sealed
archive and checks that the complete 20 Groups × 2 Conditions × 6 Arms set is
present exactly once. It emits 635 decision rows, each traceable to Run ID,
Decision ID, Forced Release event index, and strategy event index.

Generated files are in
[`phase3-algorithm-exposure-audit-data`](phase3-algorithm-exposure-audit-data/README.md):

- `global-summary.csv`;
- `group-condition-summary.csv`;
- `decision-audit.csv`;
- `strategy-pairwise-comparison.csv`;
- `fallback-reason-distribution.csv`;
- `summary.json` and `sha256-manifest.txt`.

The script refuses an existing output directory, validates the complete Main
run grid, and never extracts into or writes to the source archive.

## 3. Decision opportunity analysis

| Arm | Pressure requests | Forced releases | Candidate rows | Multi-candidate | Multi-scored | Fallbacks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| N0 | 40 | 0 | 0 | 0 | 0 | 0 |
| A0 | 40 | 127 | 134 | 7 | n/a | 0 |
| A1 | 40 | 127 | 134 | 7 | 7 | 0 |
| A2 | 40 | 127 | 134 | 7 | n/a | 74 |
| A3 | 40 | 127 | 134 | 7 | 7 | 0 |
| E0 | 40 | 127 | 134 | 7 | 7 | 0 |

Candidate count distribution for A3 is 120 decisions with one candidate and 7
with two. All 127 used `step2_sufficient`; no Step 3/4/5 decision occurred.
Consequently, 127 strategy invocations do not imply 127 competitive cost-model
opportunities. The correct denominator is seven.

The seven opportunities were:

- g09 C1/C2;
- g10 C1/C2;
- g16 C1/C2;
- g18 C2.

They comprise three C1 and four C2 cells. Increasing from C1 to C2 therefore
added only one competitive decision, despite producing a different registered
resource-pressure condition.

## 4. Branch coverage and core-mechanism execution

### A1

All 127 actual release decisions used the single-step sufficient branch. Seven
decisions scored two candidates. Per-unit, pair-lookahead, and deadline-fallback
branches were not exercised. A1 selected the same program as A0 in all paired
decisions before any trajectory divergence.

### A2

- `incremental_greedy`, cost known: 53 decisions;
- `native_lru_fallback`, `content_unverified`: 74 decisions;
- search truncated: 51 decisions;
- bounded exhaustive: 0 decisions;
- victim sequence different from Native LRU: 0 decisions.

A2 therefore executed its cost-aware machinery in 53 cases, but it never
changed the chosen victim sequence. The other 74 decisions provide no A2-vs-LRU
algorithm competition because the required content evidence was unavailable.

### A3

All 127 decisions entered Step 2. Across 134 audited candidates:

- content identity verified: 134/134;
- positive Prefill Reload Cost: 134/134;
- complete victim depths: 134/134;
- nonempty predicted victim geometry: 134/134;
- score present: 134/134;
- evidence fallback: 0.

A3's core score was computed correctly, but only seven decisions exposed it to
a competing candidate. A3 selected the same program as frozen A1 in all 127.

### E0

E0 reproduced the A3 classifier for all 127 decisions and entered its
deadline-only Step 2 ordering in all 127. It had the same seven multi-candidate
opportunities and no evidence fallback. E0 and A3 selected the same program in
all paired decisions.

The registered G2 counts are S2A=127, S2B=0 and S2C=0 (C1: 63/0/0;
C2: 64/0/0). Because A3 and E0 never selected different programs, G3-CM has
zero PROFILE_ROBUST and zero PROFILE_SENSITIVE discriminable decisions. This
is below the frozen minimum of eight, so `H2 = NOT_EVALUABLE`.

## 5. Score separation and selection divergence

All seven multi-candidate A3 decisions had nonzero first-versus-second score
gaps. Their relative gaps ranged from about 2.0% to more than 900× the winning
score. Thus the scores were not numerically identical.

However, within every multi-candidate decision:

- Cost and Deadline ranks had Spearman correlation 1.0;
- Cost and Deadline chose the same first-ranked Entry;
- A3 and A1 selected the same Entry;
- A3 and E0 selected the same program.

This is **Case B: selection space existed, but ordering agreed**, not Case C
(identical scores). The remaining 120 A3 decisions are **Case A: no selection
space**. No supported Case D or E was observed.

Cross-run program-level pairing reports no A0/A1, A0/A2, or A3/E0 selection
divergence. Native prefix hashes and physical block IDs are process-local, so
the audit does not treat raw cross-run hash equality as portable identity.

## 6. Native execution and outcome attribution

Every forced decision has a SelectionPlan and a physical outcome record. Across
each release-enabled arm:

- physical outcomes: 127;
- outcome status: `PHYSICAL_EVICTION_OBSERVED` for all 127;
- matched physical blocks: 14,241;
- unmatched physical blocks: 0.

A3 and E0 record predicted victim sets for all 127 decisions. Every predicted
block appears in the matched physical set (12,545/12,545); 108 decisions have an
exact predicted/physical set match, while 19 physical outcomes contain
additional matched blocks. Predicted victims therefore cannot be substituted
for the complete physical outcome.

The archive does not establish a unique per-decision chain from physical block
identity through a later content re-request to request-level recomputed tokens.
The formal N/E/C evaluator establishes cell-level outcomes, while
`downstream_recompute_attribution` remains `NOT_ESTABLISHED` for every decision.
No claim of individual eviction causality is made.

## 7. Workload exposure and pressure manipulation

Resource pressure and algorithm opportunity are empirically distinct:

- C1 generated 63 forced releases and 3 A3 multi-scored decisions.
- C2 generated 64 forced releases and 4 A3 multi-scored decisions.
- FLAT: 40 forced releases across 6 cells, 0 competitive decisions.
- WEAK: 50 forced releases across 16 cells, 0 competitive decisions.
- RESPONSIVE: 37 forced releases across 18 cells, all 7
  competitive decisions.

The frozen conditions produced resource pressure and physical evictions, but
pressure usually required releasing only one sufficient Entry. RESPONSIVE
Groups were the only source of competition, yet most RESPONSIVE decisions also
had only one candidate. Resource-pressure adequacy therefore does not imply
algorithm-exposure adequacy.

## 8. Failure and limitation analysis

### Established facts

- The complete Main run grid executed.
- Pressure, forced release, strategy, SelectionPlan, and physical-outcome events
  are present at the counts above.
- A3 evidence was complete for every audited candidate.
- A2 frequently fell back and never diverged from Native LRU.
- A3/A1/E0 never diverged in selected program.

### Evidence-supported interpretation

The principal bottleneck was candidate competition. Where competition existed,
Deadline and cost signals were aligned. For A2, incomplete content evidence was
an additional bottleneck.

### Not established

- unique content-level attribution from an individual decision to later
  recomputation;
- what a counterfactual divergent selection would have done;
- general equivalence of any pair of strategies outside this cohort;
- benefit under a workload with deliberately richer simultaneous candidate
  competition.

## 9. Answers to the registered research questions

**RQ1 — Was there enough resource pressure?** Yes for exercising the release and
physical paths: 127 forced releases and 14,241 matched physical blocks per
release-enabled arm. This does not imply adequate algorithm exposure.

**RQ2 — Was there enough candidate competition?** No. A3 had only seven genuine
multi-scored opportunities, 5.5% of its release decisions.

**RQ3 — Why was there no algorithm difference?** Primarily because 120/127 A3
decisions had no choice. In the remaining seven, distinct numeric scores induced
the same ordering as Deadline. A2 additionally fell back in 74/127 decisions.

**RQ4 — Did each algorithm execute its core mechanism?** A1, A3, and E0 executed
their Step-2 logic, but competitive ordering was exposed only seven times. A2
executed cost-known greedy selection 53 times and fell back 74 times; it never
changed Native LRU's victim sequence.

**RQ5 — Could different choices affect physical eviction and recomputation?** No
actual selection divergence was observed, so this campaign contains no direct
counterexample to test. Physical execution is recorded, but per-decision future
recompute attribution is not established.

**RQ6 — Where is the workload complex or simple?** It is complex enough to
produce history-rich Native replay, pressure, release, thousands of physical
evictions, and heterogeneous recomputation response. It remains simple at the
decision boundary because simultaneous sufficient candidates are rare and the
few candidate rankings are aligned.

**RQ7 — What should a separately authorized next study change?** First target
candidate construction and exposure, not greater pressure alone. A useful next
study would pre-register naturally occurring or independently selected states
with multiple content-verified sufficient Entries and measurable disagreement
between Deadline and cost ranks. A2 requires better pre-decision content
identity coverage before changing its scoring formula. Algorithm redesign is
premature until those exposure constraints are addressed.

## 10. Recommended next steps

1. Preserve this result as a valid negative component evaluation.
2. Do not rerun the frozen Phase 3 campaign or alter its evaluator.
3. If M1 authorizes a later study, freeze decision-exposure eligibility before
   observing policy outcomes.
4. Require multiple sufficient, fully scored candidates as an inclusion or
   stratification variable; do not manufacture them by adapting pressure to
   policy results.
5. For A2, improve content-identity evidence coverage and independently verify
   that cost-known cases can disagree with Native LRU before allocating a large
   campaign.
6. Retain per-decision downstream attribution as an explicit evidence gap unless
   a future runtime design observes content re-request and recomputation identity
   without inference.

No new experiment, protocol change, or algorithm modification is authorized by
this report.

## 11. Reproduction

```bash
PYTHONPATH=. .venv/bin/python \
  -m scripts.spikes.analyze_phase3_algorithm_exposure \
  --archive artifacts/phase3-option-f-unified-270-runs-v2-evidence.tar.gz \
  --classification docs/experiments/phase3-option-f-g0-v3/g0/calibration-classification.json \
  --output docs/experiments/phase3-algorithm-exposure-audit-data
```

The output directory must not already exist. This makes accidental overwriting
of a reviewed derivative fail closed.
