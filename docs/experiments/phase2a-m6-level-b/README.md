# Phase 2A M6 Level-B Seam Validation

The committed `seam-validation-summary.json` is the compact audit record for
the real-runtime S1--S5 seam validation accepted by the M1/M4 review.

The five cases validate direct native observations for no eligible prefix, full
hit, controlled partial hit, controlled full reusable loss, and an old prefix
with a fresh suffix. For every row the accounting identity holds:

```text
W = R + (N - E)
```

All five cases passed with native prefix/recomputation and request timing fields
available. This establishes the Level-B collection seam as validated and
available for later authorized work. It is not formal H1 evidence and does not
authorize H1 outcome execution.

The audit record includes both source and runtime configuration hashes because
the isolated runner materializes a runtime configuration. It also records the
original run manifests' `git_dirty: true` provenance rather than hiding it. The
M1/M4 review accepted the reported real-runtime S1--S5 result and requested this
compact repository audit record; the large raw directories remain external.
