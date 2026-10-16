"""One-command Phase 2F campaign runner (CPU-only, no GPU, no model).

Usage::

    python -m kvopt.agent_sim.cli --out results/phase2f

Generates the deterministic agent workload campaign, runs every experiment arm
over every scenario draw, computes paired statistics with bootstrap confidence
intervals, runs the sensitivity and TTL probes, and writes machine-readable
JSON, a markdown report and PNG charts.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from kvopt.agent_sim.experiments import (
    ARM_SPECS,
    first_divergence_delta_r,
    future_index_for,
    run_arm,
)
from kvopt.agent_sim.report import (
    REPORT_SCHEMA,
    build_report,
    render_charts,
    render_markdown,
)
from kvopt.agent_sim.workload_gen import DRAWS_PER_FAMILY, FAMILIES, generate_campaign
from kvopt.continuum.snapshots import TTLInput
from kvopt.continuum.ttl import estimate_ttl
from kvopt.continuum.types import (
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)

MAIN_ARMS = ("A0", "A1", "A2", "A3")
EXTRA_ARMS = ("A4", "O1", "O2", "D1")
DEFAULT_SEED = 20261016


def _ttl_probe(results, traces) -> dict[str, object]:
    """Re-run the frozen TTL estimator under a queue-delay sweep.

    The simulator has no queueing model, so the frozen estimator always sees
    ``queue_delay_t_seconds = 0`` and collapses to TTL 0 at the Phase-2E cost
    and gap scales. This probe answers: *would* TTL decisions change if the
    queue-delay term were non-zero? It uses the frozen estimator and the same
    recorded history samples; the swept values are labelled as assumptions.
    """
    sweeps = (0.0, 0.05, 0.65)
    totals = {value: 0 for value in sweeps}
    nonzero = {value: 0 for value in sweeps}
    decisions = 0
    # A1 and A3 share an identical retention path, so their TTL probe records
    # are identical; count A1 once (the equality is asserted by a test).
    for result in results.get("A1", {}).values():
        if result.error:
            continue
        for record in result.ttl_probe_records:
            decisions += 1
            for queue_delay in sweeps:
                ttl_input = TTLInput(
                    program_id=ProgramIdentity("probe"),
                    request_id=RequestIdentity(record.request_id),
                    prefix_id=PrefixIdentity("probe"),
                    decision_timestamp=0.0,
                    next_tool_type=record.next_tool_type,
                    global_server_gap_samples_seconds=record.global_samples,
                    tool_server_gap_samples_seconds=record.tool_samples,
                    queue_delay_t_seconds=queue_delay,
                    eta=record.eta,
                    prefill_reload_seconds=record.prefill_reload_seconds,
                    default_ttl_seconds=0.0,
                    server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
                    queue_delay_provenance=InputProvenance(
                        InputSource.OBSERVED,
                        "SIMULATION_ASSUMED_T_sensitivity_probe",
                    ),
                    eta_provenance=InputProvenance(InputSource.OBSERVED),
                    prefill_reload_provenance=InputProvenance(
                        InputSource.APPROXIMATED, "offline PrefillReload profile"
                    ),
                    default_ttl_provenance=InputProvenance(
                        InputSource.APPROXIMATED, "configured default TTL"
                    ),
                )
                decision = estimate_ttl(ttl_input)
                totals[queue_delay] += decision.ttl_seconds
                if decision.ttl_seconds > 0:
                    nonzero[queue_delay] += 1
    return {
        "decisions": decisions,
        "queue_delay_sweep_seconds": list(sweeps),
        "mean_chosen_ttl_seconds": {
            str(value): (totals[value] / decisions if decisions else 0.0)
            for value in sweeps
        },
        "nonzero_ttl_decisions": {str(value): nonzero[value] for value in sweeps},
        "note": (
            "T=0 is the simulator's degenerate (no queueing model) value; "
            "T>0 values are labelled SIMULATION_ASSUMED sensitivity inputs. "
            "Decisions are counted once (A1; A3 records are identical)."
        ),
    }


def _sensitivity_tail_first(seed: int) -> dict[str, object]:
    """Re-run the main arms with the free-order assumption flipped."""
    traces = generate_campaign(
        seed=seed, free_order="tail_first", draws_per_family=3
    )
    summary: dict[str, object] = {}
    for family in FAMILIES:
        family_traces = [trace for trace in traces if trace.family == family]
        divergence = []
        for trace in family_traces:
            native = run_arm(trace, ARM_SPECS["A0"])
            ours = run_arm(trace, ARM_SPECS["A2"])
            if native.error or ours.error:
                continue
            same = sum(
                1
                for left, right in zip(native.decisions, ours.decisions)
                if set(left.victim_block_ids) == set(right.victim_block_ids)
            )
            total = max(1, len(native.decisions))
            divergence.append(same / total)
        if divergence:
            summary[family] = {
                "mean_identical_victim_rate": sum(divergence) / len(divergence),
                "draws": len(divergence),
            }
    return {
        "variant": "free_order=tail_first (assumption A1 flipped)",
        "per_family_identical_victim_rate": summary,
        "interpretation": (
            "If band-internal native order is already tail-first, candidate v0 "
            "and native select identical victim sets (divergence ~ 0)."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("results/phase2f"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--families", nargs="*", default=list(FAMILIES))
    parser.add_argument("--draws", type=int, default=DRAWS_PER_FAMILY)
    parser.add_argument("--arms", nargs="*", default=list(MAIN_ARMS) + list(EXTRA_ARMS))
    parser.add_argument("--skip-extra", action="store_true")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    arms = tuple(MAIN_ARMS) if args.skip_extra else tuple(args.arms)
    traces_list = generate_campaign(
        seed=args.seed, families=tuple(args.families), draws_per_family=args.draws
    )
    trace_manifest = [
        {
            "trace_id": trace.trace_id,
            "family": trace.family,
            "draw": trace.draw,
            "total_blocks": trace.total_blocks,
            "requests": len(trace.requests),
            "trace_sha256": trace.trace_hash(),
        }
        for trace in traces_list
    ]
    (out_dir / "traces.json").write_text(
        json.dumps(trace_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    results: dict[str, dict[tuple[str, int], object]] = {arm: {} for arm in arms}
    for trace in traces_list:
        future_index = future_index_for(trace)
        for arm_id in arms:
            arm = ARM_SPECS[arm_id]
            result = run_arm(trace, arm, future_index=future_index)
            results[arm_id][(trace.family, trace.draw)] = result
            if result.error:
                print(f"  ! {arm_id} {trace.trace_id}: {result.error}")

    # report expects draw-keyed dicts; rebuild keyed by an integer id
    key_of = {(trace.family, trace.draw): index for index, trace in enumerate(traces_list)}
    report_results = {
        arm_id: {key_of[key]: value for key, value in by_key.items()}
        for arm_id, by_key in results.items()
    }
    report_traces = {index: trace for index, trace in enumerate(traces_list)}

    counterfactual: dict[str, dict[int, dict[str, object] | None]] = {}
    for baseline_arm, challenger_arm in (("A0", "A2"), ("A1", "A3")):
        pair_key = f"{challenger_arm}_vs_{baseline_arm}"
        counterfactual[pair_key] = {}
        for trace in traces_list:
            if trace.family == "S7":
                continue  # negative controls: no divergence expected by design
            entry = first_divergence_delta_r(
                trace,
                baseline_arm=ARM_SPECS[baseline_arm],
                challenger_arm=ARM_SPECS[challenger_arm],
            )
            counterfactual[pair_key][key_of[(trace.family, trace.draw)]] = entry

    sensitivity = _sensitivity_tail_first(args.seed)
    ttl_probe = _ttl_probe(
        {
            arm_id: {key_of[key]: value for key, value in by_key.items()}
            for arm_id, by_key in results.items()
        },
        report_traces,
    )

    report = build_report(
        results=report_results,
        traces=report_traces,
        counterfactual=counterfactual,
        sensitivity=sensitivity,
        ttl_probe=ttl_probe,
        arms=arms,
    )
    report["campaign"] = {
        "seed": args.seed,
        "families": list(args.families),
        "draws_per_family": args.draws,
        "arms": list(arms),
        "trace_manifest": trace_manifest,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "generator": "phase2f.workload_gen.v1",
        "schema": REPORT_SCHEMA,
    }

    (out_dir / "campaign.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    charts = render_charts(report, out_dir)
    print(f"wrote {out_dir / 'campaign.json'}")
    print(f"wrote {out_dir / 'report.md'}")
    for chart in charts:
        print(f"wrote {chart}")
    print(f"done in {report['campaign']['elapsed_seconds']}s")  # type: ignore[index]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
