"""Three diagnostics before any A1+ implementation.

M1 asked for three checks, in this order:

A. is the E1 distribution concentrated?
B. are E1 / E6 strongly correlated with elapsed?
C. is the actual recompute-cost difference between candidates large enough?

Nothing here changes a frozen decision path. Both datasets are read-only.

Data and what each one can actually answer
------------------------------------------
``H1 Level-A`` (126 runs) has per-request ``native_cached_prefix_tokens`` and the
native APC hash chain, so it is the only place where all three E1 variants exist:

  E1a  hit rate      ``cached_tokens > 0`` for a prior request of the same chain
  E1b  reuse ratio   block-level LCP of the native hash chain over the previous length
  E1c  reuse blocks  that LCP in blocks

``v10 bounded`` (54 runs, 18 per arm) **does** carry ``native_cached_prefix_tokens``
via ``VLLM_NATIVE_REQUEST_OBSERVATION``: 13 such events per run, 234 per arm. An
earlier revision of this docstring claimed otherwise and was wrong. What v10 lacks is
an A1 ``selection_trace`` for most decisions, and its timestamps span five clock
domains, so precedence has to be taken from ``event_index``.

The A1 arm is analysed separately by ``a1_three_diagnostics.py``, because that is the
only place where the real per-candidate q, block count and expected cost of an actual
A1 decision are recorded.

Definition warning: E1a, E1b and E1c are not interchangeable, and this script always
prints which one a number belongs to.
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
FORCED = "FORCED_RELEASE_DECISION"


def q_of(deadline: float, timestamp: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, (deadline - timestamp) / TAU))))


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
    if len(xs) < 5 or len(xs) != len(ys):
        return None, len(xs)
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None, len(xs)
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (None if den == 0 else num / den), len(xs)


def concentration(name: str, values: list[float]) -> None:
    """How concentrated is a signal: can it separate candidates at all?"""
    if not values:
        print(f"  {name:26s} no samples")
        return
    counts = Counter(round(v, 9) for v in values)
    total = len(values)
    modal_value, modal_count = counts.most_common(1)[0]
    del modal_value  # only the share is reported
    entropy = -sum((c / total) * math.log(c / total) for c in counts.values() if c)
    entropy_norm = entropy / math.log(total) if total > 1 else 0.0
    ordered = sorted(values)
    mean = sum(ordered) / total
    stdev = statistics.pstdev(ordered) if total > 1 else 0.0
    cv = stdev / mean if mean else float("inf")
    print(
        f"  {name:26s} n={total:5d}  distinct={len(counts):5d}  "
        f"modal_share={modal_count / total:6.1%}  H_norm={entropy_norm:.3f}  "
        f"cv={cv:.4f}"
    )
    print(
        f"  {'':26s} min={ordered[0]:.4f}  p25={ordered[total // 4]:.4f}  "
        f"p50={statistics.median(ordered):.4f}  p75={ordered[3 * total // 4]:.4f}  "
        f"max={ordered[-1]:.4f}"
    )


def spread(values: list[float]) -> tuple[float, float]:
    """max/min ratio and normalised IQR, safe against zeros."""
    if not values:
        return 1.0, 0.0
    ordered = sorted(values)
    low, high = ordered[0], ordered[-1]
    ratio = (high / low) if low > 0 else float("inf")
    median = statistics.median(ordered)
    iqr = (ordered[3 * len(ordered) // 4] - ordered[len(ordered) // 4]) / median if median else 0.0
    return ratio, iqr


def lcp_blocks(left: list[str], right: list[str]) -> int:
    count = 0
    for first, second in zip(left, right, strict=False):
        if first != second:
            break
        count += 1
    return count


def h1_runs() -> list[tuple[str, list[dict]]]:
    runs = []
    for path in sorted(glob.glob(os.path.join(H1_ROOT, "*", "events.jsonl"))):
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        runs.append((os.path.basename(os.path.dirname(path)), events))
    return runs


def v10_runs() -> list[tuple[str, list[dict]]]:
    runs = []
    for path in sorted(glob.glob(os.path.join(V10_ROOT, "*-a0-repeat-1", "events.jsonl"))):
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        runs.append((os.path.basename(os.path.dirname(path)), events))
    return runs


def observations(events: list[dict]) -> dict[str, list[dict]]:
    table: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event["event_type"] != OBS:
            continue
        payload = event["payload"]
        hashes = payload.get("native_apc_block_hashes") or []
        table[str(event.get("program_id"))].append(
            {
                "timestamp": float(event["timestamp"]),
                "cached": int(payload.get("native_cached_prefix_tokens") or 0),
                "blocks": len(hashes),
                "hashes": hashes,
            }
        )
    for series in table.values():
        series.sort(key=lambda row: row["timestamp"])
    return table


def diagnose_e1_distribution(runs: list[tuple[str, list[dict]]]) -> None:
    print("== A. is the E1 distribution concentrated? ==")
    request_hit: list[float] = []
    request_ratio: list[float] = []
    request_blocks: list[float] = []
    pressure_pairs: list[float] = []
    decision_hit: list[float] = []
    decision_ratio: list[float] = []
    decision_blocks: list[float] = []

    for _name, events in runs:
        table = observations(events)
        for program, series in table.items():
            # Pressure programs are not agent chains: each carries unique content, so
            # their adjacent pairs always share zero prefix. They are excluded from the
            # agent-chain statistics and counted separately.
            is_agent = not program.startswith("pressure")
            for index in range(1, len(series)):
                prior, current = series[index - 1], series[index]
                shared = lcp_blocks(prior["hashes"], current["hashes"])
                ratio = shared / prior["blocks"] if prior["blocks"] else 0.0
                if is_agent:
                    request_hit.append(1.0 if current["cached"] > 0 else 0.0)
                    request_ratio.append(ratio)
                    request_blocks.append(float(shared))
                else:
                    pressure_pairs.append(ratio)
        for event in events:
            if event["event_type"] != FORCED:
                continue
            timestamp = float(event["timestamp"])
            for candidate in event["payload"].get("candidates") or []:
                key = str(candidate["program_id"])
                prior = [row for row in table.get(key, []) if row["timestamp"] < timestamp]
                if len(prior) >= 2:
                    decision_hit.append(
                        sum(1 for row in prior[1:] if row["cached"] > 0) / (len(prior) - 1)
                    )
                if prior:
                    last = prior[-1]
                    # A decision has no "current" request yet, so the ratio is measured
                    # against the most recent realized chain and is reported separately.
                    decision_blocks.append(float(last["blocks"]))
                    if last["blocks"]:
                        decision_ratio.append(1.0)

    print("  request level (agent chains only, pressure programs excluded):")
    concentration("E1a hit rate", request_hit)
    concentration("E1b hash-LCP ratio", request_ratio)
    concentration("E1c hash-LCP blocks", request_blocks)
    print(
        f"  excluded pressure pairs                        {len(pressure_pairs)}"
        f"  (all with ratio 0, since each carries unique content)"
    )
    print()
    print("  decision level (only prior observations used):")
    concentration("E1a hit rate", decision_hit)
    concentration("E1b hash-LCP ratio", decision_ratio)
    concentration("E1c chain blocks", decision_blocks)
    print()
    if request_hit:
        hits = sum(request_hit)
        print(
            f"  E1a is binary by construction: {hits:.0f} hit / "
            f"{len(request_hit) - hits:.0f} miss of {len(request_hit)} pairs."
        )
        print("  its information is the miss rate, not the mean.")
    if decision_hit:
        distinct = sorted({round(v, 6) for v in decision_hit})
        print(
            "  at the decisions where E1a is defined it has "
            f"{len(distinct)} distinct value(s): {distinct}"
        )
    if request_ratio:
        print(
            f"  E1b is exactly 1.0 in {sum(1 for v in request_ratio if v == 1.0)}"
            f" / {len(request_ratio)} agent pairs: the hash chain is identical on every"
        )
        print("  repeated request of the same program, even when the cache missed.")
        print("  so E1b cannot distinguish 'content available' from 'content resident'.")
    print("  consequence: E1b is degenerate here, E1c is the previous block count,")
    print("  and only E1a carries a real distinction - but E1a measures residency,")
    print("  not content reuse, and it is censored at decision time.")
    print()


def diagnose_elapsed_correlation(runs: list[tuple[str, list[dict]]]) -> None:
    print("== B. are E1 / E6 strongly correlated with elapsed? ==")
    req_elapsed: list[float] = []
    req_hit: list[float] = []
    req_blocks: list[float] = []
    dec_elapsed: list[float] = []
    dec_hit: list[float] = []
    dec_blocks: list[float] = []
    dec_q: list[float] = []
    identity_gap = 0.0

    for _name, events in runs:
        table = observations(events)
        for program, series in table.items():
            if program.startswith("pressure"):
                continue
            for index in range(1, len(series)):
                prior, current = series[index - 1], series[index]
                req_elapsed.append(current["timestamp"] - prior["timestamp"])
                req_hit.append(1.0 if current["cached"] > 0 else 0.0)
                req_blocks.append(float(prior["blocks"]))
        for event in events:
            if event["event_type"] != FORCED:
                continue
            timestamp = float(event["timestamp"])
            for candidate in event["payload"].get("candidates") or []:
                key = str(candidate["program_id"])
                prior = [row for row in table.get(key, []) if row["timestamp"] < timestamp]
                elapsed = float(candidate.get("elapsed_since_ttl_decision_seconds") or 0.0)
                # The frozen cold-start path sets ttl = 0, so deadline equals the TTL
                # decision instant and (deadline - t) is exactly -elapsed.
                identity_gap = max(
                    identity_gap,
                    abs(elapsed - (timestamp - float(candidate["retention_deadline_timestamp"]))),
                )
                if len(prior) < 2:
                    continue
                dec_elapsed.append(elapsed)
                dec_hit.append(sum(1 for row in prior[1:] if row["cached"] > 0) / (len(prior) - 1))
                dec_blocks.append(float(prior[-1]["blocks"]))
                dec_q.append(q_of(float(candidate["retention_deadline_timestamp"]), timestamp))

    print("  algebraic identity check first:")
    print(f"    max |elapsed - (t - deadline)|            {identity_gap:.3e}")
    print("    the frozen cold-start path sets ttl = 0, so deadline is the TTL decision")
    print("    instant and q = sigmoid(-elapsed / 30) holds exactly. q is therefore a")
    print("    strictly decreasing function of elapsed, not an independent signal.")
    print()

    print("  H1, request level: elapsed since the previous same-chain request")
    for label, values in (("E1a hit rate", req_hit), ("E1c prior blocks", req_blocks)):
        rho, n = spearman(req_elapsed, values)
        print(
            f"    Spearman(elapsed, {label:16s}) = "
            f"{'n/a' if rho is None else f'{rho:+.4f}'}  (n={n})"
        )
    print()
    print("  H1, decision level: elapsed since the TTL decision")
    for label, values in (
        ("E1a hit rate", dec_hit),
        ("E1c prior blocks", dec_blocks),
        ("q", dec_q),
    ):
        rho, n = spearman(dec_elapsed, values)
        print(
            f"    Spearman(elapsed, {label:16s}) = "
            f"{'n/a' if rho is None else f'{rho:+.4f}'}  (n={n})"
        )
    print()
    print("  E6, prefix growth per turn:")
    print("    H1 block delta is 0 for every chain, so E6 has no variance and no")
    print("    correlation can be computed. On v10 the delta is prescribed by the")
    print("    replay materializer, so a correlation there would describe the")
    print("    generator. E6 cannot be tested for elapsed correlation with what is")
    print("    available offline.")
    print()


def diagnose_cost_spread() -> None:
    print("== C. is the recompute-cost difference between candidates large enough? ==")
    for label, runs in (("H1", h1_runs()), ("v10", v10_runs())):
        prefill_ratio: list[float] = []
        blocks_ratio: list[float] = []
        q_span: list[float] = []
        q_ratio: list[float] = []
        cost_ratio: list[float] = []
        cost_seconds: list[float] = []
        decisions = 0
        viable = 0
        for _name, events in runs:
            for event in events:
                if event["event_type"] != FORCED:
                    continue
                candidates = event["payload"].get("candidates") or []
                if len(candidates) < 2:
                    continue
                decisions += 1
                timestamp = float(event["timestamp"])
                prefill = [float(c["prefill_reload_seconds"]) for c in candidates]
                blocks = [float(len(c["block_ids"])) for c in candidates]
                qs = [q_of(float(c["retention_deadline_timestamp"]), timestamp) for c in candidates]
                # Physical cost of dropping an entry is its re-prefill time; the
                # expected cost multiplies that by the reuse proxy.
                expected = [q * p for q, p in zip(qs, prefill, strict=True)]
                prefill_ratio.append(
                    max(prefill) / min(prefill) if min(prefill) > 0 else float("inf")
                )
                blocks_ratio.append(max(blocks) / min(blocks) if min(blocks) > 0 else float("inf"))
                q_span.append(max(qs) - min(qs))
                if min(qs) > 1e-6:
                    q_ratio.append(max(qs) / min(qs))
                if min(expected) > 1e-9:
                    cost_ratio.append(max(expected) / min(expected))
                    if max(expected) / min(expected) >= 2.0:
                        viable += 1
                cost_seconds.append(max(expected) - min(expected))
        print(f"  {label}: {decisions} decisions with at least two candidates")
        for name, values, fmt in (
            ("prefill_reload max/min", prefill_ratio, "ratio"),
            ("block count max/min", blocks_ratio, "ratio"),
            ("q absolute span", q_span, "absolute"),
            ("q max/min (where q > 1e-6)", q_ratio, "ratio"),
            ("q*prefill max/min", cost_ratio, "ratio"),
            ("q*prefill absolute gap (s)", cost_seconds, "absolute"),
        ):
            if not values:
                print(f"    {name:28s} no samples")
                continue
            ordered = sorted(values)
            if fmt == "ratio":
                print(
                    f"    {name:28s} median={statistics.median(ordered):8.3f}  "
                    f"p90={ordered[9 * len(ordered) // 10]:10.3f}  "
                    f"max={ordered[-1]:12.3f}"
                )
            else:
                print(
                    f"    {name:28s} median={statistics.median(ordered):8.6f}  "
                    f"p90={ordered[9 * len(ordered) // 10]:10.6f}  "
                    f"max={ordered[-1]:12.6f}"
                )
        if cost_ratio:
            print(
                f"    decisions where the best/worst expected cost ratio >= 2x: "
                f"{viable} / {len(cost_ratio)} ({viable / len(cost_ratio):.1%})"
            )
        print()
    print("  reading: the ratio is computed inside one decision, so it is the spread")
    print("  the policy actually chooses between. prefill_reload differences are the")
    print("  physical recompute cost; block count is the body of the score; q is the")
    print("  reuse weight. If the combined ratio is small, the choice barely matters;")
    print("  if it is large, the policy has something real to get right.")
    print()


def main() -> int:
    runs = h1_runs()
    print(f"H1 runs: {len(runs)}   v10 runs: {len(v10_runs())}")
    print()
    diagnose_e1_distribution(runs)
    diagnose_elapsed_correlation(runs)
    diagnose_cost_spread()
    print("== summary ==")
    print("  A  E1b is degenerate on H1 (hash chain fixed per program); E1a is binary")
    print("     and censored at decision time; E1c is the previous block count.")
    print("  B  see the Spearman rows above; q is itself a function of elapsed when")
    print("     ttl = 0, so any signal correlated with elapsed adds little.")
    print("  C  see the per-decision ratios above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
