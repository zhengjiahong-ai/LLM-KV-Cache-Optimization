# Phase 2A M4 — Logical Pressure-Release Interface Specification

Status: **SPEC APPROVED / runtime implementation DEFERRED** (M1 ruling item 5, 2026-10-07)
Owner: M4 (spec), M1 (freeze)
Scope: specification only — no implementation, no runtime changes

---

## 0. Why this is not an `EvictionPolicyAdapter` extension

My first request proposed exposing the per-candidate decision-time fields (already
collected in `FORCED_RELEASE_DECISION`) on `EvictionCandidate`. **M1 rejected that**
and the reasoning is worth stating, because it is the reason this document exists:

```text
FORCED_RELEASE_DECISION candidate = logical (program, prefix) retention entry
EvictionPolicyAdapter candidate    = native physical KV block
```

These are **two different layers**. The real path is:

```text
RetentionAwareSelectionCoordinator
    -> choose a logical entry to unprotect
    -> newly eligible blocks appear
    -> RetentionAwareLRUAdapter / EvictionPolicyAdapter
    -> choose a physical block
```

Attaching `deadline` / `prefill_reload` / `next_tool_type` to `EvictionCandidate`
would re-merge *logical forced release* with *physical block victim selection* —
the exact conflation the project's frozen rules forbid. So:

```text
interface SPEC          = APPROVED
runtime implementation  = DEFERRED
```

⇒ H1 should design a **logical pressure-release policy boundary**, not extend
`EvictionPolicyAdapter`.

---

## 1. Current boundary (as it exists in `main`)

In `src/kvopt/continuum/pressure.py`:

```python
RetentionAwareSelectionCoordinator.prepare(
    candidates,              # native free-queue blocks
    retention_entries,       # RetentionEntrySnapshot per (program, prefix)
    *, required_blocks, timestamp,
) -> EligibilityPreparation
```

The release loop is:

```python
while len(tier_1_ids | tier_2_ids) < target:
    ranked_releases = sorted(candidates_for_release,
                             key=lambda item: self._release_sort_key(...))
    key, _entry = ranked_releases[0]
    released_keys.add(key)                  # release exactly one entry
    pressure_releases.append(PressureReleaseEffect(key, newly_eligible))
```

and the frozen ordering is:

```text
_release_sort_key = (deadline, min native rank over NEWLY ELIGIBLE, identity)
```

**The one-at-a-time re-evaluation is essential**: the middle term is recomputed
against the *current* released set, which is why no static candidate key can
express the frozen ordering (documented in `rules.py` and `replay.py`).

### 1.1 Available inputs today

`RetentionEntrySnapshot` already carries:

| Field | Source | Already collected? |
| --- | --- | --- |
| `program_id`, `prefix_id` | identity | ✅ |
| `deadline_timestamp` | `TTLDecision` | ✅ |
| `ttl_seconds`, `mode`, `reason` | `TTLDecision` | ✅ |
| `protected` | retention state | ✅ |
| `waiting_followup` | retention state | ✅ |
| `block_ids` | retention state | ✅ |

`TTLInput` already carries: `next_tool_type`, `prefill_reload_seconds`, `eta`,
`queue_delay_t_seconds`, `global_server_gap_samples_seconds`,
`tool_server_gap_samples_seconds`.

⇒ **Every field the nine M0–M3 rules read is already collected.** This matches the
report's §10.1 finding: the entry-level family needs **zero new observations**.
Only a *boundary* is missing, not a *measurement*.

---

## 2. Proposed boundary

### 2.1 Candidate

```python
@dataclass(frozen=True, slots=True)
class PressureReleaseCandidate:
    """One protected entry that could be released, with decision-time facts."""

    entry_key: RetentionEntryKey          # (program_id, prefix_id)

    # --- identity / retention state (already available) ---
    deadline_timestamp: float
    ttl_seconds: float
    waiting_followup: bool

    # --- cost / lifetime facts (already available) ---
    prefill_reload_seconds: float
    block_count: int

    # --- lifecycle signal (already available) ---
    next_tool_type: str | None

    # --- derived decision-time facts ---
    elapsed_since_ttl_decision_seconds: float
    current_marginal_reclaimable_blocks: int
    """Blocks this entry would make eligible *now*, given the current released
    set. Marginal, not absolute: it changes as other entries are released."""

    decision_time_native_lru_summary: int
    """min native LRU rank over the blocks this entry would newly make eligible,
    matching the frozen key's middle term. A summary is deliberate: exposing the
    full block->rank map here would leak block-level structure into a logical
    decision."""
```

### 2.2 Context

```python
@dataclass(frozen=True, slots=True)
class PressureReleaseContext:
    required_blocks: int
    timestamp: float
    current_released_set: frozenset[RetentionEntryKey]
    current_eligible_count: int
    """Eligible blocks now. The policy releases until this reaches
    min(required_blocks, candidate_count) — the same target the frozen loop uses."""
```

### 2.3 Policy protocol

```python
class PressureReleasePolicy(Protocol):
    def select_next(
        self,
        candidates: Sequence[PressureReleaseCandidate],
        context: PressureReleaseContext,
    ) -> RetentionEntryKey:
        """Return the next entry to unprotect.

        MUST return a key present in ``candidates``. MUST be a pure function of
        its arguments: no clock, no global state, no mutation.
        """
```

Deliberately **not** specified: a full ordering. The frozen loop releases one
entry and re-derives state, so a policy that returns a whole ordering would have
to re-implement that re-derivation — a divergence risk. `select_next` keeps the
policy inside the loop where the marginal quantity is always current.

---

## 3. Invariants the seam must preserve

| Invariant | Reason |
| --- | --- |
| **Native BlockPool ownership unchanged** | Frozen; the release loop only *unprotects*, native cleanup stays native |
| **Continuum baseline default unchanged** | With no cost-aware policy selected, behaviour must be byte-identical |
| **No Cost-Aware code in `src/kvopt/continuum/**`** | That package is the frozen baseline |
| **Policy returns a key, never a block** | Keeps the two layers separate (§0) |
| **Policy cannot mutate `released_keys`** | The coordinator owns loop state |
| **Returned key must be in `candidates`** | Otherwise the loop could silently stall or release an ineligible entry |
| **`ref_cnt` never touched** | Freeze §6 |
| **No future-derived field crosses the seam** | No oracle, regret, `future_reused`, `optimal_victim`, return time |
| **Missing input ⇒ frozen baseline ordering** | Never fabricate a value; see `docs/phase2a-m4-missingness-semantics.md` |

### 3.1 One subtlety: the marginal term and the layer discipline

`current_marginal_reclaimable_blocks` and `decision_time_native_lru_summary` are
**derived** quantities. They are legitimate at this layer because:

- they describe a **logical entry's** effect on eligibility, which is the
  coordinator's own concept;
- they read only current native rank + the current released set, both already
  available to the coordinator;
- they are **summaries**, not block identities, so the logical decision cannot
  degrade into a hidden physical-block decision.

If M1 prefers, `decision_time_native_lru_summary` can be dropped from v1: the
frozen key's middle term only breaks ties *within* equal deadlines, and deadlines
are tied in **0 of 60** discovery decisions. Dropping it would make the seam
strictly smaller at the cost of not being able to reproduce the frozen key
exactly as a `PressureReleasePolicy` — which matters for the **fidelity check**
(§5), so v1 keeps it.

---

## 4. Staging

```text
Stage 0  (now)        SPEC only. No code.                                <- this doc
Stage 1  (after a PROXY_CANDIDATE)
                      shadow-only / read-only seam: the policy runs and its
                      decision is LOGGED, never applied. Fidelity checked by
                      re-deriving the frozen ordering through the seam.
Stage 2  (after M1 authorizes)
                      the seam becomes selectable; baseline remains the default.
Stage 3  (block-level)
                      only if H2 returns four PASSes; then, and separately,
                      discuss block -> owner / position / content identity for
                      a block-level EvictionPolicyAdapter.
```

**Do not merge the two layers ahead of Stage 3.**

---

## 5. Fidelity requirement for Stage 1

The seam must be able to reproduce the frozen baseline exactly. Concretely: a
`PressureReleasePolicy` expressing the frozen key

```text
(deadline, min native rank over newly eligible, identity)
```

must reproduce the canonical release sequence on the discovery campaign. The
existing replay engine already establishes that this exact ordering matches the
frozen loop in **60/60** decisions
(`tests/test_costaware_replay.py`, `validate_replay_fidelity`). Stage 1 should
reuse that discipline rather than invent a second fidelity check.

---

## 6. What is explicitly out of scope

| Out of scope | Note |
| --- | --- |
| Any runtime implementation | Deferred to after a `PROXY_CANDIDATE` |
| Changes to `EvictionCandidate` / `EvictionContext` | Rejected by M1 (item 5) |
| `block -> owner` / block position / block content identity | Block-level concerns; H2/B1 only |
| Any change to `TTLDecision` or the TTL estimator | That is the frozen baseline's own logic |
| Multi-owner block weighting | Would need `block -> owners`; a B4 concern |

---

## 7. Traceability

| Statement | Source |
| --- | --- |
| Direct entry fields on `EvictionCandidate` NOT approved | M1 ruling, item 5 |
| Logical pressure-release interface SPEC APPROVED | M1 ruling, item 5 |
| Runtime interface implementation DEFERRED | M1 ruling, item 5 |
| Stage 1 shadow-only/read-only after a `PROXY_CANDIDATE` | M1 ruling, item 5 |
| Do not merge the two layers ahead of block-level work | M1 ruling, item 5 |
| Preserve native BlockPool ownership; no Cost-Aware in continuum | `docs/baseline-freeze.md`, M1 ruling |
| Entry-level family needs zero new observations | report §10.1 |
| Frozen ordering and its dynamic middle term | `src/kvopt/continuum/pressure.py::_release_sort_key`, `replay.py::ExecutedP1BStrategy` |
| Available inputs today | `RetentionEntrySnapshot`, `TTLInput`, `TTLDecision` |
| Missing input ⇒ frozen baseline ordering | `docs/phase2a-m4-missingness-semantics.md` |
| Deadlines tied in 0 of 60 decisions | `docs/phase2a-m4-h1-r1-preregistration.md` §2.1 |
| Fidelity discipline | `tests/test_costaware_replay.py` |
