"""Part B2 / A2: which decision-time signals actually exist in the archive?

IMPORTANT SCOPE LIMIT
---------------------
``TTL_HISTORY_INPUT_OBSERVED`` exposes ONLY the eta and queue-delay counters. It does
NOT expose ``global_server_gap_samples_seconds`` or the tool-conditioned gap samples,
so the archive cannot tell us how many inter-request gap samples existed. Those are
recorded by ``ServerGapHistory`` in-process (see runtime.py) but never logged here.

Therefore "sample count is zero" below refers to eta / queue-delay only and must NOT
be read as "reuse history is absent".

Checks, per run:
  - eta and queue-delay sample counters
  - eta provenance reason (this is the eta mode, NOT the TTL history mode)
  - candidate payload field presence
  - right-censored window events
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
        arrivals = 0
        programs = 0
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

            elif kind == "REQUEST_ARRIVED":
                arrivals += 1
            elif kind == "PROGRAM_STARTED":
                programs += 1

            elif kind == "W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED":
                censor[json.dumps(event["payload"], sort_keys=True)[:160]] += 1

            elif kind == "FORCED_RELEASE_DECISION":
                for cand in event["payload"]["candidates"]:
                    for field in CANDIDATE_FIELDS:
                        field_present[field] += 1
                        if cand.get(field) not in (None, "", []):
                            field_nonnull[field] += 1

        per_run_ttl.append(
            (
                run,
                max(run_samples) if run_samples else None,
                sorted(set(run_modes)),
                arrivals,
                programs,
            )
        )

    print()
    print("== estimated inter-request gap samples per run ==")
    gaps = [max(0, arrivals - programs) for _, _, _, arrivals, programs in per_run_ttl]
    if gaps:
        median_gap = sorted(gaps)[len(gaps) // 2]
        print(f"  runs                {len(gaps)}")
        print(f"  arrivals - programs: median {median_gap}, min {min(gaps)}, max {max(gaps)}")
        print("  cold-start threshold: 100  (_select_history -> COLD_START while <= 100)")
        print(f"  runs that could leave COLD_START: {sum(1 for g in gaps if g > 100)}")
    print("  note: this is an upper bound derived from event counts, since the real")
    print("        sample count is not logged (see the scope note at the top).")

    print()
    print("== eta / queue-delay sample counters (NOT the server-gap history) ==")
    for key in sorted(ttl_samples):
        if key.endswith(">0"):
            continue
        total = ttl_samples[key]
        positive = ttl_samples.get(f"{key}>0", 0)
        print(f"  {key:38s} observed={total:4d}  positive={positive:4d}")
    print("  note: global_server_gap_samples_seconds is NOT logged in this event,")
    print("        so the inter-request gap sample count cannot be read from the archive.")

    print()
    print("== eta provenance reason (this is the ETA mode, not the TTL mode) ==")
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
    print("== per run: eta provenance modes and event counts ==")
    for run, samples, run_mode, arrivals, programs in per_run_ttl[:12]:
        print(
            f"  {run[:42]:44s} arrivals={arrivals:3d} programs={programs:2d} "
            f"gap_est={max(0, arrivals - programs):3d} modes={run_mode}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
