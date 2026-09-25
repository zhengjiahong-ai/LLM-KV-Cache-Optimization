# Phase 2A Member 6 Spec — Forced-Release Profiling and Data Analysis

## 1. Goal

Member 6 owns the measurement and analysis side of Phase 2A.

The first objective is to answer:

> Does Continuum forced release have measurable decision headroom, and can that headroom be explained by information available at decision time?

This phase evaluates a candidate research gap. It does **not** assume the proposed Cost-Aware method is valid.

Authoritative inputs:

- `docs/phase2-plan.md`
- `docs/phase2-m5-workload-spec.md`
- `src/kvopt/profiling/forced_release.py`

## 2. Ownership boundary

Member 6 owns:

- profiling recorder/output schema;
- joining forced-release decisions with workload/runtime evidence;
- outcome attribution;
- offline paper-heuristic replay;
- offline oracle/proxy analysis;
- regret/headroom analysis;
- plots/tables for Phase 2A;
- measurement limitations and negative results.

Member 6 does **not** own:

- workload semantics or trace generation;
- Continuum baseline implementation;
- Cost-Aware policy implementation;
- changing the forced-release decision rule;
- adding future information to the online observation contract.

If an analysis requires a missing decision-time fact, request an interface change from Member 1 before modifying baseline internals.

## 3. Source-of-truth separation

Phase 2A data must preserve three distinct classes of information.

### A. Decision-time facts

Facts legally available when forced release is decided.

Source:

`ForcedReleaseDecisionSnapshot` plus explicitly approved runtime/workload observations.

Examples:

- candidate `(program_id, prefix_id)`;
- retention deadline;
- waiting-followup state;
- protected block IDs;
- immediately reclaimable block IDs;
- next tool type;
- elapsed time since TTL decision;
- PrefillReload estimate;
- eta;
- queue-delay signal;
- actual Phase 1B selected release effect.

### B. Execution provenance / workload facts

Facts needed to reconstruct the run but not supplied by the forced-release snapshot.

Examples:

- run/trace/scenario ID;
- seed;
- observed server arrival time of each program's first request;
- request/program mapping;
- cache-pressure configuration;
- model/runtime/hardware identity.

### C. Future outcome / oracle labels

Facts known only after the decision.

Examples:

- later follow-up arrival;
- later reuse;
- observed APC hit/miss;
- recomputed tokens or a documented recomputation proxy;
- observed next-turn TTFT/latency;
- future return distance/time.

Class C must never be fed back into an online policy feature column.

## 4. Important current interface limitation

The current forced-release snapshot intentionally does **not** contain `program_arrival_time`.

The Continuum paper-level forced-release heuristic uses program arrival time, so Member 6 must obtain:

> the observed server arrival timestamp of the program's first request

from the benchmark/runtime execution record.

Do **not** substitute:

- planned arrival offset;
- request ID ordering;
- trace-file order;
- current request arrival;
- TTL decision timestamp.

If the observed first-arrival timestamp cannot be obtained reliably, the paper-heuristic comparison is blocked and must be reported to Member 1.

## 5. Data artifacts

Prefer append-friendly machine-readable artifacts rather than one large custom report.

### A. Run metadata

One record per run:

```text
run_id
trace_id
scenario_id
seed
git_sha
backend/runtime identity
model/tokenizer revisions
hardware
cache/memory config
generation/batching config
policy/reference mode
status / failure reason
```

### B. Decision-candidate table

One row per `(forced-release decision, candidate entry)`.

Minimum logical columns:

```text
run_id
decision_id
decision_index
decision_timestamp
required_blocks

program_id
prefix_id
candidate_index

retention_deadline
waiting_followup

protected_block_count
initially_reclaimable_block_count

next_tool_type
elapsed_since_ttl_decision
prefill_reload_seconds
eta
queue_delay_t_seconds

observed_program_first_arrival

p1b_selected
p1b_release_order
```

`decision_id` may be recorder-owned, for example a deterministic composite of `run_id + decision_index`. It does not need to be added to the core runtime contract.

### C. Outcome table

One row per candidate entry when outcome facts can be established:

```text
run_id
decision_id
program_id
prefix_id

followup_arrived
followup_arrival_timestamp
reuse_observed
reuse_delay

apc_hit_or_miss
recomputed_tokens_observed_or_proxy
prefill_penalty_observed_or_proxy
next_turn_ttft
next_turn_latency

outcome_source
outcome_limitation
```

Every derived/proxy field must identify that it is not a direct measurement.

## 6. Counterfactual limitation — do not overclaim

A single run observes the real downstream consequence of the release(s) that actually occurred.

It does **not** directly observe the counterfactual latency that would have occurred if a different protected candidate had been released.

Therefore:

```text
actual selected victim outcome
    = may be directly observed

unselected candidate counterfactual outcome
    = NOT directly observed in that run
```

The first Phase 2A oracle/regret analysis must use one of the following, clearly labeled:

1. **trace-derived offline proxy / upper bound**, using future reuse/return facts plus profiled recomputation cost; or
2. controlled replay under an explicitly implemented alternate victim policy.

Do not label proxy counterfactual loss as “measured latency”.

Controlled replay is optional for the first audit, but should be used later to validate important/high-regret cases before making causal performance claims.

## 7. Paper-Continuum replay

The paper-level reference is:

```text
when protected release is required:
    repeatedly select the candidate whose program has the latest
    observed first-request arrival time
    until enough capacity is released
```

For the first Phase 2A workload, Member 5 constrains one protected entry per program and disjoint candidate blocks. This makes program-level paper semantics and entry-level replay unambiguous.

Member 6 should compute the paper-reference selection **offline from the exact observed candidate set**.

Record at least:

```text
paper_selected
paper_release_order
```

Do not mutate the live P1B baseline merely to produce this first audit.

If later formal experiments require real execution under the paper heuristic, that becomes a separate implementation/integration task reviewed by Member 1.

## 8. P1B adaptation reference

The actual P1B release is already present in the decision observation:

```text
earliest retention deadline
    -> native-LRU key
    -> stable entry identity
```

Member 6 must preserve this as an independent reference and must not call it “original Continuum”.

## 9. Offline oracle / headroom metric

The oracle exists only to answer:

> how much room is there for a better forced-release choice?

The first oracle should stay deliberately simple and auditable.

A recommended first proxy is based on future reuse plus profiled recomputation loss, for example:

```text
candidate_proxy_loss
    = future_reuse_indicator_or_weight
      * profiled_prefill_reload_cost
```

The exact proxy formula is an **analysis definition**, not the proposed online policy.

If memory released differs materially across candidates, report both:

- total release loss;
- loss normalized by immediately reclaimed blocks, where useful.

Do not add queueing/continuity terms merely to make the oracle favor the candidate hypothesis. Add additional loss terms only when their measurement semantics are explicit.

For each decision, compute:

```text
P1B adaptation proxy loss
paper heuristic proxy loss
oracle minimum proxy loss

P1B regret   = P1B loss   - oracle loss
paper regret = paper loss - oracle loss
```

For multi-entry release, evaluate the selected release set, not only the first victim.

## 10. Required first analyses

The first Phase 2A report should answer at least:

### A. Forced-release coverage

- number of runs;
- number of successful forced-release decisions;
- candidate count distribution;
- number of protected entries released per decision.

### B. Candidate-value heterogeneity

Within each decision:

- distribution/range of proxy release loss;
- recomputation-cost heterogeneity;
- future-reuse/return heterogeneity.

### C. Baseline regret

For both:

- paper-Continuum latest-arrival reference;
- P1B deterministic adaptation.

Report:

- zero-regret fraction;
- mean/median regret;
- P90/P95 where sample count is sufficient;
- worst cases with trace IDs.

### D. Causal consequence for actual releases

For the release actually executed in the runtime, connect where observable:

```text
forced release
    -> later follow-up/reuse
    -> APC miss / recomputation
    -> next-turn TTFT / latency
```

Do not imply this causal chain for unexecuted counterfactual victims without replay evidence.

### E. Signal association

Explore whether decision-time features relate to the offline proxy loss:

- remaining TTL / deadline distance;
- elapsed tool gap;
- next tool type;
- PrefillReload;
- eta;
- queue-delay signal;
- reclaimable block count;
- observed program arrival age.

This is exploratory profiling, not feature selection for the final method.

## 11. Required controls

At minimum compare across the controlled workload families:

- homogeneous control;
- return-time heterogeneity;
- recomputation-cost heterogeneity.

Results should be broken down by scenario rather than pooled immediately.

A strong candidate direction should ideally show:

- little headroom in homogeneous/control cases;
- larger and interpretable headroom when value heterogeneity exists.

Negative or null results must be preserved.

## 12. Reproducibility requirements

Every derived table/figure must be traceable to:

- run ID;
- Git SHA;
- trace/scenario ID;
- seed;
- runtime/model/hardware config;
- raw decision artifact;
- raw outcome/runtime evidence;
- analysis script/version.

Analysis scripts should regenerate summarized tables/plots from raw artifacts without manual editing.

Do not overwrite raw artifacts during analysis.

## 13. First delivery

The first Member 6 PR should contain:

1. recorder/export path for `ForcedReleaseDecisionSnapshot`;
2. join logic for M5 run/trace metadata;
3. decision-candidate schema;
4. outcome schema;
5. offline paper-heuristic replay;
6. simple oracle/proxy loss implementation;
7. tests on synthetic fixture data;
8. one small end-to-end sample artifact/summary if M5 workload is available.

It does **not** need:

- final plots;
- large experiment sweeps;
- a Cost-Aware policy;
- a learned predictor;
- a complex statistical model;
- paper-quality significance testing.

## 14. Acceptance criteria

Member 6 is ready for bulk Phase 2A collection when:

- [ ] every forced-release decision has a stable `decision_id`;
- [ ] all candidates, not only the selected victim, are recorded;
- [ ] P1B actual selection is preserved exactly;
- [ ] observed program first-arrival time is available for paper replay;
- [ ] decision-time and future-outcome columns are separated;
- [ ] proxy vs direct measurement is explicit;
- [ ] one run cannot accidentally treat unselected counterfactual latency as observed;
- [ ] paper heuristic and P1B adaptation are reported as different references;
- [ ] offline oracle never feeds future information into online features;
- [ ] raw artifacts can regenerate the first summary tables.

## 15. Escalation to Member 1

Stop and request an interface decision if:

- program first-arrival time cannot be observed reliably;
- candidate identity cannot be joined across decision and outcome records;
- actual APC reuse/miss cannot be attributed to the relevant prefix/program;
- recomputation evidence is ambiguous enough to change the regret conclusion;
- shared blocks or multiple protected entries per program appear in the first workload despite the Phase 2A simplification;
- analysis would require changing the live baseline policy path.
