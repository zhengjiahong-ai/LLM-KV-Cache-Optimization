# M1 Amendment — One-Shot 270-Run Phase 3 Execution Authorization

**Date:** 2026-11-09  
**Repository:** `zhengjiahong-ai/LLM-KV-Cache-Optimization`  
**Accepted implementation HEAD:** `6f77f7178d366a259e14285469f9419e05afaa5f`  
**PR #99 merge commit:** `a7fe138354720412b393ac584e8d1d6ed8cd4709`  
**G0 bundle:** `docs/experiments/phase3-option-f-g0-v3/`

## Decision

M1 authorizes preparation and execution of the complete **270-run Phase 3 pipeline in one continuous compute window**, with a deterministic, programmatic transition from Noise Calibration to Main Campaign.

This amendment supersedes the prior authorization record's requirement for a separate manual M1 approval between the 30-run Noise stage and the 240-run Main stage. No manual M1 review is required at that intermediate point.

This is a **conditional one-shot authorization**, not permission to ignore a failed or undefined mandatory gate.

## Frozen execution inventory

- G0 Freeze Manifest SHA-256: `db9ebb8a388d30f6d9bc1c58a19dd8b97b9ce0a7afdafea124987754fbcde971`
- External G0 Evidence Archive SHA-256: `7b3a78c8e582067e6a236885aa91980cf51a77bf2787d774b82733612cd94529`
- Noise Plan SHA-256: `2107d1fc42d7e37c0528d681cb5c1ff2dc703e7e8573376e8ffadae76e6f33f5`
- Noise Input Manifest SHA-256: `061b91e49abf912ec86b4d75f37b844654c39db8fd08fe9fcabff6b0bc8bb54a`
- Main Plan SHA-256: `5828ce55dbc23ca14aa5c0074ae8c795f51ecb301bd01de003eb8c7045e27f21`
- Main Input Manifest SHA-256: `55d967230c41de3c2229a2b4b91bcb61048ff67cafc612c8e532663a2a3b7022`
- Total new-run budget: exactly 270 (30 Noise + 240 Main).

The frozen plans, input manifests, Cohort Seal, and G0 evidence are immutable. Do not edit their contents or regenerate them to encode this execution authorization. This amendment is the separate execution authority.

## One-shot execution order

### Stage A — A0 Noise Calibration (30 runs)

Execute the exact frozen 30 Noise Run IDs, Groups, Conditions, A0 arm, repeats, and configurations. Do not rerun the existing 40-run A0 Load Calibration.

After the 30 runs, the controller must automatically invoke the independent Noise Evaluator against the exact frozen Run-ID set. It must calculate and persist:

- pooled `sigma_run`;
- `sigma_delta`;
- the Protocol v4 tied threshold;
- all required per-stratum diagnostics and ratio status;
- exact Run-ID reconciliation, failures/retries, and evidence hashes.

The pooled estimator and formulas must remain exactly those in Protocol v4 §6. Per-stratum sigma and max/min ratio remain diagnostic only; they must not replace or alter the pooled estimator.

### Automatic transition gate

Without waiting for a manual M1 review, the controller may proceed to Stage B only when all of the following are machine-verified:

1. All 30 frozen Noise Run IDs have complete, valid Native evidence and exact identity/repeat reconciliation.
2. The independent Noise Evaluator completes successfully and produces a valid, persisted pooled estimator and tied threshold under Protocol v4.
3. Every applicable mandatory G1/G2/G3-CM/G4 condition is evaluated under its frozen definition and passes. G4-M remains diagnostic and is not promoted to an admission gate.
4. All G0, Noise, Main plan, input, configuration, and archive bindings remain valid.

A diagnostic-only undefined stratum ratio is reported as diagnostic and must not be substituted for the pooled estimator. If a required pooled value cannot be computed, any mandatory gate fails, or any evidence/binding is incomplete or inconsistent, the controller must FAIL CLOSED and stop before Main.

### Stage B — Main Campaign (240 runs)

If and only if the automatic transition gate passes, immediately continue the exact frozen 240-run Main Plan in the same reserved compute window. No additional manual M1 approval is required.

Execute the complete frozen grid:
- 20 Groups;
- C1 and C2;
- N0, A0, A1, A2, A3, E0;
- exactly 240 Run IDs.

Persist the Noise result and tied threshold before the first Main Run. The Main evaluator must consume that exact frozen threshold and the original registered estimands. No post-hoc threshold, subgroup, estimator, or run-plan changes are allowed.

## Compute-window requirements

- Reserve and prepare resources for the full 270-run pipeline before launch.
- Load and initialize the model/runtime once where technically supported.
- Keep the same compute allocation available through the Noise evaluation and automatic transition; do not require a second GPU reservation.
- Run the Noise evaluation on CPU while retaining the allocated GPU resources where the platform permits.
- Prepare the Main queue in advance, but do not dispatch any Main Run until the automatic transition gate passes.
- Record the transition decision, gate outputs, timestamps, and the exact authorization/addendum hash in the execution ledger.

## Immutable constraints

- No A0 Load Calibration rerun.
- No Cohort reacquisition or task/group replacement.
- No changes to C1/C2, arms, repeats, request order, model, tokenizer, estimator, or Protocol v4.
- No additional Smoke or unregistered GPU work.
- No Main execution if the automatic transition gate fails.
- Preserve all raw Native evidence, evaluator outputs, logs, and archives immutably.

## Reporting

M6 should report:
1. Before launch: execution host/runner, GPU allocation, 270-run resource reservation, and all frozen-hash checks.
2. At the automatic transition: Noise evaluator output, pooled sigma/tied threshold, mandatory gate results, and the machine-recorded CONTINUE/STOP decision.
3. At completion: 30/30 Noise and 240/240 Main reconciliation (or an explicit fail-closed stop), full Native evidence, independent evaluation outputs, failures/retries, and final SHA-256 archive.

## Authorization state

`G0_ACCEPTED = true`  
`ONE_SHOT_270_RUN_PIPELINE_AUTHORIZED = true`  
`NOISE_RUNS_AUTHORIZED = 30`  
`MAIN_RUNS_AUTHORIZED = 240, CONDITIONAL_ON_AUTOMATIC_GATE_PASS`  
`INTERMEDIATE_MANUAL_M1_REVIEW_REQUIRED = false`

This amendment authorizes M6 to prepare and execute the complete one-shot pipeline under the exact conditions above.
