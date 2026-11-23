# Phase 5 BFCL Derived Candidate-Group Construction

**Status:** `READY_FOR_M4_GROUP_REVIEW`  
**Formal Cohort selected:** no  
**Calibration/Formal Groups assigned:** no  
**GPU authorized:** no

## Frozen construction rule

The construction follows the M1-frozen rule without replacement:

1. use `source_question_id` / `program_identity` as the independent unit;
2. sort the 88 eligible Programs by integer source-question index;
3. assign each four successive Programs to `BFCL_DERIVED_G01` through
   `BFCL_DERIVED_G22`;
4. for BOTH-mode Programs, alternate primary SNIPPET/NO_SNIPPET in source-index
   order, starting SNIPPET;
5. retain the other mode as a within-Program paired alternative, never as a
   second independent Program;
6. never substitute a later Program when a frozen eligibility check fails.

No system outcome, Candidate Exposure, Victim Set, recomputation, latency or
throughput value is an input to construction.

## Result

| Item | Count |
|---|---:|
| Candidate Programs | 88 |
| Candidate Groups | 22 |
| Primary SNIPPET Sessions | 51 |
| Primary NO_SNIPPET Sessions | 37 |
| BOTH-mode Programs with paired alternatives | 71 |
| Primary Sessions below the frozen four-Turn minimum | 14 |
| Candidate Groups passing the minimum-Turn applicability check | 12 |
| Candidate Groups unqualified by the minimum-Turn check | 10 |
| Member substitutions | 0 |

The 10 affected Group identities remain frozen and unmodified:

```text
BFCL_DERIVED_G01  program_005
BFCL_DERIVED_G03  program_013
BFCL_DERIVED_G06  program_024, program_026
BFCL_DERIVED_G07  program_029, program_030
BFCL_DERIVED_G08  program_035
BFCL_DERIVED_G09  program_038
BFCL_DERIVED_G11  program_045, program_047
BFCL_DERIVED_G15  program_061, program_063
BFCL_DERIVED_G18  program_079
BFCL_DERIVED_G20  program_085
```

This check does not remove the Programs from the immutable 159-Session parent
pool and does not promote replacements. The value 12 is an analysis-applicability
count, not a selected Formal N.

## Evidence package

The versioned metadata package is
`docs/experiments/phase5-bfcl-derived-group-data/`.

```text
candidate Group manifest:
  7e417211fac9f017ad0272478b357f47910f12b16f8c2b5e390a42afdc7c435e

paired-mode ledger:
  e45e55397bc01fcb79a6623b07c868a83115d7cb8fba984b2174aa7f96aa6419

outcome-blind audit:
  f81daa001707c7b2a9dc34b657ff1e6b5867a4448e0d3489fd3b52b3be0eaed3

statistics summary:
  94d041320b16343bace23fc99a240c9bc7b81f748d2d5d04bc43924e312a568f

Group preparation Seal:
  64cbe57194a70df8fc0b4ba5ffd2ff2c4f4adbbf359b0b55fccae45c2025deea

SHA-256 Manifest:
  d46f2102fc4586532e9b009f3e2a0ce5b21489591adc9cdf8d804fdd7835528d
```

The package binds the accepted Cohort membership, Cohort Preparation Seal and
lineage validation. It contains identity and hash metadata only, not private raw
content or derived Token IDs.

## Claim boundary

These are candidate Group identities, not assigned Calibration Groups, Formal
Groups or a selected Formal Cohort. Q4D/Q5D remain derived deterministic replay
contracts; Formal Q1-Q9 remains `NOT_EVALUATED`. Nothing here authorizes GPU,
Native Conformance, Calibration, the six-system campaign or an algorithmic
effectiveness claim.
