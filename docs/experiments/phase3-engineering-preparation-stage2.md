# Phase 3 Engineering Preparation — Stage 2 Independent N/E/C Evaluator

Status: **IMPLEMENTED AND MERGED** — PR #94, main merge `8d51897fb90d310e322d347c6e4fb23cf7512b87`.
Stage 2 is an offline evaluator implementation and did not itself authorize acquisition or execution. Current M1 authorization is recorded in [the Phase 3 Data Readiness Decision](phase3-data-readiness-decision.md).


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
whenever the frozen Replay Timeline declares an available history predecessor.
This is independent of C: `C=0` neither proves that history is complete nor
justifies deriving `E=0`. Any request with no declared history predecessor may
legitimately have `E=0`, including multiple requests enqueued in one Native
drain before any peer crosses the logical Snapshot-availability boundary. That
zero is derived from the frozen timeline state, not from global request
position, completion order, event-write order, or C. The evaluator never
substitutes `N-C` as the primary outcome.

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

`frozen_requests` is ordered and must exactly follow the deterministic Native
enqueue order. It is not completion order: concurrency may change completion
order without changing the frozen history contract. The separate
`history_predecessors` mapping must be derived from the frozen Replay Timeline
and name exactly the requests whose logical lifecycle has crossed the
Prefix-Snapshot availability boundary before each enqueue. Every declared
predecessor must have one valid, identity-matched Snapshot; inflight requests
must not be declared as predecessors.

Before formal cell execution, the accepted final data/run manifest must
bind the Frozen Request Order, Native Enqueue Order, Replay Timeline, Session
pairing, deterministic reserve-substitution rule, and per-request expected
Snapshot predecessor relation by SHA-256. M1 does not require a separate
Stage 3 Cohort Seal engineering milestone; this freeze is part of final
pre-run data/run preparation.

APC outcomes (`NO_REUSE_ELIGIBLE_PREFIX`, `FULL_HIT`, `PARTIAL_HIT`, `MISS`)
are derived from the independently validated N/E/C tuple. Physical eviction
evidence remains diagnostic; reports explicitly retain
`ownership_level_attribution = NOT_ESTABLISHED`.

## Authorization boundary

`ENGINEERING_PREPARATION_AUTHORIZED` was the scope authorization for Stage 2
at implementation time. It is historical and is superseded by the current M1
authorization in [the Phase 3 Data Readiness Decision](phase3-data-readiness-decision.md).
