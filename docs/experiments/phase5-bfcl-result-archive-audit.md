# Phase 5 BFCL-Result Archive Reuse Audit

## Scope

This read-only audit evaluates the two public BFCL-Result Agentic response
archives identified by M1. It does not select a formal cohort, modify the
frozen BFCL frame, authorize GPU execution, or copy archived third-party page
content into this repository.

The audited repository is `HuanzhiMao/BFCL-Result` at commit
`cadd76a8dc62984e7bf15ecaf358f070bae745cc`. The source response model is
`gpt-5.2-2025-12-11-FC`, not the Phase 5 execution model. Consequently, these
records can only be considered as workload/tool-interaction traces; their
token counts are not native Qwen token identities.

## Source identity

| Stratum | Git blob SHA-1 | Bytes | File SHA-256 |
|---|---|---:|---|
| SNIPPET | `c58f1cb0c19d5b6c8874dda45adaa2ae58570db4` | 5,095,293 | `62ab5b7751431809bbcd3ee9970065e5d8580f7d35a1b00f63ddf911d405416e` |
| NO_SNIPPET | `bd6bd4ae3b53442d86fd33776a1ded6b48f23de5` | 7,476,134 | `6f6574ad0b990266b9faf37c4c3ae371e80008a3c49a446fba0844c44a4eb3be` |

Both observed Git blob identities match the M1-provided values. The repository
`LICENSE` SHA-256 is
`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`;
the repository `README.md` SHA-256 is
`8326da8b8640214b9bbcaadb5300703904e26f86f0a0440d7230bfb2dfff61c5`.
Repository-level Apache-2.0 labeling is recorded but is not treated as
clearance for archived third-party webpage content.

## Frame and trace results

Both files contain 100 unique, ordered IDs with no duplicate, missing, or
unexpected IDs. All 200 IDs map one-to-one to the frozen 100 SNIPPET and 100
NO_SNIPPET cases.

The SNIPPET archive has 100/100 complete semantic traces and exact frozen
question/frame matches. It contains 162 page-fetch calls: 152 have non-empty
content and 10 contain explicit fetch errors.

The NO_SNIPPET archive has 99/100 complete semantic traces. Case
`web_search_no_snippet_51` contains an inference error instead of an inference
log after a tool output exceeded the source API's 10,485,760-byte limit. The
remaining 99 questions match the frozen source. The archive contains 253
page-fetch calls: 235 have non-empty content and 18 contain explicit fetch
errors.

Thus, frozen ID coverage is 200/200, while exact content-level trace coverage
is 199/200. The audit never substitutes another case or fabricates the missing
trace.

## Reuse decision

Direct deterministic replay is **NOT_READY** for all 200 cases. The public
records do not embed:

- absolute request timestamps;
- observed tool-gap timestamps;
- explicit terminal/censoring status;
- the exact tool definitions used at inference;
- the sampling configuration;
- native prompt token IDs.

The 199 semantic traces are structurally useful for a possible pinned
reconstruction and Qwen re-tokenization, but such derived tokens must not be
described as the source model's native token trace. Q4 timing preservation,
Q5 terminal provenance, exact request reconstruction, and Q8 third-party
content review remain unresolved. Case `web_search_no_snippet_51` is not
reconstructable from this archive.

No BFCL fixture, Token Materialization, or Q1-Q9 PASS is issued by this audit.
M4 must independently determine the internal-use boundary for the repository
records and embedded third-party webpage content. M1 must decide whether the
missing timing/terminal/input metadata permits a protocol-compliant derived
workload or requires a minimal gap-filling plan.

## Reproduction

Run:

```bash
.venv/bin/python scripts/spikes/phase5_dataset/audit_bfcl_result_archive.py \
  --result-repository data/phase5-bfcl-result-repo \
  --source data/phase5-bfcl-gorilla/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_web_search.json \
  --frame configs/phase5/phase5-bfcl-sampling-frame-v1.json \
  --output artifacts/phase5-bfcl-result-archive-audit-v2
```

The content-minimized report file SHA-256 is
`66edb570d5d19b170675ab30d7e6e1d7a216dd31128e72897d97de9c4e36fc84`.
Its internal canonical audit identity is
`22ebd27909ccde43490b988d7006194bbea71af768bc959fe612366c08318411`.
