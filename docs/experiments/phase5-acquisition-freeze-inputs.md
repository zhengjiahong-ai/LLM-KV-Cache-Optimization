# Phase 5 Acquisition Freeze Inputs

**Decision owner:** M1; **research qualification:** M4; **acquisition:** M6  
**Status:** FROZEN ACQUISITION INPUTS — NOT A FORMAL COHORT, NOT A GPU AUTHORIZATION  
**Date:** 2026-11-20  
**Source baselines:** SWE-bench Verified `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`; BFCL v4 Web Search `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`

---

## 1. Frozen decisions

| Item | Frozen decision |
|---|---|
| SWE sampling frame | `configs/phase5/phase5-swe-sampling-frame-v1.json`; 84 task IDs, 40 Primary, 24 Phase-3 Reserve, 20 historical W1-C reserve |
| SWE frame SHA-256 | `87cb86fb4d01a15c3498732e549cdf239c475f53e7135e85b29b789727ee5cde` |
| Phase-3/W1-C historical candidates | Allowed only as marked **`HISTORICAL_REUSE_RESERVE` / ledger-only**; not formal without a new M1 authorization and re-acquisition |
| BFCL source revision | `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` (immutable commit) |
| BFCL source raw file SHA-256 | `6fc41d96d003dc849028966a782923560d2fc127ed2088aa967f06daaafa4268` |
| BFCL formal evaluation cases | 100 `SNIPPET` + 100 `NO_SNIPPET` = 200 cases, derived from the 100 source questions |
| BFCL frame SHA-256 | `ce8b2e93cdf40106459338c298dab95a3081c6c34bf8f0666eab97fdd2842c07` |
| License conclusion | `CONDITIONAL_INTERNAL_RESEARCH`; redistribution/publication **not cleared**; third-party search page/snippet content separately restricted |
| Outcome-blind | No execution/policy/native outcome may select, exclude, promote or replace a candidate |

The SWE frame and BFCL frame are **candidate/acquisition frames**, not the formal Cohort. M6 may execute them in the frozen order; M4 will construct the formal Groups only after Q1–Q9 and the calibration-selected N are frozen.

---

## 2. SWE-bench Verified sampling frame

### 2.1 Source and construction

- Dataset: `princeton-nlp/SWE-bench_Verified`, `default/test`.
- Revision: `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`.
- Source plan: `configs/phase3/phase3-cohort-candidate-plan-v1.json`.
- Source plan candidate-assignment SHA-256: `4b44ddcb5e5dd342efb9f456f614115bb002600e76f13b7abddc210d16e23ef6`.
- Source sampling-freeze SHA-256: `a1fd9554d55c934590c30fd55768c617c8283a7203ece316121a057b1db3985f`.

The frame preserves the Phase-3 pre-registered outcome-blind order:

1. 40 `PRIMARY` candidates by `acquisition_rank`;
2. 24 Phase-3 `RESERVE` candidates by `role_rank`;
3. 20 W1-C historical IDs, only as `HISTORICAL_REUSE_RESERVE`.

It contains **84 unique task IDs**. The Phase-3 Primary+Reserve subset is exactly **64 candidates**, matching the formal target of 64 Programs. The 20 historical IDs are a ledger buffer, not automatically admissible formal candidates.

The full ordered list and per-candidate role/source evidence are in the frame JSON. Do not sort or resample it in M6.

### 2.2 Historical candidate decision

**Allowed, with strict labels:**

- Phase-3 candidates: `source_partition=PHASE3_PREREGISTERED`, `prior_evidence=PHASE3_PRE_NATIVE_ONLY`; Phase-5 traces must be newly acquired.
- W1-C historical candidates: `source_partition=HISTORICAL_W1C`, `candidate_role=HISTORICAL_REUSE_RESERVE`, `prior_evidence=HISTORICAL_W1C_EXPLORATORY_ONLY`; ledger-only.
- Historical evidence must never be reused as Phase-5 raw/trace evidence, and prior outcomes must not select or promote a candidate.
- W1-C historical candidates cannot enter the formal Cohort without a new M1 decision. If Phase-3 reserves cannot provide 64 qualified Programs, the run reports `NOT_FEASIBLE` rather than silently substituting historical candidates.

### 2.3 Reserve promotion

Promotion is allowed only for a pre-registered Phase-5 qualification failure:

- Q1–Q9 evidence failure;
- fewer than 4 or more than 16 real Turns;
- missing tool result or non-recoverable right-censor;
- license/provenance rejection;
- token/context materialization failure;
- adapter/schema failure.

Promotion order:

```text
Phase-3 RESERVE by role_rank
  -> if still insufficient: M1 decision on historical W1-C
  -> otherwise NOT_FEASIBLE
```

No algorithm outcome, candidate exposure, decision divergence, victim set or recomputation metric may trigger promotion. All failures and promotions remain in the ledger.

---

## 3. BFCL v4 Web Search sampling frame

### 3.1 Source

- Repository: `ShishirPatil/gorilla`.
- Revision: `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`.
- Source file: `berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_web_search.json`.
- Raw bytes: **36,984**.
- Raw SHA-256: `6fc41d96d003dc849028966a782923560d2fc127ed2088aa967f06daaafa4268`.
- Source questions: **100** human-crafted multihop questions.

The source repository has **100 questions**. BFCL evaluates them in two search configurations:

- `SNIPPET`: `show_snippet=true` (100 cases);
- `NO_SNIPPET`: `show_snippet=false` (100 cases).

This yields **200 formal evaluation cases**, not 200 independent source questions. The frame records `source_case_id` and `search_mode` separately.

### 3.2 Case identity and content hash

Formal case ID:

```text
bfcl_<source_case_id>:<snippet|no_snippet>
```

Per-case `content_sha256` is computed over the canonical JSON:

```json
{
  "source_case_id": "web_search_0",
  "search_mode": "SNIPPET",
  "show_snippet": true,
  "question": "...",
  "involved_classes": ["WebSearchAPI"]
}
```

using sorted keys and compact separators. The full 200-case list, mode, source ID and content SHA are in `configs/phase5/phase5-bfcl-sampling-frame-v1.json`.

### 3.3 Search-result fixtures

The BFCL case frame is **not** a search-response fixture. For every case M6 must capture and freeze:

- provider and backend identity/version;
- collection timestamp and clock domain;
- query and parameters;
- response bytes and SHA-256;
- source URL, title, snippet body (if mode permits) and rank;
- HTTP/network/tool error, including retries and 403/429/503/timeout;
- page-fetch mode and raw content hash where applicable;
- whether the result was supplied as a snippet or requires URL fetch.

Formal Replay must use the frozen fixture, never live search. A missing/failed fixture is a recorded acquisition failure, not a synthetic success.

---

## 4. License and third-party content audit

This is a **technical/provenance review**, not legal advice.

| Source | Verified license | Conclusion |
|---|---|---|
| SWE-bench repository code | MIT | Internal research use; upstream repository code and patches retain their own licenses |
| SWE-bench Verified dataset rows | Dataset card/revision reference; license metadata not independently re-verified here | Conditional internal research; redistribution requires separate review |
| mini-SWE-agent | MIT | Internal research use; preserve license notice |
| BFCL/Gorilla repository code | Apache-2.0 | Internal research use; preserve notice |
| BFCL question data | Distributed in the Apache-2.0 repository; data-specific terms not separately asserted | Conditional internal research; do not claim a separate data license |
| BFCL search snippets/pages | Third-party content; not relicensed by BFCL/Apache-2.0 | Internal fixture only; no redistribution/publication without per-source review |
| Upstream SWE task repositories | Each repository's own license | Patch/source content must be handled per repository; no blanket MIT claim |

**Frozen conclusion:**

```text
LICENSE_TECHNICAL_REVIEW = CONDITIONAL_ACCEPTED_FOR_INTERNAL_RESEARCH
REDISTRIBUTION_OR_PUBLICATION = NOT_CLEARED
THIRD_PARTY_SEARCH_CONTENT = SEPARATE_TERMS
```

M6 may acquire and retain raw evidence for internal research. It may not publish, redistribute or externally serve third-party search snippets/pages, or relicense SWE upstream patches, without a separate review.

---

## 5. Outcome-blind and Cohort boundary

- Candidate ordering comes only from the frozen source plans above.
- Q1–Q9 is mechanical; semantic/license review is M4.
- No policy/native outcome, candidate exposure, selection divergence, victim set or recomputation metric may affect inclusion, exclusion, replacement or promotion.
- Calibration and formal Groups remain unselected until the calibration-selected N is frozen.
- The SWE frame is not the formal Cohort; the BFCL frame is not a formal Cohort or a search fixture.
- Failed, incomplete, censored and rejected attempts remain in the acquisition ledger.
- No synthetic Turns, duplicated requests or fabricated tool outputs may fill a Group.

---

## 6. M6 immediate actions

1. Acquire SWE-bench tasks in the frame's `phase5_rank` order, starting with `PRIMARY`, then `RESERVE`; do not use historical reserve without M1.
2. Preserve raw trace, sidecar, normalized trace, token materialization, Q1–Q9 evidence and failure ledger.
3. Acquire BFCL in `phase5_case_index` order with the frozen snippet/no-snippet mode and capture complete search fixtures.
4. Run Q1–Q9 and write per-Session acceptance/rejection evidence.
5. Return the acquisition ledger, fixture hashes, yield/missingness and proposed qualified pool to M4.
6. Do not select the formal Cohort, calibrate, execute GPU, or reuse historical outcomes.
