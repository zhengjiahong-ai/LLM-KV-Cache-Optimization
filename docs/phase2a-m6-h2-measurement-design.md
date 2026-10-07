# Phase 2A M6 H2 Measurement Bring-up Design

Status: **CALIBRATION PLAN AWAITING REVIEW — NO FORMAL VERDICT AUTHORIZED**

This is the M6 execution design for
`docs/phase2a-m4-h2-measurement-protocol.md`. It prepares measurement and
calibration only. It does not implement B1, define a block victim score, or
authorize a formal H2 verdict.

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

The formal repeat count and numeric PASS thresholds remain null until M6 and M4
review these calibration results. They must then be frozen before any formal
verdict is read.

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

The primary observation is isolated native prefill/reload elapsed time. A
controlled TTFT miss–hit delta is retained only as sensitivity unless admission
and queue state are proven equivalent. The later analysis fits the frozen L0,
L1, and L2 model shapes from the M4 protocol.

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

The same `(prefix, j)` grid compares best entry-level achievable loss against
best block-level achievable loss. The cross-entry aggregation rule is still an
open dependency: if M4 cannot state it fairly before measurement, this condition
is `INCONCLUSIVE`; M6 must not invent an aggregation from observed results.

## 6. Freeze boundary

Before formal measurement, the calibration report must commit:

1. the usable grid and its context-limit evidence;
2. the selected repeat count;
3. measured noise floors and effect resolution;
4. exact numeric thresholds agreed with M4;
5. model, tokenizer, backend, and code hashes.

Until that record exists, all four numeric verdict thresholds are unset,
formal measurement is unauthorized, and B1 remains locked.
