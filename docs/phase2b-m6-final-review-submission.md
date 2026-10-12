# Phase 2B M6 Experimental Fidelity Repair — Final Review Submission

## Scope and binding

- Scope: `NON_HOLDOUT_FIDELITY_REPAIR`; no method experiment.
- Owner/reviewer: M6 / M1.
- Review commit: `ddb3e0fb8acf4ad30a6b1e288db64e9d1961c830`.
- Primary native run: `phase2b-fidelity-smoke-v3`.
- Run commit: `66f4317f7b6c6b8d06c7c5d95c35744b3feb5a52` (clean).
- Runtime: macOS arm64, vLLM `0.27.1`, vLLM-Metal `0.3.0`, MLX Metal GPU.
- vLLM-Metal source: `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb` (clean source checkout; imported module path verified).
- Model/tokenizer: `Qwen/Qwen2.5-0.5B-Instruct` at revision `7ae557604adf67be50417f59c2c2f167def9a775`.

## Result

The opt-in repair path executed seven native requests successfully with `peak_inflight = 3`. It recorded shared and distinct submitted token-prefix digests, request-scoped native APC hashes and cached-token counts, native queued/scheduled timestamps, frozen TTL input provenance, normal BlockPool hash cleanup, and subsequent APC state.

| Gate | M6 result | Evidence summary |
|---|---|---|
| `G-PREFIX-INPUT` | `PASS` | Shared content keys produced identical submitted prefix digests; the distinct key differed. |
| `G-PREFIX-NATIVE` | `PASS` | `shared-b:1` reused 256 native cached-prefix tokens with the same hash chain; distinct control hashes differed. |
| `G-INFLIGHT` | `PASS` | Three native request lifecycles were outstanding before completion. |
| `G-NATIVE-QUEUE` | `PASS` | Native queued and scheduler-admission timestamps were independently recorded. |
| `G-TTL-HISTORY` | `NOT_OBSERVABLE` | No eligible `EvictedRequestQueueDelayRecord` existed. Native queue duration remained separate and was not used as TTL history. |
| `G-PRESSURE` | `PASS` | Logical release event 45, native hashed evictions 47/49, and subsequent APC observations 86/93/100 are separately persisted. |
| `G-NEGATIVE` | `PASS` | Distinct content and ineligible-history controls did not false-pass. |
| `G-LEGACY` | `PASS` | Clean full repository regression: 1083 passed, 0 failed. |
| `G-PROVENANCE` | `PASS` | Git, config, trace, contract, runtime source, raw evidence, and archive hashes are bound. |

`G-TTL-HISTORY = NOT_OBSERVABLE` is the required technical limitation for this pinned smoke: native scheduler queue timing is observable, but it is not a semantically eligible Continuum evicted-request queue-history sample. No estimator or frozen history rule was changed to manufacture a PASS.

## Evidence handoff

- Archive: `artifacts/phase2b-m6-fidelity-evidence-ddb3e0f.tar.gz`
- Archive SHA-256: `5a8c93f0e8276e078f80275e1e553f60fe4ef0af37bb52e9313b8824841687b3`
- Size: 64 KiB.
- Manifest: `artifacts/phase2b-fidelity/handoff-manifest.json`.
- Manifest schema: `phase2b.fidelity_evidence_handoff.v1`.
- Primary final audit: `artifacts/phase2b-fidelity/phase2b-fidelity-smoke-v3/fidelity-audit-final.json`.
- Regression binding: `docs/phase2b-m6-legacy-regression-v2.json`.

The earlier v1/v2 runs and the earlier `66f4317` archive remain diagnostic evidence and are superseded by the v3 primary handoff; they were not deleted or overwritten.

## Change-impact boundary

- H1/H2 sealed artifacts, protocols, outcomes, and verdicts modified: **NO**.
- Continuum TTL, pressure-release, scheduler, or Cost-Aware algorithm modified: **NO**.
- Native BlockPool, hash table, refcount, queue ownership, or LRU order directly modified: **NO**.
- Challenger runtime policy or new formal campaign implemented: **NO**.
- This submission demonstrates repaired workload/runtime fidelity only; it is not scientific evidence that a Cost-Aware policy improves performance.

## Requested decision

M1 is requested to return one of the frozen review outcomes: `ACCEPT`, `CHANGES_REQUESTED`, or `BLOCKED`. In particular, M1 should decide whether the explicitly preserved `G-TTL-HISTORY = NOT_OBSERVABLE` limitation is acceptable for the scope of this non-holdout repair.
