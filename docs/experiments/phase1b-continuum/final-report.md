# Phase 1B Continuum-Style Baseline — Final Experiment Results

## 1. Scope

This report records the final experimental evidence for the adapted
Continuum-style Phase 1B baseline. It is not an exact reproduction of the
source Continuum system.

The evidence covers:

- formal PrefillReload profiling;
- real-runtime Phase 1B validation;
- program/session continuity and lifecycle;
- TTL, retention, and protection;
- protected-pressure release and native cleanup;
- scheduler coordination;
- NATIVE, SHADOW, and CONTROLLED mode boundaries.

The raw JSON artifacts are preserved byte-for-byte under `artifacts/`.

## 2. Runtime and provenance

The qualified runtime was:

- vLLM 0.27.1;
- pinned vLLM-Metal source revision
  `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`;
- macOS Apple Silicon arm64 / Metal;
- automatic prefix caching enabled;
- paged KV enabled;
- block size 16;
- one in-process EngineCore and one cache group;
- `Qwen/Qwen2.5-0.5B-Instruct`;
- model and tokenizer revision
  `7ae557604adf67be50417f59c2c2f167def9a775`.

The three relevant Git SHAs are intentionally distinct:

```text
Formal profiling code HEAD:
13404b7b65a786cc89589c7558c73a6debbce548

Validation artifact recorded repository HEAD:
09f8f9539afa30adec785992377ce449e2799bb8

Final PR7 runner commit:
9349075536e9deb9bbfb4bfd91d0fa1d89fde8f2
```

`validation.json` records `09f8f953...` because that was the repository HEAD
while the PR7 validation changes were still present as uncommitted working-tree
changes. The successful Metal run used those finalized PR7 runner changes.
After the successful run and final checks, those changes were committed as
`9349075536...`; no implementation or test changes were made between the
successful validation state and that commit.

## 3. Formal PrefillReload profile

Formal run ID: `formal-20260920T045859Z-6183d106`.

The profile used real MISS/HIT measurements. For each reusable-prefix length,
the raw value is:

```text
PrefillReload = TTFT_MISS - TTFT_HIT
```

The grid was `16, 32, 128, 256, 512` reusable-prefix tokens. Each point used
5 warmup pairs and 20 measured pairs, with a 32-request pressure batch and a
maximum of 64 pressure batches. The artifact preserves every pair and reports
the median of the 20 raw measured deltas. No interpolation or invented value
is used in the measured table.

| Reusable prefix tokens r | Median PrefillReload (s) |
| ---: | ---: |
| 16 | 0.009522290994937066 |
| 32 | 0.011798791994806379 |
| 128 | 0.04975464601011481 |
| 256 | 0.0887301250040764 |
| 512 | 0.17105704150890233 |

Aggregate facts:

- 125 real MISS/HIT pairs;
- 2,125 pressure batches;
- 68,000 pressure requests;
- completed profile artifact;
- zero negative raw deltas.

The runtime representative point is:

```text
r = 256
PrefillReload(256) = 0.0887301250040764 seconds
```

Raw artifact:

`artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json`

## 4. Final Phase 1B real-runtime validation

Final run ID: `pr7-host-metal-20260922-blockidentity-evidence-fix`.

```text
status: complete
failure_reason: None
```

Claims:

- `mode_boundaries`: PASS;
- `native_cleanup`: PASS;
- `nonterminal_retention`: PASS;
- `program_continuity`: PASS;
- `scheduler_coordination`: PASS;
- `terminal_cleanup`: PASS.

Scenarios:

- `controlled_multiturn`: PASS;
- `pressure_native_cleanup`: PASS.

Modes:

- `NATIVE`: PASS;
- `SHADOW`: PASS;
- `CONTROLLED`: PASS.

Validation artifact:

`artifacts/phase1b-validation-pr7-host-metal-20260922-blockidentity-evidence-fix.json`

## 5. Protected pressure and native cleanup

The final CONTROLLED validation-only configuration used:

```text
num_gpu_blocks_override = 48
max_model_len = 528
max_num_batched_tokens = 528
```

This gives:

```text
total native blocks       = 48
reserved null block       = 1
usable blocks             = 47
protected target blocks   = 16
ordinary eligible supply  = 31
512-token prefill demand  = 32
```

Therefore `31 < 32 <= 47`: ordinary eligible KV alone cannot satisfy the
allocation, so protected fallback becomes necessary. This constrained pool is
validation-only and does not change production `src/`.

The final observed pressure result was:

- batch: 1;
- actual pressure requests: 32;
- `retention_release_observed`: true;
- `plan_validated`: true;
- `native_eviction_callback_observed`: true;
- `target_present`: false;
- native cleanup observation present;
- native eviction observed for block ID 32.

The observed chain was:

```text
protected retained state
→ real GPU KV pressure
→ Continuum logical release
→ released blocks become eligible
→ allocation continues
→ native eviction callback / BlockPool cleanup
→ target cache material absent
```

The constrained pool was necessary because the original larger native cache
could recycle completed ordinary pressure KV blocks without exhausting
ordinary candidates. The constrained pool removes that ambiguity without
changing production behavior.

## 6. Scheduler and lifecycle evidence

- Explicit program identity survives changing native request IDs.
- The first nonterminal request establishes retained/protected cache state.
- A waiting follow-up preserves protection through the pressure phase.
- The ordinary competitor is admitted before pressure.
- Follow-up admission is deferred until pressure completes.
- CONTROLLED scheduler evidence demonstrates policy ordering on the real
  native `Request` objects.
- Terminal lifecycle cleanup succeeds.
- NATIVE and SHADOW remain non-mutating at their respective boundaries.

## 7. Regression checks

Final completed checks:

- focused PR7 tests: 48 passed;
- full suite: 622 passed;
- Ruff: PASS;
- AST check: PASS;
- import check: PASS;
- `git diff --check`: PASS.

These are regression summaries; no separate persistent pytest, Ruff, or
terminal-log artifacts are claimed.

Production `src/` was not modified by PR7. The formal PrefillReload profile
was not rerun during final closeout, and no Metal rerun occurred after the
successful final artifact.

## 8. Raw artifact integrity and provenance disclosure

The curated files are byte-for-byte copies of the authoritative local result
artifacts:

| Curated artifact | SHA-256 |
| --- | --- |
| `artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json` | `c995bcc19ba9d953dc7ee8115ec13b896fa394a16671f1a3b4085b0016f87d79` |
| `artifacts/phase1b-validation-pr7-host-metal-20260922-blockidentity-evidence-fix.json` | `45221cc50b6dd056ff57a3ae8733045ba321b9ccc7ae5193904bbe5318e9642f` |

The raw JSON includes machine provenance such as hostname, Python executable,
and local checkout paths. No credentials or access tokens were found. These
fields are retained unchanged to preserve artifact integrity; reviewers should
be aware that they publish local environment identifiers.
