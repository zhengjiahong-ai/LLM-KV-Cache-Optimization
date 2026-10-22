# Phase 2G Entry-level Cost-Aware —— 方法可行性研究

M1 授权：Entry-level Cost-Aware Method Research / Existing A1 Model Analysis / Frozen Evidence Reuse /
Mathematical Counterexamples / Candidate Algorithm Proposal —— 已授权。
A1/A2 实现修改、A3 实现、新 Native Campaign、Workload Redesign —— **未授权**；B1 LOCKED。

`src/` 未改动，无 Native 运行，无自建语料重算。

---

## 0. 数据来源（本版的关键修正）

前几个版本我错误地在 H1 artifacts 上自建统计，并据此断言 A1/ERC/MUS。
**本版一律引用原始 Native 证据的只读再分析：**

| 来源 | 内容 |
|---|---|
| `a1_gate2_deep_research_memo.md`（PR #54 归档 + PR #55 语义修正） | A1 Gate 2 原始 Native 证据深度分析，925 项归档 |
| `docs/experiments/phase2g-a2-bounded-value-evaluation.md` | A2 bounded evaluation（144 runs） |
| `docs/experiments/phase2g-a1/README.md` | A1 离线 selection 对照（仅作早期输入，**已被 Gate 2 取代**） |
| `scripts/probes/a1_structural_gap.py` | 纯合成反例（不读任何实验语料） |

归档 SHA-256 `f445ebfc…`，与 PR #54 一致；冻结执行 SHA `d2710d56…`。
所有 Block ID 与内容 key **只在同一 Run 内**关联，不跨进程比较。

---

## 1. 结论

| 层级 | 结论 |
|---|---|
| **A1 策略收益** | **成立**：A0/A1 Gate 2 有界负载上 −1,696 recomputed tokens（−17.7%），12 Better / 1 Worse / 22 Tied |
| **A1 数学模型的独立贡献** | **未成立**：54/54 A1 Native 决策与「Sufficient-first + 最早 deadline」完全一致；`q:=0.5` 与 `λ:=0` 均不改变选择 |
| **ERC** 的动机 | **被削弱但未否证**：`unlock ≠ immediate eviction` 不代表零成本，存在**延迟暴露**（全量 90.3% / 75.6% 后续被淘汰） |
| **MUS 的动机** | **削弱**：本批 A1 每次只释放 1 个 Entry，且 54/54 无更优的同等释放数集合 |
| **下一步方向** | **必须先把 Sufficient-first 作为非 Cost-Aware 强基线**，否则 A1 的创新性归因错误 |

**最重要的一条**：

> A1 相对 A0 的**策略收益**是真实的、可复现的；
> 但该收益**不能归因于加权 Cost-Aware 数学模型**——
> 在这批观测决策上，它与一个不含 $q$、不含 $\lambda$ 的简单规则等价。

---

## 2. 原始证据与指标复算（引用）

Campaign：36 scenario draws × 2 policies × 2 repeats = 144 runs。
**140 成功 / 4 失败**（均为 `f4-draw-06`，cost-profile 范围错误，不可恢复为 TIED）。
70 个有效成对 Repeat、35 个完整场景。Repeat 不构成独立样本。

| 指标（两 Repeat 汇总） | A0 | A1 | Δ=A1−A0 |
|---|---:|---:|---:|
| recomputed `Σ(E−C)` | 9,568 | 7,872 | **−1,696** |
| actual prefill `Σ(N−C)` | 14,058 | 12,362 | **−1,696** |
| new suffix `Σ(N−E)` | 4,490 | 4,490 | 0 |

场景级：**12 Better / 1 Worse / 22 Tied / 1 Inconclusive**；
mean Δ = −24.2286，median Δ = 0，95% exploratory CI = [−38.8571, −11.4286]。

> 70/70 完整 Pair 的请求集合与逐请求 `N,E` 一致，故 `ΔW = ΔR` 是**实测结论**而非假设。
> −17.7% 是固定六类负载格点的描述性比例，**不可外推**为普遍提升幅度。

---

## 3. 核心机制：Sufficient-first，而不是 $q$ 的数值权重

这是本报告最关键的发现，也是前几版完全遗漏的。

### 3.1 事实

- 仅 27/35 有效场景发生 forced release；108 个 Force-Release Event（A1 占 54）。
- A1 的 **54/54** 决策均恰好释放 **一个** Entry，轨迹全部为 `single_step`；
  `per_unit / pair_lookahead / deadline_fallback` 在这批 Native 决策中**一次也未触发**。
- **消融**：`q_c := 0.5` 后同一 Entry 仍被选中 **54/54**；再令 `λ := 0` 仍 **54/54** 不变。
- 54/54 的最终选择 = 「先筛 `N_i ≥ need` 的单步足够候选，再按 deadline 最早」。
- `q` 取值约 [0.4914, 0.5000]，决策内 `q` 差中位数约 0.00836。

### 3.2 含义

A1 在本批观察到的优势来自**单步容量可满足性**（避免顺序 deadline-first 的多次释放），
而不是 Reuse Prediction 或加权成本估计。

| 声称的能力 | 本批证据 |
|---|---|
| $q$ 提供独立排序信息 | **否**（`q:=0.5` 不改变 54/54） |
| $\lambda$ 残差罚项有用 | **否**（`λ:=0` 不改变 54/54） |
| pair lookahead 有用 | **未触发**（0 次） |
| per-unit 分支有用 | **未触发**（0 次） |

> 这与 A1 离线 README 的 τ 不敏感（差异恒为 48）一致，但 Gate 2 更强：
> **连 λ 的分歧也不改变实际选择**。

### 3.3 两个可手算实例

- `f1-draw-03`：A0 释放 a1+a2+a3，A1 释放 a4。A1 给 a1/a2/a3 节约 64/96/160（共 320），
  使 a4 多重算 208，净 **112 tokens** 收益。
- `f1-draw-06`：A1 保留 a1/a2 节约 80+112=192，但牺牲 a4 多 208，净 **退化 16**。

**同一结构规则不保证收益**。拆分每个 Repeat：受益程序合计节省 **2,608**，
受损程序合计增加 **1,760**，净 −848。即它是**重新分配缓存命中**，不是无代价改进。

---

## 4. 延迟暴露：对 ERC 的关键修正

前几版我断言"解锁但未被淘汰的块不应计费"，**这个说法是错的**。memo §4 给出反证。

在 108 个有 forced-release 的 Run 中，用完整 Free Queue 的 `(eligibility_tier, native_lru_rank)`
重建实际选中 Block，与 `PRESSURE_REQUEST_COMPLETED.last_selected_block_ids`
**108/108 完全一致**（仅同 Run 内比较）。

随后识别「新解锁但当前 Victim Set 未选中」的 Block，再按
**同 Run + 同 Block ID + 同 Native Content Key + 同 Hash Process** 检索后续淘汰：

| 两 Repeat 汇总 | A0 | A1 |
|---|---:|---:|
| Newly eligible, not in current Victim Set | 186 | 82 |
| `unlock` → 后续 native eviction（全量） | 168 / 186 = **90.3%** | 62 / 82 = **75.6%** |
| 同上，仅 13 个分歧场景 ×2 Repeat | **120 / 120** | **14 / 16** |

> 两个子集的括号不同，不可混用：全量 108 个 forced-release Run 含无分歧场景，
> 13 场景子集只含 A0/A1 选择不同的场景。

> **因此**：`unlock ≠ immediate eviction` **不**等于零成本。它可能意味着**未来压力下的持续暴露**。
> 以"本次未被淘汰"为由给 Entry 计零成本，是**错误的建模原则**。
>
> **同时**：这些计数**不足以**证明某次 eviction 导致了某次 `E−C` 的具体增量。
> Slot reuse、多后续请求、APC 前缀可达性仍需严格关联。

对 ERC 的结论：ERC 的方向（把代价接到实际淘汰）**没有被否证**，
但 ERC 的**范围太窄**——只看当前 Victim Set，遗漏了释放后的持久风险边界。

---

## 5. 有界离线反事实：是否还有模型空间

在 54 个 A1 Forced-Release Run 内重建合法释放集合（候选 ≤ 8，枚举大小 ≤ 3），
沿用冻结 Tier-aware victim rule 与决策时链身份，计算

$$L(S)=\sum_c q_c\bigl(m_c-\text{first\_evicted\_depth}_c(S)+1\bigr)$$

（模型块单位，**不是**实际 recomputation。）

| 条件 | 结果 |
|---|---|
| 54/54 窗口完成枚举、匹配实际 Native Victim Set、通过内容链验证 | ✓ |
| 替代集合**不能多释放 Entry** | **54/54 无更低模型损失** |
| 允许最多 3 个 Entry | **26/54 存在更低模型损失** |
| ... 其差值 | 最大 **0.0876** 加权块单位，54 窗口平均 **0.0194** |
| 均匀 $q$ 下 | **54/54 无更低模型损失** |

**请勿误读**：这 26 个替代通常需要**解除更多 Entry 的保护**。
「多释放后当前截面模型 loss 更低」**不代表**整个 Runtime 生命周期真实重计算更低。

---

## 6. 工作负载与外推限制

| 族 | 选择分歧 / 场景 | 说明 |
|---|---|---|
| F1 | **4**（3 Better, 1 Worse） | 主要收益与唯一退化都来自这里 |
| F2 | 1 / 6 | 共享结构存在，但 pair lookahead **0 次触发** |
| F3 | 3 | Better |
| **F4** | **0**（5 个有效场景 forced release 为 0） | **未验证** multi-turn / repeated pressure |
| F5 | 3 | **无共享前缀负控制**，说明改善**不要求共享** |
| F6 | 2 / 3（仅 3 个场景有 forced release） | 不足以证明 $q$ 能识别预测误差 |

两种容易混淆的结论必须分开：

1. A1 对照 A0 在封存有界负载上**确有可复现的策略级收益**；
2. A1 的加权 Cost-Aware 模型**未展示超出 Sufficient-first 的独立选择价值**。

> 第二条对方法创新性更具约束力：不能把第一条的策略收益当成复杂成本函数的贡献证明。

---

## 7. 回应 M1 的五个问题

### 7.1 Existing A1 Limitation

**成立且比前几版更具体**：A1 的 $N_i$ 与实际淘汰不等价（合成反例 §8.1 仍然有效），
**但更重要的是**——在本批 54 个真实 Native 决策上，A1 的全部机制复杂度
（$q$、$\lambda$、pair lookahead、per-unit）**都没有产生影响**。
限制不在"代价函数不够准"，而在"代价函数没有被用到"。

### 7.2 Unexploited Information

| 信息 | 现状 |
|---|---|
| `native_lru_rank`、tier 组成 | A1 不读（设计如此） |
| **释放后的持续 eligibility** | **无人建模**——这是 memo §4 揭示的真正空白 |
| 后续请求的 APC 可达性 | 未建模 |

> 真正的未利用信息不是"更准的 $q$"，而是**释放决策对下游状态的时间演化影响**。

### 7.3 Optimization Structure

- **同等释放数内**：54/54 无改进空间（均匀 $q$），允许更多释放仅 26/54 且差值 ≤ 0.0876 块；
- **跨时间**：`unlock` 与后续 `eviction` 高度相关（全量 168/186 = 90.3%、62/82 = 75.6%；
  13 分歧场景子集为 A0 120/120、A1 14/16），
  说明释放决策的**影响跨越多个后续压力事件**，不是单点决策。

### 7.4 Candidate Method（修订）

前几版的 ERC / MUS 定位需要修正：

| 候选 | 修订后的判定 |
|---|---|
| **MUS** | **不建议**：本批 A1 每次只释放 1 个，同释放数下 54/54 无改进 |
| **ERC** | **方向保留、范围需扩大**：只算当前 Victim 会遗漏延迟暴露；但 ERC 本身不足以构成新方法 |
| **Sufficient-first（非 Cost-Aware）** | **必须作为强基线**，而不是候选方法——它已是 A1 的实际行为 |

> memo §7 的建议我完全接受：**先证明 A1 的创新不是归因错误**，再谈新方法。

### 7.5 Falsifiability

| 判据 | 现状 |
|---|---|
| A1 是否优于 A0 | **已证**（−1,696 tokens, CI [−38.86, −11.43]） |
| A1 的收益是否来自 $q$ / $\lambda$ | **已否**（54/54 消融不变） |
| 是否存在同释放数的更优模型解 | **已否**（54/54 无更低 loss） |
| 是否存在多释放的模型收益 | 仅 26/54、均值 0.0194 块，**不足以支持实现** |
| 延迟暴露是否影响真实 token | **未证**（需要物理→token 归因） |

---

## 8. 保留的合成反例（不依赖语料）

### 8.1 为不会被淘汰的块付费

`target=3`，前 3 块 hashless ⇒ 目标已满足。释放 `e` 不改变淘汰集，
真实重算 **0.0000**，A1 计费 $q_e N_e = 2.7000$（与 $q$ 无关）。

### 8.2 相同 relief，不同损失

两 entry 的 $N_i$ 同为 1，真实损失 **1.5000 vs 0.5000**，A1 评分同为 **0.5000**。

> 这两个反例证明的是**模型性质**，与语料无关。
> 但 memo §4 表明：不能由它们推出"未立即淘汰 = 零成本"——
> 反例成立的是"当前截面损失为 0"，不是"生命周期成本为 0"。

### 8.3 $\lambda$ 敏感性（合成）

λ = 0 / 0.5 / 1.0 → 1.6174 / 1.6408 / 1.7042（3000 合成决策），非单调且差异小。
与 Gate 2 的 54/54 消融一致：**λ 不是关键变量**。

---

## 9. 建议（对齐 memo §7）

1. **把 54/54 的 Sufficient-first 等价性作为主要 negative lesson**，
   严格审查 A1 声称的创新是否归因错误。
2. **先设计 Sufficient-first / Earliest-Sufficient 作为必须对照的非 Cost-Aware 强基线**。
   在现有记录上已能确认其逻辑选择与 A1 一致，**无需新 Native 即可做选择级对照**。
   是否需要独立 Native 对照由 M1 另行授权。
3. **验证下游状态**：区分本次 Victim / 后续仍 Eligible / 后续实际 Eviction / 后续 APC。
   现有包已有部分同内容延迟淘汰事实，但尚无完整物理→token 归因。
4. **ERC / MUS 先不实现**。若提出进一步方法，须给出**同释放数下**与 Sufficient-first
   不同的合法决策，以及预期能影响的真实后续请求事件。
5. **如未能证明独立机会，应接受该方向可能不足以支撑论文方法创新**，
   不得通过改动后验 workload 或调 $q$ 制造收益。

---

## 10. 边界声明

- 本文所有 A1 Gate 2 数字引自 `a1_gate2_deep_research_memo.md`（PR #54 归档，
  只读再分析，归档 SHA-256 `f445ebfc…`）。
- **无自建 H1/语料重算**；前几版此类分析已删除。
- 第 5 节的有界离线反事实**属于模型层**，不是 Native 级独立实验，具显式假设。
- A2 结论保持 `INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN`。
- Block ID / Content Key 仅在**同一 Run 内**关联，不跨进程比较。
- 未修改 `src/`，未运行 Native，未实现 A3，未改 workload，未动 A1/A2 代码与结果。

---

## 11. 复现

```bash
# 唯一自建材料：合成反例（不读任何实验语料）
python scripts/probes/a1_structural_gap.py

# A1 Gate 2 原始证据再分析（需解压 PR #54 归档，见 memo §8）
#   analyze_a1.py / a1_ablation.py / a1_bounded_counterfactual.py / a1_delayed_exposure.py

# A1 离线 selection 对照（早期输入，已被 Gate 2 取代）
PYTHONPATH=src python -m kvopt.costaware.a1_compare --controlled
```
