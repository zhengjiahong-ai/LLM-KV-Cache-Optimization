# M1 Decision — Historical W1-C Reserve Re-acquisition

**Decision owner:** M1  
**Decision date:** 2026-11-24  
**Review HEAD:** `0c253be00b66ca4f1b0479b19ceb15e1a07f94f1`  
**Status:** RE-ACQUISITION AUTHORIZED; SWE COHORT STILL BLOCKED  
**Selected route:** Existing frozen Historical W1-C ledger-only reserve; no new Sampling Frame.

## 1. Decision basis

The current Phase 5 SWE readiness package reports 35 Q1–Q9-qualified independent Programs against a minimum of 48. The frozen 40 Primary + 24 Phase-3 Reserve candidates have been exhausted. The remaining two infrastructure failures and five unrecoverable records cannot close the gap even if all seven were recovered.

M1 selects the first proposed route: re-acquire the existing 20 Historical W1-C candidates in their frozen order. A new Sampling Frame is not created.

## 2. Frozen source and exact order

- Source: `configs/phase5/phase5-swe-sampling-frame-v1.json`
- Frozen SHA-256: `87cb86fb4d01a15c3498732e549cdf239c475f53e7135e85b29b789727ee5cde`
- Candidate ranks: 65–84 inclusive
- Frozen order:

| Rank | SWE-bench task ID |
|---:|---|
| 65 | `astropy__astropy-8872` |
| 66 | `django__django-11790` |
| 67 | `django__django-13023` |
| 68 | `django__django-13551` |
| 69 | `django__django-13569` |
| 70 | `django__django-14493` |
| 71 | `django__django-15554` |
| 72 | `django__django-16662` |
| 73 | `matplotlib__matplotlib-25311` |
| 74 | `mwaskom__seaborn-3069` |
| 75 | `pallets__flask-5014` |
| 76 | `psf__requests-2931` |
| 77 | `pydata__xarray-3993` |
| 78 | `pylint-dev__pylint-6386` |
| 79 | `pytest-dev__pytest-7982` |
| 80 | `scikit-learn__scikit-learn-14983` |
| 81 | `sphinx-doc__sphinx-8593` |
| 82 | `sympy__sympy-15017` |
| 83 | `sympy__sympy-16886` |
| 84 | `sympy__sympy-21596` |

M1 checked this list against the 35 currently qualified Programs and the 22 current exclusions in the readiness package at the review HEAD; no task-ID overlap was found. The frozen frame itself remains immutable.

## 3. Re-acquisition requirements

M6 is authorized to re-acquire all 20 candidates as fresh Phase 5 Agent executions, in the exact order above, using the pinned Phase 5 SWE-bench Verified revision and accepted acquisition environment/configuration.

Every new execution must produce fresh Phase 5 evidence:
- raw Agent Trace and append-only request/message/tool records;
- timestamps and clock-domain metadata;
- normalized Trace and exact Token Materialization;
- source, model, tokenizer, chat-template, environment and configuration identities;
- fresh Q1–Q9 evidence and qualification record;
- explicit terminal, failure and right-censoring classification;
- raw/normalized/token/fixture hashes and manifest bindings.

Historical W1-C traces, token IDs, timings, Native evidence, qualification results and policy outcomes are not Phase 5 evidence. They must not be copied, promoted, replayed as new evidence, or used to qualify the fresh execution. Historical identity may be retained only as provenance explaining why the task is in this reserve.

Preserve the existing Q1–Q9, exact-token, context, source/license, Program identity and terminal requirements. Preserve right-censoring explicitly. Do not restore the removed fixed 16-Turn ceiling. No synthetic Turns, duplicated requests, fabricated tool results, artificial task splitting or silent truncation.

All 20 candidates are in the authorized acquisition frame; do not stop acquisition early or reorder candidates based on outcomes. Retain every attempt and rejection in an append-only ledger.

## 4. Qualification and cohort rule

The existing 35 Programs remain candidates pending M4's independent review. The minimum design requires 48 distinct qualified Programs: 16 for four Calibration Groups and 32 for eight minimum Formal Groups.

At least 13 of the 20 fresh re-acquisitions must independently pass Q1–Q9 and M4's identity/provenance review. Only then may M4 construct disjoint Calibration/Formal Groups under the frozen four-Program Group rule and submit the Cohort and Workload Seal proposal to M1.

If fewer than 13 qualify, retain `BLOCKED_INSUFFICIENT_INDEPENDENT_QUALIFIED_PROGRAMS`. Do not lower the minimum, relax qualification, promote historical W1-C evidence, or substitute tasks outside the frozen frame. Any further source expansion requires a separate M1 decision.

## 5. BFCL Derived boundary

The BFCL Derived 4 Calibration + 8 Evaluation package remains a separate supplementary dataset and does not contribute to SWE formal sample size, Cohort membership, power or confirmatory inference. M4 performs its targeted independent review separately.

## 6. Authorization boundary

Authorized:
- fresh Phase 5 re-acquisition of all 20 frozen Historical W1-C reserve task IDs;
- normalization, Token Materialization, Q1–Q9 qualification, provenance/identity review, and append-only evidence packaging.

Not authorized:
- Native/GPU Conformance;
- SWE Calibration or Formal execution;
- BFCL Derived execution;
- any other GPU experiment.

After data-package acceptance, the project proceeds through unified D gates and then separately authorized E execution.
