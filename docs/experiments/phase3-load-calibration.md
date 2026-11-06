# Phase 3 A0 Load Calibration

This stage is the historical Protocol v3 load-calibration set reused by
Protocol v4 Option F, not an effect-estimation campaign. It contains exactly
40 runs: 20 sealed workload groups, two fixed operating points, A0 only, and
one repeat. Protocol v4 names the points C1/C2; `L_LOW`/`L_HIGH` remain input
provenance labels only.

The initial deterministic candidate grid is:

| Load | Fixed pool | Pressure demand | Target baseline recompute ratio |
| --- | ---: | ---: | ---: |
| `L_LOW` | 2048 blocks | 256 blocks / 4096 tokens | 5–15% |
| `L_HIGH` | 2048 blocks | 1024 blocks / 16384 tokens | 25–45% |

Each cell uses one fixed pressure request immediately before the two terminal
right-censored requests. Explicit pressure Token IDs, the pressure boundary,
the ControlledSparseReplayClock sequence, the Cohort Seal, Profile, Trace,
configuration, Frozen Request Order, Native Enqueue Order, and per-request
History Predecessors are SHA-256-bound before execution. Policy outcomes never
change the number or identity of pressure requests.

The candidate labels are not treated as validated load levels. Persisted Native
events are evaluated with the independent Phase 3 N/E/C evaluator, where
`R0 = sum(E-C)`, `W0 = sum(N-C)`, and `rho0 = R0/W0`. A cell outside its target
interval is reported as an `OUT_OF_BAND` non-gating manipulation check. It does
not exclude a cell and does not invalidate otherwise complete evidence. Option
F does not tune or rerun these 40 measurements.

Headroom is reported separately as `rho0 >= 5%` and `R0 >= 512` tokens. It does
not convert a missed load target into a passing calibration.
