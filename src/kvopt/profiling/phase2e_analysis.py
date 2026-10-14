"""Compute the frozen Phase 2E A1/A2 metrics from Gate C evidence."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        average_rank = (cursor + 1 + end) / 2
        for index in order[cursor:end]:
            ranks[index] = average_rank
        cursor = end
    return ranks


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks, right_ranks = _ranks(left), _ranks(right)
    left_mean, right_mean = statistics.mean(left_ranks), statistics.mean(right_ranks)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left_ranks, right_ranks, strict=True)
    )
    left_scale = sum((value - left_mean) ** 2 for value in left_ranks)
    right_scale = sum((value - right_mean) ** 2 for value in right_ranks)
    denominator = math.sqrt(left_scale * right_scale)
    return numerator / denominator if denominator else None


def _gini(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered or sum(ordered) == 0:
        return None
    total = sum(ordered)
    weighted = sum(index * value for index, value in enumerate(ordered, start=1))
    return (2 * weighted) / (len(ordered) * total) - (len(ordered) + 1) / len(
        ordered
    )


def _metric(
    value: object,
    *,
    unit: str,
    view: str,
    status: str = "AVAILABLE",
) -> dict[str, object]:
    return {
        "value": value,
        "status": status,
        "unit": unit,
        "evidence": "OFFLINE_DERIVED",
        "view": view,
    }


def _request_values(row: Mapping[str, object]) -> tuple[float, float, float, float, float, float]:
    prompt = float(row["native_prompt_tokens"])
    eligible = float(row["eligible_prefix_tokens"])
    cached = float(row["native_cached_prefix_tokens"])
    queued = float(row["native_queued_timestamp"])
    admission = float(row["native_scheduler_admission_timestamp"])
    first = float(row["native_first_token_timestamp"])
    if not (0 <= cached <= eligible <= prompt):
        raise ValueError("invalid C <= E <= N token invariant")
    if not (queued <= admission <= first):
        raise ValueError("invalid queued <= admission <= first-token invariant")
    return prompt, eligible, cached, queued, admission, first


def compute_run_metrics(run: Mapping[str, object]) -> dict[str, object]:
    rows = run.get("request_evidence")
    if run.get("status") != "VALID" or not isinstance(rows, list) or not rows:
        return {
            "run_id": run.get("run_id"),
            "scenario_id": run.get("scenario_id"),
            "family": run.get("family"),
            "baseline": run.get("baseline"),
            "repeat": run.get("repeat"),
            "status": "NOT_COMPUTABLE",
            "reason_codes": ["RUN_OR_REQUEST_EVIDENCE_INVALID"],
        }
    try:
        values = [_request_values(row) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        return {
            "run_id": run.get("run_id"),
            "scenario_id": run.get("scenario_id"),
            "family": run.get("family"),
            "baseline": run.get("baseline"),
            "repeat": run.get("repeat"),
            "status": "NOT_COMPUTABLE",
            "reason_codes": [f"INVALID_REQUIRED_FIELD:{type(error).__name__}"],
        }
    recomputed = [eligible - cached for _, eligible, cached, *_ in values]
    actual_prefill = [prompt - cached for prompt, _, cached, *_ in values]
    new_suffix = [prompt - eligible for prompt, eligible, *_ in values]
    ttft = [first - queued for *_, queued, admission, first in values]
    queue = [admission - queued for *_, queued, admission, first in values]
    admission_to_first = [first - admission for *_, admission, first in values]
    by_agent: dict[str, list[float]] = defaultdict(list)
    agent_request_counts: dict[str, int] = defaultdict(int)
    agent_eligible: dict[str, float] = defaultdict(float)
    for row, loss in zip(rows, recomputed, strict=True):
        if str(row.get("kind")) == "pressure":
            continue
        agent = str(row["program_id"])
        by_agent[agent].append(loss)
        agent_request_counts[agent] += 1
        agent_eligible[agent] += float(row["eligible_prefix_tokens"])
    agent_totals = [sum(losses) for losses in by_agent.values()]
    total_agent_loss = sum(agent_totals)
    eligible_rows = [
        (eligible, cached)
        for _, eligible, cached, *_ in values
        if eligible > 0
    ]
    severe = sum((eligible - cached) / eligible > 0.75 for eligible, cached in eligible_rows)
    median_rec, median_ttft = _quantile(recomputed, 0.5), _quantile(ttft, 0.5)
    p99_rec, p99_ttft = _quantile(recomputed, 0.99), _quantile(ttft, 0.99)
    transfer = None
    if median_rec and median_ttft and p99_rec is not None and p99_ttft is not None:
        transfer = (p99_ttft / median_ttft) / (p99_rec / median_rec)
    prompt_total = sum(value[0] for value in values)
    cached_total = sum(value[2] for value in values)
    rho = _spearman(recomputed, ttft)
    return {
        "run_id": run["run_id"],
        "scenario_id": run["scenario_id"],
        "family": run["family"],
        "baseline": run["baseline"],
        "repeat": run["repeat"],
        "status": "COMPUTABLE",
        "family_mechanism_status": run["family_mechanism_status"],
        "request_count": len(rows),
        "eligible_request_count": len(eligible_rows),
        "no_eligible_prefix_count": len(rows) - len(eligible_rows),
        "agent_request_counts": dict(sorted(agent_request_counts.items())),
        "agent_eligible_prefix_tokens": dict(sorted(agent_eligible.items())),
        "metrics": {
            "A1.1_aggregate_recomputed_tokens": _metric(sum(recomputed), unit="scenario-draw", view="I"),
            "A1.1a_aggregate_actual_prefill_tokens": _metric(sum(actual_prefill), unit="scenario-draw", view="I"),
            "A1.1b_aggregate_new_suffix_tokens": _metric(sum(new_suffix), unit="scenario-draw", view="I"),
            "A1.2_mean_recomputed_tokens_per_request": _metric(statistics.mean(recomputed), unit="per-request", view="I"),
            "A1.3_mean_ttft_seconds": _metric(statistics.mean(ttft), unit="scenario-draw", view="I"),
            "A1.4_aggregate_admission_to_first_token_seconds": _metric(sum(admission_to_first), unit="scenario-draw", view="I"),
            "A1.5_cache_reuse_efficiency": _metric(cached_total / prompt_total if prompt_total else None, unit="share", view="I"),
            "A1.6_mean_queue_delay_seconds": _metric(statistics.mean(queue), unit="scenario-draw", view="I"),
            "A2.1_p95_recomputed_tokens": _metric(_quantile(recomputed, 0.95), unit="per-request", view="I"),
            "A2.1_p99_recomputed_tokens": _metric(p99_rec, unit="per-request", view="I"),
            "A2.2_p95_ttft_seconds": _metric(_quantile(ttft, 0.95), unit="per-request", view="I"),
            "A2.2_p99_ttft_seconds": _metric(p99_ttft, unit="per-request", view="I"),
            "A2.3_max_single_request_recomputed": _metric(max(recomputed), unit="per-request", view="D"),
            "A2.4_worst_agent_cumulative_recovery": _metric(max(agent_totals, default=0), unit="tokens", view="D"),
            "A2.5a_native_miss_rate": _metric(sum(row.get("apc_outcome") == "MISS" for row in rows) / len(rows), unit="share", view="D"),
            "A2.5b_severe_loss_rate": _metric(severe / len(eligible_rows) if eligible_rows else None, unit="share", view="D", status="AVAILABLE" if eligible_rows else "NOT_APPLICABLE_NO_ELIGIBLE_PREFIX"),
            "A2.6_top1_share": _metric(max(agent_totals, default=0) / total_agent_loss if total_agent_loss else None, unit="share", view="D", status="AVAILABLE" if total_agent_loss else "NOT_APPLICABLE_ZERO_RECOMPUTE"),
            "A2.6_agent_gini": _metric(_gini(agent_totals), unit="share", view="D", status="AVAILABLE" if total_agent_loss else "NOT_APPLICABLE_ZERO_RECOMPUTE"),
            "A2.7_rho_recompute_ttft": _metric(
                rho,
                unit="share",
                view="D",
                status=(
                    "AVAILABLE" if rho is not None else "NOT_APPLICABLE_CONSTANT_INPUT"
                ),
            ),
            "A2.8_tail_transfer_ratio": _metric(transfer, unit="share", view="D", status="AVAILABLE" if transfer is not None else "NOT_APPLICABLE_ZERO_MEDIAN"),
        },
        "request_values": [
            {
                "request_id": row["request_id"],
                "program_id": row["program_id"],
                "kind": row["kind"],
                "recomputed_tokens": loss,
                "ttft_seconds": first - queued,
            }
            for row, loss, (*_, queued, admission, first) in zip(rows, recomputed, values, strict=True)
        ],
    }


def compare_run_pair(left: Mapping[str, object], right: Mapping[str, object]) -> dict[str, object]:
    left_rows = {row["request_id"]: row for row in left.get("request_values", [])}
    right_rows = {row["request_id"]: row for row in right.get("request_values", [])}
    if left.get("status") != "COMPUTABLE" or right.get("status") != "COMPUTABLE" or not left_rows or left_rows.keys() != right_rows.keys():
        return {"status": "NOT_COMPARABLE", "reason_codes": ["REQUEST_PAIRING_INCOMPLETE"]}
    deltas = [
        float(right_rows[key]["recomputed_tokens"]) - float(left_rows[key]["recomputed_tokens"])
        for key in sorted(left_rows)
    ]
    aggregate = sum(deltas)
    gross = sum(abs(value) for value in deltas)
    return {
        "status": "COMPARABLE",
        "request_count": len(deltas),
        "metrics": {
            "A1.7_aggregate_delta_tokens": _metric(aggregate, unit="scenario-draw", view="I"),
            "A1.8_gross_request_level_change_tokens": _metric(gross, unit="scenario-draw", view="I"),
            "A1.9_net_to_gross_ratio": _metric(abs(aggregate) / gross if gross else None, unit="share", view="I", status="AVAILABLE" if gross else "NOT_APPLICABLE_ZERO_GROSS"),
        },
    }


def _mean_metric(rows: Sequence[Mapping[str, object]], name: str) -> float | None:
    values = [row["metrics"][name]["value"] for row in rows if row["metrics"][name]["value"] is not None]
    return statistics.mean(values) if values else None


def _pooled_descriptive(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    request_rows = [
        request
        for row in rows
        for request in row.get("request_values", [])
    ]
    recomputed = [float(row["recomputed_tokens"]) for row in request_rows]
    ttft = [float(row["ttft_seconds"]) for row in request_rows]
    median_rec, median_ttft = _quantile(recomputed, 0.5), _quantile(ttft, 0.5)
    p99_rec, p99_ttft = _quantile(recomputed, 0.99), _quantile(ttft, 0.99)
    transfer = None
    if median_rec and median_ttft and p99_rec is not None and p99_ttft is not None:
        transfer = (p99_ttft / median_ttft) / (p99_rec / median_rec)
    return {
        "request_count": len(request_rows),
        "metrics": {
            "A2.1_p95_recomputed_tokens": _metric(
                _quantile(recomputed, 0.95), unit="per-request", view="D"
            ),
            "A2.1_p99_recomputed_tokens": _metric(
                p99_rec, unit="per-request", view="D"
            ),
            "A2.2_p95_ttft_seconds": _metric(
                _quantile(ttft, 0.95), unit="per-request", view="D"
            ),
            "A2.2_p99_ttft_seconds": _metric(
                p99_ttft, unit="per-request", view="D"
            ),
            "A2.7_rho_recompute_ttft": _metric(
                _spearman(recomputed, ttft), unit="share", view="D"
            ),
            "A2.8_tail_transfer_ratio": _metric(
                transfer,
                unit="share",
                view="D",
                status=(
                    "AVAILABLE" if transfer is not None else "NOT_APPLICABLE_ZERO_MEDIAN"
                ),
            ),
        },
    }


def analyze_campaign(campaign_gate: Mapping[str, object]) -> dict[str, object]:
    run_metrics = [compute_run_metrics(run) for run in campaign_gate["runs"]]
    by_key = {(row["scenario_id"], row["repeat"], row["baseline"]): row for row in run_metrics}
    repeat_pairs = []
    for pair in campaign_gate["pairs"]:
        key = (pair["scenario_id"], pair["repeat"])
        comparison = compare_run_pair(by_key[(*key, "native-lru")], by_key[(*key, "continuum-baseline")])
        repeat_pairs.append({"scenario_id": key[0], "repeat": key[1], "family": by_key[(*key, "native-lru")]["family"], "gate_status": pair["status"], "mechanism_evaluable": pair["mechanism_evaluable"], **comparison})
    scenario_groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in run_metrics:
        scenario_groups[(str(row["scenario_id"]), str(row["baseline"]))].append(row)
    metric_names = list(next(row["metrics"] for row in run_metrics if row.get("metrics")))
    scenarios = []
    for (scenario_id, baseline), rows in sorted(scenario_groups.items()):
        scenarios.append({
            "scenario_id": scenario_id,
            "family": rows[0]["family"],
            "baseline": baseline,
            "repeat_count": len(rows),
            "mechanism_realized_repeat_count": sum(row["family_mechanism_status"] == "REALIZED" for row in rows),
            "metrics": {name: _metric(_mean_metric(rows, name), unit=rows[0]["metrics"][name]["unit"], view=rows[0]["metrics"][name]["view"]) for name in metric_names},
        })
    scenario_pair_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in repeat_pairs:
        scenario_pair_groups[str(row["scenario_id"])].append(row)
    scenario_pairs = []
    pair_metric_names = ["A1.7_aggregate_delta_tokens", "A1.8_gross_request_level_change_tokens", "A1.9_net_to_gross_ratio"]
    for scenario_id, rows in sorted(scenario_pair_groups.items()):
        valid = [row for row in rows if row["status"] == "COMPARABLE"]
        scenario_pairs.append({
            "scenario_id": scenario_id,
            "family": rows[0]["family"],
            "repeat_count": len(rows),
            "comparable_repeat_count": len(valid),
            "mechanism_evaluable_repeat_count": sum(row["mechanism_evaluable"] for row in rows),
            "metrics": {name: _metric(statistics.mean(row["metrics"][name]["value"] for row in valid if row["metrics"][name]["value"] is not None) if any(row["metrics"][name]["value"] is not None for row in valid) else None, unit="share" if name.endswith("ratio") else "scenario-draw", view="I") for name in pair_metric_names},
        })
    family_summaries = []
    for family in sorted({str(row["family"]) for row in scenarios}):
        family_pairs = [row for row in scenario_pairs if row["family"] == family]
        deltas = [
            float(row["metrics"]["A1.7_aggregate_delta_tokens"]["value"])
            for row in family_pairs
        ]
        arm_summaries = {}
        for baseline in ("native-lru", "continuum-baseline"):
            arm_rows = [
                row
                for row in scenarios
                if row["family"] == family and row["baseline"] == baseline
            ]
            arm_summaries[baseline] = {
                name: _mean_metric(arm_rows, name) for name in metric_names
            }
        family_summaries.append(
            {
                "family": family,
                "scenario_count": len(family_pairs),
                "continuum_minus_native_lru": {
                    "mean_aggregate_delta_tokens": statistics.mean(deltas),
                    "negative_scenarios": sum(value < 0 for value in deltas),
                    "zero_scenarios": sum(value == 0 for value in deltas),
                    "positive_scenarios": sum(value > 0 for value in deltas),
                },
                "arm_metric_means": arm_summaries,
            }
        )
    metric_coverage = {}
    for name in metric_names:
        status_counts: dict[str, int] = defaultdict(int)
        for row in run_metrics:
            status_counts[str(row["metrics"][name]["status"])] += 1
        available = status_counts.get("AVAILABLE", 0)
        not_computable = sum(
            count
            for status, count in status_counts.items()
            if status.startswith("NOT_COMPUTABLE")
        )
        metric_coverage[name] = {
            "available_runs": available,
            "total_runs": len(run_metrics),
            "available_share": available / len(run_metrics),
            "not_computable_runs": not_computable,
            "not_applicable_runs": len(run_metrics) - available - not_computable,
            "status_counts": dict(sorted(status_counts.items())),
            "coverage_label": (
                "LOW_COVERAGE"
                if not_computable / len(run_metrics) > 0.1
                else "ADEQUATE_WITH_NOT_APPLICABLE_SEPARATE"
            ),
        }
    descriptive = {
        baseline: _pooled_descriptive(
            [row for row in run_metrics if row["baseline"] == baseline]
        )
        for baseline in ("native-lru", "continuum-baseline")
    }
    return {
        "schema_version": "phase2e.measured_analysis.v1",
        "analysis_scope": "EXPLORATORY_PAIRED_BASELINE_CHARACTERIZATION",
        "comparison_direction": "continuum-baseline minus native-lru",
        "statistical_unit": "scenario-draw",
        "repeat_aggregation": "mean within scenario before cross-scenario summaries",
        "threshold_or_ci_claims": "NONE",
        "run_count": len(run_metrics),
        "scenario_count": len({row["scenario_id"] for row in run_metrics}),
        "missingness": {
            "computable_runs": sum(row["status"] == "COMPUTABLE" for row in run_metrics),
            "not_computable_runs": sum(row["status"] != "COMPUTABLE" for row in run_metrics),
            "mechanism_not_realized_runs": sum(row.get("family_mechanism_status") == "NOT_REALIZED" for row in run_metrics),
            "excluded_runs": 0,
            "metric_coverage": metric_coverage,
        },
        "descriptive_pooled_request_view": descriptive,
        "family_summaries": family_summaries,
        "run_metrics": run_metrics,
        "repeat_pairs": repeat_pairs,
        "scenario_metrics": scenarios,
        "scenario_pairs": scenario_pairs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    gate = json.loads(args.campaign_gate.read_text(encoding="utf-8"))
    report = analyze_campaign(gate)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote Phase 2E measured analysis: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
