# Phase 3 Option F Final Evaluation Results

**Status:** execution complete; final audit found a G1 enqueue-order failure and process deviation; pending M1/M4 adjudication

**Execution code:** `00a512111f15abddcad329572f6e50ccaaa76775`

**Environment:** NVIDIA GeForce RTX 4090 D, vLLM 0.27.1, PyTorch 2.13.0+cu130, CUDA 13.0

**Immutable evidence archive SHA-256:** `d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8`

This report records the completed Protocol v4 Option F campaign. It does not
amend the frozen protocol, promote diagnostic evidence into a causal claim, or
replace the immutable external evidence archive.

## 1. Execution and evidence integrity

- The one-shot controller completed all **30/30 Noise** and **240/240 Main**
  runs, with no final run failure.
- The automatic transition persisted
  `MAIN_AUTHORIZED_BY_PIPELINE` before dispatching Main.
- The archive contains 270 result records, 270 Native run directories, and 40
  independent N/E/C cell reports.
- The archive structure, its internal SHA-256 manifest, and the locally
  downloaded copy all validated successfully.
- A pre-execution launch attempt stopped before any Native request because
  `VLLM_ENABLE_V1_MULTIPROCESSING=0` was absent. Its failure archive is
  retained separately and is not mixed with the successful campaign.

The transition record describes what the controller persisted, not proof that
all frozen transition gates were evaluated. A later read-only audit found that
the historical transition omitted a complete G1/G4/Cohort ledger. It also
found actual Native enqueue order equal to the frozen order in only 48/240
Main runs. This is a recorded process deviation and retrospective G1 failure;
it is not retroactively relabeled as PASS.

## 2. Noise calibration

The frozen pooled estimator returned:

| Quantity | Result |
| --- | ---: |
| `sigma_run` | 0.0 |
| `sigma_delta` | 0.0 |
| tied threshold | 0.0 |
| FLAT / WEAK / RESPONSIVE sigma | 0.0 / 0.0 / 0.0 |
| max/min stratum-sigma ratio | `UNDEFINED_ALL_STRATUM_SIGMAS_ZERO` |

The pooled estimator was valid and the Noise gate passed. The undefined
diagnostic ratio is the registered zero-denominator state, not a failure of the
pooled estimator.

## 3. Primary Main results

The registered primary estimand is arm minus A0 aggregate recomputed tokens,
with Workload Group as the statistical unit.

| Arm minus A0 | Groups analyzed | Mean delta (tokens) | Interpretation |
| --- | ---: | ---: | --- |
| A1 − A0 | 18 | 0.0 | No observed incremental benefit |
| A2 − A0 | 18 | 0.0 | No observed incremental benefit |
| A3 − A0 | 18 | 0.0 | No observed incremental benefit |
| E0 − A0 | 18 | 0.0 | Deadline-only comparator tied A0 |
| N0 − A0 | 18 | +1918.22 | N0 recomputed more than A0 |

The registered forced-release contrasts also favor A0 over N0:

- H3-0: mean `A0 − N0 = −3123.2` tokens over 20 Groups / 38 cells.
- H3-R: mean `A0 − N0 = −6435.56` tokens over 9 RESPONSIVE Groups / 16 cells.

These numbers support the incremental value of the frozen forced Entry Release
path under the controlled Phase 3 design. They are not a complete
Continuum-versus-Vanilla-vLLM system comparison.

## 4. Decision exposure and the null cost-aware result

Across Main, each of A0/A1/A2/A3/E0 emitted 127 forced Entry Release decisions,
selection plans, and physical-outcome records. The cost-aware arms therefore
executed their registered paths; the zero deltas are not explained by an arm
being absent from the runtime.

For A3 specifically:

- all 127 decisions used `step2_sufficient`;
- 120 decisions had one audited candidate;
- only 7 decisions had two audited candidates;
- A3 selected the same entry as frozen A1 in all 127 decisions.

Under the registered branch taxonomy this is S2A=127, S2B=0 and S2C=0
(C1: 63/0/0; C2: 64/0/0). A3 and E0 selected different programs in zero
decisions. G3-CM therefore has zero PROFILE_ROBUST and zero PROFILE_SENSITIVE
discriminable decisions; `H2 = NOT_EVALUABLE`.

This is weak exposure for demonstrating incremental value from the A3 cost
model. Under the frozen campaign, the model did not change an A1 choice, so a
zero A3−A0 effect does not establish general equivalence of the policies.

Cross-run diagnostic comparison found nearly identical effective choices in
the other registered variants: 39/40 cells had the same selected program for
A0/A1 and A3/E0, and 39/40 had the same A0/A2 planned Native block sequence.
These comparisons are diagnostic because per-process Native prefix hashes and
physical block identifiers are not portable identities across independent
runs. The independent N/E/C outcome remains the formal effect evidence.

## 5. Conclusions and boundaries

1. The frozen A0 forced Entry Release path reduced eligible-prefix
   recomputation relative to N0 in this controlled cohort.
2. A1, A2, A3, and E0 produced no measured recomputation improvement over A0.
3. The cost-aware variants had limited decision leverage, especially A3, so
   the correct conclusion is **no observed incremental benefit**, not proof of
   universal policy equivalence.
4. Phase 2I did not establish unique physical causal attribution, and Phase 3
   does not repair that limitation. Physical event records are supporting
   diagnostics; the formal effect conclusion rests on independent N/E/C.
5. All arms used the Native scheduler, and there is no Static-TTL arm. The
   campaign therefore does not estimate scheduler or Dynamic-TTL causal effects.

No additional GPU execution is required for this report. Any algorithm redesign
or independent full-system comparison belongs to a separately authorized later
phase.

The effect summaries above are bounded descriptive results from the completed
execution. Because G1 enqueue-order equality failed, they must not be presented
as an all-gates-passed confirmatory result without M1/M4 adjudication.

## 6. Reproducibility identities

| Artifact | SHA-256 |
| --- | --- |
| Final evidence archive | `d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8` |
| `pipeline-state.json` | `3fed697e36661f1114618391cda23c2a485e42e3c09e81287513d3c872b97726` |
| `noise-report.json` | `3ddf57fb5cebab177da36db2ee190aa0875cb08873d771a3f869c3caae1e46b6` |
| `stage-transition.json` | `4b5e585d0a6382321a872f5869e39486ebe7a1c6891ec8ce76311ca0f649430c` |
| `main-report.json` | `aabf1588758ebe6631388fb50c28f5cf1f2c288b22a968d33f17a87a8e592896` |
| Internal SHA manifest | `3bff2d6189d0eb8fabee7ba09f89490fa36f390da855af459974403ce038b4ad` |
| Preserved launch-failure archive | `3c81dc5eba2fe7e1d21ab6fe7a3b1eb774e624e827e8e3d774ebdf9886c0a3f5` |
| Authorization record | `d4ce34d41494a14c5862275bff8293670b1464d6b4b7efd6f07cf4f602af68b3` |
| Prelaunch validation | `2beed32ef6babd508f7314a67371f2d02d34a1e12d9ef7e6aa06103c505fb7da` |
