# Phase 2G Entry-level Cost-Aware —— 方法可行性研究

M1 授权：Entry-level Cost-Aware Method Research / Existing A1 Model Analysis / Frozen Evidence Reuse /
Mathematical Counterexamples & Lightweight Offline Probes / Candidate Algorithm Proposal —— 已授权。
A1/A2 实现修改、A3 实现、新 Native Campaign、Workload Redesign —— **未授权**；B1 LOCKED。

**本版修正（M1 复审后）**：删除上一版在 H1 上自建的重算分析。
A1 与 A2 的实验结果已由各自 PR 正式发布，本文**只引用已公布数据**，
不再重新构造口径。`src/` 未改动，无 Native 运行。

数据来源：

| 来源 | 内容 |
|---|---|
| `docs/experiments/phase2g-a1/README.md` | A1 离线 selection 对照（H1 formal Level-A，120 决策） |
| `docs/experiments/phase2g-a2-bounded-value-evaluation.md` | A2 bounded native value evaluation（144 runs） |
| `scripts/probes/a1_structural_gap.py` | 纯合成反例（**不依赖任何语料**） |

---

## 0. 结论

| 层级 | 结论 |
|---|---|
| **事实层**：A1 的建模缺口 | **成立**。$N_i$ 与实际 Native victim set 不等价（§2，合成反例，不依赖语料） |
| **A1 已公布事实**：分歧形态 | 48/120 分歧**由 $\lambda$ 驱动、$\tau$ 不敏感**（§3.1） |
| **A1 已公布事实**：释放基数 | A1 相对 A0 **从不多释放**（111 例相同 / 9 例少释放）（§3.2） |
| **物理收益** | **两侧均未验证**：A1 未做 native 配对；A2 已做但未观测到收益（§4） |
| **ERC / MUS** | 已公布数据**不足以判定** → `INCONCLUSIVE`（§5） |

> **不宣称** Entry-level 优化空间为零。本文只说明：现有已公布证据无法支持实现 ERC/MUS。

---

## 1. 上一版的错误（已删除）

上一版在 H1 artifacts 上自行重算了一套统计（缺口占比、同 relief 差异、A1 对最优的余量），
并据此给出"ERC/MUS 已被否证"。该做法有两个问题：

1. **重复且口径自造**：A1 的实验结果已由 `docs/experiments/phase2g-a1/README.md` 正式发布，
   自建重算只会引入与官方口径不一致的数字（M1 前两轮 RC1/RC2 已指出同类风险）；
2. **单臂语料**：H1 Level-A 是 A0 决策流，在其上反事实评估 A1 存在选择效应，
   不能替代 A1 自身的配对实验。

**本版删除该分析及其探针，改为一律引用已公布数据。** 仅保留纯合成反例（§2），
因为它证明的是模型性质，与语料无关。

---

## 2. 事实层：缺口是真实的（合成反例，不依赖语料）

`src/kvopt/continuum/selection.py` 的实际淘汰规则：

```text
virtual_eligible_order = sorted(eligible, key=(eligibility_tier, native_lru_rank))
selected               = virtual_eligible_order[:target]
TIER_1 = hashless（恒可回收，无内容）    TIER_2 = hashed 且全部 owner 已释放
```

A1（`src/kvopt/costaware/a1_entry.py`）：

```text
N_i    = |newly_eligible_after(i)|
Rhat_i = q_i * [ min(need, N_i) + λ * (N_i - min(need, N_i))^+ ]
```

$N_i$ 数的是「有多少块从受保护变成可回收」，**不读 rank、不区分 tier、不含实际淘汰谁**。
A1 的 README 也明确记录了这一点（§1「完全不读 `decision_native_lru_position`」）。

### 2.1 反例一：为不会被淘汰的块付费

`relief_not_eviction()`：队列 rank 0..5，前 3 块 hashless，后 3 块由 entry `e` 独占，
`target = 3`。

```text
before: eligible = 3, target = 3          <- 目标已满足
N_e                                      = 3
释放 e 之后实际被淘汰                     = 那 3 个 hashless 块（无内容）
释放 e 导致的真实重算                    = 0.0000
A1 为 e 计费 q_e * N_e                   = 2.7000
```

此反例与 $q$ 完全无关。

### 2.2 反例二：相同 relief，不同真实损失

`warm_vs_cold()`：`target = 1`，两个 entry 各解锁一个块，$N_i$ 都是 1。

| 释放 | 解锁块在其前缀中的深度 | 真实损失 |
|---|---:|---:|
| `cold` | 1 / 3 | **1.5000** |
| `warm` | 3 / 3 | **0.5000** |

```text
A1 score cold = 0.5000, warm = 0.5000  -> identical
```

> **事实层结论**：A1 的代价量与代价函数实际依赖的量不是同一个。
> 该结论由构造保证，不需要语料支持，也不因语料更换而改变。

---

## 3. A1 已公布数据能告诉我们什么

来源：`docs/experiments/phase2g-a1/README.md`（H1 formal Level-A，**120** 决策）。

### 3.1 分歧由 $\lambda$ 驱动，$\tau$ 几乎无影响

release-set 差异数：

| λ | τ=10 | τ=30 | τ=120 |
|---|---|---|---|
| 0.0 | 9 | 9 | 9 |
| 0.25 | 48 | 48 | 48 |
| 0.5 | 48 | 48 | 48 |
| 1.0 | 48 | 48 | 48 |

两点解读：

- **$\tau$ 不敏感**：$q$ 的具体温度不影响 A1 的选择，只要单调性保持。
  这意味着**调整 $q$ 的形状不会改变 A1 的行为**，与 A2 阶段"更精细的 $q$ 无收益"一致；
- **$\lambda$ 决定分歧**：$\lambda=0$ 时分歧从 48 降到 9，说明分歧主要来自
  $\lambda$ 对超额 $N_i$ 的惩罚项，而非 $q$ 的重排。

> 这条对本文的意义：A1 的行为空间主要由「$N_i$ 及其惩罚」占据，
> 而 §2 已证明 $N_i$ 不等于实际淘汰量。这不是说 A1 因此更差，
> 而是说**任何以 $N_i$ 为基础的改进都继承同一误差**。

### 3.2 A1 相对 A0 从不多释放 —— 但不等于相对最优

```text
A1 释放次数 − A0      0 次：111 例      −1 次：9 例      （A1 从不多释放）
branch               single_step 120 次   per_unit 78 次
```

**必须限定**：这是**相对 A0**（deadline-first）的基数比较，
不是相对最优基数的比较。因此：

- 它**不能**证明"A1 没有过度释放"；
- 但它**确实**说明"减少释放次数"这一收益来源（MUS 的动机）在 A1 身上
  已部分实现：A1 在 9 例中用更少的释放达到了同样的目标
  （README §3.2 的两个 curated 例证：A0 释放 3 个/2 个 Entry，A1 各释放 1 个，达到相同 eligible）。

### 3.3 暴露量双向偏移，离线不可判优劣

`Δ eligible_final`（A1 − A0，120 决策）：

| Δ | 决策数 | 含义 |
|---|---:|---|
| +9 | 3 | A1 用 1 次释放拿到更大可行池 |
| 0 | 72 | 相同 |
| −4 … −28 | 45 | A1 暴露更少 |

A1 的 README 明确写道：**两个方向都不是"更好"**——
少暴露意味着未来压力事件余量更少，多暴露意味着更大的残留风险敞口。

> 这直接限定了本文能做的判断：**已公布数据没有建立"哪种释放集更好"的判据**。
> 因此任何候选方法（含 ERC）的收益都无法用这批数据判定。

---

## 4. A2 已公布数据：Block 层未观测到收益

来源：`docs/experiments/phase2g-a2-bounded-value-evaluation.md`。

| 指标 | 结果 |
|---|---|
| BETTER / WORSE / TIED | **0 / 3 / 33** |
| 退化集中 | F4（multi-turn growth / repeated pressure） |
| A2 决策回退 `content_unverified` | **402 / 778（51.7%）** |
| 确认的选择分歧 | 2（同一 draw 的两次 repeat） |
| 最终判定 | `INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN` |

对本文的作用有两点：

1. **先例**：更精细的代价模型（A2 的 proxy-weighted loss）在真实 Native 上
   **未显示收益**。这不否定 Entry 层，但要求 Entry 层的新方法提供**可判定的证据**，
   而不是"目标更精细"这一理由；
2. **风险**：51.7% 的决策因内容身份不可证而回退。
   Entry 层若同样依赖 block 级内容深度，会继承同一可观测性缺口（见 §5.2）。

---

## 5. ERC / MUS 的判定

### 5.1 MUS（极小释放集）

| 判据 | 已公布数据 | 判定 |
|---|---|---|
| A1 是否相对**最优**过度释放 | **无数据**（官方只给相对 A0 的基数） | 不可判定 |
| A1 相对 A0 是否过度释放 | 从不多释放（111 相同 / 9 更少） | MUS 的动机在 A1 中已部分实现 |

**判定：`INCONCLUSIVE`**（相对最优无数据），但**动机显著减弱**：
A1 已在 9/120 例中用更少释放达到同一目标，说明"N_i 排序导致过度释放"这一前提
在已观测部分不成立。

### 5.2 ERC（以实际淘汰集为代价）

| 判据 | 已公布数据 | 判定 |
|---|---|---|
| 实际淘汰集是否与 $N_i$ 解锁集不同 | **无数据**（A1 的离线对照未模拟 Block 层，README §5 明确"Block 层淘汰未模拟"） | 不可判定 |
| 该差异是否产生重算损失差异 | **无数据** | 不可判定 |
| 是否具备内容身份可观测性 | A2 回合 51.7% 回退，说明该缺口真实存在 | 风险已知 |

**判定：`INCONCLUSIVE`。** 不是"已否证"，而是**现有已公布数据没有回答这个问题的能力**。

> A1 的 README §5 写得很清楚：`ReplayOutcome` 只有计数没有块集合，`QueueBlock` 无深度，
> 因此"释放了谁"无法连接到"实际淘汰了哪些块"。ERC 恰恰需要这条连接。

### 5.3 $\lambda$ 敏感性（合成探针）

`a1_structural_gap.py` 的合成结论：λ 从 0 到 1 的 realized loss 为
1.6174 / 1.6408 / 1.7042（3000 个合成决策），非单调且差异小。
这**支持**"问题是 $N_i$ 语义而非 $\lambda$ 取值"，但**不构成否证**——
合成几何赋予差异很大的 $q$ 且随机打乱 rank，不能外推到真实语料。

---

## 6. 回应 M1 的五个问题

### 6.1 Existing A1 Limitation

**可证明**：A1 的 $N_i$ 与实际淘汰量不等价（§2，合成反例，与语料无关）。
**已公布数据支持的部分**：A1 的分歧由 $\lambda$（即 $N_i$ 惩罚项）驱动，$\tau$ 不敏感（§3.1）。
**未证明**：该不等价是否导致 A1 在真实负载上更差。A1 未做 native 配对。

### 6.2 Unexploited Information

`native_lru_rank`、tier 组成、解锁块的前缀深度在 A1 中均未被使用（§2，A1 README §1 确认）。
**但已公布数据无法说明使用它们能带来多少收益**——因为这需要 Block 层模拟，
而 A1 的对照未做（README §5）。

### 6.3 Optimization Structure

已公布数据支持的结构事实：

- 释放数与暴露量**可以双向解耦**（§3.3：A1 有 3 例多暴露、45 例少暴露）；
- A1 已在 9/120 例中用更少释放达到目标（§3.2）；
- 但没有数据表明这些差异对应更好的重算结果。

### 6.4 Candidate Method

原拟两个，均已按 M1 要求做判据检查：

| 候选 | 判定 |
|---|---|
| **MUS** | `INCONCLUSIVE`；动机因 A1 从不多释放而显著减弱 |
| **ERC** | `INCONCLUSIVE`；所需数据（Block 层淘汰集）在已公布对照中不存在 |

按 M1 指示，证据不足时不强行推进实现。

### 6.5 Falsifiability

| 判据 | 当前可否判定 | 所需数据 |
|---|---|---|
| A1 相对最优过度释放 | ❌ | A1 语料上的基数最优解 |
| 解锁集 ≠ 淘汰集 | ❌ | Block 层模拟或 native 淘汰块集合 |
| 该差异产生损失差异 | ❌ | 内容深度 + 淘汰集（即 A2 的 T1–T3） |
| 真实重算 token 收益 | ❌ | A1/A0 paired native 测量 |

---

## 7. 建议

1. **不实现 ERC / MUS**：现有已公布数据无法支持任一方，实现会重演 A2 的模式
   （先做精细模型，再发现无可观测收益）。
2. **不调整 $\lambda$、$\tau$**：A1 已公布数据显示 $\tau$ 不敏感、$\lambda$ 只改变分歧数量
   而不改变判据。
3. **若要继续 Entry 层，先补判据数据**（按成本从低到高）：
   1. **Block 层淘汰集模拟**：在 A1 已发布的 `released` 序列上补 `QueueBlock` 深度与淘汰集，
      即可回答"解锁集是否等于淘汰集"；
   2. **A1 语料上的基数最优解**：回答 MUS 是否有空间；
   3. **A1/A0 paired native 测量**：唯一能回答 token 收益的层级。
4. 在 (1)(2) 到位前，Entry 层研究**不具备可判定的下一步**。

---

## 8. 与 A2 的关系

| | A2（已完成的负面分支） | Entry 层（本文） |
|---|---|---|
| 已公布结论 | 0 BETTER / 3 WORSE / 33 TIED | A1 只有离线 selection 对照，无物理收益 |
| 失败/缺口形态 | $q$ 与真实复用无关 | $N_i$ 与实际淘汰集不等价 |
| 共同风险 | 依赖未校准的 $q$ | 同左（A1 也用 $q$） |
| 共同的可观测性缺口 | 51.7% 决策内容身份不可证 | Block 层淘汰集未被模拟 |

两层共享同一个未解决的问题：**"选了什么"到"重算了多少 token"的连接尚未建立**。
在这条连接建立之前，任何 Entry 层改进都无法被判定。

---

## 9. 边界声明

- 本文**不再**包含任何自建的 H1 重算统计；所有 A1/A2 数字均逐项引自其已发布文档。
- 剩余的唯一自建材料是 `a1_structural_gap.py` 的**合成**反例，用于证明模型性质，
  不用于估计真实收益。
- A1 的物理收益**未验证**（A1 README §5 原文："aggregate recomputed tokens 改善：未验证"）。
- A2 的结论保持 `INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN`。
- 未修改 `src/`，未运行 Native，未实现 A3，未改 workload，未动 A1/A2 代码与结果。

---

## 10. 复现

```bash
# 唯一自建材料：合成反例与结构分析（不读任何实验语料）
python scripts/probes/a1_structural_gap.py

# A1 已公布结果的复跑方式（见 A1 README §7）
PYTHONPATH=src python -m kvopt.costaware.a1_compare --controlled
PYTHONPATH=src python -m kvopt.costaware.a1_compare \
    --corpus docs/experiments/phase2a-m6-formal/curated-evidence/exemplars
```
