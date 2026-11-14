# Phase 3 空结果的机制分析与下一轮优化设计

**Author**: M4
**Status**: `RESEARCH_ANALYSIS_ONLY` — 未授权实现、未授权新实验、未授权 GPU 执行。
**Baseline HEAD**: `a048f9743049fbd0ce42198c39bc0538b0ff3c15`（`feature/phase3-unified-270-run-pipeline`）
**Execution code**: `00a512111f15abddcad329572f6e50ccaaa76775`
**Immutable archive**: `d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8`
**Reproduction**: `scripts/probes/phase3_null_mechanism/probe.py`（只读，无 GPU，见 §12.0）
**Revision**: R1 — 回应 M1 对 PR #105 的独立审计（修订项 1–7）。本修订不改变研究路线、不授权算法实现、不修改 Protocol v4、不启动 GPU、不跑新实验。修订对应：① `q` 的单调方向；② §5.1 的 S/N 混用（Step-2 判据是 `new_blocks >= need`）；③ 四臂同序限定为本样本；④ Stage-0 完整轨迹反事实 oracle；⑤ Stage-0 继续/停止判据冲突与 group-level 门槛；⑥ probe.py 的完整性/排序复算/fail-closed；⑦ Group/Cell 口径与 `σ_run=0` 覆盖范围。

本文件不修改 Protocol v4、不修改冻结 Cohort、不修改原始 Archive、不修改既有结果与本轮 actual-order audit。
它只做三件事：解释"为什么没有观察到 Cost-Aware 相对 A0 的增量收益"、界定这个解释的边界、提出下一轮可比较的优化方案。

---

## 0. 证据等级约定

全文每个结论都带一个等级标记：

| 标记 | 含义 | 可反驳方式 |
|---|---|---|
| `[OBS]` | 直接观察。来自本仓已提交的审计产物，或本轮从冻结 Archive 重算、可逐行复核 | 指出复算错误或数据源错误 |
| `[INF]` | 合理推断。基于 `[OBS]` 加上已读过的源码语义 | 指出源码语义与该推断冲突 |
| `[HYP]` | 待验证假设。给出可执行的检验方式与预期判据 | 执行该检验并得到相反结果 |

**本轮新增的复算一律不写入冻结产物**，只写在 `local/`（gitignored）与本文件的正文里；文档中给出的数字都可以用 §12 的步骤在 Archive 上原样重放。

> **必须先说清楚 `σ_run = 0` 的适用范围。** `noise-report.json` 的 `σ_run = 0.0` 来自 **5 个 Workload Group × 2 个 condition × 3 次重复 = 10 个 cell / 30 个 A0 run**（g01、g04、g06、g07、g10；pooled within-cell SD，df=20；三个层内 σ 亦为 0）。它**只**校准了这 10 个 cell 上 A0 的 run-to-run 方差；它没有覆盖另外 30 个 cell，也没有覆盖 A1/A2/A3/E0，更没有给出主战役 240 个单次 run 的噪声地板。
>
> 因此本文不再宣称"整批结果是确定性重放、没有噪声地板"。本轮的零效果是一个**选择一致**的精确零：四个 Entry 臂在 127/127 次决策上选中同一 program，逐请求 N/E/C 完全相同；这个结论不依赖 `σ_run = 0`。`σ_run = 0` 只能支持"在被校准的 10 个 A0 cell 上，重复运行没有观察到方差"。
>
> 一个具体的反例：g18-c1 没有任何 forced release，A0−N0 仍在最后一个请求上差 544 tokens（§3.2）。它不在 H3-0 中，但说明校准范围之外不能假定零噪声，"没有噪声地板"这句话不能外推到整个 archive。

---

## 1. 执行摘要

一句话：**本轮没有测到 Cost-Aware 的增量收益，不是因为它无效，而是因为这批实验里 Cost-Aware 与 A0 从来没被要求做出不同选择。**

分解为五条，每条在 §4/§5 展开并给等级：

1. **在本轮 127 次决策中，四个 Entry 臂选中了同一个 program（127/127）。** A0 的主键是 `deadline`；E0 的主键也是 `deadline`（再按 `identity`）；A1 的 Step-2 主键是 `q·[λN + (1−λ)·min(need,N)]`，其中 `q = sigmoid((deadline − t)/τ)` 对 `deadline` **严格单调递增**；A3 的 Step-2 主键是 `L = q·prefill·S/m`，`q` 同样随 `deadline` 增大。**这是本样本上的观测结果，不是四个公式的普遍数学等价。** 在 6/7 次竞争决策中 `q` 的比值（10.4×–874×）压过 `N`、`prefill`、`S/m` 的差异；但 g10-C1 的 `q` 只差 3.4%，A3 的 `L` 仅以 2.0% 的边际与 deadline 同序。只要候选几何稍变（`q` 近并列且 `N`/`prefill`/`S/m` 显著不同），A1/A3 与 `deadline` 序完全可能分叉。`[OBS]`（127 次选择）+ `[INF]`（样本内机制）

2. **94.5% 的决策根本没有候选竞争。** 127 次 A3 决策分布在 39 个 cell（g18-c1 无决策，其余每 cell 1–8 次）；120 次只有 1 个候选，7 次有 2 个。`[OBS]`（exposure audit）

3. **在有竞争的 7 次里，三个排序键给出同一个名次。** 每次都是"刚创建的 entry（`q = 0.500`，deadline==now）"对"较老的 entry（`q = 0.000572…0.483432`）"，而 deadline 序、`q` 序、`L` 序三者名次一致；127/127 次 A3 选的 program 与 A1 相同。`[OBS]`（本轮从 Archive 提取 `selection_trace`）

4. **本轮的可观测结果面很薄。** 所有 20 个存在 A0−N0 差异的 cell，差异**全部且只**落在该 run 的**最后一个请求**上；A0/A1/A2/A3/E0 之间在 960 个请求级观测上（40 cell × 24 request）× 4 臂 = **3,840 次比较，零不一致**。但"每 cell 一个决策点"的说法不成立：每 cell 有 1–8 次 forced-release 决策，最后一次决策之后仍有 1–2 个请求到达；20 个差异 cell 中 19 个至少有 1 次 release，g18-c1 是零 release 的反例（§3.2）。`[OBS]`（本轮 N/E/C 复算）

5. **因此本轮的零是"选择一致"的零，不是"结果坍缩"的零。** 一旦某个 entry 被选中，它最深 `need` 个 block 就被记为预测受害者（`predicted_victim_count == need`，127/127），且与物理驱逐集完全包含（`12,545 = 12,545`），所以**选择确实决定驱逐集合**。差别只在于四个臂从未做出不同选择。`[OBS]`

这条区分很重要：如果零是"结果坍缩"，问题在机制；既然是"选择一致"，问题是**决策几何与信号冗余**。下一轮的着力点因此明确得多。

---

## 2. 证据矩阵

| # | 主张 | 等级 | 证据来源 |
|---|---|---|---|
| E1 | 270 run 全部完成（Noise 30 + Main 240），无最终失败 | `[OBS]` | `pipeline-state.json`, `main-report.json`, `noise-report.json` |
| E2 | Primary population = 18 paired Groups，`group_weight = 1/18` | `[OBS]` | `main-report.json:primary` |
| E3 | A1/A2/A3/E0 − A0 的 `mean_delta` 全部为 `0.0` | `[OBS]` | `main-report.json:primary` |
| E4 | 逐请求级：A0/A1/A2/A3/E0 的 `recomputed_tokens` 与 `eligible_prefix_tokens` 在 960 个请求级观测 × 4 臂 = 3,840 次比较上完全一致；40 cell × 6 臂 × 24 request = 5,760 行请求集合完整，六臂 `request_id` 集合与顺序一致 | `[OBS]` | 本轮 `nec-cells/*.json` 复算（§12.2） |
| E5 | N0 − A0 = +1918.22（18 paired Groups / 36 cells）；H3-0 A0−N0 = −3123.2（20 Groups / 38 cells，两 cell 组内 1/2，g09/g18 单 cell 权重 1）；H3-R A0−N0 = −6435.56（9 RESPONSIVE Groups / 16 cells） | `[OBS]` | `main-report.json` |
| E6 | 20/40 cell 存在 A0−N0 差异，且 100% 只落在该 run 最后一个请求；其中 19 个 cell 至少有 1 次 forced release，g18-c1 为 0 次 release 的例外；H3-0 内为 18/38 cell | `[OBS]` | 本轮复算（§12.3） |
| E7 | `σ_run = σ_δ = tied = 0.0`，三个层内 σ 亦为 0；**覆盖范围仅为 5 Groups / 10 个 A0 cell / 30 run（g01,g04,g06,g07,g10）**，不含 A1/A2/A3/E0，也不含其余 30 个 cell | `[OBS]` | `noise-report.json`, noise run logs |
| E8 | 各 release 臂 127 次 forced release（39 个 cell，每 cell 1–8 次；g18-c1 为 0）；N0 为 0 | `[OBS]` | exposure audit §3 |
| E9 | A3：127 次决策分布在 39 个 cell；120 次单候选、7 次双候选；127/127 `step2_sufficient`；127/127 与 A1 同选同一 program（前缀 hash 跨 run 不可移植） | `[OBS]` | `summary.json:a3`, `decision-audit.csv` |
| E10 | A2：53 cost-known、74 `content_unverified` 回退、51 搜索截断（2 次未截断）、0 次与 Native LRU 不同 | `[OBS]` | `summary.json:a2` |
| E11 | G3-CM 可判别决策 = 0，`H2 = NOT_EVALUABLE` | `[OBS]` | `summary.json:g3_cm` |
| E12 | `predicted_victim_count == need` 在 127/127 次成立；`predicted_victim_total = 12,545 = predicted_physical_overlap`；`matched_physical_blocks == need` 仅 108/127，其余 19 次 `matched = 128`（物理量化；这些行的 `required_blocks` 可能小于 128）而 `need < 128`；`required_blocks` 本身服从 36–128（108/127 为 128） | `[OBS]` | `decision-audit.csv` 复算（§12.6） |
| E13 | A0 排序键为 `(deadline, min native rank, identity)`；A1 Step-2 为 `q·[λN+(1−λ)min(need,N)]`；A3 为 `(L, deadline, identity)`，`L=q·prefill·S/m`；E0 为 `(deadline, identity)`；Step-2 的**充分性判据**是 `new_blocks >= need`（N），不是 `suffix_blocks >= need`（S） | `[OBS]` | `docs/phase3-final-evaluation-protocol.md` §5.1 臂表；`src/kvopt/costaware/a1_entry.py`, `a3_suffix.py`, `e0_deadline.py` |
| E14 | `q = sigmoid((deadline − t)/τ)` 对 deadline **严格单调递增**；134/134 候选的 `q` 与 `deadline` 同序 | `[OBS]` | `a1_entry.py:reuse_proxy` + 本轮复算 |
| E15 | 7 次竞争决策中，被选中候选的 `q` 严格小于另一候选（0.483432<0.500、0.048047<0.500、0.000572<0.500、0.012283<0.500） | `[OBS]` | 本轮 `selection_trace` 提取（§12.4） |
| E16 | 7 次竞争决策中 `suffix_blocks ≥ need` 恒成立；`S = need` 在 6/7 次成立，g10 的两候选 `S = 270 / 271` 而 `need = 127`（差 1 block）。全局 134 个候选审计中 `S = need` 为 122/134；**但分支判据是 `new_blocks >= need`（134/134）** | `[OBS]` | 同上 + 全量 `selection_trace` 扫描（§12.4） |
| E17 | 若在 7 次竞争决策中选了另一候选，**上界**损失 ≈ `need × 16 tokens`（747 blocks → 11,952 tokens，≈664/paired group）。真实值取决于被驱 chain 的下游复用深度 | `[HYP]` | §6.3；须由 §8 Stage-0 oracle 精确计算而非估算 |
| E18 | `downstream_recompute_attribution = NOT_ESTABLISHED`（逐决策） | `[OBS]` | Archive 字段；exposure audit §6 |
| E19 | actual-order：8 cell 精确、32 cell 六臂共同偏离、0 cell 跨臂分歧；5,760/5,760 E 确定且与冻结 E 一致 | `[OBS]` | `phase3-actual-order-audit.md` |
| E20 | Frozen replay execution conformance = **FAIL / deviation**（未修改、不得表述为 PASS） | `[OBS]` | 同上 §1、§5 |

---

## 3. 先看结果面：这个指标到底能看见什么

在讨论"为什么是 0"之前，必须先确定**这个设计有能力看见什么**。本轮的答案非常窄。

### 3.1 决定 E 与 C 的链条

`recomputed_tokens = E − C`。本轮复算显示（E4、E6）：

- **`E`（eligible prefix）在 A0/A1/A2/A3/E0 之间完全相同**，逐请求级。
- **`C`（native cached prefix）也完全相同。**
- 差异只出现在 **A0 vs N0** 之间，落在 `C` 上：`E` 相同而 `C` 不同。

也就是说：**forced Entry Release 这个机制的收益，表现为"物理上保住了多少 block"，而不是"逻辑上多认了多少前缀"。** 这符合协议里 `E` 必须臂无关（arm-independent）的设定。

### 3.2 唯一的结果窗口：最后一个请求

`[OBS]`（E6）20 个存在差异的 cell，差异**全部且只**落在该 run 最后一个请求：

```
g01-c1 只有 django__django-13401:turn:56
g02-c1 只有 matplotlib__matplotlib-14623:turn:100
g03-c1/c2 只有 psf__requests-2317:turn:100
...
g18-c2 只有 django__django-16032:turn:100
```

但原因**不是**"每 cell 只有一个决策点"。事件流给出的是：

- 每 cell 有 **1 个受控压力 boundary**，但冻结循环在该压力下会发出 **1–8 次 forced-release 决策**；全战役 127 次，分布在 39 个 cell（g18-c1 为 0 次）。协议 v4 §8 的 G3-CM 仍写"40 available decisions"（每 cell 1 次）；实际是 **127 次（3.2×）**。这是执行暴露高于设计，不是设计变更。`[OBS]`
- 对每个 cell，**最后一次** forced-release 决策之后仍有 **1–2 个请求**到达（不是 0/1）。因此"最后一个请求"是 20/20 个差异 cell 中实际承载差异的请求，但"每 cell 至多 1 个候选请求"不是几何定理；理论上的下游请求数是每 cell 1–2 个（39 个有决策的 cell，最多 78 个请求级观测；g18-c1 无决策），实际承载差异的是 20 个。
- 19/20 个差异 cell 至少有 1 次 release；g18-c1 没有任何 release，却仍有 **−544** 的 A0−N0 差异（A0 最后一个请求 `C=16,304`，N0 为 `15,760`）。g18-c1 不在 H3-0 中，但这个反例说明：校准范围之外不能假定零噪声，也不能把每一处 A0−N0 差异都归因于 release 选择（§6.1、§11）。

> **结构性结论 `[OBS]`：** 本轮的 outcome surface 是"**127 次决策 / 39 个 cell / 每 cell 最后一次决策后 1–2 个请求 / 实际 20 个请求级差异**"。它比协议预期的 40 次决策更宽，但**可承载选择差异的请求级观测仍然只有 20 个**。
> 因而正确的表述是："在这批 trace 上，只有最后一个请求的前缀链触及了被截断区域"——这是样本性质，不是"每 cell 只有一个决策点"。
> 这也解释了为什么 `σ_run = 0` 与精确的 0 可以同时出现，却不构成"没有噪声地板"的普遍证明：**结果面对选择很薄，且 `σ_run = 0` 的覆盖范围只有 10 个 A0 cell。**

### 3.3 为什么选择的后果是"精确的"

`[OBS]`（E12、E16）本轮复核了两条链路：

| 观测 | 值 |
|---|---|
| 被选中 entry 的物理驱逐 block 数（`matched_physical_blocks` 口径） | `= need` 在 108/127；其余 19 次为 128 |
| 该决策的预测受害者数 | `predicted_victim_count = need`，127/127 |
| 预测受害者与被物理驱逐的交集 | `12,545 = 12,545`（完全包含） |
| 预测集合与物理集合完全相等 | 108/127 次；其余 19 次物理多出 block |

所以机制是这样的三段式：

1. 释放 entry X → X 的最深 `need` 个 block 被记为预测受害者并变为可驱逐；
2. Native LRU 驱逐它们，并在 19/127 次中把 X 的物理驱逐量推到 128 block（压力量子）；
3. 于是 **X 的前缀链被截断**，截断量 ≈ `need`（部分情形 = 128）。

`[OBS]` 这里还有第二个**独立的过量机制**，值得单列：当残余 `need < 128` 时，物理驱逐仍按 128 block 的量子执行（19/127 次）。所以即使候选完全选对、预测完全准确，仍会多驱逐 `128 − need` 个 block。这是 M4（粒度不匹配）在**目标侧**的第二个来源，与 entry 过大（相对 128 为 3.0–14.5×，相对实际 `required_blocks` 为 3.0–36.2×）无关。

**因此选择确实决定驱逐集合，也决定截断深度。** 这一点排除了"选择被后续 LRU 抹平"这一可能解释，把归因收敛到"四个臂从未做出不同选择"。

---

## 4. 机制诊断：六类候选原因逐项裁定

用户指定的六类原因，逐项给判定。**核心结论是：M1（决策暴露）与 M5（排序退化）已被证实为主要原因；M3（信号不敏感）与 M4（Entry 粒度）被证实为结构性放大因素；M2（候选集缺乏区分度）在事后意义上正确但需要更精确的表述；M6（workload 缺乏可利用差异）只被部分证实，不能外推；"策略机制无效"未被证实。**

### M1 决策暴露不足 —— **已证实（主因之一）**

| 证据 | 数值 |
|---|---|
| A3 forced release 决策总数 | 127（39 个 cell；每 cell 1–8 次；g18-c1 为 0） |
| 单候选决策 | **120（94.5%）** |
| 双候选决策 | **7（5.5%）** |
| 分支分布 | `step2_sufficient` 127/127；`single_step` 127/127 |
| 32/39 个 cell 内 `candidate_total == decision_count`（整 cell 无选择） | `[OBS]` |
| 最后一次决策后的下游请求数 | 1–2（不是 0/1；§3.2） |

`[OBS]` **有效决策暴露 = 7 次竞争决策 × 1–2 个下游请求 = 7–14 个可承载差异的请求级观测；实际承载差异的是 7 次决策所在的 7 个 cell 的最后一个请求（7 个观测）**，而不是 127。

> 一个必须写清的负面结论：**127 次 strategy invocation 不等于 127 次算法机会。** 竞争决策的分母是 7。本轮的 `G3-CM = 0` 与 `H2 = NOT_EVALUABLE`（E11）是这一点的直接后果，而不是算法失败。

### M2 候选集缺乏区分度 —— **表述需要精确化**

`[OBS]`（E16）修正一个容易犯的错误：7 次竞争决策里，两个候选的 `S`（后缀长度）**几乎完全相等** —— 6 次都恰好等于 `need`，g10 的两次为 `270 / 271`（`need = 127`，差 1 block）。所以"区分度"并不低 —— 两个候选在 `S` 上几乎同等，差异在 `q`（1.03–874×）、`prefill`（1.20–1.95×）、`m`（1.13–1.83×）。

正确的说法不是"候选太像"，而是：**候选在"决定结果的那个维度"（未来复用深度）上没有被区分，而在"已经唯一确定结果的那个维度"（`q`/deadline）上差异很大——但 g10 是例外，`q` 只差 3.4%。** 前者使成本模型无从发挥；后者使模型大多只能给出同一个答案，却不是数学上的必然。

### M3 成本/收益信号不敏感 —— **已证实为结构性因素**

`[OBS]` + `[INF]`：把三个目标函数写在同一次决策上（g09-C1，`need = 97`）：

| candidate | `q` | `prefill` | `m` | `d_min` | `S` | `new_blocks` | A0 key (deadline) | A1 `expected` | A3 `L` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| django-12050 | 0.500000 | 0.961886 | 1006 | 910 | 97 | 999 | **399.289** | 274.0 | 0.046373 |
| sympy-13551 | 0.048047 | 0.803228 | 889 | 793 | 97 | 882 | **309.699** | 23.519 | 0.004211 |

- A0 按 `deadline` 升序 → 选 sympy（309.699 < 399.289）
- A1 按 `expected = q·(need + 0.5·(new_blocks − need))` 升序 → 选 sympy（23.519 < 274.0）
- A3 按 `L = q·prefill·S/m` 升序 → 选 sympy（0.0042 < 0.0464）—— 此例 `S` 两候选相等，故 `S/m` 项只能通过 `1/m` 起 1.13× 的作用
- E0 按 `deadline` 升序 → 选 sympy

**在本样本的 7 次竞争决策中，四个键给出同一名次（127/127 同 program）。** 这不是普遍等价：`q` 随 `deadline` 单调递增，且在 6/7 次里 `q` 的比值（10.4×–874×）远大于 `prefill`（1.20–1.95×）与 `S/m`（1.13–1.83×）；但 g10-C1 的 `q` 只差 1.034×，A3 的 `L` 仅以 **2.0%** 的边际同序（0.11883 vs 0.12123），A1 的 `expected` 边际为 51.6%。只要候选几何稍变，A1/A3 与 deadline 序就可能分叉。`[OBS]` + `[INF]`

### M4 Entry 粒度不合适 —— **已证实为结构性因素**

`[OBS]` 两个**独立**的过量源：

**源一（entry 侧）**：单个 entry 的可回收量（`new_blocks`）在全部 134 个候选上是 **389–1850 blocks**（7 次竞争决策是 709–1304），而 `required_blocks ∈ [36,128]`、`need ≤ 128`。**相对 128 的上限，一次释放过冲 3.0–14.5×；相对实际 `required_blocks`，过冲 3.0–36.2×。**

**源二（目标侧）**：当残余 `need < 128` 时，物理驱逐仍按 128 block 的量子执行 —— `matched_physical_blocks = 128` 而 `need` 更小的情形有 **19/127** 次。也就是说**即使候选完全选对、预测完全准确，仍会多驱逐 `128 − need` 个 block**。

后果：

- 127/127 次决策落在 `step2_sufficient`，`per_unit`（Step 3）、`pair_lookahead`（Step 4）、`deadline_fallback`（Step 5）**一次都没被触发**。原因是 Step-2 的判据 `new_blocks >= need` 在 134/134 个候选上成立（N=389–1850，need≤128）；不是 `suffix_blocks >= need`。
- 于是"释放多少"这个自由度在本轮**根本不存在**，只剩"释放谁"。

`[INF]` 这条粒度失配是设计层面的，不是 workload 缺陷：只要 entry 的 block 数是目标的 3–14.5 倍（相对实际 `required_blocks` 可达 36×），级联阶梯的后三级就永远进不去。**这也意味着 A1 与 A3 的差别被压缩到了 Step-2 的排序键上**，而后三级本来是它们可能分叉的地方。

`[INF]` 源二还有一个不易察觉的副作用：按 `matched_physical_blocks` 的口径，多驱逐的 `128 − need` 个 block 属于**被选中 entry**，而不是"随便哪条链"。所以在残余 `need` 很小的时候，选择某条链的代价被放大了 `128/need` 倍（最极端：`need = 4` 时放大 32×）。这使"释放谁"在**小 need 决策**上比在**大 need 决策**上更值钱 —— 而本轮的 7 次竞争决策恰好全是 `need ≥ 97` 的大 need 决策，是**最不值钱的那一端**。`[OBS]`+`[INF]`

### M5 策略排序退化为 A1 —— **已证实（主因之二）**

`[OBS]`（E13、E14、E15、E9）：

- A1 与 A3 在 127/127 次选中同一 **program**（不是同一 prefix hash：跨 run 的 native hash identity 不可移植）；
- A3 与 E0 在 127/127 次选中同一 program；
- A0 与 E0 在 127/127 次选中同一 program；
- 7 次竞争决策中，被选中候选的 `q` 恒为较小者。

`[INF]` **在本样本的 127 次决策上**，A0、A1、A3、E0 给出同一个 program 序。它们的差别只在第二、第三级 tie-break（A0 用 `min native rank`，E0 用 `identity`，A1/A3 用 `deadline` 再 `key`），而本样本所有候选的 deadline 互不相等（134/134），所以这些 tie-break 没有机会起作用。**这是样本结论，不是"四个公式数学等价"；** g10-C1 的 `q` 只差 1.034×、A3 边际 2.0%，已接近翻转边界。

`[OBS]` 旁证：A2 在 block 层用了完全不同的选择器，53 次 cost-known 下**选择结果与 Native LRU 完全相同**（E10）。也就是说，即使在 block 层换了机制，这批 workload 上依然没有产生分歧。

### M6 Workload 本身缺少可利用差异 —— **部分证实，不可外推**

`[OBS]` 支持的部分：

- H3-0 的 20 个 group 值中，前 5 个（g09、g18、g03、g04、g12）合计 −49,728，占 group-value 总量 −62,464 的 **79.6%**；**6 个 group 贡献恰好 0**（g06、g08、g11、g14、g17、g20）。若只看 18 个 primary paired groups，g03/g04/g12 合计占 primary 总量 −34,528 的 **63.1%**；g09/g18 是 H3-0 的事后加入，二者合计占 H3-0 的 **44.7%**。
- `need` 分布：76/127 次决策 `need ∈ {127,128}`，51 次 `need ≤ 115`。
- `new_blocks ≥ need` 在 134/134 个候选成立；`suffix_blocks ≥ need` 也在 134/134 成立（`= need` 122，`> need` 12，`< need` 0），说明单 entry 的最深后缀总是够用 —— 这是**冻结 workload + 2048-block 池**下的几何性质，不是算法找到的便宜。

`[INF]` 不能外推的部分：本轮每 cell 有 1 个受控压力 boundary、1–8 次 forced-release 决策、2 sessions × 12 checkpoints = 24 requests/run，TTL 由 server-gap history 自校准到接近 inter-arrival。**"这批 workload 缺少可利用差异"是关于"2 sessions × 12 checkpoints × 单次受控压力（1–8 次 release 决策）× 自校准 TTL × 2048-block 池"这一特定几何的陈述**，不是关于 agent workload 总体的陈述。

### 收束：不是"机制无效"

`[OBS]` 三条反面证据：

1. **保护本身有效（在 H3-0 主总体上）。** A0−N0 在 20/40 cell 非零，40-cell 未加权合计 −100,352 tokens；H3-0（20 Groups / 38 cells）为 −3,123.2 tokens/group，占 H3-0 A0 group mean（40,205.6 tokens/group）的 **7.8%**。其中 19/20 个差异 cell 至少有 1 次 release；g18-c1 是 0 次 release 的例外（−544），不在 H3-0 中。所以"强制 Entry Release + 保护"这个机制**在 H3-0 上有效**。
2. **选择确实决定驱逐。** `predicted_victim ⊆ physical`，且 `matched = need` 精确（§3.3）。
3. **只有在"选谁"这一层没有分歧。** 而分歧的不存在有两个结构原因（M1 无候选、M5 样本内同序），都不是"成本模型算错了"。

**因此正确的表述是：`no observed incremental benefit`，且其机制原因是"决策几何 + 信号冗余"，而不是"Cost-Aware 无效"，也不是"Cost-Aware 与 A0 等价"。** 后者需要至少一次真实的选区分歧才能主张，本轮没有。

---

## 5. 逐臂分析：每个策略实际改变了什么

| 臂 | 冻结定义（E13） | 实际改变的东西 | 为什么 `E−C` 不变 |
|---|---|---|---|
| **N0** | 不注入 forced release | 不改变任何保护；`boundary_id` 时间线保留 | 它不是"策略不变"，是**机制缺席**。因此它与 A0 的差是"保护的有无"，不是"排序的好坏" |
| **A0** | `(deadline, min native rank, identity)`，无阶梯 | 用 deadline 选 entry，释放其最深 `need` block | 它是本轮的**参照**；本样本 127/127 与 A1/A3/E0 同选（样本观测，不是等价性证明） |
| **A1** | 冻结阶梯，Step 2 = `q·[λN+(1−λ)min(need,N)]` | 名义上按"期望重算量"排序 | `expected ≈ q × 缓变项`，`q` 随 deadline 递增 ⇒ 在本样本上与 A0 同选；且 127/127 落在 Step 2，后三级阶梯从未触发 |
| **A2** | A0 策略 + cost-aware **block** selector | 换了 block 层选择器 | 74/127 因 `content_unverified` 回退到 Native LRU；53/127 cost-known（51 次搜索截断）下受害者序列与 Native LRU 相同；0 次与 Native LRU 不同 |
| **A3** | 冻结阶梯，Step 2 = `(L, deadline, identity)`，`L=q·prefill·S/m` | 把"重载代价"与"后缀比例"引入排序 | Step-2 判据是 `N ≥ need`（134/134），不是 `S ≥ need`；`S` 在候选间几乎相等（6/7 次相等，g10 差 1 block），`S` 项几乎不区分；剩下 `q·prefill/m`，6/7 由 `q` 支配，g10 边际 2% ⇒ 本样本与 A0 同选。且 127/127 落在 Step 2 |
| **E0** | 同 A1 阶梯，Step 2 = `(deadline, identity)` | 显式 deadline-only | 与 A0 的差别只在第 2/3 级 tie-break，而本样本 deadline 无并列 ⇒ 127/127 与 A0 同选（样本结论，不是等价性证明） |

### 5.1 A3 127/127 与 A1 同选背后的三个独立原因

这是本轮最值得写清楚的一条，因为它是三个原因**同时**成立的结果，任何一个单独成立都足以制造零效果：

1. **分支从未下行，判据是 `new_blocks >= need`（N），不是 `suffix_blocks >= need`（S）。** 134/134 个候选的 N 在 389–1850，而 `need ≤ 128` ⇒ 每次都有单步充分候选 ⇒ 127/127 `step2_sufficient`。后三级阶梯（A3 与 A1 唯一可能分叉处）零触发。`S`（= `m − d_min + 1`）在本样本也恰好 ≥ need（122 equal / 12 greater / 0 less），但把它当成分支判据会误述机制。`[OBS]`
2. **Step-2 键的主导项相同，但不普遍。** A1 的 `expected` 与 A3 的 `L` 都含因子 `q`；在 6/7 次竞争决策中 `q` 的比值（10.4–874×）远大于 `prefill`（1.20–1.95×）与 `S/m`（1.13–1.83×）。g10-C1 是例外：`q` 只差 1.034×，A3 的 `L` 仅以 2.0% 的边际同序，A1 的 `expected` 边际为 51.6%。`[OBS]`+`[INF]`
3. **候选集在 94.5% 的情况下只有一个元素。** 即使前两条不成立，也无从分歧。`[OBS]`

> `[INF]` 若要打破 A3 与 A1 的本样本同选，至少需满足其中之一：出现一个非 Step-2 的分支（要求 `need` 大于**任何**单 entry 的 N，而不是 S），或出现一个 `q` 近并列但 `N`/`prefill·S/m` 显著不同的候选对。本轮的 7 次竞争决策两者都不产生；这是样本结论，不是不可能性证明。

### 5.2 为什么 `H2 = NOT_EVALUABLE` 是正确判定而不是保守

`G3-CM` 要求 ≥8 个 A3 与 E0 选择不同的决策。实际 0 个。`[OBS]` 这不是阈值过严：在本样本"127/127 同 program + 94.5% 无候选"的条件下，**任何**阈值都会得到 0。`H2` 的可评估性缺陷是上游（暴露与几何）造成的。

---

## 6. 重新读这三个数：集中度与总体依赖

用户给的三组数彼此一致，但**它们之间的差异比它们本身更有信息量**。

### 6.1 三组数各自成立，而且可以精确重放

`[OBS]` 用注册的总体定义复算：

| 估计量 | 总体 | 权重 | 值 |
|---|---|---|---|
| N0 − A0 | 18 paired groups / 36 cells | 1/18；组内 2 cell 各 1/2 | **+1918.22** |
| H3-0 A0 − N0 | 20 groups / 38 cells | 1/20；两 cell 组各 1/2，g09/g18 单 cell 权重 1 | **−3123.20** |
| H3-R A0 − N0 | 9 RESPONSIVE / 16 cells | 1/9；两 cell 组各 1/2，g09/g18 单 cell 权重 1 | **−6435.56** |

三者互不矛盾（符号一致：N0 更差），差异全部来自**总体与权重**：H3-0 比 paired 多算 g09、g18 的 C2 cell（−15,104 与 −12,832），这两个值占 H3-0 **group-value 总量（−62,464）**的 44.7%。

> 必须区分三个不同的"总量"：40 个 archive cell 的未加权差值和为 **−100,352**；H3-0 的 38 个 cell 未加权和为 **−96,992**；H3-0 的 20 个 group 值之和为 **−62,464 = 20 × (−3,123.2)**。三者不是同一个量，不能互相替代。H3-0 的 −3,123.2 是 **group 均值**，不是 cell 均值（cell 均值是 −96,992 / 38 = −2,552.4）；也不是 40-cell 均值。

### 6.2 集中度

`[OBS]` 逐组 `mean(A0−N0)`（H3-0 口径：两 cell 组内平均；g09/g18 只有 C2，取该 cell）：

| 组 | 值 | 占 H3-0 group-value 总量份额 |
|---|---:|---:|
| g09 | −15,104 | 24.2% |
| g18 | −12,832 | 20.5% |
| g03 | −8,072 | 12.9% |
| g04 | −7,160 | 11.5% |
| g12 | −6,560 | 10.5% |
| g02, g05, g10, g16, g19 | 各 −2,048 | 各 3.3% |
| g07 | −1,200 | 1.9% |
| g01 | −552 | 0.9% |
| g13 | −480 | 0.8% |
| g15 | −264 | 0.4% |
| g06, g08, g11, g14, g17, g20 | **0** | 0 |

两个可直接观察的形态：

- **前 5 个 group 占 79.6%，6 个 group 完全为 0。** g09/g18 是 H3-0 的事后加入（各有 1 个 cell），二者合计占 44.7%；若只看 18 个 primary paired groups，g03/g04/g12 合计占 primary 总量 −34,528 的 63.1%。
- **量化到固定块**：8 个 cell 的差值恰好是 `−4096` tokens（= 256 block × 16）。差值不是连续分布，而是**离散的"一个前缀块组丢失/未丢失"**。

`[INF]` 这意味着 A0−N0 的效应在多数 cell 上是**二值的**：最后一个请求的前缀要么整体保住，要么整体丢掉一块。任何"百分比改善"的叙述都会掩盖这个二值性。

### 6.3 反事实落差：本轮错过了多大的东西（`[HYP]`）

`[OBS]` 每个竞争决策都有两个候选，且**只有一个被释放**。若释放的是另一个，被截断的链就换了一条。关键在于：最后那个承载差异的请求，需要的正好是**某一条特定链**的全部前缀。于是：

| cell | `need` | 被选中的链 | 未被选的链 | 若选未选链，该链被截断的 block 数 |
|---|---:|---|---|---:|
| g09-C1 | 97 | sympy-13551 (m=889) | **django-12050 (m=1006)** | 97 |
| g09-C2 | 97 | sympy-13551 (m=889) | **django-12050 (m=1006)** | 97 |
| g10-C1 | 127 | matplotlib-26466 (m=896) | **django-15569 (m=1301)** | 127 |
| g10-C2 | 127 | matplotlib-26466 (m=896) | **django-15569 (m=1301)** | 127 |
| g16-C1 | 101 | django-13363 (m=716) | **matplotlib-25287 (m=1311)** | 101 |
| g16-C2 | 101 | django-13363 (m=716) | **matplotlib-25287 (m=1311)** | 101 |
| g18-C2 | 97 | sympy-13974 (m=748) | **django-16032 (m=1019)** | 97 |

粗体的四个链，正好就是各 cell **最后一个请求所属的 program**（§6.2 的差异定位）。也就是说：**在这 7 次决策里，"选谁"直接决定了那个唯一可观测的请求是多算还是少算。**

因此落差有一个干净的**上界**：

$$
\text{swing}_{\max} = \sum_{i=1}^{7} \text{need}_i \times 16 = 747 \times 16 = 11{,}952 \text{ tokens}
$$

按 18 个 paired groups 摊薄 ≈ **664 tokens/paired group**。**但这不是"每组最多 664"**：7 次决策集中在 4 个 group（g09、g10、g16、g18）；若只摊到这 4 个 group，总上界是 ≈2,988 tokens/group。664 是按 18 个 group 的**平均**，不是 group-level 上界。Stage-0 gate 因此使用 group-level `G_g`（§8.0.8），不会被"总量大但集中在少数 group"误导。

对比锚点：primary 18 groups 的 N0−A0 = +1,918.22 tokens/group（绝对值）。所以**"选错"的代价上界（平均口径）约为"没有保护"的 34.6%** —— 同一量级，不是可忽略的二阶项；若按受影响的 4 个 group 计，落差更大。

`[HYP]` 这是**上界**，不是估计值。它假设：(a) 被释放链的最深 `need` 个 block 确实会被 Native LRU 驱逐；(b) 下游最后请求确实会复用该链到被截断的深度以下。条件 (a) 有强证据支持（`predicted_victim ⊆ physical`，`matched = need` 精确）；条件 (b) 需要逐请求的复用深度证据，**在本轮是未知的**。真实值只会更小。

> **这条反事实是全文最重要的量化结论**：本轮的零效果不是"可检测上限太低"（`σ_run = 0` 只在 10 个 A0 cell 上成立，不能推出全局无噪声地板），而是"**7 次本可承载数百 tokens/group 落差的机会，全部被同一个排序结果吞掉了**"。这直接决定了下一轮的门槛应该设在"能否制造分歧"，而不是"能否提高精度"。

---

## 7. 重新审视 Entry-level Cost-Aware 设计

用户提出的候选评分思路是 `EntryLoss = (1 − reuse_score) × recompute_cost`。**本节不预设它正确**，先做形式化，再指出它的符号问题，最后给出我认为正确的目标函数形式。

### 7.1 Entry 作为决策单位的价值与代价

**价值 `[INF]`：**

- Entry 是 retention 保护的天然单位。释放一个 entry 是**原子**操作，不破坏"保护语义"（部分释放会让 entry 处于"半保护"状态，现有 `RetentionEntrySnapshot` 与 `commit_pressure_releases` 都不表达这种状态）。
- Entry 是**可审计**的单位。`SelectionPlan` 与 `predicted_victim` 都以 entry 为锚，物理结果也按 entry 归属（`matched_physical_blocks` 逐决策可对账）。
- Entry 的几何信息（`m`、`d_min`、`S`）**恰好决定了截断深度** —— 也就是 §3.3 里唯一真正影响 `C` 的量。

**代价 `[OBS]`：**

- 粒度太大：单 entry 389–1850 block vs `required_blocks` 36–128 ⇒ 相对 128 上限过冲 3.0–14.5×（相对实际目标 3.0–36.2×），后三级阶梯永久失效（M4）。
- 数量太少：每 cell 同时"存活且受保护"的 entry 通常只有 1 个 ⇒ 候选集退化（M1）。

**判断 `[INF]`：在本轮几何下，Entry 作为单位既太大（过冲）又太少（无候选）。这是同一枚硬币的两面：受保护 entry 少，是因为 TTL 自校准到接近 inter-arrival，任何一个时刻只有一个 entry 还在保活期内。**

### 7.2 对 `(1 − reuse_score) × recompute_cost` 的符号审查

设 `p = P(该 entry 在未来窗口内被复用)`，`c = 重载该 entry 的代价`。

- **驱逐 X 造成的期望损失** = `p_X · c_X`。
- 用户的 `(1 − p_X) · c_X` = `c_X − p_X c_X`，即以**最小化**为目标时会**驱逐最可能被复用的 entry** —— 符号相反。
- 只有当它是**最大化**目标（"保留价值"）时语义才自洽，但那与"release 选择"的方向相反。

`[INF]` 这不是小事：A1 的 `expected = q·(...)` 与 A3 的 `L = q·prefill·S/m` 都是**最小化 `p·c`**，与用户式子方向相反。实现前必须先钉死"这个量是被最小化的损失，还是被最大化的保留价值"。

### 7.3 我认为正确的目标函数形式（供讨论，不冻结）

在本轮的机制下，"释放谁"的正确目标不是"谁的期望重载代价最小"，而是：

$$
\Delta R(X) \;=\; \sum_{b \in \mathrm{evict}(X)} P\bigl(b \text{ 在未来窗口内被需求}\bigr)\cdot c(b)
\qquad \text{s.t.}\quad |\mathrm{unlock}(X)| \ge \text{need}
$$

三个因子缺一不可，而现有模型各自漏了不同的一个：

| 因子 | A1 | A3 | 缺失后果 |
|---|---|---|---|
| `P(未来被需求)` | 只用 `q`（≈deadline/age 代理） | 只用 `q` | 无法区分"会不会被复用"与"复用多深" |
| `c(b)` 单块重载代价 | `new_blocks` 计数，不含真实 prefill | `prefill·S/m`（比例，不是绝对量） | 无法比较"丢掉 97 个深块"与"丢掉 97 个浅块" |
| `evict(X)` 实际驱逐集 | 未建模（用 `new_blocks` 当代理） | 用 `S` 近似，但 `S ≥ need` 且候选间几乎相等 | **把"解锁 999 块"当成"驱逐 999 块"** |

`[OBS]` 第三条是本轮最实质的缺口：`unlock(X) = 999` 而 `evict(X) = 97`，相差 10×。**A3 的 `S/m` 试图修正这一点，但在本轮的真实决策上这个修正几乎不起作用** —— 因为 `S` 在候选间要么相等（6/7），要么只差 1 block（g10）。

### 7.4 关键结论：缺的信号是"复用深度"，不是"复用概率"

`[INF]` 由 §3.3 的截断机制直接推出：

> 驱逐 X 的伤害 = `1{未来有请求复用 X 的链，且复用深度 > m_X − need}`。
>
> 决定这个的是**未来的复用深度分布**，而不是"会不会被复用"。本轮 6/7 次 `q` 把"会不会"回答得过于干脆（0.500 vs 0.048、0.0006、0.012），g10 是例外（0.500 vs 0.483）；即便"会不会"是模糊的，`q` 也依然只是 age 的函数，与"复用多深"无关。

这也解释了为什么 A2 在 block 层也没有分歧：block 层的 `q` 同样是时间代理。

### 7.5 成本、复用价值、时间窗口、容量约束、候选集生成之间的关系

按本轮证据排序（`[INF]`）：

1. **候选集生成是上游瓶颈，且由 retention 几何决定。** 候选数 = "当前仍在保活期内的受保护 entry 数"。它由 `TTL` 相对 `inter-arrival` 的比值决定。TTL 由 server-gap history 自校准 ⇒ 系统性接近 1 ⇒ 通常只有 1 个候选。**这一项比任何评分函数都更重要。**
2. **容量约束（`required_blocks ∈ [36,128]`）与 entry 粒度（389–1850）失配**，使"释放量"不可调，阶梯后三级失效。
3. **时间窗口（deadline/TTL）只提供 age 信息**，与"复用深度"正交。
4. **复用价值**是本轮唯一未被任何臂建模的量，而它恰恰是唯一能产生分歧的量。
5. **成本**（prefill）在候选间差异 <2×（本样本 1.20–1.95×），且在本样本 7/7 次中与 `q` 正相关（新 entry 的 prefill 更大），因此在这些候选对里不能单独翻转 `q` 序。

**因果顺序**：候选集 → 粒度 → 信号。任何一个环节单独修都不够；但如果只能改一个，**改候选集生成（时间窗口/并发结构）收益最大**，因为它把"要不要评分"变成有意义的问题。

`[INF]` 一个容易被忽略的副产物：由 §M4 源二，**小 `need` 决策的选择代价被放大 `128/need` 倍**（`need = 4` 时 32×），而本轮的 7 次竞争决策全是 `need ≥ 97`，恰好落在最不值钱的一端。所以下一轮的价值密度排序应是：**小 `need` 且多候选** > 大 `need` 且多候选 > 小 `need` 但单候选。这个优先级目前没有被任何方案显式优化，值得写进 G0。

---

## 8. 下一轮实验设计

### 8.0 前置门：Stage-0 完整轨迹反事实 Oracle（CPU-only，零 GPU）

**在提出任何 GPU 方案之前，必须先做这一步**，否则会重复本轮的"高成本、低信息量"。本节定义的是**完整轨迹反事实重放**，不是"逐决策独立打分后求和"。

#### 8.0.1 反事实对象与动作空间

- **输入**：冻结 archive 中每个 cell 的 24 个请求时间线、受保护 entry 快照、deadline/TTL 状态、Native cache/LRU 状态、每个决策的 `required_blocks`（本 archive 为 36–128，108/127 为 128）。
- **动作**：在每个 forced-release 决策点，从**当前模拟状态重新生成的候选集**中选择一个 entry 释放。动作空间仅限 Entry-ordering：不改 `required_blocks`、不改 TTL/时间线、不做 partial release、不改 Native LRU/APC 语义。
- **策略**：`π` 是从状态到候选的确定性映射；oracle 在全部可达的确定性选择序列上取最优。这个上界只对"同一候选集生成 + 同一释放机制 + 只改选谁"成立；它**不是** P1（改几何）或 P3（改粒度）的上界。

#### 8.0.2 状态转移必须逐项建模

1. **选择与释放**：候选 X 的 blocks 变为 evictable；X 从 protected 集合移除。后续决策的 candidate set 由新的 protected 集合重新生成，**不得复用记录里的 `selection_trace` 候选列表**。
2. **Native eviction**：按冻结的 Native LRU/APC 与 128-block 量子选择物理受害者，更新 cache 内容与 LRU 顺序。`matched_physical_blocks`、`predicted_victim`、`predicted_physical_overlap` 是**模拟输出**，用于与 archive 对账，不是 oracle 的输入。
3. **请求级 N/E/C**：请求按固定时间线到达；`E` 由冻结历史决定且必须臂无关；`C` 由模拟 cache 决定；`N = E − C`；`recomputed = N`。逐请求记录，禁止用 cell 级 aggregate 代替。
4. **后续决策的状态依赖**：`need = target − |E|`、每个候选的 `N_i`、候选集大小、甚至决策次数，都由新状态重算。释放 X 会改变后续 `need` 与候选集，因此**第 i 次决策的收益不能与第 i+1 次独立相加**。
5. **TTL/deadline**：由冻结 request history 决定，臂无关；释放改变"保护是否还在"，不改变未来 deadline 的数值。若实现中发现 TTL 状态依赖释放，必须显式建模并在产出中标注。

#### 8.0.3 Oracle 目标

对每个 cell：

$$
R_\pi(\text{cell}) = \sum_{r=1}^{24} \text{recomputed\_tokens}_\pi(r),
\qquad
G_{\text{cell}} = R_{A0}(\text{cell}) - \min_{\pi \in \Pi} R_\pi(\text{cell})
$$

因为 A0 本身在动作空间内（每个决策点选 A0 会选的候选），**在 A0 轨迹可精确重放的前提下，`G_cell ≥ 0` 必然成立**。若出现 `G_cell < 0`，说明模拟器/状态机有缺陷，必须 fail closed，不能把它解释为"oracle 更差"。

#### 8.0.4 搜索与"避免局部独立优化造成重复计益"

- 每个 cell 的**完整轨迹**是一次评估单位。用 DFS/BFS 枚举选择序列；状态指纹至少包含 `(decision_index, protected entry set, eligible block set, Native LRU order, cache contents)`，并对指纹记忆化。
- 观察到的每 cell 决策数 ≤8、候选数 ≤2；反事实树可能改变，但仍应是有界的。若状态数超过预注册上限（例如 10⁴ 节点/cell），标记 `ORACLE_INTRACTABLE` 并报告覆盖率，**不得**退化成"逐决策取局部最优再求和"。
- **禁止**把逐决策的局部 `ΔR_i` 相加作为 oracle 收益。局部 `ΔR_i` 只能作为诊断量，且必须标注"非可加"；门控只使用完整轨迹的 `G_cell`。
- 若需要报告"某次决策的贡献"，用 leave-one-decision-out 的**重新模拟**，而不是把局部差值累加。

#### 8.0.5 A0 重放校验（Fail-Closed）

- 先用记录中的 A0 策略跑同一模拟器，逐请求比较 `E`、`C`、`recomputed_tokens`，逐决策比较 `matched_physical_blocks`、`predicted_victim`、`predicted_physical_overlap`；必须与 archive **逐整数完全一致**。
- 任何 cell 不能精确复现 → 标记 `NOT_REPLAYABLE`，从 oracle 统计中剔除并报告；不得静默替换成局部估算。
- 预注册覆盖率门槛：18 个 primary groups / 36 cells 中至少 **33 个 cell** 可精确重放，否则 Stage-0 判 **INVALID**，先修模拟器，不做"继续/停止"判断。
- 为什么必须 fail closed：g18-c1 没有任何 forced release，A0−N0 仍差 544 tokens；σ_run=0 只覆盖 10 个 A0 cell，不能假定其余 cell 的 A0 轨迹可精确复现。把不可复现的 cell 混进 oracle 会把 baseline 噪声误记成"选择收益"。
- 额外校验：模拟器应复现 20 个已知 A0−N0 差异的方向与量级（尤其 18 个 H3-0 差异 cell）；若不能，说明 Native eviction 模型不完整。

#### 8.0.6 产出字段

`per_cell`: `oracle_gain_tokens`、`oracle_status`（`EXACT` / `INTRACTABLE` / `NOT_REPLAYABLE`）、`counterfactual_decision_count`、`candidate_set_sizes`、`first_divergence_decision`、`divergence_full_trajectory_gain`、`physical_eviction_validation`。
`per_group`: `oracle_gain_tokens`（两 cell 平均；g09/g18 单 cell 权重 1，若纳入 H3-0 敏感性分析）。
`campaign`: `replay_coverage_cells`、`divergence_rate`、`divergence_gain_distribution`、`oracle_intractable_cells`、`oracle_not_replayable_cells`。

`divergence_full_trajectory_gain` 必须是从分歧点开始、按 oracle 继续策略**重新模拟整条剩余轨迹**得到的差，不是该决策点的局部 `ΔR`。

#### 8.0.7 与 §6.3 上界的关系

§6.3 的 `need × 16`（747 blocks → 11,952 tokens，≈664/paired group）是 `[HYP]`，只作为交叉检查：

- 若 oracle `G` 远小于 664/paired group，说明 §6.3 的条件 (b)（下游请求确实复用被截断深度以下）不成立，应在进入下一轮前修正上界。
- 若 oracle `G` 大于 11,952，说明"只截断 need 个 block、只影响一个请求"的推导有遗漏（例如多次决策叠加、多个下游请求），必须解释后再用。
- 无论哪种情况，**不得**把 664 当作已观测效应；门控只看 oracle 的完整轨迹 `G`。

#### 8.0.8 继续/停止判据（独立 Workload Group 口径）

旧稿的"判据 A：≥8 个 cell 的 oracle 收益 ≥512 tokens"与"判据 B：oracle 上界中位数 <512 tokens/cell 则停止"可以同时成立（例如 8 个 cell 很大、其余很小，中位数仍 <512），因而是**冲突的**。本修订改为单一、互斥、按顺序判定的 group-level 规则。

- **主总体**：18 个 complete paired Groups / 36 cells。每个 group 的 oracle 收益 `G_g = (G_{g,C1} + G_{g,C2}) / 2`。**统计单元是 group，不是 cell**；同一 group 的两个 condition 是重复测量，不能当作独立样本。
- **H3-0（20 Groups / 38 cells）与 H3-R（9 Groups / 16 cells）**：只作敏感性分析。g09/g18 是事后加入，二者占 H3-0 group-value 总量的 44.7%；**不得**用 H3-0 的高值救活一个 primary gate 失败的结果。
- **效应下限**：`Δ_min = 512 tokens/group`（32 blocks × 16 tokens）。这是预注册的 **materiality floor**，不是噪声门槛；`σ_run = 0` 只覆盖 10 个 A0 cell，不能为 240 个主 run 提供噪声地板。这里不做 p 值/显著性主张：oracle 是确定性重放，独立单元是 group，门槛是决策规则。
- **单一判定顺序（先判无效，再判继续/停止）**：

| 顺序 | 条件 | 判定 | 行动 |
|---:|---|---|---|
| 1 | `replay_coverage < 33/36` 或 任一 `G_g < 0` | `STAGE0_INVALID` | 先修模拟器/证据链；**不做**继续/停止判断 |
| 2 | `count(G_g ≥ 512) ≥ 8` | `CONTINUE_P1` | 进入 P1 的 CPU 参数扫描；GPU 仍需单独授权 |
| 3 | `4 ≤ count(G_g ≥ 512) < 8` | `INCONCLUSIVE_GEOMETRY` | 先做 P1 CPU 扫描并重新过门；不得直接进 GPU |
| 4 | `count(G_g ≥ 512) ≤ 3` | `STOP_ENTRY_ORDERING` | 在本 workload 几何下停止 Entry 排序；转 P2/P3 |

- `count` 的分母固定为 18 个 primary groups；`G_g` 用两 cell 平均，**不**把 36 个 cell 当独立样本。
- `G_g` 的中位数、总量、top-5 集中度只作描述，不再作为门控条件；这样就不会再出现"≥8 个 cell 达标"和"中位数 <512"同时触发。
- 若 oracle 在某个 group 上为负（`G_g < 0`），在 A0 可精确重放的前提下只能是模拟器/状态机缺陷；按 `STAGE0_INVALID` 处理，不解释为"oracle 更差"。

### 方案 P1：暴露几何重设计（change decision geometry）

| 项 | 内容 |
|---|---|
| **机制假设** `[HYP]` | 分歧只能出现在"≥2 个 `q` 近并列但复用深度差异大的候选"且"其下游还有 ≥2 个请求"时。本轮 6/7 的 `q` 比值在 10.4–874×；g10 虽近并列，但下游只有 1–2 个请求且实际只有最后一个承载差异。两个条件在样本中很少同时满足。 |
| **改变什么** | retention 时间窗口几何：使 §3.6 的 TTL 与 inter-arrival 比值 > 1（例如 TTL 下界抬升 / 并发 session 交错 / 单 run 多 session 重叠），从而让 ≥2 个 entry 在压力时刻同时存活于保活期 |
| **预期改变的决策** | `P(candidate_count ≥ 2)` 从 5.5% 提升到 ≥50%；`P(selection divergence)` 从 0 提升到 ≥10% |
| **适用 workload** | 多 session 并发或 turn 间隔 > TTL 的 workload；本轮 cohort 需要重新物化（`history_predecessors` 与 `replay_timeline` 随之改变） |
| **最小可行实验** | **CPU-only 可行性门**：用现有 trace 做**参数扫描重放**（TTL 乘数 k ∈ {1, 2, 4, 8}、每 run 压力事件数 ∈ {1, 3}），只统计候选数与分歧率，不跑 GPU |
| **关键指标** | `multi_candidate_rate`、`selection_divergence_rate`、`downstream_requests_after_last_decision` |
| **失败判据** | 若在 TTL×8 且 3 次压力/run 下 `multi_candidate_rate` 仍 <20%，或 `divergence_rate` 仍为 0，则**Entry 排序路线在本 workload 家族不可行**，应转向 P3 |
| **风险** | 改变 TTL/几何会改变 `rho0` 与 Headroom 人口，需重新走一遍 G0/G4 冻结；可能需要新 cohort |

### 方案 P2：价值模型重设计（depth-contiguity + eviction probability）

| 项 | 内容 |
|---|---|
| **机制假设** `[HYP]` | 现有目标函数漏了"实际驱逐集"与"复用深度"两个因子（§7.3）。补上之后，即使在后选几何下也能产生分歧。 |
| **改变什么** | 评分改为 `ΔR(X) = Σ_{b∈evict(X)} P_reuse_depth(b) · c(b)`，其中 `evict(X)` 用 `need` 而非 `unlock(X)`，`P_reuse_depth` 用历史 turn-gap 深度分布估计 |
| **预期改变的决策** | 在 P1 提供的近并列候选上，`P(selection divergence)` ≥30%；在**现有 7 次**竞争决策上，用离线反事实能否翻转（可立即检验，§8.0 的一部分） |
| **适用 workload** | 任意；不依赖候选数增加即可部分验证 |
| **最小可行实验** | **CPU-only 离线反事实**：在现有 Archive 的 7 次竞争决策上计算新评分与 A0 评分，统计翻转次数与翻转后的 oracle 收益 |
| **关键指标** | `flip_rate_on_existing_7`、`flip_gain`、`oracle_regret_reduction` |
| **失败判据** | 若在 7 次上翻转 0 次**且** §8.0 的 primary gate 判 `STOP_ENTRY_ORDERING`（18 个 group 中 `G_g ≥ 512` 的 ≤3 个），则价值模型重设计不值得 GPU 验证 |
| **风险** | 需要"未来复用深度"的估计器；本轮 `downstream_recompute_attribution = NOT_ESTABLISHED`，所以深度证据只能来自 trace 级，不能来自 per-decision 归因 |

### 方案 P3：粒度解耦（partial / granular release）

| 项 | 内容 |
|---|---|
| **机制假设** `[HYP]` | M4 的过冲（相对 128 为 3.0–14.5×，相对实际 `required_blocks` 为 3.0–36.2×）使后三级阶梯永久失效，并把"释放多少"这个自由度消除。若允许**按块**释放一个 entry 的最深 `k ≤ need` 个 block（而不是整个后缀），"释放量"重新成为可优化量。 |
| **改变什么** | retention 语义：从"entry 原子保护"改为"entry 内 block 区间保护"。这是**机制变更**，需要 Protocol v5 + 新的 `RetentionEntrySnapshot` 状态 |
| **预期改变的决策** | `step2_sufficient` 占比下降，Step 3/4 重新可达；每 cell 可承载差异的下游请求数上升（因为可以多次小量释放） |
| **适用 workload** | 任意；对 `need << entry_size` 的形态收益最大 |
| **最小可行实验** | 先用 **CPU 重放** 验证"部分释放"能否在不破坏 `E` 语义的前提下减少过冲；再评估是否需要 GPU |
| **关键指标** | `over_release_ratio`（`unlock/need`）、阶梯分支分布、`evict` 与 `need` 的匹配度 |
| **失败判据** | 若部分释放在 CPU 重放中无法保持 `E` 的臂无关性，或引入 `INDETERMINATE` 证据，则放弃 |
| **风险** | 最高。触碰冻结的 retention 语义与 `commit_pressure_releases`；审计成本最高；可能破坏 `PRESSURE_BOUNDARY` 不变量 |

### 8.1 三个方案的比较

| 维度 | P1 暴露几何 | P2 价值模型 | P3 粒度解耦 |
|---|---|---|---|
| 修的环节 | 候选集生成 | 信号 | 粒度 |
| 首次验证成本 | CPU 参数扫描 | CPU 离线反事实 | CPU 重放 + 可能 GPU |
| 是否触碰冻结协议 | 是（TTL/几何/G0/G4） | 仅 Step-2 键（受 A3 位置约束） | **是（retention 语义）** |
| 单点收益上限 | 高（决定"有没有问题可答"） | 中 | 高 |
| 失败风险 | 中（可能重物化 cohort） | 低 | 高 |
| 与现有归档兼容 | 否（需新 trace） | **是**（可离线验证） | 否 |

### 8.2 共同的反"低信息量"护栏

无论选哪个方案，下一轮的 G0 必须新增三条**前置**条件（不是事后判定）：

1. **暴露门**：`multi_candidate_rate ≥ 20%` 且 **≥8 个独立 Workload Group** 至少出现一次 selection divergence（不是 8 个 cell）。不满足则**不得启动** Main campaign。
2. **上界门**：Stage-0 的 primary gate 必须是 `CONTINUE_P1`（18 个 group 中 `G_g ≥ 512` 的 ≥8 个），而不是"中位数 ≥512 tokens/cell"。`INCONCLUSIVE` 或 `STOP` 都不得用 GPU 绕过；`STAGE0_INVALID` 先修模拟器。
3. **分歧谓词预注册**：在 G0 中写死"什么算一次分歧"（A3 与 E0 选的 program 不同，且两者在**完整轨迹重放**下的收益差 > 0），并在 Main 之前用 calibration 数据验证该谓词非空。不得用逐决策局部 `ΔR` 相加来定义分歧收益。

三条都不放宽任何既有阈值，只是**增加"值得跑"的前置判断**。

---

## 9. 研究路线裁定建议

**建议：先做 Stage-0（§8.0），再按结果二选一 —— 主推 P1，P2 作为同期廉价并行项；P3 暂缓到协议 v5 讨论。当前不授权 P1/P2/P3 的实现、不授权 Protocol v4 修改、不授权 GPU 执行或新正式实验。**

理由：

1. **Stage-0 是唯一能避免重演本轮的步骤。** 它以零 GPU 成本给出"任何 Entry 排序策略在这批 trace 上的完整轨迹上界"。若 primary gate 判 `STOP_ENTRY_ORDERING`（18 个 group 中达标 ≤3 个），则 P1/P2 都不该进 GPU，这时唯一有意义的路线是 P3 或改变 workload 家族。
2. **P1 是唯一能修"上游"的方案。** 本轮零效果的根因是候选集只有 1 个（94.5%），这是几何问题。评分函数再精巧也无法在单元素集合上产生分歧。
3. **P2 便宜且可立即执行。** 它只需要 Archive + trace，可以在 Stage-0 里顺带完成，不必单独授权。
4. **P3 收益最大但代价最高。** 它触碰冻结的 retention 语义与 `commit_pressure_releases`，且会改变 `PRESSURE_BOUNDARY` 不变量。在没有 Stage-0 完整轨迹 oracle 之前启动它，风险收益比不合适。

**需要新的 trace / workload 吗？** 需要，但只在 P1 通过 CPU 可行性门之后。本轮 cohort 的 `replay_timeline` 与 `history_predecessors` 是冻结的；改 TTL/并发结构意味着新的 cohort seal 与新一轮 G0 冻结。

**需要更高决策暴露度吗？** 需要，而且是**唯一的必要条件**。门槛已在 §8.2 给出（`multi_candidate_rate ≥ 20%`、`divergence_groups ≥ 8`）。

**优先级修正** `[INF]`：由 §M4 源二，同样的多候选条件下，**小 `need` 决策的单价更高**（`128/need` 放大）。因此 P1 的 TTL 扫描目标不应只是"候选变多"，而是"**小 `need` 且多候选** 的决策变多"。本轮 7 次竞争决策全在 `need ≥ 97`，是错配的一端。

---

## 10. 哪些路线保留、哪些暂停

| 路线 | 处置 | 理由 |
|---|---|---|
| **A0（deadline Entry）** | **保留为 baseline** | 本轮唯一的参照；本样本 127/127 与 A1/A3/E0 同选（样本观测，不是等价性证明） |
| **N0（无 forced release）** | **保留为对照** | 它提供了本轮唯一有信号的对比（A0−N0），是"保护有效性"的锚点；g18-c1 的零 release 差异说明它不是在所有 cell 上都干净 |
| **A1（阶梯 Entry）** | **暂停为目标** | 它的后三级阶梯在本轮几何下不可达；在 P1 通过之前重复它不会有新信息 |
| **A3（后缀代理）** | **暂停为目标，保留为实现参考** | `L` 的形式在 §7.3 中被分析为缺少两个因子；但它对 `S`/`d_min` 的几何分解是 P2 的直接基础 |
| **A2（block 层）** | **保留为独立线索，优先级降** | 74% 回退说明证据链（`content_unverified`）是瓶颈；修证据链的成本高于 P2 |
| **E0（deadline-only）** | **保留为对照** | 它是"去掉成本模型"的干净对照；本样本 127/127 与 A0 同选，下一轮应保留以测量"成本模型是否产生了任何差别"；不得表述为已证明等价 |
| **Static-TTL / scheduler 轴** | **不在本轮讨论范围** | 本轮全部臂共用 Native scheduler，无 Static-TTL 臂；任何 scheduler 因果主张需另立协议 |

---

## 11. 过度外推防护（必须随结论一起引用）

1. **不得表述为"Cost-Aware 与 A0 等价"。** 本轮没有产生一次真实的选区分歧，因此不存在"两个策略在同一决策上选了不同结果而结果相同"的观测。正确表述：`no observed incremental benefit under a design with 7 competitive opportunities`。
2. **不得把"四个臂同选"表述为"四个公式数学等价"。** 本样本 127/127 同 program 是观测事实；`q` 只保证随 deadline 递增，A1 的 `N` 与 A3 的 `S/m` 仍可在 `q` 近并列时翻转（g10-C1 的 A3 边际 2.0%）。正确表述：`in this sample, the four keys produced the same selection; this is not a general equivalence`。
3. **不得把"同 program"表述为"同一 Entry"。** `selection_trace.key` 的第二段是 native prefix hash，跨 run 不可移植（`cross_run_native_hash_identity = NOT_PORTABLE`）；可比的是 program/chain，不是 hash 级 Entry。
4. **不得表述为"prototype 无效"。** A0−N0 在 H3-0 为 −3,123.2 tokens/group，说明**保护机制在 H3-0 上有效**；失效的是"保护之后选谁"这一层在这批几何上的可分辨性。g18-c1 的零 release 差异是校准范围之外的例外，不能反过来否定 H3-0。
5. **不得把 §6.3 的 664 tokens/paired group 上界当成已观测效应。** 它是从 `need × 16` 与"下游复用深度未知"两个假设推出的 `[HYP]` 上界，必须在 Stage-0 完整轨迹 oracle 检验后才可引用。
6. **不得把 M6 外推到 "agent workload 没有可利用差异"。** 本轮几何是"2 sessions × 12 checkpoints × 单次受控压力（1–8 次 release 决策）× 自校准 TTL × 2048-block 池"，M6 只在这个几何内成立。
7. **不得用本轮结果主张 H2 的等价性。** `H2 = NOT_EVALUABLE`（0 < 8 个可判别决策），这是不可评估，不是"无效应"。
8. **frozen replay execution conformance 仍为 FAIL / deviation。** 本文件的分析建立在 actual-order audit 的 bounded paired-effect 解释之上，该解释不改变 conformance 状态。
9. **`downstream_recompute_attribution = NOT_ESTABLISHED`。** 本文所有"某次驱逐导致某次重算"的表述都是**链路级**推断（`matched_physical_blocks` + 逐请求 `E/C`），不是逐决策因果归因。
10. **不得把 `σ_run = 0` 表述为"整批没有噪声地板"。** 它只覆盖 5 Groups / 10 个 A0 cell / 30 run；不含 A1/A2/A3/E0，也不含其余 30 个 cell。g18-c1（零 release，A0−N0=−544）就是校准范围之外的 baseline 差异实例。
11. **不得把 Stage-0 oracle 定义成"逐决策取局部最优再求和"。** 选择会改变后续 protected 集合、候选集、Native eviction 与请求级 N/E/C；必须用完整轨迹重放，门控只看 `G_cell`/`G_group`，局部 `ΔR_i` 只能作诊断且必须标注非可加。
12. **不得用 H3-0/H3-R 的高值救活 primary gate。** primary 是 18 个 paired Groups；g09/g18 是事后加入且占 H3-0 的 44.7%，只能作敏感性。

---

## 12. 复现步骤

所有数字都可以在冻结 Archive 上重放，不需要 GPU。

### 12.0 一键复现

```bash
python scripts/probes/phase3_null_mechanism/probe.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      local/phase3-null-mechanism-probe
```

脚本只读，输出写到 `--out`，不触碰任何冻结输入。它一次性完成 §12.2–§12.8 的完整性、排序复算、驱逐对账与总体/噪声范围检查，并把结果写入 `null-mechanism-probe.json`。任一完整性/回归检查失败时脚本以非零退出，并打印 `FAIL_CLOSED`。实测输出（节选）：

```
== E_request_integrity ==
  request_rows: 5760
  observations: 3840
  comparisons: 3840
  mismatches: 0
  request_set_mismatches: 0
  e_mismatches: 0
  arithmetic_failures: 0

== F_a0_vs_n0 ==
  cells_with_difference: 20
  difference_always_last_request: 20
  sum_A0_minus_N0_tokens: -100352
  cells_with_difference_and_zero_decisions: ['g18-c1']
  h30_cells: 38
  h30_cells_with_difference: 18
  h30_cell_sum_tokens: -96992
  h30_group_sum_tokens: -62464.0
  h30_zero_groups: ['g06', 'g08', 'g11', 'g14', 'g17', 'g20']
  h30_top5_share_pct: 79.6
  h30_a0_group_mean_tokens: 40205.6
  all_a0_per_cell_mean_tokens: 39603.6
  h30_over_a0_pct: 7.8

== G_candidate_and_ordering ==
  decisions: 127
  decision_cells: 39
  candidates: 134
  candidate_count_distribution: {1: 120, 2: 7}
  suffix_blocks_vs_need: {'equal': 122, 'greater': 12}
  new_blocks_ge_need: 134
  step2_sufficient: 127
  a3_recompute_ok: 127
  a1_traces: 127
  a1_recompute_ok: 127
  a1_a3_same_program: 127
  a0_deadline_ok: 127
  e0_deadline_ok: 127
  same_program_all: 127
  q_monotone_decisions: 127

== H_eviction_accounting ==
  matched_physical_blocks_total: 14241
  predicted_victim_total: 12545
  predicted_physical_overlap_total: 12545
  predicted_victim_count_equals_need: 127/127
  matched_physical_blocks_equals_need: 108/127
  rows_where_physical_exceeds_need: 19
  predicted_equals_physical_true: 108/127
  required_blocks_eq_128: 108/127
  required_blocks_distribution: {36: 1, 40: 2, ..., 123: 2, 128: 108}

== I_population_and_noise ==
  primary_groups: 18
  primary_cells: 36
  h30_cells: 38
  h3r_groups: 9
  h3r_cells: 16
  noise_cells: 10
  noise_groups: 5
  noise_runs: 30
  noise_arms: ['a0']
  requests_after_last_release: {1: 16, 2: 23}

STATUS PASS
```

以下 §12.1–§12.8 是逐项手工步骤，用于核对该脚本本身。

### 12.1 数据位置

```
local/phase3-option-f-unified-270-runs-v2-evidence/
  phase3-option-f-unified-270-runs-v2/
    nec-cells/*.json           40 个 cell 的 N/E/C（含逐请求 records）
    native-runs/<run-id>/events.jsonl
    main-report.json  noise-report.json  pipeline-state.json
docs/experiments/phase3-algorithm-exposure-audit-data/
  decision-audit.csv  summary.json  group-condition-summary.csv
docs/experiments/phase3-actual-order-audit-data/summary.json
```

### 12.2 请求集合完整性与逐请求等价性（E4）

对每个 `nec-cells/*.json`：

1. 六个臂（A0/A1/A2/A3/E0/N0）各 24 个请求，`request_id` 唯一；六臂的 `request_id` 集合与顺序必须完全一致。全 archive 预期 40 cell × 6 臂 × 24 request = **5,760 行**。
2. 每个请求检查 `recomputed_tokens == eligible_prefix_tokens − native_cached_prefix_tokens`，且 `0 ≤ C ≤ E ≤ native_prompt_tokens`；cell 级 aggregate 必须等于逐请求求和。
3. 取 `arms[A0].requests` 与 `arms[arm].requests`，按 `request_id` 对齐，比较 `recomputed_tokens` 与 `eligible_prefix_tokens`。预期：40 cell × 24 request = 960 个观测，× 4 臂 = **3,840 次比较，不一致数 = 0**；六臂的 `E` 必须完全相同。

### 12.3 A0−N0 差异定位（E6）

对每个 cell 取 `A0.requests` 与 `N0.requests`，求 `recomputed_tokens` 不同的 `request_id` 集合。预期：20 个 cell 非空，且每个非空集合的元素个数恰为 1，且该元素是该 run 的最后一个请求；其中 19 个 cell 至少有 1 次 forced release，g18-c1 为 0 次 release（−544）。H3-0 内为 18/38 cell；H3-0 的 cell 未加权和 −96,992，group-value 和 −62,464。

### 12.4 竞争决策与排序独立复算（E15、E16）

对 `native-runs/*-a3/events.jsonl` 的 `A3_SUFFIX_RELEASE_DECISION`：

1. 取 `payload.selection_trace[0].audits`，读 `reuse_proxy`、`prefill_reload_seconds`、`chain_length`、`d_min`、`suffix_blocks`、`new_blocks`、`need`、`selected`、`deadline`、`score`。
2. 独立复算 `q = sigmoid((deadline − t)/τ)`（τ=30，t=事件 timestamp）、`L = q·prefill·S/m`，并验证 `selected == argmin (L, deadline, key)`；同时验证 `suffix_blocks == chain_length − d_min + 1`。
3. 独立复算 Step-2 判据：`sufficient = any(new_blocks >= need)`；在充分时分支必须是 `single_step`/`step2_sufficient`。不要用 `suffix_blocks` 代替 `new_blocks`。
4. 对全部 40 个 `-a3` run 统计：127 次决策、39 个 cell、134 个候选；`S = need` 122、`S > need` 12、`S < need` 0；`N >= need` 134/134；候选分布 `{1:120, 2:7}`。
5. 对 A1 的 `COST_AWARE_RELEASE_DECISION` trace（127 条；无 `decision_id`），按 `(cell, timestamp, program set)` 与 A3 决策一一匹配；独立复算 `expected = q·(min(need,N) + λ·(N − min(need,N)))`、`q` 与 `argmin (expected, deadline, key)`。
6. 对 A0/E0 用同一 A3 候选集的 deadline 序独立复算：A0 = `argmin(deadline, ...)`，E0 = `argmin(deadline, key)`；本样本 134 个候选 deadline 全部互不相等，因此 tie-break 不参与。

### 12.5 反事实上界（§6.3）

对 7 个竞争决策取 `need`，上界 = `Σ need × 16`。预期 `747 × 16 = 11,952` tokens。**这是上界，不是估计值**；精确值需要 §8.0 的完整轨迹 oracle，本轮未做。

### 12.6 驱逐量化与预测一致性（E12）

对 `decision-audit.csv` 中 `arm == "A3"` 的 127 行：

- `sum(matched_physical_blocks) = 14_241`；
- `predicted_victim_total = predicted_physical_overlap = 12_545`；
- `predicted_victim_count == need` → 127/127；
- `matched_physical_blocks == need` → **108/127**；其余 19 行 `matched = 128` 且 `need < 128`（目标侧量化过量）；
- `required_blocks` 分布：108/127 为 128，其余 19 行为 36–123；`required_blocks >= need` 127/127；
- `predicted_equals_physical == "True"` → 108/127；该标志与 `matched == need` 一致 127/127；
- `unmatched_physical_blocks == 0`、`hashless_physical_blocks == 0`、`downstream_recompute_attribution == NOT_ESTABLISHED`。

### 12.7 总体与 Group/Cell 口径

- archive：20 Groups × 2 conditions = 40 cells；每 cell 6 臂 × 24 requests。
- primary：18 paired Groups / 36 cells（g01–g08、g10–g17、g19、g20）。
- H3-0：20 Groups / 38 cells = primary 36 + g09-C2 + g18-C2；两 cell 组内 1/2，g09/g18 单 cell 权重 1。
- H3-R：9 Groups / 16 cells = 7 RESPONSIVE primary groups ×2 + g09-C2 + g18-C2。
- A3 决策：127 次 / 39 cells；g18-c1 为 0 次。
- 每 cell 决策数分布：`{1:3, 2:18, 3:4, 4:4, 5:6, 7:2, 8:2}`。

### 12.8 Noise Calibration 覆盖范围

`noise-report.json` 的 `cell_count = 10`、`run_count = 30`、`df = 20`、`σ_run = σ_delta = 0`；对应 5 个 Group（g01、g04、g06、g07、g10）× 2 conditions × 3 A0 repeats。脚本从 `logs/phase3-noise-*.log` 复核该集合，并明确报告"不含 A1/A2/A3/E0、不含其余 30 个 cell"。不得把这个结果写成全局噪声地板。

---

## 附录 A — 本轮从 Archive 新算出的、未写入冻结产物的量

| 量 | 值 | 等级 |
|---|---|---|
| 逐请求 A0↔{A1,A2,A3,E0} 不一致数（960 观测 × 4 臂 = 3,840 比较） | **0** | `[OBS]` |
| 请求行完整性 | **5,760 = 40 cell × 6 臂 × 24 request**；六臂 request 集合/顺序一致 | `[OBS]` |
| A0−N0 差异 cell 数 / 差异请求数 | **20 / 20**（每 cell 恰 1 个，且为最后一个请求；19 个 cell 有 release，g18-c1 为 0 release） | `[OBS]` |
| A0−N0 合计（40 cell 未加权求和） | **−100,352 tokens** | `[OBS]` |
| H3-0 cell 未加权和 / group-value 和 | **−96,992 / −62,464** | `[OBS]` |
| H3-0 A0 group mean | **40,205.6 tokens/group** | `[OBS]` |
| 40-cell A0 per-cell mean | **39,603.6 tokens/cell** | `[OBS]` |
| H3-0 / A0 group mean | **7.8%** | `[OBS]` |
| A3 决策 / 有决策 cell / 候选 | **127 / 39 / 134** | `[OBS]` |
| 单候选 / 双候选 | **120 / 7** | `[OBS]` |
| `matched_physical_blocks` 合计 / 每决策均值 | **14,241 / 112.1** | `[OBS]` |
| 竞争决策中 `need` | 97 / 97 / 127 / 127 / 101 / 101 / 97 | `[OBS]` |
| `predicted_victim_count == need` | **127 / 127** | `[OBS]` |
| `matched_physical_blocks == need` | **108 / 127**；其余 19 次 `matched = 128` | `[OBS]` |
| `required_blocks` | **108 次 = 128；19 次 = 36–123**；`required_blocks >= need` 127/127 | `[OBS]` |
| `predicted_equals_physical == True` / 与 `matched == need` 一致 | **108/127 / 127/127** | `[OBS]` |
| `predicted_victim_total = predicted_physical_overlap` | **12,545 = 12,545** | `[OBS]` |
| `S = need` / `S > need` / `S < need`（134 候选） | **122 / 12 / 0** | `[OBS]` |
| `N >= need`（134 候选） | **134 / 134** | `[OBS]` |
| 决策-每-cell 分布 | 1:3, 2:18, 3:4, 4:4, 5:6, 7:2, 8:2 | `[OBS]` |
| `need` 分布 | 127:52, 128:24, 其余 51 次 ≤115（min 4） | `[OBS]` |
| 整 cell 无竞争选择的 cell 数 | **32 / 39** | `[OBS]` |
| H3-0 前 5 group 份额 / 零 group 数 | **79.6% / 6** | `[OBS]` |
| 反事实上界 | **11,952 tokens（≈664/paired group）** | `[HYP]` |

## 附录 B — 本轮明确未做的事

- 未修改 Protocol v4、未修改冻结 Cohort/Seal、未修改原始 Archive、未修改历史结果、未修改 actual-order audit。
- 未启动 GPU、未做 smoke、未生成任何新的 run 配置。
- 未实现任何方案（P1/P2/P3 均停留在设计与判据层面）。
- 未修改 `src/kvopt/**`。
- 未把 oracle 上界当成已知事实 —— 它是 §8.0 的待做项。

本轮新增的代码是 `scripts/probes/phase3_null_mechanism/probe.py`（只读复算，写到 `--out`）和 `tests/test_phase3_null_mechanism_probe.py`（固定 `q` 单调方向与 Step-2 判据的单元测试）。两者都不进入 `src/`，不被任何生产路径 import，也不改变任何冻结产物。
