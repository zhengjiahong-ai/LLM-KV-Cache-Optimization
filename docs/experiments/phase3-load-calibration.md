# Phase 3 A0 Load Calibration

This stage is the Protocol v3 load-calibration set, not an effect-estimation
campaign. It contains exactly 40 runs: 20 sealed workload groups, two candidate
load inputs, A0 only, and one repeat.

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
interval is reported as `TARGET_MISSED_FAIL_CLOSED`. It must not proceed to
Noise Calibration or the Main Campaign, and this implementation does not
silently tune or rerun it. Any replacement grid requires an explicit M1 ruling
because the approved accounting fixes Load Calibration at 40 runs.

Headroom is reported separately as `rho0 >= 5%` and `R0 >= 512` tokens. It does
not convert a missed load target into a passing calibration.
