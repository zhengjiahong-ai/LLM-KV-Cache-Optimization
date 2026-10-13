# Phase 2C M6 Workload Reuse Audit — Review Submission

## Requested review

M6 requests M1 review of the historical H1 workload/APC audit and the proposed
versioned content-topology schema. The candidate audit outcome is
`AUDIT_ACCEPT`. This submission does not request a formal campaign and does not
claim native validation of the proposed topology schema.

## Scope and provenance

- Run kind: `NON_HOLDOUT_WORKLOAD_AUDIT`.
- Historical source: sealed H1 Level-A evidence archive.
- Source SHA-256:
  `af5be5bd56a172f7945f12712289708aa55cda01f1b8c05a2bc3215b14c90af7`.
- Audited clean Git revision:
  `d1b20af29d1307f84df13a319a2cb61363b76a9d`.
- Full developer regression: 1,089 passed, 0 failed.
- H1/H2 sealed artifacts modified: no.
- Native runtime, BlockPool, hash, refcount, LRU, or policy modified: no.
- New experiment outcomes produced: no.

## Deliverables

| Deliverable | SHA-256 |
|---|---|
| `docs/phase2c-m6-workload-reuse-audit.json` | `74fbfca647b12645af0d91debc9ed342ec2773d051f84e132aabd73925de1b99` |
| `docs/phase2c-m6-workload-reuse-audit.md` | `bb792a637d35d2413b022adaf2f57141d3af289ce0d518fec2b0741a6f1e13f5` |
| `configs/phase2/phase2c-workload-content-schema-v1.json` | `8aba497bc498be7d210d432569bf5ae121d831fdad2a4789f98c72afff7553e4` |
| `src/kvopt/profiling/phase2c_workload_audit.py` | `cfc3697e6ddeafdf73648b85e266626ec34ee04c8ce314c0cfa8f0110643f919` |
| `docs/phase2c-m6-workload-reuse-regression.json` | `768a5efb959b074ec1723af4dac2a14858375394ecaafad0bd3c4e7456d9fbd5` |

## Audit result

The audit reproduced all frozen historical counts and identity checks. It found
that H1 materialized reusable content from `program_id`, not from logical
ownership or prefix-prompt identity. Within a program the full native hash chain
was fixed across turns, while different programs had distinct first chains.
Runtime seeds changed neither the APC outcome nor cached-token count for any of
the 165 complete three-seed groups.

The report separates content overlap potential, lifecycle reuse eligibility,
physical cache residency, and realized APC outcome. First requests without an
eligible predecessor are not classified as misses. Missing historical token IDs
and eviction-time logical ownership remain explicitly `NOT_OBSERVABLE`.

## Gate status

| Gate | Status |
|---|---|
| `G-HISTORICAL-REPRO` | `PASS` |
| `G-INPUT-IDENTITY` | `PASS` |
| `G-APC-CONDITIONAL` | `PASS` |
| `G-SEED-INDEPENDENCE` | `PASS` |
| `G-CAUSE-ACCOUNTING` | `PASS` |
| `G-DATA-PROPOSAL` | `PASS` |
| `G-NATIVE-PILOT` | `NOT_AUTHORIZED` |
| `G-H1H2-SEALED` | `PASS` |
| `G-LEGACY` | `PASS` |
| `G-PROVENANCE` | `PASS` |

## Design submitted for confirmation

The v1 schema defines block-aligned `shared_root`, `branch`, and cumulative
`turn_extension` segments and covers `W-COLD`, `W-EXACT`, `W-XPROGRAM`,
`W-ROOT-FORK`, `W-NESTED`, `W-TURN-GROW`, `W-HOT-COLD`, and `W-PRESSURE`.
Content topology is sampled independently from timing, pressure, capacity, and
concurrency. Target hit-rate tuning and silent fallback are prohibited.

M1 is asked to either accept the audit and confirm the design for a separately
authorized bounded non-holdout native pilot, or return specific design changes.
Until that decision, `native_pilot = null` and
`formal_campaign_authorized = false` remain binding.
