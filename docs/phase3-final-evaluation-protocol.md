# Phase 3 — Final Evaluation Protocol（M4 交付）

**状态**：`DESIGN_ONLY` — 待 M1 审查冻结。未授权任何 GPU Campaign。
**作者**：M4（协议与统计）。负载与执行可行性由 M6 另报，本协议只冻结审查所需的口径与门槛。
**输入**：Phase 1B 冻结基线、Phase 2E/2G 已封存结果、Phase 2H history-rich smoke、Phase 2I 冻结算法（PR #87）与实现（PR #88）。
**边界**：本文档只做协议设计、规模与统计评估。不启动正式运行、不改算法、不改 Runtime。

> 阅读顺序建议：§1 可证伪假设 → §2 实验组边界 → §3 指标 → §4 证据分层 → §5 负载设计 → §6 统计 → §7 规模评估 → §8–§9 门槛与停止条件。
> 若只看结论，读 §0 与 §7.4。

---

## 0. 摘要（结论先行）

1. **主指标是 `aggregate_recomputed_tokens = Σ(E − C)`，绝对 token 数，不做归一化替换。** `recompute_ratio` 与 `apc_reuse_ratio` 只作补充报告。原因：归一化分母 `N−C` 本身随策略变化（`C` 是政策输出），不能当作跨臂恒定的尺子（§3.2–§3.3）。
2. **本协议把"能否测量"与"是否有差异"分开。** Phase 2E/2G 的教训是：**全零结果不可解释**——当基线重算量本身接近 0，或所有候选的代价排序恒同时，"差异 = 0"既不支持也不否证任何算法。因此 Phase 3 必须先过 **Headroom Gate** 与 **Discriminability Gate**，否则判定 `NOT_EVALUABLE` 而不是宣布"无效果"。
3. **必须增加第 6 个实验组 `E0`：复用 A1 冻结阶梯，只把 Step 2 排序键换成 `(deadline, identity)`。** 它与 A3 只差"用不用成本模型"，因此 `A3 − E0` 是唯一能判定成本模型独立价值的对比。Phase 2G 报告 54/54 的 A1 决策可被朴素规则复现——若不设 E0，这个质疑无法被证伪。精确定义见 §2.5。
4. **`N0`（Native vLLM，无 forced release）必须存在**，否则无法回答"Continuum 式强制释放本身是否划算"这一前置问题。N0 必须与其他臂只差一件事，零强制释放判为 `NO_FORCED_RELEASE`（VALID），不得记为 FAILED。定义见 §2.6。
5. **A0 是项目侧对 Continuum 风格 Entry Release 的重实现，不是公开 Continuum 系统。** Phase 1B 已声明非逐字节等价；本项目任何结论都不得表述为"复现/优于 Continuum 论文"。
6. **A3 的回退目标是冻结 A1，不是 A0。** A3 只有 Step 2 可评分时使用 `L`；证据不足回落 A1 的 Step 2 键，`need<=0` 或不足量时委派 A1 的后续分支。因此每次释放必须归入 S2A/S2B/S2C 三类并分别报告，**不得**把 `A3 − A0` 归因为成本模型（§2.2）。
7. **20 Groups × 2 档 × 5–6 臂 = 240 run/repeat，计算成本极低（约 3–4 GPU 小时量级），但统计效力有限。** 真正约束不是成本，而是 (a) 可判别决策数、(b) 重算基线裕度、(c) 采集/转换工程量。§7.4 给出四处必要修正。
8. **Gate O 未通过不阻塞主指标。** 主指标由 Native Runtime 在请求级直接给出；但机制解释只能到**内容级时间关联**，`ownership_level_attribution = NOT_ESTABLISHED`（§4.1、§4.3）。

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

1. **必须分别报告 S2A / S2B / S2C 的计数与占比**（每 cell、每负载档、全战役）。只报整体均值会把"成本模型从未运行"与"成本模型运行了但选得一样"混为一谈。
2. **不得把 `A3 − A0` 的差异归因于"成本模型是否生效"。** `A3 − A0` 至少混入三种来源：S2A 的键差异、S2B 的 A1 键、S2C 的 A1 阶梯结构。
3. **`A3 − E0` 才是成本模型的纯净对比**，且只有在 S2A 占主导（见 §9 G2 阈值）时该对比才有判别力。若 S2C 占比很高，`A3` 与 `E0` 会因其享同一阶梯而必然一致——这同样不是"成本模型无价值"的证据。

> **这是本轮最重要的一处语义修正。** 原协议写作"A3 回落 A0"，与实际代码不符，会导致把 A1 阶梯的行为误记为 A0 的行为。

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
| **Step 2 排序键** | **`(L, deadline, identity)`**，`L = q·prefill·S/m` | **`(deadline, identity)`** |
| Step 3/4/5 | 冻结 A1 | 冻结 A1（同） |
| Block 层 | native LRU | native LRU（同） |
| 回退目标 | 冻结 A1 | 冻结 A1（同） |

因此 **`A3 − E0` 的差异只能来自\"Step 2 用不用成本模型\"**。若二者在 S2A 决策上仍选择相同项，则成本模型在该决策上不可判别（这与"成本模型无用"是两件事，见 §9 G3）。

> **E0 不读 `q` 是刻意的。** 若 E0 也用 `q` 加权，它就会与 A1 高度重合（Phase 2G 已观察到 54/54 重合），从而失去"最简强对照"的意义。E0 代表的是"一个工程师不看 KV 代价能做到的最好规则"。

### 2.6 N0 的精确定义

N0 的对照目的是 `H3`：**项目侧强制释放本身是否划算**。因此 N0 必须与其他臂**只差一件事**。

| 项 | 要求 |
|---|---|
| 请求集合 | **完全相同**（同一 plan，逐字节） |
| KV 容量、`block_size`、`max_model_len`、chunked-prefill 预算 | **完全相同** |
| 压力触发时机（round、逻辑时间边界、`boundary_id` 序列） | **完全相同**——pressure **请求仍然被提交**，只是不注入 forced entry release |
| 模型/分词器/GPU/temperature/max_new_tokens | **完全相同** |
| **唯一差异** | 不执行项目侧 Forced Entry Release（`pressure_stages` 保留为压力**信号**，但不触发 entry 释放；或按 M6 实现取 `pressure_stages: []` 且保留等价的时间推进） |

**`NO_FORCED_RELEASE` 判定（不得记为 FAILED）**

| 观测 | 判定 |
|---|---|
| run 正常完成、`forced_release_decision_count == 0` | **`NO_FORCED_RELEASE`** — 这是 N0 的**预期且正确**状态，属于 `VALID` |
| run 正常完成、但 N0 出现了 forced release | `CONTRACT_VIOLATION` — 该 cell 作废（说明泄漏了策略） |
| run 失败 / 超时 / 证据缺失 | `INCOMPLETE` — 与其它臂同样处理 |

evaluator 必须新增该分支。当前实现无此分支，N0 的零决策会被判为失败（见 §2.1 接通项 3）。

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

> **Headroom Gate（筛选单位 = cell，即 group × load 的组合）**
>
> - 判定量：该 cell 的 `A0` 臂重算量 `R0 = Σ(E−C)`，与其自身 prefill 工作量 `W0 = Σ(N−C)` 之比 `ρ0 = R0/W0`。
> - 阈值：`ρ0 ≥ 5%` **且** `R0 ≥ 512` tokens（双条件，见下）。
> - 不通过的 cell 标记 `NO_HEADROOM`，**保留在描述表**，但**不进入** `H1/H2/H3` 的估计。
>
> 这里用 `A0` 单臂的比值是安全的：它是**单臂内部**的量，不涉及 §3.3 的跨臂归一化问题。

**为什么加绝对量双条件**：`ρ0` 在小 workload 上会被少量 block 放大（如 16 tokens / 200 tokens = 8%）。绝对下界（512 tokens = 32 个 block）保证筛选出的 cell 也确实有足够的量化粒度。

**统计口径（与噪声标定分开定义）**

| 项 | 定义 |
|---|---|
| 筛选单位 | cell（40 个候选） |
| 参与估计的单位 | 过滤后的 cell，仍需按 group 配对（同一 group 的两 load 可一并保留或一并剔除） |
| **必须报告** | `N_candidate_cells = 40`、`N_no_headroom`、`N_incomplete`、`N_analyzed`，并**按 load 档分别给出** |
| **配对完整性规则** | 若某 group 的某一 load 被过滤，该 (group, load) 对从 `H1/H2` 中剔除；**同一 group 的另一 load 不受影响**，但报告中必须标注该 group 只有单档参与 |
| **最低可估计门槛** | `N_analyzed (per load) ≥ 8`；低于此值该 load 的估计标 `INSUFFICIENT_ANALYZED_CELLS` |

> 三处阈值（Headroom 的 5% / 512 tokens、噪声标定的 `σ_run`、可判别性的 8 个决策）**各自独立定义、互不推导**。噪声标定用 30 个 run 估计 run-to-run 变异，**不参与** Headroom 筛选；Headroom 筛选只用 A0 单臂的运行结果，**不参与**噪声估计。

---

## 4. 证据分层与 Gate O 的影响

### 4.1 四层证据（承接 Phase 2I，禁止互相冒充）

| 层 | 含义 | 采集方式 | 允许支持的主张 |
|---|---|---|---|
| **L1** 预测受害者 | 由冻结 eligibility + native rank 推算的 `V_X` | 决策 payload 离线复算 | 可判别性分析（§9 G3）。**不是**物理事实 |
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
> | **负载标定集** | 40 run（A0-only） | 确定 L-low/L-high 参数，使 `ρ0` 落入目标区间 | 否 |
> | **噪声标定集** | 30 run（5 组 × 2 档 × R=3，A0） | 估计 `σ_run`，定义 `tied` | 否 |
> | **主战役** | 240 run（6 臂 × 40 cell，R=1） | 效应估计 | 是 |
>
> **Headroom 筛选（G4）发生在分析期**，用的是**主战役里 A0 臂的实际结果**，不是负载标定集的结果。负载标定与 Headroom 筛选的关系是：前者用来**尽量**让 `ρ0` 落入目标区间，后者是**事后**的硬筛选，两者不可互相代替。

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

对每个 (group, load) cell 计算**绝对** delta：

$$\Delta_{\text{cell}}=\left(\sum(E-C)\right)_{\text{arm}}-\left(\sum(E-C)\right)_{A0}$$

在 group 层聚合（同 group 两 load 分别报告，不平均）。`recompute_ratio` 的 delta 作为**补充**同表给出，不参与判定（§3.3）。

报告：

- **均值 / 中位数 Δ（tokens）**，附 **95% bootstrap CI**：按 group 重采样 10,000 次，**保 load 分层**（每个 load 档内独立重采样，不合并 pool）。
- **方向计数**：better / tied / worse（`tied` 定义为 |Δ| ≤ 观测噪声地板 `2σ_run`，见 §6.4）。
- **每条 CI 旁必须并列三个计数**：`N_analyzed`（该 load 档参与估计的 cell 数）、可判别决策数、S2A 决策数。缺任一项的 CI 不得单独出现。
- **必须同时给出未归一化与归一化两栏**；若二者方向矛盾，以绝对 token 数为准，并把矛盾作为发现报告。

**判定规则（预注册）**：

| 条件 | 结论 |
|---|---|
| CI 上界 < 0 且 ≥8 个可判别决策 | 支持对应假设 |
| CI 含 0 且 ≥8 个可判别决策 | 未观察到可检测效应（`NO_DETECTABLE_EFFECT`） |
| CI 含 0 且 <8 个可判别决策 | **`NOT_EVALUABLE`**（禁止写成"无效果"） |
| CI 下界 > 0 | 观察到反向效应 |

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
| 设计 | 5 个 group × 2 load × **A0 臂** × `R=3` = 30 run |
| 输出 | `σ_run` = `Σ(E−C)` 的 run-to-run 标准差（**绝对 tokens**） |
| 用途 | 仅用于定义 `tied`；**不用于**判定 Headroom，**不用于**估计效应 |

`tied` 定义：`|Δ_cell| ≤ 2σ_run`（tokens）。若 `σ_run` 无法估计（标定集失败），**不得**默认一个数值，`tied` 记为 `UNDEFINED`，方向计数改为 better/worse 二分并声明该局限。

**与 Headroom 的区别**（M1 要求的显式分离）：

| 维度 | Headroom 筛选（§3.6） | 噪声标定（本节） |
|---|---|---|
| 目的 | 剔除"基线无重算可减"的 cell | 定义"多小算相同" |
| 输入 | 每 cell 的 A0 结果 | 5 个 group 的 **R=3** 重复 |
| 单位 | cell | run-to-run 方差 |
| 是否影响可估计的 cell 数 | **是**（过滤） | 否 |
| 是否进入主战役计数 | 否（筛选在分析期） | **否（独立 30 run，单列预算）** |

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
| **A3 全 cell 为 S2B（Step 2 回落）** | `H1/H2` 均判 `NOT_EVALUABLE`，机制结论为"Native 内容标识未接通"（工程结论） |
| **A3 全部决策为 S2C（后续分支）** | `H2` 判 `NOT_EVALUABLE`（A3 与 E0 共享阶梯，必然一致） |
| `NO_HEADROOM` cell | 不参与估计，但保留在描述表 |
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

### 7.3 20 组的统计含义（诚实评估）

| 问题 | 20 组是否足够 |
|---|---|
| 描述性覆盖（仓库异构性、负载档） | **足够**：20 组 × 2 档 = 40 单元，足以观察方向与量级 |
| 估计 `Δ` 的置信区间宽度 | **勉强**：若组间 SD ≈ 2,000 tokens，40 单元的 95% CI 半宽 ≈ ±620 tokens（约 2% of prefill） |
| 确认性显著性（小效应） | **不足**：n=20 只对 `d ≥ 0.66` 有效力 |
| 机制分析（可判别决策数） | **取决于负载**：Phase 2H 实测可判别率 0/6；若 Phase 3 仍 ~0，则 40 决策也无效 |

### 7.4 结论与四处必要修正

**结论：20 groups × 2 档 × 6 臂在成本上完全可接受，在统计上足以支撑"效应量估计"，但不足以支撑"确认性显著性"。可以按此规模执行，但必须加上：**

1. **必加 `E0` 臂**（否则 `H2` 无法证伪，成本模型的独立价值无法判定）。这需要新增一个 Step 2 排序变体（§2.1 接通项 4），属新增臂而非修改冻结算法。
2. **必加 Headroom + Discriminability 双门**（§3.6、§9 G3–G5），否则重演"全零不可解释"。
3. **必加噪声地板标定**（5 组 × 2 档 × R=3 = 30 run，独立预算），否则 `tied` 无法定义。
4. **必加 S2A/S2B/S2C 三分报告**（§2.2），否则无法区分"成本模型没运行"与"运行了但选得一样"。

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

## 9. 预注册门槛（G0–G5）

| 门 | 内容 | 失败后果 |
|---|---|---|
| **G0 冻结** | 6 臂定义（含 E0/N0 精确规格）、指标、20 组、负载参数、profile 版本、replay checkpoint 规则全部 SHA-256 绑定 | 不允许开跑 |
| **G1 隔离性** | 每 cell 的 plan/config（除 policy 字段）SHA-256 全臂相等；模型/tokenizer/GPU/KV 容量一致；逐请求 `E` 全臂相等 | 该 cell 作废 |
| **G2 A3 生效（三分报告）** | 每 cell 分别统计 **S2A / S2B / S2C** 占比（§2.2）。要求 `S2A_count ≥ 1` 且 `S2B / (S2A+S2B) < 20%` | `H1/H2` 判 `NOT_EVALUABLE`（而不是"无效果"） |
| **G3 可判别性** | 见下（两件事分开） | < 8 个实际可判别决策 → `NOT_EVALUABLE`，**停止解释** |
| **G4 裕度** | 每 cell `ρ0 = R0/W0 ≥ 5%` **且** `R0 ≥ 512` tokens，否则 `NO_HEADROOM` | 该 cell 不进入估计 |
| **G5 成本模型可分离** | A3 与 E0 在 A3 的 S2A 决策上存在选择差异 | 若 `A3` 与 `E0` 在全部 S2A 决策上选择相同 → `H2 = NOT_EVALUABLE` |

### 9.1 G3 的两件事必须分开（原 14% 阈值的修正）

原协议把 Phase 2I 的 14% 当作普适判据，**这是错的**：14% 只是 Phase 2H 那个特定 workload 上 `prefill/m` 的波动范围（实测 1.0001–1.1421），它描述的是**该负载的 profile 形状**，不能升级为所有新 workload 的通用阈值。

因此定义两个**独立**的量：

**(a) 实际可区分性 — 用完整 Score 不等式，不用任何百分比阈值**

对每次 S2A 决策，A3 与 E0 的选中项不同当且仅当：

$$\exists Y:\ \frac{q_Y\,\text{prefill}_Y\,S_Y}{m_Y}<\frac{q_{X^*}\,\text{prefill}_{X^*}\,S_{X^*}}{m_{X^*}}\quad\text{且}\quad (deadline_Y, id_Y)>(deadline_{X^*}, id_{X^*})$$

- 这是**精确判据**，基于实际观测到的 `q`、`prefill`、`S`、`m`，**不含任何容差**。
- 一个决策"可判别" ⟺ `argmin (L, deadline, identity)` ≠ `argmin (deadline, identity)`。
- 若两者相等，该决策记为 `NOT_DISCRIMINABLE`，**不计入** G3 的分母/分子。

**(b) 对 profile 变化的稳健性 — 用该 workload 实测的 `prefill/m` 跨度，逐 workload 计算**

$$\text{band}_{w}=\max_{i,j}\frac{\text{prefill}_i/m_i}{\text{prefill}_j/m_j}\quad(\text{该 workload } w \text{ 的实测跨度})$$

用途**仅是敏感性分析**：

> 若某决策的 `L` 差幅小于该 workload 的 `band_w`，则该决策的"可判别"结论**对 profile 误差敏感**，在报告中标记 `PROFILE_SENSITIVE`，并给出"若 `prefill/m` 取反方向时的翻转概率"。

它**不参与** G3 的判定，也**不**把"14%"写成常数。Phase 2H 的 14% 只作为历史参考值出现在脚注。

**G3 判定**：`discriminable_count ≥ 8`（跨全战役、按 load 分别统计）才允许解释 `H1/H2`。

> Phase 2H 的先验：6 次决策中 **4 次候选后缀全同**（严格不可判别）、**2 次后缀不同但 A0 选中项仍占优**（按 (a) 判据亦不可判别），即 **0/6**。这是 Phase 3 最大的先验风险，也是必须设 G5 的原因。

---

## 10. 停止条件（出现即停，不追加参数搜索）

| # | 条件 | 处置 |
|---|---|---|
| S1 | 任一门 G0–G5 未通过 | 停止，报告门槛证据，不解释效果 |
| S2 | 某臂 plan/digest 不一致 | 该 cell 作废；若 > 10% cell 作废，停止并修工具 |
| S3 | `S2B / (S2A + S2B) > 20%` | 停止，判定内容标识未接通（**工程结论，不是算法结论**） |
| S4 | 观测到 `σ_run` 与效应同量级 | 停止解释，改为"需要更多 group" |
| S5 | 任一 cell 出现 `C>E` / `E>N`，或 `E` 跨臂不一致 | Fail Closed，停止并审计证据链 |
| S6 | 主指标 CI 含 0 且可判别决策 < 8 | 输出 `NOT_EVALUABLE`，**不得**改公式/换压力重跑以追求差异 |
| S7 | A3 与 E0 在全部 S2A 决策上选择相同（G5 失败） | `H2 = NOT_EVALUABLE`；**不得**用 `A3 − A0` 代替成本模型价值 |
| S8 | N0 出现 forced release（契约违反） | 该 cell 作废；若系统性发生，停止并检查策略泄漏 |

**禁止的解释升级**（必须在报告首页出现）：

- 不得把 `A3 − A0` 的差异归因为"成本模型有效"，因为该差值混入 A1 阶梯结构与 S2B/S2C 分支（§2.2）。
- 不得把"CI 含 0"写成"算法等价"，除非 G3 与 G5 均通过。
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
| 冻结协议 JSON（6 臂、20 组、负载参数、G0–G5 门槛） | M4 | 本文档经 M1 批准 |
| **E0 的 Step 2 排序变体实现**（复用 A1 阶梯，仅换排序键） | M4/M6 | M1 单独授权（属新增臂） |
| **campaign 层映射接通**（A3/E0 臂名、N0 的 `NO_FORCED_RELEASE` 判定） | M6 | 同上 |
| **任务采集可行性结论**（能否凑 20 组、Full Payload / Profile / Replay 可行性） | **M6 独立确认** | 无（并行于本协议） |
| 240-run 主战役与 30-run 噪声标定的**实测成本** | M6 | 同上 |
| 是否可加入公开 Continuum 的独立系统级对照 | M6 | 若可行，须另立协议，**不并入本六臂矩阵** |
| 20 组 task 清单与 40 条轨迹映射 | M6 | 上述可行性结论通过 |
| Headroom 筛选结果与 `σ_run` 报告（两者分开提交） | M6 | 授权 |
| 主战役执行与证据归档 | M6 | G0–G5 通过 |
| 效果分析报告（绝对 Δ + CI + 可判别数 + S2A/S2B/S2C 占比） | M4 | 主战役完成 |
| 最终结论（含 `NOT_EVALUABLE` 分支） | M1 | 上述全部 |

---

## 13. 与已有证据的关系

- Phase 2E 54-run 结论（`A1` 0 better/1 worse/8 tied，`A2` 0/3/6）**不被本协议重新解释**，只作为规模与负载参数的先验。
- Phase 2G「54/54 可被 sufficient-first + earliest deadline 复现」是本协议引入 `E0` 的直接原因。
- Phase 2I 的 `content_verified=False` 与 M3-1 1/6 是本协议 §4 的边界来源。
- Phase 2H 的 `prefill/m` 跨度 1.0001–1.1421 **只作为历史参考值**，不作为新 workload 的判据（§9.1）。
- 本协议不修改任何已封存 artifact。

---

## 14. 本版修订记录（M1 第一轮审查后）

| M1 意见 | 本版处置 | 位置 |
|---|---|---|
| A3 回退目标是冻结 A1，不是 A0 | 修正语义，新增 S2A/S2B/S2C 三分报告与统计纪律 | §2.2 |
| 主指标与归一化指标需统一 | 主指标改回绝对 `Σ(E−C)`；ratio 降为补充；新增 `E` 臂无关约束 | §3.1–§3.3 |
| 14% 不能作普适阈值 | 拆为 (a) 完整不等式精确判据、(b) 逐 workload 的 `prefill/m` 稳健性分析 | §9.1 |
| 物理归因边界 | L1–L4 重写；`16×|refetched|` 明令禁止替代 `Σ(E−C)`；新增 `ownership_level_attribution` 必写要求 | §4.1、§4.3 |
| E0 需精确定义 | 完整定义候选集/条件/排序/Tie-break/后续分支；给出与 A3 的差异清单 | §2.5 |
| N0 需精确定义 | 完整定义隔离要求；新增 `NO_FORCED_RELEASE` 判定表 | §2.6 |
| Headroom 与统计口径 | 定义筛选单位、双条件阈值、排除规则、报告字段；与噪声标定显式分离 | §3.6、§6.4 |
| 100-task pool ≠ 100 traces | 改为"候选池"口径；新增 M6 独立确认四项 | §5.1、§12 |
| 新增 G5（成本模型可分离） | 若 A3 与 E0 在全部 S2A 上相同，则 `H2 = NOT_EVALUABLE` | §9、§10 |
