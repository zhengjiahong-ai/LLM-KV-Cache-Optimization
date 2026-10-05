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
| **压力循环 replay 引擎** | `src/kvopt/costaware/replay.py` | 离线分析，忠实重放冻结的释放循环 |
| **feasibility-aware oracle** | `src/kvopt/costaware/feasible_oracle.py` | 离线分析，精确枚举可行释放集合 |
| 离线评估器 | `src/kvopt/costaware/offline_eval.py` | 离线分析，两套 comparator 分离输出 |
| **入库可复现入口** | `src/kvopt/costaware/report.py` + `cli.py` | 已入库；见 §13 的运行方式 |
| 单元测试（111 项） | `tests/test_costaware_{rules,replay,feasible_oracle,offline_eval,report}.py` | 已提交 |
| 本地探针 | `local/probe_*.py`、`local/cost_aware_local_experiment.py` | **不入库**（`.gitignore` 已忽略 `local/`） |
| `.gitignore` | 新增 `local/` 条目 | 声明本地工作区不入评审 |

入库入口**不需要 vLLM、GPU 或模型下载**：它只重放已持久化的决策 artifact。`local/` 只是同一代码路径的薄封装，不再是唯一可复现的运行方式。

## 2. 评估器设计

### 2.1 复用 canonical regret，而不是重写

评估器不重新实现 regret。对每条规则，它重建该规则的释放集合、把对应候选标记为 `selected`，然后送入 `kvopt.profiling.analysis.build_decision_regret_table` —— 即产出 canonical M6 `decision_regret` 表的**同一个集合感知实现**。

因此：

> 规则 regret 与 canonical 的已执行 P1B regret **直接可比**，而不是两套算法之间的比较。

⚠️ **一个必须声明的限定**：`build_decision_regret_table` 的 hindsight 是**同数量**的（以损失最小的一组同规模候选为最优），**不检查该集合是否真能解开压力**。在释放数量会变化的 replay 语义下，这意味着 regret 是「给定释放了同样多个」的诊断，而不是可执行的 oracle。因此跨规则比较应主要看**总代理损失**（越低越好，因为所有规则满足同一个 target），regret 只作次要诊断。

### 2.2 释放数量是**结果**，不是输入（前版错误已修正）

⚠️ **本节描述前版评估器的错误做法，保留作为记录。**

前版把「基线释放了 N 个条目」当作约束，让替代规则也释放恰好 N 个。**这不是运行时面对的约束。** 冻结的 Phase 1B 循环是：

```text
while eligible_blocks < required_blocks:
    对仍然受保护的条目重新排序
    释放排序最低的那一个
    重算这次释放使多少块变为可用
```

因此：

1. 不同条目解开的块数不同，所以满足**同一个 target** 可能需要**不同数量的释放**；
2. **共享所有权**下，边际可用集合会随前面释放过谁而变化 —— 所以 `initially_reclaimable_block_count` **不可独立相加**（见 §2.5）。

由 replay 得到的正确语义是：**给定同一个 `required_blocks`，按规则排序逐个重放释放，动态重算可用块数，直到满足同一个 target。** 释放数量随后是**结果**。

### 2.3 不静默近似缺失

只有当一个决策**全部候选**在该损失视角下都有证据时，它才参与评估。任何部分可用的决策被计为 `skipped` 并如实报告，绝不按子集评估。

理由：按子集评估会静默低估 hindsight 最优，从而夸大规则的收益。该约束在实现阶段被发现并修正（见 §5 的测试 `test_partially_available_decision_is_skipped_not_approximated`）。

### 2.4 在线信息边界被强制执行

`CandidateRule.__post_init__` 在构造期即拒绝：

- 读取任何 `FORBIDDEN_FEATURES`（未来衍生标签）；
- 读取任何未在 `DECISION_TIME_FEATURES` 中声明的字段。

因此「不小心把未来标签写进规则」在**构造期**就失败，而不是靠事后审查。

### 2.5 压力循环 replay（本轮修正的核心）

`src/kvopt/costaware/replay.py` 从原始 `FORCED_RELEASE_DECISION` 载荷重建每个决策，并重放真实约束。

### 2.5.1 块可用性语义（逐字照搬冻结实现）

```text
未哈希的空闲块                -> 始终可用
已哈希的空闲块                -> 仅当「不存在仍受保护的所有者」时可用
```

一个所有者在其条目被释放后不再受保护。本决策之前已失去保护的条目（观察到的 `ordinary_expired_entries`）从一开始就不进入所有者集合，对应冻结循环里 `released_keys` 被预置为这些条目的做法。

### 2.5.2 为什么不能简单累加

共享所有权下，同一个条目解开的块数**取决于它之前释放了谁**：

```text
条目 a 拥有块 {1,2}，条目 b 拥有块 {2,3}
单独释放 b      -> 只能解开 {3}
先释放 a 再释放 b -> 解开 {2,3}
```

因此 `initially_reclaimable_block_ids`（冻结实现计算的初始边际）**不能**用于推断多次释放后的累计效果。replay 每次都从所有权重新计算。

### 2.5.3 保真度是验证出来的，不是假定的

`validate_replay_fidelity()` 对照原始 artifact 检查三件事：

| 检查项 | 在仓库内 3 个 M6 exemplar 上的结果 |
| --- | --- |
| 释放集合 | **3/3 = 1.0** |
| 释放**顺序** | **3/3 = 1.0** |
| 每个条目的 `initially_reclaimable_block_ids` | **11/11 = 1.0** |

第三项独立于任何策略，单独验证了所有权与可用性模型。入库入口把这三个比率放在报告最前面，**保真度不为 1.0 时任何 regret 数字都不可信**。

### 2.5.4 该修正的影响

修正前后结论发生**实质变化**。例：被否决的边际分母规则在固定数量语义下误选率为 1.000，在 replay 语义下为 0.333，且它平均只需 **1.00** 次释放，而观测基线需要 **2.00** 次（3 个决策中 2 个更省）。

⇒ 它的表面优势是**释放数量效应**，而固定数量比较在结构上无法表示这一点。这一发现直接改变了 §6.5 对它的处理。

### 2.6 feasibility-aware hindsight oracle（M1 裁定的 Q8）

#### 2.6.1 为什么必须新增第二个 comparator

`build_decision_regret_table`（canonical M6）选的是**损失最小的同规模集合**，**不检查该集合能否解开压力**。在释放数量固定时这是合理的比较对象；但释放数量现在是结果，所以它不再适合作为方法选择的主指标。

M1 裁定：**在 evaluator 层新增 feasibility-aware oracle；不修改 canonical M6 代码。** 已按此实现于 `src/kvopt/costaware/feasible_oracle.py`，两套指标**分离报告，绝不合并成同一字段**。

#### 2.6.2 定义

对每个决策与损失视角，在**所有能满足同一个 `required_blocks` target 的释放集合**中：

```text
primary    最小化总 canonical 代理损失
secondary  最小化释放条目数          （仅在损失平局时）
tertiary   稳定逻辑身份序            （确定性）
```

搜索是**精确枚举**（穷举子集）。正式 campaign 每决策仅 2–5 个候选，因此无需近似；超过 `MAX_EXACT_CANDIDATES = 16` 时**显式报错而非静默近似**，因为一个悄悄改变的 comparator 会污染全部下游比较。

#### 2.6.3 为什么子集枚举等价于循环结果

冻结循环在释放序列的**首个**满足 target 的前缀处停止，所以其释放集合总是可行的。反过来，对任何可行集合 $S$，$S$ 的某个排列会让循环停在某个前缀 $P \subseteq S$，且因为代理损失非负，有 $\text{loss}(P) \le \text{loss}(S)$ 与 $|P| \le |S|$。

⇒ 可行集合上的字典序最优必然由一个循环**实际能产生**的集合取得，所以枚举可行子集与枚举释放序列得到同一最优，而代价低得多。

#### 2.6.4 在仓库内 exemplar 上的结果

| 决策 | 目标 | 候选数 | 可行集合数 | oracle 损失 | 最差可行损失 | 选择影响结果 |
| --- | ---: | ---: | ---: | ---: | ---: | :---: |
| f1 ev64 | 32 | 5 | 27 | **0.000000** | 0.188239 | 是 |
| f4 ev40 | 32 | 3 | 5 | **0.000000** | 0.138485 | 是 |
| f6 ev40 | 16 | 3 | 7 | **0.000000** | 0.342114 | 是 |

**三个决策的 oracle 损失全为 0，且 oracle 都只需释放 1 个条目。**

含义：每个决策都存在**单个零损失条目**即可满足压力 —— 即释放一个不返回（因此代理损失为 0）的候选就够了。

两个 comparator 的对比因此变得很锐利：

| 规则 | canonical M6 平均归一化 regret | **feasible oracle 平均归一化 regret** | feasible 条目数差 |
| --- | ---: | ---: | ---: |
| `M0_p1b_executed_ordering`（基线） | 0.792135 | **1.000000** | **+1.00** |
| `M1_prefill_reload_ascending` | 0.792135 | 1.000000 | +1.00 |
| `M1_marginal_cost_per_reclaimable` | 0.333333 | **0.333333** | **0.00** |

**feasible comparator 严格得多**：基线在它下面的归一化 regret 是 **1.000**（因为 oracle 损失为 0，归一化后即为 1），而 canonical 只给出 0.792。

⚠️ **同样受 §6 的样本级限定约束**：3 个决策 / 11 个候选 / 仅 seed-101，且为 M6 按构造挑选的高 regret 样例。这些数字是**诊断假设**，不是结果。它们之所以重要，是因为它们给出了明确的、可在完整数据上检验的预测：**若「存在单个零损失可行释放」在 60 个决策上普遍成立，那么基线的可行 regret 会显著高于 canonical 所暗示的水平。**

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

## 4. 自检：replay 是否忠实

自检现在由 **replay 保真度**承担（旧的固定数量自检函数已删除，因为它假定了一个错误约束）。在仓库内已有的 3 个真实 M6 exemplar 上：

```text
decisions compared        : 3
release SET match rate    : 1.0000
release ORDER match rate  : 1.0000
marginal blocks match rate: 1.0000  (11 fields)
```

即冻结的 P1B 排序在 replay 下**精确复现了观察到的决策**：集合、顺序、以及每个条目的 `initially_reclaimable_block_ids` 全部一致。

这是对判定器本身的验证，不是研究结果。它证明：所有权模型、可用性语义、重排循环与 canonical regret 链路四者一致。第三项独立于任何策略，因此它单独验证了块可用性模型。

## 5. 已验证运行的结果（附重要偏差警告）

在 3 个已提交 exemplar 上运行全部 9 条规则（**replay 语义**）：

```text
evaluated decisions : 3
skipped decisions   : 0
unsatisfied         : 0
candidates scored   : 11
```

### 5.0 指标定义（与 M6 对齐）

- `non_tied_decisions`：**决策内候选损失不完全相同**，即选择会影响结果的决策数。
  它刻画「该决策有无 headroom」，与「本规则是否抓住」无关。
- `strictly_worse_decisions`：本规则的选择未落在 canonical 最优集合内的决策数。
- `misselection_rate` = `strictly_worse / non_tied`，即 M6 的 non-tied misselection rate。
- `tie_rate`：全部候选损失相同的决策占比。

ⓘ 这两个概念在实现初期被混淆过（把 `non_tied` 当作「本规则失手」），
会**隐藏「有 headroom 但规则未取」的决策**。已修正，并由
`tests/test_costaware_offline_eval.py` 的多释放用例锁定。

### 5.1 汇总表

| 规则 | 平均归一化 regret | 平均绝对 regret | 误选率 | 平均释放数 | 对比基线：更好/更差/平 |
| --- | ---: | ---: | ---: | ---: | --- |
| `M1_marginal_cost_per_reclaimable` | **0.333333** | 0.057019 | **0.333** | **1.00** | 2 / 0 / 1 |
| `M2_non_code_first` | 0.713574 | 0.103181 | 1.000 | 2.00 | 1 / 0 / 2 |
| `M3_non_code_then_small_prefill` | 0.713574 | 0.103181 | 1.000 | 2.00 | 1 / 0 / 2 |
| `M3_non_code_then_size_score` | 0.713574 | 0.103181 | 1.000 | 2.00 | 1 / 0 / 2 |
| `M0_p1b_executed_ordering` | 0.792135 | 0.132757 | 1.000 | 2.00 | 基线 |
| `M1_prefill_reload_ascending` | 0.792135 | 0.132757 | 1.000 | 2.00 | 0 / 0 / 3 |
| `M1_block_count_ascending` | 0.792135 | 0.132757 | 1.000 | 2.00 | 0 / 0 / 3 |
| `M1_reclaimable_ascending` | 0.792135 | 0.132757 | 1.000 | 2.00 | 0 / 0 / 3 |
| `M3_size_score_only` | 0.792135 | 0.132757 | 1.000 | 2.00 | 0 / 0 / 3 |

ⓘ **与修正前对比**：在固定数量语义下边际分母规则的误选率是 1.000、平均归一化 regret 是 0.626172；在 replay 语义下误选率降为 0.333、平均归一化 regret 降为 0.333333，且平均只需 **1.00** 次释放（基线 2.00）。

⇒ 这正是 §2.2 所述语义错误的影响：它在结构上看不到「用更少释放满足同一 target」这一维度，因而**低估**了该规则。

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

## 6. 退化审计（handoff §10）—— **样本级证据**

Handoff §10 要求重新检验请求级退化，而非假设其不存在。结果如下。

> ⚠️ **证据级别声明（必读）**：本节全部观察建立在本仓库内可得的 **3 个决策 / 11 个候选**上，且这 3 个 exemplar 是 M6 **按构造挑选的高 regret 代表性样例**，**仅含 seed-101**。
>
> 因此以下内容应读作 **exemplar-level evidence suggests …**（样本级证据提示），**而不是**已验证机制或最终结论。它们是有价值的诊断假设，需在完整 canonical bundle（54 runs / 60 decisions / 174 candidates / 6 families / 3 seeds）上重新验证后，才能升格为机制陈述。
>
> 本节此前曾使用「已验证机制」「否证 block-level 路径」等表述，**已降级**。

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

### 6.2 修正：6.1 的成因**不是**线性成本退化（样本内测量）

本节记录一次被自己证伪的解释，因为它是本报告最重要的方法学修正。

**曾提出的解释（已证伪）**：spike 的线性成本论证认为 `C_recompute / Blocks` 近似常数，因此 deadline 排序与尺寸排序一致。本文档初版沿用了这一解释。

**证伪**：对 3 个决策逐候选比较「PrefillReload 序」与「retention deadline 序」：

```text
decisions where cost-order == deadline-order : 1/3
Pearson(deadline, PrefillReload) over 11 candidates : 0.4517
```

只有 **1/3** 的决策同序，相关系数仅 **0.45**。线性成本退化论证在本样本上**不成立**。

### 6.3 样本级证据提示的机理：损失可能由返回窗口主导，成本规则对此全盲

> 措辞已降级：本节是 **exemplar-level evidence suggests**，不是已验证机制。

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

**样本级机理假设**：在本样本的 canonical 代理下，判别维度可能是**复用/返回窗口**，而不是成本。假如这成立，任何纯成本规则都无法改善，**与成本曲线形状无关**。

假如该假设在完整数据上成立，它的意义是：它**削弱**了「只要测到非线性 $C(r)$ 就能让成本规则生效」这一路径。注意这里用「削弱」而非「否证」：3 个高 regret exemplar 不足以否证一条路径。

### 6.4 该机理与既有证据的关系

- 与 spike 的 F.2（「TTL 层本身就是 cost-aware 过滤器」）方向一致，但**机制不同**：F.2 说的是保护池被同质化，这里说的是**损失函数本身由返回窗口主导**。
- 与 M6 的信号门禁一致：`next_tool_type=code` 是唯一从**不同语义维度**通过的特征，也是本样本上唯一能打破同构的。
- ⚠️ **仍不得作为结论引用**：3 个 exemplar 是 M6 按构造挑选的高 regret 样例，任何在其中发现的规律都被系统性筛选过。Handoff §13 明确禁止仅凭样本内代理 regret 改善来论证实现。该机理需在完整 54-run / 60 决策上验证（§11 Q1/Q5）。

### 6.5 边际分母规则（handoff §10 明令）—— 修正后的新解释

在**固定数量**语义下，`M1_marginal_cost_per_reclaimable` 是本样本上唯一大幅改善的规则（2/3 更好），当时只能猜测它「只是打破了同构」。

在**修正后的 replay 语义**下，解释变得可用测量支撑，而且**不同**：

| 指标 | 观测基线 | 边际分母规则 |
| --- | ---: | ---: |
| 平均释放次数 | 2.00 | **1.00** |
| 相对基线的平均释放数差 | 0 | **−1.00** |
| 更省释放的决策数 | — | **2 / 3** |
| 误选率 | 1.000 | 0.333 |

即：它满足**同一个** `required_blocks` 时只需 **1 次**释放，而基线需要 **2 次**。释放的条目正是产生代理损失的条目，所以**更少释放 = 更低总损失**。结合 §6.6 的分母测量（分母与成本单调同向但非成比例，相除后破坏成本序），可以得出一个不再依赖猜测的结论：

> 该规则的表面优势主要是一个**释放数量效应**：它优先选中那些能一次解开更多块的条目（即「每单位成本解开块数」最高者），而不是因为更好地度量了成本。

因此：**该规则仍不作为候选方法提出。** 理由与之前不同——不是「可能是假象」，而是「它的机制不是成本信号」。它留在规则集中仅作为退化审计项。

⚠️ 但这里出现了一个**新的、更重要的开放性**：释放数量本身就是一个可优化维度。如果某条规则能持续用更少释放满足同一 target，那它的价值就不在于「成本感知」而在于「解开效率」。这需要在完整数据上判定，且可能需要重新考虑它是否应该被排除（§11 Q2/Q7）。

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

**结论：§10 子问题 c 已回答——是，分母破坏了成本序。** 这为 §6.5 的机制解释提供了支撑：该规则的收益不能归因于成本信号。但它**不再单独构成排除理由**，因为 replay 语义显示它的优势主要来自释放数量效益（§6.5、§7.5）。是否应排除它，取决于 Q7。

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
| 分母：成本 alone vs 成本/可回收 | **0.333** | **0.333333** | 0.792135 |

两点：

1. **size 簇的三个特征完全互换**（同一率 1.000，regret 差为 0）。这不是「冗余」的统计陈述，而是**在任何测试决策上不产生任何不同选择**。切换其中任何一个都不会有任何效果。
2. **只有 tool 指示（0.667）与分母（0.333）真正改变了选择。** 分母改变得最多，而且在 replay 语义下其 regret 改善（0.333）远大于固定数量下的测值（0.626）—— 因为后者的语义根本看不到「用更少释放满足同一 target」。

这同时回答了 §10 子问题 d（表观收益是否只来自 tool 指示变量）：**否。** tool 指示确实改变了选择（同一率 0.667），但分母改变得更多（0.333）且改善更大。不过 §6.5 已说明分母的机制是释放数量效应，而非成本信号，因此这两个都不是已验证的「成本感知」收益。

### 7.2 按场景族的行为

平均归一化 regret（每个族包含 1 个 run）：

| 规则 | F1 | F4 | F6 |
| --- | ---: | ---: | ---: |
| `M0_p1b_executed_ordering`（基线） | 0.735684 | 0.640721 | 1.000000 |
| `M1_block_count_ascending` | 0.735684 | 0.640721 | 1.000000 |
| `M1_marginal_cost_per_reclaimable` | **0.000000** | **0.000000** | **1.000000** |

在 replay 语义下，边际分母规则的面貌变得非常锐利：它在 **F1 与 F4 上完全正确（0.0）**，而在 **F6 上完全错（1.0）**。

原因能在数据里直接看到：F1 与 F4 的 `required_blocks` 都可以被**一次**释放满足（见 §7.5），而 F6 的三个候选成本特征**全等**（`PrefillReload` 均为 `0.171057`、`block_count` 均为 32），在那里任何成本类排序都无法分辨，分母规则也不例外。

⇒ 样本级提示：该规则的收益与失败都取决于「能否用更少释放满足 target」，而不是取决于成本排序的优劣。

### 7.3 按候选集规模与释放数的行为

平均归一化 regret：

| 规则 | n=3 | n=5 | releases=1 | releases=2 | releases=3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `M0_p1b_executed_ordering` | 0.820361 | 0.735684 | 1.000000 | 0.640721 | 0.735684 |
| `M1_marginal_cost_per_reclaimable` | — | — | **0.333333** | — | — |

边际分母规则**只在 `releases=1` 出现**（它的每次决策都只用一次释放），而基线横跨 1–3 次。这正是 §6.5 所述释放数量效应的直接体现：两者的 `releases=1` 桶不可直接比较，因为其中的决策集合不同。

三点：

1. **多释放行为已分离报告**（`releases=1/2/3`），不再合并。这直接回应了 handoff §9 对 multi-release 行为的要求。
2. **size 簇的每一条规则（包括基线）在所有维度上给出完全相同的数字。** 这不是巧合，而是 §6.1 同构的直接后果：它们的选择集逐决策一致。
3. **基线在 `releases=1` 上 regret 为 1.000000**，即单释放决策上完全错 —— 与上表 F6 是同一个决策。

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

### 7.5 释放负担（replay 语义下新增的维度）

在修正后的语义下，**释放数量本身成为可报告的结果**。评估器为每条规则给出：

| 字段 | 含义 |
| --- | --- |
| `mean_releases` | 平均需要多少次释放才能满足共享 target |
| `mean_releases_vs_baseline` | 相对**观测基线**的平均释放数差（负 = 更省） |
| `frugal_decisions` | 比基线释放更少的决策数 |
| `saturated_decisions` | 比基线释放更多的决策数 |

本样本上的结果：size 簇全部规则与基线**完全一致**（`mean_releases` 2.00，差 0，更省 0 / 更饱和 0）；只有 `next_tool_type` 与边际分母规则改变了释放次数，其中边际分母规则平均只需 **1.00** 次（差 **−1.00**，2 个决策更省）。

这一维度的重要性：释放的条目正是产生代理损失的条目，因此**在满足同一 target 的前提下，更少的释放直接意味着更低的总损失**。前版固定数量比较把这一维度完全遮蔽了。

### 7.6 结论冻结声明

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
| Q7 | §6.5 的**释放数量效应**在 60 个决策上是否可复现？若可复现，「每单位成本解开块数」是否应被当作一个正当的优化目标（而不是被当作成本信号的伪装而排除）？ | 未决 —— 同上；这可能需要修正 §6.5 的排除结论 |
| Q8 | §2.1 声明的 regret 局限（hindsight 为**同数量**且不检查可行性）是否影响主结论？ | **已解决（§2.6）**：按 M1 裁定实现了 feasibility-aware oracle。canonical M6 继续保留为 provenance/sensitivity，M4 方法选择改用 feasible oracle。剩余问题：oracle 的结论（零损失单条目普遍存在）需在 60 个决策上验证 |

前八项**都不需要新观测**，只需要把外部证据包传进来。

## 12. 局限

- **没有提出候选方法。** Handoff §13 第 1 项要求“提出的规则”，而 §14 要求的是能胜出的设计。本报告交付的是 replay 引擎、评估器、规则集与诊断，**尚未收敛到一条可提交评审的规则**。这是最主要的遗留缺口，且有双重制约：§6.3 的样本级机理假设，以及 §6.5 新出现的「释放数量是否本身就是一个目标」的开放问题。
- **机制结论均为样本级。** §6 全部内容来自 **3 个决策 / 11 个候选 / 仅 seed-101**，且这 3 个 exemplar 是 M6 **按构造挑选的高 regret 样例**。任何在其中发现的规律都被系统性筛选过，不能作为机制陈述或效应量引用。
- **regret 是同数量且非可行的。** §2.1 已声明：hindsight 只取损失最小的同规模集合，不检查是否能解开压力。跨规则比较应以总代理损失为主。
- **证据为代理级别。** canonical 损失视角 `planned_return_weighted_prefill_proxy` 是 trace 派生的规划代理，不是实测重计算、TTL 或 serving 影响。依 handoff §3，除 `PROXY_SUPPORTED` 外不得作更强声明。
- **无运行时验证。** 无 vLLM 进程、无 GPU、无延迟数据。运行时可复制性（runtime replication）按 canonical 记录仍为 `false`。
- **未拟合任何模型。** 依 handoff §8，未对 60 个受控决策拟合高容量模型。
- **未做新颖性核查**（§13 第 11 项），需 M2 的相关工作输入。
- **仓库既有测试失败。** 全量套件在干净 `origin/main` 上即有失败（`test_continuum_vllm_observation_runner` 6 项、`test_phase2a_m6_*` 5 项），已核实与本次改动无关；属 M1/M6 范围。

## 13. 复现

**入库入口（推荐，无需 vLLM / GPU / 模型下载）：**

```bash
python -m kvopt.costaware.cli --artifact-root <raw run dir>
```

安装后也可用控制台脚本（`pyproject.toml` 的 `[project.scripts]`）：

```bash
kvopt-m4-offline --artifact-root <raw run dir> --output report.json
```

在完整 canonical 数据上（需先按 `docs/experiments/phase2a-m6-formal-v5/README.md` 取得外部证据包）：

```bash
python -m kvopt.costaware.cli \
  --artifact-root <extracted>/phase2a-formal-v5-final \
  --formal \
  --output report.json
```

限定规则或视角：

```bash
python -m kvopt.costaware.cli --rules M2_non_code_first
python -m kvopt.costaware.cli --loss-view observed_recomputed_tokens
```

输出：控制台报告；加上 `--output <path>` 会额外写入完整 JSON 报告。

`local/cost_aware_local_experiment.py` 只是同一代码路径的薄封装（默认为仓库内 exemplar，输出到 `local/output/`），**不再是唯一可复现的运行方式**。

## 14. 可追溯性

| 章节 | 来源 |
| --- | --- |
| §1, §13 | `src/kvopt/costaware/`、`pyproject.toml` 的 `[project.scripts]`、`.gitignore` |
| §2.1 | `src/kvopt/profiling/analysis.py` 的 `build_decision_regret_table` |
| §2.5 | `src/kvopt/costaware/replay.py`；`tests/test_costaware_replay.py` |
| §2.6 | `src/kvopt/costaware/feasible_oracle.py`；`tests/test_costaware_feasible_oracle.py`；入库 CLI 的 PRESSURE-FEASIBLE ORACLE 段 |
| §2, §3 | `src/kvopt/costaware/offline_eval.py`、`rules.py`；`docs/phase2a-m4-method-design-input.md` §8/§9/§10 |
| §4, §5 | 入库 CLI 报告（`python -m kvopt.costaware.cli`）的 REPLAY FIDELITY 与 EVALUATION 段 |
| §5.0 | `src/kvopt/costaware/offline_eval.py` 的 `candidate_loss_tied` 与 `_aggregate` |
| §5.2 | `docs/experiments/phase2a-m6-formal/README.md`（exemplars 为高 regret 样例） |
| §5.3 | 入库 CLI 报告的 LEAVE-ONE-FAMILY-OUT 段 |
| §6.1 | 入库 CLI 报告的 DEGENERACY 段 |
| §6.2 | `local/probe_deadline_vs_cost.py` 输出（1/3、r=0.4517） |
| §6.3 | `local/probe_loss_mechanism.py` 输出 |
| §6.5, §7.5 | 入库 CLI 报告的 RELEASE BURDEN 段（`ReleaseBurdenRow`） |
| §6.6 | `offline_eval.denominator_diagnostic()`；入库 CLI 报告的 DENOMINATOR DIAGNOSTIC 段 |
| §7.1 | `offline_eval.ablation_table()` 与 `ABLATION_PAIRS` |
| §7.2–7.3 | `offline_eval.behaviour_breakdown()`；入库 CLI 报告的对应段 |
| §7.4 | `docs/experiments/phase2a-m6-formal/README.md`（exemplars 仅含 seed-101） |
| §8 | `local/probe_rule_complexity.py` 输出；`tests/test_costaware_rules.py::test_size_score_prepare_does_not_rescan_per_candidate` |
| §9 | `src/kvopt/costaware/rules.py` 模块 docstring 与 `fallback_key()`；四个回退测试 |
| §10 | `docs/policy-adapter-design.md`；`src/kvopt/runtime/vllm/types.py`；`docs/phase2a-m4-method-design-input.md` §5/§11 |
| §11, §12 | `docs/phase2a-m4-method-design-input.md` §3/§7/§9/§11/§13 |
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
local/cost_aware_local_experiment.py   入库 CLI 的薄封装（不再是主实现）
local/probe_replay_fidelity.py         §2.5.3 的保真度与释放数量对比
local/probe_deadline_vs_cost.py        §6.2 的证伪测量
local/probe_loss_mechanism.py          §6.3 的逐候选机理诊断
local/probe_rule_complexity.py         §8 的分规则复杂度
```
