# Phase 2G A2 Bounded Native Value Evaluation

## Scope

This record summarizes the M1-authorized exploratory comparison of frozen A0
entry release plus Native LRU block selection against the same entry-release
path plus frozen A2 cost-aware block selection. It is not a paper-level formal
evaluation and does not modify the sealed Gate 2 v3 evidence.

The executed grid contained 36 predefined scenarios (F1--F6, six per family),
two policy arms, and two runtime repeats per arm. The scenario draw is the
independent analysis unit; runtime repeats are not independent samples.

## Execution and integrity

- Planned and successful Native runs: **144 / 144**.
- Valid runs after binding checks: **144 / 144**.
- Comparable repeat pairs: **72 / 72**.
- Complete scenario estimates: **36 / 36**.
- Runtime code: `2f064728054f8d529ade03460f69107a8823d49f`.
- Extended PrefillReload profile SHA-256:
  `96b946b9ff8fb28901790f3444e18542d7defb31dc1390a4248ac0da8e8dda7d`.
- The original Gate 2 v3 campaign and artifacts were not modified or combined
  with this evaluation.

## Request-level token results

The frozen primary metric is `aggregate_recomputed_tokens = sum(E - C)`, and
the paired effect is `A2 - A0`, so a negative value favors A2.

| Result | Scenario count |
|---|---:|
| BETTER | 0 |
| WORSE | 3 |
| TIED | 33 |
| INCONCLUSIVE token pair | 0 |

- Mean scenario delta: **+26.2222 tokens**.
- Median scenario delta: **0 tokens**.
- Exploratory 95% bootstrap interval: **[0.0, 65.3333]**.
- A0 total recomputed tokens: **24,832**.
- A2 total recomputed tokens: **26,720**.
- Total observed arm-level difference: **+1,888 tokens**.
- New-suffix accounting was identical between arms: **6,440 tokens** each.

F1, F2, F3, F5, and F6 were tied in all six scenarios. F4 contained three
tied and three worse scenarios. Its mean delta was **+157.3333 tokens**, median
delta **+48 tokens**, and exploratory interval **[16.0, 330.6667]**. The three
nonzero scenario deltas were:

- `f4-draw-04`: +560 tokens;
- `f4-draw-05`: +96 tokens;
- `f4-draw-06`: +288 tokens.

These are valid paired arm-level observations. They are not, by themselves,
proof that a particular A2 victim caused the later recomputation.

## Selection and physical-evidence audit

The run artifacts contain 778 A2 block-decision events:

- 122 are associated with the 122 forced-release windows;
- 656 occurred in ordinary Native allocation paths;
- 376 used the incremental greedy selector;
- 402 explicitly fell back with `content_unverified`;
- 122 decisions had complete identity/contract evidence;
- two decisions, both repeats of `f4-draw-04`, selected content identities
  different from the A2 internal Native-LRU reference.

The frozen campaign evaluator conservatively considered all 778 decisions when
forming a run-level selection state. The 656 ordinary-allocation decisions with
incomplete identity therefore made all 72 repeat pairs
`SELECTION_NOT_OBSERVABLE`. This is retained rather than rewritten after
outcomes were observed.

The read-only audit also found that the real A0 forced-window victim set agreed
with A2's internal Native-LRU reference in 94 of 122 windows and disagreed in
28. Consequently, the A0 comparator and A2's internal reference were not fully
interchangeable in this workload. Physical evidence also remained incomplete:
3,444 of 7,390 pressure-window eviction records were not strictly mapped under
the frozen content/process/order checks. Event coexistence is not treated as
per-block recomputation causality.

## Research judgment

**Overall: `INCONCLUSIVE`.**

The experiment provides complete request-level paired measurements and records
an **arm-level regression observation** concentrated in F4. However, it does
not establish that the regression was caused by the two observed cost-aware
victim-set divergences because:

1. selection evidence is not observable at the frozen run-level aggregation;
2. A0's actual Tier-aware victim path differs from A2's internal LRU reference
   in 28 forced-release windows; and
3. strict physical identity attribution is incomplete.

Accordingly, this result is neither `VALUE_SUPPORTED` nor a clean proof that
the frozen A2 algorithm is intrinsically worse than LRU. It is also not
`VALUE_NOT_DEMONSTRATED` under a fully faithful comparator. The defensible
conclusion is that value remains unresolved, while the current integrated arms
show a reproducible adverse request-level outcome in three F4 scenarios.

No new campaign, A3 implementation, B1 work, or post-hoc workload/threshold
change is authorized by this record.

## Evidence bindings

| Artifact | SHA-256 |
|---|---|
| Campaign manifest | `2da6c3359b0c1ea13acb85231aec3d7476e090f85aa710735c9b6f9adf9a8d6a` |
| Validation report | `b66487278213d6556c0ca8ce88a280b5ed1d19aa7c11209eff5df4bb6587171a` |
| Authorization record | `ae91a126a4bc1dd41023808d2648e5dd4cb505cdcd86c9258f7f45bfbd31c7ae` |
| Smoke report | `c04774342ca460bb7974af7ef556ff24ec5d7f36cdd3fef7aee606b0f659d778` |
| Campaign report | `45d5ec1355dd0854a66ce3517582bb68cb66b11c67991cde76c2508f11ecec87` |
| Root-cause audit | `605a5d4c90c48c05b2e58936a0eae8b43d3f47deed270e8f4a78e1841000c861` |
| Decision table | `fb2649d0f247af1626425737b7cda98a97babc26bad03bf95019fa6b754a4aad` |

