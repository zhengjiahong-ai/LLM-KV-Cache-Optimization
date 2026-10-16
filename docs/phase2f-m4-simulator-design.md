# Phase 2F — Simulator Design: Physical-Block APC + Agent Lifecycle + Continuum Retention

**Submitter**: M4 **Reviewer**: M1 **Date**: 2026-10-16
**Nature**: CPU-only, GPU-free, model-free event-driven offline simulation.
**Not** a latency model and **not** a serving benchmark.
**Companion**: `docs/phase2f-m4-combined-algorithm-design.md` (algorithm layer).

---

## 0. Why a new simulator

Verified inventory (main @ `069e5dc`): nothing in the repository implements a
physical-block-level APC simulation with contiguous-prefix hits, shared
prefixes, or post-eviction cache state:

| Existing artifact | Actual semantics | Gap |
| --- | --- | --- |
| `kv_cache/manager.py::KVCacheManager` | request-granular logical block counter + `set[int]` free set | no content identity, no contiguous prefix, whole-request eviction |
| `runtime/simulator.py::Simulator` | request-level functional loop (1 token/step) | no block events, no APC hit/miss |
| `costaware/replay.py` | replays the pressure loop over recorded `FORCED_RELEASE_DECISION` snapshots | entry-level; does not simulate physical eviction consequences |
| `workload/phase2e_*` | workload generation/validation (CPU) + Metal backend execution | execution requires a real backend |

A separate physical-block harness is therefore built as `src/kvopt/agent_sim/`.
It **reuses** the frozen Continuum components unchanged and records its
deviations from real vLLM explicitly (§9).

---

## 1. Content identity and the prefix trie

Each request prompt is a sequence of block-aligned segments; block i carries a
chained content hash:

```text
content_id(b_0) = H("root", seg_key(b_0), 0)
content_id(b_i) = H(content_id(b_{i-1}), seg_key(b_i), i)
```

This mirrors vLLM prefix-hash semantics: identical tokens at different prefix
positions produce different identities, so the content universe is a prefix
trie. Sharing a deep block implies sharing every ancestor, which makes per-block
`depth` a well-defined content property.

**Cacheable-prefix cap (frozen semantics).** For an N-token request the
cacheable prefix is `M = (N - 1) // B` blocks, following the frozen derivation
in `profiling/runtime_evidence.py::_eligible_prefix_tokens`. The final prompt
block is allocated as a **hashless** physical block, never enters the cache
mapping, and can never be hit.

---

## 2. Physical block pool and free queue (vLLM 0.27.1 alignment)

```text
pool: fixed total_blocks slots; block_size_tokens defaults to 16 (configurable)
slot state: content_id, depth, ref_cnt, band_id, band_hashless, band_pos,
            has_block_hash, in_queue, prev/next
cache mapping: content_id -> block   (hashed blocks only; the single source of
                                      truth for hits)
free queue: doubly linked list in native order; lru_rank = position (0 = head)
```

**Insertion rules (assumptions A1/A2).** One request completion releases its
whole block list (head to tail). Because vLLM prepends hashless blocks and
appends hashed blocks, the release produces **two queue runs**:

```text
hashless blocks -> prepended at the queue head (order preserved)
hashed blocks   -> appended at the queue tail (order preserved)
```

A band is therefore keyed by `(free_event_id, kind)`; blocks never allocated
belong to the synthetic band `(-1, hashless)` and sit between the freed
hashless tails and the hashed region. The `head_first` / `tail_first` flag
selects the list order inside the hashed run and drives sensitivity arm S1.

**Eviction.** A selected victim leaves the queue; if hashed, its mapping entry
is removed (real hash cleanup) and the slot is immediately reassigned to new
content (`get_new_blocks` → `_maybe_evict_cached_block` semantics). Hash status
follows the assigned position, not the slot's history.

**Physical ID lifecycle.** Slot IDs are recycled; content identity is not. The
mapping is the only hit source, so a recycled slot cannot produce a phantom
hit. Descendants of an evicted ancestor stay cached (each has its own hash, as
in vLLM) but are unreachable through the truncated prefix until the ancestor is
re-cached; this recovery path is pinned by a regression test.

**Invariants** (`BlockPool.check_invariants`, asserted once per run):

1. every block is either queued (`in_queue`, `ref_cnt == 0`) or owned
   (`ref_cnt >= 1`) — never both, never neither;
2. each mapped block's `content_id` equals its mapping key;
3. no content identity is held by two blocks (duplicate assignment rejected);
4. queue size equals the number of queued blocks.

---

## 3. Allocation path (one LLM request)

```text
input: request r (content ids c_1..c_M plus the hashless tail), time t
1. strict prefix-truncated hit depth:
     j = 0
     while j < M and c_{j+1} in cache_mapping: j += 1
     # the scan stops at the first missing block; later cached blocks do not
     # count (no set-intersection shortcuts)
2. acquire hits: for i in 1..j: unlink from the queue if present, ref_cnt += 1
3. needed = (M - j) + 1
4. if needed > len(free queue): hard error (single request above capacity;
   the generator validates this cannot happen)
5. victim selection (arm specific, §6):
     candidates = the complete free queue in order (lru_rank = index)
     retention on : frozen coordinator prepares eligibility and pressure
                    releases; releases are committed
     retention off: all blocks eligible
     victims = policy selects min(needed, |eligible|) blocks
6. execute: victims are assigned head-to-tail to the unmatched full blocks,
   then to the hashless tail; hashed victims notify the retention manager
   (mirroring the frozen `_maybe_evict_cached_block` hook)
7. bookkeeping: N_r, M_r, E_r, C_r, recomputed_r
```

---

## 4. Agent lifecycle and event timing

Event heap keyed by `(timestamp, seq)` with `seq` assigned at generation time;
processing is fully deterministic. Requests execute instantaneously at their
arrival time (serialized execution, matching the Phase 2E
`max_concurrent_requests = 1` regimes); concurrent agents interact only through
the shared pool and the shared retention entries.

```text
PROGRAM_STARTED / PROGRAM_COMPLETED      program boundary (observational)
REQUEST_ARRIVED                          records the server-gap history
REQUEST_ADMITTED                         admit_followup (ends prior idle
                                         protection of that program)
   -> §3 allocation path
TOOL_GAP_STARTED / TOOL_GAP_ENDED        external tool intervals (their own
                                         timestamps)
TURN_FINISHED(is_terminal, next_tool)    TTL decision + retention upsert
FOLLOWUP_WAITING                         protection during the idle window
FOLLOWUP_CANCELLED                       abnormal termination
BLOCKS_OBSERVED / BLOCK_EVICTED          block association / physical eviction
```

**Clock discipline (audited).** The monotonic clock advances only at request
arrivals; tool-gap-end events carry their own timestamps
(`arrival + declared gap`) without moving the clock, so the clock can never
move backwards and a future tool return cannot influence an earlier decision.
The declared gap and the observed server gap are recorded separately (external
tool duration vs. finish → next-arrival gap), exactly as in the frozen runtime.
A regression test asserts monotonicity and that every tool-gap record's
start/end timestamps equal `arrival` and `arrival + gap`.

**Multi-turn structure.** Turn t's prompt extends turn t-1's cacheable prefix
with a new segment (natural trie extension). Termination is configurable:
`COMPLETED` (terminal turn → `complete_program`) or `CANCELLED` (abnormal end
after the final turn; the entry lingers unprotected, matching the frozen
lifecycle in which `ProgramCompleted` is a no-op and only a terminal turn
completes a program).

**Warmup / measured windows.** A trace carries `warmup_requests` and
`measured_requests`; both execute (warmup changes cache state and TTL history),
metrics cover the measured window only. Cold draws have an empty warmup.

---

## 5. Retention reuse mapping (frozen components only)

| Frozen component | Role in the simulator |
| --- | --- |
| `RuntimeCoordinator` (clock = `FakeClock`) | receives §4 events; maintains server-gap / tool-duration / queue-delay / eta histories; produces the real `TTLDecision` and upserts `RetentionEntrySnapshot(protected=True, block_ids=...)` at each non-terminal `TurnFinished` |
| `RetentionManager` | protection state, lazy expiry, waiting, admit/cancel/complete, `observe_eviction` reverse-index cleanup |
| `RetentionAwareSelectionCoordinator.prepare` | Tier 1 / Tier 2 and pressure release at every allocation |
| `RetentionAwareLRUAdapter` | arm A1 instantiates the frozen class directly (bit fidelity) |
| `load_prefill_reload_provider` + `compute_default_ttl_seconds` | the TTL's R term and cold-start TTL from the formal profile artifact |
| `ContinuumSchedulingPolicy` | admission order in system-reference arm A4 only |

**TTL input provenance.**

| Input | Value | Source |
| --- | --- | --- |
| global / tool server-gap samples | trace-declared gaps | `OBSERVED` (workload input; freeze §2 permits external → observed records) |
| `queue_delay_t_seconds` | **0.0** — the simulator has no queueing model | `OBSERVED`, degenerate; documented limitation |
| `eta` | `eta_history.eta()` computed by the frozen estimator | `OBSERVED` / `APPROXIMATED` (frozen estimator) |
| `prefill_reload_seconds` | formal profile (16–512 linear interpolation); beyond 512 linear extrapolation, separately flagged | `APPROXIMATED` (profile artifact) + extrapolation flag |
| `default_ttl_seconds` | `compute_default_ttl_seconds(profile(256))` = `max(0, log(0.0887))` = 0.0 | frozen concretization |

**Measurement-timing notes (audited).**

- `expire_due()` runs once per arrival group (freeze §7 "at/near each scheduler
  step"); the coordinator independently recomputes ordinary expiry from the
  decision timestamp, so a stale manager flag cannot change eligibility.
- Protection-window bookkeeping (reuse, survival at window end) is measured at
  the moment protection ends: at admission *before* the returning request's own
  allocation, at group-start expiry, and after each decision (which covers
  pressure releases and cancellation).
- The protected block-token-seconds integral integrates the recorded
  `(timestamp, protected-count)` samples in time order; at equal timestamps the
  last recorded sample wins. The integral covers `[first event, last event]`.

---

## 6. Policy interface and the no-lookahead contract

```text
policy input (per decision):
  SimCandidate = {block_id, lru_rank, has_block_hash, tier, depth, band_id,
                  band_hashless, band_pos, content_id}
  DecisionContext = {required_blocks, free_blocks, total_blocks, timestamp,
                     decision_index, request_id, preparation}
policy output: ordered victim block ids (unique, subset of candidates,
              count = min(required_blocks, |candidates|))
```

**No-lookahead contract.** `DecisionContext` also carries `future_index` and
`current_request_index`, but the engine populates them **only** for policies
that declare `requires_future_trace = True` — the explicitly labelled
oracle-like references. Ordinary policies (native, retention-native, candidate
v0, diagnostics) always receive `None` for both fields, enforced in
`_decision_context`, so future trace information cannot reach an ordinary
decision even by accident. A recording-policy regression test asserts this for
every ordinary arm, and a second test asserts that supplying or withholding the
future index does not change any ordinary decision.

All arms share the same allocation and bookkeeping path; the only differences
are the victim-selection key and the retention switch.

---

## 7. Simulator-only measurements of runtime gaps (RC-B)

Every decision records `(block_id, depth, lru_rank, band_id, band_pos, tier,
required, |eligible|)`, which yields the first in-project statistics of the
`(depth, native_lru_rank)` correspondence:

```text
rank correlation of depth vs lru_rank within bands
share of decisions where native evicts a shallow block first   <- the RC-B
                                                                    signal
non-trivial window share (|eligible| > required)
victim-set divergence rates (A2 != A0, A3 != A1)
```

These quantities are `NOT_OBSERVABLE` at runtime (P5). Simulation output is
therefore **not** runtime evidence; it is a prior for "worth verifying if the
interface is extended".

---

## 8. Determinism, reproducibility, failure attribution

- One seeded `random.Random` (per-draw seed) is used only by the workload
  generator; the simulation itself contains no randomness.
- The event heap is `(timestamp, seq)`; all iteration orders are deterministic;
  no wall clock and no threads.
- Identical `(trace hash, config hash, code version)` reproduces byte-identical
  results; the campaign records seed, schema version and per-trace SHA-256.
- Failure attribution table (mechanism-chain diagnostics):

| Observation | Attribution | Simulator detection |
| --- | --- | --- |
| L1 fails (victim sets never diverge) | not triggered (no non-trivial window / A1 false) | `nontrivial_share`, `divergence_rate` |
| L1 passes, L3 fails (cache state unchanged) | not implemented (eviction did not remove hashes) | cache-mapping diff |
| L3 passes, L4 fails (recomputation unchanged) | mechanism failed / no benefit | dR distribution |
| effect size tiny | effective but unusable | effect size + CI |

---

## 9. Deviations from real vLLM (published with every result)

| # | Deviation | Direction | Handling |
| --- | --- | --- | --- |
| 1 | requests execute instantaneously; no running period, no preemption, no concurrent execution | simplification | consistent with Phase 2E F1–F5 (`max_concurrent_requests = 1`); F6-style bursts use simultaneous arrivals with serialized admission |
| 2 | no scheduler contention; queue delay degenerates to 0 | conservative (TTL benefit understated) | TTL sensitivity probe quantifies the queue-delay threshold |
| 3 | the last prompt block is never cacheable (frozen cap) | conservative (understates hits) | frozen Phase 2E semantics |
| 4 | band-internal head-first insertion is source-derived (assumption A1) | key assumption | sensitivity arm S1 flips it; D1 ≡ A0 confirms the simulated native direction |
| 5 | no decode phase (`max_new_tokens = 1` regimes) | same as Phase 2E | no decode claims |
| 6 | segments are discrete block-aligned content units | modeling abstraction | generator-enforced; assumptions recorded in the trace |
| 7 | no TTFT / TPOT / throughput | **NOT_MEASURED** | token metrics are not latency proxies (Phase 2E lesson) |
| 8 | PrefillReload is a TTL input only, not a time cost | — | costs are token/block counts throughout |

---

## 10. Scale and performance

- 7 families x 10 draws = **70 independent scenario draws** (statistical unit).
- Per draw per arm: ~20–150 requests, capacity 27–248 blocks, decisions scan
  the queue in O(queue length).
- Full campaign (8 arms plus probes): ~75 s on one CPU core; the exact figure
  is recorded in `campaign.json` (`campaign.elapsed_seconds`).
