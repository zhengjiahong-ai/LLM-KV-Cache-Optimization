# Phase 5 SWE Calibration execution preparation

**Status:** `FAIL_CLOSED_EXECUTION_NOT_READY`

This preparation is CPU/interface work only. It does not authorize or claim a
GPU Calibration run.

## Frozen execution population

- 4 Calibration Groups: `SWE_G01` through `SWE_G04`.
- 6 systems and 3 runtime repeats: 72 runs.
- 16 independent Programs.
- 1,506 observed model requests across the four shared Group replay templates.
- 1,490 observed within-Session tool gaps; no missing or negative gap.
- Frozen-Poisson Program starts and empirical within-Session timing are reused
  by all six systems and all repeats.

The private preparation root contains the exact normalized-trace,
token-materialization and tool-fixture file bindings. The public repository
does not contain third-party trace bodies or derived token arrays.

## Implemented pre-execution contracts

1. The exact 72-run inventory binds Group, system, repeat, policy identity,
   private inputs and shared replay-template SHA-256.
2. Every run requires a fresh process, fresh EngineCore, empty-cache preflight,
   no preheat and no automatic retry.
3. Native, project A0, A1 and A3 use the same EngineCore Utility-RPC execution
   foundation. A3 retains the accepted P5E-A-01 Native evidence binding.
4. Official Continuum is pinned to upstream revision
   `316a58794a6ff86b216e579b74fd56ed0c5a911f`; its observation-only plugin does
   not install project policies.
5. Controller timer commands contain only identities already observed at the
   predecessor terminal boundary and the frozen empirical gap duration.
   EngineCore samples the armed timestamp in its own clock domain. The command
   does not carry future Turn content, future reuse outcomes or a frontend
   timestamp.

## Current fail-closed boundary

`DVA_ER_V1` is ready for its first Calibration run to provide Native readiness
evidence. The live BlockPool/FreeQueue/refcount/
protection provider, frozen CPU selector and EngineCore entry-release
coordinator are installed. Controller timer commands are armed only after the
predecessor terminal and are timestamped inside EngineCore. Its first valid
Calibration run has not yet supplied Native readiness evidence. This is allowed
by M1's first-valid-run rule and is not a preliminary GPU run.

Two execution blockers remain.

First, all 16 accepted Calibration token materializations identify
`Qwen/Qwen2.5-Coder-3B-Instruct` revision
`2ffd030b308f6bdd29ee43e7383f30ce8ac2e225`, with chat-template SHA-256
`cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f`.
The frozen Formal Protocol identifies the shared execution model and tokenizer
as `Qwen/Qwen2.5-Coder-1.5B-Instruct` revision
`d18ecad881a290f0c792f1c2b5dbee1820d4a424` and requires identical prompt token
IDs across systems. The preparation records this as
`MODEL_TOKENIZER_IDENTITY:MISMATCH`. It does not silently rematerialize prompts,
change the Protocol or select either identity.

Second, the shared 72-run Calibration runner is not implemented. Its
per-run process lifecycle, exact request dispatcher, archive writer and
first-valid-run readiness validator are not yet implemented. The preparation
therefore remains blocked with:

- `MODEL_TOKENIZER_IDENTITY:MISMATCH`
- `CALIBRATION_RUNNER:NOT_READY`
- `CALIBRATION_RUNNER:ENTRYPOINT_MISSING`

No A0/A1/A3 coordinator is used as a fallback. No timer is synthesized
from a future request or future outcome. The exact DVA selector is wired and
CPU-validated, but the 72-run Calibration must not start until the frozen
execution identity is resolved and the exact runner is implemented against
that resolved identity.

## Execution boundaries

- SWE Calibration GPU execution: authorized by M1, but mechanically blocked by
  the execution-identity conflict and missing shared runner.
- SWE Formal Campaign: not authorized.
- BFCL Derived GPU execution: not authorized.
- Positive benefit, Native conformance for all six systems and Formal sample
  size: not claimed by this preparation.
