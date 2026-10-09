# Continuum Baseline Implementation Record

## Status

**Phase 1B implementation, real-runtime validation, and integration to `main` are COMPLETE. Phase 1B is CLOSED.**

This document is the current implementation index for the Continuum-style baseline adapted to vLLM 0.27.1. It intentionally stays concise. Historical feasibility, observation-spike, and implementation-decision records are preserved under `docs/archive/phase1b-continuum/`.

The project does **not** claim an exact source-level reproduction of Continuum.

## Implemented baseline

The validated baseline contains:

```text
explicit program/session identity
    -> server inter-request-gap history
    -> server-side tool-call parsing (next_tool_type fallback)
    -> dynamic TTL estimation
    -> soft retention/protection
    -> lazy expiry
    -> deterministic protected-pressure release
    -> narrow program-level admission ordering
    -> retention-aware victim eligibility
    -> native vLLM BlockPool eviction/cleanup
```

Native vLLM remains authoritative for allocation, `ref_cnt`, APC hash metadata, physical block reuse, and scheduler bookkeeping.

## Runtime components

| Component | Implementation |
| --- | --- |
| Identity / provenance | `src/kvopt/continuum/types.py` |
| Lifecycle events | `src/kvopt/continuum/events.py` |
| Histories | `src/kvopt/continuum/history.py` |
| Dynamic TTL | `src/kvopt/continuum/ttl.py` |
| Server-side tool-call parsing | `src/kvopt/continuum/tool_call.py` |
| PrefillReload provider | `src/kvopt/continuum/prefill_profile.py` |
| Retention manager | `src/kvopt/continuum/retention.py` |
| Pressure coordinator | `src/kvopt/continuum/pressure.py` |
| Runtime coordinator | `src/kvopt/continuum/runtime.py` |
| Scheduler policy | `src/kvopt/continuum/scheduler.py` |
| Composition | `src/kvopt/continuum/composition.py` |
| vLLM observation | `src/kvopt/runtime/vllm/continuum_observation.py` |
| vLLM tool-call observation adapter | `src/kvopt/runtime/vllm/tool_call_observation.py` |
| vLLM retention integration | `src/kvopt/runtime/vllm/retention_integration.py` |
| Metal PrefillReload adapter | `src/kvopt/runtime/vllm/prefill_profile.py` |

The Phase 1A `VLLMEvictionBridge` and native BlockPool cleanup path remain the common lower-level victim-selection boundary.

## Frozen implementation semantics

The baseline follows `docs/baseline-freeze.md`. Detailed implementation decisions made during Phase 1B are preserved for provenance in:

```text
docs/archive/phase1b-continuum/phase1b-continuum-implementation-decisions.md
```

Important project adaptations include:

- `duration_history_threshold = 100` for the Continuum duration-history reliability threshold;
- `queue_delay_window_size = 100` as a project adaptation for the sliding queue-delay history;
- pressure release ordered by earliest retention deadline, then entry native-LRU key, then stable entry identity;
- soft protection rather than mutation of native vLLM reference counts.

The canonical formal profile point used for startup concretization is:

```text
r = 256 reusable-prefix tokens
PrefillReload(256) = 0.0887301250040764 seconds
T_default = 0.0 seconds
```

Per-request TTL estimation continues to use the request-specific profiled/interpolated `PrefillReload(r)` where required by the estimator.

## Validation

Final real-runtime evidence is recorded in:

```text
docs/experiments/phase1b-continuum/final-report.md
```

Qualified validation profile:

- vLLM 0.27.1;
- pinned vLLM-Metal revision `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`;
- macOS Apple Silicon / Metal;
- APC enabled;
- paged KV enabled;
- block size 16;
- `Qwen/Qwen2.5-0.5B-Instruct`.

Final validation recorded PASS for:

- program continuity;
- nonterminal retention;
- scheduler coordination at the controlled scheduler boundary;
- protected-pressure release;
- native BlockPool cleanup;
- terminal cleanup;
- NATIVE / SHADOW / CONTROLLED mode boundaries.

The formal PrefillReload artifact and validation artifact are preserved byte-for-byte under `docs/experiments/phase1b-continuum/artifacts/`.

## Evidence interpretation boundary

The controlled scheduler validation demonstrates Continuum policy ordering on real native `Request` objects and logical waiting-follow-up retention through the staged pressure phase. It does **not** claim that native request completion itself remained blocked until the staged logical admission event.

## Known limitations

- This is a Continuum-style adaptation, not an exact source-level reproduction.
- The source scheduler's preemption victim ordering is intentionally not
  reproduced: the frozen Phase 1B scope (`docs/baseline-freeze.md` §9)
  excludes it, and its primary effect (protected entries surviving memory
  pressure) is already covered by deterministic pressure release. Full-system
  experiments must not attribute the missing preemption layer to eviction.
- The server-side tool-call parser (scope amendment,
  `feature/continuum-toolcall-preemption`) is covered by unit tests with fake
  vLLM module boundaries; it has not yet been real-runtime validated on the
  qualified Metal profile and must be before formal comparative experiments.
- Partial-prefix policy semantics are not a dependency of the validated first-version workload and remain outside the closed Phase 1B claim.
- LoRA, multimodal, and prompt-embedding cache namespaces were not qualified by the Phase 1B text-only validation profile.
- Metal is the qualified Phase 1B correctness/integration backend; final comparative performance experiments may qualify another common backend, but must not rewrite Continuum core semantics.
- Hardware/model-specific PrefillReload profiles must be regenerated or separately qualified for a different formal evaluation environment.

## Historical records

Historical Phase 1B process documents are retained under:

```text
docs/archive/phase1b-continuum/
```

They are provenance records, not current project-status documents.
