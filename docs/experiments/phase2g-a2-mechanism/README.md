# Phase 2G · A2 Block-level Mechanism Study (rev.3)

**Scope: bounded offline mechanism study.** No native policy, no new experiment.
Every number is selection-level.

**Gate 2 status: `NOT_COMPUTABLE` on this machine.** The 144-run archive is not
present, so nothing here is a Gate 2 verdict. The corpus analysed below is labelled
`legacy` and the driver records that label in every report.

---

## 0. What rev.3 corrects

revision | claim | status after rev.3
---|---|---
rev.1 | depth from candidate `block_ids`; `294/294` chains "already deepest-first"; no block-level space | **retracted** (rank is not depth; multi-chain ownership dropped)
rev.2 | depth from snapshot content position; multi-chain marginal loss; 87/120 scorable; "headroom exists (33/216 windows) but coincides with the observation gap" | **the headroom claim is retracted**

rev.2 still joined a *historical snapshot's* ``block_ids`` to a *current free-queue*
``block_id``. Block ids are slots, not content: a slot evicted after the snapshot may
hold different content, and rev.2 kept every chain it had ever seen in a ``current``
map. Under the corrected protocol the headroom disappears entirely — so it was an
artefact of the invalid join, not a real signal hidden behind missing observations.

rc | what was wrong | what rev.3 does
---|---|---
RC1 | memberships from an unverified slot-id join; stale chains retained; hash read *after* the join | per-candidate proof: latest prior snapshot + **ordered** `block_ids` equality + complete payload + no intervening same-process eviction. No proof ⇒ block unknown. No stale carry-over
RC2 | `q_by_chain.setdefault(chain, 0.0)`; `marginal_delta` defaulted a missing weight to 0; `scorable` ignored unknown weights; unverified decisions still produced counted losses | missing weight **raises**; a proved chain without a weight makes the decision unscorable; losses are withheld unless every cost term is known; selections are retained as diagnostics only
RC3 | gate hard-ANDed depth inversion with `q`-vs-rank disagreement; denominators not recomputed; legacy corpus implicitly stood in for Gate 2 | gate is *identified + set differs + lower modelled loss*, with cause **stratified**; every exclusion is counted; corpus label recorded and Gate 2 reported `NOT_COMPUTABLE`

---

## 1. Identity protocol (RC1)

Applied per candidate chain, mirroring
`phase2d_shared_retention._mapping_for_candidate`:

```text
1  latest VLLM_PREFIX_SNAPSHOT for this chain, strictly before the decision
   (never an earlier one, so an invalid later snapshot invalidates the mapping)
2  payload must carry block_ids, ordered_native_hashes,
   ordered_native_cache_keys and a non-empty native_hash_process_id
3  candidate block_ids == snapshot block_ids  as an ORDERED list
4  len(blocks) == len(hashes) == len(cache_keys)
5  no VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED of those block ids, by the same hash
   process, between the snapshot and the decision
```

Failing any step yields a named status — `no_prior_snapshot`,
`snapshot_payload_incomplete`, `candidate_blocks_differ_from_snapshot`,
`block_hash_key_lengths_differ`, `mapped_block_evicted_before_decision` — and **no
membership**. A hash-carrying block without a proof is `content_unverified`; it is
never given a depth borrowed from a slot number.

Regression covered by tests: snapshot(slot X, hash A) → eviction(slot X) → decision
must not be proved, and an invalid later snapshot must not fall back to an older one.

---

## 2. RQ1 — Is there a real block-level selection space?

```text
decisions                                    120
  verified (every candidate identified,
            every priced chain has a weight)   87   = 72.5%
  excluded                                    33   = 27.5%
    content_unverified                        33
    reuse_weight_unknown                       0
  verified with real freedom (need < legal)    75

chain windows (>=3 hash-carrying proved blocks)         183
  native already deepest-first                          183  = 100%
  depth INVERTED                                          0
  non-monotone                                            0

q vs rank                 comparable 39   agrees 39   disagrees 0

victim set differs        verified 0 / 87
expected-loss delta       exactly 0 on every verified decision
```

**Answer: no, not on this corpus.** On every decision whose candidates can be
proven identical, native LRU is already evicting deepest-first inside each chain
(183/183 windows), and the reuse proxy never reorders chains against recency
(39/39 agree). Both rules therefore select the same victim set, and the modelled
loss is identical.

The 33 excluded decisions are **unmeasured, not measured-as-zero**. They are 27.5% of
the corpus, which is why this is not a statement about block-level value in general.

### Why rev.2's "headroom" vanished

| | rev.2 (slot-id join) | rev.3 (proved identity) |
|---|---|---|
| windows | 216 | 183 |
| inverted | 12 | **0** |
| non-monotone | 21 | **0** |
| `q` disagreements | 12 / 45 | **0 / 39** |

The 33 windows that carried the inversion were exactly the windows that the join
fabricated. Rev.2's conclusion — "the headroom exists but coincides with the
observation gap" — described a phantom. The honest statement is narrower: **under
proved identity, no depth headroom is observed at all in the measurable part of this
corpus.**

---

## 3. RQ2 — Can a difference be explained by decision-time cost information?

Everything needed is available *when it can be proved*, and nothing is substituted
when it cannot:

| Signal | Reconstructible | Source |
|---|---|---|
| content identity | **only via proof** | `ordered_native_hashes` position-aligned with `block_ids`, latest prior snapshot |
| true prefix depth | **only via proof** | position in that proved chain; never from rank |
| shared-chain membership | yes | a block id proved in several chains keeps every membership |
| `q_c` | yes, when the candidate carries a deadline | `retention_deadline_timestamp`, same sigmoid as A1 |
| `Delta(b)` | derives from the above | PR #50 §3.4, summed once per chain |
| `q` order vs rank order | only when every chain has a weight | `None` otherwise, rather than treating unknown as cheapest |

Note that the deadline is read from the **event payload**, not from the replay row:
the row fills a missing deadline with `0.0` to keep the frozen release order total,
and that default must not become a reuse weight.

---

## 4. RQ3 — Should A2 enter a minimal native implementation?

**Not on current evidence**, and the blocker is now precisely identified.

### 4.1 The screening gate

```text
qualifies when ALL THREE hold:
  (1) every candidate identified   (proof + weight)
  (2) nontrivial victim-set difference
  (3) lower modelled loss

current: 0 / 87 verified decisions
gate2:    NOT_COMPUTABLE (archive absent)
```

Conditions (1)–(3) are the gate. Depth inversion and `q`-vs-rank disagreement are
*stratified as causes*, not required: a single chain with inverted depth yields a
different victim set with no `q` comparison at all, and requiring both would discard
exactly the case worth finding. The driver reports
`divergence_causes_verified = {depth_inversion, q_reorder, shared_ownership}`.

### 4.2 The interface gap

`FORCED_RELEASE_DECISION.original_free_queue` rows carry only
`block_id, native_lru_rank, has_block_hash, eligibility_tier`. There is no content
hash for a legal candidate, so identity must be reconstructed from prefix snapshots
and 27.5% of decisions cannot be proved. `block_id` cannot substitute: slot reuse is
exactly the failure the proof exists to catch.

Minimum change for an A2 native opt-in — expose one of:

```text
(a) content_hash + depth + owning chain ids   -> enough to compute Delta
(b) precomputed (chain_id -> marginal loss)   -> enough to rank, no content exposed
```

No change to eviction, ref-counting, hashing or LRU is required. Inside the engine
this is derivable (a block's position in the request prefix), so it is an **exposure
gap**, not a missing-information gap.

### 4.3 What would change the answer

Two things, either of which is cheap:

1. **Run the corrected driver on the Gate 2 archive.** It accepts any artifact root
   and needs no native execution:
   ```bash
   PYTHONPATH=src python -m kvopt.costaware.a2_compare \
       --corpus <gate2-artifact-root> --corpus-label gate2 --json a2_gate2.json
   ```
   A1 showed 13 selection-divergence scenarios there, so entry release orders differ
   from this corpus and chain ownership patterns differ with them.
2. **Raise identifiability.** If the Gate 2 archive also fails the identity proof at
   a similar rate, the binding constraint is the missing candidate content hash, and
   exposing it (option (a) above) becomes the prerequisite for *any* A2 verdict —
   including a negative one.

---

## 5. Controlled scenarios

The corpus cannot exercise divergence, so the machinery is pinned by construction.
Two arms, one shared loss function:

| Scenario | Native | Cost-aware | Set differs | Expected loss |
|---|---|---|---|---|
| single chain, depth inverted | shallowest first | deepest first | **yes** | 4.0 → **2.0** |
| single chain, depth ordered | deepest first | deepest first | no | equal |
| `need` equals legal count | any order | any order | **no** | equal |
| shared block vs private block | rank order | cheaper private first | yes | lower |

The first row is the decisive one, and it is also the case RC3 warned would be lost:
one chain, no `q` comparison available, yet a genuine victim-set difference that
halves the modelled loss. The third row is the trap — a decision that must evict the
entire legal set cannot differ under any rule, so counting it as "no divergence"
would be vacuous.

All asserted in `tests/test_costaware_a2_geometry.py` and
`tests/test_costaware_a2_screening.py`.

---

## 6. Reproduce

```bash
# geometry, identity proof, screening gate (no artifacts needed)
python -m pytest tests/test_costaware_a2_geometry.py \
                 tests/test_costaware_a2_evidence.py \
                 tests/test_costaware_a2_screening.py -q

# real-corpus study, labelled so the report cannot be mistaken for Gate 2
PYTHONPATH=src python -m kvopt.costaware.a2_compare \
    --corpus <artifact-root> --corpus-label legacy --json a2.json
```
