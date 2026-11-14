# Phase 4 Task 1: Session Continuation feasibility

CPU-only, read-only Archive analysis. No GPU, Native smoke, production algorithm
change, Protocol v5, or Partial Release.

```bash
python scripts/probes/phase4_session_continuation/study.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --seal     local/cohort-seal.json \
    --out      docs/experiments/phase4-session-continuation-data
```

## Headline finding

The archive **cannot independently identify Session Continuation**:

- the event stream has no `session_id`; session bindings exist only in the
  cohort seal and are recovered from `request_id`;
- every session's `instance_id` is also the request `program_id`;
- no program has more than one session;
- there is no explicit session switch/start/end event.

Session Continuation and Program Continuation are therefore observationally
identical in this archive. The report gives a **program-level proxy** only and
does not claim a Session Continuation result.

## Outputs

- `phase4-session-continuation-report.md`: data audit, target contract, window
  probabilities, group-isolated baselines, Expected Loss proxy, data gaps.
- `phase4-session-continuation-evidence.json`: machine-readable evidence.
- `sha256-manifest.txt`: script/test/README/evidence/report hashes.

Tests: `tests/test_phase4_session_continuation.py`.
