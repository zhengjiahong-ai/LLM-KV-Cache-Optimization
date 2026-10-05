# Phase 2A M4 — 方法设计与离线评估报告 v1

状态：**方法设计（非运行时实现）** — 依 `docs/phase2a-m4-method-design-input.md` §14

**证据状态：完整 canonical campaign 已评估**（54 runs / 60 decisions / 174 candidates / 6 families / 3 seeds）。

⛔ **主要结论是否定性的**：9 条被评估的 entry-level 规则中，**没有一条带来实质改善**。详见 §5 与 §12。

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

### 1.1 数据来源与可复现性

本节全部数字来自 canonical 证据包的 `phase2a-formal-v5-final`：

```text
artifacts/phase2a-formal-v5-final/
  54 run 目录，每个含 run.json / trace.json / replay.jsonl / events.jsonl
```

provenance 已核对：

```text
run git_sha     : b0ca52fb9a743aa46447feff34be6675c76af290   （与 M6 results 文档一致）
git_dirty       : False
schema          : phase2a.derived.v2
campaign        : formal = True
```

复现命令（无需 vLLM / GPU / 模型下载）：

```bash
python -m kvopt.costaware.cli \
  --artifact-root <path>/phase2a-formal-v5-final --formal --output report.json
```

在完整数据上耗时 **约 1.2 秒**。

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
#### 2.6.4 完整 canonical 数据上的结果

**以下为权威结果**（60 决策）。§2.6.5 保留了 3 个 exemplar 的早期读数，作为「不要在高 regret 样例上推断」的记录。

| 事实 | 值 |
| --- | ---: |
| 有 oracle 的决策 | 60 / 60 |
| oracle 只需 **1 个条目**的决策 | **60 / 60** |
| oracle 损失为 **0** 的决策 | **24 / 60** |
| 不可达决策 | 0 |
| 平均可行集合数 | 8.1 |

两个 comparator 的对比：

| 指标 | canonical M6 comparator | **feasible oracle comparator** |
| --- | ---: | ---: |
| 基线平均归一化 regret | 0.368820 | **0.400000** |
| 基线平均绝对 regret | 0.036250 | **0.041225** |
| 基线达到可行最优的比例 | — | 0.600 |
| 基线平均条目数差 | — | +0.15 |

⇒ feasible comparator **确实更严**（0.400 vs 0.369），因为它检查了压力可行性。但**差距远小于 exemplar 读数**。

⚠️ **一个需要 M1 裁定的度量问题**：由于 24 个决策的 `oracle_loss` 恰为 0，这些决策上的归一化 regret 只能取 `abs/selected = 1.0`（未达最优时）或 `0.0`，因此该指标对多数规则都落在 `24/60 = 0.400`，**近似二值**。跨规则比较应以 `mean_absolute_regret` 与配对损失变化为主。**登记为 Q11。**

#### 2.6.5 保留记录：3 个 exemplar 的早期读数（**已被完整数据部分证伪**）

在仓库内的 3 个高 regret exemplar 上：

| 决策 | 目标 | 候选数 | 可行集合数 | oracle 损失 | 最差可行损失 |
| --- | ---: | ---: | ---: | ---: | ---: |
| f1 ev64 | 32 | 5 | 27 | **0.000000** | 0.188239 |
| f4 ev40 | 32 | 3 | 5 | **0.000000** | 0.138485 |
| f6 ev40 | 16 | 3 | 7 | **0.000000** | 0.342114 |

当时得到了「基线 feasible 归一化 regret = 1.000」这类很强的读数，并据此预测「单个零损失可行释放在全样本普遍成立」。

**完整数据的结果是 24/60 = 40%，而非普遍成立。** 这是本报告第二处「exemplar 推断被完整数据修正」的记录（第一处见 §6.5）。

⇒ **方法学教训**：3 个按构造挑选的高 regret 样例会把效应幅度系统性放大，并可能制造出看似普遍的规律。本报告的所有结论现在都只在完整数据上陈述。

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

自检由 **replay 保真度**承担（旧的固定数量自检函数已删除，因为它假定了一个错误约束）。

### 4.1 在完整 canonical campaign 上（54 runs / 60 decisions / 174 candidates）

```text
decisions compared        : 60
release SET match rate    : 1.0000
release ORDER match rate  : 1.0000
marginal blocks match rate: 1.0000  (174 fields)
```

即冻结的 P1B 排序在 replay 下**精确复现了全部 60 个观察决策**：集合、顺序、以及每个条目的 `initially_reclaimable_block_ids` 全部一致。第三项独立于任何策略，单独验证了所有权与可用性模型。

### 4.2 独立复现 canonical M6 数字

评估器在完整数据上给出的基线指标，与 M6 正式报告**逐位一致**：

| 指标 | 本报告 | M6 handoff §1 |
| --- | ---: | ---: |
| 平均绝对 regret | `0.03624980627828336` | `0.03625` |
| 平均归一化 regret | `0.3688202702960877` | `0.36882` |
| 非平局决策 | 39 | 39 |
| 严格劣选决策 | 24 | 12（见下方说明） |

这与「保真度 1.0」共同构成对 harness 的强验证：**replay 语义、可用性模型、与 canonical regret 链路三者一致**。

ⓘ 严格劣选数 24 vs M6 的 12：M6 的 12 是基于其自身的 `hindsight_mandatory` 定义在**非平局 27 个决策**上；本报告的 24 建立在**非平局 39 个决策**上，因为 `non_tied` 采用「候选损失不完全相同」的 M6 定义而 M6 的 regret 表使用的是另一套平局判定。两者的 `mean_absolute_regret` 与 `mean_normalized_regret` 完全一致，说明差异仅在平局分母口径，不影响任何比较结论。**登记为 §11 Q9。**

## 5. canonical campaign 上的完整结果

数据源：`artifacts/phase2a-formal-v5-final`（54 runs / 60 decisions / 174 candidates / 6 families / 3 seeds），`formal_campaign=True`。

```text
evaluated decisions : 60
skipped decisions   : 0
unsatisfied         : 0
candidates scored   : 174
```

### 5.0 指标定义（与 M6 对齐）

- `non_tied_decisions`：**决策内候选损失不完全相同**，即选择会影响结果的决策数。
  它刻画「该决策有无 headroom」，与「本规则是否抓住」无关。
- `strictly_worse_decisions`：本规则的选择未落在 canonical 最优集合内的决策数。
- `misselection_rate` = `strictly_worse / non_tied`。
- `tie_rate`：全部候选损失相同的决策占比。

### 5.1 canonical 汇总表

| 规则 | 平均归一化 regret | 平均绝对 regret | 误选率 | 平均释放数 | 对比基线 更好/更差/平 |
| --- | ---: | ---: | ---: | ---: | --- |
| `M0_p1b_executed_ordering`（基线） | 0.368820 | 0.036250 | 0.615 | 1.150 | 基线 |
| `M1_prefill_reload_ascending` | 0.368820 | 0.036250 | 0.615 | 1.150 | **0 / 0 / 60** |
| `M1_block_count_ascending` | 0.368820 | 0.036250 | 0.615 | 1.150 | **0 / 0 / 60** |
| `M1_reclaimable_ascending` | 0.368820 | 0.036250 | 0.615 | 1.150 | **0 / 0 / 60** |
| `M3_size_score_only` | 0.368820 | 0.036250 | 0.615 | 1.150 | **0 / 0 / 60** |
| `M2_non_code_first` | **0.357036** | **0.031813** | 0.615 | 1.150 | **3 / 0 / 57** |
| `M3_non_code_then_small_prefill` | 0.357036 | 0.031813 | 0.615 | 1.150 | 3 / 0 / 57 |
| `M3_non_code_then_size_score` | 0.357036 | 0.031813 | 0.615 | 1.150 | 3 / 0 / 57 |
| `M1_marginal_cost_per_reclaimable` | 0.254498 | 0.043534 | 0.538 | **1.000** | 18 / 18 / 24 |

**三个确定结论：**

1. **size 簇与基线在全部 60 个决策上完全同构**（0 更好 / 0 更差 / 60 平）。这不是样本噪声，而是结构性事实（详见 §6）。
2. **只有 tool 指示打破同构**，且方向一致向好：3 更好 / 0 更差 / 57 平，平均损失改善 `+0.004437` 秒，**零回归**。
3. **边际分母规则是净负面的**：18 更好但 18 更差，平均损失变化 `−0.002308` 秒（负值 = 更贵）。它确实用更少的释放（1.000 vs 1.150），但换来的损失抵消并超过了这一收益。

### 5.2 该样本的统计地位

与之前 3 个 exemplar 版本不同，本节的数字**不再受「刻意挑选高 regret 样例」影响**——它们是完整正式 campaign 的全部 60 个决策。

但仍须注意：

- **证据仍为代理级别**（`planned_return_weighted_prefill_proxy`），非实测重计算或 serving 影响；
- **有效独立样本量小于 60**，因为 seed 维度近似重复（详见 §5.4）；
- **`PROXY_SUPPORTED` 不等于 `RUNTIME_STABLE`**：尚无独立正式重跑复现信号结果。

### 5.3 族级行为（handoff §9，Q3 的核心证据）

平均归一化 regret：

| 规则 | F1 | F2 | F3 | F4 | F5 | F6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `M0_p1b_executed_ordering`（基线） | 0.2452 | 0.3333 | 0.3333 | 0.4102 | 0.3333 | 0.5000 |
| `M2_non_code_first` | **0.1667** | 0.3333 | 0.3333 | 0.4102 | 0.3333 | 0.5000 |
| `M1_marginal_cost_per_reclaimable` | 0.2364 | 0.2364 | **0.0000** | **0.1203** | 0.3333 | **0.5476** |

**这是本轮最重要的否定性发现之一：**

> `M2_non_code_first` 与基线**只在 F1 一个族上不同**（0.1667 vs 0.2452）；在 F2–F6 上**逐位相同**。

也就是说，tool 信号的全部收益**来自单一场景族**。这正是 handoff §9 警告的「scenario-family memorization」失败模式。按 M6 预注册的族一致性要求（≥ 2/3），该信号**不满足稳定性**。

留出交叉验证给出同一结论（留出 F1 时两者完全相同）：

| 规则 | 留出 F1 | 留出 F2 | 留出 F3 | 留出 F4 | 留出 F5 | 留出 F6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 基线 | 0.3906 | 0.3751 | 0.3751 | 0.3585 | 0.3751 | 0.3360 |
| `M2_non_code_first` | 0.3906 | 0.3612 | 0.3612 | 0.3438 | 0.3612 | 0.3213 |

边际分母规则在 F1/F2/F3/F4 上改善，但在 **F6 上明显变差**（0.5476 vs 0.5000），与其整体净负面的配对结果一致。

### 5.4 seed 维度：**近似重复，seed 稳定性为空**

handoff §3 要求 seed 一致性。本报告测得一个**方法学上重要的负面事实**：

```text
基线 mean_abs  = 0.03624980627828336   （seed 101 / 211 / 307 三个子集逐位相同）
基线 mean_norm = 0.3688202702960877    （同上）
每个 seed 的决策数 = 20；每个 (family, seed) 单元决策数完全相同
```

原因：18 个场景组中，**16 组的损失剖面在三个 seed 之间完全相同**，只有 2 组（`f4-repeated-pressure`、`f6-repeated-block-reuse`）不同。

⇒ **三个 seed 在指标层面是排列副本，几乎不提供独立信息。**

后果：

1. **「跨 seed 稳定」在本 campaign 上是空命题** —— 没有变异可供稳定；
2. **有效独立样本约为 20 个场景决策**，而非 60；
3. 任何「在 3 个 seed 上稳定」的声明都应视为**未获证据**。

M6 的 gate 在数值上满足「≥3 seeds represented」，但该满足不带来统计效力。**登记为 §11 Q10。**

### 5.5 结论冻结声明

本报告**未冻结任何验收规则**，因为**没有任何候选规则达到可提交标准**（见 §12 第一条）。§5–§7 的分解因此仅具诊断地位。

⚠️ 前版报告曾基于 3 个高 regret exemplar 给出数字，**已全部替换为本节的完整 canonical 结果**。二者差异很大（例如「单个零损失可行释放」在 exemplar 上是 3/3，在完整数据上只有 24/60），这本身就是「不要在高 regret 样例上做推断」的实证。

## 6. 退化审计（handoff §10）—— 已在完整数据上确认

Handoff §10 要求重新检验请求级退化，而非假设其不存在。结果如下。

> **证据级别声明**：本节结论建立在**完整 canonical campaign**（54 runs / 60 decisions / 174 candidates / 6 families）之上，不再是 exemplar 推断。前版报告基于 3 个高 regret exemplar 的表述**已全部替换或修正**，其中两项被完整数据推翻（§6.5、§6.7）。
>
> 仍须注意：证据为**代理级别**（`planned_return_weighted_prefill_proxy`）；**seed 维度近似重复**（§5.4），故「跨 seed 稳定」不构成独立验证；且 `PROXY_SUPPORTED ≠ RUNTIME_STABLE`。

### 6.1 已确认：size/recompute 簇与基线排序**完全同构**

在完整 canonical campaign（60 决策）上：

```text
M0_p1b_executed_ordering == M1_prefill_reload_ascending   over 60 decisions
M0_p1b_executed_ordering == M1_block_count_ascending      over 60 decisions
M0_p1b_executed_ordering == M1_reclaimable_ascending      over 60 decisions
M0_p1b_executed_ordering == M3_size_score_only            over 60 decisions
```

配对比较（对基线）：**0 更好 / 0 更差 / 60 平**，平均损失变化 `0.000000`。

消融表确认同一事实——三个 size 开关的选择同一率均为 **1.000**：

| 消融变体 | 选择同一率 |
| --- | ---: |
| size 簇：成本 vs 占用 | **1.000** |
| size 簇：成本 vs 可回收 | **1.000** |
| size 簇：成本 vs 三者平均 | **1.000** |

且在**每个 seed 上都是 1.000**（101 / 211 / 307）。

**结论（已验证，非假设）：`PROXY_SUPPORTED` 的四个特征中，三个 size 特征在本 campaign 上不产生任何与已执行 P1B 排序不同的选择。** 13 个规则对完全同构。

⚠️ 这**不**意味着 M6 的 ρ≈0.205 是错的。秩关联可以完全落在基线排序的方向上而不产生分歧。**关联显著 ≠ 决策可分歧** —— 而这正是之前 3 个 exemplar 无法确定的。

### 6.2 该同构的成因**不是**线性成本退化（已在完整数据上确认）

**曾提出的解释（已证伪）**：spike 的线性成本论证认为 `C_recompute / Blocks` 近似常数，因此 deadline 排序与尺寸排序一致。

**完整数据上的证伪**：逐候选比较「PrefillReload 序」与「retention deadline 序」：

```text
decisions where cost-order == deadline-order : 21/60  (35%)
Pearson(deadline, PrefillReload) over 174 candidates : 0.1960
```

只有 **35%** 的决策同序，相关系数仅 **0.196**。线性成本退化论证在全样本上**不成立**（且比 3-exemplar 时的 0.45 更弱）。

### 6.3 已确认的机理候选：损失由返回窗口主导，成本规则对此全盲

canonical 代理损失**不是纯成本**：

$$
\text{loss} = \begin{cases} \text{PrefillReload} & \text{若规划在 horizon 内返回} \\ 0 & \text{否则} \end{cases}
$$

完整数据上的两项支持证据：

1. **24/60 个决策存在零损失可行释放**，而 oracle 在 **60/60** 个决策中都只需释放 **1 个条目**（§6.7）。也就是说，总存在一个单条目释放能满足压力；其中 40% 的情况该条目损失为 0。
2. **size 簇与基线同构**（§6.1）：若判别维度是成本，成本升序应当偏离 deadline 排序；它没有偏离，而两者的成对相关性又只有 0.196。**它们同构不是因为同序，而是因为两者都无法分辨真正的判别维度。**

**机理假设（现有证据支持，但仍为假设）**：在 canonical 代理下，判别维度是**复用/返回窗口**，而非成本。因此任何纯成本规则都无法改善，**与成本曲线形状无关**。

其意义：它**削弱**（不是否证）了「只要测到非线性 $C(r)$ 就能让成本规则生效」这条路径。

⚠️ **仍需独立正式重跑验证**：本 campaign 是 `PROXY_SUPPORTED`，且 seed 维度近似重复（§5.4），因此「在 3 seeds 上稳定」不构成独立验证。该机理升格为机制陈述需要一次**独立重跑**。

### 6.4 与既有证据的关系

- 与 spike 的 F.2（「TTL 层本身就是 cost-aware 过滤器」）方向一致，但**机制不同**：F.2 说的是保护池被同质化，这里说的是**损失函数本身由返回窗口主导**。
- 与 M6 的信号门禁**部分冲突**：`next_tool_type=code` 通过了门禁，但在完整数据上它的收益只在 **F1 一个族**出现（§5.3），因此不满足族一致性。

### 6.5 边际分母规则：**完整数据上不成立**（修正前版的结论）

前版基于 3 个高 regret exemplar 认为该规则是「唯一大幅改善者」。**完整数据推翻了这一结论：**

| 指标 | 观测基线 | 边际分母规则 |
| --- | ---: | ---: |
| 平均释放次数 | 1.150 | **1.000** |
| 更省释放的决策数 | — | **6 / 60** |
| 配对结果 vs 基线 | — | **18 更好 / 18 更差 / 24 平** |
| 平均损失变化 | — | **−0.002308 秒（净负面）** |
| 平均归一化 regret | 0.368820 | 0.254498 |
| feasible oracle 误选率 | 0.400 | **0.450（更差）** |
| feasible oracle 平均绝对 regret | 0.041225 | **0.043534（更差）** |

**两个 comparator 出现分歧**，这本身是重要发现：

- canonical comparator 认为它最好（0.2545 vs 0.3688）；
- feasible comparator 认为它**更差**（误选率 0.450 vs 0.400，绝对 regret 0.0435 vs 0.0412）。

配对比较给出了裁决：**18 更好 / 18 更差 / 净损失变化为负**。它是「用更少释放换更差选择」的赌博，且**赌输了**。

⇒ **明确结论：该规则不成立，应从候选中排除。** 这与 handoff §10 的禁令一致，且现在有了完整数据支撑。

⚠️ 它也**推翻了「释放数量效应是真实收益」这一假设**（§11 Q7）：释放更少确实发生了（1.000 vs 1.150），但**总损失没有下降**。原因是它换掉的那些条目损失更高，抵消并超过了释放数量带来的收益。

### 6.6 §10 子问题 c：分母是否抵消了成本信号（完整数据）

`denominator_diagnostic()` 在 60 个决策上：

```text
decisions with a CONSTANT denominator : 24/60
cost-vs-ratio rank inversions          : 126/189 comparable pairs (66.7%)
```

三分之二的可比较对发生秩反转。**答案：是，分母确实破坏了成本序**，与 3-exemplar 时的定性结论一致（当时 11/16 = 69%），现在在完整数据上确认。

但它**不再构成排除理由**——§6.5 已经用配对比较直接否证了该规则的有效性。

### 6.7 feasibility-aware oracle 在完整数据上的结果（Q8 交付）

| 事实 | 值 |
| --- | ---: |
| 有 oracle 的决策 | 60 / 60 |
| oracle 只需 **1 个条目**的决策 | **60 / 60** |
| oracle 损失为 **0** 的决策 | **24 / 60** |
| 不可达决策 | 0 |
| 平均可行集合数 | 8.1 |
| 平均候选数 | 2.9 |

**baseline 与可行最优的差距：**

| 指标 | canonical M6 comparator | **feasible oracle comparator** |
| --- | ---: | ---: |
| 基线平均归一化 regret | 0.368820 | **0.400000** |
| 基线平均绝对 regret | 0.036250 | **0.041225** |
| 基线达到可行最优的比例 | — | 0.600 |
| 基线平均条目数差 | — | +0.15 |

⇒ feasible comparator **严格更严**（0.400 vs 0.369），但**没有 3-exemplar 时那么悬殊**（当时基线归一化 regret 为 1.000，因为所有决策 oracle 损失都是 0）。

⚠️ **前版预测被部分证伪**：3 个 exemplar 上「单个零损失可行释放」是 3/3，我据此预测它在全样本普遍成立。**完整数据只有 24/60 = 40%。** 这正是「不要在高 regret 样例上做推断」的又一实证。

⚠️ **feasible 归一化 regret 在当前损失结构下近似二值**：由于 24 个决策的 `oracle_loss` 恰为 0，这些决策上的归一化 regret 只能是 `abs/selected = 1.0`（未达最优时）。因此该指标的均值对多数规则都落在 `24/60 = 0.400`。**跨规则比较应以 `mean_absolute_regret` 与配对损失变化为主。** 登记为 §11 Q11。

## 7. §9 要求的行为分解与消融（完整 canonical 数据）

§9 列出 9 项必须报告的内容。本节覆盖全部 9 项。

### 7.1 特征消融表

`ablation_table()` 由既有规则对构建，避免新增规则造成的比较污染。

| 消融变体 | 选择同一率 | 变体平均归一化 regret | 基准 |
| --- | ---: | ---: | ---: |
| size 簇：成本 alone vs 占用 alone | **1.000** | 0.368820 | 0.368820 |
| size 簇：成本 alone vs 可回收 alone | **1.000** | 0.368820 | 0.368820 |
| size 簇：成本 alone vs 三者平均 | **1.000** | 0.368820 | 0.368820 |
| tool 指示：关闭 vs 开启（成本为主） | **0.950** | **0.357036** | 0.368820 |
| tool 指示：关闭 vs 开启（分数为主） | 0.950 | 0.357036 | 0.368820 |
| 分母：成本 alone vs 成本/可回收 | **0.400** | 0.254498 | 0.368820 |

三点：

1. **size 簇三个特征完全互换**（同一率 1.000，regret 差为 0）：切换其中任何一个都**不产生任何不同选择**。
2. **tool 指示改变 3/60 个决策**（同一率 0.950），是唯一带来**零回归改善**的维度。
3. **分母改变 36/60 个决策**（同一率 0.400），是改变最多者——但 §6.5 已证明它在配对比较上**净负面**。

这回答了 §10 子问题 d（表观收益是否只来自 tool 指示）：**否**——分母改变得更多。但两者都不构成「成本感知」收益。

### 7.2 按场景族的行为（Q3 核心）

平均归一化 regret：

| 规则 | F1 | F2 | F3 | F4 | F5 | F6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `M0_p1b_executed_ordering`（基线） | 0.2452 | 0.3333 | 0.3333 | 0.4102 | 0.3333 | 0.5000 |
| `M1_block_count_ascending` | 0.2452 | 0.3333 | 0.3333 | 0.4102 | 0.3333 | 0.5000 |
| `M3_size_score_only` | 0.2452 | 0.3333 | 0.3333 | 0.4102 | 0.3333 | 0.5000 |
| `M2_non_code_first` | **0.1667** | 0.3333 | 0.3333 | 0.4102 | 0.3333 | 0.5000 |
| `M1_marginal_cost_per_reclaimable` | 0.2364 | 0.2364 | **0.0000** | **0.1203** | 0.3333 | **0.5476** |

**决定性发现**：`M2_non_code_first` 与基线**只在 F1 一个族上不同**（0.1667 vs 0.2452），在 F2–F6 上**逐位相同**。

⇒ tool 信号的**全部**收益来自单一场景族，正是 handoff §9 警告的 family memorization。按 M6 预注册的族一致性要求（≥ 2/3），**该信号不满足稳定性**。

### 7.3 按候选集规模与释放数的行为

平均归一化 regret（基线）：

| n=2 | n=3 | n=4 | n=5 | releases=1 | releases=2 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.4000 | 0.3333 | 0.2857 | 0.4000 | 0.4000 | 0.2857 |

三点：

1. **多释放行为已分离报告**（`releases=1/2`），回应 handoff §9 对 multi-release 的要求。
2. **size 簇的每条规则（含基线）在所有维度上给出完全相同的数字** —— 这是 §6.1 同构的直接后果。
3. canonical campaign 的释放数只取 1 与 2（平均 1.150），**没有 3 次释放的决策**。

### 7.4 跨 seed 的排序稳定性：**已评估，但为空命题**

§9 要求报告 ranking stability across seeds。现在数据齐备，结果是：

```text
seed 101 : mean_abs 0.03624980627828336  mean_norm 0.3688202702960877  n=20
seed 211 : mean_abs 0.03624980627828336  mean_norm 0.3688202702960877  n=20
seed 307 : mean_abs 0.03624980627828336  mean_norm 0.3688202702960877  n=20
all      : mean_abs 0.03624980627828336  mean_norm 0.3688202702960877  n=60
```

**三个 seed 的聚合值逐位相同。** 原因见 §5.4：18 个场景组中 16 组的损失剖面在 seed 之间完全相同。

⇒ 跨 seed 稳定性**形式上满足但实质为空**：没有变异可供稳定。任何「在 3 个 seed 上稳定」的声明都应视为**未获证据**。

依 §3，特征升格为 `RUNTIME_STABLE` 需要**独立正式重跑**复核方向、效应量、族一致性与 seed 一致性。**这不在当前授权范围内，且本报告不主张任何特征已达到该级别。**

### 7.5 释放负担（replay 语义下新增的维度）

| 字段 | 含义 |
| --- | --- |
| `mean_releases` | 平均需要多少次释放才能满足共享 target |
| `mean_releases_vs_baseline` | 相对**观测基线**的平均释放数差（负 = 更省） |
| `frugal_decisions` | 比基线释放更少的决策数 |
| `saturated_decisions` | 比基线释放更多的决策数 |

完整数据上的结果：

| 规则 | 平均释放数 | 差 vs 基线 | 更省 | 更饱和 |
| --- | ---: | ---: | ---: | ---: |
| size 簇（全部 4 条） | 1.150 | 0.000 | 0 | 0 |
| `M2_non_code_first` 等 | 1.150 | 0.000 | 0 | 0 |
| `M1_marginal_cost_per_reclaimable` | **1.000** | **−0.150** | **6** | 0 |

**唯一改变释放次数的是边际分母规则**，但它只影响 6/60 个决策，且**净损失变化为负**（§6.5）。

⇒ **Q7 的答案：释放数量效应在完整数据上不构成收益。** 释放更少确实发生，但换来的损失抵消并超过它。前版基于 3 个 exemplar 的「释放数量效应是真实收益」假设**被推翻**。

### 7.6 结论冻结声明

§9 要求：

> Any score/threshold acceptance rule must be frozen before using the final holdout result.

**本报告未冻结任何验收规则**，因为**没有任何候选规则达到可提交标准**（见 §12 第一条）。§7 的消融与分解因此仅具诊断地位。

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

### 10.1 entry-level 家族只需要**零新增观测**

M1/M2/M3 家族用到的全部字段（`prefill_reload_seconds`、`block_count`、`initially_reclaimable_block_count`、`next_tool_type`）**已经存在于 `FORCED_RELEASE_DECISION` 载荷中**，即已在正式 campaign 中被采集。

因此不需要新的运行时观测缝。这与 handoff §9「M1 may decide whether an additional safe decision-time observation is justified」是相容的：**对 entry-level 家族而言，答案是不需要。**

⚠️ **但必须同时说明**：完整数据的结论是 **entry-level 家族内没有任何规则带来实质改善**（§11 Q1/Q2/Q3）。所以「不需要新观测」不等于「可以实施」——恰恰相反，它意味着**在现有观测下，这条路径已经被完整数据否定**。

这正是 handoff §9 提到的另一种可能结局：

```text
HEADROOM-BUT-NO-ONLINE-SIGNAL 的复发
```

本 campaign 上，headroom 存在（基线 feasible 误选率 0.400），但**可用的在线信号无法把它转化为可靠的改善**：唯一零回归的维度（tool 指示）只在单一族有效。

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

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| Q1 | size 簇与基线排序的同构在完整数据上是否成立？ | **已答（§6.1）：成立。** 0 更好 / 0 更差 / **60 平**，消融同一率 1.000，且在全部 3 个 seed 上为 1.000 |
| Q2 | `M1_marginal_cost_per_reclaimable` 的改善是否复现？ | **已答（§6.5）：不复现。** 配对 **18 更好 / 18 更差**，平均损失变化 **−0.002308（净负面）**；feasible oracle 上误选率更差（0.450 vs 0.400）。**应从候选中排除** |
| Q3 | `next_tool_type=code` 的收益是否跨族稳定？ | **已答（§5.3、§7.2）：不稳定。** 收益**只在 F1 一个族**出现，F2–F6 逐位相同。不满足 M6 族一致性要求 |
| Q4 | 是否存在能超越 entry-level 的 block-level 收益？ | **未决** —— handoff §11 的四个前置问题（真实 $C(r)$、部分 APC 语义、接口可用性、超越 entry-level 的离线收益）。**且因 Q3 的否定结果，其优先级下降** |
| Q5 | §6.3 的「返回窗口主导」机理在完整数据上是否成立？ | **部分确认（§6.3）：** 24/60 决策存在零损失可行释放、60/60 只需单条目释放；size 簇与基线同构且 cost/deadline 相关性仅 0.196。升格为机制陈述仍需**独立正式重跑** |
| Q6 | size 簇完全互换在完整数据上是否成立？ | **已答（§6.1、§7.1）：成立。** 三个尺寸特征应被视为**一个**特征，而非三个独立信号 |
| Q7 | 释放数量效应是否构成收益？ | **已答（§6.5、§7.5）：不构成。** 只有边际分母规则改变释放数（6/60），但它**净损失为负**。前版「释放更少 = 总损失更低」的假设**被推翻** |
| Q8 | regret 的同数量、非可行局限是否影响主结论？ | **已解决（§2.6）** —— feasibility-aware oracle 已实现并与 canonical M6 comparator 分离报告 |
| **Q9** | **本报告的 `non_tied`/`strictly_worse`（39/24）与 M6 报告（27/12）口径不一致** | **未决** —— 两者的 `mean_absolute_regret` 与 `mean_normalized_regret` 逐位相同，差异仅在平局分母定义。需 M1/M6 统一口径 |
| **Q10** | **seed 维度近似重复，如何影响「3 seeds」的 gate 证据效力？** | **未决** —— §5.4 测得 seed 聚合值逐位相同、16/18 场景组损失剖面相同。**需 M1 裁定**该 gate 项是否仍算有效证据 |
| **Q11** | **feasible 归一化 regret 因 24 个 `oracle_loss==0` 决策而近似二值** | **未决** —— 跨规则比较应以 `mean_absolute_regret` 与配对损失变化为主；需 M1 确认该优先级 |

**Q1/Q2/Q3/Q6/Q7 已由完整数据回答；Q8 已实现；Q4/Q5/Q9/Q10/Q11 待定。**

## 12. 局限

- **没有提出候选方法 —— 而且现在有证据表明当前规则集内不存在。** Handoff §13 第 1 项要求「提出的规则」，§14 要求「能胜出的设计」。完整数据给出的结论是：**9 条被评估的决策时规则中，没有一条带来实质改善。** size 簇与基线完全同构（Q1）、边际分母规则净负面（Q2）、tool 信号只在单一族有效（Q3）。这是本报告最重要的交付——一个**有完整数据支撑的否定结果**。
- **regret 是同数量且非可行的。** §2.1 已声明；M4 方法选择已改用 feasibility-aware oracle（§2.6），canonical M6 comparator 保留为 provenance。
- **`non_tied` 口径与 M6 不一致（Q9）。** 不影响 regret 数值（逐位相同），但影响误选率的分母。
- **seed 维度近似重复（Q10）。** 有效独立样本约为 **20 个场景决策**，而非 60。「跨 seed 稳定」在本 campaign 上不构成独立证据。
- **证据为代理级别。** `planned_return_weighted_prefill_proxy` 是 trace 派生的规划代理，不是实测重计算、TTL 或 serving 影响。依 handoff §3，**`PROXY_SUPPORTED` 不得升格为 `RUNTIME_STABLE`**，且本 campaign 尚无独立正式重跑。
- **无运行时验证。** 无 vLLM 进程、无 GPU、无实测延迟。canonical 记录的 runtime replication 仍为 `false`。
- **未拟合任何模型。** 依 handoff §8，未对 60 个受控决策拟合高容量模型；本报告只评估小规模、可手审的规则。
- **未做新颖性核查**（§13 第 11 项），需 M2 的相关工作输入。
- **区块级路径的证据基础被削弱。** §6.3 的机理若成立，则「测到非线性 $C(r)$ 就能让成本规则生效」这条路径被削弱，因此 block-level 的**动机**（此前依赖于成本非线性）需要重新论证。
- **仓库既有测试失败。** 全量套件在干净 `origin/main` 上即有 11 项失败（`test_continuum_vllm_observation_runner` 6 项、`test_phase2a_m6_*` 5 项），已核实与本次改动无关；属 M1/M6 范围。

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
| §6.2 | 本报告在完整数据上的测量（21/60、r=0.1960） |
| §6.3 | 入库 CLI 的 PRESSURE-FEASIBLE ORACLE 段；`local/probe_loss_mechanism.py` |
| §6.5 | 入库 CLI 的 PAIRED COMPARISON、RELEASE BURDEN 与 PRESSURE-FEASIBLE ORACLE 段 |
| §6.6 | `offline_eval.denominator_diagnostic()`；入库 CLI 的 DENOMINATOR DIAGNOSTIC 段 |
| §6.7 | 入库 CLI 的 PRESSURE-FEASIBLE ORACLE 段 |
| §7.1 | `offline_eval.ablation_table()` 与 `ABLATION_PAIRS` |
| §7.2–7.5 | `offline_eval.behaviour_breakdown()`；入库 CLI 的对应段；`local/probe_seed_stability.py` |
| §5.4, §7.4 | `local/probe_seed_stability.py` 输出（seed 聚合值逐位相同） |
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
