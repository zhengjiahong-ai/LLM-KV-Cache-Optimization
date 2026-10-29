# Phase 2I A3 Target CUDA Native Preflight

Status: **AUTHORIZED / NOT YET EXECUTED**.

This is one bounded CUDA Native correctness run, not an A3 effect campaign.
The implementation branch starts from merged `main` commit
`35af35a2e06e67cc126f780395966a83cbd5f444`.

## Frozen source and permitted derivation

The preflight reuses the already executed Phase 2H
`hr02-short-gap-long-context-a1-repeat-1` input because it supplied three real
multi-candidate entry decisions without changing pressure after observing a
policy result. Preparation verifies and preserves:

- Qwen2.5-Coder-1.5B-Instruct model/tokenizer revision
  `d18ecad881a290f0c792f1c2b5dbee1820d4a424`;
- 180 exact-token requests and their submitted-token SHA-256 bindings;
- 2,048 blocks of 16 tokens;
- HR02 pressure geometry (`required=379`, `initial_shortage=128`);
- fixed barriers after rounds 40, 50 and 55 and their pressure Token IDs;
- the frozen interpreted PrefillReload profile.

Only the reviewed integration identity changes: campaign kind becomes
`phase2i_a3_native_integration`, entry release policy becomes A3, block policy
remains A0, and the backend/policy labels identify this preflight. The derived
configuration, unchanged trace, profile and execution Git commit are sealed in
`freeze-record.json` before GPU execution.

## Fail-closed execution

`scripts.spikes.run_phase2i_a3_cuda_preflight prepare` refuses source drift,
token drift, an unclean worktree or a non-frozen geometry. The `run` command
rechecks all file hashes and the exact Git SHA, records CUDA/vLLM/PyTorch/GPU
identity, performs one Native run, and then reloads `events.jsonl` from disk.

The persisted evidence is independently evaluated as follows:

- Gate I: Native-live process, event-index and pressure-clock binding;
- Gate C: content-verified ChainDepth proof and independent
  `q × prefill × S / m` recomputation;
- Gate D: at least one non-fallback multi-candidate A3 decision, exact candidate
  score/selection recomputation, and equality with the submitted Entry Release
  and Native SelectionPlan. A1/A3 divergence is diagnostic, not required;
- Gate O: unique Decision/Boundary/Stage/Pressure/Counter/Pending-Plan join and
  exact Block ID plus Content Identity physical-eviction attribution.

Any failed run or gate produces `FAIL_CLOSED`. Unmatched physical events are
counted as missingness and never inferred as attributable. The run preserves
right-censoring and makes no benefit claim.

## Resource and stop control

Target: the previously bound RTX 4090D CUDA environment, vLLM 0.27.1, PyTorch
2.13.0+cu130. The outer invocation must use a 30-minute timeout with a 60-second
forced termination grace period. Only one Native run is authorized. No parameter,
pressure, workload or strategy change is allowed after preparation.

The deliverable contains the freeze record, environment record, raw run files,
Native gate report and recursive SHA-256 manifest. The archive is produced only
after `PASS_NATIVE_PREFLIGHT`.
