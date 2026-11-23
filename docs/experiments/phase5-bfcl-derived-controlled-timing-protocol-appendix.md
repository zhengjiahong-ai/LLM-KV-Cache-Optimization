# Phase 5 BFCL Derived Controlled-Timing Protocol Appendix

**Status:** FROZEN  
**Workload type:** `BFCL_DERIVED_CONTROLLED_TIMING`  
**Decision owner:** M4  
**Engineering HEAD reviewed:** `a7ae6c4f9c2479c11e5426e1e4ba62bba41c0b31`  
**Formal Cohort:** not selected  
**GPU execution:** not authorized

This is a minimal appendix, not a redesign of the Formal Protocol and not a change to
the six-system definitions or algorithms.

---

## 0. Scope and status

The appendix defines qualification and reporting semantics for the 199 accepted
BFCL-Result semantic records. It explicitly does **not** turn these records into
source-observed Agent traces.

```text
SOURCE_TERMINAL_UNKNOWN
REPLAY_TRACE_EXHAUSTED
SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED
DERIVED_NOT_QWEN_NATIVE_TRACE
```

The workload is an internal derived workload. It is not a natural BFCL execution
trace and does not carry the source system's original arrival or Tool Gap timing.

---

## 1. Eligibility and accepted Archive Record IDs

### Source

- Repository: `HuanzhiMao/BFCL-Result`
- Commit: `cadd76a8dc62984e7bf15ecaf358f070bae745cc`
- Source model: `gpt-5.2-2025-12-11-FC`
- SNIPPET archive SHA-256:
  `62ab5b7751431809bbcd3ee9970065e5d8580f7d35a1b00f63ddf911d405416e`
- NO_SNIPPET archive SHA-256:
  `6f6574ad0b990266b9faf37c4c3ae371e80008a3c49a446fba0844c44a4eb3be`

### Frozen counts

```text
accepted sessions: 199
SNIPPET: 100
NO_SNIPPET: 99
excluded: 1
model requests: 1,040
```

The accepted IDs are ordered by frozen `phase5_case_index`: SNIPPET 1..100,
then NO_SNIPPET 101..200.

### Complete ordered accepted Archive Record ID list

```text
web_search_base_0
web_search_base_1
web_search_base_2
web_search_base_3
web_search_base_4
web_search_base_5
web_search_base_6
web_search_base_7
web_search_base_8
web_search_base_9
web_search_base_10
web_search_base_11
web_search_base_12
web_search_base_13
web_search_base_14
web_search_base_15
web_search_base_16
web_search_base_17
web_search_base_18
web_search_base_19
web_search_base_20
web_search_base_21
web_search_base_22
web_search_base_23
web_search_base_24
web_search_base_25
web_search_base_26
web_search_base_27
web_search_base_28
web_search_base_29
web_search_base_30
web_search_base_31
web_search_base_32
web_search_base_33
web_search_base_34
web_search_base_35
web_search_base_36
web_search_base_37
web_search_base_38
web_search_base_39
web_search_base_40
web_search_base_41
web_search_base_42
web_search_base_43
web_search_base_44
web_search_base_45
web_search_base_46
web_search_base_47
web_search_base_48
web_search_base_49
web_search_base_50
web_search_base_51
web_search_base_52
web_search_base_53
web_search_base_54
web_search_base_55
web_search_base_56
web_search_base_57
web_search_base_58
web_search_base_59
web_search_base_60
web_search_base_61
web_search_base_62
web_search_base_63
web_search_base_64
web_search_base_65
web_search_base_66
web_search_base_67
web_search_base_68
web_search_base_69
web_search_base_70
web_search_base_71
web_search_base_72
web_search_base_73
web_search_base_74
web_search_base_75
web_search_base_76
web_search_base_77
web_search_base_78
web_search_base_79
web_search_base_80
web_search_base_81
web_search_base_82
web_search_base_83
web_search_base_84
web_search_base_85
web_search_base_86
web_search_base_87
web_search_base_88
web_search_base_89
web_search_base_90
web_search_base_91
web_search_base_92
web_search_base_93
web_search_base_94
web_search_base_95
web_search_base_96
web_search_base_97
web_search_base_98
web_search_base_99
web_search_no_snippet_0
web_search_no_snippet_1
web_search_no_snippet_2
web_search_no_snippet_3
web_search_no_snippet_4
web_search_no_snippet_5
web_search_no_snippet_6
web_search_no_snippet_7
web_search_no_snippet_8
web_search_no_snippet_9
web_search_no_snippet_10
web_search_no_snippet_11
web_search_no_snippet_12
web_search_no_snippet_13
web_search_no_snippet_14
web_search_no_snippet_15
web_search_no_snippet_16
web_search_no_snippet_17
web_search_no_snippet_18
web_search_no_snippet_19
web_search_no_snippet_20
web_search_no_snippet_21
web_search_no_snippet_22
web_search_no_snippet_23
web_search_no_snippet_24
web_search_no_snippet_25
web_search_no_snippet_26
web_search_no_snippet_27
web_search_no_snippet_28
web_search_no_snippet_29
web_search_no_snippet_30
web_search_no_snippet_31
web_search_no_snippet_32
web_search_no_snippet_33
web_search_no_snippet_34
web_search_no_snippet_35
web_search_no_snippet_36
web_search_no_snippet_37
web_search_no_snippet_38
web_search_no_snippet_39
web_search_no_snippet_40
web_search_no_snippet_41
web_search_no_snippet_42
web_search_no_snippet_43
web_search_no_snippet_44
web_search_no_snippet_45
web_search_no_snippet_46
web_search_no_snippet_47
web_search_no_snippet_48
web_search_no_snippet_49
web_search_no_snippet_50
web_search_no_snippet_52
web_search_no_snippet_53
web_search_no_snippet_54
web_search_no_snippet_55
web_search_no_snippet_56
web_search_no_snippet_57
web_search_no_snippet_58
web_search_no_snippet_59
web_search_no_snippet_60
web_search_no_snippet_61
web_search_no_snippet_62
web_search_no_snippet_63
web_search_no_snippet_64
web_search_no_snippet_65
web_search_no_snippet_66
web_search_no_snippet_67
web_search_no_snippet_68
web_search_no_snippet_69
web_search_no_snippet_70
web_search_no_snippet_71
web_search_no_snippet_72
web_search_no_snippet_73
web_search_no_snippet_74
web_search_no_snippet_75
web_search_no_snippet_76
web_search_no_snippet_77
web_search_no_snippet_78
web_search_no_snippet_79
web_search_no_snippet_80
web_search_no_snippet_81
web_search_no_snippet_82
web_search_no_snippet_83
web_search_no_snippet_84
web_search_no_snippet_85
web_search_no_snippet_86
web_search_no_snippet_87
web_search_no_snippet_88
web_search_no_snippet_89
web_search_no_snippet_90
web_search_no_snippet_91
web_search_no_snippet_92
web_search_no_snippet_93
web_search_no_snippet_94
web_search_no_snippet_95
web_search_no_snippet_96
web_search_no_snippet_97
web_search_no_snippet_98
web_search_no_snippet_99
```

### Excluded record

```text
archive_record_id: web_search_no_snippet_51
phase5_case_id: bfcl_web_search_51:no_snippet
phase5_case_index: 152
reason: SOURCE_TOOL_OUTPUT_SIZE_LIMIT
semantic_trace_complete: false
```

`web_search_no_snippet_51` is not retried, repaired, replaced, counted as complete,
or included in the 199. The M1 text's "99 SNIPPET + 99 NO_SNIPPET" is a counting
typo; the immutable archive and independent audit establish **100 SNIPPET + 99
NO_SNIPPET = 199**.

---

## 2. Synthetic Tool Gap generation, freezing and use

### Generator

```text
generator: DETERMINISTIC_CONSTANT_1S_V1
gap_seconds: 1.0
clock_domain: synthetic_controlled
source_observed: false
future_visibility: FORBIDDEN_UNTIL_PRECEDING_REQUEST_COMPLETES
```

The schedule is a **controlled replay timing realization**, not a measurement of
the source system's tool latency.

### Per-session values

For each accepted session, one gap exists between each consecutive pair of frozen
model requests:

```text
gap_count(session) = max(0, request_count(session) - 1)
gap_seconds = 1.0 for every boundary
```

The exact per-session map is in:

- `configs/phase5/phase5-bfcl-derived-protocol-appendix-v1.json`
  (`synthetic_tool_gap_schedule.gap_seconds_by_archive_record_id`)

The map covers all 199 accepted IDs and exactly 1,040 request boundaries.

### Use rule

- The same schedule is used by all six systems.
- A gap is released only after the preceding request completion.
- A policy or algorithm must not read a future gap.
- The schedule must not be relabeled as observed source timing.
- A missing or changed schedule fails qualification.

---

## 3. Q4D — synthetic timing qualification

Normal Q4 is replaced only for this workload by `Q4D`.

### Q4D PASS conditions

1. The per-session schedule covers exactly the frozen request boundaries.
2. Every gap is finite and non-negative.
3. The schedule SHA-256 matches the frozen appendix.
4. The gap is released only after the preceding request completes.
5. No future gap is visible to a policy or algorithm.
6. All six systems use the same schedule.
7. The record is labelled `SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED`.

No observed source Tool Gap is required or claimed.

```text
Q4D_SYNTHETIC_TIMING = PASS
SOURCE_OBSERVED_TOOL_GAP = NOT_AVAILABLE
```

---

## 4. Q5D — terminal semantics

### Two distinct states

```text
SOURCE_TERMINAL_UNKNOWN
```

This is a source-record property. The archive does not provide a source natural
terminal or a source right-censor decision.

```text
REPLAY_TRACE_EXHAUSTED
```

This is a replay-local state: every frozen request in the derived session has been
consumed exactly once. It does **not** mean the source Agent completed naturally and
does not assert that the source would not have produced more requests.

### Q5D PASS conditions

1. `source_terminal_state == SOURCE_TERMINAL_UNKNOWN`.
2. `replay_terminal_state == REPLAY_TRACE_EXHAUSTED`.
3. All frozen requests were consumed exactly once.
4. No source terminal is inferred.
5. `REPLAY_TRACE_EXHAUSTED` is not mapped to `COMPLETED` or `RIGHT_CENSORED`.
6. Early replay stop is `FAIL_CLOSED` (`REPLAY_INCOMPLETE`).

```text
SOURCE_TERMINAL_UNKNOWN != REPLAY_TRACE_EXHAUSTED
REPLAY_TRACE_EXHAUSTED != NATURAL_COMPLETION
REPLAY_TRACE_EXHAUSTED != RIGHT_CENSORED
```

---

## 5. Context budget

The existing Phase 5 limits remain frozen:

```text
maximum_prompt_tokens: 32,640
maximum_generation_tokens: 128
maximum_combined_tokens: 32,768
```

Read-only Qwen materialization found:

| Stratum | Sessions | Requests | Over-32,640 Requests | Affected Sessions | Maximum Prompt Tokens |
|---|---:|---:|---:|---:|---:|
| SNIPPET | 100 | 471 | 22 | 14 | 97,971 |
| NO_SNIPPET | 99 | 569 | 41 | 26 | 210,085 |
| Total | 199 | 1,040 | 63 | 40 | 210,085 |

### Treatment

- Do not truncate tool results.
- Do not shorten history.
- Do not split a Session.
- Do not reconstruct a different prompt.
- Any Session with at least one request above 32,640 prompt tokens is
  `EXCLUDED_CONTEXT_BUDGET`.
- The Session remains in the Acquisition/Evidence Ledger.
- The exact 40 affected IDs are produced mechanically by the M6 materialization
  report as `context-budget-exclusions.json` and must be hash-bound; M4 does not
  manually choose them.

Expected:

```text
context_excluded_sessions: 40
context_excluded_requests: 63
expected_formal_eligible_sessions: 159
```

Context-excluded Sessions do not receive Q1-Q9 or Q4D/Q5D PASS and do not enter
the formal derived cohort.

---

## 6. BFCL and SWE-Bench stratification and reporting

- SWE-Bench and BFCL remain separate strata.
- No pooled estimate across the two strata.
- No cross-stratum comparison is reported as a single effect.
- BFCL results are reported as `BFCL_DERIVED_CONTROLLED_TIMING`, not as
  source-observed natural workload.
- SWE-Bench reports its own observed workload and timing evidence.
- BFCL synthetic timing may be used for within-BFCL replay contrasts, but not to
  claim the real distribution of tool gaps.
- All six systems use the same BFCL synthetic schedule; this equality is a
  cross-system timing identity, not a source timing claim.
- No formal Cohort is selected in this appendix.

If BFCL cannot supply a formal source-observed stratum, M1 must decide how the
frozen two-stratum design is handled; M4/M6 do not silently replace or drop it.

---

## 7. Final schema and hashes

### Schema

```text
phase5.bfcl_derived_protocol_appendix.v1
```

Companion machine-readable appendix:

`configs/phase5/phase5-bfcl-derived-protocol-appendix-v1.json`

### Hashes

```text
protocol_appendix_canonical_sha256:
  0d5f5b92fb03a631707cf51cb46c993f1347c80e178543cf63f9f2db7e6de52e

protocol_appendix_file_sha256:
  5f945eb087859ffaeae8dca2aff7a7f7411a858d0514c4a6e55ba11d14676e5c

accepted_ids_sha256:
  887ee93c72b4bc40d79a743e19e53e53f1ea085b722f6a395bd2c2edb9e8518e

synthetic_schedule_sha256:
  9d9ac750eb2e8ce3bd2b872269fb69aab9701868bf7afaeeced0879e0138b6f5

q4_derived_sha256:
  0d3a849c2f855fde9e8358f1fece3f64d7b641e6a360eb1cdedd2b83b64e2de6

q5_derived_sha256:
  f426f82951b2dd1a777b9bf697415c8a6f19b440ebde874430618fe7a39f0f4c

arrival_generator_sha256:
  cbc9d51f96527650642d3b0b5621ebe1e5a2e5fd6fdee5ee94a57779638d62e5

tool_definitions_sha256:
  61fcee411e35f7ff67415e18cd67276615cf06e1c8841a683d2d997dbb46eac5
```

The `protocol_appendix_canonical_sha256` is computed over the JSON object excluding
that field. The file hash is the immutable file identity. M6 must bind the file
hash in the derived workload seal; the canonical hash is the research-contract
identity.

---

## 8. Status

```text
workload_type = BFCL_DERIVED_CONTROLLED_TIMING
accepted_sessions = 199
snippet_sessions = 100
no_snippet_sessions = 99
excluded = web_search_no_snippet_51
synthetic_schedule = DETERMINISTIC_CONSTANT_1S_V1
source_terminal = SOURCE_TERMINAL_UNKNOWN
replay_terminal = REPLAY_TRACE_EXHAUSTED
formal_q1_q9_status = NOT_EVALUATED_PENDING_FROZEN_M4_APPENDIX
formal_cohort_selected = false
gpu_execution_authorized = false
```
