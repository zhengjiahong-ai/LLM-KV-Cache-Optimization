# Phase 3 — Final Evaluation Protocol（M4 交付）

> **Historical protocol draft — superseded:** This earlier design-only protocol was superseded by [Phase 3 Final Evaluation Protocol v4 — Option F](phase3-final-evaluation-protocol-v4.md), the sole operative protocol for the current 270-run campaign. The original text below is retained for revision history; do not use its older hypotheses, arm details, budget, or gate wording as current authorization.

**Original status at drafting time**：`DESIGN_ONLY` — 待 M1 审查冻结。未授权任何 GPU Campaign。
**作者**：M4（协议与统计）。负载与执行可行性由 M6 另报，本协议只冻结审查所需的口径与门槛。
**输入**：Phase 1B 冻结基线、Phase 2E/2G 已封存结果、Phase 2H history-rich smoke、Phase 2I 冻结算法（PR #87）与实现（PR #88）。
**边界**：本文档只做协议设计、规模与统计评估。不启动正式运行、不改算法、不改 Runtime。

> 阅读顺序建议：§1 可证伪假设 → §2 实验组边界 → §3 指标 → §4 证据分层 → §5 负载设计 → §6 统计 → §7 规模评估 → §8–§9 门槛与停止条件。
> 若只看结论，读 §0 与 §7.4。

---

## 0. 摘要（结论先行）

1. **主指标是 `aggregate_recomputed_tokens = Σ(E − C)`，绝对 token 数，不做归一化替换。** `recompute_ratio` 与 `apc_reuse_ratio` 只作补充报告。原因：归一化分母 `N−C` 本身随策略变化（`C` 是政策输出），不能当作跨臂恒定的尺子（§3.2–§3.3）。
2. **本协议把"能否测量"与"是否有差异"分开。** Phase 2E/2G 的教训是：**全零结果不可解释**——当基线重算量本身接近 0，或所有候选的代价排序恒同时，"差异 = 0"既不支持也不否证任何算法。因此 Phase 3 必须先过 **Headroom（开跑前冻结）** 与 **G3-CM 成本模型可判别性** 两道门，否则判定 `NOT_EVALUABLE` 而不是宣布"无效果"。
3. **必须增加第 6 个实验组 `E0`：复用 A1 冻结阶梯，只把 Step 2 排序键换成 `(deadline, identity)`，且 S2B 回退路径必须与 A3 逐位相同。** 它与 A3 只差"用不用成本模型"，因此 `A3 − E0` 是唯一能判定成本模型独立价值的对比。若 S2B 无法对齐，则 `H2` 只用 S2A 决策估计（§2.2.1、§2.5）。
4. **`N0`（Native vLLM，无 forced release）必须存在**，且必须用 **No-op 实现**：保留 Pressure Request、`boundary_id`、逻辑时间线与 Pressure Barrier，仅禁用 Forced Entry Release。零强制释放判为 `NO_FORCED_RELEASE`（VALID）；若 `boundary_id` 序列与其它臂不等则 `CONTRACT_VIOLATION`。定义见 §2.6。
5. **A0 是项目侧对 Continuum 风格 Entry Release 的重实现，不是公开 Continuum 系统。** Phase 1B 已声明非逐字节等价；本项目任何结论都不得表述为"复现/优于 Continuum 论文"。
6. **A3 的回退目标是冻结 A1，不是 A0，且 H1 与 H2 的可评估条件不同。** H1 评估**完整 A3 策略**，部分决策回退不影响其正当性；H2 评估**成本模型本身**，需要足够的 S2A 与可判别决策。**不得**因 S2B 占比高就判 H1 不可评估（§2.2.2、§9.1）。
7. **20 Groups × 2 档 × 6 臂 = 240 run/repeat，计算成本极低（约 4.0 GPU 小时含两套标定），但统计效力有限。** 每个 load 档只有 **n = 20 个独立 group**（两档同 group，**不得合并为 40**），CI 半宽约 ±875 tokens。定位为**探索性效应量估计**，不作确认性显著性主张（§7.3）。
8. **Gate O 未通过不阻塞主指标。** 主指标由 Native Runtime 在请求级直接给出；但机制解释只能到**内容级时间关联**，`ownership_level_attribution = NOT_ESTABLISHED`（§4.1、§4.3）。
9. **Headroom 筛选必须在开跑前用独立负载标定集完成并冻结**，不得用主战役的 A0 结果事后筛选。主战役照常执行全部 40 cell，分析期同时报告完整样本与冻结子集（§3.6）。

---

## 1. 研究问题与可证伪假设

### 1.1 研究问题

> 在真实 vLLM + APC 的 Native 执行下，**cost-aware KV cache eviction（Entry-level victim 选择）是否在可测量的重算代价上优于 Native LRU / Continuum 风格 deadline 规则 / 最简启发式？**

### 1.2 三个必须分开的假设

| ID | 假设 | 证伪条件 | 统计形式 |
|---|---|---|---|
| **H1 EFFICACY** | `A3` 的 `Σ(E−C)` 低于 `A0` | 配对 CI 含 0 或方向为正 | 配对估计（§6.2） |
| **H2 VALUE** | 成本模型 `q·prefill·S/m` 优于**不使用成本模型**的最简阶梯 `E0` | `A3 − E0` 的 CI 含 0 | 配对估计 |
| **H3 CONSTRAINT** | 强制释放本身（`A0`）相对 `N0` 有净收益 | `A0 − N0` 的 CI 含 0 | 配对估计（前置问题） |

`H2` 是最容易被忽略、但对项目结论最致命的一项：如果 `A3 ≈ E0`，那么整个 Phase 2D–2I 的成本建模工作**在本负载上没有产生可测量的独立价值**，必须如实报告。

### 1.3 明确不主张的

- 不主张对 Continuum 论文或公开实现的复现、等价或优越性（§2.3）。
- 不主张 `A3` 优于 `A1` 或 `A2`（那是不同决策层，非同类替换）。
- 不主张生产级 serving 收益：负载是受控重放，不是生产到达过程。
- 不主张跨模型、跨 GPU 的普适性（单模型、单 GPU 档位）。
- **不主张 owner 级物理因果归因**：`E−C` 的差异可以观测，但"A3 的哪个块导致了哪些 token 的重算"不可确立，`ownership_level_attribution = NOT_ESTABLISHED`（§4.1）。
- **不把 `A3 − A0` 当作成本模型的价值证明**：该差值混入阶梯结构与 S2B/S2C 分支，成本模型只能由 `A3 − E0` 判定（§2.1、§2.2）。

---

## 2. 实验组定义与比较边界

### 2.1 六个实验组（两层决策分解）

Entry Release 与 Physical Victim Selection 是**两个独立决策层**，任何实验组只能改动其中一层（Phase 2 冻结原则）。

| 组 | Entry Release（谁先放手） | Block Victim（谁被物理逐出） | 存在的理由 |
|---|---|---|---|
| **N0** Native vLLM | **无**（不注入 forced release） | native LRU + APC | 绝对基线：无 Continuum 机制时的真实代价 |
| **A0** Continuum 风格 | 冻结 `(deadline, min native rank, identity)`，**无阶梯** | native LRU | 项目侧 Continuum 类比 |
| **A1** 冻结成本感知 Entry | 冻结阶梯，Step 2 = `q·[λN+(1−λ)min(need,N)]` | native LRU | Phase 2G 冻结算法 |
| **A2** 冻结成本感知 Block | 同 A0 | A2 cost-aware block selector | Phase 2G-A2 冻结算法 |
| **A3** 后缀代价代理 Entry | 冻结阶梯，Step 2 = `(L, deadline, identity)`，`L = q·prefill·S/m` | native LRU | Phase 2I 冻结算法（PR #87/#88） |
| **E0** 最简强对照 | **同 A1 冻结阶梯**，Step 2 = `(deadline, identity)` | native LRU | 隔离成本模型的关键对照（§5.1） |

**结构关系（本协议的核心对照逻辑）**

A0 **没有阶梯**（它是单个 `_release_sort_key`），A1/A3/E0 **共享同一套冻结阶梯**。因此效应可分解为：

| 对比 | 隔离出的东西 |
|---|---|
| `A0 − N0` | 强制释放本身（`H3`） |
| `E0 − A0` | 引入 sufficient-first 阶梯本身（与 deadline 排序无关） |
| **`A3 − E0`** | **仅 Step 2 排序键：成本模型 `L` vs 朴素 deadline**（`H2`） |
| `A1 − A0` | 阶梯 + A1 成本键（不纯，因此不作主对比） |

这个分解是 E0 存在的唯一理由：**只有 `A3 − E0` 能让"收益是否来自成本模型"成为一个可判定的问题**。

**实现映射（逐臂核对 main @ `35af35a` 的实际代码状态）**

| 组 | 现有可复用实现 | 接入状态 |
|---|---|---|
| N0 | `phase2.PlannedRequest` 计划中 `pressure_stages: []`（`load_phase2_trace` 解析层默认即空列表） | **需验证**：campaign/evaluator 对零压力臂的判定（应记为 `NO_FORCED_RELEASE`，不是 `FAILED`） |
| A0 | `costaware/replay.py::ExecutedP1BStrategy` + `continuum/pressure.py::_release_sort_key` | **就绪**，已用于 54-run 战役 |
| A1 | `costaware/a1_entry.py::A1EntryCostAwareStrategy` | **就绪**，已用于 54-run 战役 |
| A2 | `costaware/a2_selector.py`（block 层） | **就绪**，已用于 54-run 战役 |
| A3 | `costaware/a3_suffix.py::A3SuffixCostStrategy` + `A3NativeSelectionCoordinator`（`phase2_minimal_observability_metal.py:1059+`），backend 已接受 `phase2g_release_policy="A3"` | **Native 路径就绪**（PR #89 合并），但**campaign 层未接通**——见下 |
| E0 | **代码中不存在**。`rules.py` 虽有 `M0_p1b_executed_ordering`（= A0）与 `RuleStrategy` 的扁平规则，但**没有"阶梯 + deadline Step 2"这一组合** | **需新增**（定义见 §5.1） |

**必须做的最小接通工作**

1. `continuum_bounded_campaign.py::_arm()` 当前只支持 `A0/A1/A2`，收到 `"A3"` 会 `raise ValueError`。需要加 `"A3" → ("A3", "A0", …)` 与 `"E0"` 的映射。
2. `continuum_bounded_materialize` 的臂循环需要接受 6 个臂名。
3. evaluator 需要为 N0 增加 `NO_FORCED_RELEASE` 判定分支，否则零压力 run 会被记为 `FAILED`。
4. **E0 需要一个新的 Step 2 排序"变体"**：复用 A1 冻结阶梯，只把 Step 2 的排序键换成 `(deadline, identity)`。建议实现方式为给 `A3SuffixCostStrategy` 增加一个 `step2_key` 模式，或抽出一个共享基类——**两者都不改变任何已有臂的行为**。

> 前三项是配置/映射层。第 4 项是**新增一个臂**（不是修改已冻结算法），需 M1 明确授权后方可实现。若 M1 认为 E0 实现成本超授权，则 `H2` 无法判定，报告必须写成 `H2 NOT_EVALUABLE`，**不得**用 `A3 − A0` 冒充成本模型价值。

> **A3 的启用前提**：backend 侧已强制 `verification_mode="native_live"`、`native_hash_process_id=os.getpid()`、`decision_clock_domain="continuum_pressure"`，且 `A3` 要求 `phase2g_a2_registry`、`phase2i_a3_depth_index`、`event_index` 三者齐备（`phase2_minimal_observability_metal.py:739-770`）。任一 missing 会在构造期 `ValueError`，不会静默降级。

### 2.2 A3 的回退目标是冻结 A1，不是 A0（语义修正）

核对 `a3_suffix.py::select()` 的实际行为：

```python
base = self._frozen_a1().select(remaining, state)   # ← 冻结 A1 先跑
...
if not sufficient:
    return A3SuffixSelection(key=base.key, ...)      # ← Step 3/4/5
if unscorable:
    return A3SuffixSelection(key=base.key, fell_back=True, ...)  # ← Step 2 证据不足
chosen = min(audits, key=self._order)                # ← 只有这里用 L
```

因此 **A3 有且只有一条路径用到 `L`**，其余全部落在**冻结 A1**（而不是 A0）上。A3 的每次释放必须归入三个互斥类别之一：

| 类别 | 触发条件 | 实际使用的排序键 |
|---|---|---|
| **S2A — Step 2 正常执行** | `need > 0`、存在 `N_i >= need`、全部候选可评分 | **A3 的 `(L, deadline, identity)`** |
| **S2B — Step 2 证据不足回落** | 同上但任一候选不可评分（`NO_OBSERVATION` / `DEPTH_UNAVAILABLE` / `PREFILL_MISSING` / `LIVE_IDENTITY_MISSING` / `VICTIM_SHORTFALL` / `INVALID_GEOMETRY`） | **冻结 A1 的 Step 2 键 `q·[λN+(1−λ)min(need,N)]`** |
| **S2C — 后续分支委派** | `need <= 0`（Step 1）或无候选满足 `N_i >= need`（Step 3 per-unit / Step 4 pair / Step 5 fallback） | **冻结 A1 的对应分支**，A3 完全不参与 |

**三条统计纪律**：

1. **必须分别报告 S2A / S2B / S2C 的计数与占比**（全战役与各负载档，见 §9 G2）。只报整体均值会把"成本模型从未运行"与"成本模型运行了但选得一样"混为一谈。
2. **不得把 `A3 − A0` 的差异归因于"成本模型是否生效"。** `A3 − A0` 至少混入三种来源：S2A 的键差异、S2B 的 A1 键、S2C 的 A1 阶梯结构。
3. **`A3 − E0` 才是成本模型的纯净对比**，但该纯净性只有在 S2B 的选择逻辑被严格对齐时才成立——见 §2.2.1。

> 原协议写作"A3 回落 A0"，与实际代码不符，会导致把 A1 阶梯的行为误记为 A0 的行为。

#### 2.2.1 S2B 的 A3/E0 对齐问题（本轮必须写清的边界）

A3 的 S2B 回退是**冻结 A1 的 Step 2 键**，这一点由 `a3_suffix.py` 的现有实现固定，本轮不可修改。

因此 E0（新臂）有两种可能的实现方式，二者对 `H2` 的含义完全不同：

| 方案 | E0 的 S2B 行为 | `A3 − E0` 在 S2B 上 | `H2` 的解释 |
|---|---|---|---|
| **B-aligned** | 同样回落到**冻结 A1 的 Step 2 键** | **必然相同**（两者都是 A1 键） | S2B 不贡献任何 `A3−E0` 差异，纯净 |
| **B-native** | 按 E0 自己的 insufficient 处理（如 `(deadline, identity)`） | 可能不同，但差异**不来自成本模型** | S2B 污染 `H2` |

**协议冻结 B-aligned**：E0 的 S2B 必须复用与 A3 完全相同的回退路径（即"任一候选不可评分 → 整次 Step 2 采用冻结 A1 的键"）。这样：

> **A3 与 E0 只在 S2A（全部可评分）时的 Step 2 排序键上存在差异；S2B 与 S2C 两者逐位相同。**

**若实现上无法保证 B-aligned**（例如 E0 的描述不可能复用 A3 的 `_audit` 回退逻辑），则必须执行以下降级，**不得**含糊过去：

1. `H2` 的估计**只用 S2A 决策**，S2B/S2C 决策从 `A3 − E0` 的比较集中剔除；
2. 报告中必须写明剔除的决策数，以及"若把 S2B 计入，方向会如何变化"的敏感性分析；
3. `H2` 的结论限定为 **"在可评分决策上成本模型的独立价值"**，不得表述为完整 A3 策略的价值。

#### 2.2.2 H1 与 H2 的可评估条件不同（不得混用）

| 假设 | 比较对象 | 包含哪些决策 | 可评估条件 |
|---|---|---|---|
| **H1** | 完整 `A3` 策略 vs `A0` | **全部决策**（S2A + S2B + S2C） | 只要样本量与 Headroom 足够即可评估；**部分决策回退不影响 H1 的正当性**，因为 H1 问的就是"完整策略的实际效果" |
| **H2** | 成本模型 vs 朴素排序键 | **仅 S2A**（B-aligned 下等价于全部决策，但解释上只认 S2A） | 需要足够的 **S2A 决策数** 且其中有足够的 **A3/E0 实际可区分决策**（§9.2 G3-CM） |

**关键区别**：H1 允许回退存在（回退本身就是策略的一部分）；H2 不允许把回退的行为算进"成本模型的价值"。因此：

> **不得因为 S2B 占比超标就判 H1 不可评估**——那是 H2 的条件。
> **也不得因为 H1 可评估就认为 H2 也可评估**——H2 还需要可判别性。

### 2.3 A0 与公开 Continuum 的关系（必须写进每份报告）

| 维度 | 公开 Continuum | 本项目 A0 |
|---|---|---|
| 代码来源 | `Hanchenli/vllm-continuum`（audited commit `316a587`，Apache-2.0） | 项目内重实现（`continuum/pressure.py`） |
| TTL 估计 | 论文含估计组件；公开仓 README 声明 "without the estimation in the paper" | **无估计组件**，直接使用观测到的 deadline |
| 调度层 | 含 scheduling 侧机制 | **不实现**，只复用 vLLM 原生调度 |
| Entry 选择键 | 论文描述 TTL 优先级 | 冻结 `(deadline, min native rank, identity)` |
| Block 逐出 | 未在本项目验证 | native LRU（不干预） |
| 与论文数值可比性 | — | **不可比**（Phase 1B 已记录） |

**强制措辞**：报告中一律写 `A0 (project-side Continuum-style entry release)`；禁止写 "Continuum"、"vs Continuum"、"复现 Continuum"。

### 2.4 隔离性要求（每 cell 必须满足，否则该 cell 作废）

| 要求 | 检查方式 |
|---|---|
| 各臂 replay 计划**逐字节相同**（token ids、顺序、到达偏移、并发） | plan 内容 SHA-256 全臂相等 |
| KV pool 容量、block size、`max_model_len`、chunked-prefill 预算相同 | config 归一化后 SHA-256 相等（除 policy 字段） |
| 模型/分词器/dtype/GPU 相同 | manifest 绑定 |
| 压力触发点相同（同一 round、同一 `need`） | `boundary_id` 序列相等 |
| 唯一允许的差异 | `phase2g_release_policy` / block policy 字段 |

### 2.5 E0 的精确定义（`H2` 的唯一有效对照）

E0 的目的只有一个：**与 A3 只差 Step 2 的排序键**。因此 E0 必须复用 A1 的冻结阶梯，不得自行发明任何分支。

| 项 | 定义 |
|---|---|
| **候选集合** | 与 A1/A3 完全相同：`remaining` = `state` 中尚未释放的决策候选（`snapshot.candidate_keys` 减去已释放） |
| **`need`** | 冻结定义 `need = target − |eligible(t)|`，与 A1/A3 同一计算 |
| **`N_i`** | 冻结定义 `N_i = |newly_eligible_after(i)|`，与 A1/A3 同一计算 |
| **Step 1**（`need <= 0`） | 与 A1 相同：`argmin (expected_recompute, deadline, identity)`（此分支 A3 也不改动） |
| **Step 2 候选集** | `sufficient = { i : N_i >= need }`，**与 A1/A3 相同的 sufficient-first 条件** |
| **Step 2 排序键（唯一的差异）** | **`(deadline, identity)`** —— 不做任何成本加权，不读 `q`、不读 `prefill`、不读 `S` |
| **Step 2 Tie-break** | 先 `deadline` 升序；相同则 `identity = (program_id, prefix_id)` 字典序升序。**全序、无随机、无浮点容差** |
| **Step 3**（无 sufficient 候选，有 `N_i > 0`） | 与 A1 完全相同（`argmin expected_recompute / N_i`） |
| **Step 4**（全部 `N_i == 0`） | 与 A1 完全相同（两两 lookahead） |
| **Step 5**（无可行 pair） | 与 A1 完全相同（`argmin (deadline, identity)`） |

**E0 与 A3 的差异清单（必须只有这些）**

| 维度 | A3 | E0 |
|---|---|---|
| Step 1 | 冻结 A1 | 冻结 A1（同） |
| Step 2 候选集 | `N_i >= need` | `N_i >= need`（同） |
| **Step 2 排序键（S2A）** | **`(L, deadline, identity)`**，`L = q·prefill·S/m` | **`(deadline, identity)`** |
| **Step 2 证据不足（S2B）** | 任一候选不可评分 → 整步回落冻结 A1 的 Step 2 键 | **必须完全相同**（见 §2.2.1 B-aligned） |
| Step 3/4/5（S2C） | 冻结 A1 | 冻结 A1（同） |
| Block 层 | native LRU | native LRU（同） |

**对齐要求（本轮新增）**：E0 必须复用 A3 的同一条回退判定（"任一 sufficient 候选不可评分 ⇒ 整次 Step 2 采用冻结 A1 的键"），而不是各自定义。这样 S2B 与 S2C 在两者之间**逐位相同**，`A3 − E0` 的差异被严格限制在 S2A 的排序键。

若实现上无法保证该对齐，按 §2.2.1 的降级执行：`H2` 只用 S2A 决策估计，并报告剔除数与敏感性。

> **E0 不读 `q` 是刻意的。** 若 E0 也用 `q` 加权，它就会与 A1 高度重合（Phase 2G 已观察到 54/54 重合），从而失去"最简强对照"的意义。E0 代表的是"一个工程师不看 KV 代价能做到的最好规则"。

### 2.6 N0 的精确定义

N0 的对照目的是 `H3`：**项目侧强制释放本身是否划算**。因此 N0 必须与其他臂**只差一件事**。

| 项 | 要求 |
|---|---|
| 请求集合 | **完全相同**（同一 plan，逐字节） |
| KV 容量、`block_size`、`max_model_len`、chunked-prefill 预算 | **完全相同** |
| 压力触发时机（round、逻辑时间边界、`boundary_id` 序列） | **完全相同**——pressure **请求仍然被提交**，只是不注入 forced entry release |
| 模型/分词器/GPU/temperature/max_new_tokens | **完全相同** |
| **唯一差异** | 不执行项目侧 Forced Entry Release |

**N0 的接入方式：No-op，而不是删除压力阶段（本轮优先级）**

| 方案 | 是否采用 | 说明 |
|---|---|---|
| **No-op（首选）** | **是** | 保留 Pressure Request、`boundary_id`、逻辑时间线、Pressure Barrier；**仅禁用 Forced Entry Release**。压力事件照常发出、逻辑时钟照常推进、barrier 照常记录，只是不产生 entry 释放决策 |
| 删除 `pressure_stages` | 仅作后备 | 若 No-op 实现不可行，允许 `pressure_stages: []`，但必须另行保证"逻辑时间线与 barrier 序列与其它臂等价"，且该等价性需单独验证 |

**选 No-op 的理由**：删除压力阶段会同时删掉 `CONTROLLED_REPLAY_TIME_ADVANCED` 的 barrier 边界，使 N0 的时间结构与其它臂不同。此时 `A0 − N0` 的差异会混入"时间结构不同"而非"强制释放的有无"，直接污染 `H3`。

**与 M6 确认的事项**（§12）：No-op 的具体接入点（是保留 `pressure_stages` 但把 release policy 设为 no-op，还是在 backend 层拦截 forced release 调用）由 M6 决定，但**必须满足**：`boundary_id` 序列全臂相等、逻辑时间推进序列全臂相等。

**`NO_FORCED_RELEASE` 判定（不得记为 FAILED）**

| 观测 | 判定 |
|---|---|
| run 正常完成、`forced_release_decision_count == 0` | **`NO_FORCED_RELEASE`** — 这是 N0 的**预期且正确**状态，属于 `VALID` |
| run 正常完成、但 N0 出现了 forced release | `CONTRACT_VIOLATION` — 该 cell 作废（说明泄漏了策略） |
| `boundary_id` 序列与同 cell 其它臂不等 | `CONTRACT_VIOLATION` — 压力时间线不一致 |
| run 失败 / 超时 / 证据缺失 | `INCOMPLETE` — 与其它臂同样处理 |

evaluator 必须新增前两个分支。当前实现无此分支，N0 的零决策会被判为失败（见 §2.1 接通项 3）。

---

## 3. 指标冻结

### 3.1 主指标：绝对 token 数，不做归一化替换

$$\boxed{\text{aggregate\_recomputed\_tokens}=\sum_{\text{requests}}\,(E-C)}$$

- `N` = 原生 prompt tokens；`E` = 按**冻结 eligibility 定义**可复用的前缀 tokens；`C` = Native APC 实际命中 tokens。
- 约束 `0 ≤ C ≤ E ≤ N`，任何违例即证据失败（Fail Closed），不得截断修补。
- 语义：**本来可以复用、但因为有内容已不在 KV 中而必须重新计算的部分**。这是 eviction 政策唯一能直接影响的量。
- **主指标在所有报告中以绝对 token 数出现**。`H1/H2/H3` 的配对 delta 也是绝对 token 数之差。

### 3.2 `E` 必须与臂无关（关键约束）

`E` 只能来自**冻结的请求集合与冻结的 eligibility 规则**，不得由实验臂的计算结果推导。检查方式：

> 同一 cell 的 6 个臂，逐请求的 `E` 必须**完全相同**。任何一个请求的 `E` 在不同臂间不同 → 该 cell 作废。

这是"主指标可比"的前提。若 `E` 随臂变化，`Σ(E−C)` 就不再是同一把尺子。

### 3.3 归一化指标：补充，不替代

$$\text{recompute\_ratio}=\frac{\sum (E-C)}{\sum (N-C)},\qquad \text{apc\_reuse\_ratio}=\frac{\sum C}{\sum N}$$

**必须写明的限制**：`N−C` 的**分子与分母都随策略变化**（`C` 本身就是政策输出）。因此 `recompute_ratio` 是"重算占实际 prefill 工作量的比例"，**不是**一个跨臂恒定的尺子：

- 若某臂减少了重算（`E−C` 下降）同时减少了总工作（`N−C` 也下降），ratio 可能不变甚至上升；
- 方向相反的臂之间，ratio 之差**不等于**绝对重算量之差。

因此：

> **`recompute_ratio` 只作为补充报告，不得替代 `Σ(E−C)` 作为主指标，也不得单独用于 `H1/H2/H3` 的判定。**
> 两个数必须成对出现；若二者方向矛盾，**以绝对 token 数为准**，并把矛盾本身作为发现报告。

### 3.4 辅助指标（必须一并报告）

| 指标 | 定义 | 用途 |
|---|---|---|
| `aggregate_actual_prefill_tokens` | `Σ(N−C)` | 总 prefill 工作，用于交叉验证 |
| `aggregate_new_suffix_tokens` | `Σ(N−E)` | 真正新内容，应与策略无关（恒等性检验） |
| `apc_reuse_ratio` | `ΣC/ΣN` | 缓存整体有效性 |
| `forced_release_exposure` | 每 cell 的 forced-release 决策数 | 机制暴露量；= 0 则该 cell 对 Entry 层无信息 |
| `decision_count_per_100_requests` | 决策密度 | 负载可判别性的结构指标 |
| `prefill_wall_p95_seconds` | 请求级 prefill 墙钟 p95 | 仅描述，不作性能主张（受控重放） |

**恒等性检验（免费的正确性检查）**：`Σ(N−C) = Σ(E−C) + Σ(N−E)`。三者在同一 cell 内必须精确相等，否则证据链作废。

### 3.5 指标红线（防止 Goodhart）

1. **各臂请求集合必须相同**：任何"某臂跳过某些请求"的处理直接判该 cell 无效。
2. **不得按 q 或 token 长度挑选请求**来放大差异。
3. **不得在观测到结果后调整 `λ`、`τ`、`prefill` profile 或压力强度**（Phase 2G 已发生过 profile 修复争议，Phase 3 需预注册 profile 版本并冻结）。
4. **失败请求保留并计入分母**（`C=0`、`E` 按冻结规则），不得剔除。

### 3.6 指标可达性前提（本协议的核心新增）

实测（Phase 2E/2G 54-run 战役，A0 组）：

| 压力档 | 每 run 重算 tokens | 占 prefill 比例 |
|---|---|---|
| moderate（9 cells） | 16 – 1,296（6 个 cell 恰为 16） | **0.65%** |
| deep（9 cells） | 7,216 – 30,352 | **36.3%** |

结论：**moderate 档在测量上等于"没有重算"**（16 tokens = 1 个 block）。在该档位上，任何政策的 delta 只能是 0，且"0"不携带信息。

因此冻结：

> **Headroom Gate —— 基于独立负载标定集，在正式主战役之前判定并冻结**
>
> - **判定数据来源**：独立 A0-only **负载标定集**（20 组 × 2 档 × 1 = 40 run），**不使用正式主战役的 A0 结果**。
> - **判定量**：该 (group, load) 的 `A0` 重算量 `R0 = Σ(E−C)` 与 prefill 工作量 `W0 = Σ(N−C)` 之比 `ρ0 = R0/W0`。
> - **阈值（预先冻结）**：`ρ0 ≥ 5%` **且** `R0 ≥ 512` tokens。
> - **判定时点**：主战役开跑**之前**完成，筛选结果写入 G0 冻结清单（SHA-256 绑定）。
> - **正式主战役保留全部结果**：被筛掉的 cell **照常执行、照常归档、照常报告**，只是不进入 `H1/H2/H3` 的估计集。

**为什么必须前置**：若用主战役的 A0 结果事后筛选，筛选规则就与观测结果相关，等价于一次未预注册的自适应选择。M1 本轮明确要求避免这一点。

**为什么加绝对量双条件**：`ρ0` 在小 workload 上会被少量 block 放大（如 16 tokens / 200 tokens = 8%）。绝对下界（512 tokens = 32 个 block）保证筛选出的 cell 也有足够的量化粒度。

**统计口径**

| 项 | 定义 |
|---|---|
| 筛选单位 | cell（group × load） |
| 筛选数据 | **独立负载标定集**（A0-only，40 run） |
| 筛选结果冻结 | 写入 G0 清单，SHA-256 绑定，主战役后**不得修改** |
| **分析报告必须同时给出两组** | **完整样本**（全部 40 cell）+ **预先确定的 Headroom 子集** |
| **必须报告字段** | `N_candidate_cells = 40`、`N_no_headroom`、`N_incomplete`、`N_analyzed`，**按 load 档分别给出** |
| **配对完整性规则** | 若某 group 的某一 load 被筛除，该 (group, load) 对从 `H1/H2` 的估计集剔除；同一 group 的另一 load 不受影响，但须标注该 group 只有单档参与 |
| **最低可估计门槛** | 每 load `N_analyzed ≥ 8`；低于此值该 load 标 `INSUFFICIENT_ANALYZED_CELLS` |
| **禁止** | 不得在观测到任何算法臂结果后调整筛选规则或阈值；不得用完整样本与子集中"更好看"的那个作为结论 |

> 三处阈值（Headroom 的 5% / 512 tokens、噪声标定的 `σ_run`、可判别性的 8 个决策）**各自独立定义、互不推导**，且**全部在开跑前冻结**。

---

## 4. 证据分层与 Gate O 的影响

### 4.1 四层证据（承接 Phase 2I，禁止互相冒充）

| 层 | 含义 | 采集方式 | 允许支持的主张 |
|---|---|---|---|
| **L1** 预测受害者 | 由冻结 eligibility + native rank 推算的 `V_X` | 决策 payload 离线复算 | 可判别性分析（§9.2 G3-CM）。**不是**物理事实 |
| **L2** 物理逐出 | `BLOCK_EVICTED` / `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` | 已记录，含 `block_id`、`native_cache_key_before`、`native_hash_process_id` | 机制暴露量、"发生过逐出" |
| **L3** 内容身份 | 逐出内容键 vs 请求前缀内容键是否一致 | per-request `native_apc_block_hashes` + 逐出事件内容键 | **内容级时间关联**（§4.3）。**不是**完整物理因果归属 |
| **L4** 重算后果 | 该内容是否真的被重新计算 | 请求级 `E`、`C`，即 `Σ(E−C)` | **主指标；唯一的效果依据** |

**两条不可逾越的界线**：

1. **L4 是效果的唯一依据。** `Σ(E−C)` 由 Native Runtime 在请求粒度直接给出。任何离线估算（如 `16 × |refetched|`）**不得**替代它作为效果指标。
2. **L3 不等于完整物理因果归属。** 内容键交集证明的是"同一内容先后出现在逐出事件与后续请求前缀中"，属于**时间关联 + 内容一致**；它不能证明"该块是被本策略、而不是被自然淘汰或别的请求杀掉的"。`ownership_level_attribution = NOT_ESTABLISHED` 除非原生层提供 owner 级证据。

**关键结论**：主指标属于 L4，**不依赖 L3**，所以 **Gate O 未通过不阻塞 `H1` 的测量**。

### 4.2 Gate O 未通过的具体影响

Phase 2I Gate O 的实测是 **M3-1 = 1 精确 / 5 不可验证**（`last_selected_block_ids` 非逐回合写入）。其影响必须精确表述为：

| 主张 | 是否受 Gate O 影响 | 说明 |
|---|---|---|
| `A3` 与 `A0` 的重算 tokens 差异 | **不受影响** | 请求级直接测量 |
| "`A3` 决策确实被执行了" | **受影响** | 需要 M3-1 逐回合证据；Phase 3 用 `fallback_reason` + `selection_sequence` 替代（见 §9 G2） |
| "差异来自被逐出的那些块" | **受影响** | 需要 §4.3 的逐块链路，且只能到内容级 |
| "差异来自该内容被再次请求" | **受影响** | 同上 |

**因此 Phase 3 不得**用 Phase 2I 的数据补证因果；Phase 3 自己能做的也只是**内容级**关联（§4.3）。

### 4.3 Phase 3 独立采集 APC / Recompute 证据的方案

**已具备字段（实测确认存在，无需新 Runtime 修复）**：

| 证据 | 事件 | 字段 |
|---|---|---|
| 每请求前缀的逐块内容键 | `VLLM_NATIVE_REQUEST_OBSERVATION` | `native_apc_block_hashes`（实测 86 项对应 1,387 prompt tokens，block=16）、`native_cached_prefix_tokens`、`native_prompt_tokens` |
| 每块物理逐出与其内容键 | `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` | `block_id`、`native_cache_key_before`、`native_hash_process_id`、`ref_count_before` |
| 决策及其受害者 | `FORCED_RELEASE_DECISION` | `candidates[].initially_reclaimable_block_ids`、`original_free_queue`、`selected_releases` |
| 回合边界 | `CONTROLLED_REPLAY_PRESSURE_COMPLETED` | `boundary_id`、`before/after` 计数 |

**离线可计算的关联链（仅 L3：内容级时间关联）**：

```
对每个 pressure episode e（decision → completion 窗口 W_e）：
  evicted_keys(e) = { native_cache_key_before | 事件在 W_e 内 }
逐请求 r（在 W_e 之后、同一 session 的生命周期内）：
  prefix_keys(r) = native_apc_block_hashes(r)
  refetched(r, e) = prefix_keys(r) ∩ evicted_keys(e)
```

这条链不依赖 `last_selected_block_ids`，它回答"被杀过的内容有没有再次出现在后续请求里"，即 Phase 2 记为不可算的 `r_i`（当初不可算是因为没做逐块内容 join，不是数据缺失）。

**但这个量只能用于解释，不得用于计分量**：

| 允许 | 禁止 |
|---|---|
| 报告 `|refetched|` 的分布、与 `E−C` 的**相关性** | 用 `16 × |refetched|` 作为重算量、或用它替代 `Σ(E−C)` |
| 用它解释"为什么某 arms 的 `E−C` 不同" | 用它声称"这 16 个 token 是被本策略逐出导致的" |
| 与 `E−C` 做上限/一致性校验（`16×|refetched|` 应 ≤ `E−C` 的相应量级） | 在二者矛盾时以它为准 |

**仍不可得的部分**（必须显式标注 `NOT_ESTABLISHED`）：

- "哪个 Request 的哪个 Block 是被**本策略**而不是自然淘汰杀掉的"——需要逐回合 native owner 级 attribution；Phase 3 只能给到内容级。
- `ownership_level_attribution = NOT_ESTABLISHED`，且该标注必须出现在摘要里，不得只出现在附录。

**M6 可选的最小修复**（若成本很低）：把 `last_selected_block_ids` 改为逐压力回合写入。这会把 M3-1 从 1/6 提升到可验证，并让"选择级"证据与内容级关联交叉印证。**若不做，因果表述必须停在内容级。**

---

## 5. Workload 设计

### 5.1 分组规则

- 统计单元 = **workload group**（不是 run，不是 turn，不是 request）。
- 每组 2 个 task，**同一 group 内两 task 不同 repository**（避免同仓共享前缀导致的伪复用）。
- 20 组 = 40 task，需覆盖 ≥10 个 repository。

**任务可得性与 M6 独立确认（重要边界）**

W1-C 的 `sample_count = 100` 是**候选任务池**（12 仓库的抽样设计），**不是 100 条已采集轨迹**。实际状态：

| 项 | 数量 | 状态 |
|---|---:|---|
| 冻结候选任务池 | 100 | 仅任务标识与源引用 |
| 已采集轨迹 | 20 | `pilot_instance_ids` |
| 其中 Full-payload-comparable | **18** | 可进入 Native 重放 |
| 其余候选 | 80 | **仅候选，采集可行性与质量未建立** |
| Phase 3 需要 | 40 | = 20 组 × 2 |

因此：**本协议不把"80 个候选"当作"80 条可用数据"**。下列事项必须由 M6 独立确认后，规模才能冻结：

1. 能否从 80 个候选中采集到足够任务，形成 20 个**新的** Workload Groups（且满足"组内不同仓库"）；
2. 新任务的 **Full Payload 可比性**、**Prefill Profile 覆盖**、**Native Replay 可行性**；
3. 240-run 主战役 + 30-run 噪声标定的**实测执行成本**；
4. 是否有条件加入**公开 Continuum 的独立系统级对照**（若有，须另立协议；不并入本六臂矩阵）。

在 M6 给出上述结论前，本协议的规模是**候选规模**，不是冻结规模。

### 5.2 负载强度：按**实测基线**标定，不按 nominal 标签

Phase 2E 的 `moderate`/`deep` 是**相对短缺量**定义的，实测比例分别是 0.65% 与 36.3%，前者无裕度。

Phase 3 改为**目标基线重算比例**：

| 档 | 目标基线（`A0` 单臂） | 手段 | 目的 |
|---|---|---|---|
| **L-low** | `ρ0 = R0/W0` 落在 5%–15% | 较小短缺 + 较多复用机会 | 可测量但非灾难性 |
| **L-high** | `ρ0` 落在 25%–45% | 较大短缺 / 更小 KV pool | 高裕度，检测上限 |

**负载参数标定（预注册，独立于两类噪声/筛选）**：先跑 A0-only 的负载标定集（20 组 × 2 档 × 1 = **40 run**），测出每组的 `ρ0` 与 `R0`；若某组达不到 L-low 的下界，则调整该组的 `required_blocks`（这是**负载参数**，不是算法参数），并记录调整日志。**不得**在观测到任何算法臂的结果后重新标定。

> **三套 run 集合必须分开记账，不得混算**：
>
> | 集合 | 规模 | 用途 | 是否计入主战役 |
> |---|---:|---|---|
> | **负载标定集** | 40 run（A0-only） | ① 确定 L-low/L-high 参数；② **产出 Headroom 筛选结果**（§3.6） | 否 |
> | **噪声标定集** | 30 run（5 组 × 2 档 × R=3，A0） | 估计 `σ_run` 与 `σ_delta`，定义 `tied` | 否 |
> | **主战役** | 240 run（6 臂 × 40 cell，R=1） | 效应估计 | 是 |
>
> **Headroom 筛选在开跑前冻结**：判定数据来自**负载标定集**（而不是主战役），结果写入 G0 冻结清单。主战役照常执行全部 40 个 cell，分析期同时报告**完整样本**与**冻结的 Headroom 子集**（§3.6）。
>
> 负载标定的两个职责有先后：先调 `required_blocks` 让 `ρ0` 落入目标区间，再对该**已冻结参数**下测得的 `ρ0` 应用 5%/512 阈值并冻结筛选结果。两次标定若参数有变，必须重跑标定集，不得复用调整前的数据做筛选。

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
| **每个 load 档的独立 group 数** | **20** | 两档同 group，**不得合并为 40** |
| 机制分析的有效决策数 | 见 §9.2 G3-CM | 按全战役与各 load 档分别统计 |

### 6.2 主分析（估计，不是显著性检验）

对每个 (group, load) cell 计算**绝对** delta：

$$\Delta_{\text{cell}}=\left(\sum(E-C)\right)_{\text{arm}}-\left(\sum(E-C)\right)_{A0}$$

在 group 层聚合（同 group 两 load 分别报告，不平均）。`recompute_ratio` 的 delta 作为**补充**同表给出，不参与判定（§3.3）。

报告：

- **均值 / 中位数 Δ（tokens）**，附 **95% bootstrap CI**：按 **group** 重采样 10,000 次，**每个 load 档内独立重采样**（`n = 20`/档），不合并 pool。
- **方向计数**：better / tied / worse（`tied` 定义见 §6.4）。
- **每条 CI 旁必须并列三个计数**：`N_analyzed`（该 load 档参与估计的 cell 数）、可判别决策数、S2A 决策数。缺任一项的 CI 不得单独出现。
- **必须同时给出两组样本**：完整样本（全部 40 cell，按档分开）与**开跑前冻结的 Headroom 子集**（§3.6）。
- **必须同时给出未归一化与归一化两栏**；若二者方向矛盾，以绝对 token 数为准，并把矛盾作为发现报告。

**判定规则（预注册，分假设）**：

| 假设 | 评估条件 | 结论 |
|---|---|---|
| **H1**（完整 A3 vs A0） | CI 上界 < 0 | 支持 H1 |
| **H1** | CI 含 0 | `NO_DETECTABLE_EFFECT`（H1 不要求可判别性，因为问的是完整策略实际效果） |
| **H2**（成本模型 vs E0） | CI 上界 < 0 **且** 可判别决策 ≥ 8 | 支持 H2 |
| **H2** | CI 含 0 且可判别 ≥ 8 | `NO_DETECTABLE_EFFECT` |
| **H2** | 可判别决策 < 8 | **`NOT_EVALUABLE`**（禁止写成"无效果"） |
| 任一 | CI 下界 > 0 | 观察到反向效应 |

### 6.3 效力说明（为什么不做 p 值主张）

- n=20 配对、双侧 Wilcoxon signed-rank、α=0.05：只有当标准化效应量约 `d ≥ 0.66` 时才有 80% 效力。
- 基于 Phase 2E 的观测（最坏情况是 +3,712 tokens，且深压档全部为 0），**没有任何理由预期如此大的效应**。
- 因此 Phase 3 定位为**效应量估计**：`Δ` 的置信区间与量级才是交付物；"p<0.05" 不作为结论依据。
- 若 M1 要求确认性检验，唯一正当做法是提高独立 group 数（≥60），而不是增加 repeat（repeat 不是独立单元）。

### 6.4 噪声地板（与 Headroom 筛选严格分开）

受控重放 + `temperature=0` + `max_new_tokens=1` 使运行**近乎确定性**，但仍有真实噪声源（CUDA 调度、APC hash 进程、allocator）。

**噪声标定集**（独立于主战役、独立于 Headroom 筛选）：

| 项 | 值 |
|---|---|
| 设计 | 5 个 group × 2 load × **A0 臂只是其中一环** × `R=3` = 30 run |
| 为什么只测 A0 | 单臂重复只能给出 `σ_run`（单臂运行噪声），**不能直接给出两臂差值的噪声**——见下 |
| 输出 | `σ_run`（单臂 `Σ(E−C)` 的 run-to-run SD，绝对 tokens） |
| 用途 | 仅用于定义 `tied`；**不用于**判定 Headroom，**不用于**估计效应 |

**单臂噪声 ≠ 差值噪声（本轮修正）**

| 量 | 含义 | 估计方式 |
|---|---|---|
| `σ_run` | 同一臂重复运行之间的波动 | 30-run 标定集直接测得 |
| `σ_delta` | 两臂**配对差值**的波动 | 若两臂独立同方差：`σ_delta = √2 · σ_run` |

因为 `Δ = arm − A0` 是两个随机量之差，`Var(Δ) = Var(arm) + Var(A0)`；在两臂独立同方差假设下即 `2σ_run²`，故 `σ_delta = √2·σ_run ≈ 1.414 σ_run`。

**因此 `tied` 的阈值必须用 `σ_delta`，而不用 `σ_run`：**

`tied` 定义：`|Δ_cell| ≤ 2·σ_delta = 2√2·σ_run ≈ 2.83 σ_run`。

**该假设不成立时怎么办**：

| 情形 | 处理 |
|---|---|
| 有额外数据可直接估计两臂配对差值的 run-to-run SD（如标定集扩展到含 A3 的重复） | 直接用实测 `σ_delta`，不使用 √2 假设 |
| 无此数据 | 用 `√2·σ_run` 作为**经验性**上界，并在报告中**明确标注**"基于独立同方差假设" |
| `σ_run` 本身无法估计 | `tied` 记为 `UNDEFINED`；方向计数退化为 better/worse 二分并声明该局限 |

> **`tied` 不是统计显著性界限。** 它只是一个经验性的"多小算相同"阈值，用于归类方向计数。不得用 `|Δ| ≤ 2σ_delta` 推出"两臂等价"，也不得用 `|Δ| > 2σ_delta` 推出"差异显著"。真正的推断依据是 §6.2 的 bootstrap CI。

**与 Headroom 的区别**（M1 要求的显式分离）：

| 维度 | Headroom 筛选（§3.6） | 噪声标定（本节） |
|---|---|---|
| 目的 | 剔除"基线无重算可减"的 cell | 定义"多小算相同" |
| 输入 | **独立负载标定集**的 A0 结果 | 5 个 group 的 **R=3** 重复 |
| 判定时点 | **主战役开跑前冻结** | 主战役前 |
| 单位 | cell | run-to-run 方差 |
| 是否影响可估计的 cell 数 | **是**（过滤） | 否 |
| 是否进入主战役计数 | 否 | **否（独立 30 run，单列预算）** |

### 6.5 多重比较与主次对比

- **预注册主对比只有一个**：`A3 − A0`（`H1`）。
- **成本模型对比**：`A3 − E0`（`H2`）。它与 `H1` 是并列的两个主问题，但**不做联合显著性主张**。
- 次要对比：`A0 − N0`（`H3`）、`E0 − A0`、`A1 − A0`、`A2 − A0`、`A3 − A1`。
- 次要对比一律**报告效应量与 CI，不做显著性主张**；若需并列判定，使用 Holm 校正并声明为探索性。
- 禁止事后新增对比（例如"在高负载子集上 A3 更好"）而不标注为 `POST_HOC`。

### 6.6 缺失与不可评估

| 情形 | 处理 |
|---|---|
| run 失败 / 超时 | 该 cell 标记 `INCOMPLETE`；保留其余臂；配对分析剔除该 cell 并报告剔除数 |
| 某臂 plan/digest 不一致 | 该 cell 全臂作废（隔离性失败） |
| **N0 出现 forced release** | `CONTRACT_VIOLATION`，该 cell 作废 |
| **N0 零 forced release** | `NO_FORCED_RELEASE`，**VALID**（不是失败） |
| **N0 的 `boundary_id` 序列与其它臂不等** | `CONTRACT_VIOLATION`，该 cell 作废（压力时间线不一致） |
| **A3 回退占比高（`S2B/(S2A+S2B) ≥ 20%`）** | **只影响 `H2`**（判 `NOT_EVALUABLE`）；`H1` 可继续报告，但须写明回退占比 |
| **A3 全部决策为 S2C（后续分支）** | `H2` 判 `NOT_EVALUABLE`（A3 与 E0 共享阶梯，必然一致）；`H1` 不受影响 |
| **`discriminable_count < 8`** | `H2 = NOT_EVALUABLE`；`H1` 不受影响 |
| `NO_HEADROOM` cell（按开跑前冻结清单） | 不参与估计，但**照常执行并保留在描述表** |
| 请求级 `C > E` 或 `E > N` | 证据失败，Fail Closed，不修补 |
| 某请求的 `E` 在不同臂间不同 | 该 cell 作废（`E` 非臂无关，§3.2） |

---

## 7. 规模评估：20 groups × 2 档 × 5–6 臂是否合理

### 7.1 运行矩阵（三套集合并列，分开记账）

| 集合 | Runs | Requests | GPU 墙钟（46 s/run） | 进入效应估计 |
|---|---:|---:|---:|---|
| 负载标定集（A0-only，20 组 × 2 档） | 40 | 960 | 0.5 h | 否 |
| 噪声标定集（5 组 × 2 档 × R=3，A0） | 30 | 720 | 0.4 h | 否（仅定义 `tied`） |
| **主战役（6 臂 × 40 cell，R=1）** | **240** | **5,760** | **3.1 h** | **是** |
| **合计（推荐方案）** | **310** | **7,440** | **≈ 4.0 h** | — |
| 备选：主战役 R=3 | 720 | 17,280 | 9.2 h | — |
| 备选：R=3 + 两套标定 | 790 | 18,960 | ≈ 10.1 h | — |

墙钟估算依据（实测）：

| 来源 | 每 run 墙钟 | 分解 |
|---|---:|---|
| Phase 2E bounded（12 req） | 38.6 s（均） | engine init 31.6 s（82%）、native exec 6.7 s |
| Phase 2H history-rich（180 req） | 63.7 s | engine init 26.7 s、native exec 34.8 s |

Phase 3（24 req）预计 native exec ≈ 12–16 s，加 init ≈ 45–50 s/run。
**结论：主战役 240 run ≈ 3.0–3.3 h；6 臂 × 40 cell 的成本不构成约束。**

### 7.2 成本（服务侧 GPU）

沿用 Phase 2E 冻结的预算口径（CNY 2.0/GPU-hour）：

| 项 | 估算 |
|---|---|
| 负载标定集（40 run） | 0.5 h ≈ CNY 1 |
| 噪声标定集（30 run） | 0.4 h ≈ CNY 1 |
| 主战役（R=1，240 run） | 3.1 h ≈ CNY 7 |
| 小计 | ≈ 4.0 h ≈ CNY 9 |
| 失败重跑 / 调试余量（2×） | ≈ CNY 20 |
| 建议授权上限 | **CNY 100**（覆盖全流程；acquisition 侧的 GPU 时长**另计**，由 M6 确认） |

> 若 M1 要求更紧，可裁剪为「5 臂（去 A1）+ 无重复」≈ CNY 7。**但两套标定集不可省**：负载标定决定 `ρ0` 是否落入目标区间，噪声标定决定 `tied` 是否有定义。

### 7.3 20 组的统计含义（按 load 独立口径重算）

**独立单元口径修正**：两个 load 档属于**同一个 group**，不能当作 40 个独立样本。因此：

| 项 | 值 |
|---|---|
| 独立 Group 数 | **20**（每个 load 档各自 20 个独立 group） |
| 每个 load 档的估计单元 | **n = 20**（不是 40） |
| 是否可跨档合并 | **不可**——两档是不同压力参数，只做平行报告 |

**CI 半宽修正**（普通近似，λ=1 的 paired 情形）：

$$\text{half-width}\approx 1.96\cdot\frac{\sigma_{\text{group}}}{\sqrt{n}}=1.96\cdot\frac{2000}{\sqrt{20}}\approx \pm 875\ \text{tokens}$$

> 若按错误的 n=40 计算会得到 ≈ ±620 tokens；**修正后为 ≈ ±875 tokens**（M1 估算的 ±935 与本节差异来自 `t_{\alpha/2,19}=2.093` vs `1.96` 的取法，二者同一量级）。**最终以预注册的 group-level bootstrap CI 为准**，此处的正态近似仅用于说明样本量量级。

**结论（诚实评估）**：

| 问题 | 20 组是否足够 |
|---|---|
| 描述性覆盖（仓库异构、负载档） | **足够**：20 组 × 2 档 = 40 个描述单元 |
| 估计 `Δ` 的 CI 宽度 | **勉强**：每档 n=20，若组间 SD ≈ 2,000 tokens，半宽 ≈ ±875 tokens（约 3% of prefill） |
| 确认性显著性（小效应） | **不足**：n=20 只对 `d ≥ 0.66` 有效力 |
| 机制分析（可判别决策数） | **取决于负载**：Phase 2H 实测可判别率 0/6 |

> **本次实验定位：探索性效应量估计**。交付物是 `Δ` 的 CI 与量级，**不作确认性显著性主张**。若需要确认性检验，唯一正当做法是把独立 group 数提到 ≥60，而不是增加 repeat 或增加 load 档。

### 7.4 结论与四处必要修正

**结论：20 groups × 2 档 × 6 臂在成本上完全可接受，在统计上足以支撑"效应量估计"，但不足以支撑"确认性显著性"。可以按此规模执行，但必须加上：**

1. **必加 `E0` 臂**（否则 `H2` 无法证伪，成本模型的独立价值无法判定）。这需要新增一个 Step 2 排序变体（§2.1 接通项 4），属新增臂而非修改冻结算法。
2. **必加 Headroom（开跑前冻结）+ G3-CM 可判别性双门**（§3.6、§9.2），否则重演"全零不可解释"。
3. **必加噪声地板标定**（5 组 × 2 档 × R=3 = 30 run，独立预算），否则 `tied` 无法定义。
4. **必加 S2A/S2B/S2C 三分报告**（§2.2、§9.1），否则无法区分"成本模型没运行"与"运行了但选得一样"。

**规模未因本轮修正而扩大**：仍为 310-run 候选预算（40 负载标定 + 30 噪声标定 + 240 主战役）。本轮修正只改变**统计口径与门槛定义**，不改变任何 run 数量。

若 M1 只允许 5 臂，建议去掉 `A1`（它与 `E0` 高度重合，Phase 2G 已报告 54/54 被朴素规则复现），保留 `N0/A0/E0/A2/A3`。

**规模仍为候选规模**：20 组依赖 40 条可用轨迹，而当前只有 18 条 full-payload-comparable；新任务采集可行性由 M6 独立确认（§5.1）。

---

## 8. Gate O 未通过的处理（汇总）

| 问题 | 处理 |
|---|---|
| 能否用 Phase 2I 数据补证因果 | **否**。Phase 2I 的 M3-1 仅 1/6，且 `content_verified` 全为 `False` |
| Phase 3 主指标是否需要逐块归属 | **不需要**。`E−C` 由 Runtime 请求级给出 |
| Phase 3 机制主张需要什么 | §4.3 的内容级关联（离线可得）+ `selection_sequence` 的决策级证据 |
| 若 M6 补上逐回合 `last_selected_block_ids` | 可把"选择级"证据与内容级关联交叉印证，但**仍不等于** owner 级归因 |
| 报告必须保留的限制 | `ownership_level_attribution = NOT_ESTABLISHED`，且必须写入摘要而非只在附录 |

---

## 9. 预注册门槛（G0–G4，含 G3-CM）

| 门 | 内容 | 失败后果 |
|---|---|---|
| **G0 冻结** | 6 臂定义（含 E0/N0 精确规格）、指标、20 组、负载参数、**Headroom 筛选结果**、profile 版本、replay checkpoint 规则全部 SHA-256 绑定 | 不允许开跑 |
| **G1 隔离性** | 每 cell 的 plan/config（除 policy 字段）SHA-256 全臂相等；模型/tokenizer/GPU/KV 容量一致；逐请求 `E` 全臂相等；N0 的 `boundary_id` 序列与同 cell 其它臂相等 | 该 cell 作废 |
| **G2 A3 分支构成** | **按全战役与各 load 档分别**统计 S2A / S2B / S2C（**不要求每个 cell 都有 S2A**） | 见下 |
| **G3-CM 成本模型可判别性**（原 G3 + G5 合并） | 统计 S2A 决策数、**A3 与 E0 实际选择不同**的决策数、以及该数量的 load 分布 | 见下 |
| **G4 裕度** | 按**开跑前冻结**的 Headroom 清单（来自独立负载标定集） | 清单外的 cell 不进入估计 |

### 9.1 G2：分支构成，按战役层统计（本轮修正统计层级）

**原协议的问题**：每 cell 只有 1 次 A3 决策，若要求"每 cell 至少 1 次 S2A"，逻辑上等价于要求**所有** cell 都是 S2A。这把一个总体比例约束写成了逐 cell 的全称要求。

**修正为分层统计**：

| 统计层级 | 统计量 |
|---|---|
| **全战役** | `S2A_count`、`S2B_count`、`S2C_count` 与其占比（以**决策**为单位，即 40 × R × 每 run 决策数） |
| **各 load 档** | 同上，两档分别给 |
| **各 cell** | 只作**描述性**给出（该 cell 的 1 次决策落在哪一类），**不设逐 cell 门槛** |

**G2 判定（作用于 H2，而不是 H1）**：

| 条件 | 结论 |
|---|---|
| `S2B / (S2A + S2B) ≥ 20%`（全战役） | `H2 = NOT_EVALUABLE`，机制结论为"内容标识未接通或证据不足"（工程结论） |
| `S2A_count == 0`（全战役） | `H2 = NOT_EVALUABLE`：成本模型从未运行 |
| `S2C` 占比很高但 `S2A > 0` | 不判失败；按 §2.2.1 的 B-aligned 处理，S2C 在 A3/E0 间逐位相同，不污染 `H2` |

**H1 的可评估条件与 G2 无关**：H1 比较的是**完整 A3 策略**与 A0，回退本身就是策略的一部分。`S2B` 占比高会削弱 H1 的**机制解释**，但不影响 H1 作为"完整策略实际效果"的正当性。

> 唯一影响 H1 的 G2 情形是 `S2A_count == 0` 且 `S2C_count == 0`——即 A3 与 A1 完全相同，此时 A3 实际上不是一个独立臂。这种情况极不可能，但协议要求报告出来。

### 9.2 G3-CM：成本模型可判别性（合并原 G3 与 G5）

**合并理由**：原 G3（"可判别决策 ≥ 8"）与 G5（"A3 与 E0 在 S2A 上存在差异"）测的是同一件事的两个门槛，重复定义只会产生两套数字。现合并为一道门，统一统计。

**统一判据（零容差，用完整 Score 不等式）**

一个 S2A 决策是**可判别**的，当且仅当：

$$\arg\min_{\text{S2A 候选}}\big(L,\ \text{deadline},\ \text{identity}\big)\ \ne\ \arg\min_{\text{S2A 候选}}\big(\text{deadline},\ \text{identity}\big)$$

其中

$$L(X)=q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X},\qquad S_X=m_X-d_{\min}(X)+1$$

- 这是**精确判据**，全部量取自该决策的实际观测（`q`、`prefill`、`S`、`m`、deadline、identity），**不含任何百分比容差**。
- 判据只涉及 S2A 决策（全部候选可评分），S2B/S2C 不参与。
- 两式 argmin 相同 → 记为 `NOT_DISCRIMINABLE`，**不计入**分子也不计入分母。

**G3-CM 必须报告三个量（逐 load 档 + 全战役）**

| # | 量 | 说明 |
|---|---|---|
| 1 | `S2A_count` | 有多少决策真正用了成本排序 |
| 2 | `discriminable_count` | 其中 A3 与 E0 **实际选择不同**的决策数 |
| 3 | `discriminable_by_load` | 上述数量的 load 分布（避免全部集中在单一档） |

**判定**：

| 条件 | 结论 |
|---|---|
| `discriminable_count ≥ 8` | `H2` 可评估 |
| `1 ≤ discriminable_count < 8` | `H2 = NOT_EVALUABLE`（**不可**写成"成本模型无价值"） |
| `discriminable_count == 0` | `H2 = NOT_EVALUABLE`，且必须报告"该负载上 A3 与 E0 从未产生不同选择" |
| `discriminable_by_load` 单档占 100% | `H2` 仅在该档可解释，另一档标 `NO_DISCRIMINABLE_DECISIONS` |

> Phase 2H 的先验：6 次决策中 4 次候选后缀全同（严格不可判别）、2 次后缀不同但 A0 选中项仍占优（按本判据亦不可判别），即 **0/6**。这是 Phase 3 最大的先验风险。

### 9.3 Profile 敏感性：正确的数学形式（本轮修正）

原协议比较的是无量纲的 `band_w` 与 `L` 的**绝对差值**，量纲不一致。修正为**相对量比较**。

**定义（逐 workload `w` 实测）**

$$\rho_w=\max_{i,j}\left|\ln\frac{\text{prefill}_i/m_i}{\text{prefill}_j/m_j}\right|$$

即该 workload 内 `prefill/m` 的相对波动幅度的对数上界（无量纲，`e^{ρ_w}` 等于原 `band_w`）。

**敏感性判据（对每次 S2A 决策）**

记该决策 `argmin L` 的选中项为 `X*`、次优为 `Y`。若 `L(Y) > L(X*)`，定义两者的相对 Score 差：

$$\delta=\left|\ln\frac{L(Y)}{L(X^*)}\right|$$

判定：

| 条件 | 标记 |
|---|---|
| `δ > ρ_w` | `PROFILE_ROBUST` — 即使 `prefill/m` 在该 workload 的实测范围内反向波动，排序也不会翻转 |
| `δ ≤ ρ_w` | `PROFILE_SENSITIVE` — 排序可能因 profile 误差翻转，**不能**作为稳健的可判别证据 |

**报告要求**：G3-CM 的 `discriminable_count` 必须拆成 `PROFILE_ROBUST` 与 `PROFILE_SENSITIVE` 两个子计数。`H2` 的判定以 `PROFILE_ROBUST` 计数为准；`PROFILE_SENSITIVE` 的决策只能进入敏感性分析。

**为什么用相对量**：`L` 与 `prefill/m` 相乘，二者的相对误差才可比；绝对差值因量纲不同无法与 `band_w` 直接比较。这也是原 14% 阈值不可移植的根本原因——它只是一个特定 workload 的 `ρ_w` 实例。

> Phase 2H 的 `prefill/m` 跨度 1.0001–1.1421 对应 `ρ_w ≈ 0.133`。该值**仅作历史参考**，Phase 3 每个 workload 各自实测 `ρ_w`。

---

## 10. 停止条件（出现即停，不追加参数搜索）

| # | 条件 | 处置 |
|---|---|---|
| S1 | 任一门 G0–G4 未通过 | 停止，报告门槛证据，不解释效果 |
| S2 | 某臂 plan/digest 不一致，或 N0 的 `boundary_id` 序列与其它臂不等 | 该 cell 作废；若 > 10% cell 作废，停止并修工具 |
| S3 | `S2B / (S2A + S2B) ≥ 20%`（全战役） | **`H2` 判 `NOT_EVALUABLE`**；`H1` 不受影响，可继续报告（但须写明回退占比） |
| S4 | `σ_run` 与效应同量级 | 停止解释，改为"需要更多 group" |
| S5 | 任一 cell 出现 `C>E` / `E>N`，或 `E` 跨臂不一致 | Fail Closed，停止并审计证据链 |
| S6 | 成本模型 `discriminable_count < 8`（G3-CM） | `H2 = NOT_EVALUABLE`，**不得**改公式/换压力重跑以追求差异 |
| S7 | `discriminable_count == 0` | `H2 = NOT_EVALUABLE`，必须报告"A3 与 E0 从未产生不同选择" |
| S8 | N0 出现 forced release（契约违反） | 该 cell 作废；若系统性发生，停止并检查策略泄漏 |
| S9 | 观测到结果后试图调整 Headroom 筛选、阈值或负载参数 | 立即停止；该战役作废，须完整重跑 |

**禁止的解释升级**（必须在报告首页出现）：

- 不得把 `A3 − A0` 的差异归因为"成本模型有效"，因为该差值混入 A1 阶梯结构与 S2B/S2C 分支（§2.2）。
- 不得因为 `S2B` 占比高就判 `H1` 不可评估（H1 问的是完整策略）。
- 不得在 `discriminable_count < 8` 时把"CI 含 0"写成"成本模型等价"。
- 不得把 `PROFILE_SENSITIVE` 的决策计入 `H2` 的可判别证据（§9.3）。
- 不得把 L3 内容级关联写成"物理因果归因"（§4.1）。

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
| 冻结协议 JSON（6 臂、20 组、负载参数、G0–G4 与 G3-CM 门槛） | M4 | 本文档经 M1 批准 |
| **E0 的 Step 2 排序变体实现**（复用 A1 阶梯，仅换排序键） | M4/M6 | M1 单独授权（属新增臂） |
| **campaign 层映射接通**（A3/E0 臂名、N0 的 `NO_FORCED_RELEASE` 判定） | M6 | 同上 |
| **N0 的 No-op 接入点确认**（保留 Pressure Request / `boundary_id` / 逻辑时间线 / Barrier，仅禁用 Forced Entry Release，并验证全臂 `boundary_id` 序列相等） | **M6 确认** | 无 |
| **任务采集可行性结论**（能否凑 20 组、Full Payload / Profile / Replay 可行性） | **M6 独立确认** | 无（并行于本协议） |
| 240-run 主战役与 30-run 噪声标定的**实测成本** | M6 | 同上 |
| 是否可加入公开 Continuum 的独立系统级对照 | M6 | 若可行，须另立协议，**不并入本六臂矩阵** |
| 20 组 task 清单与 40 条轨迹映射 | M6 | 上述可行性结论通过 |
| Headroom 筛选结果与 `σ_run` 报告（两者分开提交） | M6 | 授权 |
| 主战役执行与证据归档 | M6 | G0–G4 与 G3-CM 通过 |
| 效果分析报告（绝对 Δ + CI + 可判别数 + S2A/S2B/S2C 占比） | M4 | 主战役完成 |
| 最终结论（含 `NOT_EVALUABLE` 分支） | M1 | 上述全部 |

---

## 13. 与已有证据的关系

- Phase 2E 54-run 结论（`A1` 0 better/1 worse/8 tied，`A2` 0/3/6）**不被本协议重新解释**，只作为规模与负载参数的先验。
- Phase 2G「54/54 可被 sufficient-first + earliest deadline 复现」是本协议引入 `E0` 的直接原因。
- Phase 2I 的 `content_verified=False` 与 M3-1 1/6 是本协议 §4 的边界来源。
- Phase 2H 的 `prefill/m` 跨度 1.0001–1.1421 **只作为历史参考值**（对应 `ρ_w ≈ 0.133`），Phase 3 每个 workload 各自实测 `ρ_w`（§9.3）。
- 本协议不修改任何已封存 artifact。

---

## 14. 本版修订记录（M1 第一轮审查后）

| M1 意见 | 本版处置 | 位置 |
|---|---|---|
| A3 回退目标是冻结 A1，不是 A0 | 修正语义，新增 S2A/S2B/S2C 三分报告与统计纪律 | §2.2 |
| 主指标与归一化指标需统一 | 主指标改回绝对 `Σ(E−C)`；ratio 降为补充；新增 `E` 臂无关约束 | §3.1–§3.3 |
| 14% 不能作普适阈值 | 拆为 (a) 完整不等式精确判据、(b) 逐 workload 的相对量 `ρ_w` 稳健性分析 | §9.2、§9.3 |
| 物理归因边界 | L1–L4 重写；`16×|refetched|` 明令禁止替代 `Σ(E−C)`；新增 `ownership_level_attribution` 必写要求 | §4.1、§4.3 |
| E0 需精确定义 | 完整定义候选集/条件/排序/Tie-break/后续分支；给出与 A3 的差异清单 | §2.5 |
| N0 需精确定义 | 完整定义隔离要求；新增 `NO_FORCED_RELEASE` 判定表 | §2.6 |
| Headroom 与统计口径 | 定义筛选单位、双条件阈值、排除规则、报告字段；与噪声标定显式分离 | §3.6、§6.4 |
| 100-task pool ≠ 100 traces | 改为"候选池"口径；新增 M6 独立确认四项 | §5.1、§12 |
| 新增 G5（成本模型可分离） | 若 A3 与 E0 在全部 S2A 上相同，则 `H2 = NOT_EVALUABLE` | §9、§10（**v3 已并入 G3-CM**） |

---

## 15. 本版修订记录（M1 第二轮审查后，v3）

本轮**不改变**协议结构、六臂设计、核心假设与 310-run 预算；只修正统计层级与对照逻辑。

| # | M1 意见 | 本版处置 | 位置 |
|---|---|---|---|
| 1 | E0 与 A3 的 S2B/S2C 分支必须一致 | 冻结 **B-aligned**：E0 的 S2B 必须复用与 A3 完全相同的回退判定（任一 sufficient 候选不可评分 ⇒ 整步采用冻结 A1 键）。给出"无法对齐"时的降级：`H2` 只用 S2A 估计 + 报告剔除数与敏感性 | §2.2.1、§2.5 |
| 1b | H1 与 H2 的可评估条件必须区分 | 新增对照表：H1 覆盖**全部决策**（回退是策略的一部分）；H2 **仅 S2A**。明令不得因 S2B 超标判 H1 不可评估 | §2.2.2 |
| 2 | G2 的统计层级错误（每 cell 1 次决策却要求每 cell 有 S2A） | G2 改为**全战役与各 load 档**统计 S2A/S2B/S2C；各 cell 只作描述性。保留 S2B 比例门槛，但**不要求每 cell 为 S2A** | §9.1 |
| 2b | G2 失败应只影响 H2 | 明确：`S2B/(S2A+S2B) ≥ 20%` 或 `S2A==0` ⇒ **`H2 = NOT_EVALUABLE`**，`H1` 不受影响；`S2C` 占比高不判失败（B-aligned 下逐位相同） | §9.1、§6.6、§10 S3 |
| 3 | Headroom 不得用主战役 A0 结果事后筛选 | 改为**基于独立负载标定集、开跑前判定并冻结**（写入 G0 清单）；主战役全部 40 cell 照常执行；分析期同时报告**完整样本**与**冻结子集**；新增 S9 禁止事后调整 | §3.6、§5.2、§9 G0/G4、§10 S9 |
| 4 | 统计效力估算错误（40 cells 非独立） | 改为**每 load 档 n = 20 个独立 group**；CI 半宽由 ±620 修正为 **≈ ±875 tokens**（`1.96·2000/√20`），并注明 M1 的 ±935 来自 `t_{0.975,19}`，最终以 bootstrap 为准；明确**探索性效应量估计**定位 | §7.3、§6.1、§6.2 |
| 4b | H1/H2 判定表须分开 | 判定表按假设拆行：H1 只看 CI 方向；H2 需 CI 且有可判别决策。列出"CI 含 0"在两者下的不同含义 | §6.2 |
| 5 | 单臂噪声 ≠ 差值噪声 | 引入 `σ_delta = √2·σ_run`（独立同方差假设）；`tied` 改用 `2·σ_delta ≈ 2.83σ_run`；注明该假设不成立时的三种处理；明令 `tied` **不是**统计显著性界限 | §6.4 |
| 6 | N0 应采用 No-op 压力实现 | 首选方案改为**保留 Pressure Request / `boundary_id` / 逻辑时间线 / Pressure Barrier，仅禁用 Forced Entry Release**；删除 `pressure_stages` 降为后备且需单独验证等价性；新增 `boundary_id` 序列一致性检查（`CONTRACT_VIOLATION`） | §2.6、§6.6、§9 G1 |
| 7 | G3 与 G5 重复，应合并 | 合并为 **G3-CM**，统一统计 `S2A_count` / `discriminable_count` / `discriminable_by_load`；保留 ≥8 的门槛；原 G5 编号撤销 | §9.2、§10 |
| 7b | Profile Sensitivity 数学定义错误 | 改用**相对量**：`ρ_w = max|ln((prefill_i/m_i)/(prefill_j/m_j))|`，决策侧用 `δ = |ln(L(Y)/L(X*))|`；判据 `δ > ρ_w` ⇒ `PROFILE_ROBUST`。`discriminable_count` 须拆成 robust/sensitive 两个子计数，只有 robust 进入 `H2` | §9.3 |
| 8 | 保留 310-run 预算 | 未增加任何 run：40 负载标定 + 30 噪声标定 + 240 主战役 = **310**，与 v2 一致 | §7.1、§7.4 |
| 9 | §14 更新修订记录 | 即本节 | §15 |
