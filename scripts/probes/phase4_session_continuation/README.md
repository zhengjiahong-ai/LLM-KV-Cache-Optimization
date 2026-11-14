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

## Right-censoring

Each request's observable remaining time is measured from its session's
`W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED` timestamp. A request with less than W
seconds remaining is `CENSORED` for that window and is excluded from the binary
Brier/AUC/accuracy metrics; it is not counted as a negative. Only a request with
at least W seconds remaining and no later same-session request inside W is a
negative.

Censored share by window: 5s 4.8%, 15s 8.1%, 60s 12.1%, 300s 54.2%.

The Expected Loss section is a preliminary program-level diagnostic only; it
does not establish a validated continuation-prediction plus cost-model
combination.

## Outputs

- `phase4-session-continuation-report.md`: data audit, target contract, window
  probabilities, group-isolated baselines, Expected Loss proxy, data gaps.
- `phase4-session-continuation-evidence.json`: machine-readable evidence.
- `sha256-manifest.txt`: script/test/README/evidence/report hashes.

Tests: `tests/test_phase4_session_continuation.py`.
