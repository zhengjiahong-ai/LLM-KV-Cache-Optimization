# Post-Phase-3 Experimental Roadmap

> **Status: planning document only (M1, 2026-11-10).** This roadmap records the proposed research sequence after the already-frozen Phase 3 campaign. It does not amend Protocol v4, G0 v3, the one-shot 270-run authorization, or any sealed evidence. It does not authorize implementation, data acquisition, smoke tests, or GPU execution for Phase 4 or Phase 5. Each later campaign requires a separate M1 decision and a study-specific frozen protocol.

## 1. Purpose and research logic

The project should distinguish three different evidence goals:

1. **Controlled component evaluation:** determine whether a registered decision-layer change produces an incremental effect when the workload and operating conditions are held comparable.
2. **Algorithm development and independent confirmation:** use the controlled results to diagnose limitations, develop a final candidate, and then evaluate it on data not used to tune that candidate.
3. **Full-system evaluation under representative Agent workloads:** determine whether the resulting system is useful under less artificial, more natural request arrivals, concurrency, and cache pressure.

These goals should not be collapsed into one experiment. A controlled experiment improves attribution; a broader full-system evaluation improves external validity. Neither substitutes for the other.

The proposed sequence is:

| Stage | Main question | Evidence role | Current status |
| --- | --- | --- | --- |
| Phase 3 | Do the registered Entry Release and Block Victim Selection policies change the measured outcome under frozen conditions? | Controlled component-level evidence | Protocol v4 frozen; 270-run pipeline authorized, execution state must be read from the canonical status ledger |
| Phase 4 | What should be improved, and which final policy should be carried forward? | Post-campaign diagnosis, algorithm development, official-code audit, and candidate freeze | Proposed; not authorized |
| Phase 5 | Does the final system provide value against Native vLLM and Continuum implementations under representative Agent workloads? | Independent full-system evaluation | Proposed; not authorized |

## 2. Phase 3 — preserve the current controlled campaign

Phase 3 remains governed exclusively by [Protocol v4](phase3-final-evaluation-protocol-v4.md), G0 v3, and the separate [one-shot 270-run authorization](experiments/phase3-option-f-270-run-pipeline-authorization.md).

The current registered design remains:

- Six arms: N0 / A0 / A1 / A2 / A3 / E0.
- 20 Workload Groups × C1/C2 × 6 arms = 240 Main runs.
- 5 frozen Groups × C1/C2 × 3 repeats = 30 Noise runs.
- Existing 40-run A0 Load Calibration is reused and is not rerun.
- The Workload Group remains the statistical unit; cells, requests, turns, and repeats are not independent Groups.

No Phase 4 or Phase 5 idea in this roadmap may be inserted into the 270-run campaign. In particular, do not add arms, Groups, repeats, pressure conditions, timing modes, or software variants to the frozen execution.

Phase 3 is a controlled component-level evaluation within the project-side Continuum-style cache-management adaptation. It is not a full-system Continuum-versus-Vanilla-vLLM comparison. All Phase 3 arms use the Native scheduler; TTL events are observable, but there is no Static-TTL arm. These boundaries remain unchanged.

## 3. Phase 4 — post-campaign diagnosis and algorithm development

### 3.1 Inputs and entry conditions

Phase 4 should begin only after:

- the authorized Phase 3 pipeline has a complete execution ledger and immutable raw evidence archive;
- independent N/E/C evaluation and all applicable Protocol v4 gates have completed;
- M1 has reviewed and accepted the Phase 3 evidence and its claim boundaries;
- the Phase 3 analysis has distinguished supported, unsupported, and not-evaluable hypotheses.

Authorization of the 270-run pipeline is not evidence that Phase 3 has started or completed. Phase 4 must not be scheduled as if Phase 3 results already exist.

### 3.2 Analysis before optimization

The first Phase 4 task is diagnosis, not immediate algorithm rewriting. Review:

- group-level paired effects and their uncertainty;
- between-Group heterogeneity and FLAT / WEAK / RESPONSIVE strata;
- decision exposure: how often each policy actually changes a release or victim decision;
- whether observed improvements are concentrated in a small number of Groups;
- false-positive or harmful release decisions;
- N/E/C evidence completeness and physical victim-set attribution;
- timing observations that can be reconstructed from preserved raw events, subject to timestamp completeness and comparability;
- the distinction between recomputed Token volume, estimated compute cost, and measured wall-clock outcomes.

Do not interpret request rows, turns, or repeated runs as independent Workload Groups. Use the frozen Phase 3 statistical contract for Phase 3 claims.

### 3.3 Algorithm development

Potential Phase 4 work includes:

- revising Entry Release scoring based on observed failure cases;
- revising physical Block Victim Selection where Phase 3 establishes adequate decision exposure;
- investigating whether an Entry-level score should account for downstream physical victim consequences;
- deciding whether any of A1/A2/A3 should be combined, only when the evidence and decision-layer semantics justify the combination;
- refining cost proxies and, where defensible, adding position-aware recomputation-cost estimates;
- retaining the Native vLLM BlockPool, reference counts, hash lifecycle, and physical eviction ownership.

The four proposals in [Potential Future Research Directions](future-research-directions.md) remain a separate research reserve. Their preservation does not mean that all four should be implemented in Phase 4.

Every candidate change should record its motivation, source revision, expected mechanism, failure criterion, and the evidence used to select it. Development data and tuning results must not later be presented as independent confirmation.

### 3.4 Official Continuum repository audit

The authors' public repository should be retained as an external implementation reference:

- Repository: [Hanchenli/vllm-continuum](https://github.com/Hanchenli/vllm-continuum)
- Reference snapshot inspected on 2026-11-10: `316a58794a6ff86b216e579b74fd56ed0c5a911f`.

The official README describes the repository as a modified vLLM with Continuum-style scheduling support **without the estimation in the paper**. Therefore, the repository must be named **Continuum Official Public Implementation** (or equivalent), not "the complete original Continuum implementation" and not an exact reproduction of every paper mechanism.

Before using it in a performance campaign, Phase 4 must audit and freeze:

- the exact upstream commit and any local patches;
- the vLLM base revision and relevant dependency versions;
- the actual TTL / estimation behavior present in that snapshot;
- scheduler and KV-cache lifecycle differences;
- supported hardware, model, and runtime configuration;
- whether a comparable Native-vLLM build can be produced from the same software base.

The reference SHA above records the source snapshot inspected for planning; it is not yet an execution freeze. Any later benchmark must pin the exact tested commit and environment.

### 3.5 Phase 4 exit criteria

Phase 4 should produce:

1. an accepted Phase 3 evidence and failure-analysis report;
2. a versioned final Cost-Aware candidate (or an explicit decision not to promote a candidate);
3. an implementation and configuration freeze;
4. a feasibility report for the official repository and common-environment comparison;
5. a separate Phase 5 protocol proposal, workload sampling plan, statistical plan, and compute budget.

No final performance claim should be based only on Phase 4 development or tuning runs.

## 4. Phase 5 — representative full-system comparison

### 4.1 Four primary comparison systems

The proposed full-system comparison has four primary systems:

| Arm | Implementation | Purpose |
| --- | --- | --- |
| Native | Unmodified Native vLLM | Basic reference |
| Continuum Official | Authors' pinned public repository snapshot | External comparison against the released implementation |
| Continuum Adapted | Project-side Continuum-style baseline, derived from A0 | Evaluate our adaptation of the paper's mechanisms |
| Cost-Aware | The Phase 4 frozen Cost-Aware candidate built on the same project-side foundation | Evaluate the project's optimization contribution |

**Important A0 naming boundary:** Phase 3 A0 is a component-level baseline and uses the Native scheduler like every other Phase 3 arm. It is not, by itself, the complete project-side Continuum system. If Phase 5 is intended to compare full systems, the "Continuum Adapted" configuration must explicitly state whether the project Dynamic TTL and program-level scheduler are enabled. If they are enabled, label the configuration **A0-derived full-system adaptation**, not "the exact Phase 3 A0 arm". The Cost-Aware system must use the same non-target TTL, scheduler, runtime, and workload configuration so that its incremental policy contribution remains interpretable.

If the program-level scheduler cannot be validated or is deliberately excluded, the comparison must be named a cache-management-path comparison rather than a complete full-system Continuum comparison. A separate scheduler ablation may be required.

### 4.2 Interpretation of the official-code comparison

The four-system comparison answers a useful external question: how do Native vLLM, the authors' released Continuum-style code, our project-side adaptation, and our final Cost-Aware system behave on the same representative workload?

It does **not**, by itself, isolate which individual mechanism caused a difference between the official repository and our adaptation. The official public repository differs in implementation, software base, and estimation scope. Whole-system results must therefore be described as system-level comparisons.

Mechanism-level claims require separate controlled ablations, such as:

- Static TTL versus project Dynamic TTL;
- Native scheduler versus project program-aware scheduler;
- baseline Entry Release versus the selected Cost-Aware Entry Release;
- Native LRU victim selection versus the selected Cost-Aware Block Victim Selection.

These ablations are optional follow-on studies and must not be implied by the four primary system arms alone.

### 4.3 Relax artificial operating-point controls, not comparison fairness

Phase 5 should be more representative than the Phase 3 fixed replay design. The intention is **not** to remove all controls. It is to replace artificial pressure and timing interventions with realistic workload behavior while retaining the conditions required for a fair comparison.

| Dimension | Phase 3 controlled design | Phase 5 proposed design |
| --- | --- | --- |
| Pressure | Two registered C1/C2 operating points and fixed pressure requirements | No C1/C2-style forced pressure injection; natural cache competition generated by the workload |
| KV capacity | Frozen Phase 3 pool and conditions | Same pre-registered KV memory budget across matched systems; optional capacity sensitivity strata |
| Arrival timing | Frozen replay timeline | Empirical non-uniform arrival traces and/or closed-loop Agent execution |
| Concurrency | Frozen Phase 3 execution pattern | Representative multi-Session concurrency, bursts, idle gaps, and overlapping jobs |
| Workload | Frozen 40-task / 20-Group cohort | Larger independently sampled Agent workflow cohort with broader task and repository coverage |
| Model/runtime | Frozen Phase 3 model and vLLM 0.27.1 | One or more explicitly pinned model/runtime strata, with fair within-stratum comparisons |
| Goal | Isolate registered component effects | Evaluate complete-system behavior under representative workload conditions |

The same KV capacity should normally be retained across the four systems within a matched comparison. What is removed is the artificial requirement to trigger exactly C1/C2 pressure events. The workload should naturally generate cache occupancy and eviction pressure. If a capacity sweep is needed, its capacity levels must be pre-registered and treated as explicit strata, not chosen after seeing results.

### 4.4 Two complementary workload modes

Phase 5 should consider two workload modes because they answer different questions.

**Mode A — empirical trace-driven replay**

- Collect or acquire representative Agent workflow traces with documented provenance and permission.
- Preserve naturally irregular arrival intervals, burstiness, tool gaps, and idle periods rather than imposing one fixed synthetic inter-arrival schedule.
- Replay the same exogenous arrival trace, task inputs, tool outputs/fixtures, and concurrency envelope across all four systems.
- This mode provides the stronger matched comparison for attributing system differences under a common arrival process.

**Mode B — closed-loop Agent execution**

- Execute the same Agent task definitions and tool environment on each system.
- A subsequent model request is generated when the preceding model/tool step actually completes; do not force a fixed timestamp for every future request.
- Preserve the same initial task set, model parameters, tool behavior, and concurrency policy.
- Measure complete Job Completion Time and throughput under the resulting endogenous request process.

Closed-loop execution measures the total system/workflow effect, but the exact later request arrival times may diverge because each system completes earlier steps at different times. It must therefore be interpreted as a full-system outcome, not as a perfectly identical request-by-request replay. Mode A and Mode B should be reported separately.

### 4.5 Controls that remain necessary

Even when Phase 5 is less artificially controlled, the following should remain matched or explicitly stratified:

- model and tokenizer revision within each comparison stratum;
- prompt/task definitions, generation parameters, and stopping rules;
- tool implementations, tool data, and external service behavior (or deterministic fixtures where needed);
- hardware class, GPU allocation, and background-load policy;
- KV cache memory budget within a matched comparison;
- software commits, dependency versions, build flags, and runtime configuration;
- initial cache state and warm-up policy;
- concurrency envelope and, for Mode A, the exact arrival trace;
- seeds where the runtime supports meaningful seed control;
- metric definitions, event collection, timeout, failure, and censoring rules.

If the official repository cannot be brought onto the same vLLM base as the project implementation, pin each environment and report the version difference as a confound. In that case, the official comparison remains a useful external system comparison, but not a pure algorithm-only comparison. Do not silently attribute all differences to Continuum or Cost-Aware logic.

### 4.6 Outcomes to collect

The Phase 5 protocol should pre-register a primary outcome and a small set of key secondary outcomes. Candidate measurements include:

- **Recomputation work:** recomputed prefix Token volume, with the same evidence-quality rules where applicable.
- **Estimated compute cost:** position-aware or model-structure-aware FLOPs estimates only if the estimator is validated and its assumptions are reported. Do not label Token counts as FLOPs or estimates as hardware-measured FLOPs.
- **Latency:** queue delay, Native queued-to-first-token, admission-to-first-token, TTFT, and inter-token latency where validly observable.
- **Workflow completion:** Job Completion Time, task completion rate, and timeout/right-censoring rate.
- **Serving capacity:** throughput under a clearly defined offered-load or closed-loop workload.
- **Cache behavior:** prefix reuse, hit rate, eviction/release counts, protected-entry duration, and pressure events.
- **Resource use:** KV occupancy and other resource measurements available with reliable provenance.
- **Task quality:** task success and output-quality checks, so a faster but degraded system is not treated as an improvement.

Preserve raw event timestamps and run-level provenance during execution. Derived timing summaries can be computed after the campaign only if the required raw events were collected and archived. GPU kernel time, hardware FLOPs, or hardware performance counters cannot be reconstructed from ordinary request timestamps if they were not instrumented during execution.

### 4.7 Statistical design and independent data

- Use independently sampled Workload Groups / Agent workflows as the unit of inference, not request rows, turns, or runtime repeats.
- Reserve a holdout cohort that is not used to tune Phase 4 algorithms.
- Determine the Phase 5 sample size from a pre-specified minimum meaningful effect, pilot variance, desired uncertainty/power, and available compute budget. Do not choose the sample size solely by multiplying the Phase 3 run count.
- Use paired Group-level comparisons when the workload and arrival trace can be matched.
- Report effect distributions and confidence intervals at the Group level; use Group-level bootstrap or another justified method.
- Treat repeated runs within a Group as measurements of runtime noise, not as new independent Groups.
- Pre-register exclusions, missingness, timeouts, right-censoring, multiple-comparison handling, and primary/secondary outcomes.

### 4.8 Phase 5 exit criteria

Before any Phase 5 execution, M1 must separately accept:

1. the four system definitions and exact source revisions;
2. the official-code compatibility and environment audit;
3. the A0-derived full-system configuration, including the scheduler/TTL scope;
4. the independent workload sampling and holdout plan;
5. Mode A / Mode B protocols and their separate estimands;
6. primary and secondary metrics, raw event schema, and statistical analysis plan;
7. sample-size rationale, GPU budget, and execution schedule;
8. a frozen reproducibility manifest and failure/stop rules.

This document does not authorize Phase 5 execution.

## 5. Threats to validity and claim boundaries

- Phase 3's fixed replay design and Phase 5's representative workload design answer different questions; do not pool their results as if they came from one homogeneous experiment.
- The authors' public repository is a released Continuum-style implementation, not a verified complete implementation of every paper estimator and experiment.
- A four-system comparison establishes system-level differences, not isolated mechanism causality.
- A0 in Phase 3 is not identical to an A0-derived full-system configuration with the program-level scheduler enabled.
- Natural workload pressure can vary across workloads. Keep the memory budget matched and report the pressure actually observed; do not post-hoc select only workloads where a preferred method is under pressure.
- Closed-loop arrival processes are endogenous to system completion time. Interpret them as full-system outcomes and keep them separate from trace-driven replay.
- Timing metrics are only valid when their raw timestamps were captured with comparable semantics and adequate completeness.
- Estimated FLOPs are not hardware-measured FLOPs unless supported by appropriate instrumentation.
- Phase 5 does not become an exact reproduction of the original Continuum paper merely by including the official public repository.

## 6. Decision gates and authority

| Decision | Required authority |
| --- | --- |
| Complete and accept Phase 3 | M1, after evidence and gate review |
| Begin Phase 4 diagnosis | M1, after Phase 3 evidence acceptance |
| Implement or promote a Phase 4 candidate | Separate M1 scope decision |
| Freeze Phase 5 systems and workload | M1, after technical and statistical review |
| Acquire new workload data / run GPU experiments | Separate M1 authorization and frozen protocol |

M4 should lead statistical design and independent analysis. M6 should assess environment compatibility, runner changes, resource requirements, and execution feasibility. M2/M3 may support literature, upstream-code, and workload-provenance audits. M1 retains research-scope, protocol, and final-evidence authority.

## 7. Relationship to other project documents

- [Experimental Plan](experiment-plan.md) — current Phase 3 and research question index.
- [Research Status](research-status.md) — canonical status, authorization, and evidence boundaries.
- [Protocol v4](phase3-final-evaluation-protocol-v4.md) — immutable Phase 3 contract.
- [Phase 3 mechanism coverage and claim boundaries](experiments/phase3-mechanism-coverage-and-claim-boundaries.md) — mechanisms that Phase 3 does and does not evaluate.
- [Potential Future Research Directions](future-research-directions.md) — four preserved research proposals; separate from the Phase 4/5 stage plan.
- [Phase 3 final report outline](phase3-final-report-outline.md) — reporting structure for the frozen campaign only.
