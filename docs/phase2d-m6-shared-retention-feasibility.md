# Phase 2D M6 Shared Retention & Marginal Relief Feasibility Audit

## Scope and conclusion

- Audit kind: read-only, non-holdout E1 feasibility audit.
- Baseline: `main` merge commit `d7bad3a`.
- Reused evidence: Phase 2C bounded native pilot; no new GPU run.
- Conclusion: **`OBSERVED_NO_SHARED_PROTECTED`**.

The two Phase 2C forced-release decisions can both be reconstructed with complete decision-time logical-entry, physical-block, native-content-hash, free-queue, and process identity. Each decision contains exactly one legal protected retention candidate. Therefore the inspected fixture contains no decision at which two protected logical entries own the same native physical block. This is an observed negative result for these fixtures, not a claim that the runtime cannot represent shared protection.

## Capability table

| Required information | Status | Evidence and boundary |
|---|---|---|
| Decision identity | `OBSERVABLE` | `run_id + FORCED_RELEASE_DECISION.event_index` uniquely identify a decision. Both inspected decisions occur at event 17 in different runs. |
| Logical retention entries | `OBSERVABLE` | `ForcedReleaseDecisionSnapshot.candidates` serializes every protected, non-ordinarily-expired entry supplied to the coordinator. |
| Protection state | `OBSERVABLE` | Candidate inclusion is derived from `entry.protected` at preparation time; ordinary expiry is separately recorded. |
| Entry → block mapping | `OBSERVABLE` | Candidate `program_id/prefix_id/block_ids` join to the latest matching pre-decision `VLLM_PREFIX_SNAPSHOT`. |
| Block content identity | `OBSERVABLE` | The matched snapshot records aligned `ordered_native_hashes` and `ordered_native_cache_keys`. Content identity is not treated as logical ownership. |
| Native free-queue position | `OBSERVABLE` | `original_free_queue` records every candidate block and its `native_lru_rank`. |
| Initially reclaimable blocks | `OBSERVABLE` | Each candidate persists `initially_reclaimable_block_ids`, computed before release by the frozen coordinator. |
| Native process identity | `OBSERVABLE` | The matched prefix snapshot records `native_hash_process_id`; joins are run-local and decision-local. |

The audit rejects a mapping if the latest candidate snapshot is missing required block/hash/process fields, its block sequence differs from the decision candidate, or a mapped physical block is evicted between the snapshot and decision. It never uses native `ref_cnt`, content-hash equality, or cross-decision block-slot equality as proof of multiple logical owners.

## E1 evidence summary

| Run | Decision event | Snapshot event | Process | Legal candidates | Blocks per candidate | Marginal relief | Shared protected blocks |
|---|---:|---:|---|---:|---:|---:|---:|
| `w-pressure-native-repeat-1` | 17 | 9 | `13028` | 1 | 24 | 24 | 0 |
| `w-pressure-native-repeat-2` | 17 | 9 | `13038` | 1 | 24 | 24 | 0 |

Aggregate results:

- Valid forced-release decisions: **2**.
- Legal retention candidates per decision: **1, 1**.
- Decisions with fully reconstructed owner mapping: **2**.
- Decisions with multiple protected owners of one physical block: **0**.
- Decisions that are not observable: **0**.
- Decisions with multiple candidates and differentiated marginal relief: **0**.

The representative candidate in each run owns 24 observed native blocks and has 24 `initially_reclaimable_block_ids`. Thus its frozen marginal relief is 24 blocks. This is newly obtained eviction eligibility, not proof that all 24 blocks were subsequently physically evicted. Because each decision has only one legal candidate, the evidence cannot compare candidate-specific relief or victim-selection headroom.

## Why Phase 2C sharing does not establish shared retention

Phase 2C demonstrated cross-program native APC sharing and other content topologies. Those sharing cases did not produce a forced-release decision while two distinct programs simultaneously retained protected logical entries. The pressure fixture produced real eviction and partial APC survival, but it used one target program and therefore exposed only one logical retention candidate.

Identical native hashes in separate request observations prove content identity and reuse eligibility. They do not prove that two distinct protected retention entries simultaneously owned the same physical block. The E1 conclusion is based only on decision-time candidates joined to their own physical block snapshots.

## Marginal relief interpretation

The audit uses the frozen definition:

```text
relief(entry) = |eligible_after_release - eligible_before_release|
              = len(initially_reclaimable_block_ids)
```

It does not use `block_count - initially_reclaimable_block_count` as relief. It also does not equate new eligibility with physical eviction. In the two observed decisions, `relief == block_count == 24`; there is no partial relief requiring a shared-owner or other-cause diagnosis.

## Minimal E2 fixture design — not executed

E2 is needed because E1 has complete observability but no shared-protected state. The smallest proposed native fixture is:

1. Submit non-terminal turn A for program A with a 256-token block-aligned shared prefix, then leave A waiting and protected.
2. Submit non-terminal turn B for program B with the exact same 256-token native prefix, verify real cross-program APC reuse, then leave B waiting and protected.
3. Before pressure, require two distinct retention keys in `planning_snapshots()` whose block mappings overlap in the same native process and have matching per-block native hashes.
4. Apply one bounded normal native allocation-pressure stage large enough to create a legal forced-release decision, without forcing a particular victim.
5. Require the decision event to contain both candidates and preserve their decision-time block mappings, native hashes/process, free-queue ranks, and `initially_reclaimable_block_ids`.

Controls and stop conditions:

- Negative control: program B uses a distinct real prefix and must not share protected physical blocks with A.
- Do not infer ownership from hash equality or native `ref_cnt`.
- Fail closed if either entry becomes unprotected before the decision, if physical block identity cannot be bound to one process and observation time, or if the decision contains fewer than two candidates.
- Do not specify the victim, modify the selection order, or compare policy benefit.
- Preserve `OBSERVED_NO_SHARED_PROTECTED`, `NOT_OBSERVABLE`, and failed executions rather than tuning until sharing appears.

Estimated authorized-run cost if M1 later approves E2 execution: one shared fixture and one negative control, two isolated repeats each, for **4 bounded runs**. No E2 run has been performed in this audit.

## Provenance

- Phase 2C execution commit: `9f8408e78ae1e645bfe61ff83f5413f0f5d3c06f` (clean).
- Phase 2C evidence archive SHA-256: `8d66d1ee84b8144bf1cbdf23a7fdc7fd4b1ed16cb89e929c9424060879b0e3be`.
- Repeat 1 raw events SHA-256: `b6c722c6fc5d08ae1851d9bedae3596bedb34bb5eb2ec0b2e971c038bc1c58ed`.
- Repeat 2 raw events SHA-256: `3342da4b3be71f0bf6ddcce9a0b7b008ce6a071eec6e3b67746a1ed721a6f9c8`.
- Phase 2C pilot report SHA-256: `7a19715fff3e665395f5dd45dda5bf375f96b86c6f516c07b13c7409cbd0e3b0`.
- Phase 2D machine-readable result: `docs/phase2d-m6-shared-retention-feasibility.json`.
- Read-only audit implementation: `src/kvopt/profiling/phase2d_shared_retention.py`.

## Authorization boundary and requested decision

- E2 fixture design: completed under conditional authorization.
- E2 native execution: **NOT PERFORMED / NOT AUTHORIZED**.
- E3 forced-victim replay: **NOT PERFORMED / NOT AUTHORIZED**.
- E4 concurrency pressure experiment: **NOT PERFORMED / NOT AUTHORIZED**.
- Cost-Aware policy and formal campaign: **NOT MODIFIED / NOT AUTHORIZED**.
- H1/H2 sealed artifacts and frozen Continuum/native cache behavior: unchanged.

M1 is requested to decide whether to authorize the four-run E2 bounded native fixture, request narrower C1/C2 observation changes, or stop the shared-retention research direction.
