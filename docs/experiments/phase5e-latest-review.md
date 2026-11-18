# Phase 5E Latest Review — PR #121

**Reviewer:** M4  
**User-cited HEAD:** `21de40c1aa0626f14f73bd5e4034c553b28b0dfd`  
**Current PR HEAD at review:** `7b03b57f9d04cd0a5728852704bc52bc8a67740d`  
**PR:** <https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/121>  
**Scope:** targeted re-review of the previous contract gaps and newly introduced risks. No GPU, Native smoke, or merge.

---

## 0. Verdict

**Part A: `NOT_READY_FOR_AUTHORIZATION` as written.**  
**Part B: `NOT_READY` — correct.**  
**Plan direction:** accepted; the prior order/identity/budget/seal/abort findings are substantially fixed. Two execution-critical issues remain, plus one end-to-end readiness gap.

The PR advanced from the user-cited `21de40c` to `7b03b57` with a final freeze package. I reviewed both; the remaining findings apply to the current head. The final commit changes packaging/code bindings, not the pressure geometry issue.

---

## 1. Prior findings closed

| Prior finding | Latest status |
|---|---|
| enqueue order accepted without derivation | **Fixed**: `derive_native_enqueue_order()` and exact comparison; negative test added. |
| fixture could have ≠4×2 requests | **Fixed**: exactly 4 Programs × 2 requests; per-Program ordinals 1/2. |
| pressure lacked expected inflight set | **Fixed**: `PressureFixture.expected_inflight_request_ids`, controller and Native snapshot checks. |
| no serialized dispatch rule | **Fixed**: `SERIAL_DISPATCH_IN_FROZEN_ORDER_WITHOUT_COMPLETION_WAIT_V1`; plan/controller order gate. |
| KV budget lacked engine cap/reserve | **Fixed**: `engine_max_num_seqs=4`, adapter capacity equality, pressure reserve, prompt/generation caps, static budget checks. |
| Workload Seal binding absent | **Fixed**: reused Phase 5A Seal; plan hash-binds seal, model/tokenizer, sampling, engine config, pressure. |
| abort readiness could be enabled by string | **Fixed**: abort readiness forced `NOT_READY`; source must be `None`. |
| Part A finish ambiguity | **Fixed**: explicit `classify_part_a_finish`; length separated; stop/abort excluded. |
| EngineCore identity | **Fixed** in pressure executor: Adapter/Scheduler/KV instrumentation must be the same EngineCore object; BlockPool ownership checked. |
| freeze package | **Added**: `phase5e_freeze.py` + manifest/confirmation request, still `execution_authorized=false`. |

This is a meaningful improvement. The plan is close.

---

## 2. Remaining blocking findings

### P5E-R1 — Pressure free-block geometry is not achievable at the declared trigger

**Location:** plan §7/§8 (pressure boundary, 1,536 free blocks, r2 at 2.0, pressure at 2.001); `PressureFixture` and `Phase5GPUConformancePlan.__post_init__`; `PinnedNativeBlockPoolPressureExecutor.execute()`.

The plan fixes:

```text
request prompt = 1,984 tokens = 124 blocks
generation     = 64 tokens   = 4 blocks
4 requests × 128 blocks = 512 blocks
free before pressure = 2,048 − 512 = 1,536
pressure allocation = 1,536 blocks
```

The boundary fires at **2.001s**, after `p4:r2` has a verified **Native submission**. A Native submission is not a guarantee that all four r2 requests have already allocated their **full prompt + full generation** 128 blocks. The executor checks:

```python
before = block_pool.get_num_free_blocks()
if before != request.expected_free_blocks_before:
    raise ...
```

At the declared trigger, the four r2 requests may have allocated only their prompt blocks (or less), so the observed free count can differ from 1,536 and the run can fail before pressure. Conversely, if the count happens to match, it may be for a different allocation state than the sealed “full wave” geometry.

The document says the “first measured wave contains four Native-inflight r2 requests” but does not freeze an allocation watermark. In-flight does not imply full KV allocation.

**Required fix:** choose one of:

1. add a frozen **allocation watermark** trigger (e.g., after all four r2 requests have a verified `allocated_blocks == prompt_blocks + generation_blocks`, or after a verified first decode/first output), and record the watermark in the Seal; or
2. redefine the expected free geometry for the actual trigger (prompt-only) and reserve the 16 generation blocks explicitly; or
3. use a dedicated pressure fixture with a deterministic allocation state and calibrate the free count.

The pressure trigger must be a **Native allocation/state predicate**, not merely Native submission. Add a negative test where the executor sees a free count that differs by a known amount.

### P5E-R2 — The r1 completion barrier is asserted, not enforced by the arrival contract

**Location:** plan §7 (“the four r1 requests ... must naturally complete before the tied r2 wave”); r2 at 2.0; pressure at 2.001.

The controller schedules r2 by logical offset; it does not wait for an explicit **all four r1 natural terminals** barrier before the r2 arrives. If r1 Native completion is late, r2 submissions may be delayed or the pressure inflight set will not equal the four r2 IDs. The plan’s fixed 2.0s is a timing assumption, not a proof.

**Required fix:** add a frozen `r1_natural_completion_barrier` event/predicate before r2 dispatch, or define r2’s logical arrival relative to the barrier and record lateness. The pressure gate must require the barrier was observed, not just that r2 was submitted.

### P5E-R3 — No end-to-end GPU runner exists in this PR

**Location:** `scripts/spikes/prepare_phase5e_part_a.py` only materializes the freeze; `phase5e_freeze.py` writes manifests. There is no script that:

- constructs AsyncLLM with `VLLM_ENABLE_V1_MULTIPROCESSING=0`;
- installs the lifecycle proxy;
- constructs `PinnedNativeBlockPoolPressureExecutor` and its `evidence_reader`;
- executes the four-Program plan through the controller;
- evaluates G0–G8 and writes the execution archive.

`PinnedNativeBlockPoolPressureExecutor` is a concrete pressure executor, and Phase5D adapter provides the lifecycle; but the **runner wiring** is not present. “Ready for authorization review” should not be confused with “executable without M6 implementation.”

**Required fix:** either provide a CPU/Mock end-to-end runner test that exercises the full execute→gate→archive path, or explicitly label Part A as `READY_FOR_M6_IMPLEMENTATION` rather than `READY_FOR_AUTHORIZATION_REVIEW`. M1 should not authorize a GPU run until the runner path is exercised at least in Mock.

---

## 3. Non-blocking corrections

- `engine_configuration_sha256` is a fixed string/hash from the builder; the plan does not validate it against the actual resource budget or runtime config. Bind the actual engine config object and compare.
- `git_sha`, model revision and tokenizer revision are only non-empty strings in `Phase5GPUConformancePlan`; add format checks and freeze-package verification.
- `PressureExecutionEvidence` does not carry `expected_free_blocks_before`; the adapter checks it, but the evidence object should include it for independent audit.
- `P5E-G3` peak inflight is described as “Native inflight”; define exact interval endpoints (`NATIVE_SUBMISSION_OBSERVED` to `NATIVE_TERMINAL_CONFIRMED`) and whether frontend terminal/failure states affect it. The current plan implies this but should be machine-readable.
- The plan accepts `LENGTH` as a Part A finish class but labels it separately; ensure G4’s `NATURAL_FINISH` acceptance explicitly includes/excludes LENGTH and reports it separately, not as EOS.
- The “30-minute reservation” and “10-minute timeout / 60-second grace” are consistent as an outer envelope, but the run identity should record both and fail if the run exceeds the hard timeout.
- Part B remains correct: no native abort confirmation; do not allow any string source.

---

## 4. Final P5E recommendation

**Do not authorize Part A GPU execution at current HEAD.** Fix P5E-R1 and P5E-R2, and either provide the end-to-end Mock runner (P5E-R3) or re-label the plan as M6-implementation-ready rather than authorization-ready.

After those fixes, the remaining conformance plan is credible: exact order derivation, 4×2 fixture, pressure identity set, same-EngineCore check, seal binding, natural/abort separation, and freeze packaging are all materially better.

No GPU, Native smoke, trace acquisition, algorithm execution, or merge was performed in this review. I did not independently rerun the claimed 2,038 tests; this is a static review of the plan/code/tests at the cited and current heads.
