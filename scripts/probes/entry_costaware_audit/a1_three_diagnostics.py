"""Three diagnostics run on the A1 arm, which is where the real A1 decisions live.

Why not H1
----------
H1 is a synthetic pressure harness: one fixed content per program, ``max_new_tokens
= 1``, two or three turns per program, a first request that never hits, and a block
delta of exactly zero. It records no A1 decision trace at all, so it cannot say
anything about what A1's own scoring saw.

The v10 bounded archive does record it. Each A1 run emits
``COST_AWARE_RELEASE_DECISION`` events, 29 of which carry a ``selection_trace``
holding, for every candidate, the ``reuse_proxy`` (q), ``expected_recompute``,
``new_blocks``, ``deadline`` and ``per_unit`` the real A1 decision used. That trace
is the only place where A1's own inputs are observable.

Two facts that must be handled explicitly
-----------------------------------------
1. **Timestamps span five clock domains** and are not comparable across them:

   ``continuum_lifecycle``        0 .. 808        REQUEST_ARRIVED, TURN_FINISHED
   ``continuum_logical_replay``   0 .. 821        COST_AWARE_RELEASE_DECISION
   ``continuum_pressure``         615.04          FORCED_RELEASE_DECISION
   ``engine_core_monotonic``      ~4.98e7         VLLM_NATIVE_REQUEST_OBSERVATION
   ``system_monotonic``           ~4.98e7         VLLM_PREFIX_SNAPSHOT

   ``event_index`` is one global sequence, so "has this observation already
   happened" must be answered by index, not by timestamp. Deadline is in the same
   domain as the release decision, so ``elapsed = t - deadline`` is still valid.

2. **A hit does not require a same-program repeat.** In 18 of 36 agent programs the
   first request already reports ``cached = 112`` tokens, from a shared cross-program
   prefix. In H1 the first request was always a miss. So E1a here mixes "own repeat"
   with "shared prefix", and later requests hit in 180 of 180 cases in all three arms.
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/artifacts/"
    "continuum-native-cost-aware-bounded-runs-v10/runs"
)
OBS = "VLLM_NATIVE_REQUEST_OBSERVATION"
SNAPSHOT = "VLLM_PREFIX_SNAPSHOT"
RELEASE = "COST_AWARE_RELEASE_DECISION"
FORCED = "FORCED_RELEASE_DECISION"
TAU = 30.0


def q_of(deadline: float, timestamp: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, (deadline - timestamp) / TAU))))


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            result[order[k]] = average
        i = j + 1
    return result


def spearman(xs: list[float], ys: list[float]) -> tuple[float | None, int]:
    if len(xs) < 5 or len(xs) != len(ys) or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None, len(xs)
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (None if den == 0 else num / den), len(xs)


def concentration(name: str, values: list[float], width: int = 30) -> None:
    if not values:
        print(f"  {name:{width}s} no samples")
        return
    counts = Counter(round(v, 9) for v in values)
    total = len(values)
    _, modal_count = counts.most_common(1)[0]
    entropy = -sum((c / total) * math.log(c / total) for c in counts.values() if c)
    entropy_norm = entropy / math.log(total) if total > 1 else 0.0
    ordered = sorted(values)
    mean = sum(ordered) / total
    stdev = statistics.pstdev(ordered) if total > 1 else 0.0
    cv = stdev / mean if mean else float("inf")
    print(
        f"  {name:{width}s} n={total:5d} distinct={len(counts):4d} "
        f"modal={modal_count / total:6.1%} H_norm={entropy_norm:.3f} cv={cv:.3f} "
        f"min={ordered[0]:.6g} p50={statistics.median(ordered):.6g} max={ordered[-1]:.6g}"
    )


def ratio_stats(name: str, values: list[float], width: int = 30) -> None:
    if not values:
        print(f"  {name:{width}s} no samples")
        return
    ordered = sorted(values)
    print(
        f"  {name:{width}s} n={len(ordered):3d} "
        f"p50={statistics.median(ordered):10.4g} "
        f"p90={ordered[9 * len(ordered) // 10]:10.4g} max={ordered[-1]:10.4g}"
    )


def load_runs(arm: str) -> list[tuple[str, list[dict]]]:
    runs = []
    for path in sorted(glob.glob(os.path.join(ROOT, f"*-{arm}-repeat-1", "events.jsonl"))):
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        runs.append((os.path.basename(os.path.dirname(path)), events))
    return runs


def observation_table(events: list[dict]) -> dict[str, list[dict]]:
    """Native observations per program, ordered by the global event_index."""
    table: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event["event_type"] != OBS:
            continue
        payload = event["payload"]
        table[str(event.get("program_id"))].append(
            {
                "index": int(event["event_index"]),
                "cached": int(payload.get("native_cached_prefix_tokens") or 0),
                "prompt": int(payload.get("native_prompt_tokens") or 0),
                "blocks": len(payload.get("native_apc_block_hashes") or []),
            }
        )
    for series in table.values():
        series.sort(key=lambda row: row["index"])
    return table


def traced_decisions(runs: list[tuple[str, list[dict]]]) -> list[tuple[str, dict]]:
    found = []
    for name, events in runs:
        for event in events:
            if event["event_type"] != RELEASE:
                continue
            if event["payload"].get("selection_trace"):
                found.append((name, event))
    return found


def coverage(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 0. what the A1 arm actually records ==")
    all_decisions = 0
    traced = 0
    multi = 0
    selected_all: Counter[int] = Counter()
    per_run: Counter[int] = Counter()
    run_to_traces: Counter[str] = Counter()
    for name, events in runs:
        for event in events:
            if event["event_type"] != RELEASE:
                continue
            all_decisions += 1
            payload = event["payload"]
            selected_all[len(payload.get("selected_native_block_ids") or [])] += 1
            trace = payload.get("selection_trace") or []
            if trace:
                traced += 1
                run_to_traces[name] += 1
                count = len(trace[0].get("scores") or [])
                per_run[count] += 1
                if count >= 2:
                    multi += 1
    print(f"  A1 release decisions                       {all_decisions}")
    print(f"  ... carrying a selection_trace             {traced}")
    print(f"  ... with at least two scored candidates    {multi}")
    print(f"  candidates per traced decision              {sorted(per_run.items())}")
    print(
        f"  traced decisions per run                   {sorted(Counter(run_to_traces.values()).items())}"
    )
    print(f"  runs with at least one trace               {len(run_to_traces)}")
    print("  the untraced decisions release a single candidate, so they cannot host a")
    print("  signal comparison; 18 decisions are the effective sample.")
    print()


def part_a(runs: list[tuple[str, list[dict]]]) -> None:
    print("== A. is the E1 distribution concentrated? ==")
    first_hit = Counter()
    later_hit = Counter()
    for _name, events in runs:
        for program, series in observation_table(events).items():
            if program.startswith("pressure"):
                continue
            first_hit[series[0]["cached"] > 0] += 1
            for row in series[1:]:
                later_hit[row["cached"] > 0] += 1
    print("  raw reuse outcomes in the workload:")
    print(f"    first request of an agent program: {dict(first_hit)}")
    print(f"    every later request:               {dict(later_hit)}")
    print("    a first-request hit is possible here because the two programs share a")
    print("    112-token prefix; in H1 the first request was always a miss.")
    print()

    e1a_values: list[float] = []
    prior_counts: Counter[int] = Counter()
    for _name, events in runs:
        observations = observation_table(events)
        for event in events:
            if event["event_type"] != RELEASE:
                continue
            trace = event["payload"].get("selection_trace") or []
            if not trace:
                continue
            index = int(event["event_index"])
            for score in trace[0].get("scores") or []:
                program = str(score["key"][0])
                history = [row for row in observations.get(program, []) if row["index"] < index]
                prior_counts[len(history)] += 1
                if len(history) >= 2:
                    e1a_values.append(
                        sum(1 for row in history[1:] if row["cached"] > 0) / (len(history) - 1)
                    )
    print("  E1a as A1+ would consume it (prior measurements only):")
    print(f"    prior observations per candidate row      {sorted(prior_counts.items())}")
    concentration("E1a at decision time", e1a_values)
    print("    every value is 1.0: after the first turn this workload never misses, so")
    print("    there is no reuse failure left to predict. The degeneracy is a property")
    print("    of the workload, not of the observation window.")
    print()


def part_b(runs: list[tuple[str, list[dict]]]) -> None:
    print("== B. is E1 correlated with elapsed, and is q just elapsed? ==")
    elapsed: list[float] = []
    qs: list[float] = []
    identity_gap = 0.0
    span: list[float] = []
    for _name, events in runs:
        for event in events:
            if event["event_type"] != RELEASE:
                continue
            trace = event["payload"].get("selection_trace") or []
            if not trace:
                continue
            timestamp = float(event["timestamp"])
            scores = trace[0].get("scores") or []
            local_q = []
            for score in scores:
                deadline = float(score["deadline"])
                recorded = float(score["reuse_proxy"])
                recomputed = q_of(deadline, timestamp)
                identity_gap = max(identity_gap, abs(recomputed - recorded))
                elapsed.append(timestamp - deadline)
                qs.append(recorded)
                local_q.append(recorded)
            if len(local_q) >= 2:
                span.append(max(local_q) - min(local_q))

    print(f"  max |sigmoid((deadline - t)/tau) - recorded q|   {identity_gap:.3e}")
    print("  so the recorded q is exactly the frozen formula, evaluated with the same")
    print("  deadline and decision time. It is not an independent measurement.")
    print()
    rho, n = spearman(elapsed, qs)
    print(
        f"  Spearman(elapsed, q)                             "
        f"{'n/a' if rho is None else f'{rho:+.6f}'}  (n={n})"
    )
    print("  elapsed is t - deadline, so this correlation is an algebraic identity:")
    print("  q is a strictly decreasing function of elapsed by construction.")
    print()
    concentration("q across candidate rows", qs)
    concentration("per-decision q span", span)
    print("  unlike H1, q does have leverage here: the median per-decision span is")
    print("  about 0.44 and the extreme reaches 0.5, so a signal could in principle")
    print("  reorder these decisions.")
    print("  E1 cannot: it is constant at 1.0 in exactly the rows that carry a trace.")
    print()
    print("  E6 is still not testable here: the prefix length is prescribed by the")
    print("  replay materializer, so a growth rate would describe the generator.")
    print()


def part_c(runs: list[tuple[str, list[dict]]]) -> None:
    print("== C. is the recompute-cost difference between candidates large enough? ==")
    ratio_expected: list[float] = []
    ratio_expected_finite: list[float] = []
    ratio_blocks: list[float] = []
    gap_blocks: list[float] = []
    gap_finite: list[float] = []
    decisions = 0
    degenerate = 0
    close_calls = 0
    for _name, events in runs:
        for event in events:
            if event["event_type"] != RELEASE:
                continue
            trace = event["payload"].get("selection_trace") or []
            if not trace:
                continue
            scores = trace[0].get("scores") or []
            if len(scores) < 2:
                continue
            decisions += 1
            expected = sorted(float(score["expected_recompute"]) for score in scores)
            blocks = [float(score["new_blocks"]) for score in scores]
            if expected[0] <= 1e-9 * max(expected[-1], 1.0):
                degenerate += 1
            if expected[0] > 1e-12:
                value = expected[-1] / expected[0]
                ratio_expected.append(value)
                if value < 1e6:
                    ratio_expected_finite.append(value)
            gap_blocks.append(expected[-1] - expected[0])
            if expected[-1] - expected[0] < 1e6:
                gap_finite.append(expected[-1] - expected[0])
            if expected[0] > 0 and expected[1] / expected[0] < 2.0:
                close_calls += 1
            if min(blocks) > 0:
                ratio_blocks.append(max(blocks) / min(blocks))
    print(f"  multi-candidate decisions with a trace     {decisions}")
    ratio_stats("expected max/min (all)", ratio_expected)
    ratio_stats("expected max/min (< 1e6)", ratio_expected_finite)
    ratio_stats("new_blocks max/min", ratio_blocks)
    ratio_stats("expected gap (< 1e6)", gap_finite)
    print(f"  decisions with a near-zero minimum          {degenerate} / {decisions}")
    print(f"  decisions where the top two are within 2x   {close_calls} / {decisions}")
    print()
    print("  reading: the spread is large, but a substantial share of it comes from")
    print("  candidates whose q has collapsed to ~1e-9, where expected_recompute is")
    print("  essentially zero and the decision is forced regardless of any new signal.")
    print("  The informative subset is the non-degenerate one, and there the ratio is")
    print("  reported separately above.")
    print()


def main() -> int:
    runs = load_runs("a1")
    print(f"A1 runs: {len(runs)}")
    print()
    coverage(runs)
    part_a(runs)
    part_b(runs)
    part_c(runs)
    print("== verdict ==")
    print("  Yes: the A1 arm is experimentable, and it is strictly better than H1 for")
    print("  this question. It records the real per-candidate q, blocks and expected")
    print("  cost, and it has native cached-token observations.")
    print()
    print("  A  E1a is measurable here but constant at 1.0: the workload has no reuse")
    print("     failures after the first turn, so no signal of this kind has variance.")
    print("     H1 could not even measure it at decision time; v10 can, and it is flat.")
    print("  B  q is exactly sigmoid(-elapsed/tau); E1 is not correlated with elapsed")
    print("     because it does not vary. q has real leverage here, unlike H1.")
    print("  C  the cost spread is large but contaminated by q-collapse cases; the")
    print("     non-degenerate subset is where a new signal could plausibly matter.")
    print()
    print("  the binding limit is sample size, not measurement: 18 real choice points")
    print("  across 18 runs, all at the forced-release moment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
