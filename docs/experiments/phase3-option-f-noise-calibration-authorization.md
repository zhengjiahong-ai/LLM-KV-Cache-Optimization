# Historical M1 G0 Acceptance and Noise-Only Authorization (Superseded)

**Date:** 2026-11-07  
**Status:** SUPERSEDED on 2026-11-09 by the one-shot 270-run authorization.

This file records the original stage-limited authorization and is retained as immutable decision history. It is no longer the operative execution authorization.

The operative authorization is:

`docs/experiments/phase3-option-f-270-run-pipeline-authorization.md`

That amendment authorizes one continuous 270-run pipeline: 30 A0 Noise runs, automatic independent Noise evaluation and mandatory gate checks, then 240 Main runs if and only if the machine-verified transition gate passes. No intermediate manual M1 review is required.

The frozen G0 v3 manifests, plans, cohort, and evidence remain unchanged. The 40-run A0 Load Calibration must not be rerun. If a mandatory gate fails, a required pooled Noise value is undefined, or evidence/hash validation fails, the controller must stop before Main and preserve all evidence.

Historical original decision: G0 accepted; Noise 30 runs authorized; Main 240 runs locked pending Noise and a separate M1 decision. This historical decision is superseded only as to the intermediate manual approval requirement; Protocol v4 estimands, gate definitions, frozen inputs, and fail-closed requirements remain in force.
