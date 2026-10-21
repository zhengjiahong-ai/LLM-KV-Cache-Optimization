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

The original read-only audit reported that the A0 forced-window queue prefix
agreed with A2's internal Native-LRU reference in 94 of 122 windows and
disagreed in 28. The bounded correction below supersedes that comparison:
those counts compared process-local physical Block IDs and therefore were not
valid cross-arm policy identities. Physical evidence also remained incomplete:
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

## Bounded offline correction after M1 review

The versioned correction separates all three cases requested by M1:

- A2 versus its internal Native-LRU reference;
- A2 versus the actual A0 Tier-aware queue selection; and
- windows whose Native state or legal candidates cannot be paired.

Physical Block IDs and process-local Native hashes are never compared across
arms. Instead, the correction represents a victim by its observed
`(program_id, chain_position)` memberships and treats explicitly hashless
blocks as no-content candidates. A forced window is pairable only when its
ordinal, required capacity, released programs, and semantic victim identities
are all available.

The final correctness pass reconstructs A0 only from the real
`PRESSURE_REQUEST_COMPLETED.last_selected_block_ids` event. It validates that
the selection excludes protected candidates and equals the frozen
`(eligibility_tier, native_lru_rank)` ordering. A missing or ambiguous selected
event is not replaced by a free-queue prefix. Likewise, A2 treats a block as
hashless only when the forced-window evidence explicitly records
`has_block_hash=false`; hashed-but-unverified and missing memberships remain
unknown.

The final implementation does not fall back from failed Native identity
validation to logical Retention Candidate membership. A2 uses only verified
decision-time content identities or explicit Native hashless evidence. A0 uses
only current Native snapshot membership, resetting a physical slot when its
content key changes and invalidating it on observed eviction.

Of 122 forced-release windows, 40 had complete actual A0/A2 comparison evidence
and 82 remained unpairable or identity-incomplete. Separately, 82 windows
permitted the within-A2 comparison against its internal Native-LRU reference.
Two windows diverged in both comparisons: the final forced-release window of
each `f4-draw-04` repeat. In those two windows, actual A0 equaled A2's internal
Native-LRU reference while A2's verified Cost-Aware selection differed.

The unresolved-reason report records overlapping evidence failures, including
74 missing/ambiguous A0 selected-block events, 20 window-contract mismatches,
4 incomplete A0 selected-content identities, and incomplete A2 legal or
victim identities. Two actual selected-block records also failed the frozen
Tier-aware reconstruction and are retained as unobservable rather than
reinterpreted.

The 656 ordinary-allocation A2 decisions have no
equivalent persisted A0 decision event and remain explicitly
`NO_EQUIVALENT_A0_DECISION_EVENT_NOT_COMPARABLE`, rather than making every
repeat pair globally unobservable.

The F4 request-level correction preserves the arm-level deltas exactly:

| Scenario | Repeat 1 | Repeat 2 |
|---|---:|---:|
| `f4-draw-04` | +560 | +560 |
| `f4-draw-05` | +96 | +96 |
| `f4-draw-06` | +288 | +288 |

There are 22 requests with nonzero paired recomputation deltas. Their `E`, `C`,
and derived FULL/PARTIAL/MISS states are preserved in
`f4-request-deltas.csv`. These request differences are reproducible, but the
existing evidence cannot establish a complete per-block physical
selection-to-recomputation causal chain. `f4-draw-04` now has a confirmed
A2-versus-A0 forced-window selection difference, but its full +560-token arm
difference cannot automatically be assigned to that decision. F4 draws 05 and
06 still have no confirmed comparable selection divergence. The archive also
cannot exclude ordinary-allocation fallback/order effects or Native
timing/state differences because A0 lacks matching ordinary decision evidence.

The answer to the bounded review question is therefore:

**`INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN`.**

The three F4 regressions remain valid arm-level measurements. F4 draw 04 also
contains a reproducible, verified Cost-Aware selection divergence, but strict
causal attribution of its token regression remains incomplete. Draws 05 and 06
remain unexplained arm-level regressions. The missing link is a comparable A0
ordinary-allocation decision record plus complete physical attribution for the
82 unresolved forced windows. No new Native execution was performed.

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
| Bounded offline correction | `d0f61829140b1b1fb15e59a2a0a02978d7740921c15eaf004a87156d4402265d` |
| Forced-window semantic comparisons | `d460902f6eb62992010bb6f31ffe783e30e68f00c86317f4dec0573cd4ced2b6` |
| F4 request-level deltas | `b9fe4fc8e4e0ed3fb6e6c80c1bae0ceada63eefb1373b34cf92350e9da9ccc0d` |
| Final corrected offline comparison | `e8364e49c627b34d1ea9f852df997120e9994a30a74ca4ba3055a42346184ab8` |
| Final forced-window comparisons | `daed4d909d13048288a2b71f025eac1f2cbad7145d798a4d48445a873633165b` |
| No-fallback offline comparison | `c1bb895835a16f10a58e8714fb40fa3fd241299f815f6604be02b1cc3cd16c85` |
| No-fallback forced-window comparisons | `6b66ae5eb79fc6a128adc36eb5d9f8f32bdc2c6470d384b2f1f11f9c0a4e0b11` |

