# Phase 2C M6 Bounded Native Workload Pilot — Review Submission

## Scope and provenance

- Scope: `NON_HOLDOUT_NATIVE_PILOT`; not a formal method experiment.
- Owner/reviewer: M6 / M1.
- Clean execution commit: `9f8408e78ae1e645bfe61ff83f5413f0f5d3c06f`.
- vLLM-Metal source: `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`.
- Runtime: vLLM `0.27.1+cpu`, vLLM-Metal `0.3.0`, MLX `0.32.0`.
- Hardware: MacBook Pro `Mac17,9`, Apple M5 Pro, 24 GB.
- Model/tokenizer: `Qwen/Qwen2.5-0.5B-Instruct` revision `7ae557604adf67be50417f59c2c2f167def9a775`.

## Result

All 18 planned isolated runs executed successfully. All 18 evidence-driven run gates passed, covering every authorized topology twice. A successful process exit was not used as a gate result: each gate was recomputed from materialized-input and native runtime events.

| Topology | Repeats | Result | Native evidence |
|---|---:|---|---|
| `W-COLD` | 2 | `PASS` | First requests had no eligible prior prefix and were classified `NO_REUSE_ELIGIBLE_PREFIX`, not MISS. |
| `W-EXACT` | 2 | `PASS` | Identical materialized digests, 192-token native hash LCP, and 192 cached tokens. |
| `W-XPROGRAM` | 2 | `PASS` | Different logical programs shared the same real token prefix and native APC identity. |
| `W-ROOT-FORK` | 2 | `PASS` | Shared root and divergent branches produced the preregistered native block LCP. |
| `W-NESTED` | 2 | `PASS` | Strict prefix containment was visible in submitted content and native hash chains. |
| `W-TURN-GROW` | 2 | `PASS` | Later turns retained earlier reusable content and added new aligned segments. |
| `W-HOT-COLD` | 2 | `PASS` | Interleaved unrelated content preserved the declared hot-prefix reuse relation. |
| `W-PRESSURE` | 4 | `PASS` | Two paired no-pressure runs retained 384/384 tokens; two pressure runs retained 256/384 tokens after ordered native hash cleanup. |

Across the 40 evaluated request observations, the resulting classifications were 22 `NO_REUSE_ELIGIBLE_PREFIX`, 16 `FULL_HIT`, 2 `PARTIAL_HIT`, and 0 `MISS`. These are observed consequences, not target proportions or acceptance thresholds.

## Pressure evidence boundary

Both controlled-pressure repeats recorded the required event order in one native hash process:

```text
FORCED_RELEASE_DECISION
< VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED (hash_removed_after=true)
< pressure-target:2 VLLM_NATIVE_REQUEST_OBSERVATION
```

The paired no-pressure return was a 384-token `FULL_HIT`; the pressure return was a 256-of-384-token `PARTIAL_HIT`. This supports a layered same-process temporal sequence and physical-residency distinction. It does not claim content-level counterfactual ownership attribution.

## Repair relative to historical H1

The pilot demonstrates that the new schema can express real token-content identity independently of `program_id`, including cross-program sharing, forks, nesting, cumulative turn growth, hot/cold interleaving, and pressure-dependent physical residency. This directly addresses the Phase 2C historical audit findings that old H1 used program-derived fixed prefixes and lacked cross-program native sharing and cumulative context growth.

## Evidence and bindings

- Machine-readable result: `docs/phase2c-m6-native-pilot-result.json`.
- Materialization manifest: `artifacts/phase2c-native-pilot-materialized-v2/manifest.json`, SHA-256 `406f7a71fa678b8de3f82c6bdd4b4d4b1406c0b74067469bf85a8d99d7340581`.
- Execution summary: `artifacts/phase2c-native-pilot-runs-v1/execution-summary.json`, SHA-256 `a888d4e7fb055ea0a23070c4e4c49f9ed0c455ee68c30f2475e186aa3d547383`.
- Pilot report: `artifacts/phase2c-native-pilot-runs-v1/pilot-report.json`, SHA-256 `7a19715fff3e665395f5dd45dda5bf375f96b86c6f516c07b13c7409cbd0e3b0`.
- Evidence archive path, size, SHA-256, and entry count are recorded in the separate handoff manifest generated after packaging.

The archive retains raw `events.jsonl`, run/config/trace/replay records, launcher logs, materialized campaign inputs, frozen authorization/contract/cases, the gate implementation, and tests. Failed smoke attempts and superseded materialization v1 remain local diagnostic history; they are not presented as primary pilot evidence.

## Research boundary

- H1/H2 sealed artifacts modified: **NO**.
- Continuum TTL estimator, scheduler, or selection policy modified: **NO**.
- Native BlockPool, hash table, refcount, ownership, or LRU modified: **NO**.
- Cost-Aware policy implemented or evaluated: **NO**.
- Formal campaign or method-benefit claim: **NO**.
- `G-TTL-HISTORY` upgraded by this pilot: **NO**.

## Requested decision

M1 is requested to review the raw/native fidelity evidence and return `ACCEPT`, `CHANGES_REQUESTED`, or `BLOCKED`. If accepted, the evidence may be handed to M4 only to judge whether a future Cost-Aware Victim Selection study opportunity exists; it does not itself authorize a new policy or formal campaign.
