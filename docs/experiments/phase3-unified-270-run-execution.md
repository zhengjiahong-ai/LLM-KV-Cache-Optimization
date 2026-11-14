# Phase 3 Option F unified 270-run execution

## Authorization and scope

M1 approved one continuous execution window containing the frozen 30-run A0
Noise Calibration followed, conditionally, by the frozen 240-run six-arm Main
Campaign.  No intermediate manual M1 review is required.  This changes only
the execution schedule; Protocol v4, G0 v3, Cohort, conditions, arms, Run IDs,
estimators, and budget remain frozen.

The materialized G0, Noise, and Main inputs deliberately retain
`execution_authorized=false`.  They are not independently executable.  The
unified controller requires a separate authorization record binding the clean
execution Git SHA and the G0/Noise/Main input hashes.

## Fail-closed transition

The controller executes the exact 30 Noise Run IDs first and persists each
Native result before advancing.  It then applies the frozen pooled within-cell
estimator and writes `sigma_run`, `sigma_delta`, the tied threshold, all three
stratum diagnostics, and the max/min ratio status.

Main changes to `MAIN_AUTHORIZED_BY_PIPELINE` only when:

- all 30 unique Noise Run IDs and repeats match the frozen plan;
- all Native runs and independent N/E/C evaluations succeed;
- the pooled estimator and tied threshold are valid and persisted;
- G0, plans, inputs, Cohort, execution code, and external evidence retain their
  frozen SHA-256 bindings; and
- the Main inventory is exactly 20 Groups x 2 Conditions x 6 Arms.

A diagnostic stratum ratio with a Protocol-v4-defined `UNDEFINED` status does
not invalidate an otherwise valid pooled estimator.  Any other missing,
duplicate, drifted, or invalid evidence stops the pipeline before Main.

## Isolation and recovery

Every run executes in a fresh child process.  This avoids cross-run KV cache,
Scheduler, request-state, and evidence-sink contamination.  Model files remain
in the local Hugging Face cache, but an in-memory model or KV cache is not
shared across formal runs unless a future separately reviewed reset contract
proves equivalent isolation.

The controller atomically commits a result and state update after every run.
Restarting skips only committed Run IDs.  A partial Native directory without a
committed result is not silently retried; it requires explicit evidence review.
All failure states preserve the completed evidence and keep Main locked unless
the automatic Noise transition was already persisted.

## Execution boundary

The controller and its tests perform no GPU work during engineering review.
Formal execution requires the reviewed code commit, a clean worktree, the
bound authorization record, and a startup report identifying the actual
server, GPU, driver, CUDA, PyTorch, vLLM, model, tokenizer, and reserved window.
