# Phase 2G A1+ —— E1 / E6 离线可行性判断（改用 M6 真实轨迹）

**范围**：只回答 E1/E6 是否存在、能否在 Entry 释放决策之前拿到、是否携带独立于 deadline 的信息、是否泄漏。
未修改 A0/A1/A2，未新增 λ、未改 N 语义、未改 Block Selection 与 Native 路径，未启动 Campaign。

**数据源更正**：上一版用 H1 Level-A，那是自建压力实验而非真实 Agent 负载 ——
每 program 固定一份内容、`max_new_tokens = 1`、每 program 只有 2–3 轮、
首个请求按构造永不命中、前缀块数差恒为 0。用它回答"真实复用是否可预测"是选错了数据。
本轮改用 M6 的 W1-A / W1-C Agent 轨迹证据。

分析脚本：`scripts/probes/entry_costaware_audit/m6_signal_feasibility.py`（只读）。

---

## 1. M6 分支实际能提供什么

盘点结果（逐分支 `git ls-tree` 核对）：

| 资产 | 分支 | 是否入库 |
|---|---|---|
| W1-A 采集器 / 转换器 / 报告器 + 测试 | `origin/feature/continuum-w1a-trajectory-acquisition` | 是（代码） |
| W1-C 采样 / 运行器 / 报告器 + 冻结配置 | `origin/feature/continuum-w1c-expanded-workload-pilot` | 是（代码 + 配置） |
| W1-C 执行结果汇总 | 同上，`docs/continuum-w1c-feasibility-pilot.md` | 是（聚合表） |
| W1-A 443 条 gap 历史 | `origin/main`，`configs/phase2/continuum-w1a-server-gap-history-v1.json` | 是（仅 gap 数值） |
| **原始 sidecar（逐次调用的 token ID + 双时钟）** | — | **否**，只在 M6 机器上 |

关键：**逐次调用的 `submitted_token_ids` 与 `model_submit/completion_monotonic_seconds`
只存在于 sidecar**；W1-C 报告里的 LCP、复用率、上下文增长都是从它算出来的。
所以"逐调用覆盖率/分布"必须拿到 sidecar；"整体规模与退化程度"已由入库的聚合表给出。

---

## 2. E1（历史实际复用）在真实轨迹上的实测

W1-C pilot 聚合（40 runs / **2800 次成功模型调用** / 1407 次工具调用，均由脚本从 git 读出）：

| 条件 | 任务数 | 调用数 | 中位 prompt | 中位上下文增长 | 中位相邻精确 LCP | **中位相邻复用率** |
|---|---:|---:|---:|---:|---:|---:|
| S50 | 20 | 1000 | 5836 | 9131.5 | 5773 | **0.9709** |
| S100 | 20 | 1800 | 9245 | 17495.5 | 9209 | **0.9829** |

三点判断：

1. **作为比值，E1 接近饱和。** 0.9709 → 0.9829，跨条件差仅 **+0.0120**。
   若 E1 定义为"相邻复用率"，候选之间可用差异不到 3 个百分点，无法承担排序的主要权重。
2. **作为量级，E1 与 N 共线。** 中位相邻 LCP 是 5773 / 9209 tokens，而中位 prompt 是 5836 / 9245。
   也就是说 E1 的绝对量约等于整个前缀长度，与现有评分里已使用的 N 高度重合，
   加进模型等于给 N 再加一次权重。
3. 因此 E1 在真实轨迹上的主要问题是**信息重复**，不是数据缺失。

同时必须说清限制：W1-C 的 token 是**本地确定性分词**，不是 Native 运行时提交观测
（报告原文 `PINNED_LOCAL_TOKENIZATION_NOT_NATIVE_SUBMISSION`）。
所以上表是"复用潜力"，不是"实际命中"；真实命中仍只能由 Native 观测给出。

---

## 3. E6（Prefix 增长速率）在真实轨迹上的实测

| 条件 | 中位每任务增长 (tokens) | 每任务调用数 | 隐含每调用增长 |
|---|---:|---:|---:|
| S50 | 9131.5 | 50 | ≈ 183 |
| S100 | 17495.5 | 90 | ≈ 194 |

- 预算翻倍（50 → 100 步）使**总增长**接近翻倍（9131 → 17495，1.92×），
  但**每调用增长**几乎不变（183 → 194，1.06×）。
- 因此在均值层面 E6 近似常数（约 190 tokens/轮），不随预算变化；
  不能用"增长快/慢"解释 S50 与 S100 的差异。
- E6 是否可用，取决于**跨任务**的每调用增长率离散度。
  已提交的聚合表只有中位数，**回答不了**；必须逐任务重算。

这是唯一仍值得投入的检查项，而它需要 sidecar。

---

## 4. 与 Entry 决策的映射（W1-C 自己列的边界）

W1-C 文档把下列量标为 `NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY`：

```
decision-time candidate count
marginal newly_eligible_blocks
pressure requirement (need)
candidate q values / their span
A1 divergence from Earliest Deadline / Minimum Overshoot
Native APC eligibility, residency, eviction, recomputation
```

含义很直接：**即使拿到全部 sidecar，也只能把 E1/E6 算到"轨迹层"，
不能直接算成"Entry 决策时刻的特征"。** 从轨迹层到决策层还需要一次 Native replay，
因为候选集、`need`、q 的跨度都只在引擎内部产生。

所以本阶段可行性判断只能分两层给出：

| 层 | 能否离线判定 | 结论 |
|---|---|---|
| 轨迹层：E1/E6 是否有变异 | 能（聚合已有；逐调用需 sidecar） | E1 饱和且共线；E6 均值近常数 |
| 决策层：能否改变 Entry 排序 | **不能**（缺候选集与 `need`） | 待授权后的 Native replay |

---

## 5. 泄漏规则

| # | 泄漏 | 规避 |
|---|---|---|
| 1 | 用整段轨迹而非 `t` 之前的调用算 E1 | 只用 submit 时间早于决策时刻的调用 |
| 2 | 用当前调用自身的 token 结果算它自己的特征 | 当前调用的特征只由前序调用构成 |
| 3 | 用 SWE-bench 的 `is_terminal` / 真实结束轮判断"会不会继续" | 不得读数据集侧的完成标签 |
| 4 | 跨 run 池化（同一批任务多次执行） | 不跨 run；S50/S100 是两次独立执行 |
| 5 | 只给一个 arm 加特征 | 三臂（含 A0）必须同构 |
| 6 | 把本地分词当运行时提交 | 必须标注 `PINNED_LOCAL_TOKENIZATION_NOT_NATIVE_SUBMISSION` |

---

## 6. 覆盖率：正确问法与所需数据

上一版用 H1 报的"覆盖 8.3%"反映的是 H1 的构造缺陷，不应作为 E1/E6 的结论。
在 M6 数据上应这样问：

| 问题 | 现状 |
|---|---|
| 有多少次调用之前已有 ≥1 个相邻对（E1 可算） | 需 sidecar |
| 有多少次调用之前已有 ≥2 个相邻对（可算速率） | 需 sidecar |
| 同一时刻多个候选 program 的 E1/E6 是否不同 | 需 sidecar + 候选集（后者仍需 Native） |
| 跨任务的每调用增长离散度 | **需 sidecar（最有价值的一项）** |

脚本已按 W1-C 的目录约定写好：`<runs-root>/<run>/<instance>/acquisition-sidecar.json`。
拿到路径后直接运行，无需改代码：

```bash
python scripts/probes/entry_costaware_audit/m6_signal_feasibility.py --runs-root <dir>
# 或 export W1_RUNS_ROOT=<dir>
```

---

## 7. 最小实现方案（仅当 §6 的检查通过）

只改 q 的构造，λ / N 语义 / Block Selection / Native 路径一律不动。

1. 运行时按链维护（纯新增字段，不改变现有语义）：
   `observed_requests`、`reuse_pairs`、`mean_adjacent_reuse`、`mean_growth_tokens`。
   更新点与现有 `reuse_state` 相同（每次请求完成），只写当前值与计数。
2. `q' = (1-β)·q + β·f(E)`，β 冻结 0.5，不提供调参入口。
3. **硬护栏**：`observed_requests < 3`（不足两个相邻对）时 `q' = q`，
   与 A1 逐位相同，使任何差异只能来自信号本身。
4. 决策时记录 `e1_n / e1_value / e6_n / e6_value / q_base / q_used`，
   下一轮覆盖率审计不需要新的 Campaign。

---

## 8. 结论

1. **E1**：真实轨迹里确实存在强前缀复用，但
   - 作为比值已接近饱和（0.97 / 0.98，跨条件差 0.012）；
   - 作为量级与 N 共线（相邻 LCP ≈ 整个前序 prompt）。
   因此它提供的**新**信息很少，不建议作为主信号。
2. **E6**：均值层面近似常数（≈190 tokens/轮，跨预算 1.06×）。
   是否可用取决于**跨任务离散度**，而聚合表不含该信息。
3. **两者都无法只靠轨迹判定能否改变 Entry 排序**：候选集、`need`、q 跨度
   被 W1-C 明确列为 `NOT_OBSERVABLE_FROM_TRAJECTORY_ONLY`。
4. **建议先做一件低成本的事**：让 M6 提供 W1-C 的 runs root（sidecar 目录），
   用现成脚本跑出跨任务 E6 离散度与 E1 的真实分布。
   若离散度显著大于轮内噪声，再谈机制实现；
   若不足，则如实报告"两个候选信号均未提供足够的独立信息"，不为凑算法而拼特征。
5. 本轮不给研究方向裁定，不申请 Campaign。

---

## 复现

```bash
# 聚合模式：从 git 读 W1-C 已提交结果，不需要任何本地数据
python scripts/probes/entry_costaware_audit/m6_signal_feasibility.py

# 逐调用模式：需要 M6 的 sidecar 目录
python scripts/probes/entry_costaware_audit/m6_signal_feasibility.py --runs-root <dir>
```

脚本只读，不写文件；聚合数字由解析 `docs/continuum-w1c-feasibility-pilot.md` 的表格得到，
不手工转录，避免抄写误差。
