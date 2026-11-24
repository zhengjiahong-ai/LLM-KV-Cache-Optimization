# Phase 5 SWE Cohort Candidate Materialization

**Status:** 12 candidate Groups materialized and validated; M4 targeted review
and final M1 Workload Seal acceptance remain required. GPU execution is not
authorized.

## Frozen construction

The materializer independently recomputes
`SHA256("phase5-swe-group-v1|20419074|" + program_id)`, sorts all 48 accepted
Programs by hash and identity, partitions consecutive groups of four, and
requires exact equality with the normative membership in the M1 construction
freeze. `SWE_G01`--`SWE_G04` are Calibration candidates and
`SWE_G05`--`SWE_G12` are Formal candidates.

All 12 Groups contain at least three repositories and no more than two
Programs from one repository. The Calibration and Formal children have zero
Program, Session or Group overlap, and every accepted Program occurs exactly
once.

## Frozen arrival realization

One 48-Program stream is generated with
`PYTHON_RANDOM_MT19937_EXPONENTIAL_V1`, rate `0.1 Program/s` and seed
`20261201`. Each consecutive four-Program slice is rebased to a local first
arrival of zero. The stored Group schedule is reused across all six systems
and repeats; per-system and per-repeat resampling are prohibited.

## Right-censoring boundary

The population remains 2 Natural Terminal and 46 Right-Censored Programs.
Primary analysis uses only valid observed Turns. Sensitivity analysis excludes
right-censored Sessions. Materialization does not impute missing future Turns
or upgrade source terminal classifications.

## Outputs

Machine-readable outputs are in
[`phase5-swe-cohort-data`](phase5-swe-cohort-data/): full Group manifest,
Calibration/Formal children, arrival realization, disjointness and diversity
validators, outcome-blind audit, statistics, combined candidate manifest,
Workload Seal input bundle and SHA-256 manifest.

Key file SHA-256 values:

- Group manifest: `2354d9c98862828684dd6491c67eaa4a6dd7007d5fa38d6a1a1e7aa13a6b020f`
- Calibration child: `97e3709a6be1175d762f6cc60054c6834ee3d7833557c82abc6d2ca66c88c54e`
- Formal child: `6dadaddecead9be4b552e0e843f0cecd2c7b465449d6e6d589845384a01c2bb7`
- Frozen arrival manifest: `09b6c1ef10b950a85a7f5a29d59181106373e3fdef63b664239d64ef117fcbae`
- Combined candidate manifest: `fbfdf4f5d3bd4be2db38b9879b58a3277070e50881170a1128c3c9708205d850`
- Workload Seal input: `588d53a027133d813c8dcf44486324b71188e4e701098bb71b598284bb919965`
- Package manifest: `8131060f1c573ed14b9a5362dc2f7087dfc2b19cc7ceaa6a4a0af7cfff2ad2b6`

This package does not issue the final Workload Seal, choose a Formal N above
the currently available eight Groups, authorize GPU execution, or establish
algorithmic benefit.
