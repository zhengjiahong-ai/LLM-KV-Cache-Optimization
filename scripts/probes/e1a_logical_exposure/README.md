# E1-A logical exposure feasibility audit

CPU-only, read-only audit of the frozen Phase 3 archive. It does not run a GPU,
Native smoke, production algorithm, new data acquisition, or Protocol v5.

```bash
python scripts/probes/e1a_logical_exposure/audit.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --freeze  configs/phase4/e1a-logical-exposure-freeze-v1.json \
    --out     docs/experiments/e1a-logical-exposure-data
```

The primary model uses only the actual `FORCED_RELEASE_DECISION.candidates`
list. The sensitivity models require a complete protected-entry snapshot; if it
is absent they are reported as `NOT_EXECUTABLE`, not filled with inferred
candidates. W1-C aggregate reporting is present, but no W1-C raw per-request
traces are present in this workspace.

Outputs: `e1a-logical-exposure-evidence.json`,
`e1a-logical-exposure-report.md`, `sha256-manifest.txt`.
Tests: `tests/test_e1a_logical_exposure.py`.
