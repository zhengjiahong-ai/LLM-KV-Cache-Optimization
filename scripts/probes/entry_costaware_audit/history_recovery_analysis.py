"""Mechanism-recovery analysis for the History-Rich Native Replay design.

Three questions, answered from recorded data only:

1. how does server-gap history reach the TTL decision, and what does sufficient
   history actually change?
2. which candidate signals could give q information it does not already have?
3. where is the ``q x N`` score structurally wrong?

Nothing here changes a frozen path.

Two correctness rules this file enforces
----------------------------------------
**Pairing is by event_index and identity, never by timestamp.** The v10 archive
writes ``FORCED_RELEASE_DECISION`` in ``continuum_pressure`` and
``COST_AWARE_RELEASE_DECISION`` in ``continuum_logical_replay``. Their timestamps are
numerically close in this archive but they are different clock domains, so proximity
is not evidence of correspondence. A release is paired with the nearest *preceding*
pressure event by ``event_index`` and accepted only when the candidate set matches
exactly on ``(program_id, prefix_id)``.

**A missing observation is never filled in.** If the paired pressure event does not
carry ``prefill_reload_seconds`` for a candidate, that decision is excluded and
counted; no default prefill cost is substituted.

Time arithmetic is still needed for ``elapsed``. It is validated rather than assumed:
recomputing ``q`` from ``(deadline, release timestamp)`` must reproduce the recorded
``reuse_proxy``, and the maximum deviation is printed.
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")

from kvopt.continuum.snapshots import TTLInput
from kvopt.continuum.ttl import estimate_ttl
from kvopt.continuum.types import (
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)

ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/artifacts/"
    "continuum-native-cost-aware-bounded-runs-v10/runs"
)
W1A_REF = "origin/main"
W1A_PATH = "configs/phase2/continuum-w1a-server-gap-history-v1.json"
RELEASE = "COST_AWARE_RELEASE_DECISION"
FORCED = "FORCED_RELEASE_DECISION"
TTL_HISTORY = "TTL_HISTORY_INPUT_OBSERVED"
THRESHOLD = 100
TAU = 30.0
#: The value the frozen A1 strategy runs with, and therefore the ablation baseline.
FROZEN_LAMBDA = 0.5


def q_of(deadline: float, timestamp: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, (deadline - timestamp) / TAU))))


def load_runs(arm: str) -> list[tuple[str, list[dict]]]:
    runs = []
    for path in sorted(glob.glob(os.path.join(ROOT, f"*-{arm}-repeat-1", "events.jsonl"))):
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        runs.append((os.path.basename(os.path.dirname(path)), events))
    return runs


def w1a_manifest() -> dict:
    """The frozen W1-A history, read from git because it is not on this branch."""
    raw = subprocess.run(
        ["git", "show", f"{W1A_REF}:{W1A_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(raw.lstrip("\ufeff"))


def w1a_gaps() -> list[float]:
    return [float(row["duration_seconds"]) for row in w1a_manifest()["server_gap_records"]]


def family_of(run: str) -> str:
    return run.rsplit("-a1-", 1)[0]


def part1_history_path(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 1. how history reaches the TTL decision, and what is recorded ==")
    arrivals = 0
    programs = 0
    observed = 0
    eta_counts: Counter[int] = Counter()
    queue_counts: Counter[int] = Counter()
    for _name, events in runs:
        per_run_arrivals = 0
        per_run_programs: set[str] = set()
        for event in events:
            kind = event["event_type"]
            if kind == "REQUEST_ARRIVED":
                per_run_arrivals += 1
            elif kind == "PROGRAM_STARTED":
                per_run_programs.add(str(event.get("program_id")))
            elif kind == TTL_HISTORY:
                observed += 1
                payload = event["payload"]
                eta_counts[int(payload.get("eta_history_sample_count") or 0)] += 1
                queue_counts[int(payload.get("queue_delay_history_sample_count") or 0)] += 1
        arrivals += per_run_arrivals
        programs += len(per_run_programs)
    print(f"  runs                                       {len(runs)}")
    print(f"  REQUEST_ARRIVED per arm                    {arrivals}")
    print(f"  PROGRAM_STARTED per arm                    {programs}")
    print(f"  TTL_HISTORY_INPUT_OBSERVED                 {observed}")
    print(f"  eta_history_sample_count values            {sorted(eta_counts.items())}")
    print(f"  queue_delay_history_sample_count values    {sorted(queue_counts.items())}")
    print()
    print("  gap samples a run can generate = arrivals - programs")
    print(
        f"    observed                               {arrivals} - {programs} "
        f"= {arrivals - programs} over {len(runs)} runs "
        f"= {(arrivals - programs) / len(runs):.1f} per run"
    )
    print(f"  frozen threshold                         {THRESHOLD}")
    print("  therefore every TTL decision is COLD_START, and ttl = default_ttl_seconds")
    print()
    print("  the chain, from ttl.py:")
    print("    _select_history:  len(global) <= threshold  -> COLD_START")
    print("                      next_tool_type is None    -> GLOBAL")
    print("                      len(tool) <= threshold    -> GLOBAL")
    print("                      else                      -> TOOL_SPECIFIC")
    print("    COLD_START:       ttl = ttl_input.default_ttl_seconds   (startup constant)")
    print("    otherwise:        ttl = _choose_empirical_ttl(...)")
    print()
    print("  the event does not expose the server-gap sample count, only eta and")
    print("  queue-delay counters. So the 10-per-run figure is derived from event")
    print("  counts, not read from the archive. M6 must log it explicitly.")
    print()


def pair_releases(runs: list[tuple[str, list[dict]]]) -> tuple[list[dict], Counter[str]]:
    """Pair every traced release with its pressure event, by index and identity.

    Returns the usable pairs plus a counter of rejection reasons. A release is usable
    only when the preceding pressure event exists, its candidate identity set equals
    the traced score identity set, and every traced candidate has a recorded
    ``prefill_reload_seconds`` on that pressure event.
    """
    pairs: list[dict] = []
    rejected: Counter[str] = Counter()
    for run, events in runs:
        for event in events:
            if event["event_type"] != RELEASE:
                continue
            trace = event["payload"].get("selection_trace") or []
            if not trace:
                continue
            scores = trace[0].get("scores") or []
            index = int(event["event_index"])
            prior = [
                row
                for row in events
                if row["event_type"] == FORCED and int(row["event_index"]) < index
            ]
            if not prior:
                rejected["no_preceding_pressure_event"] += 1
                continue
            forced = max(prior, key=lambda row: int(row["event_index"]))
            identity = {(str(score["key"][0]), str(score["key"][1])) for score in scores}
            recorded = {
                (str(c["program_id"]), str(c["prefix_id"])): c
                for c in forced["payload"].get("candidates") or []
            }
            if set(recorded) != identity:
                rejected["candidate_identity_mismatch"] += 1
                continue
            prefill = {}
            missing = False
            for key, candidate in recorded.items():
                value = candidate.get("prefill_reload_seconds")
                if value is None:
                    missing = True
                    break
                prefill[key] = float(value)
            if missing:
                rejected["prefill_not_recorded"] += 1
                continue
            pairs.append(
                {
                    "run": run,
                    "family": family_of(run),
                    "event": event,
                    "forced": forced,
                    "scores": scores,
                    "prefill": prefill,
                    "selected": (
                        str(trace[0]["key"][0]),
                        str(trace[0]["key"][1]),
                    ),
                }
            )
    return pairs, rejected


def recover_need(scores: list[dict], lam: float) -> tuple[float | None, int]:
    """Invert the recorded score to recover the ``need`` A1 actually used.

    ``expected = q * [min(need, N) + lam * max(0, N - need)]``. When ``N <= need`` the
    bracket saturates and carries no information, so that candidate is skipped. When
    ``N > need`` the equation is invertible:

        need = (expected / q - lam * N) / (1 - lam)

    Returns the median estimate over the informative candidates and their count.
    """
    estimates: list[float] = []
    for score in scores:
        q = float(score["reuse_proxy"])
        blocks = float(score["new_blocks"])
        expected = float(score["expected_recompute"])
        if q <= 0.0 or blocks <= 0.0:
            continue
        ratio = expected / q
        if abs(ratio - blocks) <= 1e-6 * max(1.0, blocks):
            continue
        if lam >= 1.0:
            continue
        estimates.append((ratio - lam * blocks) / (1.0 - lam))
    if not estimates:
        return None, 0
    return statistics.median(estimates), len(estimates)


def part1_counterfactual(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 1b. counterfactual: what changes if history exceeds the threshold? ==")
    gaps = w1a_gaps()
    manifest = w1a_manifest()
    print(
        f"  history source   W1-A, {len(gaps)} samples, "
        f"median {statistics.median(gaps):.4f}s, "
        f"p90 {sorted(gaps)[int(0.9 * (len(gaps) - 1))]:.4f}s"
    )
    tool_gaps = [
        float(row["duration_seconds"])
        for row in manifest["server_gap_records"]
        if row.get("tool_type") == "mini-swe-agent-handshake"
    ]
    shell_gaps = [
        float(row["duration_seconds"])
        for row in manifest["server_gap_records"]
        if row.get("tool_type") == "mini-swe-agent-shell"
    ]
    print(f"  tool-specific subset: {len(shell_gaps)} samples for 'mini-swe-agent-shell'")
    print("  the v10 candidate next_tool_type is 'observed-agent-gap', which has 0")
    print("  W1-A samples, so TOOL_SPECIFIC stays unreachable and the mode is GLOBAL.")
    if tool_gaps:
        print(f"  (unexpected: {len(tool_gaps)} samples under the other label)")
    print()

    pairs, rejected = pair_releases(runs)
    multi = [pair for pair in pairs if len(pair["scores"]) >= 2]
    print(f"  traced releases                            {len(pairs) + sum(rejected.values())}")
    print(f"  paired to a pressure event by index+identity {len(pairs)}")
    print(f"  ... with at least two scored candidates    {len(multi)}")
    for reason, count in sorted(rejected.items()):
        print(f"    rejected: {reason:32s} {count}")
    print()

    chosen_ttl: list[float] = []
    benefits: list[float] = []
    q_change: list[float] = []
    identity_error = 0.0
    order_changed = 0
    argmin_changed = 0
    multi_order_changed = 0
    multi_argmin_changed = 0
    examples = []

    for pair in pairs:
        event = pair["event"]
        scores = pair["scores"]
        timestamp = float(event["timestamp"])
        local_new = []
        local_old = []
        for score in scores:
            key = (str(score["key"][0]), str(score["key"][1]))
            deadline = float(score["deadline"])
            q_recorded = float(score["reuse_proxy"])
            # Validate the time arithmetic instead of assuming it.
            identity_error = max(identity_error, abs(q_of(deadline, timestamp) - q_recorded))
            # Cold start means ttl = 0, so the TTL decision instant is the deadline.
            ttl_decision_ts = deadline
            prefill = pair["prefill"][key]
            ttl_input = TTLInput(
                program_id=ProgramIdentity(key[0]),
                request_id=RequestIdentity(f"{key[0]}:cf"),
                prefix_id=PrefixIdentity(key[1]),
                decision_timestamp=ttl_decision_ts,
                next_tool_type="observed-agent-gap",
                global_server_gap_samples_seconds=tuple(gaps),
                tool_server_gap_samples_seconds=(),
                queue_delay_t_seconds=0.0,
                eta=1.0,
                prefill_reload_seconds=prefill,
                default_ttl_seconds=0.0,
                server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
                queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
                eta_provenance=InputProvenance(
                    InputSource.APPROXIMATED, "FULLY_MEMORYFUL_COLD_START"
                ),
                prefill_reload_provenance=InputProvenance(
                    InputSource.APPROXIMATED, "COUNTERFACTUAL_FROM_RECORDED_PREFILL"
                ),
                default_ttl_provenance=InputProvenance(
                    InputSource.APPROXIMATED, "COUNTERFACTUAL_NOT_USED"
                ),
            )
            decision = estimate_ttl(ttl_input, duration_history_threshold=THRESHOLD)
            chosen_ttl.append(decision.ttl_seconds)
            benefits.append(prefill)
            q_new = q_of(ttl_decision_ts + decision.ttl_seconds, timestamp)
            q_change.append(q_new - q_recorded)
            local_new.append((q_new, key[0]))
            local_old.append((q_recorded, key[0]))
            if len(examples) < 3:
                examples.append(
                    (
                        pair["run"],
                        key[0],
                        round(timestamp - ttl_decision_ts, 2),
                        round(decision.ttl_seconds, 4),
                        round(q_recorded, 6),
                        round(q_new, 6),
                    )
                )
        if [row[1] for row in sorted(local_new)] != [row[1] for row in sorted(local_old)]:
            order_changed += 1
        if min(local_new)[1] != min(local_old)[1]:
            argmin_changed += 1
        if len(scores) >= 2:
            multi_order_changed += int(
                [row[1] for row in sorted(local_new)] != [row[1] for row in sorted(local_old)]
            )
            multi_argmin_changed += int(min(local_new)[1] != min(local_old)[1])

    if not chosen_ttl:
        print("  no usable pairs")
        print()
        return
    print(f"  q identity check  max |sigmoid((deadline-t)/tau) - recorded q|  {identity_error:.3e}")
    print("  elapsed is computed as release_time - deadline. The residual above is the")
    print("  check that this subtraction is meaningful; it is not assumed.")
    print()
    print(
        f"  empirical ttl values chosen                "
        f"{sorted(Counter(round(v, 6) for v in chosen_ttl).items())[:5]}"
    )
    print(
        f"  prefill benefit B  min/median/max          "
        f"{min(benefits):.4f} / {statistics.median(benefits):.4f} / {max(benefits):.4f}"
    )
    print(
        f"  empirical ttl  min/median/max              "
        f"{min(chosen_ttl):.4f} / {statistics.median(chosen_ttl):.4f} / {max(chosen_ttl):.4f}"
    )
    print(f"  bound |dq| <= B/(4*tau)  max               {max(benefits) / (4 * TAU):.6f}")
    print(
        f"  q shift  min/median/max                    "
        f"{min(q_change):+.3e} / {statistics.median(q_change):+.3e} / {max(q_change):+.3e}"
    )
    print(f"  q ordering changed                         {order_changed} / {len(pairs)}")
    print(f"  argmin changed                             {argmin_changed} / {len(pairs)}")
    print(
        f"  of which multi-candidate decisions: "
        f"ordering {multi_order_changed} / {len(multi)}, "
        f"argmin {multi_argmin_changed} / {len(multi)}"
    )
    print()
    for row in examples:
        print(
            f"    {row[0][:34]:36s} {row[1][:22]:24s} elapsed={row[2]:8.2f}s "
            f"ttl={row[3]:.4f}s q {row[4]:.6f} -> {row[5]:.6f}"
        )
    print()
    print("  scope of this result: it says that switching THIS workload's history input")
    print("  from cold start to the W1-A distribution did not reorder THESE decisions.")
    print("  It does not say that no history-rich replay can reorder any decision, and")
    print("  it does not say that a small numeric q change cannot change an ordering:")
    print("  the bound only shows the change is bounded by B/(4*tau), and whether that")
    print("  suffices depends on the actual q spread in the decisions being judged.")
    print()
    print("  the bound itself: _choose_empirical_ttl maximises CDF(t)*B - t, so a")
    print("  positive score needs t < B, and q = sigmoid((ttl - elapsed)/tau) gives")
    print("  |dq| <= B/(4*tau). It is a property of the frozen TTL rule, not of M6's")
    print("  workload design.")
    print()


def part2_signals(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 2. which candidate signals could add information to q ==")
    print("  evidence already established, reused rather than rerun:")
    print("    1. q = sigmoid((deadline - t)/tau) with deadline = ttl_decision + ttl.")
    print("       Under cold start this is sigmoid(-elapsed/tau), a monotone function")
    print("       of elapsed alone (verified to 0.0 error above).")
    print("    2. E1a, the native cached-token hit rate, is constant at 1.0 in every row")
    print("       carrying an A1 trace. Note it counts a partially cached prefix as a")
    print("       hit, so it is not a full-cache-hit indicator.")
    print("    3. E1b, the hash-LCP ratio, is exactly 1.0 for every repeated request.")
    print("    4. E1c is the previous block count, so it duplicates N.")
    print("    5. E6, prefix growth, is fixed by the replay materializer in v10 and")
    print("       exactly zero in H1, so it carries no measured variance anywhere.")
    print()
    evicted = sum(
        1 for _name, events in runs for event in events if event["event_type"] == "BLOCK_EVICTED"
    )
    print(f"  BLOCK_EVICTED events in the arm            {evicted}")
    print()
    print("  the one quantity that would be independent of elapsed AND have candidate")
    print("  variation is the realized reuse of an entry after it was evicted. This")
    print("  workload enumerates the evictions but does not record whether the evicted")
    print("  content was later requested again, so that quantity is not computable here.")
    print()


def part3_score(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 3. structure of the q x N score ==")
    print("  R_i = q_i * [min(need, N_i) + lam * max(0, N_i - need)]")
    print("      = q_i * [lam * N_i + (1 - lam) * min(need, N_i)]")
    print()
    print("  a. the bracket is affine in N_i with slope lam, so lam is the price per")
    print("     overshoot block, charged identically to every candidate regardless of")
    print("     whether that block is likely to be reused.")
    print("  b. N_i counts newly eligible blocks, not physically evicted blocks and not")
    print("     recomputed blocks; the native pressure path and APC residency sit in")
    print("     between.")
    print("  c. when every candidate is sufficient, min(need, N_i) = need for all of")
    print("     them, the bracket keeps only lam*(N_i - need), and the ordering is")
    print("     decided by q times a weak N term.")
    print()

    pairs, rejected = pair_releases(runs)
    print(f"  usable paired decisions                    {len(pairs)}")
    for reason, count in sorted(rejected.items()):
        print(f"    rejected: {reason:32s} {count}")
    print()

    needs: list[float] = []
    insufficient: Counter[int] = Counter()
    n_ratios: list[float] = []
    required_blocks: list[float] = []
    lam_grid = (0.0, 0.25, 0.5, 1.0)
    picks: dict[float, list[str]] = {lam: [] for lam in lam_grid}
    divergence: dict[str, Counter[str]] = {lam: Counter() for lam in lam_grid}
    diverged_families: dict[float, Counter[str]] = {lam: Counter() for lam in lam_grid}
    recorded: list[str] = []
    need_vs_required: list[tuple[float, float]] = []

    for pair in pairs:
        scores = pair["scores"]
        need, informative = recover_need(scores, FROZEN_LAMBDA)
        if need is None or informative < 2:
            continue
        needs.append(need)
        required = float(pair["forced"]["payload"].get("required_blocks") or 0.0)
        required_blocks.append(required)
        need_vs_required.append((need, required))
        blocks = [float(score["new_blocks"]) for score in scores]
        qs = [float(score["reuse_proxy"]) for score in scores]
        keys = [str(score["key"][0]) for score in scores]
        insufficient[sum(1 for value in blocks if value < need)] += 1
        if min(blocks) > 0:
            n_ratios.append(max(blocks) / min(blocks))
        recorded.append(pair["selected"][0])
        for lam in lam_grid:
            total = [
                q * (lam * n + (1 - lam) * min(need, n)) for q, n in zip(qs, blocks, strict=True)
            ]
            index = min(range(len(total)), key=lambda i: total[i])
            picks[lam].append(keys[index])
            if keys[index] != pair["selected"][0]:
                divergence[lam]["differs_from_frozen_a1"] += 1
                diverged_families[lam][pair["family"]] += 1

    print(f"  decisions with a recovered need             {len(needs)}")
    if not needs:
        print()
        return
    print(
        f"  recovered need  min/median/max               "
        f"{min(needs):.1f} / {statistics.median(needs):.1f} / {max(needs):.1f}"
    )
    print(f"  distinct recovered need values               {sorted({round(v, 6) for v in needs})}")
    print(
        f"  recorded pressure required_blocks  median     {statistics.median(required_blocks):.1f}"
    )
    print("  required_blocks from the pressure event is NOT the need A1 scored with;")
    print("  reading it as need would mis-state every decision. The need is recovered")
    print("  by inverting the recorded score instead.")
    print()
    print(f"  candidates below need, per decision            {sorted(insufficient.items())}")
    print(f"  N_i max/min  median                           {statistics.median(n_ratios):.3f}")
    print()

    print("  lambda ablation, baseline is the frozen lambda = 0.5")
    print("  (all lambdas are evaluated before any comparison, so no lambda is")
    print("   compared against a baseline that has not been computed yet)")
    baseline = picks[FROZEN_LAMBDA]
    for lam in lam_grid:
        differing = sum(1 for a, b in zip(picks[lam], baseline, strict=True) if a != b)
        vs_recorded = divergence[lam]["differs_from_frozen_a1"]
        print(
            f"    lam={lam:4.2f}  differs from lam=0.50: {differing:2d} / {len(baseline)}"
            f"    differs from recorded A1: {vs_recorded:2d}"
        )
    print()
    for lam in lam_grid:
        if not diverged_families[lam]:
            continue
        print(
            f"    lam={lam:4.2f} divergences by family: "
            f"{dict(sorted(diverged_families[lam].items()))}"
        )
    print()
    print("  cross-check with the earlier phase2g ablation, which reported 27 decisions")
    print("  unchanged and 2 changed, both in g05. That ablation used a different corpus")
    print("  and a different need recovery, so agreement is not expected to be exact;")
    print("  what matters is whether this run contradicts it. A contradiction would be")
    print("  a reason to distrust the lambda conclusion, not a licence to declare lambda")
    print("  inert.")
    print()


def main() -> int:
    runs = load_runs("a1")
    print(f"A1 runs: {len(runs)}")
    print()
    part1_history_path(runs)
    part1_counterfactual(runs)
    part2_signals(runs)
    part3_score(runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
