# Phase 5 SWE Formal Dataset Readiness

**Workload:** SWE-bench Verified
**Status:** `BLOCKED_INSUFFICIENT_INDEPENDENT_QUALIFIED_PROGRAMS`
**Calibration/Formal Cohort selected:** no
**Workload Seal issued:** no
**GPU execution:** not authorized

## Current evidence

This package independently inventories the latest processed collection under the current no-additional-Turn-ceiling protocol and exact Q1–Q9 contract.

- Frozen new-acquisition frame: 40 Primary + 24 Reserve = 64 Programs.
- Acquisition attempts: 75; unique completed Programs: 62.
- Converted and processed Sessions: 57.
- Q1–Q9 qualified Sessions: 35.
- Independent qualified Program identities: 35; no duplicate Program identity was found.
- Qualified terminal classes: 2 Natural Terminal and 33 explicitly Right-Censored.
- Excluded Sessions: 22.
- Current capacity: 8 complete four-Program Groups plus 3 ungrouped Programs.

The current sole-formal-stratum design needs at least 48 distinct qualified Programs: 16 for four Calibration Groups and 32 for eight minimum Formal Groups. The verified shortfall is therefore 13 Programs.

## Why Cohort construction stops here

The 64-Program new-acquisition frame has already been exhausted. Two frozen candidates remain unresolved infrastructure failures, and five completed records were excluded before normalization because their elided tool results cannot be recovered. Even if all seven became qualified, the pool would contain only 42 Programs, still six short of the minimum. The 20 Historical W1-C ledger-only candidates require reacquisition and explicit M1 promotion under the frozen Sampling Frame policy; they were not silently promoted.

Accordingly, this package deliberately does not construct Calibration or Formal Groups and does not issue a Workload Seal. Doing so would require duplicate Programs, member substitution outside the frozen outcome-blind rule, a reduced formal minimum, or unauthorized historical promotion.

## Package contents

The machine-readable package is under `phase5-swe-formal-dataset-data/`:

- `swe-formal-candidate-program-inventory.json`: all 35 qualified independent Programs with Q1–Q9, terminal, raw-source, normalized, token, fixture and qualification identities.
- `swe-formal-exclusion-ledger.json`: all 22 exclusions and their exact rule failures.
- `swe-formal-dataset-readiness.json`: counts, design requirement, shortfall and input bindings.
- `sha256-manifest.json`: file-level package integrity.

The readiness record binds the processed collection summary and manifest, attempt reconciliation, conversion report, frozen Sampling Frame, Formal Protocol and Workload Qualification Contract.

## Reproduction

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/spikes/phase5_dataset/prepare_swe_dataset_readiness.py \
  --processed-root artifacts/phase5-swe-acquisition-processed-v5 \
  --reconciliation artifacts/phase5-swe-acquisition-reconciliation-v1/attempt-reconciliation.json \
  --conversion-report artifacts/phase5-swe-acquisition-adapted-v2/conversion-report.json \
  --sampling-frame configs/phase5/phase5-swe-sampling-frame-v1.json \
  --protocol configs/phase5/phase5-formal-protocol-v1.json \
  --qualification-contract configs/phase5/phase5-workload-qualification-contract-v1.json \
  --output /tmp/phase5-swe-formal-dataset-data
```

## Required decision to continue acquisition

M1/M4 must provide an outcome-blind source of at least 13 additional qualified independent Programs. Under the existing Sampling Frame, the only defined unused population is the 20-entry Historical W1-C ledger-only pool, whose policy requires explicit M1 authorization and fresh Phase 5 reacquisition. If that route is selected, the acquisition order and evidence treatment must remain frozen before execution; prior W1-C results cannot be used as Phase 5 qualification evidence.
