# Phase 2B M6 Experimental Fidelity Repair — Final Review Submission

## Scope and binding

- Scope: `NON_HOLDOUT_FIDELITY_REPAIR`; no method experiment.
- Owner/reviewer: M6 / M1.
- Gate-fix commit: `1b7b242717197fcd3273285489b5503c4867a154`.
- Evidence-packaging commit: `e363dbd9395332c990b081026bf122bcbc658e27`.
- Primary native run: `phase2b-fidelity-smoke-v3`.
- Run commit: `66f4317f7b6c6b8d06c7c5d95c35744b3feb5a52` (clean).
- Runtime: macOS arm64, vLLM `0.27.1`, vLLM-Metal `0.3.0`, MLX Metal GPU.
- vLLM-Metal source: `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb` (clean source checkout; imported module path verified).
- Model/tokenizer: `Qwen/Qwen2.5-0.5B-Instruct` at revision `7ae557604adf67be50417f59c2c2f167def9a775`.

## Result

The opt-in repair path executed seven native requests successfully with `peak_inflight = 3`. It recorded shared and distinct submitted token-prefix digests, request-scoped native APC hashes and cached-token counts, native queued/scheduled timestamps, frozen TTL input provenance, normal BlockPool hash cleanup, and subsequent APC state.

| Gate | M6 result | Evidence summary |
|---|---|---|
| `G-PREFIX-INPUT` | `PASS` | Shared content keys produced identical submitted prefix digests; every distinct key has a distinct materialized digest. Different keys sharing a digest now fail closed. |
| `G-PREFIX-NATIVE` | `PASS` | `shared-b:1` reused 256 native cached-prefix tokens with the same hash chain; distinct control hashes differed. |
| `G-INFLIGHT` | `PASS` | Three native request lifecycles were outstanding before completion. |
| `G-NATIVE-QUEUE` | `PASS` | Native queued and scheduler-admission timestamps were independently recorded. |
| `G-TTL-HISTORY` | `NOT_OBSERVABLE` | Observed eta history and eligible pre-decision `EvictedRequestQueueDelayRecord` history were not both available. Native queue duration remained separate. |
| `G-PRESSURE` | `PASS` | Same-run/process evidence establishes `release 45 < native hashed evictions 47..85 < subsequent APC 86/93/100`. This is layered temporal evidence, not content-level counterfactual attribution. |
| `G-NEGATIVE` | `PASS` | Distinct content and ineligible-history controls did not false-pass. |
| `G-LEGACY` | `PASS` | Clean full repository regression: 1083 passed, 0 failed. |
| `G-PROVENANCE` | `PASS` | Git, config, trace, contract, runtime source, raw evidence, and archive hashes are bound. |

`G-TTL-HISTORY = NOT_OBSERVABLE` is the required technical limitation for this pinned smoke: native scheduler queue timing is observable, but it is not a semantically eligible Continuum evicted-request queue-history sample. The finalizer now reports observed eta and eligible queue history separately and requires both to precede the decision before PASS. No estimator or frozen history rule was changed to manufacture a PASS.

## Requested-change resolution

- RC1: `G-PREFIX-INPUT` now checks within-key stability and cross-key digest separation directly. A different-key/same-digest negative control is included.
- RC2: `G-PRESSURE` now joins evidence by run and native hash process and requires strict event order. Out-of-order evidence is covered by a negative control. The reported attribution scope is `layered_temporal_sequence_only`.
- RC3: the archive includes raw events, run/config/trace inputs, final audit, gate implementation, targeted tests, regression record, hashes, and a handoff manifest. Raw evidence remains bound to `66f4317`; audit recalculation is separately bound to `e363dbd`.

## Evidence handoff

- Archive: `artifacts/phase2b-m6-fidelity-evidence-e363dbd.tar.gz`
- Archive SHA-256: `298de0d4e6424bf41afa4b346610049cb44be55254d83b19499f27172ed002bf`
- Size: 76 KiB; 33 archive entries.
- Manifest: `artifacts/phase2b-fidelity/handoff-manifest.json`.
- Manifest schema: `phase2b.fidelity_evidence_handoff.v1`.
- Primary final audit: `artifacts/phase2b-fidelity/phase2b-fidelity-smoke-v3/fidelity-audit-final.json`.
- Final audit SHA-256: `9c9effa806561a0ba0cb43ef016c49b32cacd2789fa666baa7f34bfd16d5f1a4`.
- Raw events SHA-256: `c40bbae6c4fac623f405451ef776323869836c7be4e56e0f689f5a37a16bc5e7`.
- Regression binding: `docs/phase2b-m6-legacy-regression-v3.json` (`1085 passed`, `0 failed`).
- External reviewer-accessible archive URL: pending upload; it must resolve to the exact archive hash above.

The earlier v1/v2 runs and the earlier `66f4317` archive remain diagnostic evidence and are superseded by the v3 primary handoff; they were not deleted or overwritten.

## Change-impact boundary

- H1/H2 sealed artifacts, protocols, outcomes, and verdicts modified: **NO**.
- Continuum TTL, pressure-release, scheduler, or Cost-Aware algorithm modified: **NO**.
- Native BlockPool, hash table, refcount, queue ownership, or LRU order directly modified: **NO**.
- Challenger runtime policy or new formal campaign implemented: **NO**.
- This submission demonstrates repaired workload/runtime fidelity only; it is not scientific evidence that a Cost-Aware policy improves performance.

## Requested decision

M1 is requested to return one of the frozen review outcomes: `ACCEPT`, `CHANGES_REQUESTED`, or `BLOCKED`. In particular, M1 should decide whether the explicitly preserved `G-TTL-HISTORY = NOT_OBSERVABLE` limitation is acceptable for the scope of this non-holdout repair.
