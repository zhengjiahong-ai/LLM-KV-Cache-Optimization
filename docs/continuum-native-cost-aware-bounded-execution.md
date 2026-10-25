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
  --budget-hours 30
```

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
