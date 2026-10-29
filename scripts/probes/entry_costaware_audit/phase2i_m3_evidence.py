"""Phase 2I RC9: keep the four M3 evidence claims apart, and measure each one.

The four claims were previously collapsed into a single "M3 passed" line. They are not
interchangeable, and none of them implies the next:

    M3-1 Selected Victim Agreement  -- does the project-level SelectionPlan record agree
                                       with the predicted victim set? This compares two
                                       computations, it is not a physical observation.
    M3-2 Native Eviction            -- were those block ids actually evicted by the
                                       native block pool inside the episode window?
                                       Physical, but not owned.
    M3-3 Content Identity           -- does the content key recorded at eviction match the
                                       key the chain snapshot recorded for that slot, and
                                       is that key unique to one chain? Content identity
                                       is checkable offline; *ownership* is not, and the
                                       archive says so itself
                                       (``attribution_reason: native hash identity does
                                       not prove logical ownership``).
    M3-4 Downstream Recompute       -- did killing that content cause an APC miss or a
                                       recompute? Not observable in this archive.

Run this file directly. Output is evidence, not a verdict: it prints what is available
and labels what is not, instead of reporting an overlap percentage as agreement.
"""

from __future__ import annotations

import glob
import json
import os
from collections import Counter
from pathlib import Path

ROOT = (
    "local/phase2h-history-rich-native-smoke-v1-evidence/artifacts/"
    "phase2h-history-rich-native-smoke-runs-v1/runs"
)
FORCED = "FORCED_RELEASE_DECISION"
SNAPSHOT = "VLLM_PREFIX_SNAPSHOT"
PRESSURE_DONE = "CONTROLLED_REPLAY_PRESSURE_COMPLETED"
PRESSURE_REQUEST = "PRESSURE_REQUEST_COMPLETED"
EVICTED = "BLOCK_EVICTED"
EVICTED_RICH = "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def run_paths() -> list[Path]:
    pattern = os.path.join(ROOT, "*-a1-repeat-1", "events.jsonl")
    return [Path(p) for p in sorted(glob.glob(pattern))]


def victim_prediction(event: dict) -> tuple[set[int], set[int], int, int]:
    """Split the frozen rule's output into *freed* blocks and *evicted* victims.

    TIER_1 blocks are consumed first but they are **released to the free queue**, not
    evicted from the pool. Only the surplus beyond TIER_1 comes out of the promoted
    entry, and only those are real eviction candidates. Conflating the two inflates the
    denominator by the whole TIER_1 population and makes the agreement rate meaningless.

    Returns ``(victims, freed, need, deficit)``.
    """
    payload = event["payload"]
    queue = payload["original_free_queue"]
    need = int(payload["required_blocks"])
    rank_of = {row["block_id"]: row["native_lru_rank"] for row in queue}
    tier1 = [row["block_id"] for row in queue if row["eligibility_tier"] == 0]
    deficit = max(0, need - len(tier1))
    tier1_by_rank = sorted(tier1, key=lambda b: rank_of[b])
    freed = set(tier1_by_rank[:need])
    victims: set[int] = set()
    released = {str(r["program_id"]) for r in payload.get("selected_releases") or []}
    chosen = next(
        (c for c in payload["candidates"] if str(c["program_id"]) in released),
        None,
    )
    if chosen is not None:
        reclaimable = [b for b in chosen["initially_reclaimable_block_ids"] if b in rank_of]
        reclaimable.sort(key=lambda b: rank_of[b])
        victims = set(reclaimable[:deficit])
    return victims, freed, need, deficit


def asof_snapshot(events: list[dict], key: tuple[str, str], before_index: int) -> dict | None:
    best: dict | None = None
    best_index = -1
    for event in events:
        if event["event_type"] != SNAPSHOT:
            continue
        if (str(event.get("program_id")), str(event.get("prefix_id"))) != key:
            continue
        index = int(event["event_index"])
        if index >= before_index:
            continue
        if index > best_index:
            best, best_index = event, index
    return best


def window_for(events: list[dict], position: int) -> tuple[int, int]:
    """Episode window: the release itself up to the pressure completion it belongs to."""
    start = int(events[position]["event_index"])
    for later in events[position + 1 :]:
        if later["event_type"] == PRESSURE_DONE:
            return start, int(later["event_index"])
    return start, start + 1


def main() -> int:
    totals: Counter[str] = Counter()
    for path in run_paths():
        run = path.parent.name
        events = load(str(path))
        print(f"=== {run} ===")

        # Content keys recorded per chain, so a shared prefix can be detected.
        chain_keys: dict[tuple[str, str], dict[int, str]] = {}
        for event in events:
            if event["event_type"] != SNAPSHOT:
                continue
            key = (str(event.get("program_id")), str(event.get("prefix_id")))
            block_ids = [int(b) for b in event["payload"].get("block_ids") or []]
            keys = list(event["payload"].get("ordered_native_cache_keys") or [])
            if len(keys) == len(block_ids):
                chain_keys[key] = dict(zip(block_ids, (str(k) for k in keys), strict=True))

        key_owners: Counter[str] = Counter()
        for mapping in chain_keys.values():
            for cache_key in set(mapping.values()):
                key_owners[cache_key] += 1
        # Keys present in *every* chain's snapshot are the genuinely shared prefix; the
        # per-key owner count is otherwise dominated by prefix nesting (a deep block is
        # contained by every request that extended it), so it must not be reported as if
        # it measured contention.
        globally_shared = {
            cache_key for cache_key, owners in key_owners.items() if owners == len(chain_keys)
        }
        attribution_note = next(
            (
                str(event["payload"].get("attribution_reason"))
                for event in events
                if event["event_type"] == EVICTED_RICH
                and event["payload"].get("attribution_reason")
            ),
            "(none recorded)",
        )
        print(f"  chains={len(chain_keys)} globally_shared_prefix_blocks={len(globally_shared)}")
        print(f"  native attribution_reason: {attribution_note}")

        for position, event in enumerate(events):
            if event["event_type"] != FORCED:
                continue
            index = int(event["event_index"])
            victims, freed, need, deficit = victim_prediction(event)
            released = [
                str(r["program_id"]) for r in event["payload"].get("selected_releases") or []
            ]
            chosen = next(
                (c for c in event["payload"]["candidates"] if str(c["program_id"]) in released),
                None,
            )
            chain = (str(chosen["program_id"]), str(chosen["prefix_id"])) if chosen else None
            # ``last_selected_block_ids`` covers the whole selection, so M3-1 compares
            # against freed + victims. M3-2 and M3-3 only ever concern the victims.
            predicted_selection = freed | victims
            print(
                f"  idx={index} need={need} deficit={deficit} "
                f"freed={len(freed)} victims={len(victims)}"
            )

            # ---- M3-1: does the recorded SelectionPlan agree with the prediction?
            recorded: set[int] | None = None
            for later in events[position + 1 :]:
                if later["event_type"] == PRESSURE_REQUEST:
                    ids = later["payload"].get("last_selected_block_ids")
                    if ids is not None:
                        recorded = {int(b) for b in ids}
                    break
                if later["event_type"] == PRESSURE_DONE:
                    break
            if recorded is None:
                print("    M3-1 selection agreement       : UNAVAILABLE (no record)")
                totals["m3_1_unavailable"] += 1
            elif predicted_selection == recorded:
                print(f"    M3-1 selection agreement       : EXACT ({len(predicted_selection)})")
                totals["m3_1_exact"] += 1
            else:
                print(
                    f"    M3-1 selection agreement       : MISMATCH "
                    f"(pred {len(predicted_selection)} rec {len(recorded)} "
                    f"inter {len(predicted_selection & recorded)})"
                )
                totals["m3_1_mismatch"] += 1

            # ---- M3-2: were the *victim* slots physically evicted inside the window?
            start, end = window_for(events, position)
            in_window = {
                int(e["payload"]["block_id"])
                for e in events[position + 1 :]
                if e["event_type"] == EVICTED and start < int(e["event_index"]) <= end
            }
            hit = victims & in_window
            print(
                f"    M3-2 victim set evicted         : {len(hit)}/{len(victims)} "
                f"({len(in_window)} evictions occurred in the window)"
            )
            totals["m3_2_victims"] += len(victims)
            totals["m3_2_hit"] += len(hit)

            # ---- M3-3: content identity at eviction vs the chain snapshot
            if chain is None or chain not in chain_keys:
                print("    M3-3 content identity          : IDENTITY_UNVERIFIED (no chain record)")
                totals["m3_3_unverified"] += 1
                continue
            snapshot = asof_snapshot(events, chain, index)
            if snapshot is None:
                print(
                    "    M3-3 content identity          : IDENTITY_UNVERIFIED (no as-of snapshot)"
                )
                totals["m3_3_unverified"] += 1
                continue
            snap_blocks = [int(b) for b in snapshot["payload"].get("block_ids") or []]
            snap_keys = [str(k) for k in snapshot["payload"].get("ordered_native_cache_keys") or []]
            if len(snap_keys) != len(snap_blocks):
                print("    M3-3 content identity          : IDENTITY_UNVERIFIED (keys misaligned)")
                totals["m3_3_unverified"] += 1
                continue
            recorded_key = dict(zip(snap_blocks, snap_keys, strict=True))

            matched = 0
            shared_key = 0
            owner_counts: list[int] = []
            checked = 0
            for later in events[position + 1 :]:
                if later["event_type"] != EVICTED_RICH:
                    continue
                if not (start < int(later["event_index"]) <= end):
                    continue
                block_id = int(later["payload"]["block_id"])
                if block_id not in victims:
                    continue
                checked += 1
                key_before = later["payload"].get("native_cache_key_before")
                if key_before is None:
                    continue
                cache_key = str(key_before)
                owner_counts.append(key_owners.get(cache_key, 0))
                if cache_key == recorded_key.get(block_id):
                    matched += 1
                    if cache_key in globally_shared:
                        shared_key += 1
            if checked == 0:
                print("    M3-3 content identity          : IDENTITY_UNVERIFIED (no rich record)")
                totals["m3_3_unverified"] += 1
            else:
                band = (
                    f"owners {min(owner_counts)}..{max(owner_counts)}"
                    if owner_counts
                    else "owners n/a"
                )
                print(
                    f"    M3-3 content identity          : {matched}/{checked} key matches, "
                    f"{shared_key} in the globally shared prefix, {band}"
                )
                print(
                    "         content identity proven; OWNERSHIP not proven "
                    "(the same content belongs to many request prefixes)"
                )
                totals["m3_3_checked"] += checked
                totals["m3_3_matched"] += matched
                totals["m3_3_shared"] += shared_key

        print("    M3-4 downstream recompute      : NOT OBSERVABLE in this archive")
        print()

    print("== totals ==")
    print(
        f"  M3-1 exact / mismatch / unavailable   {totals['m3_1_exact']} / "
        f"{totals['m3_1_mismatch']} / {totals['m3_1_unavailable']}"
    )
    print(
        f"  M3-2 victim-hit / victims             {totals['m3_2_hit']} / {totals['m3_2_victims']}"
    )
    print(
        f"  M3-3 key matched / checked, globally-shared    {totals['m3_3_matched']} / "
        f"{totals['m3_3_checked']}, {totals['m3_3_shared']} globally shared"
    )
    print(f"  M3-3 unverified decisions             {totals['m3_3_unverified']}")
    print("  M3-4 recompute                        NOT OBSERVABLE")
    print()
    print("  No single number here is 'M3 passed'. M3-1 is agreement between two")
    print("  computations; M3-2 is physical but unowned; M3-3 proves content, not")
    print("  ownership; M3-4 is absent. Ownership would require a per-episode native")
    print("  attribution that this archive explicitly declines to make.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
