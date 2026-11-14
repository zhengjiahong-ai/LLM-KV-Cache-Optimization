# P2 online future-reuse-depth study

CPU-only, read-only offline study authorized after Stage 0. No GPU, Native
smoke, Protocol v5, or Partial Release implementation.

```bash
python scripts/probes/phase3_p2_depth/p2_study.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      docs/experiments/phase3-p2-depth-data
```

Scenarios are split into `REAL` (the 7 observed two-candidate decisions) and
`CONSTRUCTED_HISTORICAL` (single-candidate decisions paired with the most recent
other-program chain in the same cell; these are artificial counterfactuals, not
observed candidate competitions).

P2 is an **online** predictor: it may use only prior request history and the
candidate's current geometry. The future reuse depth and the one-decision
hindsight oracle are offline labels. Full-trajectory gains use the Stage 0
A0-Anchored Prefix-State Loss Oracle, not a Native State Oracle; capacity gains
remain unassessed.

Outputs: `p2-depth-evidence.json`, `p2-depth-report.md`, `sha256-manifest.txt`.
Tests: `tests/test_phase3_p2_depth.py`.
