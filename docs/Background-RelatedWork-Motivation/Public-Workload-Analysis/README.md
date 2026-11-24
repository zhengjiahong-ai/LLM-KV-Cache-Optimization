# Public Workload Evidence

Nebius OpenHands is an independent public workload for studying multi-turn software-engineering requests, prefix geometry, and the consequences of hypothetical evictions. Findings describe this archive and the stated CPU replay. The active formal SWE cohort and independent BFCL Derived supplement have their own evidence and authorization. [Research status](../../research-status.md)

| Question | Research record |
| --- | --- |
| Which Continuum assumptions can the archive test? | [Paper Mechanism Evidence Mapping](Paper-Mechanism-Evidence-Mapping.md) |
| How much recomputation can an eviction change under a shared initial state? | [Cost Geometry and Offline Oracle](Public-Workload-Cost-Geometry-and-Oracle.md) |
| How does that evidence change the interpretation of A1, A2, A3 and DVA-ER? | [Algorithm Evolution Analysis](Cost-Aware-Algorithm-Evolution-Analysis.md) |
| Can DVA-ER be evaluated against attributable Native downstream loss? | [DVA-ER Predictive Validity Gate](DVA-ER-Predictive-Validity-Analysis.md) |
| What does the complete public archive contain? | [Initial full-workload analysis, PR #135](Nebius-OpenHands-Trajectories.md) |

## Research assets

- **Data and projections.** Fixed Nebius Parquet, Qwen3-Coder and target Qwen2.5-Coder tokenizer revisions, source links, SHA-256 and run configuration are in the [manifest](evidence-results/manifest.json). The initial analysis comes from [PR #135](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/135), head `f369425639349fe11f8d7837266df4a45331c31a`. The historical reference for this study started from main `73effa9df7d330e51ec2dd95cab94f5b21be1339`.
- **Implementation.** The [CPU analysis entry point](../../../scripts/analyze_public_workload_evidence.py) and [offline loss core](../../../src/kvopt/profiling/public_workload_oracle.py) are isolated from the serving policy. [Tests](../../../tests/test_public_workload_oracle.py) exercise identity, refill, hindsight and missingness.
- **Algorithms and prior decisions.** The [architecture](../../architecture.md), [baseline freeze](../../baseline-freeze.md), [Phase 1B report](../../experiments/phase1b-continuum/final-report.md), [Cost-Aware joint design](../../phase2-cost-aware-joint-design.md), and [DVA-ER implementation](../../experiments/dva-er-v1-implementation.md) describe deployment boundaries. The [evidence ledger](../../research-consolidation/r1-experiment-evidence-ledger.md) and [M4-reviewed synthesis](../../research-consolidation/research-results-and-contributions.md) index the historical verdicts.
- **Derived data.** [Full census and memoryfulness](evidence-results/memoryfulness.json), [prefix geometry](evidence-results/geometry.json), [scenario summary](evidence-results/oracle_summary.csv), [sample composition](evidence-results/issue_clusters.csv), and [regret plot](evidence-results/oracle_regret.png). The manifest identifies every derived artifact. Raw data and tokenizer files are local inputs.

For Phase 5 D, the study supplies candidate geometries for future validation of identity, eligibility, victim attribution and follow-up. Phase 5 E continues to use its frozen or separately accepted experimental assets.
