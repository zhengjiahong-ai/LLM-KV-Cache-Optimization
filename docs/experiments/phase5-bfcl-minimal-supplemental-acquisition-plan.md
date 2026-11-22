# Phase 5 BFCL Minimal Supplemental Acquisition Plan

## Status and authority

This document implements M1's Route A decision: the Formal Protocol remains
unchanged, synthetic Tool Gaps are not admissible, and the 199 complete
BFCL-Result semantic traces do not enter the Formal Cohort. It is an execution
proposal only. It does not authorize a provider call, a pilot, batch
acquisition, Cohort selection, GPU work, Calibration, or the Formal Campaign.

The acquisition frame remains exactly the frozen 100 SNIPPET plus 100
NO_SNIPPET cases at BFCL revision
`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`. Case IDs, ordering, source
questions, search modes, and content identities are unchanged.

## Feasibility conclusion

A protocol-conforming BFCL Session is technically collectable only by running
the complete Agent interaction again with a real, approved search/content
source and recording clocks at the acquisition boundary. A later observation
cannot retroactively supply an observed Tool Gap or terminal state for an
archived GPT-5.2 Session. Therefore, new timestamps cannot be spliced into the
199 BFCL-Result records.

No currently reviewed source closes the complete contract:

- BFCL-Result supplies 199 useful semantic interaction traces but no observed
  Tool Gap clocks or explicit terminal fields.
- Tavily search was technically usable, but the authorized Forbes Extract
  preflight failed closed before any Extract call because the publisher access
  and retention boundary was not sufficiently clear.
- A provider API alone cannot clear third-party page bodies. HTML scraping,
  CAPTCHA/login bypass, paywall access, or silent URL/query replacement remain
  prohibited.

Accordingly, acquisition feasibility is `NOT_YET_ESTABLISHED`, not impossible.
It becomes established only after M4 accepts one complete provider/content
chain and M1 authorizes the exact bounded execution.

## Evidence that may be reused

The following BFCL-Result evidence may be reused internally without changing
its identity:

- the 200 ordered archive IDs and their mapping to the frozen frame;
- the 199 complete message/tool-call/tool-result sequences;
- tool-interaction topology and error observations;
- immutable source file, Git blob, record, and repository hashes;
- private page-content evidence for internal comparison, subject to the M4
  internal-use boundary;
- derived Qwen tokenization for Adapter/Materializer engineering tests, labeled
  `DERIVED_QWEN_TOKEN_MATERIALIZATION` and never Qwen-native.

These records may serve as schema fixtures, regression inputs, and an
independent comparison against newly collected interaction topology. They may
not provide Tool Gap values, terminal states, source sampling configuration,
Qwen-native tokens, formal Q1-Q9 PASS, or formal workload observations.

`web_search_no_snippet_51` remains an immutable excluded error record with
`SOURCE_TOOL_OUTPUT_SIZE_LIMIT`; it is not retried, repaired, replaced, or
counted as complete.

## Evidence that must be newly observed

Every supplemental acquisition attempt must record the following from the same
Agent Session and the same clock domain:

1. planned case start and actual Agent start;
2. every model-request dispatch and model-response completion;
3. every tool-call emission, including exact tool name and arguments;
4. provider request dispatch and response completion;
5. every URL-fetch dispatch and response completion, when the mode requires a
   page fetch;
6. delivery of each tool result to the Agent;
7. dispatch of the next model request;
8. explicit terminal transition and reason.

The primary timing clock is `system_monotonic`. UTC timestamps are recorded
only for audit/provenance. For consecutive model requests `i` and `i+1`, the
observed within-Session gap is frozen as:

```text
tool_gap_i = model_request_dispatch_(i+1) - model_response_complete_i
```

The provider/fetch sub-events remain available to decompose that interval.
Negative or missing intervals, mixed clock domains, inferred times, and values
derived from source latency summaries fail Q4. Replay uses the frozen observed
gap; it does not replay live network access or claim that local fixture latency
is the original network latency.

## Explicit terminal contract

The collector must write one terminal record rather than deriving termination
from the presence of a final answer. Allowed acquisition classifications are:

| Terminal state | Qualification meaning |
|---|---|
| `NATURAL_COMPLETION` | Agent emitted an accepted natural terminal under the frozen runner contract |
| `STEP_LIMIT_RIGHT_CENSORED` | Explicit collector step limit reached; retain censor provenance |
| `CONTEXT_LIMIT_FAILURE` | Failure; never converted to a natural or censored success |
| `TOOL_FAILURE` | Tool/provider failure with original error evidence |
| `PROVIDER_TIMEOUT` | Provider timeout with no substitution or retry-based relabeling |
| `INFRASTRUCTURE_FAILURE` | Runtime/container/network infrastructure failure |
| `MODEL_FAILURE` | Model endpoint or decoding failure |
| `INCOMPLETE_EVIDENCE` | Required payload, clock, response, or identity missing |

The terminal record binds the last model/tool event, collector limit, error
class, retry count, right-censor flag, and raw-evidence SHA-256. Q5 remains a
mechanical qualification decision; no `final_answer_present -> completed`
inference is introduced.

## Provider and content admission gate

Before any network call, M4 must approve a single documented chain covering:

- provider identity, API/version, automated-access terms, and retention terms;
- whether raw search responses may be retained for private internal research;
- publisher terms, robots/access controls, paywall/login state, and retention
  boundary for every required page-fetch domain;
- third-party-content labeling and the private Evidence Root;
- prohibition on public redistribution of raw page bodies and derived tokens;
- error, empty-result, rate-limit, and timeout behavior without substitution;
- shared source identity between each SNIPPET/NO_SNIPPET pair.

The provider must return real results. Mock, synthetic, community fixtures of
unknown origin, HTML scraping outside accepted terms, CAPTCHA bypass, and
silent fallback providers are inadmissible. A provider-returned URL is recorded
as observed evidence; M6 may not manually replace the frozen query or a failed
URL to obtain a passing case.

If no provider/content chain passes this gate for the frozen frame, BFCL remains
an internal derived workload and is not used as a Formal workload source in
this campaign. That outcome is reported rather than repaired through selective
case removal.

## Proposed bounded execution after separate authorization

### Stage 0 — no-call preflight

M4 reviews provider and publisher boundaries, while M6 validates credentials,
model/tokenizer revisions, frozen frame hashes, event-clock support, terminal
recording, immutable raw storage, and secret redaction. This stage emits only
metadata and performs no search/content request.

### Stage 1 — one frozen source-pair pilot

After explicit M1 authorization, execute exactly one predeclared source
question in both frozen modes. The query and case IDs are taken directly from
the frame. The same real source identity is bound across SNIPPET and
NO_SNIPPET. No alternate query, manually selected URL, fallback provider, or
automatic retry is allowed.

The pilot passes only when both Sessions have complete messages, real tool
calls/results, monotonic Tool Gap evidence, explicit terminal evidence,
immutable raw provider responses, private content retention, exact Qwen
materialization, and content/provenance hashes. A failure stops the route and is
archived; it does not trigger a second pilot automatically.

### Stage 2 — frozen 200-case acquisition

This stage requires a second explicit M1 authorization based on the pilot and
M4 review. Execute all 200 cases in `phase5_case_index` order. Attempt records,
failures, empty results, timeouts, censoring, and disqualifications remain in
the ledger. There is no outcome-driven replacement, query change, URL change,
selective reacquisition, or promotion of BFCL-Result records into new Native
Sessions.

### Stage 3 — offline processing

Normalize immutable raw Sessions, perform Qwen Token Materialization, execute
Q1-Q9 mechanically, and create a private content-bearing evidence package plus
a content-minimized public audit report. M4 independently reviews provenance,
content boundaries, and qualification. M6 does not select the Formal Cohort.

## Pilot acceptance gates

All gates are fail-closed:

1. frozen revision, frame, query, case, mode, and order identities match;
2. provider and publisher/content review is M4-accepted;
3. raw provider/page responses and hashes are immutable and private;
4. complete Agent message, tool-call, argument, result, and ordering evidence;
5. one monotonic clock domain covers every model/tool boundary;
6. observed Tool Gaps are finite, non-negative, and directly calculated from
   recorded events;
7. explicit terminal/censor/failure record is present;
8. exact pinned Qwen tokenizer/chat-template/tool definitions produce the
   derived request Token IDs;
9. context and generation budgets pass without truncation or history rewriting;
10. replay uses frozen fixtures and never accesses the live provider;
11. all secrets are absent from evidence and logs;
12. archive and manifest SHA-256 validation passes.

`NOT_OBSERVABLE`, missing evidence, unclear content rights, and partial pair
completion are failures, not warnings.

## Resource estimate

Stage 0 is CPU-only. The bounded pilot requires two Agent Sessions and a real
model endpoint but no Native Conformance GPU. The 200-case batch cost cannot be
frozen until a provider, its per-call/page-fetch pricing, and the pilot's actual
call distribution are accepted. The plan therefore does not invent a request
or monetary budget before those observations exist.

## Decision requested from M4 and M1

M4 should first state whether any proposed provider/content chain satisfies the
admission gate. If none does, the recommended outcome is to retain BFCL only as
an internal derived workload and proceed without the BFCL Formal stratum,
subject to M1's handling of the frozen two-stratum design. If one chain passes,
M1 may separately authorize the exact one-pair pilot. No batch authorization is
implied by approval of this document or its pilot.
