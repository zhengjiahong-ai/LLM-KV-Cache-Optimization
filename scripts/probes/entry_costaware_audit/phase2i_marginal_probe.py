"""Phase 2I design probe: marginal recompute cost under the frozen eligibility rule.

Read-only. Nothing here touches a frozen A1/A2 path.

Frozen facts this probe depends on (read from source, not inferred)
-------------------------------------------------------------------
``src/kvopt/continuum/selection.py``
    ``EligibilityTier``: TIER_1 = 0, TIER_2 = 1.
    ``virtual_eligible_order`` sorts by ``(tier, native_lru_rank)``, so every TIER_1
    block is consumed before any TIER_2 block.
    A pressure release promotes exactly one entry's blocks from protected to TIER_2,
    and ``selected = virtual_eligible_order[:required_blocks]``.

``src/kvopt/continuum/pressure.py`` ``_release_sort_key``
    A0's release order is ``(deadline, min native rank over newly eligible, identity)``.
    It is a Continuum **deadline** rule at the Entry layer. Native LRU is a **block**
    eviction rule and is not what A0 chooses entries with.

Three correctness rules this probe enforces
-------------------------------------------
1. **As-of snapshot.** For a decision at event index ``i``, the chain geometry used is
   the *latest* ``VLLM_PREFIX_SNAPSHOT`` with index ``< i`` for that exact
   ``(program_id, prefix_id)``. A later snapshot from the same run is never used, even
   if it happens to describe the same prefix, because it may postdate the eviction.
2. **Fail closed on missing depth.** Every predicted victim must have a recoverable
   depth. If any victim's block is absent from the as-of chain, the decision is
   reported as unscorable and excluded from rule comparison. No depth is guessed and no
   victim is skipped.
3. **Cross-arm matching by barrier identity**, never by nearest event index. Each
   pressure completes with ``CONTROLLED_REPLAY_PRESSURE_COMPLETED.boundary_id`` such as
   ``pressure:after-round-55``; that string is the link between arms.
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
PRESSURE_DONE = "CONTROLLED_REPLAY_PRESSURE_COMPLETED"
TIME_ADVANCED = "CONTROLLED_REPLAY_TIME_ADVANCED"
TAU = 30.0
LAMBDA = 0.5


def q_of(deadline: float, timestamp: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, (deadline - timestamp) / TAU))))


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def asof_chains(events: list[dict], before_index: int) -> dict[tuple[str, str], list[int]]:
    """Latest snapshot strictly before ``before_index``, per (program_id, prefix_id)."""
    latest: dict[tuple[str, str], tuple[int, list[int]]] = {}
    for event in events:
        if event["event_type"] != SNAPSHOT:
            continue
        index = int(event["event_index"])
        if index >= before_index:
            continue
        key = (str(event.get("program_id")), str(event.get("prefix_id")))
        blocks = [int(b) for b in event["payload"].get("block_ids") or []]
        previous = latest.get(key)
        if previous is None or index > previous[0]:
            latest[key] = (index, blocks)
    return {key: blocks for key, (_index, blocks) in latest.items()}


def barrier_for(events: list[dict]) -> tuple[dict[int, str], list[str]]:
    """Map each forced-release event index to the barrier id that triggered it.

    Alignment is checked, not assumed. Pairing by position alone would silently accept a
    run where a pressure completed twice, a release happened outside any pressure, or a
    boundary id repeats. The four checks below must all hold; anything else is returned
    as a problem and the caller must fail closed for that run.

    Checks
    ------
    1. **count** -- every pressure completion consumed exactly one release, and the
       completion's ``forced_release_count_after`` increases by one each time.
    2. **order** -- each release precedes its own completion, and completions are
       themselves ordered.
    3. **unique barrier id** -- no ``boundary_id`` appears twice in a run.
    4. **stage attribution** -- the completion's ``stage_id`` is non-empty, so each
       barrier can be traced to a replay stage.
    """
    problems: list[str] = []
    releases = [int(event["event_index"]) for event in events if event["event_type"] == FORCED]
    completions = [
        (
            int(event["event_index"]),
            str(event["payload"].get("boundary_id")),
            str(event["payload"].get("stage_id")),
            int(event["payload"].get("forced_release_count_after") or 0),
        )
        for event in events
        if event["event_type"] == PRESSURE_DONE
    ]

    # 1. count
    if len(releases) != len(completions):
        problems.append(
            f"count mismatch: {len(releases)} forced releases vs "
            f"{len(completions)} pressure completions"
        )

    # 2. order, plus the monotone release counter as an independent check
    for position, (completion_index, _boundary, _stage, count_after) in enumerate(completions):
        if position >= len(releases):
            break
        if releases[position] > completion_index:
            problems.append(
                f"order mismatch: release {releases[position]} follows its "
                f"completion {completion_index}"
            )
        if count_after != position + 1:
            problems.append(
                f"release counter mismatch at barrier {position}: "
                f"forced_release_count_after={count_after}, expected {position + 1}"
            )

    # 3. unique barrier id
    boundaries = [entry[1] for entry in completions]
    if len(set(boundaries)) != len(boundaries):
        problems.append(f"duplicate boundary ids: {boundaries}")

    # 4. stage attribution
    for _index, boundary, stage, _count in completions:
        if not stage or stage == "None":
            problems.append(f"barrier {boundary} has no stage_id")

    mapping: dict[int, str] = {}
    for position, release_index in enumerate(releases):
        if position < len(completions):
            mapping[release_index] = completions[position][1]
    return mapping, problems


def _recorded_selections(events: list[dict]) -> dict[int, set[int]]:
    """Per-episode recorded victim sets, keyed by 1-based forced-release ordinal.

    ``PRESSURE_REQUEST_COMPLETED`` carries ``last_selected_block_ids``, the blocks the
    native path reports it selected. That is a direct record rather than an inference,
    so it is the only admissible content-attribution source. It is returned per episode
    because the field is not self-describing about which episode it belongs to; the
    caller must compare each entry against the prediction and treat a mismatch as
    missing evidence rather than as a refutation.
    """
    recorded: dict[int, set[int]] = {}
    episode = 0
    for event in events:
        if event["event_type"] == FORCED:
            episode += 1
        elif event["event_type"] == "PRESSURE_REQUEST_COMPLETED":
            ids = event["payload"].get("last_selected_block_ids")
            if episode and ids is not None:
                recorded[episode] = {int(block_id) for block_id in ids}
    return recorded


def evaluate_decision(events: list[dict], event: dict) -> dict:
    """Compute deficit, victims, d_min and the three candidate costs for one decision."""
    payload = event["payload"]
    index = int(event["event_index"])
    queue = payload["original_free_queue"]
    need = int(payload["required_blocks"])
    timestamp = float(event["timestamp"])
    rank_of = {row["block_id"]: row["native_lru_rank"] for row in queue}
    tier1 = [row["block_id"] for row in queue if row["eligibility_tier"] == 0]
    deficit = max(0, need - len(tier1))
    chains = asof_chains(events, index)

    rows = []
    unscorable: list[str] = []
    for cand in payload["candidates"]:
        program = str(cand["program_id"])
        prefix = str(cand["prefix_id"])
        chain = chains.get((program, prefix))
        if chain is None:
            unscorable.append(f"{program}: no as-of snapshot for this prefix")
            continue
        depth_of = {block_id: position for position, block_id in enumerate(chain, 1)}
        m = len(chain)
        reclaimable = [b for b in cand["initially_reclaimable_block_ids"] if b in rank_of]
        reclaimable.sort(key=lambda b: rank_of[b])
        victims = reclaimable[:deficit]
        missing = [b for b in victims if b not in depth_of]
        if missing:
            unscorable.append(
                f"{program}: {len(missing)}/{len(victims)} victims absent from as-of chain"
            )
            continue
        depths = [depth_of[b] for b in victims]
        d_min = min(depths) if depths else m + 1
        suffix = max(0, m - d_min + 1)
        q = q_of(float(cand["retention_deadline_timestamp"]), timestamp)
        n_eligible = len(cand["initially_reclaimable_block_ids"])
        prefill = float(cand["prefill_reload_seconds"])
        rows.append(
            {
                "program": program,
                "n_eligible": n_eligible,
                "m": m,
                "victims": len(victims),
                "d_min": d_min,
                "suffix": suffix,
                # Prefix-suffix-aware cost proxy, in proxy-weighted seconds.
                "proxy": q * prefill * (suffix / m),
                # Frozen A1 score, for reference only.
                "literal": q * (LAMBDA * n_eligible + (1 - LAMBDA) * min(need, n_eligible)),
                # A0 release key components.
                "deadline": float(cand["retention_deadline_timestamp"]),
                "coldest_newly_eligible_rank": min(
                    (rank_of[b] for b in reclaimable), default=math.inf
                ),
                "q": q,
                "prefill": prefill,
                "suffix_is_victim_count": suffix == len(victims),
                "suffix_equals_deficit": suffix == deficit,
            }
        )
    return {
        "index": index,
        "need": need,
        "tier1": len(tier1),
        "deficit": deficit,
        "rows": rows,
        "unscorable": unscorable,
        "released": [str(r["program_id"]) for r in payload.get("selected_releases") or []],
    }


def main() -> int:
    # ---------------------------------------------------------------- collect
    by_scenario: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    arm_of: dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "*", "events.jsonl"))):
        run = os.path.basename(os.path.dirname(path))
        arm = "a1" if "-a1-" in run else ("a0" if "-a0-" in run else "a2")
        scenario = run.rsplit("-" + arm + "-", 1)[0]
        arm_of[run] = arm
        by_scenario[scenario][arm] = load(path)

    print("== 0. as-of snapshot and identity checks ==")
    total_decisions = 0
    unscorable_total = 0
    barrier_problems_total = 0
    decisions: list[dict] = []
    for scenario in sorted(by_scenario):
        events = by_scenario[scenario]["a1"]
        barriers, barrier_problems = barrier_for(events)
        if barrier_problems:
            barrier_problems_total += len(barrier_problems)
            print(f"  {scenario}: BARRIER ALIGNMENT FAILED, run excluded from cross-arm")
            for problem in barrier_problems:
                print(f"    {problem}")
            continue
        for event in events:
            if event["event_type"] != FORCED:
                continue
            total_decisions += 1
            record = evaluate_decision(events, event)
            record["scenario"] = scenario
            record["barrier"] = barriers.get(record["index"], "<unmatched>")
            decisions.append(record)
            if record["unscorable"]:
                unscorable_total += 1
            print(
                f"  {scenario:34s} idx={record['index']:6d} "
                f"barrier={record['barrier']:26s} "
                f"need={record['need']:4d} deficit={record['deficit']:4d} "
                f"scorable={len(record['rows'])}/{len(record['rows']) + len(record['unscorable'])}"
            )
            for problem in record["unscorable"]:
                print(f"    FAIL CLOSED: {problem}")
    print()
    print(f"  decisions                      {total_decisions}")
    print(f"  fail-closed decisions          {unscorable_total}")
    print("  every ratio below uses an as-of snapshot with index < decision index.")
    print()

    # -------------------------------------------------------- the six decisions
    print("== 1. per-candidate geometry from the as-of snapshot ==")
    for record in decisions:
        print(f"  {record['scenario']:34s} idx={record['index']:6d} barrier={record['barrier']}")
        print(f"    need={record['need']} tier1={record['tier1']} deficit={record['deficit']}")
        for row in record["rows"]:
            flag = []
            if row["suffix_is_victim_count"]:
                flag.append("suffix==victims")
            if row["suffix_equals_deficit"]:
                flag.append("suffix==deficit")
            print(
                f"    {row['program'][:26]:28s} N={row['n_eligible']:5d} m={row['m']:5d} "
                f"victims={row['victims']:3d} d_min={row['d_min']:4d} "
                f"S={row['suffix']:4d} q={row['q']:.6f} prefill={row['prefill']:.6f}"
            )
            print(
                f"    {'':28s} proxy={row['proxy']:.6f} literal={row['literal']:12.4f}"
                f"{'  [' + ','.join(flag) + ']' if flag else ''}"
            )
    print()

    # ------------------------------------------------------------- rule compare
    print("== 2. rule comparison, with A0 defined as its real Entry rule ==")
    print("  A0 release key = (deadline, min native rank over newly eligible, identity)")
    print("  MinOvershoot   = (N_i, identity)")
    print("  EarliestDL     = (deadline, identity)")
    print("  proxy rule     = (proxy, deadline, identity)")
    print()
    agreement = defaultdict(int)
    scorable = [r for r in decisions if r["rows"] and not r["unscorable"]]
    for record in scorable:
        rows = record["rows"]
        a0 = min(
            rows,
            key=lambda r: (
                r["deadline"],
                r["coldest_newly_eligible_rank"],
                r["program"],
            ),
        )["program"]
        overshoot = min(rows, key=lambda r: (r["n_eligible"], r["program"]))["program"]
        earliest = min(rows, key=lambda r: (r["deadline"], r["program"]))["program"]
        proxy = min(rows, key=lambda r: (r["proxy"], r["deadline"], r["program"]))["program"]
        actual = record["released"][0] if record["released"] else None
        picks = {
            "A0_deadline_rule": a0,
            "min_overshoot": overshoot,
            "earliest_deadline": earliest,
            "proxy_rule": proxy,
        }
        for name, pick in picks.items():
            if pick == actual:
                agreement[name] += 1
        print(f"  {record['scenario']:34s} idx={record['index']:6d}")
        print(f"    A1 released     {str(actual)[:34]}")
        for name, pick in picks.items():
            mark = "  <- differs" if pick != actual else ""
            print(f"    {name:16s} {pick[:34]}{mark}")
    print()
    print(f"  agreement with A1's own release over {len(scorable)} scorable decisions:")
    for name in ("A0_deadline_rule", "min_overshoot", "earliest_deadline", "proxy_rule"):
        print(f"    {name:18s} {agreement[name]} / {len(scorable)}")
    print()

    # Pairwise: the question that matters is proxy vs A0, not proxy vs A1.
    print("== 2b. pairwise rule agreement (the discriminating question) ==")
    picks_by_decision = []
    for record in scorable:
        rows = record["rows"]
        picks_by_decision.append(
            {
                "A0": min(
                    rows,
                    key=lambda r: (
                        r["deadline"],
                        r["coldest_newly_eligible_rank"],
                        r["program"],
                    ),
                )["program"],
                "overshoot": min(rows, key=lambda r: (r["n_eligible"], r["program"]))["program"],
                "proxy": min(rows, key=lambda r: (r["proxy"], r["deadline"], r["program"]))[
                    "program"
                ],
            }
        )
    for left in ("A0", "overshoot"):
        agree = sum(1 for p in picks_by_decision if p[left] == p["proxy"])
        print(f"  proxy vs {left:10s} {agree} / {len(picks_by_decision)}")
    print(
        "  0 disagreements with A0 means this workload cannot separate the proxy "
        "from the deadline rule."
    )
    print()

    # --------------------------------------------------------- cross-arm compare
    print("== 3. cross-arm release per barrier (matched by boundary_id, not by index) ==")
    for scenario in sorted(by_scenario):
        barriers = {}
        for arm in ("a0", "a1", "a2"):
            events = by_scenario[scenario].get(arm)
            if events is None:
                continue
            mapping, problems = barrier_for(events)
            if problems:
                print(f"  {scenario} {arm.upper()}: excluded, barrier alignment failed")
                for problem in problems:
                    print(f"    {problem}")
                continue
            chosen = {}
            for event in events:
                if event["event_type"] != FORCED:
                    continue
                index = int(event["event_index"])
                barrier = mapping.get(index, "<unmatched>")
                released = [
                    str(r["program_id"]) for r in event["payload"].get("selected_releases") or []
                ]
                chosen[barrier] = released
            barriers[arm] = chosen
        for barrier in sorted({b for arm in barriers for b in barriers[arm]}):
            row = {arm: barriers[arm].get(barrier, ["-"]) for arm in barriers}
            distinct = {tuple(v) for v in row.values()}
            tag = "AGREE" if len(distinct) == 1 else "DIFFER"
            print(f"  {scenario:34s} {barrier:26s} {tag}")
            for arm in sorted(row):
                print(f"    {arm.upper()} {row[arm]}")
    print()

    # ------------------------------------------------------- evidence grading (RC7)
    print("== 3b. physical evidence grading (RC7) ==")
    print("  Four distinct claims, not to be conflated:")
    print("    L1 predicted victims    -- computed here from tier/rank; a PREDICTION")
    print("    L2 native eviction      -- BLOCK_EVICTED events actually RECORDED")
    print("    L3 content attribution  -- per-block identity join L1 <-> L2, only")
    print("                               meaningful inside the pressure episode that")
    print("                               the release caused")
    print("    L4 recompute consequence-- downstream APC/recompute, NOT observable here")
    print()
    print("  Two joins are available and only one of them is admissible:")
    print("    (a) join against ALL BLOCK_EVICTED ids in the whole run. This is")
    print("        TAUTOLOGICAL and must not be reported as attribution: a long run")
    print("        evicts thousands of blocks, so every predicted block is 'found'")
    print("        eventually no matter which candidate was selected.")
    print("    (b) join against the recorded last_selected_block_ids of the pressure")
    print("        episode in the same window. This is a direct record of what the")
    print("        native path selected, so it is the only admissible join -- but it")
    print("        is only available where that callback actually fired per episode.")
    print()
    for scenario in sorted(by_scenario):
        events = by_scenario[scenario]["a1"]
        evicted_ids = [
            int(event["payload"]["block_id"])
            for event in events
            if event["event_type"] == "BLOCK_EVICTED"
        ]
        print(f"  {scenario}")
        print(f"    L2 eviction events recorded          {len(evicted_ids)}")
        print(f"    L2 distinct evicted block ids        {len(set(evicted_ids))}")
        recorded_selections = _recorded_selections(events)
        print(f"    L2 pressure-completion callbacks     {len(recorded_selections)}")
        for episode, event in enumerate([e for e in events if e["event_type"] == FORCED], start=1):
            payload = event["payload"]
            queue = payload["original_free_queue"]
            need = int(payload["required_blocks"])
            rank_of = {row["block_id"]: row["native_lru_rank"] for row in queue}
            tier1 = [row["block_id"] for row in queue if row["eligibility_tier"] == 0]
            deficit = max(0, need - len(tier1))
            released = [str(r["program_id"]) for r in payload.get("selected_releases") or []]
            chosen = None
            for cand in payload["candidates"]:
                if str(cand["program_id"]) in released:
                    chosen = cand
            if chosen is None:
                continue
            # Full eligibility-rule prediction: TIER_1 by rank first, then the
            # released entry's reclaimable blocks by rank, until `need` is met.
            tier1_by_rank = sorted(tier1, key=lambda b: rank_of[b])
            reclaimable = [b for b in chosen["initially_reclaimable_block_ids"] if b in rank_of]
            reclaimable.sort(key=lambda b: rank_of[b])
            predicted = set(tier1_by_rank[:need]) | set(reclaimable[:deficit])
            naive = predicted & set(evicted_ids)
            recorded = recorded_selections.get(episode)
            if recorded is None:
                grade = "L3 UNAVAILABLE (no per-episode selection callback)"
                detail = ""
            elif predicted == recorded:
                grade = "L3 EXACT"
                detail = f"({len(predicted)}/{len(recorded)})"
            else:
                grade = "L3 DISJOINT/STALE"
                detail = (
                    f"(pred {len(predicted)} vs rec {len(recorded)}, "
                    f"inter {len(predicted & recorded)})"
                )
            print(
                f"    ep{episode} idx={event['event_index']:6d} need={need:4d} "
                f"|tier1|={len(tier1):3d} L1 predicted={len(predicted):4d}"
            )
            print(f"      naive whole-run overlap {len(naive):4d}  <-- NOT attribution")
            print(f"      {grade} {detail}")
        print("    L4 recompute consequence            NOT OBSERVABLE in this archive")
        print()

    # ------------------------------------------------------- degeneracy summary
    print("== 4. when does the proxy rule have depth information to use? ==")
    for record in scorable:
        rows = record["rows"]
        distinct_suffix = {r["suffix"] for r in rows}
        print(
            f"  {record['scenario']:34s} idx={record['index']:6d} "
            f"distinct_suffix={sorted(distinct_suffix)} "
            f"{'degenerate: suffix identical for all candidates' if len(distinct_suffix) == 1 else 'suffix differs across candidates'}"
        )
    print()

    # ------------------------------------------- structural headroom against A0
    print("== 5. could the proxy deviate from A0 at all, given the observed prefill? ==")
    print("  Lower bound on A = prefill * S/m is attained at S = victims: the suffix")
    print("  cannot be shorter than the number of blocks being evicted. So the best")
    print("  case a candidate can hope for is proxy_min = q * prefill * victims / m.")
    print()
    for record in scorable:
        rows = record["rows"]
        a0 = min(
            rows,
            key=lambda r: (r["deadline"], r["coldest_newly_eligible_rank"], r["program"]),
        )
        print(
            f"  {record['scenario']:34s} idx={record['index']:6d} "
            f"A0 picks {a0['program'][:26]} (proxy={a0['proxy']:.6f})"
        )
        for row in rows:
            if row["program"] == a0["program"]:
                continue
            floor = row["q"] * row["prefill"] * (row["victims"] / row["m"])
            possible = floor < a0["proxy"]
            print(
                f"    {row['program'][:26]:28s} deadline={row['deadline']:9.3f} "
                f"({'>' if row['deadline'] > a0['deadline'] else '<'} A0) "
                f"proxy_min={floor:.6f} "
                f"{'COULD deviate' if possible else 'cannot deviate even at S=victims'}"
            )
    # --------------------------------------- does prefill scale with chain length?
    print("== 6. is prefill proportional to m? (decides what the proxy really ranks) ==")
    print("  If prefill_X ~ c*m_X then L = q*prefill*S/m ~ c*q*S and the chain length")
    print("  cancels, leaving q times the suffix in blocks.")
    print()
    for record in scorable:
        print(f"  {record['scenario']:34s} idx={record['index']:6d}")
        per_block = []
        for row in record["rows"]:
            value = row["prefill"] / row["m"]
            per_block.append(value)
            print(
                f"    {row['program'][:26]:28s} prefill/m={value:.6f} "
                f"S={row['suffix']:4d} q={row['q']:.6f} "
                f"q*S={row['q'] * row['suffix']:9.4f} proxy={row['proxy']:.6f}"
            )
        if per_block:
            spread = max(per_block) / min(per_block) if min(per_block) > 0 else float("inf")
            print(f"    prefill/m spread max/min = {spread:.4f}")
    print()
    return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
