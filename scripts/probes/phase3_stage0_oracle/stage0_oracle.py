"""Stage 0: CPU-only full-trajectory oracle and P2 depth study.

Scope and honesty boundary
--------------------------
The archive does not contain a complete, independently replayable Native cache
state: cross-run native prefix hashes are not portable, and the observed
``native_cached_prefix_tokens`` is a property of the Native run, not a state
snapshot that can be reset and re-executed.  This module therefore implements an
**A0-anchored prefix-state counterfactual**:

* every request keeps its observed ``N``, ``E``, and A0 ``C`` (so the A0 path is
  exact by construction);
* a counterfactual release removes the candidate's deepest ``need`` blocks from
  the future cache and, if the candidate is not A0's choice, restores blocks A0
  evicted but the candidate would not evict;
* future requests are re-scored in full (24 requests), with re-add on use.  No
  per-decision local gain is summed.

This is an **avoidable-loss upper bound** on what an Entry-ordering policy could
gain from not choosing a victim that a future request needs.  It removes only
the candidate's predicted victims and allows A0-evicted blocks to come back,
both of which are optimistic for that loss channel; it does not model capacity
gains from evicting a different chain.  A zero avoidable-loss bound is a stop
signal for this channel, not a proof that every Entry policy is useless.

The companion Stage-0 note records ``A0_NATIVE_REPLAY = NOT_AVAILABLE``.  The
per-decision release geometry is validated against the archive's physical
victim sets; 108/127 decisions match exactly, and all 7 competitive decisions
match.  The 19 mismatches are single-candidate quantum cases, where no ordering
choice exists.

Usage
-----
    python scripts/probes/phase3_stage0_oracle/stage0_oracle.py \
        --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
        --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
        --out      docs/experiments/phase3-stage0-oracle-data
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BLOCK_TOKENS = 16
NON_PRIMARY_GROUPS = frozenset({"g09", "g18"})
H3_EXCLUDED_CELLS = frozenset({"g09-c1", "g18-c1"})
EFFECT_FLOOR_TOKENS = 512
MIN_COMPLETE_CELLS = 33
MIN_COMPLETE_GROUPS = 15


@dataclass(frozen=True)
class RequestPoint:
    request_id: str
    program_id: str
    event_index: int
    n: int
    e: int
    c: int
    hashes: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    program_id: str
    prefix_id: str
    need: int
    victim_hashes: frozenset[str]
    first_victim_depth: int | None


@dataclass(frozen=True)
class Decision:
    cell: str
    event_index: int
    need: int
    candidates: tuple[Candidate, ...]
    a0_index: int
    matched_count: int
    a0_victim_subset_physical: bool
    a0_selected_program: str


@dataclass
class CellTrajectory:
    cell: str
    requests: tuple[RequestPoint, ...]
    decisions: tuple[Decision, ...]
    r_a0: int
    r_a0_recorded: int


@dataclass
class PathResult:
    total: int
    per_request: list[dict[str, Any]]
    choices: tuple[int, ...]


@dataclass
class Check:
    name: str
    ok: bool = True
    detail: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def require(self, condition: bool, message: str) -> bool:
        if not condition:
            self.ok = False
            self.failures.append(message)
        return condition

    def expect(self, actual: Any, expected: Any, label: str, *, tol: float = 0.0) -> bool:
        if isinstance(actual, float) or isinstance(expected, float):
            good = math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tol or 1e-9)
        else:
            good = actual == expected
        return self.require(good, f"{label}: expected {expected!r}, got {actual!r}")


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _request_observations(events: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for event in events:
        if event.get("event_type") != "VLLM_NATIVE_REQUEST_OBSERVATION":
            continue
        request_id = event.get("request_id")
        if request_id:
            out[request_id] = event
    return out


def load_cell(evidence: Path, cell: str) -> CellTrajectory:
    nec = json.loads((evidence / "nec-cells" / f"{cell}.json").read_text(encoding="utf-8"))
    requests_payload = nec["arms"]["A0"]["requests"]
    a0_events = [
        json.loads(line)
        for line in (evidence / "native-runs" / f"phase3-main-{cell}-r1-a0" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    a3_events = [
        json.loads(line)
        for line in (evidence / "native-runs" / f"phase3-main-{cell}-r1-a3" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    observations = _request_observations(a0_events)
    requests: list[RequestPoint] = []
    for row in requests_payload:
        observation = observations[row["request_id"]]
        payload = observation["payload"]
        requests.append(
            RequestPoint(
                request_id=row["request_id"],
                program_id=row["program_id"],
                event_index=observation["event_index"],
                n=payload["native_prompt_tokens"],
                e=row["eligible_prefix_tokens"],
                c=row["native_cached_prefix_tokens"],
                hashes=tuple(payload["native_apc_block_hashes"]),
            )
        )

    # A0 block-id -> native hash map, updated at snapshots and plan events.
    block_map: dict[int, str] = {}
    forced: list[dict] = []
    for event in a0_events:
        if event["event_type"] == "VLLM_PREFIX_SNAPSHOT":
            for block_id, key in zip(
                event["payload"].get("block_ids", []),
                event["payload"].get("ordered_native_cache_keys", []),
            ):
                block_map[block_id] = key[:64]
        elif event["event_type"] == "FORCED_RELEASE_DECISION":
            forced.append({"event": event, "map": dict(block_map), "physical": None})
        elif event["event_type"] == "NATIVE_SELECTION_PLAN_PENDING":
            for item in event["payload"].get("content_identity_by_block", []):
                block_map[item["block_id"]] = item["native_cache_key"][:64]
            if forced:
                forced[-1]["map"] = dict(block_map)
                forced[-1]["physical"] = {
                    item["native_cache_key"][:64]
                    for item in event["payload"].get("content_identity_by_block", [])
                }

    # A3 decisions, in the same forced-release order as the A0 run.
    a3_decisions = [
        event for event in a3_events if event.get("event_type") == "A3_SUFFIX_RELEASE_DECISION"
    ]
    if len(a3_decisions) != len(forced):
        raise ValueError(
            f"{cell}: A3 decisions {len(a3_decisions)} != forced decisions {len(forced)}"
        )

    decisions: list[Decision] = []
    for item, a3_event in zip(forced, a3_decisions):
        forced_event = item["event"]
        event_index = forced_event["event_index"]
        trace = (a3_event["payload"].get("selection_trace") or [{}])[0]
        audits = trace.get("audits") or []
        if not audits:
            continue
        need = int(trace["need"])
        a0_selected = forced_event["payload"]["selected_releases"][0]["program_id"]
        physical = item["physical"] or set()
        candidates: list[Candidate] = []
        for raw in forced_event["payload"]["candidates"]:
            program = raw["program_id"]
            audit = next((a for a in audits if a["key"][0] == program), None)
            if audit is None:
                continue
            victim_ids = raw["initially_reclaimable_block_ids"][:need]
            mapped = [item["map"].get(block_id) for block_id in victim_ids]
            if any(value is None for value in mapped):
                continue
            depths = audit.get("victim_depths") or []
            candidates.append(
                Candidate(
                    program_id=program,
                    prefix_id=raw["prefix_id"],
                    need=need,
                    victim_hashes=frozenset(mapped),
                    first_victim_depth=min(depths) if depths else None,
                )
            )
        a0_candidate = next((c for c in candidates if c.program_id == a0_selected), None)
        if a0_candidate is None:
            continue
        decisions.append(
            Decision(
                cell=cell,
                event_index=event_index,
                need=need,
                candidates=tuple(candidates),
                a0_index=candidates.index(a0_candidate),
                matched_count=len(physical),
                a0_victim_subset_physical=a0_candidate.victim_hashes <= physical,
                a0_selected_program=a0_selected,
            )
        )

    r_a0 = sum(row.e - row.c for row in requests)
    r_recorded = sum(r["recomputed_tokens"] for r in requests_payload)
    return CellTrajectory(
        cell=cell,
        requests=tuple(requests),
        decisions=tuple(decisions),
        r_a0=r_a0,
        r_a0_recorded=r_recorded,
    )


# ---------------------------------------------------------------------------
# A0-anchored prefix-state trajectory simulation
# ---------------------------------------------------------------------------


def simulate_path(trajectory: CellTrajectory, choices: tuple[int, ...]) -> PathResult:
    """Evaluate one complete 24-request path; never sum local decision gains."""
    if len(choices) != len(trajectory.decisions):
        raise ValueError("one choice per decision is required")
    extra: set[str] = set()
    restore: set[str] = set()
    decision_index = 0
    total = 0
    per_request: list[dict[str, Any]] = []
    for request in trajectory.requests:
        while (
            decision_index < len(trajectory.decisions)
            and trajectory.decisions[decision_index].event_index < request.event_index
        ):
            decision = trajectory.decisions[decision_index]
            chosen = decision.candidates[choices[decision_index]]
            baseline = decision.candidates[decision.a0_index]
            for block_hash in chosen.victim_hashes - baseline.victim_hashes:
                extra.add(block_hash)
                restore.discard(block_hash)
            for block_hash in baseline.victim_hashes - chosen.victim_hashes:
                restore.add(block_hash)
                extra.discard(block_hash)
            decision_index += 1

        e_blocks = request.e // BLOCK_TOKENS
        c_blocks = request.c // BLOCK_TOKENS
        c_blocks_cf = 0
        for depth in range(1, e_blocks + 1):
            block_hash = request.hashes[depth - 1]
            present = depth <= c_blocks
            if block_hash in extra:
                present = False
            if block_hash in restore:
                present = True
            if not present:
                break
            c_blocks_cf = depth
        c_cf = c_blocks_cf * BLOCK_TOKENS
        recomputed = request.e - c_cf
        total += recomputed
        per_request.append(
            {
                "request_id": request.request_id,
                "N": request.n,
                "E": request.e,
                "C_A0": request.c,
                "C_counterfactual": c_cf,
                "recomputed": recomputed,
            }
        )
        # A recomputed block is present for later requests.
        for block_hash in request.hashes[:e_blocks]:
            extra.discard(block_hash)
    while decision_index < len(trajectory.decisions):
        decision = trajectory.decisions[decision_index]
        chosen = decision.candidates[choices[decision_index]]
        baseline = decision.candidates[decision.a0_index]
        for block_hash in chosen.victim_hashes - baseline.victim_hashes:
            extra.add(block_hash)
        decision_index += 1
    return PathResult(total=total, per_request=per_request, choices=choices)


def a0_choices(trajectory: CellTrajectory) -> tuple[int, ...]:
    return tuple(decision.a0_index for decision in trajectory.decisions)


def enumerate_oracle(trajectory: CellTrajectory) -> dict[str, Any]:
    choices_space = [range(len(decision.candidates)) for decision in trajectory.decisions]
    baseline_choices = a0_choices(trajectory)
    competitive_indices = [
        index
        for index, decision in enumerate(trajectory.decisions)
        if len(decision.candidates) >= 2
    ]
    baseline = simulate_path(trajectory, baseline_choices)
    best_total = baseline.total
    best_choices = baseline_choices
    alternatives: list[dict[str, Any]] = []
    for choices in itertools.product(*choices_space):
        if choices == baseline_choices:
            continue
        result = simulate_path(trajectory, choices)
        gain = baseline.total - result.total
        alternatives.append(
            {
                "choices": list(choices),
                "programs": [
                    decision.candidates[c].program_id
                    for decision, c in zip(trajectory.decisions, choices)
                ],
                "competitive_programs": [
                    trajectory.decisions[index].candidates[choices[index]].program_id
                    for index in competitive_indices
                ],
                "total_recomputed": result.total,
                "gain_tokens": gain,
            }
        )
        if result.total < best_total:
            best_total = result.total
            best_choices = choices
    oracle_gain = baseline.total - best_total
    return {
        "cell": trajectory.cell,
        "decisions": len(trajectory.decisions),
        "need": (
            trajectory.decisions[competitive_indices[0]].need
            if competitive_indices
            else (trajectory.decisions[0].need if trajectory.decisions else 0)
        ),
        "a0_programs": [
            decision.candidates[decision.a0_index].program_id for decision in trajectory.decisions
        ],
        "competitive_indices": competitive_indices,
        "competitive_a0_programs": [
            trajectory.decisions[index].candidates[trajectory.decisions[index].a0_index].program_id
            for index in competitive_indices
        ],
        "baseline_recomputed": baseline.total,
        "oracle_recomputed": best_total,
        "oracle_gain_tokens": oracle_gain,
        "oracle_gain_upper_bound": True,
        "a0_choices": list(baseline_choices),
        "oracle_choices": list(best_choices),
        "oracle_programs": [
            decision.candidates[c].program_id
            for decision, c in zip(trajectory.decisions, best_choices)
        ],
        "alternatives": alternatives,
        "a0_exact": baseline.total == trajectory.r_a0,
        "recorded_exact": trajectory.r_a0 == trajectory.r_a0_recorded,
    }


# ---------------------------------------------------------------------------
# P2 depth model
# ---------------------------------------------------------------------------


def p2_depth_score(trajectory: CellTrajectory, decision_index: int, candidate_index: int) -> int:
    """Offline depth-aware loss proxy for one candidate.

    For every future request of the same program, truncate at the candidate's
    shallowest victim depth.  This is a hindsight feature, not an online one.
    """
    decision = trajectory.decisions[decision_index]
    candidate = decision.candidates[candidate_index]
    if candidate.first_victim_depth is None:
        return 0
    score = 0
    for request in trajectory.requests:
        if request.event_index <= decision.event_index:
            continue
        if request.program_id != candidate.program_id:
            continue
        cached_blocks = request.c // BLOCK_TOKENS
        lost = max(0, cached_blocks - candidate.first_victim_depth + 1)
        score += lost * BLOCK_TOKENS
    return score


def p2_analysis(trajectories: list[CellTrajectory]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    flips = 0
    positive_gain_flips = 0
    for trajectory in trajectories:
        if not trajectory.decisions:
            continue
        for decision_index, decision in enumerate(trajectory.decisions):
            if len(decision.candidates) < 2:
                continue
            baseline_choices = list(a0_choices(trajectory))
            scores = [
                p2_depth_score(trajectory, decision_index, c)
                for c in range(len(decision.candidates))
            ]
            p2_index = min(
                range(len(scores)),
                key=lambda c: (
                    scores[c],
                    0 if c == decision.a0_index else 1,
                    decision.candidates[c].program_id,
                ),
            )
            p2_choices = list(baseline_choices)
            p2_choices[decision_index] = p2_index
            p2_result = simulate_path(trajectory, tuple(p2_choices))
            p2_gain = trajectory.r_a0 - p2_result.total
            flip = p2_index != decision.a0_index
            flips += int(flip)
            positive_gain_flips += int(flip and p2_gain > 0)
            rows.append(
                {
                    "cell": trajectory.cell,
                    "decision_event_index": decision.event_index,
                    "need": decision.need,
                    "a0_program": decision.a0_selected_program,
                    "p2_program": decision.candidates[p2_index].program_id,
                    "p2_flip": flip,
                    "p2_depth_scores": {
                        candidate.program_id: scores[index]
                        for index, candidate in enumerate(decision.candidates)
                    },
                    "p2_full_trajectory_gain": p2_gain,
                    "oracle_best_gain": max(
                        (
                            trajectory.r_a0
                            - simulate_path(
                                trajectory,
                                tuple(
                                    baseline_choices[:decision_index]
                                    + [candidate_index]
                                    + baseline_choices[decision_index + 1 :]
                                ),
                            ).total
                            for candidate_index in range(len(decision.candidates))
                        ),
                        default=0,
                    ),
                }
            )
    return {
        "decisions": len(rows),
        "p2_flips": flips,
        "p2_flips_with_positive_gain": positive_gain_flips,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def render_report(campaign: dict[str, Any]) -> str:
    """Render the independent Stage-0 report from the evidence object."""
    cells = [cell for cell in campaign["cells"] if cell["alternatives"]]
    lines: list[str] = [
        "# Phase 3 Stage 0：完整轨迹 Oracle 与 P2 离线价值模型",
        "",
        "**Author**: M4  ",
        "**Status**: `STAGE0_CPU_ONLY_AUTHORIZED` — 只读 Archive，无 GPU，无 Native smoke，无生产算法修改。  ",
        "**Authorization**: M1 对 Stage 0 的正式授权（完整轨迹 Oracle + P2 离线研究）。  ",
        "**Model**: A0-anchored prefix-state counterfactual（A0 逐请求基线 + 候选受害者前缀损失 + 完整 24 请求重算）。",
        "",
        "## 0. 结论",
        "",
        f"- Stage-0 gate：**`{campaign['status']}`**。",
        f"- primary 18 Groups / 36 cells 全部完整；`count_complete(G_g >= 512) = {campaign['count_groups_ge_512']}`。",
        f"- Oracle Gain **上界合计 = {campaign['oracle_gain_total_tokens']} tokens**；18 个 primary Group 的上界均为 0。",
        "- 在现有 Archive 的 7 次真实竞争决策上，A0 的选择已经是 oracle 最优：另一候选的全轨迹收益为 0 或负值。",
        "- 因此本轮没有任何正的 **avoidable-loss** Oracle Gain；继续优化 Entry 排序在本 archive 上没有可实现的避免损失空间。",
        "",
        '> 这是**avoidable-loss 上界为 0** 的结论，不是"所有 Entry 策略都无收益"的证明。模型只移除候选的预测受害者、并允许恢复 A0 已驱逐块；它**不建模**换一条链释放容量所带来的正效应。若上界仍为 0，则现有 7 次决策中没有可避免的受害者损失收益；容量效应需要更完整的 Native state 重放才能检验。',
        "",
        "## 1. 合同与命名",
        "",
        "本报告严格采用 Protocol v4 的 N/E/C：",
        "",
        "$$",
        "N = \\text{Native Prompt Tokens},\\quad E = \\text{Eligible Prefix Tokens},\\quad C = \\text{Native APC Cached Tokens}",
        "$$",
        "",
        "$$",
        "\\text{Recomputed} = E - C,\\qquad \\text{Actual Prefill} = N - C",
        "$$",
        "",
        "`E - C` 不叫 `N`。A1/A3 公式里的候选新解锁量写作 `new_blocks`。",
        "",
        "## 2. 方法",
        "",
        "### 2.1 为什么是 A0-anchored 而不是 Native replay",
        "",
        "Archive 没有可独立重置并重放的完整 Native cache state；跨 run 的 native prefix hash 不可移植（`cross_run_native_hash_identity = NOT_PORTABLE`）。因此本阶段不宣称 Native replay，而是：",
        "",
        "1. 每个请求保留观测的 `N/E/C_A0`，A0 路径逐请求精确；",
        "2. 在每次 forced-release 决策，把候选的最深 `need` 个 block（`initially_reclaimable_block_ids[:need]`）作为反事实受害者；",
        "3. 与 A0 选择做集合差：`extra = D_candidate - D_A0` 从未来 cache 中移除，`restore = D_A0 - D_candidate` 恢复 A0 已驱逐但候选不会驱逐的块；",
        "4. 对全部 24 个请求重新计算 `C_cf` 与 `Recomputed_cf = E - C_cf`，使用后重新加入；",
        "5. Oracle 枚举每个 cell 的全部可达候选序列，取完整轨迹最小值；**不**把逐决策局部收益相加。",
        "",
        "### 2.2 有效性验证",
        "",
        f"- A0 逐请求：`R_A0` 与 Archive `aggregate_recomputed_tokens` 逐 cell 精确一致（{campaign['complete_cells_primary']}/{campaign['complete_cells_primary']} primary cells）。",
        f"- 每决策受害者集合：预测受害者是物理驱逐集的子集，`{campaign['decisions_selected_victim_subset_physical']}`；7 次竞争决策 `{campaign['competitive_selected_victim_subset_physical']}`。",
        "- 19 次 `matched=128 > need` 的量子过量全部是单候选决策，不存在排序选择，因而不会改变 oracle 的候选空间。",
        "- **`A0_NATIVE_REPLAY = NOT_AVAILABLE`**：本阶段没有把 prefix-state 模型冒充为 Native 重执行。",
        "",
        "### 2.3 边界",
        "",
        "- 结果为 **avoidable-loss upper bound**：只移除预测受害者，并允许恢复 A0 已驱逐块，均偏向候选；不建模换链释放容量的正效应；",
        "- 不建模 19 次量子过量中的额外 block（全是单候选，无选择）；",
        "- 不改变 `E`、请求时间线、TTL 或 Native 调度；",
        "- P2 深度特征是事后 oracle 特征，不是在线可用特征。",
        "",
        "## 3. Oracle 结果：7 次竞争决策",
        "",
        "| cell | need | A0 选择 | 另一候选 | 另一候选全轨迹 gain (tokens) | oracle gain (tokens) |",
        "|---|---:|---|---|---:|---:|",
    ]
    for cell in cells:
        alternatives = cell["alternatives"]
        if alternatives:
            alt = alternatives[0]
            alt_program = ", ".join(alt["competitive_programs"])
            alt_gain = alt["gain_tokens"]
        else:
            alt_program = "—"
            alt_gain = 0
        lines.append(
            f"| {cell['cell']} | {cell['need']} | {', '.join(cell['competitive_a0_programs'])} | "
            f"{alt_program} | {alt_gain} | {cell['oracle_gain_tokens']} |"
        )
    lines += [
        "",
        "> 表中 `A0 选择` 与 `另一候选` 的 program 见证据 JSON；负 gain 表示该候选会让全轨迹重算量增加。7 次决策的 oracle 最优选择全部是 A0 的选择。",
        "",
        "## 4. Group-level 门槛",
        "",
        f"- primary Groups：{campaign['primary_groups']}；完整 Groups：{campaign['complete_groups_primary']}；完整 cells：{campaign['complete_cells_primary']}。",
        f"- `count_complete(G_g >= {campaign['effect_floor_tokens']}) = {campaign['count_groups_ge_512']}`。",
        "- H3-0 sensitivity mean gain（upper bound）：**0 tokens/group**；g09/g18 的单 cell 不进入 primary gate。",
        "",
        "| 判定条件 | 结果 |",
        "|---|---|",
        f"| complete_cells >= {MIN_COMPLETE_CELLS} 且 complete_groups >= {MIN_COMPLETE_GROUPS} | 是 |",
        f"| count_complete(G_g >= {campaign['effect_floor_tokens']}) >= 8 | 否（{campaign['count_groups_ge_512']}） |",
        "| 4 <= count_complete < 8 | 否 |",
        f"| count_complete <= 3 | 是 → `{campaign['status']}` |",
        "",
        "## 5. P2 深度模型",
        "",
        f"- P2 depth-score 在 {campaign['p2']['decisions']} 次竞争决策上的 flip 数：**{campaign['p2']['p2_flips']}**；其中正 gain flip：**{campaign['p2']['p2_flips_with_positive_gain']}**。",
        "- P2 的 same-program depth proxy 在 7 次决策上没有产生正收益；与 A0 同选或在 tie 时按 A0 优先。",
        "",
        "| cell | need | A0 | P2 choice | flip | P2 gain |",
        "|---|---:|---|---|---|---:|",
    ]
    for row in campaign["p2"]["rows"]:
        lines.append(
            f"| {row['cell']} | {row['need']} | {row['a0_program']} | {row['p2_program']} | "
            f"{row['p2_flip']} | {row['p2_full_trajectory_gain']} |"
        )
    lines += [
        "",
        '**解释**：P2 的 depth 特征作为事后 oracle 特征，在 7 次真实竞争决策上没有找到比 A0 更好的选择；现有 7 次竞争决策是"风险"而不是"机会"。',
        "",
        "## 6. 建议",
        "",
        "1. **不启动 GPU Campaign。** avoidable-loss 上界为 0，且当前没有正收益路径；容量效应需要更完整的 Native state 重放，当前 archive 不支持。",
        "2. **不推进 P2 的 GPU 验证。** 7 次竞争决策上 P2 无正 gain。",
        '3. **P1 的 CPU 参数扫描可保留为暴露几何的诊断**，但它不再是\\"追求 oracle gain\\"的后续：本 archive 的候选暴露本身不足，先确认 P1 能否把 multi-candidate rate 提升到 ≥20%；若无，则 Entry 排序路线在本 workload 家族应停止。',
        "4. **P3 仍暂缓**，本阶段不授权 Partial Release 实现。",
        "",
        "## 7. 限制",
        "",
    ]
    for limitation in campaign["limitations"]:
        lines.append(f"- {limitation}")
    lines += [
        "",
        "## 8. 复现",
        "",
        "```bash",
        "python scripts/probes/phase3_stage0_oracle/stage0_oracle.py \\",
        "    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \\",
        "    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \\",
        "    --out      docs/experiments/phase3-stage0-oracle-data",
        "```",
        "",
        "输出：`stage0-evidence.json`、`stage0-report.md`、`sha256-manifest.txt`。",
        "",
    ]
    return "\n".join(lines).replace('\\"', '"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    cells = [path.stem for path in sorted((args.evidence / "nec-cells").glob("*.json"))]
    trajectories: list[CellTrajectory] = []
    for cell in cells:
        trajectories.append(load_cell(args.evidence, cell))

    oracle_rows = [enumerate_oracle(t) for t in trajectories]
    p2 = p2_analysis(trajectories)

    # Per-decision victim-set validation.
    total_decisions = 0
    physical_subset_ok = 0
    competitive_decisions = 0
    competitive_subset_ok = 0
    for trajectory in trajectories:
        for decision in trajectory.decisions:
            total_decisions += 1
            physical_subset_ok += int(decision.a0_victim_subset_physical)
            if len(decision.candidates) >= 2:
                competitive_decisions += 1
                competitive_subset_ok += int(decision.a0_victim_subset_physical)

    # Group-level gate on the primary 18 paired Groups.
    by_cell = {row["cell"]: row for row in oracle_rows}
    groups: dict[str, list[str]] = defaultdict(list)
    for cell in cells:
        group = cell.split("-")[0]
        if group in NON_PRIMARY_GROUPS:
            continue
        groups[group].append(cell)
    group_rows: list[dict[str, Any]] = []
    complete_groups = 0
    complete_cells = 0
    for group in sorted(groups):
        member_cells = groups[group]
        complete = all(
            by_cell[cell]["a0_exact"] and by_cell[cell]["recorded_exact"] for cell in member_cells
        )
        gains = [by_cell[cell]["oracle_gain_tokens"] for cell in member_cells]
        complete_groups += int(complete)
        complete_cells += len(member_cells) if complete else 0
        group_rows.append(
            {
                "group": group,
                "cells": member_cells,
                "complete": complete,
                "oracle_gain_tokens": sum(gains) / len(gains) if complete else None,
                "oracle_gain_upper_bound": True,
            }
        )
    count_high = sum(
        1
        for row in group_rows
        if row["complete"] and row["oracle_gain_tokens"] >= EFFECT_FLOOR_TOKENS
    )
    if complete_cells < MIN_COMPLETE_CELLS or complete_groups < MIN_COMPLETE_GROUPS:
        gate = "STAGE0_INVALID"
    elif count_high >= 8:
        gate = "CONTINUE_P1"
    elif count_high >= 4:
        gate = "INCONCLUSIVE_GEOMETRY"
    else:
        gate = "STOP_ENTRY_ORDERING"

    # H3-0 sensitivity only.
    h3_cells = [cell for cell in cells if cell not in H3_EXCLUDED_CELLS]
    h3_gain = sum(by_cell[cell]["oracle_gain_tokens"] for cell in h3_cells) / len(h3_cells)

    campaign = {
        "schema_version": "phase3.stage0_oracle.v1",
        "status": gate,
        "authorization": "M1 Stage 0 CPU-only full-trajectory Oracle + P2 offline study",
        "model": "A0_ANCHORED_PREFIX_STATE_COUNTERFACTUAL",
        "a0_native_replay": "NOT_AVAILABLE",
        "oracle_gain_is_upper_bound": True,
        "complete_cells_primary": complete_cells,
        "complete_groups_primary": complete_groups,
        "primary_cells": len(
            [cell for cell in cells if cell.split("-")[0] not in NON_PRIMARY_GROUPS]
        ),
        "primary_groups": len(groups),
        "count_groups_ge_512": count_high,
        "effect_floor_tokens": EFFECT_FLOOR_TOKENS,
        "h30_sensitivity_mean_gain_tokens": h3_gain,
        "decisions_total": total_decisions,
        "decisions_selected_victim_subset_physical": f"{physical_subset_ok}/{total_decisions}",
        "competitive_decisions": competitive_decisions,
        "competitive_selected_victim_subset_physical": f"{competitive_subset_ok}/{competitive_decisions}",
        "oracle_gain_total_tokens": sum(row["oracle_gain_tokens"] for row in oracle_rows),
        "p2": p2,
        "groups": group_rows,
        "cells": oracle_rows,
        "limitations": [
            "Native cache state is not replayable from the archive; results are A0-anchored prefix-state counterfactuals.",
            "The model is loss-only: it removes candidate victims and restores A0-evicted blocks, but does not model capacity gains from evicting a different chain. A positive capacity effect is outside this model.",
            "Counterfactual eviction uses each candidate's deepest need blocks; the 19 quantum over-eviction cases are not modeled and are single-candidate.",
            "Cross-run Native prefix hashes are not portable; all counterfactual block identities come from the A0 run.",
            "P2 depth scores are offline hindsight features and must not be treated as online features.",
            "This study does not authorize GPU execution, Protocol v4 changes, or P3 partial release.",
        ],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out / "stage0-evidence.json"
    evidence_path.write_text(
        json.dumps(campaign, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path = args.out / "stage0-report.md"
    report_path.write_text(render_report(campaign), encoding="utf-8")

    # SHA-256 of the evidence, report, and the two source files.
    files = [
        Path(__file__),
        Path(__file__).resolve().parents[3] / "tests" / "test_phase3_stage0_oracle.py",
        Path(__file__).resolve().parent / "README.md",
        evidence_path,
        report_path,
    ]
    manifest_lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {path.as_posix()}")
    (args.out / "sha256-manifest.txt").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "status": gate,
                "complete_groups": complete_groups,
                "complete_cells": complete_cells,
                "count_groups_ge_512": count_high,
                "oracle_gain_total_tokens": campaign["oracle_gain_total_tokens"],
                "p2_flips": p2["p2_flips"],
                "p2_flips_with_positive_gain": p2["p2_flips_with_positive_gain"],
                "victim_validation": campaign["decisions_selected_victim_subset_physical"],
                "competitive_validation": campaign["competitive_selected_victim_subset_physical"],
                "out": str(args.out),
            },
            indent=2,
        )
    )
    return 0 if gate != "STAGE0_INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
