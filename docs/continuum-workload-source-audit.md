# Continuum Workload Source Audit (W0)

Status: `CONDITIONAL_GO`  
Scope: source audit and conversion feasibility only; no Native campaign or policy evaluation.

## P0 inventory

| Field | Finding |
|---|---|
| Paper | *Continuum: Efficiently Serving Agentic Workflows with Elastic KV Cache Management* (`arXiv:2511.02230`) |
| Author repository | `Hanchenli/vllm-continuum`, audited at commit `316a58794a6ff86b216e579b74fd56ed0c5a911f` |
| Repository license | Apache-2.0 |
| Workload dataset | `princeton-nlp/SWE-bench_Verified`, `default/test`, 500 rows |
| Dataset task | Human-validated GitHub issue resolution; issue text and repository base commit are published |
| Agent runner | Bundled Mini-SWE-Agent `mini-extra swebench` path |
| Agent configuration | `swebench.yaml`: cumulative chat messages, shell action/observation loop, step limit 50 |
| Model in repository example | `meta-llama/Llama-3.1-70B-Instruct`, 4 GPUs; this is an example/default, not a binding recovered from raw paper traces |
| Load modes | Fixed worker concurrency (`--workers`) or Poisson arrivals (`--use-jps --jps`) |
| Public per-task inputs | Dataset rows: AVAILABLE |
| Public full agent trajectories from paper run | NOT AVAILABLE in the audited repository |
| Public submitted token IDs | NOT AVAILABLE |
| Public per-request timestamps/tool gaps | NOT AVAILABLE in saved `mini-swe-agent-1` schema |
| Public aggregate outputs | AVAILABLE (`continuum_exp/.../results.json` and verification summaries) |
| Runtime replay fidelity | CONDITIONAL: exact message growth is convertible when trajectory files exist; paper timing/token identity cannot be reconstructed from aggregate files |

## Source-path findings

The author path loads `princeton-nlp/SWE-bench_Verified` through Hugging Face
`datasets`, creates one Mini-SWE-Agent job per `instance_id`, and saves a
`mini-swe-agent-1` trajectory containing `info` and cumulative `messages`.
Each model call receives the full message list accumulated so far. Assistant
shell actions are followed by user-role observation messages, which means real
context growth and tool results can be preserved by converting each assistant
turn's preceding message list into one Phase 2 request.

The repository does not publish those per-instance paper trajectories. Its
saved trajectory schema also does not require request timestamps or submitted
token IDs. The Poisson arrival implementation samples interarrival time in the
runner, but those planned arrival values are not written into each trajectory.
Consequently, aggregate result files cannot recover the original request text,
token identity, arrival process, or tool gaps.

The README describes the repository as a preview implementation "without the
estimation in the paper". Results produced from this public path therefore
must not be presented as a byte-for-byte recreation of the paper setup.

## Frozen W0 sample

`configs/phase2/continuum-swebench-w0-sample-v1.json` freezes ten rows before
trajectory acquisition. Selection is the first ten records in the published
`default/test` order; no random sampling is involved, so the seed is explicitly
`null`. The sample is a source-migration fixture, not an experimental sample.

At W0 close, the task metadata is publicly accessible, while the corresponding
paper trajectories are `NOT_MATERIALIZED`. This is deliberately fail-closed:
the manifest does not substitute fabricated conversations for missing runs.

## Data rights and provenance boundary

- The audited Continuum code declares Apache-2.0.
- SWE-bench code declares MIT; individual benchmark records point to upstream
  repositories and retain their source identities.
- Mini-SWE-Agent declares MIT.
- This repository stores only the fixed identifiers and source references in
  the W0 manifest, not gold patches or copied repository contents.

Before distributing acquired trajectories, the operator must preserve dataset,
agent, model, repository revision, tokenizer revision, and execution provenance.

## W0 decision

`CONDITIONAL_GO` for a bounded migration pilot after authentic trajectories are
materialized with additional request timing and token-ID capture. The available
sources are sufficient to implement and test a converter, but insufficient to
claim faithful replay of the original paper workload.

P1 BFCL and P2 OpenHands remain deferred. W0 does not authorize Native A0/A1/A2
comparisons, a formal campaign, or claims about cache benefit.
