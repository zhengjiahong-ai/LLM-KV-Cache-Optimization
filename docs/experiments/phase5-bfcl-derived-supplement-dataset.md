# Phase 5 BFCL Derived Supplement Dataset Package

**Workload:** `BFCL_DERIVED_CONTROLLED_TIMING`
**Status:** ready for M4 independent partition review
**Formal Q1–Q9:** `NOT_EVALUATED`
**GPU execution:** not authorized

## Frozen partition

The package applies the M1 scope amendment without changing the accepted Parent Candidate Group Inventory.

- Derived Calibration, descriptive only: G02, G10, G14, G19 (4 Groups / 16 independent Programs).
- Derived Evaluation, exploratory only: G04, G05, G12, G13, G16, G17, G21, G22 (8 Groups / 32 independent Programs).
- The 48 selected Program identities and Primary Session identities are disjoint across both child partitions.
- A SNIPPET/NO_SNIPPET paired alternative remains attached to its source Program and is never counted as another independent Program.
- The ten unselected Groups are exactly the Parent Inventory's minimum-Turn-unqualified Groups: G01, G03, G06, G07, G08, G09, G11, G15, G18 and G20. No substitution or promotion occurred.

## Evidence and lineage

The child Seal binds the accepted Parent Group Manifest, Parent Group Preparation Seal, Parent Paired-Mode Ledger and Parent SHA-256 Manifest. Each child Group also binds the Parent Group content hash and preserves the full Program, source-question, Primary Session, paired-alternative and synthetic Tool Gap identities.

The package preserves `SOURCE_TERMINAL_UNKNOWN` and `REPLAY_TRACE_EXHAUSTED` as separate states. The controlled 1-second synthetic Tool Gap remains explicit and does not become observed historical timing.

Files are under `phase5-bfcl-derived-supplement-data/`:

- `bfcl-derived-calibration-child-manifest.json`
- `bfcl-derived-evaluation-child-manifest.json`
- `bfcl-derived-child-paired-mode-ledger.json`
- `bfcl-derived-child-partition-audit.json`
- `bfcl-derived-supplement-seal.json`
- `sha256-manifest.json`

## Reproduction

```bash
PYTHONPATH=src .venv/bin/python \
  scripts/spikes/phase5_dataset/prepare_bfcl_derived_partitions.py \
  --parent-group-root docs/experiments/phase5-bfcl-derived-group-data \
  --output /tmp/phase5-bfcl-derived-supplement-data
```

The generator refuses to overwrite an existing output directory and fails closed on Parent Seal drift, missing Groups, an ineligible frozen Group, cross-partition overlap, paired-mode loss, hash mismatch or authorization drift.

## Claim boundary

This is a separate supplementary controlled-timing dataset package. It is not a formal BFCL Native Stratum, not Formal Q1–Q9 PASS, not Natural Terminal evidence, not GPU Native Conformance and not evidence that any cache policy is beneficial.
