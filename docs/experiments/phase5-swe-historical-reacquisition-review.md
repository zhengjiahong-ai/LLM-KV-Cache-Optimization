# Phase 5 SWE Historical Reserve Reacquisition Review

**Status:** minimum 48-Program count and fresh-provenance gates passed;
independent M4 qualification and Cohort review pending. No Workload Seal or GPU
execution is authorized. The v2 package supersedes the initial count-only
review package without rewriting it.

## Scope

M1 authorized fresh Phase 5 acquisition of the 20 pre-registered
`HISTORICAL_W1C` reserve identities at ranks 65--84. Historical W1-C traces,
timings, token IDs, Native evidence and outcomes were not reused. All 20 fresh
Agent executions completed in the frozen order.

## Reconciliation

| Stage | Result |
| --- | ---: |
| Fresh Phase 5 attempts | 20 / 20 completed |
| Adapted with complete recoverable evidence | 17 |
| Excluded before normalization | 3 |
| New Q1--Q9 qualified Programs | 13 |
| New Q1--Q9 exclusions | 4 |
| Previously accepted qualified Programs | 35 |
| Cross-batch Program overlap | 0 |
| Combined independent candidate Programs | 48 |

The three pre-normalization exclusions preserve their raw attempts but cannot
recover an exact complete Tool Result from the immutable trajectory. No output
was inferred, synthesized or silently truncated. The four mechanical
qualification exclusions comprise two `Q1_COMPLETE_PAYLOAD` failures and two
`Q6_CONTEXT_AND_EXACT_TOKENS` failures. No automatic retry was performed.

Each fresh attempt is bound to a stable Phase 5 attempt ID, rank, start/finish
timestamps, model/tokenizer/config/dataset/runtime identities, `run.json`,
trajectory and sidecar SHA-256. These hashes are independently compared with
both historical W1-C S50 and S100 artifacts for the same task. The observed
historical-artifact hash match count is zero. The package also carries exact
copies of the batch manifest, M1 authorization and Sampling Frame as lineage.

## Claim and authorization boundary

The 48 identities form a candidate pool for M4's independent source,
identity, qualification, censoring and outcome-blind review. This package does
not construct Calibration or Formal Groups, select a Cohort, issue a Workload
Seal, authorize GPU execution, or establish algorithm benefit.

The current machine-readable review metadata is stored in
[`phase5-swe-historical-reacquisition-data-v2`](phase5-swe-historical-reacquisition-data-v2/).
The [initial count-only package](phase5-swe-historical-reacquisition-data/) is
retained as review history and is not the current provenance authority.
Raw Agent traces, full normalized/token evidence and private acquisition
artifacts remain outside the tracked documentation package and are bound by
SHA-256.

## Review-package hashes

- Attempt and old-evidence isolation ledger:
  `3875c9dbfc9326e47db12235f3246fae10cde4c287b3f2a54ac9b77a7a4dbaf2`
- Combined 48-Program candidate inventory:
  `575665709114ad3c9741d9c903f8356342eb14cca9bbb56b517f414c3cd1e4db`
- Review summary:
  `352beb2ae2f73645a4190dd0e23393812b5df3fd5a7c9de92a58d89076c7cff4`
- Review-package manifest:
  `3e7f05808cacc7efba37d89d257fc710a679d8f649221c15b6a65242b9ba7b3f`

The review summary binds the frozen Sampling Frame, M1 authorization, original
35-Program inventory, 20-attempt batch manifest, conversion report, processed
collection summary and processed evidence manifest.
