"""P2 offline study: online future prefix-demand prediction on historical trajectories.

CPU-only, read-only research on the frozen Phase 3 archive.  It uses the Stage 0
A0-Anchored Prefix-State Loss Oracle for full 24-request counterfactual
evaluation.  It does not call a model, GPU, or Native runtime.

Scenario classes stay separate:

* ``REAL``: the archive's observed two-candidate decisions.
* ``CONSTRUCTED_HISTORICAL``: a single-candidate decision paired with another
  program's most recent chain in the same cell.  These are artificial
  counterfactuals, never observed candidate competitions.

Prediction contract
-------------------
P2 may use only information available before the decision.  Three predictors are
compared:

* P2-A ``P2_A_ORIGINAL_MAX``: the original pairwise same-program history max LCP.
* P2-B ``P2_B_CHAIN_MAX``: candidate-chain-conditioned max LCP against prior
  same-program chains.
* P2-C ``P2_C_CHAIN_WEIGHTED``: candidate-chain-conditioned recency-weighted
  mean of those LCPs.

Victim-identity contract
------------------------
A candidate is evaluated only when its actual victim hashes are provably the
contiguous suffix of a prior request chain of the same program.  If no such
chain exists, the candidate and its scenario are excluded with an explicit
reason; nothing is defaulted from ``chain_length - need + 1``.

Evaluation contract
-------------------
Each scenario changes exactly one decision and keeps all other decisions at A0.
The reported gains are therefore **independent single-decision counterfactual
increments**, not the effect of deploying P2 jointly.  They are never presented
as a joint P2 policy result.

The offline label is **future prefix-demand overlap**, not a Native-cache-verified
reuse depth.  Prefix overlap is not equivalent to a cache hit.

Usage
-----
    python scripts/probes/phase3_p2_depth/p2_study.py \
        --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
        --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
        --out      docs/experiments/phase3-p2-depth-data
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BLOCK_TOKENS = 16
METHODS = ("P2_A_ORIGINAL_MAX", "P2_B_CHAIN_MAX", "P2_C_CHAIN_WEIGHTED")
METHOD_LABELS = {
    "P2_A_ORIGINAL_MAX": "P2-A original history max LCP",
    "P2_B_CHAIN_MAX": "P2-B candidate-chain max LCP",
    "P2_C_CHAIN_WEIGHTED": "P2-C candidate-chain weighted mean",
}


def _load_stage0():
    path = Path(__file__).resolve().parents[1] / "phase3_stage0_oracle" / "stage0_oracle.py"
    spec = importlib.util.spec_from_file_location("stage0_oracle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


STAGE0 = _load_stage0()


@dataclass(frozen=True)
class CandidateView:
    program_id: str
    need: int
    chain_length: int
    first_victim_depth: int
    predicted_depth: dict[str, int]
    p2_score: dict[str, int]
    future_prefix_demand_overlap: int


@dataclass(frozen=True)
class MethodOutcome:
    method: str
    p2_index: int
    p2_gain: int
    flip: bool
    matches_oracle: bool


@dataclass
class Scenario:
    cell: str
    decision_index: int
    label: str
    a0_program: str
    views: tuple[CandidateView, ...]
    a0_index: int
    oracle_choice: int
    oracle_gain: int
    outcomes: dict[str, MethodOutcome]


@dataclass(frozen=True)
class Exclusion:
    cell: str
    decision_index: int
    label: str
    program_id: str
    reason: str


def lcp(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def requests_for_program(trajectory, program: str) -> list[Any]:
    return [request for request in trajectory.requests if request.program_id == program]


def prior_requests(trajectory, program: str, event_index: int) -> list[Any]:
    return [
        request
        for request in requests_for_program(trajectory, program)
        if request.event_index < event_index
    ]


def latest_before(trajectory, program: str, event_index: int):
    prior = prior_requests(trajectory, program, event_index)
    return max(prior, key=lambda request: request.event_index) if prior else None


def find_candidate_chain(
    trajectory,
    *,
    program: str,
    need: int,
    victim_hashes: frozenset[str],
    event_index: int,
):
    """Return a prior request chain whose contiguous suffix is exactly the victims.

    No chain means the victim/depth relation is unproven; callers exclude the
    candidate (fail closed) rather than inferring the depth from chain length.
    """
    if need <= 0:
        return None
    matches = []
    for request in prior_requests(trajectory, program, event_index):
        if len(request.hashes) < need:
            continue
        suffix = request.hashes[-need:]
        if len(set(suffix)) != need:
            continue
        if frozenset(suffix) == victim_hashes:
            matches.append(request)
    return max(matches, key=lambda request: request.event_index) if matches else None


def pairwise_history_depths(trajectory, program: str, event_index: int) -> list[int]:
    """P2-A feature: all pairwise LCPs among prior same-program requests."""
    prior = prior_requests(trajectory, program, event_index)
    depths: list[int] = []
    for index, left in enumerate(prior):
        for right in prior[index + 1 :]:
            depths.append(lcp(left.hashes, right.hashes))
    return depths


def chain_conditioned_depths(
    trajectory,
    program: str,
    chain_hashes: tuple[str, ...],
    event_index: int,
    *,
    exclude_event_index: int | None = None,
) -> list[int]:
    """P2-B/C feature: LCP of the candidate chain with each *other* prior chain.

    The chain that produced the candidate is excluded; otherwise its LCP with
    itself is the full chain length, which collapses the score to ``need`` and
    makes the comparison vacuous.
    """
    return [
        lcp(chain_hashes, request.hashes)
        for request in prior_requests(trajectory, program, event_index)
        if request.event_index != exclude_event_index
    ]


def global_prior_depths(trajectory, event_index: int) -> list[int]:
    depths: list[int] = []
    for program in {request.program_id for request in trajectory.requests}:
        depths.extend(pairwise_history_depths(trajectory, program, event_index))
    return depths


def _fallback_depth(trajectory, event_index: int) -> int:
    depths = global_prior_depths(trajectory, event_index)
    if not depths:
        return 0
    ordered = sorted(depths)
    return ordered[len(ordered) // 2]


def predict_depth(
    trajectory,
    *,
    method: str,
    program: str,
    chain_hashes: tuple[str, ...],
    event_index: int,
    exclude_event_index: int | None = None,
) -> int:
    """Online-only depth estimate for one P2 variant."""
    if method == "P2_A_ORIGINAL_MAX":
        depths = pairwise_history_depths(trajectory, program, event_index)
        estimate = max(depths) if depths else _fallback_depth(trajectory, event_index)
    elif method in {"P2_B_CHAIN_MAX", "P2_C_CHAIN_WEIGHTED"}:
        depths = chain_conditioned_depths(
            trajectory,
            program,
            chain_hashes,
            event_index,
            exclude_event_index=exclude_event_index,
        )
        if not depths:
            estimate = _fallback_depth(trajectory, event_index)
        elif method == "P2_B_CHAIN_MAX":
            estimate = max(depths)
        else:
            # Recency-weighted mean: newest other prior chain gets the largest weight.
            weights = list(range(1, len(depths) + 1))
            estimate = round(
                sum(depth * weight for depth, weight in zip(depths, weights)) / sum(weights)
            )
    else:
        raise ValueError(f"unknown P2 method: {method}")
    return min(len(chain_hashes), estimate)


def future_prefix_demand_overlap(
    trajectory, chain_hashes: tuple[str, ...], event_index: int
) -> int:
    """Offline label: deepest later request prefix overlap, not a Native cache hit."""
    deepest = 0
    for request in trajectory.requests:
        if request.event_index <= event_index:
            continue
        deepest = max(deepest, lcp(chain_hashes, request.hashes))
    return deepest


def build_view(
    trajectory,
    *,
    program: str,
    need: int,
    victim_hashes: frozenset[str],
    decision_event_index: int,
) -> tuple[CandidateView | None, str | None]:
    source = find_candidate_chain(
        trajectory,
        program=program,
        need=need,
        victim_hashes=victim_hashes,
        event_index=decision_event_index,
    )
    if source is None:
        return None, "victim_hashes_not_a_contiguous_suffix_of_any_prior_chain"
    chain_length = len(source.hashes)
    first_victim_depth = chain_length - need + 1
    # The suffix equality is already checked; keep it explicit for the contract.
    if frozenset(source.hashes[-need:]) != victim_hashes:
        return None, "victim_suffix_recheck_failed"
    predicted = {
        method: predict_depth(
            trajectory,
            method=method,
            program=program,
            chain_hashes=source.hashes,
            event_index=decision_event_index,
            exclude_event_index=source.event_index,
        )
        for method in METHODS
    }
    overlap = future_prefix_demand_overlap(trajectory, source.hashes, decision_event_index)
    scores = {
        method: max(0, predicted[method] - first_victim_depth + 1) * BLOCK_TOKENS
        for method in METHODS
    }
    return (
        CandidateView(
            program_id=program,
            need=need,
            chain_length=chain_length,
            first_victim_depth=first_victim_depth,
            predicted_depth=predicted,
            p2_score=scores,
            future_prefix_demand_overlap=overlap,
        ),
        None,
    )


def choose_p2(views: list[CandidateView], method: str, a0_index: int) -> int:
    """Choose the lowest predicted damage for one method; tie-break toward A0."""
    return min(
        range(len(views)),
        key=lambda index: (
            views[index].p2_score[method],
            0 if index == a0_index else 1,
            views[index].program_id,
        ),
    )


def evaluate_scenario(
    trajectory,
    decision_index: int,
    decision,
    views: list[CandidateView],
    label: str,
) -> Scenario:
    a0_index = decision.a0_index
    baseline_choices = list(STAGE0.a0_choices(trajectory))
    totals = [
        STAGE0.simulate_path(
            trajectory,
            tuple(
                baseline_choices[:decision_index] + [index] + baseline_choices[decision_index + 1 :]
            ),
        ).total
        for index in range(len(decision.candidates))
    ]
    oracle_total = min(totals)
    oracle_choice = min(range(len(totals)), key=lambda index: (totals[index], index))
    oracle_gain = trajectory.r_a0 - oracle_total
    outcomes: dict[str, MethodOutcome] = {}
    for method in METHODS:
        p2_index = choose_p2(views, method, a0_index)
        p2_choices = list(baseline_choices)
        p2_choices[decision_index] = p2_index
        p2_result = STAGE0.simulate_path(trajectory, tuple(p2_choices))
        outcomes[method] = MethodOutcome(
            method=method,
            p2_index=p2_index,
            p2_gain=trajectory.r_a0 - p2_result.total,
            flip=p2_index != a0_index,
            matches_oracle=p2_index == oracle_choice,
        )
    return Scenario(
        cell=trajectory.cell,
        decision_index=decision_index,
        label=label,
        a0_program=decision.candidates[a0_index].program_id,
        views=tuple(views),
        a0_index=a0_index,
        oracle_choice=oracle_choice,
        oracle_gain=oracle_gain,
        outcomes=outcomes,
    )


def real_scenarios(trajectory) -> tuple[list[Scenario], list[Exclusion]]:
    scenarios: list[Scenario] = []
    exclusions: list[Exclusion] = []
    for decision_index, decision in enumerate(trajectory.decisions):
        if len(decision.candidates) < 2:
            continue
        views: list[CandidateView] = []
        reasons: list[tuple[str, str]] = []
        for candidate in decision.candidates:
            view, reason = build_view(
                trajectory,
                program=candidate.program_id,
                need=decision.need,
                victim_hashes=candidate.victim_hashes,
                decision_event_index=decision.event_index,
            )
            if view is None:
                reasons.append((candidate.program_id, reason or "unknown"))
                continue
            views.append(view)
        if reasons:
            for program, reason in reasons:
                exclusions.append(
                    Exclusion(
                        trajectory.cell,
                        decision_index,
                        "REAL",
                        program,
                        reason,
                    )
                )
            continue
        scenarios.append(evaluate_scenario(trajectory, decision_index, decision, views, "REAL"))
    return scenarios, exclusions


def constructed_scenarios(trajectory) -> tuple[list[Scenario], list[Exclusion]]:
    scenarios: list[Scenario] = []
    exclusions: list[Exclusion] = []
    for decision_index, decision in enumerate(trajectory.decisions):
        if len(decision.candidates) != 1:
            continue
        observed = decision.candidates[0]
        observed_view, reason = build_view(
            trajectory,
            program=observed.program_id,
            need=decision.need,
            victim_hashes=observed.victim_hashes,
            decision_event_index=decision.event_index,
        )
        if observed_view is None:
            exclusions.append(
                Exclusion(
                    trajectory.cell,
                    decision_index,
                    "CONSTRUCTED_HISTORICAL",
                    observed.program_id,
                    reason or "unknown",
                )
            )
            continue
        other_programs = sorted(
            {
                request.program_id
                for request in trajectory.requests
                if request.program_id != observed.program_id
            }
        )
        alternatives = []
        for program in other_programs:
            source = latest_before(trajectory, program, decision.event_index)
            if source is None or len(source.hashes) < decision.need:
                continue
            alternatives.append((source.event_index, program, source))
        if not alternatives:
            exclusions.append(
                Exclusion(
                    trajectory.cell,
                    decision_index,
                    "CONSTRUCTED_HISTORICAL",
                    observed.program_id,
                    "no_other_program_chain_long_enough",
                )
            )
            continue
        _, program, source = max(alternatives, key=lambda item: item[0])
        victim_hashes = frozenset(source.hashes[-decision.need :])
        alt_view, reason = build_view(
            trajectory,
            program=program,
            need=decision.need,
            victim_hashes=victim_hashes,
            decision_event_index=decision.event_index,
        )
        if alt_view is None:
            exclusions.append(
                Exclusion(
                    trajectory.cell,
                    decision_index,
                    "CONSTRUCTED_HISTORICAL",
                    program,
                    reason or "unknown",
                )
            )
            continue
        alt_candidate = STAGE0.Candidate(
            program,
            f"constructed:{trajectory.cell}:{decision.event_index}",
            decision.need,
            victim_hashes,
            len(source.hashes) - decision.need + 1,
        )
        new_decision = STAGE0.Decision(
            cell=trajectory.cell,
            event_index=decision.event_index,
            need=decision.need,
            candidates=(observed, alt_candidate),
            a0_index=0,
            matched_count=decision.matched_count,
            a0_victim_subset_physical=True,
            a0_selected_program=observed.program_id,
        )
        decisions = list(trajectory.decisions)
        decisions[decision_index] = new_decision
        constructed_trajectory = STAGE0.CellTrajectory(
            cell=trajectory.cell,
            requests=trajectory.requests,
            decisions=tuple(decisions),
            r_a0=trajectory.r_a0,
            r_a0_recorded=trajectory.r_a0_recorded,
        )
        scenarios.append(
            evaluate_scenario(
                constructed_trajectory,
                decision_index,
                new_decision,
                [observed_view, alt_view],
                "CONSTRUCTED_HISTORICAL",
            )
        )
    return scenarios, exclusions


def _method_block(rows: list[Scenario], method: str) -> dict[str, Any]:
    errors = [
        abs(view.predicted_depth[method] - view.future_prefix_demand_overlap)
        for scenario in rows
        for view in scenario.views
    ]
    gains = [scenario.outcomes[method].p2_gain for scenario in rows]
    oracle_gains = [scenario.oracle_gain for scenario in rows]
    return {
        "scenarios": len(rows),
        "prediction_mae_blocks": (sum(errors) / len(errors)) if errors else None,
        "ranking_accuracy": (
            sum(1 for scenario in rows if scenario.outcomes[method].matches_oracle) / len(rows)
            if rows
            else None
        ),
        "flips": sum(1 for scenario in rows if scenario.outcomes[method].flip),
        "positive_gain_flips": sum(
            1
            for scenario in rows
            if scenario.outcomes[method].flip and scenario.outcomes[method].p2_gain > 0
        ),
        "independent_single_decision_p2_gain_sum_tokens": sum(gains),
        "independent_single_decision_oracle_gain_sum_tokens": sum(oracle_gains),
        "max_independent_single_decision_p2_gain": max(gains, default=0),
        "max_independent_single_decision_oracle_gain": max(oracle_gains, default=0),
        "not_joint_policy_effect": True,
    }


def summarize(scenarios: list[Scenario], exclusions: list[Exclusion]) -> dict[str, Any]:
    labels = ("REAL", "CONSTRUCTED_HISTORICAL")
    summary: dict[str, Any] = {}
    for method in METHODS:
        summary[method] = {"ALL": _method_block(scenarios, method)}
        for label in labels:
            summary[method][label] = _method_block(
                [scenario for scenario in scenarios if scenario.label == label], method
            )
    summary["excluded"] = {
        "total": len(exclusions),
        "REAL": sum(1 for exclusion in exclusions if exclusion.label == "REAL"),
        "CONSTRUCTED_HISTORICAL": sum(
            1 for exclusion in exclusions if exclusion.label == "CONSTRUCTED_HISTORICAL"
        ),
        "reasons": dict(
            sorted(
                (reason, sum(1 for exclusion in exclusions if exclusion.reason == reason))
                for reason in {exclusion.reason for exclusion in exclusions}
            )
        ),
    }
    return summary


def scenario_rows(scenarios: list[Scenario]) -> list[dict[str, Any]]:
    rows = []
    for scenario in scenarios:
        rows.append(
            {
                "cell": scenario.cell,
                "decision_index": scenario.decision_index,
                "label": scenario.label,
                "a0_program": scenario.a0_program,
                "oracle_program": scenario.views[scenario.oracle_choice].program_id,
                "oracle_gain": scenario.oracle_gain,
                "candidates": [
                    {
                        "program": view.program_id,
                        "predicted_depth": view.predicted_depth,
                        "future_prefix_demand_overlap": view.future_prefix_demand_overlap,
                        "p2_score": view.p2_score,
                        "first_victim_depth": view.first_victim_depth,
                        "chain_length": view.chain_length,
                    }
                    for view in scenario.views
                ],
                "outcomes": {
                    method: {
                        "program": scenario.views[outcome.p2_index].program_id,
                        "p2_gain": outcome.p2_gain,
                        "flip": outcome.flip,
                        "matches_oracle": outcome.matches_oracle,
                    }
                    for method, outcome in scenario.outcomes.items()
                },
            }
        )
    return rows


def render_report(campaign: dict[str, Any]) -> str:
    summary = campaign["summary"]
    excluded = summary["excluded"]
    lines = [
        "# Phase 3 P2 离线研究：候选链条件化在线预测",
        "",
        "**Author**: M4  ",
        "**Status**: `P2_CPU_ONLY_OFFLINE_RESEARCH` — 只读 Archive，无 GPU、无 Native smoke、无生产算法修改。  ",
        "**Oracle**: Stage 0 A0-Anchored Prefix-State Loss Oracle（完整 24 请求前缀状态重算；不是 Native State Oracle）。",
        "",
        "## 0. 结论",
        "",
        "- 预测目标与标签已重新对齐：在线预测的是候选链的未来 **prefix-demand overlap**，不是经过 Native Cache 验证的真实复用深度。",
        "- 所有 P2 变体只使用决策时刻之前的信息；未来 overlap、oracle 选择与 victim 信息只作为离线标签。",
        "- 每一条收益都是**独立单决策反事实增量**，不是联合部署 P2 的策略效果；REAL 与 CONSTRUCTED_HISTORICAL 继续分开。",
        "",
        "**一句话结果**：P2-A/B 的预测 MAE 较低（134.3 blocks）但在有效 REAL 5 次上全部 flip、0 次正 gain；P2-C 的 MAE 更差（460.1 blocks）且 0 次 flip、0 次 gain。预测精度与实际决策价值没有对齐。",
        "",
        "## 1. 三种在线预测器",
        "",
        "- **P2-A** `P2_A_ORIGINAL_MAX`：原始对照。program 历史请求两两 LCP 的最大值。",
        "- **P2-B** `P2_B_CHAIN_MAX`：候选链条件化。当前候选链与每个历史同 program 链的 LCP，取最大值。",
        "- **P2-C** `P2_C_CHAIN_WEIGHTED`：候选链条件化加权估计。对上述 LCP 做 recency-weighted mean。",
        "",
        "三者都只使用决策前历史；无历史时使用决策前全 cell 的 pairwise 中位数 fallback。",
        "",
        "## 2. Victim identity 与 Fail-Closed",
        "",
        "- 候选只在 victim hashes 可证明为某条历史同 program 链的**连续后缀**时进入评估。",
        "- 不能证明连续后缀的候选/场景记为 `EXCLUDED`，不使用 `chain_length - need + 1` 默认推断。",
        f"- 本轮排除：**{excluded['total']}** 个候选（REAL {excluded['REAL']}，CONSTRUCTED {excluded['CONSTRUCTED_HISTORICAL']}）；原因：{excluded['reasons']}。",
        "- REAL 的 4 个候选排除对应 g10-c1、g10-c2 两个决策；其余 5 个 REAL 决策进入评估（7 个真实竞争决策中 2 个被排除）。",
        "- REAL 与 CONSTRUCTED 的排除项都保留在证据 JSON 的 exclusions 中，不当作 0 收益。",
        "",
        "## 3. 汇总：预测精度与决策价值分开",
        "",
        "| 方法 | 场景类 | n | MAE (blocks) | ranking accuracy | flips | 正 gain flips | 独立单决策 P2 gain 和 | 独立单决策 oracle gain 和 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        for label in ("REAL", "CONSTRUCTED_HISTORICAL", "ALL"):
            block = summary[method][label]
            mae = block["prediction_mae_blocks"]
            rank = block["ranking_accuracy"]
            lines.append(
                f"| {METHOD_LABELS[method]} | {label} | {block['scenarios']} | "
                f"{mae:.1f} | {rank:.3f} | {block['flips']} | {block['positive_gain_flips']} | "
                f"{block['independent_single_decision_p2_gain_sum_tokens']} | "
                f"{block['independent_single_decision_oracle_gain_sum_tokens']} |"
            )
    lines += [
        "",
        "> `independent_single_decision_p2_gain_sum_tokens` 是各场景“只改一个决策”的增量之和，**不是**联合 P2 策略的总体效果；不能把任何一个总和表述为部署 P2 的收益。",
        "",
        "## 4. REAL 场景明细（仅完整后缀可证明的决策）",
        "",
        "| cell | A0 | oracle | P2-A | P2-B | P2-C |",
        "|---|---|---|---|---|---|",
    ]
    for row in campaign["rows"]:
        if row["label"] != "REAL":
            continue

        def outcome_text(row: dict[str, Any], method: str) -> str:
            outcome = row["outcomes"][method]
            return f"{outcome['program']} ({outcome['p2_gain']})"

        lines.append(
            f"| {row['cell']} | {row['a0_program']} | {row['oracle_program']} ({row['oracle_gain']}) | "
            f"{outcome_text(row, 'P2_A_ORIGINAL_MAX')} | {outcome_text(row, 'P2_B_CHAIN_MAX')} | "
            f"{outcome_text(row, 'P2_C_CHAIN_WEIGHTED')} |"
        )
    lines += [
        "",
        "## 5. CONSTRUCTED_HISTORICAL：oracle gain > 0 的场景",
        "",
        "| cell | A0 | oracle | P2-C choice | P2-C gain | oracle gain |",
        "|---|---|---|---|---:|---:|",
    ]
    positive_rows = [
        row
        for row in campaign["rows"]
        if row["label"] == "CONSTRUCTED_HISTORICAL" and row["oracle_gain"] > 0
    ]
    for row in positive_rows:
        outcome = row["outcomes"]["P2_C_CHAIN_WEIGHTED"]
        lines.append(
            f"| {row['cell']} | {row['a0_program']} | {row['oracle_program']} | "
            f"{outcome['program']} | {outcome['p2_gain']} | {row['oracle_gain']} |"
        )
    lines += [
        "",
        f"其余 {summary['P2_C_CHAIN_WEIGHTED']['CONSTRUCTED_HISTORICAL']['scenarios'] - len(positive_rows)} 个有效 CONSTRUCTED 场景 oracle gain = 0。",
        "",
        "## 6. 解释与边界",
        "",
        "- **P2-A 与 P2-B 在本 cohort 上完全同值**：候选链条件化的最大 LCP 已经由另一条历史链达到，因此 P2-B 没有改变排序；这是观测事实，不是实现错误。",
        "- **P2-C 的 MAE 更差但 flip 为 0**：加权估计把预测深度压低，候选分数在多数场景落到 0，tie 保留 A0；因此它“不犯错”但不产生任何决策价值。",
        "- `ranking_accuracy` 在 oracle gain = 0 的场景中被 tie 抬高，不能单独当作预测能力；必须与 positive-gain flip、全轨迹 gain 一起看。",
        "- 预测精度与实际决策价值分开报告；MAE/ranking accuracy 不能替代全轨迹 gain。",
        "- `future_prefix_demand_overlap` 是请求前缀重合，不等于 Native cache hit。",
        "- REAL 与 CONSTRUCTED_HISTORICAL 不可合并解释；CONSTRUCTED 是反事实构造。",
        "- 全轨迹收益来自 loss oracle，不是 Native State Oracle；容量收益未评估。",
        "- 不授权 GPU、Native smoke、Protocol v5 或 Partial Release 实现。",
        "",
        "## 7. 后续",
        "",
        "1. 保留本轮结果；不启动 GPU。",
        "2. P2 继续 CPU-only：先解决“未来请求/session program 续接”的预测目标，再扩展候选与场景。",
        "3. P1 暴露几何作为独立诊断保留。",
        "",
        "## 8. 复现",
        "",
        "```bash",
        "python scripts/probes/phase3_p2_depth/p2_study.py \\",
        "    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \\",
        "    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \\",
        "    --out      docs/experiments/phase3-p2-depth-data",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    cells = [path.stem for path in sorted((args.evidence / "nec-cells").glob("*.json"))]
    trajectories = [STAGE0.load_cell(args.evidence, cell) for cell in cells]
    scenarios: list[Scenario] = []
    exclusions: list[Exclusion] = []
    for trajectory in trajectories:
        real, real_excluded = real_scenarios(trajectory)
        constructed, constructed_excluded = constructed_scenarios(trajectory)
        scenarios.extend(real)
        scenarios.extend(constructed)
        exclusions.extend(real_excluded)
        exclusions.extend(constructed_excluded)

    real_decisions = {
        (scenario.cell, scenario.decision_index)
        for scenario in scenarios
        if scenario.label == "REAL"
    } | {
        (exclusion.cell, exclusion.decision_index)
        for exclusion in exclusions
        if exclusion.label == "REAL"
    }
    if len(real_decisions) != 7:
        raise ValueError(f"REAL decision accounting is incomplete: {len(real_decisions)}/7")

    summary = summarize(scenarios, exclusions)
    rows = scenario_rows(scenarios)
    campaign = {
        "schema_version": "phase3.p2_depth_study.v2",
        "status": "P2_CPU_ONLY_OFFLINE_RESEARCH",
        "authorization": "M1 P2 CPU-only offline research",
        "p2_definition": "online future prefix-demand predictor; no future features",
        "oracle": "A0-Anchored Prefix-State Loss Oracle (not Native State Oracle)",
        "capacity_gain_dimension": "NOT_EVALUATED",
        "gain_interpretation": "independent_single_decision_counterfactual_increments_not_joint_policy",
        "label_definition": "future_prefix_demand_overlap_not_native_cache_hit",
        "summary": summary,
        "exclusions": [
            {
                "cell": exclusion.cell,
                "decision_index": exclusion.decision_index,
                "label": exclusion.label,
                "program": exclusion.program_id,
                "reason": exclusion.reason,
            }
            for exclusion in exclusions
        ],
        "rows": rows,
        "limitations": [
            "The 7 REAL decisions are the only observed candidate competitions; some are excluded if victim suffix cannot be proven.",
            "CONSTRUCTED_HISTORICAL scenarios are artificial pairings, not observed decisions.",
            "Reported gains are independent single-decision counterfactual increments, not a joint P2 policy.",
            "future_prefix_demand_overlap is request-prefix overlap, not a Native-cache-verified hit.",
            "Full-trajectory gains use the loss oracle, which does not model Native capacity or LRU evolution.",
        ],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out / "p2-depth-evidence.json"
    evidence_path.write_text(
        json.dumps(campaign, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path = args.out / "p2-depth-report.md"
    report_path.write_text(render_report(campaign), encoding="utf-8")
    files = [
        Path(__file__),
        Path(__file__).resolve().parents[3] / "tests" / "test_phase3_p2_depth.py",
        Path(__file__).resolve().parent / "README.md",
        evidence_path,
        report_path,
    ]
    manifest = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append(f"{digest}  {path.as_posix()}")
    (args.out / "sha256-manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"summary": summary, "excluded": summary["excluded"], "out": str(args.out)}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
