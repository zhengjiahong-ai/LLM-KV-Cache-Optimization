# M1 authorization: Phase 3 Option F unified 270-run execution

M1 accepts G0 v3 and authorizes one continuous Phase 3 execution window with
the following immutable scope:

- 30 A0 Noise Calibration runs: Groups g01, g04, g06, g07, and g10; Conditions
  C1 and C2; Repeats 1, 2, and 3;
- automatic evaluation of the frozen pooled Noise estimator, persistence of
  `sigma_run`, `sigma_delta`, the tied threshold, and all registered stratum
  diagnostics; and
- 240 Main Campaign runs (20 Groups x 2 Conditions x N0/A0/A1/A2/A3/E0), but
  only after the automatic Noise and applicable frozen gates pass.

Authorization state:

```text
G0_ACCEPTED = true
NOISE_RUNS_AUTHORIZED = 30
MAIN_RUNS_AUTHORIZED = 240
ONE_SHOT_270_RUN_PIPELINE_AUTHORIZED = true
INTERMEDIATE_MANUAL_M1_REVIEW_REQUIRED = false
```

This approval does not authorize regeneration of frozen inputs, rerunning the
40-run A0 Load Calibration, replacing Cohort tasks, changing Protocol v4 or its
estimators, adding Smoke runs, or starting Main before the automatic transition
is persisted.  A failed Noise gate must stop the pipeline and retain all
evidence.  The executable JSON authorization record is generated only after
the reviewed implementation is committed, so it can bind the clean Git SHA and
the accepted G0/Noise/Main SHA-256 values.
