"""H1 evidence: do candidate entries share blocks, and is depth reconstructible?

Backs the two H1 range statements used by the joint design document:

  F1  Do candidate ENTRIES share blocks inside one decision?
      Entry-level's only distinctive signal is shared ownership. If overlap is
      always zero then ``relief == block_count`` is structural and the entry
      axis is degenerate in H1.

  F2  Do entries occupy CONTIGUOUS, NON-OVERLAPPING bands of ``native_lru_rank``?
      If yes, entry choice = "which bands to take" and block choice = "how far
      into a band to cut", i.e. genuinely different decision spaces.

  F3  Is block DEPTH reconstructible offline, i.e. is the block-level path
      blocked by interface exposure or by missing information?

  F4  Does ``N_i`` (the relief a lone release unlocks) VARY across the candidates
      of one decision? If it does, the entry score is not a function of ``deadline``
      alone, so A1 is not equivalent to A0 even without shared blocks.

Usage::

    python scripts/probes/h1_entry_block_overlap.py <runs-dir> [--strict]
    KVOPT_H1_RUNS=<runs-dir> python scripts/probes/h1_entry_block_overlap.py

``<runs-dir>`` is the formal Level-A run artifacts directory, i.e. the directory
that contains per-run subdirectories with ``events.jsonl``. The artifacts are not
committed; only this script is.

``--strict`` additionally asserts the exact counts quoted in the documents, so a
mismatch fails loudly instead of silently drifting.
"""

from __future__ import annotations

import collections
import json
import os
import statistics
import sys
from pathlib import Path

DOCUMENTED = {
    "decisions": 81,
    "overlap_decisions": 0,
    "bands_contiguous": 81,
    "bands_disjoint": 81,
    "hash_num_tokens_snapshots": 903,
    "hash_num_tokens_distinct": 10,
    "ni_varying_decisions": 72,
    "all_zero_ni_decisions": 0,
}


def resolve_runs(argv: list[str]) -> Path:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if args:
        return Path(args[0]).resolve()
    env = os.environ.get("KVOPT_H1_RUNS")
    if env:
        return Path(env).resolve()
    raise SystemExit(
        "usage: h1_entry_block_overlap.py <runs-dir> [--strict]\n"
        "       (or set KVOPT_H1_RUNS)"
    )


def main() -> int:
    runs = resolve_runs(sys.argv)
    strict = "--strict" in sys.argv
    if not runs.is_dir():
        raise SystemExit(f"not a directory: {runs}")

    decisions = 0
    overlap_decisions = 0
    total_pairs = 0
    overlapping_pairs = 0
    bands_contig = 0
    bands_disjoint = 0
    band_decisions = 0
    ni_varying = 0
    all_zero_ni = 0
    distinct_ni_counts: list[int] = []
    snapshot_keys: collections.Counter = collections.Counter()
    hash_num_tokens_seen = 0
    hash_num_tokens_values: set[int] = set()

    for path in sorted(runs.rglob("events.jsonl")):
        try:
            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            continue

        # ---- F3: what does VLLM_PREFIX_SNAPSHOT carry? ----
        for event in events:
            if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT":
                payload = event.get("payload") or {}
                snapshot_keys.update(payload.keys())
                if "hash_num_tokens" in payload:
                    hash_num_tokens_seen += 1
                    value = payload.get("hash_num_tokens")
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        hash_num_tokens_values.add(int(value))

        forced = [
            e for e in events if e.get("event_type") == "FORCED_RELEASE_DECISION"
        ]
        if not forced:
            continue
        payload = forced[-1].get("payload") or {}
        queue = payload.get("original_free_queue") or []
        candidates = payload.get("candidates") or []
        if not queue or len(candidates) < 2:
            continue
        decisions += 1

        rank_of: dict[int, int] = {}
        for row in queue:
            block_id, rank = row.get("block_id"), row.get("native_lru_rank")
            if block_id is not None and rank is not None:
                rank_of[int(block_id)] = int(rank)

        entry_blocks = [
            {int(b) for b in (c.get("block_ids") or [])} for c in candidates
        ]

        # ---- F1: block overlap between entries ----
        any_overlap = False
        for i in range(len(entry_blocks)):
            for j in range(i + 1, len(entry_blocks)):
                total_pairs += 1
                if entry_blocks[i] & entry_blocks[j]:
                    overlapping_pairs += 1
                    any_overlap = True
        if any_overlap:
            overlap_decisions += 1

        # ---- F4: does N_i vary across the candidates of this decision? ----
        # ``initially_reclaimable_block_ids`` is the observed form of N_i at
        # R = empty, i.e. exactly what a lone release of that entry unlocks.
        ni_sizes = [
            len(c.get("initially_reclaimable_block_ids") or []) for c in candidates
        ]
        distinct_ni_counts.append(len(set(ni_sizes)))
        if len(set(ni_sizes)) > 1:
            ni_varying += 1
        if all(s == 0 for s in ni_sizes):
            all_zero_ni += 1

        # ---- F2: are the entries' rank bands contiguous AND disjoint? ----
        bands = []
        for blocks in entry_blocks:
            ranks = sorted(rank_of[b] for b in blocks if b in rank_of)
            if ranks:
                bands.append((ranks[0], ranks[-1], len(ranks)))
        if bands:
            band_decisions += 1
            if all(hi - lo + 1 == n for lo, hi, n in bands):
                bands_contig += 1
            ordered = sorted(bands)
            if all(
                ordered[i][1] < ordered[i + 1][0] for i in range(len(ordered) - 1)
            ):
                bands_disjoint += 1

    print("=" * 78)
    print("F1. DO ENTRIES SHARE BLOCKS? (entry-level's distinctive signal)")
    print("=" * 78)
    print(f"decisions with >=2 entries           : {decisions}")
    print(f"  entry pairs compared               : {total_pairs}")
    print(f"  pairs sharing >=1 block            : {overlapping_pairs}")
    print(f"  decisions with ANY overlap         : {overlap_decisions}"
          f"  = {100 * overlap_decisions / max(1, decisions):.1f}%")

    print()
    print("=" * 78)
    print("F2. ARE ENTRY BANDS CONTIGUOUS / DISJOINT IN native_lru_rank?")
    print("=" * 78)
    print(f"decisions with usable bands          : {band_decisions}")
    print(f"  all bands contiguous               : {bands_contig}"
          f"  = {100 * bands_contig / max(1, band_decisions):.1f}%")
    print(f"  bands pairwise disjoint            : {bands_disjoint}"
          f"  = {100 * bands_disjoint / max(1, band_decisions):.1f}%")

    print()
    print("=" * 78)
    print("F3. IS BLOCK DEPTH RECONSTRUCTIBLE FROM EXISTING EVIDENCE?")
    print("=" * 78)
    print(f"VLLM_PREFIX_SNAPSHOT payload keys    : {sorted(snapshot_keys)}")
    print(f"  snapshots carrying hash_num_tokens : {hash_num_tokens_seen}")
    if hash_num_tokens_values:
        values = sorted(hash_num_tokens_values)
        print(f"  distinct hash_num_tokens values    : {len(values)}"
              f"  min {values[0]}  median "
              f"{statistics.median(values):.0f}  max {values[-1]}")

    print()
    print("=" * 78)
    print("F4. DOES N_i VARY ACROSS CANDIDATES? (is A1 == A0 on this corpus?)")
    print("=" * 78)
    print(f"decisions with >1 distinct N_i     : {ni_varying}"
          f"  = {100 * ni_varying / max(1, decisions):.1f}%")
    print(f"decisions where ALL N_i == 0       : {all_zero_ni}"
          f"  = {100 * all_zero_ni / max(1, decisions):.1f}%")
    if distinct_ni_counts:
        mean_distinct = sum(distinct_ni_counts) / len(distinct_ni_counts)
        print(f"mean distinct N_i values/decision  : {mean_distinct:.2f}")
        print("  -> N_i varies, so the entry score is NOT a function of deadline alone;")
        print("     A1 is not equivalent to A0 here and must be measured, not assumed.")

    if strict:
        assert decisions == DOCUMENTED["decisions"], decisions
        assert overlap_decisions == DOCUMENTED["overlap_decisions"], overlap_decisions
        assert bands_contig == DOCUMENTED["bands_contiguous"], bands_contig
        assert bands_disjoint == DOCUMENTED["bands_disjoint"], bands_disjoint
        assert hash_num_tokens_seen == DOCUMENTED["hash_num_tokens_snapshots"]
        assert len(hash_num_tokens_values) == DOCUMENTED["hash_num_tokens_distinct"]
        assert ni_varying == DOCUMENTED["ni_varying_decisions"], ni_varying
        assert all_zero_ni == DOCUMENTED["all_zero_ni_decisions"], all_zero_ni
        print("\nSTRICT: documented counts reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
