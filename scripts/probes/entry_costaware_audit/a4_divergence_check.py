"""Does A2 ever diverge from ANY LRU reference in the v10 archive?

Two references matter and must not be conflated:
  (R1) A2's internal reference = native_lru_order() over the legal set:
       sorted by native_rank ALONE, no eligibility-tier constraint.
  (R2) A0's actual rule = (eligibility_tier, native_lru_rank) truncated to target.

This script checks (R1) via the recorded fields, and reconstructs what (R2) would
pick from the recorded queue/tier data when available.
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
BLOCK_DECISION = "COST_AWARE_BLOCK_DECISION"


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a2-repeat-1", "events.jsonl")))
    stats = Counter()
    examples = []

    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] != BLOCK_DECISION:
                continue
            payload = event["payload"]
            selected = payload.get("selected_victims") or []
            native = payload.get("native_lru_victims") or []
            legal = payload.get("legal_block_ids") or []
            weight = payload.get("proxy_weighted_loss")
            states = payload.get("identity_state_counts") or {}
            verified = states.get("CONTENT_VERIFIED_CHAIN_WEIGHTED", 0)
            unverified = states.get("CONTENT_UNVERIFIED", 0)

            stats["decisions"] += 1
            stats["selected_eq_internal_lru"] += int(selected == native)
            stats["selected_set_eq_internal_lru"] += int(set(selected) == set(native))
            stats["native_is_legal_prefix"] += int(native == legal[: len(native)])
            stats["selected_is_legal_prefix"] += int(selected == legal[: len(selected)])
            stats["loss_is_zero"] += int(weight == 0.0)
            stats["no_verified_chain"] += int(verified == 0)
            stats["has_unverified"] += int(unverified > 0)
            stats["all_hashless"] += int(verified == 0 and unverified == 0)

            if selected == native:
                stats["identical_order_and_set"] += 1
            elif set(selected) == set(native):
                stats["same_set_different_order"] += 1
            else:
                stats["REAL_SET_DIFFERENCE"] += 1
                if len(examples) < 5:
                    examples.append(
                        (
                            os.path.basename(os.path.dirname(path)),
                            payload.get("selector"),
                            sorted(set(selected) ^ set(native))[:10],
                            weight,
                        )
                    )

    print("== A2 vs its own internal rank-only LRU reference ==")
    for key, value in sorted(stats.items()):
        print(f"  {key:34s} {value}")
    if examples:
        print()
        print("== real set differences ==")
        for row in examples:
            print("  ", row)
    else:
        print()
        print("  no real set difference from the internal rank-only reference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
