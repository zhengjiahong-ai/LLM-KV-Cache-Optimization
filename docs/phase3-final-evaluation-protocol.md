# Phase 3 — Final Evaluation Protocol（M4 交付）

**状态**：`DESIGN_ONLY` — 待 M1 审查冻结。未授权任何 GPU Campaign。
**作者**：M4（协议与统计）。负载与执行可行性由 M6 另报，本协议只冻结审查所需的口径与门槛。
**输入**：Phase 1B 冻结基线、Phase 2E/2G 已封存结果、Phase 2H history-rich smoke、Phase 2I 冻结算法（PR #87）与实现（PR #88）。
**边界**：本文档只做协议设计、规模与统计评估。不启动正式运行、不改算法、不改 Runtime。

> 阅读顺序建议：§1 可证伪假设 → §2 实验组边界 → §3 指标 → §4 证据分层 → §5 负载设计 → §6 统计 → §7 规模评估 → §8–§9 门槛与停止条件。
> 若只看结论，读 §0 与 §7.4。

---

## 0. 摘要（结论先行）

1. **主指标必须是 `aggregate_recomputed_tokens = Σ(E − C)`，并以 `recompute_ratio = Σ(E−C)/Σ(N−C)` 归一化。** 绝对 token 数会随 workload 规模漂移，跨组不可直接比较。
2. **本协议把"能否测量"与"是否有差异"分开。** Phase 2E/2G 的教训是：**全零结果不可解释**——当基线重算量本身接近 0，或所有候选的代价排序恒同时，"差异 = 0"既不支持也不否证任何算法。因此 Phase 3 必须先过 **Headroom Gate** 与 **Discriminability Gate**，否则判定 `NOT_EVALUABLE` 而不是宣布"无效果"。
3. **必须增加第 6 个实验组 `E0`（sufficient-first + earliest deadline）。** Phase 2G 报告 54/54 的 A1 决策可被这个最简规则复现。若 A3 的收益等同于 `E0`，则"成本模型"没有独立价值，只有 deadline 规则有价值——这是本阶段最需要证伪的对照。
4. **`N0`（Native vLLM，无 forced release）必须存在**，否则无法回答"Continuum 式强制释放本身是否划算"这一前置问题。
5. **A0 是项目侧对 Continuum 风格 Entry Release 的重实现，不是公开 Continuum 系统。** Phase 1B 已声明非逐字节等价；本项目任何结论都不得表述为"复现/优于 Continuum 论文"。
6. **20 Groups × 2 档 × 5–6 臂 = 240 run/repeat，计算成本极低（约 3–4 GPU 小时量级），但统计效力有限。** 真正约束不是成本，而是 (a) 可判别决策数、(b) 重算基线裕度、(c) 采集/转换工程量。§7.4 给出三处必要修正。
7. **Gate O 未通过不阻塞主指标。** 主指标由 Native Runtime 在请求级直接给出，不依赖逐块归属；但"机制解释"需要逐块因果，Phase 3 用**已有的** per-request APC 哈希 + 逐出内容键在离线侧重建，不依赖新的 Runtime 修复（§4.3）。

---

## 1. 研究问题与可证伪假设

### 1.1 研究问题

> 在真实 vLLM + APC 的 Native 执行下，**cost-aware KV cache eviction（Entry-level victim 选择）是否在可测量的重算代价上优于 Native LRU / Continuum 风格 deadline 规则 / 最简启发式？**

### 1.2 三个必须分开的假设

| ID | 假设 | 证伪条件 | 统计形式 |
|---|---|---|---|
| **H1 EFFICACY** | `A3` 的 `recompute_ratio` 低于 `A0` | 配对 CI 含 0 或方向为正 | 配对估计（§6.2） |
| **H2 VALUE** | 成本模型（`q·prefill·S/m`）优于**不使用成本模型**的最简规则 `E0` | `A3 − E0` 的 CI 含 0 | 配对估计 |
| **H3 CONSTRAINT** | 强制释放本身（`A0`）相对 `N0` 是否有净收益 | `A0 − N0` 的 CI 含 0 | 配对估计（前置问题） |

`H2` 是最容易被忽略、但对项目结论最致命的一项：如果 `A3 ≈ E0`，那么整个 Phase 2D–2I 的成本建模工作**在本负载上没有产生可测量的独立价值**，必须如实报告。

### 1.3 明确不主张的

- 不主张对 Continuum 论文或公开实现的复现、等价或优越性（§2.2）。
- 不主张 `A3` 优于 `A1` 或 `A2`（那是不同决策层，非同类替换）。
- 不主张生产级 serving 收益：负载是受控重放，不是生产到达过程。
- 不主张跨模型、跨 GPU 的普适性（单模型、单 GPU 档位）。

---

## 2. 实验组定义与比较边界

### 2.1 六个实验组（三层决策分解）

Entry Release 与 Physical Victim Selection 是**两个独立决策层**，任何实验组只能改动其中一层（Phase 2 冻结原则）。

| 组 | Entry Release（谁先放手） | Block Victim（谁被物理逐出） | 存在的理由 |
|---|---|---|---|
| **N0** Native vLLM | **无**（不注入 forced release） | native LRU + APC | 绝对基线：无 Continuum 机制时的真实代价 |
| **A0** Continuum 风格 | 冻结 `(deadline, min native rank, identity)` | native LRU | 项目侧 Continuum 类比 |
| **A1** 冻结成本感知 Entry | 冻结 `q·[λN + (1−λ)min(need,N)]` | native LRU | Phase 2G 冻结算法 |
| **A2** 冻结成本感知 Block | 同 A0 | A2 cost-aware block selector | Phase 2G-A2 冻结算法 |
| **A3** 后缀代价代理 Entry | `argmin (L, deadline, identity)`，`L = q·prefill·S/m` | native LRU | Phase 2I 冻结算法（PR #87/#88） |
| **E0** 最简强对照（可选第 6 组） | sufficient-first + **earliest deadline** | native LRU | 证伪 `H2` 的关键对照 |

**实现映射（逐臂核对 main @ `35af35a` 的实际代码状态）**

| 组 | 现有可复用实现 | 接入状态 |
|---|---|---|
| N0 | `phase2.PlannedRequest` 计划中 `pressure_stages: []`（`load_phase2_trace` 解析层默认即空列表） | **需验证**：campaign/evaluator 对零压力臂的判定（应记为 `NO_FORCED_RELEASE`，不是 `FAILED`） |
| A0 | `costaware/replay.py::ExecutedP1BStrategy` + `continuum/pressure.py::_release_sort_key` | **就绪**，已用于 54-run 战役 |
| A1 | `costaware/a1_entry.py::A1EntryCostAwareStrategy` | **就绪**，已用于 54-run 战役 |
| A2 | `costaware/a2_selector.py`（block 层） | **就绪**，已用于 54-run 战役 |
| A3 | `costaware/a3_suffix.py::A3SuffixCostStrategy` + `A3NativeSelectionCoordinator`（`phase2_minimal_observability_metal.py:1059+`），backend 已接受 `phase2g_release_policy="A3"` | **Native 路径就绪**（PR #89 合并），但**campaign 层未接通**——见下 |
| E0 | sufficient-first + deadline 排序（`rules.py` 已有 EarliestDeadline 规则，无需新算法） | **需新增 campaign 映射** |

**必须做的最小接通工作（三处，均属配置/映射层，不改算法、不改 Native Ownership）**

1. `continuum_bounded_campaign.py::_arm()` 当前只支持 `A0/A1/A2`，收到 `"A3"` 会 `raise ValueError`。需要加一行映射（`"A3" → ("A3", "A0", …)`）与 `"E0"` 的映射。
2. `continuum_bounded_materialize` 的臂循环需要接受 6 个臂名。
3. evaluator 需要为 N0 增加 `NO_FORCED_RELEASE` 判定分支，否则零压力 run 会被记为 `FAILED`。

> 这三项都是"把已有实现接到一起"，不是新算法开发。若 M1 认为连接成本超出本阶段授权，可退化为 **5 臂（去掉 A1，保留 `N0/A0/E0/A2/A3`）**，但 `A3` 与 `E0` 的映射仍必须补齐——否则 `H1/H2` 无从测量。

> **A3 的启用前提**：backend 侧已强制 `verification_mode="native_live"`、`native_hash_process_id=os.getpid()`、`decision_clock_domain="continuum_pressure"`，且 `A3` 要求 `phase2g_a2_registry`、`phase2i_a3_depth_index`、`event_index` 三者齐备（`phase2_minimal_observability_metal.py:739-770`）。任一 missing 会在构造期 `ValueError`，不会静默降级。但 **若 live 内容标识在决策点不可得**，`A3SuffixCostStrategy` 会 Fail Closed 回落 A0，此时 A3 组与其对照**无差异是必然的**。因此 §9 的 G2 门必须**先验证 A3 真的走了 Step 2 且未回落**（用 `fallback_reason` 计数），再谈效果。

### 2.2 A0 与公开 Continuum 的关系（必须写进每份报告）

| 维度 | 公开 Continuum | 本项目 A0 |
|---|---|---|
| 代码来源 | `Hanchenli/vllm-continuum`（audited commit `316a587`，Apache-2.0） | 项目内重实现（`continuum/pressure.py`） |
| TTL 估计 | 论文含估计组件；公开仓 README 声明 "without the estimation in the paper" | **无估计组件**，直接使用观测到的 deadline |
| 调度层 | 含 scheduling 侧机制 | **不实现**，只复用 vLLM 原生调度 |
| Entry 选择键 | 论文描述 TTL 优先级 | 冻结 `(deadline, min native rank, identity)` |
| Block 逐出 | 未在本项目验证 | native LRU（不干预） |
| 与论文数值可比性 | — | **不可比**（Phase 1B 已记录） |

**强制措辞**：报告中一律写 `A0 (project-side Continuum-style entry release)`；禁止写 "Continuum"、"vs Continuum"、"复现 Continuum"。

### 2.3 隔离性要求（每 cell 必须满足，否则该 cell 作废）

| 要求 | 检查方式 |
|---|---|
| 各臂 replay 计划**逐字节相同**（token ids、顺序、到达偏移、并发） | plan 内容 SHA-256 全臂相等 |
| KV pool 容量、block size、`max_model_len`、chunked-prefill 预算相同 | config 归一化后 SHA-256 相等（除 policy 字段） |
| 模型/分词器/dtype/GPU 相同 | manifest 绑定 |
| 压力触发点相同（同一 round、同一 `need`） | `boundary_id` 序列相等 |
| 唯一允许的差异 | `phase2g_release_policy` / block policy 字段 |

---

## 3. 指标冻结

### 3.1 主指标

$$\text{aggregate\_recomputed\_tokens}=\sum_{\text{requests}}\,(E-C)$$

- `N` = 原生 prompt tokens；`E` = 按冻结 eligibility 可复用的前缀 tokens；`C` = Native APC 实际命中 tokens。
- 约束 `0 ≤ C ≤ E ≤ N`，任何违例即为证据失败（Fail Closed），不得截断修补。
- 语义：**本来可以复用、但因为有内容已不在 KV 中而必须重新计算的部分**。这是 eviction 政策唯一能直接影响的量。
- 主报告的归一化形式：

$$\text{recompute\_ratio}=\frac{\sum (E-C)}{\sum (N-C)}$$

（分母 = 实际 prefill 工作量。用 `N−C` 而非 `N`，因为 `N−C` 才是真做的工作。）

### 3.2 辅助指标（必须一并报告）

| 指标 | 定义 | 用途 |
|---|---|---|
| `aggregate_actual_prefill_tokens` | `Σ(N−C)` | 总 prefill 工作，用于交叉验证 |
| `aggregate_new_suffix_tokens` | `Σ(N−E)` | 真正新内容，应与策略无关（恒等性检验） |
| `apc_reuse_ratio` | `ΣC/ΣN` | 缓存整体有效性 |
| `forced_release_exposure` | 每 cell 的 forced-release 决策数 | 机制暴露量；= 0 则该 cell 对 Entry 层无信息 |
| `decision_count_per_100_requests` | 决策密度 | 负载可判别性的结构指标 |
| `prefill_wall_p95_seconds` | 请求级 prefill 墙钟 p95 | 仅描述，不作性能主张（受控重放） |

**恒等性检验（免费的正确性检查）**：`Σ(N−C) = Σ(E−C) + Σ(N−E)`。三者在同一 cell 内必须精确相等，否则证据链作废。

### 3.3 指标红线（防止 Goodhart）

1. **各臂请求集合必须相同**：任何"某臂跳过某些请求"的处理直接判该 cell 无效。
2. **不得按 q 或 token 长度挑选请求**来放大差异。
3. **不得在观测到结果后调整 `λ`、`τ`、`prefill` profile 或压力强度**（Phase 2G 已发生过 profile 修复争议，Phase 3 需预注册 profile 版本并冻结）。
4. **失败请求保留并计入分母**（`C=0`、`E` 按冻结规则），不得剔除。

### 3.4 指标可达性前提（本协议的核心新增）

实测（Phase 2E/2G 54-run 战役，A0 组）：

| 压力档 | 每 run 重算 tokens | 占 prefill 比例 |
|---|---|---|
| moderate（9 cells） | 16 – 1,296（6 个 cell 恰为 16） | **0.65%** |
| deep（9 cells） | 7,216 – 30,352 | **36.3%** |

结论：**moderate 档在测量上等于"没有重算"**（16 tokens = 1 个 block）。在该档位上，任何政策的 delta 只能是 0，且"0"不携带信息。

因此冻结：

> **Headroom Gate**：一个 cell 只有在其 `A0.recompute_ratio ≥ 5%` 时才进入效果分析。
> 低于阈值的 cell 标记 `NO_HEADROOM` 并原样报告（不得删除），但**不参与** `H1/H2` 的估计。

阈值 5% 的理由：8,000 token 的 prompt 上，5% ≈ 400 tokens ≈ 25 个 block，足以容纳"少杀一个浅层块"带来的差异；低于此值则差异小于单块量化粒度（16 tokens）。

---

## 4. 证据分层与 Gate O 的影响

### 4.1 四层证据（承接 Phase 2I，禁止互相冒充）

| 层 | 含义 | 采集方式 | 可服务于 |
|---|---|---|---|
| **L1** 预测受害者 | 由冻结 eligibility + native rank 推算的 `V_X` | 决策 payload 离线复算 | 可判别性分析（§9 G3） |
| **L2** 物理逐出 | `BLOCK_EVICTED` / `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` | 已记录，含 `block_id`、`native_cache_key_before`、`native_hash_process_id` | 机制暴露量 |
| **L3** 内容身份 | 逐出内容键 vs 请求前缀内容键是否一致 | per-request `native_apc_block_hashes`（已记录）+ 逐出事件的内容键 | **逐块因果归属**（§4.3） |
| **L4** 重算后果 | 该内容是否真的被重新计算，计入 `E−C` | 请求级 `E`、`C` | **主指标** |

**关键结论**：主指标 `E − C` 属于 L4，**由 Native Runtime 在请求粒度直接给出**，不依赖 L3。所以 **Gate O 未通过不阻塞 `H1` 的测量**。

### 4.2 Gate O 未通过的具体影响

Phase 2I Gate O 的实测是 **M3-1 = 1 精确 / 5 不可验证**（`last_selected_block_ids` 非逐回合写入）。其影响必须精确表述为：

| 主张 | 是否受 Gate O 影响 | 说明 |
|---|---|---|
| `A3` 与 `A0` 的重算 tokens 差异 | **不受影响** | 请求级直接测量 |
| "`A3` 决策确实被执行了" | **受影响** | 需要 M3-1 逐回合证据；Phase 3 用 `fallback_reason` + `selection_sequence` 替代（见 §9 G2） |
| "差异来自被逐出的那些块" | **受影响** | 需要 §4.3 的逐块链路 |
| "差异来自该内容被再次请求" | **受影响** | 同上 |

**因此 Phase 3 不得**用 Phase 2I 的数据补证因果；但 Phase 3 **自己**可以在离线侧建立完整链路（§4.3），因为所需字段都已存在。

### 4.3 Phase 3 独立采集 APC / Recompute 证据的方案

**已具备字段（实测确认存在，无需新 Runtime 修复）**：

| 证据 | 事件 | 字段 |
|---|---|---|
| 每请求前缀的逐块内容键 | `VLLM_NATIVE_REQUEST_OBSERVATION` | `native_apc_block_hashes`（实测 86 项对应 1,387 prompt tokens，block=16）、`native_cached_prefix_tokens`、`native_prompt_tokens` |
| 每块物理逐出与其内容键 | `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` | `block_id`、`native_cache_key_before`、`native_hash_process_id`、`ref_count_before` |
| 决策及其受害者 | `FORCED_RELEASE_DECISION` | `candidates[].initially_reclaimable_block_ids`、`original_free_queue`、`selected_releases` |
| 回合边界 | `CONTROLLED_REPLAY_PRESSURE_COMPLETED` | `boundary_id`、`before/after` 计数 |

**离线可计算的因果链（Phase 3 的 L3/L4 归属）**：

```
对每个 pressure episode e（decision → completion 窗口 W_e）：
  evicted_keys(e) = { native_cache_key_before | 事件在 W_e 内 }
逐请求 r（在 W_e 之后、同一 session 的生命周期内）：
  prefix_keys(r) = native_apc_block_hashes(r)
  refetched(r, e) = prefix_keys(r) ∩ evicted_keys(e)
  重算量贡献 ≈ 16 × |refetched(r, e)|，并可用 (E−C) 做上限校验
```

这条链路**完全离线**，不依赖 `last_selected_block_ids`。它回答的正是 `r_i`（"被杀的内容会不会回来"），而该量在 Phase 2 被记为不可算，原因是当时没有做逐块内容 join，而不是数据缺失。

**仍不可得的部分**（必须显式标注 `NOT_ESTABLISHED`）：
- "哪个 Request 的哪个 Block 是被**本策略**而不是自然淘汰杀掉的"——需要逐回合 native attribution；Phase 3 只能用窗口 + 内容键建立**内容级**因果，用 `selected_releases` 建立**选择级**因果，两者合起来仍不等于 owner 级归因。

**M6 可选的最小修复**（若成本很低）：把 `last_selected_block_ids` 改为逐压力回合写入。这会把 M3-1 从 1/6 提升到可验证，并让 §4.3 的链路多一层交叉校验。**若不做，Phase 3 的因果表述必须停在"内容级"**。

---

## 5. Workload 设计

### 5.1 分组规则

- 统计单元 = **workload group**（不是 run，不是 turn，不是 request）。
- 每组 2 个 task，**同一 group 内两 task 不同 repository**（避免同仓共享前缀导致的伪复用）。
- 20 组 = 40 task，需覆盖 ≥10 个 repository。任务池由 W1-C 的 100-task 冻结设计（12 仓库）提供，已执行 20 个，池内剩余 80 个可用。

### 5.2 负载强度：按**实测基线**标定，不按 nominal 标签

Phase 2E 的 `moderate`/`deep` 是**相对短缺量**定义的，实测比例分别是 0.65% 与 36.3%，前者无裕度。

Phase 3 改为**目标基线重算比例**：

| 档 | 目标 `A0.recompute_ratio` | 手段 | 目的 |
|---|---|---|---|
| **L-low** | 5% – 15% | 较小短缺 + 较多复用机会 | 可测量但非灾难性 |
| **L-high** | 25% – 45% | 较大短缺 / 更小 KV pool | 高裕度，检测上限 |

**标定流程（预注册）**：先跑 A0-only 的标定集（20 组 × 1 = 20 run），测出每组在两种短缺参数下的 ratio；若某组达不到 5%，则调整该组的 `required_blocks` 目标（这是**负载参数**，不是算法参数），并记录调整日志。**不得**在观测到 A3 结果后重新标定。

### 5.3 会话密度与并发

Phase 2E 使用"每 session 6 个 checkpoint"，实测 12 requests/run。Phase 2H 使用 history-rich 全量回放，180 requests/run。

Phase 3 冻结：

| 参数 | 值 | 理由 |
|---|---|---|
| checkpoints per session | **12**（S100 成功调用的整数分位点，含首尾）；**下限 6** | 12 = 2× Phase 2E 的暴露量；6 是 Phase 2E 已验证的物化密度，作为退化选项，避免因物化成本把战役卡死 |
| requests per run | 24（2 sessions × 12）；下限 12 | 可预算，且每 run 有 1 次决策 → 40 决策/战役 |
| 相邻 session 启动错峰 | 0.25 s | 沿用冻结值，保证跨臂逐字节相同 |
| 最大并发 | 2 | 沿用冻结值（决定压力可观测性） |
| 逻辑时钟 | `ControlledSparseReplayClock`（逻辑时间推进，无 wall sleep） | 沿用冻结值 |

> **checkpoint 密度不改变决策几何。** 增加 checkpoint 只增加"看到同一决策点的次数"，不改变候选集合、`S`、`q` 的相对关系。因此若 M1 因物化成本选择下限 6，`H1/H2` 的估计仍然有效，只是每 cell 的暴露量回到 Phase 2E 水平（12 requests/run）。**唯有可判别性（G3）不能靠加密 checkpoint 换来**，见 §9。

> **为什么不用 180 requests 的 history-rich 全量**：它能提供更真实的复用结构，但 3 个决策/run 且运行时长 5×，且其到达过程仍是受控的。Phase 3 用 12 checkpoint 换取"每组可复现、每 cell 成本可控"；若 M1 要求更高暴露量，可把 checkpoint 提到 24（requests 48/run，成本线性 ×2）。

### 5.4 配对方式

- **within-cell paired**：同一 (group, load) 下 6 个臂共享同一 plan SHA-256。
- **cross-load 不配对**：低/高负载是不同压力参数，只做平行报告，不做合并检验。
- **统计量**：每 (group, load) 一个 delta = `arm − A0`（因此 `A0 − A0 = 0` 恒为参照）。

---

## 6. 统计分析

### 6.1 独立单元与样本量

| 项 | 数量（R=1） | 说明 |
|---|---:|---|
| Groups | 20 | 统计单元 |
| Cells（group × load） | 40 | 配对单元 |
| Runs | 240 | 6 臂 × 40 cell |
| Requests | 5,760 | 24/run |
| Pressure episodes | 240 | 每 run 1 次 |
| **可比较决策（按 cell）** | **40** | 每 cell 每臂 1 次，跨臂可配对 |
| 机制分析的有效决策数 | 40 × (可判别比例) | 见 §9 G3 |

### 6.2 主分析（估计，不是显著性检验）

对每个 (group, load) 计算 `Δ = recompute_ratio_arm − recompute_ratio_A0`，在 group 层聚合（同 group 两 load 分别报告，不平均）。

报告：

- **均值 / 中位数 Δ**，附 **95% bootstrap CI**（按 group 重采样 10,000 次，保 load 分层）。
- **方向计数**：better / tied / worse（`tied` 定义为 |Δ| ≤ 观测噪声地板，见 §6.4）。
- **每条 CI 必须与对应的可判别决策数一起出现**，否则读者无法判断"0 差异"是算法等价还是测量无力。

**判定规则（预注册）**：

| 条件 | 结论 |
|---|---|
| CI 上界 < 0 且 ≥8 个可判别决策 | 支持 `H1` |
| CI 含 0 且 ≥8 个可判别决策 | 未观察到可检测效应（`NO_DETECTABLE_EFFECT`） |
| CI 含 0 且 <8 个可判别决策 | **`NOT_EVALUABLE`**（禁止写成"无效果"） |
| CI 下界 > 0 | 观察到反向效应 |

### 6.3 效力说明（为什么不做 p 值主张）

- n=20 配对、双侧 Wilcoxon signed-rank、α=0.05：只有当标准化效应量约 `d ≥ 0.66` 时才有 80% 效力。
- 基于 Phase 2E 的观测（最坏情况是 +3,712 tokens，且深压档全部为 0），**没有任何理由预期如此大的效应**。
- 因此 Phase 3 定位为**效应量估计**：`Δ` 的置信区间与量级才是交付物；"p<0.05" 不作为结论依据。
- 若 M1 要求确认性检验，唯一正当做法是提高独立 group 数（≥60），而不是增加 repeat（repeat 不是独立单元）。

### 6.4 噪声地板与重复

受控重放 + `temperature=0` + `max_new_tokens=1` 使运行**近乎确定性**，但仍有真实噪声源（CUDA 调度、APC hash 进程、allocator）。因此：

- **标定子集**：取 5 个 group × 2 load × A0 臂，`R=3`（30 run），计算 `recompute_ratio` 的 run-to-run 标准差 `σ_run`。
- `tied` 的定义：`|Δ| ≤ 2σ_run`（若 `σ_run` 不可测，退化为 `|Δ| ≤ 0.5%`）。
- 若 `σ_run` 与预期效应同量级，则**必须**增加 group 数或降低结论强度，不得靠增加 repeat 掩盖。

### 6.5 多重比较与主次对比

- **预注册主对比只有一个**：`A3 − A0`（`H1`）。
- 次要对比：`A3 − E0`（`H2`）、`A0 − N0`（`H3`）、`A1 − A0`、`A2 − A0`、`A3 − A1`。
- 次要对比一律**报告效应量与 CI，不做显著性主张**；若需并列判定，使用 Holm 校正并声明为探索性。
- 禁止事后新增对比（例如"在高负载子集上 A3 更好"）而不标注为 `POST_HOC`。

### 6.6 缺失与不可评估

| 情形 | 处理 |
|---|---|
| run 失败 / 超时 | 该 cell 标记 `INCOMPLETE`；保留其余臂；配对分析剔除该 cell 并报告剔除数 |
| 某臂 plan/digest 不一致 | 该 cell 全臂作废（隔离性失败） |
| `A3` 全 cell 回落（`fallback_reason` 非空） | `H1` 判定为 `NOT_EVALUABLE`，机制结论为"Native 内容标识未接通" |
| `NO_HEADROOM` cell | 不参与估计，但保留在描述表 |
| 请求级 `C > E` 或 `E > N` | 证据失败，Fail Closed，不修补 |

---

## 7. 规模评估：20 groups × 2 档 × 5–6 臂是否合理

### 7.1 运行矩阵

| R（repeat） | Runs | Requests | GPU 墙钟（估算，46 s/run） |
|---:|---:|---:|---:|
| 1（主战役） | 240 | 5,760 | 3.1 h |
| 3（主战役 ×3） | 720 | 17,280 | 9.2 h |
| 1 + 标定子集（30 run，R=3） | 270 | 6,480 | 3.5 h |
| 3 + 标定子集 | 750 | 18,000 | 9.6 h |

墙钟估算依据（实测）：

| 来源 | 每 run 墙钟 | 分解 |
|---|---:|---|
| Phase 2E bounded（12 req） | 38.6 s（均） | engine init 31.6 s（82%）、native exec 6.7 s |
| Phase 2H history-rich（180 req） | 63.7 s | engine init 26.7 s、native exec 34.8 s |

Phase 3（24 req）预计 native exec ≈ 12–16 s，加 init ≈ 45–50 s/run。
**结论：240 run ≈ 3.0–3.3 h；6 臂 × 40 cell 的成本不构成约束。**

### 7.2 成本

沿用 Phase 2E 冻结的预算口径（CNY 2.0/GPU-hour）：

| 项 | 估算 |
|---|---|
| 主战役（R=1） | 3.5 h ≈ CNY 7 |
| 含标定与重复 | 10 h ≈ CNY 20 |
| 预备/调试/失败重跑余量（2×） | ≈ CNY 40 |
| 建议授权上限 | **CNY 100**（覆盖全流程，含 acquisition 的 GPU 时长另计） |

> 与 Phase 2E 的 `recommended_budget_cap_cny = 60` 相比略显宽松，因为 Phase 3 含 6 臂 + 标定子集；若 M1 要求更紧，可裁剪为「5 臂 + 无重复」≈ CNY 25。

### 7.3 20 组的统计含义（诚实评估）

| 问题 | 20 组是否足够 |
|---|---|
| 描述性覆盖（仓库异构性、负载档） | **足够**：20 组 × 2 档 = 40 单元，足以观察方向与量级 |
| 估计 `Δ` 的置信区间宽度 | **勉强**：若组间 SD ≈ 2,000 tokens，40 单元的 95% CI 半宽 ≈ ±620 tokens（约 2% of prefill） |
| 确认性显著性（小效应） | **不足**：n=20 只对 `d ≥ 0.66` 有效力 |
| 机制分析（可判别决策数） | **取决于负载**：Phase 2H 实测可判别率 0/6；若 Phase 3 仍 ~0，则 40 决策也无效 |

### 7.4 结论与三处必要修正

**结论：20 groups × 2 档 × 6 臂在成本上完全可接受，在统计上足以支撑"效应量估计"，但不足以支撑"确认性显著性"。可以按此规模执行，但必须加上：**

1. **必加 `E0` 臂**（否则 `H2` 无法证伪，成本模型的独立价值无法判定）。
2. **必加 Headroom + Discriminability 双门**（§3.4、§9 G3），否则重演"全零不可解释"。
3. **必加噪声地板标定**（5 组 × R=3），否则 `tied` 无法定义。

若 M1 只允许 5 臂，建议去掉 `A1`（它与 `E0` 高度重合，Phase 2G 已报告 54/54 被 E0 复现），保留 `N0/A0/E0/A2/A3`。

---

## 8. Gate O 未通过的处理（汇总）

| 问题 | 处理 |
|---|---|
| 能否用 Phase 2I 数据补证因果 | **否**。Phase 2I 的 M3-1 仅 1/6，且 `content_verified` 全为 `False` |
| Phase 3 主指标是否需要逐块归属 | **不需要**。`E−C` 由 Runtime 请求级给出 |
| Phase 3 机制主张需要什么 | §4.3 的逐块内容链路（离线可得）+ `selection_sequence` 的决策级证据 |
| 若 M6 补上逐回合 `last_selected_block_ids` | 因果强度可从"内容级"提升到"选择级 + 内容级"双重印证 |
| 报告必须保留的限制 | `ownership_level_attribution = NOT_ESTABLISHED`（除非 M6 提供原生 owner 证据） |

---

## 9. 预注册门槛（G0–G4）

| 门 | 内容 | 失败后果 |
|---|---|---|
| **G0 冻结** | 6 臂定义、指标、20 组、负载参数、profile 版本、replay checkpoint 规则全部 SHA-256 绑定 | 不允许开跑 |
| **G1 隔离性** | 每 cell 的 plan/config（除 policy 字段）SHA-256 全臂相等；模型/tokenizer/GPU/KV 容量一致 | 该 cell 作废 |
| **G2 A3 生效** | 每 cell 检查 `fallback_reason`：`A3` 的 Step 2 回落率必须 < 20%，且 `step == step2_sufficient` 的决策数 ≥ 1 | `H1` 判 `NOT_EVALUABLE`（而不是"无效果"） |
| **G3 可判别性** | 离线用冻结公式计算每 cell 的 `argmin L` vs `argmin deadline`；计入 margin > 14%（`prefill/m` 带）的决策 | 若全战役可判别决策 < 8 → 判 `NOT_EVALUABLE`，**停止解释** |
| **G4 裕度** | 每 cell `A0.recompute_ratio ≥ 5%`，否则 `NO_HEADROOM` | 该 cell 不进入估计 |

G3 的判据来自 Phase 2I §5.5：即使 `S` 不同，若 `L_min(Y) > L(X*)` 则 A0 的选中项不可被推翻。Phase 2H 的 6 次决策中 **4 次候选后缀完全相同、2 次后缀不同但 A0 仍占优**，即 **0/6 可判别**。这是 Phase 3 最大的先验风险。

---

## 10. 停止条件（出现即停，不追加参数搜索）

| # | 条件 | 处置 |
|---|---|---|
| S1 | 任一门 G0–G4 未通过 | 停止，报告门槛证据，不解释效果 |
| S2 | 某臂 plan/digest 不一致 | 该 cell 作废；若 > 10% cell 作废，停止并修工具 |
| S3 | `A3` 回落率 > 20% | 停止，判定内容标识未接通（工程结论，不是算法结论） |
| S4 | 观测到 `σ_run` 与效应同量级 | 停止解释，改为"需要更多 group" |
| S5 | 任一 cell 出现 `C>E` / `E>N` | Fail Closed，停止并审计证据链 |
| S6 | 主指标 CI 含 0 且可判别决策 < 8 | 输出 `NOT_EVALUABLE`，**不得**改公式/换压力重跑以追求差异 |

---

## 11. 明确不做

- 不新增算法分支、不调 `λ/τ`、不改 `prefill` profile（已有版本冻结）。
- 不引入 `r_i` 作为**决策输入**（本文档的 `r_i` 只用于离线机制解释，不回灌策略）。
- 不做逐候选 `λ_i`、不做学习模型。
- 不修改 Native Ownership / BlockPool / ref count / hash cleanup。
- 不为了制造差异而修改负载（G0 之后冻结）。
- 不把 `N0`（无强制释放）作为"最优基线"来暗示 Continuum 无价值——`N0` 只在 `H3` 中有意义。

---

## 12. 交付物与责任人

| 交付 | 责任人 | 前置 |
|---|---|---|
| 冻结协议 JSON（6 臂、20 组、负载参数、门槛） | M4 | 本文档经 M1 批准 |
| 20 组 task 清单与 40 条轨迹映射 | M6 | 100-task 冻结池扩充 acquisition |
| 标定集报告（Headroom + `σ_run`） | M6 | 授权 |
| 主战役执行与证据归档 | M6 | G0–G4 通过 |
| 效果分析报告（估计 + CI + 可判别数） | M4 | 主战役完成 |
| 最终结论（含 `NOT_EVALUABLE` 分支） | M1 | 上述全部 |

---

## 13. 与已有证据的关系

- Phase 2E 54-run 结论（`A1` 0 better/1 worse/8 tied，`A2` 0/3/6）**不被本协议重新解释**，只作为规模与负载参数的先验。
- Phase 2G「54/54 可被 sufficient-first + earliest deadline 复现」是本协议引入 `E0` 的直接原因。
- Phase 2I 的 `content_verified=False` 与 M3-1 1/6 是本协议 §4 的边界来源。
- 本协议不修改任何已封存 artifact。
