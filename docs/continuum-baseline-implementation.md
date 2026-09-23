# Continuum Baseline Implementation Record

## 1. Status

**Phase 1B Continuum-style baseline: IMPLEMENTED AND VALIDATED.**

This document is the current implementation record for the adapted Continuum-style baseline on vLLM 0.27.1. The detailed pre-closeout implementation log is preserved under:

`docs/archive/phase1b-continuum/continuum-baseline-implementation-pre-closeout.md`

Authority order remains:

1. `docs/baseline-freeze.md`
2. `docs/phase1b-continuum-implementation-decisions.md`
3. `docs/experiment-plan.md`
4. `docs/architecture.md`

The final runtime evidence is recorded in:

`docs/experiments/phase1b-continuum/final-report.md`

## 2. Implemented mechanism

The completed Phase 1B path is:

```text
program/session identity
    -> request/prefix/block observation
    -> server inter-request gap history
    -> external tool-duration history
    -> dynamic TTL estimation
    -> soft retention/protection
    -> lazy expiry / terminal cleanup
    -> protected-pressure release
    -> retention-aware victim eligibility
    -> program-level admission ordering
    -> native vLLM BlockPool cleanup
```

The implementation preserves the Phase 1A ownership boundary: vLLM remains authoritative for block allocation, reference counts, prefix-cache hash cleanup, scheduler bookkeeping, and physical block reuse. Project code contributes observation, retention state, scheduling policy, and victim eligibility/selection only.

## 3. Component status

| Component | Final status |
| --- | --- |
| Program / session identity | Implemented |
| Request / prefix / block identity boundaries | Implemented for the qualified text-only runtime profile |
| Server inter-request gap history | Implemented |
| External tool-duration history | Implemented and kept separate |
| Queue-delay history input | Implemented as a typed runtime input |
| Completed-program eta history | Implemented |
| Dynamic TTL estimator | Implemented |
| K=100 duration-history hierarchy | Implemented |
| PrefillReload provider | Implemented |
| Formal PrefillReload profile | Completed on the qualified Metal runtime |
| Soft retention manager | Implemented |
| Waiting-follow-up expiry exception | Implemented |
| Terminal cleanup | Implemented |
| Shared-block any-protected rule | Implemented |
| Deterministic protected-pressure release | Implemented |
| Retention-aware LRU selection | Implemented |
| Native LRU rank preservation | Implemented |
| NATIVE / SHADOW / CONTROLLED modes | Implemented |
| Program-level scheduler adapter | Implemented |
| Real vLLM 0.27.1 / Metal validation | PASS |
| Full regression suite | PASS |

## 4. Final runtime qualification

The final Phase 1B validation used:

- vLLM 0.27.1;
- vLLM-Metal source revision `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`;
- macOS Apple Silicon / Metal;
- APC enabled;
- paged KV enabled;
- block size 16;
- `Qwen/Qwen2.5-0.5B-Instruct`;
- model/tokenizer revision `7ae557604adf67be50417f59c2c2f167def9a775`.

The final validation artifact reports PASS for:

- program continuity;
- nonterminal retention;
- scheduler coordination at the native scheduler boundary;
- protected-pressure release;
- native cleanup;
- terminal cleanup;
- NATIVE / SHADOW / CONTROLLED mode boundaries.

See the final report and raw JSON artifacts for exact run identifiers and provenance.

## 5. Final PrefillReload profile

Formal reusable-prefix points:

| Reusable prefix tokens | Median MISS-HIT TTFT delta (s) |
| ---: | ---: |
| 16 | 0.009522290994937066 |
| 32 | 0.011798791994806379 |
| 128 | 0.04975464601011481 |
| 256 | 0.0887301250040764 |
| 512 | 0.17105704150890233 |

The representative Phase 1B runtime value remains:

```text
r = 256
PrefillReload(256) = 0.0887301250040764 s
```

## 6. Project adaptations

The following are project concretizations rather than claims of source-perfect Continuum reproduction:

- `queue_delay_window_size = 100`;
- startup `T_default` based on the representative PrefillReload profile point;
- protected fallback ordered by earliest retention deadline, entry native-LRU key, then stable logical identity;
- soft protection implemented outside native `ref_cnt`;
- narrow waiting/admission-order scheduler adaptation without running-request preemption.

The baseline should therefore be described as a **Continuum-style baseline adaptation**, not an exact source-level reproduction.

## 7. Known limitations

The following remain outside the qualified Phase 1B profile and are not closure blockers:

- explicit partial-prefix policy semantics beyond validated complete-block reuse;
- LoRA, multimodal, and prompt-embedding hash namespaces;
- cross-process or restart-persistent prefix identity;
- multi-GPU execution;
- custom CUDA / attention-kernel changes;
- a canonical CUDA evaluation adapter for later formal comparison.

Queue-delay samples are accepted through the typed runtime record defined by the Phase 1B contracts. Automatic backend-specific reconstruction of every eviction-to-return queue-delay sample is not part of the frozen Phase 1B closure requirement.

## 8. Evidence boundary

The final controlled validation demonstrates the project scheduler policy at the native scheduler boundary together with logical waiting-follow-up retention through the staged pressure phase. It should not be interpreted as a stronger claim that native request completion itself remained blocked until the project-side staged admission event.

This distinction does not affect the validated retention release, policy ordering, or native BlockPool cleanup evidence.

## 9. Closure

Phase 1B implementation work is complete. Further work belongs to Phase 2/3:

- baseline profiling and bottleneck identification;
- Cost-Aware eviction design and implementation;
- workload/benchmark development;
- canonical-backend formal evaluation.

No new Continuum mechanism should be added unless later evaluation reveals a correctness defect in the frozen baseline.
