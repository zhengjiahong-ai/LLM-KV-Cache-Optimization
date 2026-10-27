"""A1 lambda ablation on the v10 archive: does lambda=0 change any decision?

Read-only replay of A1's scoring ladder over the recorded decision payloads.
Uses only decision-time fields (queue tiers, candidate block_ids, deadline,
elapsed) -- no future outcome, no block-level attribution.

For each recorded A1 forced-release decision we recompute the ladder under
lambda=0.5 (as configured) and lambda=0, and report whether the chosen entry
changes. Need and N_i are derived exactly as the frozen replay does.
"""

from __future__ import annotations

import glob
import json
import math
import os
import sys
from collections import Counter

TAU = 30.0
LAMBDA_CONFIGURED = 0.5


def load_decisions(path):
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") != "FORCED_RELEASE_DECISION":
                continue
            out.append((float(event["timestamp"]), event["payload"]))
    return out


def build(payload):
    queue = payload["original_free_queue"]
    candidates = []
    for cand in payload["candidates"]:
        candidates.append(
            {
                "key": (cand["program_id"], cand["prefix_id"]),
                "blocks": tuple(cand["block_ids"]),
                "deadline": float(cand["retention_deadline_timestamp"]),
                "elapsed": float(cand["elapsed_since_ttl_decision_seconds"]),
            }
        )
    owners = {}
    for cand in candidates:
        for block_id in cand["blocks"]:
            owners.setdefault(block_id, set()).add(cand["key"])
    return queue, candidates, owners


def eligible_ids(queue, owners, released):
    out = set()
    for row in queue:
        block_id = row["block_id"]
        if not row["has_block_hash"]:
            out.add(block_id)
            continue
        own = owners.get(block_id, set())
        if own <= released:
            out.add(block_id)
    return out


def newly_eligible(queue, owners, released, key):
    before = eligible_ids(queue, owners, released)
    after = eligible_ids(queue, owners, released | {key})
    return after - before


def q_of(deadline, timestamp, tau=TAU):
    x = (deadline - timestamp) / tau
    x = max(-60.0, min(60.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def rhat(q, need, n_blocks, lam):
    forced = min(need, n_blocks)
    residual = max(0, n_blocks - forced)
    return q * (forced + lam * residual)


def main(argv):
    root = argv[1] if len(argv) > 1 else None
    if root is None:
        # <repo>/scripts/probes/entry_costaware_audit -> <repo>
        repo = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        root = os.path.join(
            repo,
            "local",
            "continuum-native-cost-aware-bounded-v10-final-evidence",
            "artifacts",
            "continuum-native-cost-aware-bounded-runs-v10",
            "runs",
        )
    pattern = os.path.join(root, "*-a1-repeat-1", "events.jsonl")
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"no A1 run files under {root}")
        return 2

    stats = Counter()
    detail = []
    for path in paths:
        run_id = os.path.basename(os.path.dirname(path))
        decisions = load_decisions(path)
        released = set()
        for timestamp, payload in decisions:
            queue, candidates, owners = build(payload)
            target = min(int(payload["required_blocks"]), len(queue))
            need = target - len(eligible_ids(queue, owners, released))
            if need <= 0:
                stats["decision_already_satisfied"] += 1
                continue

            # Recompute scores under both lambdas with the real timestamps.
            scored = {}
            for cand in candidates:
                if cand["key"] in released:
                    continue
                n_blocks = len(newly_eligible(queue, owners, released, cand["key"]))
                force = min(need, n_blocks)
                if force <= 0:
                    continue
                q = q_of(cand["deadline"], timestamp)
                scored[cand["key"]] = {
                    "q": q,
                    "N": n_blocks,
                    "r_default": rhat(q, need, n_blocks, LAMBDA_CONFIGURED),
                    "r_zero": rhat(q, need, n_blocks, 0.0),
                }
            if not scored:
                stats["no_positive_candidate"] += 1
                continue

            pick_default = min(scored, key=lambda k: (scored[k]["r_default"], k))
            pick_zero = min(scored, key=lambda k: (scored[k]["r_zero"], k))
            observed = [rel.get("program_id") for rel in payload.get("selected_releases", [])]
            stats["decisions"] += 1
            if pick_default != pick_zero:
                stats["lambda_changes_choice"] += 1
                detail.append(
                    {
                        "run": run_id,
                        "need": need,
                        "observed": observed,
                        "pick_lambda_0.5": list(pick_default),
                        "pick_lambda_0": list(pick_zero),
                        "scores": {
                            str(k[0]): {m: round(v, 4) for m, v in s.items()}
                            for k, s in scored.items()
                        },
                    }
                )
            else:
                stats["lambda_irrelevant"] += 1

            # advance the replay using the configured (observed) choice
            for rel in payload.get("selected_releases", []):
                released.add((rel.get("program_id"), rel.get("prefix_id")))

    print(f"A1 run files: {len(paths)}")
    for key, value in sorted(stats.items()):
        print(f"  {key:28s} {value}")
    if detail:
        print()
        print("== lambda changes the choice ==")
        for row in detail:
            print(json.dumps(row, ensure_ascii=False, indent=1)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
