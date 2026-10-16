# Phase 2F — Combined Algorithm Design: Ours-Evict (simulation candidate v0) x Continuum Retention

**Submitter**: M4 **Reviewer**: M1 **Date**: 2026-10-16
**Branch**: `sim/phase2f-agent-apc-eviction-retention`
**Nature**: **design plus CPU-only offline simulation validation**. No runtime
implementation, no native run, no frozen-baseline change.
**Upstream boundary**: PR #50 (`docs/ours-evict-algorithm-design-v1.md` rev.2)
is currently `CHANGES_REQUESTED / METHOD NOT YET APPROVED / RUNTIME
IMPLEMENTATION NOT AUTHORIZED / B1 LOCKED`.

> Audit note (Member 2, 2026-10-16): this revision incorporates the review of
> the implemented study. Confirmed defects and their fixes are listed in the
> final report (`docs/phase2f-m4-final-report.md` §10); no conclusion below
> changed as a result, and the two corrected measurements (protection-time
> integral, TTL sensitivity probe) are reported explicitly.

---

## 0. Position and inherited rulings

### 0.1 Facts inherited from PR #50 (not re-argued here)

| # | Fact | Source |
| --- | --- | --- |
| F1 | The frozen block-level boundary exposes exactly `EvictionCandidate = {block_id, ref_cnt, has_block_hash, lru_rank}` and `EvictionContext = {required_blocks, free_blocks, total_blocks, timestamp}`. It contains no depth, owner, or content identity. | PR #50 §0.1; `src/kvopt/runtime/vllm/types.py` |
| F2 | vLLM 0.27.1 already prefers hashless blocks natively (`free_blocks()` prepends hashless and appends hashed blocks; `get_new_blocks()` pops from the head). Hashless-first is therefore **not** claimed as an innovation here. | M1 RC-A; vLLM v0.27.1 `block_pool.py` L719–742, L647–667 |
| F3 | `lru_rank` direction: smaller rank is selected earlier by `NativeLRUAdapter`, which sorts ascending and takes `required_blocks`. | M1 RC-B; `src/kvopt/runtime/vllm/adapter.py:27-39` |
| F4 | Q1 logical release does not imply Q2 physical eviction, which does not imply Q3 future recomputed tokens. The cost model prices Q2 only; the Q2 → Q3 mapping is an explicit assumption. | PR #50 RC2; M1 RC-D |
| F5 | Incremental recomputation is defined as `dR = sum_r B * max(0, j_old(r) - j_new(r))`, where `j` is the longest **contiguous** prefix hit depth. It is not the full prefill token count. | M1 RC-D; task contract |
| F6 | Entry-level pressure-release replay effects must not be presented as block-level Ours-Evict effects. | PR #50 §0.1; task §7 |
| F7 | No cost-aware scoring may be added under `src/kvopt/continuum/**`; no adapter field changes; no change to the frozen release key or TTL. | `docs/phase2a-m4-block-level-design-draft.md` §7; PR #50 verdict |

### 0.2 The only ruling requested here

Whether `simulation candidate v0` (§2) may be studied as the Phase 2F
simulation object, with its explicit non-authorized status
(simulation-observable signals, not runtime-deployable, not the formal method).
**Not requested**: adapter field expansion, runtime implementation, B1 unlock,
frozen-baseline changes.

---

## 1. Method layers and this round's boundary

```text
Layer 1  Ours-Evict                independent block-level victim selection
Layer 2  Ours-Evict + Retention    Continuum retention/protection on top
Layer 3  Ours-Full                 plus scheduling coordination (not this round)
```

Layer 1 must run and be evaluated without Retention (arm A2). Layer 2 measures
the incremental contribution of Retention (A3 vs A2, A1 vs A0, and the full
four-arm contrast). All component arms use the same native scheduling
(FIFO by `(arrival, request_id)`); scheduling differences appear only in the
separately reported system reference arm A4 and are never used for component
attribution.

---

## 2. Ours-Evict — `simulation candidate v0`

### 2.1 Motivation: the structural direction of Native LRU inside a free-event band

The native free-queue insertion rules (F2) imply that one request completion
releases a **band** of blocks: hashless blocks are prepended to the queue head
and hashed blocks appended to the queue tail, each group preserving the request
block-table order (head to tail). Inside a hashed band, the chain-head block
therefore has the smaller `lru_rank`, and ascending-rank native selection
evicts **shallow blocks first**.

This is exactly the direction M1 flagged in RC-B, and it is the structural
signal candidate v0 targets:

```text
evicting shallow block a_1  -> the contiguous prefix breaks at block 1 -> the
                               entire suffix is recomputed
evicting deep block a_m     -> blocks 1..m-1 stay reusable -> only the suffix
                               is lost
```

The band-internal direction (head-first vs tail-first insertion) is
**assumption A1**, derived from the pinned vLLM source and the Phase 2C
87/87 contiguous-band evidence. It is *not* measured in this project's runtime
(P5 `(depth, native_lru_rank)` correspondence is `NOT_OBSERVABLE`). The
simulator measures the correspondence directly (§ simulator design §7) and the
sensitivity arm quantifies dependence on A1; in the simulated campaign,
diagnostic arm D1 (explicit shallow-first ordering) reproduces native LRU
bit-for-bit on all 70 draws, which is the in-simulation confirmation that the
native band-internal order is indeed shallow-first.

### 2.2 Dominance theorem (correctness basis)

**Setting.** Content identity forms a prefix trie (chained block hashes, the
same semantics as vLLM prefix hashes). A band is one request's full block list,
i.e. one root-to-leaf chain; shared blocks enter the queue only when their last
owner releases them.

**Theorem.** Fix the number of victims taken from one band. Changing that
band's internal choice from shallow-preferred to deep-preferred (cross-band
order unchanged) never increases aggregate recomputed tokens for **any** future
request set and **any** return distribution.

**Proof.** Take any future request r. If its path does not intersect the band,
its hit depth is unaffected. If it does, the intersection is a prefix `1..q` of
the band (trie property: a path through a deep block passes through all its
ancestors). Let the band hold n blocks and k be taken:

- shallow-preferred (native under A1): positions `1..k` are evicted, so the
  first missing position on r's path is 1 and `j_native(r) = 0`;
- deep-preferred (candidate v0): positions `n-k+1..n` are evicted; if
  `q < n-k+1` nothing on the path is evicted and `j_candidate(r) = q`,
  otherwise the first missing position is `n-k+1` and
  `j_candidate(r) = n-k`.

In both cases `j_candidate(r) >= j_native(r)`, and
`recompute(r) = (m_r - j(r) + 1) * B` is non-increasing in `j`. ∎

**Relation to PR #50 rev.2.** rev.2 could only offer the weaker
"fixed per-chain count" proposition, which RC-C showed does not cover shared
prefixes. The free-event band structure turns "each chain loses the same number
of blocks" into a structural fact (a band *is* one chain), which covers shared
prefixes as well: a shared root sits at the head of every band that contains
it, so deep-first ordering protects it by construction.

**What the theorem does not cover (reported, not hidden):**

| # | Situation | Consequence |
| --- | --- | --- |
| X1 | Assumption A1 is false (native band order is tail-first) | candidate v0 and native select identical sets; no divergence and no harm (the divergence metric reads ~0; the sensitivity arm shows exactly this) |
| X2 | The cut falls on a band boundary | victim set identical to native (non-trivial window absent) |
| X3 | Multiple bands are consumed in one decision | Only the within-band direction changes; cross-band allocation stays native by key construction |

### 2.3 Exact ordering rule (zero hyperparameters)

For each legal candidate block b:

```text
lru_rank(b)       native free-queue position (0 = head = native first)  [runtime]
has_block_hash(b) APC hash presence                                    [runtime]
band(b)           the band's queue position = min lru_rank over its blocks
depth(b)          1-based position on its prefix-trie path (root = 1)
tier(b)           retention eligibility tier (TIER_1 / TIER_2); TIER_1 when
                  retention is off
```

Selection of R victims:

```text
retention on : key(b) = (tier(b), band(b), -depth(b), lru_rank(b))
retention off: key(b) = (band(b), -depth(b), lru_rank(b))

victims = eligible candidates sorted ascending by key, first R
```

Properties:

1. **Zero hyperparameters**: no weights, thresholds or bucket widths; every
   key component is a structural quantity.
2. **Cross-band allocation unchanged**: `band(b)` is the primary key, so the
   same bands are consumed in the same order as native; only the direction
   inside a band is reversed. This is the guarantee behind X3 and the reason
   the hot-long-chain vs cold-short-chain counterexample (PR #50 §3.1) cannot
   break the rule: the colder chain's band is consumed first.
3. **Hashless blocks keep native priority**: hashless blocks cost nothing to
   evict and native already prefers them (F2); candidate v0 keeps that
   behavior unchanged and claims nothing for it.
4. **Ties**: `(band, depth)` is unique inside a band (a band is one chain, so
   depths are distinct); any residual tie is resolved by `lru_rank`. There is
   no randomized tie-breaking.
5. **Safe degradation**: if `depth`/`band` are unavailable (the runtime
   situation), the key collapses to `(lru_rank)` — **exactly** native LRU
   order, not a size rule and not another policy. The collapse is asserted
   bit-for-bit by tests (diagnostic D3).

### 2.4 Signal inventory and runtime availability (RC-E)

| Signal | Unit | Source | Updated | Runtime status |
| --- | --- | --- | --- | --- |
| `lru_rank` | queue position | native free-queue snapshot | every free/acquire | available (`EvictionCandidate.lru_rank`) |
| `has_block_hash` | bool | native block hash state | allocation/eviction | available (`EvictionCandidate.has_block_hash`) |
| `tier` | enum | Continuum `EligibilityPreparation` | every pressure decision | only when retention is on (frozen path already provides it) |
| `depth` | block index (1-based) | prefix-trie path position | fixed at content allocation | **simulation-observable; runtime needs an interface extension** |
| `band` | free-event order | native free-event grouping | every block release | **simulation-observable; runtime needs an interface extension** |

**Minimal interface gap (recorded, not requested).** Runtime deployment would
need, at minimum, an optional read-only `EvictionCandidate.depth: int | None`
plus free-event grouping information (or equivalently "same enqueue batch plus
position within batch"). `depth` alone is insufficient to recover the band
structure (RC-E). Until that capability exists, candidate v0 must not be
described as deployable.

### 2.5 Failure conditions (falsification list for the report)

```text
C1  every band holds <= 1 block, or all cuts fall on band boundaries
       -> identical to native (no divergence)
C2  assumption A1 is false (native is tail-first)
       -> identical to native (quantified by the sensitivity arm)
C3  future requests never reuse the preserved shallow prefix
       -> preserving shallow blocks buys nothing (measured by family S7)
C4  retention shrinks the candidate set until the non-trivial window closes
       -> no combination increment (A3 vs A2 measures this)
C5  the deep block is the only reused part (shared-DAG counterexample)
       -> theorem premise violated; detected by family S3 plus divergence
          attribution
```

---

## 3. Continuum Retention layer (frozen components reused unchanged)

### 3.1 Reuse map

| Responsibility | Reused implementation | Semantics |
| --- | --- | --- |
| Agent/program lifecycle | `continuum.events` + `RuntimeCoordinator.handle` | ProgramStarted / RequestArrived / RequestAdmitted / FollowupWaiting / FollowupCancelled / ToolGapStarted / ToolGapEnded / TurnFinished / BlocksObserved / BlockEvicted |
| Tool-interval history | `ServerGapHistory` / `ExternalToolDurationHistory` | finish → next-arrival gaps tagged by tool type; explicit tool-gap durations kept separate |
| Dynamic TTL | `estimate_ttl` (`continuum.ttl`) | `argmax_tau F(tau) * (T * eta + R) - tau`; COLD_START / GLOBAL / TOOL_SPECIFIC tiers |
| Soft retention / protection | `RetentionManager` | `protected` / `waiting_followup` / `expire_due` / `admit_followup` / `cancel_followup` / `complete_program` |
| Pressure release | `RetentionAwareSelectionCoordinator.prepare` | Tier 1 (hashless or no remaining protected owner) → release whole entries by `(deadline, min newly-eligible lru_rank, key)` until `min(required_blocks, len(queue))` |
| Shared ownership | `_entries_by_block` + `_newly_eligible_blocks_after_release` | a block becomes reclaimable only after **all** owners release; zero-marginal releases are recorded honestly |
| Release commit | `commit_pressure_releases` + `observe_eviction` | logical unprotection and physical eviction are booked separately |
| Frozen baseline arm | `RetentionAwareLRUAdapter` (used directly by arm A1) | `(tier, lru_rank)` order |

### 3.2 What the retention layer decides (boundary)

```text
Retention decides:
  (a) which cached content stays protected        -> entry.protected
  (b) which physical blocks may be evicted now     -> Tier 1 = hashless or all
                                                      owners released/expired
  (c) how soft protection is released under need  -> frozen loop: whole entries,
                                                      (deadline, min rank, key)
  (d) which blocks become reclaimable after that -> PressureReleaseEffect
Ours-Evict decides:
  (e) which of the legal candidates become victims
```

Logical release (c), physical eviction (e) and future recomputation are booked
separately (`pressure_releases`, `physical evictions`, `recomputed tokens`) and
never derived from one another.

### 3.3 Observable retention effects required for the mechanism to count as implemented

1. protection in force during tool gaps;
2. natural expiry of non-waiting entries;
3. forced release under pressure;
4. shared-ownership release differences (a co-owned block enters Tier 2 only
   on the last owner's release; zero-marginal releases are visible).

Effects 1, 3 and 4 occur throughout the campaign (final report §6). Effect 2
does not occur in the simulated regimes: the frozen TTL estimator selects
TTL = 0 for every decision when the queue-delay term degenerates to 0 (the
simulator has no queueing model), and a non-waiting protected entry does not
persist across events except after a cancellation. A bridge-level regression
test exercises the cancellation path with a positive TTL and shows natural
expiry firing; the campaign itself contains no cancelled program, so the
campaign-level count is 0. The claim is therefore scoped: natural expiry was
**not observed in these regimes**, not "unreachable in principle".

---

## 4. Experiment arms, oracle reference and diagnostics

### 4.1 Main arms (same trace, capacity, block size, event times, seeds)

| Arm | Retention | Victim selection | Purpose |
| --- | --- | --- | --- |
| **A0** | off | `lru_rank` ascending (native) | native baseline |
| **A1** | on (frozen path) | `RetentionAwareLRUAdapter` (`(tier, lru_rank)`) | retention's independent increment; the frozen adapter class is instantiated directly for bit fidelity |
| **A2** | off | candidate v0 `(band, -depth, lru_rank)` | Ours-Evict standalone |
| **A3** | on | candidate v0 `(tier, band, -depth, lru_rank)` | target combination |
| **A4** | on | same as A1 plus `ContinuumSchedulingPolicy` admission order | optional full-system reference; reported separately, never mixed into component attribution |

### 4.2 Oracle-like references (research references, not the proposed method)

```text
O1  Belady-style next-use ordering over the eligible set (no retention)
O2  the same ordering inside the retention-restricted eligible set
```

Both arms read the future trace. They are **oracle-like references, not proven
optimal** (Belady-style next-use ordering is not proven optimal under
prefix-truncation semantics) and **not** Ours-Evict; their results indicate
headroom only and must not be quoted as achievable performance.

### 4.3 Non-trivial window and diagnostics

```text
trivial event  : |EligibleCandidates| == required_blocks -> any reordering
                 selects the same set
non-trivial    : |EligibleCandidates| >  required_blocks -> the victim set can
                                                   genuinely diverge
```

The workloads cover both non-trivial sources (unpin overshoot: a release frees
M candidates while only K < M are needed; and several unprotected chains in the
pool at once). The report lists the non-trivial event share and the true
victim-set divergence rates (`VictimSet_A2 != VictimSet_A0`,
`VictimSet_A3 != VictimSet_A1`).

| Arm | Definition | Observed result | Use |
| --- | --- | --- | --- |
| **D1** | candidate v0 with the in-band direction reversed (shallow-first) | **bit-identical to A0** on all 70 draws | model validation: the simulated native band order *is* shallow-first, i.e. candidate v0 reverses exactly the native direction (corresponds to PR #50's A4-style direction check; the outcome is a positive model confirmation, not a degradation) |
| **D3** | `depth` and `band` dropped (order by `lru_rank` only) | must equal A0 bit-for-bit | source discrimination (corresponds to PR #50 A5); asserted by tests |
| **S1** | whole campaign re-run with the free-order assumption flipped (`tail_first`) | candidate v0 and native select identical victim sets in every family | quantifies dependence on assumption A1 |

### 4.4 Mechanism chain (task §7)

```text
L1 legality    victims subset of eligible, |victims| = R, unique, requirement met
L2 real difference   victim ID *sets* differ from native (not just order)
L3 physical change  cache mapping, contiguous hits, later reusability change
L4 recomputation    same future trace replayed; aggregate recomputed tokens change
increment attribution A0/A1, A2/A3, A1/A3, A2/A3
failure attribution not triggered / not implemented / mechanism failed /
                    effective but unusable
```

The first-divergence counterfactual isolates the causal effect of a single
decision: the baseline arm is re-run with the challenger's victims substituted
at the first divergent decision, and the future recomputation difference is
attributable to that decision alone.

---

## 5. Metric definitions (comparison direction is explicit)

Per request r (measured window):

```text
N_r = prompt tokens
M_r = cacheable blocks = (N_r - 1) // B        (frozen Phase 2E cap)
E_r = eligible prefix tokens = LCP(r, any earlier request) * B
C_r = j(r) * B, j(r) = longest contiguous hit depth (strict truncation)
recomputed_r          = E_r - C_r
actual_prefill_r      = N_r - C_r
new_suffix_r          = N_r - E_r
```

Per draw (statistical unit = independent scenario draw):

| Metric | Definition |
| --- | --- |
| `aggregate_recomputed_tokens` | `sum_r recomputed_r` |
| signed aggregate delta | `sum_r (recomputed_challenger(r) - recomputed_baseline(r))`; **negative means the challenger recomputes less (improvement)** |
| `dR` (task formula) | `sum_r B * max(0, j_baseline(r) - j_challenger(r))` — non-negative extra recomputation caused by the challenger |
| `gross` | `sum_r B * |j_baseline(r) - j_challenger(r)|` — absolute request-level change |
| `NGR` | `|sum delta| / sum gross`; `NOT_APPLICABLE_ZERO_GROSS` when gross is 0 |
| `cache_reuse_efficiency` | `sum C_r / sum N_r` |
| eviction counts | hashed evictions (real hash cleanup) and hashless reuses, separately |
| non-trivial share | share of decisions with `|eligible| > required` |
| divergence rate | share of index-aligned decisions with different victim ID sets |

Statistics: per-draw pairing; mean and median; 10,000-resample paired bootstrap
95% CI (seed 20261016); improved / tied / degraded draw counts; per-family and
overall. Requests, turns and decisions are never treated as independent
samples.

---

## 6. Research question and pre-registered criteria

> In agent-like multi-turn tool-calling cache workloads, does Continuum's
> dynamic retention and pressure release add value on top of an independent
> cost-aware block eviction rule? Is the gain from better physical victim
> selection, from extended effective reuse, or merely from a candidate-set
> change? Where does the benefit exist, and where does it disappear?

```text
H-attr-1  A2 < A0 (paired aggregate recomputed tokens) and divergence rate > 0
          -> the gain comes from physical victim selection (in-band deep-first)
H-attr-2  A1 < A0 and A3 < A2 in the same direction
          -> retention adds value beyond the victim rule (candidate-set
             restriction plus extended effective reuse)
H-attr-3  A3 ~ A2 while A3's candidate set is much smaller than A2's
          -> retention changes only the candidate set, not recomputation
             (recorded honestly as no increment)
H-null    negative-control family (S7) may show delta = 0 or delta > 0
          (policy cost); no benefit is presumed
```

---

## 7. Traceability

| Statement | Source |
| --- | --- |
| frozen 4-field candidate / native LRU ascending | `src/kvopt/runtime/vllm/types.py`; `adapter.py:27-39` |
| hashless preference is native | M1 RC-A (vLLM v0.27.1 `block_pool.py` L719–742, L647–667) |
| band-internal head-first insertion (assumption A1) | same source (`append_n(blocks_with_hash)` preserves block-table order) plus Phase 2C 87/87 contiguous bands; the direction is not measured in this project's runtime |
| D1 ≡ A0 confirms the native band direction | campaign result; `tests/test_agent_sim_invariants.py::test_direction_reversal_is_bitwise_native` |
| Q1/Q2/Q3 separation, dR formula | M1 RC-D; PR #50 §2 |
| frozen pressure-release key and tier semantics | `src/kvopt/continuum/pressure.py:300-324`; `selection.py` |
| shared block reclaimable only after all owners release | `pressure.py:260-278`; `tests/test_continuum_pressure.py:277-290` |
| frozen TTL objective and cold-start concretization | `continuum/ttl.py:63-78`, `ttl.py:27-34` |
| PrefillReload formal profile | `docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json` |
| Phase 2E metric contract and statistical unit | `docs/phase2e-m4-task-a-metrics-freeze.md` §1–§3 |
| no cost-aware scoring under `continuum/**` | `docs/phase2a-m4-block-level-design-draft.md` §7 |
| PR #50 current verdict | PR #50 review (`CHANGES_REQUESTED`, RC-A..RC-E) |
| no-lookahead gate and audit regressions | `src/kvopt/agent_sim/policies.py` (`requires_future_trace`); `tests/test_agent_sim_audit.py` |
