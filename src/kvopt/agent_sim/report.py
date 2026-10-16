"""Phase 2F campaign report: machine-readable JSON, markdown tables, charts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from kvopt.agent_sim.experiments import (
    ARM_SPECS,
    BLOCK_SIZE,
    DrawMetrics,
    PairedComparison,
    ScenarioResult,
    draw_metrics,
    paired_comparison,
    victim_set_divergence,
)
from kvopt.agent_sim.trace import SimulationTrace
from kvopt.agent_sim.workload_gen import DRAWS_PER_FAMILY

REPORT_SCHEMA = "phase2f.campaign_report.v1"


def _family_of(trace: SimulationTrace) -> str:
    return trace.family


def build_report(
    *,
    results: dict[str, dict[int, ScenarioResult]],
    traces: dict[int, SimulationTrace],
    counterfactual: dict[str, dict[int, dict[str, object] | None]],
    sensitivity: dict[str, object],
    ttl_probe: dict[str, object],
    arms: tuple[str, ...],
) -> dict[str, object]:
    """Assemble the machine-readable campaign report."""
    metrics: dict[str, dict[int, DrawMetrics]] = {}
    for arm_id, by_draw in results.items():
        metrics[arm_id] = {
            draw: draw_metrics(result) for draw, result in by_draw.items()
        }

    families = sorted({_family_of(trace) for trace in traces.values()})
    comparisons: list[PairedComparison] = []
    for family in families + ["ALL"]:
        pairs = [("A0", "A2"), ("A1", "A3"), ("A0", "A1"), ("A2", "A3")]
        if "A4" in arms:
            pairs.append(("A1", "A4"))
        for baseline_arm, challenger_arm in pairs:
            if baseline_arm not in metrics or challenger_arm not in metrics:
                continue
            base_by_draw = {
                draw: value
                for draw, value in metrics[baseline_arm].items()
                if family == "ALL" or _family_of(traces[draw]) == family
            }
            chall_by_draw = {
                draw: value
                for draw, value in metrics[challenger_arm].items()
                if family == "ALL" or _family_of(traces[draw]) == family
            }
            base_results = {
                draw: results[baseline_arm][draw]
                for draw in base_by_draw
                if draw in results.get(baseline_arm, {})
            }
            chall_results = {
                draw: results[challenger_arm][draw]
                for draw in chall_by_draw
                if draw in results.get(challenger_arm, {})
            }
            comparisons.append(
                paired_comparison(
                    base_by_draw,
                    chall_by_draw,
                    baseline_arm=baseline_arm,
                    challenger_arm=challenger_arm,
                    family=family,
                    baseline_result_by_draw=base_results,
                    challenger_result_by_draw=chall_results,
                )
            )

    divergence: dict[str, object] = {}
    for baseline_arm, challenger_arm in (("A0", "A2"), ("A1", "A3")):
        rates = []
        nontrivial = []
        for draw, trace in sorted(traces.items()):
            if baseline_arm not in results or challenger_arm not in results:
                continue
            base_result = results[baseline_arm].get(draw)
            chall_result = results[challenger_arm].get(draw)
            if base_result is None or chall_result is None:
                continue
            if base_result.error or chall_result.error:
                continue
            stats = victim_set_divergence(base_result, chall_result)
            rates.append(stats["divergence_rate"])
            nontrivial.append(stats["nontrivial_share"])
        if rates:
            divergence[f"{challenger_arm}_vs_{baseline_arm}"] = {
                "mean_divergence_rate": sum(rates) / len(rates),
                "mean_nontrivial_share": sum(nontrivial) / len(nontrivial),
                "draws": len(rates),
            }

    arm_summaries = {}
    for arm_id in arms:
        by_draw = metrics.get(arm_id, {})
        if not by_draw:
            continue
        arm_summaries[arm_id] = {
            "label": ARM_SPECS[arm_id].label,
            "draws": len(by_draw),
            "errors": sum(1 for value in by_draw.values() if value.error),
            "mean_aggregate_recomputed_tokens": (
                sum(v.aggregate_recomputed_tokens for v in by_draw.values()) / len(by_draw)
            ),
            "total_hashed_evictions": sum(v.hashed_eviction_count for v in by_draw.values()),
            "total_forced_releases": sum(v.forced_release_count for v in by_draw.values()),
            "mean_nontrivial_share": (
                sum(v.nontrivial_decision_count for v in by_draw.values())
                / max(1, sum(v.decision_count for v in by_draw.values()))
            ),
            "mean_worst_agent_recomputed": (
                sum(v.worst_agent_cumulative_recomputed for v in by_draw.values()) / len(by_draw)
            ),
            "mean_agent_top1_share": (
                sum(v.agent_top1_share for v in by_draw.values()) / len(by_draw)
            ),
            "mean_p95_recomputed": (
                sum(v.p95_recomputed_tokens for v in by_draw.values()) / len(by_draw)
            ),
            "total_decisions": sum(v.decision_count for v in by_draw.values()),
            "total_policy_seconds": sum(v.policy_seconds for v in by_draw.values()),
            "mean_policy_seconds_per_decision": (
                sum(v.policy_seconds for v in by_draw.values())
                / max(1, sum(v.decision_count for v in by_draw.values()))
            ),
            "mean_protected_block_token_seconds": (
                sum(v.protected_block_token_seconds for v in by_draw.values()) / len(by_draw)
            ),
            "total_protected_reuse_blocks": sum(
                v.protected_reuse_blocks for v in by_draw.values()
            ),
            "total_protected_unused_blocks": sum(
                v.protected_unused_blocks for v in by_draw.values()
            ),
            "total_protected_survived_blocks": sum(
                v.protected_survived_blocks for v in by_draw.values()
            ),
            "total_protected_destroyed_blocks": sum(
                v.protected_destroyed_blocks for v in by_draw.values()
            ),
            "total_natural_ttl_expiry": sum(
                v.natural_ttl_expiry_count for v in by_draw.values()
            ),
            "total_zero_marginal_releases": sum(
                v.zero_marginal_release_count for v in by_draw.values()
            ),
        }

    cold_warm: dict[str, dict[str, float]] = {}
    s6_metrics = {
        arm_id: {
            draw: value
            for draw, value in by_draw.items()
            if _family_of(traces[draw]) == "S6"
        }
        for arm_id, by_draw in metrics.items()
    }
    if any(s6_metrics.values()):
        for arm_id, by_draw in s6_metrics.items():
            cold = [
                value
                for draw, value in by_draw.items()
                if traces[draw].draw <= DRAWS_PER_FAMILY // 2
            ]
            warm = [
                value
                for draw, value in by_draw.items()
                if traces[draw].draw > DRAWS_PER_FAMILY // 2
            ]
            if cold and warm:
                cold_warm[arm_id] = {
                    "cold_recomputed": sum(v.aggregate_recomputed_tokens for v in cold)
                    / len(cold),
                    "warm_recomputed": sum(v.aggregate_recomputed_tokens for v in warm)
                    / len(warm),
                    "cold_evictions": sum(v.hashed_eviction_count for v in cold) / len(cold),
                    "warm_evictions": sum(v.hashed_eviction_count for v in warm) / len(warm),
                }

    return {
        "schema_version": REPORT_SCHEMA,
        "block_size_tokens": BLOCK_SIZE,
        "statistical_unit": "independent_scenario_draw",
        "arms": arm_summaries,
        "comparisons": [asdict(comparison) for comparison in comparisons],
        "victim_set_divergence": divergence,
        "counterfactual_first_divergence": counterfactual,
        "sensitivity": sensitivity,
        "ttl_probe": ttl_probe,
        "cold_warm": cold_warm,
        "failures": {
            arm_id: {
                str(draw): value.error
                for draw, value in by_draw.items()
                if value.error
            }
            for arm_id, by_draw in metrics.items()
        },
    }


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def render_markdown(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Phase 2F — Agent APC Eviction x Retention: Simulation Campaign Report")
    lines.append("")
    lines.append(
        "- Statistical unit: the independent scenario draw (paired comparisons; "
        "requests, turns and decisions are never independent samples)."
    )
    lines.append(
        "- Cost semantics: `recomputed = E - C` per request; the signed aggregate "
        "difference is `challenger - baseline` (negative = improvement); "
        "`dR = sum_r B * max(0, j_baseline(r) - j_challenger(r))` is the "
        "non-negative extra recomputation the challenger causes; "
        "`gross = sum_r B * |j_baseline(r) - j_challenger(r)|` is the absolute "
        "request-level change."
    )
    lines.append(
        "- This report contains **offline simulation** results only. TTFT, TPOT "
        "and throughput are **NOT_MEASURED**."
    )
    lines.append("")
    lines.append("## 1. Arm-level summary")
    lines.append("")
    lines.append(
        "| Arm | Definition | Draws | Mean recomputed tokens | Hashed evictions | "
        "Forced releases | Non-trivial window share |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for arm_id, summary in report["arms"].items():  # type: ignore[union-attr]
        lines.append(
            f"| {arm_id} | {summary['label']} | {summary['draws']} | "
            f"{_fmt(summary['mean_aggregate_recomputed_tokens'])} | "
            f"{summary['total_hashed_evictions']} | {summary['total_forced_releases']} | "
            f"{_fmt(100 * summary['mean_nontrivial_share'])}% |"
        )
    lines.append("")
    lines.append("## 2. Paired comparisons (negative = challenger recomputes less)")
    lines.append("")
    lines.append(
        "| Family | Comparison | Mean delta | Median delta | 95% CI | "
        "Improved/tied/degraded draws | NGR | Mean dR (task formula) |"
    )
    lines.append("| --- | --- | ---: | ---: | --- | --- | --- | ---: |")
    for comparison in report["comparisons"]:  # type: ignore[index]
        ngr = comparison["ngr"]
        ngr_text = ngr if isinstance(ngr, str) else _fmt(float(ngr), 3)
        delta_r_values = comparison["draw_delta_r"]
        mean_delta_r = (
            sum(delta_r_values) / len(delta_r_values) if delta_r_values else 0.0
        )
        lines.append(
            f"| {comparison['family']} | {comparison['challenger_arm']} vs "
            f"{comparison['baseline_arm']} | {_fmt(comparison['mean_delta'])} | "
            f"{_fmt(comparison['median_delta'])} | "
            f"[{_fmt(comparison['ci95_low'])}, {_fmt(comparison['ci95_high'])}] | "
            f"{comparison['improved_draws']}/{comparison['tied_draws']}/"
            f"{comparison['degraded_draws']} | {ngr_text} | {_fmt(mean_delta_r)} |"
        )
    lines.append("")
    lines.append("## 3. Victim-set divergence and non-trivial windows")
    lines.append("")
    lines.append(
        "Divergence is measured on index-aligned decisions; after the first "
        "divergence the two arms' states differ, so later index-aligned "
        "comparisons are descriptive rather than counterfactual."
    )
    for key, value in report["victim_set_divergence"].items():  # type: ignore[union-attr]
        lines.append(
            f"- `{key}`: {_fmt(100 * value['mean_divergence_rate'])}% of decisions "
            f"select different victim ID sets; "
            f"{_fmt(100 * value['mean_nontrivial_share'])}% of decisions are in the "
            f"non-trivial window (|eligible| > required) ({value['draws']} draws)"
        )
    lines.append("")
    lines.append("## 4. Counterfactual: causal effect of the first divergent decision")
    lines.append("")
    lines.append(
        "For each draw, the baseline arm is re-run with the challenger's victim "
        "set substituted at the single first-divergent decision; the difference "
        "in future recomputed tokens is attributable to that one decision alone."
    )
    counterfactual = report["counterfactual_first_divergence"]  # type: ignore[index]
    for pair, by_draw in counterfactual.items():
        improvements = [
            entry["delta_r_improvement_tokens"]
            for entry in by_draw.values()
            if entry is not None and "delta_r_improvement_tokens" in entry
        ]
        damages = [
            entry["delta_r_damage_tokens"]
            for entry in by_draw.values()
            if entry is not None and "delta_r_damage_tokens" in entry
        ]
        missing = sum(1 for entry in by_draw.values() if entry is None)
        if improvements:
            lines.append(
                f"- `{pair}`: {len(improvements)} draws show a first divergence; "
                f"mean recomputation avoided by the challenger's choice at that "
                f"single decision is {_fmt(sum(improvements) / len(improvements))} "
                f"tokens (min {_fmt(min(improvements))}, max {_fmt(max(improvements))}); "
                f"total reverse damage {_fmt(sum(damages))} tokens; "
                f"{missing} draws show no divergence"
            )
        else:
            lines.append(f"- `{pair}`: no draw shows a victim-set divergence")
    lines.append("")
    lines.append("## 5. Sensitivity probes")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(report["sensitivity"], indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(report["ttl_probe"], indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append("## 6. Per-agent distribution and tails (I view)")
    lines.append("")
    lines.append(
        "I view: per-draw aggregates are computed first, then averaged across "
        "draws; requests are never pooled across draws."
    )
    lines.append("")
    lines.append(
        "| Arm | Mean worst-agent cumulative recomputed | Mean top-1 share | "
        "Mean p95 per draw |"
    )
    lines.append("| --- | ---: | ---: | ---: |")
    for arm_id, summary in report["arms"].items():  # type: ignore[union-attr]
        lines.append(
            f"| {arm_id} | {_fmt(summary['mean_worst_agent_recomputed'])} | "
            f"{_fmt(summary['mean_agent_top1_share'], 3)} | "
            f"{_fmt(summary['mean_p95_recomputed'])} |"
        )
    lines.append("")
    lines.append("## 7. Cold-start vs warm-start stratification (family S6)")
    lines.append("")
    lines.append(
        "In S6 the measured content is never destroyed under either starting "
        "condition (recomputed tokens stay 0 because recency suffices), so the "
        "cold/warm difference shows up in eviction counts and TTL history mode "
        "rather than in recomputation."
    )
    lines.append("")
    cold_warm = report["cold_warm"]  # type: ignore[index]
    if cold_warm:
        lines.append(
            "| Arm | Cold recomputed | Warm recomputed | Cold evictions | Warm evictions |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for arm_id, values in cold_warm.items():
            lines.append(
                f"| {arm_id} | {_fmt(values['cold_recomputed'])} | "
                f"{_fmt(values['warm_recomputed'])} | {values['cold_evictions']:.0f} | "
                f"{values['warm_evictions']:.0f} |"
            )
    else:
        lines.append("- no S6 draws")
    lines.append("")
    lines.append("## 8. Decision cost (measured inside the CPU simulator)")
    lines.append("")
    lines.append(
        "Wall-clock cost of the policy's `select` call only; this is simulator "
        "overhead, not serving latency."
    )
    lines.append("")
    lines.append("| Arm | Decisions | Total policy CPU (s) | Mean microseconds/decision |")
    lines.append("| --- | ---: | ---: | ---: |")
    for arm_id, summary in report["arms"].items():  # type: ignore[union-attr]
        lines.append(
            f"| {arm_id} | {summary['total_decisions']} | "
            f"{_fmt(summary['total_policy_seconds'], 3)} | "
            f"{_fmt(1e6 * summary['mean_policy_seconds_per_decision'], 1)} |"
        )
    lines.append("")
    lines.append("## 9. Failures")
    lines.append("")
    failures = report["failures"]  # type: ignore[index]
    any_failure = False
    for arm_id, by_draw in failures.items():
        for draw, error in by_draw.items():
            any_failure = True
            lines.append(f"- `{arm_id}` draw {draw}: {error}")
    if not any_failure:
        lines.append("- none: every arm x draw combination completed successfully")
    lines.append("")
    return "\n".join(lines)


def render_charts(report: dict[str, object], out_dir: Path) -> list[Path]:
    """Write PNG charts; returns the written paths (empty if no matplotlib)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover - charts are optional
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # 1) paired deltas per family for the key comparisons
    families = sorted(
        {
            comparison["family"]
            for comparison in report["comparisons"]  # type: ignore[index]
            if comparison["family"] != "ALL"
        }
    )
    pairs = [("A0", "A2"), ("A1", "A3"), ("A0", "A1"), ("A2", "A3")]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=False)
    for axis, (baseline, challenger) in zip(axes.flat, pairs):
        means = []
        for family in families:
            for comparison in report["comparisons"]:  # type: ignore[index]
                if (
                    comparison["family"] == family
                    and comparison["baseline_arm"] == baseline
                    and comparison["challenger_arm"] == challenger
                ):
                    means.append(comparison["mean_delta"])
                    break
        axis.bar(families, means, color="#3b7ddd")
        axis.axhline(0.0, color="black", linewidth=0.8)
        axis.set_title(f"{challenger} vs {baseline} (mean Δ recomputed tokens)")
        axis.set_ylabel("tokens (negative = better)")
        axis.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    path = out_dir / "phase2f-paired-deltas.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    written.append(path)

    # 2) victim-set divergence rates
    divergence = report["victim_set_divergence"]  # type: ignore[index]
    if divergence:
        fig, axis = plt.subplots(figsize=(7, 4))
        labels = list(divergence)
        rates = [100 * divergence[label]["mean_divergence_rate"] for label in labels]  # type: ignore[index]
        axis.bar(labels, rates, color="#dd7d3b")
        axis.set_ylabel("% of decisions with different victim sets")
        axis.set_ylim(0, 100)
        axis.set_title("Victim-set divergence (A2≠A0, A3≠A1)")
        fig.tight_layout()
        path = out_dir / "phase2f-victim-divergence.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        written.append(path)

    # 3) arm-level mean recomputed tokens
    arms = report["arms"]  # type: ignore[index]
    if arms:
        fig, axis = plt.subplots(figsize=(8, 4))
        labels = list(arms)
        values = [arms[label]["mean_aggregate_recomputed_tokens"] for label in labels]  # type: ignore[index]
        axis.bar(labels, values, color="#3b7ddd")
        axis.set_ylabel("mean aggregate recomputed tokens / draw")
        axis.set_title("Arm-level recomputation (all families)")
        fig.tight_layout()
        path = out_dir / "phase2f-arm-recomputed.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        written.append(path)
    return written
