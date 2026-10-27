"""E1/E6 feasibility for an A1+ q-construction change.

Read-only. Nothing here alters the frozen A0/A1 decision function.

The three questions this has to answer, for each candidate signal:

1. is it obtainable **before** the entry release decision?
2. does it carry information that the deadline-derived ``q`` does not?
3. is it free of information leakage?

Definitions (stated because they are choices, not facts)
-------------------------------------------------------
For one content chain and a decision at time ``t``, using **only** observations with
timestamp < t:

``E1_hit_rate``
    over prior requests of the same chain, the fraction whose
    ``native_cached_prefix_tokens`` was > 0. A single prior request cannot express a
    rate and is reported separately.
``E1_last_outcome``
    the indicator of the most recent prior request. Defined with one prior
    observation, but structurally constant where that observation is the chain's
    first request.
``E6_blocks_per_turn``
    mean of ``blocks[i] - blocks[i-1]`` over prior consecutive observation pairs.
    Requires at least two prior observations.

Chain identity is ``program_id``: the native observation events do not carry
``prefix_id``, and the H1 materialization fixes one content per program anyway.
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path

H1_ROOT = "local/phase2a-h1-level-a-evidence-e3a02fd/artifacts/phase2a-h1-formal-level-a-runs-v1"
V10_ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/artifacts/"
    "continuum-native-cost-aware-bounded-runs-v10/runs"
)
TAU = 30.0
OBS = "VLLM_NATIVE_REQUEST_OBSERVATION"
SNAPSHOT = "VLLM_PREFIX_SNAPSHOT"
FORCED = "FORCED_RELEASE_DECISION"


def q_of(deadline: float, timestamp: float) -> float:
    """Frozen reuse proxy: sigmoid((deadline - t) / tau), tau = 30 s."""
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, (deadline - timestamp) / TAU))))


def describe(name: str, values: list[float], width: int = 26) -> None:
    if not values:
        print(f"  {name:{width}s} no samples")
        return
    ordered = sorted(values)
    distinct = len({round(v, 9) for v in ordered})
    print(
        f"  {name:{width}s} n={len(ordered):4d}  min={ordered[0]:.6f}  "
        f"median={statistics.median(ordered):.6f}  max={ordered[-1]:.6f}  "
        f"distinct={distinct}"
    )


def load_runs(root: str) -> list[tuple[str, list[dict]]]:
    runs = []
    for path in sorted(glob.glob(os.path.join(root, "*", "events.jsonl"))):
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        runs.append((os.path.basename(os.path.dirname(path)), events))
    return runs


def chain_observations(events: list[dict]) -> dict[str, list[dict]]:
    """Per-program realized-request timeline (observations carry no prefix_id)."""
    table: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event["event_type"] != OBS:
            continue
        payload = event["payload"]
        table[str(event.get("program_id"))].append(
            {
                "timestamp": float(event["timestamp"]),
                "cached": int(payload.get("native_cached_prefix_tokens") or 0),
                "prompt": int(payload.get("native_prompt_tokens") or 0),
                "blocks": len(payload.get("native_apc_block_hashes") or []),
            }
        )
    return table


def chain_snapshots(events: list[dict]) -> dict[str, list[dict]]:
    table: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event["event_type"] != SNAPSHOT:
            continue
        table[str(event.get("program_id"))].append(
            {
                "timestamp": float(event["timestamp"]),
                "blocks": len(event["payload"].get("block_ids") or []),
            }
        )
    return table


def before(series: list[dict], timestamp: float) -> list[dict]:
    return [row for row in series if row["timestamp"] < timestamp]


def e1_hit_rate(history: list[dict]) -> float | None:
    if len(history) < 2:
        return None
    return sum(1 for row in history[1:] if row["cached"] > 0) / (len(history) - 1)


def e6_blocks_per_turn(series: list[dict]) -> float | None:
    if len(series) < 3:
        return None
    deltas = [series[i]["blocks"] - series[i - 1]["blocks"] for i in range(1, len(series))]
    return sum(deltas) / len(deltas)


def part_a(runs: list[tuple[str, list[dict]]]) -> None:
    print("== A. what the available data supports ==")
    cached = 0
    per_program_turns: Counter[int] = Counter()
    first_turn_hits = Counter()
    eligible_hits = Counter()
    for _name, events in runs:
        turns: Counter[str] = Counter()
        obs = chain_observations(events)
        for event in events:
            if event["event_type"] == "TURN_FINISHED":
                turns[str(event.get("program_id"))] += 1
            elif event["event_type"] == OBS:
                cached += 1
        for values in turns.values():
            per_program_turns[values] += 1
        for series in obs.values():
            if not series:
                continue
            first_turn_hits[series[0]["cached"] > 0] += 1
            for row in series[1:]:
                eligible_hits[row["cached"] > 0] += 1
    print(f"  native APC observations                   {cached}")
    print(f"  turns per program (all 126 runs)          {sorted(per_program_turns.items())}")
    print(f"  first request of a chain: reused?         {dict(first_turn_hits)}")
    print(f"  later requests: reused?                   {dict(eligible_hits)}")
    print("  first requests never hit, by construction: nothing existed to reuse.")
    print()


def part_b(runs: list[tuple[str, list[dict]]]) -> None:
    print("== B. decision-time state actually recorded ==")
    decisions = 0
    multi = 0
    candidates = 0
    elapsed: list[float] = []
    qs: list[float] = []
    blocks: list[float] = []
    waiting = Counter()
    prior_counts: Counter[int] = Counter()

    for _name, events in runs:
        obs = chain_observations(events)
        for event in events:
            if event["event_type"] != FORCED:
                continue
            decisions += 1
            timestamp = float(event["timestamp"])
            pool = event["payload"].get("candidates") or []
            if len(pool) > 1:
                multi += 1
            for candidate in pool:
                candidates += 1
                key = str(candidate["program_id"])
                prior_counts[len(before(obs.get(key, []), timestamp))] += 1
                elapsed.append(float(candidate.get("elapsed_since_ttl_decision_seconds") or 0.0))
                qs.append(q_of(float(candidate["retention_deadline_timestamp"]), timestamp))
                blocks.append(float(len(candidate["block_ids"])))
                waiting[str(candidate.get("waiting_followup"))] += 1

    print(f"  entry decisions                           {decisions}")
    print(f"  decisions with more than one candidate    {multi}")
    print(f"  candidate rows                            {candidates}")
    print(f"  prior same-chain observations per row     {sorted(prior_counts.items())}")
    print(f"  waiting_followup                          {dict(waiting)}")
    describe("elapsed since TTL decision", elapsed)
    describe("q = sigmoid((deadline-t)/30)", qs)
    describe("candidate block count", blocks)
    if qs:
        print(f"  q dynamic range                           {max(qs) - min(qs):.6f}")
        print("  the decision happens within seconds of the TTL decision, so q sits in a")
        print("  narrow band just below 0.5 and its ordering is nearly flat; the score is")
        print("  dominated by the block count unless a signal with real variance is added.")
    print()


def part_c(runs: list[tuple[str, list[dict]]]) -> None:
    print("== C. E1 / E6 availability at the recorded decisions ==")
    e1_rate = 0
    e1_last = 0
    e6 = 0
    candidates = 0
    e1_last_values: list[float] = []
    e1_values: list[float] = []
    e6_values: list[float] = []
    q_pairs: list[tuple[float, float]] = []
    decisions_with_e1 = 0
    for _name, events in runs:
        obs = chain_observations(events)
        snaps = chain_snapshots(events)
        decisions = 0
        for event in events:
            if event["event_type"] != FORCED:
                continue
            decisions += 1
            timestamp = float(event["timestamp"])
            defined_here = 0
            for candidate in event["payload"].get("candidates") or []:
                candidates += 1
                key = str(candidate["program_id"])
                history = before(obs.get(key, []), timestamp)
                merged = sorted(
                    before(obs.get(key, []), timestamp) + before(snaps.get(key, []), timestamp),
                    key=lambda row: row["timestamp"],
                )
                rate = e1_hit_rate(history)
                if rate is not None:
                    e1_rate += 1
                    defined_here += 1
                    e1_values.append(rate)
                    q_pairs.append(
                        (
                            q_of(float(candidate["retention_deadline_timestamp"]), timestamp),
                            rate,
                        )
                    )
                if history:
                    e1_last += 1
                    e1_last_values.append(1.0 if history[-1]["cached"] > 0 else 0.0)
                per_turn = e6_blocks_per_turn(merged)
                if per_turn is not None:
                    e6 += 1
                    e6_values.append(per_turn)
            decisions_with_e1 += int(defined_here > 0)
        del decisions
    print(f"  candidate rows                            {candidates}")
    print(f"  decisions with at least one E1             {decisions_with_e1}")
    print(f"  E1_hit_rate defined (>=2 prior requests)  {e1_rate}")
    print(f"  E1_last_outcome defined (>=1 prior)       {e1_last}")
    describe("E1_last_outcome values", e1_last_values)
    describe("E1_hit_rate values", e1_values)
    print(f"  E6_blocks_per_turn defined (>=2 prior)    {e6}")
    describe("E6_blocks_per_turn values", e6_values)
    if q_pairs:
        print(
            f"  E1 distinct where defined                 "
            f"{sorted({round(row[1], 6) for row in q_pairs})}"
        )
    print()
    print("  timing is the binding constraint, not instrumentation: 432 of 471 rows have")
    print("  exactly one prior request, and that request is the chain's first, which cannot")
    print("  be a reuse. Only the 39 rows from runs whose pressure fires after a second")
    print("  turn have a realized reuse event to read.")
    print("  every one of those 39 values is 1.0, so the window is censored rather than the")
    print("  signal being uninformative: a chain reaches two prior observations only before")
    print("  pressure reaches it, and before pressure nothing is evicted, so that second")
    print("  request always hits. Once pressure starts, the decision fires before the next")
    print("  request, so no further observation is ever available.")
    print()


def part_d(runs: list[tuple[str, list[dict]]]) -> None:
    print("== D. if a history did exist, would it discriminate? ==")
    patterns: Counter[tuple] = Counter()
    within_two: Counter[tuple] = Counter()
    hits_by_prior = Counter()
    for _name, events in runs:
        obs = chain_observations(events)
        chains = [series for series in obs.values() if len(series) >= 3]
        if not chains:
            continue
        patterns[
            tuple(tuple(1 if row["cached"] > 0 else 0 for row in series) for series in chains)
        ] += 1
        if len(chains) >= 2:
            outcomes = tuple(1 if series[1]["cached"] > 0 else 0 for series in chains)
            within_two[outcomes] += 1
        for series in chains:
            prior = 1 if series[1]["cached"] > 0 else 0
            following = 1 if series[2]["cached"] > 0 else 0
            hits_by_prior[(prior, following)] += 1

    total_chains = sum(
        sum(len(series) >= 3 for series in chain_observations(events).values())
        for _n, events in runs
    )
    print(f"  chains with at least three turns          {total_chains}")
    print(
        "  runs whose 3-turn chains agree exactly    "
        f"{sum(v for k, v in patterns.items() if len(set(k)) == 1)} / {sum(patterns.values())}"
    )
    print(f"  turn2 -> turn3 outcome pairs              {sorted(hits_by_prior.items())}")
    for prior in sorted({key[0] for key in hits_by_prior}):
        total = sum(count for (p, _f), count in hits_by_prior.items() if p == prior)
        hits = sum(count for (p, f), count in hits_by_prior.items() if p == prior and f == 1)
        print(f"    P(turn3 reused | turn2 reused={prior})    {hits}/{total} = {hits / total:.3f}")
    print("  the contrast is confounded: chains inside one run usually share a pattern,")
    print("  so what looks like chain-level persistence is mostly the run's pressure")
    print("  level plus the universal first-turn miss. It cannot be read as an")
    print("  independent per-chain propensity without a within-run contrast.")
    print()


def part_c2(runs: list[tuple[str, list[dict]]]) -> None:
    """Within-decision variation and an ordering test, where E1 is defined."""
    print("== C2. can E1 reorder a decision? ==")
    usable = 0
    varying = 0
    changed_replacement = 0
    changed_blend = 0
    examples = []
    for name, events in runs:
        obs = chain_observations(events)
        for event in events:
            if event["event_type"] != FORCED:
                continue
            timestamp = float(event["timestamp"])
            rows = []
            for candidate in event["payload"].get("candidates") or []:
                key = str(candidate["program_id"])
                history = before(obs.get(key, []), timestamp)
                rate = e1_hit_rate(history)
                if rate is None:
                    continue
                rows.append(
                    (
                        key,
                        rate,
                        q_of(float(candidate["retention_deadline_timestamp"]), timestamp),
                        float(len(candidate["block_ids"])),
                    )
                )
            if len(rows) < 2:
                continue
            usable += 1
            if len({round(row[1], 9) for row in rows}) > 1:
                varying += 1
            base = min(rows, key=lambda row: (row[2] * row[3], row[0]))[0]
            replaced = min(rows, key=lambda row: (row[1] * row[3], row[0]))[0]
            blended = min(rows, key=lambda row: ((0.5 * row[2] + 0.5 * row[1]) * row[3], row[0]))[0]
            changed_replacement += int(replaced != base)
            changed_blend += int(blended != base)
            if len(examples) < 4:
                examples.append(
                    (name, [(r[0], r[1], round(r[2], 5), r[3]) for r in rows], base, replaced)
                )

    print(f"  decisions with >=2 candidates carrying E1  {usable}")
    print(f"  ... where E1 differs across candidates     {varying}")
    print(f"  ... argmin changes under q' = E1           {changed_replacement}")
    print(f"  ... argmin changes under q' = q/2 + E1/2   {changed_blend}")
    for example in examples:
        print(f"    {example[0][:40]:42s} base={example[2]} E1only={example[3]}")
        print(f"      rows (program, E1, q, blocks): {example[1]}")
    print()


def part_e() -> None:
    print("== E. E6 variance ==")
    root = Path(H1_ROOT)
    per_chain: Counter[tuple] = Counter()
    for path in sorted(root.glob("*/events.jsonl")):
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for series in chain_snapshots(events).values():
            blocks = tuple(row["blocks"] for row in series)
            if len(blocks) > 1:
                per_chain[tuple(blocks[i] - blocks[i - 1] for i in range(1, len(blocks)))] += 1
    print(f"  H1 per-chain block deltas                 {sorted(per_chain.items())[:6]}")
    print("  every delta is 0: one content per program, no accumulation of model output.")
    print()

    v10: dict[tuple[str, str], list[tuple[float, int]]] = defaultdict(list)
    for name, events in load_runs(V10_ROOT):
        for event in events:
            if event["event_type"] != SNAPSHOT:
                continue
            v10[(name, str(event.get("program_id")))].append(
                (float(event["timestamp"]), len(event["payload"].get("block_ids") or []))
            )
    deltas = []
    for series in v10.values():
        series.sort()
        deltas.extend(series[i][1] - series[i - 1][1] for i in range(1, len(series)))
    describe("v10 per-turn block delta", [float(d) for d in deltas])
    print("  the v10 delta is prescribed by the replay materializer (a linear ramp),")
    print("  so an E6 fitted here would describe the generator, not the workload.")
    print()


def part_f() -> None:
    print("== F. geometric mean and lambda are not the bottleneck ==")
    print("  ordering by sqrt(q * N) equals ordering by q * N, because the square root")
    print("  is strictly monotone; the geometric mean is a relabelling, not a new rule.")
    print("  a weighted geometric mean q^w * N^(1-w) is the same as comparing")
    print("  w*log q + (1-w)*log N, i.e. it re-scales the two terms. With q compressed")
    print("  into a band of width ~0.03 the re-scaling mostly moves the score along the")
    print("  N axis, so it changes lambda's role without adding information.")
    print()


def part_g() -> None:
    print("== G. leakage rules a candidate must satisfy ==")
    rules = [
        "compute from observations with timestamp < t only",
        "never read the current request's own cached-token outcome",
        "never reconstruct is_terminal or the trace's future turns",
        "never pool across runs unless the workload repeats the same trace, which",
        "  makes cross-run history a copy of the answer",
        "apply the identical feature to every arm, including A0",
        "log the feature value at decision time so coverage stays auditable",
    ]
    for rule in rules:
        print(f"  - {rule}")
    print()


def main() -> int:
    runs = load_runs(H1_ROOT)
    print(f"H1 runs loaded: {len(runs)}")
    print()
    part_a(runs)
    part_b(runs)
    part_c(runs)
    part_c2(runs)
    part_d(runs)
    part_e()
    part_f()
    part_g()
    print("== H. verdict ==")
    print("  E1  obtainable, but coverage at the recorded decisions is 39/471 (8.3%),")
    print("      and for the other 432 the only prior request is the chain's first,")
    print("      which is always a miss, so E1 carries no variation there.")
    print("  E6  not evaluable on any dataset here: H1 variance is exactly zero and")
    print("      v10 variance is prescribed by the materializer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
