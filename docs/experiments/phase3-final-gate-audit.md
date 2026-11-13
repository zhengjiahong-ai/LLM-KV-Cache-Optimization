# Phase 3 Option F Final Gate and Process Audit

**Status:** read-only audit complete; M1/M4 adjudication required

**Immutable execution archive:**
`d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8`

This audit was performed after the completed 270-run campaign. It neither
modifies the immutable evidence nor retroactively authorizes Main.

## Findings

| Check | Read-only result | Execution-time status |
| --- | --- | --- |
| Cohort Seal SHA | PASS; observed and frozen SHA are both `9e528b173e2205a3f5137ee036e842dc739e7827e5f294dd7907c180ee38ea5f` | The historical authorization record omitted this field |
| Run inventory | PASS; 30 Noise and 240 Main IDs exactly reconcile across plan, state, results and Native directories | Completed |
| Normalized cross-arm configuration | PASS, 40/40 cells | Not persisted as a stage-transition gate |
| Frozen replay execution conformance | **FAIL; 48/240 runs exact, 192/240 differ from the frozen order** | Not checked before/during Main admission |
| Cross-arm actual enqueue-order equality | PASS, 40/40 cells; 32 cells share a common deviation | Established by the subsequent read-only actual-order audit |
| N0/cross-arm Pressure Boundary sequence | PASS, 40/40 cells | Not persisted as a stage-transition gate |
| Independent N/E/C | PASS, 40/40 cell reports | Evaluated after collection |
| G2 branch composition | S2A=127, S2B=0, S2C=0 | Post-collection evidence |
| G3-CM | `NOT_EVALUABLE`; A3/E0 different choices=0, PROFILE_ROBUST=0, PROFILE_SENSITIVE=0 | Post-collection evidence |
| G4 Headroom | PASS_HEADROOM_38_OF_40; 18 paired Headroom Groups | Not persisted as a stage-transition gate |

The enqueue mismatch is not a missing-document problem. For example, frozen
g01 requires `astropy__astropy-7671:turn:83` before
`django__django-13401:turn:31`, while the observed submission stream places
the former after turns 31 through 51. The frozen request set is intact, but
the order contract is not.

## Process deviation

The historical `stage-transition.json` contains the Noise result and tied
threshold, but not a complete G1/G4/Cohort ledger. Main therefore started
without a persisted proof of all stated transition checks. The read-only
checks above are retrospective evidence only and are deliberately not labeled
as execution-time PASS results.

The frozen replay execution-conformance check fails, so the completed campaign
cannot be reported as satisfying every frozen execution contract. A subsequent
read-only audit established that all six arms had identical actual order in
every cell, all 5,760 actual-order E values were determinate and unchanged, and
the fixed-population effect estimates were identical. This supports a bounded
paired-effect interpretation under an explicitly retained process deviation;
final status still requires M1/M4 adjudication. No GPU rerun is performed or
requested.

## Evidence location

[`phase3-final-gate-audit-data`](phase3-final-gate-audit-data/) contains the
gate ledger, authorization and prelaunch records, pipeline/noise/transition/
main reports, the 40 N/E/C reports, algorithm-exposure outputs, and a SHA-256
manifest.

The follow-up [Actual Native Order and E Sensitivity Audit](phase3-actual-order-audit.md)
contains the per-cell cross-arm sequence comparison and actual-order E
reconstruction required to interpret the mismatch.

Reproduction:

```bash
PYTHONPATH=. .venv/bin/python \
  -m scripts.spikes.audit_phase3_final_gates \
  --execution-archive artifacts/phase3-option-f-unified-270-runs-v2-evidence.tar.gz \
  --g0-archive artifacts/phase3-option-f-g0-v3-evidence.tar.gz \
  --cohort-seal artifacts/phase3-cohort-seal-v1/cohort-seal.json \
  --authorization artifacts/phase3-unified-270-authorization-v1.json \
  --prelaunch artifacts/phase3-unified-270-prelaunch-validation-v1.json \
  --algorithm-audit-directory docs/experiments/phase3-algorithm-exposure-audit-data \
  --output-directory phase3-final-gate-audit-data
```

The output directory must not exist. This prevents an audited derivative from
being overwritten accidentally.
