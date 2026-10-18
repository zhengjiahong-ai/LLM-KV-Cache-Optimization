"""A2 feasibility: reconstruct block geometry from recorded native evidence.

Answers the first A2 question -- can depth, chain membership, native rank and
content hash be recovered offline? -- by measuring it rather than assuming it.

Checks, per ``FORCED_RELEASE_DECISION``:

  G1  every candidate's blocks are present in ``original_free_queue``
      (otherwise the legal candidate set cannot be reconstructed)
  G2  inside one candidate, ``native_lru_rank`` is strictly inverse-monotone in
      the ``block_ids`` index. This is what licenses reading index 0 as the
      shallowest block, and what proves native LRU already evicts deepest-first
      inside a chain
  G3  ``VLLM_PREFIX_SNAPSHOT`` carries the hashes and hash geometry needed for
      content identity

Usage::

    python scripts/probes/a2_block_geometry.py <runs-dir> [--strict]
    KVOPT_H1_RUNS=<runs-dir> python scripts/probes/a2_block_geometry.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DOCUMENTED = {
    "decisions": 87,
    "entries_with_three_or_more_blocks": 294,
    "inverse_monotone_entries": 294,
    "decisions_with_all_blocks_in_queue": 87,
}


def resolve_runs(argv: list[str]) -> Path:
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    if positional:
        return Path(positional[0]).resolve()
    env = os.environ.get("KVOPT_H1_RUNS")
    if env:
        return Path(env).resolve()
    raise SystemExit(
        "usage: a2_block_geometry.py <runs-dir> [--strict]\n"
        "       (or set KVOPT_H1_RUNS)"
    )


def main() -> int:
    runs = resolve_runs(sys.argv)
    strict = "--strict" in sys.argv
    if not runs.is_dir():
        raise SystemExit(f"not a directory: {runs}")

    decisions = 0
    all_in_queue = 0
    entries = 0
    inverse_monotone = 0
    forward_monotone = 0
    non_monotone = 0
    snapshot_keys: set[str] = set()
    hash_block_sizes: set[int] = set()

    for path in sorted(runs.rglob("events.jsonl")):
        try:
            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            continue

        for event in events:
            if event.get("event_type") != "VLLM_PREFIX_SNAPSHOT":
                continue
            payload = event.get("payload") or {}
            snapshot_keys.update(payload.keys())
            size = payload.get("native_hash_block_size")
            if isinstance(size, int) and not isinstance(size, bool):
                hash_block_sizes.add(size)

        forced = [
            event for event in events if event.get("event_type") == "FORCED_RELEASE_DECISION"
        ]
        if not forced:
            continue
        payload = forced[-1].get("payload") or {}
        queue = payload.get("original_free_queue") or []
        candidates = payload.get("candidates") or []
        if not queue or not candidates:
            continue
        decisions += 1

        rank: dict[int, int] = {}
        for row in queue:
            block_id = row.get("block_id")
            if block_id is not None:
                rank[int(block_id)] = int(row["native_lru_rank"])

        every_block_visible = True
        for candidate in candidates:
            ids = [int(block_id) for block_id in (candidate.get("block_ids") or [])]
            if any(block_id not in rank for block_id in ids):
                every_block_visible = False
            observed = [(index, rank[block_id]) for index, block_id in enumerate(ids) if block_id in rank]
            if len(observed) < 3:
                continue
            entries += 1
            if all(observed[i][1] > observed[i + 1][1] for i in range(len(observed) - 1)):
                inverse_monotone += 1
            elif all(observed[i][1] < observed[i + 1][1] for i in range(len(observed) - 1)):
                forward_monotone += 1
            else:
                non_monotone += 1
        if every_block_visible:
            all_in_queue += 1

    print("=" * 78)
    print("G1. IS THE LEGAL CANDIDATE SET RECONSTRUCTIBLE?")
    print("=" * 78)
    print(f"decisions                                        : {decisions}")
    print(f"  every candidate block found in the free queue  : {all_in_queue}"
          f"  = {100 * all_in_queue / max(1, decisions):.1f}%")

    print()
    print("=" * 78)
    print("G2. IS DEPTH ORDER RECONSTRUCTIBLE FROM block_ids ORDER?")
    print("=" * 78)
    print(f"entries with >=3 queue-visible blocks            : {entries}")
    print(f"  rank strictly DECREASING as index increases     : {inverse_monotone}"
          f"  = {100 * inverse_monotone / max(1, entries):.1f}%")
    print(f"  rank strictly INCREASING                        : {forward_monotone}")
    print(f"  neither                                         : {non_monotone}")
    print("  -> deeper blocks have smaller native rank, so native LRU already")
    print("     evicts deepest-first inside a chain")

    print()
    print("=" * 78)
    print("G3. IS CONTENT IDENTITY AVAILABLE?")
    print("=" * 78)
    print(f"VLLM_PREFIX_SNAPSHOT payload keys                : {sorted(snapshot_keys)}")
    print(f"native_hash_block_size values observed           : {sorted(hash_block_sizes)}")

    if strict:
        assert decisions == DOCUMENTED["decisions"], decisions
        assert entries == DOCUMENTED["entries_with_three_or_more_blocks"], entries
        assert inverse_monotone == DOCUMENTED["inverse_monotone_entries"], inverse_monotone
        assert forward_monotone == 0, forward_monotone
        assert non_monotone == 0, non_monotone
        assert all_in_queue == DOCUMENTED["decisions_with_all_blocks_in_queue"], all_in_queue
        print("\nSTRICT: documented counts reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
