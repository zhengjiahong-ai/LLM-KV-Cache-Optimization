# M5 Phase 2 First-Stage Status

This status is intentionally limited to the experimental substrate owned by
M5. Synthetic smoke evidence verifies infrastructure plumbing only; it is not
real vLLM performance evidence.

## Checklist

| Requirement | Status | Evidence or boundary |
|---|---|---|
| Unified Phase 2 runner | Complete | `benchmarks/run_phase2.py` and `run_phase2(...)` |
| Deterministic workload/trace replay | Complete | `src/kvopt/workload/phase2.py`, round-trip tests |
| Multi-program/multi-turn workload | Complete | `configs/phase2/smoke-trace.json` |
| Configurable bounded cache pressure | Complete as substrate | `PressureStage`, `safety_ceiling`, forced-release stop condition |
| Automatic run provenance | Complete | `run.json`: SHA, config/trace hashes, model, tokenizer, platform, status |
| Stable raw event artifact | Complete | append-only `events.jsonl`, monotonic `event_index`, clock domain |
| Current lifecycle/tool/prefix/KV/retention/forced-release facts | Partial | Existing approved contracts are serialized; backend-specific facts remain unavailable when not exposed |
| Forced-release candidate and selected release reconstruction | Complete | `FORCED_RELEASE_DECISION` includes queue, candidates, expiry, and selected releases |
| Hardware observation boundary | Complete as interface | `HardwareObservationProvider`; missing provider is recorded as unavailable |
| No fabricated unavailable data | Complete | Manifest explicitly reports unavailable native/hardware facts |
| Observation neutrality | Complete for substrate contracts | Synthetic comparison uses an event sink and `NullExperimentEventSink`; real backend still requires validation |
| M6 can collect ordinary raw data without runtime patching | Partial | Approved lifecycle/forced-release path is ready; listed missing backend facts require M1 interface decisions |

## M1 interface requests

The following facts are not inferred or collected through private vLLM state:

- stable APC hit/miss or prefix reuse observation;
- recomputed/prefill token work and its clock domain;
- first-token timestamp and generated token count;
- native cleanup completion and physical eviction evidence;
- approved scheduler waiting/admission/preemption timestamps and ordering;
- backend-specific hardware capabilities and optional measurements.

For each item, M1 must decide whether to add a public observation boundary to
the pinned backend integration. Until then, the runner records the fact as
unavailable or accepts backend-supplied events only when directly observed.

## Remaining first-stage integration work

The synthetic backend proves artifact and safety behavior. The first stage is
not fully closed until a deployment-owned vLLM backend is exercised with the
same runner and supplies the approved observations above. No research claim,
oracle, regret, or Cost-Aware score belongs in this M5 substrate.
