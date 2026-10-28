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

每个场景包含 3 个独立 Session，每个 Session 重放成功调用 `1..60`。首次评估压力位于每个 Session 完成第 40 个请求之后；此时每 Session 已产生 39 条 server gap，全局历史为 `3 × 39 = 117`，严格超过冻结阈值 100。随后继续到第 50、60 个请求，并在相同边界重复压力。

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

### 2.4 连续 Replay 契约

- 三个 Session 使用冻结的 round-robin 提交顺序：每轮依次 A、B、C；跨臂顺序完全一致。
- 观测 gap 进入 Continuum 逻辑时间域；不做真实 wall-clock sleep，不缩放、不截断、不归零。
- Native 提交、完成、物理淘汰和 APC 使用真实 monotonic clock；两种时钟不得直接相减或混排。
- 逻辑时间只在 Native inflight 为零的显式边界推进。
- 每个 Session 内的 60 个请求连续保留，不再像 v10 一样抽取 6 个稀疏 checkpoint。
- Run 结束保留右删失状态；尚未再次访问的被逐出内容不得记为“永久未复用”。

## 3. Cache capacity 与重复压力

### 3.1 Capacity

冻结 `max_model_len = 32768`、`block_size = 16`、`num_gpu_blocks_override = 2048`。

2,048 blocks 是当前 32K 请求合法执行所需的最低已验证容量。进一步降低会使引擎无法服务 `max_model_len`，等价于改变长上下文执行条件，因此本 Smoke 不做更小容量 sweep。相较设备可分配的完整 KV Pool，2,048-block override 已构成受控缩容。

Preflight 必须重新证明：最长冻结请求可执行、三 Session 顺序可重放、跨臂 block capacity 完全一致。若实际引擎要求高于 2,048 blocks，Fail Closed，不通过截断或降低 `max_model_len` 绕过。

### 3.2 Pressure boundaries

每个 Run 仅在以下冻结边界施加压力：

1. `after_round_40`：历史门槛跨越后的首次机制决策；
2. `after_round_50`：检查释放、物理淘汰、后续访问后的第二次竞争；
3. `after_round_60`：检查重复竞争和观察窗口末端右删失。

HR01 使用目标 shortage 32 blocks；HR02 使用目标 shortage 128 blocks。压力生成器必须基于边界时实际 free blocks 计算所需输入，并逐请求检查 Native eviction；一旦达到目标 shortage/forced release 即停止，保留 64-request fail-closed ceiling。不得按策略臂修改压力强度，也不得根据首次结果调高压力以制造分歧。

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

GPU 执行前必须通过离线/低成本 Preflight：source hashes、60-call 连续性、Token IDs、逻辑时间单调性、跨臂 timeline SHA、2,048-block 容量、三 Session 顺序和三次 pressure materialization。

以下任一情况立即停止，不继续增加 run：

- 任一冻结请求被截断、重新 Tokenize 或无法在 32K 条件下执行；
- 首次压力时 global history 未超过 100，或历史来源不可验证；
- `mode != COLD_START` 但 TTL 无法用归档历史复算；
- q、TTL、Deadline 或逻辑时间不自洽；
- 直接记录的 `need` 与评分输入不一致；
- 跨臂 Token IDs、顺序、容量、压力或逻辑时间 SHA 不一致；
- stable content identity 无法关联 eligible、eviction 和 later request；
- 三次压力均未形成 Forced Release，导致 Gate D 不可判定；
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
2. 2,048-block 单容量与 32/128-block 两个场景级 shortage；
3. round 40/50/60 三个 pressure 边界；
4. 最多 6 个 Native runs、1 repeat、4 GPU-hour stop limit；
5. 本文的历史/TTL、Entry decision、physical reuse 观测字段；
6. Gate H、Gate D 与联合解释规则。

在 M1 明确冻结之前，不实现 GPU Runner 扩展、不启动 Smoke、不修改 A1/A2。

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
