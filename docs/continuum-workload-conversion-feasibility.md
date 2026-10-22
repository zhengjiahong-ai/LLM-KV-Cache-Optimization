# Continuum Workload Conversion Feasibility

## Implemented conversion

`kvopt.workload.continuum_source_audit` accepts an authentic
`mini-swe-agent-1` trajectory and emits:

- `trace.json`: a validated `phase2.trace.v1` input;
- `conversion-report.json`: source/request hashes and field-level provenance;
- `validation-report.json`: exact prompt-growth and evidence-completeness gates.

Each assistant turn becomes one Phase 2 request. Its input is the canonical JSON
serialization of all prior messages, preserving the system prompt, task prompt,
assistant shell commands, tool observations, order, and logical cumulative
context. This serialization is diagnostic and is not claimed to be the actual
chat-template-rendered model input. `prefix_prompt` remains empty until a real
rendered prompt or submitted token sequence proves literal prefix reuse.

## Fidelity rules

| Property | Rule |
|---|---|
| Program/session identity | Preserve SWE-bench `instance_id` |
| Turn order | Preserve assistant-message order |
| Prompt and tool output | Preserve canonical complete preceding message list |
| Logical context growth | Recompute each turn from the exact preceding message list |
| Literal prompt prefix | Leave empty/unknown without rendered prompt or token-prefix evidence |
| Token IDs | Preserve only explicit `input_token_ids`; otherwise `NOT_OBSERVABLE_IN_PUBLIC_TRAJECTORY` |
| Message timing | Preserve explicit values as diagnostic metadata only |
| Arrival/tool timing | Use labelled ordinal/zero placeholders; never claim request/tool timing fidelity |
| Deterministic replay | Canonical JSON plus SHA-256 for source trajectory and each request prompt |
| Pressure stages | None inferred; workload conversion must not invent cache pressure |

The validator independently recomputes the trace, trajectory hash, request
hashes, identities, token observations, and provenance flags from the supplied
trajectory. W0 output is capped at `CONDITIONAL_PASS`; source/report tampering,
prompt drift, nonfinite timestamps, and timestamp reordering produce `FAIL` or
are rejected.

## Framework compatibility

The converted trace satisfies the existing Phase 2 request lifecycle model:
contiguous turns, diagnostic monotonically ordered ordinal arrivals, and one
terminal final turn. It can enter structural materialization and validation,
but it does not yet provide a verified APC-reusable prefix.

The following gaps remain and are not silently repaired:

1. Mini-SWE-Agent's public save schema lacks request timestamps and token IDs.
2. The author repository does not contain the original per-instance trajectories.
3. Dataset issue metadata alone is not a multi-turn agent trajectory.
4. Ordinal arrival offsets are suitable only for conversion tests, not timing or
   concurrency claims.
5. Token identity depends on the exact chat template, tokenizer, model revision,
   and request serialization used during acquisition.
6. Phase 2 cannot infer physical APC behavior, cache residency, or eviction from
   logical message reuse.

## Minimal acquisition additions for a future pilot

Without changing the agent algorithm, the acquisition wrapper should record for
every model call: monotonic submit/admit/complete timestamps, exact submitted
messages or rendered prompt, tokenizer/model revisions, submitted token IDs,
job/turn/request IDs, and tool start/end times. The existing trajectory remains
the semantic source; the added record is an observation sidecar.

## Descriptive opportunity only

Authentic Mini-SWE-Agent runs naturally create cumulative prefixes because each
model call includes the previous conversation and tool observations. Multiple
tasks also share system and instruction templates. These facts make the source
appropriate for studying prefix reuse after a real acquisition run. They do not
show that native sharing, physical eviction, recomputation benefit, or a policy
advantage occurs.

## Decision

`CONDITIONAL_GO`:

- GO for acquiring the frozen ten tasks and validating the conversion path.
- GO for offline descriptive prompt/LCP/context-growth statistics after capture.
- NO GO for timing-sensitive replay until timestamp sidecars exist.
- NO GO for token-identity claims until exact token IDs and revisions exist.
- NO GO for a formal Native campaign until a separate review freezes the
  materialized trajectories, runtime config, evaluator, and evidence contract.

Example conversion command:

```bash
python -m kvopt.workload.continuum_source_audit \
  --trajectory path/to/instance.traj.json \
  --output-root artifacts/continuum-w0-conversion/instance-id
```
