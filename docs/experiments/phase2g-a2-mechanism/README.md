# Phase 2G · A2 Block-level Mechanism Study (rev.2)

**Scope: bounded offline mechanism study. No native policy, no new experiment.**
All numbers are selection-level; nothing here is a measured cache benefit.

This revision responds to M1's four corrections and **retracts two claims** from
rev.1, both of which came from the same mistake.

---

## 0. What changed and why

| M1 correction | rev.1 state | rev.2 |
|---|---|---|
| Native LRU rank ≠ prefix depth | depth read from candidate `block_ids` order, justified by rank monotonicity | depth read from **content position in `VLLM_PREFIX_SNAPSHOT`**; rank used only as recency |
| A block can belong to several chains | mapped each block to exactly one chain, and later *rejected* multi-chain blocks outright | every membership is kept; `Delta(b)` is summed **once per chain containing `b`** (PR #50 §3.4.5) |
| Entry gains ≠ block gains | entry release replayed, but conclusion stated loosely | entry release held fixed via the frozen replay; only the block choice varies |
| Must compare on the same legal set | legal set came from the frozen release, but the shared-chain defect could distort it | same set for both rules, and the loss is scored by one shared function |

**Two retractions.** rev.1 reported `294/294` chain windows as "native already
evicts deepest-first, therefore no depth decision" and concluded that block-level
space was structurally absent. Both were artefacts of using candidate
`block_ids` order as depth. Measured against true content depth the figure is
**183/216 (84.7%)**, not 100% — so depth headroom *does* exist. rev.1's
"`0 / 39`" gate number and the "no headroom" wording are withdrawn.

---

## 1. RQ1 — Is there a real block-level selection space?

Measured on the only corpus available locally. **The Gate 2 artifact root is not
present on this machine**, so this is *not* yet the new workload; see §5.

```text
decisions                                      120
  scorable (full content geometry)              87
  with an observation gap                       33
  with real freedom (need < legal blocks)       75
  multi-chain                                   45
  shared physical blocks observed                0

chain windows (>=3 hash-carrying legal blocks) 216
  native already deepest-first                 183  = 84.7%
  depth INVERTED (shallower colder)             12  =  5.6%   <-- headroom
  non-monotone                                  21  =  9.7%   <-- headroom

VICTIM SET differs                             0 / 120
  among scorable                                 0 / 87
  among scorable with real freedom               0 / 75
expected-loss delta                             exactly 0 in all 120
```

So the corpus *does* contain depth headroom (33 of 216 windows), and it is inside a
chain that the demand actually reaches in **9 decisions**. But:

```text
decisions with a reachable depth inversion         9
  of which scorable                                0     <-- every one is unscorable
```

**This is the answer to RQ1.** Ordering differs in 33 decisions and the victim set
never does, for two separate and measurable reasons:

1. in every decision we can score, the chains native actually drains are already
   depth-ordered, so native is optimal exactly where it is forced to act;
2. the 9 decisions where an inverted chain is reached are precisely the ones whose
   content identity is missing, so they cannot be scored either way.

Reporting only the first would repeat rev.1's error. The correct statement is that
**the headroom exists but coincides with the observation gap**.

---

## 2. RQ2 — Can the difference be explained by decision-time cost information?

| Signal | Reconstructible? | Source |
|---|---|---|
| block content identity | **partially** | `VLLM_PREFIX_SNAPSHOT.ordered_native_hashes`, position-aligned with `block_ids` |
| true prefix depth | **partially** | position in that same snapshot; **never** derived from rank |
| shared-chain membership | yes | a block id appearing in several chain snapshots keeps all of them |
| `q_c` per chain | yes | `retention_deadline_timestamp` → same sigmoid as A1 |
| marginal loss `Delta(b)` | derives from the above | PR #50 §3.4 |
| `q` order vs rank order | yes, where scorable | 45 comparable: 33 agree, 12 disagree |

`q`-order disagrees with rank-order in 12 of 45 comparable decisions, but **all 12
are unscorable**, so they cannot contribute a measured difference. Where both
signals are available, they agree, and the two rules make the same choice.

The one thing that must not be substituted is rank-as-depth. Doing so was rev.1's
defect and it inverted the sign of the finding.

---

## 3. RQ3 — Should A2 enter a minimal native implementation?

**Not yet, and the blocker is a specific observation gap, not a judgement about
block-level value.**

### 3.1 The gap

`FORCED_RELEASE_DECISION.original_free_queue` rows carry only:

```text
block_id, native_lru_rank, has_block_hash, eligibility_tier
```

There is **no content hash** for a legal candidate block. Neither this branch nor
the Gate 2 branch adds one (verified: `experiment_events.py` is unchanged between
`main` and `feature/phase2g-m6-a1-native-gate2`).

Consequences:

- 735 hash-carrying legal blocks across 33 decisions have no membership at all, so
  `Delta(b)` is undefined for them;
- `block_id` cannot substitute, because block ids are recycled — a snapshot's
  `block_ids` describe the physical blocks of a *live* request, and a free-queue
  block's id may since have been reassigned. Using it would be exactly the
  "silently overwrite an owner" failure M1 warned about.

### 3.2 Minimum interface change for an A2 native opt-in

Per candidate block, expose one of:

```text
(a) content_hash + depth + the owning chain ids   -- enough to compute Delta
(b) the precomputed (chain_id -> marginal loss)   -- enough to rank, no content exposed
```

Everything else already exists: legal candidate set, `required_blocks`, block size,
and constancy of ownership. No change to eviction, ref-counting, hashing or LRU is
needed. Inside the engine this is derivable (a block's position in the request
prefix), so it is an **exposure gap**, not a missing-information gap.

### 3.3 Gate before any A2 native work

```text
share of decisions where
  (a) every hash-carrying legal block has reconstructible content + depth, AND
  (b) a depth-inverted or non-monotone chain is actually touched, AND
  (c) q-order disagrees with rank-order
must be > 0
```

Current measurement on the available corpus: condition (b) holds in 9 decisions,
of which **0** satisfy (a). The gate is therefore `0 / 120`.

---

## 4. Controlled scenarios (what the gate would look like when satisfied)

The corpus cannot exercise divergence, so four hand-built geometries pin the
machinery. Each is scored by the same loss function for both rules.

| Scenario | Native | Cost-aware | Set differs | Expected loss |
|---|---|---|---|---|
| depth inverted, forced to touch | shallowest first | deepest first | **yes** | 4.0 → **2.0** |
| depth ordered | deepest first | deepest first | no | equal |
| need equals legal count | any order | any order | **no** | equal |
| shared block vs private block | rank order | cheaper private first | yes | lower |

The first row is the decisive one: an inverted chain gives a genuine victim-set
difference and halves the expected loss. The third row is the trap — a decision
that must evict the whole legal set cannot differ regardless of rule, so counting
such decisions as "no divergence" would be vacuous.

All are asserted in `tests/test_costaware_a2_geometry.py`.

---

## 5. What is still missing

**The Gate 2 artifact root.** RQ1–RQ3 must be re-run on the 144-run Gate 2 evidence
to answer M1's actual question about the new workload. This machine does not have
`artifacts/`, and it is excluded from version control, so the new-corpus answer is
currently `NOT_COMPUTABLE` rather than answered.

What that re-run needs: the campaign manifest and the run root. No native execution
is implied. The driver already accepts any artifact root:

```bash
PYTHONPATH=src python -m kvopt.costaware.a2_compare \
    --corpus <gate2-artifact-root> --json a2_gate2.json
```

Expected change on the new corpus: A1's 13 selection-divergence scenarios imply
entries are released in different orders there, so chain ownership patterns differ
from this corpus. Whether a depth-inverted chain is *touched* is exactly what the
run will report.

---

## 6. Documents this supersedes

- `docs/experiments/phase2g-a2/README.md` rev.1 — its `294/294`, `0/39` and
  "no decision space" statements are withdrawn as described in §0.
  This file replaces it.

## 7. Reproduce

```bash
# geometry and evidence tests (no artifacts needed)
python -m pytest tests/test_costaware_a2_geometry.py tests/test_costaware_a2_evidence.py -q

# real-corpus study
PYTHONPATH=src python -m kvopt.costaware.a2_compare --corpus <artifact-root> --json a2.json
```
