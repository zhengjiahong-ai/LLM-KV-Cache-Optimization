# Phase 2A M6 — H2 Final Freeze Review

Status: **AWAITING M1/M4 FINAL REVIEW — FORMAL H2 STILL LOCKED**

The profiling-only isolated native prefill seam was validated on a clean run,
then calibrated over the fixed eight-point long-context region. All 56 planned
calibration runs succeeded: 16 warmups and 40 measured runs on one clean code
revision.

## Frozen timing resolution

The calibration used the predeclared protocol:

```text
8 prefix points
2 warmups + 5 measured runs per point
10000 bootstrap resamples per point
resample size = 9
statistic = median
seed = 20261007 at every point
95th percentile = nearest-rank rule
```

The resulting formal nine-repeat median resolution is:

```text
delta_M1 = 0.19029591700382298 seconds
```

This value is now bound in
`configs/phase2/h2-final-freeze-record.json`. It is a resolution threshold for
the frozen M1 curvature rule, not an H2 result and not a universal latency
tolerance.

## Provenance

- Calibration code: `8e42b098bc13922f33018dce982b015a74832984`, clean.
- vLLM-Metal source: `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`, clean.
- Campaign SHA-256: `bbb069d76dbc75a40aa7f2679b7f3f253b8245ac5e73d071c4b076b27ccc689f`.
- Execution SHA-256: `24d31cebaf5eefc004bb41937bb732994f42c57a3105adb36e081eeb49116e88`.
- Report SHA-256: `8d67d1152b1a796b95c16b078b1b4d2a4a3b15641e7a57b002711d4603176225`.
- Formal rule-spec SHA-256: `79f2e8a662841f70a5578f6ef8f684799de530d137b1421d9606fe81e9131833`.
- Model/tokenizer revision: `7ae557604adf67be50417f59c2c2f167def9a775`.

Large raw artifacts remain external. Their campaign, execution, and report
hashes are committed here so the reviewed evidence can be verified without
placing all run directories in Git.

## Authorization requested

M1/M4 should verify the bound provenance and confirm that
`delta_M1 = 0.19029591700382298` was computed by the frozen rule. Only after an
explicit ruling should a separate authorization record permit formal H2
measurement. This draft deliberately retains:

```text
formal_measurement_authorized = false
formal_verdict_authorized = false
b1_method_or_implementation_authorized = false
```

No formal H2 outcome has been materialized or inspected.
