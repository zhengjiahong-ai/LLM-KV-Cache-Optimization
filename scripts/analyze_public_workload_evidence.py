"""Offline projections and counterfactual replay for the Nebius public workload."""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from analyze_nebius_openhands import stats
from public_workload_memoryfulness import census
from public_workload_prefix_inputs import common, materialize, select
from kvopt.profiling.public_workload_oracle import (
    evaluate, loss_by_request, make_paths, prepare, suffix_loss,
)

WARM = 24
HORIZONS = (1, 4, 12)
BLOCKS = (16, 32, 64, 128)
GROUPS = 128
TARGET_INPUT_LIMIT = 32768 - 128
SEED = 251102230
DATA_REV = "35455389ab51bf5e2306bfd436ef72d0f98bf882"
QWEN3_REV = "9d90cf8fca1bf7b7acca42d3fc9ae694a2194069"
QWEN25_REV = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
DATA = f"https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories/resolve/{DATA_REV}"
INPUTS = [
    (DATA + "/trajectories.parquet", "14048dd1fcd22ce094b6e85f8a38f223a9ef1327031aaaad052804870212efa1"),
    (f"https://huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct/resolve/{QWEN3_REV}/tokenizer.json",
     "19564a48c4f71a2a1b937cce34c737a1e662b171c5f5d7edf641a15cd896f07d"),
    (f"https://huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct/resolve/{QWEN3_REV}/tokenizer_config.json",
     "60f6e8cb15c98dd07300a3cc465ea662de245d2095e4245616af21b2324db3fc"),
    (f"https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct/resolve/{QWEN25_REV}/tokenizer.json",
     "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539"),
    (f"https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct/resolve/{QWEN25_REV}/tokenizer_config.json",
     "e0f3c98369c93e05e00fa73d32a5a52fd0fb09269196cba514a8f1fe7709c3ec"),
]


def digest(path):
    with path.open("rb") as stream:
        result = sha256()
        while chunk := stream.read(1 << 20):
            result.update(chunk)
        return result.hexdigest()


def write_json(path, value):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def input_manifest(parquet, qwen3, qwen25):
    paths = [parquet, *(qwen3 / f for f in ("tokenizer.json", "tokenizer_config.json")),
             *(qwen25 / f for f in ("tokenizer.json", "tokenizer_config.json"))]
    result = []
    for path, (url, expected) in zip(paths, INPUTS, strict=True):
        observed = digest(path)
        if observed != expected:
            raise ValueError(f"SHA-256 mismatch for {path.name}")
        result.append({"file": path.name, "source": url, "sha256": observed,
                       "bytes": path.stat().st_size})
    return result


def select_depths(path, start=0):
    size = len(path) - start
    return [path[start + (size-1)*i//4] for i in (1, 2, 3)] if size >= 5 else []


def candidates(current, scenario):
    if len(current) == 1:
        pool = set(select_depths(current[0]))
        shared = 0
    else:
        shared = common(*current)
        pool = set(select_depths(current[0], shared) + select_depths(current[1], shared))
        if scenario == "shared" and shared >= 2:
            pool.update((current[0][shared//2-1], current[0][shared-1]))
    order = {}
    for touch, path in enumerate(current):
        for depth, block in enumerate(path):
            if block in pool:
                order[block] = touch, depth
    return (sorted(pool, key=order.__getitem__),
            sorted(pool, key=lambda b: (order[b][0], -order[b][1])), shared)


def slot_order(streams, horizon, order, ends):
    """Omit terminal empty slots. Return None for an unobserved, censored slot."""
    rows = []
    for slot in range(horizon):
        member = (slot + order) % len(streams)
        turn = WARM + 1 + slot // len(streams)
        if turn in streams[member]:
            rows.append((member, turn))
        elif ends[member] != "submit":
            return None
    return rows


def entry_scores(current, future, ranked, budget):
    """Two synthetic exclusive-tail releases with the same actual victim budget."""
    if len(current) != 2:
        return {}
    entries = [set(left) - set(right)
               for left, right in (current, reversed(current))]
    choices = [frozenset([b for b in ranked if b in path][:budget]) for path in entries]
    if any(len(choice) != budget for choice in choices):
        return {}
    initial = set().union(*map(set, current))
    requests = prepare(initial, future, set().union(*choices))
    loss = [sum(loss_by_request(requests, choice)) for choice in choices]
    suffix = [suffix_loss([path], choice) for path, choice in zip(current, choices)]
    ratios = [size / len(path) for size, path in zip(suffix, current)]
    # No q or PrefillReload imputation. These are unweighted geometric ordering probes.
    depth_pick = min(range(2), key=suffix.__getitem__)
    fraction_pick = min(range(2), key=ratios.__getitem__)
    return {
        "entry_a_suffix_fraction": ratios[0], "entry_b_suffix_fraction": ratios[1],
        "entry_loss_spread": abs(loss[0] - loss[1]), "entry_order_regret": loss[0] - min(loss),
        "entry_suffix_regret": loss[depth_pick] - min(loss),
        "entry_fraction_regret": loss[fraction_pick] - min(loss),
        "entry_suffix_switch": depth_pick != 0, "entry_fraction_switch": fraction_pick != 0,
        "entry_suffix_switch_no_gain": depth_pick != 0 and loss[depth_pick] >= loss[0],
        "entry_fraction_switch_no_gain": fraction_pick != 0 and loss[fraction_pick] >= loss[0],
        "entry_a3_multiplier_crossing": ratios[1] / ratios[0],
    }


def group_results(group, projected, end_by_attempt, geometry, failures):
    label, _, _, same_repo, a, b, c = group
    relation = "same_repo" if same_repo else "cross_repo"
    pairs = ((a, b, "same_issue"), (a, c, relation))
    for left, right, kind in pairs:
        left_proj, right_proj = projected[left], projected[right]
        for name in ("qwen3", "qwen25"):
            left_start = left_proj[1][name][1]
            right_start = right_proj[1][name][1]
            geometry.append({
                "group": label, "relation": kind, "projection": name,
                "raw_codepoint_lcp": common(left_proj[0], right_proj[0]),
                "rendered_codepoint_lcp": common(left_start[0], right_start[0]),
                "initial_token_lcp": common(left_start[1], right_start[1]),
            })
    rows = []
    for scenario, ids in (("single", [a]), ("shared", [a, b]), ("competition", [a, c])):
        ends = [end_by_attempt[attempt] for attempt in ids]
        for name in ("qwen3", "qwen25"):
            streams = [projected[attempt][1][name] for attempt in ids]
            if any(WARM not in stream for stream in streams):
                failures[f"{scenario}/{name}/warm_turn_unobserved"] += 1
                continue
            prompt_keys = [(m, k) for m, stream in enumerate(streams) for k in stream if k >= WARM]
            prompts = [streams[m][k][1] for m, k in prompt_keys]
            for block in BLOCKS:
                paths = dict(zip(prompt_keys, make_paths(prompts, block), strict=True))
                current = [paths[m, WARM] for m in range(len(ids))]
                ranked, alternate, shared = candidates(current, scenario)
                if len(ranked) <= 2:
                    failures[f"{scenario}/{name}/b{block}/fewer_than_three_candidates"] += 1
                    continue
                for rotation in range(len(ids)):
                    for horizon in HORIZONS:
                        slots = slot_order(streams, horizon, rotation, ends)
                        if slots is None:
                            failures[f"{scenario}/{name}/b{block}/r{rotation}/h{horizon}/censored"] += 1
                            continue
                        future = [paths[slot] for slot in slots]
                        max_input = max(len(p) for p in [
                            *(stream[WARM][1] for stream in streams),
                            *(streams[m][k][1] for m, k in slots),
                        ])
                        row = {
                            "group": label, "projection": name, "scenario": scenario,
                            "block": block, "rotation": rotation, "horizon": horizon,
                            "shared_blocks": shared, "resident_blocks": len(set().union(*map(set, current))),
                            "chain_blocks": float(np.mean([len(p) for p in current])),
                            "minimum_exclusive_blocks": min(len(p) for p in current) - shared,
                            "candidate_blocks": len(ranked),
                            "shared_candidate_blocks": sum(b in set(current[0][:shared]) for b in ranked),
                            **request_counts(slots, len(ids)),
                            "context_fits_target": max_input <= TARGET_INPUT_LIMIT,
                        }
                        result = evaluate(current, future, ranked, 2, alternate)
                        result.update(entry_scores(current, future, ranked, 2))
                        token_fields = {"warm_shallow", "greedy", "geometry_exact", "oracle", "victim_loss_span",
                                        "warm_shallow_regret", "warm_deep_regret", "greedy_regret", "geometry_exact_regret",
                                        "static_range", "greedy_proxy_gap", "min_initial_marginal",
                                        "max_initial_marginal", "entry_loss_spread", "entry_order_regret",
                                        "entry_suffix_regret", "entry_fraction_regret"}
                        row.update({k: v * block if k in token_fields else v
                                    for k, v in result.items()})
                        rows.append(row)
    return rows


def request_counts(slots, participants):
    return {
        "future_requests": len(slots),
        "future_requests_a": sum(member == 0 for member, _ in slots),
        "future_requests_b": sum(member == 1 for member, _ in slots) if participants == 2 else None,
    }


def summarize_request_counts(rows, horizon):
    total = rows.future_requests
    result = {
        "full_horizon_clusters": int(total.eq(horizon).sum()),
        "terminal_empty_slots": int((horizon - total).sum()),
    }
    for metric in ("future_requests", "future_requests_a", "future_requests_b"):
        observed = rows[metric].dropna()
        if not observed.empty:
            result.update({
                metric + "_mean": float(observed.mean()),
                metric + "_p50": float(observed.median()),
                metric + "_min": int(observed.min()),
                metric + "_total": int(observed.sum()),
            })
    return result


def summarize_cases(cases):
    result = []
    keys = ["projection", "scenario", "block", "rotation", "horizon"]
    for labels, rows in cases.groupby(keys, sort=True):
        out = dict(zip(keys, labels, strict=True))
        out["clusters"] = len(rows)
        for metric in ("shared_blocks", "chain_blocks", "minimum_exclusive_blocks", "candidate_blocks",
                       "shared_candidate_blocks", "legal_sets", "warm_shallow", "oracle", "greedy", "geometry_exact",
                       "victim_loss_span", "warm_shallow_regret", "greedy_regret", "geometry_exact_regret",
                       "greedy_proxy_gap", "rank_agreement", "min_initial_marginal", "max_initial_marginal",
                       "zero_second_marginals", "zero_marginal_pair_rate", "warm_deep_regret",
                       "entry_loss_spread", "entry_order_regret",
                       "entry_suffix_regret", "entry_fraction_regret", "entry_a3_multiplier_crossing"):
            if metric in rows and len(observed := rows[metric].dropna()):
                out.update({metric + "_mean": observed.mean(), metric + "_p50": observed.median(),
                            metric + "_p90": observed.quantile(.9)})
        entry_rows = rows.loc[rows.entry_order_regret.notna()] if "entry_order_regret" in rows else rows.iloc[:0]
        out["entry_competitions"] = len(entry_rows)
        if len(entry_rows):
            out["entry_fraction_a_p50"] = entry_rows.entry_a_suffix_fraction.median()
            out["entry_fraction_b_p50"] = entry_rows.entry_b_suffix_fraction.median()
            combined = pd.concat([entry_rows.entry_a_suffix_fraction, entry_rows.entry_b_suffix_fraction])
            out["entry_suffix_fraction_p10"] = combined.quantile(.1)
            out["entry_suffix_fraction_p90"] = combined.quantile(.9)
            for metric in ("entry_suffix_switch", "entry_fraction_switch",
                           "entry_suffix_switch_no_gain", "entry_fraction_switch_no_gain"):
                out[metric + "_rate"] = entry_rows[metric].mean()
        for metric in ("context_fits_target", "greedy_diverges", "geometry_exact_diverges", "oracle_diverges"):
            out[metric + "_rate"] = rows[metric].mean()
        for metric in ("warm_shallow_regret", "greedy_regret", "geometry_exact_regret",
                       "victim_loss_span", "greedy_proxy_gap"):
            out[metric + "_positive_rate"] = rows[metric].gt(0).mean()
        out["rank_agreement_n"] = int(rows.rank_agreement.notna().sum())
        fits = rows.loc[rows.context_fits_target]
        out["context_fit_clusters"] = len(fits)
        if len(fits):
            for metric in ("warm_shallow_regret", "warm_deep_regret", "geometry_exact_regret"):
                out["context_fit_" + metric + "_mean"] = fits[metric].mean()
        if labels[2:] == (16, 0, 12):
            rng = np.random.default_rng(SEED)
            data = rows[["warm_shallow_regret", "greedy_regret", "geometry_exact_regret"]].to_numpy()
            sampled = data[rng.integers(len(data), size=(1000, len(data)))].mean(axis=1)
            for column, bounds in zip(("warm_shallow", "greedy", "geometry_exact"),
                                      np.quantile(sampled, [.025, .975], axis=0).T):
                out[column + "_regret_bootstrap_low"], out[column + "_regret_bootstrap_high"] = bounds
        out.update(summarize_request_counts(rows, labels[-1]))
        result.append(out)
    return pd.DataFrame(result)


def plot_regret(summary, path):
    from matplotlib import pyplot as plt

    primary = summary.loc[
        summary.projection.eq("qwen25") & summary.block.eq(16) & summary.rotation.eq(0)
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharey=True, layout="constrained")
    for axis, scenario in zip(axes, ("single", "shared", "competition"), strict=True):
        rows = primary.loc[primary.scenario.eq(scenario)].sort_values("horizon")
        for name, label, color, marker in (
            ("warm_shallow", "Warm A then B, shallow first", "#b15532", "o"),
            ("warm_deep", "Warm A then B, deep first", "#849b35", "D"),
            ("greedy", "Greedy geometry", "#17657d", "s"),
            ("geometry_exact", "Exact geometry", "#513e7d", "^"),
        ):
            axis.plot(rows.horizon, rows[name + "_regret_mean"], label=label,
                      color=color, marker=marker, linewidth=1.5, alpha=.85)
        axis.set(title=scenario.capitalize(), xlabel="Future request slots", xticks=list(HORIZONS))
        axis.grid(axis="y", alpha=.25)
    axes[0].set_ylabel("Mean regret (tokens)")
    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncols=4, frameon=False, fontsize=9)
    fig.savefig(path, dpi=150, metadata={"Software": "Matplotlib public workload analysis"})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("qwen3", type=Path)
    parser.add_argument("qwen25", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ.setdefault("RAYON_NUM_THREADS", "8")
    inputs = input_manifest(args.parquet, args.qwen3, args.qwen25)
    root = Path(__file__).resolve().parents[1]
    code_commit = subprocess.check_output(
        ["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"],
        cwd=root, text=True,
    ).strip()
    frame, memoryfulness = census(args.parquet)
    groups = select(frame, GROUPS)
    ids = {attempt for group in groups for attempt in group[-3:]}
    projected = materialize(args.parquet, ids, args.qwen3, args.qwen25, WARM, max(HORIZONS))
    ends = frame.set_index("attempt").end.to_dict()
    geometry, cases = [], []
    failures = Counter()
    for group in groups:
        cases.extend(group_results(group, projected, ends, geometry, failures))
    windows = pd.DataFrame(cases)
    geometry_frame = pd.DataFrame(geometry)
    cross = {}
    for (projection, relation), rows in geometry_frame.groupby(["projection", "relation"]):
        metrics = ["raw_codepoint_lcp", "rendered_codepoint_lcp", "initial_token_lcp"]
        cross[f"{projection}/{relation}"] = {
            **{m: stats(rows[m]) for m in metrics},
            **{f"aligned_{block}": stats((rows.initial_token_lcp // block) * block) for block in BLOCKS},
        }
    shape = {"initial_sharing": cross, "projections": {}}
    for name in ("qwen3", "qwen25"):
        deltas = [row[2][name] for row in projected.values() if row[2][name] is not None]
        warm = [row[1][name][WARM][1] for row in projected.values() if WARM in row[1][name]]
        lengths = [len(path) for path in warm]
        shape["projections"][name] = {
            "first_tokens": stats([len(row[1][name][1][1]) for row in projected.values()]),
            "warm_tokens": stats(lengths), "warm_over_target_limit": sum(n > TARGET_INPUT_LIMIT for n in lengths),
            "adjacent_warm_tokens_added": stats([d[0] for d in deltas]),
            "adjacent_warm_lcp_tokens": stats([d[1] for d in deltas]),
        }
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "memoryfulness.json", memoryfulness)
    write_json(out / "geometry.json", shape)
    summary = summarize_cases(windows)
    summary.to_csv(
        out / "oracle_summary.csv", index=False, float_format="%.6f", lineterminator="\n"
    )
    plot_regret(summary, out / "oracle_regret.png")
    with (out / "issue_clusters.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["group", "primary_issue", "partner_issue", "same_repo",
                         "primary_attempt", "retry_attempt", "partner_attempt"])
        writer.writerows(groups)
    write_json(out / "manifest.json", {
        "input_artifacts": inputs, "code_commit": code_commit, "configuration": {
            "warm_turn": WARM, "horizon_slots": HORIZONS, "block_sizes": BLOCKS, "victim_budget": 2,
            "target_project_input_limit": TARGET_INPUT_LIMIT, "sampled_issue_clusters": GROUPS,
            "bootstrap_seed": SEED, "bootstrap_replicates": 1000,
            "online_native_policies": {policy: "NOT_EVALUABLE"
                                       for policy in ("Native LRU", "A1", "A2", "A3", "DVA-ER")},
        },
        "integrity": {"archive_attempts": len(frame), "selected_attempts": len(ids),
                      "direct_template_checks_per_projection": sum(row[3] for row in projected.values()),
                      "issues_disjoint": len({issue for group in groups for issue in group[1:3]}) == 2*GROUPS,
                      "oracle_cells_evaluated": len(windows), "case_exclusions": dict(failures)},
        "outputs": {name: digest(out / name) for name in (
            "memoryfulness.json", "geometry.json", "oracle_summary.csv", "issue_clusters.csv", "oracle_regret.png"
        )},
    })


if __name__ == "__main__":
    main()
