# Phase 5 BFCL Derived Cohort Preparation

**Status:** `READY_FOR_M4_INDEPENDENT_REVIEW`  
**Workload:** `BFCL_DERIVED_CONTROLLED_TIMING`  
**Formal Cohort selected:** no  
**GPU authorized:** no

## Scope

This package prepares the complete independently reviewable candidate pool from
the M1-accepted BFCL derived asset. It does not assign Calibration Groups or
Formal Groups and does not claim Formal Q1-Q9, Native conformance or algorithmic
benefit.

Membership is derived outcome-blind from the frozen appendix order by removing
only the 40 mechanically recorded `EXCLUDED_CONTEXT_BUDGET` Sessions. No system
outcome, candidate exposure, victim set, recomputation or serving metric is an
input to membership.

## Prepared population

| Item | Count |
|---|---:|
| Accepted source semantic Sessions | 199 |
| Context-excluded Sessions | 40 |
| Derived-eligible Sessions | 159 |
| Eligible SNIPPET Sessions | 86 |
| Eligible NO_SNIPPET Sessions | 73 |
| Independent source-question Program clusters | 88 |
| Maximum disjoint four-Program Groups | 22 |

The 100 frozen source-question identities partition as follows:

| Eligible mode pattern | Source questions |
|---|---:|
| SNIPPET and NO_SNIPPET | 71 |
| SNIPPET only | 15 |
| NO_SNIPPET only | 2 |
| Neither mode context-eligible | 12 |

SNIPPET and NO_SNIPPET variants of one source question share one
`program_identity`. They are explicitly marked
`PAIRED_VARIANTS_NOT_INDEPENDENT_PROGRAMS` and never contribute two independent
Programs to the capacity calculation.

## Preserved semantics

- source terminal: `SOURCE_TERMINAL_UNKNOWN`;
- replay terminal: `REPLAY_TRACE_EXHAUSTED`;
- timing: `SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED`;
- Formal Q1-Q9: `NOT_EVALUATED`;
- Derived Q4D/Q5D: `PASS` in the accepted parent asset;
- mode pairing and original source-question identity remain explicit.

The proposal preserves all 40 context exclusions in the parent immutable
evidence and binds their report by SHA-256. It does not alter the frozen
appendix, schedule, sampler, tokenizer identities or Token Materialization.

## Evidence package

`artifacts/phase5-bfcl-derived-cohort-preparation-v1/` contains only identity,
status and hash metadata; it contains no third-party webpage body or derived
Token IDs.

```text
bfcl-derived-cohort-membership-proposal.json
  d4f59386b1388bb2ae095c4cababf40eb29384480bd8aace3fc0acc274ff105d

bfcl-derived-cohort-preparation-seal.json
  f763920c7403bf333dfc079eda9e3288d4dd99175e9347535da628569f8b6439

sha256-manifest.json
  f9b7e941365f56fc3f3d0f7434938b7f088f26e0a1be72fc893991d874657612
```

M4 remains responsible for independent lineage, source-question independence,
mode-pairing, outcome-blindness and group-readiness review. M1 remains the final
authority for any Cohort selection or execution authorization.
