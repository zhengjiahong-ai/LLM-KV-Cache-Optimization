# P2 candidate-chain-conditioned online study

CPU-only, read-only offline study authorized after Stage 0. No GPU, Native
smoke, Protocol v5, or Partial Release implementation.

```bash
python scripts/probes/phase3_p2_depth/p2_study.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      docs/experiments/phase3-p2-depth-data
```

## Predictors

- **P2-A** original control: pairwise same-program history max LCP.
- **P2-B** candidate-chain-conditioned max LCP against other prior same-program chains.
- **P2-C** candidate-chain-conditioned recency-weighted mean of those LCPs.

All predictors use only information available before the decision. The source
chain that produced the candidate is excluded from P2-B/C history; otherwise the
self-LCP would collapse the score to `need`.

## Contracts

- **Victim suffix:** a candidate is evaluated only when its actual victim hashes
  are provably a contiguous suffix of a prior same-program request chain. If no
  such chain exists, the candidate/scenario is `EXCLUDED`; the depth is never
  defaulted from `chain_length - need + 1`.
- **Label:** `future_prefix_demand_overlap` is the deepest later request-prefix
  overlap. It is not a Native-cache-verified hit.
- **Gain:** each scenario changes exactly one decision, keeping the rest at A0.
  Sums are independent single-decision counterfactual increments, not a joint
  P2 policy effect.
- **Scenarios:** `REAL` and `CONSTRUCTED_HISTORICAL` are always reported
  separately; constructed scenarios are artificial pairings.

Full-trajectory gains use the Stage 0 A0-Anchored Prefix-State Loss Oracle, not a
Native State Oracle; Native capacity gains remain unassessed.

Outputs: `p2-depth-evidence.json`, `p2-depth-report.md`, `sha256-manifest.txt`.
Tests: `tests/test_phase3_p2_depth.py`.
