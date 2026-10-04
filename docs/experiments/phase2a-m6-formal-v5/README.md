# Phase 2A M6 V5 Canonical Evidence

This index identifies the canonical planned-timing re-derivation of the V5
formal profiling campaign.

## Canonical inputs and outputs

- campaign: `artifacts/phase2a-formal-campaign-v4/`;
- immutable raw runs: `artifacts/phase2a-formal-v5-final/`;
- canonical derived bundle: `artifacts/phase2a-formal-v5-derived-v2/`;
- canonical Gate: `GAP-PROVISIONAL`;
- signal support level: `PROXY_SUPPORTED`;
- runtime replication: false.

The derived manifest records clean analysis commit
`6023c66e9b8d51491f189e881b45eabe4a823cd9`, schema
`phase2a.derived.v2`, and `planned_return_weighted_prefill_proxy` as the only
canonical trace-derived loss view. The observed-horizon view is sensitivity
only and is excluded from the formal Gate.

## External evidence package

The complete evidence is not committed because `artifacts/` is intentionally
Git-ignored. Transfer this archive separately:

```text
artifacts/phase2a-m6-formal-evidence-6023c66.tar.gz
```

- size: 656 KiB;
- entries: 447;
- SHA-256:
  `eb38f82643c9f173f745cb7bf6b822e4019932f5dbebf9bfc77860bde12d3770`.

The archive contains the campaign definition, all 54 immutable V5 raw runs,
and the canonical derived-v2 bundle. Its transfer channel must be agreed with
M1 or the project team.

A targeted credential-value scan found no API keys, access tokens,
authorization values, passwords, secrets, or HF tokens. The raw evidence does
retain local absolute paths and machine provenance, so reviewers should treat
those environment identifiers as disclosed metadata.

## Review entry points

After extracting the archive, review:

- `phase2a-formal-v5-derived-v2/manifest.json`;
- `phase2a-formal-v5-derived-v2/empirical_gap_report.jsonl`;
- `phase2a-formal-v5-derived-v2/horizon_sensitivity_summary.jsonl`;
- `phase2a-formal-v5-derived-v2/signal_evaluation.jsonl`;
- `phase2a-formal-v5-derived-v2/signal_support.jsonl`;
- `phase2a-formal-v5-derived-v2/method_support_pack.json`.

The earlier V4 result and V5 observed-horizon derived-v1 result are retained
as diagnostic/superseded evidence and must not replace this canonical bundle.
