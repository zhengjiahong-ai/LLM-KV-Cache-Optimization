# Phase 5 Trace Acquisition Runbook

**Status:** acquisition and mechanical qualification authorized; GPU Native
Conformance, Calibration, and Formal Campaign remain unauthorized.

## Evidence boundary

The acquisition pipeline preserves each source record byte-for-byte before it
produces normalized traces, prompt Token IDs, frozen tool fixtures, Q1--Q9
reports, and a SHA-256 manifest. It does not choose the formal cohort. A public
benchmark task row is not treated as an Agent trace, and a historical W1-C run
must retain its historical provenance.

Two raw acquisition schemas are accepted:

- `phase5.mini_swe_acquisition_bundle.v1` for an observed mini-SWE-agent
  Session;
- `phase5.bfcl_web_search_acquisition.v1` for an observed BFCL Web Search
  Session whose complete search responses are embedded in tool-call results.

Both schemas require an immutable source revision. The placeholder
`PINNED_BY_M1` fails closed. BFCL bulk acquisition therefore cannot begin until
the actual Gorilla/BFCL data revision is written into every acquisition record.

## SWE-bench acquisition environment

Reuse `continuum_w1a_runner` and the existing mini-SWE-agent observation
wrappers. The dataset revision remains:

`c104f840cc67f8b6eec6f759ebc8b2693d585d4a`

Use a Phase 5 output root distinct from Phase 3. Do not overwrite historical
W1-C or Phase 3 attempts. A bounded validation run is followed by batch
collection only after the run directory contains `run.json`, the trajectory,
and `acquisition-sidecar.json` with matching hashes.

## BFCL Web Search acquisition environment

Each of the 100 snippet and 100 no-snippet cases keeps its official case ID and
source class. The acquisition wrapper must record cumulative messages, model
submit/completion timing, tool arguments, the complete returned search payload,
provider identity, and terminal state. The complete returned payload becomes
the frozen fixture. Formal replay reads that fixture and never performs live
search.

Before live collection, validate the frozen 200-case frame:

```bash
python -m kvopt.workload.phase5_bfcl_acquisition \
  --sampling-frame /absolute/path/to/bfcl-web-search-frame.json \
  --source-revision <immutable-bfcl-revision> \
  --output artifacts/phase5-bfcl-frame-validation.json
```

The validator consumes the full M4 sampling-frame object, verifies its own
`frame_sha256`, and requires exactly 100 `SNIPPET` and 100 `NO_SNIPPET` cases,
unique case IDs, contiguous indices, and an immutable content SHA-256 for every
case. An unresolved or mismatched revision fails closed. Every observed search
must preserve the complete response bytes, response hash, query arguments,
provider identity, timestamps, source URLs, HTTP status, and errors; a failed
search is not replaced by a synthetic result.

Search-result redistribution terms are separate from the BFCL repository
license. Until M4 accepts the source and fixture license record, Q8 remains
false even when Q1--Q7 pass.

## Mechanical processing

Convert each completed mini-SWE-agent run directory before collection
processing. `--acquisition-origin` is mandatory so historical W1-C evidence is
not represented as a new Phase 5 acquisition:

```bash
python -m kvopt.workload.phase5_swe_acquisition_adapter \
  --run-directory /absolute/path/to/one-run \
  --chat-template-sha256 <64-lowercase-hex> \
  --license-expression '<audited-expression>' \
  --acquisition-origin PHASE5_NEW_ACQUISITION \
  --output /absolute/path/to/staging/one-session.json
```

The adapter verifies the run, trajectory and sidecar hashes, request sequence,
assistant response hashes, tool-result hashes and original source identity. A
trailing failed model attempt, such as a context-limit rejection with no
assistant response, remains a limitation and cannot be synthesized into a
Turn.

After acquisition records have been written to a staging directory:

```bash
python -m kvopt.workload.phase5_acquisition \
  --input /absolute/path/to/session-1.json \
  --input /absolute/path/to/session-2.json \
  --output-root /absolute/path/to/phase5-acquisition-processed-v1 \
  --license-accepted \
  --outcome-blind
```

Use `--license-accepted` only after the source-specific license audit has
actually passed. Use `--outcome-blind` only when task inclusion was fixed
without observing policy outcomes. Omitting either flag records a Q8 or Q9
exclusion; the pipeline does not infer those decisions.

The output contains:

- immutable raw records;
- normalized traces;
- full Token ID arrays and their hashes;
- tool fixtures and hashes;
- per-Session Q1--Q9 reports;
- collection statistics and a SHA-256 manifest.

An accepted Session must have 4--16 Turns. Failures, truncation, and explicit
right-censoring remain visible and are never padded with synthetic Turns.
