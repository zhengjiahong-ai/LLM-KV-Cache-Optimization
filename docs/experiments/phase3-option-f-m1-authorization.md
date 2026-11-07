# M1 Authorization Record — Phase 3 Option F

**Date:** 2026-11-06  
**Management issue:** #98  
**Accepted design and evidence:** PR #97  
**Decision:** `OPTION_F_TWO_LEVEL_FIXED_PRESSURE = ACCEPTED`

M1 accepted Option F as the final Phase 3 design and authorized engineering
adaptation followed by the gated execution route. The fixed conditions are C1
at 256 `required_blocks` and C2 at 1024 in the unchanged 2048-block KV pool.
All 20 Groups, 40 cells, and six arms remain. The existing 40 A0 runs are
reused; the designed rho bands become a non-gating manipulation check;
Headroom remains gating.

The authorized new-run budget is 30 A0 Noise Calibration runs plus 240 six-arm
Main Campaign runs. This record does not itself authorize GPU execution. G0
must first bind the Cohort Seal, existing A0 evidence, Protocol v4, and all
input manifests. Noise execution follows M1 G0 review. Main execution follows
Noise Calibration and the remaining applicable gates.

Prohibited changes include another A0 load calibration, workload replacement,
condition relabelling, arm removal, altered statistical units or weights,
post-hoc subgroup selection, changed noise estimator, and budget expansion.
