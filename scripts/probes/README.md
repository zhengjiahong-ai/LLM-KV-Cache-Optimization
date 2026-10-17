# Joint Cost-Aware design — minimal reproducible probes

Each script here backs a specific number or claim in
[`docs/phase2-cost-aware-joint-design.md`](../../docs/phase2-cost-aware-joint-design.md).
They are deliberately small: no framework, no dataset, no plotting.

## Self-contained (no artifacts needed)

These run on any machine with Python 3.10+ and assert their own results, so a
failure means the document and the code have drifted apart.

| Script | Backs | Run |
|---|---|---|
| `probe_example_entry_release.py` | §5.1 numbers, incl. the break-even `lambda > 0.2666` | `python scripts/probes/probe_example_entry_release.py` |
| `probe_example_block_eviction.py` | §5.2 numbers for the new rule, the withdrawn WRR and native LRU in both regimes | `python scripts/probes/probe_example_block_eviction.py` |
| `probe_metric_semantics.py` | §3.5.1 subadditivity (not concavity) and §3.5.2 token-metric linearity | `python scripts/probes/probe_metric_semantics.py` |
| `probe_replay_capability.py` | §6.4.1 — the replay layer records no evicted block set and no depth | `PYTHONPATH=src python scripts/probes/probe_replay_capability.py` |

`probe_example_block_eviction.py` also asserts that the **withdrawn** share-ascending
key would have selected the opposite entry, so the RC2 erratum stays checkable.

## Needs H1 artifacts (data is not committed)

These two scripts produce the H1 evidence range limits quoted in the joint design
document. They need the formal Level-A run artifacts, which are too large to commit.
Point them at the artifacts root, either positionally or via `KVOPT_H1_RUNS`:

```bash
export KVOPT_H1_RUNS=/path/to/phase2a-h1-formal-level-a-runs-v1
python scripts/probes/h1_entry_block_overlap.py
python scripts/probes/h1_lru_monotonicity.py
```

| Script | Backs |
|---|---|
| `h1_entry_block_overlap.py` | 0/81 decisions with two entries sharing a block; 0/81 discontinuous or overlapping entry bands; `hash_num_tokens` present in 903 snapshots with 10 distinct values |
| `h1_lru_monotonicity.py` | 294/294 chain windows with `rho == -1`, i.e. native LRU already evicts deepest-first inside a chain |

Expected output for the currently committed documents, on the same artifact set:

```text
h1_entry_block_overlap.py
  decisions with >=2 entries           : 81
  decisions with ANY overlap           : 0  = 0.0%
  all bands contiguous                 : 81 = 100.0%
  bands pairwise disjoint              : 81 = 100.0%
  snapshots carrying hash_num_tokens   : 903
  distinct hash_num_tokens values      : 10  min 16  median 112  max 512

h1_lru_monotonicity.py
  decisions                                     : 87
  ordering-relevant decisions (required<queue)  : 54
  windows measured (>=3 comparable blocks)      : 294
  exactly -1.0000 : 294
  exactly +1.0000 : 0
```

Pass `--strict` to turn those printed figures into assertions. Without the flag the
scripts only print, so they can be pointed at a different artifact set without
failing; with it, any drift from the quoted numbers fails loudly.

## Why these two are still load-bearing

The joint design document uses them for exactly two narrow claims, both scoped to
H1 plus the frozen four-field interface:

1. entry-level's only distinctive signal (shared ownership) does not occur in H1;
2. inside a chain, `native_lru_rank` already orders blocks deepest-first.

Neither is used to argue that block-level optimisation has no headroom in general.
That inference was explicitly withdrawn — see §1.0 of
`docs/ours-evict-algorithm-design-v1.md`.
