# Phase 2 Research Status (M1 canonical status index)

Status: **ACTIVE — W1-B PR #73 under review; W1-C bounded pilot authorized, not yet accepted**  
As-of baseline: `main` @ `f95fa481ce7eb055089a9cd5da368860d33ef977` (PR #72 merged).  
Owner: M1. This document indexes decisions and evidence; it does **not** amend sealed artifacts or replace their final reports.

## How to read the evidence

- **Campaign delivered / code merged** does not imply **hypothesis supported** or **formal algorithm benefit demonstrated**.
- `CLOSED` means a stage's accepted scope has concluded, not that every research hypothesis passed.
- `UNDER_REVIEW` means its submission, numbers and gate are **not yet M1 accepted**.
- `AUTHORIZED` means an explicitly bounded operation may start; it does not imply measurements have been collected.
- Unit of inference matters: independent scenario draws or independently sampled tasks/session groups, **not** runtime repeats, turns or request rows.
- No source-generated Agent trace is the author's original paper-run serving trace unless independently established.

## Research objective and decision layers

The project studies **cost-aware KV-cache eviction / victim selection on real vLLM 0.27.1 with GPU APC**. Retention and scheduling are supporting/baseline mechanisms, not a replacement for the eviction research question.

Current experimental arms must be distinguished by decision layer:

| Arm | Entry forced release | Physical block victim selection |
| --- | --- | --- |
| A0 | Frozen Continuum-style deterministic baseline | Native LRU under existing eligibility |
| A1 | Cost-aware entry-level selection | Same block-level baseline as A0 |
| A2 | A0 entry-level release | Cost-aware block-level selector |

`A2` is **not** an A1+A2 combined policy. A1-versus-A0 differences cannot by themselves establish the independent value of A1's q/λ/pair-lookahead signals. **Sufficient-first + earliest-deadline** remains a required strong comparator for any future formal claim.

## Phase status ledger

| Phase / evidence | Status | What is supported / what is not |
| --- | --- | --- |
| Phase 0 / 1A | CLOSED | Backend/adapter validation; native BlockPool retains refcounts, hashes, free-queue and eviction bookkeeping |
| Phase 1B | CLOSED | Continuum-style baseline integrated and real-runtime validated; project adaptation is not asserted byte-for-byte equivalent to the paper |
| Phase 2A H1 | CLOSED — `DIAGNOSTIC_ONLY` | 29 independent paired-evaluable draws, below threshold 30; no rule promotion; Phase 2C later identified content-topology fidelity limitations |
| Phase 2A H2 | CLOSED | M1/M2/M3 measurements passed their gates; M4 failed; aggregate did not unlock B1 |
| Phase 2B / 2C | CLOSED | Native evidence/fidelity repair and a workload audit; historical H1 artifacts remain sealed |
| Phase 2E | CLOSED | Frozen Native LRU/Continuum measured comparability campaign; outcome is workload/measurement evidence, not cost-aware benefit |
| Phase 2G A1 | BOUNDED EVALUATION COMPLETED | Native evidence of some beneficial entry-release differences; prior Gate 2 decision analysis found 54/54 A1 selections reproduced by simple sufficient-first heuristic; independent cost-model signal unproven |
| Phase 2G A2 | INCONCLUSIVE | Bounded evaluation found 0 better / 3 worse / 33 tied in 36 draws; attribution and decision exposure limitations; neither proof of universal equivalence nor formal benefit |
| Phase 2 W0 — PR #71 | CLOSED / `CONDITIONAL_GO` | Public Continuum/SWE-bench source and converter path audited; paper-run per-request trajectories absent |
| Phase 2 W1-A — PR #72 | CLOSED / `CONDITIONAL_GO` | 10 frozen SWE-bench Verified Agent tasks acquired; reported 453 model / 271 tool calls; 1 submitted, 9 right-censored at step limit; local tokenization and wrapper timing have explicit provenance |
| Phase 2 W1-B — PR #73 | **UNDER REVIEW / CHANGES REQUESTED** | M6 reports 4 groups × A0/A1/A2 = 12 successful runs and A1−A0 aggregate recompute delta −3904 tokens; **not accepted** pending RC1–RC4 |
| Phase 2 W1-C | **BOUNDED PILOT AUTHORIZED** | Cross-repository stratified sampling design and S50/S100 feasibility pilot; not an approved 100-task acquisition or formal benefit evaluation |

### Current PR #73 review boundary

[PR #73](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/73), submitted HEAD `2145e6703992967d91e8ff49e5f90ff54143a9e3`, remains open and unmerged. M1 requested changes to:

1. RC1: causal replay's claimed completion-plus-tool-gap versus actual absolute-offset scheduling;
2. RC2: full policy-independent cross-arm config, frozen source and per-request token digest bindings;
3. RC3: event-count-only forced-release gate versus complete decision and downstream APC evidence;
4. RC4: narrowly justify the extra generated-token native-hash-chain block allowance.

The reported per-group A1−A0 deltas are **−1056, 0, −1616, −1232**; A2−A0 are **0 in all four groups**, with no reported A2/native-LRU victim-set divergence. These are **M6-reported, bounded, controlled-pressure smoke observations** (one repeat per arm/group), not formal treatment effects or author-workload reproduction. M1 has not independently rehashed the attached archive or recomputed the 12 raw runs. **Do not promote PR #73's submitted `PASS` to the canonical ledger before RC closure and explicit approval.**

### Real Agent workload limitations

W0's first ten sampled tasks all came from Astropy and are not a cross-project representative cohort. W1-A captured real model/tool interactions but 9/10 trajectories were right-censored by the author's configured 50-step limit. W1-B replays selected sparse turns with controlled concurrency/pressure; it does **not** replay the original W1-A cross-session serving arrival process. Local deterministic token IDs, native submitted input, native APC hash identity and physical KV residency remain distinct evidence tiers.

W1-C may **design** a roughly 100-task stratified sample, and is authorized only for a **bounded ~20-task S50/S100 feasibility pilot** subject to resource/context checks. Full acquisition and any formal A0/A1/A2/Sufficient-first campaign require a separate M1 decision.

## Measurement and interpretation rules

For requests with complete native hash/APC evidence, let `N` = native prompt tokens, `E` = reusable eligible native-prefix tokens, `C` = native cached-prefix tokens. Enforce `0 ≤ C ≤ E ≤ N` and report separately:

- `R = E - C`: eligible-prefix recomputation;
- `W = N - C`: actual prefill work;
- `S = N - E`: genuinely new suffix; `W = R + S`.

Logical release, physical hashed eviction, subsequent APC hit/miss and request-level recomputation are different claims requiring different observations. If any required evidence is missing, preserve the missingness and fail closed. A short smoke is not an independently powered statistical campaign.

## Authority, ownership and next steps

- **M1**: phase grants, canonical status, architecture/fairness boundary, integration and final experimental verdicts.
- **M4**: A1/A2 decision opportunity, theory, Sufficient-first comparison and claim interpretation; not default workload acquisition owner.
- **M6**: current W0/W1 Agent-source acquisition, conversion, replay, native measurement and evidence statistics.
- **M5**: shared workload/runner substrate when a concrete interface gap requires work; not the owner of M6's W1 data acquisition.
- **M2/M3**: background/source-mechanism review and frozen baseline support, respectively.

Next gates: resolve PR #73 RC1–RC4 and review raw evidence; independently complete W1-C stratification and S50/S100 feasibility; only then propose a pre-registered, adequately sized A0/A1/A2/**Sufficient-first** campaign. No parameter retuning based on preliminary A1 performance, no A3/B1 authorization.

## Provenance and reading order

Read this file for **current state**, then use the [experiment navigation index](experiments/README.md) and sealed/final records for exact results:

- [Project README](../README.md) and [experimental framing](experiment-plan.md)
- [Phase 2A H1/H2 closeout](phase2a-h1-h2-closeout-verdict-record.md)
- [Phase 2E measured campaign](phase2e-m6-measured-campaign-report.md)
- [A1 evidence](experiments/phase2g-a1/README.md), [A2 bounded evaluation](experiments/phase2g-a2-bounded-value-evaluation.md), [A2 research judgment](experiments/phase2g-a2-research-judgment.md)
- [W0 source audit](continuum-workload-source-audit.md) and [conversion feasibility](continuum-workload-conversion-feasibility.md)
- [W0 PR #71](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/71), [W1-A PR #72](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/72), [W1-B PR #73 pending](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/73)

Historical plans, negative results, old approvals and sealed hashes are **not modified by this index**. When phase status changes, update this ledger in a new reviewable commit and link the M1-approved verdict.
