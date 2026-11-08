# Bounded Native Cost-Aware Evaluation

This is the single execution entry point for the M1-authorized 1.5B CUDA
evaluation. It runs, in order, the target-resource preflight, the frozen
70-pair PrefillReload measurement, campaign materialization and validation,
the integrated three-arm Native fidelity gate, authorization, all 54 formal
runs, offline evaluation, and evidence packaging.

The execution host must provide an RTX 4090-class 24 GB GPU, vLLM 0.27.1,
CUDA, the frozen Qwen model revision, a clean checkout of the exact tooling
commit, and the W1-C source evidence at the paths bound by
`continuum-native-cost-aware-formal-freeze-candidate-v1.json`.

Run from the repository root:

```bash
python -m kvopt.workload.continuum_bounded_pipeline run-all \
  --repository . \
  --output-root artifacts/continuum-native-cost-aware-bounded-runs-v1 \
  --protocol configs/phase2/continuum-native-cost-aware-bounded-protocol-v1.json \
  --source-freeze configs/phase2/continuum-native-cost-aware-formal-freeze-candidate-v1.json \
  --profile-protocol configs/phase2/continuum-native-cost-aware-bounded-prefill-profile-v1.json \
  --profile-base-config configs/phase2/continuum-native-cost-aware-bounded-profile-base.json \
  --profile-interpretation-contract configs/phase2/continuum-native-cost-aware-profile-interpretation-v1.json \
  --budget-hours 30
```

The preserved RTX 4090D v4 Profile may be continued without repeating its 70
pairs. The command below copies the immutable raw Profile and resource record,
derives the separately identified non-negative cost view authorized by M1, and
then proceeds through Native fidelity and the 54-run campaign:

```bash
python -m kvopt.workload.continuum_bounded_pipeline resume-after-profile \
  --repository . \
  --output-root artifacts/continuum-native-cost-aware-bounded-runs-v5 \
  --protocol configs/phase2/continuum-native-cost-aware-bounded-protocol-v1.json \
  --source-freeze configs/phase2/continuum-native-cost-aware-formal-freeze-candidate-v1.json \
  --raw-profile artifacts/continuum-native-cost-aware-bounded-runs-v4/profile/prefill-reload-profile.json \
  --resource-record artifacts/continuum-native-cost-aware-bounded-runs-v4/preflight/resource-record.json \
  --profile-interpretation-contract configs/phase2/continuum-native-cost-aware-profile-interpretation-v1.json \
  --budget-hours 30
```

The raw 1024-token median, raw deltas and uncertainty interval remain intact.
Only the derived runtime view uses the approved 0-second non-negative estimate;
non-cold A1 ordering remains `INCONCLUSIVE_COST_ORDERING` where the uncertainty
envelope can admit another legal selection.

The command is deliberately fail-closed. It stops before formal outcomes when
resource, exact-token, Profile, Native fidelity, cross-arm, Git, hash, or cost
bindings fail. A failed execution writes `execution-summary.json` and creates
a sibling `*-partial-evidence.tar.gz`; it does not silently resume, replace a
failed run, or weaken the frozen protocol.

The final report treats the nine predefined workload groups as the independent
units. Request-level validity and mechanism realization are reported
separately: a valid run with no content-identified physical eviction remains
in the results as `NOT_REALIZED`, rather than being silently removed or being
misrepresented as proof of policy equivalence.

The replay uses controlled logical lifecycle time and real Native monotonic
time. Logical time advances only at frozen event boundaries while no Native
request is inflight; no original gap is converted into a wall-clock sleep.
The output records both domains and never uses their raw difference as a
latency or TTL measurement.
