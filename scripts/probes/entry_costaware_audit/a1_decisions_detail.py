"""Part A1/A3: recover all 29 A1 release decisions with full scoring detail.

For every recorded A1 forced-release step we report:
  - candidate count, need, each candidate's N_i, q, deadline offset
  - the score under lambda in {0, 0.5} and the resulting pick
  - the observed pick, and whether it equals:
        earliest-deadline, minimum-overshoot, sufficient-first
  - the q span inside the decision

Read-only. Decision-time fields only.
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


def q_of(deadline_minus_t: float) -> float:
    x = max(-60.0, min(60.0, deadline_minus_t / TAU))
    return 1.0 / (1.0 + math.exp(-x))


def score(q: float, need: int, n_blocks: int, lam: float) -> float:
    forced = min(need, n_blocks)
    residual = max(0, n_blocks - forced)
    return q * (forced + lam * residual)


def eligible(queue, owners, rel) -> set[int]:
    """Blocks eligible under the frozen rule when ``rel`` is released."""
    out = set()
    for b in queue:
        if not b["has_block_hash"] or owners.get(b["block_id"], set()) <= rel:
            out.add(b["block_id"])
    return out


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a1-repeat-1", "events.jsonl")))
    rows_out = []

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
                    owners.setdefault(bid, set()).add(
                        (cand["program_id"], cand["prefix_id"])
                    )

            target = min(int(payload["required_blocks"]), len(queue))
            need = target - len(eligible(queue, owners, released))
            if need <= 0:
                continue

            cands = []
            for cand in payload["candidates"]:
                key = (cand["program_id"], cand["prefix_id"])
                if key in released:
                    continue
                after = eligible(queue, owners, released | {key})
                before = eligible(queue, owners, released)
                n_blocks = len(after - before)
                if min(need, n_blocks) <= 0:
                    continue
                dmt = float(cand["retention_deadline_timestamp"]) - timestamp
                cands.append(
                    {
                        "key": key,
                        "program": cand["program_id"],
                        "N": n_blocks,
                        "blocks": len(cand["block_ids"]),
                        "dmt": dmt,
                        "q": q_of(dmt),
                    }
                )
            if not cands:
                continue

            qs = [c["q"] for c in cands]
            for c in cands:
                c["s05"] = score(c["q"], need, c["N"], 0.5)
                c["s0"] = score(c["q"], need, c["N"], 0.0)

            pick05 = min(cands, key=lambda c: (c["s05"], c["key"]))
            pick0 = min(cands, key=lambda c: (c["s0"], c["key"]))
            pick_ed = min(cands, key=lambda c: (c["dmt"], c["key"]))
            pick_mo = min(cands, key=lambda c: (max(0, c["N"] - need), c["key"]))
            sufficient = [c for c in cands if c["N"] >= need]
            pick_sf = min(sufficient, key=lambda c: (c["dmt"], c["key"])) if sufficient else None

            observed = [
                (r.get("program_id"), r.get("prefix_id"))
                for r in payload.get("selected_releases", [])
            ]
            first_obs = observed[0] if observed else None

            rows_out.append(
                {
                    "run": run,
                    "need": need,
                    "target": target,
                    "n_cands": len(cands),
                    "q_span": round(max(qs) - min(qs), 6),
                    "cands": [
                        {
                            "p": c["program"][:30],
                            "N": c["N"],
                            "q": round(c["q"], 4),
                            "dmt": round(c["dmt"], 3),
                        }
                        for c in cands
                    ],
                    "observed": first_obs[0][:30] if first_obs else None,
                    "pick_l05": pick05["program"][:30],
                    "pick_l0": pick0["program"][:30],
                    "pick_earliest_deadline": pick_ed["program"][:30],
                    "pick_min_overshoot": pick_mo["program"][:30],
                    "pick_sufficient_first": (
                        pick_sf["program"][:30] if pick_sf else None
                    ),
                    "obs_eq_ed": first_obs == pick_ed["key"],
                    "obs_eq_mo": first_obs == pick_mo["key"],
                    "obs_eq_marginal_gain": None,
                }
            )
            for rel in payload.get("selected_releases", []):
                released.add((rel.get("program_id"), rel.get("prefix_id")))

    print(f"A1 decisions recovered: {len(rows_out)}")
    print()
    hdr = (
        f"{'run':46s} {'need':>4s} {'#c':>3s} {'qspan':>7s} "
        f"{'observed':32s} {'λ.5':32s} {'λ0':32s} {'ED':>3s} {'MO':>3s}"
    )
    print(hdr)
    for r in rows_out:
        print(
            f"{r['run'][:44]:46s} {r['need']:4d} {r['n_cands']:3d} {r['q_span']:7.4f} "
            f"{str(r['observed'])[:30]:32s} {r['pick_l05'][:30]:32s} "
            f"{r['pick_l0'][:30]:32s} "
            f"{'Y' if r['obs_eq_ed'] else 'n':>3s} {'Y' if r['obs_eq_mo'] else 'n':>3s}"
        )

    n = len(rows_out)
    print()
    print("== agreement of the observed pick with simple rules ==")
    print(f"  observed == earliest deadline      {sum(r['obs_eq_ed'] for r in rows_out)} / {n}")
    print(f"  observed == minimum overshoot      {sum(r['obs_eq_mo'] for r in rows_out)} / {n}")
    print(
        "  observed == configured lambda=0.5   "
        f"{sum(r['observed'] == r['pick_l05'] for r in rows_out)} / {n}"
    )
    print(
        "  observed == lambda=0 scoring        "
        f"{sum(r['observed'] == r['pick_l0'] for r in rows_out)} / {n}"
    )
    print(f"  decisions where lambda=0 differs    "
          f"{sum(r['pick_l05'] != r['pick_l0'] for r in rows_out)}")

    print()
    print("== per-decision candidate sizes (N_i) and ratio ==")
    print(f"  {'run':46s} {'need':>5s} {'N values':>24s} {'maxN/minN':>10s} {'flip?':>6s}")
    for r in rows_out:
        ns = [c["N"] for c in r["cands"]]
        ratio = (max(ns) / min(ns)) if len(ns) > 1 and min(ns) else float("nan")
        flip = "YES" if r["pick_l05"] != r["pick_l0"] else "-"
        print(
            f"  {r['run'][:44]:46s} {r['need']:5d} {str(sorted(ns))[:24]:>24s} "
            f"{ratio:10.2f} {flip:>6s}"
        )

    print()
    print("== detail for the decisions where lambda changes the pick ==")
    for r in rows_out:
        if r["pick_l05"] != r["pick_l0"]:
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
