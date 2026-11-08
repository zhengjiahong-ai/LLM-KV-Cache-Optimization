"""B4: how many unlocked blocks were not among the actual victims?

For each forced-release window in the A0 arm, compare:
  - blocks unlocked by the chosen release (N_i)
  - blocks actually evicted (PRESSURE_REQUEST_COMPLETED.last_selected_block_ids)
"""

from __future__ import annotations

import glob
import json
import os
import statistics
from pathlib import Path

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/"
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/runs"
)


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a0-repeat-1", "events.jsonl")))
    rows = []
    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        pending = None
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            kind = event["event_type"]
            if kind == "FORCED_RELEASE_DECISION":
                payload = event["payload"]
                queue = {b["block_id"]: b for b in payload["original_free_queue"]}
                owners = {}
                ids = []
                for cand in payload["candidates"]:
                    block_ids = set(cand["block_ids"])
                    ids.append(block_ids)
                    for bid in block_ids:
                        owners.setdefault(bid, set()).add(cand["program_id"])
                shared = 0
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        shared += len(ids[i] & ids[j])
                hashless = {b for b, r in queue.items() if not r["has_block_hash"]}
                target = min(int(payload["required_blocks"]), len(queue))
                need = target - len(hashless)
                chosen = [r["program_id"] for r in payload.get("selected_releases", [])]
                unlocked = set()
                for b, r in queue.items():
                    if r["has_block_hash"] and owners.get(b, set()) <= set(chosen):
                        unlocked.add(b)
                pending = {
                    "run": run,
                    "need": need,
                    "target": target,
                    "unlocked": len(unlocked),
                    "chosen": len(chosen),
                    "shared": shared,
                    "n_cands": len(ids),
                }
            elif kind == "PRESSURE_REQUEST_COMPLETED" and pending:
                victims = set(event["payload"].get("last_selected_block_ids") or [])
                pending["victims"] = len(victims)
                rows.append(pending)
                pending = None

    print(f"A0 windows with victims: {len(rows)}")
    print(f"  {'run':46s} {'need':>5s} {'target':>7s} {'unlocked':>9s} {'victims':>8s}")
    for row in rows:
        print(
            f"  {row['run'][:44]:46s} {row['need']:5d} {row['target']:7d} "
            f"{row['unlocked']:9d} {row.get('victims'):8d}"
        )
    ratios = [
        row["unlocked"] / row["victims"] for row in rows if row.get("victims")
    ]
    if ratios:
        print()
        print(f"  unlocked / victims : median {statistics.median(ratios):.1f}x "
              f"max {max(ratios):.1f}x")
    overs = [row["unlocked"] / row["need"] for row in rows if row["need"] > 0]
    if overs:
        print(f"  unlocked / need    : median {statistics.median(overs):.1f}x "
              f"max {max(overs):.1f}x min {min(overs):.1f}x")
        print(f"  windows >= 2x      : {sum(1 for x in overs if x >= 2)} / {len(overs)}")
        print(f"  windows >= 10x     : {sum(1 for x in overs if x >= 10)} / {len(overs)}")
    multi = [row for row in rows if row["n_cands"] > 1]
    if multi:
        print(f"  multi-candidate windows: {len(multi)} / {len(rows)}")
        print(f"  shared blocks (sum over all windows): "
              f"{sum(row['shared'] for row in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
