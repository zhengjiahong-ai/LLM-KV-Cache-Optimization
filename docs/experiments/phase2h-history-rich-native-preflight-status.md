# Phase 2H History-Rich Native Replay — Preflight Status

## Scope

This record covers the execution infrastructure and CPU/static preflight
authorized after the PR #85 freeze. It is not a Native GPU Smoke result and it
does not authorize the six frozen GPU runs.

## Frozen execution inputs

- Scenarios: `hr01-balanced-gap`, `hr02-short-gap-long-context`
- Arms: A0, A1, A2; one run per arm and scenario
- Requests: 180 exact-token requests per scenario (60 per session)
- Pressure barriers: after rounds 40, 50, and 55
- KV capacity: 2,048 blocks of 16 tokens
- Fixed pressure: 12,256 tokens for HR01; 6,064 tokens for HR02
- Stop controls: 1,800 seconds per run; 14,400 seconds total GPU wall time

## Static preflight result

The static preflight generated from the frozen W1-C S100 sidecars reports
`PASS_STATIC_PREFLIGHT`.

- Both scenarios contain exactly 180 requests and 363 logical boundaries.
- Each scenario contains 117 observed within-session gaps before the first
  pressure boundary, meeting the frozen empirical-TTL history threshold.
- Every individual request fits within the 2,048-block capacity.
- The first fixed pressure input produces the preregistered nominal shortage:
  32 blocks for HR01 and 128 blocks for HR02, before accounting for earlier
  physical evictions.
- Later logical joint demand can exceed capacity by design. This is repeated
  capacity competition, not evidence that all three prefixes remain resident.
- Timeline and pressure token inputs are deterministic and share identical
  SHA-256 identities across A0/A1/A2.

Generated artifact:

`artifacts/phase2h-history-rich-native-preflight-v1/static-preflight.json`

SHA-256:

`51ef3df0130b6710ac82499cebf15e33d08f99e9ba2433656de6464e31547608`

## Implemented observation contract

- Every TTL input persists global/tool history sample counts, complete sample
  arrays, source provenance, threshold, ETA, queue delay, and reload estimate.
- Every TTL result persists mode, reason, consumed TTL, and derived deadline.
- A1 selection traces persist actual decision-time `need` together with every
  candidate's q, newly eligible blocks, deadline, and score inputs.
- The Gate H evaluator independently recomputes TTL and deadline from persisted
  inputs.
- Gate D treats A1 scoring as actual evidence only on A1. A0/A2 expose candidate
  opportunity but are explicitly labelled `SHADOW_DIAGNOSTIC_NOT_EXECUTED`.
- Fixed pressure token IDs are validated against stage size and model vocabulary;
  runtime policy outcomes cannot alter the pressure input.

## PR #86 correctness closure

- The exact `phase2h_history_rich_native_smoke` campaign kind is allowlisted for
  the frozen A1 and A2 paths; similar names remain rejected.
- Gate D rebuilds the decision from the persisted Free Queue, candidate block
  ownership, required need, deadlines, q inputs, lambda and tau. It independently
  executes the frozen A1 branch ladder and verifies selected identities, scores,
  newly eligible blocks and tie-breaking. Tampered score, need and selection
  controls fail.
- Gate H compares the recorded History Mode with the mode recomputed by the
  frozen TTL implementation, in addition to TTL and Deadline.
- Source loading binds all six sidecar, trajectory and run SHA-256 identities.
  It requires the original first 60 calls to be an ordered, contiguous success
  cohort; failed calls cannot be silently removed by filtering.
- The static count of 117 gaps remains a structural expectation. Gate H uses
  the actual Native-run events to report the number consumed at each decision.

## Target CUDA Native preflight result

The authorized minimum Native preflight was executed on an RTX 4090D. It used
four diagnostic runs rather than the six-run formal Smoke:

- HR01/A0 verifies the second scenario's three-session timeline and fixed
  pressure geometry;
- HR02/A0 verifies the longest-context scenario on the baseline arm;
- HR02/A1 is the only run whose Gate D evidence represents actual A1 Entry
  scoring and selection;
- HR02/A2 verifies the frozen block-selection path without mislabelling its
  shadow Entry diagnostics as executed A1 decisions.

HR01/A1 and HR01/A2 were deliberately not executed. All six frozen runs remain
unstarted as formal outcomes and, if authorized, must run in a new formal
output directory.

### Runtime binding

- GPU: NVIDIA GeForce RTX 4090 D, 24,564 MiB
- Driver: 580.105.08
- CUDA runtime: 13.0
- Python: 3.12.4
- PyTorch: 2.13.0+cu130
- vLLM: 0.27.1
- Model and tokenizer: `Qwen/Qwen2.5-Coder-1.5B-Instruct`
- Frozen revision: `d18ecad881a290f0c792f1c2b5dbee1820d4a424`
- KV pool: 2,048 blocks of 16 tokens
- Maximum model length: 32,768 tokens
- Maximum batched tokens: 2,048
- Execution code: `55d085e1b66aa75811594d2303d44c2233293961`

### Execution and Gate results

All four runs completed successfully. Each submitted and completed 180 frozen
Agent requests, observed three fixed pressure stages, used peak Native inflight
two, and recorded zero replay-idle wall time.

| Run | Wall seconds | Gate H | Gate D | Empirical TTL decisions | Forced multi-candidate decisions |
|---|---:|---|---|---:|---:|
| HR01/A0 | 57.713 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 76 | 3 |
| HR02/A0 | 77.612 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 75 | 3 |
| HR02/A1 | 74.553 | PASS | PASS | 75 | 3 |
| HR02/A2 | 131.725 | PASS | NOT_APPLICABLE_SHADOW_ONLY | 75 | 3 |

Every run recorded 177 history and TTL decisions, consumed as many as 176
global Server Gap samples, and had zero missing or invalid TTL recomputations.
HR02/A1 independently reconstructed all three actual A1 decisions with zero
invalid or unmatched decisions. Gate D on A0/A2 remains deliberately
non-applicable because their Entry evidence is shadow diagnostic, not executed
A1 scoring.

The aggregate measured wall time was 341.604 seconds. Its instrumented
components were 95.097 seconds of engine initialization, 235.753 seconds of
Native request execution, 33.409 seconds of pressure execution, and 7.561
seconds of evidence writing. Component timers can overlap and therefore must
not be summed to reconstruct wall time.

### Frozen pressure and physical evidence

All 12 Native pressure submissions (four runs times three barriers) matched the
frozen pressure Token IDs and SHA-256 identities exactly. No arm-dependent
pressure compensation occurred.

Every pressure barrier exposed one forced release with multiple legal
candidates. The Native callback persisted 3,679 hashed evictions for HR01/A0,
7,467 for each HR02 A0/A2 run, and 7,862 for HR02/A1. Every persisted hashed
eviction recorded a pre-eviction Native cache key, process identity, block ID,
and successful hash removal.

All 12 selected releases were followed by a later request from the selected
program. At the first request after each barrier, the expected reusable prefix
was only partially cached and recomputation was positive. The observed
recomputed prefix ranged from 528 to 11,632 tokens. Eleven of the 12 barriers
also observed eviction of the selected full-prefix Native key. At HR02/A1's
third barrier, selected block IDs were physically evicted and the following
request recomputed 11,632 tokens, but the selected full-prefix key itself was
not among the eviction callbacks.

This supports a bounded stable-identity and temporal join from logical release
through physical eviction to later APC/recomputation. It does **not** establish
complete content-level causal attribution for every block: the Native eviction
callback explicitly does not assign logical ownership. Content with no later
request before the 60-call boundary remains right-censored and is not counted
as permanently unreused. The final request of each of the three sessions in
each run is likewise terminally right-censored by the frozen observation
window.

## Evidence identity and recommendation

- Raw evidence archive:
  `artifacts/phase2h-history-rich-native-preflight-v2-evidence.tar.gz`
- Archive SHA-256:
  `66d706c37b12d7753a62ca61ef00496a18127a9386579f5795884d11474fa22f`
- Archive validation: `PASS`
- Native schema diagnostic SHA-256:
  `1fd897fe3c29be51098ab321ccad2ea8310120d7509a4c1a18c62c9f35e76b9e`

Recommendation: `GO_FOR_M1_EXECUTION_AUTHORIZATION_REVIEW`. The Native
preflight demonstrates that Gate H is reachable, actual A1 Gate D decisions
are independently reproducible, three-session replay and all pressure barriers
execute under the frozen 2,048-block pool, and the bounded physical evidence
chain is observable. This recommendation does not itself authorize or start
the six-run formal Smoke.
