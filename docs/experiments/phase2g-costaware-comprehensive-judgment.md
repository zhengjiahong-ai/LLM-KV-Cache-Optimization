# Phase 2G Cost-Aware —— 综合研究判断报告（离线分析）

**输入**：PR #82 / v10 Evidence Archive（54/54 runs，`gate: PASS`）。

> **来源核对（一处不一致，需 M1 确认）**：M1 通报的归档 SHA-256 为
> `ac2b910e…`，而本机归档内 `execution-summary.json` 记录的 `archive_sha256`
> 为 `d4aaf36e…`（`tooling_git_sha = 7d0546ab…`）。
> 二者可能分别为"运行期生成的 tar.gz"与"分发用的重打包文件"，但本报告
> **无法验证**这一点。本文全部结论基于**本机解压的这一份**；
> 若 M1 使用另一份，需先逐文件校验 `sha256-manifest.txt` 确认内容一致。
**授权边界**：仅离线只读分析。未修改 A0/A1/A2，未覆盖 PR #82 原始数据，未启动 Native Campaign，未实现新算法。
**分析脚本**：`local/a1_decisions_detail.py`、`local/a4_identity_gap.py`、`local/a4_divergence_check.py`、
`local/a4_legal_order.py`、`local/a5_a2_attribution.py`、`local/a4_legal_strict.py`、`local/a1_flip_criterion.py`、
`local/b4_unlocked_vs_evicted.py`、`local/a2_field_variation.py`、
`local/b2_signal_audit.py`、`local/b3b4_structure.py`、`local/a1_lambda_ablation.py`。

---

## 0. 首要结论（先于全部细节）

本轮分析得到两个**决定性**的审计事实，它们改变了此前所有定性判断：

| # | 事实 | 证据 | 影响 |
|---|---|---|---|
| 1 | **A2 的代价模型在本 campaign 中从未重排块** | `selected_victims == legal_block_ids[:N]` 在 **601/601** 次决策成立 | A2 的 block 层实际等价于"取 legal 列表前 N 个"，不是 cost-aware 选择。B1 的 Gate 问题不存在，因为从未介入 |
| 2 | **`native_lru_victims` 不是独立参照** | `native_lru_victims == legal_block_ids[:N]` 在 **601/601** 成立 | "A2 与 native LRU 一致"是**同义反复**，不能作为证据 |

以及一个**结构性**事实：

| # | 事实 | 证据 |
|---|---|---|
| 3 | 受控压力让 `need` 在 moderate 恒为 **1**、deep 为 **28–114**，而单个 Entry 解锁 200–1663 块 | 18 个 A0 forced 窗口，`N_i / need` 中位数 **118.9×**，最大 **993×** |
| 4 | 复用类中间信号在本归档中**完全缺失** | 540 次 `TTL_HISTORY_INPUT_OBSERVED`，四类样本计数**全部为 0** |

**因此：本轮无法评估 Block 层 cost-aware 的价值（它没有发生），也无法评估任何复用信号的价值（数据不存在）。**
唯一可以严格评估的是 Entry 层的 λ 项，见 Part A3。

---

## 0.1 证据规模与限制

| 项 | 值 |
|---|---|
| Runs | 54 / 54 完成 |
| 网格 | 9 groups × 2 regimes（moderate / deep）× 3 arms |
| **Runtime repeat** | **1** |
| 独立统计单位 | 9（group） |
| Forced-release decisions | **85**（其中 54 个多候选） |
| A1 release steps | **29** |
| A2 block decisions | **601** |
| 内容级因果归因 | `NOT_ESTABLISHED` |
| 单 run wall time | 33–36 s（engine init ≈30 s + native ≈3.4 s） |

三条限制贯穿全文，不再重复：

1. **无 repeat**：任何单 cell 的 token 差都无法与运行间波动区分；
2. **独立单位只有 9 个**：`mean Δ` 是在 9 个 group 上取均值；
3. **Controlled Sparse Replay ≠ 在线服务**：`required_blocks` 由注入设定。

---

# Part A —— 原有分析的验证与深化

## A1. Entry 层：q 是否提供独立价值？

### A1.1 q 的数学关系（本次严格确认）

冻结公式与配置：

```text
ttl_seconds = max(0, ln(prefill_reload_seconds))        # COLD_START 分支
deadline    = ttl_decision_timestamp + ttl_seconds
q           = sigmoid((deadline - t) / tau),  tau = 30.0  (phase2g_a1_tau_seconds)
```

实测本归档：

```text
ttl_seconds == 0          139 / 139   candidate records
=> deadline - t == -elapsed_since_ttl_decision_seconds
=> q = sigmoid(-elapsed / tau)
```

依据：`prefill_reload_seconds` 全部 < 1.0（18 个不同取值），故 `ln(·) < 0`，`max(0, ·) = 0`。

> **结论**：在本归档中，`q` 是 **elapsed 的严格单调递减变换**，
> 而 elapsed 又是一 -（deadline − t）。三者秩完全一致（此前 H1 上实测 114/114）。

### A1.2 信息冗余与"是否可能改变排序"

必须区分 M1 指出的三个层次：

**(i) q 是否提供新的独立观测信息？**
**否。** `q = σ(-elapsed/τ)`，而 deadline 是同一变量的线性函数。`q` 不引入任何
`deadline`/`elapsed` 之外的信息。这一点是**代数结论**，不依赖语料。

**(ii) q 是否改变实际选择？**
**可以，但仅通过与其他项的乘积。** M1 提醒不可由"确定性变换"直接推断"永不改变排序"，
这一点完全正确，机制如下：

$$\widehat R_i=q_i\Big[\min(\text{need},N_i)+\lambda(N_i-\min(\text{need},N_i))^+\Big]$$

- 若 $\lambda=0$ 且所有候选都 sufficient（$N_i\ge$ need），则 $\widehat R_i=q_i\cdot\text{need}$，
  排序 = $q$ 排序 = deadline 排序 → **q 对结果无影响**；
- 若 $\lambda>0$，则 $\widehat R_i$ 是 $q_i$ 与 $N_i$ 的**乘积**。此时 $q$ 的**数值量级**
  与 $N_i$ 的相对大小共同决定结果，q 的差异**可以**翻转排序。

实测本归档 29 个 A1 决策的 $q$ 跨度（跨度 = 决策内 max q − min q）：

| 情形 | 决策数 | q span |
|---|---:|---|
| 单候选（span 恒为 0） | 11 | 0.0000 |
| 双候选 | 18 | 0.1472 – 0.5000 |

**(iii) 改变选择是否有可观测价值？**
见 A1.4。**本归档中唯一的 q 相关翻转是有害的。**

### A1.2b 翻转的定量判据（本报告新增的推导结果）

当所有候选都 sufficient 且 $N_i\gg$ need 时，

$$\widehat R_i=q_i\big(\text{need}+\lambda(N_i-\text{need})\big)\;\approx\;\lambda\,q_iN_i$$

于是：

- **λ=0 的排序** = 最小化 $q_i$（= 最早 deadline）；
- **λ>0 的排序** = 最小化 $q_iN_i$。

两者**必然不一致的充要条件**是：

$$\frac{q_{\text{high}}}{q_{\text{low}}}\;<\;\frac{N_{\text{low-q}}}{N_{\text{high-q}}}$$

即**"低 q 候选的块数优势超过其 q 优势"时，λ 才会翻转选择**。

**实测验证 18 / 18**（`local/a1_flip_criterion.py`，全部双候选决策）：

| run | need | N 值 | q 比值 | N 比值 | 预测翻转 | 实际翻转 |
|---|---:|---|---:|---:|---|---|
| g01 / g02 / g03 / g04 | — | 差 1.6–8.1× | **8.5 – 2.0×10⁸** | 0.12 – 0.63 | 否 | 否 |
| **g05** | 1 / 114 | 649 / 993 | **1.417** | **1.530** | **是** | **是** |
| g06 / g07 / g08 / g09 | — | 差 1.0–1.4× | **1.73 – 26.7** | 0.78 – 1.39 | 否 | 否 |

> **这是本报告最有价值的可复用结论**：
> A1 的分歧概率不是"随负载随机出现"，而是由**两个可测量比值**决定。
> 在本归档中只有 g05 的 q 比（1.417）小于 N 比（1.530），因此只有它翻转——
> 而翻转后的选择是错的。
>
> 推论：**要让 λ 有用，必须存在"低 q 候选同时显著更长"的窗口，
> 并且低 q 确实意味着更低的复用概率。** 后者正是本归档无法验证的部分
> （见 A2：无复用数据）。

> **一个必须写明的边界**：$q$ 的跨度达到 0.5（Gate 2 只有 0.008），
> 说明在本负载上 $q$ 的**数值**确实有区分度。但因为 (i)，这种区分度
> 完全来自 elapsed，即来自 recency。$q$ 的"量级"之所以开始起作用，
> 只是因为它进入了乘积，而不是因为它提供了新信息。

### A1.3 29 次 A1 Release Selection 逐项恢复

完整表见 `local/a1_decisions_detail.py` 输出。汇总：

| 判据 | 吻合数 | 说明 |
|---|---:|---|
| 以配置值 λ=0.5 重放 == 观测选择 | **29 / 29** | 打分阶梯可**精确**复现引擎行为，重放可信 |
| 观测 == Earliest Deadline | **27 / 29** | 与 M1 引用的 27/29 一致 |
| 观测 == Minimum Overshoot（min $N_i$） | 25 / 29 | — |
| 观测 == λ=0 打分 | **27 / 29** | 即 λ=0 与被观测的差异仅 2 次 |

**2 次不一致全部在 g05**，且两次都是同一对候选：

| run | need | django (N, q) | sphinx (N, q) | 观测 | ED 规则 | λ=0 规则 |
|---|---:|---|---|---|---|---|
| g05-deep | 114 | 649, 0.5000 | 993, 0.3528 | **django** | sphinx | sphinx |
| g05-moderate | 1 | 649, 0.5000 | 993, 0.3528 | **django** | sphinx | sphinx |

打分（need=1）：

$$\widehat R_{\text{django}}=0.5\,(1+0.5\cdot648)=162.5,\qquad
\widehat R_{\text{sphinx}}=0.3528\,(1+0.5\cdot992)=175.3$$

→ 选 django。**翻转阈值 $\lambda^\ast\approx0.079$，配置值 0.5 是其 6.3 倍。**

若 $\lambda=0$：$\widehat R_{\text{django}}=0.500$ vs $\widehat R_{\text{sphinx}}=0.353$ → 选 sphinx
（与 ED、与 A0 一致）。

**机制一句话**：A1 在此处选择了 $N_i$ 较小（超额小）的候选；而该候选恰是
**仍在使用中**的那条前缀，代价是 +3712 tokens。

### A1.4 A1 与 A0 在 2/18 Cell 分歧的条件

| 条件 | 观测 |
|---|---|
| 分歧 cell 数 | **2 / 18**（g05 moderate + g05 deep） |
| 其余 16 cell 的 Entry 释放序列 | 与 A0 **逐项相同** |
| 分歧的必要条件 | ①≥2 个候选；②$\lambda>0$；③两候选的 $N_i$ 差异足够大以抵消 $q$ 差 |
| g05 是否唯一满足 | 是。按 A1.2b 的判据，仅 g05 的 q 比值（1.42）小于 N 比值（1.53）；其余 8 组 q 比值 1.73–2.0×10⁸，远大于其 N 比值 |

更精确地：**A1 与 A0 的分歧完全由 λ 产生，而非由 q 产生**，
且其发生条件已由 A1.2b 给出：

| 组 | q 比值 | N 比值 | q 比值 < N 比值？ | 是否分歧 |
|---|---:|---:|---|---|
| g01 | 2.0×10⁸ | 0.12 | 否 | 否 |
| g02 | 886 | 0.41 | 否 | 否 |
| g03 | 8.5 | 0.51 | 否 | 否 |
| g04 | 24.7 | 0.63 | 否 | 否 |
| **g05** | **1.42** | **1.53** | **是** | **是** |
| g06 | 5.0 | 1.39 | 否 | 否 |
| g07 | 1.73 | 0.78 | 否 | 否 |
| g08 | 1.86 | 0.94 | 否 | 否 |
| g09 | 26.7 | 1.01 | 否 | 否 |

**九个组中只有 g05 满足翻转条件，且它是四个非零观测中唯一可归因于策略的那个。**

---

## A2. Entry 层：能否构造真正的 EntryLoss？

### A2.1 先修正成本语义（M1 的意见成立）

若 `reuse_score` 表示**未来复用概率** $p$，则释放造成的期望重算损失应为

$$\text{EntryLoss}_c \;\propto\; p_c \cdot \text{RecomputeCost}_c$$

即 **随复用概率上升而上升**。此前草案的 `(1 − reuse_score) × cost` 方向相反，
会产生"复用概率越高越该先释放"的错误排序，**已撤回**。

同时必须承认第二点：**Unpin 只是解除保护，不等于立即驱逐**。
所以以"当前 victim set"计价的模型会低估，以"解锁块数"计价的模型会高估。
正确口径应是**释放后仍暴露的期望重算**，而这需要下游信息（见 B3）。

### A2.2 决策时可用信号：实测审计

`local/a2_field_variation.py` 对 139 条候选记录逐字段统计：

| 字段 | 不同取值数 | 在多候选决策中变化 | 判定 |
|---|---:|---:|---|
| `prefill_reload_seconds` | **18** | **54 / 54** | 可用（但见下） |
| `elapsed_since_ttl_decision_seconds` | **11** | **54 / 54** | 可用，= deadline 同源 |
| `retention_deadline_timestamp` | **18** | **54 / 54** | 可用，= elapsed 同源 |
| `next_tool_type` | **1**（恒 `observed-agent-gap`） | 0 | **零判别力** |
| `eta` | **1**（恒 1.0） | 0 | 常数 |
| `queue_delay_t_seconds` | **1**（恒 0.0） | 0 | 常数 |
| `waiting_followup` | **1**（恒 True） | 0 | 常数 |

**复用历史完全缺失**（`local/b2_signal_audit.py`）：

```text
TTL_HISTORY_INPUT_OBSERVED 事件          540 次
  eta_history_sample_count                 540 次观测，正值 0 次
  queue_delay_history_sample_count         540 次观测，正值 0 次
  queue_delay_history_recent_sample_count  540 次观测，正值 0 次
  eta_completed_program_count              540 次观测，正值 0 次
eta_provenance_reason   FULLY_MEMORYFUL_COLD_START   540 / 540
right-censored windows  W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED  102 次
```

### A2.3 逐条回答 M1 的 6 个问题

| # | 问题 | 实测答案 |
|---|---|---|
| 1 | 能否取到 prefix_id 级历史 APC Hit / 复用次数 / 最近真实命中时间？ | **本归档中不能**。所有历史计数器为 0，且无 prefix 级命中记录 |
| 2 | 哪些是 Native 观测，哪些是历史推断？ | Native 观测：`block_ids`、`native_lru_rank`、`has_block_hash`、`retention_deadline_timestamp`、`elapsed`。历史/推断：`eta`（`FULLY_MEMORYFUL_COLD_START`，常数 1.0）、`queue_delay`（0.0） |
| 3 | 历史命中频率样本是否充足？冷启动如何处理？ | **样本为 0**，冷启动即全部状态。F4 类多轮场景在本归档中 forced release 为 0，无法产生历史 |
4. 前缀共享、连续性、下游 eviction 如何影响实际重算损失？ | 全臂 54 个窗口共 **224** 个候选间共享块（A0 臂 77 个）；`chain_prefix_broken` 证据项出现 **1 100** 次。共享真实存在，但不是本归档的主因 |
| 5 | 能否构造简单、非负、语义明确的 EntryLoss？ | **不能基于复用来构造**（无数据）。唯一可构造的是 `p_c ≡ 常数` 的退化版，即 `EntryLoss ∝ RecomputeCost_c`——这等价于"按前缀长度排序"，是 A1/$N_i$ 的变体，无信息增量 |
| 6 | 相对 A1/A0/简单规则是否有信息增量？ | **在本归档中无**。可变化的字段只有 prefill_reload / elapsed / deadline 三者，而 deadline 与 elapsed 同源，prefill_reload 与 block 数高度共线 |

### A2.4 EntryLoss 判定

**`INCONCLUSIVE`（不是被否证，而是数据不足）。**

要求 M1 注意一个不可绕过的前置条件：

> 要验证任何"基于复用概率"的 EntryLoss，**必须先有非零的 gap/hit 样本**。
> 本归档的 540 次观测全部为零，`FULLY_MEMORYFUL_COLD_START` 100%。
> 因此**任何新 EntryLoss 都无法用本归档评估**，也无法用"再跑一次同 workload"获得——
> 因为冷启动状态由 workload 结构决定，不随重复运行改变。

这不是"缺少大规模数据"的问题，而是**该 workload 不产生历史**。

---

## A3. λ 项：两个备选方案

### A3.1 方案一：λ = 0

**实测结果**（`local/a1_lambda_ablation.py`，含重放保真度校验）：

| 项 | 值 |
|---|---|
| 重放保真（λ=0.5 复现观测） | **29 / 29** |
| λ 不改变选择 | **27** |
| λ 改变选择 | **2**（均在 g05） |
| λ=0 时与观测一致 | 27 / 29 |
| λ=0 时与被观测差异的 cell | 1（g05 moderate） |

**M1 要求验证"λ=0 是否一般性等价于 A0"——答案是否定的，条件如下：**

λ=0 的分数为 $\widehat R_i=q_i\min(\text{need},N_i)$。与 A0 的
`(deadline, min native_rank of newly eligible, identity)` 等价需要**同时**满足：

1. **所有候选都 sufficient**（$N_i\ge$ need）。否则 $\widehat R_i=q_iN_i$，
   排序不再等于 $q$ 排序；
2. **deadline 无并列**。否则 A1 用 `(program, prefix)` 破平，而 A0 用
   `min native_rank`，两者可以选出不同 Entry。

**本归档的实测**：

```text
multi-candidate decisions        54
decisions with a deadline tie     0 / 54      <- 条件 2 成立
candidate N_i 范围                200 – 1627
need 范围                         1 – 8        <- 条件 1 成立（全部 sufficient）
```

⇒ **在本归档中，λ=0 的 A1 与 A0 在全部 18 个 cell 上等价。**
但这个等价性是**条件性的**，不能推广：

- 若 workload 出现"需多轮释放"（`per_unit` 分支），条件 1 失效；
- 若出现 deadline 并列，条件 2 失效。

> **结论**：λ=0 不是"不会退化的保底策略"，而是"在本归档的几何下退化为 A0"。
> 它消除了唯一的退化，**但没有产生任何改善**。

### A3.2 方案二：边际释放收益 / 成本模型

**M1 的问题**："每单位重算损失换取多少有效容量"是否可计算、是否优于简单规则？

**(i) 可计算性。** 本归档中 $N_i/\text{need}$ 的中位数是 **118.9×**，最大 **993×**。
分母（moderate 为 1，deep 为 28–114）相对分子（200–1663）几乎可以忽略，
因此“每单位容量”这个比值**在本 workload 上退化为 $1/N_i$**，即“偏好最大解锁量”。

**(ii) 与简单规则的关系。** λ=0.5 的分数在 $N_i \gg$ need 时近似为
$q_i\lambda N_i$，即"最小化 $q\cdot N$"。而在 g05，这等价于"最小化 $N$"
（因为 $q$ 差异被 $N$ 差异压过）→ A1 选了 $N$ 小的 django。

**这是有害的**：$N$ 小意味着前缀短，而短前缀可能恰是活跃的。

**(iii) 结论。** 在本归档几何下，"每单位容量成本"不构成独立判据：
它要么退化为 $1/N$（偏好大解锁），要么被 λ 放大成 $qN$（偏好小解锁），
**两者都不是重算成本的代理**，因为真正决定重算的是**哪条前缀先断**，
而这与 $N$ 的大小无必然关系。

| 简单规则 | 在本归档的隐含偏好 | 实测后果 |
|---|---|---|
| Earliest Deadline | 最旧的前缀 | 27/29 与 A1 一致；g05 未选中 → 该 cell 重算 16 tokens |
| Minimum Overshoot（min $N$） | 最短前缀 | 25/29 与 A1 一致；g05 选中 → 3712 tokens |
| Sufficient-first + ED | 与 ED 相同（全 sufficient） | 29/29 与 ED 相同 |

---

## A4. Block 层：A2 身份缺口与实际有效介入

### A4.1 核对 167 / 601 的分母与分类

`local/a4_identity_gap.py` 逐事件重建：

| 项 | 值 |
|---|---|
| `COST_AWARE_BLOCK_DECISION` 总数 | **601** |
| `selector = incremental_greedy` | **434**（`cost_known = true`，`fallbacks = []`） |
| `selector = native_lru_fallback` | **167**（27.8%，`fallbacks = ['content_unverified']`） |
| `contract_problems` 非空 | 0 |
| `adapter_problems` 非空 | 0 |
| `search_truncated = true` | 434（即全部 greedy 决策均超枚举预算） |

**与 Gate 2 的 51.7% 不可直接比较**，理由三条：分母口径不同（本归档 601 次
块级决策，Gate 2 为 778）；workload 不同；本归档 372 次决策发生在**任何
forced-release 窗口之前**，Gate 2 的分母以 forced 窗口为主。

回退原因（来自 `evidence_problem_counts`）：

| 证据问题 | 计数（块级） |
|---|---:|
| `legal_hashed_candidate_without_membership` | **158 483** |
| `chain_prefix_broken` | **1 100** |

块身份状态分布（块级累计）：

| 状态 | 计数 |
|---|---:|
| `HASHLESS_NO_CONTENT` | 441 994 |
| `CONTENT_UNVERIFIED` | 158 483 |
| `CONTENT_VERIFIED_CHAIN_WEIGHTED` | 74 302 |

### A4.2 关键问题：601 次中多少次真正完成了 cost-aware 选择？

**答案：0 次。** 这是本次分析最重要的发现。

```text
selected_victims == legal_block_ids[:required_blocks]      601 / 601
selected_victims == native_lru_victims                     601 / 601
native_lru_victims == legal_block_ids[:required_blocks]    601 / 601
```

**三条同时成立意味着**：
1. A2 的代价模型**从未改变过块的顺序或集合**——它总是取给定 legal 列表的前 N 个；
2. 报告中的 `native_lru_victims` 字段**不是独立参照**，而是 `legal[:N]` 的回声，
   因此"A2 与 native LRU 一致"是同义反复，**不能作为 A2 保守/正确的证据**；
3. 因此本 campaign **没有检验过** block 层 cost-aware 决策的价值。

补充：`proxy_weighted_loss == 0.0` 出现在 **368 / 601** 次决策；
`no verified chain` 出现在 **488 / 601** 次。即多数决策的模型损失恒为零，
本就没有可优化的差异。

### A4.3 与实际 A0 的分歧：本归档**无法判定**

A2 取 `legal[:N]`，A0 用 `(eligibility_tier, native_lru_rank)`。两者是否一致，
需要知道 legal 列表的排序依据。**这一点在本归档中不可靠地恢复：**

| 项 | 值 |
|---|---:|
| 可定位队列快照的块决策 | 229 |
| 其中 legal 中含快照里查不到的块（快照已过期） | **151** |
| **严格可比（全部 legal 块都在快照中）** | **78** |
| 其中 legal 顺序 == (tier, rank) | 71 |
| 其中 legal 顺序 != (tier, rank) | **7** |

**为什么不能据此下结论**：

1. 队列快照只在 `FORCED_RELEASE_DECISION` 事件中记录，而块决策发生在其后的任意时刻；
   105/229 的决策所涉及的块已经不在该快照里，说明快照与决策时刻不同步；
2. 对那 7 个“不一致”的例子，legal 顺序呈 **rank 降序**（如 202, 201, 200…），
   这与“快照过期导致 rank 错位”高度一致，**不能当作真实的排序依据**；
3. 归档没有记录 legal 列表的**生成规则**（排序字段）。

> **准确的结论是**：A2 的代价模型**从未重排**（601/601，不依赖快照，可靠）；
> 但“`legal[:N]` 是否等于 A0 的 tier-aware 选择”**本归档无法验证**。
> 因此 A2 的 4 个非零差异**既不能归因于 cost-aware，也不能归因于 tier**，
> 只能标为 `NOT_ATTRIBUTABLE`。

### A4.4 "同条目内按 LRU Rank 从尾部驱逐"（候选想法）

M1 要求不得预先认定不劣于 A0。据此说明其必须满足的条件：

1. `native_lru_rank` **不等于** prefix depth，不能直接当深度用；
2. 必须保持物理前缀连续性（断在中段 vs 尾部的重算量差一个数量级）；
3. 必须正确保持共享引用（一个块被多 Entry 拥有时，只有全部 owner 释放才可回收）；
4. 必须尊重 eligibility tier（hashless 优先）。

本归档的 `chain_prefix_broken = 1100` 说明断裂确实在发生，但**没有逐块的
深度证据**可以判定断裂位置，因此**当前数据无法验证该想法**。

### A4.5 身份缺口的性质判定

| 可能性 | 判定 | 依据 |
|---|---|---|
| 工程同步问题 | **部分成立** | `legal_hashed_candidate_without_membership` 158 483 次主导，说明 legal 列表中的 hashed 候选未被赋予链成员关系 |
| 观测缺失问题 | **成立** | 无 prefix 级命中历史、无 per-block 深度 |
| 算法信息需求超出 Runtime 能力 | **不成立于本归档** | 因 A2 从未重排，算法实际未"需要"这些信息 |

---

## A5. 统计与字段问题

### A5.1 Repeats

| 项 | 状态 |
|---|---|
| 本 campaign repeats | **1** |
| 因此可估计的方差 | **无** |
| 最需要重复验证的观测 | g05 +3712；g02 +1824；g08 +816；g09 +256 |
| 单次观测能支持什么 | 仅"该 cell 存在差异"这一描述性事实 |
| 单次观测**不能**支持什么 | 退化稳定存在；算法稳定更差 |

**成本估算**（实测 wall time 33–36 s/run，engine init ≈30 s）：

| 设计 | Runs | GPU 时间 |
|---|---:|---:|
| 9 groups × 1 regime × 3 arms × 2 repeats | 54 | ≈ 32 min |
| 9 groups × 2 regimes × 3 arms × 2 repeats | 108 | ≈ 65 min |
| 9 groups × 2 regimes × 3 arms × 1 repeat（现状） | 54 | ≈ 32 min |

> 结论：**GPU 时间不是约束**（一小时级）。约束是授权轮次与独立样本数（仅 9 个 group）。

### A5.2 `physical_eviction_divergence`

| 项 | 发现 |
|---|---|
| 定义位置 | **不在本仓库**（全库 `grep` 无匹配），由外部分析器生成 |
| 本归档取值 | **18 / 18 cell 全为 `{"A1": true, "A2": true}`** |
| 其中 A1 与 A0 释放序列相同的 cell | 16 / 18（`selection_sequence` 逐项相同） |
| 可比性 | `physical_eviction_signature` 含进程内 block_id 与 native hash，**跨 run 不可比** |

**建议**（明确）：**弃用该字段**，或重新定义为"仅在 `selection_sequence` 不同时
才计算的内容级分歧"，并在文档中写明其定义。当前形式会误导读者认为
"A1/A2 在 18 个 cell 上都发生了物理淘汰分歧"，而这与事实不符。

### A5.3 非零结果归因

| cell | Δ | 策略上做了什么不同 | 可验证事实 | 是否发生真实前缀丢失 | 可观测重算变化 | 归因判定 |
|---|---:|---|---|---|---|---|
| **g05-moderate** | **+3712** | A1 释放 django，A0 释放 sphinx | $N_i$、$q$、need 全部来自事件；λ=0.5 打分可复现 | **是**：A0 侧 `E−C = 16`，A1 侧 `3728` | `aggregate_recomputed_tokens` 直接测量 | **强**（唯一一次可手算的确定差异） |
| g05-deep | 0 | A1 先 django 再 sphinx（2 步） | 同上 | 最终 victim 集合等价 | 最终相同（10512 两侧） | 弱：多释放一次但被后续决策修正 |
| g02-moderate | +1824 | Entry 释放序列**与 A0 相同** | 601/601 块选择为 legal 前缀；legal 排序依据不可恢复 | **不可判定**（无逐块证据） | 有 token 差 | **不可归因**（`NOT_ATTRIBUTABLE`）：Entry 相同、块未重排 ⇒ 无法区分快照/排序差异与运行间波动 |
| g08-moderate | +816 | 同上 | 同上 | 同上 | 有 | 同上 |
| g09-moderate | +256 | 同上 | 同上 | 同上 | 有 | 同上 |

> 一个必须强调的点：**A2 的 4 个非零差异中，3 个（g02/g08/g09）发生在
> Entry 序列与 A0 完全相同的 cell，且 A2 的块选择从未重排。**
> 因此这些差异**在机制上找不到 cost-aware 的来源**。

---

# Part B —— M2 四方向的真实数据机会审计

## B1. Block Idea 1：条件介入 / Native-LRU fallback

| 审计项 | 实测 |
|---|---|
| 身份证据覆盖率 | 434/601 cost_known（72.2%）；167/601 回退（27.8%） |
| **实际介入（重排）次数** | **0 / 601** |
| 与 A0 的可验证块级分歧 | 无法建立（`native_lru_victims` 是回显） |
| 决策时可用的 Gate 特征 | prefill_reload、elapsed、deadline、chain_count、shared_block_count 等 |
| 是否有观测到"值得偏离 LRU"的窗口 | **无**（从未偏离，故无收益/代价样本） |

**判定：`NOT TESTABLE ON THIS ARCHIVE`（在现有归档上不可检验）。**

理由不是"回退率太高"，而是更基本的：**A2 从未产生过与 legal 前缀不同的选择**。
要让 Gate 有价值，必须先出现"cost-aware 会选不同的块"的窗口；
本归档中此类窗口数为 0。

> 这也修正了此前"51.7% 回退率是主要障碍"的说法：回退率确实高，
> 但**在未回退的 434 次决策中，cost-aware 也一次都没有改变选择**。
> 因此**障碍不是身份缺口，而是"没有可被改变的差异"**。

**M1 的警告已遵守**：本报告不尝试用已观测收益反推 Gate 阈值。

---

## B2. Block Idea 2：Continuum 中间信号

逐项核对（`local/b2_signal_audit.py` + `local/a2_field_variation.py`）：

| 信号 | 决策时可得？ | 本归档变异 | 已知 Deadline 下是否有增量 |
|---|---|---|---|
| Tool Type | 字段在，但**恒为** `observed-agent-gap` | 1 个取值 | **无**（常数无法排序） |
| Tool Duration | **不存在**该字段 | — | **无** |
| Inter-request Gap History | 计数器存在，**样本数恒为 0** | 0 | **无** |
| Queue Delay | 字段在，**恒为 0.0** | 1 个取值 | **无** |
| Program Progress / Eta | 字段在，**恒为 1.0**（`FULLY_MEMORYFUL_COLD_START`） | 1 个取值 | **无** |
| PrefillReload Cost | 有，18 个取值 | 54/54 决策中变化 | **与 block 数高度共线**；profile 自身标记 `INCONCLUSIVE_COST_ORDERING` |
| 复用历史（命中次数/最近命中） | **不存在** | — | **无** |

**判定：`NO DATA`。**

三个必须区分的事实（M1 明确要求）：

1. **信号在代码中存在** ≠ 可用：`queue_delay_history`、`eta_history` 类均存在，
   但本归档 540 次观测全部为 0；
2. **Runtime 存储过该字段** ≠ Block Selector 可读：`TTL_HISTORY_INPUT_OBSERVED`
   只是观测事件，Block 决策事件 payload 中不含这些字段；
3. **需要多少接线工作**：要让 Block 层读 tool type / gap 历史，需要扩展
   `EvictionCandidate` / `EvictionContext` 契约 —— 属接口改动，不是配置改动。

> 关键：本方向的**绑定约束不是信号质量，而是本 workload 不产生历史**。
> 重复运行同一 workload 无法改变这一点（冷启动由结构决定）。

---

## B3. Entry Idea 3：下游感知的释放排序

| 审计项 | 实测 |
|---|---|
| 候选间共享块 | 全部臂 54 个窗口共 **224** 个；A0 臂 18 个窗口共 77 个 |
| 多候选窗口 | **32 / 54**（全臂） |
| 不同释放顺序是否可能改变 victim set | **是**（g05 的 2 个决策实际改变了） |
| A0 的键已包含哪些下游信息 | `(deadline, min native_rank over newly eligible, identity)` —— **已消费下游 rank** |
| A1 的独立选择数 | 2（全在 g05），且**有害** |
| One-step lookahead 是否可能优于 SF/ED | **本归档中不可能**：所有候选均 sufficient，单步即可达成目标，lookahead 分支从未触发 |

**判定：`LIMITED`（可测但机会极小，且需要身份证据）。**

两点关键：

1. A0 的第二键 `min native_rank of newly eligible` **本身就是下游感知**。
   因此"下游感知排序"相对 A0 的增量**小于相对纯 deadline 基线的增量**；
2. 评价单位必须分开（M1 要求）：
   - **边际单步**：只评估一次假设释放带来的增量；
   - **完整循环**：继续走完整个释放循环后再评分。
   本归档中因为单步即满足目标，两者**恰好相同**；但下一个 campaign 若出现多步，
   必须预先固定使用哪一种。

---

## B4. Entry Idea 4：部分尾部释放

| 审计项 | 实测 |
|---|---|
| `need` 范围 | moderate **1**；deep **28–114** |
| 单 Entry `N_i` 范围 | 200 – 1663 |
| `N_i / need` 中位数 | **118.90×** |
| 最大 | **993×** |
| 最小 | 8.71× |
| ≥ 2× 的窗口 | **18 / 18** |
| ≥ 10× 的窗口 | 17 / 18 |
| **解锁块 / 实际淘汰块**（中位数） | **17.3×**（最大 66.2×） |

逐窗口数据（A0 臂，18 个 forced 窗口）：

| run | need | target | 解锁 | 实际淘汰 |
|---|---:|---:|---:|---:|
| g01-deep | 44 | 44 | 1663 | 44 |
| g01-moderate | 1 | 93 | 200 | 93 |
| g05-deep | 114 | 128 | 993 | 31 |
| g05-moderate | 1 | 15 | 993 | 15 |
| g09-moderate | 1 | 16 | 951 | 16 |

（完整 18 行见 `local/b4_unlocked_vs_evicted.py`）

**理论上限极高**：释放一个 Entry 解锁 200–1663 块，而 moderate 档只需 **1** 块、
deep 档需 28–114 块。解锁量与需求量的中位数比值为 **118.9×**。

**但必须立即说明三点限制**：

1. **这个超额是 campaign 设计造成的，不是自然现象**。
   配置中 `pressure.initial_shortage_blocks = 1`，moderate 档的 `need` 恒为 1。
   真实 agent 服务的压力通常需要释放大量块。因此**不能把 118.9× 当作真实负载的
   优化空间**；
2. **超额 ≠ 浪费**。解锁但未立即驱逐的块仍留在缓存中，会在后续压力下被用掉。
   本归档有 102 个右删失窗口（`W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED`），
   说明观测在 session 结束前被截断，**无法度量"后续是否被用掉"**；
3. **实现成本高**：`RetentionEntrySnapshot.protected` 是单一 Boolean
   （`snapshots.py`），`KVCacheManager.free()` 释放整请求。改为深度级保护需要：
   改保护表示、改 `_eligible_block_ids` 的 per-block 判定、重新定义共享块的
   "部分保护"语义、并通过全部冻结测试。

**判定：`HIGH COST / HIGH RISK`。** 对课程项目最后一轮**不建议实现**。

---

# Part C —— 综合研究裁定

## C1. 统一评价表

| 方向 | 针对的问题 | 真实数据支持的事实 | 可观测的决策机会 | 新信号决策时可获取 | 能改变真实 Native 选择 | 可验证潜在收益 | 身份/Profile 依赖 | 工程复杂度 | 主要正确性风险 | 适合最后一轮 |
|---|---|---|---|---|---|---|---|---|---|---|
| **A1 q 重设计** | q 无独立信息 | q = σ(−elapsed/τ)，代数同一 | 18 个双候选决策，q span 最高 0.5 | ✗（无复用历史） | 只能通过乘积 | **无**（唯一翻转有害） | 中 | 低 | 低 | ✗（不值得） |
| **A2 新 EntryLoss** | 引入真实复用概率 | 历史样本 **0 / 540** | 0（无数据） | ✗ | 不可测 | 不可测 | **高**（需新信号） | 中 | 中 | ✗（数据不存在） |
| **A3 λ=0** | 移除有害罚项 | 29/29 重放可复现；λ 仅影响 g05 | 2 个决策 | 无需新信号 | **是**（改为 A0） | 消除 +3712，但不产生改善 | 低 | **零**（配置项） | 低（但需验证条件） | **✓ 作为对照臂** |
| **A4 身份缺口** | 601 次决策有效性 | **0/601 实际介入** | 0 | — | — | — | — | — | 先修接口与快照同步 | ✗（先修接口） |
| **B1 条件介入** | A2 该不该总是执行 | 从未偏离，故无窗口 | 0 / 601 | 有候选特征 | 不可测 | 不可测 | 高 | 中 | 中 | ✗ |
| **B2 中间信号** | 引入 TTL 中间量 | 样本全 0；三个字段为常数 | 0 | ✗ | 不可测 | 不可测 | 高 | 中高（接口改动） | 高（双计） | ✗ |
| **B3 下游感知排序** | 释放顺序影响 victim | 224 共享块；2/18 分歧 | 32/54 多候选，但全部单步 | 已有 rank | 是（2 次） | 边际极小 | 中 | 中 | 中 | △（仅离线） |
| **B4 部分尾部释放** | 整 Entry 过度释放 | 超额 118.9×（**但为设计造成**） | 18/18 | 已有 | 是 | 理论大、实测无 | 高 | **高** | **高**（共享语义） | ✗ |

## C2. M4 与 M2 方案的相互关系（M1 要求逐条回答）

**① 新 EntryLoss 与 Idea 3 能否互补？**
**不能在本归档互补。** EntryLoss 需要复用概率（数据为 0），Idea 3 需要下游 victim
信息（数据部分存在）。两者都指向同一个缺失条件：**需要能区分"哪条前缀还活着"的信号**，
而本 workload 不产生该信号。若将来有了历史数据，两者可互补：EntryLoss 给
"该不该放"，Idea 3 给"先放谁"。

**② λ 的边际收益思路是否已包含在 Idea 3 中？**
**实质上是。** λ 的项 $\lambda(N_i-\min(\text{need},N_i))^+$ 惩罚"超额解锁"，
而 Idea 3 的 one-step lookahead 正是评估"这次释放会带来多少下游变化"。
两者都在估计同一件事：**释放的边际价值**。差别仅在评价单位（单步 vs 完整循环）。
实测支持这一判断：λ 的唯一作用就是选出"超额小"的候选，与 min-overshoot 规则
25/29 一致。

**③ A2 身份缺口是否是 Idea 1/2 的共同前置障碍？**
**是，但不是主要障碍。** 更主要的障碍是：**A2 的代价模型在本归档中从未产生
与 legal 前缀不同的顺序**（0/601）。即使身份缺口完全修复，只要模型不改变顺序，
Idea 1 的 Gate 也无可评之物。Idea 2 另有独立障碍（无历史样本、需接口改动）。

**④ 若 A0/Sufficient-first 已覆盖绝大部分有效选择，是否应优先保留简单规则？**
**是。** 实测支持：29 个 A1 决策中 27 个与 ED 一致、λ=0 时 27/29 与观测一致；
A2 的 601 次决策全部等于 legal 前缀。**"简单规则"在本归档中已经覆盖了
几乎全部实际选择**，而唯一偏离基线的那次是退化的。

**⑤ Idea 4 是否因成本过高不适合本阶段？**
**是。** 需要改 `RetentionEntrySnapshot.protected` 的语义、`KVCacheManager` 的
释放粒度、共享块的部分保护定义，并通过全部冻结测试。课程项目最后一轮不应承担。

## C3. 裁定建议

| 方向 | 裁定 | 理由 |
|---|---|---|
| **A1 q 重设计（换 q 输入）** | **放弃** | 代数上无新信息；无复用数据；唯一偏离有害 |
| **A2 新 EntryLoss** | **暂缓（前提未满足）** | 历史样本 0/540；需先产生非冷启动 workload |
| **A3 λ=0** | **保留为必测对照** | 零成本（配置项），且是唯一能隔离"λ 是否致因"的手段 |
| **A4 身份缺口修复** | **暂缓** | 修了也无对象（0/601 介入） |
| **B1 条件介入 Gate** | **放弃（本阶段）** | 无可介入窗口，无法建立 Gate |
| **B2 中间信号** | **放弃（本阶段）** | 三个字段为常数，其余无样本，且需接口改动 |
| **B3 下游感知排序** | **仅保留离线** | 边际机会极小，且 A0 已消费下游 rank |
| **B4 部分尾部释放** | **放弃（本阶段）** | 工程成本与正确性风险过高 |

**保留的候选方法（最多两个）：**

1. **Sufficient-first + Earliest Deadline（SFED）** —— 不是新算法，而是
   **必须被证伪的强基线**。本归档显示它覆盖了 29/29 中 27 个、且 λ=0 时
   与 A1 完全一致。**它的价值在于：如果 A1 赢不过它，A1 的复杂度就没有依据。**
2. **λ=0 的 A1（≡ SFED）作为候选最终方法** —— 条件是验证其在
   `per_unit` 与 deadline 并列情形下不退化为 A0。本归档两条件都成立，
   故等价；但这不是一般结论。

> **明确不接受的方向**：任何以"更精细的代价函数"为核心的新方案。
> 本归档给出的证据是：代价函数在两个层级都没有产生任何改变选择的实例。

---

# Part D —— 最后一轮实验 Freeze Proposal

## D1. 核心研究假设

> **H1**：A1 在 g05 的 +3712 退化由 λ 超额罚项**确定性**造成，而非运行间波动。
>
> **H2**：在该 workload 上λ=0 的 A1（≡ SFED）与 A0 **完全等价**（无差异、无退化）。

**H3（可预注册的强预测）**：由 A1.2b 的判据，A1 与 SFED 的差异**只能**出现在
满足 $q_{\text{ratio}}<N_{\text{ratio}}$ 的 group 上。本归档中仅 g05 满足，
因此预注册预测：**其余 8 组的 A1−SFED 必须为 0**。
若出现任何偏离，则 A1.2b 的判据被否定，需重新建模。

这两个假设**互相独立可证伪**，且共同回答本项目最关键的未决问题：
**A1 的加权成本模型是否存在任何可测量的贡献？**

选择该问题而非新算法的理由：

- 本归档已证明 A2 从未介入、复用信号不存在、B1–B4 均不可测；
- 因此**唯一还能在本预算内产生确定性结论的，是 λ 的因果作用**；
- 该问题若答案为"λ 是唯一变异源且有害"，则 A1 的复杂度应被判定为无依据，
  这对课程结题是一个**清晰、可信、可辩护的负结论**。

## D2. 具体算法与信息

| 臂 | `policy` | `phase2g_a1_lambda` | 说明 |
|---|---|---|---|
| **A0** | `continuum-a0-entry-native-lru` | — | 冻结基线 |
| **A1** | `continuum-a1-entry-native-lru` | **0.5** | 冻结原样，不改代码 |
| **SFED** | `continuum-a1-entry-native-lru` | **0.0** | 同一实现、仅改配置；λ=0 时分式退化为 $q\cdot\min(\text{need},N)$ |

**关键**：SFED 臂**不需要任何代码改动**——`phase2g_a1_lambda` 已是配置项
（`campaign/*.config.json`），且 λ=0 时若候选全部 sufficient，
打分等价于"最旧 deadline 优先"。

不使用任何新信号（本归档证明无可用信号）。

## D3. 网格与独立样本

| 项 | 设计 |
|---|---|
| Groups | **全部 9 个**（g01–g09），不做 group 级筛选 |
| Regime | **moderate only** |
| Arms | 3（A0 / A1 / SFED） |
| **Runtime repeats** | **2** |
| **Runs** | 9 × 1 × 3 × 2 = **54** |
| 独立统计单位 | **9**（group；repeats 不独立） |

**为什么只取 moderate（必须在预注册中写明的设计选择及其风险）**：

- 依据：本归档 `deep` 档 18 个 cell 的 Δ **全部为 0**（含 A1 与 A2）；
  所有 4 个非零观测都在 `moderate`；
- **风险声明**：这是基于已观测结构的筛选，可能引入选择偏差；
- **缓解**：保留**全部 9 个 group**（不剔除任何组），因此不是"只挑有差异的组"；
- **代价**：`deep` 档在本次将不再被检验，其"无非零差异"的结论保持不变。

若不接受该筛选，备选为 `9 × 2 regimes × 3 arms × 1 repeat = 54`（无 repeat），
但那会放弃本轮最需要的方差估计，**不推荐**。

## D4. 指标

**主要指标**

| 指标 | 定义 |
|---|---|
| `aggregate_recomputed_tokens` 的 paired Δ | A1−A0、SFED−A0，按 group 配对 |
| **repeat 一致性** | 同一 (group, arm) 两次重复的 Δ 是否同符号/同量 |

**辅助指标**

- `aggregate_actual_prefill_tokens`、`aggregate_new_suffix_tokens`（应恒为 0 差）；
- `selection_sequence` 逐项比较（**唯一可信的选择分歧判据**）；
- forced-release 决策数、`branch` 分布（单步 / per_unit）；
- per-decision 的 λ 消融（离线，复用 `local/a1_lambda_ablation.py`）。

**明确弃用**

- `physical_eviction_divergence`（语义未定义、18/18 全 true）；
- `physical_eviction_signature`（含进程内 ID，跨 run 不可比）；
- `native_lru_victims` 作为"独立参照"（实测为 `legal[:N]` 回显）。

## D5. 证据链要求

| 层级 | 要求 |
|---|---|
| 物理决策 | 每臂的 `selection_sequence` 必须逐项记录并可跨 run 比较（逻辑 Entry 键） |
| Block victim | 必须额外记录 **legal 列表的排序依据**（rank-only / tier-aware），否则无法判断是否重排 |
| APC | `E`、`C`、`N` 三元组逐请求记录，且 `0 ≤ C ≤ E ≤ N` 校验 |
| 重算 | 按请求聚合并按 group 配对；禁止用 proxy loss 代替 token |
| 身份 | 区分 `HASHLESS_NO_CONTENT` / `CONTENT_UNVERIFIED` / `CONTENT_VERIFIED`，并**分别报告**分母 |

## D6. 统计与不确定性

| 项 | 方法 |
|---|---|
| 配对单位 | group（n = 9） |
| 效应量 | 每个 group 的 Δ（两次 repeat 取均值；若两次不一致则**报为不稳定**） |
| 区间 | 9 个点的 bootstrap 95%（明确标注 exploratory） |
| **repeat 一致性检验** | 逐 (group, arm) 检验两次 Δ 是否相同；**这是本轮的主检验** |
| 不做的检验 | 不做跨 group 的显著性检验（n=9，且 group 非随机抽样） |

## D7. 预注册的成功 / 失败 / 不可判定条件

**判据 1（λ 的因果性）**

| 结果 | 判定 |
|---|---|
| g05：A1 的 +3712 在两次 repeat 中**均出现**，且 SFED−A0 = 0（两次） | **H1 成立**：λ 是确定性致因 |
| g05：A1 的差异在两次 repeat 中**不一致** | **H1 被否**：+3712 属运行间波动 |
| g05：A1 稳定退化但 SFED 也退化 | **H1 被否**：λ 不是唯一原因 |

**判据 2（SFED 与 A0 的等价性）**

| 结果 | 判定 |
|---|---|
| SFED 在 9 个 group × 2 repeats 中 Δ **全部为 0** | **H2 成立**：SFED ≡ A0 on this workload |
| 存在任一 group 的 SFED Δ ≠ 0 | **H2 被否**：λ=0 不等于 A0，需重新审视等价条件 |

**判据 3（整体）**

| 结果 | 课程项目可支持的结论 |
|---|---|
| H1 成立 + H2 成立 | **"A1 的加权成本模型在本 workload 上无独立价值；其唯一的偏离是有害的。"** 这是一个完整、可辩护的负结论 |
| H1 成立 + H2 被否 | 需要进一步分析 λ=0 与 A0 的差异来源（可能是 deadline 并列） |
| H1 被否 | **所有此前的非零观测都应标记为不稳定**，结论改为"无稳定差异" |

**判据 4（翻转判据 H3 的否证）**

| 结果 | 判定 |
|---|---|
| 八个非 g05 组的 A1−SFED **全部为 0**，且 g05 不为 0 | **H3 成立**：判据可推广，可用于**预测**何时该用 λ |
| 任一组 A1−SFED ≠ 0 但 q_ratio > N_ratio | **H3 被否**：判据失效，A1 的行为不可预测 |
| g05 的 A1−SFED = 0 | 该 cell 在本次运行中未翻转 → 需查候选/队列是否变化 |

**不可判定条件（必须预先声明）**

- 若某 group 的两次 repeat 执行失败或 `checks` 任一为 false → 该 group 标为
  `UNEVALUABLE`，不纳入统计，且**不得事后替换**；
- 若 `selection_sequence` 记录缺失 → 该 group 的分歧判定为 `NOT_OBSERVABLE`。

## D8. 执行成本

| 项 | 估算 |
|---|---|
| Runs | 54 |
| 单 run wall | ≈ 33–36 s（engine init ≈30 s + native ≈3.4 s） |
| GPU 总计 | **≈ 32 分钟** |
| 存储 | 与 v10 同量级（archive ≈ 73 MB） |
| 分析 | 离线，复用现有脚本，≈ 1 小时 |

> GPU 不是瓶颈。真正成本是授权轮次与人工分析。

## D9. 该提案能支持什么结论

**能支持：**

- λ 项是否为本 workload 上唯一的确定性变异源；
- **A1.2b 的翻转判据是否可预测哪些 group 会翻转**（H3）——这是本提案最可证伪的部分；
- SFED（sufficient-first + earliest deadline）是否可作为最终方法的
  **可辩护简化**；
- 现有 4 个非零观测中哪些是稳定的。

**不能支持：**

- 任何关于 Block 层 cost-aware 价值的结论（本归档 A2 从未介入，且本提案不含 A2 臂）；
- 任何关于复用信号的结论（无数据）；
- 任何关于真实（非受控注入）负载的推广。

**若 M1 希望同时检验 Block 层**，需把 A2 臂加入，并**先完成两项修复**：
①让 `native_lru_victims` 成为真正独立的参照（当前是 `legal[:N]` 回显）；
②在块决策事件中**记录 legal 列表的排序依据与当时队列快照**，否则无法判断
是否发生了真实重排。当前 229 个块决策中仅 78 个能找到严格可比的快照。
这会使 Runs 增至 72（9 × 3 arms × 2 repeats 加 A2 臂 × 2 repeats）或需另行设计。

---

## 附录：全部实测数字的来源

| 数字 | 来源脚本 |
|---|---|
| 29 决策逐项、λ/ED/MO 吻合数、q span | `a1_decisions_detail.py` |
| **翻转判据 `q_ratio < N_ratio`，18/18 验证** | `a1_flip_criterion.py` |
| λ 消融（29/29 重放、2 次改变） | `a1_lambda_ablation.py` |
| 601 决策、434/167、身份状态、证据问题 | `a4_identity_gap.py` |
| `selected == legal[:N]` 601/601 | `a4_divergence_check.py` |
| legal 严格可比 78、tier 一致 71 / 不一致 7（**仅作快照同步性参考，不作结论**） | `a4_legal_strict.py` |
| 字段变异、ttl=0 139/139、deadline 无并列 | `a2_field_variation.py` |
| TTL 历史样本全 0、102 右删失 | `b2_signal_audit.py` |
| 共享块 224、超额 118.9×、need 1–114 | `b4_unlocked_vs_evicted.py` |
| run 耗时、指标复算 | `analysis/campaign-report-v2.json`、`execution-summary.json` |
