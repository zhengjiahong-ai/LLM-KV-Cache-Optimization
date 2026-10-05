# Phase 2A M4 — 方法设计与离线评估报告 v1

状态：**方法设计（非运行时实现）** — 依 `docs/phase2a-m4-method-design-input.md` §14

授权依据与边界：

```text
M1 授权：M4 方法设计与离线评估。
M1 未授权：冻结或合并最终运行时 Cost-Aware 实现。
```

本文档因此**不提出、也不包含**任何运行时策略。它比较若干证据支撑的简单规则，并给出获胜设计所需的最小运行时接口。

## 1. 交付内容

| 项目 | 位置 | 性质 |
| --- | --- | --- |
| 决策时规则集（M0–M3） | `src/kvopt/costaware/rules.py` | 离线分析，纯决策时特征 |
| 离线评估器 | `src/kvopt/costaware/offline_eval.py` | 离线分析，复用 canonical regret |
| 单元测试（37 项） | `tests/test_costaware_rules.py`、`tests/test_costaware_offline_eval.py` | 已提交 |
| 本地实验运行器 | `local/cost_aware_local_experiment.py` | **不入库**（`.gitignore` 已忽略 `local/`） |
| `.gitignore` | 新增 `local/` 条目 | 声明本地工作区不入评审 |

本地运行器**不需要 vLLM、GPU 或模型下载**。它只重放已持久化的决策 artifact，因此可在任意机器上给出快速反馈回路。

## 2. 评估器设计

### 2.1 复用 canonical regret，而不是重写

评估器不重新实现 regret。对每条规则，它重建该规则的释放集合、把对应候选标记为 `selected`，然后送入 `kvopt.profiling.analysis.build_decision_regret_table` —— 即产出 canonical M6 `decision_regret` 表的**同一个集合感知实现**。

因此：

> 规则 regret 与 canonical 的已执行 P1B regret **直接可比**，而不是两套算法之间的比较。

### 2.2 固定释放数量

每个决策中被释放的候选数量固定等于**已执行基线的数量**。这样比较隔离的是「释放哪些」而不是「释放几个」，正是研究问题本身（RQ1）。

### 2.3 不静默近似缺失

只有当一个决策**全部候选**在该损失视角下都有证据时，它才参与评估。任何部分可用的决策被计为 `skipped` 并如实报告，绝不按子集评估。

理由：按子集评估会静默低估 hindsight 最优，从而夸大规则的收益。该约束在实现阶段被发现并修正（见 §5 的测试 `test_partially_available_decision_is_skipped_not_approximated`）。

### 2.4 在线信息边界被强制执行

`CandidateRule.__post_init__` 在构造期即拒绝：

- 读取任何 `FORBIDDEN_FEATURES`（未来衍生标签）；
- 读取任何未在 `DECISION_TIME_FEATURES` 中声明的字段。

因此「不小心把未来标签写进规则」在**构造期**就失败，而不是靠事后审查。

## 3. 规则集（依 handoff §8 的 M0–M3 家族）

| 规则 | 家族 | 特征 | 说明 |
| --- | --- | --- | --- |
| `M0_p1b_executed_ordering` | M0 | deadline, native LRU 位置 | 冻结 P1B 排序的重新推导，用于自检 |
| `M1_prefill_reload_ascending` | M1 | PrefillReload | 先释放最便宜者 |
| `M1_block_count_ascending` | M1 | block_count | 先释放最小占用者 |
| `M1_reclaimable_ascending` | M1 | reclaimable | 先释放腾出最少块者 |
| `M1_marginal_cost_per_reclaimable` | M1 | PrefillReload / reclaimable | **退化审计项**，非候选方法 |
| `M2_non_code_first` | M2 | next_tool_type | 只用受支持的语义指示 |
| `M3_non_code_then_small_prefill` | M3 | tool, PrefillReload | 字典序组合 |
| `M3_size_score_only` | M3 | PrefillReload, blocks, reclaimable | 归一化加性分数，**排除** tool 项 |
| `M3_non_code_then_size_score` | M3 | tool + 上述簇 | 字典序：tool 优先，再分数 |

`M3_size_score_only` 与 `M3_non_code_then_size_score` 是刻意设计的一对，用于回答 handoff §10 的「表面收益是否只来自 tool-type 指示变量」。

## 4. 自检：评估器是否可信

在仓库内已有的 3 个真实 M6 exemplar 上：

```text
decisions compared        : 3
exact match               : 3
match rate                : 1.0000
decisions missing LRU pos : 0
```

即 `M0_p1b_executed_ordering` **100% 复现了已执行的 P1B 释放集合**。

这是对评估器本身的验证，不是研究结果。它证明：规则 API、集合选择、标记与 canonical regret 链路三者一致。

## 5. 已验证运行的结果（附重要偏差警告）

在 3 个已提交 exemplar 上运行全部 9 条规则：

```text
evaluated decisions : 3
skipped decisions   : 0
candidates scored   : 11
```

| 规则 | 平均归一化 regret | 平均绝对 regret | 对比基线：更好/更差/平 |
| --- | ---: | ---: | --- |
| `M1_marginal_cost_per_reclaimable` | 0.626172 | 0.083003 | 2 / 0 / 1 |
| `M2_non_code_first` | 0.713574 | 0.103181 | 1 / 0 / 2 |
| `M3_non_code_then_small_prefill` | 0.713574 | 0.103181 | 1 / 0 / 2 |
| `M3_non_code_then_size_score` | 0.713574 | 0.103181 | 1 / 0 / 2 |
| `M0_p1b_executed_ordering` | 0.792135 | 0.132757 | 基线 |
| `M1_prefill_reload_ascending` | 0.792135 | 0.132757 | 0 / 0 / 3 |
| `M1_block_count_ascending` | 0.792135 | 0.132757 | 0 / 0 / 3 |
| `M1_reclaimable_ascending` | 0.792135 | 0.132757 | 0 / 0 / 3 |
| `M3_size_score_only` | 0.792135 | 0.132757 | 0 / 0 / 3 |

### 5.1 警告：该样本被刻意偏差化，数字不得引用为效应量

这 3 个 exemplar 是 M6 **特意挑选的高 regret 样例**（见 `docs/phase2a-m6-formal/README.md`：`exemplars/` 为 "three representative high-regret runs"）。

后果：

- 基线 regret 在此样本上**按构造就很大**，因此任何改善幅度都被系统性放大；
- 3 个决策无法支撑任何统计结论；
- 上述数字只能作为**仪器可用性证据**（instrument check），不能作为方法效果证据。

**结论：本报告不宣称任何效应量。** 有效评估必须在完整 canonical bundle 上运行（见 §8）。

## 6. 退化审计（本次最强的观察）

Handoff §10 要求重新检验请求级退化，而非假设其不存在。结果如下。

### 6.1 size/recompute 簇与基线排序同构

```text
M0_p1b_executed_ordering == M1_prefill_reload_ascending   over 3 decisions
M0_p1b_executed_ordering == M1_block_count_ascending      over 3 decisions
M0_p1b_executed_ordering == M3_size_score_only            over 3 decisions
M1_prefill_reload_ascending == M1_block_count_ascending   over 3 decisions
M1_prefill_reload_ascending == M1_reclaimable_ascending   over 3 decisions
M1_block_count_ascending == M3_size_score_only            over 3 decisions
```

**整个 size/recompute 簇（PrefillReload、block_count、reclaimable）与已执行的 P1B 排序在全部 3 个决策上完全同构，配对比较为 0 更好 / 0 更差 / 3 平。**

这与历史 spike 的线性成本退化论证一致：在这些决策上，`C_recompute / Blocks` 近似常数，deadline 排序与尺寸排序给出同一顺序。

也就是说：**handoff §2 表中四个 PROXY_SUPPORTED 特征里的三个（size 簇）在本样本上没有产生任何与基线不同的选择。** 只有 `next_tool_type` 打破了同构。

这一点的意义：M6 的 rho≈0.205 是**秩关联**证据，而秩关联可以与基线排序同向而不产生分歧。关联显著 ≠ 决策可分歧。

### 6.2 边际分母规则的异常表现必须在完整数据上复核

`M1_marginal_cost_per_reclaimable` 是本样本上唯一大幅改善的规则（2/3 更好）。但：

- 它在 2026-09-24 的 spike 中已被**分析否决**（拒绝释放共保护条目、规划开销退化）；
- handoff §10 明确要求：「Do not resurrect the previously rejected marginal-block denominator without new evidence」；
- 它在 3 个高 regret 样例上改善，**可能只是打破了 6.1 的同构**，而非抓住了真实损失结构。

因此：**该规则不作为候选方法提出。** 它留在规则集中仅作为退化审计项，其异常表现登记为需在完整 canonical 数据上复核的未决问题（§8 Q2）。

## 7. 最小运行时接口需求（handoff §14 要求）

这是本节的核心结论，也是与之前 block-level 草案不同的地方。

### 7.1 胜出家族只需要**零新增观测**

M1/M2/M3 家族用到的全部字段（`prefill_reload_seconds`、`block_count`、`initially_reclaimable_block_count`、`next_tool_type`）**已经存在于 `FORCED_RELEASE_DECISION` 载荷中**，即已在正式 campaign 中被采集。

因此不需要新的运行时观测缝。这与 handoff §9「M1 may decide whether an additional safe decision-time observation is justified」是相容的：**对 entry-level 家族而言，答案是不需要。**

### 7.2 但需要一次接口扩展才能到达策略边界

运行时策略边界 `EvictionPolicyAdapter.select_victims(candidates, context)` 目前只拿到：

```text
EvictionCandidate: block_id, ref_cnt, has_block_hash, lru_rank
EvictionContext:   required_blocks, free_blocks, total_blocks, timestamp
```

决策时字段（PrefillReload、block_count、next_tool_type 等）**从适配器不可达**。所以最小接口需求是一条**搬运**，而不是一条**新观测**：

> 把已在 `FORCED_RELEASE_DECISION` 中采集的逐候选决策时字段，以只读方式暴露给 `EvictionPolicyAdapter`。

这比 block-level 草案 §6 的请求窄得多：它不需要前缀内位置索引，也不需要 block → owner 映射。

### 7.3 尚未请求

Block-level / partial-prefix（草案 B1）**未被本报告请求**，因为 handoff §7 明确它未被批准，且 §11 的四个前置问题（真实 `C(r)` 曲线、部分 APC 语义、接口可用性、超越 entry-level 的离线收益）尚未解决。

## 8. 未决问题

| 编号 | 问题 | 解决方式 |
| --- | --- | --- |
| Q1 | size 簇与基线排序的同构在完整 54-run 数据上是否成立？ | 在 canonical bundle 上运行本评估器 |
| Q2 | `M1_marginal_cost_per_reclaimable` 的改善是真实结构还是打破同构的副作用？ | 同上，并按族分层报告 |
| Q3 | `next_tool_type=code` 的收益在 family-held-out 下是否稳定？ | 同上；本仓库已实现 leave-one-family-out |
| Q4 | 是否存在能超越 entry-level 的 block-level 收益？ | handoff §11 的四个前置问题 |

三项均**不需要新观测**，只需要把外部证据包传进来。

## 9. 局限

- **证据为代理级别。** canonical 损失视角 `planned_return_weighted_prefill_proxy` 是 trace 派生的规划代理，不是实测重计算、TTL 或 serving 影响。依 handoff §3，除 `PROXY_SUPPORTED` 外不得作更强声明。
- **已运行样本为 3 个刻意偏差的高 regret exemplar**，不能支撑效应量。
- **无运行时验证。** 无 vLLM 进程、无 GPU、无延迟数据。运行时可复制性（runtime replication）按 canonical 记录仍为 `false`。
- **未拟合任何模型。** 依 handoff §8，未对 60 个受控决策拟合高容量模型。
- **退化审计的样本量极小**（3 决策），6.1 的结论需要在完整数据上确认。
- **仓库既有测试失败。** 全量套件在干净 `origin/main` 上即有 12 项失败（`test_continuum_logging`、`test_continuum_vllm_observation_runner`、`test_phase2a_m6_*`），已核实与本次改动无关；属 M1/M6 范围。

## 10. 复现

在已有原始 run 的任意机器上（无需 vLLM）：

```bash
python local/cost_aware_local_experiment.py
```

在完整 canonical 数据上（需先按 `docs/experiments/phase2a-m6-formal-v5/README.md` 取得外部证据包）：

```bash
python local/cost_aware_local_experiment.py \
  --artifact-root <extracted>/phase2a-formal-v5-final \
  --formal
```

限定规则或视角：

```bash
python local/cost_aware_local_experiment.py --rules M2_non_code_first
python local/cost_aware_local_experiment.py --loss-view observed_recomputed_tokens
```

输出：控制台报告 + `local/output/local_report.json`。

## 11. 可追溯性

| 章节 | 来源 |
| --- | --- |
| §1, §10 | `src/kvopt/costaware/`、`local/cost_aware_local_experiment.py`、`.gitignore` |
| §2, §3 | `src/kvopt/costaware/offline_eval.py`、`rules.py`；`docs/phase2a-m4-method-design-input.md` §8/§9/§10 |
| §4, §5 | 本地运行输出（`local/output/local_report.json`） |
| §5.1 | `docs/experiments/phase2a-m6-formal/README.md`（exemplars 为高 regret 样例） |
| §6.1 | 本地运行的退化审计段 |
| §6.2 | `docs/phase2a-m4-method-design-input.md` §10；2026-09-24 spike（`origin/feature/cost-aware-forced-unpin-spike`） |
| §7 | `docs/policy-adapter-design.md`；`src/kvopt/runtime/vllm/types.py`；`docs/phase2a-m4-method-design-input.md` §5/§11 |
| §8, §9 | `docs/phase2a-m4-method-design-input.md` §3/§7/§11/§13 |

相关：`docs/phase2a-m4-block-level-design-draft.md`（block-level 预设计，未被本报告请求）、
`docs/phase2a-m4-gate-contract-gap-audit.md`（门禁—契约差距审计）。
