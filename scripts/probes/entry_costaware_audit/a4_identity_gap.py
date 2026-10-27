"""Part A4: classify A2 block-decision identity gaps from the v10 archive.

Rebuilds the 601 COST_AWARE_BLOCK_DECISION events and classifies:
  - selector used (greedy vs native fallback)
  - fallback reasons
  - identity_state_counts mix
  - whether the decision was in a forced-release window
  - whether selected_victims differs from native_lru_victims
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
FORCED = "FORCED_RELEASE_DECISION"
BLOCK_DECISION = "COST_AWARE_BLOCK_DECISION"


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a2-repeat-1", "events.jsonl")))
    print(f"A2 run files: {len(paths)}")

    totals = Counter()
    identity_states = Counter()
    fallback_reasons = Counter()
    contract_problems = Counter()
    adapter_problems = Counter()
    evidence_problems = Counter()
    by_selector = Counter()
    diff_by_selector = Counter()
    per_run = {}

    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        forced_indices = []
        events = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            events.append(event)
            if event["event_type"] == FORCED:
                forced_indices.append(int(event["event_index"]))

        run_stats = Counter()
        last_forced = -1
        for event in events:
            idx = int(event["event_index"])
            if event["event_type"] == FORCED:
                last_forced = idx
                continue
            if event["event_type"] != BLOCK_DECISION:
                continue

            payload = event["payload"]
            totals["decisions"] += 1
            run_stats["decisions"] += 1

            # identity mix
            for state, count in payload.get("identity_state_counts", {}).items():
                identity_states[state] += count

            selector = payload.get("selector", "?")
            by_selector[selector] += 1
            run_stats[f"sel:{selector}"] += 1

            for reason in payload.get("fallbacks") or []:
                fallback_reasons[reason] += 1
            for problem in payload.get("contract_problems") or []:
                contract_problems[problem[:60]] += 1
            for problem in payload.get("adapter_problems") or []:
                adapter_problems[problem[:60]] += 1
            for problem, count in (payload.get("evidence_problem_counts") or {}).items():
                evidence_problems[problem] += count

            # divergence vs native LRU victim list
            selected = payload.get("selected_victims") or []
            native = payload.get("native_lru_victims") or []
            differs = selected != native
            totals["victim_differs_total"] += int(differs)
            diff_by_selector[selector] += int(differs)

            # position relative to forced-release windows
            if last_forced >= 0:
                totals["after_a_forced_window"] += 1
                totals["differs_after_forced"] += int(differs)
                run_stats["after_forced"] += 1
            else:
                totals["before_any_forced"] += 1
                totals["differs_before_forced"] += int(differs)
                run_stats["before_forced"] += 1

            if payload.get("search_truncated"):
                totals["search_truncated"] += 1
            if payload.get("cost_known"):
                totals["cost_known_true"] += 1
            else:
                totals["cost_known_false"] += 1

        per_run[run] = run_stats

    print()
    print("== totals ==")
    for key, value in sorted(totals.items()):
        print(f"  {key:28s} {value}")

    print()
    print("== selector ==")
    for key, value in by_selector.most_common():
        print(f"  {key:32s} {value}")

    print()
    print("== victim list differs from native LRU ==")
    for key, value in sorted(diff_by_selector.items()):
        print(f"  {key:32s} {value}")

    print()
    print("== identity_state_counts (block-level tallies) ==")
    for key, value in identity_states.most_common():
        print(f"  {key:40s} {value}")

    print()
    print("== fallback reasons ==")
    for key, value in fallback_reasons.most_common():
        print(f"  {key:40s} {value}")

    print()
    print("== contract problems (top) ==")
    for key, value in contract_problems.most_common(8):
        print(f"  {value:5d}  {key}")

    print()
    print("== adapter problems (top) ==")
    for key, value in adapter_problems.most_common(8):
        print(f"  {value:5d}  {key}")

    print()
    print("== evidence problem counts ==")
    for key, value in evidence_problems.most_common(10):
        print(f"  {key:40s} {value}")

    print()
    print("== per run ==")
    for run in sorted(per_run):
        stats = per_run[run]
        print(
            f"  {run[:44]:46s} dec={stats['decisions']:3d} "
            f"greedy={stats['sel:incremental_greedy']:3d} "
            f"fallback={stats['sel:native_lru_fallback']:3d} "
            f"after_forced={stats['after_forced']:3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
