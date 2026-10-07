# Phase 2A M6 H2 Measurement Bring-up Design

Status: **ISOLATED-SEAM VALIDATION PENDING — FORMAL MEASUREMENT LOCKED**

This is the M6 execution design for
`docs/phase2a-m4-h2-measurement-protocol.md`. It prepares measurement and
calibration only. It does not implement B1, define a block victim score, or
authorize a formal H2 verdict.

M1/M4 accepted the first sensitivity-timing pilot, froze nine formal measured
repetitions and the exact decision rules, and required a profiling-only isolated
native prefill seam. The exact rules now live in
`configs/phase2/h2-formal-freeze-spec.json`. Formal H2 measurement, verdict
computation, and B1 remain locked.

The machine-readable plan is
`configs/phase2/h2-measurement-design.json`.

## 1. Calibration sequence

Each pilot point uses two warmups and five measured repetitions in an isolated
process with concurrency one, an empty queue, deterministic one-token output,
and fixed model/tokenizer/backend revisions. The pilot records median, median
absolute deviation, minimum, and maximum elapsed time.

The pilot determines:

- which requested grid points fit the actual model context;
- native timing resolution and per-point noise floors;
- whether 5, 7, or 9 formal repetitions are required;
- the smallest pairwise effect distinguishable from jitter.

The first pilot used scheduler-admission-to-first-token timing and remains
sensitivity only. The formal repeat count is now frozen at nine. A new
eight-point calibration must validate the isolated seam and derive `delta_M1`
before any formal outcome is materialized.

## 2. M1 — real C(r)

The frozen token grid is:

```text
16, 32, 64, 128, 256, 512, 1024, 2048,
4096, 8192, 12288, 16384, 20480, 24576,
26624, 28672, 30720
```

This includes all required points and three points above 24576 for a model with
at least a 32768-token context. If the reviewed model cannot safely admit this
grid, the plan must be revised before measurement; points must not be silently
dropped afterward.

The primary observation is `isolated_native_prefill_elapsed_seconds`. It is
collected only when `backend_options.isolated_native_prefill_timing` is true.
The profiling hook synchronizes the submitted Metal prefill forward before
sampling; normal H1 serving keeps the option disabled. Admission-to-first-token
timing remains sensitivity only.

## 3. M2 — partial-prefix APC

With block size 16 and a 64-block prefix, retain leading block counts:

```text
k = 0, 16, 32, 48, 64
```

These provide a full miss control, three partial-prefix points, and a full hit
control. A separate no-eviction re-request is also required. Native cached
prefix tokens and recomputed prefill tokens are direct observations collected
through the Level-B seam; logical identity is not evidence.

## 4. M3 — leading versus trailing position

For prefix sizes 512, 2048, 8192, and 24576 tokens, compare leading and trailing
eviction using the same `j` in `{1, 4, 16}` blocks. The primary outcome is
direct recomputed prefill tokens. Each pair uses the same configuration and
runtime controls.

## 5. M4 — block-level extra headroom

The same `(prefix, j)` grid uses the frozen single-prefix comparator: actual
recomputation from logical entry release plus native LRU versus the controlled
trailing-j offline mechanism oracle. Cross-entry aggregation is outside H2 and
must not be invented from the outcomes.

## 6. Freeze boundary

Before formal measurement, the calibration report must commit:

1. the usable grid and its context-limit evidence;
2. the selected repeat count;
3. the isolated-seam calibration and derived `delta_M1`;
4. the already-frozen M1/M2/M3/M4 decision rules;
5. model, tokenizer, backend, and code hashes.

Until that final record exists and is reviewed, formal measurement is
unauthorized and B1 remains locked.
