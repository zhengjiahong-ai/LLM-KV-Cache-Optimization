# Phase 2A Member 5 Spec — Forced-Release Workload and Benchmark Framework

## 1. Goal

Member 5 owns the reproducible workload/benchmark side of Phase 2A.

The first objective is **not** to build the final benchmark suite. It is to make the Phase 2A decision point happen reliably:

```text
multiple live protected Agent KV entries
    -> ordinary eligible/free KV is insufficient
    -> Continuum must perform protected forced release
    -> later turns make the release consequence observable
```

The workload must support fair replay across the Phase 2A decision references without embedding policy-specific logic.

Authoritative Phase 2A context:

- `docs/phase2-plan.md`
- `src/kvopt/profiling/forced_release.py`

## 2. Ownership boundary

Member 5 owns:

- deterministic program/session traces;
- prompt/prefix construction;
- program arrival schedule;
- tool-gap / follow-up schedule;
- controlled cache-pressure generation;
- benchmark/replay entry points;
- run configuration and trace manifests;
- workload-level reproducibility checks.

Member 5 does **not** own:

- Continuum forced-release policy logic;
- oracle/regret definitions;
- profiling feature semantics;
- Cost-Aware scoring;
- changes to `RetentionAwareSelectionCoordinator`;
- final performance analysis.

If the workload cannot be expressed through current public interfaces, report the missing interface to Member 1 instead of depending on private implementation state.

## 3. First-version workload constraints

The first Phase 2A workload should deliberately stay simpler than the final evaluation workload.

At the intended forced-release decision:

1. there must be at least **two protected, unexpired logical candidates**;
2. ordinary Tier-1/free supply must be insufficient for the requested allocation;
3. protected release must therefore be necessary;
4. each program should have at most **one protected logical entry** at that decision point;
5. candidate protected entries should use **disjoint physical cached blocks** in the first version;
6. later follow-up turns must be scheduled so the consequences of release can be observed;
7. the workload must not depend on partial-prefix semantics.

Constraints 4–5 are temporary Phase 2A simplifications. They keep the paper-level program victim rule, the project entry-level adaptation, and outcome attribution comparable without introducing shared-block or multi-entry ambiguity.

## 4. Trace manifest

Every generated trace must have a machine-readable manifest. The exact serialization format is Member 5's implementation choice, but the logical fields must include at least:

```text
trace_id
scenario_id
seed

runtime/model configuration reference
cache-pressure configuration reference

programs:
    program_id
    program_order
    planned_program_arrival_offset
    turns:
        turn_index
        prompt/prefix construction parameters
        expected reusable-prefix token target
        terminal / non-terminal
        next_tool_type
        planned_followup_gap
```

Important:

- `planned_program_arrival_offset` is a workload input, **not** the authoritative paper-heuristic arrival timestamp.
- For Phase 2A, the project's operationalization of paper-level `program arrival time` is the **observed server arrival time of the program's first request** collected during execution. This is a project execution convention for replay, not a claim that the paper explicitly defines the timestamp that way.
- Prefix/block IDs and actual block counts are runtime observations and must not be hard-coded into the trace manifest.

## 5. Minimum scenario family

The first framework should support a small controlled matrix rather than many ad-hoc cases.

### A. Homogeneous control

Purpose:

> establish a case where candidate release values are intentionally similar.

Keep approximately similar:

- reusable-prefix size;
- follow-up gap;
- tool type;
- reuse pattern.

This scenario should show whether measured regret remains small when there is little value heterogeneity.

### B. Return-time heterogeneity

Keep recomputation cost approximately similar while varying follow-up/tool-return timing.

Purpose:

> isolate whether different near-future reuse timing creates forced-release headroom.

Use at least two arrival-order permutations so that program arrival order is not permanently correlated with return value.

### C. Recomputation-cost heterogeneity

Keep follow-up timing approximately similar while varying reusable-prefix/prefill cost.

Purpose:

> isolate whether expensive-to-recompute protected state creates forced-release headroom.

Again use at least two arrival-order permutations so that “latest arrival” is sometimes aligned and sometimes misaligned with recomputation cost.

### Optional D. Combined heterogeneity

Only add after A–C work reliably.

Combine return-time and recomputation-cost heterogeneity to test the more realistic mixed case.

## 6. Pressure construction

The framework must create bounded, reproducible cache pressure.

Preferred behavior:

```text
build protected candidate set
    -> verify candidates are still protected
    -> submit deterministic pressure workload
    -> stop once the intended forced-release decision is observed
       or a configured safety ceiling is reached
```

Requirements:

- pressure generation must be deterministic from config/seed;
- use an explicit safety ceiling;
- do not rely on OOM as a pressure mechanism;
- cache budget / block override must be a run configuration, not hidden in code;
- pressure requests must not accidentally share the protected prefixes under test;
- benchmark output must report whether forced release was actually observed.

The existing Phase 1B validation pressure construction may be reused as a reference, but Phase 2A should extract a reusable benchmark path rather than expanding the old validation script indefinitely.

## 7. Replay and fairness

A single logical trace must be replayable under different Phase 2A decision references.

The trace generator must not inspect which forced-release policy is active.

Hold fixed across policy/replay comparisons:

- model and revision;
- tokenizer and revision;
- trace manifest;
- program arrival schedule;
- follow-up/tool-gap schedule;
- prompts/token construction;
- cache/memory budget;
- batching/generation parameters;
- pressure sequence;
- seed.

Any run-specific divergence caused by the runtime must be recorded rather than silently corrected by the workload.

## 8. Suggested repository shape

Member 5 may choose the exact internal decomposition, but prefer extending the existing project layout:

```text
src/kvopt/workload/
benchmarks/
configs/
tests/
```

A reasonable first structure is:

```text
src/kvopt/workload/phase2_forced_release.py
benchmarks/run_phase2_forced_release.py
configs/phase2/forced_release/
tests/test_phase2_forced_release_workload.py
```

Do not put the new benchmark into `scripts/spikes/` unless it is explicitly throwaway exploratory code. Phase 2A is now a project experiment path, not another Phase 1B spike.

## 9. Required benchmark output

Each run must produce or expose enough metadata for Member 6 to join profiling records back to the workload:

```text
run_id
trace_id
scenario_id
seed
git_sha
runtime/backend identity
hardware identity
model/tokenizer revisions
cache-pressure config
program_id -> observed first-request arrival timestamp
request/program mapping
actual request lifecycle timestamps
completion status
forced-release-observed flag
```

Member 5 owns producing the run/trace identity and execution metadata. Member 6 owns the profiling/result tables built from it.

## 10. First delivery

The first PR should contain:

1. deterministic trace/config model;
2. A–C scenario generation;
3. bounded pressure runner;
4. machine-readable trace/run manifest;
5. tests for deterministic trace reproduction;
6. a small smoke run showing:
   - at least two protected candidates;
   - forced release occurs;
   - the run terminates without deadlock/OOM;
   - later follow-up requests execute.

It does **not** need:

- final datasets;
- large parameter sweeps;
- final plots;
- Cost-Aware policy code;
- oracle analysis;
- paper-quality performance numbers.

## 11. Acceptance criteria

Member 5's Phase 2A framework is ready for Member 6 data collection when:

- [ ] the same config/seed produces the same logical trace;
- [ ] at least two protected, unexpired candidates exist at the intended decision;
- [ ] forced release occurs reliably without relying on OOM;
- [ ] first-version candidates are one-entry-per-program and physically disjoint;
- [ ] later follow-ups make reuse/recompute consequences observable;
- [ ] program/request identities and observed first-arrival timestamps are recorded;
- [ ] the workload is policy-agnostic;
- [ ] cache pressure and all important runtime inputs are explicit;
- [ ] no Cost-Aware assumptions are embedded in workload generation;
- [ ] tests cover deterministic generation and bounded pressure termination.

## 12. Escalation to Member 1

Stop and report an interface blocker rather than working around it if:

- actual server program-arrival time cannot be recorded;
- forced release cannot be identified without private state inspection;
- stable program/request identity cannot be propagated;
- pressure requires modifying baseline victim-selection behavior;
- M6 needs a decision-time fact that is unavailable through the approved observation boundary.
