# Phase 5 Session Turn-Limit Sensitivity Analysis

**Status:** offline read-only analysis complete; protocol decision remains with M1

**Scope:** existing Phase 5 acquisition attempts, normalized traces, token
materializations, and Q1-Q9 reports only

**GPU work:** none

**Protocol changes:** none

**Analysis base Git SHA:** `ccd84369652028413b58397c174264eec68de1b3`

## Decision summary

The observed data do not support `max_turns_per_session=16` as a useful safety
boundary. The recommended protocol change is to remove the additional Turn cap
while retaining all of the following:

- the four-Turn minimum;
- the 32,640 Prompt Token limit and the frozen generation budget;
- explicit collector termination rules;
- explicit right-censoring labels;
- fail-closed exclusion of Context failures, infrastructure failures, and
  incomplete evidence.

This recommendation does not silently admit every long Session. Under the
existing evidence rules, only 35 of the 57 observed SWE Sessions would be
retained without an extra Turn cap: two natural completions and 33 Sessions
right-censored at the 100-step collector limit. Fourteen Context failures,
three infrastructure timeouts, and five Sessions below four Turns remain
excluded.

The result is SWE-only. No Phase 5 BFCL normalized/tokenized Session was present
in the analyzed repository snapshot, so the BFCL stratum is reported as zero
and remains a data gap.

## Denominator and reconstruction

The attempt ledger contains 75 attempts: 62 completed attempts and 13 failed
attempts. Those attempts produced 62 unique completed task identities. The
conversion layer materialized 57 normalized Sessions; five completed task
identities were excluded before the processed Session set.

The analysis denominator is therefore **57**, not 75 or 62. Deduplication uses
one normalized `session_id` per task and binds each processed record's original
`run.json` SHA-256 to exactly one completed ledger attempt. Failed attempts are
kept at attempt level and never counted as Sessions. Historical W1-A/W1-C data
are not included; their evidence role remains separate background only.

The independently rebuilt distribution confirms the preliminary counts:

| Observed successful model requests | Sessions |
|---|---:|
| Below 4 | 5 |
| 4 through 16 | 3 |
| Above 16 | 49 |
| Total | 57 |

The observed terminal classes are:

| Terminal class | Sessions | Treatment |
|---|---:|---|
| Natural completion | 7 | eligible subject to other gates |
| Step-limit right-censored | 33 | eligible only with explicit censoring |
| Context-limit failure | 14 | excluded |
| Infrastructure failure | 3 | excluded |

`LimitsExceeded` is classified as step-limit right-censoring, not natural
completion. `ContextLengthExceeded` and `JobTimeoutError` remain separate
failure classes. The analysis never converts a right-censored Session into a
natural completion.

## Turn-cap sensitivity

The “Turn-window” column applies only the minimum and candidate maximum. The
“Retained” column additionally requires an allowed terminal class, the Prompt
Token limit, and all Q1-Q9 checks other than the Turn-range component of Q6.

| Candidate cap | SWE Turn-window | SWE retained | Natural | Step-limit censored | Context failures observable within cap | Infrastructure failures within cap | 4-Program Group upper bound | BFCL retained |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 | 3 | 2 | 2 | 0 | 1 | 0 | 0 | 0 |
| 32 | 3 | 2 | 2 | 0 | 1 | 0 | 0 | 0 |
| 50 | 5 | 2 | 2 | 0 | 3 | 0 | 0 | 0 |
| 64 | 11 | 2 | 2 | 0 | 8 | 1 | 0 | 0 |
| 100 | 52 | 35 | 2 | 33 | 14 | 3 | 8 | 0 |
| No additional cap | 52 | 35 | 2 | 33 | 14 | 3 | 8 | 0 |

Caps 16, 32, 50, and 64 all retain the same two natural Sessions. The extra
Sessions appearing in the 50/64 Turn windows terminate through Context or
infrastructure failures and remain ineligible. Cap 100 and no additional cap
are identical for this finite observed dataset because the collector already
stopped successful model-call sequences at 100.

The 4-Program Group counts are feasibility upper bounds only. They do not select
a Cohort, establish independence, or modify the Group-level statistical unit.

## Context constraints

Across the 57 Sessions, the largest materialized successful Prompt contains
32,256 tokens. No successful Turn exceeds the protocol limit of 32,640 tokens.
The distribution of per-Session maximum Prompt length is:

- minimum: 1,728;
- median: 20,311;
- 95th percentile: 32,224;
- maximum: 32,256.

Fourteen Sessions end in an explicit Context-length failure. Their failed next
request is not silently truncated or reconstructed; only preceding successful
requests have exact Token IDs. These Sessions remain excluded at every cap that
otherwise reaches their observed successful Turn count.

There are also 33 Sessions with 100 successful Turns whose maximum successful
Prompt remains at or below 32,640. They demonstrate that a Session can greatly
exceed 16 Turns without crossing the Prompt limit. This is why a Turn cap is
not a substitute for the actual Context gate.

The Session detail table contains the full per-Turn Prompt Token count vector,
the first/last values, maximum, cumulative count, and exact request sequence.
No history was shortened and no Prompt was regenerated.

## Effect on workload distributions

For caps 16 through 64, the retained set is the same two natural Sessions:

- Turn count: 5 to 6, median 5.5;
- maximum Prompt length: 1,861 to 2,198 tokens;
- cumulative Prompt length: 8,156 to 11,046 tokens;
- Session duration: 16.7 to 19.6 seconds;
- total observed tool wait: 2.2 to 3.1 seconds.

At cap 100 or no additional cap, the 35 retained SWE Sessions have:

- Turn count: 5 to 100, median 100, mean 94.6;
- maximum Prompt length: 1,861 to 32,093, median 19,159;
- cumulative Prompt length: 8,156 to 1,703,863, median 1,041,442;
- Session duration: 16.7 to 804.1 seconds, median 370.0;
- total observed tool wait: 0 to 156.2 seconds, median 26.9.

These differences are descriptive properties of the observed workloads, not
additional independent observations. Formal inference remains at Workload
Group level.

## Research-value boundary

The 49 Sessions above 16 Turns contain 3,648 successful model requests beyond
their first 16 requests and therefore at least 3,648 additional adjacent-Turn
comparisons. Across those long Sessions, the exact adjacent Prompt Token LCP
total is 52,010,853 tokens, and 3,067 tool calls are observed. The session-level
CSV preserves every adjacent LCP length and every per-Turn Prompt length.

These facts support a trajectory-level claim: long Sessions expose substantially
more cumulative context, exact adjacent Prefix continuity, request arrivals,
and tool-wait structure than a 16-Turn truncation would preserve. They are
therefore useful inputs for studying potential cache competition and historical
Prefix reuse.

They do **not** establish Native cache hits, legal candidate counts, physical
victims, eviction, recomputation, or Cost-Aware benefit. Those remain Native
runtime questions and require the separately authorized evidence chain.

## Recommendation and limits

M1 should remove the additional `max_turns_per_session` ceiling rather than
replace 16 with 32, 50, or 64. For the current finite evidence, setting the cap
to 100 is observationally equivalent; removing the extra cap better expresses
the intended contract because actual safety is already controlled by Context,
generation, acquisition termination, and censoring rules.

This recommendation has four important boundaries:

1. the 33 long retained Sessions are right-censored and must remain labelled as
   such;
2. BFCL cannot be adjudicated until its normalized/tokenized evidence exists;
3. a future collector with a different execution limit requires a new
   sensitivity review, even if the protocol has no extra Turn cap;
4. more Turns increase within-Session evidence, not the number of independent
   statistical units.

No Formal Protocol JSON, Q1-Q9 contract, Workload Seal, Cohort decision, or
historical artifact was changed by this analysis.

## Reproduction

```bash
.venv/bin/python scripts/probes/phase5_session_turn_sensitivity.py \
  --repository . \
  --output-root docs/experiments/phase5-session-turn-sensitivity-data
```

The output directory is exclusive: reproduction must use a new directory or
first compare and deliberately replace the prior derived output. The input
inventory binds every raw run, acquisition sidecar, adapted record, normalized
trace, token materialization, qualification report, and the attempt ledger by
SHA-256.

Derived outputs:

- `session-details.csv`: 57 Session-level records and per-Turn vectors;
- `turn-cap-summary.csv`: flattened cap-by-stratum retention summary;
- `turn-cap-sensitivity.json`: all cap/stratum summaries and recommendation;
- `input-inventory.json`: source paths, hashes, code version, and read-only
  scope;
- `sha256-manifest.txt`: derived-file integrity manifest.
