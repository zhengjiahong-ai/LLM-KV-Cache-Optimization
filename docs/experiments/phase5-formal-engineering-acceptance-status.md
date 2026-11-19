# Phase 5 Formal Campaign Engineering Acceptance Status

**As of:** 2026-11-19  
**Integrated main before documentation update:** `4a8ff8e3f9c3829be4fd542f8a19132f1837d753` (PR #124)  
**Current status:** CPU/Mock engineering integration substantially complete; dataset acquisition and all Native/GPU gates remain outstanding.  
**GPU Calibration / Formal execution:** NOT STARTED; NOT AUTHORIZED.

## 1. M1 disposition

M1 accepts M4's six-system trace-driven research design and approves construction of SWE-bench Verified and BFCL v4 Web Search Agent Trace datasets. The handoff is recorded in [Phase 5 Dataset Acquisition & Construction](phase5-dataset-acquisition-and-construction.md).

New acquisition and dataset-construction execution are temporarily paused while canonical documentation and ownership records are synchronized. Once this documentation pause is lifted, the limited work authorization covers source acquisition, real Agent Trace capture, immutable raw retention, BFCL fixture construction, normalization, Token Materialization, Q1–Q9 qualification and outcome-blind Cohort preparation. It does not authorize Native GPU Conformance, Calibration or Formal execution.

The machine-readable protocol remains `DESIGN_FROZEN_CANDIDATE` with `execution_authorized=false`. This status document does not modify protocol JSON or its hashes.

## 2. Integrated CPU/Mock path

PR #124 merged the Phase 5A–5E engineering assets, DVA-ER adapter integration and six-system campaign infrastructure.

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Protocol/schema/hash validation | PASS | structural and identity validation only |
| Generic Trace contract / normalization boundary | PASS | no Phase 5 source cohort acquired |
| Q1–Q9 mechanical qualification | PASS | evaluator mechanics; not a qualified real dataset |
| Token Materialization contract | PASS | exact IDs still need to be produced and provenance-bound |
| Workload Seal mechanics | PASS | no Formal Cohort selected or sealed |
| N-session Replay / Frozen-Poisson planning | PASS | CPU planning contract; not Native concurrency |
| Six-system matrix and routing | PASS | execution contract only |
| DVA-ER v1 core correctness | PASS | 28 focused CPU tests; does not freeze formal candidate |
| DVA-ER candidate adapter | PASS | CPU integration; formal candidate-selection gate remains open |
| Independent metrics and N/E/C evaluation | PASS | evaluator contract; no new Phase 5 Native results |
| Group-level analysis / Calibration backend | PASS | statistical implementation only; no Calibration runs |
| Manifest / deterministic archive | PASS | archive round-trip contract only |
| Phase 5E Part A Mock pipeline | PASS | not Native/GPU Conformance |
| Production-shaped Phase 5E Native runner wiring | PASS | CPU-injected path; live GPU run not performed |

PR #124 reported:
- Phase 5/DVA targeted suite: **285 passed, 1 skipped**;
- repository CPU regression: **2,241 passed, 16 skipped**;
- separate clean-worktree authorization test: **1 passed**;
- frozen 10,000-resample Calibration bootstrap, Ruff and diff checks: **PASS**.

These results establish software-contract and CPU/Mock integration. They do not establish live EngineCore/BlockPool behavior, real Pressure execution, Native concurrency, GPU conformance, data qualification or algorithmic benefit.

## 3. Dataset state

| Item | Status |
| --- | --- |
| SWE-bench Verified task source | Revision recorded in protocol; new Phase 5 Agent Trace acquisition not completed |
| mini-SWE-agent acquisition | Version/path identified; Phase 5 acquisition not completed |
| BFCL v4 Web Search | 200-case source family selected; exact immutable revision and license/provenance audit required |
| Frozen search fixtures | Not acquired or sealed |
| Raw Phase 5 Trace Archive | Not created |
| Normalized Phase 5 Trace set | No qualified Phase 5 source traces |
| Token Materialization | No Phase 5 Cohort materialized |
| Q1–Q9 qualification | Evaluator implemented; no Phase 5 Cohort has passed |
| Calibration Groups | Not selected |
| Formal Groups | Not selected |
| Formal Workload Seal | Not created |

Historical W1-C traces and Phase 3/4 archives may support parser development or explicitly exploratory diagnostics. They must not silently become the independent Phase 5 confirmatory Cohort. Any exception requires explicit source-lineage and outcome-blind justification and M1 acceptance.

## 4. Six-system and Native gates

| Gate | Status |
| --- | --- |
| DVA-ER CPU correctness | PASS (28 focused tests) |
| DVA-ER formal candidate selection/freeze | OPEN; protocol still says `PROVISIONAL_NOT_FROZEN` |
| Continuum Adapted scheduler conformance | OPEN |
| Continuum Official compatibility/environment audit | OPEN |
| Phase 5E Part A Native GPU Conformance | NOT_RUN |
| Phase 5E Part B Abort Conformance | NOT_READY |
| Actual six-system Native evidence | NOT_RUN |
| Calibration | NOT_RUN |
| Formal sample-size freeze | NOT_RUN |
| Six-system Formal Campaign | NOT_RUN |

The 2026-11-18 pinned-runtime no-GPU audit in the engineering preparation record validates the pinned Python/vLLM API and request-identity contract only. It is not live EngineCore/BlockPool or GPU evidence.

## 5. Protocol and sample plan (design reference)

- Systems: Native, Continuum Official, Continuum Adapted (A0), A1 Original, A3 Suffix and DVA-ER v1.
- Strata: SWE-bench coding-agent traces and BFCL v4 Web Search traces.
- Group: four distinct Programs, one Session per Program.
- Session: 4–16 model-request Turns; preserve source order and observed tool gaps.
- Calibration: four Groups per stratum, three repeats per system; **144 runs total**.
- Formal: eight minimum, twelve target, sixteen maximum Groups per stratum; two repeats per system; **192 / 288 / 384 runs** at min / target / max.
- Calibration and Formal Groups are disjoint.
- Independent statistical unit: Workload Group, not Turn, request or repeat.
- Exact prompt Token IDs, model/tokenizer/chat-template identity, tool-fixture hashes and Workload/Arrival identities must be bound before comparison.

Formal N is selected by the pre-registered Calibration method. The sample plan is not execution authorization.

## 6. Next work and restrictions

After the documentation pause is lifted:
1. acquire new SWE-bench/mini-SWE-agent and BFCL Web Search traces;
2. freeze BFCL outputs as deterministic, hash-bound fixtures and audit third-party content terms;
3. preserve immutable raw artifacts and source provenance;
4. normalize traces without losing messages, tool calls/results, failures or clock domains;
5. materialize exact prompt Token IDs under pinned model/tokenizer/chat-template revisions;
6. run Q1–Q9 and retain every rejection with explicit reason;
7. construct Calibration and Formal Groups outcome-blind and disjoint;
8. submit Dataset Qualification Report, Workload Seals and SHA-256 manifests for M1 acceptance.

**Not authorized:** Phase 5E GPU Conformance, six-system GPU Calibration, Formal Campaign, or use/reservation of the requested 72–112 GPU-hour envelope. Each requires separate gate review and explicit M1 authorization.

Mock PASS, candidate exposure, predicted victim divergence and physical victim matching do not establish Cost-Aware system benefit.
