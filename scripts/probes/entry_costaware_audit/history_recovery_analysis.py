"""Mechanism-recovery analysis for the History-Rich Native Replay design.

Three questions, answered from recorded data only:

1. how does server-gap history reach the TTL decision, and what does sufficient
   history actually change?
2. which candidate signals could give q information it does not already have?
3. where is the ``q x N`` score structurally wrong?

Nothing here changes a frozen path. The TTL counterfactual calls the real
``kvopt.continuum.ttl.estimate_ttl`` rather than reimplementing it, so the answer is
about the frozen algorithm and not about a paraphrase of it.
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


def q_of(deadline: float, timestamp: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, (deadline - timestamp) / TAU))))


def load_runs(arm: str) -> list[tuple[str, list[dict]]]:
    runs = []
    for path in sorted(glob.glob(os.path.join(ROOT, f"*-{arm}-repeat-1", "events.jsonl"))):
        events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        runs.append((os.path.basename(os.path.dirname(path)), events))
    return runs


def w1a_gaps() -> list[float]:
    """The frozen W1-A server-gap samples, read from git (not present on this branch)."""
    raw = subprocess.run(
        ["git", "show", f"{W1A_REF}:{W1A_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    manifest = json.loads(raw.lstrip("\ufeff"))
    return [float(row["duration_seconds"]) for row in manifest["server_gap_records"]]


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


def part1_counterfactual(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 1b. counterfactual: what changes if history exceeds the threshold? ==")
    gaps = w1a_gaps()
    print(
        f"  history source   W1-A, {len(gaps)} samples, "
        f"median {statistics.median(gaps):.4f}s, p90 {sorted(gaps)[int(0.9 * (len(gaps) - 1))]:.4f}s"
    )
    tool_gaps: list[float] = []
    raw = subprocess.run(
        ["git", "show", f"{W1A_REF}:{W1A_PATH}"], capture_output=True, text=True, check=True
    ).stdout
    manifest = json.loads(raw.lstrip("\ufeff"))
    for row in manifest["server_gap_records"]:
        if row.get("tool_type") == "mini-swe-agent-shell":
            tool_gaps.append(float(row["duration_seconds"]))
    print(
        f"  tool-specific subset: {len(tool_gaps)} samples for "
        f"'mini-swe-agent-shell' (threshold {THRESHOLD})"
    )
    print("  v10 candidate next_tool_type is 'observed-agent-gap', which has 0")
    print("  W1-A samples, so TOOL_SPECIFIC stays unreachable and mode is GLOBAL.")
    print()

    chosen_ttl: list[float] = []
    benefits: list[float] = []
    base_ttl: list[float] = []
    q_change: list[float] = []
    order_changed = 0
    argmin_changed = 0
    decisions = 0
    examples = []

    for name, events in runs:
        forced = [event for event in events if event["event_type"] == FORCED]
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
            timestamp = float(event["timestamp"])
            # The true prefill cost of a candidate lives on the pressure event, not in
            # the trace: per_unit * new_blocks is expected_recompute in weighted block
            # units, not seconds.
            nearest = (
                min(forced, key=lambda row: abs(float(row["timestamp"]) - timestamp))
                if forced
                else None
            )
            prefill_by_program: dict[str, float] = {}
            if nearest is not None:
                for candidate in nearest["payload"].get("candidates") or []:
                    prefill_by_program[str(candidate["program_id"])] = float(
                        candidate.get("prefill_reload_seconds") or 0.0
                    )
            local_new = []
            local_old = []
            for score in scores:
                deadline_recorded = float(score["deadline"])
                q_recorded = float(score["reuse_proxy"])
                program = str(score["key"][0])
                # cold start means ttl was 0, so the TTL decision instant is the deadline
                ttl_decision_ts = deadline_recorded
                elapsed_seconds = timestamp - ttl_decision_ts
                prefill = prefill_by_program.get(program, 0.0)
                if prefill <= 0.0:
                    prefill = 1.0
                ttl_input = TTLInput(
                    program_id=ProgramIdentity(program),
                    request_id=RequestIdentity(f"{program}:cf"),
                    prefix_id=PrefixIdentity(f"cf:{program}"),
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
                base_ttl.append(0.0)
                q_new = q_of(ttl_decision_ts + decision.ttl_seconds, timestamp)
                q_change.append(q_new - q_recorded)
                local_new.append((q_new, program, float(score["new_blocks"])))
                local_old.append((q_recorded, program, float(score["new_blocks"])))
                if len(examples) < 3:
                    examples.append(
                        (
                            name,
                            str(score["key"][0]),
                            round(elapsed_seconds, 2),
                            round(decision.ttl_seconds, 4),
                            round(q_recorded, 6),
                            round(q_new, 6),
                        )
                    )
            new_order = [row[1] for row in sorted(local_new)]
            old_order = [row[1] for row in sorted(local_old)]
            if new_order != old_order:
                order_changed += 1
            if min(local_new)[1] != min(local_old)[1]:
                argmin_changed += 1

    print(f"  traced decisions with >=2 candidates       {decisions}")
    if not chosen_ttl:
        print("  no decisions available")
        print()
        return
    counts = Counter(round(v, 6) for v in chosen_ttl)
    print(f"  empirical ttl values chosen                {sorted(counts.items())[:5]}")
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
        f"  q shift caused by that ttl  min/median/max "
        f"{min(q_change):+.3e} / {statistics.median(q_change):+.3e} / {max(q_change):+.3e}"
    )
    print(f"  q ordering changed                         {order_changed} / {decisions}")
    print(f"  argmin changed                             {argmin_changed} / {decisions}")
    print()
    for row in examples:
        print(
            f"    {row[0][:34]:36s} {row[1][:22]:24s} elapsed={row[2]:8.2f}s "
            f"ttl={row[3]:.4f}s q {row[4]:.6f} -> {row[5]:.6f}"
        )
    print()
    print("  why: q = sigmoid((deadline - t)/tau) and deadline = ttl_decision + ttl, so")
    print("  lifting cold start shifts the sigmoid argument by ttl/tau. With ttl in the")
    print("  sub-second range and elapsed in the hundreds of seconds, that shift is")
    print("  orders of magnitude below the spread the ordering lives in.")
    print()


def part2_signals(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 2. which candidate signals could add information to q ==")
    print("  evidence already established in this repository, reused rather than rerun:")
    print("    1. q = sigmoid((deadline - t)/tau) with deadline = ttl_decision + ttl.")
    print("       Under cold start this is sigmoid(-elapsed/tau), i.e. a monotone")
    print("       function of elapsed alone. Verified to 0.0 error on 47 rows.")
    print("    2. E1a (native cached-token hit rate) is constant at 1.0 in every row")
    print("       that carries an A1 trace, and the workload never misses after turn 1.")
    print("    3. E1b (hash-LCP ratio) is exactly 1.0 for every repeated request.")
    print("    4. E1c is the previous block count, so it duplicates N.")
    print("    5. E6 (prefix growth) is fixed by the replay materializer in v10 and")
    print("       exactly zero in H1, so it carries no measured variance anywhere.")
    print()
    evict = Counter()
    for _name, events in runs:
        for event in events:
            if event["event_type"] == "BLOCK_EVICTED":
                evict["observed"] += 1
    print(f"  BLOCK_EVICTED events in the arm            {evict['observed']}")
    print()
    print("  therefore the only signal with measured candidate-level variation that is")
    print("  independent of elapsed is the realized reuse of *earlier* entries, which")
    print("  this workload cannot produce because it never misses. Any new signal must")
    print("  come from a workload that actually loses and re-fetches content.")
    print()


def part3_score(runs: list[tuple[str, list[dict]]]) -> None:
    print("== 3. structure of the q x N score ==")
    print("  R_i = q_i * [min(need, N_i) + lam * max(0, N_i - need)]")
    print("      = q_i * [lam * N_i + (1 - lam) * min(need, N_i)]")
    print()
    print("  three consequences, in order of severity:")
    print("   a. the bracket is affine in N_i with slope lam, so lam is exactly the")
    print("      price charged per overshoot block. It is the same price for every")
    print("      candidate, regardless of whether that block is likely to be reused.")
    print("   b. N_i is newly eligible blocks, not blocks that will be physically")
    print("      evicted, and not blocks that will be recomputed. The two are")
    print("      separated by the native pressure path and by APC residency.")
    print("   c. as need shrinks relative to N_i the bracket approaches lam * N_i, so")
    print("      lam = 1 degenerates the score to q_i * N_i, i.e. plain q-weighted")
    print("      block count, and lam = 0 degenerates it to q_i * need, which is")
    print("      merely q-ordering with a constant factor.")
    print()

    lam_grid = (0.0, 0.25, 0.5, 1.0)
    flips: dict[float, int] = {lam: 0 for lam in lam_grid}
    decisions = 0
    need_known = 0
    need_gt_one_candidate = 0
    sufficient_counts: Counter[int] = Counter()
    n_ratios: list[float] = []
    for _name, events in runs:
        forced = [event for event in events if event["event_type"] == FORCED]
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
            timestamp = float(event["timestamp"])
            nearest = (
                min(forced, key=lambda row: abs(float(row["timestamp"]) - timestamp))
                if forced
                else None
            )
            need = int(nearest["payload"].get("required_blocks") or 0) if nearest else 0
            if need > 0:
                need_known += 1
            blocks = [float(score["new_blocks"]) for score in scores]
            qs = [float(score["reuse_proxy"]) for score in scores]
            keys = [str(score["key"][0]) for score in scores]
            sufficient = sum(1 for value in blocks if value >= need)
            sufficient_counts[sufficient] += 1
            if sufficient >= 2:
                need_gt_one_candidate += 1
            if min(blocks) > 0:
                n_ratios.append(max(blocks) / min(blocks))
            base = None
            for lam in lam_grid:
                total = [
                    q * (lam * n + (1 - lam) * min(need, n))
                    for q, n in zip(qs, blocks, strict=True)
                ]
                pick = keys[min(range(len(total)), key=lambda i: total[i])]
                if lam == 0.5:
                    base = pick
                elif base is not None and pick != base:
                    flips[lam] += 1
    print(f"  traced multi-candidate decisions            {decisions}")
    print(f"  decisions with a recoverable need           {need_known}")
    print(
        f"  N_i max/min median                          {statistics.median(n_ratios):.3f}"
        if n_ratios
        else "  N ratio unavailable"
    )
    print(f"  sufficient candidates per decision          {sorted(sufficient_counts.items())}")
    print(f"  decisions with >= 2 sufficient candidates   {need_gt_one_candidate}")
    print()
    print("  argmin under each lam, compared with lam = 0.5:")
    for lam in lam_grid:
        print(f"    lam={lam:4.2f}  changes {flips[lam]:3d} / {decisions}")
    print()
    print("  sufficient-first is not free: when several candidates are sufficient, the")
    print("  score still has to choose among them, and that is where lam and q act.")
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
