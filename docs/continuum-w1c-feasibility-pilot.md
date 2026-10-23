# Phase 2 W1-C Cross-Repository S50/S100 Feasibility Pilot

## Scope

W1-C is a workload-feasibility study, not a Native cache-policy comparison. It
freezes a 100-task cross-repository sampling design and executes only a paired
20-task pilot under two independently executed step budgets: S50 and S100.

The pilot does not authorize the remaining 80 tasks, an A0/A1/A2 campaign, or
any claim about Continuum paper-workload reproduction.

## Frozen provenance

- Dataset: `princeton-nlp/SWE-bench_Verified`, test split.
- Dataset revision: `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`.
- Sampling seed: `20261023`.
- Author checkout: `316a58794a6ff86b216e579b74fd56ed0c5a911f`.
- Agent: Mini-SWE-Agent 1.14.4, author SWE-bench configuration.
- Model and tokenizer: `Qwen/Qwen2.5-Coder-3B-Instruct` at revision
  `2ffd030b308f6bdd29ee43e7383f30ce8ac2e225`.
- Runtime: local Apple GPU through vLLM-Metal, one Agent worker, Docker-based
  SWE-bench environments.
- Model context limit: 32,768 tokens; maximum completion: 512 tokens.
- Execution code: `c78fb70cd52c3202b4170cd1f4e9f8cad9c27eff`.
- Authorization SHA-256:
  `0ddb1aa716aa12e35ae135ef9ff4c2e9c7bdd5dcc634ce1fe994f0c5c98ded6b`.

The 100-task design covers all 12 repositories present in the frozen
candidate snapshot. The 20-task pilot also covers all 12 repositories. The
historical W1-A Astropy task identities were excluded rather than relabeled as
new observations.

## Execution completeness

All 40 planned executions produced preserved run manifests:

| Condition | Runs | Successful model calls | Failed model calls | Tool calls |
|---|---:|---:|---:|---:|
| S50 | 20 | 1,000 | 0 | 464 |
| S100 | 20 | 1,800 | 3 | 943 |

There are 20/20 paired task records, with no missing or extra task-condition
keys. S50 and S100 are separate executions of the same frozen task IDs; S50 is
not reconstructed by truncating an S100 trajectory.

## Lifecycle outcomes

| Condition | Natural completion | Step-limit right censoring | Context-limit failure |
|---|---:|---:|---:|
| S50 | 0 | 20 | 0 |
| S100 | 1 | 16 | 3 |

The single natural completion was `psf__requests-2931` under S100. The three
context-limit observations were:

- `astropy__astropy-8872`, after 32 successful model calls;
- `django__django-13569`, after 86 successful model calls;
- `sympy__sympy-21596`, after 74 successful model calls.

In each case, the acquisition sidecar preserves one final failed submission
whose error states that prompt plus requested completion exceeded the frozen
32K limit. These observations are not reclassified as ordinary step-limit
censoring.

Across paired tasks, S100 minus S50 model-call count had mean `40.15`, median
`50`, and range `[-42, 50]`. Eighteen tasks had more model calls under S100;
two had fewer because they naturally completed or hit the context boundary.
Thus the longer budget usually produced additional interaction, but did not
substantially resolve natural-completion missingness.

## Context growth and prefix reuse potential

The captured token IDs are deterministic local tokenization of the exact
rendered prompt. They are not claimed to be Native runtime-submitted token
observations.

| Condition | Median prompt tokens | Maximum prompt tokens | Median per-task context growth | Median adjacent exact-token LCP | Median adjacent reuse ratio |
|---|---:|---:|---:|---:|---:|
| S50 | 5,836 | 19,726 | 9,131.5 | 5,773 | 0.9709 |
| S100 | 9,252 | 34,085 | 17,495.5 | 9,213 | 0.9829 |

The long exact-token common prefixes demonstrate strong replay potential
within an Agent session. They do not prove Native APC eligibility, KV
residency, cache hits, or physical reuse.

## Evidence validation

Thirty-seven trajectories passed the existing W1-A strict source-to-sidecar
validation with `CONDITIONAL_PASS`, including all 20 S50 runs and the 17 S100
runs without a failed final model submission. The remaining three S100 runs
are explicitly represented as valid context-limit observations: all successful
calls match their serialized trajectory, and the sidecar retains the final
failed call that cannot have a corresponding assistant response.

No failed, censored, or context-limited task was silently removed.

## Decision-opportunity boundary

Trajectory evidence supports analysis of prompt length, exact-token LCP,
context growth, model-call timing, tool-call timing, task lifetime, and
cross-repository heterogeneity. It does not observe:

- decision-time candidate count;
- marginal newly eligible blocks;
- the pressure requirement (`need`);
- candidate q values or their span;
- A1 divergence from Earliest Deadline or Minimum Overshoot;
- Native APC eligibility, residency, eviction, or recomputation.

All of these Native decision quantities remain
`NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY`. A future Native experiment would need
to freeze replay content, concurrency, cache capacity and pressure, then
capture complete decision snapshots without deriving cache state from the
trajectory.

## Recommendation

**CONDITIONAL_GO.**

The pilot passes the predeclared data-completeness gate for expanded workload
review: 20/20 pairs, 12 repositories, no infrastructure failures, and three
bounded context-limit outcomes. It demonstrates substantially longer Agent
lifecycle, real context growth, and strong within-session exact-prefix reuse.

It does not yet justify executing all 100 tasks or starting a formal policy
campaign. Before expansion, M1 should decide whether the next stage should:

1. retain the 32K limit and treat context exhaustion as part of the workload;
2. authorize a separately frozen larger-context acquisition condition; or
3. select a bounded Native replay subset using pre-execution workload criteria.

The low natural-completion rate and lack of Native decision state remain the
principal limitations. No A1/A2 effectiveness conclusion is made.
