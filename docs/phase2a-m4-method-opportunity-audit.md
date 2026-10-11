# Phase 2A M4 — Method Opportunity Audit

Status: **AUDIT ONLY — no method proposed, no campaign requested, no implementation authorized**
Author: M4
Date: 2026-10-11 (**rev.3** — M1 review point revisions; rev.2 revised against the released bundles)
Baseline: `origin/main` @ `9a0cdff`
Corpora: H1 Level-A bundle `phase2a-h1-level-a-evidence-e3a02fd`; H2 bundle `phase2a-h2-final-evidence-c34a172`

> **rev.2 说明**：rev.1 在拿到 H1/H2 原始证据包之前写成，其**首选假设（HYP-A）未被数据支持**。
> 本文档保留否证过程，因为它本身是本阶段最有价值的产物之一：它证明前置可证伪性检查可以在
> **不跑任何 campaign** 的前提下淘汰一个方向。
>
> **rev.3 说明（M1 PR review，REQUEST CHANGES，文档级定点修订）**：
> 1. 收紧 HYP-A 的否定范围 —— 只否 **raw `C(r)/relief`** 这一形态，**不外推**至整个 cost-aware 主线（§2.3、§3.1、§5.1）
> 2. **撤回前版一条错误主张** —— `16 tokens/block` 是容量换算，**不是**每块实际重算成本（§2.2、§3.1、§5.1）
> 3. 下调 cross-entry 重叠的证据等级，标为**未验证假设**，并补上候选间 block-ID 无重叠的实测（§4.1、§4.4、§5.2）
> 4. 不再把关联写成确定机制；正式判级仍以冻结 paired evaluation 为准（§2.5、§2.8、§3.3）
> 另：跨语料对照已统一到 scenario-draw 口径（§3.2）。

---

## 0. 范围与约束

回答 M1 的核心问题：

> 已有证据证明了哪些 decision-time 信息具有意义？这些信息是否可能在**多 entry 竞争**条件下带来相对 Continuum baseline 的增量收益？

| 项 | 保持不变 |
| --- | --- |
| 研究主线 | Cost-Aware KV Cache **Eviction / Victim Selection** |
| 决策粒度 | **logical retention entry** |
| 不重定位为 | TTL estimator / scheduler / physical block-level eviction |
| 不提出 | 完整算法、评分公式冻结、工程实现 |
| 不请求 | 新的 formal campaign、新的观测缝 |

**分类纪律**：每条陈述标注 `[事实]` / `[推断]` / `[假设]`。`[假设]` / `[推断]` 一律不是结论；
正式判级一律以冻结 acceptance protocol 的 paired evaluation 为准。

---

## 1. 数据基础

| 语料 | 规模 | 用于本审计的用途 |
| --- | --- | --- |
| **H1 Level-A derived** | 471 candidate rows / 120 decisions / 1884 loss rows | 特征结构与损失分解 |
| **H2 M1 outcome** | 17 个 r 点 × 9 次重复的 native isolated 曲线 | 真实 $C(r)$ 形状 |
| Discovery corpus（M6 v5） | 54 runs / 60 decisions | 弱先验，已被 §3.2 降级 |

**复核方法（可复现）**：本文档每个数字由 `local/probe_h1_*.py`、`local/probe_h2_*.py` 计算，均为**描述性统计** —— 不评估任何规则、不产出任何验收指标。读取语料做**特征刻画**与「用该语料检验假设」是两件事；本审计只做前者。

---

## 2. 决定性结构事实

### 2.1 `[事实]` canonical loss 的确切形式

`src/kvopt/profiling/loss_views.py::_return_weighted_prefill_evidence`：

```python
loss = candidate.prefill_reload_seconds if returned_within_horizon else 0.0
```

⇒ **`loss = I[在 horizon 内返回] × C(prefix 长度)`**。经 H1 数据直接验证：proxy 视图中每个 `block_count` 下 loss ∈ `{0, C(r)}` 两个值，无第三值。

### 2.2 `[事实]` 决策时成本特征在决策内严格有序，且 `relief` 与 `block_count` 等价

H1 的 471 行候选数据：

| 关系 | 结果 |
| --- | --- |
| `initially_reclaimable_block_count == block_count` | **471/471（100%）** |
| `initially_reclaimable_block_ids` 是 `block_ids` 的真子集 | **0/471**（从不） |
| 决策内 `spearman(block_count, prefill_reload_seconds)` | **+1.0000，99/99 决策精确为 1** |
| 固定 `block_count` 下 relief 是否变化 | **完全不变化** |

⇒ **决策时成本特征（`prefill_reload_seconds`，取自 profile 表）在决策内是 `block_count` 的确定函数。**

⚠️ **三个量必须分开（M1 review item 2 的修订）**：

| 量 | 含义 | 来源 | 在本语料中的性质 |
| --- | --- | --- | --- |
| **A. reclaimable blocks** | 释放一个 entry 后立即可回收的块数 | `initially_reclaimable_block_count` | ≡ `block_count`（471/471） |
| **B. prefix length (tokens)** | 该 entry 前缀的 token 长度 | `block_count × 16` | 物理容量换算，**不是成本** |
| **C. observed recomputed tokens** | 实际发生的重算量 | `observed_recomputed_tokens` | **159/207 等于 B，48/207 小于 B** |

⇒ A 与 B 的关系是确定的（16 tokens/block 是容量换算）；**B 与 C 的关系不是**。
下方 §2.7 给出 C 的实测分布。

### 2.3 `[事实]` 在本语料中，raw `C(r)/relief` 退化为尺寸的单变量函数

因为 `relief ≡ block_count`（100%），而决策时成本特征在决策内是 `block_count` 的严格单调函数，所以

```text
决策时成本特征 / relief = C(block_count) / block_count
```

**是 `block_count` 的单变量函数**，在本语料中不可能携带成本与容量之外的第二个信号。

⚠️ **该事实的适用范围（M1 review item 1 的修订）**：

本结论只说明

```text
使用 raw C(r) / reclaimable 作为分子分母的策略，在本语料中退化
```

**它不足以否定所有 *expected loss / marginal reclaimable capacity* 类策略。** 若分子含有决策时可获得的返回概率，
即形如 `P(return|x) · C(r)`，则即使 `relief` 与尺寸等价，该比值也**未必**退化为尺寸排序 —— 因为
`P(return|x)` 本身随 entry 变化，而它在决策内**不是** `block_count` 的确定函数（§2.5、§2.8）。

### 2.4 `[事实]` 真实 native $C(r)$ 的形状

H2 M1，17 个 r 点，每点 9 次重复（取 median）：

| 区间 | `C/r` 行为 |
| --- | --- |
| r = 16 → 1024 | **单调下降**，1220.5e-6 → 90.5e-6 |
| r = 1024 | **最小值**（90.5e-6） |
| r = 2048 → 30720 | **单调上升**，100.5e-6 → 295.1e-6 |
| 全域离散度 | **13.49×** |

⇒ 真实的「每 token 平均成本」是一条**单起伏的 U 形曲线**，最低点在 **r ≈ 1024**。这比「二次非线性」更具体，且**在 16–1024 区间是单调的**。

### 2.5 `[事实]` baseline 的主键与损失的关联很弱

**直接计数（无任何统计假设）：** 在 75 个可判别决策中，按 deadline 能否分开「返回 vs 不返回」的候选：

```text
返回候选 deadline 更晚 : 37
返回候选 deadline 更早 : 38
```

⇒ **该计数不显示 deadline 与返回行为有稳定的方向性关联。**

**相关系数（我独立复算的 raw pooled Spearman，与 proxy loss / runtime loss）：**

| 关系 | ρ | n |
| --- | ---: | ---: |
| `retention_deadline_timestamp` ↔ proxy loss | **+0.1376** | 471 |
| `retention_deadline_timestamp` ↔ runtime loss | **−0.0178** | 207 |
| `block_count` ↔ proxy loss | +0.5207 | 471 |
| `block_count` ↔ runtime loss | +0.5794 | 207 |

⚠️ **口径说明（重要）**：M6 的 `signal_support.jsonl` 报告的是**另一套统计量**，数值不同
（deadline/proxy 为 +0.0585，block_count/proxy 为 0.5999，block_count/runtime 为 1.0000）。
读实现 `src/kvopt/profiling/signals.py` 得出的口径是：**决策内平均秩归一化到 [0,1] 后 pooled 求 Pearson**，
并丢弃损失恒定的决策与含缺失特征的决策。我按此重建，**7 项中有 2 项精确吻合**（deadline 在 proxy 视图的
两个方向），其余落在同一区间但不逐位一致 —— 说明 M6 还含了额外的分组/样本过滤（其 runtime 视图仅
`evaluable_family_count = 4`）。

⇒ 本审计**不声称复现** M6 的统计量。两种口径在**符号与相对大小上一致**：
`block_count` 关联较强，`deadline` 关联接近零。你引用时应标明是哪个口径。

**与 H1-R1 结果的一致性（M1 review item 4 的修订）**：现有证据表明 deadline 与代理损失的关联很弱，
这与 H1-R1 在冻结 paired evaluation 上未获得支持的结果**一致**。

⚠️ 但**不可写成因果结论**：「某特征关联弱 ⇒ 反转它必定无收益」超出该证据能支持的范围。
正式判级只以冻结 acceptance protocol 的 paired evaluation 为准（H1-R1 的正式 verdict 是 `DIAGNOSTIC_ONLY`，
而非 `NOT_ACCEPTED`）。

### 2.6 `[事实]` 损失离散度的来源分解

H1，120 个决策：

| 来源 | 决策数 | 占比 |
| --- | ---: | ---: |
| 仅成本变化（返回因子恒定） | 39 | 32.5% |
| 仅返回因子变化（成本恒定） | 21 | 17.5% |
| 两者都变 | 54 | 45.0% |
| 损失恒定 | 6 | 5.0% |

返回因子在 **75/120（62.5%）** 决策中具有判别力。

### 2.7 `[事实]` runtime 视图存在**部分重计算**，且每块实际重算量**并不恒定**

`observed_recomputed_tokens` 视图下 `loss == 16 × block_count` 仅 **159/207（76.8%）** 成立。
48 行（23.2%）中 loss **小于** prefix 全长，例如 `block_count=24` 时 loss 可为 48（全长为 384）。

且**同一 `block_count` 可对应多个 loss**：`block_count=16` → `{32, 48, 64, 80, 96, 256}`。

⇒ 实际重算量**不是**前缀长度的确定函数；存在**部分命中**（与 H2-M2 PASS 一致）。

**每 reclaimable block 的实际重算量（M1 review item 2 的修订依据）：**

```text
distinct values : 12
范围         : 0.6667 – 16.0000
离散度         : 24.00×
```

⇒ **每释放一个 block 的实际重算成本远非恒定**，跨度达 24×。

⚠️ **一个关键限制**：上述 207 条观测**只覆盖已执行的基线路径**。H1 每次 run 只执行一条基线，
因此这 207 条均为 **baseline 实际发生的重算量**，**没有未选中 candidate 的反事实值**。
所以它可支持「部分重计算确实存在」，
但**不可**用作「若淘汰另一个 candidate 则重算量为 X」的依据。

### 2.8 `[事实]` 可用决策时特征的判别力

下表引自 H1 derived bundle 的 `signal_support.jsonl`（M6 产出），口径见 §2.5 的说明 ——
它是**决策内排序一致性**的度量，不是跨决策的原始相关。

| 特征 | ρ | 族一致 | 判定 |
| --- | ---: | ---: | --- |
| `block_count` / `initially_reclaimable` / `prefill_reload` | 0.5999 | 1.000 | PROXY_SUPPORTED（三者等价，见 §2.3） |
| `next_tool_type=database` | **+0.2283** | 0.833 | PROXY_SUPPORTED |
| `next_tool_type=search` | −0.1532 | 0.833 | NOT_SUPPORTED |
| `next_tool_type=code` | −0.0569 | 0.500 | NOT_SUPPORTED |
| `retention_deadline_timestamp` | +0.0585 | 0.667 | NOT_SUPPORTED |
| `decision_native_lru_position` | +0.0585 | 0.667 | NOT_SUPPORTED |
| `elapsed_since_ttl_decision_seconds` | −0.0585 | 0.667 | NOT_SUPPORTED |
| `eta` / `queue_delay` / `waiting_followup` | — | — | coverage 不足（见 §2.9） |

**除成本维度外，唯一正向关联的是 `next_tool_type=database`，ρ = 0.228。**
在我的 raw pooled 口径下它也为正，而三个 tool 指示在 proxy 视图下分别
`database` +0.23 / `search` −0.15 / `code` −0.06 — 即**只有一个 tool 类别带信息**。

⚠️ **口径限制（M1 review item 4）**：ρ 是**特征与 proxy loss 的关联**，
**不是 `P(return)` 预测能力的理论或经验上限**。它只说明：
在**该代理损失**上，现有特征的判别力较弱。正式判级仍以冻结的 paired evaluation 为准。

⚠️ `next_tool_type=code` 在 discovery corpus 上是唯一 supported 的生命周期信号（收益且仅在 F1 一族）。
**它在本语料上 NOT_SUPPORTED。** 这是「定向发现不可迁移」的第二次独立实例（§3.2）。

### 2.9 `[事实]` H1 的设计意图有两个维度**未被落实**

H1 campaign 设计声明 *"Eta and queue delay are sampled per candidate so the campaign can contain within-decision variation"*。但 H1 derived 数据实测：

```text
eta            corpus-distinct = 1 (1.0)，决策内 distinct 上限 = 1
queue_delay_t  corpus-distinct = 1 (0.0)，决策内 distinct 上限 = 1
```

⇒ **这两个退化维度在 H1 中依然退化。** H1 修正了成本分辨率（3 → 10 个取值）与返回行为，但**未**修正 TTL `benefit` 项的退化。

---

## 3. 已被排除、削弱或未被支持的命题

### 3.1 `[事实]` 已被证据排除 / 未被当前数据支持

| 方向 | 状态 | 依据 |
| --- | --- | --- |
| **反转 / 取反 baseline 排序** | **排除**（针对该具体形态） | H1-R1 在冻结 paired evaluation 上全部判据未通过；现有关联证据与之一致（§2.5） |
| **原 HYP-A（raw `C(r)/relief` 作为独立双信号机制）** | **未被当前数据支持** | §2.3：在本语料中 `relief ≡ block_count`、决策时成本特征是 `block_count` 的确定函数 ⇒ raw `C(r)/relief` 退化为**单变量函数** |
| **block-level partial-prefix retention（B1）** | **排除** | H2-M4 FAIL，冻结 single-prefix 比较器下 pairwise headroom = 0 |

⚠️ **上表与前版的区别（M1 review items 1 与 2 的修订）**：

**(a) 不得外推至整个 cost-aware 主线。** 原 HYP-A 被否的是

```text
用 raw C(r) / reclaimable blocks 作为独立双信号机制
```

**而不是**「所有 *expected loss / marginal reclaimable capacity* 类策略不可能有效」。若有分子形如
`P(return|x) · C(r)`，其中 `P(return|x)` 在决策内**不是** `block_count` 的确定函数，则即使 `relief` 与尺寸等价，
该比值也**未必**退化为尺寸排序。

**(b) 前版的 runtime 主张是错误的，现予撤回。** 前版写：

```text
runtime 视图下「每块释放成本」恒为 16 token/block ⇒ 效率排序在该视图无定义
```

**该主张不成立。** `16 tokens/block` 是 **block 到 token 的物理容量换算**，不是每释放一个 block 的实际重算成本。
实测（§2.7）：每 reclaimable block 的实际重算量为 **0.6667 – 16.0000**，共 **12 个不同取值**，
离散度 **24×**。因此**不能**以「每块成本恒定」为依据宣布 runtime 成本效率排序无意义。
正确表述是：成本效率信号在 runtime 视图**未被测量**（207 条观测只覆盖已执行的基线路径，无未选中 candidate 的反事实值）。

### 3.2 `[事实]` 定向发现不可迁移（第二次独立实例）

⚠️ **跨语料对照必须统一统计单位（M1 review 一致性修订）。** Discovery 的
`+0.014797` 是 **decision-position 口径**；H1 的 `−0.008329` 是 **scenario-draw 口径**。二者不可直接相减。
下表同时列出 discovery 的 draw 级数字（`+0.016086`，18 draws）以便同口径对照。

| 规则 / 信号 | Discovery corpus（draw 级） | H1 corpus（draw 级） |
| --- | --- | --- |
| reverse-deadline mean Δ | **+0.016086**（18 draws） | **−0.008329**（29 draws） |
| 同口径单位 | independent scenario draw | independent scenario draw |
| `next_tool_type=code` | PROXY_SUPPORTED，收益仅在 F1 | **NOT_SUPPORTED**（ρ=−0.057） |
| 唯一 supported 生命周期信号 | `code` | **`database`** |

参考（不同单位，不可与 H1 直接比较）：discovery 的 decision-position 口径为 `+0.014797`（20 clusters）。

⇒ **同一信号在两个语料上都换了方向或消失。** 这使 discovery corpus 的方向性结论不能作为先验。

### 3.3 `[推断]` 与「为何简单规则未获支持」一致的解释

本节为**推断**，不是已证明的机制；正式判级仍以冻结 paired evaluation 为准。

§2.1–§2.8 合起来给出一个一致的图景：

```text
proxy loss = I[返回] × C(prefix 长度)
```

- **决策时成本特征** → 在决策内是**精确可得的**：与 `block_count` 的决策内秩一致率是 **99/99 精确为 1**（§2.2）。
  这意味着在该特征上**没有推断空间**（但这不等于实际重算量可知，见 §2.7）。
- **实际重算量并不能由 `block_count` 决定**：同一 `block_count` 可对应至多 6 个不同 loss（§2.7）。
- **返回 / 实现因子** → 似乎是唯一需要预测的部分；而现有特征对**该代理损失**的关联较弱
  （最强为 `next_tool_type=database`，ρ = 0.228）。

⇒ **一个与证据一致的猜测是：瓶颈位于 horizon 内返回 / 实现因子。** 这解释了为何现有规则均未获稳健收益：
它们要么在动已经可得的成本特征，要么在使用关联较弱的返回代理。

⚠️ **不得写成确定机制。** §2.5 与 §2.8 的相关系数均为**关联**，不是因果；
也未证明现有特征集就是 `P(return)` 预测能力的上限。

---

## 4. 仍存在的、尚未验证的优化机会

### 4.1 `[假设 — 尚未验证]` 机会一：淘汰顺序可能改变**实际**重算量

⚠️ **本节证据等级已下调（M1 review item 3）**。前版把它写成「重整后的首选」并暗示跨 entry 因果机制成立；
实测不支持该因果。

**已被数据支持的（事实）：**

- runtime 视图下 **48/207（23.2%）** 行 `loss < prefix 全长`，且同一 `block_count` 可对应至多 6 个不同 loss（§2.7）。
- ⇒ **部分重计算确实存在**，与 H2-M2（partial-prefix APC 语义 PASS）相容。

**尚未证明的（因果）：**

- 48 行 partial recompute **未被证明**是由**另一个 logical entry 的保留**导致；也可能是该 entry 自身的部分命中。
- **未被证明**不同 eviction order 会改变该重算量。
- **直接反证（我实测）**：H1 的 **114 个多候选决策中，候选之间共享 block ID 的为 0 个（0.0%）**。

⚠️ 上述 block-ID 结果**不能单独排除**跨 entry 重叠，因为 `block_id` 是**槽位而非持久内容身份**
（仓库既有事实），且 APC 复用基于内容哈希。两个前缀可在**内容**上重叠而持有不同 slot id。
因此正确的表述是：**跨 entry 重叠在本语料中未被观测到，也未证明存在因果机制。**

**与 baseline 的可能区别**：baseline 键为 `(deadline, min native LRU rank over newly eligible, identity)`，
三项**均不含跨 entry 重叠信息**。若该机制存在，则确实未被表达。

**下一步（M1 已批准为描述性诊断）**：下面的 F-C1。

### 4.2 `[假设 — 尚未验证]` 机会二：返回因子的判别力

- **数据依据（§2.6、§2.8）**：返回因子在 62.5% 决策中可判别；现有特征对**该代理损失**的最强关联为 ρ = 0.228。
- **关键**：这不是「换一个排序键」，而是「**现有决策时信息集是否含足够的返回信息**」。
- ⚠️ **口径限制**：ρ = 0.228 只是特征与 proxy loss 的关联，**不是** `P(return)` 预测能力的上限。
- **越界警告**：任何改变 `ttl_seconds` 计算的方案属 TTL estimator optimization，**超出主线**（G4 已明确）。

### 4.3 `[事实]` 机会三：共享所有权 —— **本语料无法表达**

- §2.2：`relief == block_count` 在 **471/471（100%）** 行成立，**包含 F6「共享所有权」场景**。
- ⇒ 本语料任何候选 entry 的**全部块**在被释放时立即可回收。**部分可回收性在数据中不存在**，因此「多所有者块」不可作为决策变量。
- ⇒ 这不是「未检验」，而是「**当前数据未表达，故不可检验**」。要检验它，需一个 `relief < block_count` 存在的语料。

### 4.4 机会与基线差异总览（rev.3）

| 机会 | baseline 实际使用 | baseline **未**使用 | 证据等级 |
| --- | --- | --- | --- |
| 一：淘汰顺序对实际重算量的影响 | 无跨 entry 信息 | 保留集合与候选前缀的重叠 | **部分重算存在（48/207），但跨 entry 因果机制未知** |
| 二：返回因子判别力 | 单 entry `deadline`（关联弱） | 更强的返回预测 | **现有特征对该代理损失关联较弱；未证明这是信息集上限** |
| 三：共享所有权聚合 | 无 | 多所有者块集合 | **数据未表达，不可检验**（§4.3） |
| ~~原 HYP-A：raw `C(r)/relief` 效率~~ | — | — | **未被当前数据支持**（§3.1） |

---

## 5. 假设与被否证记录

### 5.1 `[未被当前数据支持]` 原 HYP-A：容量归一化的边际释放排序

**rev.1 原话**：「按每 entry 释放后新增可用容量对预期重计算损失的比值排序，优于按 (deadline, native LRU rank) 排序」。

**否证过程（全部为前置检查，未跑任何 campaign）：**

| 检查 | 结果 | 结论 |
| --- | --- | --- |
| `relief` 是否独立于 `block_count`？ | 471/471 相等 | 不独立 |
| 决策内**决策时成本特征**与 `block_count` 是否可分离？ | 秩一致率 99/99 精确为 1 | 不可分离 |
| 真实 $C(r)$ 在 H1 用量区间（r=16–512）内 `C/r` 是否单调？ | **单调下降** | 物理上 raw `C(r)/relief` 等价于尺寸序 |
| 表观非单调来自何处？ | 10 点 proxy 表的局部突起（r=48–128） | 是**代理表假象**，非物理效应 |

**结论（修订后）**：**原 HYP-A 作为「raw `C(r)/relief` 独立双信号机制」的主张，未被当前数据支持** ——
在本语料中它退化为尺寸的单变量重排序，且表观非单调来自代理表离散化。

⚠️ **撤回前版的一条错误依据。** 前版表内有一行「该方向在 runtime 视图是否有意义 ⇒ 每块成本恒为 16 ⇒ 无定义」。
**该行已删除，主张不成立**：16 tokens/block 是容量换算，不是每块实际重算成本；实测每 block 实际重算量
为 0.6667–16.0000（**12 个不同取值，离散 24×**，§2.7）。

⚠️ **不得外推（M1 review item 1）**：本结论只针对 **raw `C(r)/relief`** 这一具体形态。
若分子为 `P(return|x) · C(r)`，则即使 `relief` 与尺寸等价，也**未必**退化，因为 `P(return|x)`
不是 `block_count` 的确定函数。因此**不能**据此否定整个 cost-aware 容量效率主线。

⚠️ 附带发现：proxy 成本表与 native 实测在共用 r 点上比值范围为 **0.303 – 2.051**（r=512 时 proxy 高 3.3×，r=16 时低 2×）。二者测量边界不同（TTFT 差 vs isolated forward），**不可互换**。这会影响任何以 proxy 成本形状为基础的推理。

### 5.2 `[假设 — 尚未验证]` HYP-B：淘汰顺序对实际重算量的影响

```text
[假设] 在满足同一压力目标时，偏好淘汰「其前缀被保留集合覆盖最多」的 entry，
       可降低实际重计算量，优于只按 (deadline, native LRU rank) 排序。
```

⚠️ **证据等级：未验证。** 见 §4.1：部分重计算确实存在（事实），但**跨 entry 因果机制未被证明**；
且 H1 的 114 个多候选决策中候选间共享 block ID 的为 **0**（虽不能单独排除内容重叠，因为
`block_id` 是槽位而非内容身份）。

**与基线的可能区别**：基线三项键**全部**不含跨 entry 重叠信息。

**可能否定它的观测：**

| # | 观测 | 若成立则 |
| --- | --- | --- |
| F-C1 | §2.7 的 48 行 `loss < 全长` 全部来自**单 entry 内部**的部分命中，与其它 entry 的保留无关 | 无跨 entry 机制 ⇒ **否决** |
| F-C2 | 决策内候选的「净重叠」无离差 | 无区分度 ⇒ **预期 null** |
| F-C3 | 需**已观测**的保留集合（事后变量）才能计算 | **不可在线实现** ⇒ 否决（越界） |
| F-C4 | 独立语料上 family agreement < 2/3 或 CI 含 0 | **否决** |

### 5.3 `[假设 — 尚未验证]` HYP-C：返回因子的判别力

```text
[假设] 存在某个可在线获得的组合，对 horizon 内返回指示器的判别力显著高于
       现有特征在当前代理损失上的关联水平（ρ = 0.228）；且据此排序可带来相对
       baseline 的增量收益。不改变 TTL 估计器。
```

⚠️ **口径**：ρ = 0.228 是特征与 **proxy loss** 的关联，**不是** `P(return)` 预测能力的上限。
该假设的实质是「现有信息集是否够用」。

**可能否定它的观测：**

| # | 观测 | 若成立则 |
| --- | --- | --- |
| F-D1 | 现有 12 个特征的任意简单组合，与**返回指示器**的关联仍很弱（可在已解封语料上做**描述性诊断**） | 信息集不足 ⇒ **否决当前信息集**，需新观测缝 |
| F-D2 | 仅 `next_tool_type=database` 有正向关联且收益限于单族 | 族记忆化 ⇒ **否决** |
| F-D3 | 需改动 `ttl_seconds` | **越界**（G4），退回主线外 |

⚠️ **两者的前置检查均为描述性诊断**，其结果只能标 exploratory；F-C1 与 F-D1 的结果
**不能直接授予候选方法资格**（G3）。

### 5.4 若 HYP-B 与 HYP-C 都被否定

则本阶段的正确读法是：

> **在 logical-entry 粒度、当前 12 个 decision-time 特征、当前 proxy loss 定义下，
> 相对 Continuum baseline 的增量空间未被找到；与现有证据一致的推断是瓶颈位于
> horizon 内返回／实现因子，而现有特征对该代理损失的关联较弱。**

此时合理结论是**需要新的决策时观测**（而非新的规则形态）。是否值得开辟新观测缝应由 M1 裁定。

⚠️ 不得写成「已证明不存在任何 cost-aware 策略」：本审计只排除了特定形态，且从未测试
形如 `P(return|x) · C(r)` 的策略。

---

## 6. 建议的下一步

| # | 动作 | 产物 | 前置 |
| --- | --- | --- | --- |
| S1 | 交本文档给 M1 作为方向评审 | 本文 | — |
| S2 | **F-C1 检查**：判定 §2.7 的 `loss < 全长` 行是否与跨 entry 保留相关 | 描述性诊断备忘（标 exploratory） | ✅ **G3 已批准** |
| S3 | **F-D1 检查**：现有特征组合与返回指示器的关联水平 | 同上 | ✅ **G3 已批准** |
| S4 | 仅在 S2/S3 显示方向**值得**时，按 G2 重新 preregister（不自动继承旧绑定） | preregistration 记录 | 需 M1 批准方向 |
| S5 | 若需新语料 / 新观测缝，由 M1 裁定来源（G1） | — | **需 M1 裁定** |

⛔ 本审计**不**请求新 formal campaign、**不**请求新观测缝、**不**授权任何 runtime policy。

---

## 7. M1 的方向裁定（G1–G5，已下达）

本节由 M1 在 PR review 中直接给出，此处仅记录以实现可追溯；**不再列为待裁定项**。

| # | 裁定 |
| --- | --- |
| **G1** | 已解封 H1 语料可用于探索 / 特征诊断，但**不可作为由该语料启发的新假设的独立验证集** |
| **G2** | 可以延续统计框架；新假设**须重新 preregister**，不能自动继承旧 campaign 的独立性、阈值绑定或实验授权 |
| **G3** | **允许** M4 继续做**非验收性的描述性诊断**，包括 F-C1 / F-D1 的可证伪性检查；结果须标 exploratory，**不能从中直接授予候选方法资格** |
| **G4** | Cross-entry / retention-set-dependent victim selection 属于 logical-entry cost-aware 主线；返回因子研究仅在**服务于 victim selection 且不改变 TTL estimator** 时属于主线 |
| **G5** | 记录 `eta` / `queue_delay` native 退化为本轮 H1 的**实验限制**；**不因此重开 H1** |

⇒ **S2 与 S3 现在可以开展**（G3 已批准），但两者产出均为 **exploratory descriptive diagnostics**，
不得据以授予任何候选方法资格，也不得当作独立验证。

---

## 8. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| `loss = I[返回] × C(prefix)` | `src/kvopt/profiling/loss_views.py::_return_weighted_prefill_evidence`；H1 derived `candidate_loss_evidence.jsonl` |
| `relief ≡ block_count`（471/471） | H1 derived `decision_candidates.jsonl`（`local/probe_h1_cost_vs_relief.py`） |
| 决策内 `spearman(block_count, cost) = 1.0`（99/99） | 同上（`local/probe_h1_hypa_collapse.py`） |
| 真实 $C(r)$ U 形，最小值 r≈1024，离散 13.49× | H2 `raw-observations.json`（`local/probe_h2_cost_curve_shape.py`） |
| proxy 表 vs native 比值 0.303–2.051 | 同上 |
| raw pooled `deadline` ρ = +0.1376 / −0.0178；判别 37/38 | H1 derived（`local/probe_h1_decisive_identities.py`） |
| 损失分解 32.5 / 17.5 / 45.0 / 5.0 | 同上（`local/probe_h1_loss_structure.py`） |
| runtime `loss < 全长` 48/207；同一 `block_count` → 最多 6 个 loss | `local/probe_h1_decisive_identities.py` |
| 每 reclaimable block 实际重算量 0.6667–16.0000（12 个取值，24×） | `local/probe_h1_capacity_vs_recompute.py` |
| 候选间共享 block ID：0/114 决策；`relief` 真子集：0/471 | 同上 |
| M6 信号表（ρ、族一致、SUPPORTED） | H1 derived `signal_support.jsonl`、`signal_evaluation.jsonl`（M6 产出） |
| M6 ρ 的口径推导与部分复现（7 项中 2 项精确吻合） | `src/kvopt/profiling/signals.py`（`_normalized_ranks`、`_association`）；`local/probe_h1_signal_rho_definition.py` |
| `eta` / `queue_delay` 仍退化 | H1 derived `decision_candidates.jsonl`（`local/probe_h1_corpus_characterisation.py`） |
| discovery draw 级 `+0.016086`（18 draws） | `local` 探针（decision-position 口径为 `+0.014797` / 20 clusters） |
| G1–G5 裁定 | M1，PR #36 review（2026-10-11） |
| H1 设计声明的逐候选采样 | `docs/phase2a-m6-h1-independent-campaign-design.md` §2 |
| H1-R1 两个语料的 mean Δ | `docs/experiments/phase2a-m6-h1/formal-level-a-review-submission.json`；`docs/phase2a-m4-method-design-report.md` §5 |
| H2 M1/M2/M3/M4 结论 | `docs/experiments/phase2a-m6-h2/formal-final-verdict.json` |
| 冻结释放键 | `src/kvopt/continuum/pressure.py::_release_sort_key` |
| 阶段裁定与封存链 | `docs/phase2a-h1-h2-closeout-verdict-record.md` |

**复核脚本**（`local/`，不入库）：`probe_h1_corpus_characterisation.py`、`probe_h1_cost_vs_relief.py`、`probe_h1_hypa_collapse.py`、`probe_h1_loss_structure.py`、`probe_h1_decisive_identities.py`、`probe_h2_cost_curve_shape.py`、`probe_h1_signal_rho_definition.py`。
