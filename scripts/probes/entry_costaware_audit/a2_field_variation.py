"""Which candidate fields actually vary at decision time in this archive?

A field that is constant across candidates cannot order them. This audits the
realised variation of every decision-time candidate field, and checks for
deadline ties (which decide whether lambda=0 scoring coincides with A0's
(deadline, min-rank, id) tie-break).
"""

from __future__ import annotations

import glob
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/"
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/runs"
)

FIELDS = [
    "next_tool_type",
    "waiting_followup",
    "prefill_reload_seconds",
    "eta",
    "queue_delay_t_seconds",
    "elapsed_since_ttl_decision_seconds",
    "retention_deadline_timestamp",
]


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-repeat-1", "events.jsonl")))
    values = defaultdict(list)
    per_decision_spread = defaultdict(list)
    decisions = 0
    multi = 0
    deadline_ties = 0
    ttl_zero = 0
    ttl_total = 0
    tool_mix = Counter()

    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] != "FORCED_RELEASE_DECISION":
                continue
            payload = event["payload"]
            timestamp = float(event["timestamp"])
            cands = payload["candidates"]
            decisions += 1
            if len(cands) > 1:
                multi += 1

            for cand in cands:
                for field in FIELDS:
                    values[field].append(cand.get(field))
                ttl = (
                    float(cand["retention_deadline_timestamp"]) - timestamp
                    + float(cand["elapsed_since_ttl_decision_seconds"])
                )
                ttl_total += 1
                if abs(ttl) < 1e-9:
                    ttl_zero += 1
                tool_mix[cand.get("next_tool_type")] += 1

            for field in FIELDS:
                distinct = {cand.get(field) for cand in cands}
                per_decision_spread[field].append(len(distinct))

            offsets = [
                round(
                    float(c["retention_deadline_timestamp"]) - timestamp, 9
                )
                for c in cands
            ]
            if len(offsets) != len(set(offsets)):
                deadline_ties += 1

    print(f"forced decisions: {decisions}   multi-candidate: {multi}")
    print(f"ttl_seconds == 0: {ttl_zero} / {ttl_total}")
    print(f"decisions with a deadline tie: {deadline_ties} / {multi}")
    print()
    print("== field variation ==")
    print(f"  {'field':38s} {'distinct values':>16s} {'decisions where it varies':>26s}")
    for field in FIELDS:
        distinct = len(set(values[field]))
        varying = sum(1 for n in per_decision_spread[field] if n > 1)
        print(f"  {field:38s} {distinct:16d} {varying:26d}")
    print()
    print("== next_tool_type distribution ==")
    for key, value in tool_mix.most_common():
        print(f"  {key!s:30s} {value}")
    print()
    print("== value sets for the discrete fields ==")
    for field in ("eta", "queue_delay_t_seconds", "waiting_followup"):
        print(f"  {field:38s} {sorted(set(values[field]), key=str)[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
