"""RC2/RC3: quantify the cost scale and the geometry in A2's live-choice decisions.

Two separate degeneracies are tested:

  (a) scale     -- decision_reuse_weights magnitudes, and the resulting proxy loss
  (b) geometry  -- within each chain, is rank already deepest-first? If yes the
                   cost-optimal victim set coincides with rank-LRU even when the
                   weights are non-trivial.

Plus a genuine counterfactual: rebuild DecisionGeometry from the recorded
block_memberships / effective_chain_lengths / decision_reuse_weights and ask
whether exhaustive selection differs from rank-LRU.
"""

from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "src")

from kvopt.costaware.a2_geometry import (
    DecisionGeometry,
    LegalBlock,
    Membership,
)
from kvopt.costaware.a2_selector import (
    native_lru_order,
    select_victims,
)

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/"
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/runs"
)
BLOCK = "COST_AWARE_BLOCK_DECISION"


def build_geometry(payload):
    weights = payload.get("decision_reuse_weights") or {}
    lengths = {}
    for key, value in (payload.get("effective_chain_lengths") or {}).items():
        lengths[key] = int(value)
    blocks = {}
    for item in payload.get("block_memberships") or []:
        members = tuple(
            Membership(chain=m["chain_id"], depth=int(m["depth"]), content_hash=m.get("content_hash") or "")
            for m in item.get("memberships") or []
        )
        if not members:
            continue
        blocks[int(item["block_id"])] = LegalBlock(
            block_id=int(item["block_id"]),
            native_rank=len(blocks),
            memberships=members,
        )
    if not blocks:
        return None
    # ranks come from the recorded legal order, which is the supplied candidate order
    order = payload.get("legal_block_ids") or []
    rank_of = {bid: index for index, bid in enumerate(order)}
    blocks = {
        bid: LegalBlock(
            block_id=bid,
            native_rank=rank_of.get(bid, 10**9),
            memberships=blk.memberships,
        )
        for bid, blk in blocks.items()
    }
    return DecisionGeometry(
        blocks=blocks,
        chain_length=lengths,
        q_by_chain=weights,
    )


def chain_is_deepest_first(geometry) -> bool:
    """Within every chain, does colder rank mean deeper depth?"""
    per_chain = {}
    for blk in geometry.blocks.values():
        for m in blk.memberships:
            per_chain.setdefault(m.chain, []).append((m.depth, blk.native_rank))
    for pairs in per_chain.values():
        pairs.sort()
        ranks = [r for _, r in pairs]
        if any(ranks[i] < ranks[i + 1] for i in range(len(ranks) - 1)):
            return False
    return True


def main() -> int:
    paths = sorted(glob.glob(os.path.join(ROOT, "*-a2-repeat-1", "events.jsonl")))
    live = []
    all_weights = []
    degenerate = 0
    geo_ok = 0
    deepest_first = 0
    counterfactual_differs = 0
    rows = []

    for path in paths:
        run = os.path.basename(os.path.dirname(path))
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] != BLOCK:
                continue
            payload = event["payload"]
            weights = payload.get("decision_reuse_weights") or {}
            for value in weights.values():
                all_weights.append(float(value))

            states = payload.get("identity_state_counts") or {}
            if states.get("CONTENT_VERIFIED_CHAIN_WEIGHTED", 0) == 0:
                degenerate += 1
                continue
            if (payload.get("proxy_weighted_loss") or 0.0) == 0.0:
                degenerate += 1
                continue

            live.append(payload)
            geometry = build_geometry(payload)
            if geometry is None or not geometry.scorable:
                continue
            geo_ok += 1
            df = chain_is_deepest_first(geometry)
            deepest_first += int(df)

            need = min(int(payload.get("required_blocks") or 0), len(geometry.blocks))
            native = native_lru_order(geometry)[:need]
            aware = select_victims(geometry, need).blocks
            if set(native) != set(aware):
                counterfactual_differs += 1
                rows.append((run, need, len(geometry.blocks), sorted(native)[:5], sorted(aware)[:5]))

    print(f"decisions with verified content and nonzero loss: {len(live)}")
    print(f"  geometry rebuildable and scorable:              {geo_ok}")
    print(f"  chain is deepest-first in every chain:          {deepest_first}")
    print(f"  counterfactual (exhaustive) differs from rank:  {counterfactual_differs}")
    print()
    if all_weights:
        ws = sorted(all_weights)
        print("== decision_reuse_weights distribution ==")
        print(f"  n        {len(ws)}")
        print(f"  min      {ws[0]:.3e}")
        print(f"  median   {statistics.median(ws):.3e}")
        print(f"  max      {ws[-1]:.3e}")
        print(f"  > 0.01   {sum(1 for w in ws if w > 0.01)} / {len(ws)}")
        print(f"  > 0.1    {sum(1 for w in ws if w > 0.1)} / {len(ws)}")
    if rows:
        print()
        print("== counterfactual differences ==")
        for row in rows[:5]:
            print("  ", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
