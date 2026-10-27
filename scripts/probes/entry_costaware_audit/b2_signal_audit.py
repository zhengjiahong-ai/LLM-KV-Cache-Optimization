"""Part B2 / A2: which decision-time signals actually exist in the archive?

Checks, per run:
  - TTL history sample counts (eta, queue delay) -> reuse/gap signal availability
  - TTL history mode (cold_start vs global vs tool_specific)
  - whether candidate payload carries tool type, prefill reload, waiting flag
  - censoring events (right-censored windows)

Also counts how many candidate records expose each field, so we can tell
"field exists in code" from "field reaches the decision point".
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

CANDIDATE_FIELDS = [
    "program_id",
    "prefix_id",
    "block_ids",
    "initially_reclaimable_block_ids",
    "retention_deadline_timestamp",
    "elapsed_since_ttl_decision_seconds",
    "next_tool_type",
    "prefill_reload_seconds",
    "eta",
    "queue_delay_t_seconds",
    "waiting_followup",
]


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*", "events.jsonl")))
    print(f"run files: {len(paths)}")

    field_present = Counter()
    field_nonnull = Counter()
    ttl_samples = Counter()
    modes = Counter()
    censor = Counter()
    per_run_ttl = []

    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        run_modes = []
        run_samples = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            kind = event["event_type"]

            if kind == "TTL_HISTORY_INPUT_OBSERVED":
                payload = event["payload"]
                for key in (
                    "eta_history_sample_count",
                    "queue_delay_history_sample_count",
                    "queue_delay_history_recent_sample_count",
                    "eta_completed_program_count",
                ):
                    value = payload.get(key)
                    ttl_samples[key] += 1
                    if value:
                        ttl_samples[f"{key}>0"] += 1
                run_samples.append(payload.get("queue_delay_history_sample_count", 0))
                modes[payload.get("eta_provenance_reason")] += 1
                run_modes.append(payload.get("eta_provenance_reason"))

            elif kind == "W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED":
                censor[json.dumps(event["payload"], sort_keys=True)[:160]] += 1

            elif kind == "FORCED_RELEASE_DECISION":
                for cand in event["payload"]["candidates"]:
                    for field in CANDIDATE_FIELDS:
                        field_present[field] += 1
                        if cand.get(field) not in (None, "", []):
                            field_nonnull[field] += 1

        per_run_ttl.append((run, max(run_samples) if run_samples else None, sorted(set(run_modes))))

    print()
    print("== TTL history sample counts ==")
    for key in sorted(ttl_samples):
        if key.endswith(">0"):
            continue
        total = ttl_samples[key]
        positive = ttl_samples.get(f"{key}>0", 0)
        print(f"  {key:38s} observed={total:4d}  positive={positive:4d}")

    print()
    print("== eta provenance reason (TTL history mode proxy) ==")
    for key, value in modes.most_common():
        print(f"  {key!s:38s} {value}")

    print()
    print("== right-censored window events ==")
    print(f"  total events: {sum(censor.values())}")
    for key, value in censor.most_common(3):
        print(f"  {value:3d}  {key}")

    print()
    print("== candidate fields: present vs non-null ==")
    print(f"  {'field':38s} {'present':>8s} {'non-null':>9s}")
    for field in CANDIDATE_FIELDS:
        print(f"  {field:38s} {field_present[field]:8d} {field_nonnull[field]:9d}")

    print()
    print("== per run: max queue-delay history samples, modes ==")
    for run, samples, run_mode in per_run_ttl[:12]:
        print(f"  {run[:46]:48s} samples={samples} modes={run_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
