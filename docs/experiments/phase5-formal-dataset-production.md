# Phase 5 Formal Dataset Production

This document records the reproducible processing entry points for the frozen
Phase 5 acquisition frames. It does not select a Formal Cohort and does not
authorize GPU execution.

## Frozen identities

- Base main: `943d833ae30414bd91291c9a015bff71302b18a9`
- Formal Protocol SHA-256:
  `62cc5b10b71b1bdc8dc55edf04edeee4c4fadc8f84dfe85b59873ce589fa8063`
- Workload Qualification Contract SHA-256:
  `98f9d9f968690b7a63a1ff6e597ab9b3503204886bcf52b11646a3d3ad34240a`
- BFCL revision: `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`
- BFCL source SHA-256:
  `6fc41d96d003dc849028966a782923560d2fc127ed2088aa967f06daaafa4268`

## SWE-bench requalification

The current protocol is applied to the immutable 57-session processed input.
The command refuses to overwrite an existing output directory.

```bash
.venv/bin/python scripts/spikes/phase5_dataset/requalify_swe.py \
  --input artifacts/phase5-swe-acquisition-processed-v1 \
  --output artifacts/phase5-swe-acquisition-processed-v4 \
  --protocol configs/phase5/phase5-formal-protocol-v1.json \
  --qualification-contract \
    configs/phase5/phase5-workload-qualification-contract-v1.json \
  --terminal-adjudication \
    configs/phase5/phase5-swe-terminal-adjudication-v1.json
```

The resulting mechanical decision is 35 qualified Sessions and 22 excluded
Sessions. The qualified set contains 2 natural completions and 33 explicit
step-limit right-censored Sessions. No 16-Turn maximum is applied. This is a
qualification result only; M6 does not select the Formal Cohort.

## BFCL source and execution preflight

The official source checkout must be at the frozen revision. The preflight
independently validates the 100 source rows, the 200 ordered SNIPPET /
NO_SNIPPET identities, both protocol hashes, the real model endpoint, and the
presence (but never the value) of the SerpAPI credential.

```bash
.venv/bin/python scripts/spikes/phase5_dataset/preflight_bfcl.py \
  --bfcl-root data/phase5-bfcl-gorilla \
  --frame configs/phase5/phase5-bfcl-sampling-frame-v1.json \
  --protocol configs/phase5/phase5-formal-protocol-v1.json \
  --qualification-contract \
    configs/phase5/phase5-workload-qualification-contract-v1.json \
  --output artifacts/phase5-bfcl-acquisition-preflight-v1
```

At the time of this record, source validation passes, while acquisition remains
fail-closed because `SERPAPI_API_KEY` and a configured OpenAI-compatible model
endpoint serving the frozen model are absent. No synthetic model response or
search fixture is substituted. Live search is permitted only during
acquisition; every response must subsequently be frozen and hash-bound, and
Formal Replay must not access live search.

Secrets must be supplied through the execution environment and must not be
committed, printed, or stored in evidence artifacts.
