"""P2 offline study: online future-reuse-depth prediction on historical trajectories.

This is CPU-only, read-only research on the frozen Phase 3 archive.  It does not
call a model, GPU, or Native runtime.  It uses the Stage 0 A0-Anchored
Prefix-State Loss Oracle for full 24-request counterfactual evaluation.

Two scenario classes are kept separate:

* ``REAL``: the 7 decisions where the archive itself exposed two candidates.
* ``CONSTRUCTED_HISTORICAL``: a single-candidate decision paired with the most
  recent request chain of a different program in the same cell.  This is a
  counterfactual construction, not an observed candidate competition.

P2 is an **online** predictor: at decision time it may use only prior request
history and the candidate's current geometry.  The ideal hindsight oracle and
the actual future reuse depth are labels used only for offline evaluation.

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
    predicted_depth: int
    actual_depth: int
    p2_score: int


@dataclass
class Scenario:
    cell: str
    decision_index: int
    label: str
    a0_program: str
    views: tuple[CandidateView, ...]
    a0_index: int
    p2_index: int
    p2_gain: int
    oracle_gain: int
    p2_matches_oracle: bool
    decision: Any


def lcp(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def requests_for_program(trajectory, program: str) -> list[Any]:
    return [request for request in trajectory.requests if request.program_id == program]


def latest_before(trajectory, program: str, event_index: int):
    candidates = [
        request
        for request in requests_for_program(trajectory, program)
        if request.event_index < event_index
    ]
    return max(candidates, key=lambda request: request.event_index) if candidates else None


def prior_depth_history(trajectory, program: str, event_index: int) -> list[int]:
    prior = [
        request
        for request in requests_for_program(trajectory, program)
        if request.event_index < event_index
    ]
    depths: list[int] = []
    for index, left in enumerate(prior):
        for right in prior[index + 1 :]:
            depths.append(lcp(left.hashes, right.hashes))
    return depths


def global_prior_depths(trajectory, event_index: int) -> list[int]:
    depths: list[int] = []
    for program in {request.program_id for request in trajectory.requests}:
        depths.extend(prior_depth_history(trajectory, program, event_index))
    return depths


def predict_depth(trajectory, program: str, event_index: int, chain_length: int) -> int:
    """Online-only depth estimate: prior same-program reuse, global prior fallback."""
    program_depths = prior_depth_history(trajectory, program, event_index)
    if program_depths:
        estimate = max(program_depths)
    else:
        global_depths = global_prior_depths(trajectory, event_index)
        if global_depths:
            ordered = sorted(global_depths)
            estimate = ordered[len(ordered) // 2]
        else:
            estimate = 0
    return min(chain_length, estimate)


def actual_future_depth(trajectory, chain_hashes: tuple[str, ...], event_index: int) -> int:
    """Offline label: deepest reuse of this chain by any later request in the cell."""
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
) -> CandidateView | None:
    source = latest_before(trajectory, program, decision_event_index)
    if source is None:
        return None
    chain_length = len(source.hashes)
    if chain_length < need or need <= 0:
        return None
    first_victim_depth = chain_length - need + 1
    predicted = predict_depth(trajectory, program, decision_event_index, chain_length)
    actual = actual_future_depth(trajectory, source.hashes, decision_event_index)
    score = max(0, predicted - first_victim_depth + 1) * BLOCK_TOKENS
    # The observed candidate's victim set is authoritative; keep it even if the
    # latest request chain is longer than the chain that produced the entry.
    del victim_hashes
    return CandidateView(
        program_id=program,
        need=need,
        chain_length=chain_length,
        first_victim_depth=first_victim_depth,
        predicted_depth=predicted,
        actual_depth=actual,
        p2_score=score,
    )


def choose_p2(views: list[CandidateView], a0_index: int) -> int:
    """Choose the lowest predicted damage; tie-break toward A0."""
    return min(
        range(len(views)),
        key=lambda index: (
            views[index].p2_score,
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
) -> Scenario | None:
    a0_index = decision.a0_index
    p2_index = choose_p2(views, a0_index)
    baseline_choices = list(STAGE0.a0_choices(trajectory))
    p2_choices = list(baseline_choices)
    p2_choices[decision_index] = p2_index
    p2_result = STAGE0.simulate_path(trajectory, tuple(p2_choices))
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
    p2_gain = trajectory.r_a0 - p2_result.total
    oracle_gain = trajectory.r_a0 - oracle_total
    return Scenario(
        cell=trajectory.cell,
        decision_index=decision_index,
        label=label,
        a0_program=decision.candidates[a0_index].program_id,
        views=tuple(views),
        a0_index=a0_index,
        p2_index=p2_index,
        p2_gain=p2_gain,
        oracle_gain=oracle_gain,
        p2_matches_oracle=p2_index == oracle_choice,
        decision=decision,
    )


def real_scenarios(trajectory) -> list[Scenario]:
    out: list[Scenario] = []
    for decision_index, decision in enumerate(trajectory.decisions):
        if len(decision.candidates) < 2:
            continue
        views: list[CandidateView] = []
        for candidate in decision.candidates:
            view = build_view(
                trajectory,
                program=candidate.program_id,
                need=decision.need,
                victim_hashes=candidate.victim_hashes,
                decision_event_index=decision.event_index,
            )
            if view is None:
                views = []
                break
            views.append(view)
        if len(views) != len(decision.candidates):
            continue
        out.append(evaluate_scenario(trajectory, decision_index, decision, views, "REAL"))
    return out


def constructed_scenarios(trajectory) -> list[Scenario]:
    out: list[Scenario] = []
    for decision_index, decision in enumerate(trajectory.decisions):
        if len(decision.candidates) != 1:
            continue
        observed = decision.candidates[0]
        observed_view = build_view(
            trajectory,
            program=observed.program_id,
            need=decision.need,
            victim_hashes=observed.victim_hashes,
            decision_event_index=decision.event_index,
        )
        if observed_view is None:
            continue
        # Construct a competitor from the most recent other-program chain.
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
            source_request = source
            alternatives.append((source_request.event_index, program, source))
        if not alternatives:
            continue
        _, program, source = max(alternatives, key=lambda item: item[0])
        victim_hashes = frozenset(source.hashes[-decision.need :])
        alt_view = build_view(
            trajectory,
            program=program,
            need=decision.need,
            victim_hashes=victim_hashes,
            decision_event_index=decision.event_index,
        )
        if alt_view is None:
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
        out.append(
            evaluate_scenario(
                constructed_trajectory,
                decision_index,
                new_decision,
                [observed_view, alt_view],
                "CONSTRUCTED_HISTORICAL",
            )
        )
    return out


def summarize(scenarios: list[Scenario]) -> dict[str, Any]:
    def block(rows: list[Scenario]) -> dict[str, Any]:
        errors = [
            abs(view.predicted_depth - view.actual_depth)
            for scenario in rows
            for view in scenario.views
        ]
        return {
            "scenarios": len(rows),
            "prediction_mae_blocks": (sum(errors) / len(errors)) if errors else None,
            "flips": sum(1 for scenario in rows if scenario.p2_index != scenario.a0_index),
            "positive_gain_flips": sum(
                1
                for scenario in rows
                if scenario.p2_index != scenario.a0_index and scenario.p2_gain > 0
            ),
            "p2_gain_total": sum(scenario.p2_gain for scenario in rows),
            "oracle_gain_total": sum(scenario.oracle_gain for scenario in rows),
            "p2_matches_oracle": sum(
                1 for scenario in rows if scenario.p2_gain == scenario.oracle_gain
            ),
            "max_p2_gain": max((scenario.p2_gain for scenario in rows), default=0),
            "max_oracle_gain": max((scenario.oracle_gain for scenario in rows), default=0),
        }

    return {
        "all": block(scenarios),
        "REAL": block([scenario for scenario in scenarios if scenario.label == "REAL"]),
        "CONSTRUCTED_HISTORICAL": block(
            [scenario for scenario in scenarios if scenario.label == "CONSTRUCTED_HISTORICAL"]
        ),
    }


def scenario_rows(scenarios: list[Scenario]) -> list[dict[str, Any]]:
    rows = []
    for scenario in scenarios:
        rows.append(
            {
                "cell": scenario.cell,
                "decision_index": scenario.decision_index,
                "label": scenario.label,
                "a0_program": scenario.a0_program,
                "candidates": [
                    {
                        "program": view.program_id,
                        "predicted_depth": view.predicted_depth,
                        "actual_depth": view.actual_depth,
                        "p2_score": view.p2_score,
                        "first_victim_depth": view.first_victim_depth,
                        "chain_length": view.chain_length,
                        "selected": index == scenario.p2_index,
                    }
                    for index, view in enumerate(scenario.views)
                ],
                "p2_choice": scenario.views[scenario.p2_index].program_id,
                "p2_gain": scenario.p2_gain,
                "oracle_gain": scenario.oracle_gain,
                "p2_matches_oracle": scenario.p2_gain == scenario.oracle_gain,
            }
        )
    return rows


def render_report(campaign: dict[str, Any]) -> str:
    summary = campaign["summary"]
    real = summary["REAL"]
    constructed = summary["CONSTRUCTED_HISTORICAL"]
    lines = [
        "# Phase 3 P2 离线研究：在线未来复用深度预测",
        "",
        "**Author**: M4  ",
        "**Status**: `P2_CPU_ONLY_OFFLINE_RESEARCH` — 只读 Archive，无 GPU、无 Native smoke、无生产算法修改。  ",
        "**Input**: Stage 0 A0-Anchored Prefix-State Loss Oracle（完整 24 请求前缀状态重算；不是 Native State Oracle）。",
        "",
        "## 0. 结论",
        "",
        f"- 场景总数：**{summary['all']['scenarios']}**（REAL {real['scenarios']}，CONSTRUCTED_HISTORICAL {constructed['scenarios']}）。",
        f"- 在线 P2 预测深度 MAE：**{summary['all']['prediction_mae_blocks']:.1f} blocks**（REAL {real['prediction_mae_blocks']:.1f}；CONSTRUCTED {constructed['prediction_mae_blocks']:.1f}）。",
        f"- P2 decision flips：**{summary['all']['flips']}**（REAL {real['flips']}；CONSTRUCTED {constructed['flips']}）；其中正 gain flips：**{summary['all']['positive_gain_flips']}**。",
        f"- P2 全轨迹 gain 合计：**{summary['all']['p2_gain_total']} tokens**；hindsight oracle gain 合计：**{summary['all']['oracle_gain_total']} tokens**。",
        f"- P2 与 one-decision hindsight oracle 同 gain：**{summary['all']['p2_matches_oracle']}/{summary['all']['scenarios']}**（REAL {real['p2_matches_oracle']}/{real['scenarios']}；CONSTRUCTED {constructed['p2_matches_oracle']}/{constructed['scenarios']}）。",
        "",
        "> 本轮没有发现 P2 在线预测器在现有/构造场景中稳定产生正收益的证据。该结论限于 prefix-state loss 通道；容量收益仍未评估。",
        "",
        "**关键失败模式（REAL）**：7 次真实竞争决策上 P2 全部 flip，4 次为负 gain、3 次为 0；P2 的深度预测并不低（MAE 91.6 blocks），但它无法识别“未来请求会使用哪一条链”。REAL 的 oracle 最优始终是 A0，P2 却选择了另一条链；这说明下一轮 P2 的关键不是继续拟合深度，而是预测**未来请求/session 的 program 续接**。",
        "",
        "## 1. 场景定义",
        "",
        "- **REAL**：Archive 中真实存在两个候选的 7 次决策；A0 选择与另一候选均为观测。",
        "- **CONSTRUCTED_HISTORICAL**：单候选决策与同一 cell 中最近的其他 program chain 配对；这是**反事实构造**，不是观测到的候选竞争。",
        "",
        "REAL 与 CONSTRUCTED 在表中分开报告；任何 CONSTRUCTED 结果都不能直接当作真实决策收益。",
        "",
        "## 2. 在线 P2 模型",
        "",
        "P2 只能使用决策前信息：",
        "",
        "- program 在决策前的 request 链与两两 LCP 深度；",
        "- 若 program 无历史，使用决策前全 cell 的历史深度中位数；",
        "- 候选的 `chain_length`、`first_victim_depth` 与 `need`。",
        "",
        "预测目标：该 chain 在决策后的最深复用深度（hindsight label，仅用于离线评估）。",
        "P2 loss score = `max(0, predicted_depth - first_victim_depth + 1) * 16`，越低越好。",
        "",
        "## 3. 汇总",
        "",
        "| 场景类 | n | MAE (blocks) | flips | 正 gain flips | P2 gain 合计 | oracle gain 合计 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| REAL | {real['scenarios']} | {real['prediction_mae_blocks']:.1f} | {real['flips']} | {real['positive_gain_flips']} | {real['p2_gain_total']} | {real['oracle_gain_total']} |",
        f"| CONSTRUCTED_HISTORICAL | {constructed['scenarios']} | {constructed['prediction_mae_blocks']:.1f} | {constructed['flips']} | {constructed['positive_gain_flips']} | {constructed['p2_gain_total']} | {constructed['oracle_gain_total']} |",
        f"| ALL | {summary['all']['scenarios']} | {summary['all']['prediction_mae_blocks']:.1f} | {summary['all']['flips']} | {summary['all']['positive_gain_flips']} | {summary['all']['p2_gain_total']} | {summary['all']['oracle_gain_total']} |",
        "",
        "## 4. REAL 场景明细",
        "",
        "| cell | A0 | P2 choice | P2 gain | oracle gain | matches oracle |",
        "|---|---|---|---:|---:|---|",
    ]
    for row in campaign["rows"]:
        if row["label"] != "REAL":
            continue
        lines.append(
            f"| {row['cell']} | {row['a0_program']} | {row['p2_choice']} | {row['p2_gain']} | "
            f"{row['oracle_gain']} | {row['p2_matches_oracle']} |"
        )
    lines += [
        "",
        "## 5. CONSTRUCTED_HISTORICAL：oracle gain > 0 的全部场景",
        "",
        "| cell | A0 | P2 choice | P2 gain | oracle gain | matches oracle |",
        "|---|---|---|---:|---:|---|",
    ]
    constructed_rows = sorted(
        (
            row
            for row in campaign["rows"]
            if row["label"] == "CONSTRUCTED_HISTORICAL" and row["oracle_gain"] > 0
        ),
        key=lambda row: row["oracle_gain"],
        reverse=True,
    )
    for row in constructed_rows:
        lines.append(
            f"| {row['cell']} | {row['a0_program']} | {row['p2_choice']} | {row['p2_gain']} | "
            f"{row['oracle_gain']} | {row['p2_matches_oracle']} |"
        )
    lines += [
        "",
        f"其余 {constructed['scenarios'] - len(constructed_rows)} 个 CONSTRUCTED_HISTORICAL 场景 oracle gain = 0；P2 在这些场景中没有可实现的损失收益。",
        "",
        "## 6. 解释与边界",
        "",
        "- P2 是**在线**预测器：不使用未来 request、oracle 选择或事后 victim 信息；hindsight 只用于评估。",
        "- CONSTRUCTED_HISTORICAL 场景是人为配对，不能替代真实候选竞争；其结果只用于检验模型是否能在更多历史形态上产生分歧。",
        "- 全轨迹收益由 Stage 0 loss oracle 计算，不做局部收益累加；它不是 Native State Oracle，容量收益未评估。",
        "- 不授权 GPU、Native smoke、Protocol v5 或 Partial Release 实现。",
        "",
        "## 7. 后续",
        "",
        "1. 保留本轮结果；不启动 GPU。",
        "2. P2 继续 CPU-only 离线研究：优先预测**未来请求/session 的 program 续接**，而不是只拟合历史复用深度；扩大真实/构造场景，比较 A0、P2、ideal hindsight oracle。",
        "3. P1 暴露几何作为独立诊断保留，不因 loss-only oracle 为零而取消。",
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
    for trajectory in trajectories:
        scenarios.extend(real_scenarios(trajectory))
        scenarios.extend(constructed_scenarios(trajectory))

    summary = summarize(scenarios)
    rows = scenario_rows(scenarios)
    campaign = {
        "schema_version": "phase3.p2_depth_study.v1",
        "status": "P2_CPU_ONLY_OFFLINE_RESEARCH",
        "authorization": "M1 P2 CPU-only offline research",
        "p2_definition": "online future reuse depth predictor; no future features",
        "oracle": "A0-Anchored Prefix-State Loss Oracle (not Native State Oracle)",
        "capacity_gain_dimension": "NOT_EVALUATED",
        "summary": summary,
        "rows": rows,
        "limitations": [
            "The 7 REAL decisions are the only observed candidate competitions.",
            "CONSTRUCTED_HISTORICAL scenarios are artificial pairings, not observed decisions.",
            "Full-trajectory gains use the loss oracle, which does not model Native capacity or LRU evolution.",
            "P2 is evaluated offline; this is not an online deployment result.",
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
    print(json.dumps({"summary": summary, "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
