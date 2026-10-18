# Phase 2G · A1 Gate 2 — Algorithm and Metric Review

**Verdict: the metric implementation in PR #54 is wrong, and the paired conclusion
cannot be re-verified on this machine because the raw evidence is not present.**

Two separate statements, and they need to stay separate:

- the **metric defect is proven** from the source that PR #54 ships;
- the **numerical re-verification is not computable here**, so the published A1
  result stands only as reported by M6 until the corrected evaluator is run against
  the same artifacts.

---

## 1. Task 1.1 — Token metric consistency

### 1.1.1 What the frozen protocol says

From `src/kvopt/profiling/runtime_evidence.py::derive_level_b_token_semantics`:

```text
N  native_prompt_tokens
E  eligible_prefix_tokens
C  native_cached_prefix_tokens

actual_prefill_tokens  = N - C
observed_recomputed    = E - C        <- the frozen recomputation metric
new_suffix_tokens      = N - E
invariant: W = R + S, enforced with ArtifactValidationError
```

### 1.1.2 What PR #54 computes

`phase2g_a1_bounded_gate.py` built its observations as

```python
"recomputed_tokens": native_prompt_tokens - native_cached_prefix_tokens   # = N - C = W
```

and then summed that same quantity twice:

```python
"aggregate_recomputed_tokens":     sum(recomputed_tokens)   # actually W
"aggregate_actual_prefill_tokens": sum(recomputed_tokens)   # also W
```

So three defects, all mechanical:

1. `N - C` is actual prefill, not recomputation;
2. the frozen recomputation metric `E - C` was **never computed**;
3. the two aggregate fields were **identical**, so one of the two labels had to be
   wrong — and the report did not notice.

Verified by reading the source in the PR branch; not inferred from the results.

### 1.1.3 Does the defect change the paired conclusion?

Not necessarily, and the condition is exact. With `Δ = A1 − A0` per matched request:

```text
W = R + S   =>   ΔW = ΔR + ΔS
=>   ΔW = ΔR   <=>   ΔS = 0   <=>   every paired request has identical (N, E)
```

`E` is derived from the request's own block hashes against *prior recorded* hashes
and capped at `(N − 1) // block_size`, so it does not depend on cache occupancy and
is arm-invariant **provided both arms observe the same, equally complete request
set**. That proviso is precisely Task 1.3, so the two checks are not independent.

Consequence for the published numbers:

- if request completeness holds in every pair, then `Δ(N − C) = Δ(E − C)` exactly,
  and the reported directions (**12 BETTER / 1 WORSE / 22 TIED / 1 INCONCLUSIVE**,
  mean Δ = −24.23, median Δ = 0) survive unchanged, because the solver would have
  compared deltas of the same size;
- if any pair has an unpaired or partially observed population, the two metrics
  diverge and the stale number must be replaced.

**I did not choose the metric by the direction of the effect.** The metric was fixed
first, from the source; the equivalence condition is stated independently of
whether it favours A1, and the test suite includes a constructed case where the two
metrics disagree *in sign* (prefill improves by 40 tokens while recomputation
regresses by 40).

### 1.1.4 What was changed

| Item | Change |
|---|---|
| observation construction | now uses `runtime_evidence` frozen derivation via `phase2g_a1_metric.request_token_facts` |
| `aggregate_recomputed_tokens` | now `Σ(E − C)` |
| `aggregate_actual_prefill_tokens` | now `Σ(N − C)`, previously duplicated the above |
| `aggregate_new_suffix_tokens` | added, so the identity is checked rather than trusted |
| per pair | `metric_equivalence` ∈ {`EXACT`, `NOT_EQUIVALENT`, `NOT_COMPUTABLE`}, with the reason and the differing request ids |
| report | `metric_equivalence_counts`, `request_completeness_counts`, plus `metric_definition` |

Fail-closed: a request whose `E − C` cannot be derived now raises instead of being
dropped, so a total can never be quietly computed over a smaller population.

**Consequence that must be expected on re-run.** The old evaluator built its
observation map from `VLLM_NATIVE_REQUEST_OBSERVATION` events only, so a request
without one was **silently omitted** from the aggregate — the precise under-counting
Task 1.3 forbids. The patched path raises, which turns such a run `INVALID` instead
of quietly cheaper-looking. Verified end-to-end: loading a real run whose requests
have no native observation fails with `native_request_observation_missing` rather
than returning a partial sum. If the Gate 2 re-run reports fewer comparable pairs
than before, that is the reason, and it is the intended behaviour.


### 1.1.5 Not computable here

The Gate 2 artifact root (144 run manifests, packaged under `artifacts/`) is
**not present on this machine** and is excluded from version control. Therefore:

```text
NOT_COMPUTABLE: re-running the corrected evaluator on the Gate 2 evidence
```

`python -m kvopt.profiling.phase2g_gate2_review --manifest <m> --run-root <r>`
returns exit code 2 with that message when the root is missing, and otherwise emits
the three checks. **This is the specific gap**: the corrected numbers require one
execution against the existing artifacts — no new native runs.

---

## 2. Task 1.2 — Physical evidence attribution

What PR #54 establishes, and at what strength:

| Layer | Status |
|---|---|
| **Logical release** | Confirmed. `FORCED_RELEASE_DECISION` records the selected entries; the pairing compares them directly. |
| **Physical eviction events** | Confirmed to occur (`VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED`), but content identity is mapped by prefix-matching `native_cache_key_before` against recorded block hashes. An eviction whose key matches **zero or several** hashes is counted as unmapped. |
| **Eviction → recomputation causality** | **Not established per event.** The paired token delta is a strategy-level measurement. No per-eviction attribution is claimed, and none should be inferred. |

The evaluator now reports `mapped_fraction` and refuses to promote a pair to a
token verdict unless selection *and* physical signatures both diverge — which is the
correct guard, and is why `NOT_REALIZED` and `NO_PHYSICAL_DIVERGENCE` exist as
separate states. Incomplete per-event attribution lowers the evidence level for
*mechanism* claims; it does not invalidate the strategy-level paired comparison,
which is the distinction M1 asked for.

---

## 3. Task 1.3 — Request completeness

The evaluator now emits, per pair:

```text
request_completeness ∈ {COMPLETE, UNPAIRED, NO_ELIGIBLE_REQUESTS}
unpaired_request_ids
paired_eligible_request_count
```

and the campaign report aggregates `request_completeness_counts`. A pair whose arms
observe different eligible populations is marked `UNPAIRED` and its metric verdict
becomes `NOT_COMPUTABLE`, rather than being averaged in.

Under-counting one arm is the exact failure mode that would bias the result toward
whichever arm dropped requests, so it is treated as a hard gate on the metric, not
as a footnote.

---

## 4. Where the A1 result stands

**Trustworthy now:**

- A1 and A0 differ in *entry release selection* in 13 scenarios, both arms always
  meeting the pressure target — that is selection-level evidence from an
  independent source (Phase 2G Gate 1 and the offline study) and does not depend on
  the token metric.
- A0 reproduces frozen Continuum behaviour (fidelity 1.0 in the offline path).
- The pairing design (same trace, same requests, same materialized tokens, same
  git sha) is sound and enforced fail-closed.

**Pending one re-run:**

- the token deltas. The published distribution and mean remain **provisional**
  until the corrected evaluator is executed on the same 144-run artifact root.

**Not established at all:**

- per-eviction causal attribution;
- any mechanism claim tying the 13 divergent scenarios to specific recomputed blocks.

**Validity conditions and failure conditions for A1** (unchanged by this review, and
supported by the offline study):

| | |
|---|---|
| Effective when | the reuse proxy reorders entries relative to the retention deadline, i.e. `N_i` varies and `q_i` varies independently of it |
| Fails when | `q_i` mis-ranks the entries that actually return — the controlled `c_a1_worse` scenario: the estimate prefers the wrong entry and the realised loss doubles |
| Degenerate when | all candidates have equal `N_i` (score becomes monotone in `q`, i.e. the deadline order) |
| Structural limit | only two-entry lookahead; decisions needing three-way co-ownership fall back to deadline order |

**Merge recommendation: do not merge as final until the corrected evaluator has been
run.** The code fix is required, and the corrected run is cheap (replay of existing
artifacts). Merging on the current numbers would mean shipping a report whose
primary metric is the wrong quantity.

---

## 5. Reproduce

```bash
# unit + algebraic proof of the metric relationship (no artifacts needed)
python -m pytest tests/test_phase2g_a1_metric.py tests/test_phase2g_a1_bounded_gate.py -q

# the three checks, against the Gate 2 artifact root
PYTHONPATH=src python -m kvopt.profiling.phase2g_gate2_review \
    --manifest <campaign-manifest.json> --run-root <runs-dir> --output review.json

# corrected campaign report
python -m kvopt.profiling.phase2g_a1_bounded_gate \
    --manifest <campaign-manifest.json> --run-root <runs-dir> --output gate-report.json
```


## M1 closeout scope (2026-10-18)

The evaluator implementation is accepted as a corrected post-processing path, **not** as an independently recomputed final Gate 2 result. The packaged 144-run attachment is not accessible in the review execution environment; the historical `12/1/22` and `-24.23` numbers therefore remain **PROVISIONAL**. The frozen raw experiment is preserved; no new Native runs or silent substitutions are authorized. The corrected evaluator must be run against that same artifact archive before its aggregate results can be cited as frozen A1 evidence.

The A2 study is a legacy H1-derived, singly-owned selection diagnostic. It is not a verdict on Phase 2G Gate 2's block-level choice space. Shared block co-ownership is fail-closed until multi-chain content identity and marginal-cost support exist.
