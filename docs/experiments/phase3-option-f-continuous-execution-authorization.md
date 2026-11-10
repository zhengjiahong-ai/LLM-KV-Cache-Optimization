# M1 Decision — Single-Allocation Continuous Phase 3 Noise + Main Execution

> **Execution-control status:** This is an intermediate 2026-11-09 decision record. The later [One-Shot 270-Run Phase 3 Execution Authorization](phase3-option-f-270-run-pipeline-authorization.md) is the operative execution contract and prevails if any wording differs. This file is retained as decision history.

**Date:** 2026-11-09
**Decision owner:** M1
**Implementation owner:** M6
**Repository:** `zhengjiahong-ai/LLM-KV-Cache-Optimization`
**Protocol:** Phase 3 Final Evaluation Protocol v4 — Option F
**Accepted G0:** `docs/experiments/phase3-option-f-g0-v3/`
**Previous authorization:** `docs/experiments/phase3-option-f-noise-calibration-authorization.md`

## Why this decision is needed

GPU platform availability is constrained. M1 therefore authorizes a **single GPU allocation** to execute the two *already-frozen* experimental stages sequentially, without giving up the GPU between them.

This record changes the **stage authorization and handoff procedure**, not the experiment design, metrics, estimator, run grid, or G0 evidence. The earlier Noise-only authorization remains a historical record; the authorization described here supersedes its manual-review-before-Main handoff requirement **only if all automatic conditions below are met**.

## Conditional execution authorization

**Stage 1 — Execute the exact 30 A0 Noise Calibration runs. Authorized immediately.**

- Noise Plan SHA-256: `2107d1fc42d7e37c0528d681cb5c1ff2dc703e7e8573376e8ffadae76e6f33f5`.
- Noise input manifest SHA-256: `061b91e49abf912ec86b4d75f37b844654c39db8fd08fe9fcabff6b0bc8bb54a`.
- Groups: g01, g04, g06, g07, g10; conditions C1/C2; arm A0; repeats 1/2/3.
- Complete exactly the 30 frozen run identities and preserve their per-run native evidence.

**Automatic checkpoint — Required before Stage 2, without releasing the GPU allocation.**

1. Validate all 30 expected Noise Run IDs, conditions, repeats, inputs, config identities, outcome schemas and native evidence. Missing, duplicate, invalid or inconsistent observations fail closed.
2. Run the independent frozen `evaluate_noise()` estimator on those exact runs. Require a successful result and a finite, nonnegative pooled `sigma_run`, `sigma_delta`, and `tied_threshold` according to Protocol v4.
3. Commit an immutable, SHA-256-bound Noise result and threshold-freeze record to the local evidence archive. Preserve the original raw output and evaluation logs.
4. Independently confirm G0 and all **pre-execution-verifiable** gates remain satisfied; do not modify input manifests, cohort, plans, policies, conditions or thresholds.
5. The per-stratum sigma ratio is diagnostic only: an explicitly reported `UNDEFINED_*` ratio is **not** by itself a reason to replace the pooled estimator or invent a new gate.
6. If any required Noise evidence, estimator calculation, or pre-execution gate fails, **do not launch Main**. Stop, preserve the diagnostic evidence, and report to M1. Do not insert additional calibration runs or rerun changed inputs.

**Stage 2 — Exact 240-run Main Campaign. Conditionally pre-authorized.**

M6 is authorized to start the Main Campaign **immediately after the automatic checkpoint passes, in the same GPU allocation, without a second M1 round-trip**.

- Main Plan SHA-256: `5828ce55dbc23ca14aa5c0074ae8c795f51ecb301bd01de003eb8c7045e27f21`.
- Main input manifest SHA-256: `55d967230c41de3c2229a2b4b91bcb61048ff67cafc612c8e532663a2a3b7022`.
- Exact 20 Groups × C1/C2 × N0/A0/A1/A2/A3/E0 = 240 frozen runs.
- Continue per-run identity/evidence checks and early fail-closed checks on runtime contract violations.

**This is NOT unconditional authorization of Main**; until the checkpoint passes, its effective status stays `LOCKED_CONDITIONAL`. Do not change historical G0 manifests containing `execution_authorized=false`; that flag records the original G0 freeze, while this signed M1 decision and the checkpoint evidence are the separate authorization layer.

## Clarification of gate timing, without changing any gate definition

- G0 and frozen Headroom G4 are pre-execution checks.
- Noise sample completeness, `sigma_run`, `sigma_delta` and tied threshold are verified and frozen **between the two execution stages**.
- G1 can be checked statically before launch for configuration isolation, but its runtime assertions (e.g., cross-arm E and N0 boundaries) require Main observations; check them as the relevant arm results become available and fail closed on violations.
- G2 A3 branch composition and G3-CM cost-model discriminability require actual Main A3/E0 decisions. Their final pass/fail/verdicts are **post-collection evidentiary/evaluability gates**, not conditions that can be fully measured using the 30 A0-only Noise runs. Preserve their exact Protocol v3/v4 thresholds and consequences. If H2 is NOT_EVALUABLE, report that result, not a fabricated PASS.
- This clarification modifies no statistical or mechanism-estimand definition and does not authorize post hoc redesign.

## Budget and boundaries

Maximum new runs: **270 total = 30 Noise + 240 Main**. No additional GPU runs, smoke, load calibration, repeated tuning, new cohort, changed arm, condition, group, replay profile, or estimator is authorized. If the allocation ends early, preserve complete per-run evidence and the exact frozen plan identity; never invent success for missing runs.

## M6 acceptance report

M6 must submit:
- GPU allocation and execution-environment identity; prelaunch G0/plan/input/archive SHA validation.
- Stage 1 30/30 Run-ID reconciliation and raw Native evidence.
- Independent Noise evaluator PASS/FAIL, `sigma_run`, `sigma_delta`, tied threshold, and frozen threshold-record SHA.
- The automated checkpoint result and the exact time Main was admitted.
- Stage 2 240/240 Run-ID reconciliation, failures, evidence inventory, protocol/G1–G4 results, G2/G3-CM and H2 evaluability, and full immutable archive hashes.
- No claim of campaign success until M1 reviews the final evidence.

**Formal status:** `NOISE_CALIBRATION_AUTHORIZED = true`; `MAIN_CAMPAIGN_AUTHORIZATION = CONDITIONAL_AUTOMATIC_AFTER_NOISE_GATE`; `MAIN_CAMPAIGN_STARTED = false` until actual evidence proves the checkpoint passed.
