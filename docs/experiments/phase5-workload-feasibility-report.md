# Phase 5 Workload Feasibility Report

**Status:** M6 feasibility assessment complete; no Phase 5 protocol or GPU campaign authorized

**Code baseline:** `ced1d1ce1d9135c1d013d34acd9850648a2e1d42` (`main` at audit start)

**Audit date:** 2026-11-15

**Scope:** Workload-Driven Candidate Exposure and Cost-Aware Validation

## 1. Executive decision

Phase 5 is feasible on the existing RTX 4090 D environment, but it is **not
ready for a formal campaign without a bounded replay extension and a new
workload seal**.

The recommended source mix is:

1. authentic SWE-Bench + mini-swe-agent trajectories acquired with the existing
   observation sidecar, for realistic cumulative coding-agent sessions;
2. BFCL v4 Web Search task inputs replayed through a pinned, recordable search
   environment, for shorter programs with different tool gaps;
3. public Multi-SWE-Bench/OpenHands trajectories as a secondary diversity pool,
   after their message/tool schema and redistribution terms are sealed.

None of these sources is a drop-in reproduction of the private Continuum paper
traces. The paper's 100 SWE-Bench and 100 BFCL GPT-5 traces are not present in
the audited preview repository. Public benchmark rows are task definitions,
not Agent traces. Public trajectories can preserve semantic interaction, but
do not contain this project's exact runtime token IDs, arrival clock, or Native
block identities. Those fields must be produced by a pinned acquisition and
replay path.

The current generic Phase 2 trace model already represents multiple programs,
program/turn identity, ordered arrivals, tool gaps, and exact replay token IDs.
The controlled Native runner used by the accepted campaign, however, is limited
to exactly two sessions and drains Native work in bounded waves. It does not yet
implement a general 2/4/8/16-program event-driven replay or a frozen Poisson
arrival generator. Phase 3 also demonstrated that a frozen enqueue plan is not
enough: actual `VLLM_REQUEST_SUBMITTED` order must be checked as an execution
contract.

The report therefore recommends a small, reviewable Phase 5 engineering step
before any GPU run. It does **not** recommend changing A1/A2/A3 or declaring a
new protocol.

## 2. Evidence levels

This report uses four evidence levels so that workload realism is not confused
with replay fidelity.

| Level | Meaning | Permitted claim |
| --- | --- | --- |
| L0 task input | Issue/question, repository revision, tools and expected result | Public benchmark task exists |
| L1 semantic Agent trace | Ordered messages, tool calls and observations | Agent interaction/content can be reconstructed |
| L2 replay-ready trace | L1 plus exact rendered prompt/token IDs, program/turn IDs and frozen arrival/tool timing | Deterministic logical replay is possible |
| L3 Native execution evidence | L2 plus actual submission order, hash chain, block IDs, decisions, plans and physical outcomes | Native candidate exposure and execution can be audited |

An arrival sequence generated from a fixed seed is a controlled workload, not
an observed production trace. A paper-reported aggregate is not a trace.

## 3. Continuum paper and official implementation

### 3.1 What the paper actually used

The [Continuum paper](https://arxiv.org/abs/2511.02230) reports collecting 100
mini-swe-agent/SWE-Bench traces and 100 BFCL v4 Web Search traces with GPT-5.
Its reported mean (standard deviation) workload statistics are:

| Workload | Turns/program | Tool time (ms) | Tokens/program |
| --- | ---: | ---: | ---: |
| SWE-Bench | 10.9 (2.1) | 925 (3,550) | 70,126 (19,732) |
| BFCL v4 Web Search | 6.3 (2.3) | 1,923 (2,133) | 93,256 (68,687) |

The main trace-replay experiments use Poisson arrivals. SWE-Bench is generated
with mini-swe-agent and kept within the context window. BFCL uses the Web Search
category and is scaled by 0.4 so that at least 100 requests fit the Llama-3.1
128K context. OpenHands is evaluated on the official Multi-SWE-Bench Go example.
The paper also describes a separate real 500-task SWE-Bench Verified deployment
on an internal H100 testbed; that is not the same evidence as the collected
trace-replay workload. Its turn-scaling experiment repeats SWE traces 1x--5x
while inversely scaling token lengths, and is therefore a simulated trace
transformation rather than an additional real Agent corpus.

### 3.2 What the official repository exposes

The official [vllm-continuum repository](https://github.com/Hanchenli/vllm-continuum)
is Apache-2.0 and was previously pinned in this project at
`316a58794a6ff86b216e579b74fd56ed0c5a911f`. Its README explicitly calls the
code a preview "without the estimation in the paper." It provides:

- a modified vLLM server and Continuum scheduling mode;
- mini-swe-agent/SWE-Bench execution examples;
- fixed worker concurrency (`--workers N`);
- Poisson program arrivals (`--use-jps --jps X`);
- aggregate analysis and pass-rate submission paths.

It does **not** publish the paper's 200 collected per-program traces, exact GPT-5
messages, submitted token IDs, or per-turn timestamps/tool gaps. The repository
examples are reproducible acquisition instructions, not a byte-for-byte paper
replay bundle. This is consistent with the prior project
[W0 source audit](../continuum-workload-source-audit.md).

## 4. Public source inventory

### 4.1 SWE-Bench + mini-swe-agent

| Property | Finding |
| --- | --- |
| Public scale | SWE-Bench Verified contains 500 human-validated tasks |
| Download | Hugging Face `princeton-nlp/SWE-bench_Verified`; project W0 pinned revision `c104f840cc67f8b6eec6f759ebc8b2693d585d4a` |
| Licensing | SWE-bench code is MIT; upstream repositories retain their own licenses; mini-swe-agent is MIT |
| L0 task input | Yes: instance ID, issue, base revision, tests/patch metadata |
| Public paper trace | No |
| Public trace alternatives | Locally acquired W1 traces; third-party SWE-Gym/OpenHands traces |
| Required fields | Program identity and task source exist; prompts, tools and timing exist only after acquisition; exact submitted tokens require the pinned tokenizer/runtime sidecar |
| Phase 5 status | **Preferred primary source, acquisition required for new tasks** |

The project already has an acquisition wrapper that records cumulative messages,
model submit/completion clocks, tool start/end clocks and content hashes. Its
tokenizer observer is correctly labelled
`DETERMINISTIC_LOCAL_TOKENIZATION_NOT_RUNTIME_SUBMISSION`; therefore runtime
submission identity still needs the Native replay validation path.

### 4.2 BFCL v4 Web Search

The official [BFCL v4 description](https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html)
defines 200 Web Search cases: 100 snippet and 100 no-snippet cases. The broader
Agentic set has 665 cases (200 Web Search + 465 Memory). The official Gorilla/
BFCL code is Apache-2.0; the data is distributed in the BFCL repository/package.

| Field | Availability |
| --- | --- |
| Question/function definitions | Public |
| Stable case ID | Public |
| Model messages/tool calls | Generated during evaluation, not supplied as the Continuum GPT-5 traces |
| Web results | Time-varying unless a search backend/result corpus is pinned |
| Exact prompt tokens | Not in the task rows |
| Request/tool intervals | Not in the task rows |
| Program/session identity | Can be derived from case ID during acquisition |

BFCL is valuable because its tool pattern differs from shell-heavy SWE-Bench,
but live web search would make both content and latency non-reproducible. Phase 5
should either (a) pin captured search responses and replay them as observations,
or (b) label a live-search run as a newly acquired workload with complete
provenance. It must not claim to reproduce Continuum's private BFCL traces.

### 4.3 OpenHands and Multi-SWE-Bench

The official [Multi-SWE-Bench repository](https://github.com/multi-swe-bench/multi-swe-bench)
reports 1,632 curated instances across Java, TypeScript, JavaScript, Go, Rust, C
and C++, selected from 2,456 candidates by 68 annotators. Task rows and execution
environments are public. Dataset licensing must be read from the selected
distribution and pinned; the Hugging Face task card currently labels the license
as `other`, so the report does not infer a blanket redistribution right.

Unlike SWE-Bench Verified, Multi-SWE-Bench also has an official
[trajectory archive](https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench_trajs):
4.73 GB, CC0-1.0 on the current card, with MSWE-agent, MopenHands and other model
archives across languages. These are authentic published Agent executions, but
not necessarily the exact OpenHands/Go trace set used by Continuum. Each selected
archive still needs schema inspection for full messages, tool results, failures,
turn identity and truncation. Exact runtime token IDs and Native timings are not
assumed.

Additional public [SWE-Gym datasets](https://huggingface.co/SWE-Gym/datasets)
include 491 OpenHands SFT trajectories and approximately 6.06K OpenHands sampled
trajectories. They are useful discovery sources, not automatically admissible:
the sampled dataset card does not state a license clearly, and neither source is
the Continuum paper trace bundle.

### 4.4 Trace availability decision table

| Source | Evidence level as downloaded | Directly usable? | Additional work |
| --- | --- | --- | --- |
| Continuum aggregates | Aggregate only | No | Cannot reconstruct traces |
| SWE-Bench Verified | L0 | No | Run/acquire mini-swe-agent; capture sidecar |
| Existing project W1-C | L2 for qualified traces | Yes for engineering/pilot; historical Phase 3 cohort remains sealed | New Phase 5 workload seal and exposure screen |
| BFCL v4 task data | L0 | No | Pin tool backend/results; acquire messages, clocks and tokens |
| Multi-SWE-Bench tasks | L0 | No | Select environment/agent and acquire, or pair with published trajectories |
| Multi-SWE-Bench trajectories | L1 candidate | Conditional | Inspect archive schema/license; retokenize and produce L2 seal |
| SWE-Gym/OpenHands trajectories | L1 candidate | Conditional | Pin revision/license; validate full messages/tools/failures |
| Controlled fixed/Poisson arrivals | L2 timing after seal | Yes as controlled load only | Record generator, seed, rate and realized offsets |

## 5. Existing replay capability audit

### 5.1 Capability matrix

| Requirement | Current state | Evidence and boundary |
| --- | --- | --- |
| Multiple independent programs in a trace | **Available structurally** | `Phase2Trace` accepts arbitrary program IDs; validates unique request IDs, contiguous turns and non-decreasing per-program arrivals |
| Interleave programs while preserving within-program order | **Available structurally** | Actions are globally ordered by planned arrival; per-program turn/arrival order is validated |
| Controlled Native replay for 2/4/8/16 programs | **Needs extension** | `materialize_request_boundaries()` rejects anything other than exactly two sessions; accepted campaign uses max concurrency 2 |
| Preserve exact prompt token IDs | **Available when supplied** | `replay_token_ids_by_request` plus expected submission hashes; Native observations verify actual prompt identity |
| Infer exact tokens from public messages | **Not available** | Chat template, tokenizer/model revisions and runtime submission must be pinned; local tokenization is not runtime proof |
| Tool gaps | **Available** | `PlannedRequest` carries `next_tool_type` and `tool_gap_seconds`; W1 acquisition records observed tool clocks |
| Fixed arrival | **Available** | Frozen `planned_arrival_offset_seconds` and controlled logical clock |
| Poisson arrival generation | **Not implemented as a frozen project module** | Precomputed offsets can be replayed, but there is no seed/rate/generator manifest and validator equivalent to the official runner |
| Different concurrency | **Partially available** | Runner accepts `max_inflight`; current timeline/drain behavior and materializers are two-session specific |
| Actual enqueue-order verification | **Available after execution, not enforced by generic runner** | Phase 3 actual-order audit can compare submitted order; Phase 5 needs this as a per-run fail-closed gate |
| Full legal Entry Release candidates | **Available at decision layer** | `FORCED_RELEASE_DECISION` records candidate audits and chosen releases |
| Candidate-to-physical-block identity | **Conditional** | Prefix snapshots and SelectionPlan/physical outcome can map block/hash/process identity; missing or invalidated snapshots fail closed |
| Downstream recompute causality per victim | **Not established** | Historical Gate O limitation remains; later evictions/recomputation cannot be attributed merely by temporal adjacency |

### 5.2 Replay semantics that matter for Phase 5

The generic trace schema is more general than the controlled executor. The
controlled executor advances a logical clock without sleeping, accumulates
arrivals to the inflight ceiling, submits them, and drains Native work before
crossing later logical boundaries. That gives a deterministic bounded replay,
but it is not equivalent to a continuous event-driven Poisson system where
arrivals, completions and tool returns overlap arbitrarily.

For Phase 5, "supports concurrency 16" must mean more than setting
`max_inflight=16`. The implementation must prove:

- an arbitrary number of non-empty sessions is accepted;
- each session's next turn cannot arrive before its frozen predecessor/tool gap;
- realized Native submissions match the frozen total order (or an explicitly
  permitted tie equivalence class);
- no full drain silently serializes an intended overlap;
- fixed and Poisson inputs produce the same evidence contract;
- the same realized arrival sequence is used across compared arms.

### 5.3 Native candidate and physical evidence

The project can record the logical candidate set at each forced Entry Release
and validate selections. `VLLM_PREFIX_SNAPSHOT` carries ordered block IDs,
hashes, cache keys and process identity; `NATIVE_ENTRY_RELEASE_SELECTION_PLAN`
and physical outcomes bind a real plan to later Native observations. The
read-only shared-retention audit rejects missing snapshots, differing block
lists, unequal block/hash/key lengths and pre-decision invalidation.

This is sufficient to measure **candidate exposure** if Phase 5 requires, for
every relevant decision:

- number of legal candidates;
- number with complete cost evidence;
- score/order and selected Entry;
- planned block IDs and content identity;
- matched/unmatched/hashless physical outcomes.

It remains insufficient to claim that a particular victim caused a later
recomputed-token delta unless the new protocol supplies a causal link. Phase 5
should keep decision exposure and downstream performance as separate outcomes.

## 6. Necessary engineering changes (not implemented in this report)

### Required before a formal Phase 5 run

1. **N-session timeline materializer.** Generalize the two-session boundary
   builder and pressure-join assumptions to 2/4/8/16 programs without changing
   A0/A1/A2/A3.
2. **Event-driven bounded executor.** Submit arrivals up to the concurrency
   ceiling without an unintended full-drain barrier; define tie handling and
   completion/tool-return causality explicitly.
3. **Frozen arrival generator.** Add fixed and Poisson modes with algorithm,
   PRNG, seed, JPS, realized offsets and SHA-256 manifest. Generate once and
   reuse exactly across arms.
4. **Execution conformance gate.** Compare actual submitted request sequence,
   per-program order, logical boundaries and concurrency against the seal.
5. **Phase 5 workload seal.** Bind source revision/license, message and tool
   content, tokenizer/chat template/model, exact token IDs, arrival timeline,
   right-censoring, program mapping and permitted truncation.
6. **Candidate-exposure evaluator.** Require complete decision candidate audits
   and candidate-to-block mapping; report missingness separately from zero
   competition.
7. **Context admission check.** Reject/truncate only by a predeclared rule before
   observing policy outcomes; the paper's 70K--93K tokens/program exceed the
   current 32,768-token per-request ceiling when naively materialized.

### Useful but not required for first feasibility pilot

- BFCL frozen search-response recorder;
- schema adapters for selected Multi-SWE/OpenHands trajectory archives;
- workload-level exposure predictor based only on prefix geometry and schedule;
- richer scheduler iteration and cache-publication events.

### Currently unavailable without new runtime evidence

- exact reconstruction of Continuum's private GPT-5 traces;
- proof that public trajectory tokens match a different model's native prompt;
- per-victim downstream recomputation causality;
- production arrival-distribution claims from a seeded Poisson generator.

## 7. RTX 4090 D resource assessment

### 7.1 Frozen environment anchor

The reference environment is the previously validated RTX 4090 D (24,564 MiB),
Qwen2.5-Coder-1.5B-Instruct, vLLM 0.27.1, PyTorch 2.13.0+cu130, CUDA 13.0,
BF16 KV, block size 16, `max_model_len=32768`, and
`max_num_batched_tokens=2048`. Prior Native runs used a 2,048-block pool and
observed approximately 5.2 GiB device use during active execution. That is an
empirical anchor, not a guarantee for every Phase 5 cell.

For the model's 28 layers, 2 KV heads and head dimension 128, BF16 KV costs:

`28 layers × 2(K,V) × 2 heads × 128 × 2 bytes = 28,672 bytes/token`.

At 16 tokens/block, this is 448 KiB/block. Candidate capacity tiers are:

| Tier (planning label only) | Blocks | Token slots | KV payload | Approx. total GPU use* |
| --- | ---: | ---: | ---: | ---: |
| Low | 512 | 8,192 | 224 MiB | 4.5--5.5 GiB |
| Medium | 1,024 | 16,384 | 448 MiB | 4.7--5.8 GiB |
| High | 2,048 | 32,768 | 896 MiB | 5.1--6.3 GiB |

\* Includes model/runtime/workspace estimate anchored to earlier runs, not a
new measurement. CUDA graphs, batching, attention workspace and allocator
fragmentation can raise the peak. A later authorized capacity preflight must
measure it.

The pool is shared, so increasing program concurrency does not multiply the KV
allocation. It reduces average resident capacity per active program and raises
contention:

| Programs | Low | Medium | High |
| ---: | ---: | ---: | ---: |
| 2 | 4,096 tokens/program | 8,192 | 16,384 |
| 4 | 2,048 | 4,096 | 8,192 |
| 8 | 1,024 | 2,048 | 4,096 |
| 16 | 512 | 1,024 | 2,048 |

These are even-share diagnostics, not scheduler guarantees. The 16-program/low
cell is likely a pressure stress test rather than a representative operating
point. It may generate repeated allocation failures or single-candidate
releases rather than useful multi-candidate competition.

### 7.2 Expected bottlenecks

| Dimension | Likely bottleneck |
| --- | --- |
| Programs 2 | Too little competition; repeats the Phase 3 exposure problem |
| Programs 4 | Good first realistic exposure point |
| Programs 8 | Strong candidate competition; scheduling and 2,048-token batch cap become important |
| Programs 16 | Queueing, timeline fidelity and context admission dominate; use as bounded stress diagnostic |
| Low pool | May be degenerate for long SWE/BFCL prompts |
| Medium pool | Best primary pressure point |
| High pool | Feasible and closest to prior runtime, but may reduce candidate competition at low concurrency |
| Fixed arrival | Easier paired diagnosis and exposure attribution |
| Poisson arrival | More paper-aligned, but requires one frozen realized sequence per workload cell |
| SWE-Bench | Container/tool acquisition time and long cumulative prompts |
| BFCL | Reproducible web-tool results and highly variable total token volume |

Program totals in the paper (70K/93K mean) are sums over turns, not necessarily
one request. Nevertheless, later cumulative requests may exceed the current
32K context limit. No silent clipping is acceptable. Admission, turn subset or
context-window strategy must be fixed before acquisition/evaluation.

### 7.3 Runtime and campaign-size estimate

Based on earlier 24-request Native cells (roughly 30--50 seconds including
engine initialization) and the much longer Phase 5 programs, conservative
planning ranges are:

| Concurrent programs | Estimated wall time/cell | Confidence |
| ---: | ---: | --- |
| 2 | 1.5--3 min | Low--medium |
| 4 | 3--6 min | Low |
| 8 | 6--12 min | Low |
| 16 | 12--25 min | Low |

These are resource-planning estimates only. Tool execution is replayed, model
initialization strategy and admitted turns materially affect time. One later
authorized calibration cell is needed before a hard budget.

The full requested cross-product is
`4 concurrency × 3 pools × 2 arrivals × 2 workloads = 48 cells`; at three
repeats it becomes 144 runs, plausibly 12--24 GPU-hours. It is too broad for a
first formal study on a single 4090 D.

## 8. Recommended workload design for M1 consideration

### 8.1 Core matrix

Use a staged, predeclared matrix rather than the full cross-product:

- sources: SWE-Bench/mini-swe-agent and BFCL v4 Web Search;
- program concurrency: 4 and 8;
- pools: medium (1,024) and high (2,048) blocks;
- arrivals: paired fixed and frozen Poisson;
- repetitions: three after one non-effect-bearing authorized calibration.

This is 16 cells and 48 repeated runs per arm. It targets the region most likely
to expose multiple legal candidates without making every cell a capacity
failure. It is a feasibility recommendation, **not a frozen Phase 5 protocol**.

Add only bounded diagnostics:

- concurrency 2/high pool: low-exposure control;
- concurrency 16/medium pool: stress boundary;
- low pool at concurrency 4 or 8: only if an offline admission/exposure screen
  proves it is non-degenerate.

### 8.2 Trace selection criteria

Select traces without observing policy outcomes. Pre-register criteria such as:

- at least four model turns;
- complete messages and tool observations;
- exact program/turn identity and terminal/right-censored status;
- no request beyond the frozen context limit;
- nontrivial cumulative prefix growth;
- tool gaps present or explicitly controlled;
- token IDs reproducible under the pinned model/tokenizer/chat template;
- source repository/tool environment legally redistributable or referenceable.

An offline structural exposure screen may count overlapping live programs and
eligible prefix geometry, but must not run A1/A2/A3 to cherry-pick favorable
tasks.

### 8.3 Outcome hierarchy

1. **Primary feasibility outcome:** number and fraction of decisions with at
   least two legal, fully scored candidates.
2. **Decision discrimination:** A0/A1/A3/E0 selection differences and A2 block
   selection differences under the same frozen state.
3. **Performance:** independent recomputed tokens and timing, only when the
   evidence contract is complete.
4. **Physical diagnostics:** matched and unmatched block outcomes, reported
   without manufacturing downstream causal attribution.

This ordering addresses the Phase 3 null result directly: first prove that the
workload creates genuine decision competition, then test whether cost awareness
changes a choice, and only then estimate benefit.

## 9. Risks and unresolved questions

1. **No paper-exact traces.** Exact Continuum reproduction is unavailable from
   public artifacts.
2. **Model mismatch.** GPT-5-generated traces replayed on Qwen 1.5B are workload
   traces, not quality-equivalent live Agent behavior.
3. **Context mismatch.** Paper programs were shaped for 128K Llama context;
   current Native runs cap each request at 32K.
4. **BFCL web drift.** Live results and latency are unstable without a frozen
   backend.
5. **Public-trajectory licensing/schema.** Multi-SWE trajectories are CC0 on the
   current card; individual task repositories and selected OpenHands sources
   need separate provenance review.
6. **Replay semantics.** Current two-session wave/drain behavior cannot support
   the full requested concurrency claim.
7. **Enqueue conformance.** Phase 3 found actual-vs-frozen order deviations;
   Phase 5 must make this an execution-time gate.
8. **Candidate completeness.** Missing prefix snapshots must yield
   `NOT_OBSERVABLE`, not zero candidates.
9. **Physical causality.** Decision-to-block matching does not by itself prove
   later recomputation causality.
10. **Runtime budget uncertainty.** No Phase 5 GPU calibration was authorized;
    runtime ranges remain estimates.

## 10. CPU validation

No GPU execution or large trace acquisition was performed. The following
existing tests were run against the audit baseline and the documentation-only
working tree:

- targeted acquisition, timeline, Native-input, shared-retention, actual-order
  and six-arm materialization tests: **49 passed**;
- full CPU suite excluding the one test whose purpose is to reject any dirty
  worktree: **1,956 passed, 15 skipped, 1 deselected**;
- `git diff --check`: passed.

The unfiltered suite reached **1,636 passed, 7 skipped** before the clean-tree
authorization test rejected the intentionally uncommitted report files. Full
repository Ruff currently reports 27 pre-existing findings outside this
documentation-only change; no Python file was modified in this stage.

## 11. Final readiness verdict

`WORKLOAD_SOURCE_FEASIBILITY = CONDITIONAL_GO`

`EXISTING_REPLAY_FOR_2_PROGRAM_CONTROLLED_RUNS = AVAILABLE`

`EXISTING_REPLAY_FOR_4_8_16_PROGRAM_EVENT_DRIVEN_RUNS = NOT_READY`

`EXACT_CONTINUUM_PAPER_TRACE_REPRODUCTION = NOT_AVAILABLE`

`PHASE5_GPU_CAMPAIGN = NOT_AUTHORIZED`

M1 can proceed to define a bounded engineering and acquisition phase. A formal
Phase 5 protocol should be frozen only after the N-session replay, arrival seal,
actual-order gate, selected source schemas and 4090 D calibration are reviewed.
No production algorithm change is needed to reach that decision point.

## 12. Sources and reproducibility notes

- [Continuum paper, arXiv:2511.02230](https://arxiv.org/abs/2511.02230)
- [Official Continuum preview repository](https://github.com/Hanchenli/vllm-continuum)
- [SWE-Bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)
- [BFCL v4 Web Search](https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html)
- [BFCL data directory](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard/bfcl_eval/data)
- [OpenHands](https://github.com/All-Hands-AI/OpenHands)
- [Multi-SWE-Bench](https://github.com/multi-swe-bench/multi-swe-bench)
- [Multi-SWE-Bench task data](https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench)
- [Multi-SWE-Bench published trajectories](https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench_trajs)
- [SWE-Gym public trajectory inventory](https://huggingface.co/SWE-Gym/datasets)
- Project source: `src/kvopt/workload/phase2.py`,
  `src/kvopt/workload/continuum_bounded_timeline.py`,
  `src/kvopt/workload/continuum_w1a_acquisition.py`,
  `src/kvopt/workload/continuum_bounded_campaign.py`,
  `src/kvopt/runtime/vllm/retention_integration.py`, and
  `src/kvopt/profiling/phase2d_shared_retention.py`.

