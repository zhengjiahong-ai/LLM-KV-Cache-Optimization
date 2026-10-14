# Phase 2D → Cost-Aware Method Opportunity Assessment

**提交人**：M4　**送审**：M1　**日期**：2026-10-14
**依据**：Phase 2D（PR #42，merge `2c375ce`，`ACCEPT_WITH_KNOWN_LIMITATIONS`）、Phase 2C、H1/H2 已封存证据
**性质**：离线方法机会分析。**未**实施策略、**未**运行实验、**未**改动仓库既有语义
**边界**：H1/H2 CLOSED、B1 LOCKED、Continuum baseline UNCHANGED、Cost-Aware policy NOT_AUTHORIZED、Formal campaign NOT_AUTHORIZED

---

## 0. 明确判断（对 M1 的最终问题）

> **Phase 2D 观察到的选择空间，是否可能通过决策时真实可获得的信号，被转化为有研究价值且可验证的 Cost-Aware Victim Selection 方法？**

**当前证据下的答案是：NO —— 且这个「NO」不是「还没找到信号」，而是 E3 这个 fixture 的自身设计使然。**

三条独立理由，任何一条都足以否定在本 fixture 上的可捕获性：

**理由一（聚合口径）**：fixture 在两臂中**均列出两个 `return_programs`**，只是顺序相反。
若二者确实均返回（fixture 的字面含义），则**无论释放哪一个 entry，恰好有一个 64-token 分支必须重算**
⇒ **聚合重算量不变（66）**，E3 的 `Δ = ±64` 是**单请求再分配**而非聚合节省。
⚠️ 该读法**须以原始 run 核对**（我无法独立验证，见 §3.2 与 §6 S0-a）；核对前不得把 64 视作可节省成本。

**理由二（决策时不可分）**：E3 的有效性 gate（D3）**要求**两臂的 decision signature **逐位相等**。
该签名涵盖 `required_blocks`、候选几何（含 `waiting_followup`）、以及**整个 free queue 的 `(native_lru_rank, has_block_hash)`**。
⇒ **决策时可观测状态在两臂间完全相同，而最优动作相反。**

**理由三（对称不确定性下期望增益为 0）**：两臂对称 ⇒ 任何确定性规则必在同一臂出错。
形式化：单请求增益 = `32 · (2p − 1)`，其中 `p` = 命中最优 released entry 的概率。
E3 中决策时状态相同 ⇒ `p = 1/2` ⇒ **增益 = 0**。

⚠️ **`64 tokens` 不是 Cost-Aware 方法已能节约的成本**（遵 M1 指示）。
它是 oracle 与 anti-oracle 的**差**；**可捕获部分为零**。

---

## 1. Phase 2D 支持与不支持什么

### 1.1 `[支持]`

| 结论 | 证据 |
| --- | --- |
| 原 Phase 2C 语料**无法**表达「同一决策时刻多个受保护 entry 共享同一 native block」 | E1 `OBSERVED_NO_SHARED_PROTECTED`：两个合法决策各只有 **1** 个候选 |
| 该状态**可以被构造** | E2 `PASS`：两个受保护 entry 共享 **8** 个真实 native block |
| 真实服务重叠可与该 fixture 共存 | E4 `TRUE_OVERLAP_DEMONSTRATED`：两臂均观察到正的 scheduler-to-completion overlap |
| **同一**共享结构下，不同 release 顺序**可**伴随不同**单请求**重算量 | E3 `HEADROOM_OBSERVED`，4/4 配对有效 |

### 1.2 `[不支持]`

| 主张 | 为何不支持 |
| --- | --- |
| 存在**聚合**层面可节省的重算成本 | §0 理由一：聚合量不变 |
| headroom **可在线预测** | §0 理由二/三：决策时状态对称 |
| headroom 源于 **retention-set-dependent 边际损失** | E2：两候选 `relief` **相等（均为 4）**，故 Δ 不能由释放容量差异解释 |
| 任何 Cost-Aware policy 优于 Continuum | M1 限制 6：未证明，也不得声称 |
| 效果可外推到真实工作负载 | M1 限制 4/5：4 次配对来自 2 个受控 target 条件，非 4 个独立 scenario draws；压力决策发生在并发请求完成**之后** |

---

## 2. Decision-Time Feature Inventory 与可观测边界

### 2.1 基线的完整决策时结构

`src/kvopt/continuum/selection.py::EligibilityPreparation`：

```text
required_blocks          : int                    压力目标
original_free_queue      : (block_id, native_lru_rank, has_block_hash, eligibility_tier)*
ordinary_expired_entries : (program_id, prefix_id)*
pressure_releases        : ((program_id, prefix_id), newly_eligible_block_ids)*  <- 合法候选
preparation_timestamp    : float
```

### 2.2 基线的排序键（关键）

`src/kvopt/continuum/pressure.py:324`：

```python
return (entry.deadline_timestamp, native_key, key.sort_key)
#        └ 决策时           └ min(native_lru_rank of newly_eligible)   └ (program_id, prefix_id)
```

⇒ **基线只用三样：deadline、newly-eligible 块的*最小* LRU 秩、逻辑身份。**

**这是本次分析最重要的机制发现**：基线通过 `_entries_by_block`（block → owning entries 的**共有多重度映射**）
计算**资格**（被其他受保护 entry 仍持有的块不可回收），但**从不把共有多重度或 relief 数量用于排序**。
即：结构信息**已可得、已被计算、但未被用于排序**。

### 2.3 特征清单（区分决策时 vs 未来结果）

| 特征 | 类别 | 决策时可得 | 在可用语料中的方差 |
| --- | --- | --- | --- |
| `retention_deadline_timestamp` | 决策时 | ✅ | H1：有；关联弱（ρ=+0.1376 raw pooled） |
| `native_lru_rank` | 决策时 | ✅ | 有（基线主键） |
| `required_blocks` | 决策时 | ✅ | 有 |
| `marginal relief = |newly_eligible_block_ids|` | 决策时 | ✅ | **H1: 0（471/471 ≡ block_count）；E2: 平局（4 vs 4）** |
| **共有多重度（block → #owners）** | 决策时 | ✅ | **H1: 恒为 1；E2: 可变（8 共享）** |
| 候选内容身份（hash） | 决策时 | ✅ | 有 —— 但需内容证据模式 |
| `waiting_followup` / `next_tool_type` | 决策时 | ✅ | 有 |
| `eta` / `queue_delay` | 决策时（名义） | ⚠️ 名义 | **H1 退化（恒 1.0 / 0.0，`F-HISTORY`）** |
| ⛔ `evaluation_program` | **未来（oracle）** | ❌ | — |
| ⛔ future return order | **未来（oracle）** | ❌ | — |
| ⛔ future APC outcome | **未来结果** | ❌ | — |
| ⛔ `observed_recomputed_tokens` | **未来结果（标签）** | ❌ | — |

### 2.4 E3 的 gate 签名 —— 可观测边界的形式化

`src/kvopt/profiling/phase2d_e3.py:23`：

```python
def _decision_signature(payload):
    return {
        "required_blocks": ...,
        "candidates": sorted((program_id,
                              len(block_ids),
                              len(initially_reclaimable_block_ids),
                              waiting_followup) for row in candidates),
        "free_queue": [(row.native_lru_rank, row.has_block_hash) for row in free_queue],
    }
```

`phase2d_e3.py:136`：**两臂签名不等即判 `COMPARABILITY_FAILED`。**

⇒ **该 fixture 通过 gate 强制「两臂决策时可观测状态相同」。** 这是实验有效性的前提，也正是可捕获性为零的原因。

⚠️ **精确边界**：签名**不含** `retention_deadline_timestamp`。
两臂重建了相同内容/容量/压力目标/候选集/free-queue 形状，故 deadline 亦应相等（**推断**，非 gate 认证）。
若 deadline 或任何非签名量在两臂间不等，则存在一个**未被 gate 覆盖的潜在信号** —— 这是 §6 Step 0 的核查项之一。

---

## 3. Headroom 与 Predictability 的区别 —— 核心分析

### 3.1 E3 的几何

E2/E3 fixture：共享根 128 tokens（**8 blocks**）+ 各自分支 64 tokens（**4 blocks**）。
每候选 12 blocks，**8 共享**，`relief = 4`（各自私有分支）。

⇒ 释放 A 的 entry：A 的 4 个私有块可回收；8 个共享块因 B 仍受保护而**驻留**。
⇒ 若 A 随后返回：A 的分支被毁 ⇒ 重算 **64+1 = 65**。
⇒ 若 B 随后返回且 A 已被释放：B 内容完好 ⇒ 重算 **1**。✔ 与 E3 表一致。

### 3.2 聚合口径的算术（关键警示）

fixture 的 `return_programs` 在两臂中**均含两个程序**，只是顺序相反。
故**两个程序都会返回**：

| 释放选择 | 返回 A 时 | 返回 B 时 | **聚合** |
| --- | ---: | ---: | ---: |
| 释放 A | 65 | 1 | **66** |
| 释放 B | 1 | 65 | **66** |

⇒ **聚合重算量与选择无关。** 选择改变的是**由哪个请求承担这 64 tokens**，不是总量。

**因此 E3 的 headroom 有两种读法，必须由 M1 明确：**

| 读法 | 含义 | 可捕获性 |
| --- | --- | --- |
| **(a) 单请求** | 被评估请求的重算量差 64 | 需预测；`p=1/2` ⇒ 增益 0 |
| **(b) 聚合** | 总重算量不变（66） | **无可捕获量** |

⚠️ 我**无法**独立验证 (a)/(b)，因为 E3 原始 run 归档在外部、未入库（M1 限制 3）。
两项读法的分辨是 §6 Step 0 的首要核查项。**在分辨之前，不得把 64 tokens 当作可节省成本。**

### 3.3 对称不确定性下期望增益的形式化

设 `p` = 规则选中所释放的「正确」entry（即最优 entry）的概率。
单请求期望重算 = `p·1 + (1−p)·65 = 65 − 64p`。
固定规则（恒选同一 entry）：`p = 1/2` ⇒ 33。
**增益 = 33 − (65 − 64p) = 32·(2p − 1)。**

| `p` | 增益（tokens/决策，单请求口径） |
| ---: | ---: |
| 0.50 | **0** |
| 0.60 | 6.4 |
| 0.75 | 16 |
| 1.00 | 32 |

⇒ **整个研究问题归结为：能否在决策时做到 `p > 1/2`？**
在 E3 fixture 中，决策时状态相同 ⇒ **`p ≡ 1/2`，增益恒为 0**。
⚠️ 常数 32 依赖分支规模（此处 64 tokens），但 `(2p−1)` 的形状是通用的。

### 3.4 为什么这不是「还没找到信号」

E3 **不是**「信号存在但我们没找到」，而是：**决策时状态被构造为对称，最优动作却被未来决定。**
更精确地，损失 = 「你释放的是否正是*将来那个请求所属*的 entry」。**归属关系属于未来事实。**

⇒ **任何仅由决策时可观测状态构成的函数，在本 fixture 上都不可能与最优动作一致。**
这不是观测局限，是**构造性不可能**。

---

## 4. 值得继续验证的假设（至多 2 个）

### HYP-D1 `[主推]` 结构不对称是否产生**聚合**headroom

```text
[假设] 在同一决策时刻，若候选的 release 后果存在决策时可观测的不对称
       （marginal relief 不等，或 released blocks 的共有多重度不等），
       则优先释放「实际可回收容量更大 / 破坏的共享覆盖更少」的 entry，
       可降低该决策点的聚合真实重计算量。
```

**与 E3 的关键差别**：E3 的两候选 `relief` **相等**（4 vs 4），故其 Δ 必然来自未来，而非结构。
HYP-D1 考察**结构不对称**是否本身就产生聚合效应 —— 这是**不需要预测未来**的唯一杠杆。

**可能的机制**：释放更多容量 ⇒ 后续压力更小 ⇒ 更少后续淘汰。
⚠️ 但需检查反面：释放更多容量往往同时**破坏更多内容**，二者可能抵消。

**这是唯一一个既（i）决策时可计算、（ii）不依赖未来预测、（iii）机制明确可证伪的候选。**

### HYP-D2 `[不推荐立即推进]` 未来返回的可预测性

即 M1 定义的 H1 问题，等价于既有 HYP-C。**不推荐立即推进**，理由：

- H1 已测：返回特征最强为 `next_tool_type=database`，ρ = **0.228**，族一致 0.833；
- F-D1（Issue #37）已测：共同子集组合**未获稳健增量**（decision-mean 0.6604 < 0.6675，by-draw 0.7128 > 0.6827，**口径不一致**）；
- H1 语料**无法**验证：`F-PREFIX` 未实现预期跨 program 共享，且每 run 只执行一条基线 ⇒ **无反事实值**。

⇒ 除非先取得**具备真实共享结构且带反事实的语料**，否则重复该方向只是重跑已知的弱结果。

---

## 5. 每个假设相对于 frozen Continuum baseline 的**真正机制差异**

基线键：`(deadline, min(native_lru_rank of newly_eligible), (program_id, prefix_id))`

| 维度 | 基线 | HYP-D1 | 是真差异吗 |
| --- | --- | --- | --- |
| 用共有多重度？ | **仅用于资格判定**（块被其他受保护 entry 持有 ⇒ 不可回收） | 用于**排序** | ✅ **真差异**：信息已计算但未用于排序 |
| 用 `relief` 数量排序？ | **不用**（只取 newly-eligible 块的最小 LRU 秩） | 用 | ✅ **真差异**（但见下） |
| 用 deadline？ | 用 | 可保留 | — |
| 用未来信息？ | 否 | 否 | — |
| 释放粒度 | 逐个 entry、前缀式（greedy 至满足目标） | 同 | — |

⚠️ **必须报告的去重事实**：仓库 `src/kvopt/costaware/rules.py` **已实现** relief/size 类规则：

```text
M1_reclaimable_ascending              (rule_id 已存在)
M1_marginal_cost_per_reclaimable      (rule_id 已存在)
M1_block_count_ascending / M1_prefill_reload_ascending / M2 / M3 ...
```

⇒ **「按 relief 排序」不是新假设**，它已实现、已在 H1 上评估、并因 `relief ≡ block_count`（471/471）
而与 size 规则**秩同构**（degeneracy）。
⇒ **HYP-D1 的候选资格只能来自「共有多重度排序 + 结构不对称」这一从未被表达的维度**，
不能来自重新包装既有规则。

据此回答 M1 的第三组问题：

| 问题 | 回答 |
| --- | --- |
| 存在 retention-set-dependent 真实边际损失？ | **未在可用语料中观测到**：H1 的 `relief ≡ block_count`（471/471），E2 两候选 relief 相等 |
| 候选间出现 baseline 未利用的可观测结构差异？ | **在 E2 中出现**：共有多重度（8 共享）——基线已计算却未用于排序。是否**因果关联损失**未知 |
| relief / 内容覆盖 ↔ 未来重算损失有可验证联系？ | **未建立**；且 §3.2 表明 E3 的 Δ 与 relief 无关（relief 相等） |
| 无新增预测信息时，重组既有排序键能否有实质贡献？ | **不能**。既有规则组合已在 H1/F-D1 上未获稳健增量；且基准键已含 LRU+deadline，重组空间受限 |

---

## 6. 最小验证方案

### Step 0 `[零新实验，离线，立即可执行]` —— **强烈建议先做**

**全部在既有持久化产物上运行，不需要 GPU、vLLM 或新 native run。**

| 核查 | 方法 | 判定 |
| --- | --- | --- |
| **S0-a 口径分辨**：E3 的 Δ 是单请求还是聚合？ | 对 E3 原始 run 逐事件核对两个 future 请求的 `observed_recomputed_tokens` 之和 | 若聚合不变 ⇒ **E3 无聚合 headroom，HYP-D1 成为唯一可能** |
| **S0-b 结构方差审计**：可用语料中 relief / 共有多重度是否有决策内方差？ | H1 derived（471 行）+ Phase 2D fixtures | 若无方差 ⇒ **结构杠杆在真实语料中不存在** |
| **S0-c 基线 vs oracle regret**：基线选择与 loss-最优可行集的距离 | 复用**既有** `src/kvopt/costaware/feasible_oracle.py` + `offline_eval.py`（纯离线，不加载模型） | 若 regret ≈ 0 于绝大多数决策 ⇒ **关闭主线** |
| **S0-d 非签名量核查**：E3 两臂的 deadline 等非签名量是否相等？ | 逐事件比对 | 若不等 ⇒ 存在未被 gate 覆盖的潜在信号（需另议） |

**资源需求**：纯 CPU，分钟级，复用既有离线设施。**无 native 实验。**

**停止条件（任一成立即建议关闭主线）**：
- S0-a 判定为聚合不变，且 S0-b 显示结构量无语料方差；
- S0-c 显示基线 regret 在绝大多数决策上≈0；
- S0-b 与 S0-c 同时表明既无可利用结构、基线又已近最优。

### Step 1 `[仅在 Step 0 显示结构杠杆存在时]` 结构不对称 fixture

**设计**：E2 的非对称变体 —— 分支长度不等（如 64 vs 128 tokens ⇒ relief 4 vs 8），
其余（共享根、容量、压力目标、free-queue 形状）保持相等。

| 项 | 值 |
| --- | --- |
| 性质 | 小规模、non-holdout、非 campaign |
| 规模 | 2 臂 × 2 重复 = **4 run**（与 E3 同量级） |
| 资源 | 单机 Metal，分钟级/run |
| 需否新插桩 | **否** —— E2/E3 已产出候选几何与 `newly_eligible_block_ids` |

**通过判据**：释放高-relief 与低-relief entry 之间出现**可重复的聚合重算量差异**。
**失败即证伪（停止条件）**：若聚合重算量相同，则结构不对称**不携带因果权重** ⇒ **HYP-D1 立即否决**，
且因 S0-a 已否定聚合 headroom，**建议关闭主线并记录为负结果**。

⚠️ Step 1 **不在本轮授权范围内**（需 M1 授权新的 native 实验）。

---

## 7. 是否建议进入下一阶段 preregistration

**不建议。**

理由：

1. **E3 的 headroom 在本 fixture 上可捕获量 = 0**（§0、§3.4）—— 不是「弱」，是构造性为零；
2. **唯一可能的新维度（共有多重度）在可用语料中的因果地位未建立**（§4 HYP-D1）；
3. **relief 类规则已实现且已退化**（§5），重组既有键不构成新假设；
4. **返回预测方向证据已弱**（H1 ρ=0.228；F-D1 无稳健增量）；
5. 依 G2，新假设须重新 preregister，而当前**尚无可 preregister 的、具备决策时可观测判据的假设**。

⛔ **建议的下一步不是 preregistration，而是 Step 0（离线、零 native 实验、分钟级）。**
只有在 Step 0 与 Step 1 均给出肯定信号后，preregistration 才具备实质依据。

---

## 8. 缺失的信号与研究障碍（明确报告）

依 M1 指示：**若信息不足以建立可预测性假设，应明确报告缺失信号，而非人为构造有效性结论。**
本节的报告是：**缺的不是「更多数据」，而是三类特定条件。**

| # | 缺失项 | 为何是阻塞 | 归属 |
| --- | --- | --- | --- |
| **M-1** | **未来的「归属」**：将来的请求属于哪个受保护 entry | 损失 = 释放的 entry 被未来请求所需。此关系属未来事实，决策时不可得 | 需要**真实的、非对称的、可预测的**访问模式；fixture 中被刻意排除 |
| **M-2** | **结构不对称的语料方差** | H1 `relief ≡ block_count`（471/471）；共有多重度恒为 1 ⇒ 结构杠杆无方差可测 | 需具备真实跨-program 共享的语料（`F-PREFIX` 修复后） |
| **M-3** | **反事实值** | H1 每 run 只执行一条基线 ⇒ 未选中候选无观测损失，故 headroom 不可估 | 需 opt-in 反事实重放（E3 已证明可行，但仅 2 目标条件） |
| **M-4** | **E3 口径未分辨** | 聚合 vs 单请求决定「是否真的有可捕获量」 | **可立即解决**（Step 0 的 S0-a） |
| **M-5** | **压力与并发的时序错位** | E4 的真实并发发生在压力决策**之前**，压力决策实际上是串行的（M1 限制 5） | 需压力决策发生在真实重叠期间 |

**综合**：M-1 是**根本障碍**，M-2/M-3 是**语料障碍**，M-4 是**可立即消除的解读障碍**，M-5 是**外推障碍**。

⇒ **在 M-1 与 M-2 同时未满足、M-4 未分辨之前，任何 Cost-Aware 可预测性假设都缺乏可检验的判据。**
这正是我不建议进入 preregistration 的实质原因。

---

## 9. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 基线排序键 `(deadline, min LRU of newly_eligible, identity)` | `src/kvopt/continuum/pressure.py:324` |
| 共有多重度映射 `_entries_by_block`，仅用于资格 | `src/kvopt/continuum/pressure.py`（`_entries_by_block`、`_eligible_block_ids`） |
| 决策时结构 `EligibilityPreparation` 字段 | `src/kvopt/continuum/selection.py` |
| D3 gate 签名定义与「签名不等即失败」 | `src/kvopt/profiling/phase2d_e3.py:23`、`:136` |
| E2 几何（共享根 128、分支 64、8 共享、relief 4） | `configs/phase2/phase2d-e2-shared-retention-fixture-v1.json`、`docs/phase2d-m6-headroom-investigation.md` |
| E3 fixture（`return_programs` 两臂均含两程序，顺序相反） | `configs/phase2/phase2d-e3-paired-headroom-fixture-v1.json` |
| E3 结果 65 / 1、Δ = ±64、4/4 有效 | `docs/phase2d-m6-headroom-investigation.md` |
| `observed_recomputed_tokens = native_prompt_tokens − native_cached_prefix_tokens` | 同上 |
| E4 overlap 0.433 s / 0.352 s，压力为 barrier | 同上 |
| 既有 relief/size 规则已实现 | `src/kvopt/costaware/rules.py`（`M1_reclaimable_ascending`、`M1_marginal_cost_per_reclaimable` 等） |
| 既有离线 oracle 与评估器 | `src/kvopt/costaware/feasible_oracle.py`、`offline_eval.py`（均不加载模型） |
| H1 `relief ≡ block_count` 471/471；候选共享 block_ids 0/114 | `local/probe_relief_field.py` |
| H1 返回特征最强 ρ = 0.228（`tool=database`，族一致 0.833） | H1 derived `signal_support.jsonl` |
| F-D1 共同子集 30 决策 / 7 draws；口径不一致 | `local/probe_fd1_subset_accounting.py`、`local/ISSUE_REPLY_37.md` |
| 冻结统计协议（draw / ≥30 / seed 20261007 / 2/3） | `docs/phase2a-m4-rule-acceptance-protocol.md` §1–§3 |
| M1 的 Phase 2D 限制 1–6 | Phase 2D 交接（PR #42 review） |

---

## 10. 请求的裁定

1. **确认裁决**：是否接受本评估对 E3 可捕获性的判断（**本 fixture 上可捕获量 = 0**）？
2. **口径裁定**：E3 的 `Δ = 64` 应以**单请求**还是**聚合**解读？（决定后续是否有可捕获量）
3. **Step 0 授权**：是否授权执行 §6 Step 0 的**离线**核查（零 native 实验、复用既有设施）？
4. **Step 1 是否授权**：若 Step 0 显示结构杠杆存在，是否授权 §6 Step 1 的 4-run 非对称 fixture？
5. **主线去留**：若 Step 0 判定既无结构杠杆、基线又近最优，是否同意**关闭 Cost-Aware 主线并记录为负结果**？

⛔ 本评估**不**请求：policy 实现、formal campaign、TTL estimator 变更、native cache 内部改动、
H1/H2 重开或改判、新观测缝的无界扩展。
