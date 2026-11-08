"""Strict check: is A2's legal_block_ids order tier-consistent?

Only decisions where EVERY legal block is present in the queue snapshot are
counted; a partial list would manufacture false inversions.
"""

from __future__ import annotations

import glob
import json
import os
from collections import Counter
from pathlib import Path

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/"
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/runs"
)


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a2-repeat-1", "events.jsonl")))
    stats = Counter()
    by_run = Counter()

    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        queue = None
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            kind = event["event_type"]
            if kind == "FORCED_RELEASE_DECISION":
                queue = {b["block_id"]: b for b in event["payload"]["original_free_queue"]}
                continue
            if kind != "COST_AWARE_BLOCK_DECISION" or queue is None:
                continue
            legal = payload_legal(event)
            if not legal:
                continue
            stats["decisions_with_queue"] += 1
            missing = [b for b in legal if b not in queue]
            if missing:
                stats["partial_legal_excluded"] += 1
                continue
            stats["strictly_comparable"] += 1
            by_run[run] += 1
            tiers = [
                (0 if not queue[b]["has_block_hash"] else 1, queue[b]["native_lru_rank"])
                for b in legal
            ]
            if tiers == sorted(tiers):
                stats["tier_consistent"] += 1
            else:
                stats["tier_INCONSISTENT"] += 1

    print("== strict legal-order check (all legal blocks present in queue) ==")
    for key, value in sorted(stats.items()):
        print(f"  {key:32s} {value}")
    print()
    print("== comparable decisions per run ==")
    for run in sorted(by_run):
        print(f"  {run[:46]:48s} {by_run[run]}")
    return 0


def payload_legal(event):
    payload = event["payload"]
    return payload.get("legal_block_ids") or []


if __name__ == "__main__":
    raise SystemExit(main())
