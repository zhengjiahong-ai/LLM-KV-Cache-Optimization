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
  │    chain_id, active, pending_tool_gap_seconds
  │    observation_timestamp, chain_established_timestamp, gap source
  └─ explicit A0 candidate order (tie-break only)
            ↓
     DVAERDecisionInput
            ↓
  NativePoolSnapshot.victim_sequence_after(candidate, required_blocks)
            ↓
  Tier 1 eligible + Tier 2 newly eligible + physical victim prefix + shortfall
            ↓
  DVAERStrategy.choose()
       loss = count(physical victims belonging to an active follow-up chain with gap <= H)
       select min(loss); on loss tie, select by A0 order
            ↓
     DVAERDecision (selection, per-candidate losses, victim sequences)
```

`build_decision_input()` adapts a `DecisionSnapshot`-shaped object (the existing replay boundary) together with the explicitly supplied complete block records, follow-ups and A0 order. Missing records fail closed.

## 3. Native refcount, protection and victim simulation

`refcount` is the observed Native refcount. Retention Protection is an
independent owner set. A cache block may have `refcount=0` and still be
protected; releasing a candidate removes only its protection, and **never**
changes Native refcount, block hash or free-queue membership.

For each legal candidate `X`:

1. start from the observed full block table and the complete free queue;
2. remove only `X` from `protected_owners`; refcount is unchanged;
3. Tier 1 = blocks already eligible before release: `refcount == 0` and either
   unhashed or no protected owner;
4. Tier 2 = blocks that become eligible after the protection release;
5. order Tier 1 by Native LRU rank, then Tier 2 by Native LRU rank;
6. actual physical victims = the first `min(required_blocks, eligible_count)` of
   that `(Tier 1, Tier 2)` order, matching `EligibilityPreparation` and
   `RetentionAwareLRUAdapter`;
7. retain separately:
   - `original_eligible_block_ids` (Tier 1);
   - `newly_eligible_block_ids` (Tier 2);
   - `virtual_eligible_order` (Tier 1 then Tier 2);
   - `physical_victim_block_ids` (actual prefix);
   - `full_free_queue_order` (observed Native queue order);
   - explicit `shortfall` (never zero-filled).

The free queue must satisfy `free_queue_order[i].native_lru_rank == i`; any
mismatch fails closed. `VictimSequence.victim_block_ids` remains a compatibility
alias for the physical victim prefix.

## 4. Score and tie-break

For each candidate, for each **actual physical victim block**, the policy checks the block's logical owners excluding the released candidate. A victim block contributes 1 iff at least one remaining owner has a `FollowupObservation` that is:

- active; and
- has an observable `pending_tool_gap_seconds <= H`.

`loss(X) = number of such victim blocks`.

`H = 60s`; sensitivity parameters are 30s and 120s. The policy never reads future Turn content or future reuse outcomes. The pending gap must come from `FollowupGapSource.CONTROLLER_ARMED_TIMER`; its observation timestamp and chain-establishment timestamp must both be no later than the decision timestamp. Block owner → candidate → follow-up chain identity is therefore bound through the explicit observation map; no trace arrival is used. Chain identity must already be known from the controller/Program/Turn context; DVA-ER does not infer Session identity from future trace events or unsupported fields. If the Session/chain identity is not identifiable, the observation is incomplete and fails closed.

Tie-break order:

```text
(loss, a0_rank, candidate_key)
```

`a0_order` is explicitly supplied and must contain exactly the legal candidate set. The CPU gate also derives this order from the existing frozen `ExecutedP1BStrategy` and compares DVA-ER's tie result. A separate end-to-end fixture builds a real `EligibilityPreparation` and `RetentionAwareLRUAdapter` and asserts that DVA-ER's predicted physical victim prefix equals the adapter's actual selection.

## 5. Fail-closed evidence

`DVAEREvidenceError` is raised when any required evidence is missing or inconsistent, including:

- no legal candidate;
- duplicate candidate/block/rank identities;
- unknown block owner;
- incomplete/duplicate free queue;
- free-queue blocks that do not exactly match refcount-zero blocks;
- free-queue position not equal to `native_lru_rank`;
- missing follow-up observation for a candidate;
- active follow-up without an observable pending gap or without the controller-armed source;
- inactive follow-up carrying a gap/source;
- observation or chain establishment after the decision;
- A0 order missing a candidate or containing duplicates;
- H mismatch between strategy and decision input.

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
| DVA vs A0 changes physical victim set | `test_dva_selection_changes_physical_victim_set_vs_a0` |
| no future fields in input contract | `test_future_fields_are_not_in_the_input_contract` |
| full Native LRU order | `test_native_lru_sequence_is_ordered_and_full` |
| shortfall explicit, not imputed | `test_shortfall_is_explicit_not_imputed` |
| A0 tie-break reproduced | `test_a0_tie_break_is_reproduced` |
| A0 ordering from frozen strategy | `test_a0_tie_break_uses_frozen_a0_strategy` |
| end-to-end A0 eligibility/adapter equality | `test_prediction_matches_real_a0_eligibility_and_adapter` |
| H sensitivity | `test_h_sensitivity_changes_weight` |
| missing follow-up fails closed | `test_missing_followup_fails_closed` |
| active gap missing fails closed | `test_missing_active_gap_fails_closed` |
| observation after decision fails closed | `test_observation_after_decision_fails_closed` |
| chain established after decision fails closed | `test_chain_established_after_decision_fails_closed` |
| future trace-arrival source rejected | `test_future_arrival_source_is_rejected` |
| incomplete free queue fails closed | `test_incomplete_free_queue_fails_closed` |
| free-queue rank mismatch fails closed | `test_free_queue_position_must_equal_native_lru_rank` |
| missing A0 order fails closed | `test_missing_a0_order_fails_closed` |
| unknown owner fails closed | `test_unknown_owner_fails_closed` |
| deterministic selection | `test_deterministic_selection` |
| replay snapshot adapter | `test_decision_input_adapter` |
| replay strategy adapter | `test_replay_strategy_adapter_uses_evidence_provider` |
| A1/A3 import boundary | `test_a1_a3_are_not_imported_by_dva_er` |
| released candidate not counted as own risk | `test_released_candidate_does_not_count_as_its_own_downstream_risk` |
| refcount=0 + protected owner separate | `test_refcount_zero_with_protected_owner_is_eligible_only_after_release` |
| hashed/unprotected eligibility | `test_hashed_and_unprotected_block_is_eligible_without_release` |

Run:

```text
python -m pytest tests/test_dva_er.py -q -p no:cacheprovider
```

Result at this implementation commit: **27 passed**.

## 8. What is not claimed

- This is not a GPU or Native conformance result.
- It does not establish recomputation-token benefit, serving benefit or physical causality.
- It does not freeze DVA-ER; M1 must accept the CPU gate and hash the implementation.
- It does not modify A0/A1/A3, the Phase 5 protocol, the historical Cohort or any Archive.
