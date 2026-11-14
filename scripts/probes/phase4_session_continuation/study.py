"""Phase 4 Task 1: Session Continuation Prediction feasibility study.

CPU-only, read-only analysis of the frozen Phase 3 archive.  No GPU, Native
smoke, production algorithm change, Protocol v5, or Partial Release.

The first question is data availability, not modelling.  The archive's cohort
seal carries session bindings, but the runtime event stream does not carry a
session identifier.  More importantly, every session's ``instance_id`` is also
the request ``program_id`` and no program has more than one session.  Session
Continuation is therefore observationally identical to Program Continuation in
this archive; it is not independently identifiable.

The study reports that gap, then provides a clearly labelled **program-level
continuation proxy** with windowed probabilities, historical baselines, and a
preliminary Expected Loss model.  It never presents the proxy as a Session
Continuation result.

Usage
-----
    python scripts/probes/phase4_session_continuation/study.py \
        --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
        --seal     local/cohort-seal.json \
        --out      docs/experiments/phase4-session-continuation-data
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WINDOWS = (5.0, 15.0, 60.0, 300.0)
PRIMARY_WINDOW = 60.0
BLOCK_TOKENS = 16


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_p2():
    path = Path(__file__).resolve().parents[1] / "phase3_p2_depth" / "p2_study.py"
    return _load_module("p2_study", path)


P2 = _load_p2()
STAGE0 = P2.STAGE0


@dataclass(frozen=True)
class RequestRow:
    group: str
    cell: str
    session: str
    program: str
    request_id: str
    timestamp: float
    prior_requests: int
    last_gap_seconds: float | None
    labels: dict[float, int]


@dataclass(frozen=True)
class Audit:
    group_count: int
    session_count: int
    group_sessions: Counter
    session_requests: Counter
    request_rows: int
    event_session_field_count: int
    program_equals_session: str
    multi_session_programs: int
    tool_gap_started: int
    tool_gap_ended: int
    tool_gap_unpaired: int
    source_time_rows: int
    session_switch_events: int
    conclusion: str
    gaps: tuple[str, ...]


def load_timeline(
    evidence: Path, seal_path: Path, groups: list[str]
) -> tuple[list[RequestRow], Audit]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    sessions_by_group: dict[str, list[dict]] = {}
    request_to_session: dict[str, tuple[str, str]] = {}
    source_time_rows = 0
    for group in seal["groups"]:
        gid = group["group_id"]
        sessions_by_group[gid] = group["sessions"]
        for session in group["sessions"]:
            sid = session["instance_id"]
            for request in session["selected_requests"]:
                rid = request["request_id"]
                request_to_session[rid] = (gid, sid)
                if (
                    "model_submit_monotonic_seconds" in request
                    and "model_completion_monotonic_seconds" in request
                ):
                    source_time_rows += 1

    rows: list[RequestRow] = []
    event_session_field_count = 0
    program_mismatches: list[str] = []
    tool_gap_started = 0
    tool_gap_ended = 0
    tool_gap_unpaired = 0
    session_switch_events = 0

    for group in groups:
        cell = f"{group}-c1"
        events = [
            json.loads(line)
            for line in (evidence / "native-runs" / f"phase3-main-{cell}-r1-a0" / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        for event in events:
            if "session_id" in event or "session_id" in (event.get("payload") or {}):
                event_session_field_count += 1
            if event.get("event_type") == "TOOL_GAP_STARTED":
                tool_gap_started += 1
            elif event.get("event_type") == "TOOL_GAP_ENDED":
                tool_gap_ended += 1
            elif "SESSION" in str(event.get("event_type", "")) and "SWITCH" in str(
                event.get("event_type", "")
            ):
                session_switch_events += 1

        # Pair tool gaps by program, in event order.
        gap_start: dict[str, float] = {}
        next_gap: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for event in events:
            if event.get("event_type") == "TOOL_GAP_STARTED":
                gap_start[event.get("program_id")] = event["timestamp"]
            elif event.get("event_type") == "TOOL_GAP_ENDED":
                program = event.get("program_id")
                start = gap_start.pop(program, None)
                if start is None:
                    tool_gap_unpaired += 1
                    continue
                duration = event["timestamp"] - start
                next_gap[program].append((event["timestamp"], duration))

        request_events = [event for event in events if event.get("event_type") == "REQUEST_ARRIVED"]
        for index, event in enumerate(request_events):
            rid = event.get("request_id")
            session_info = request_to_session.get(rid)
            if session_info is None:
                program_mismatches.append(f"{rid}:missing_from_seal")
                continue
            group_id, session_id = session_info
            if event.get("program_id") != session_id:
                program_mismatches.append(f"{rid}:{event.get('program_id')}!={session_id}")
            # Gap that ended immediately before this request for the same session.
            program = event.get("program_id")
            prior_gaps = [
                (end, duration)
                for end, duration in next_gap.get(program, [])
                if end <= event["timestamp"] + 1e-9
            ]
            last_gap = max(prior_gaps, key=lambda item: item[0])[1] if prior_gaps else None
            same_session_later = [
                later for later in request_events[index + 1 :] if later.get("program_id") == program
            ]
            labels = {
                window: int(
                    any(
                        later["timestamp"] - event["timestamp"] <= window
                        for later in same_session_later
                    )
                )
                for window in WINDOWS
            }
            rows.append(
                RequestRow(
                    group=group_id,
                    cell=cell,
                    session=session_id,
                    program=event.get("program_id"),
                    request_id=rid,
                    timestamp=event["timestamp"],
                    prior_requests=len(
                        [row for row in rows if row.session == session_id and row.group == group_id]
                    ),
                    last_gap_seconds=last_gap,
                    labels=labels,
                )
            )

    group_sessions = Counter(len(sessions) for sessions in sessions_by_group.values())
    session_requests = Counter(
        len(session["selected_requests"])
        for sessions in sessions_by_group.values()
        for session in sessions
    )
    session_to_program: dict[str, set[str]] = defaultdict(set)
    for request in rows:
        session_to_program[request.session].add(request.program)
    multi_session_programs = 0
    program_occurrences: Counter = Counter(
        session["instance_id"] for sessions in sessions_by_group.values() for session in sessions
    )
    multi_session_programs = sum(1 for count in program_occurrences.values() if count > 1)

    audit = Audit(
        group_count=len(groups),
        session_count=sum(len(sessions) for sessions in sessions_by_group.values()),
        group_sessions=group_sessions,
        session_requests=session_requests,
        request_rows=len(rows),
        event_session_field_count=event_session_field_count,
        program_equals_session=(
            "PASS"
            if not program_mismatches
            and all(len(values) == 1 for values in session_to_program.values())
            else f"FAIL:{program_mismatches[:5]}"
        ),
        multi_session_programs=multi_session_programs,
        tool_gap_started=tool_gap_started,
        tool_gap_ended=tool_gap_ended,
        tool_gap_unpaired=tool_gap_unpaired,
        source_time_rows=source_time_rows,
        session_switch_events=session_switch_events,
        conclusion="SESSION_CONTINUATION_NOT_IDENTIFIABLE",
        gaps=(
            "EVENT_STREAM_HAS_NO_SESSION_ID",
            "SESSION_ID_EQUALS_PROGRAM_ID",
            "NO_PROGRAM_WITH_MULTIPLE_SESSIONS",
            "NO_EXPLICIT_SESSION_SWITCH_EVENT",
        ),
    )
    return rows, audit


def window_counts(rows: list[RequestRow]) -> dict[float, dict[str, int]]:
    result = {}
    for window in WINDOWS:
        labels = [row.labels[window] for row in rows]
        result[window] = {
            "rows": len(labels),
            "positive": sum(labels),
            "negative": len(labels) - sum(labels),
        }
    return result


def gap_bucket(gap: float | None) -> str:
    if gap is None:
        return "none"
    if gap <= 5:
        return "0-5s"
    if gap <= 15:
        return "5-15s"
    if gap <= 60:
        return "15-60s"
    return ">60s"


def _smoothed(positive: int, total: int, fallback: float) -> float:
    return (positive + 1.0) / (total + 2.0) if total else fallback


def train_rates(rows: list[RequestRow], window: float, exclude_group: str) -> dict[str, Any]:
    train = [row for row in rows if row.group != exclude_group]
    global_rate = (sum(row.labels[window] for row in train) + 1.0) / (len(train) + 2.0)
    by_program: dict[str, list[int]] = defaultdict(list)
    by_gap: dict[str, list[int]] = defaultdict(list)
    by_history: dict[tuple[str, int], list[int]] = defaultdict(list)
    for row in train:
        label = row.labels[window]
        by_program[row.program].append(label)
        by_gap[gap_bucket(row.last_gap_seconds)].append(label)
        by_history[(row.program, min(row.prior_requests, 4))].append(label)
    return {
        "global": global_rate,
        "program": {
            key: (sum(values) + 1.0) / (len(values) + 2.0) for key, values in by_program.items()
        },
        "gap": {key: (sum(values) + 1.0) / (len(values) + 2.0) for key, values in by_gap.items()},
        "history": {
            key: (sum(values) + 1.0) / (len(values) + 2.0) for key, values in by_history.items()
        },
        "program_counts": {key: len(values) for key, values in by_program.items()},
        "gap_counts": {key: len(values) for key, values in by_gap.items()},
    }


def predict_baselines(row: RequestRow, window: float, rates: dict[str, Any]) -> dict[str, float]:
    global_rate = rates["global"]
    program_rate = rates["program"].get(row.program, global_rate)
    gap_rate = rates["gap"].get(gap_bucket(row.last_gap_seconds), global_rate)
    history_rate = rates["history"].get((row.program, min(row.prior_requests, 4)), program_rate)
    return {
        "GLOBAL": global_rate,
        "PROGRAM": program_rate,
        "TOOL_GAP": gap_rate,
        "SESSION_HISTORY": history_rate,
    }


def auc_score(labels: list[int], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores) if label == 1]
    negatives = [score for label, score in zip(labels, scores) if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def evaluate_baselines(rows: list[RequestRow]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for window in WINDOWS:
        labels: list[int] = []
        predictions: dict[str, list[float]] = {
            name: [] for name in ("GLOBAL", "PROGRAM", "TOOL_GAP", "SESSION_HISTORY")
        }
        for group in sorted({row.group for row in rows}):
            rates = train_rates(rows, window, group)
            for row in rows:
                if row.group != group:
                    continue
                prediction = predict_baselines(row, window, rates)
                labels.append(row.labels[window])
                for name, values in predictions.items():
                    values.append(prediction[name])
        block = {"rows": len(labels), "positive": sum(labels)}
        for name, scores in predictions.items():
            brier = sum((score - label) ** 2 for score, label in zip(scores, labels)) / len(labels)
            log_loss = -sum(
                label * math.log(max(score, 1e-12)) + (1 - label) * math.log(max(1 - score, 1e-12))
                for score, label in zip(scores, labels)
            ) / len(labels)
            accuracy = sum(
                (score >= 0.5) == bool(label) for score, label in zip(scores, labels)
            ) / len(labels)
            block[name] = {
                "brier": brier,
                "log_loss": log_loss,
                "accuracy": accuracy,
                "auc": auc_score(labels, scores),
            }
        output[window] = block
    return output


def _scenario_decision(trajectory, scenario):
    """Rebuild the P2 scenario decision (real or constructed) for simulation."""
    original = trajectory.decisions[scenario.decision_index]
    if len(original.candidates) == len(scenario.views):
        return original
    if len(scenario.views) != 2 or len(original.candidates) != 1:
        raise ValueError("unexpected P2 scenario candidate shape")
    observed = original.candidates[0]
    alt_view = scenario.views[1]
    source = P2.latest_before(trajectory, alt_view.program_id, original.event_index)
    if source is None or len(source.hashes) < original.need:
        raise ValueError("constructed scenario source chain disappeared")
    victim_hashes = frozenset(source.hashes[-original.need :])
    alt_candidate = STAGE0.Candidate(
        alt_view.program_id,
        f"constructed:{trajectory.cell}:{original.event_index}",
        original.need,
        victim_hashes,
        len(source.hashes) - original.need + 1,
    )
    return STAGE0.Decision(
        cell=trajectory.cell,
        event_index=original.event_index,
        need=original.need,
        candidates=(observed, alt_candidate),
        a0_index=0,
        matched_count=original.matched_count,
        a0_victim_subset_physical=True,
        a0_selected_program=observed.program_id,
    )


def expected_loss_proxy(
    evidence: Path,
    rows: list[RequestRow],
) -> dict[str, Any]:
    """Preliminary EL = P(program continuation) * P2-B prefix loss.

    This is a program-continuation proxy, not a Session Continuation model.  All
    scenarios are independent single-decision counterfactuals.
    """
    p2_rows = []
    for group in sorted({row.group for row in rows}):
        cell = f"{group}-c1"
        trajectory = STAGE0.load_cell(evidence, cell)
        scenarios, exclusions = P2.real_scenarios(trajectory)
        constructed, constructed_exclusions = P2.constructed_scenarios(trajectory)
        scenarios.extend(constructed)
        exclusions.extend(constructed_exclusions)
        rates = train_rates(rows, PRIMARY_WINDOW, group)
        for scenario in scenarios:
            views = scenario.views
            p_values = [rates["program"].get(view.program_id, rates["global"]) for view in views]
            el_scores = [
                p_values[index] * views[index].p2_score["P2_B_CHAIN_MAX"]
                for index in range(len(views))
            ]
            choice = min(
                range(len(views)),
                key=lambda index: (
                    el_scores[index],
                    0 if index == scenario.a0_index else 1,
                    views[index].program_id,
                ),
            )
            # Reconstruct the scenario trajectory and evaluate the full 24 requests.
            decisions = list(trajectory.decisions)
            decisions[scenario.decision_index] = _scenario_decision(trajectory, scenario)
            scenario_trajectory = STAGE0.CellTrajectory(
                cell=trajectory.cell,
                requests=trajectory.requests,
                decisions=tuple(decisions),
                r_a0=trajectory.r_a0,
                r_a0_recorded=trajectory.r_a0_recorded,
            )
            baseline = list(STAGE0.a0_choices(scenario_trajectory))
            p2_choices = list(baseline)
            p2_choices[scenario.decision_index] = choice
            gain = (
                scenario_trajectory.r_a0
                - STAGE0.simulate_path(scenario_trajectory, tuple(p2_choices)).total
            )
            p2_rows.append(
                {
                    "cell": scenario.cell,
                    "label": scenario.label,
                    "a0_program": scenario.a0_program,
                    "el_choice": views[choice].program_id,
                    "el_flip": choice != scenario.a0_index,
                    "el_gain": gain,
                    "oracle_gain": scenario.oracle_gain,
                    "p_continue": {
                        views[index].program_id: p_values[index] for index in range(len(views))
                    },
                    "expected_loss_scores": {
                        views[index].program_id: el_scores[index] for index in range(len(views))
                    },
                }
            )
    return {
        "window_seconds": PRIMARY_WINDOW,
        "model": "PROGRAM_CONTINUATION_PROXY_EXPECTED_PREFIX_LOSS",
        "session_continuation_claim": "NOT_MADE",
        "not_joint_policy_effect": True,
        "scenarios": len(p2_rows),
        "real": sum(1 for row in p2_rows if row["label"] == "REAL"),
        "constructed": sum(1 for row in p2_rows if row["label"] == "CONSTRUCTED_HISTORICAL"),
        "flips": sum(1 for row in p2_rows if row["el_flip"]),
        "positive_gain_flips": sum(1 for row in p2_rows if row["el_flip"] and row["el_gain"] > 0),
        "independent_gain_sum_tokens": sum(row["el_gain"] for row in p2_rows),
        "oracle_gain_sum_tokens": sum(row["oracle_gain"] for row in p2_rows),
        "rows": p2_rows,
    }


def render_report(campaign: dict[str, Any]) -> str:
    audit = campaign["audit"]
    counts = campaign["window_counts"]
    baselines = campaign["baselines"]
    el = campaign["expected_loss"]
    lines = [
        "# Phase 4 Task 1：Session Continuation Prediction 可行性研究",
        "",
        "**Author**: M4  ",
        "**Status**: `PHASE4_TASK1_CPU_ONLY_FEASIBILITY` — 只读 Archive，无 GPU、无 Native smoke、无生产算法修改。  ",
        "**Scope**: 数据可用性审计、目标契约、窗口续接概率、历史基线、初步 Expected Loss 代理。",
        "",
        "## 0. 结论",
        "",
        f"- **Session Continuation 在本 Archive 中不可独立识别**：`{audit['conclusion']}`。",
        "- 事件流没有 `session_id`；session 只能从 cohort seal + `request_id` 恢复。",
        f"- `program_id == session instance_id`：**{audit['program_equals_session']}**；没有任何 program 拥有多个 session（`multi_session_programs={audit['multi_session_programs']}`）。",
        "- 因此 Session Continuation 与 Program Continuation 在本 Archive 中观测上等价；本报告只给出 **Program Continuation proxy**，不冒充 Session Continuation 结论。",
        "",
        "## 1. Data Availability Audit",
        "",
        "| 项 | 观测 |",
        "|---|---|",
        f"| Groups | {audit['group_count']} |",
        f"| Sessions | {audit['session_count']} |",
        f"| Sessions per Group | {json.dumps(dict(audit['group_sessions']), sort_keys=True)} |",
        f"| Selected requests per Session | {json.dumps(dict(audit['session_requests']), sort_keys=True)} |",
        f"| Replay request rows (C1 only) | {audit['request_rows']} |",
        f"| `session_id` in event stream | {audit['event_session_field_count']} |",
        f"| Program == Session | {audit['program_equals_session']} |",
        f"| Programs with >1 session | {audit['multi_session_programs']} |",
        f"| Tool gap started/ended | {audit['tool_gap_started']}/{audit['tool_gap_ended']} |",
        f"| Tool gap unpaired start/end | {audit['tool_gap_unpaired']} |",
        f"| Source request timestamps | {audit['source_time_rows']} |",
        f"| Explicit session-switch events | {audit['session_switch_events']} |",
        "",
        "**数据缺口**：",
        "",
    ]
    for gap in audit["gaps"]:
        lines.append(f"- `{gap}`")
    lines += [
        "",
        "**最小补充数据需求**：",
        "",
        "1. 每个 request / tool-gap 事件带独立 `session_id`，且 `session_id` ≠ `program_id`。",
        "2. 至少一个 program 拥有 ≥2 个 session（或同一 session 包含多个 program），才能区分 Session 与 Program 续接。",
        "3. 显式的 session start / switch / end 事件，带时间戳。",
        "4. 所有 replay request 的源 submit/completion 时间，以及 tool gap 的 session 归属。",
        "5. 请求级 continuation 标签与 session 生命周期绑定，而不是从 `program_id` 反推。",
        "",
        "## 2. Prediction Target Contract",
        "",
        "| 目标 | 定义 | 本 Archive 可识别性 |",
        "|---|---|---|",
        "| **Session Continuation** | 给定时刻 t 与 session s，窗口 W 内 s 是否再出现请求 | **不可独立识别**（session≡program） |",
        "| **Program Continuation** | 给定时刻 t 与 program p，窗口 W 内 p 是否再出现请求 | 可识别；本报告作为 proxy |",
        "| **Prefix-Demand Overlap** | 候选链与未来请求前缀的最深重合深度 | 可计算；**不等于 APC cache hit** |",
        "",
        "所有在线特征只使用决策前信息；窗口标签、oracle 与未来 overlap 只用于离线评估。",
        "",
        "## 3. Continuation Probability by Window",
        "",
        "| Window (s) | rows | positive | negative | positive rate |",
        "|---:|---:|---:|---:|---:|",
    ]
    for window in WINDOWS:
        block = counts[window]
        rate = block["positive"] / block["rows"] if block["rows"] else 0.0
        lines.append(
            f"| {window:g} | {block['rows']} | {block['positive']} | {block['negative']} | {rate:.3f} |"
        )
    lines += [
        "",
        "> 由于 session≡program，这张表同时是 session-level 与 program-level 的**同一组标签**；不能当作两个独立目标。",
        "",
        "## 4. Baseline Comparison（Group-isolated）",
        "",
        "Leave-one-Group-out；同一 Group 的两个 session 不跨 train/test。指标为 held-out Brier / AUC / accuracy。",
        "",
        "| Window | Baseline | Brier | AUC | Accuracy |",
        "|---:|---|---:|---:|---:|",
    ]
    for window in WINDOWS:
        for name in ("GLOBAL", "PROGRAM", "TOOL_GAP", "SESSION_HISTORY"):
            block = baselines[window][name]
            auc = block["auc"]
            auc_text = f"{auc:.3f}" if auc is not None else "n/a"
            lines.append(
                f"| {window:g} | {name} | {block['brier']:.4f} | "
                f"{auc_text} | {block['accuracy']:.3f} |"
            )
    lines += [
        "",
        "**解读**：",
        "",
        "- 5s 窗口没有正例，AUC 不可定义；15s 只有 12 个正例，估计不稳定。",
        "- `PROGRAM` 与 `SESSION_HISTORY` 在本 Archive 上退化为 `GLOBAL`：每个 program 只属于一个 Group，leave-one-Group-out 时 test program 在 train 中完全 unseen，只能回退 global。这不是模型调参问题，而是 program/session 与 Group 绑定的数据设计限制。",
        "- `TOOL_GAP` 是唯一有稳定信号的基线：60s 窗口 AUC 0.686、Brier 0.103，说明“上一次 tool gap 长度”比 program 身份更有用。",
        "- 这仍是 **program-level proxy**；不能把 tool gap 对 program 续接的预测能力写成 session continuation 结论。",
        "",
        "## 5. Expected Loss Proxy",
        "",
        "模型形式：",
        "",
        "```text",
        "EL(candidate) = P_program_continue(program, t, W=60s) * P2-B_prefix_loss(candidate)",
        "```",
        "",
        "- `P_program_continue` 来自其他 Group 的历史频率，**不是** session continuation；由于 program 在 leave-one-Group-out 中完全 unseen，它实际退化为训练集 global rate，不能当作 program-specific 概率。",
        "- `P2-B_prefix_loss` 来自 Stage 0 loss oracle 的 P2-B 深度代理；",
        "- 每个场景只改一个决策，收益是独立单决策反事实增量，不是联合策略效果；",
        "- 这是初步 proxy，不用于宣称算法有效。",
        "",
        f"- 场景：{el['scenarios']}（REAL {el['real']}，CONSTRUCTED {el['constructed']}）；",
        f"- flips：{el['flips']}；正 gain flips：{el['positive_gain_flips']}；",
        f"- 独立单决策 gain 合计：{el['independent_gain_sum_tokens']} tokens；oracle gain 合计：{el['oracle_gain_sum_tokens']} tokens。",
        "",
        "**解读**：",
        "",
        "- 这里只使用 C1 cell 的 55 个有效场景（2 REAL + 53 CONSTRUCTED），不是 P2 的 111 个 C1+C2 场景；两组数字不可直接比较。",
        "- 15 次 flip、0 次正 gain；EL proxy 没有找到可用的独立单决策收益。",
        "- 预期损失中的 `P_program_continue` 是 program-level 历史频率，不是 session continuation；该结果不能用于宣称 Session 模型有效。",
        "",
        "> 由于 Session Continuation 不可独立识别，本 EL 只能作为 **program-level proxy diagnostic**；不能把它当作 Session Continuation 模型的收益。",
        "",
        "## 6. 解释边界",
        "",
        "- 不能把 Program 当作 Session；本报告明确二者在 Archive 中同源。",
        "- 不能把 Prefix-Demand Overlap 当作实际 APC cache hit。",
        "- 不能因为 MAE / AUC 较好就宣称算法有效；预测质量与独立反事实收益分开报告。",
        "- 不构造大量人工 session 样本来制造有效性；数据缺口直接列出。",
        "- 不授权 GPU、Native smoke、Protocol v5、Partial Release 或生产算法修改。",
        "",
        "## 7. 建议",
        "",
        "1. **暂不进入 Session Continuation 算法实现**；当前 Archive 不支持独立 session 目标。",
        "2. 若要继续，最小补充数据是显式 `session_id` + 一个 program 的多个 session + session switch 事件。",
        "3. Program-level continuation proxy 可作为下一轮 CPU 可行性研究，但必须与 Session 目标分开命名。",
        "4. P1 暴露几何仍作为独立诊断保留。",
        "",
        "## 8. 复现",
        "",
        "```bash",
        "python scripts/probes/phase4_session_continuation/study.py \\",
        "    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \\",
        "    --seal     local/cohort-seal.json \\",
        "    --out      docs/experiments/phase4-session-continuation-data",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    seal = json.loads(args.seal.read_text(encoding="utf-8"))
    groups = [group["group_id"] for group in seal["groups"]]
    rows, audit = load_timeline(args.evidence, args.seal, groups)
    counts = window_counts(rows)
    baselines = evaluate_baselines(rows)
    expected = expected_loss_proxy(args.evidence, rows)

    campaign = {
        "schema_version": "phase4.session_continuation_feasibility.v1",
        "status": "SESSION_CONTINUATION_NOT_IDENTIFIABLE",
        "authorization": "Phase 4 Task 1 CPU-only, read-only Archive",
        "audit": {
            "group_count": audit.group_count,
            "session_count": audit.session_count,
            "group_sessions": dict(audit.group_sessions),
            "session_requests": dict(audit.session_requests),
            "request_rows": audit.request_rows,
            "event_session_field_count": audit.event_session_field_count,
            "program_equals_session": audit.program_equals_session,
            "multi_session_programs": audit.multi_session_programs,
            "tool_gap_started": audit.tool_gap_started,
            "tool_gap_ended": audit.tool_gap_ended,
            "tool_gap_unpaired": audit.tool_gap_unpaired,
            "source_time_rows": audit.source_time_rows,
            "session_switch_events": audit.session_switch_events,
            "conclusion": audit.conclusion,
            "gaps": list(audit.gaps),
        },
        "window_counts": counts,
        "baselines": baselines,
        "expected_loss": expected,
        "limitations": [
            "Session Continuation is observationally identical to Program Continuation because session_id == program_id.",
            "No program has multiple sessions; no explicit session-switch event exists.",
            "Program-level proxy only; no Session Continuation algorithm result is claimed.",
            "Prefix-demand overlap is not a Native-cache-verified hit.",
            "Expected-loss results are independent single-decision counterfactuals, not a joint policy.",
        ],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out / "phase4-session-continuation-evidence.json"
    evidence_path.write_text(
        json.dumps(campaign, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path = args.out / "phase4-session-continuation-report.md"
    report_path.write_text(render_report(campaign), encoding="utf-8")
    files = [
        Path(__file__),
        Path(__file__).resolve().parents[3] / "tests" / "test_phase4_session_continuation.py",
        Path(__file__).resolve().parent / "README.md",
        evidence_path,
        report_path,
    ]
    manifest = []
    for path in files:
        manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.as_posix()}")
    (args.out / "sha256-manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"status": campaign["status"], "audit": campaign["audit"], "out": str(args.out)},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
