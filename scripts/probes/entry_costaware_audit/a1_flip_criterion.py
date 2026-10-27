"""When does lambda=0.5 flip the pick relative to lambda=0?

With N >> need the score is approximately q * lambda * N, so minimising it is
minimising q*N. The lambda=0 pick minimises q. The two therefore disagree exactly
when the candidate with the smaller q has a larger N by more than the q ratio:

    flip  <=>  q_ratio < N_ratio

This script tests that prediction on every two-candidate A1 decision.
"""

from __future__ import annotations

import glob
import json
import math
import os
from pathlib import Path

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/"
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/runs"
)
TAU = 30.0


def q_of(dmt: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, dmt / TAU))))


def score(q: float, need: int, n: int, lam: float) -> float:
    return q * (min(need, n) + lam * max(0, n - min(need, n)))


def eligible(queue, owners, rel) -> set[int]:
    """Blocks eligible under the frozen rule when ``rel`` is released."""
    return {
        b["block_id"]
        for b in queue
        if not b["has_block_hash"] or owners.get(b["block_id"], set()) <= rel
    }


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a1-repeat-1", "events.jsonl")))
    ok = 0
    total = 0
    rows = []
    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        released = set()
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] != "FORCED_RELEASE_DECISION":
                continue
            payload = event["payload"]
            timestamp = float(event["timestamp"])
            queue = payload["original_free_queue"]
            owners = {}
            for cand in payload["candidates"]:
                for bid in cand["block_ids"]:
                    owners.setdefault(bid, set()).add((cand["program_id"], cand["prefix_id"]))

            target = min(int(payload["required_blocks"]), len(queue))
            need = target - len(eligible(queue, owners, released))
            if need <= 0:
                continue
            cands = []
            for cand in payload["candidates"]:
                key = (cand["program_id"], cand["prefix_id"])
                if key in released:
                    continue
                n = len(
                    eligible(queue, owners, released | {key})
                    - eligible(queue, owners, released)
                )
                if min(need, n) <= 0:
                    continue
                cands.append(
                    (
                        cand["program_id"],
                        n,
                        q_of(float(cand["retention_deadline_timestamp"]) - timestamp),
                    )
                )
            if len(cands) == 2:
                total += 1
                low_q = min(cands, key=lambda c: c[2])
                high_q = max(cands, key=lambda c: c[2])
                q_ratio = high_q[2] / low_q[2] if low_q[2] > 0 else float("inf")
                n_ratio = low_q[1] / high_q[1] if high_q[1] else float("inf")
                predicted = q_ratio < n_ratio
                p05 = min(cands, key=lambda c: (score(c[2], need, c[1], 0.5), c[0]))
                p0 = min(cands, key=lambda c: (score(c[2], need, c[1], 0.0), c[0]))
                actual = p05[0] != p0[0]
                ok += int(predicted == actual)
                rows.append(
                    (
                        run,
                        need,
                        [c[0][:22] for c in cands],
                        [c[1] for c in cands],
                        round(q_ratio, 3),
                        round(n_ratio, 3),
                        predicted,
                        actual,
                    )
                )
            for rel in payload.get("selected_releases", []):
                released.add((rel.get("program_id"), rel.get("prefix_id")))

    print("flip <=> q_ratio < N_ratio")
    print(f"  two-candidate decisions: {total}")
    print(f"  prediction correct:      {ok} / {total}")
    print()
    print(f"  {'run':44s} {'need':>5s} {'N':>14s} {'q_ratio':>8s} {'N_ratio':>8s} "
          f"{'pred':>6s} {'actual':>7s}")
    for run, need, names, ns, qr, nr, pred, act in rows:
        print(
            f"  {run[:42]:44s} {need:5d} {str(ns)[:14]:>14s} {qr:8.3f} {nr:8.3f} "
            f"{pred!s:>6s} {act!s:>7s}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
