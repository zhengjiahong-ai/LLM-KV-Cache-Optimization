# E1-A：Logical Candidate Exposure Feasibility Audit

**Status:** `E1A_EXECUTED_DATA_GAP_FOR_MODELED_EXPOSURE`  
**Scope:** CPU-only, read-only existing Phase 3 archive; no W1-C raw traces were present.  
**Freeze config:** `configs/phase4/e1a-logical-exposure-freeze-v1.json`  
**Freeze SHA-256:** `dabf3022f24acf4e012704a1a01e208f252557396b0cb6ae020fc775fcdcc9e9`

## 0. Short answer

- Phase 3 observed **7/127** multi-candidate decision events (5.512%) across 4 Groups; this is the already-known observed exposure, not a new natural-workload estimate.
- The primary program-level differential downstream-opportunity rate is **5/7** (71.429%) at H=60s across 3 Groups. This is a **program-level** opportunity, not a prefix-hit claim.
- The modeled retention models **cannot be executed**: the archive exposes actual candidate lists but not the full protected-entry set, and no W1-C raw traces are present in the workspace.
- Therefore E1-A **does not establish natural/logical candidate expansion** and does not justify P1-B on current data.

## 1. Frozen model and denominators

| Item | Value |
|---|---|
| Primary model | `M0_OBSERVED_PHASE3` |
| Candidate source | actual `FORCED_RELEASE_DECISION.candidates` |
| Primary denominator | all forced-release decision events |
| Secondary denominator | events with at least one candidate |
| Primary H | 60s |
| Secondary H | 15s / 300s (300s descriptive only; Phase 4 censoring 54.2%) |

## 2. Observed exposure

| Metric | Value |
|---|---:|
| Decision events | 127 |
| Cells | 39 |
| Candidate-count distribution | {1: 120, 2: 7} |
| Multi-candidate events | 7 |
| Multi-candidate Groups | 4 |
| Rate over all decision events | 5.512% |
| Rate over live-candidate decision events | 5.512% |

**Program-level differential downstream opportunity:**

- numerator: 5 multi-candidate events with a later request in a candidate program but not every candidate program;
- denominator: 7 multi-candidate events;
- rate: 71.429%;
- differential Groups: 3 (g09, g16, g18);
- this is `PROGRAM_LEVEL_DIFFERENTIAL_OPPORTUNITY`, not a Native prefix-hit or physical-victim claim.

### 2.1 Secondary horizons

| H (s) | multi-candidate events | differential events | differential rate | note |
|---:|---:|---:|---:|---|
| 15 | 7 | 0 | 0.000% |  |
| 60 | 7 | 5 | 71.429% |  |
| 300 | 7 | 5 | 71.429% | descriptive only (54.2% censored in Phase 4) |

## 3. Data availability and why the modeled part is not executed

| Item | Status |
|---|---|
| W1-C report | present |
| W1-C raw traces | W1C_RAW_TRACES_NOT_PRESENT_IN_WORKSPACE |
| Protected-entry snapshot | PROTECTED_ENTRY_SNAPSHOT_NOT_PRESENT |

The frozen Phase 3 archive records actual candidate lists and free-queue snapshots, but not the complete set of protected entries that would be needed to generate counterfactual candidates under a different retention window. The W1-C report provides aggregate LCP/context statistics but no per-request raw trajectories in this workspace. E1-A therefore reports the observed exposure and declines to fabricate a modeled exposure rate.

## 4. Model status

| Model | Status |
|---|---|
| M0_OBSERVED_PHASE3 | EXECUTABLE |
| M1_RETENTION_X2 | NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT |
| M2_RETENTION_X4 | NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT |
| M3_RETENTION_X8 | NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT |

The sensitivity models remain **pre-registered but not executable**; they are not dropped and no post-hoc model is substituted.

## 5. Recommendation

**Do not proceed to P1-B on the current data.** The observed Phase 3 exposure is still 7/127, and the modeled logical-expansion question cannot be answered without a representative multi-session trace or a protected-entry snapshot. The appropriate next action is either:

1. provide a real W1-C raw-trace bundle and a protected-entry snapshot, then re-run this frozen audit; or
2. stop P1-B on this workload family and report the exposure/evidence result.

No GPU, Native smoke, production algorithm change, Protocol v5, or new data acquisition was performed.

## 6. Reproduction

```bash
python scripts/probes/e1a_logical_exposure/audit.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --freeze  configs/phase4/e1a-logical-exposure-freeze-v1.json \
    --out     docs/experiments/e1a-logical-exposure-data
```
