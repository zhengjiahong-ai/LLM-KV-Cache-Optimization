# Stage 0 oracle + P2 offline study

Read-only, CPU-only Stage 0 for the authorized post-PR #105 work.

```bash
python scripts/probes/phase3_stage0_oracle/stage0_oracle.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      docs/experiments/phase3-stage0-oracle-data
```

The archive does not expose a resettable Native cache state, so the study is an
**A0-anchored prefix-state counterfactual**, not a Native replay. It keeps every
observed `N`, `E`, and A0 `C`, removes the chosen candidate's deepest `need`
blocks from future requests, restores A0-evicted blocks when the candidate is
not A0, and re-scores all 24 requests. The A0 path is exact by construction; the
per-decision predicted-victim set is a subset of the physical eviction set for
127/127 decisions and 7/7 competitive decisions.

The result is an **avoidable-loss upper bound**. It deliberately does not model
capacity gains from evicting a different chain, so a zero result stops this loss
channel but does not prove that every Entry policy is useless. No GPU, Native
smoke, Protocol v4 change, production algorithm change, or P3 implementation is
authorized or performed.

Outputs are `stage0-evidence.json`, `stage0-report.md`, and
`sha256-manifest.txt`; the test is `tests/test_phase3_stage0_oracle.py`.
