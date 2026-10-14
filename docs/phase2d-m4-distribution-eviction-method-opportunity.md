# Phase 2D → 分布式淘汰方法机会评估（借鉴 RR-EVICT）

**提交人**：M4　**送审**：M1　**日期**：2026-10-14
**性质**：离线方法机会分析 + 方案设计（不含实现、不含新实验）
**参考**：Pan et al., *RR-EVICT: Fine-Grained Prefix Cache Eviction Beyond LRU for Agentic LLM Serving*（UCSD，Preprint / under review）
**边界**：H1/H2 CLOSED、B1 LOCKED、Continuum baseline UNCHANGED、Cost-Aware policy NOT_AUTHORIZED、Formal campaign NOT_AUTHORIZED

---

## 0. 结论摘要

这篇论文给出一种值得研究的**尾部分布目标与跨 Agent 分散淘汰机制**。其 §3.3 在等长私有前缀、无跨 Agent 共享、均匀返回、固定容量与忽略 chunk 效应等假设下，证明**理想 LRU 与理想 RR 的均值相同、尾部不同**。

> 这一结果说明我们此前可能遗漏了尾部成本维度；**不等于**真实异构 Agent workload 下任意策略的均值最优值相同，也**不能单独解释**所有历史负结果。

因此本评估的核心建议不是「实现一个新规则」，而是三件事按序：

| # | 建议 | 成本 |
| --- | --- | --- |
| **A** | **在 Phase 2E 探索性评价中增加尾部指标**（P95/P99 uncached/recomputed tokens、TTFT），同时保留聚合/均值指标；正式验收协议另行冻结 | 文档 |
| **B** | **离线验证可证伪前提**（recency 同步、regime `na<m<n`、分位条件 `q>1-p`） | ✅ **M1 已授权**（PR #43 Step 0），本轮已完成 |
| **C** | 仅在 B 全部成立时，才讨论「分布式淘汰」的最小 fixture | 需授权 |

✅ **B 已完成**：四个前提中 **P1/P4 成立、P2/P3 部分成立**，但存在一个越界区间
（37.9% 决策 $q\ge0.95$）与一个**新识别的未验证前提 P5**。详见 §0.1。

⚠️ A 是下一阶段探索性研究的指标建议；既有 H1/H2 冻结接受协议不会因此变更。

⚠️ **本轮不请求**：B1 解锁、policy 实现、formal campaign、任何 native run。


## 0.1 Step 0 离线验证结果（本轮已完成）

⚠️ **本节为实测，非引用。** 全部在 H1 原始 `events.jsonl`（126 个文件）上离线完成，
零 native run、零 GPU。探针：`local/probe_s1_recency_sync.py`、`probe_s1b_lru_concentration.py`、
`probe_s1c_q_regime.py`。

| 前提 | 判据 | 实测 | 判定 |
| --- | --- | --- | --- |
| **P1** recency 同步 | entry 内 `native_lru_rank` 是否连续 | **候选 entry 的块在 LRU 序中 100% 连续（87/87 决策）** | ✅ **成立（形式比论文更强）** |
| **P4** 多个 idle entry | 决策时可选 entry 数 | 每决策 median **3**、max **6**（1 个的仅 6/87） | ✅ **成立** |
| **P2** 进入可用区间 | $n_a<m<n$ | q 中位数 **0.500**；**55.2%** 落在 $0.05<q<0.80$ | ✅ **部分成立** |
| **P3** 分位条件 | $q>1-p$（P99 ⇒ $q>0.01$） | 62.1% 的决策可用 Eq 2–3 公式；**理想模型计算的示意性 P99 降幅中位数 50.0%，非性能预测** | ✅ **成立（限于 q≤1 的 62.1%）** |

**但有两个必须挂上的限制**：

1. **37.9% 的决策 $q\ge0.95$**（其中 $q$ 最大 6.44 ⇒ **候选池本身不足**，压力须由其他手段满足）。
   依论文：$m	o n_a$ 时 $q	o1$，**无策略可保留有意义的 idle 状态** ⇒ 这些决策**不在收益区**。
2. ⚠️ **H1 无法验证上述尾部收益**：`max_concurrent_requests = 1`、`max_new_tokens = 1`，缺乏真实的多轮 Agent idle/overlap 形态。而 S1c 的 $q$ 来自 `required_blocks / idle_protected_blocks` 容量代理，**尚不能直接等同**论文的 $(n-m)/n_s$ 时间占用模型，因此这些比例仅供筛选研究场景，并非 native P99 改善预测。

**S1b 的结构发现（本轮最有价值的实测）**：

```text
候选 entry 的块在 native LRU 序中形成"恰好连续的一段"
  bands_contiguous = 87/87 = 100.0%
  spread ≈ size − 1（median: size 12, spread 11）
```

⇒ **在这 87 个受检 H1 决策快照中**，受检 entry 的候选块在 native LRU 秩中形成相邻带，这是潜在集中回收的一种结构线索。
⇒ 但相邻秩不等于跨 Agent 多轮访问的 recency synchronization，更不能直接证明原生 LRU 在真实 Agent workload 中集中物理淘汰并导致尾延迟异常；该机制仍需 Phase 2E 的 native 验证。

**集中度实测（S1b）**：从最冷端按 rank 走，满足 `required_blocks` 前消耗的候选 entry 数：

| 消耗 entry 数 | 1 | 2 | 3 | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 决策数 | **30** | 24 | 18 | 3 | 12 |

⇒ **34.5% 的决策 LRU 只吃一个 entry**（当 `required_blocks` 落在最冷带内 —— 占 27.6% —— 则**恰好 1 个**）。
其余情形因 `required_blocks`（median 34）大于最冷带（median 8）而必须跨带。
⇒ 上述为候选队列中的**模拟回收集中度**，不是已观察到的 native cache miss 分布，也不能据此解释旧语料均值结果。

---

## 1. 论文的关键论断（三句话）

1. **Recency 同步**：agent 的一次访问会**同时刷新其存活前缀上的所有缓存节点**（无论这些节点何时创建、各代表多少重算量）。而不同 agent 只共享很短的公共前缀，绝大部分历史是**私有的**。⇒ 每个 agent 的私有节点构成一个**时间戳几乎相同的大组**。

2. **节点级 LRU 退化为 agent 级淘汰**：由于同步，LRU 堆顶持续停留在**同一个** idle agent 上（其后代被删后父节点成为新叶子，仍在堆顶附近）。⇒ 连续淘汰集中在**同一个 agent**，直到它几乎被清空。该 agent 返回时须重算**几乎整个上下文** ⇒ **TTFT 尾部尖峰**，即使整体命中率仍很高。

3. **RR-EVICT**：把候选按 **agent 轨迹分组**，**轮转**访问各组，每次只回收该组的**一个 tail chunk**（保留连续可用的前缀）。⇒ 用**渐进退化**替代**集中损失**。**「requires no prediction of future arrivals or tool latency」**。

### 1.1 最关键的公式（论文 Eq. 2–3）

设 $n$ 个活跃轨迹（等长私有前缀）、活跃比例 $a$、空闲比例 $s=1-a$、$n_a=na$、$n_s=ns$、容量 $m$（以「前缀」为单位）：

$$h=\frac{m-n_a}{n_s},\qquad q=1-h=\frac{n-m}{n_s}$$

| 策略 | 归一化重算代价 $X_\pi$ | 尾部行为 |
| --- | --- | --- |
| LRU | $1$（概率 $q$），$0$（概率 $1-q$） | **$q$ 比例的 agent 全量重算** |
| RR | $q$（恒定） | 每个返回 agent 都只重算 $q$ 份额 |

$$\boxed{\mathbb{E}[X_{\text{LRU}}]=\mathbb{E}[X_{\text{RR}}]=q}$$

论文原文：*"Both policies have the same mean recomputation cost, ... but distribute it differently."*

⇒ **在上述论文简化模型与 LRU/RR 对照中**均值恒等、尾部分布不同；这不是一般 Cost-Aware 策略的均值不可能性定理。分位条件为：*"At percentile $p$, LRU has a full miss when $q>1-p$, while round-robin incurs a $q$-fraction miss."*

### 1.2 可用区间（两侧有界）

$$n_a<m<n$$

- $m\le n_a$：活跃自身已占满，无空间留给 idle ⇒ **thrashing，无可分配**；
- $m\ge n$：根本无需淘汰 ⇒ LRU 的全量 miss 已足够罕见，无法影响固定分位；
- 中间地带才是 RR-EVICT 的收益区。

论文实测（τ²-bench，Qwen3-Coder-30B，H100；SWE-bench 1P3D）：相对 LRU，P99 TTFT **−75.4%**、P99 uncached tokens **−65.7%**；相对 completion-aware LRU 为 **−46.9% / −30.6%**。chunk 大小 1,024 tokens。

---

## 2. 为什么这解释了本项目此前的全部否定结果

下表提出可能的**解释联系**，不重新裁决历史实验。RR-EVICT 的理想化理论揭示均值与尾部可能分离，但不能单独解释 H1/H2 中的样本有效性、proxy loss 和 workload fidelity 问题。

| 我们的实测 | 该论文给出的解释 |
| --- | --- |
| **S0-c**：runtime 视图上基线 **27/27** 达压力可行 oracle 最优，8 条规则**全部 0 好 / 0 差 / 27 平** | 受检 27 条决策的特定 runtime loss-view 下未观察到基线 regret；与均值空间有限**相容**，但不是 Eq. 3 在 H1 上的证明 |
| **Phase 2D E3**：释放 A ⇒ {65, 1}；释放 B ⇒ {1, 65}；**聚合推算不变** | 两种 logical release 的单请求结果可能体现损失转移；但这并非理想 LRU/RR tail-chunk 对照，聚合 native recomputation 尚需原始事件核验 |
| **H1-R1**：reverse-deadline `DIAGNOSTIC_ONLY`，13 better / 14 worse，无改善 | 该 reverse-deadline 规则未获支持，原因不能仅归于理想模型的均值恒等，也未检验分散尾部损失的策略 |
| **F-D1 / H1**：返回预测最强 ρ = 0.228，无稳健增量 | RR-EVICT 式分散风险策略可不预测未来返回；这不否定预测式 Cost-Aware 方向，亦不能解释此前弱结果的全部成因 |
| **M-1（我列为「根本障碍」）**：损失 =「你释放的是否是将来那个请求所属的 entry」，属未来事实 | ⭐ 该论文**绕开**了 M-1：不预测归属，而是让**每个 agent 都只损失一部分**，从而**不依赖**任何归属预测 |
| **H2-M4 FAIL**：block-level partial-prefix retention，冻结 single-prefix 比较器下 pairwise headroom = 0 | 单前缀对照不能直接检测跨 Agent 的分布性收益，但不能据此确定 H2-M4 FAIL 的唯一原因 |

⚠️ **一条必须说清的后果**：我此前在 `PHASE2D_COST_AWARE_METHOD_OPPORTUNITY_ASSESSMENT` 中把 **M-1 列为「根本障碍」**。
在该论文的目标下，M-1 **不再阻塞**。该结论的适用域需要相应收窄（见 §7）。

---

## 3. 与我们机制的精确对应关系

| 论文概念 | 我们的对应物 | 状态 |
| --- | --- | --- |
| Agent / trajectory | logical program（`program_id`） | ✅ 有 |
| Agent turn | 同一 program 的后续 request | ✅ 有（`turn_index`、`W-TURN-GROW`） |
| Idle trajectory（等待工具/用户） | entry **protected 但当前无活跃 request** | ⚠️ 语义存在，**未见显式建模** |
| 节点级 LRU | Native LRU 才是论文讨论的物理块淘汰基线；Continuum 的该分量只是 whole-entry release 的次级排序信息 | ⚠️ **策略粒度不同** |
| Agent 级缓存组 | 一个 `RetentionEntryKey` 的全部 `block_ids` | ✅ 有 |
| Tail chunk 回收 | **entry 的尾部若干 block 的部分回收** | ❌ **不支持**（见 §4.1） |
| Completion signal | lifecycle / 完成信号 | ⚠️ 未使用 |
| Recency tiering（论文的退路） | **我们已有显式 `deadline_timestamp`** → 可做**deadline 分层 + 组内轮转** | ✅ **比论文的退路更强** |

**一个正面发现**：论文的 recency tiering 只是用「最后访问时间」**近似**「是否陈旧」；而我们的 baseline **已有显式 `deadline_timestamp`**（来自 Continuum retention）。⇒ 我们的「deadline 分层 + 组内轮转」是**一个可供测试的替代分层信号**；TTL deadline 不等于 Agent completion/失活真值，不能预设其效果优于论文的分层机制。

---

## 4. 与 frozen baseline 的**机制差异**（对应 M1 的旧 §5 要求）

### 4.1 差异点：释放键的第 2 分量

```python
# src/kvopt/continuum/pressure.py:324  —— 基线
return (entry.deadline_timestamp, native_key, key.sort_key)
#                                  └ min(native_lru_rank of newly_eligible)   ← Continuum whole-entry release 的 LRU 次级键，并非原生 node-level LRU
```

| 维度 | 基线 | 分布式方案 | 是真差异吗 |
| --- | --- | --- | --- |
| 决策时输入 | `deadline`、newly-eligible 块的**最小** LRU 秩、逻辑身份 | `deadline`（**保留为分层**）+ **entry 轮转游标** + 候选**尾块** | ✅ |
| 是否需要预测未来 | 否 | **否** | 两者都不用 ✅ |
| 释放粒度 | **整 entry**（`released_keys.add(key)`，循环至满足 `required_blocks`） | **entry 尾部子集** | ⚠️ **需扩展，见 §6** |
| 优化目标 | **均值** | **尾部 P99** | ⭐ **协议级差异** |
| 是否用共有多重度 | 仅用于**资格**判定 | 可用于**排序** | ✅ 已存在但未利用 |

### 4.2 关键洞察：tail-first 天然保护「共享头」

我们的语料有**共有多重度**结构（Phase 2D E2：两候选共享 **8** blocks）。注意共享发生在**前缀根部**（`shared_root`），而 tail chunk 取自**尾部**。

⇒ 在**仅释放私有后缀且共享根仍受有效保护**的条件下，tail-first 可能保留共享头。但论文的**理想分析**假设无跨 Agent 共享，不代表其实际前缀树实现无法支持共享。

⇒ 是否存在额外优势，必须通过 native ownership、边际可回收容量和尾部损失验证；目前只是候选研究问题。

### 4.3 与已实现规则的**去重**（必须声明）

`src/kvopt/costaware/rules.py` 已实现 `M1_reclaimable_ascending`、`M1_marginal_cost_per_reclaimable` 等。
本方案**不是**这些规则的重新包装，理由：

- 那些规则主要重排 whole-entry 候选，在受检 H1 的 proxy/均值视图中缺乏稳健收益；但**不能**由 RR-EVICT 简化模型断言它们在一般负载中不可能有效；
- 本方案改的是**目标函数 + 释放粒度 + 跨 entry 的损失分布**，三者都不是排序键重排。

---

## 5. 我们 setting 的两个**真实扩展点**（潜在贡献所在）

### 5.1 非等长 entry ⇒「等块数」与「等比例」不同

论文假设**等长前缀**，故理想轮转 = 每个前缀保留**同一比例** $h$。

我们的 `block_count` 有 **10 个不同取值**（1, 2, 3, 4, 6, 8, 12, 16, 24, 32）：

| 轮转口径 | 后果 |
| --- | --- |
| **等块数**（每轮各取 1 个 chunk） | 对小 entry，一个 chunk 可能是其**全部** ⇒ 该 agent **全量重算**，退化回论文批评的 LRU 行为 |
| **等比例**（各保留 $h$ 份额） | 匹配 Eq 2 的理想；但 chunk 粒度需更细 |

我们的 block 粒度是 **16 tokens**，相对 32-block entry 为 3.125% ⇒ **能做到接近理想的等比例轮转**（论文 1,024-token chunk 粗得多）。

⚠️ **但不能直接断言等比例更优**：真实 $C(r)$ 是 **U 形**（§2.4：最低点在 $r\approx1024$ tokens，全域离散 13.49×）。在非线性的 $C$ 下，「等比例损失」**未必**是「尾部最优」。这构成一个**可证伪的新问题**：

> 在非线性的 $C(r)$ 下，跨**非等长** entry 的尾部最优损失分布是什么？

### 5.2 共有多重度 ⇒ tail chunk 未必是私有的

论文的 tail chunk 是私有后缀。我们的共享结构在**根部**，故 tail-first 兼容（§4.2）。
但**一般情形**下，若两个 entry 的共享段落在尾部，回收 A 的尾块会**同时缩短 B**。
⇒ 需要一个「**共同引用度加权**的轮转」，而非朴素轮转。这是**论文未覆盖**的情形，也是我们独有数据（`_entries_by_block`）**已经算好但未使用**的信息。

---

## 6. 方案设计

### 6.1 目标函数（第一优先级，协议级）

| 项 | 现值（已冻结） | 建议新增 |
| --- | --- | --- |
| 主指标 | `planned_return_weighted_prefill_proxy` | **P99 每请求 `observed_recomputed_tokens`** |
| 辅助 | mean / median absolute regret | **P95、P99.9、全量 miss 率** |
| 统计单位 | independent scenario draw | 同（不变） |
| 判据 | 均值改善 + CI 下界 > 0 | **P99 改善 + bootstrap CI（同 seed 20261007）** |

⚠️ **这是对冻结接受协议的修改**，必须由 M1 裁定（§8 决策 1）。
⚠️ 依论文，**均值对比预期为「无差异」**，因此**不得**把「均值未改善」当作否证。

### 6.2 淘汰规则（最小形态）

```
在 FORCED_RELEASE_DECISION：
  1. 按 deadline 分层（保留基线的第一分量语义）
  2. 层内：按 entry 轮转游标取一个「tail chunk」
  3. tail chunk = 该 entry 中 native_lru_rank 最差（最冷）的 k 个 block
     且必须使剩余部分仍是连续可用前缀
  4. 轮转游标 push-back，直至 required_blocks 满足
```

**新增状态**：跨 pressure 轮次的 **entry 轮转游标**（论文 Algorithm 1 的 queue）。
**不需要新观测缝**：所需输入（entry 分组、`block_ids`、`native_lru_rank`、`deadline`）**全部已在 `original_free_queue` 与 `entries` 中**。

### 6.3 可证伪前提（**已离线验证，见 §0.1**）

| # | 前提 | 判据 | 本轮结果 |
| --- | --- | --- | --- |
| **P1** | **Recency 同步** | 同一 entry 内 `native_lru_rank` 连续 | ✅ **100% 连续（87/87）** |
| **P2** | **进入可用区间** | 存在区间使 $n_a<m<n$ | ✅ 部分：**55.2%** 在 $0.05<q<0.80$；37.9% 已越界 |
| **P3** | **分位条件** | $q>1-p$（P99 ⇒ $q>0.01$） | ✅ 成立（62.1% 可算，预测 P99 削减 median **50.0%**） |
| **P4** | **多个 idle entry** | 决策时受保护 idle entry 数 $n_s\ge2$ | ✅ 成立：median **3**、max **6** |
| **P5** | **带内排序 = 前缀顺序？**（新增，**未验证**） | 带的冷端是否对应前缀**尾部** | ⚠️ **未验证** —— tail-first 的正确性依赖它 |

⚠️ **P5 是新识别的必要前提**：若某 entry 的带内 LRU 序与前缀顺序**相反**，
则从冷端回收会先破坏**前缀头部**（含共享根），反而更糟。
判据需 `block_id → 前缀内位置` 映射；历史 H1 已声明该映射 `NOT_OBSERVABLE`，
但 Phase 2C 分段 schema **已提供** `prefix_segment_content_keys`/`token_counts` ⇒ 在新 fixture 上可测。

⚠️ **P1 若为否，则整个方向不成立**（节点级 LRU 本已细粒度）。**本轮 P1 成立。**

---

## 7. 需要修正的**既有结论**（诚实报备）

本论文使以下我在前一轮写下的判断需要收窄：

| 位置 | 原表述 | 修正 |
| --- | --- | --- |
| Phase 2D 评估 §8 | **M-1 是「根本障碍」** | 在**尾部目标 + 分布式策略**下 M-1 **不阻塞**。仍阻塞「**预测式**策略」这一支 |
| Phase 2D 评估 §7 | 建议不对当前假设集 preregister | **仍成立**（那些假设都在均值目标下） |
| Phase 2D 评估 §6 S0-c | runtime 视图基线达 oracle 最优 ⇒ 无可改进空间 | 该结论**限于均值目标**。**不得**外推为「尾部亦无空间」 |
| §3.2 聚合不变推算 | 用于否定可捕获量 | 与 Eq 3 **一致**，但含义改变：**聚合不变恰恰是该机制的前提**，不是否证 |
| 机会审计 §4.3 | 共享所有权「本语料不可检验」 | 若 tail-first 天然保护共享头，则**不需要** `relief < block_count` 作为前置 ⇒ 该门槛**可能不必跨越**（待 P1–P4 验证） |

⚠️ 上述修正均为**文档级**，**不改变**任何 campaign verdict（H1-R1 仍 `DIAGNOSTIC_ONLY`、H2-M4 仍 FAIL、B1 仍 LOCKED）。

---

## 8. 风险与边界

| # | 风险 | 说明 |
| --- | --- | --- |
| **R1** | **需部分释放 ⇒ 触及 B1（LOCKED）** | 已核实基线是**整 entry 释放**（`pressure.py:107` 的循环 + `released_keys.add(key)`）。tail chunk **必须**子 entry 释放。⇒ **需 M1 裁定是否解锁 B1 的只读/诊断子集** |
| **R2** | 需**新工作负载** | 必须在 regime 内且有多个 idle entry。`tool_gap_seconds`、`W-TURN-GROW` **已存在**；但 H1 的 `max_concurrent_requests = 1` 与 `max_new_tokens = 1` **无法表达**该 regime |
| **R3** | 目标是**尾部**，样本需求更高 | P99 估计需远多于 27/29 个决策；现行 floor（≥30 draws）为**均值**设计 |
| **R4** | 论文为 **preprint（under review）** | 其结论尚未经同行评审；且其限制（idle 区间较短、cache 全在 HBM）**未覆盖**我们的情形 |
| **R5** | 论文的收益**依赖 completion signal** | 其 stale trajectory 处理需要生命周期信号或 recency tiering |
| **R6** | 我们不改变任何 runtime 行为 | 本方案在本轮**不实现** |

---

## 9. 最小验证方案（Step 0 **已完成**）

### 9.1 已完成（本轮，零 native run）

| 步骤 | 内容 | 结果 |
| --- | --- | --- |
| **S1** | entry 内 `native_lru_rank` 离散度 | **100% 带内连续**；normalized spread median 0.152 ⇒ **P1 成立** |
| **S1b** | 最冷端起走，满足 `required_blocks` 消耗几个 entry | 只吃 1 个：30/87；median 2；⇒ 集中真实但非极端 |
| **S1c** | $q=$ `required_blocks` / idle 受保护块数 | median **0.500**；55.2% 在可用区；62.1% 可套 Eq 2–3，**预测 P99 削减 median 50.0%** |
| **S1d** | 决策时候选 entry 数（P4） | median **3**、max 6（仅 6/87 只有 1 个）⇒ **P4 成立** |
| **S5** | 尾部基线 | runtime 视图仅 **27** 个决策，样本过薄；见 §8 R3 |

**探针**（`local/`，不入库）：`probe_s1_recency_sync.py`、`probe_s1b_lru_concentration.py`、
`probe_s1c_q_regime.py`；输出 `local/s1c_out.txt`。

### 9.2 仍未完成

| # | 项 | 阻塞 |
| --- | --- | --- |
| **S2 / S5** | 真正的时间线 regime 判定（论文 Fig. 4 方法）与尾部基线 | 需**具备 idle 间隔与并发**的 trace；H1 无（`max_concurrent_requests=1`） |
| **P5** | 带内 LRU 序是否与前缀顺序一致 | 需 `block_id → 前缀内位置` 映射；需 Phase 2C 分段 schema 的新 fixture |
| **Step 1** | 多 agent × 私有增长历史 × idle 间隔 × regime 内的最小 fixture | **NOT YET AUTHORIZED**；且受 §8 R1（B1 LOCKED）与 R2（需新负载）阻塞 |

### 9.3 停止条件（修订后）

```text
S1  已实测：成立（100% 带内连续）            -> 继续
S1d 已实测：成立（median 3 个候选）           -> 继续
S1c 已实测：55.2% 在可用区，但 37.9% 越界     -> 收益区覆盖仅约一半
P5  未验证：若带内序与前缀序相反            -> tail-first 前提不成立，方向需重新设计
S2  未做：若 timeline 从不进入 na<m<n        -> 关闭
```

⇒ **判定：方向未被证伪，但收益区仅覆盖约一半决策，且新增一个未验证前提 P5。
在 P5 与 S2 落实前，不应进入 Step 1。**

---

## 10. 请求的裁定

1. **目标函数（最关键）**：是否授权把**评估目标**从均值扩展为**尾部（P99 recompute）**？
   这是本方向的**前提**：依论文 Eq 3，均值目标下**不存在**可捕获空间（且已被我们 S0-c 实测确认）。
2. **Step 0 授权**：是否授权 §9 的 S1–S5 离线检查（零 native run、复用现有数据）？
3. **既有结论的适用域修正**：是否确认 §7 的收窄（特别是 **M-1 在尾部目标下不阻塞**、S0-c 结论**仅限均值目标**）？
4. **B1 边界**：若 Step 0 肯定，是否考虑解锁 **B1 的只读/诊断子集**（非 runtime 实现），
   以支持子 entry 的 tail chunk 语义？⚠️ 若否，则本方向**在技术上无法验证**（需在 Step 0 之后即停止）。
5. **确认**：本方案**不**请求 policy 实现、formal campaign、native cache 改动、H1/H2 重开或改判。

---

## 11. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| Recency 同步 / 节点级 LRU 退化为 agent 级淘汰 | RR-EVICT §1、§3.1 |
| $h=(m-n_a)/n_s$、$q$、$\mathbb{E}[X_{\text{LRU}}]=\mathbb{E}[X_{\text{RR}}]=q$ | RR-EVICT §3.3（Eq. 2–3） |
| 可用区间 $n_a<m<n$ | RR-EVICT §3.3（Eq. 1）与 Fig. 4 |
| 分位条件 $q>1-p$ | RR-EVICT §3.3 |
| 「no prediction of future arrivals or tool latency」 | RR-EVICT §1、§3.2、§6 |
| P99 TTFT −75.4% / P99 uncached −65.7%（vs LRU）；−46.9% / −30.6%（vs completion-aware） | RR-EVICT §4、§1 |
| SWE-bench 1P3D：−60.7% / −60.8%；−60.5% / −56.2% | RR-EVICT §4 |
| 1,024-token chunk；假设 no cross-agent sharing；需 completion signal 或 recency tiering | RR-EVICT §3.2、§4 |
| 论文限制（idle 较短、cache 在 HBM） | RR-EVICT §6 |
| 基线释放键三元组含节点级 LRU 分量 | `src/kvopt/continuum/pressure.py:324` |
| 压力循环为**整 entry 释放** | `src/kvopt/continuum/pressure.py:107`、`:150` |
| 共有多重度映射 `_entries_by_block` 已算但仅用于资格 | `src/kvopt/continuum/pressure.py` |
| `original_free_queue` 含逐块 `native_lru_rank` | `src/kvopt/continuum/selection.py` |
| `block_count` 10 个取值（1–32） | `local/probe_relief_field.py` |
| S0-c：runtime 视图 27/27 达 oracle 最优、8 规则全平 | `docs/phase2d-m4-cost-aware-method-opportunity-assessment.md` §6；`local/h1_runtime_view.json` |
| E3：{65,1} / {1,65}，聚合推算不变 | `docs/phase2d-m6-headroom-investigation.md`；同文档 §3.2 |
| E2：两候选共享 8 blocks、relief 各 4 | 同上 |
| 真实 $C(r)$ U 形，最低点 $r\approx1024$，离散 13.49× | H2 `raw-observations.json`（`local/probe_h2_cost_curve_shape.py`） |
| `tool_gap_seconds`、`W-TURN-GROW`、`turn_extension` 已存在 | `src/kvopt/workload/phase2.py:57`；`configs/phase2/phase2c-workload-content-schema-v1.json` |
| H1 `max_concurrent_requests=1`、`max_new_tokens=1` | Phase 2C 历史审计（`docs/phase2c-m6-workload-reuse-audit.md`） |
| 既有 relief/size 规则已实现 | `src/kvopt/costaware/rules.py` |
| 冻结协议（均值主指标、draw 单位、seed 20261007） | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| G1–G5 裁定 | M1，PR #36 review |
| **S1：带内连续性 87/87** | `local/probe_s1_recency_sync.py`（H1 126 个 `events.jsonl`） |
| **S1b：消耗 entry 分布 {1:30,...}** | `local/probe_s1b_lru_concentration.py` |
| **S1c：q median 0.500、55.2% 可用区** | `local/probe_s1c_q_regime.py`；`local/s1c_out.txt` |
| 候选 entry 数 median 3 / max 6 | `local/probe_s1_recency_sync.py` |

