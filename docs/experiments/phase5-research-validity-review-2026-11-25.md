# Phase 5 研究有效性审查与必要修订建议

**审查日期：** 2026-11-25  
**审查基线：** main `3ede01356d5e3f9c014bea8a31c4ef5aa1a4eb54`；PR #135–#137 审查时仍为 open，PR #138 已合并  
**审查范围：** PR #135–#138、Phase 5 Formal Protocol、Metrics Contract、DVA-ER v1、SWE Cohort 与 BFCL Derived Supplement  
**性质：** M4 研究设计审查；不修改 PR #138 已冻结的 SWE Cohort、Group 和 Arrival，不重新开启双正式负载设计，不改变 `E−C` 主指标或 Workload Group 独立单位。  
**执行边界：** 不授权 GPU、Calibration、Formal Campaign 或任何算法收益结论。

---

# 0. 总体判断

Phase 5 目前具备三样东西：

1. 一个可执行的六系统比较框架；
2. 一套已经冻结的 SWE Candidate Cohort 和 Group/Arrival 设计；
3. 一套较完整的系统级指标与部分决策级诊断指标。

但当前设计还不足以直接支撑“为什么有效/无效”的完整机制结论。主要问题不是指标数量不够，而是**指标之间的证据链还没有被冻结成可判定的层级**。

当前最需要明确的五个判断：

```text
SYSTEM_LEVEL_COMPARISON = DESIGNED
DECISION_LEVEL_DESCRIPTION = PARTIALLY_INSTRUMENTED
PHYSICAL_VICTIM_CAUSALITY = NOT_ESTABLISHED
DOWNSTREAM_RECOMPUTE_CAUSALITY = NOT_ESTABLISHED
DVA_ER_PREDICTIVE_VALIDITY = NOT_ESTABLISHED
```

以及两个数据层结论：

```text
SWE_RIGHT_CENSORING_SENSITIVITY = NOT_ESTIMABLE
SWE_FORMAL_N_ABOVE_8 = NOT_MATERIALIZABLE_WITH_CURRENT_48_PROGRAMS
```

---

# 1. PR #135–#137 与 Phase 5 的理论联系

不能把三份公开研究当成三个并列的“背景结果”。它们分别回答链条上的不同环节。

## 1.1 PR #135：真实 Agent 工作负载支持什么

PR #135 的 Nebius OpenHands 分析支持以下**工作负载结构**：

- 长程 Agent 执行会持续累积上下文；
- 相邻 Turn 有很高的前缀复用；
- 工具调用和工具结果占据新增上下文的很大一部分；
- 不同 Issue、不同重试以及同 Issue 重试之间存在可构造的共享头部和不同尾部；
- Agent 工作负载不是“每轮独立请求”，而是有生命周期的 Program/Session。

它支持 Phase 5 的假设：

> 如果缓存能够在工具间隔期间保留可复用 Entry，并在需要时做出合理的 Release/Victim 选择，那么有机会减少重复 Prefill。

但它**不支持**：

- 我们的 vLLM Native Cache 一定命中这些前缀；
- 我们的 A0/A1/A3/DVA-ER 一定减少重计算；
- 公开轨迹的 Turn 分布就是 Phase 5 SWE 的分布；
- 公开数据的 prefix LCP 等于 Native APC 的 `E` 或 `C`。

PR #135 的 OpenHands/Qwen3 轨迹与 Phase 5 的 mini-SWE-agent/Qwen2.5-Coder-1.5B 采集不是同一个模型、运行时或采集协议。它只能支持“机会存在”，不能替代 Phase 5 的运行证据。

对 Phase 5 的影响：

- 保留真实长会话和工具间隔，不应把 Turn 当成独立样本；
- 在 SWE 数据报告中加入长度、前缀复用和工具间隔的描述，用于判断 Phase 5 是否真的覆盖了相似结构；
- 不把公开数据的 LCP 直接填入 `E`/`C` 指标；
- Candidate Exposure 和 multi-candidate rate 必须作为正式机制前置条件，而不是事后补充。

## 1.2 PR #136：成本几何如何解释 Entry Release 与未来重算

PR #136 的离线 Oracle/几何分析支持以下条件性结论：

- 共享祖先可能属于多条链；
- 释放一个浅层 Block 可能同时破坏多个下游路径；
- 独占后缀的厚度、深度和返回顺序会改变同等预算下的损失；
- “释放哪个 Entry”与“Native 接下来选哪些物理 Block”不是同一个问题；
- 只看 Entry 数量或简单后缀长度，可能无法解释实际损失。

它支持 Phase 5 的假设：

> 在相同决策快照、相同候选集和相同预算下，不同的 Entry Release 可能通过不同的物理 Victim 序列造成不同的下游重算。

但它**不支持**：

- 公开数据的 Oracle 损失等于我们 Native 运行的实际损失；
- A1、A2、A3、DVA-ER 的真实 rank、deadline、profile 或 armed timer 已经被观测；
- 公开数据中的 synthetic touch order 等于我们运行时的 Native LRU 顺序；
- 几何代理的零 regret 可以外推为实际系统收益。

对 Phase 5 的影响：

- 需要把 **selection divergence → predicted victim set → actual physical victim set → downstream reuse → E−C** 拆开；
- `victim_set_divergence` 必须区分 predicted 与 actual；
- `physical_victim_sequence` 必须绑定同一个 decision/pressure boundary；
- 不能只报告 `E−C` 的变化，然后把它解释成“Entry Release 改善了缓存”。

## 1.3 PR #137：DVA-ER 揭示了什么缺口

PR #137 的核心裁定是：

```text
DVA_ER_PREDICTIVE_VALIDITY = NOT_EVALUABLE
DVA_ER_NATIVE_RECOMPUTE_CAUSALITY = NOT_ESTABLISHED
```

它指出：

- 历史 Native 归档缺少完整的 DVA-ER score、候选集、实际 victim set 和逐 victim 下游归因；
- Phase 3 的 127 个决策中 120 个是单候选，只有 7 个竞争决策；
- 相同预测 victim set 必然同分，count-only 指标可能全并列；
- 历史简单深度代理在小样本上甚至方向相反；
- H=60s、A0 tie-break 和 DVA-ER 实测收益都未被检验；
- armed timer、完整 Native rank/refcount、候选逐块归因仍然缺失。

对 Phase 5 的影响：

- DVA-ER 不能以“CPU 正确性”或“决策可以不同”替代 Native 预测有效性；
- Phase 5 必须先证明 DVA-ER 的决策差异能够传导到 physical victim，再证明下游 reuse/recompute 差异；
- 如果只有算法内部分数变化，没有 physical/downstream 差异，只能报告“决策差异未传导”，不能报告“算法收益”；
- H=60s 必须被标记为设计先验，不是经验估计。

## 1.4 统一逻辑链

建议把 Phase 5 的研究逻辑固定为：

```text
真实 Agent 工作负载
  → 上下文与复用结构
  → KV Cache 生命周期
  → Entry Release 决策
  → Native Physical Eviction
  → 下游实际复用与重算
  → 系统级 E−C / 服务指标
```

每一段都需要独立证据：

| 环节 | 需要的证据 | 公开数据能否替代 |
|---|---|---|
| 工作负载 | 真实 Session、Turn、工具间隔、前缀复用 | 只能提供动机，不能替代 Phase 5 |
| 生命周期 | Entry 保护、TTL、refcount、owner | 不能 |
| Entry Release | 合法候选、A0 顺序、候选分数 | 不能 |
| Physical Eviction | 同 EngineCore、同决策、实际 victim 序列 | 不能 |
| 下游复用 | 后续真实请求、相同链、命中/重算 | 不能从静态 LCP 直接替代 |
| 系统效果 | Group 级 E−C、TTFT、Latency、Throughput、Memory | 不能 |

---

# 2. 系统级效果评价

## 2.1 主指标 `E−C` 是否与研究目标一致

**一致，但不能单独承担全部结论。**

`E−C` 表示“本来可复用的 eligible prefix 中，实际没有被 Native 缓存命中、因此需要重算的 Token 数”。它直接对应 Entry Release/Victim 选择的潜在代价，适合作为系统级 primary。

但必须明确：

- `E−C` 不是完整 Prefill 成本；`N−C` 才是实际 Prefill 工作量；
- `E−C` 下降不必然导致 TTFT/Latency 等比例改善；
- `E−C` 也不证明变化来自 Entry Release，而不是调度、batching、cache 状态或测量噪声；
- `E−C` 是 Group 级聚合指标，不是 Request 级独立样本。

因此建议保留：

```text
PRIMARY: recomputed_tokens_E_minus_C
SECONDARY: actual_prefill_tokens_N_minus_C
SERVING: TTFT / latency / throughput / completion_time
RESOURCE: GPU memory / admission queue / peak inflight / policy overhead
DIAGNOSTIC: candidate/decision/victim/downstream metrics
```

不改主指标，但必须同时报告 `N−C`，避免把“eligible 重算减少”解释成“实际 Prefill 成本同比例下降”。

## 2.2 指标冗余与解释边界

当前指标中需要明确以下关系：

| 指标 | 解释 | 不应声称 |
|---|---|---|
| `E−C` | eligible-prefix 重算 | 不是全部 Prefill 成本 |
| `N−C` | 实际 Prefill Token | 不是纯策略效果 |
| `C/E` | eligible prefix 命中比例 | 不是全局 cache hit rate |
| `C/N` | prompt 命中比例 | 不是 hit rate |
| TTFT | 首 Token 延迟 | 不必然与 E−C 同方向 |
| Latency/Throughput | 系统级服务 | 受 batching/调度影响 |
| Memory | 资源占用 | 不是策略收益 |

建议在 Metrics Contract 中把：

- primary；
- secondary system；
- serving；
- resource；
- mechanism diagnostic；

作为**固定的报告层级**，禁止用结果选择一个“更好看”的指标作为主结论。

## 2.3 Group-level 统计单位

当前 `Workload Group` 是独立单位，这是正确的。

必须保持：

- 同一 Group 的 4 个 Program 是匹配的；
- Turn、Request、Tool Call、Repeat 不是独立样本；
- 同一 Program 的跨系统结果不是独立样本；
- 同一 Group 的 2 次 Repeat 不是独立样本；
- Decision-level 诊断只能做描述性/聚类，不得把 decision 当独立观测做显著性检验。

需要特别防止：

- 把 48 个 Program 当成 48 个独立系统比较样本（实际是 12 个 Group）；
- 把 46 个 right-censored Session 当成额外统计功效；
- 把 decision-level 的数千条记录当成数千个独立样本。

---

# 3. 决策级机制评价

## 3.1 现有指标能回答什么

现有 Metrics Contract 已经包含：

- Candidate Exposure；
- Candidate Score Distribution；
- Pairwise Rank Inversion；
- Selection Divergence；
- Victim Set Divergence；
- Physical Victim Sequence；
- Downstream Reuse；
- Evidence Coverage；
- Fallback Rate；
- Matched/Unmatched Physical Victim Blocks。

这些指标足以做**描述性机制审查**，但不足以自动证明因果机制。

## 3.2 需要明确的证据链

建议冻结以下“机制证据层级”，不新增替代主指标：

| Level | 证据 | 可支持的结论 |
|---|---|---|
| **M0** | 合法候选数、fully scored 数、candidate exposure | 是否存在决策空间 |
| **M1** | 同一 snapshot 下的 score/rank inversion、selection divergence | 算法是否做出不同选择 |
| **M2** | 同一决策下 predicted victim sequence 是否不同 | 选择差异是否改变预测物理对象 |
| **M3** | predicted victim 与 actual physical victim 的 matched/unmatched | 是否真正改变 Native eviction |
| **M4** | 后续真实请求是否触及 candidate chain，是否产生可归因重算 | 是否改变下游复用 |
| **M5** | Group 级 E−C 与 serving 指标 | 是否形成系统级效果 |

当前 Contract 的 `causal_boundary` 已正确写明：

```text
physical_causal_attribution = NOT_ESTABLISHED
downstream_recompute_attribution = NOT_ESTABLISHED
```

这应当保留，不能因为 Phase 5 新增了 M2/M3 指标就自动升级为因果结论。

## 3.3 各诊断指标的使用条件

### Candidate Exposure

必须报告分母：

- decisions；
- legal candidates；
- fully scored candidates；
- multi-candidate decisions；
- single-candidate decisions。

只有 multi-candidate decisions 才可能产生 selection divergence。  
单候选比例过高时，算法差异没有发挥空间，不能把系统结果解释为“算法无效”。

### Candidate Score Distribution

只能在同一决策 snapshot、同一候选集、同一算法定义下比较。  
A1/A3/DVA-ER 的 score 量纲不同，不能直接做跨算法数值比较；应比较同一 snapshot 内的 rank 和选择。

### Pairwise Rank Inversion

必须按同一 snapshot 内的候选对计算，且只在双方都 fully scored 时计入。  
不能把不同 decision 的分数拼成一对。

### Selection Divergence

只对 multi-candidate decisions 有意义。  
需要区分：

```text
NO_MULTI_CANDIDATE
SAME_SELECTION
DIFFERENT_SELECTION
UNSCOREABLE
```

### Victim Set Divergence

必须区分：

```text
predicted victim sequence
actual physical victim sequence
```

当前 `victim_set_divergence` 的公式描述容易混用二者。建议在报告中强制使用两个不同字段名，并在 `matched_physical_victim_blocks`、`unmatched_physical_victim_blocks` 中绑定同一 `(run_id, decision_id, pressure_request_id)`。

### Physical Victim Sequence

需要同 EngineCore、同决策边界、同 Block 身份、同 hash process。  
没有这些证据时只能是 `NOT_OBSERVABLE`，不能以 Block ID 相似或时间接近替代。

### Downstream Reuse

只能使用决策之后实际观测到的请求和真实链身份。  
`NO_FOLLOWUP`、`CENSORED`、`UNOBSERVED` 不能填零；右删失不能当作“没有复用”。

### Evidence Coverage

必须作为所有机制结论的分母：

```text
evidence_coverage = fully_joined_decisions / valid_decisions
```

低覆盖时，机制结论应降级为 `INSUFFICIENT_EVIDENCE`，不能只报告通过子集。

## 3.4 不能通过新增指标掩盖缺口

不建议新增更多“综合机制分数”。  
当前缺的是：

- decision 级 physical binding；
- downstream label；
- evidence coverage；
- staged conclusion gate。

这些是**证据连接问题**，不是再加一个统计指标能解决的。

---

# 4. DVA-ER 专项审查

## 4.1 H=60s 的依据

**没有充分的经验依据。**

H=60s 是一个设计先验，来自 Phase 4 的 60 秒 TOOL_GAP proxy 和工程直觉；PR #137 已明确：

- 旧归档缺少 `CONTROLLER_ARMED_TIMER`；
- Phase 4 的 60 秒代理 AUC 约 0.594，只有弱区分；
- 公开轨迹没有秒级工具间隔；
- H=60 没有被 Native 结果校准。

因此：

```text
H_60s = DESIGN_PRIOR_NOT_EMPIRICALLY_CALIBRATED
```

不能在看到结果后把 H 调到更有利的值。

## 4.2 30/60/120 敏感性分析应回答什么

敏感性分析应回答：

1. 在不同 H 下，**同一决策的 candidate ranking 是否改变**；
2. 在不同 H 下，**selection divergence 是否改变**；
3. 在不同 H 下，**predicted victim set 是否改变**；
4. 如果这些都没有改变，H 不构成解释变量；
5. 如果只有 selection 改变但 physical victim 不变，说明 score 变化没有传导；
6. 不能把“某个 H 下 E−C 最低”当作选择 H 的依据。

报告应固定为：

```text
H ∈ {30, 60, 120}
primary reporting = H=60
sensitivity = H=30/120
no post-outcome H selection
```

## 4.3 Controller Armed Timer 是否对应在线信息

只有当 timer 满足以下条件时，才对应我们希望利用的在线信息：

- `pending_tool_gap_source = CONTROLLER_ARMED_TIMER`；
- observation timestamp 和 chain establishment timestamp 均不晚于 decision timestamp；
- 不是事后 `TOOL_GAP_STARTED`、历史 gap、下一请求 arrival 或 trace 回放推断；
- timer 在决策时确实处于 armed 状态；
- missing/ambiguous → Fail Closed。

如果不是这五条，DVA-ER 的“未来需求”就是事后信息，不能用于在线策略。

## 4.4 Follow-up Chain 与 Program/Session 身份

合理的关系应是：

```text
Program identity
  → Session identity
  → Follow-up chain identity
  → candidate/owner
```

要求：

- chain 在决策前已经建立；
- chain 不跨 Program 误连；
- Session identity 不能从未来 trace 推断；
- 同一个 Program 的多次尝试不能共享错误的 chain；
- owner 到 chain 的映射必须显式。

当前 DVA-ER 实现已有 chain/timestamp/source 校验，这是正确的；Phase 5 需要在 live evidence 中保持同样的严格性。

## 4.5 DVA-ER 相比 A1/A3 增加了什么信息

| 方法 | 主要信息 | 是否使用实际 victim 序列 | 是否使用 active follow-up |
|---|---|---|---|
| A1 | cost / deadline / reuse proxy | 否 | 否 |
| A3 | suffix cost `S/m` | 部分结构，不是完整 physical victim | 否 |
| DVA-ER | 候选释放后的 Native LRU victim 序列 + follow-up risk | 是，预测序列 | 是 |

DVA-ER 新增的是：

1. 对每个候选的**完整预测 physical victim prefix**；
2. victim block 的 **owner/active follow-up** 风险；
3. 以 A0 顺序作为同分 tie-break。

它没有新增：

- source-observed future request；
- 真实 Native 物理执行；
- 真实下游重算标签。

## 4.6 什么情况下 DVA-ER 应产生不同 Victim Set

必要条件：

1. 至少 2 个合法候选；
2. 候选释放后 eligibility/victim prefix 不同；
3. 至少一个候选的 victim set 覆盖 active follow-up block，另一个不覆盖或覆盖更少；
4. 这些差异发生在同一 pressure budget 和同一 decision snapshot；
5. 选择结果不同；
6. Native 实际 victim 与预测一致。

如果 1–6 不成立，DVA-ER 不应产生 different physical victim set。

## 4.7 没有决策差异时如何解释

必须分阶段标记，而不是笼统说“DVA-ER 无效”：

```text
NO_MULTI_CANDIDATE
SAME_PREDICTED_VICTIM_SET
SAME_RISK_MASK
SAME_SELECTION
SAME_PHYSICAL_VICTIM
SAME_DOWNSTREAM_REUSE
NO_OBSERVED_FOLLOWUP
INSUFFICIENT_EVIDENCE
```

只有最后两层（physical/downstream）都没有差异，才能说“在当前 workload 上没有观察到 DVA-ER 的机制传导”；不能反推“DVA-ER 在总体上无效”。

## 4.8 三个层次不能混为一谈

```text
CPU correctness
  ≠ decision distinguishability
  ≠ Native predictive validity
  ≠ real workload benefit
```

当前 28 个 CPU tests 只支持第一层；PR #137 说明第二、三层仍为 `NOT_EVALUABLE`。

---

# 5. SWE-only 数据与统计设计

## 5.1 当前 Cohort

PR #138 冻结：

```text
48 Programs
12 Groups × 4 Programs
Calibration: SWE_G01–G04 = 16 Programs
Formal Candidate: SWE_G05–G12 = 32 Programs
```

该成员、顺序、repository diversity、disjointness 与 arrival 设计均已通过 M4 targeted review。这里不重新打开。

## 5.2 单 Stratum 后统计合同尚未同步

这是当前最严重的合同缺口。

Scope Amendment 已把 SWE 定为**唯一正式 Stratum**，但当前 Calibration Contract 仍然写着：

```text
strata = 2
calibration runs = 144
df_between = 6
df_within = 16
df_total = 22
formal runs = 192/288/384
```

在 single-stratum 下应改为：

```text
strata = 1
calibration groups = 4
calibration runs = 6 × 4 × 3 = 72
df_between = 4 - 1 = 3
df_within = 4 × (3 - 1) = 8
df_total = 11
df_covariance = 3
formal runs = 96 / 144 / 192 at N = 8 / 12 / 16
```

方差模型应从：

```text
d_{g,r,s} = μ + τ_s + b_{g(s)} + ε
```

改为单 stratum：

```text
d_{g,r} = μ + b_g + ε_{g,r}
```

这是 model/df/covariance 的变化，不只是 run count 变化。当前 `BETWEEN` 的 `df=6` 和 `within=16` 若继续用于 SWE-only，会高估有效样本量并低估不确定性。

**必须由 M1 裁定并修订 Calibration Contract、Protocol JSON、schema、backend 和 tests。**

## 5.3 Formal N 只能支持 8

当前 48 Programs 只能形成：

```text
4 Calibration + 8 Formal = 12 Groups
```

如果 Calibration 的 sample-size 方法返回 N>8，当前数据不足。此时必须：

```text
STOP
→ return to M1
→ additional outcome-blind data source decision
```

不能：

- 降低 power；
- 复用 Calibration Groups；
- 创建 pseudo-replicates；
- 把 48 个 Program 重复使用。

## 5.4 Right-censoring 敏感性分析

当前：

```text
Natural Terminal = 2
Right-Censored = 46
```

Primary 分析：

- 包含 right-censored；
- 只使用已观测有效 Turns；
- 不补造未来 Turns。

Sensitivity 分析：

- 排除 right-censored；
- 只剩 2 个 Natural Terminal Program。

由于 Group 必须由 4 个独立 Program 构成：

```text
4 Programs per Group
2 natural Programs total
→ 0 complete four-Program Groups
```

因此：

```text
SWE_RIGHT_CENSORING_SENSITIVITY = NOT_ESTIMABLE
```

不能：

- 把 2 个自然 Program 当作一个 Group；
- 把 right-censored Program 补进“敏感性 Group”；
- 降低 Group 必须 4 Program 的要求；
- 用 Program-level 显著性替代 Group-level 正式分析。

可以报告：

- 2 个自然 Program 的描述性个案；
- right-censoring 比例；
- primary 中 censored 的影响；
- 不能声称 sensitivity 估计。

## 5.5 Program / Group / Session / Turn 单位

保持：

- Group 是独立统计单位；
- Program 是 Group 内成员；
- Session 是 Program 的一次执行；
- Turn 不是独立样本；
- Repeat 不是独立 Group。

当前 48 Programs、12 Groups；formal N=8；统计功效基于 8 个 Group，不是 32 个 Program、也不是 48 个 Program。

## 5.6 主分析与敏感性分析的“实际可估计性”

建议明确：

| 分析 | 状态 |
|---|---|
| Primary Group-level E−C | 可估计，但只有 8 Formal Groups |
| Censored vs non-censored | `NOT_ESTIMABLE` |
| Excluding right-censored | `NOT_ESTIMABLE` |
| Program-level descriptive | 可报告，不是正式推断 |
| Turn/request-level significance | 禁止 |

---

# 6. BFCL Derived 的研究定位

## 6.1 4 个 Calibration Group 能回答什么

只能回答：

- 在固定的 1 秒 synthetic Tool Gap 下，指标和证据合同是否可执行；
- 受控时序下决策空间、candidate exposure、victim divergence 的描述；
- instrumentation、日志、manifest、Q4D/Q5D 合同；
- 为后续 exploratory 研究提供描述性方差和运行经验。

不能回答：

- formal sample size / power；
- natural Tool Gap 分布；
- BFCL Native 策略收益；
- 与 SWE 合并的总体效果。

## 6.2 8 个 Evaluation Group 能回答什么

只能回答：

- controlled-timing 条件下的 exploratory 机制观察；
- 不同系统的 decision-level 差异；
- 在 synthetic schedule 下的 E−C 描述性差异；
- 作为补充性、假设生成研究。

不能支持：

- confirmatory BFCL claim；
- natural-time serving 结论；
- SUT/缓存收益；
- 与 SWE Formal 的 pooled estimate。

## 6.3 Synthetic Gap 与 Terminal 的限制

```text
SYNTHETIC_CONTROLLED_NOT_SOURCE_OBSERVED
SOURCE_TERMINAL_UNKNOWN
REPLAY_TRACE_EXHAUSTED
```

限制：

- 不能恢复源系统的真实 Tool Gap 分布；
- 不能恢复自然 terminal；
- 不能推断自然完成后是否会继续请求；
- 不能推断真实网络/工具延迟；
- 不能把 `REPLAY_TRACE_EXHAUSTED` 当成 `COMPLETED`；
- 不能把 controlled E−C 解释成 natural-time benefit。

BFCL 的 40 个 context-excluded Session、10 个 min-turn-unqualified Group 也要在报告中明确，不能只报告 4+8 的“好看”子集。

## 6.4 与 SWE 的关系

```text
SWE = sole formal stratum
BFCL Derived = independent supplementary experiment
No pooled estimate
No shared Calibration/power/multiplicity
No formal BFCL Native Stratum
```

---

# 7. 当前设计的缺口清单

| 严重度 | 缺口 | 影响 |
|---|---|---|
| **Critical** | Single-stratum Calibration Contract 仍为 two-strata（df=6/16/22, 144 runs, 192–384 formal） | 直接导致错误的方差、df、样本量和资源计划 |
| **Critical** | Right-censoring sensitivity 只有 2 Natural Programs，无法组成 4-Program Group | `NOT_ESTIMABLE`；不能声称做了 censored sensitivity |
| **Critical** | Formal N>8 在当前 48 Programs 下不可实现 | Calibration 若要求 N>8，必须停止并回 M1 |
| **Critical** | DVA-ER 没有 Native predictive validity 或 candidate-level downstream labels | 不能把 CPU 正确性/决策差异当成收益 |
| **Critical** | Decision→physical→downstream 证据链未建立 | 不能从 E−C 关联推出机制因果 |
| **High** | 公开工作负载与 Phase 5 SWE 的模型/采集协议不同 | 只能做动机，不能外推 Native 结果 |
| **High** | E−C 与 N−C、C/E、C/N、serving 指标的解释边界未统一 | 可能产生重复或错误表述 |
| **High** | Decision metrics 缺少统一 denominator/evidence coverage | 容易只报告通过子集 |
| **High** | Calibration 只有 4 Groups，df 很低 | 区间宽、功效有限，必须报告不确定性 |
| **Medium** | BFCL Derived 4+8 不是 formal；synthetic timing | 只能 supplemental/exploratory |
| **Medium** | 10 个 BFCL min-turn Group 被排除；40 个 context Session 被排除 | 选择性和外部有效性限制 |
| **Medium** | Arrival 是 controlled Poisson，不是自然到达 | 不能声称自然并发/服务分布 |
| **Medium** | Decision-level diagnostics 易被当作独立样本 | 统计单位错误 |

---

# 8. 必要修订建议

以下修改需要 M1 裁定；本报告不直接改 frozen JSON。

## 8.1 Single-stratum Protocol / Calibration Contract

建议把：

```text
strata = 2
calibration_groups = 8
calibration_runs = 144
df_between = 6
df_within = 16
df_total = 22
formal_runs = 192/288/384
```

改为：

```text
strata = 1
calibration_groups = 4
calibration_runs = 72
df_between = 3
df_within = 8
df_total = 11
df_covariance = 3
formal_runs = 96/144/192
```

并同步：

- Protocol JSON 的 `strata`、run counts、formal counts；
- Calibration backend 的 variance model；
- covariance/PSD/df；
- noncentral-t 与 bootstrap；
- campaign plan、schema、validators、tests；
- 资源预算与 GPU-hour projection。

## 8.2 Formal N

Freeze：

```text
current materialized Formal N = 8
N > 8 = NOT_MATERIALIZABLE
```

如果 Calibration 要求 N>8：

```text
STOP_AND_RETURN_TO_M1
```

## 8.3 Right-censoring

增加明确字段：

```text
right_censoring_primary = VALID_OBSERVED_TURNS_ONLY
right_censoring_sensitivity = NOT_ESTIMABLE
reason = ONLY_2_NATURAL_TERMINAL_PROGRAMS
```

不要为了保留 sensitivity 而降低 Group 4-Program 要求。

## 8.4 Decision evidence contract

不新增“综合因果分数”。建议新增一个**证据连接报告**：

```text
decision_id
run_id
pressure_request_id
legal_candidate_count
fully_scored_candidate_count
selection_divergence
predicted_victim_sequence
matched_physical_victim_blocks
unmatched_physical_victim_blocks
downstream_reuse_observations
evidence_coverage
```

并把结论分级：

```text
M0 DECISION_SPACE
M1 SELECTION_DIVERGENCE
M2 PREDICTED_VICTIM_DIVERGENCE
M3 ACTUAL_PHYSICAL_DIVERGENCE
M4 DOWNSTREAM_RECOMPUTE_DIFFERENCE
M5 SYSTEM_EFFECT
```

每一级没有证据时，只能报告到上一级。

## 8.5 DVA-ER

- H=60 标记 `DESIGN_PRIOR_NOT_CALIBRATED`；
- 30/60/120 只做敏感性，不选 H；
- `CONTROLLER_ARMED_TIMER` 必须在线可证；
- chain identity 必须 Program/Session anchored；
- 先通过 DVA predictive-validity gate，再谈 Native effect；
- 报告 `NO_MULTI_CANDIDATE` 等分阶段 null，不用“无效”一概而论；
- 保留 CPU correctness ≠ decision distinguishability ≠ physical validity ≠ benefit 四层边界。

## 8.6 BFCL Derived

- 4 Calibration = descriptive only；
- 8 Evaluation = exploratory only；
- 不计算 formal N/power/multiplicity；
- 不合并 SWE；
- 报告 synthetic gap、source unknown、replay exhaustion 的限制；
- 报告 40 context/10 min-turn exclusions；
- 不将 `REPLAY_TRACE_EXHAUSTED` 映射为自然完成。

## 8.7 Metrics Contract

保留 `E−C` primary 和 Group 单位。建议补充：

- 明确 `N−C` 是实际 Prefill 成本，不作为 E−C 替代；
- `C/E`、`C/N` 只是 diagnostic，不是 hit rate；
- decision-level metrics 只做 descriptive/cluster，不做独立显著性；
- 所有 diagnostic 必须报告 denominator/evidence coverage；
- `physical_causal_attribution` 与 `downstream_recompute_attribution` 保持 `NOT_ESTABLISHED`，除非 M0–M4 证据完整。

## 8.8 Workload external validity

在 Phase 5 报告中增加：

- SWE Trace 的长度、Turn、Tool Gap、Prefix Reuse 分布；
- 与 PR #135 的 OpenHands 分布对比；
- 明确模型/agent/协议差异；
- 公开数据只作 motivation，不作 Native 结果；
- 不用公开 LCP 直接填充 E/C。

---

# 9. 结论

Phase 5 的系统级比较设计仍然成立，`E−C` 主指标和 Workload Group 独立单位应保留。

但当前证据体系需要三项实质补强：

1. **把 single-stratum 统计合同真正改过来**，而不是只改 run count；
2. **承认 SWE right-censoring sensitivity 在当前数据上 NOT_ESTIMABLE**；
3. **把 decision → physical → downstream → system 的证据链显式分级**，不能仅凭 E−C 或 diagnostic count 声称机制因果。

BFCL Derived 继续作为独立补充研究，不能混入 SWE formal 总体。

DVA-ER 仍应保持 provisional；CPU 正确性、决策可区分性、Native 预测有效性和系统收益必须分开报告。
