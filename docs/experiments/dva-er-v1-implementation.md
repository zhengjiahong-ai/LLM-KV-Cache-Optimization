# DVA-ER v1 Implementation and CPU Gate

**Status:** CPU implementation complete; DVA-ER remains `PROVISIONAL_NOT_FROZEN`. No GPU, Native smoke, trace acquisition, Protocol v4, Cohort or Archive change.

**Code:** `src/kvopt/costaware/dva_er.py`  
**Tests:** `tests/test_dva_er.py`  
**Protocol family contract:** `configs/phase5/phase5-cost-aware-candidate-v1.json`

---

## 1. Scope

DVA-ER v1 changes only the Entry Release choice on the Continuum Adapted/A0 foundation. It does not change:

- Native scheduler, BlockPool, APC/LRU or physical-eviction ownership;
- A1/A3 implementations;
- Protocol v4, historical Cohort or Phase 3/4 archives;
- the A0 tie-break itself.

The implementation is CPU-only and deterministic.

## 2. Data flow

```text
decision boundary
  ├─ legal Entry candidates
  ├─ complete Native BlockPool records
  │    block_id, has_hash, refcount, native_lru_rank, owners, protected_owners
  ├─ complete FreeKVCacheBlockQueue order
  ├─ one FollowupObservation per candidate
  │    chain_id, active, pending_tool_gap_seconds (only if active)
  └─ explicit A0 candidate order (tie-break only)
            ↓
     DVAERDecisionInput
            ↓
  NativePoolSnapshot.victim_sequence_after(candidate, required_blocks)
            ↓
  full Native LRU eligible sequence + victim prefix + shortfall
            ↓
  DVAERStrategy.choose()
       loss = count(victim blocks belonging to an active follow-up chain with gap <= H)
       select min(loss); on loss tie, select by A0 order
            ↓
     DVAERDecision (selection, per-candidate losses, victim sequences)
```

`build_decision_input()` adapts a `DecisionSnapshot`-shaped object (the existing replay boundary) together with the explicitly supplied complete block records, follow-ups and A0 order. Missing records fail closed.

## 3. Native LRU victim simulation

For each legal candidate `X`:

1. start from the observed full block table;
2. if `X` is a protected owner of a block, decrement that block's refcount once and remove `X` from `protected_owners`;
3. a block is Native-eligible iff `refcount == 0` and either it is unhashed or no protected owner remains;
4. sort all eligible blocks by `native_lru_rank`;
5. retain the **full eligible sequence** for audit;
6. compute `deficit = max(0, required_blocks - current_eligible_count)`;
7. the first `deficit` blocks are the victim prefix; a shortfall is explicit, never filled with a zero or an invented block.

The full sequence is retained in `VictimSequence.full_eligible_sequence`; `victim_block_ids` is only the prefix the pressure target would consume.

## 4. Score and tie-break

For each candidate, for each victim block, the policy checks the block's logical owners excluding the released candidate. A victim block contributes 1 iff at least one remaining owner has a `FollowupObservation` that is:

- active; and
- has an observable `pending_tool_gap_seconds <= H`.

`loss(X) = number of such victim blocks`.

`H = 60s`; sensitivity parameters are 30s and 120s. The policy never reads future Turn content or future reuse outcomes; the pending gap is the already-armed controller timer/next-arrival state.

Tie-break order:

```text
(loss, a0_rank, candidate_key)
```

`a0_order` is explicitly supplied and must contain exactly the legal candidate set. Tie-break reproduction is tested separately.

## 5. Fail-closed evidence

`DVAEREvidenceError` is raised when any required evidence is missing or inconsistent, including:

- no legal candidate;
- duplicate candidate/block/rank identities;
- unknown block owner;
- incomplete/duplicate free queue;
- free-queue blocks that do not exactly match refcount-zero blocks;
- refcount below the protected-owner count;
- missing follow-up observation for a candidate;
- active follow-up without an observable pending gap;
- inactive follow-up carrying a gap;
- A0 order missing a candidate or containing duplicates;
- H mismatch between strategy and decision input;
- a release that would make refcount negative.

No zero-value substitution or silent A0 fallback is performed. A tie is resolved by the explicit A0 order; a tie is not an evidence failure.

## 6. A0/A1/A3 boundary

| System | Boundary |
|---|---|
| **A0** | Supplied only as the explicit candidate tie-break order. DVA-ER does not change A0's release logic or Native physical eviction. |
| **A1** | A1's cost/reuse-probability score is not imported or called. DVA-ER does not reuse A1's branch ladder. The source-boundary test asserts no `from .a1_entry` import. |
| **A3** | A3's suffix score is not imported or called. DVA-ER does not reuse A3's victim prediction. The source-boundary test asserts no `from .a3_suffix` import. |

The three candidates are independent comparison objects under the Phase 5 protocol; DVA-ER's mechanism is the full victim sequence, not a re-ranking of A1/A3 scores.

## 7. CPU gate

The gate is correctness-only. Historical Phase 3/4 full-trajectory gain is not a pass condition.

| Gate check | Test |
|---|---|
| multiple legal candidates can change selection | `test_multiple_legal_candidates_can_change_selection` |
| same Entry order, different victim risk | `test_same_entry_order_can_have_different_victim_risk` |
| different candidates produce different victim sets | `test_different_candidates_have_different_victim_sets` |
| full Native LRU order | `test_native_lru_sequence_is_ordered_and_full` |
| shortfall explicit, not imputed | `test_shortfall_is_explicit_not_imputed` |
| A0 tie-break reproduced | `test_a0_tie_break_is_reproduced` |
| H sensitivity | `test_h_sensitivity_changes_weight` |
| missing follow-up fails closed | `test_missing_followup_fails_closed` |
| active gap missing fails closed | `test_missing_active_gap_fails_closed` |
| incomplete free queue fails closed | `test_incomplete_free_queue_fails_closed` |
| missing A0 order fails closed | `test_missing_a0_order_fails_closed` |
| unknown owner fails closed | `test_unknown_owner_fails_closed` |
| deterministic selection | `test_deterministic_selection` |
| replay snapshot adapter | `test_decision_input_adapter` |
| replay strategy adapter | `test_replay_strategy_adapter_uses_evidence_provider` |
| A1/A3 import boundary | `test_a1_a3_are_not_imported_by_dva_er` |
| released candidate not counted as own risk | `test_released_candidate_does_not_count_as_its_own_downstream_risk` |
| refcount/protection eligibility | `test_refcount_and_protection_control_victim_eligibility` |
| hashed/unprotected eligibility | `test_hashed_and_unprotected_block_is_eligible_without_release` |

Run:

```text
python -m pytest tests/test_dva_er.py -q -p no:cacheprovider
```

Result at this implementation commit: **19 passed**.

## 8. What is not claimed

- This is not a GPU or Native conformance result.
- It does not establish recomputation-token benefit, serving benefit or physical causality.
- It does not freeze DVA-ER; M1 must accept the CPU gate and hash the implementation.
- It does not modify A0/A1/A3, the Phase 5 protocol, the historical Cohort or any Archive.
