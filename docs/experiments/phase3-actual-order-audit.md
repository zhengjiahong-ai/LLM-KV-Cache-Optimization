# Phase 3 Actual Native Order and E Sensitivity Audit

**Status:** read-only audit complete; pending M1/M4 adjudication

**Immutable execution archive:**
`d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8`

This audit answers whether the 192 run-level Native enqueue-order deviations
changed cross-arm comparability or the independently derived eligible-prefix
quantity `E`. It reads the original archive without modifying or replacing any
historical evidence and performs no GPU execution.

## 1. Terminology and protocol boundary

Three checks are deliberately kept separate:

1. **Protocol G1 arm isolation** checks equality of frozen inputs,
   configuration, independently derived E, and N0 Pressure Boundaries across
   arms.
2. **Frozen replay execution conformance** checks whether each observed Native
   submission sequence equals the Native enqueue order in the Cohort Seal.
3. **Cross-arm execution-order equality** checks whether all six arms in one
   Group × Condition cell observed the same Native submission sequence.

The second check failed historically. This report does not rename that failure
as a G1 PASS or retroactively alter the Protocol. It determines whether the
common deviation also broke the first or third checks.

## 2. Actual submission sequences

The complete `VLLM_REQUEST_SUBMITTED` request-ID sequence was extracted for
every one of the 240 Main runs. Each observed sequence was hashed independently
and compared both with the Cohort Seal and with the other five arms in its
cell.

| Cell classification | Count |
| --- | ---: |
| Exact to frozen order | 8 |
| Six arms identical, but all differ from frozen order | 32 |
| Six arms differ from one another | 0 |

Thus the 192 mismatching runs are exactly 32 cells × 6 arms with a shared
replay deviation. No cell has an arm-specific actual submission order.

## 3. Actual-order E reconstruction

For each of 5,760 request-arm observations, the evaluator reconstructs E from
the observed submission stream and immutable evidence. It distinguishes:

- actual earlier submission;
- logical completion and Snapshot availability before the consumer;
- same-scheduler-iteration and earlier-scheduler-iteration visibility;
- event-log position, which is never treated alone as proof of visibility.

A predecessor Snapshot already visible before consumer submission is accepted
as historical evidence. A later Snapshot is accepted only when the existing
Native visibility audit proves the relevant same-batch or earlier-forward
physical-prefix relation. Missing or ambiguous evidence produces
`INDETERMINATE`; it is never filled from C.

Results:

| Check | Result |
| --- | ---: |
| Request-arm audits | 5,760 |
| Cells with determinate actual E | 40/40 |
| Cells with indeterminate E | 0/40 |
| Cells with cross-arm E disagreement | 0/40 |
| Request-arm E values changed from the frozen-contract evaluation | 0/5,760 |

The shared order deviation therefore did not change E for this archive. This
is an evidence-specific result, not a claim that enqueue order is generally
irrelevant.

## 4. Fixed-population effect recomputation

The actual-order N/E/C results were passed through the unchanged Protocol v4
main evaluator using the frozen 20 Groups, frozen Headroom population, and
registered Group weights. No Group, cell, threshold, or population was
reselected.

| Estimand | Original report | Actual-order recomputation |
| --- | ---: | ---: |
| A1 − A0 | 0.0 | 0.0 |
| A2 − A0 | 0.0 | 0.0 |
| A3 − A0 | 0.0 | 0.0 |
| E0 − A0 | 0.0 | 0.0 |
| N0 − A0 | 1918.2222222222222 | 1918.2222222222222 |
| H3-0, A0 − N0 | -3123.2 | -3123.2 |
| H3-R, A0 − N0 | -6435.555555555556 | -6435.555555555556 |

The serialized registered effect subsets are exactly equal. The paired primary
population remains 18 Groups; H3-0 remains 20 Groups / 38 cells and H3-R
remains 9 Groups / 16 cells.

## 5. Conclusion and limitation

The campaign did not conform to the frozen Native enqueue order in 32 cells,
and that process deviation remains recorded. However, all six arms shared the
same actual order within every cell, the actual-order E reconstruction was
determinate for all requests, cross-arm E remained identical, and the fixed
effect estimates were unchanged.

Accordingly, the archive supports a bounded paired-effect interpretation under
the observed common replay deviation. It must not be described as having
passed frozen replay execution conformance, and final confirmatory status
remains an M1/M4 adjudication decision.

## 6. Evidence and reproduction

The generated evidence is in
[`phase3-actual-order-audit-data`](phase3-actual-order-audit-data/).

| Artifact | SHA-256 |
| --- | --- |
| `summary.json` | `ecbb570910621189f4cc218ae724758dc7f84cd7f60016f310c4d27d3b561deb` |
| `sha256-manifest.txt` | `d3feebd5c8d60097176ffdf8da73a96b6fad00c250e9be06d717124ef64739fc` |

Reproduction:

```bash
PYTHONPATH=. .venv/bin/python \
  -m scripts.spikes.audit_phase3_actual_order \
  --execution-archive artifacts/phase3-option-f-unified-270-runs-v2-evidence.tar.gz \
  --cohort-seal artifacts/phase3-cohort-seal-v1/cohort-seal.json \
  --classification docs/experiments/phase3-option-f-g0-v3/g0/calibration-classification.json \
  --output-directory phase3-actual-order-audit-data
```

The output directory must not already exist.
