# Phase 2I A3 Target CUDA Native Preflight

Status: **PREFLIGHT_01 FAIL_CLOSED / RUNTIME-EVIDENCE REPAIR UNDER REVIEW**.

This is one bounded CUDA Native correctness run, not an A3 effect campaign.
The implementation branch starts from merged `main` commit
`35af35a2e06e67cc126f780395966a83cbd5f444`.

## First execution and immutable failure record

`PHASE2I_A3_TARGET_CUDA_PREFLIGHT_01` completed the 180-request HR02 Native
Replay but failed the persisted-evidence gates. Gate C passed with two
content-verified, non-fallback multi-candidate A3 decisions. Gate O failed:
756 physical evictions could not be uniquely attributed to the three A3 Entry
decisions and therefore remain non-causal observations. The first archive is
immutable and is not an input to an effect claim.

The persisted lifecycle exposed three distinct cases that the original event
scope had conflated:

- decision 123: a real non-fallback A3 Entry decision inside the round-40
  controlled-pressure context, with no pending physical plan;
- decision 153: a real non-fallback A3 Entry decision during an ordinary
  two-request Native drain batch;
- decision 188: an A1-fallback Entry decision during another ordinary drain
  batch;
- unrelated allocation attempts at the pressure barriers, with empty A3
  traces, which must not be reported as A3 Entry decisions.

The repair does not change the workload, pressure, A3 formula, A1 fallback or
Native ownership. It introduces one explicit Native execution context with a
deterministic ID, boundary type and real request-ID set. Controlled pressure,
ordinary single-request execution and multi-request drain batches remain
distinct. Every queue-selection callback consumes only the immediately
preceding plan.

Only a Forced Release creates `NATIVE_ENTRY_RELEASE_SELECTION_PLAN`. A pure
allocator call creates `NATIVE_ALLOCATION_ATTEMPT`. A real Entry plan either
creates a content-bound pending plan or records one explicit outcome:
`PHYSICAL_EVICTION_OBSERVED`, `PARTIAL_PHYSICAL_EVICTION_OBSERVED`,
`NO_PHYSICAL_EVICTION_OBSERVED`, or `EVIDENCE_MISSING`. Pending plans expire at
their exact Native execution-context boundary and cannot be borrowed by a
later request.

Gate D now joins A3 Decision, Forced Release and Entry SelectionPlan without
requiring a physical outcome. Gate O independently requires at least one
required A3 decision to have complete Block ID and Content Identity physical
attribution. An explicit no-eviction outcome remains valid evidence but cannot
make Gate O pass.

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
- Gate C: content-verified ChainDepth proof, independent
  `q × prefill × S / m` recomputation, and independent strict
  `(score, deadline, key)` ordering reconstruction. Numeric booleans, implicit
  integer conversion, missing/duplicate selected markers, and winner/marker
  disagreement all fail closed;
- Gate D: at least one non-fallback multi-candidate A3 decision, exact candidate
  score/selection recomputation, and equality with the submitted Entry Release
  and Native SelectionPlan. A1/A3 divergence is diagnostic, not required;
- Gate O: unique Decision/Boundary/Stage/Pressure/Counter/Pending-Plan join and
  exact Block ID plus Content Identity physical-eviction attribution.

A `NO_PHYSICAL_EVICTION_OBSERVED` result without a Pending Plan is valid only
for a genuinely hashless Native return. It must list every hashless Block ID and
that set must exactly equal the SelectionPlan set. Missing Pending evidence or
an empty fabricated outcome cannot masquerade as a hashless result.

Any failed run or gate produces `FAIL_CLOSED`. Unmatched physical events are
counted as missingness and never inferred as attributable. The run preserves
right-censoring and makes no benefit claim.

## Resource and stop control

Target: the previously bound RTX 4090D CUDA environment, vLLM 0.27.1, PyTorch
2.13.0+cu130. The outer invocation must use a 30-minute timeout with a 60-second
forced termination grace period. The first Native run has already been
consumed. This repair PR does not start another run. After CPU/Mock review, at
most one separately authorized `REPLACEMENT_PREFLIGHT_02` may run with a new
Freeze Record, output directory and archive. Its record must bind the immutable
first-failure archive SHA-256. No parameter, pressure, workload or strategy
change is allowed.

The replacement Freeze Record is deliberately emitted with
`execution_authorized=false`. Preparation opens the predecessor archive without
extracting it, validates its original v1 Freeze Record, failed Native Preflight
Report and Native Run Manifest as one coherent execution, and compares the HR02
config, trace, explicit request tokens, pressure tokens, logical timeline and
profile SHA-256 bindings field by field. It then emits an authorization request.
Only a separately signed M1 authorization record can enable execution. The
Freeze Candidate embeds the reviewed M1 SSH-Ed25519 public key and its SHA-256;
the Runner verifies the detached signature. Editing the request or merely
setting `execution_authorized=true` is insufficient. The signed record binds
the reviewed Git SHA, replacement Freeze Record SHA, predecessor Archive SHA,
Run ID, one-execution limit, 1,800-second timeout and 60-second termination
grace.

The `(Replacement Run ID, Freeze SHA)` pair has one atomic `O_EXCL` consumption
receipt stored beside the immutable predecessor archive. Changing the
authorization file, authorization ID or output directory cannot consume it
again. The public `run` command is a bounded parent process; its child requires
a one-use capability delivered through an inherited anonymous file descriptor
and bound to the actual parent PID. Environment variables and direct `_run-once`
invocation cannot mint it. The parent creates an independent process session,
sends
SIGINT at 30 minutes, kills after the 60-second grace if necessary, and packages
inputs, authorization, partial or complete output, execution envelope and
recursive hashes for success, failure or timeout.

The final archive path and output directory are checked before GPU startup.
Packaging writes to a same-directory temporary archive, rereads every member,
verifies required evidence members and only then atomically renames it into
place. Path collisions, compression interruption and incomplete archives leave
no final archive. Process-group termination prevents GPU grandchildren from
surviving a timeout.

The deliverable contains the freeze record, environment record, raw run files,
Native gate report and recursive SHA-256 manifest. The replacement archive must
be produced for either PASS or FAIL and preserve all explicit missingness and
physical-outcome states. No third GPU preflight is permitted.

Runtime startup fails closed unless the environment reports exactly RTX 4090D,
vLLM 0.27.1, PyTorch 2.13.0+cu130 and CUDA 13.0. Right-censoring status is
derived by comparing frozen endpoint IDs with persisted endpoint events; it is
not a constant report field.
