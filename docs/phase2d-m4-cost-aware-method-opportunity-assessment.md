# Phase 2D → Cost-Aware Method Opportunity Assessment

**提交人**：M4　**送审**：M1　**日期**：2026-10-14
**依据**：Phase 2D（PR #42，merge `2c375ce`，`ACCEPT_WITH_KNOWN_LIMITATIONS`）、Phase 2C、H1/H2 已封存证据
**性质**：离线方法机会分析 + Step 0 离线检查（M1 已授权）。**未**实施策略、**未**新增 native run、**未**改动仓库既有语义
**边界**：H1/H2 CLOSED、B1 LOCKED、Continuum baseline UNCHANGED、Cost-Aware policy NOT_AUTHORIZED、Formal campaign NOT_AUTHORIZED
**修订**：rev.2 —— 依 M1 PR #43 评审（`CHANGES_REQUESTED`）落实 RC1/RC2/RC3，并追加 §6 的 Step 0 结果；Step 1 NOT YET AUTHORIZED

---

## 0. 明确判断（对 M1 的最终问题）

> **Phase 2D 观察到的选择空间，是否可能通过决策时真实可获得的信号，被转化为有研究价值且可验证的 Cost-Aware Victim Selection 方法？**

**当前证据下的答案是：在本 fixture 所刻画的对称场景下不可捕获；一般结论未建立。**

⚠️ **rev.1 曾写成「构造性不可预测」「可捕获量严格为零」，该表述过强，现依 RC2/RC3 收窄。**
准确陈述分三层：

| 层 | 陈述 | 强度 |
| --- | --- | --- |
| **已实测** | 在 runtime 损失视图上，**执行基线在 27/27 个可评估决策上已达压力可行 oracle 最优**（regret ≡ 0），且**全部 8 条候选规则与基线逐位同选**（0 更好 / 0 更差 / 27 平） | **实测**（§6 S0-c） |
| **已构造** | E3 的两臂在**决策时可观测状态上完全相同**（gate 强制），而最优动作相反 ⇒ 在该对称场景内，`p = 1/2`、单请求期望增益为 0 | **构造性**（限该 fixture） |
| **未建立** | 「一般 Cost-Aware Victim Selection 不可预测」或「聚合 headroom 不存在」 | **不足以断言** |

**依赖三个前提**（缺一即不成立）：① 两个 future 目标**等概率**；② 决策时**不可区分**；③ 只考虑**单请求**指标。
⚠️ **受控 fixture 不代表真实 workload 的返回分布**：历史返回行为、上下文与工具类型仍可能提供预测信息（§4 HYP-D2）。

### 0.1 关于 E3 的 64 tokens

**前提已由代码证实**（`src/kvopt/workload/phase2d_e3_materialize.py:60`）：

```python
returns = tuple(str(value) for value in case["return_programs"])
if set(returns) != set(program_prefix_tokens) or len(returns) != 2:
    raise ValueError(...)
```

⇒ materializer **强制要求** `return_programs` 恰为 `{e3-a, e3-b}` 两元素 ⇒ **两臂中两个程序均返回**，仅顺序不同。
因此 `Δ = ±64` 是**单请求再分配**，而非已实测的聚合节省。

⚠️ **但仍不得把 64 视为可节省成本**：聚合量**尚未实测**（RC1）。且 D3 gate 只对 `evaluation_program`
计算单请求重算量 —— 第二个请求的原生重算量**从未被该 gate 读取**。
另需注意 `required_blocks = 12` 而单次释放仅带来 4 blocks 的 relief，
故后续释放轮次在两臂间是否不同**也会影响聚合**。⇒ **须实测，不得由推算替代**（见 §6 S0-a）。

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
| 存在**聚合**层面可节省的重算成本 | **尚未实测**（RC1）：D3 只读 `evaluation_program`；两请求均返回这一前提已由 §0.1 的代码证实，但聚合量需逐 run 汇总原生事件才能给出 |
| headroom 在本 fixture 的对称场景内**可在线预测** | §0 第二层：决策时可观测状态被 gate 强制相同，`p = 1/2` ⇒ 该场景内期望增益 0 |
| headroom 源于 **retention-set-dependent 边际损失** | E2：两候选 `relief` **相等（均为 4）**，故 Δ 不能由释放容量差异解释 |
| 任何 Cost-Aware policy 优于 Continuum | M1 限制 6：未证明，也不得声称 |
| 效果可外推到真实工作负载 | M1 限制 4/5：4 次配对来自 2 个受控 target 条件，非 4 个独立 scenario draws；压力决策发生在并发请求完成**之后** |
| 「一般 Cost-Aware Victim Selection 不可预测」 | **不足以断言**（RC3）：该结论需假设两个未来目标等概率且决策时不可区分，而受控 fixture 不代表真实返回分布 |

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

⚠️ **精确边界（依 RC2 修订）**：签名**不等于完整的决策时信息集**。它是**反事实可比性条件**，
不是在线不可预测性的证明：

1. 签名**不含** `retention_deadline_timestamp`；两臂重建了相同内容/容量/压力目标/候选集/free-queue 形状，
   故 deadline 亦应相等 —— 这是**推断，非 gate 认证**。
2. gate 只检查**同一 case 的两条干预臂**之间的签名相等，**未直接检查两个 future-target case 之间的完整状态等价性**。
3. 任何未被签名覆盖的量若在两臂间不等，都构成**未被排除的潜在在线信号**。

⇒ 正确表述是：**当前 fixture 未提供经过验证的在线区分信号**；
而不是「决策时信息在原理上不可能区分」。第 1、2 点的核查列入 §6 S0-d。

---

## 3. Headroom 与 Predictability 的区别 —— 核心分析

### 3.1 E3 的几何

E2/E3 fixture：共享根 128 tokens（**8 blocks**）+ 各自分支 64 tokens（**4 blocks**）。
每候选 12 blocks，**8 共享**，`relief = 4`（各自私有分支）。

⇒ 释放 A 的 entry：A 的 4 个私有块可回收；8 个共享块因 B 仍受保护而**驻留**。
⇒ 若 A 随后返回：A 的分支被毁 ⇒ 重算 **64+1 = 65**。
⇒ 若 B 随后返回且 A 已被释放：B 内容完好 ⇒ 重算 **1**。✔ 与 E3 表一致。

### 3.2 聚合口径的算术（关键警示）

**前提已由代码证实**（`phase2d_e3_materialize.py:60`，见 §0.1）：materializer 强制
`return_programs` 恰为 `{e3-a, e3-b}` ⇒ 两臂中**两程序均返回**，仅顺序不同。
下表数值是**推算**，不是实测（RC1）：

| 释放选择 | 返回 A 时 | 返回 B 时 | **推算聚合** |
| --- | ---: | ---: | ---: |
| 释放 A | 65 | 1 | **66**（推算） |
| 释放 B | 1 | 65 | **66**（推算） |

⇒ 若该推算成立，则选择只改变**由哪个请求承担**这 64 tokens。

⚠️ **推算的已知薄弱点**：`required_blocks = 12` 而单次释放只带来 **4** blocks 的 relief
⇒ 压力循环需**多轮释放**；两臂的**后续释放集合是否相同**未经验证。
若不同，聚合量**可能不相等**。因此**必须实测**，不得以推算替代（§6 S0-a）。

**因此 E3 的 headroom 有两种读法，必须由 M1 明确：**

| 读法 | 含义 | 可捕获性 |
| --- | --- | --- |
| **(a) 单请求** | 被评估请求的重算量差 64 | 需预测；`p=1/2` ⇒ 增益 0 |
| **(b) 聚合** | 总量是否随选择变化 | **尚未实测**；若不变则无递增空间 |

⚠️ E3 原始 run 归档在外部、未入库（M1 限制 3）⇒ **我无法完成 (b) 的实测**。
**在实测之前，不得把 64 tokens 当作可节省成本。**

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
在本 fixture 的对称场景内，决策时状态相同 ⇒ **`p = 1/2`，增益为 0**。
⚠️ 常数 32 依赖分支规模（此处 64 tokens），但 `(2p−1)` 的形状是通用的。
⚠️ **`p = 1/2` 是条件结论（RC3）**：它需要假设两个 future 目标**等概率**且决策时**不可区分**。
本 fixture 通过对称构造**恰好满足**这两个前提 —— 但那是**实验为了暴露 headroom 而刻意控制的**，
**不代表真实 workload 的返回分布**。在真实负载中，历史返回行为、上下文与工具类型都可能使 `p ≠ 1/2`
（§4 HYP-D2；H1 实测最强返回特征 ρ = 0.228，虽弱但非零）。

### 3.4 该 fixture 的可捕获性（依 RC2 收窄）

⚠️ **rev.1 曾写「构造性不可预测」「任何决策时函数都必与最优动作不一致」，该表述过强，现予撤回。**

准确的陈述是三层，强度递减：

**(a) 已实测（最强）**：在 runtime 损失视图上，**执行基线在 27/27 个可评估决策上已达压力可行 oracle 最优**，
且 8 条候选规则**全部与基线逐位同选**（§6 S0-c，已与 M6 冻结数字交叉验证）。
⇒ 在**该视图 + 该语料**上，**没有观察到任何规则能够改进**。

**(b) 已构造**：在本 fixture 内，决策时可观测状态被 gate 强制相同（就签名涵盖的量而言），
而最优动作相反 ⇒ 在该**对称场景**内 `p = 1/2`、单请求期望增益为 0。

**(c) 未建立**：「一般 Cost-Aware Victim Selection 不可在线预测」**不成立**。理由：
- ① 签名不等于完整决策时信息集（§2.4）；
- ② 对称性是**实验构造**的产物，不是真实分布；
- ③ `p = 1/2` 需等概率 + 不可区分两个假设，真实负载不保证；
- ④ 单请求口径本身是一个**读法选择**（§3.2），聚合口径尚未实测。

**损失机制陈述（保留）**：单请求口径下，损失 = 「你释放的是否正是*将来那个请求所属*的 entry」，
而该**归属关系属未来事实**。这解释了 E3 为何能产生 headroom，**但不构成对一般方法的否证**。

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

## 6. Step 0 结果（M1 已授权，已完成）

**执行方式**：全部复用**既有数据 + 既有离线代码**。未新增 native run，未实施策略。
主工具为仓库自带、免 GPU/vLLM 的离线评估器：

```powershell
$env:PYTHONPATH="src"
python -m kvopt.costaware.cli `
  --artifact-root local\phase2a-h1-level-a-evidence-e3a02fd\artifacts\phase2a-h1-formal-level-a-runs-v1 `
  --loss-view <loss_view> --output <report.json>
```

使用的 H1 原始 run（含 `events.jsonl`）与 `src/kvopt/costaware/{feasible_oracle,offline_eval}.py`
均在仓库/本地可用。两个损失视图各产出一份报告；对照脚本为 `local/probe_s0c_loss_views.py`。

### S0-c `[已完成，主结果]` 基线与可行性感知 oracle 的距离 —— **损失视图依赖性**

| 损失视图 | 决策数 | 基线 meanAbs regret | zero-regret rate | 正 regret 决策 | canonical misselection | 候选规则 vs 基线（更好/更差/平） |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `observed_recomputed_tokens`（**运行时**） | **27** | **0.0** | **1.0** | **0** | **0.0** | 8 条规则**全部 0 / 0 / 27** |
| `planned_return_weighted_prefill_proxy`（代理） | 114 | 0.031560 | 0.5526 | 51 | **0.4074** | 例：`M1_prefill_reload_ascending` 39 / 15 / 60；`M1_marginal_cost_per_reclaimable` **6 / 45 / 63**（净负面） |

**交叉验证**：我的独立重跑**逐位复现**了 M6 冻结的 `regret_summary.jsonl`
（proxy 视图 misselection `0.4074074074074074`；runtime 视图 `0.0`）⇒ 该重跑可信。

**解读 —— 必须分开的四个量（对应 M1 的目标）**：

1. **单请求 headroom 存在**：E3 已实测 `Δ = ±64`（§3.1）。
2. **真实聚合成本差异**：**未实测**（§6 S0-a 阻塞）。
3. **runtime 视图上基线已达压力可行 oracle 最优**：27/27 decisions regret ≡ 0，
   且**没有任何候选规则能够不同** ⇒ 在该视图 + 该语料上**无可改进空间**。
4. **proxy 视图上基线并非最优**：40.7% 误选，规则可 39 好 / 15 差。
   ⇒ **「有无 headroom」强烈依赖损失视图的选择。**

⚠️ **适用范围限制（遵 M1 的 loss-view 适用范围要求）**：
runtime 视图仅覆盖 **27** 个可评估决策（vs proxy 的 114）；
两视图测量边界不同（规划代理 vs 实测重计算），**不可互换**；
本结果为 **H1 语料**结论，**不得**据此外推到新的共享结构 workload（RC3 明确）。

### S0-b `[已完成]` 结构量的语料方差审计

| 结构量 | H1 实测 | 结论 |
| --- | --- | --- |
| `relief`（= `initially_reclaimable_block_count`） | **471/471 与 `block_count` 完全相等**；0 行真子集 | **基线聚合量恒等于块数，无方差** |
| 候选间共享 block（共有多重度 > 1） | **0 / 114 多候选决策** | **共有多重度恒为 1，无方差** |

⇒ 在 H1 中**两个候选结构量都没有决策内方差**，故结构杠杆在 H1 上**不可检验**。

⚠️ 但 Phase 2D E2 fixture **是反例**：该处共享确实存在（**8** blocks），
然而两候选 `relief` **相等（4 vs 4）** ⇒ 变化的量是**共有多重度**，不是 relief。
这与 §4 HYP-D1 的候选资格判断一致（只能来自共有多重度，不能来自 relief）。

### S0-a `[未完成 —— 数据缺失]` E3 的聚合重算成本

**阻塞原因**：Phase 2D v2 原始 run（`events.jsonl` / `gate-d3-v2.json` / `execution-summary.json`）
**既不在仓库、也不在本地工作区**（交接记录称其在外部归档，且 M1 限制 3 载明「尚未完成独立逐事件复核」）。
本地仅有 H1/H2 语料。⇒ **我无法逐 run 汇总两个返回请求的原生重算量。**

**已能确定的部分**（代码分析，非实测）：

- §0.1 已由 `phase2d_e3_materialize.py:60` **证实两程序均返回** ⇒ 讨论聚合是有意义的；
- 但 `required_blocks = 12` 与单次释放 **4 blocks** 的差距 ⇒ 压力循环需**多轮释放**，
  两臂**后续释放集合是否相同未知** ⇒ 聚合量**不能由推算确定**。

**所需**：Phase 2D v2 原始归档的读取权限，或由 M1/M6 提供逐 run 的两请求原生重算量汇总。
**在取得之前 S0-a 保持未完成，§3.2 的聚合读法保持「未实测」。**

### S0-d `[未完成 —— 同一数据阻塞]` 两 future-target case 的完整决策时等价性

**阻塞原因**：同上，需 Phase 2D 原始事件。

**已能确定的边界**（代码分析）：gate 签名**不含** `retention_deadline_timestamp`；
且 D3 只检查**同一 case 的两条干预臂**之间的签名相等，
**未检查两个 future-target case 之间的完整状态等价性**。
⇒ 这两项**仍属未验证**，不能表述为「已证明决策时信息相同」。

### Step 1 `[NOT YET AUTHORIZED]` 结构不对称 fixture

**设计**：E2 的非对称变体 —— 分支长度不等（如 64 vs 128 tokens ⇒ relief 4 vs 8），
其余（共享根、容量、压力目标、free-queue 形状、**共有多重度**）保持相等。

| 项 | 值 |
| --- | --- |
| 性质 | 小规模、non-holdout、非 campaign |
| 规模 | 2 臂 × 2 重复 = **4 run**（与 E3 同量级） |
| 资源 | 单机 Metal，分钟级/run |
| 需否新插桩 | **否** —— E2/E3 已产出候选几何与 `newly_eligible_block_ids` |

**通过判据**：释放高-relief 与低-relief entry 之间出现**可重复的聚合重算量差异**。
**失败即停止条件**：若聚合重算量相同 ⇒ 结构不对称**不携带因果权重** ⇒ **HYP-D1 被否**。
⚠️ 依 RC3，该否证**只关闭 HYP-D1 这一具体假设**，**不自动关闭整个 Cost-Aware 研究方向**。

---

## 7. 是否建议进入下一阶段 preregistration

**不建议 —— 但范围仅限于当前假设集，不构成对整个研究方向的关闭。**

依 RC3 修订，结论的**作用域**如下：

| 措辞 | 强度 |
| --- | --- |
| ~~「建议关闭 Cost-Aware 主线」~~ | **已撤回**（RC3） |
| **建议**：不对当前 8 条已评估规则 + HYP-D2 的现有形态 preregister | 有实测支撑（§6 S0-c proxy 视图无稳健增量；H1/F-D1 已测） |
| **建议**：HYP-D1 在其结构前提未被实测前不 preregister | 前置未建立（§6 S0-a / S0-b） |
| **不主张**：一般 Cost-Aware Victim Selection 无研究价值 | 证据不足（§3.4(c)） |

理由：

1. **当前假设集无实测增量**：S0-c 显示 proxy 视图上净负面或不可泛化（§6），
   且 runtime 视图上**基线已达 oracle 最优** ⇒ 现有规则集内未观察到改进空间；
2. **HYP-D1 的结构前提未实测**：S0-b 显示 H1 无语料方差；S0-a 阻塞于数据缺失；
3. **relief 类规则已实现且已退化**（§5），重组既有键不构成新假设；
4. 依 G2，新假设须重新 preregister，而当前**尚无可 preregister 的、具备决策时可观测判据的假设**。

⛔ **建议的下一步**：先解除 S0-a / S0-d 的数据阻塞（需 Phase 2D v2 原始归档访问），
再判断是否存在值得检验的结构差异。**Step 1 在 S0 未完成前不推进。**

---

## 8. 缺失的信号与研究障碍（明确报告）

依 M1 指示：**若信息不足以建立可预测性假设，应明确报告缺失信号，而非人为构造有效性结论。**

⚠️ **rev.2 更新：M-2、M-4 已在本轮 Step 0 中部分解决；M-1 仍是根本障碍。**

| # | 缺失项 | 状态（rev.2） | 归属 |
| --- | --- | --- | --- |
| **M-1** | **未来的「归属」**：将来的请求属于哪个受保护 entry | **仍缺失**。损失 = 释放的 entry 被未来请求所需；该关系属未来事实 | 需**真实的、非对称的、可预测的**访问模式；fixture 中被刻意排除 |
| **M-2** | **结构不对称的语料方差** | **已实测：H1 两边都无语料方差**（§6 S0-b：`relief ≡ block_count` 471/471、共有多重度恒为 1）。但 Phase 2D E2 是反例（共有多重度 8），该处 relief 却相等 | 需**同时**具备「共享结构」与「不对称 relief」的语料 |
| **M-3** | **反事实值** | **仍缺失**。H1 每 run 只执行一条基线 ⇒ 未选中候选无观测损失 | 需 opt-in 反事实重放（E3 已证可行，但仅 2 目标条件） |
| **M-4** | **E3 口径未分辨** | **部分解决**：单请求口径已实测（§3.1）；**聚合口径仍未实测**（§6 S0-a 阻塞于原始归档不可得） | 需 Phase 2D v2 原始归档读取权限 |
| **M-5** | **压力与并发的时序错位** | **仍缺失**。E4 的真实并发发生在压力决策**之前**（M1 限制 5） | 需压力决策发生在真实重叠期间 |
| **M-6** | **损失视图的选择本身是未冻结的自由度** | **本轮新增（§6 S0-c）**：runtime 视图下基线 27/27 达 oracle 最优且无规则可不同；proxy 视图下基线 40.7% 误选、规则可 39 好 / 15 差 | 需 M1 裁定**以哪个视图为正式判据** |

**综合**：
M-1 是**根本障碍**；M-2/M-3 是**语料障碍**（M-2 已确认 H1 不表达）；
M-4 是**可消除的解读障碍但受数据可得性阻塞**；M-5 是**外推障碍**；
**M-6 是本轮新发现，且它可能决定了「有无 headroom」的答案本身**。

⇒ 在 M-1、M-3、M-5 未满足，M-4 未实测，且 **M-6 未经 M1 裁定**之前，
任何 Cost-Aware 可预测性假设都**缺乏公认的可检验判据**。
这是不建议对当前假设集 preregister 的实质原因。

---

## 9. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 基线排序键 `(deadline, min LRU of newly_eligible, identity)` | `src/kvopt/continuum/pressure.py:324` |
| 共有多重度映射 `_entries_by_block`，仅用于资格 | `src/kvopt/continuum/pressure.py`（`_entries_by_block`、`_eligible_block_ids`） |
| 决策时结构 `EligibilityPreparation` 字段 | `src/kvopt/continuum/selection.py` |
| D3 gate 签名定义与「签名不等即失败」 | `src/kvopt/profiling/phase2d_e3.py:23`、`:136` |
| E2 几何（共享根 128、分支 64、8 共享、relief 4） | `configs/phase2/phase2d-e2-shared-retention-fixture-v1.json`、`docs/phase2d-m6-headroom-investigation.md` |
| **E3 两臂均含两 `return_programs`（materializer 强制）** | `src/kvopt/workload/phase2d_e3_materialize.py:60` |
| E3 fixture | `configs/phase2/phase2d-e3-paired-headroom-fixture-v1.json` |
| E3 结果 65 / 1、Δ = ±64、4/4 有效 | `docs/phase2d-m6-headroom-investigation.md` |
| `observed_recomputed_tokens = native_prompt_tokens − native_cached_prefix_tokens` | 同上 |
| E4 overlap 0.433 s / 0.352 s，压力为 barrier | 同上 |
| 既有 relief/size 规则已实现 | `src/kvopt/costaware/rules.py`（`M1_reclaimable_ascending`、`M1_marginal_cost_per_reclaimable` 等） |
| 既有离线 oracle 与评估器 | `src/kvopt/costaware/feasible_oracle.py`、`offline_eval.py`（均不加载模型） |
| **S0-c 两视图 regret 表（本报告运行）** | `python -m kvopt.costaware.cli --loss-view <view>`；报告 `local/h1_proxy_view.json`、`local/h1_runtime_view.json`；对照脚本 `local/probe_s0c_loss_views.py` |
| **S0-c 与 M6 冻结数字交叉验证** | H1 derived `regret_summary.jsonl`（proxy `0.4074074074074074`；runtime `0.0`） |
| S0-b `relief ≡ block_count` 471/471；共有多重度 0/114 | `local/probe_relief_field.py` |
| H1 返回特征最强 ρ = 0.228（`tool=database`，族一致 0.833） | H1 derived `signal_support.jsonl` |
| F-D1 共同子集 30 决策 / 7 draws；口径不一致 | `local/probe_fd1_subset_accounting.py`、`local/ISSUE_REPLY_37.md` |
| 冻结统计协议（draw / ≥30 / seed 20261007 / 2/3） | `docs/phase2a-m4-rule-acceptance-protocol.md` §1–§3 |
| M1 的 Phase 2D 限制 1–6 与 RC1–RC3 | Phase 2D 交接与 PR #43 评审 |

---

## 10. 请求的裁定

**Step 0 已完成**（§6）。以下为修订后的请求：

1. **M-6 裁定（最重要）**：正式判据应采用**哪个损失视图** —— `observed_recomputed_tokens` 还是
   `planned_return_weighted_prefill_proxy`？本轮的实测差异是**判据级的**：
   前者下基线 27/27 达 oracle 最优、无规则可改进；后者下基线 40.7% 误选、规则可 39 好 / 15 差。
2. **数据放行**：是否提供 **Phase 2D v2 原始归档**的读取权限，以解除 S0-a（聚合成本）与
   S0-d（两 target case 的完整决策时等价性）的阻塞？
3. **确认 RC2/RC3 修订**：是否接受把 rev.1 的「构造性不可预测」「可捕获量严格为零」
   收窄为「当前 fixture 未提供经过验证的在线区分信号」，并撤回「关闭主线」的措辞？
4. **Step 1 是否授权**：若 S0-a 实测显示聚合量**真的随选择变化**，是否授权 §6 的 4-run 非对称 fixture？
5. **当前假设集的处置**：是否同意**不对当前 8 条已评估规则 + HYP-D2 的现有形态 preregister**？
   ⚠️ 依 RC3，这**不等于**关闭 Cost-Aware 研究方向。

⛔ 本评估**不**请求：policy 实现、formal campaign、TTL estimator 变更、native cache 内部改动、
H1/H2 重开或改判、新观测缝的无界扩展。
