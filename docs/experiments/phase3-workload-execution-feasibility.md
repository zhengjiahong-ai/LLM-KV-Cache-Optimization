# Phase 3 Workload & Execution Feasibility Report

Status: **DESIGN / DATA AUDIT ONLY — FORMAL GPU CAMPAIGN NOT AUTHORIZED**

## 1. Executive finding

The repository already contains enough authentic multi-turn data and Native
instrumentation to build a 20-group Phase 3 campaign without creating a new
agent framework. It does **not** yet contain 20 independent, fully frozen
groups: the strongest existing cross-repository source is the 20-task W1-C
S100 acquisition, while the prior bounded campaign used 18 of those tasks in
nine groups. Reaching 20 disjoint groups therefore requires either acquiring
at least 22 additional tasks (for two-session groups) or adopting larger
multi-session groups with fewer independent units, which would not meet M1's
20-group target.

Recommendation: acquire and seal a deterministic extension from the already
frozen 100-task W1-C sampling frame, retain W1-C's Mini-SWE-Agent capture path,
then form 20 disjoint two-session groups. Do not substitute public issue rows
for missing trajectories.

## 2. Existing workload inventory

### W1-A — authentic single-repository acquisition

| Property | Audited value |
| --- | ---: |
| Independent tasks | 10 |
| Repositories | 1 (`astropy/astropy`) |
| Successful request records | 453 |
| Requests per task | 3–50 |
| Prompt token range | 1,463–20,782 |
| Median prompt tokens | 7,868 |
| Adjacent server-gap samples | 443 |

W1-A has trajectories, acquisition sidecars, explicit locally tokenized prompt
IDs, request/tool timing, converted traces, and validation reports. It is high
quality but repository-homogeneous and uses the historical 3B model/revision.
It is useful for history calibration and regression, not as the sole Phase 3
population.

### W1-B — replay/profile layer, not a new population

W1-B materializes ten W1-A sessions into Native replay and supplies the
PrefillReload profile, cache-pressure machinery, APC observations, and
request-level evidence. It adds no independent tasks or repositories. Its
constructed timing and selected checkpoints must not be counted as new Agent
workload observations.

### W1-C — strongest reusable cross-repository source

| Property | S50 | S100 |
| --- | ---: | ---: |
| Independent tasks | 20 | 20 |
| Repositories covered | 12 | 12 in the paired design |
| Successful model calls | 1,000 | 1,800 |
| Failed model calls | 0 | 3 |
| Tool calls | 464 | 943 |
| Median prompt tokens | 5,836 | 9,245 |
| Maximum admitted prompt tokens | 19,726 | 32,223 |
| Median per-task context growth | 9,131.5 | 17,495.5 |
| Median adjacent exact-token LCP | 5,773 | 9,209 |
| Median adjacent reuse ratio | 0.9709 | 0.9829 |

All 20 tasks have paired lifecycle records. Thirty-seven trajectories passed
the strict source-to-sidecar validator: all 20 S50 trajectories and 17 S100
trajectories without a rejected final submission. Eighteen of the 20 pairs are
fully evidence-comparable; all 20 remain lifecycle-comparable. Three S100 runs
hit the frozen 32K context boundary. The existing formal bounded cohort reused
18 tasks as nine groups; it must not be treated as 54 independent samples.

The trace records preserve request order, logical gaps, explicit token IDs,
tool observations, and model-call identities. Native runtime-submitted token
identity was subsequently checked by the CUDA replay path. W1-C is therefore
the preferred Phase 3 seed.

### Phase 2H/2I history-rich data

Phase 2H froze two three-session scenarios, each with 180 requests and pressure
at rounds 40/50/55. These runs prove that three-session replay, empirical TTL
history, fixed pressure, and Native request observation are feasible. They use
only six W1-C tasks and are mechanism-focused, so they add no new independent
task source. Phase 2I reuses HR02 and adds A3 evidence; it is not additional
workload.

## 3. Public-source trace availability

Primary source references used by this audit:

- SWE-bench dataset guide:
  <https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/datasets.md>
- SWE-bench evaluation harness and resource requirements:
  <https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/harness.md>
- Mini-SWE-Agent repository:
  <https://github.com/swe-agent/mini-swe-agent>
- audited Continuum repository:
  <https://github.com/Hanchenli/vllm-continuum>

| Source | Task descriptions | Complete Agent trajectories | Exact submitted token IDs/timing | Phase 3 use |
| --- | --- | --- | --- | --- |
| Continuum public repository | Yes, via SWE-bench Verified loader | **No** paper-run trajectories published in the audited checkout | No | implementation/provenance reference only |
| SWE-bench Verified | Yes, 500 engineer-verified task rows | No; it is a task/evaluation dataset | No | deterministic acquisition frame |
| Mini-SWE-Agent | Agent and trajectory writer available | Yes **after executing acquisition** | only if this project's sidecar instrumentation is enabled | preferred acquisition scaffold |
| Existing W1-C | Yes | Yes, 20 S50 + 20 S100 executions | Yes in sidecars/converted replay, with declared local-vs-Native boundary | immediate reusable seed |

The audited Continuum repository saves Mini-SWE-Agent-style trajectories when
it runs, but does not publish the paper experiment's per-task trajectories.
Aggregate results cannot reconstruct message content, exact tokens, arrivals,
or tool gaps. SWE-bench Verified likewise supplies issue/repository/test data,
not conversations. Only newly executed, pinned Mini-SWE-Agent acquisition (or
the existing W1-C artifacts) satisfies the complete Trace requirement.

## 4. Path to 20 independent groups

For two-session groups, 20 disjoint groups require 40 independent tasks. W1-C
currently supplies 20, so the minimal extension is 20 more eligible tasks; a
22–24 task acquisition reserve is prudent because context-limit or sidecar
failures must remain recorded rather than silently replaced.

Reuse the existing 100-task W1-C frozen sample and acquisition tooling:

1. exclude the 20 already acquired task IDs;
2. preselect a deterministic 24-task extension using repository and static
   length strata, before any policy result exists;
3. run the same pinned Mini-SWE-Agent capture contract;
4. retain every success, failure, context-limit, and right-censored record;
5. seal at least 40 eligible tasks and form 20 disjoint pairs with repository,
   length, call-count, and gap diversity;
6. freeze group membership before Native execution.

Estimated engineering work is low-to-moderate because sampling, acquisition,
conversion, sidecar validation, timeline, fixed pressure, five policy hooks,
and evaluator components already exist. New work should be limited to a
five-arm materializer, Native-only baseline mode, group freeze, and unified
Phase 3 evaluator. The dominant cost is acquisition/validation, not algorithm
development.

## 5. Load, timing, and concurrency feasibility

Existing W1-C acquisition is one Agent worker and therefore does not itself
contain production concurrency. Phase 2H proves deterministic three-session
source-time merge with peak Native inflight 2 and no wall-clock replay idle.
For Phase 3, two load regimes should use the same frozen per-session requests:

- **moderate**: two concurrent sessions, native inflight ceiling 2;
- **deep**: three concurrent sessions or the same sessions with a pre-frozen
  arrival compression/pressure boundary.

The transformation must be fixed before outcomes, identical across arms, and
retain source gaps as logical lifecycle time. The report must distinguish
source-time gaps, logical replay gaps, native timestamps, and wall time. Public
SWE-bench rows alone cannot supply these timing fields.

## 6. RTX 4090D and capacity feasibility

The qualified environment is one RTX 4090D (24,564 MiB), CUDA 13.0, PyTorch
2.13.0+cu130, and vLLM 0.27.1. The frozen Phase 2 model is non-quantized
`Qwen2.5-Coder-1.5B-Instruct`, 32,768 context, 2,048-token chunked prefill,
16-token blocks, and a 2,048-block KV pool (32,768 tokens). It successfully ran
180-request three-session replays and the 54-run bounded campaign.

Capacity consequence: a single near-32K request can occupy essentially the
entire deliberately constrained 2,048-block pool. Multi-session legality is
provided by chunked execution and sequential/inflight control, not by capacity
for several simultaneous 32K resident chains. The final protocol must preserve
the same pool across arms and fail closed if an admitted request cannot run;
increasing capacity after seeing an arm outcome is forbidden.

The completed 54-run bounded campaign took 38m54s end to end. Phase 2H/2I
three-session runs typically took roughly 1–2 minutes per arm after environment
setup. A candidate `20 groups × 2 loads × 5 arms × 3 repeats` matrix is 600
Native runs. At 1–3 minutes/run plus initialization and evidence writing, the
planning range is approximately **15–40 GPU-hours**. At 2 CNY/hour this is
**30–80 CNY**, excluding Agent acquisition and CPU SWE-bench grading. A sixth
arm raises the matrix to 720 runs and approximately **18–48 GPU-hours**.

This estimate is not an authorization or measured forecast. Before freeze,
calculate total requests/tokens from the sealed 40-task cohort and enforce a
hard GPU-hour ceiling. Engine initialization currently dominates short runs;
cross-run engine reuse is not recommended because it risks cross-arm cache
contamination and adds new infrastructure.

## 7. Native evidence capability

### Available and suitable for the primary outcome

- `VLLM_NATIVE_REQUEST_OBSERVATION` exposes N (prompt), E (eligible prefix),
  and C (cached prefix) with `0 <= C <= E <= N` validation.
- Actual request recomputation is `E - C`; new suffix work is `N - E`; actual
  prefill work is `N - C`.
- Stable request/program/run/group/arm identities and explicit-token hashes are
  persisted.
- Native request submission/completion, queue duration, APC classification,
  pressure completion, Entry decisions, and execution telemetry are available.

Aggregate Recomputed Tokens can therefore be measured independently of a
content-level physical join and is feasible as the Phase 3 primary metric.

### Available but claim-limited

- Hashed physical eviction callbacks and content identity fields are recorded.
- Phase 2I final execution observed 7,862 hashed evictions and three physical
  outcomes, but Gate O accepted zero complete decision-to-physical joins and
  reported 7,822 unattributed evictions.
- Right-censoring is explicitly observable and must be preserved.

Thus physical evictions may be reported descriptively, but Phase 3 cannot claim
that a selected A3 block caused a later recomputation unless a separately
frozen identity gate passes. Gate O failure must not invalidate valid N/E/C
request measurements, and request measurements must not be relabeled as
per-block causal attribution.

### Remaining limitations

- Native first-token timestamp was unavailable in the historical
  `wait_for_completion` adapter; TTFT needs a real Native timestamp or must be
  declared unavailable.
- Native APC hit/miss was historically derived from N/E/C rather than a stable
  per-request engine event. The derivation and categories must be frozen.
- Logical `REQUEST_ADMITTED` is not a Native scheduler admission timestamp.
- Unattributed eviction events and content never re-requested remain missing or
  right-censored, not permanent non-reuse.

## 8. Feasibility gates and recommendation

**GO for protocol freeze preparation, NOT YET for GPU execution.**

Before M1 authorizes the campaign:

1. seal 40 eligible authentic tasks and 20 disjoint groups;
2. publish repository/task/request/token/gap distributions for the final seal;
3. freeze two load transformations and identical arm inputs;
4. qualify the Native-only arm without changing Native ownership;
5. freeze N/E/C/APC derivation and missingness rules;
6. either add true Native TTFT or remove TTFT from confirmatory metrics;
7. bind model/cache/runtime/environment and offline Hugging Face cache;
8. calculate the final token-based 4090D budget and hard stop;
9. keep physical attribution diagnostic unless an independent Gate O successor
   passes before outcomes are inspected.

No new GPU pilot is required to establish basic runtime feasibility; existing
Phase 2H/2I and bounded evidence already do that. Any preliminary execution
should be limited to non-outcome-bearing configuration validation explicitly
authorized by M1.
