# Phase 2H History-Rich Native Replay Smoke — Measured Campaign Report

## Scope and claim boundary

This report covers the six Native runs authorized after the PR #86 target-CUDA
preflight. The statistical units are the two frozen workload scenarios, each
with one runtime observation per arm. Results are descriptive mechanism
evidence; they do not establish population-level performance or statistical
significance.

The preflight runs are excluded from all measured outcomes below.

## Frozen execution

- Scenarios: `hr01-balanced-gap`, `hr02-short-gap-long-context`
- Arms: A0, A1, and A2
- Requests: 180 exact-token Agent requests per run, 60 per session
- Pressure barriers: after rounds 40, 50, and 55
- KV capacity: 2,048 blocks of 16 tokens
- Model and tokenizer: `Qwen/Qwen2.5-Coder-1.5B-Instruct`
- Model/tokenizer revision: `d18ecad881a290f0c792f1c2b5dbee1820d4a424`
- Runtime: vLLM 0.27.1, PyTorch 2.13.0+cu130, CUDA 13.0
- GPU: NVIDIA GeForce RTX 4090 D, 24,564 MiB
- Reviewed and executed Git SHA: `2d0174dccd09ace52003f311077d18b9b92c285b`

The formal authorization record binds the input manifest SHA-256
`661b04b89b1b73669ae8758a196326cefda3ae20a532e4fdf020ad162ae11810`,
the accepted preflight archive, the reviewed Git SHA, and the orchestration
script. No workload, pressure, policy, or timing input was changed between
arms.

## Execution completeness and resource controls

All six planned runs completed successfully. Every run submitted and completed
180 Native Agent requests, reached all three pressure barriers, and recorded
zero replay-idle wall time. Gate H passed in all six runs. Gate D independently
reconstructed all three executed A1 decisions in each A1 run; A0/A2 correctly
remain `NOT_APPLICABLE_SHADOW_ONLY` for A1 scoring.

| Run | Wall seconds | Gate H | Gate D | Empirical TTL decisions | Multi-candidate decisions |
|---|---:|---|---|---:|---:|
| HR01/A0 | 63.696 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 76 | 3 |
| HR01/A1 | 65.065 | PASS | PASS | 76 | 3 |
| HR01/A2 | 99.596 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 76 | 3 |
| HR02/A0 | 76.804 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 75 | 3 |
| HR02/A1 | 80.645 | PASS | PASS | 75 | 3 |
| HR02/A2 | 124.738 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 75 | 3 |

The sum of per-run wall time is 510.545 seconds. Recorded components include
155.672 seconds of engine initialization, 339.461 seconds of Native execution,
54.662 seconds of pressure execution, and 12.661 seconds of evidence writing.
Component timers can overlap and must not be summed to reconstruct wall time.
No per-run or total stop control was approached.

There are no failed or missing formal runs. The only intentional evidence
limits are the frozen right-censoring boundary and the Native callback's lack
of complete logical-owner attribution.

## Gate H: history and TTL mechanism

Gate H passes for every arm and scenario. Each run records and independently
recomputes 177 TTL decisions with zero invalid or missing decisions. The
maximum observed global Server Gap history is 176 samples.

- HR01: 101 cold-start decisions and 76 tool-specific empirical decisions.
- HR02: 102 cold-start decisions and 75 tool-specific empirical decisions.

The result establishes that the history-rich replay crosses the empirical
history threshold and that the persisted history reproduces the executed TTL,
mode, and deadline. It does not imply that empirical history necessarily gives
q independent predictive value.

## Gate D and A1 Entry selection

Both A1 runs expose three legal multi-candidate decisions. All six decisions
are independently reproduced from the archived Free Queue, candidate
ownership, need, q, N, lambda, deadline, and tie-break evidence.

The six within-decision q spans are positive and range from approximately
0.0607 to 0.4771. History recovery therefore produces non-degenerate q values.
Nevertheless:

- A1 matches A0 in five of six Entry decisions.
- A1 matches Earliest Deadline in five of six decisions.
- A1 matches Sufficient-first plus Minimum Overshoot in all six decisions.
- The only A1/A0 divergence occurs at HR02's round-55 pressure boundary.

At that boundary A0 selects `pytest-dev__pytest-7982`, while A1 selects
`pylint-dev__pylint-6386`. The A1 decision has actual remaining need 17 blocks.
The two candidates have:

| Candidate | q | N | Deadline | Frozen score proxy |
|---|---:|---:|---:|---:|
| pylint | 0.463529 | 460 | 259.468813 | 110.551584 |
| pytest | 0.402859 | 640 | 252.046163 | 132.339183 |

A1's choice is not reproducible by Earliest Deadline, but it is reproducible by
Minimum Overshoot because pylint has the smaller sufficient N. This experiment
therefore does not isolate q as the cause of an independently valuable choice.

## A2 block selection

Across the two A2 runs, 54 decisions use the incremental-greedy selector and
384 allocation decisions explicitly fall back to Native LRU because the
available evidence is content-unverified. Every one of the 54 effective
incremental-greedy selections equals the corresponding recorded Native LRU
victim sequence. No confirmed A2-vs-LRU victim divergence occurs.

At the pressure windows specifically, HR01 records six incremental-greedy and
two fallback allocation decisions; HR02 records eleven incremental-greedy and
one fallback allocation decision. None diverges from its within-run Native LRU
counterfactual. Native hashes are process-scoped, so raw hash identities are
not compared directly across separate arm processes.

## Primary outcome: recomputed prefix tokens

Recomputed tokens use the frozen request-level accounting: the exact reusable
prefix E comes from the preceding same-session Native prefix snapshot, C is the
observed Native cached prefix, and R = E - C.

| Scenario | A0 | A1 | A2 | A1 - A0 | A2 - A0 |
|---|---:|---:|---:|---:|---:|
| HR01 | 25,136 | 25,136 | 25,136 | 0 | 0 |
| HR02 | 92,512 | 98,832 | 92,512 | +6,320 | 0 |

HR01 has 3 requests with no eligible prior prefix, 171 Full Hits, and 6 Partial
Hits in every arm. HR02 has 3 requests with no eligible prior prefix, 156 Full
Hits, and 21 Partial Hits in every arm. Hit-category counts alone hide the A1
cost increase because the amount recomputed within one Partial Hit changes.

The entire HR02 A1 delta comes from
`pylint-dev__pylint-6386:turn:56`: A0 observes E/C/R =
12,784/7,472/5,312, whereas A1 observes 12,784/1,152/11,632. The resulting
6,320-token increase follows the round-55 A1 Entry divergence. With only two
scenarios and one repeat, this is a descriptive paired outcome, not evidence of
a general A1 regression rate.

A2 ties A0 in both scenarios. Because no effective A2 selection differs from
Native LRU, the tie does not demonstrate that a distinct cost-aware victim
choice is equally good; it shows that this campaign did not realize such a
choice.

## Pressure, eviction, downstream reuse, and attribution

All 18 pressure barriers expose multiple legal Entry candidates and one forced
release. Every selected program has a subsequent request inside the observation
window, and every immediate downstream request is a Partial Hit with positive
recomputation.

For 17 of 18 barriers, the selected full-prefix Native key is directly present
in the pressure-window eviction callbacks. At HR02/A1 round 55, selected pylint
block IDs are evicted and the subsequent request recomputes 11,632 tokens, but
the selected full-prefix key itself is not present in the callback set.

Accordingly, the campaign establishes a bounded stable-identity and temporal
association from logical release through physical eviction to downstream APC
and recomputation. It does not establish complete block-level content causality:
the Native callback does not attribute every victim to a logical owner, and a
different arm runs in a different process-local hash domain.

Each session's final request is right-censored by the frozen 60-call window.
Content not requested again before that boundary is retained as right-censored,
not classified as permanently unreused.

## Research conclusion

The formal Smoke answers the two mechanism gates separately:

1. **Gate H succeeds.** Continuous real Agent history enters empirical TTL
   mode and its decisions are exactly reproducible.
2. **Gate D succeeds as an opportunity gate.** All six A1 pressure decisions
   have multiple legal candidates, positive q spans, and reproducible scores.
3. **Independent A1 value is not established.** A1 is still fully reproducible
   by Minimum Overshoot, and its sole divergence from A0 increases recomputation
   by 6,320 tokens in HR02.
4. **Independent A2 value is not exercised.** Effective A2 victim choices never
   differ from Native LRU; the remaining decisions fail closed to LRU.

The result supports M1/M4 analysis of the scoring structure and marginal loss
model. It does not justify a claim that q is useless, that A1/A2 are generally
worse, or that any replacement algorithm is already validated. No A1+, r_i,
or per-candidate lambda implementation is authorized by this report.

## Evidence identity

- Evidence archive:
  `artifacts/phase2h-history-rich-native-smoke-v1-evidence.tar.gz`
- Archive SHA-256:
  `4f0527f6afa322be0423378a3fa01c6d5a4d4f421a55a218ced907a1c5968580`
- Archive validation: `PASS`
- Internal SHA-256 manifest:
  `80bde41d189bb920b3e2de9c421d48f10090240e460907b32a4e295c8946b5d0`
- Accepted preflight archive SHA-256:
  `66d706c37b12d7753a62ca61ef00496a18127a9386579f5795884d11474fa22f`

Final recommendation: `FORMAL_PHASE2H_SMOKE_COMPLETE / FORWARD_TO_M1_M4`.
