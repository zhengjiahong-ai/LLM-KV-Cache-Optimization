# Phase 2G A2 Native Evidence Fidelity Repair

## Scope

This work is a bounded, non-formal repair of the Native evidence supplied to the
frozen A2 selector. It does not modify the A2 cost function, A0 entry release,
Native cache ownership, the sealed Gate 2 v3 campaign, or its outcome.

## Repaired evidence lifecycle

- Native content identity is tracked independently from logical retention lifetime.
- Original chain geometry is retained across partial physical eviction.
- The current contiguous reusable-prefix boundary is recomputed from resident
  content rather than treating a partially evicted chain as wholly present or absent.
- Program completion preserves resident content identity while marking future reuse
  weight unknown; A2 then fails closed to Native LRU.
- Slot reuse replaces the old content proof and cannot inherit stale chain membership.
- Decision events distinguish missing snapshots, sequence mismatch, broken prefixes,
  unknown weights, and legal hashed candidates without membership.

## Native fidelity validation

Six non-formal cases were executed against the real Native runtime. Five passed:

- `COMPLETE_CHAIN`: full content, depth, chain-length, and weight evidence reached A2.
- `PARTIAL_EVICTION`: a 12-block chain retained depths 1–10 and exposed a reusable
  boundary of 10 after trailing physical eviction.
- `PROGRAM_COMPLETION`: resident content remained visible, its weight became unknown,
  and the selector failed closed.
- `SLOT_REUSE`: new content in a recycled physical slot did not inherit old identity.
- `INCOMPLETE_EVIDENCE`: missing or stale chain evidence produced explicit problems
  and Native-LRU fallback.

`SHARED_CONTENT` is `NOT_DEMONSTRATED`: the run did not prove multiple live chain
memberships for one Native block. This is retained as a limitation, not converted to
a pass from logical labels.

Overall fidelity status is therefore `NOT_DEMONSTRATED` (5 PASS, 1
NOT_DEMONSTRATED), even though the individual repaired lifecycle paths above worked.

## Non-formal A0/A2 positive control

The bounded positive control separately evaluates three gates:

- Gate A — Cost Evidence: **PASS**. The decisive A2 event contained 24 verified,
  chain-weighted hashed candidates, no fallback, and no adapter or contract problem.
- Gate B — Selection Intervention: **FAIL**. The A2 selected victim set equaled its
  Native-LRU reference set.
- Gate C — Physical Realization: **NOT_OBSERVABLE**. All 13 selected hashed identities
  were correlated with later same-process, hash-removing physical eviction, but no
  selection divergence existed to realize physically.

The positive-control outcome is `INTERVENTION_NOT_REALIZED`. Cross-process block IDs
and Native hashes are not compared, and physical correlation is not interpreted as
per-block recomputation causality.

## Conclusion

The repair restores decision-time content, chain geometry, partial-prefix, terminal,
slot-reuse, and fail-closed evidence paths. It does not establish shared-block
membership or a distinct Native A2 intervention under the tested positive control.
No A2 effectiveness or recomputation-benefit conclusion follows from this work.
