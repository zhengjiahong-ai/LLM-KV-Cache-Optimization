"""RC2: classify every A2 block decision by whether cost-aware COULD have differed.

The question is not "how many decisions were there" but "in how many decisions did
a genuine choice exist and the cost model still agreed with rank-LRU".

Classification per decision (mutually exclusive, ordered by strength of evidence):

  S1  fallback               cost scoring not reached (selector == native_lru_fallback)
  S2  degenerate_geometry    no verified chain-weighted content, or all step costs 0
  S3  no_candidate_spread    legal set has <= 1 block, or required >= legal (no freedom)
  S4  single_step_cost       multiple legal blocks, non-zero cost, but step costs equal
                             -> cost model had no signal to distinguish
  S5  live_choice            multiple legal blocks AND step costs differ
                             -> a real choice existed; did it change the victim set?

Only S5 constitutes "a cost-aware opportunity that was not taken".

Also splits every class by before/after the first forced-release window.
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
BLOCK = "COST_AWARE_BLOCK_DECISION"


def classify(payload: dict) -> str:
    if payload.get("selector") != "incremental_greedy":
        return "S1_fallback"

    legal = payload.get("legal_block_ids") or []
    required = int(payload.get("required_blocks") or 0)
    states = payload.get("identity_state_counts") or {}
    verified = states.get("CONTENT_VERIFIED_CHAIN_WEIGHTED", 0)
    steps = payload.get("step_costs") or []
    loss = payload.get("proxy_weighted_loss")

    if verified == 0:
        return "S2_degenerate_no_verified_content"
    if loss == 0.0 and all(abs(c) < 1e-12 for c in steps):
        return "S2_degenerate_zero_cost"
    if len(legal) <= 1 or required >= len(legal):
        return "S3_no_freedom"
    non_zero = [c for c in steps if abs(c) > 1e-12]
    if len({round(c, 12) for c in non_zero}) <= 1:
        return "S4_equal_marginals"
    return "S5_live_choice"


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a2-repeat-1", "events.jsonl")))
    classes = Counter()
    phase = Counter()
    by_phase = Counter()
    differs = Counter()
    examples = []

    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        seen_forced = False
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            kind = event["event_type"]
            if kind == FORCED:
                seen_forced = True
                continue
            if kind != BLOCK:
                continue
            payload = event["payload"]
            cls = classify(payload)
            where = "after_forced" if seen_forced else "before_forced"
            classes[cls] += 1
            phase[where] += 1
            by_phase[(cls, where)] += 1

            selected = payload.get("selected_victims") or []
            native = payload.get("native_lru_victims") or []
            if selected != native:
                differs[cls] += 1
                if len(examples) < 5:
                    examples.append((run, cls, selected[:6], native[:6]))

    total = sum(classes.values())
    print(f"A2 block decisions: {total}")
    print()
    print("== classification ==")
    for key in sorted(classes):
        print(f"  {key:38s} {classes[key]:4d}  {classes[key]/total:6.1%}  "
              f"differs_from_rankLRU={differs[key]}")
    print()
    print("== phase split ==")
    for key, value in sorted(phase.items()):
        print(f"  {key:16s} {value}")
    print()
    print("== class x phase ==")
    for key in sorted(by_phase):
        print(f"  {key[0]:38s} {key[1]:14s} {by_phase[key]:4d}")
    print()
    print("== opportunity summary ==")
    live = classes["S5_live_choice"]
    print(f"  decisions where a real cost choice existed (S5): {live}")
    print(f"  of those, where cost still matched rank-LRU:     {live - differs['S5_live_choice']}")
    print(f"  of those, where cost differed from rank-LRU:     {differs['S5_live_choice']}")
    if examples:
        print()
        print("== decisions where selected != native ==")
        for row in examples:
            print("  ", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
