# Phase 2G · A1 结果摘要

> **Historical scope: initial A1 offline selection and algorithm tests only.** Statements below such as “no native validation” and the original “next steps” describe *this document's stage*, not the project's latest state. Later A1 Native Gate 2 evidence and the still-open independent-value question are indexed at [Phase 2 experiment index](../README.md) and [canonical research status](../../research-status.md). The simple Sufficient-first comparator reproduced the recorded 54/54 A1 Gate 2 forced-release selections; the q/λ contribution remains unproven. Original offline measurements below are unchanged.


**Scope: offline selection only.** 本轮实现了 A1（Entry-level Cost-Aware Release +
Native LRU），未实现 A2/A3，未做任何 native 验证。以下所有数字都是**释放选择层面**的
事实，**不是** aggregate recomputed tokens 的改善。

| 项 | 状态 |
|---|---|
| A0 冻结行为复现 | ✅ 保真度 1.0 / 1.0 / 1.0 |
| A1 实现 + 单元测试 | ✅ 27 tests |
| A0/A1 离线对照入口 | ✅ `python -m kvopt.costaware.a1_compare` |
| 物理收益 | ❌ **未验证**（Block 层未模拟，见 §5） |
| A2 / A3 / B1 | 未授权，未触碰 |

---

## 1. 实现了什么

`src/kvopt/costaware/a1_entry.py` —— `A1EntryCostAwareStrategy`，实现既有的
`ReleaseStrategy.pick_next(remaining, state)` 协议，可直接投入 `replay_decision`，
**未改动** replay 循环、Continuum 或 native 语义。

分数（`B` 为正常数，在所有比较中约去）：

$$
\widehat R_i = q_i\Big[\min(\text{need}, N_i) + \lambda\,(N_i-\min(\text{need},N_i))^{+}\Big],
\qquad
q_i=\sigma\!\left(\frac{\text{deadline}_i-t}{\tau}\right)
$$

其中 `need = target − |E(R)|` 每轮重算，`N_i = |E(R ∪ {i})| − |E(R)|`。
分支阶梯（每轮重新求值）：

| 分支 | 条件 | 规则 |
|---|---|---|
| `single_step` | 存在 `N_i ≥ need` | `argmin R̂_i` |
| `per_unit` | 否则，存在 `N_i > 0` | `argmin R̂_i / N_i` |
| `pair_lookahead` | 否则（全部 `N_i = 0`） | 两 Entry 联合边际 `N_ij > 0`，按 `R̂_ij/N_ij`；`q̃ = 1−(1−q_i)(1−q_j)`；先释放 deadline 较早者 |
| `deadline_fallback` | 无可用对 | deadline 升序 |

确定性：全序为 `(score, deadline, identity)`。停止条件沿用冻结目标
`target = min(required_blocks, queue_len)`，达标即停，不额外释放。

**信息边界（已测试）**：A1 的全部输入是
`retention_deadline_timestamp`（候选行）、`timestamp` / `target` / `candidate_keys`
（快照）、以及由 `owners_by_block` + `queue` 推出的 eligibility 与边际容量。
**完全不读 `decision_native_lru_position`，也不读 `ranking_by_block`** —— 若读，
A1 就可能与 native LRU 趋同而掩盖真实差异。
`test_choice_does_not_depend_on_the_native_lru_position` 通过置换该字段并断言选择不变
来固定这一点。此外 `FORBIDDEN_FEATURES` 中没有任何一项是 `DecisionCandidateRow` 的字段，
所以未来信息在类型上就读不到。

**唯一对既有代码的改动**：`ReplayState.newly_eligible_after_many(keys)` 为纯增方法，
`newly_eligible_after(key)` 改为委托给它，语义完全一致（既有 16 个 replay 测试全通过）。
两 Entry 前瞻需要联合边际，无法用单 Entry 方法表达。

---

## 2. 验收第一项：A0 能复现冻结行为

`validate_replay_fidelity` 在三个语料上均为满分：

| 语料 | 决策数 | release_set | release_sequence | initial_reclaimable |
|---|---|---|---|---|
| H1 formal Level-A | 120 | 1.0 | 1.0 | 1.0 |
| curated exemplars（已提交） | 3 | 1.0 | 1.0 | 1.0 |

A0 = `ExecutedP1BStrategy`（`deadline → min native rank → identity`），未改动。

---

## 3. 验收第二项：A1 产生可解释的差异

### 3.1 受控场景（三个，可手工复核）

| 场景 | 目的 | A0 | A1 | 合法 | 说明 |
|---|---|---|---|---|---|
| `a_divergent` | 正向：两者不同且都合法 | 释放 A（暴露 8 块） | 释放 B（暴露 2 块） | ✅✅ | $\widehat R_A=2.5$，$\widehat R_B=1.8$，选 B |
| `b_identical` | 退化：两者相同 | A | A | ✅✅ | $N_A=N_B$ ⇒ 分数 $\propto q$ ⇒ 即 deadline 序 |
| `c_a1_worse` | 反例：A1 更差 | 释放 X（0 块重算） | 释放 Y（3 块风险暴露） | ✅✅ | $\widehat R_X=3.25>\widehat R_Y=2.996$；但真值只有 Y 会返回 |

场景 C 是刻意保留的失败案例：A1 的估计偏低是因为它把 Y 判成"贵重"（$q_Y\approx1$），
而实际返回的是 Y 本身 —— **$q$ 是启发式代理，这一层误差无法靠公式消除**。

场景实现：`src/kvopt/costaware/a1_scenarios.py`；逐项断言：`tests/test_costaware_a1_entry.py`。

### 3.2 真实语料（selection-level）

H1 formal Level-A（120 个决策）：

```text
order_differs          48 / 120
set_differs            48 / 120        ← order 差异全部伴随集合差异（0 例仅换序）
A0 meets target       120 / 120
A1 meets target       120 / 120
A1 fails where A0 ok    0
A1 释放次数 − A0       0 次：111 例   −1 次：9 例   （A1 从不多释放）
branch   single_step 120 次   per_unit 78 次
```

curated exemplars（3 个决策，数据已提交，可直接复跑）：

```text
order_differs 2 / 3 ; set_differs 2 / 3
例 f5-five-contention-deep-seed-101 : A0 释放 3 个 Entry → 44 eligible；A1 释放 1 个 → 44 eligible
例 f4-deep-multi-release-seed-101  : A0 释放 2 个 → 36 eligible；A1 释放 1 个 → 44 eligible
```

这两例说明差异**确实来自 Cost-Aware 机制**而不是随机性：同样的压力目标下，A1 用更少的
逻辑释放达到了目标，A0 的 deadline-first 顺序没有发现那个单步就足够的 Entry。

### 3.3 参数敏感性（H1，release-set 差异数）

| λ | τ=10 | τ=30 | τ=120 |
|---|---|---|---|
| 0.0 | 9 | 9 | 9 |
| 0.25 | 48 | 48 | 48 |
| 0.5 | 48 | 48 | 48 |
| 0.75 | 48 | 48 | 48 |
| 1.0 | 48 | 48 | 48 |

两点结论：**分歧主要由 λ 决定**（λ=0 时只剩 9 例单位成本效应），而 **τ 几乎不影响**
（$q$ 的单调性足够，具体温度不敏感）。所有配置下 A1 都 0 次目标失败。

---

## 4. 成本估计与实际暴露

`cost_proxy_a1` 记录 A1 所释放 Entry 的 $\widehat R_i$ 之和（由走同一阶梯得出，
与选择逻辑不能漂移）。它只是**模型下的估计**，受三层误差：$q$ 的启发式、$N_i$ 的
可观测性、以及 $S$ 未物化。

`eligible_final` 与 A0 的差（H1，120 个决策的完整分布）：

| Δ eligible_final | 决策数 | 含义 |
|---|---|---|
| +9 | 3 | A1 暴露更多（用 1 次释放拿到更大可行池） |
| 0 | 72 | 相同 |
| −4 … −28 | 45 | A1 暴露更少（−4:9, −5:3, −6:3, −8:6, −10:6, −16:3, −20:3, −24:3, −26:3, −28:6） |

**两个方向都不是"更好"**：少暴露意味着未来压力事件的可用余量更少，多暴露意味着更大的
残留风险敞口。哪个更划算取决于 $q$ 是否估准，这正是设计文档 §3.5 那条待检验命题的具体
形态，**无法在离线层判定**。这也是为什么本轮不报任何"改善"。

---

## 5. 尚未验证的物理效果（必须明确）

| 未验证 | 原因 |
|---|---|
| aggregate recomputed tokens 改善 | Block 层淘汰未模拟。`ReplayOutcome` 只有计数没有块集合，`QueueBlock` 无深度 |
| 真实缓存收益 | 同上，需要 native 配对实验（M6） |
| A2/A3 | 本轮未授权 |

`a1_compare` 的每个 JSON 都带 `is_physical_benefit: false`，防止离线数字被当成收益引用。

---

## 6. 实现中发现的接口缺口

1. **`DecisionSnapshot` 不携带 `retention_deadline_timestamp`。** A1 的 $q_i$ 需要它，
   A0 也需要它。目前靠 `DecisionCandidateRow`（来自 derived bundle）按
   `(run_id, decision_event_index)` 与快照配对提供。**不阻塞本轮**，但如果将来要让
   replay 只依赖快照，需要把该字段加入快照。
2. **A2/A3 仍缺深度与淘汰块集合**（设计文档 §6.4.2 的 T1–T3）。本轮未触碰。
3. 未发现其他缺口；`owners_by_block`、`ranking_by_block`、`required_blocks` 均够用。

---

## 7. 如何复跑

```bash
# 受控三场景
PYTHONPATH=src python -m kvopt.costaware.a1_compare --controlled

# 已提交语料（无需额外数据）
PYTHONPATH=src python -m kvopt.costaware.a1_compare \
    --corpus docs/experiments/phase2a-m6-formal/curated-evidence/exemplars

# H1 formal Level-A（数据不提交）
PYTHONPATH=src python -m kvopt.costaware.a1_compare \
    --corpus <h1-artifacts-root> --json results/a1_h1.json

# 单元测试
python -m pytest tests/test_costaware_a1_entry.py -q
```

参数：`--lambda`（默认 0.5）、`--tau`（默认 30.0）。二者是**排序用启发式**，
不是校准概率，取值记录在每个 JSON 的 `strategy` 段。

---

## 8. 下一步（待 M6）

本轮交付的可用输入：每个决策的 `released` 序列、`eligible_final`、`branch_trace`
和 `cost_proxy_a1`。native 配对实验需要在此基础上补 T1–T3（深度、victim 选择、
淘汰块集合），才能把"释放了谁"连接到"实际淘汰了哪些块、重算了多少 token"。
