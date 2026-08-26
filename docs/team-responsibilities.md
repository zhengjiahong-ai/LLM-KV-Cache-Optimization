# Team Responsibilities

This document defines the ownership, deliverables, boundaries, dependencies, and acceptance criteria for the seven project members.

The goal is not to isolate everyone into independent silos. Each member owns one primary area, but all code must integrate through the public interfaces under `src/kvopt`, and all experimental claims must be reproducible by the team.

## Shared rules

1. `main` must remain runnable. All code changes go through feature branches and pull requests.
2. Every technical task must have a concrete deliverable: code, documentation, dataset/workload artifact, benchmark script, figure, or presentation material.
3. Do not modify another member's module internals without discussion. Prefer public interfaces and small integration PRs.
4. Each owner is responsible for tests for their own module.
5. Before final evaluation, all members should understand the overall pipeline well enough to answer questions about how their own component interacts with the rest of the system.
6. Q&A ownership follows module ownership: questions about a component should be answered first by the corresponding owner.

---

## Member 1 — Architecture, Scheduler, Integration, Project Management

### Primary goal

Own the overall system skeleton and keep all modules compatible as the repository evolves from the current deterministic simulator toward a real LLM inference backend.

### Main responsibilities

- Maintain the overall architecture and public interfaces.
- Own the scheduler-side request lifecycle and scheduler/KV-cache interaction.
- Define and maintain interfaces between:
  - scheduler;
  - KV-cache manager;
  - eviction policies;
  - workload/benchmark code;
  - metrics/evaluation code;
  - future real inference backend.
- Integrate PRs from Members 3, 4, 5, and 6.
- Resolve cross-module design conflicts.
- Maintain project-level configuration conventions and repository structure.
- Track project milestones and make sure the project scope remains feasible.
- Lead the transition from simulator-only validation to the selected real inference framework once that framework is decided.

### Primary files / directories

- `src/kvopt/scheduler/`
- integration-facing parts of `src/kvopt/kv_cache/`
- integration-facing parts of `src/kvopt/runtime/`
- `configs/`
- `docs/architecture.md`
- `docs/development.md`

### Expected deliverables

- Stable scheduler and request lifecycle API.
- Stable policy/manager/backend integration interfaces.
- End-to-end runnable pipeline after each major phase.
- Architecture updates when the project moves to a real backend.
- Integration PRs and release-ready main branch.

### Acceptance criteria

- Baseline and optimized policies can be switched without modifying scheduler internals.
- Benchmark and evaluation code can drive the same runtime through stable interfaces.
- The repository remains runnable after merged changes.
- Cross-module assumptions are documented instead of hidden in implementation details.

### Q&A ownership

- Overall architecture.
- Project scope.
- Scheduler design.
- Why modules are separated as they are.
- Integration decisions and system limitations.

---

## Member 2 — Background, Related Work, Motivation

### Primary goal

Build the technical rationale for the project: what KV-cache management problem is being studied, how existing systems address it, and why the chosen optimization is worth evaluating.

### Main responsibilities

- Study KV cache in LLM inference, including prefill/decode behavior and memory growth.
- Study PagedAttention / paged KV-cache management and relevant baseline policies.
- Identify prior work related to:
  - KV-cache allocation;
  - eviction;
  - preemption;
  - recomputation;
  - workload-aware cache management;
  - relevant serving-system design.
- Summarize the limitations of selected baselines.
- Maintain the project's motivation and related-work notes.
- Provide concise background material to Member 7 for slides.
- Verify that terminology used in slides and reports is technically correct.

### Primary files / directories

- documentation under `docs/`
- future `docs/related-work.md` or equivalent notes

### Expected deliverables

- A structured related-work summary.
- A clear project motivation: problem -> limitation -> optimization opportunity.
- Definitions of important terms used consistently by the team.
- References and comparison notes for the final presentation/report.

### Acceptance criteria

- The team can explain why KV-cache management matters for LLM inference.
- The selected baselines are justified by prior systems or common practice.
- The proposed optimization is motivated by an identifiable limitation rather than arbitrary parameter tuning.

### Q&A ownership

- KV-cache background.
- Existing systems and prior work.
- Why particular baselines were chosen.
- Motivation for the research question.

---

## Member 3 — Baseline KV-Cache Policy Implementation

### Primary goal

Implement and validate the baseline KV-cache management policies used as the experimental comparison point.

### Main responsibilities

- Implement the agreed baseline policies through the shared `EvictionPolicy` interface.
- Likely candidates include FIFO, LRU, or another simple policy selected after literature review.
- Keep baseline behavior deterministic where possible.
- Add unit tests for policy behavior and edge cases.
- Document baseline semantics precisely.
- Work with Member 1 on integration with the cache manager/runtime.
- Work with Member 6 to ensure baseline metrics are observable.

### Primary files / directories

- `src/kvopt/policies/`
- baseline-specific tests under `tests/`

### Expected deliverables

- Tested baseline policy implementation(s).
- Documentation of policy rules and tie-breaking behavior.
- Reproducible baseline runs through the common benchmark interface.

### Acceptance criteria

- Baseline policies conform to the public policy interface.
- Tests cover eviction order and capacity edge cases.
- Baseline code does not contain optimization-specific logic.
- Baseline and optimized policies can be compared under identical workloads and memory budgets.

### Q&A ownership

- Baseline algorithm details.
- Baseline implementation choices.
- Correctness and edge cases of baseline behavior.

---

## Member 4 — Optimization Design and Implementation

### Primary goal

Own the project's main technical contribution: identify a concrete weakness in the baseline and implement an optimization that can be experimentally tested.

### Main responsibilities

- Analyze baseline behavior together with Members 1, 3, and 6.
- Define the optimization objective and design rationale.
- Propose the optimized KV-cache management policy.
- Implement the method through the same policy/runtime interfaces used by baselines.
- Keep the method configurable so ablation is possible.
- Add correctness tests and deterministic decision tests.
- Document algorithm inputs, scoring logic, complexity, and expected trade-offs.
- Avoid changing unrelated runtime components solely to favor the optimized method.

### Primary files / directories

- `src/kvopt/policies/`
- optimization-specific tests under `tests/`
- method-related configuration under `configs/`
- method design notes under `docs/`

### Expected deliverables

- A clearly specified optimization algorithm.
- Working implementation.
- Tests and configuration knobs required for ablation.
- A concise explanation of why the method should improve the target metric.

### Acceptance criteria

- The method is more than parameter tuning of the baseline.
- It runs under the same runtime and workload interface as the baselines.
- Its additional policy-decision overhead can be measured.
- Important parameters can be disabled or varied for ablation.

### Q&A ownership

- What the proposed method is.
- Why it should work.
- Algorithm and implementation details.
- Complexity and trade-offs.
- Failure cases of the proposed method.

---

## Member 5 — Dataset, Workload, Benchmark Framework

### Primary goal

Create reproducible input traces and benchmark tooling so that all policies are evaluated on the same requests under controlled conditions.

### Main responsibilities

- Research and select suitable public datasets or request traces after the experimental setting is fixed.
- Define dataset preprocessing and sampling rules.
- Convert dataset records into the common `Request`/workload representation.
- Build synthetic workloads when needed for controlled experiments.
- Construct workload categories such as:
  - short-request dominated;
  - long-request dominated;
  - mixed-length;
  - different arrival rates / burstiness if relevant.
- Maintain benchmark scripts and workload configuration.
- Ensure the exact same workload trace can be replayed across different policies.
- Record dataset source, preprocessing, sampling seed, and trace statistics.
- Do not commit large raw datasets or model weights into Git.

### Primary files / directories

- `src/kvopt/workload/`
- `benchmarks/`
- workload-related `configs/`
- future lightweight metadata/manifests under `data/` if needed, while raw datasets remain ignored

### Expected deliverables

- Dataset selection rationale.
- Reproducible preprocessing scripts.
- Workload generator / trace loader.
- Benchmark entry point.
- Workload statistics such as request count and prompt/output-length distributions.

### Acceptance criteria

- A workload can be reproduced from configuration and seed.
- All compared policies receive the same request sequence.
- Dataset transformation is documented.
- Synthetic and real workloads are clearly distinguished.

### Q&A ownership

- Dataset choice.
- Workload construction.
- Request-length distributions.
- Benchmark trace fairness and reproducibility.

---

## Member 6 — Evaluation, Visualization, Profiling, and Analysis

### Primary goal

Own the complete experimental evaluation and determine whether the proposed optimization actually improves the intended behavior under fair conditions.

### Main responsibilities

- Define the final evaluation protocol with Members 1, 4, and 5.
- Run baseline and optimized methods under identical configurations.
- Collect and validate metrics.
- Perform repeated runs where needed.
- Create final figures and tables.
- Profile the system to identify where time and memory are spent.
- Analyze why the method improves, regresses, or has no effect under different workloads.
- Measure optimization overhead.
- Maintain experiment result organization and reproducibility notes.
- Report negative results and failure cases instead of hiding them.

### Target metrics

Depending on the final backend, likely metrics include:

- throughput;
- TTFT;
- TPOT;
- end-to-end latency;
- KV-cache utilization;
- number of evictions;
- recomputation / preemption overhead;
- policy-decision overhead;
- GPU memory usage;
- GPU utilization where meaningful.

### Primary files / directories

- `src/kvopt/metrics/`
- evaluation-related code under `benchmarks/`
- `results/`
- profiling scripts/artifacts outside Git when large
- `docs/experiment-plan.md`

### Expected deliverables

- Final experimental matrix.
- Reproducible result files.
- Publication/presentation-ready plots and tables.
- Profiling evidence explaining the observed behavior.
- Written conclusions and limitations for each major experiment.

### Acceptance criteria

- Baseline and proposed method use the same model, workload trace, memory budget, and relevant runtime configuration.
- Plots are generated from stored result data, not manually edited values.
- Performance claims can be traced back to reproducible runs.
- Both improvement and overhead are reported.

### Q&A ownership

- Experimental setup.
- Metric definitions.
- Fairness of comparisons.
- Why a result changed.
- Statistical/repeatability questions.
- Profiling and bottleneck interpretation.

---

## Member 7 — Slides and Main Presentation

### Primary goal

Turn the technical work of Members 1-6 into one coherent presentation and serve as the primary presenter.

### Main responsibilities

- Own the final slide deck and presentation structure.
- Collect technical material, figures, and conclusions from Members 1-6.
- Turn raw technical material into a coherent story:
  1. problem;
  2. background;
  3. baseline;
  4. observed limitation;
  5. proposed method;
  6. implementation;
  7. evaluation;
  8. analysis and limitations;
  9. conclusion.
- Keep terminology and figures consistent across slides.
- Prepare speaker notes and rehearse the complete talk.
- Control presentation timing.
- Organize at least one internal rehearsal before the final presentation.
- Maintain a list of likely questions and route technical questions to the corresponding module owner during Q&A.

### Important boundary

Member 7 is responsible for presentation quality, not for inventing technical content or experimental conclusions. Members 1-6 must provide accurate, slide-ready material for the sections they own.

### Expected deliverables

- Final slide deck.
- Presentation script / speaker notes.
- Rehearsal-ready version before the deadline.
- Q&A question list organized by module owner.

### Acceptance criteria

- The full presentation fits within the required time.
- Every major performance claim shown on slides is backed by Member 6's results.
- Every method claim is verified by Member 4.
- Background statements are checked with Member 2.
- The presenter can explain the end-to-end system at a high level even when detailed technical questions are answered by the corresponding owner.

### Q&A ownership

- Presentation-level summary questions.
- Overall story and conclusions.
- Technical questions are handed to the relevant owner.

---

## Cross-member collaboration map

```text
Member 2: background / motivation
             |
             v
Member 1: architecture / integration
   |          |          |
   v          v          v
Member 3   Member 4   Member 5
baseline   optimized  dataset/workload/benchmark
   \          |          /
    \         |         /
     +------> Member 6
              evaluation / profiling / analysis
                     |
                     v
                 Member 7
              slides / presentation
```

This diagram represents information flow, not a strict sequential schedule. Members should work in parallel whenever interfaces are stable enough.

---

## Suggested development phases

### Phase 0 — Repository and interface validation

- Member 1: architecture, scheduler, integration interfaces.
- Member 2: background reading begins.
- Member 5: survey candidate datasets/workloads.
- Members 3/4/6: review interfaces and evaluation needs.

### Phase 1 — Baseline

- Member 3: implement agreed baseline policies.
- Member 5: produce first reproducible workloads.
- Member 6: define baseline metrics and run protocol.
- Member 1: integrate baseline path.

Exit condition: baseline can run end-to-end on a fixed workload and produce reproducible metrics.

### Phase 2 — Bottleneck identification and optimization

- Member 6: profile baseline and report bottlenecks.
- Member 4: finalize optimization based on an observed problem.
- Member 1: support runtime/interface changes only where justified.
- Member 3: keep baseline frozen for fair comparison.

Exit condition: optimized method is implemented through the same evaluation path as the baseline.

### Phase 3 — Formal evaluation

- Member 5: freeze datasets/workloads/traces.
- Member 6: execute the final experiment matrix and generate plots.
- Member 4: provide ablation configurations.
- Member 1: freeze runtime/configuration versions.

Exit condition: every major claim is supported by a reproducible experiment.

### Phase 4 — Presentation

- Members 1-6: provide slide-ready content and verify their sections.
- Member 7: assemble the deck, write the presentation script, and lead rehearsal.
- Q&A: each owner answers questions about their own component.

---

## Definition of done for individual work

A task is not considered complete merely because code exists. For technical work, the owner should provide:

1. implementation;
2. tests or a reproducible validation command;
3. relevant configuration;
4. a short description of assumptions and limitations;
5. a PR that explains the change and its impact on other modules.

For experimental work, the owner should additionally provide the exact workload/configuration and machine/runtime information required to reproduce the result.
