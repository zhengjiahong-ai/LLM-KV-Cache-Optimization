# Phase 2D M6 Victim-Selection Headroom Investigation

## Scope and final result

This work is a bounded `NON_HOLDOUT_RESEARCH_PILOT` executed under the frozen Phase 2D E1–E4 authorization. It does not implement a Cost-Aware policy, modify native BlockPool/hash/refcount/LRU ownership, change the default Continuum release order, reopen H1/H2, or make a formal method-benefit claim.

The final evidence chain is:

| Stage | Gate result | Main observation |
|---|---|---|
| E1 | `OBSERVED_NO_SHARED_PROTECTED` | The accepted Phase 2C pressure runs were fully observable but exposed only one legal protected candidate per decision. |
| E2 / D2 | `PASS` | A native fixture produced two simultaneous protected logical entries sharing 8 real native blocks; each candidate had 12 blocks and 4 blocks of marginal relief. |
| E3 / D3 | `HEADROOM_OBSERVED` | Four valid paired comparisons produced a repeatable absolute difference of 64 actually recomputed prompt tokens. |
| E4 / D4 | `TRUE_OVERLAP_DEMONSTRATED` | Both bounded arms contained two real native scheduler-to-completion intervals with positive overlap before the pressure decision. |

The narrow scientific conclusion is that **local victim-selection headroom exists in the tested shared-prefix fixture**. This proves that two legal logical-release choices can lead to different native recomputation costs. It does not prove that the better choice is predictable online, that a Cost-Aware policy improves end-to-end performance, or that the effect generalizes beyond these fixtures.

## E1 — historical decision-time audit

The read-only E1 audit joined each `FORCED_RELEASE_DECISION` to the latest pre-decision native prefix snapshot in the same run and process. Both eligible Phase 2C decisions had complete logical-entry, physical-block, content-hash, free-queue and marginal-relief evidence, but each contained only one legal candidate. The result was therefore `OBSERVED_NO_SHARED_PROTECTED`, not an observability failure and not a runtime impossibility claim.

The detailed historical audit remains in `docs/phase2d-m6-shared-retention-feasibility.md` and `docs/phase2d-m6-shared-retention-feasibility.json`.

## E2 — shared-retention materialization

E2 used two programs with a 128-token shared root and distinct 64-token branches. The negative control used distinct roots. Each case was executed twice in an isolated process, for four successful runs.

In both shared-root repeats:

- two legal protected candidates were observed at the same decision;
- each candidate owned 12 observed native blocks;
- 8 blocks were shared at the physical/native-content level;
- each candidate had 4 `initially_reclaimable_block_ids`;
- every expected request had materialized-input and native APC evidence.

The distinct-root control observed zero shared protected blocks and 12 blocks of relief per candidate. Gate D2 therefore passed without forcing a victim.

## E3 — paired logical-release counterfactual

E3 used an opt-in diagnostic input that selects only the first logical retention entry released under pressure. The default path remains the frozen `_release_sort_key`; native physical eviction is still performed by the existing native LRU path. No block ID, hash entry, refcount, or native physical victim is directly forced.

Each arm independently rebuilt the same content, cache capacity, pressure target, candidate set, native free-queue shape and future requests. The paired evaluator rejected mismatched content digests, candidate geometry, marginal relief, pressure state, or free-queue shape.

The four valid paired results were:

| Evaluation target | Repeat | Release A recomputed tokens | Release B recomputed tokens | Δ, A − B |
|---|---:|---:|---:|---:|
| A | 1 | 65 | 1 | +64 |
| A | 2 | 65 | 1 | +64 |
| B | 1 | 1 | 65 | −64 |
| B | 2 | 1 | 65 | −64 |

`observed_recomputed_tokens` is calculated directly from native request evidence as `native_prompt_tokens - native_cached_prefix_tokens`. All four pairs were valid and the direction reversed with the designated future-return target, ruling out a fixed arm-label advantage in this fixture.

An initial D3 analysis record incorrectly included post-intervention `eligibility_tier` in the pre-decision comparison signature and therefore returned `COMPARABILITY_FAILED`. Raw runs were not changed or rerun. The corrected `gate-d3-v2.json` compares only intervention-independent native queue structure and is the canonical D3 record; the earlier record is retained as diagnostic provenance.

## E4 — true in-flight overlap applicability

E4 reused the existing opt-in submit/collect executor with `max_concurrent_requests=2`. The two first-turn shared-content requests were submitted at the same planned offset. Pressure remained a barrier and occurred only after both concurrent requests completed.

| Arm | Native scheduler-to-completion overlap | Observed peak in-flight | First logical release |
|---|---:|---:|---|
| Release A | 0.43336775 s | 2 | A |
| Release B | 0.352154292 s | 2 | B |

Both runs used distinct native request IDs within one native hash process, recorded scheduler admission and completion timestamps, observed normal hashed-cache eviction after the pressure decision, and retained native APC observations for both returning requests. Gate D4 therefore returned `TRUE_OVERLAP_DEMONSTRATED`.

E4 establishes that the shared-content/pressure fixture can coexist with real in-flight overlap. It is not an additional proof of E3's causal effect and is not a throughput or latency result.

## Answers to the research questions

1. **Did real shared protection exist?** Yes. E2 observed two protected logical entries sharing 8 real native blocks at one decision.
2. **Did candidates have different marginal relief?** No. In the E2/E3 shared fixture both candidates had equal relief of 4 blocks. The observed recomputation difference is therefore not explained by unequal released capacity.
3. **Was nonzero victim-selection headroom observed?** Yes. Four valid pairs showed an absolute 64-token difference in actual native recomputation.
4. **Is there enough decision-time information to predict the better choice?** Not yet demonstrated. The experiment controlled future return order to expose headroom; it did not establish an online observable predictor.
5. **Was true concurrency validated?** Yes, narrowly. E4 observed positive native scheduler-to-completion overlap in both bounded arms.
6. **Is further method research justified?** The evidence supports M4 formulating a separate preregistered predictability hypothesis. It does not authorize or validate a Cost-Aware runtime policy.

## Provenance and evidence hashes

- Repository execution head after E4 gate: `d682da868f11abb4ee2627da46277a7f503ba0aa`.
- vLLM-Metal source checkout: `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`.
- Model revision: `Qwen/Qwen2.5-0.5B-Instruct@7ae557604adf67be50417f59c2c2f167def9a775`.
- E1 machine result: `7a82bfc6ae6f902cdc815641102802f20b887f7a59c22e4086605ea336855a72`.
- E2 Gate D2: `960ef29abe97dd7c5b2d960a8385a60ba7b923933bdf66fcd3295fd7f7c39d4f`.
- E2 execution summary: `2fa6c282d37664da151857ab31d261e0f381ba2b381a25789d108b9f20efd5de`.
- E3 materialization manifest: `4d54a1fcb06ffebdf7c13aa771ee5802760a9cec1fd60cfe76213fffe389770a`.
- E3 Gate D3 v2: `a2972af479fa31c38bd1dcf74fadc27bfbe21d6462d5e701ddb75343b98dc989`.
- E3 execution summary: `098c4a2326dae7a548a0a3bb7363839075cb9d32851bbd769cf1dcc2c6b642c5`.
- E4 materialization manifest: `db0232e3db77797cfb5d9393d839769bece52597fefef185e3296dd4c8c5f9ac`.
- E4 Gate D4: `f5417655e6865da84c21ae30e1aa2e504993153c30fe6227b5afe7da7f7da460`.

The external evidence archive contains the materialization manifests, retained debug failures and all successful E2–E4 run directories, including raw `events.jsonl`, `run.json`, config, trace, replay and launcher logs. Its non-self-referential SHA-256 is reported alongside the archive in the PR handoff.

## Final boundaries

- H1/H2 remain closed and their sealed artifacts are unchanged.
- Continuum's default TTL and selection behavior is unchanged.
- The diagnostic intervention is opt-in and restricted to `phase2d_non_holdout_research_pilot`.
- Native BlockPool/hash/refcount/LRU ownership is unchanged.
- No Cost-Aware policy or formal campaign was implemented.
- D3 is local mechanism evidence; D4 is bounded concurrency applicability evidence.
- Any next-stage method or formal evaluation requires a new M4 hypothesis and M1 authorization.
