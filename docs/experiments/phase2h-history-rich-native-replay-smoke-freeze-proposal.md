# Phase 2H History-Rich Native Replay Smoke Freeze Proposal

**状态**：`PROPOSAL / GPU EXECUTION NOT AUTHORIZED`  
**研究输入**：PR #84，`docs/experiments/phase2h-a1-mechanism-recovery-design.md`  
**范围**：只冻结候选 workload、Native 执行几何、观测契约与 H/D 门禁；不修改 A1/A2，不启动 GPU Smoke。

## 1. 研究问题与结论边界

本 Smoke 只回答两个彼此独立的问题：

1. 连续真实 Agent 请求能否让冻结 TTL 路径使用可复算的经验历史，而不是一直停留在 `COLD_START`（Gate H）；
2. 同一时刻是否存在至少两个合法 Entry 候选、不同的边际释放结构以及可复现的 A1 评分（Gate D）。

Gate H 通过不代表 q 已获得预测能力；Gate D 通过也不代表 A1 有收益。PR #84 已证明，在 v10 决策上注入 443 条 W1-A 历史虽可进入 `GLOBAL`，但 q 最大变化约 0.003，排序没有改变。因此本 Smoke 不以 q 必须显著变化、A1 必须背离简单基线或 Token 结果必须改善为验收条件。

## 2. 冻结候选 workload

### 2.1 选择规则

只使用已验收的 W1-C S100 原始 sidecar，且必须同时满足：

- source-to-sidecar payload 可比；
- 至少 60 个连续成功 Model Calls；
- 前 60 个请求不含失败提交或上下文溢出；
- 保留原始 Explicit Token IDs、顺序、Prompt 增长和观测 gap；
- 任务选择在 Native 结果产生前冻结，不按 A1/A0 结果筛选。

每个场景包含 3 个独立 Session，每个 Session 重放成功调用 `1..60`。首次评估压力位于每个 Session 完成第 40 个请求之后；此时每 Session 已产生 39 条 server gap，全局历史为 `3 × 39 = 117`，严格超过冻结阈值 100。随后继续到第 50、55 个请求，并在相同边界重复压力；第 56–60 个请求作为第三次压力后的真实 Return 观察窗口。

### 2.2 HR01：balanced-gap

| Session | Repository / Task | Calls | Token range (first 60) | Median tokens | Gap count | Median observed gap |
|---|---|---:|---:|---:|---:|---:|
| A | `django__django-13023` | 60 | 1,326–8,197 | 4,797.5 | 59 | 0.282706 s |
| B | `sympy__sympy-15017` | 60 | 1,499–9,381 | 5,428.0 | 59 | 0.278263 s |
| C | `mwaskom__seaborn-3069` | 60 | 1,473–12,366 | 6,925.0 | 59 | 1.150413 s |

该场景共 177 条观测 gap，中位 0.286837 s，p90 1.161468 s，范围 0.003299–2.845740 s。它用于检查非退化但不过度放大的真实历史分布。

### 2.3 HR02：short-gap / long-context

| Session | Repository / Task | Calls | Token range (first 60) | Median tokens | Gap count | Median observed gap |
|---|---|---:|---:|---:|---:|---:|
| A | `pylint-dev__pylint-6386` | 60 | 1,449–13,839 | 7,644.0 | 59 | 0.007331 s |
| B | `pytest-dev__pytest-7982` | 60 | 1,348–11,205 | 6,299.5 | 59 | 0.006546 s |
| C | `pydata__xarray-3993` | 60 | 1,432–16,718 | 9,018.5 | 59 | 0.008617 s |

该场景共 177 条观测 gap，中位 0.007346 s，p90 0.011759 s，范围 0.002202–0.382832 s。它提供与 HR01 不同的真实历史分布和更高的上下文占用，但不人为加入十秒级排队延迟。

### 2.4 三 Session 时间线与调度选择

严格保留三个 Session 各自的原始 gap，通常无法同时保证每轮都按 A、B、C 的 wall-clock Round-Robin 顺序到达。本 Proposal 明确选择以下可复现规则，避免隐式扭曲：

1. 每个 Session 的第一个 submit 归一化到 `session_index × 0.25 s`；
2. 每个 Session 内使用原始 submit/completion offset，按 source logical time 合并；
3. 同一逻辑时间的事件按 Session A、B、C 稳定排序；该排序只是 tie-break，不声称原始生产环境采用 Round-Robin；
4. Pressure Barrier 位于三个 Session 对应轮次全部完成之后、任一 Session 下一轮到达之前；
5. 若下一轮原始 arrival 早于 Barrier，只增加显式 `CONTROLLED_PRESSURE_JOIN_DELAY`，不缩短原始 gap；新增 delay 按 Session 和边界记录；
6. A0/A1/A2 使用完全相同的物化时间线及 SHA-256。

因此，冻结语义是 **source-time merge with deterministic session tie-break and explicit pressure-join delay**，不是严格 Round-Robin wall-clock replay。

其他契约：

- 观测 gap 进入 Continuum 逻辑时间域；不做真实 wall-clock sleep，不缩放、不截断、不归零；Pressure Join 产生的额外 delay 单独记录。
- Native 提交、完成、物理淘汰和 APC 使用真实 monotonic clock；两种时钟不得直接相减或混排。
- 逻辑时间只在 Native inflight 为零的显式边界推进。
- 每个 Session 内的 60 个请求连续保留，不再像 v10 一样抽取 6 个稀疏 checkpoint。
- Run 结束保留右删失状态；尚未再次访问的被逐出内容不得记为“永久未复用”。

只读 Mock 检查由 `phase2h_history_rich_proposal.materialize_history_rich_mock_timeline` 固化：180 个请求形成 360 个 arrival/completion boundaries，加 3 个 Pressure Barriers，共 363 个边界；首次压力前全局 gap 数为 117。

## 3. Cache capacity 与重复压力

### 3.1 Capacity

冻结 `max_model_len = 32768`、`block_size = 16`、`num_gpu_blocks_override = 2048`。

2,048 blocks 是当前 32K 请求合法执行所需的最低已验证容量。进一步降低会使引擎无法服务 `max_model_len`，等价于改变长上下文执行条件，因此本 Smoke 不做更小容量 sweep。相较设备可分配的完整 KV Pool，2,048-block override 已构成受控缩容。

Preflight 必须重新证明：最长冻结请求可执行、三 Session 顺序可重放、跨臂 block capacity 完全一致。若实际引擎要求高于 2,048 blocks，Fail Closed，不通过截断或降低 `max_model_len` 绕过。

在每个边界用 16-token chain blocks 做静态 trie 口径估算（仅用于容量可行性，不冒充 Native residency）：

| Scenario / round | Session prefix blocks | Joint blocks before sharing | Shared-prefix saving | Unique chain blocks | 2048-capacity margin |
|---|---|---:|---:|---:|---:|
| HR01 / 40 | 368 / 418 / 542 | 1,328 | 14 | 1,314 | +734 |
| HR01 / 50 | 440 / 502 / 657 | 1,599 | 14 | 1,585 | +463 |
| HR01 / 55 | 476 / 544 / 713 | 1,733 | 14 | 1,719 | +329 |
| HR01 / 60 | 512 / 586 / 772 | 1,870 | 14 | 1,856 | +192 |
| HR02 / 40 | 602 / 491 / 718 | 1,811 | 14 | 1,797 | +251 |
| HR02 / 50 | 733 / 597 / 881 | 2,211 | 14 | 2,197 | −149 |
| HR02 / 55 | 799 / 647 / 963 | 2,409 | 14 | 2,395 | −347 |
| HR02 / 60 | 864 / 700 / 1,044 | 2,608 | 14 | 2,594 | −546 |

边界处没有 Native inflight 请求；表中的 active-request count 为 0。HR02 从 round 50 起不可能让三个完整当前前缀同时驻留于 2,048 blocks，这正是预期的自然容量竞争，不是配置错误。实际 residency、共享链和已淘汰内容必须从 Native Snapshot 读取；若单个请求本身超过容量才 Fail Closed。

### 3.2 Pressure boundaries

每个 Run 仅在以下冻结边界施加压力：

1. `after_round_40`：历史门槛跨越后的首次机制决策；
2. `after_round_50`：检查释放、物理淘汰、后续访问后的第二次竞争；
3. `after_round_55`：第三次竞争；round 56–60 提供每 Session 5 次下游 Return 机会。

### 3.3 策略无关的 Pressure 输入

Pressure 不再根据运行时 free blocks 动态生成 Token 请求。每个场景在所有臂和三个边界使用预先物化的、彼此内容不同但长度固定的 Explicit Token IDs：

| Scenario | First-boundary target shortage | Frozen pressure allocation | Frozen pressure tokens | Content seed |
|---|---:|---:|---:|---|
| HR01 | 32 blocks | 766 blocks | 12,256 | `phase2h:hr01:{boundary}:pressure-v1` |
| HR02 | 128 blocks | 379 blocks | 6,064 | `phase2h:hr02:{boundary}:pressure-v1` |

这些长度由 round-40 静态容量估算预先确定；每个 boundary 的 Token IDs 与 SHA-256 必须在 Final Freeze Record 中固化。三个策略臂接收逐位相同的 Pressure Token IDs、边界和请求数。

运行时分别记录但不混用：

- `target_shortage_blocks`：预注册设计目标；
- `actual_free_blocks_before_pressure` 与 `actual_shortage_blocks`：Native 实测；
- `native_allocation_blocks`：冻结 Pressure 请求实际申请量；
- `a1_scoring_need`：A1 决策直接使用的 need。

如果实际 shortage 未达到目标，保留为 `PRESSURE_TARGET_NOT_REACHED`；不得追加 Token、增加请求或按某个策略结果补偿。Pressure 内容本身不得跨边界命中 APC，因此三个边界使用不同 content seed。

`need` 必须由实际 A1 决策直接记录。Pressure generator 的 shortage、Native allocation request 和 A1 scoring `need` 分别保存，不能互相替代。

## 4. Native Smoke 数量与策略边界

冻结候选规模为：

```text
2 workload scenarios × 3 frozen arms (A0/A1/A2) × 1 repeat = 6 Native runs
```

单次 repeat 只支持机制可达性判断，不支持稳定收益或显著性结论。A0/A1/A2 的模型、Tokenizer、Token IDs、请求顺序、逻辑时间序列、容量和压力完全相同。A1/A2 数学目标、λ、τ、Native ownership 均不修改。

Sufficient-first、Earliest Deadline 和 Minimum Overshoot 只作为同一 A1 Decision Snapshot 上的离线对照，不增加 Native arm。若 M1 只授权原始 A1 机制恢复，可执行 A0/A1 两臂并把 A2 留作未授权；完整 proposal 的上限仍为 6 runs。

## 5. 必须补齐的观测契约

### 5.1 历史与 TTL

每个 TTL 决策事件必须直接记录：

- `global_server_gap_sample_count`；
- `tool_server_gap_sample_count`；
- history source、source artifact SHA-256、timestamp provenance；
- `TTLDecision.mode`、`reason`、`ttl_seconds`、`default_ttl_seconds`；
- `ttl_decision_logical_timestamp`、`deadline_logical_timestamp`；
- 实际送入 `_choose_empirical_ttl` 的冻结历史摘要与可定位的完整历史证据。

工具耗时不得进入 server-gap history。`GLOBAL` 与 `TOOL_SPECIFIC` 的样本必须分开计数。

### 5.2 Entry decision

每个 Forced Release 必须记录：

- 真实 `need`（直接记录，不事后反解）；
- 所有合法候选的稳定 `(program_id, prefix_id)`；
- `q_i`、`N_i`、λ、sufficient 状态、Score、Deadline、TTL；
- A1、A0、Sufficient-first、Earliest Deadline、Minimum Overshoot 的选择；
- 新增 Eligible Block IDs 与最终 Native Victim IDs，二者不得合并成同一概念；
- 候选被排除或 fallback 的具体理由。

只把带非空 `selection_trace` 且能与 `FORCED_RELEASE_DECISION` 通过 event order + stable identity 配对的事件计为 Entry 决策；ordinary allocation trace 不得混入。

### 5.3 物理淘汰与复用

本 Smoke 至少保存以下链路，即使暂不计算完整的 eviction→refetch rate：

```text
Entry release
  -> newly eligible content identities
  -> actual Native victim identities
  -> later request of the same stable content/prefix
  -> cached prefix tokens / prompt tokens
  -> FULL_HIT | PARTIAL_HIT | MISS
  -> request-level recomputed tokens
```

物理 slot/block ID 不能跨生命周期充当内容身份。Run 结束时“已逐出但尚未重取”的记录标为 `RIGHT_CENSORED`，不进入永久未复用分母。

未来若实现 per-entry eviction→refetch rate，还必须另行冻结观察窗口、身份、右删失、最小样本量、与 q 的语义关系及去偏规则；本 Proposal 不授权 `r_i`、`λ_i` 或 A1+。

## 6. 两个独立门禁

### Gate H：历史机制有效

Gate H PASS 必须同时满足：

1. 至少一个被评估决策的 `global_server_gap_sample_count > 100`；
2. 该决策的 `TTLDecision.mode != COLD_START`；
3. 使用归档的实际历史和冻结实现重算 TTL，与记录值一致（绝对误差 ≤ `1e-9`）；
4. `deadline = ttl_decision_logical_timestamp + ttl_seconds` 在同一逻辑时钟域成立；
5. 跨臂历史记录、逻辑边界序列及其 SHA-256 一致。

经验 TTL 与默认 TTL 数值相同只是诊断结果，不导致 Gate H 失败。q 排序是否变化也不是 Gate H 条件。

### Gate D：真实决策机会

Gate D PASS 必须同时满足：

1. 至少一个 Forced Release 决策有不少于 2 个合法候选；
2. 至少两个候选具有可复现的 `N_i`，且候选集合、`need`、λ 和 Score 可从归档独立重算；
3. selected release 属于合法候选，新增 eligible blocks 与实际 Native victims 分别可追踪；
4. 决策没有因身份未知、历史不可验证或无效 fallback 而失去比较资格。

Score 差距小于 2×、A1 与简单基线分歧、A1 与 A0 分歧均为诊断，不是硬门禁。即使 H/D 均通过且所有策略选择相同，Smoke 仍可有效；结论必须解释趋同原因，不能改参数追求分歧。

### 联合解释

| Gate H | Gate D | 可接受结论 |
|---|---|---|
| PASS | PASS | 历史机制和真实选择机会均成立；可分析 q/N/need/Score，但不自动证明收益 |
| PASS | FAIL | 历史恢复，但 workload 没有可判定选择机会 |
| FAIL | PASS | 只能解释 cold-start 下的决策，不能声称 history-rich A1 已被检验 |
| FAIL | FAIL | Smoke 无机制判别力，停止后续算法判断 |

## 7. Preflight、停止条件与缺失性

GPU 执行前必须通过离线/低成本 Preflight：source hashes、60-call 连续性、Token IDs、逻辑时间单调性、跨臂 timeline SHA、2,048-block 容量、三 Session source-time merge 和三次固定 pressure materialization。

以下任一情况立即停止，不继续增加 run：

- 任一冻结请求被截断、重新 Tokenize 或无法在 32K 条件下执行；
- 首次压力时 global history 未超过 100，或历史来源不可验证；
- `mode != COLD_START` 但 TTL 无法用归档历史复算；
- q、TTL、Deadline 或逻辑时间不自洽；
- 直接记录的 `need` 与评分输入不一致；
- 跨臂 Token IDs、顺序、容量、压力或逻辑时间 SHA 不一致；
- stable content identity 无法关联 eligible、eviction 和 later request；
- 三次压力均未形成 Forced Release，导致 Gate D 不可判定；未达到单次目标 shortage 本身只标记，不动态补偿；
- 单 run 超过 30 分钟、总 GPU wall time 超过 4 小时，或出现系统性运行故障。

未再次访问、未形成多候选、fallback、身份未知和运行末端右删失均保留在 Missingness Accounting，不静默删除。

## 8. 资源预算

目标环境沿用已验证的 RTX 4090D / CUDA / Qwen2.5-Coder-1.5B-Instruct Native 路径。按 v10 的 54 runs 约 39 分钟作为仅供预算的下界，本设计每 run 有 180 个真实长短不一请求和 3 次压力，预计：

| 项目 | 预计 wall time |
|---|---:|
| 静态 materialization、hash 与门禁 | < 15 分钟 CPU |
| 6 次 Engine 初始化 | 3–6 分钟 |
| 6 个 Native runs | 60–180 分钟 |
| 验证、归档与报告 | 15–30 分钟 CPU |
| GPU 预算上限 | 4 小时 |

这是资源上限，不是性能预测。实际 Engine、Native execution、pressure、evidence writing 和总墙钟时间必须分别记录。逻辑 gap 不产生真实 sleep。

## 9. 对后续 q 与 q/N 研究的判别力

本设计能够提供：

- 历史从 cold-start 进入经验模式的直接证据；
- 两种真实 gap 分布下 TTL、Deadline 与 q 的可复算变化；
- 多候选时真实 `need`、`N_i`、λ 与 Score；
- 多次 release 后 eligible、actual eviction、later request、APC 和 recomputation 的身份链；
- 判断 A1 趋同究竟来自 q 排序、全部候选 sufficient、N 分布窄，还是 Native/fallback 缺口。

它不能单独支持：总体性能显著性、A1+ 参数选择、`r_i` 的稳定估计或逐出后重取率的无偏结论。只有 H/D 同时通过且 eviction→later-request 证据非退化，才建议 M1 决定是否另行冻结 q 替代信号、逐候选 λ 或量纲正确的重算代价；否则不进入算法修改。

## 10. 请求 M1 冻结的项目

请求 M1 审核并明确冻结：

1. 两个三 Session workload 及每 Session 前 60 个连续 S100 请求；
2. 2,048-block 单容量、固定 Pressure Token 输入与 32/128-block 首边界目标 shortage；
3. round 40/50/55 三个 pressure 边界及 round 56–60 Return 窗口；
4. 最多 6 个 Native runs、1 repeat、4 GPU-hour stop limit；
5. 本文的历史/TTL、Entry decision、physical reuse 观测字段；
6. Gate H、Gate D 与联合解释规则。

在 M1 明确冻结之前，不实现 GPU Runner 扩展、不启动 Smoke、不修改 A1/A2。

### 10.1 Gate 报告粒度

Gate H 与 Gate D 必须对每个 `scenario × arm × repeat` Run 分别报告 `PASS / FAIL / NOT_OBSERVABLE` 和具体原因，再提供汇总矩阵。任何单个 Run 的通过都不得表述为全部六个 Run 通过；跨臂机制比较只使用对应 Run 均可观察的配对单元。

## Appendix A. Source artifact bindings

以下 SHA-256 绑定本 Proposal 实际审计的 W1-C S100 输入；最终 Freeze Record 必须逐项重验，任一不一致即停止：

| Task | Acquisition sidecar SHA-256 | Trajectory SHA-256 | Run manifest SHA-256 |
|---|---|---|---|
| `django__django-13023` | `5d39abd0974cac0921e1b47c4907d2cb0b4d0ca7bd8a881a427b20c8b68f8a31` | `ea003eced150c99c576507c0c6548b1ccf27f12c118d2f5950a818b48afe6ae3` | `935a75ddd975156f3582fa8894f0979ea8e70fa9f70c4c16088810091bcfc85e` |
| `sympy__sympy-15017` | `50ade68d15ae69dc68b716b4a664d44abf51b1483f788c001adf0b24c968c2cd` | `5db09e058e7a8fc6170c0ec1ff89276dc62884cc38c0d5f2ec130154237ce6e6` | `b15ec236ff837f8ca9464b5f119815598aae3a13af57f6bebd54bfaadd2be009` |
| `mwaskom__seaborn-3069` | `c7c9c421af578ee66f2c4a79f2e6df546dba4553880bea0fc1c402d7df0561ce` | `4f64f50e6e25949f3519eb726bfbcab528c1b6e1ed9b0423495d29181d9230b7` | `1920c879fd4bce1ac5f7adc9c80751412afd0c02f208c966b4c460407971fc73` |
| `pylint-dev__pylint-6386` | `9db69a2f8ecbeb61743718bed1ae54a46bd1c1edcc2316d321fd392632d1cc64` | `2f8951cbe86aa33cd6eecfa94548ed87739bd1005997925862db2296eb510e7c` | `aa094eafc021f23f869c7d1f1e421c1670d48bf098bd6bb7a26ddc9efab65015` |
| `pytest-dev__pytest-7982` | `ae8d96f5094c570ba16ab2c67b5080c46aceb883e798d928b55b3b0993db91ca` | `c744f93914b17a9fdd9c4ab989831eb260cb17a0066ebb7f3f625c1dc777a45c` | `3433e6fab29bffd3d67f7704ada74de4b1a0a8df88db7dde04c60290b867f8c8` |
| `pydata__xarray-3993` | `aa3e986a698cb1a13d21abfb53c1077910ccc8e78d69c2edcf81f18b118d3747` | `404809eee9be18795d5088dc2808f78a8dfde06fe54347c883f0cde98d78cfa9` | `ab8dfd48c90a2d09cacbc998f1748a576c92d177f6058089bcd1429d9ed9aa46` |
