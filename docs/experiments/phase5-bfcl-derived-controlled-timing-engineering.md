# Phase 5 BFCL Derived Controlled-Timing Engineering

**Status:** Frozen M4 appendix integrated; offline materialization and Q4D/Q5D
evaluation implemented. No Formal Cohort or GPU execution is authorized.

## Scope

This implementation supports the M1-approved special workload type
`BFCL_DERIVED_CONTROLLED_TIMING`. It retains the immutable BFCL-Result semantic
interaction records while refusing to invent historical Tool Gap timestamps or
an original Agent terminal state.

The source and replay terminal states remain distinct:

- source: `SOURCE_TERMINAL_UNKNOWN`;
- replay: `REPLAY_TRACE_EXHAUSTED`.

Replay exhaustion means only that the frozen semantic trace was consumed. It is
not natural source completion and does not assert that no later source request
would have existed.

## Implemented contracts

- Immutable raw-record SHA-256 binding.
- Stable Program, Case, Request and request-order identities.
- Deterministic caller-supplied Synthetic Tool Gap schedules.
- Synthetic timing labeled `SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED`.
- Stateful release gate that reveals a gap only after the preceding request has
  completed, preventing future-gap leakage to a policy.
- Explicit exclusion support for `web_search_no_snippet_51`.
- Derived Qwen Token Materialization labeled
  `DERIVED_NOT_QWEN_NATIVE_TRACE`.
- Independent hashes for source archives, protocol appendix, frozen BFCL Tool
  Definitions, Arrival Generator, per-Session timing and Token IDs.
- One cross-system timing identity shared by Native, Continuum Official, A0,
  A1, A3 and DVA-ER v1.
- Independent Q4D/Q5D evaluation with fail-closed six-system schedule identity,
  exact-once request consumption and terminal-state separation.
- Mechanical context-budget partitioning into 40
  `EXCLUDED_CONTEXT_BUDGET` Sessions and 159 derived-qualified Sessions without
  failing the whole collection.
- A hash-bound `context-budget-exclusions.json` included in the workload Seal
  and archive manifest.
- Formal Cohort selection and GPU authorization remain false.

The historical assistant tool-call list is converted to replay prompt text only
from BFCL's preserved successful `model_response_decoded` evidence using the
frozen rule `BFCL_HANDLER_DECODED_LIST_BRACKET_JOIN_V1`. No call or argument is
inferred from free text.

## Real archive CPU findings

Read-only validation against the two pinned BFCL-Result archives found:

- semantic records parsed: 199;
- SNIPPET records parsed: 100;
- NO_SNIPPET records parsed: 99;
- excluded record: `web_search_no_snippet_51`;
- reconstructed model requests: 1,040;
- adapter parse failures: 0.

The frozen appendix resolves the accepted population as 100 SNIPPET plus 99
NO_SNIPPET Sessions. The only archive-level exclusion remains
`web_search_no_snippet_51`.

Using the pinned Qwen tokenizer and chat-template identity, the read-only
materialization check found:

| Stratum | Sessions | Requests | Requests over 32,640 | Affected Sessions | Maximum Prompt Tokens |
|---|---:|---:|---:|---:|---:|
| SNIPPET | 100 | 471 | 22 | 14 | 97,971 |
| NO_SNIPPET | 99 | 569 | 41 | 26 | 210,085 |
| Total | 199 | 1,040 | 63 | 40 | 210,085 |

The 40 affected Sessions remain in the evidence ledger and are marked
`EXCLUDED_CONTEXT_BUDGET`; they do not receive Q4D/Q5D PASS and do not enter the
eligible derived population. The other 159 Sessions continue, and the collection
status is `READY_WITH_CONTEXT_EXCLUSIONS`. The implementation does not truncate
Tool Results, shorten history, split a Session or reconstruct a different Prompt.

## Materialization entry point

`scripts/spikes/phase5_dataset/materialize_bfcl_derived_workload.py` consumes:

- both immutable BFCL-Result archives;
- the frozen M4 special-workload appendix;
- frozen BFCL Tool Definitions;
- the frozen Arrival Generator manifest;
- the pinned local Qwen tokenizer;
- a private Evidence Root.

The script refuses to overwrite output and requires the output directory to be
inside the private Evidence Root. Raw third-party content and derived Token IDs
must not be committed to public Git/PR artifacts.

The materializer validates the appendix canonical and file identities, the 199
accepted IDs, all 841 frozen boundaries, Q4D/Q5D contracts and companion input
hashes before producing evidence. Q4D/Q5D PASS is a data and deterministic replay
contract result; it does not claim GPU Native conformance or algorithmic benefit.
