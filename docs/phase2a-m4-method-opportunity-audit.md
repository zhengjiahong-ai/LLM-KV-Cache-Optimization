# Phase 2A M4 — Method Opportunity Audit

Status: **AUDIT ONLY — no method proposed, no campaign requested, no implementation authorized**
Author: M4
Date: 2026-10-10 (**rev.2** — revised against the released H1/H2 evidence bundles)
Baseline: `origin/main` @ `9a0cdff`
Corpora: H1 Level-A bundle `phase2a-h1-level-a-evidence-e3a02fd`; H2 bundle `phase2a-h2-final-evidence-c34a172`

> **rev.2 说明**：rev.1 在拿到 H1/H2 原始证据包之前写成，其**首选假设（HYP-A）现已被数据否证**。
> 本文档保留否证过程，因为它本身是本阶段最有价值的产物之一：它证明前置可证伪性检查可以在
> **不跑任何 campaign** 的前提下淘汰一个方向。

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

**分类纪律**：每条陈述标注 `[事实]` / `[推断]` / `[假设]`。`[假设]` 一律不是结论。

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

### 2.2 `[事实]` 成本维度**完全可观测**，且决策内严格有序

H1 的 471 行候选数据：

| 关系 | 结果 |
| --- | --- |
| `initially_reclaimable_block_count == block_count` | **471/471（100%）** |
| 决策内 `spearman(block_count, prefill_reload_seconds)` | **+1.0000，99/99 决策精确为 1** |
| 固定 `block_count` 下 relief 是否变化 | **完全不变化** |

⇒ **成本维度在决策内是一个可完美观测的单变量（`block_count`）**，不需要任何推断。

### 2.3 `[事实]` `relief` 不提供**任何**独立于成本的信号

因为 `relief ≡ block_count`（100%），而 `cost` 在决策内是 `block_count` 的严格单调函数，所以

```text
cost / relief = C(block_count) / block_count
```

**是 `block_count` 的单变量函数**，不可能携带成本与容量之外的第二个信号。

### 2.4 `[事实]` 真实 native $C(r)$ 的形状

H2 M1，17 个 r 点，每点 9 次重复（取 median）：

| 区间 | `C/r` 行为 |
| --- | --- |
| r = 16 → 1024 | **单调下降**，1220.5e-6 → 90.5e-6 |
| r = 1024 | **最小值**（90.5e-6） |
| r = 2048 → 30720 | **单调上升**，100.5e-6 → 295.1e-6 |
| 全域离散度 | **13.49×** |

⇒ 真实的「每 token 平均成本」是一条**单起伏的 U 形曲线**，最低点在 **r ≈ 1024**。这比「二次非线性」更具体，且**在 16–1024 区间是单调的**。

### 2.5 `[事实]` baseline 的主键几乎不携带损失信息

**直接计数（无任何统计假设）：** 在 75 个可判别决策中，按 deadline 能否分开「返回 vs 不返回」的候选：

```text
返回候选 deadline 更晚 : 37
返回候选 deadline 更早 : 38
```

⇒ **baseline 的主键在判别上与抛硬币无差别。**

**相关系数（我独立复算的 raw pooled Spearman）：**

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
`block_count` 明显具信息量，`deadline` 接近零。你引用时应标明是哪个口径。

**对 H1-R1 的机械解释**：反转一个在两种口径下都接近零的特征不可能产生收益。H1-R1 的失败不是方向选错，
而是**该特征本身几乎不含信息**。

### 2.6 `[事实]` 损失离散度的来源分解

H1，120 个决策：

| 来源 | 决策数 | 占比 |
| --- | ---: | ---: |
| 仅成本变化（返回因子恒定） | 39 | 32.5% |
| 仅返回因子变化（成本恒定） | 21 | 17.5% |
| 两者都变 | 54 | 45.0% |
| 损失恒定 | 6 | 5.0% |

返回因子在 **75/120（62.5%）** 决策中具有判别力。

### 2.7 `[事实]` runtime 视图存在**部分重计算**

`observed_recomputed_tokens` 视图下 `loss == 16 × block_count` 仅 **159/207（76.8%）** 成立。48 行（23.2%）中 loss **小于** prefix 全长，例如 `block_count=24` 时 loss 可为 48（全长为 384）。

且**同一 `block_count` 可对应多个 loss**：`block_count=16` → `{32, 48, 64, 80, 96, 256}`。

⇒ 实际重算量**不是**前缀长度的确定函数；存在**部分命中**（与 H2-M2 PASS 一致）。

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

**除成本维度外，唯一有正向判别力的特征是 `next_tool_type=database`，ρ = 0.228。**
在我的 raw pooled 口径下它也为正，而三个 tool 指示在 proxy 视图下分别
`database` +0.23 / `search` −0.15 / `code` −0.06 — 即**只有一个 tool 类别带信息**。

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

## 3. 已被排除或削弱的命题

### 3.1 `[事实]` 已排除

| 方向 | 依据 |
| --- | --- |
| **反转 / 取反 baseline 排序** | H1-R1 在独立语料上全部冻结判据未通过；§2.5 给出机械原因（主键 ρ≈0） |
| **「成本归一化容量效率」作为独立信号**（原 HYP-A） | §2.3：`relief ≡ block_count`、`cost` 是 `block_count` 的单调函数 ⇒ `cost/relief` 是**单变量函数**，非双信号组合 |
| **容量效率排序在 runtime 视图有意义** | §2.7：runtime 视图下「每块释放成本」恒为 16 token/block，**对所有 entry 相同** ⇒ 效率排序在该视图无定义 |
| **block-level partial-prefix retention（B1）** | H2-M4 FAIL，冻结 single-prefix 比较器下 pairwise headroom = 0 |

### 3.2 `[事实]` 定向发现不可迁移（第二次独立实例）

| 规则 / 信号 | Discovery corpus | H1 corpus |
| --- | --- | --- |
| reverse-deadline | mean Δ **+0.014797** | mean Δ **−0.008329** |
| `next_tool_type=code` | PROXY_SUPPORTED，收益仅在 F1 | **NOT_SUPPORTED**（ρ=−0.057） |
| 唯一 supported 生命周期信号 | `code` | **`database`** |

⇒ **同一信号在两个语料上都换了方向或消失。** 这使 discovery corpus 的任何方向性结论都不能作为先验。

### 3.3 `[推断]` 「为什么没有简单规则能赢」的机制解释

§2.1–§2.8 合起来给出完整解释：

```text
proxy loss = I[返回] × C(prefix 长度)
```

- **成本因子** → 在决策内是**精确可观测**的：`cost` 与 `block_count` 的决策内秩一致率是 **99/99 精确为 1**（§2.2）。不需要推断，也没有推断空间。
- **损失本身并不能由 `block_count` 决定**：同一 `block_count` 可对应至多 6 个不同 loss（§2.7），因为返回/实现因子在变。
- **返回因子** → 唯一需要**预测**的部分；而**没有任何可用特征能较好预测它**（最强为 `next_tool_type=database`，ρ = 0.228；baseline 的 deadline 是抛硬币，§2.5）。

⇒ **决策瓶颈被定位为一个具体变量：horizon 内返回指示器（或其对等的实现因子）。**

这也解释为何 H1-R1（动 deadline）、size 簇（动成本序）、tool 指示（生命周期代理）都无法给出稳健收益：**它们都在动已经可观测的成本侧，或在使用判别力极弱的返回代理。**

---

## 4. 仍存在的、尚未验证的优化机会

### 4.1 `[推断]` 机会一：跨 entry 前缀重叠导致的**实际**重算减少（**重整后的首选**）

- **数据依据（§2.7）**：runtime 视图下 23.2% 行 `loss < prefix 全长`，且同一 `block_count` 可对应至多 6 个不同 loss。说明**淘汰一个 entry 后实际需要重算的量小于它的前缀长度**。
- **机制**：若某 entry 的前缀与「仍被保留/仍被缓存」的另一 entry 重叠，则该 entry 返回时只需重算未被覆盖的后缀。此时**淘汰哪个 entry** 会改变实际重算量 —— 而**这一量在 baseline 中完全不可见**。
- **与 baseline 的真正区别**：baseline 键为 `(deadline, min native LRU rank over newly eligible, identity)`，三项**全部不含跨 entry 重叠信息**。
- **与 §3.1 已排除项的区别**：这不是成本归一化，也不是位置效应的**单前缀**版本（H2-M4 已 FAIL）；它是**跨 entry**、依赖**保留集合**的效应 —— H2-M4 的冻结比较器是 **single-prefix**，**未覆盖**该情形。

### 4.2 `[推断]` 机会二：返回因子判别力提升（瓶颈所在）

- **数据依据（§2.6、§2.8）**：返回因子在 62.5% 决策中可判别，但**现有特征对其判别力上限仅 ρ = 0.228**。
- **关键**：这不是「换一个排序键」，而是「**现有决策时信息集是否含足够的返回信息**」。
- **越界警告**：任何改变 `ttl_seconds` 计算的方案属 TTL estimator optimization，**超出主线**，不得以此名义提出。

### 4.3 `[事实]` 机会三：共享所有权 —— **本语料无法表达**

- §2.2：`relief == block_count` 在 **471/471（100%）** 行成立，**包含 F6「共享所有权」场景**。
- ⇒ 本语料任何候选 entry 的**全部块**在被释放时立即可回收。**部分可回收性在数据中不存在**，因此「多所有者块」不可作为决策变量。
- ⇒ 这不是「未检验」，而是「**当前数据未表达，故不可检验**」。要检验它，需一个 `relief < block_count` 存在的语料。

### 4.4 机会与基线差异总览（rev.2）

| 机会 | baseline 实际使用 | baseline **未**使用 | 数据是否支持其存在 |
| --- | --- | --- | --- |
| 一：跨 entry 重叠的实际重算 | 无跨 entry 信息 | 保留集合与候选前缀的重叠 | ✅ §2.7（23.2% 行 loss < 全长） |
| 二：返回因子判别力 | 单 entry `deadline`（ρ≈0.14） | 更强的返回预测 | ✅ §2.6/§2.8（瓶颈所在，上限 0.228） |
| 三：共享所有权聚合 | 无 | 多所有者块集合 | ❌ **数据未表达**（§2.2/§4.3） |
| ~~原 HYP-A：成本/容量效率~~ | — | — | ❌ **已排除**（§3.1） |

---

## 5. 假设与被否证记录

### 5.1 `[已否证]` 原 HYP-A：容量归一化的边际释放排序

**rev.1 原话**：「按每 entry 释放后新增可用容量对预期重计算损失的比值排序，优于按 (deadline, native LRU rank) 排序」。

**否证过程（全部为前置检查，未跑任何 campaign）：**

| 检查 | 结果 | 结论 |
| --- | --- | --- |
| `relief` 是否独立于 `block_count`？ | 471/471 相等 | ❌ 不独立 |
| 决策内 `cost` 与 `block_count` 是否可分离？ | ρ = 1.0000 精确，99/99 | ❌ 不可分离 |
| 真实 $C(r)$ 在 H1 用量区间（r=16–512）内 `C/r` 是否单调？ | **单调下降** | ❌ 物理上等价于尺寸序 |
| 表观非单调来自何处？ | 10 点 proxy 表的局部突起（r=48–128） | ❌ 是**代理表假象**，非物理效应 |
| 该方向在 runtime 视图是否有意义？ | 每块成本恒为 16 | ❌ 无定义 |

**结论**：原 HYP-A **不是双信号组合**，而是**由代理成本表离散化假象驱动的单特征重排序**，物理上等价于尺寸排序。**应从后续考虑中移除。**

⚠️ 附带发现：proxy 成本表与 native 实测在共用 r 点上比值范围为 **0.303 – 2.051**（r=512 时 proxy 高 3.3×，r=16 时低 2×）。二者测量边界不同（TTFT 差 vs isolated forward），**不可互换**。这会影响任何以 proxy 成本形状为基础的推理。

### 5.2 `[假设]` HYP-B（保留）：跨 entry 重叠的实际重算

```text
[假设] 在满足同一压力目标时，偏好淘汰「其前缀被保留集合覆盖最多」的 entry，
       可降低实际重计算量，优于只按 (deadline, native LRU rank) 排序。
```

**与基线的真正区别**：基线三项键**全部**不含跨 entry 重叠信息。

**可能否定它的观测：**

| # | 观测 | 若成立则 |
| --- | --- | --- |
| F-C1 | §2.7 的 48 行 `loss < 全长` 全部来自**单 entry 内部**的部分命中，与其它 entry 的保留无关 | 无跨 entry 机制 ⇒ **否决** |
| F-C2 | 决策内候选的「净重叠」无离差 | 无区分度 ⇒ **预期 null** |
| F-C3 | 需**已观测**的保留集合（事后变量）才能计算 | **不可在线实现** ⇒ 否决（越界） |
| F-C4 | 独立语料上 family agreement < 2/3 或 CI 含 0 | **否决** |

### 5.3 `[假设]` HYP-C（保留，瓶颈导向）：返回因子判别力

```text
[假设] 存在某个可在线获得的组合，对 horizon 内返回指示器的判别力显著高于当前
       上限 ρ = 0.228；且据此排序可带来相对 baseline 的增量收益。
       不改变 TTL 估计器。
```

**可能否定它的观测：**

| # | 观测 | 若成立则 |
| --- | --- | --- |
| F-D1 | 现有 12 个特征的任意简单组合判别力仍 ≤ 0.228（可在已解封语料上做**诊断**） | 信息集不足 ⇒ **否决当前信息集**，需新观测缝 |
| F-D2 | 仅 `next_tool_type=database` 达标且收益限于单族 | 族记忆化 ⇒ **否决** |
| F-D3 | 需改动 `ttl_seconds` | **越界**，退回主线外 |

### 5.4 若 HYP-B 与 HYP-C 都被否定

则本阶段的正确读法是：

> **在 logical-entry 粒度、当前 12 个 decision-time 特征、当前 proxy loss 定义下，
> 相对 Continuum baseline 的增量空间未被找到；瓶颈已定位为 horizon 内返回／实现因子，
> 而当前信息集对其最强判别力仅为 ρ = 0.228。**

此时合理结论是**需要新的决策时观测**（而非新的规则形态）。是否值得开辟新观测缝应由 M1 裁定。

---

## 6. 建议的下一步

| # | 动作 | 产物 | 前置 |
| --- | --- | --- | --- |
| S1 | 交本文档给 M1 作为方向评审 | 本文 | — |
| S2 | **F-C1 检查**：判定 §2.7 的 `loss < 全长` 行是否与跨 entry 保留相关 | scoping 备忘 | **需 M1 裁定 G3** |
| S3 | **F-D1 检查**：现有特征组合对返回指示器的判别力上限 | 同上 | 同 S2 |
| S4 | 仅在 S2/S3 显示方向可证伪时，preregister 一条规则 | preregistration 记录 | 需 M1 批准方向 |
| S5 | 若需新语料 / 新观测缝，由 M1 裁定来源 | — | **需 M1 裁定 G1** |

⛔ 本审计**不**请求新 formal campaign、**不**请求新观测缝、**不**授权任何 runtime policy。

---

## 7. 需要 M1 裁定的开放事项

| # | 事项 | 影响 |
| --- | --- | --- |
| G1 | H1 的 42 个 sealed scenario 能否用于**新**假设 | 决定 S4/S5 是否需新语料；若复用须预先声明多重比较处置 |
| G2 | 新假设是否沿用同一冻结 acceptance 协议与既有绑定 | 决定 preregistration 字段 |
| G3 | M4 能否以**诊断**（非假设检验）目的读取已解封语料 | **最关键解锁项**；S2/S3 均依赖它 |
| G4 | §4.1 / §4.2 是否属于「Cost-Aware victim selection」主线 | 防止选题漂移（尤其 §4.2 有滑向 TTL 优化的风险） |
| **G5** | **H1 设计声明的 `eta`/`queue_delay` 逐候选采样未在数据中落实（§2.9）** | 若 H1 被再次引用，需记录该维度实际未生效；也影响「H1 已修正退化维度」这一说法 |

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
| M6 信号表（ρ、族一致、SUPPORTED） | H1 derived `signal_support.jsonl`、`signal_evaluation.jsonl`（M6 产出） |
| M6 ρ 的口径推导与部分复现（7 项中 2 项精确吻合） | `src/kvopt/profiling/signals.py`（`_normalized_ranks`、`_association`）；`local/probe_h1_signal_rho_definition.py` |
| `eta` / `queue_delay` 仍退化 | H1 derived `decision_candidates.jsonl`（`local/probe_h1_corpus_characterisation.py`） |
| H1 设计声明的逐候选采样 | `docs/phase2a-m6-h1-independent-campaign-design.md` §2 |
| H1-R1 两个语料的 mean Δ | `docs/experiments/phase2a-m6-h1/formal-level-a-review-submission.json`；`docs/phase2a-m4-method-design-report.md` §5 |
| H2 M1/M2/M3/M4 结论 | `docs/experiments/phase2a-m6-h2/formal-final-verdict.json` |
| 冻结释放键 | `src/kvopt/continuum/pressure.py::_release_sort_key` |
| 阶段裁定与封存链 | `docs/phase2a-h1-h2-closeout-verdict-record.md` |

**复核脚本**（`local/`，不入库）：`probe_h1_corpus_characterisation.py`、`probe_h1_cost_vs_relief.py`、`probe_h1_hypa_collapse.py`、`probe_h1_loss_structure.py`、`probe_h1_decisive_identities.py`、`probe_h2_cost_curve_shape.py`、`probe_h1_signal_rho_definition.py`。
