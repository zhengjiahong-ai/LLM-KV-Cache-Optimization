# Phase 5 Dataset Acquisition & Construction

**Decision owner:** M1  
**Research design:** M4  
**Acquisition / engineering:** M6  
**Decision date:** 2026-11-19  
**Status update:** 2026-11-20 — PR #125 merged; documentation pause lifted; acquisition authorized to proceed  
**Status:** DESIGN ACCEPTED; DATASET CONSTRUCTION AUTHORIZED  
**GPU execution:** NOT AUTHORIZED

## 1. M1 decision

M1 accepts M4's Phase 5 six-system trace-driven design and approves construction of two primary workload strata:

1. **SWE-bench Verified** — coding-Agent Sessions acquired through the pinned mini-SWE-agent path.
2. **BFCL v4 Web Search** — tool-use Agent Sessions with captured search/tool outputs frozen as deterministic fixtures.

The approved work package includes source acquisition, real Agent Trace capture, immutable raw retention, source-specific normalization, Token Materialization, Q1–Q9 qualification, outcome-blind Group construction, and submission of the dataset evidence package.

**Documentation synchronization:** PR #125 merged on 2026-11-19 at `5e453a6926e3c1092235b2ec2e8b6227a22362f3`. The temporary documentation-control pause is lifted. M6 may proceed with the approved acquisition and construction work package; M4 performs independent source, license, outcome-blind and Cohort review.

This is a limited acquisition decision. It does not alter the hash-bound Formal Protocol JSON, authorize GPU work, or make the Formal Campaign executable.

## 2. Frozen research shape

- One Program is one logical Agent task/workflow.
- One Session is one acquired execution of one Program.
- One Turn is one model request in that Session.
- Each qualified Session must contain **4–16 real Turns**.
- Each Workload Group contains **4 distinct Programs**, one Session per Program.
- Workload Group is the independent statistical unit.
- Preserve within-Session Turn order and observed tool gaps.
- Each Group is replayed across all six systems and repeats with the same frozen Trace, Token IDs and Arrival realization.

No synthetic Turn, duplicated request, fabricated tool output, or artificial task split may be used to meet the minimum Turn count. Ineligible candidates remain in the acquisition ledger with explicit rejection reasons.

| Partition | Groups per stratum | Programs per stratum | Repeats per system |
| --- | ---: | ---: | ---: |
| Calibration | 4 | 16 | 3 |
| Formal minimum | 8 | 32 | 2 |
| Formal target | 12 | 48 | 2 |
| Formal maximum | 16 | 64 | 2 |

At the target, each stratum needs 64 qualified Programs (16 Groups total); across two strata this is 128. At the maximum, each stratum needs 80 Programs; across two strata this is 160. These are qualified counts, not candidate-pool sizes. M4/M6 must plan a pre-registered reserve using source/evidence quality only.

Calibration and Formal Groups must be disjoint. Formal N is determined by the pre-registered Calibration procedure. No lowering the minimum or outcome-informed extension/replacement.

Run counts are design references only:
- Calibration: 2 × 4 × 6 × 3 = **144**.
- Formal minimum / target / maximum: **192 / 288 / 384**.

## 3. Acquisition and evidence pipeline

`Source task/revision → Raw Agent Trace → Normalized Trace → Token Materialization → Q1–Q9 Qualification → Outcome-blind Groups → Workload Seal / Manifest`

### SWE-bench

Use the protocol-pinned SWE-bench Verified revision `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`, unless a separately reviewed M1 decision supersedes it. Pin mini-SWE-agent, agent configuration, model/provider identity, tokenizer and chat template. Public task rows and patches are L0 task inputs, not replayable Agent Traces. Keep upstream repository licenses distinct from the benchmark and agent licenses.

### BFCL Web Search

Use the BFCL v4 Web Search source family (200 cases: 100 snippet and 100 no-snippet). Record the exact immutable revision and selected case IDs before sealing. Capture actual model/tool interactions and every search response. Freeze fixtures with provider, collection time, query, source URL, response bytes/hash, errors and retrieval metadata. Audit third-party content terms separately; BFCL's repository license does not automatically license external page content. Formal Replay must use fixtures, never live search.

### Required raw evidence

For every acquisition attempt retain source revision/task ID, agent version/config/code revision, model identity, complete messages, tool calls/arguments/results/errors, timestamps with clock domains, terminal/failure/truncation/right-censor state, raw bytes and SHA-256, and license/provenance information. Failed, incomplete and censored attempts remain recorded.

### Token Materialization

Pin model, tokenizer and chat-template revisions. Store rendered prompt identity, exact Token IDs, Token-ID hash and revision/template hashes per request. Local tokenization is not proof of Native submission; Native identity is checked later. Context overflow is rejected, never repaired by silent truncation.

### Qualification and Cohort construction

M6 runs mechanical Q1–Q9 and retains per-rule evidence and every rejection. M4 independently reviews semantic completeness, provenance/license, censor reasons, diversity, outcome blindness and qualification. M4 constructs four disjoint Calibration Groups per stratum and Formal Groups at the Calibration-selected N (8 minimum, 12 target, 16 maximum). Reserve promotion uses only predeclared evidence-quality rules.

No algorithm outcome, candidate exposure, selection divergence, victim set or recomputation metric may influence inclusion, exclusion or replacement.

## 4. Ownership

**M6 — acquisition and engineering**
1. Implement SWE-bench and BFCL source-specific Trace adapters.
2. Execute acquisition and capture immutable raw evidence.
3. Build/hash BFCL fixtures.
4. Produce normalized traces and Token Materializations.
5. Run Q1–Q9 and retain failures/rejections.
6. Produce source inventories, provenance manifests and reproducible packaging.
7. Report yield, missingness, failure/censor distribution and resource cost.

**M4 — research qualification and Cohort**
1. Freeze source revisions and task sampling frames before acquisition.
2. Review licenses, provenance and third-party fixture terms.
3. Audit Q1–Q9 semantics and adapter completeness.
4. Verify outcome-blind selection and reserve rules.
5. Construct disjoint Calibration/Formal Groups and audit independence/diversity.
6. Submit Dataset Qualification Report and proposed Workload Seals to M1.

**M1 — final authority**

M1 retains authority over source exceptions, Cohort Seal acceptance, formal protocol freeze, Native/GPU gates, resource authorization and Formal Campaign. Routine acquisition/normalization/qualification requires no step-by-step approval after the documentation pause is lifted. Material protocol changes, source substitutions, license exceptions, outcome-informed selection or sample-minimum changes require a new M1 decision.

## 5. Required dataset package

- source/task inventory and immutable revisions;
- complete Raw Trace Archive, including rejected/failed attempts;
- raw SHA-256 manifest;
- normalized Trace set and adapter/version identity;
- Token Materialization and model/tokenizer/template hashes;
- BFCL frozen fixtures and third-party content provenance/license audit;
- Q1–Q9 per-Session matrix with evidence and rejection reasons;
- source/license/provenance report;
- acquisition yield and missingness report;
- outcome-blind sampling and reserve-promotion record;
- disjoint Calibration/Formal Group manifests;
- Workload Seal(s), Arrival Plan identity and canonical hashes;
- independent M4 Dataset Qualification Report.

## 6. Non-authorizations

This decision does **not** authorize Phase 5E Part A/B Native GPU Conformance, six-system GPU Calibration, Formal Campaign, or use/reservation of the requested 72–112 GPU-hour envelope. Each requires separate gate review and explicit M1 authorization.

The machine-readable Formal Protocol remains `DESIGN_FROZEN_CANDIDATE` with `execution_authorized=false`. DVA-ER formal candidate freeze/selection, Continuum Official compatibility, Continuum Adapted scheduler conformance, Native conformance, Calibration, final sample-size freeze, resources and execution manifests remain gates.

## 7. Checklist

- [x] M1 accepts M4's six-system research design.
- [x] SWE-bench Verified and BFCL v4 Web Search selected as primary strata.
- [x] Dataset construction approved in principle.
- [x] Documentation synchronization complete (PR #125 merged); pause lifted.
- [ ] New Phase 5 SWE-bench Agent Traces acquired.
- [ ] New Phase 5 BFCL Agent Traces and frozen fixtures acquired.
- [ ] Token Materialization complete.
- [ ] Q1–Q9 qualification complete.
- [ ] Calibration/Formal Cohorts constructed and independently reviewed.
- [ ] Workload Seal and SHA-256 manifests accepted by M1.
- [ ] Separate Native/GPU and Calibration/Formal authorization granted.
