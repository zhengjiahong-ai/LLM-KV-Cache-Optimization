# Phase 2C M6 Workload Content and APC Reuse Audit

## Scope

This is a read-only historical diagnostic of the sealed H1 Level-A archive. It
does not rerun H1/H2, alter a sealed artifact, implement a policy, or authorize
a formal campaign. The source archive SHA-256 is
`af5be5bd56a172f7945f12712289708aa55cda01f1b8c05a2bc3215b14c90af7`.

## Reproduced historical result

The audit independently reproduced 1,068 request rows: 903 turn requests and
165 pressure requests. Of the turn requests, 495 had an eligible reusable
prefix. Their native APC outcomes were 288 full hits (58.18%), 48 partial hits
(9.70%), and 159 misses (32.12%). The 408 first eligible-turn predecessors are
classified as `NO_REUSE_ELIGIBLE_PREFIX`, not as misses.

All required identity checks reproduced exactly:

- first-to-second same-program native hash chains: 408/408 identical;
- first-to-all-later same-program chains: 495/495 identical;
- different-program first chains: 0/771 equal;
- three-seed APC outcome and cached-token groups: 165/165 identical;
- partial hits: 16 independent request positions repeated across three seeds;
- campaign configurations: 42/42 used `max_concurrent_requests = 1` and
  `max_new_tokens = 1`.

Family counts `(FULL_HIT, PARTIAL_HIT, MISS)` were F1 `(66, 6, 36)`, F2
`(39, 9, 18)`, F3 `(48, 12, 12)`, F4 `(54, 9, 48)`, F5 `(60, 9, 6)`, and F6
`(21, 3, 39)`.

## Field lineage

| Field or fact | Classification | Source and interpretation |
|---|---|---|
| scenario, family, seed | `PLANNED_INPUT` | Campaign config; joined through derived `runs.jsonl`. |
| ownership group and prefix prompt | `PLANNED_INPUT` | H1 compiler candidate contract and trace. |
| actual prefix construction | `MATERIALIZED_INPUT` | `_program_prefix_token_ids` and `_turn_token_ids`; keyed by `program_id`. |
| native APC hash chain and cached tokens | `NATIVE_OBSERVED` | `VLLM_NATIVE_REQUEST_OBSERVATION`, preserved in runtime evidence. |
| eligible prefix and APC label | `OFFLINE_DERIVED` | Runtime-evidence join and APC classification. |
| exact submitted historical token IDs | `NOT_OBSERVABLE` | Token IDs were not persisted. Re-execution would be reconstruction, not observation. |

The H1 compiler used `ownership_group` to reuse a logical `prefix_prompt`, but
the Metal backend ignored that identity when constructing actual token IDs.
`_program_prefix_token_ids` hashes `program_id`, while `_turn_token_ids` reuses
that fixed program prefix and appends only a request-specific one-token suffix.
With `max_new_tokens = 1`, later model output was not accumulated into future
prefixes. Therefore logical sharing, lifecycle labels, and concurrency labels
did not create hierarchical native content overlap.

## Four-layer APC interpretation

1. **Content overlap potential** is represented by native hash-chain equality.
   Same-program content was invariant; different programs never shared a full
   first-request chain, including programs with the same ownership group.
2. **Reuse eligibility** is a lifecycle fact. The 408 predecessor rows with no
   earlier reusable prefix are not native misses.
3. **Physical residency** is measured by cached tokens conditional on an
   eligible prefix. It varied after pressure even when the content chain stayed
   identical.
4. **Realized APC** is the conditional full/partial/miss label. It combines
   fixed content identity with observed survival and must not be interpreted as
   a pure content-distribution statistic.

For example, `h1-f5-draw-02-seed-101` declares `h1-agent-1` and
`h1-agent-2` in ownership group `shared-0`, but their first native observations
at event indices 7 and 20 have different hash chains. Within `h1-agent-1`, the
chain remains identical while event 73 observes 464/512 cached tokens
(`PARTIAL_HIT`) and event 110 observes 512/512 (`FULL_HIT`). This separates
content identity from physical residency without claiming unavailable
eviction-time ownership.

## Hypothesis verdicts

- `H-DATA-1` content homogeneity: **SUPPORTED**.
- `H-DATA-2` seed ineffectiveness for content topology: **SUPPORTED**.
- `H-DATA-3` content/cache-state confounding: **PARTIALLY_SUPPORTED** because
  historical eviction-time content ownership is unavailable.
- `H-DATA-4` richer structure changes native APC: **NOT_OBSERVABLE** until a
  separately authorized bounded native pilot is executed.

## Boundaries and next design step

The audit does not reconstruct missing token IDs and does not assign every miss
to a single cause. Native eviction ownership, counterfactual no-pressure APC,
and the effect of true hierarchical content remain unobservable in this
archive. The next deliverable is a versioned, block-aligned segmented content
schema covering `W-COLD`, `W-EXACT`, `W-XPROGRAM`, `W-ROOT-FORK`, `W-NESTED`,
`W-TURN-GROW`, `W-HOT-COLD`, and `W-PRESSURE`. A native pilot remains locked
until design confirmation; `formal_campaign_authorized` remains `false`.

## Proposed content schema v1

The machine-readable proposal is
`configs/phase2/phase2c-workload-content-schema-v1.json`. It separates reusable
content into block-aligned `shared_root`, `branch`, and cumulative
`turn_extension` segments. A one-token request suffix stays outside the
reusable boundary. Explicit content keys, rather than program ID, ownership
labels, or prompt strings, determine submitted tokens.

The eight topology classes specify relationships rather than desired outcomes:

- `W-COLD`: unique content without a prior eligible request;
- `W-EXACT`: exact repeated reusable content;
- `W-XPROGRAM`: exact content shared across different program IDs;
- `W-ROOT-FORK`: shared root followed by distinct branches;
- `W-NESTED`: a short reusable prefix nested in a longer one;
- `W-TURN-GROW`: cumulative block-aligned context extensions;
- `W-HOT-COLD`: stable hot content interleaved with unique cold content;
- `W-PRESSURE`: fixed content compared under no-pressure and controlled-pressure conditions.

Reuse interval, interleaving, tool gap, concurrency, capacity, and pressure are
orthogonal controls. Every eventual materialization must record exact submitted
digest, expected token/block LCP, native hash chain, cached tokens, suffix and
special-token boundaries, and collision checks. The schema explicitly forbids
target hit-rate and target partial-hit-rate tuning. Its validator also rejects
authorization drift, missing topology classes, and non-block-aligned reusable
segments.
