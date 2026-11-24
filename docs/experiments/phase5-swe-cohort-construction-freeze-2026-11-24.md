# M1 Decision — Phase 5 SWE Cohort Construction Freeze

**Decision owner:** M1  
**Decision date:** 2026-11-24  
**M4 review HEAD:** `f230515e1ae0abe7a8471e339d9e46e5633f3ba2`  
**Status:** CONSTRUCTION RULES FROZEN; MATERIALIZATION AND M4 REVIEW REQUIRED  
**Workload:** SWE-bench Verified — sole formal stratum

## 1. Entry gate and scope

M1 accepts the reported M4 results:

- `FRESH_PHASE5_PROVENANCE = PASS`
- `HISTORICAL_W1C_HASH_ISOLATION = PASS`
- `NEW_13_PROGRAM_ACCEPTANCE = PASS`
- `M4_INDEPENDENT_DATASET_GATE = PASS`
- `MINIMUM_DATASET_GATE = PASS`
- 48 independent Programs: 35 existing + 13 fresh.

The accepted source inventory is `docs/experiments/phase5-swe-historical-reacquisition-data-v2/swe-combined-48-program-candidate-inventory.json`, with candidate inventory content SHA-256:

`12084a34c7833a657f8c2beb0059f9e7a256976d291d2a54bf3057639e861368`

The inventory contains 48 distinct Program identities and zero cross-batch overlap. The 20-attempt ledger records 20/20 fresh executions, 17 converted, 3 fail-closed before normalization, 13 Q1–Q9 qualified and 4 Q1/Q6 exclusions. Historical W1-C file hash matches are zero.

This decision freezes only deterministic Cohort construction and arrival parameters. It does not issue a Workload Seal, select a final Formal N, authorize Native/GPU Conformance, or authorize Calibration/Formal execution.

## 2. Repository diversity constraint

Freeze the following constraint for every four-Program Group:

- exactly 4 distinct Program identities;
- at least **3 distinct repositories**;
- at most **2 Programs from any one repository**.

Repository identity is the upstream repository slug, parsed from the qualified `program_id` prefix before `__` and checked against the repository field in the accepted source inventory. Task IDs from the same repository count as one repository even when they are different tasks.

This is deliberately feasible under the observed inventory (Django 23/48; SymPy 9/48; Matplotlib 4/48; other repositories 12/48). A four-distinct-repository rule is not required and is not imposed.

No Program is dropped because its repository is common. No source/task is substituted to improve balance. If the frozen algorithm cannot produce all 12 groups under the above constraint, fail closed and return to M1; do not weaken the constraint.

## 3. Deterministic outcome-blind Group assignment

Freeze the following deterministic algorithm:

1. Use exactly the 48 Program identities and their canonical repository identity from the accepted combined inventory. No additions, removals, or replacements.
2. Compute for each Program:
   `key = SHA256(UTF8("phase5-swe-group-v1|20419074|" + program_id))`.
3. Sort Programs by `(key ascending, program_id ascending)`.
4. Partition the sorted sequence into 12 consecutive, non-overlapping Groups of four, named `SWE_G01` through `SWE_G12`.
5. Validate every Group against the repository constraint in §2, all 48 Program identities appear exactly once, and every Program's Session identity is unique.
6. Freeze the first four Groups as Calibration: `SWE_G01`–`SWE_G04`.
7. Freeze the remaining eight Groups as the initial Formal candidate cohort: `SWE_G05`–`SWE_G12`.

The seed `20419074` and the hash-domain string above are fixed. The sort/partition algorithm is normative; implementations must not use language-default randomized hashes, local filesystem order, completion order, source acquisition batch order, or system outcomes.

The seed was selected solely through a deterministic search against predeclared structural constraints (per-Group repository diversity and Calibration/F formal batch balance) using repository identities and fresh-vs-existing provenance labels only. No policy, Native, exposure, latency, recomputation, victim-set or other system outcome was available or used. M6 must emit an outcome-blind audit proving the materializer consumed no outcome fields.

### Frozen Group membership

| Group | Role | Ordered Program IDs |
|---|---|---|
| SWE_G01 | Calibration | `django__django-15572`; `scikit-learn__scikit-learn-14894`; `mwaskom__seaborn-3069`; `django__django-11138` |
| SWE_G02 | Calibration | `pydata__xarray-4695`; `django__django-11095`; `pylint-dev__pylint-4551`; `sympy__sympy-18199` |
| SWE_G03 | Calibration | `django__django-15741`; `sympy__sympy-13974`; `django__django-11880`; `matplotlib__matplotlib-25311` |
| SWE_G04 | Calibration | `sympy__sympy-21596`; `django__django-13212`; `django__django-13513`; `pytest-dev__pytest-7982` |
| SWE_G05 | Formal candidate | `scikit-learn__scikit-learn-25747`; `django__django-12209`; `django__django-14373`; `sphinx-doc__sphinx-8721` |
| SWE_G06 | Formal candidate | `django__django-16032`; `django__django-13023`; `sympy__sympy-15017`; `matplotlib__matplotlib-25287` |
| SWE_G07 | Formal candidate | `sympy__sympy-20801`; `django__django-15554`; `psf__requests-2931`; `django__django-16662` |
| SWE_G08 | Formal candidate | `django__django-13569`; `sympy__sympy-12419`; `matplotlib__matplotlib-26466`; `django__django-14011` |
| SWE_G09 | Formal candidate | `pydata__xarray-3305`; `django__django-14493`; `sympy__sympy-22714`; `django__django-14170` |
| SWE_G10 | Formal candidate | `django__django-11790`; `sympy__sympy-16886`; `django__django-15569`; `matplotlib__matplotlib-14623` |
| SWE_G11 | Formal candidate | `psf__requests-2317`; `sympy__sympy-13551`; `django__django-12276`; `django__django-12050` |
| SWE_G12 | Formal candidate | `pytest-dev__pytest-8399`; `django__django-13933`; `django__django-16901`; `pydata__xarray-3095` |

The ordered Program IDs above are normative. M6 must independently regenerate them from the bound inventory and verify exact equality; do not merely copy the table into a manifest.

## 4. Calibration/Formal partition and sample-size boundary

- Calibration: `SWE_G01`–`SWE_G04`, 16 Programs, 4 independent Groups.
- Formal candidate pool: `SWE_G05`–`SWE_G12`, 32 Programs, 8 independent Groups.
- Calibration and Formal Program, Session and Group identities must be pairwise disjoint.
- Calibration uses 6 systems × 4 Groups × 3 repeats = **72 planned runs**.
- Formal currently has **8 candidate Groups**, which is the minimum supported N. The eventual Formal N remains selected only by the already frozen Calibration sample-size method, after Calibration results are collected and independently evaluated.
- If the sizing method requires N>8, the current 8 Formal Groups are insufficient. Stop before Formal execution and return to M1 for an additional outcome-blind data-source decision; do not reduce power, reuse Calibration Groups, or create pseudo-replicates.
- Formal run counts remain 96 / 144 / 192 for N=8 / 12 / 16 respectively. Only the N=8 cohort is currently materializable from this 48-Program dataset.

The 4 Calibration Groups are never reused as Formal evidence. The initial 8 Formal Groups are the fixed candidate cohort, not an authorization to start Formal.

## 5. Frozen-Poisson Program arrivals

Accept and freeze:

- `arrival_mode = FROZEN_POISSON`
- `program_start_rate_per_second = 0.1`
- `master_seed = 20261201`
- generator: `PYTHON_RANDOM_MT19937_EXPONENTIAL_V1` as implemented by `src/kvopt/workload/phase5_replay.py::frozen_poisson_arrival_plan`.

For each four-Program Group, M6 must materialize and persist one immutable arrival realization. Use the master seed to generate a single deterministic Poisson stream over the concatenated, frozen order `SWE_G01` Program order, then `SWE_G02`, …, `SWE_G12`. For each Group, take its four corresponding start offsets and subtract that Group's first offset so its local first Program starts at 0.0 seconds. This uses one master-seed realization without giving all 12 Groups identical inter-arrival gaps.

The resulting Group-local start offsets, Program order, rate, generator/version, master seed, derivation rule and canonical SHA-256 must be persisted in the Group/Arrival Manifest. The exact same realization for a Group must be used across all six systems and all repeats. No per-system or per-repeat resampling is allowed.

This is a controlled arrival process, not a claim that the rate is an empirically observed production arrival rate. Keep observed within-Session Tool Gaps unchanged. Preserve the actual Native enqueue-order gate; planned arrival equality alone does not establish native execution order.

The existing generation seed, execution-order seed, bootstrap seed and Poisson master seed are separate protocol fields even where their numeric values happen to coincide. This decision freezes only the Poisson master seed at 20261201; it does not redefine the other seeds.

## 6. Right-censoring and inference boundary

Preserve the accepted M4 rule without modification:

- Primary analysis includes a right-censored Session only for its valid, actually observed Turns.
- Missing future Turns are not imputed or synthesized.
- Sensitivity analysis repeats the analysis excluding right-censored Sessions.
- A system failure is never reclassified as source right-censoring.
- Program/Group remains the independent sampling hierarchy; Turns, Requests, tool calls and repeats are not independent samples.

The inventory's current aggregate of 2 Natural Terminal + 46 Right-Censored is reported as such. Group construction does not change terminal classifications or upgrade any Session to natural completion.

## 7. M6 implementation authorization and required outputs

M6 is authorized to implement the frozen deterministic construction and produce, in one batch:

1. Deterministic Group Materializer and reproducible CLI.
2. Group manifest with all 12 Groups, exact ordered Program/Session IDs, repository IDs, batch/provenance labels and per-member evidence hashes.
3. Separate Calibration and Formal candidate child manifests.
4. Program/Session/Group cross-cohort disjointness validator.
5. Repository-diversity validator enforcing `min_distinct_repositories=3` and `max_programs_per_repository_per_group=2`.
6. Frozen-Poisson arrival realization manifest with all 12 Group-local schedules and hashes.
7. Outcome-blind audit, group statistics summary, combined Cohort candidate manifest and Workload Seal input bundle.
8. SHA-256 manifest binding the source 48-Program inventory, M4 review artifacts, frozen rule/seed, all child manifests, arrival realization and validator outputs.

M4 performs one targeted independent review of the materialized package: exact membership/order, repository counts, disjointness, hash/lineage bindings, outcome blindness, arrival reproducibility and right-censoring boundaries. Do not repeat Fresh Provenance acquisition review or broad CPU smoke; test only the new materializer/validator/arrival integration.

## 8. Authorization boundary

Authorized now:
- deterministic Group and Cohort candidate construction;
- Frozen-Poisson arrival materialization and hash sealing;
- associated CPU tests, validation, documentation and M4 review.

Not authorized:
- Workload Seal issuance as final M1 acceptance;
- Native/GPU Conformance;
- SWE Calibration execution;
- SWE Formal execution;
- BFCL Derived GPU execution;
- any other GPU experiment.

After M6 delivery and M4 targeted review, return the complete package to M1 for final Cohort/Workload Seal acceptance. D gates and separate M1 execution authorization remain mandatory.
