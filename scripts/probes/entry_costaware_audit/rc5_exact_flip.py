"""RC5: exact flip criterion with the full finite-need formula, full Entry identity.

For candidates that are all sufficient (N_i >= need >= 0):

    R_i = q_i * [need + lam * (N_i - need)]  =  q_i * a_i
    a_i = lam*N_i + (1-lam)*need

lambda=0 picks argmin q. lambda>0 picks argmin q*a.
They disagree exactly when the low-q candidate L has  q_L a_L > q_H a_H, i.e.

    q_H / q_L  <  a_L / a_H

The earlier report used a_L/a_H -> N_L/N_H, which is only the lam=1 / N>>need
limit. This script uses the exact ratio and checks the strict form.

Comparisons use full (program_id, prefix_id) keys, never truncated display names.
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
LAM = 0.5


def q_of(dmt: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, dmt / TAU))))


def a_of(need: int, n: int, lam: float) -> float:
    return lam * n + (1.0 - lam) * need


def eligible(queue, owners, rel) -> set[int]:
    """Blocks eligible under the frozen rule when ``rel`` is released."""
    return {
        b["block_id"]
        for b in queue
        if not b["has_block_hash"] or owners.get(b["block_id"], set()) <= rel
    }


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a1-repeat-1", "events.jsonl")))
    stats = {"decisions": 0, "multi_step_runs": 0, "two_candidate": 0}
    exact_ok = approx_ok = 0
    approx_false_positives = 0
    rows = []
    identity_mismatch = 0

    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        released = set()
        steps = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] != "FORCED_RELEASE_DECISION":
                continue
            steps += 1
            payload = event["payload"]
            timestamp = float(event["timestamp"])
            queue = payload["original_free_queue"]
            owners = {}
            for cand in payload["candidates"]:
                key = (cand["program_id"], cand["prefix_id"])
                for bid in cand["block_ids"]:
                    owners.setdefault(bid, set()).add(key)

            target = min(int(payload["required_blocks"]), len(queue))
            need = target - len(eligible(queue, owners, released))
            stats["decisions"] += 1
            if need <= 0:
                for rel in payload.get("selected_releases", []):
                    released.add((rel["program_id"], rel["prefix_id"]))
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
                dmt = float(cand["retention_deadline_timestamp"]) - timestamp
                cands.append((key, n, q_of(dmt)))

            observed = [
                (r["program_id"], r["prefix_id"])
                for r in payload.get("selected_releases", [])
            ]
            first_obs = observed[0] if observed else None
            if first_obs is not None and first_obs not in {c[0] for c in cands}:
                identity_mismatch += 1

            if len(cands) == 2:
                stats["two_candidate"] += 1
                low = min(cands, key=lambda c: (c[2], c[0]))
                high = max(cands, key=lambda c: (c[2], c[0]))
                q_ratio = high[2] / low[2] if low[2] > 0 else math.inf
                exact_ratio = a_of(need, low[1], LAM) / a_of(need, high[1], LAM)
                approx_ratio = low[1] / high[1]

                p05 = min(cands, key=lambda c: (c[2] * a_of(need, c[1], LAM), c[0]))
                p0 = min(cands, key=lambda c: (c[2], c[0]))
                actual = p05[0] != p0[0]

                exact_pred = q_ratio < exact_ratio
                approx_pred = q_ratio < approx_ratio
                exact_ok += int(exact_pred == actual)
                approx_ok += int(approx_pred == actual)
                approx_false_positives += int(approx_pred and not actual)
                rows.append(
                    (
                        run,
                        need,
                        [c[1] for c in cands],
                        round(q_ratio, 4),
                        round(exact_ratio, 4),
                        round(approx_ratio, 4),
                        actual,
                    )
                )

            for rel in payload.get("selected_releases", []):
                released.add((rel["program_id"], rel["prefix_id"]))
        if steps > 1:
            stats["multi_step_runs"] += 1

    print("== coverage ==")
    print(f"  forced-release decisions replayed       {stats['decisions']}")
    print(f"  runs with more than one step            {stats['multi_step_runs']}")
    print(f"  first observed pick not among candidates {identity_mismatch}")
    print()
    print("== flip criterion, two-candidate decisions ==")
    print(f"  decisions                               {stats['two_candidate']}")
    print(f"  exact ratio (a_L/a_H) correct           {exact_ok} / {stats['two_candidate']}")
    print(f"  approximate ratio (N_L/N_H) correct     {approx_ok} / {stats['two_candidate']}")
    print(f"  approximate false positives             {approx_false_positives}")
    print()
    print(f"  {'run':44s} {'need':>5s} {'N':>14s} {'q_ratio':>8s} "
          f"{'a_ratio':>8s} {'N_ratio':>8s} {'flip':>5s}")
    for run, need, ns, qr, er, ar, actual in rows:
        print(
            f"  {run[:42]:44s} {need:5d} {str(ns)[:14]:>14s} {qr:8.4f} "
            f"{er:8.4f} {ar:8.4f} {actual!s:>5s}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
