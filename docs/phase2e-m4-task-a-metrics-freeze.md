# Phase 2E 任务 A — 指标冻结与观测需求

**提交人**：M4　**送审**：M1　**执行方**：M6　**日期**：2026-10-14
**任务**：Phase 2E — LRU Failure Mode & Cost-Aware Opportunity Study
**本文件范围**：M1 §三「任务 A：冻结 Phase 2E 的研究指标」+ §六「交给 M6 的指标与观测需求清单」
**性质**：**指标定义与观测需求**。未实施策略、未新增 native run、未改动任何既有裁决
**边界**：H1/H2 CLOSED、B1 LOCKED、Cost-Aware policy NOT_AUTHORIZED、Formal campaign NOT_AUTHORIZED

---

## 0. 冻结声明

本文件**冻结 Phase 2E 的指标口径、统计单位、证据分级与缺失性处理**。

⚠️ **冻结后不得依据早期有利结果临时更改主要指标或 workload 分布**（M1 §六）。
探索性测量契约如因 native smoke 暴露观测缺口而确需修订，应在正式 measured execution 前**版本化记录变更及理由**；不得依据早期效果方向事后修改主要指标。正式 preregistration 仍属于未来单独阶段。

⚠️ **A2 的阈值（θ、κ）标为 `PROVISIONAL`**，等待 M1 裁定。

---

## 1. 通用约定

### 1.1 统计单位（不变）

```text
seed repetition        -> 运行噪声 / 可复现性，不是独立样本
同一 scenario 内的 request / decision  -> 不是独立样本
统计单位               -> 一个独立 scenario draw
聚合顺序               -> seeds → positions/requests → scenario
```

沿用 `docs/phase2a-m4-rule-acceptance-protocol.md` §1（**M1 ruling**）。

### 1.2 尾部指标的两个视图（必须分别标注）

| 视图 | 定义 | 用途 |
| --- | --- | --- |
| **D 视图（描述性）** | 把 scenario 内**全部请求**池化后算分位 | **机制发现**、画分布 |
| **I 视图（推断性）** | **先在每个 draw 内算分位**，再跨 draw 配对比较 | 任何**结论性**主张 |

⚠️ **禁止把 D 视图的分位数当真伪判据**：在 36 draws 上池化请求会**伪重复**（pseudo-replication）。
本阶段仅用于描述（§1.5）。

### 1.3 证据分级（对应 M1 §A3）

| 级别 | 含义 | 可否用于因果主张 |
| --- | --- | --- |
| **`NATIVE_OBSERVED`** | runtime 直接发出（时间戳、token 计数、hash 链、淘汰事件） | ✅ 可作事实 |
| **`OFFLINE_DERIVED`** | 由原生字段 + 已声明输入经确定函数得到 | ✅ 可陈述派生事实；因果性仍取决于识别设计，须列明函数与输入 |
| **`ASSOCIATION_ONLY`** | 仅时间/空间共现，**无隔离** | ❌ **不得**作因果 |
| **`NOT_OBSERVABLE`** | 所需观测缝不存在 | ❌ 须显式报告缺口 |

### 1.4 指标命名的强制后缀

每个上报数值必须带**三标签**：

```text
metric_name  : value
unit         : scenario-draw | per-request | share
evidence     : NATIVE_OBSERVED | OFFLINE_DERIVED | ASSOCIATION_ONLY
view         : D | I
```

### 1.5 本阶段的统计效力边界（M1 §A2 明确）

⚠️ **36 draws 不足以自动支撑高置信度 P99 统计结论。**

因此本阶段：

```text
允许 : 描述性分位、机制发现、失败模式识别、方向性对照
不做 : 正式置信区间、P99 显著性检验、接受阈值
```

正式的 CI / P99 检验 / 接受阈值**留待后续独立 preregistration**。

---

## 2. A1 — 聚合效率指标

### 2.1 指标表

| ID | 指标 | 定义 | 单位 | 证据 | 必需字段 |
| --- | --- | --- | --- | --- | --- |
| **A1.1** | `aggregate_recomputed_tokens` | $\sum_i (E_i-C_i)$；只统计此前证据可认定可复用的前缀缺失 | scenario-draw | OFFLINE_DERIVED | `eligible_prefix_tokens`、`native_cached_prefix_tokens`、同进程内容证据 |
| **A1.1a** | `aggregate_actual_prefill_tokens` | $\sum_i (N_i-C_i)$；实际输入 prefill 工作量，**包含自然新增内容** | scenario-draw | OFFLINE_DERIVED | `native_prompt_tokens`、`native_cached_prefix_tokens` |
| **A1.1b** | `aggregate_new_suffix_tokens` | $\sum_i (N_i-E_i)$；首次出现/自然增长的 token | scenario-draw | OFFLINE_DERIVED | `native_prompt_tokens`、`eligible_prefix_tokens` |
| **A1.2** | `mean_recomputed_tokens_per_request` | `A1.1 / 全部预期请求数`，必须先检查请求完整性 | per-request | OFFLINE_DERIVED | 同 A1.1 + expected request manifest |
| **A1.3** | `mean_ttft_seconds` | $\operatorname{mean}(\text{first\_token}_i - \text{queued}_i)$（**native queued-to-first**，非必然用户端到端 TTFT） | scenario-draw | OFFLINE_DERIVED | `native_first_token_timestamp`、`native_queued_timestamp`、同 clock domain |
| **A1.4** | `aggregate_admission_to_first_token_seconds` | $\sum_i (\text{first\_token}_i - \text{admission}_i)$；包含调度/执行影响，**非 isolated GPU prefill** | scenario-draw | OFFLINE_DERIVED | `native_scheduler_admission_timestamp`、`native_first_token_timestamp` |
| **A1.5** | `cache_reuse_efficiency` | $\sum_i C_i / \sum_i N_i$ | share | OFFLINE_DERIVED | `native_prompt_tokens`、`native_cached_prefix_tokens` |

### 2.2 Token 语义与 TTFT 的强制分解

沿用 `src/kvopt/profiling/runtime_evidence.py::derive_level_b_token_semantics` 的冻结定义：

```text
N_i = native_prompt_tokens；E_i = eligible_prefix_tokens；C_i = native_cached_prefix_tokens
约束：0 <= C_i <= E_i <= N_i
actual_prefill_i = N_i - C_i = (E_i - C_i) + (N_i - E_i)
recomputed_i     = E_i - C_i     （先前可复用内容当前未命中）
new_suffix_i     = N_i - E_i     （新输入/增长；不得归为淘汰损失）
```

`E_i` 需以当前 hash 与兼容的先前 prefix snapshot 推导；缺少有效的历史内容 provenance 时不能用 `N_i` 冒充 `E_i`。即使 `E-C>0`，无淘汰因果证据也不得称为“LRU 导致的重计算”。

```text
TTFT_i = (admission_i - queued_i)   +   (first_token_i - admission_i)
         └ A1.6 queue_delay_seconds     └ A1.4 admission-to-first
```

⚠️ **为何必须分开报**：RR-EVICT 指出延迟收益部分来自**避免超长 prefill 引发的 head-of-line blocking**。
在 `max_concurrent_requests = 1` 下队列分量**退化**（实测 H1 最大 queue delay 仅 **0.006 s**），
即使并发为 1，token 尾也不一定与 TTFT 尾等比例；并发 >1 时还可能进一步引入排队与调度差异。

⇒ **A1.6 `mean_queue_delay_seconds` 与并发度必须与 A1.3 同时上报**，否则延迟结论不可比。

### 2.3 ⭐ 关键：聚合变化 vs 单请求再分配（M1 §A1 明确要求，E3 教训）

仅报 `A1.1` 会**掩盖** Phase 2D E3 暴露的问题：某种选择可能**只是把损失在 agent 间转移**。

因此凡涉及**对照臂**（counterfactual / baseline vs candidate）的比较，**必须同时上报**：

| ID | 指标 | 定义 |
| --- | --- | --- |
| **A1.7** | `aggregate_delta_tokens` | $\sum_i \Delta_i$，其中 $\Delta_i = \text{rec}_i^{\text{armB}} - \text{rec}_i^{\text{armA}}$ |
| **A1.8** | `gross_request_level_change_tokens`（兼容旧别名 `abs_redistribution_tokens`） | $\sum_i |\Delta_i|$（**毛变化量**，不全等于实际转移量） |
| **A1.9** | **`NGR`（net-to-gross ratio）** | $\dfrac{\left|\sum_i \Delta_i\right|}{\sum_i |\Delta_i|}$ |

**`NGR` 仅刻画净变化相对毛变化的比例，不提供收益方向。** 令 `Δ_i = rec_i(armB) - rec_i(armA)`，则 `aggregate_delta_tokens < 0` 表示 B 比 A 少重算，`> 0` 表示 B 更多；**是否减少总体成本必须首先由带符号的聚合量判断**。`NGR=1` 也可能是全面退化；`NGR<0.5` 仍可存在真实净节省，只能额外描述为 `REDISTRIBUTION_HEAVY_DIAGNOSTIC`，**不得设 0.5 硬收益门槛**。

`Σ|Δ_i| = 0` 时 NGR 为 `NOT_APPLICABLE_ZERO_GROSS`，不能填 0 或 1。计算前须一对一匹配 scenario、request identity 和完整返回序列；若任一臂预期请求缺失/无法匹配，则标 `NOT_COMPARABLE` 并报告 missingness，不得静默减少分母。基线与候选比较属于**策略级配对观察**，本身不证明某一次 physical eviction 的因果贡献。

**观测性（非对照）场景的替代量**：无配对臂时，改用
**A1.10 `within_scenario_recompute_gini`**（见 A2.6）刻画 `E-C` 在 agent 间的分散程度，且应同时报告各 agent 的请求次数，以免混淆活跃度与损失程度。

### 2.4 缺失性

若 `native_prompt_tokens`、`native_cached_prefix_tokens` 或有效的 `eligible_prefix_tokens` 缺失 ⇒ `A1.1` 记 `NOT_COMPUTABLE`（不能回退为 `N-C`）；`A1.1a` 仅要求 N/C，但须单独标注口径。
并附 reason code；**不得插补**，**不得静默丢弃**（沿用 `docs/phase2a-m4-missingness-semantics.md` 与 issue #34）。

---

## 3. A2 — 尾部损失指标

### 3.1 指标表

| ID | 指标 | 定义 | 单位 | 证据 | view |
| --- | --- | --- | --- | --- | --- |
| **A2.1** | `p95/p99_recomputed_tokens` | scenario 内请求级 `recomputed` 的 P95/P99 | per-request | OFFLINE_DERIVED | D + I |
| **A2.2** | `p95/p99_ttft_seconds` | 同上的 TTFT 分位 | per-request | OFFLINE_DERIVED | D + I |
| **A2.3** | `max_single_request_recomputed` | $\max_i \text{rec}_i$ | per-request | OFFLINE_DERIVED | D |
| **A2.4** | `worst_agent_cumulative_recovery` | $\max_{a} \sum_{i \in a} \text{rec}_i$ | tokens | OFFLINE_DERIVED | D |
| **A2.5a** | `native_miss_rate` | 请求中 `apc_outcome == MISS` 的比例 | share | OFFLINE_DERIVED（**派生标签**，见 §4.3 R3） | D |
| **A2.5b** | `severe_loss_rate` | 只在 $E_i>0$ 的可复用请求中统计 `(E_i-C_i)/E_i > 1-θ` 的比例；$E_i=0$ 为 `NOT_APPLICABLE_NO_ELIGIBLE_PREFIX` | share | OFFLINE_DERIVED | D |
| **A2.6** | `inter_agent_concentration` | **top1_share** $=\max_a R_a / \sum_a R_a$ 与 **agent_gini** | share | OFFLINE_DERIVED | D |

⚠️ `θ=0.25` 与 `κ=512`（基于 `E-C` 的绝对损失）仅为探索性敏感性参数，不是正式接受阈值，也不是具体 eviction 因果证据。必须报告 $E=0$、不适用数量及有效分母。

### 3.2 ⭐ 强制：尾部重计算量 vs 实际 P99 TTFT（M1 §A2 明确要求）

⚠️ **不得假设 token 成本下降等比例转化为延迟收益。** 本阶段须**实测传递关系**：

| ID | 指标 | 定义 |
| --- | --- | --- |
| **A2.7** | `rho_recompute_ttft` | 请求级 $\rho_{\text{Spearman}}(\text{recomputed}_i, \text{TTFT}_i)$ |
| **A2.8** | `tail_transfer_ratio` | $\dfrac{\text{p99 TTFT} / \text{median TTFT}}{\text{p99 rec} / \text{median rec}}$ |

**读法**：A2.8 仅描述两种指标相对于自身中位数的尾部放大程度；接近 1 不能证明 tokens 可代理 TTFT，超过 1 也不能直接归因于排队/调度。若分母所需中位数为零或缺失，标 `NOT_APPLICABLE`。

⇒ 任何「改善尾部」的主张**必须同时给出 A2.1 与 A2.2**，并报告 A2.7/A2.8。

### 3.3 集中度的口径说明

`A2.6` 是**观测性的请求/Agent 损失分布**指标，不需要配对臂，但不能单独证明 LRU 物理淘汰集中。应同时上报 Agent 请求数与可复用前缀总量。

⚠️ 与 RR-EVICT 理论模型的落差须显式报告：其模型预测 LRU 令 $q$ 比例的 agent **全量**受损；
`top1_share` 与论文归一化单请求损失变量不是同一种量，不能直接用 1.0 对比判定模型是否匹配；必须考虑 Agent 数量、活动次数与可复用内容长度。

---

## 4. A3 — Eviction 归因指标（M1 §A3）

### 4.1 证据链的八个环节与可得性

| # | 环节 | 事件 | 分级 | Phase 2C/2D 实测可得性 |
| --- | --- | --- | --- | --- |
| 1 | 决策时合法候选 | `FORCED_RELEASE_DECISION.payload.candidates` | `NATIVE_OBSERVED` | ✅ |
| 2 | Native LRU 顺序 | 同事件的 `original_free_queue[].native_lru_rank` | `NATIVE_OBSERVED` | ✅ |
| 3 | Logical retention release | `selected_releases` | `NATIVE_OBSERVED` | ✅ |
| 4 | Native physical hashed eviction | `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` | `NATIVE_OBSERVED`（事件）/ ⚠️ **内容身份不可得** | ⚠️ H1 中 5757/5757 `identity_kind = block_slot_only`，`native_hash_hex` 全 null |
| 5 | Prefix residency | `VLLM_PREFIX_SNAPSHOT` + `_eligible_prefix_tokens` | `OFFLINE_DERIVED` | ✅ |
| 6 | 后续 APC hit/miss | `apc_outcome` | `OFFLINE_DERIVED`（**由 (eligible, cached) 派生，非独立上报**） | ✅ |
| 7 | Agent 返回请求 | `VLLM_NATIVE_REQUEST_OBSERVATION` / `VLLM_REQUEST_COMPLETED` | `NATIVE_OBSERVED` | ✅ |
| 8 | 实测重算 / TTFT | 时间戳与 token 计数 | `NATIVE_OBSERVED` 输入 / `OFFLINE_DERIVED` 差 | ✅ |

### 4.2 三条强制归因规则

> **R1（禁止越层归因）**
> 一个请求发生 miss，**不得**据此认定它来自某次次优 eviction。
> 归因到**具体某次淘汰**需同时满足：
> (a) 淘汰事件与 miss **处于同一 native hash process**；
> (b) 该淘汰块的**内容身份可解析**。
> ⚠️ 在 H1 语料中 (b) **不成立**（§4.1 第 4 行）⇒ **对具体淘汰的归因判 `NOT_IDENTIFIABLE`**。
> **Phase 2E 必须要求内容身份可得**（§7 O2）。

> **R2（因果需反事实）**
> 观测性共现（「淘汰发生在 miss 之前」）**只能**标 `ASSOCIATION_ONLY`。
> 因果主张**必须**来自配对臂（同一 scenario、同一决策点、仅干预项不同）。

> **R3（派生标签不得充当独立验证）**
> `apc_outcome` 是 `(eligible, cached)` 的确定函数 ⇒ 它**不能**用来独立验证 `recomputed = eligible − cached`。
> 同理 `eligible` 由 prior prefix snapshot + hash 前缀比较派生 ⇒ **不依赖淘汰台账**。
> 引用这两个量时必须标 `OFFLINE_DERIVED` 并给出派生函数。

### 4.3 每个环节允许的主张强度

| 主张 | 允许的最高强度 | 条件 |
| --- | --- | --- |
| 「某决策点存在多个合法候选及其几何」 | 事实 | 环节 1 |
| 「候选在 native LRU 序中的位置关系」 | 事实 | 环节 2 |
| 「哪个 entry 被逻辑释放」 | 事实 | 环节 3 |
| 「某块在物理上被 hashed 淘汰」 | 事实 | 环节 4（身份为槽位级） |
| 「某 entry 的 X% 前缀仍可复用」 | 派生事实 | 环节 5，须列函数 |
| 「该请求发生 miss / partial」 | 派生事实 | 环节 6，须标派生 |
| 「**此次淘汰导致了**该 miss」 | **`NOT_IDENTIFIABLE`**（H1） | 需 R1 两条件 + R2 反事实 |
| 「淘汰顺序改变会降低聚合重算」 | **`ASSOCIATION_ONLY`** 或需配对臂 | R2 |

---

## 5. 缺失性处理（统一）

| 规则 | 内容 |
| --- | --- |
| **M1** | 任何指标若必需字段缺失 ⇒ 记 **`NOT_COMPUTABLE`** + reason code |
| **M2** | **禁止插补**；**禁止静默丢弃** |
| **M3** | 每个 scenario/baseline 上报一张 **missingness summary**（缺什么、多少、为何） |
| **M4** | 缺失率 > 10% 的指标在结论中标注 `LOW_COVERAGE`，不得单独承载主张 |
| **M5** | 排除（exclusion）必须与「未观测（missing）」**分开计数** |

---

## 6. 任务 A 的可测量性实测（本轮已完成，H1 语料）

⚠️ **本节是实测，用于证明上述指标**不是**纸上定义。探针：`local/probe_a_measurability.py`、
`local/probe_a_tail_transfer.py`（H1 的 126 个 `events.jsonl`，1068 条请求观测）。

### 6.1 字段可得性

| 字段 | 填充率 |
| --- | ---: |
| `native_prompt_tokens` | **1068/1068 = 100%** |
| `native_cached_prefix_tokens` | **100%** |
| `native_queued_timestamp` | **100%** |
| `native_scheduler_admission_timestamp` | **100%** |
| `native_first_token_timestamp` | **100%** |
| `native_apc_block_hashes` / process / hash fn / block size | **100%** |
| `isolated_native_prefill_elapsed_seconds` | **0%**（H2 专用字段；**A1.4 必须用时间戳差**，不得用该字段） |

### 6.2 TTFT 可算且可分解

```text
monotone orderings (queued <= admission <= first_token) : 1068
VIOLATIONS                                              : 0
```

| 量 | min | median | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| **TTFT = first_token − queued** | 0.0074 | 0.0331 | 0.2939 | **1.1137** |
| queue delay | 0.00002 | 0.00014 | 0.00030 | 0.0060 |
| prefill→first | 0.0074 | 0.0329 | 0.2937 | 1.1133 |
| recomputed tokens | 1 | 97 | 544 | 2400 |

⇒ **A1.3 / A1.4 / A1.6 / A2.2 全部可算**。
⚠️ queue delay 最大仅 **0.006 s** ⇒ 在 `max_concurrent_requests = 1` 下队列分量**退化**，
验证了 §2.2 的强制分解要求。

### 6.3 ⭐ 尾部形状与传递率（对应 A2.7 / A2.8）

| 量（归一化到各自中位数） | p50 | p90 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| recomputed tokens | 1.00 | 5.29 | 5.61 | **14.85** | 24.74 |
| TTFT | 1.00 | 5.88 | 8.94 | **14.01** | 33.66 |

$$\rho_{\text{Spearman}}(\text{recomputed}, \text{TTFT}) = \mathbf{0.4327}$$

⇒ 旧 H1 的**报告性探索结果**提示 token 与延迟并非严格同序（$\rho = 0.43$）。此处 probe 位于 `local/`，未纳入 PR；Phase 2E 需要由归档与 evaluator 可复算，不能据此作新方法的性能主张。
`tail_transfer_ratio`（A2.8）在 p95 上 $= 8.94/5.61 \approx 1.59 > 1$
⇒ 两种分位放大程度不同，但不足以定量归因其来源，因此必须直接上报真实 TTFT。

### 6.4 集中度（A2.6）

| 量 | 实测 |
| --- | ---: |
| 累计重算 top-1 agent 占比 | **24.2%** |
| top-3 agent 占比 | 59.8% |
| 单 run 内 max-agent share | median **0.359**，max **0.715** |

⇒ 这是旧 H1 的 Agent 累计重算占比，不能与 RR-EVICT 理想模型的单请求归一化损失值 1.0 直接比较；活动次数、Agent 数量与已知 workload fidelity 限制均须注明。

---

## 7. 给 M6 的观测需求清单（M1 §六交付项）

⚠️ **全部为只读插桩或配置项，不含任何 runtime policy 改动。**

### 7.1 阻塞性（缺则该指标不可算）

| # | 需求 | 阻塞的指标 | 现状 |
| --- | --- | --- | --- |
| **O1** | 每个请求保留 `native_queued_timestamp` / `native_scheduler_admission_timestamp` / `native_first_token_timestamp` | A1.3、A1.4、A1.6、A2.2、A2.7、A2.8 | ✅ Phase 2C/2D 已有，**须在 Phase 2E 保持** |
| **O2** | **开启 `_content_evidence_enabled`**，使**淘汰时刻**持久化 pre-eviction native hash | A3 环节 4 的**具体归因**（R1） | ❌ legacy 模式不可用；需 opt-in |
| **O3** | 在 Continuum 下观测淘汰时刻的 logical retention owners；Native LRU 不要求同样的 protected-entry 语义 | A3 环节 3→4、B3 marginal capacity | ⚠️ native smoke 确认只读可用性 |
| **O4** | 每请求保留 `program_id` 与 `turn_index` | A2.4、A2.6、B1/B2 的 agent 归组 | ✅ 有；须保持 |
| **O5** | `FORCED_RELEASE_DECISION` 保留 `required_blocks` / `original_free_queue`（含 `native_lru_rank`）/ `candidates` | A1 与 A3 全部候选分析 | ✅ 有；须保持 |
| **O6** | workload 表达 **agent 空闲间隔**（inter-turn gap），并记录 | P2 regime 判定、B1 | ✅ `tool_gap_seconds` 存在；**须真正落在时间线上** |
| **O7** | 同一 scenario 内同一 native hash process，且记录 process id | 时序有效性（R1 条件 a） | ✅ 有 |
| **O8** | 至少一个有真实 admission/completion overlap 的并发 >1 场景 | A1.6 队列分量、A2.8 传递率（否则退化） | ❌ H1 为 `max_concurrent_requests = 1` |

**O12（P5 必需）**：保留带有 native content hash/process 身份及观测时刻的 `block → logical prefix position / token range` 映射、有序 prefix hash chain 和 slot reuse 防护；绝不以 LRU rank 代替前缀位置。只读 instrumentation 与 smoke 可在既有授权内开展，缺失则 P5 记 `NOT_OBSERVABLE`。

### 7.2 重要但非阻塞

| # | 需求 | 用途 |
| --- | --- | --- |
| **O9** | 统一 evidence archive（原始 `events.jsonl` + 派生表 + 哈希） | 可追溯性与复核 |
| **O10** | 保留失败/被排除 run，并标 reason | M5（排除与未观测分开计数） |
| **O11** | 逐 scenario 的 workload 参数（family、draws、seed、容量、并发） | 复用效率与 regime 复算 |

### 7.3 明确不要求

```text
❌ 不改 native BlockPool / hash / refcount / ownership / LRU
❌ 不实现任何 Cost-Aware 或 RR-EVICT 策略
❌ 不解锁 B1 runtime 修改
❌ 不要求 hardware counters（如不可得，标 NOT_OBSERVABLE 即可）
```

### 7.4 交付物命名建议（便于 M4 提前调试）

```text
<archive>/runs/<scenario>-<baseline>-<seed>/events.jsonl   请求与原生事件
<archive>/derived/request_evidence.jsonl                   请求级派生
<archive>/derived/decision_candidates.jsonl                候选与几何
<archive>/derived/physical_evictions.jsonl                 淘汰台账
<archive>/derived/missingness_summary.json                 缺失性
<archive>/manifest.json                                    哈希与绑定
```

---

## 8. 边界与请求裁定

**AUTHORIZED（本文件已遵守）**：完整 Phase 2E 离线分析、均值与尾部并行探索、
基于真实 native evidence 的失败模式归因、B1 只读/离线 tail-chunk 可行性分析、
最多两个方法假设、与 M6 直接协作确定只读观测需求。

**NOT AUTHORIZED（本文件未触碰）**：新 Cost-Aware runtime policy、RR-EVICT/tail-chunk 实现、
B1 runtime 修改、native ownership 改动、重开 H1/H2、正式 holdout campaign。

### 请求 M1 裁定

1. θ=0.25 与 κ=512 仅认可作探索性敏感性参数，非正式验收阈值。
2. NGR 仅作净/毛变化诊断；不批准 0.5 硬判据，以带符号的 aggregate delta 判断变化方向。
3. D/I 双视图认可；本轮均非高置信度 P99 推断，正式统计协议另行冻结。
4. O2/O3/O8/O12：允许 M6 开展只读 instrumentation、内容身份和并发/P5 smoke，不得修改 native ownership。
5. Recomputation 与 TTFT 必须成对上报，不得互相代理。

---

## 9. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 统计单位 = 独立 scenario draw；聚合顺序 | `docs/phase2a-m4-rule-acceptance-protocol.md` §1（**M1 ruling**） |
| 缺失性：不插补、不静默丢弃、reason code | `docs/phase2a-m4-missingness-semantics.md`；issue #34 |
| `apc_outcome` 由 `(eligible, cached)` 派生 | `src/kvopt/profiling/runtime_evidence.py::derive_level_b_token_semantics` |
| `eligible` 由 prior prefix snapshot + hash LCP 派生 | 同上 `_eligible_prefix_tokens` |
| 淘汰台账仅槽位身份（5757/5757 `block_slot_only`） | H1 derived `physical_evictions.jsonl`；`local/probe_fc1_partial_recompute_origin.py` |
| 能力矩阵 O2/O3 状态 | `scripts/spikes/phase2_minimal_observability_metal.py`（capability matrix） |
| 字段填充率、TTFT 分解、0 违例 | `local/probe_a_measurability.py`（1068 条观测） |
| ρ = 0.4327、归一化尾部表、agent 集中度 | `local/probe_a_tail_transfer.py` |
| `tool_gap_seconds`、`turn_index` 存在 | `src/kvopt/workload/phase2.py` |
| H1 `max_concurrent_requests = 1`、`max_new_tokens = 1` | `docs/phase2c-m6-workload-reuse-audit.md` |
| E3 的「再分配而非聚合节省」教训 | `docs/phase2d-m6-headroom-investigation.md`；`phase2d_e3_materialize.py:60` |
| RR-EVICT 的尾部机制与 head-of-line blocking | `local/2609.32278v2.pdf` §1、§3.3、§4 |
| B1 LOCKED、边界清单 | Phase 2E 授权（M1）；`docs/phase2a-m4-block-level-design-draft.md` §7 |
