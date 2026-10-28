"""Phase 2I design probe: why A1 collapsed into Minimum Overshoot, and what a real
marginal-cost rule would have chosen on the same six decisions.

Read-only. Nothing here touches the frozen A1/A2 paths.

Frozen facts taken from ``src/kvopt/continuum/selection.py``
----------------------------------------------------------
- ``EligibilityTier.TIER_1 = 0``, ``TIER_2 = 1``.
- ``virtual_eligible_order`` sorts by ``(tier, native_lru_rank)``, so **every TIER_1
  block is consumed before any TIER_2 block**, regardless of rank.
- A pressure release promotes exactly one entry's blocks from protected (``None``) to
  TIER_2, and ``newly_eligible_block_ids`` is that entry's Tier-2 set.
- ``selected = virtual_eligible_order[:required_blocks]``.

Consequence: with ``deficit = max(0, need - |TIER_1|)`` a released entry contributes
``min(deficit, |its newly eligible blocks|)`` victims, and that count is the **same for
every candidate** whenever each candidate covers the deficit. The decision therefore
does not choose how many of an entry's blocks die; it chooses *whose* cold blocks fill
the Tier-2 window. ``N_i`` is not a cost, it only gates coverage.

Two cost reconstructions are compared
-------------------------------------
``literal``
    ``q * (lambda * N + (1 - lambda) * min(need, N))`` -- the frozen A1 score.
``chain_suffix``
    ``q * prefill_reload * (m - d_min + 1) / m`` where ``m`` is the released chain's
    length and ``d_min`` the shallowest depth among its blocks that the eligibility
    rule would actually evict. This is the frozen A2 chain-loss idea
    (``L = q * (m - j + 1)``) lifted to the Entry layer, expressed in seconds.

Everything is computed from decision-time evidence: ``original_free_queue``,
``required_blocks``, the candidate block set, and ``VLLM_PREFIX_SNAPSHOT`` for depth.
"""

from __future__ import annotations

import glob
import json
import math
import os
from collections import defaultdict
from pathlib import Path

ROOT = (
    "local/phase2h-history-rich-native-smoke-v1-evidence/artifacts/"
    "phase2h-history-rich-native-smoke-runs-v1/runs"
)
FORCED = "FORCED_RELEASE_DECISION"
SNAPSHOT = "VLLM_PREFIX_SNAPSHOT"
TAU = 30.0
LAMBDA = 0.5


def q_of(deadline: float, timestamp: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, (deadline - timestamp) / TAU))))


def chain_geometry(events: list[dict]) -> dict[tuple[str, str], list[int]]:
    """Latest snapshot per (program, prefix) gives that chain's ordered block list."""
    latest: dict[tuple[str, str], list[int]] = {}
    for event in events:
        if event["event_type"] != SNAPSHOT:
            continue
        key = (str(event.get("program_id")), str(event.get("prefix_id")))
        latest[key] = [int(b) for b in event["payload"].get("block_ids") or []]
    return latest


def released_by(events: list[dict], event_type: str) -> dict[int, list[str]]:
    """Which entry each arm released, keyed by event index."""
    releases: dict[int, list[str]] = {}
    for event in events:
        if event["event_type"] != event_type:
            continue
        payload = event["payload"]
        chosen = payload.get("selected_releases")
        if chosen is None:
            continue
        releases[int(event["event_index"])] = [str(r["program_id"]) for r in chosen]
    return releases


def main() -> int:
    decisions: list[dict] = []
    arm_choices: dict[str, dict[int, list[str]]] = {}

    for path in sorted(glob.glob(os.path.join(ROOT, "*", "events.jsonl"))):
        run = os.path.basename(os.path.dirname(path))
        arm = "a1" if "-a1-" in run else ("a0" if "-a0-" in run else "a2")
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        if arm != "a1":
            arm_choices.setdefault(run, {}).update(released_by(events, FORCED))
            continue

        chains = chain_geometry(events)
        for event in events:
            if event["event_type"] != FORCED:
                continue
            payload = event["payload"]
            queue = payload["original_free_queue"]
            need = int(payload["required_blocks"])
            timestamp = float(event["timestamp"])
            rank_of = {row["block_id"]: row["native_lru_rank"] for row in queue}
            tier1 = [row["block_id"] for row in queue if row["eligibility_tier"] == 0]
            deficit = max(0, need - len(tier1))
            rows = []
            for cand in payload["candidates"]:
                key = (str(cand["program_id"]), str(cand["prefix_id"]))
                chain = chains.get(key)
                if chain is None:
                    raise SystemExit(f"no snapshot for {key} in {run}")
                depth_of = {b: pos for pos, b in enumerate(chain, 1)}
                m = len(chain)
                reclaimable = [b for b in cand["initially_reclaimable_block_ids"] if b in rank_of]
                reclaimable.sort(key=lambda b: rank_of[b])
                victims = reclaimable[:deficit]
                depths = sorted(depth_of[b] for b in victims if b in depth_of)
                d_min = depths[0] if depths else m + 1
                suffix = max(0, m - d_min + 1)
                q = q_of(float(cand["retention_deadline_timestamp"]), timestamp)
                n_eligible = len(cand["initially_reclaimable_block_ids"])
                prefill = float(cand["prefill_reload_seconds"])
                rows.append(
                    {
                        "program": str(cand["program_id"]),
                        "n_eligible": n_eligible,
                        "m": m,
                        "victims": len(victims),
                        "depth_known": len(depths),
                        "d_min": d_min if depths else None,
                        "suffix": suffix,
                        "q": q,
                        "prefill": prefill,
                        "deadline": float(cand["retention_deadline_timestamp"]),
                        "literal": q * (LAMBDA * n_eligible + (1 - LAMBDA) * min(need, n_eligible)),
                        "chain_suffix": q * prefill * (suffix / m),
                    }
                )
            decisions.append(
                {
                    "run": run,
                    "idx": int(event["event_index"]),
                    "need": need,
                    "deficit": deficit,
                    "tier1": len(tier1),
                    "rows": rows,
                    "released": released_by(events, FORCED).get(int(event["event_index"]), []),
                }
            )

    print(f"A1 forced-release decisions: {len(decisions)}")
    print()

    print("== 1. eligibility arithmetic: N is not the victim count ==")
    for d in decisions:
        counts = sorted({r["victims"] for r in d["rows"]})
        print(
            f"  {d['run'][:30]:32s} idx={d['idx']:6d} need={d['need']:4d} "
            f"tier1={d['tier1']:4d} deficit={d['deficit']:4d} victim_counts={counts}"
        )
    print()

    print("== 2. per-candidate geometry and the two costs ==")
    for d in decisions:
        print(f"  {d['run'][:30]} idx={d['idx']} need={d['need']} deficit={d['deficit']}")
        for r in d["rows"]:
            print(
                f"    {r['program'][:26]:28s} N={r['n_eligible']:5d} m={r['m']:5d} "
                f"victims={r['victims']:3d} d_min={r['d_min']!s:>5s} "
                f"suffix={r['suffix']:4d} q={r['q']:.6f} prefill={r['prefill']:.6f}"
            )
            print(f"    {'':28s} literal={r['literal']:12.4f} chain_suffix={r['chain_suffix']:.6f}")
    print()

    print("== 3. which rule picks what, and what each arm actually released ==")
    matches = defaultdict(int)
    total = 0
    for d in decisions:
        rows = d["rows"]
        literal = min(rows, key=lambda r: (r["literal"], r["program"]))["program"]
        suffix = min(rows, key=lambda r: (r["chain_suffix"], r["program"]))["program"]
        earliest = min(rows, key=lambda r: (r["deadline"], r["program"]))["program"]
        overshoot = min(rows, key=lambda r: (r["n_eligible"], r["program"]))["program"]
        actual = d["released"][0] if d["released"] else None
        total += 1
        for name, pick in (
            ("literal", literal),
            ("chain_suffix", suffix),
            ("earliest_deadline", earliest),
            ("min_overshoot", overshoot),
        ):
            if pick == actual:
                matches[name] += 1
        print(f"  {d['run'][:30]:32s} idx={d['idx']:6d}")
        print(f"    released        {str(actual)[:34]}")
        print(f"    literal         {literal[:34]}")
        print(f"    chain_suffix    {suffix[:34]}")
        print(f"    earliest_dl     {earliest[:34]}")
        print(f"    min_overshoot   {overshoot[:34]}")
    print()
    print(f"  agreement with A1's own release, over {total} decisions:")
    for name in ("literal", "chain_suffix", "earliest_deadline", "min_overshoot"):
        print(f"    {name:18s} {matches[name]} / {total}")
    print()

    print("== 4. what the other arms released at the same pressure events ==")
    for d in decisions:
        print(f"  {d['run'][:30]:32s} idx={d['idx']:6d} A1={d['released']}")
        for run, releases in sorted(arm_choices.items()):
            if run.rsplit("-", 3)[0] != d["run"].rsplit("-", 3)[0]:
                continue
            same_time = sorted(releases.items())
            nearest = (
                min(same_time, key=lambda item: abs(item[0] - d["idx"])) if same_time else None
            )
            if nearest is not None:
                print(f"    {run[:34]:36s} idx~{nearest[0]:6d} {nearest[1]}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
