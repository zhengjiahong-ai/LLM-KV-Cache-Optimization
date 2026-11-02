# Phase 3 Engineering Preparation — Stage 2 Independent N/E/C Evaluator

## Scope

This stage implements the offline request-level evidence path required by the
Phase 3 Final Evaluation Protocol v3. It does not authorize acquisition or GPU
execution and does not change any runtime policy.

## Frozen token semantics

For every frozen request:

- `N` is `native_prompt_tokens` from the persisted Native request observation.
- `C` is `native_cached_prefix_tokens` from that observation.
- `E` is independently reconstructed from the longest block-aligned common
  prefix between the request's Native APC content-hash chain and compatible
  prefix snapshots that precede that request in the persisted frozen history.

`E` never uses `C` as a fallback, lower bound, replacement, or repair. A missing
or incompatible prior content-identity chain fails the affected cell closed
when `C > 0`; the evaluator does not substitute `N-C` as the primary outcome.

The request invariant is `0 <= C <= E <= N`. The aggregate identity is:

`sum(N-C) = sum(E-C) + sum(N-E)`.

The primary metric is the absolute token count `sum(E-C)`. The evaluator also
reports `sum(N-C)`, `sum(N-E)`, APC reuse ratio, and recompute ratio. Ratios are
auxiliary and never replace the primary metric.

## Cross-arm isolation and failure behavior

The evaluator requires the exact frozen request set and all six arms
`N0/A0/A1/A2/A3/E0`. It verifies request-level `N` and `E` equality across the
arms. The only Native observations excluded from effect estimation are request
IDs explicitly frozen in the Stage 1 Manifest's `pressure_request_contract`;
any other unknown observation fails closed.

Every content hash must be a 64-character lowercase SHA-256 digest. A current
request chain must cover every complete prompt block. The sole permitted extra
tail hash follows the existing Native rule: a one-token completion may finish
a prompt whose length is one token short of a complete block. Prior snapshots
must contain a non-empty chain and a positive, chain-consistent token count.

Duplicate or missing observations, malformed identities, incompatible hash
provenance, incomplete chains, invalid token ordering, aggregate identity
failure, or any cross-arm `N/E` drift yields `FAIL_CLOSED` for the cell. Empty
frozen request sets and any arm set other than the fixed six-arm matrix are
also rejected.

APC outcomes (`NO_REUSE_ELIGIBLE_PREFIX`, `FULL_HIT`, `PARTIAL_HIT`, `MISS`)
are derived from the independently validated N/E/C tuple. Physical eviction
evidence remains diagnostic; reports explicitly retain
`ownership_level_attribution = NOT_ESTABLISHED`.

## Authorization boundary

`ENGINEERING_PREPARATION_AUTHORIZED`; `ACQUISITION_NOT_AUTHORIZED`;
`GPU_CAMPAIGN_NOT_AUTHORIZED`.
