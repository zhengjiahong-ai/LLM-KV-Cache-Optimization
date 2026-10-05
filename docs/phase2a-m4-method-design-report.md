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
| 单元测试（含多释放、回退、复杂度 51 项） | `tests/test_costaware_rules.py`、`tests/test_costaware_offline_eval.py` | 已提交 |
| 本地实验运行器 | `local/cost_aware_local_experiment.py` | **不入库**（`.gitignore` 已忽略 `local/`） |
| 本地探针（4 个） | `local/probe_*.py` | **不入库** |
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
non-tied decisions  : 3
```

### 5.0 指标定义（与 M6 对齐）

- `non_tied_decisions`：**决策内候选损失不完全相同**，即选择会影响结果的决策数。
  它刻画「该决策有无 headroom」，与「本规则是否抓住」无关。
- `strictly_worse_decisions`：本规则的选择未落在 canonical 最优集合内的决策数。
- `misselection_rate` = `strictly_worse / non_tied`，即 M6 的 non-tied misselection rate。
- `tie_rate`：全部候选损失相同的决策占比。

ⓘ 这两个概念在实现初期被混淆过（把 `non_tied` 当作「本规则失手」），
会**隐藏「有 headroom 但规则未取」的决策**。已修正，并由
`test_multi_release_holds_count_and_picks_the_cheapest_pair` 等测试锁定。

### 5.1 汇总表

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

### 5.2 警告：该样本被刻意偏差化，数字不得引用为效应量

这 3 个 exemplar 是 M6 **特意挑选的高 regret 样例**（见 `docs/phase2a-m6-formal/README.md`：`exemplars/` 为 "three representative high-regret runs"）。

后果：

- 基线 regret 在此样本上**按构造就很大**，因此任何改善幅度都被系统性放大；
- 3 个决策无法支撑任何统计结论；
- 上述数字只能作为**仪器可用性证据**（instrument check），不能作为方法效果证据。

**结论：本报告不宣称任何效应量。** 有效评估必须在完整 canonical bundle 上运行（见 §11）。

### 5.3 族留出（leave-one-family-out）

评估器已实现族级留出（handoff §9）。在这个 3 决策样本上，每个族只含 1 个 run，
因此留出某族后的 `mean_normalized_regret` 如下（来自本地运行的
`leave_one_family_out`）：

| 规则 | 留出 F1 | 留出 F4 | 留出 F6 |
| --- | ---: | ---: | ---: |
| `M0_p1b_executed_ordering` | 0.820361 | 0.867842 | 0.688203 |
| `M1_prefill_reload_ascending` | 0.820361 | 0.867842 | 0.688203 |
| `M1_block_count_ascending` | 0.820361 | 0.867842 | 0.688203 |
| `M1_marginal_cost_per_reclaimable` | 0.719629 | 0.719629 | 0.439259 |
| `M2_non_code_first` | 0.820361 | 0.750000 | 0.570361 |
| `M3_non_code_then_size_score` | 0.820361 | 0.750000 | 0.570361 |

两点谨慎解读：

1. 所有规则在**每一个**留出配置下都保持正归一化 regret，即**没有规则能消除 headroom**。
2. 规则间的相对次序在三个留出配置下一致（边际分母规则最低，size 簇与基线并列最高）。
   但这是 3 个决策、每族 1 个 run 的结果，**不构成稳定性证据**。真正的族留出检验
   需要完整 campaign 的 18 个场景 / 6 个族（见 §11）。

## 6. 退化审计（handoff §10）

Handoff §10 要求重新检验请求级退化，而非假设其不存在。结果如下。

### 6.1 观察：size/recompute 簇与基线排序同构

```text
M0_p1b_executed_ordering == M1_prefill_reload_ascending   over 3 decisions
M0_p1b_executed_ordering == M1_block_count_ascending      over 3 decisions
M0_p1b_executed_ordering == M1_reclaimable_ascending      over 3 decisions
M0_p1b_executed_ordering == M3_size_score_only            over 3 decisions
M1_prefill_reload_ascending == M1_block_count_ascending   over 3 decisions
M1_prefill_reload_ascending == M1_reclaimable_ascending   over 3 decisions
M1_block_count_ascending == M3_size_score_only            over 3 decisions
```

**整个 size/recompute 簇（PrefillReload、block_count、reclaimable）与已执行的 P1B 排序在全部 3 个决策上完全同构，配对比较为 0 更好 / 0 更差 / 3 平。**

也就是说：**handoff §2 表中四个 `PROXY_SUPPORTED` 特征里的三个（size 簇）在本样本上没有产生任何与基线不同的选择。** 只有 `next_tool_type` 打破了同构。

M6 的 ρ≈0.205 是**秩关联**证据，而秩关联可以完全落在基线排序的方向上而不产生分歧。**关联显著 ≠ 决策可分歧。**

### 6.2 修正：6.1 的成因**不是**线性成本退化

本节记录一次被自己证伪的解释，因为它是本报告最重要的方法学修正。

**曾提出的解释（已证伪）**：spike 的线性成本论证认为 `C_recompute / Blocks` 近似常数，因此 deadline 排序与尺寸排序一致。本文档初版沿用了这一解释。

**证伪**：对 3 个决策逐候选比较「PrefillReload 序」与「retention deadline 序」：

```text
decisions where cost-order == deadline-order : 1/3
Pearson(deadline, PrefillReload) over 11 candidates : 0.4517
```

只有 **1/3** 的决策同序，相关系数仅 **0.45**。线性成本退化论证在本样本上**不成立**。

### 6.3 已验证的真实机理：损失由返回窗口主导，成本规则对此全盲

canonical 代理损失**不是纯成本**：

$$
\text{loss} = \begin{cases} \text{PrefillReload} & \text{若规划在 horizon 内返回} \\ 0 & \text{否则} \end{cases}
$$

对三个决策逐候选展开（本地诊断输出）：

| 决策 | 候选数 | 基线释放数 | 最优集中零损失候选数 | **最高成本候选的损失为 0** |
| --- | ---: | ---: | ---: | :---: |
| `f1-five-contention-deep-seed-101` event 64 | 5 | 3 | 2 / 3 | **是** |
| `f4-deep-multi-release-seed-101` event 40 | 3 | 2 | 1 / 2 | **是** |
| `f6-shared-ownership-audit-seed-101` event 40 | 3 | 1 | 1 / 1 | **是** |

**三个决策中，损失为 0（即规划不返回）的候选恰好都是 PrefillReload 最高的那个。**

于是：

- P1B（最早 deadline 优先）挑走了「会返回」的候选 → 有 regret；
- M1（成本升序优先）也挑走最便宜的 = 同样「会返回」的 → **同一个错误**；
- 两者因此同构，原因是**它们读同一类信号**，不是因为成本曲线退化。

`f6` 最能说明问题：三个候选的 `PrefillReload` 全等于 `0.171057`、`block_count` 全等于 `32` —— **成本特征在结构上无法区分任何东西**，唯一差别是 deadline 与是否返回。

**机理陈述**：在 canonical 代理下，判别维度是**复用/返回窗口**，不是成本。任何纯成本规则都无法改善，与成本曲线形状无关。

这一结论之所以重要，是因为它**否证了「只要测到非线性 $C(r)$ 就能让成本规则生效」这一路径**：即便 `C(r)` 非线性，只要损失由返回窗口主导，成本规则依然无效。

### 6.4 该机理与既有证据的关系

- 与 spike 的 F.2（「TTL 层本身就是 cost-aware 过滤器」）方向一致，但**机制不同**：F.2 说的是保护池被同质化，这里说的是**损失函数本身由返回窗口主导**。
- 与 M6 的信号门禁一致：`next_tool_type=code` 是唯一从**不同语义维度**通过的特征，也是本样本上唯一能打破同构的。
- ⚠️ **仍不得作为结论引用**：3 个 exemplar 是 M6 按构造挑选的高 regret 样例，任何在其中发现的规律都被系统性筛选过。Handoff §13 明确禁止仅凭样本内代理 regret 改善来论证实现。该机理需在完整 54-run / 60 决策上验证（§11 Q1/Q5）。

### 6.5 边际分母规则（handoff §10 明令）

`M1_marginal_cost_per_reclaimable` 是本样本上唯一大幅改善的规则（2/3 更好）。但：

- 它在 2026-09-24 的 spike 中已被**分析否决**（拒绝释放共保护条目、规划开销退化）；
- handoff §10 明确要求：「Do not resurrect the previously rejected marginal-block denominator without new evidence」；
- 它在 3 个高 regret 样例上改善，**可能只是打破了 6.1 的同构**，而非抓住了真实损失结构。

因此：**该规则不作为候选方法提出。** 它留在规则集中仅作为退化审计项，其异常表现登记为需在完整 canonical 数据上复核的未决问题（§11 Q2）。

### 6.6 §10 子问题 c：分母是否抵消了成本信号（已测）

§10 明确列出四个必须审计的子问题，其中第三个此前未答：

> does dividing by reclaimable blocks cancel the useful cost signal?

现在已测。`denominator_diagnostic()` 逐决策比较「成本序」与「成本 / 可回收块数序」：

| 决策 | 候选数 | 分母恒定 | Spearman(成本, 分母) | 秩反转 / 可比较对数 |
| --- | ---: | :---: | ---: | ---: |
| `f1-five-contention-deep-seed-101` ev64 | 5 | 否 | **1.000** | **8 / 10** |
| `f4-deep-multi-release-seed-101` ev40 | 3 | 否 | **1.000** | **3 / 3** |
| `f6-shared-ownership-audit-seed-101` ev40 | 3 | **是** | n/a | 0 / 3 |

汇总：

```text
decisions with a CONSTANT denominator : 1/3
cost-vs-ratio rank inversions          : 11/16 comparable pairs (69%)
```

**答案：是，分母确实破坏了成本序。** 注意 Spearman = 1.000 表示分母与成本**单调同向**，但并非**成比例**——于是相除后序被反转。11/16 的可比较对发生秩反转。

这为 §6.5 的异常表现提供了确定解释：

> `M1_marginal_cost_per_reclaimable` 的改善**不是**因为更好地度量了成本。
> 它是因为**放弃了成本序**，去探索一个不同的候选。
> 因此它不能被描述为成本感知方法的候选，其收益也不能被归因于成本信号。

**结论：§10 子问题 c 已回答，且答案支持排除该规则。** 这与 §10 的禁令一致（「Do not resurrect the previously rejected marginal-block denominator without new evidence」）——现在有了新证据，而证据指出应排除。

## 7. §9 要求的行为分解与消融

§9 列出 9 项必须报告的内容。本节补齐此前缺失的 5 项（其余 4 项见 §5.1）。

### 7.1 特征消融表

`ablation_table()` 由既有规则对构建，避免新增规则造成的比较污染。

| 消融变体 | 选择同一率 | 变体平均归一化 regret | 基准 |
| --- | ---: | ---: | ---: |
| size 簇：成本 alone vs 占用 alone | **1.000** | 0.792135 | 0.792135 |
| size 簇：成本 alone vs 可回收 alone | **1.000** | 0.792135 | 0.792135 |
| size 簇：成本 alone vs 三者平均 | **1.000** | 0.792135 | 0.792135 |
| tool 指示：关闭 vs 开启（成本为主） | 0.667 | 0.713574 | 0.792135 |
| tool 指示：关闭 vs 开启（分数为主） | 0.667 | 0.713574 | 0.792135 |
| 分母：成本 alone vs 成本/可回收 | **0.333** | 0.626172 | 0.792135 |

两点：

1. **size 簇的三个特征完全互换**（同一率 1.000，regret 差为 0）。这不是「冗余」的统计陈述，而是**在任何测试决策上不产生任何不同选择**。切换其中任何一个都不会有任何效果。
2. **只有 tool 指示（0.667）与分母（0.333）真正改变了选择。** 分母改变得最多，而 §6.6 已证明它改变的方式是**放弃成本序**。

这同时回答了 §10 子问题 d：**表观收益并非只来自 tool 指示变量**，但也不是来自 size 簇，而是来自分母对成本序的破坏。

### 7.2 按场景族的行为

| 规则 | F1 | F4 | F6 |
| --- | ---: | ---: | ---: |
| `M0_p1b_executed_ordering`（基线） | 0.735684 | 0.640721 | **1.000000** |
| `M1_block_count_ascending` | 0.735684 | 0.640721 | 1.000000 |
| `M1_marginal_cost_per_reclaimable` | 0.439259 | 0.439259 | **1.000000** |

F6 是 `M1_marginal_cost_per_reclaimable` 唯一**没有**改善的族（1.000000 = 完全错）。F6 正是三个候选成本特征**全等**的那个决策 —— 在那里任何成本类排序都无法分辨，而分母规则也不例外。

### 7.3 按候选集规模与释放数的行为

| 规则 | n=3 | n=5 | releases=1 | releases=2 | releases=3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `M0_p1b_executed_ordering` | 0.820361 | 0.735684 | 1.000000 | 0.640721 | 0.735684 |
| `M1_marginal_cost_per_reclaimable` | 0.719629 | 0.439259 | 1.000000 | 0.439259 | — |

三点：

1. **多释放行为已分离报告**（`releases=1/2/3`），不再合并。
2. 所有非平局决策的误选率均为 **1.000** —— 在这个样本上**没有任何一条被评估的规则达到 hindsight 最优**。改善是 regret 的**减少**，不是消除。
3. `releases=1` 的 regret 为 1.000000 且误选率 1.000 —— 单释放决策上全员全错，与上表 F6 是同一个决策。

### 7.4 跨 seed 的排序稳定性：**不可评估**

§9 要求报告 ranking stability across seeds。**在本仓库内无法完成**，原因已核实：

```text
curated-evidence/exemplars/ 仅含 seed-101
  f1-five-contention-deep-seed-101
  f4-deep-multi-release-seed-101
  f6-shared-ownership-audit-seed-101
```

正式 campaign 的另两个 seed（**211、307**）不在仓库中。因此跨 seed 稳定性**必须等外部证据包**（§13）。

依 §3，特征只有经过**独立正式 campaign**复核方向、效应量阈值、族一致性与 seed 一致性之后，才可称为 `RUNTIME_STABLE`。这不在当前授权范围内。

### 7.5 结论冻结声明

§9 要求：

> Any score/threshold acceptance rule must be frozen before using the final holdout result.

**本报告未冻结任何验收规则**，因为**没有任何候选规则被提出**（见 §12 第一条）。这使 §7 的消融与分解仅具诊断地位，不构成方法选择。

## 8. 复杂度与开销（handoff §13 第 8 项）

### 8.1 排序复杂度为 O(n log n)

每条规则的排序复杂度为 **O(n log n)**，其中 n 为单次决策的候选数，另加 O(n) 预处理（仅归一化分数规则需要）。

实现中曾有**两处静默的 O(n²)**，均已修正并被测试锁定：

| 缺陷 | 位置 | 修正 |
| --- | --- | --- |
| 归一化在排序键内计算 → 每次比较都重扫全部候选 | `M3_size_score_only`、`M3_non_code_then_size_score` | 引入 `prepare` 钩子，每决策预计算一次 |
| 预计算内**逐候选**重算每个特征的 min/max → 仍是 O(n²) | 同上 | 改为每特征单次求界 |

### 8.2 实测（本地纯 Python 离线分析）

`local/probe_rule_complexity.py` 的输出，单位微秒/决策：

| 规则 | n=4 | n=16 | n=64 | n=256 | 增长（4→256） |
| --- | ---: | ---: | ---: | ---: | ---: |
| `M0_p1b_executed_ordering` | 1.60 | 4.00 | 20.60 | 53.10 | 33.2x |
| `M1_prefill_reload_ascending` | 2.00 | 3.10 | 10.50 | 39.80 | 19.9x |
| `M1_marginal_cost_per_reclaimable` | 1.70 | 4.70 | 16.40 | 63.70 | 37.5x |
| `M2_non_code_first` | 1.50 | 4.30 | 17.30 | 71.80 | 47.9x |
| `M3_size_score_only` | 5.00 | 15.30 | 55.50 | 227.10 | **45.4x** |
| `M3_non_code_then_size_score` | 5.40 | 16.90 | 65.80 | 272.80 | **50.5x** |

参考值：候选数增长 **64x**；O(n²) 参考增长 **4096x**；O(n log n) 预期远低于 4096x。

修正前，size 分数规则在 n=256 时为 **12192.50 µs**（增长 **1385.5x**，介于线性与二次之间）。修正后为 **227.10 µs**，即 **54 倍提速**，增长 45.4x，与 O(n log n) 一致。

### 8.3 重要限定

- 上述是**纯 Python 离线分析**开销，**不是运行时策略开销**，不得作为运行时数字引用。
- 真实 campaign 的候选集仅 **2–5**（M4 handoff §1），该区间内单次排序成本为**微秒量级**。
- 运行时复杂度/开销的正式界定属于 §13 第 8 项，需在 M1 评审的接口设计阶段完成，本报告只界定规则层的排序复杂度。

## 9. 回退排序（handoff §13 第 7 项）

当规则无法区分两个候选时，解析遵循固定的、已文档化的阶梯：

```text
第 1 级  规则主键（该规则声明使用的决策时特征）
第 2 级  稳定逻辑身份 (program_id, prefix_id)
         —— 恒定可用、确定性，保证全序
第 3 级  仅冻结 P1B 规则：未知的 decision_native_lru_position (None) 排最后
         —— 保守解读：位置未知视为「最近使用」，即最贵，故推迟而非猜测
```

`fallback_key()` 公开了第 2 级，便于调用方复现评估器的确切回退，而非自行推导。

**阶梯明确不做的事**：

1. **不为非 P1B 规则回退到 LRU 新近度。** 否则每条成本规则会被静默变成它正在被比较的基线，令比较失去意义；
2. **不回退到任何未来衍生标签**；
3. **不回退到输入顺序**。否则结果将取决于 artifact 的枚举次序，破坏可复现性。

由测试锁定：`test_ordering_is_total_when_every_feature_is_identical`（第 2 级能被触发）、
`test_ordering_does_not_depend_on_input_order`（第 3 条禁令）、
`test_p1b_rule_sorts_unknown_lru_position_last`（第 3 级）、
`test_non_p1b_rules_ignore_the_lru_position_capability`。

**一个有意义的副产品**：entry-level 规则（M1/M2/M3）**完全不读取** `decision_native_lru_position`，因此不受该能力在 M6 信号分析中未通过的影响。这也是它们比 P1B 基线更少依赖脆弱观测的原因。

## 10. 最小运行时接口需求（handoff §14 要求）

这是本节的核心结论，也是与之前 block-level 草案不同的地方。

### 10.1 胜出家族只需要**零新增观测**

M1/M2/M3 家族用到的全部字段（`prefill_reload_seconds`、`block_count`、`initially_reclaimable_block_count`、`next_tool_type`）**已经存在于 `FORCED_RELEASE_DECISION` 载荷中**，即已在正式 campaign 中被采集。

因此不需要新的运行时观测缝。这与 handoff §9「M1 may decide whether an additional safe decision-time observation is justified」是相容的：**对 entry-level 家族而言，答案是不需要。**

### 10.2 但需要一次接口扩展才能到达策略边界

运行时策略边界 `EvictionPolicyAdapter.select_victims(candidates, context)` 目前只拿到：

```text
EvictionCandidate: block_id, ref_cnt, has_block_hash, lru_rank
EvictionContext:   required_blocks, free_blocks, total_blocks, timestamp
```

决策时字段（PrefillReload、block_count、next_tool_type 等）**从适配器不可达**。所以最小接口需求是一条**搬运**，而不是一条**新观测**：

> 把已在 `FORCED_RELEASE_DECISION` 中采集的逐候选决策时字段，以只读方式暴露给 `EvictionPolicyAdapter`。

这比 block-level 草案 §6 的请求窄得多：它不需要前缀内位置索引，也不需要 block → owner 映射。

### 10.3 尚未请求

Block-level / partial-prefix（草案 B1）**未被本报告请求**，因为 handoff §7 明确它未被批准，且 §11 的四个前置问题（真实 `C(r)` 曲线、部分 APC 语义、接口可用性、超越 entry-level 的离线收益）尚未解决。

## 11. 未决问题

| 编号 | 问题 | 状态与解决方式 |
| --- | --- | --- |
| Q1 | size 簇与基线排序的同构在完整 54-run 数据上是否成立？ | 未决 —— 在 canonical bundle 上运行本评估器 |
| Q2 | `M1_marginal_cost_per_reclaimable` 的改善是真实结构还是打破同构的副作用？ | **本仓库内已答（§6.6）：是后者。** 分母与成本单调同向但非成比例，相除后 11/16 可比较对发生秩反转，即该规则放弃了成本序。剩余问题：这个「放弃成本序」的收益是否在 60 个决策上可复现，还是高 regret 样例的偶合 |
| Q3 | `next_tool_type=code` 的收益在 family-held-out 下是否稳定？ | 未决 —— 同上；本仓库已实现 leave-one-family-out |
| Q4 | 是否存在能超越 entry-level 的 block-level 收益？ | 未决 —— handoff §11 的四个前置问题 |
| Q5 | §6.3 的「返回窗口主导」机理在 60 个决策上是否成立？ | 未决 —— 同上；并检查不同族是否给出不同机理 |
| Q6 | §7.1 的 size 簇完全互换（同一率 1.000）在 60 个决策上是否成立？ | 未决 —— 若成立，则三个 `PROXY_SUPPORTED` 尺寸特征应被视为**一个**特征，而非三个独立信号 |

前六项**都不需要新观测**，只需要把外部证据包传进来。

## 12. 局限

- **没有提出候选方法。** Handoff §13 第 1 项要求“提出的规则”，而 §14 要求的是能胜出的设计。本报告交付的是评估器、规则集与诊断，**尚未收敛到一条可提交评审的规则**。这是最主要的遗留缺口，且可能受 §6.3 机理制约（见 Q5）。
- **原始样本量极小（3 个决策）。** §6 的全部观察都建立在这 3 个决策上。
- **证据为代理级别。** canonical 损失视角 `planned_return_weighted_prefill_proxy` 是 trace 派生的规划代理，不是实测重计算、TTL 或 serving 影响。依 handoff §3，除 `PROXY_SUPPORTED` 外不得作更强声明。
- **已运行样本为 3 个刻意偏差的高 regret exemplar**，不能支撑效应量，见 §5.2。
- **无运行时验证。** 无 vLLM 进程、无 GPU、无延迟数据。运行时可复制性（runtime replication）按 canonical 记录仍为 `false`。
- **未拟合任何模型。** 依 handoff §8，未对 60 个受控决策拟合高容量模型。
- **未做新颖性核查**（§13 第 11 项），需 M2 的相关工作输入。
- **仓库既有测试失败。** 全量套件在干净 `origin/main` 上即有 12 项失败（`test_continuum_logging`、`test_continuum_vllm_observation_runner`、`test_phase2a_m6_*`），已核实与本次改动无关；属 M1/M6 范围。

## 13. 复现

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

## 14. 可追溯性

| 章节 | 来源 |
| --- | --- |
| §1, §13 | `src/kvopt/costaware/`、`local/cost_aware_local_experiment.py`、`.gitignore` |
| §2, §3 | `src/kvopt/costaware/offline_eval.py`、`rules.py`；`docs/phase2a-m4-method-design-input.md` §8/§9/§10 |
| §4, §5 | 本地运行输出（`local/output/local_report.json`）；自检 3/3 |
| §5.0 | `src/kvopt/costaware/offline_eval.py` 的 `candidate_loss_tied` 与 `_aggregate` |
| §5.2 | `docs/experiments/phase2a-m6-formal/README.md`（exemplars 为高 regret 样例） |
| §5.3 | 本地运行的 `leave_one_family_out` 输出 |
| §6.1 | 本地运行的退化审计段 |
| §6.2 | 本地 `local/probe_deadline_vs_cost.py` 输出（1/3、r=0.4517） |
| §6.3 | 本地 `local/probe_loss_mechanism.py` 与 `cost_aware_local_experiment.py` 的 LOSS MECHANISM 段 |
| §6.4 | 2026-09-24 spike（`origin/feature/cost-aware-forced-unpin-spike`）；`docs/phase2a-m6-formal-results.md` |
| §6.5 | `docs/phase2a-m4-method-design-input.md` §10 |
| §6.6 | `offline_eval.denominator_diagnostic()`；本地运行的 DENOMINATOR DIAGNOSTIC 段 |
| §7.1 | `offline_eval.ablation_table()` 与 `ABLATION_PAIRS` |
| §7.2–7.3 | `offline_eval.behaviour_breakdown()`；本地运行的 BEHAVIOUR BREAKDOWN 段 |
| §7.4 | `docs/experiments/phase2a-m6-formal/README.md`（exemplars 仅含 seed-101） |
| §8 | `local/probe_rule_complexity.py` 输出；`tests/test_costaware_rules.py::test_size_score_prepare_does_not_rescan_per_candidate` |
| §9 | `src/kvopt/costaware/rules.py` 模块 docstring 与 `fallback_key()`；四个回退测试 |
| §10 | `docs/policy-adapter-design.md`；`src/kvopt/runtime/vllm/types.py`；`docs/phase2a-m4-method-design-input.md` §5/§11 |
| §11, §12 | `docs/phase2a-m4-method-design-input.md` §3/§7/§9/§11/§13 |

相关：`docs/phase2a-m4-block-level-design-draft.md`（block-level 预设计，未被本报告请求）、
`docs/phase2a-m4-gate-contract-gap-audit.md`（门禁—契约差距审计）。

本地探针脚本（均不入库，`.gitignore` 已忽略 `local/`）：

```text
local/cost_aware_local_experiment.py    主实验运行器
local/probe_multi_release_and_scale.py  多释放正确性与规模
local/probe_deadline_vs_cost.py         §6.2 的证伪测量
local/probe_loss_mechanism.py           §6.3 的逐候选机理诊断
local/probe_rule_complexity.py          §8 的分规则复杂度
```
