# Phase 2A M6 Curated Evidence

This directory contains the reviewable, text-only subset of the authoritative
M6 formal profiling artifacts. The complete raw artifacts remain external, as
required by the repository's established evidence-handling boundary.

## Contents

- `curated-evidence/campaign.json`: formal campaign manifest;
- `curated-evidence/formal-execution.json`: 54-run execution summary;
- `curated-evidence/derived/`: validity, capability, statistical, signal,
  gate, and Method Support Pack outputs from the final derived bundle;
- `curated-evidence/exemplars/`: authoritative source files for three
  representative high-regret runs;
- `curated-evidence/SHA256SUMS`: byte-integrity digests for the copied evidence.

The three exemplars retain only the four Phase 2 source-of-truth files:
`run.json`, `trace.json`, `replay.jsonl`, and `events.jsonl`. Launcher logs are
not curated into Git.

The files are byte-for-byte copies from:

- `artifacts/phase2a-formal-campaign-v4/`;
- `artifacts/phase2a-formal-v4-final/`;
- `artifacts/phase2a-formal-v4-derived-v3/`.

Verify the curated copies from this directory with:

```bash
cd curated-evidence
shasum -a 256 -c SHA256SUMS
```

The full external bundle is
`artifacts/phase2a-m6-formal-evidence-f40a3bb.tar.gz`, with SHA-256
`ea6fda72d6fb1cb09f357fcfbc30bac4122ff8baec8387dccf55a19ab507c114`.
Its transfer channel must be agreed separately with M1 or the project team.

The raw JSON retains local absolute paths and machine provenance so byte
integrity is not altered. A targeted credential-field scan found no API keys,
access tokens, authorization values, passwords, secrets, or HF tokens. Reviewers
should nevertheless treat local environment identifiers as disclosed metadata.
