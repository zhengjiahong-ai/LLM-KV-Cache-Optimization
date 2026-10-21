# Phase 2G Entry-level Cost-Aware —— 方法可行性研究

M1 授权：Entry-level Cost-Aware Method Research / Existing A1 Model Analysis / Frozen Evidence Reuse /
Mathematical Counterexamples & Lightweight Offline Probes / Candidate Algorithm Proposal —— 已授权。
A1/A2 实现修改、A3 实现、新 Native Campaign、Workload Redesign —— **未授权**；B1 LOCKED。

本文按 M1 对 PR #70 的复审（RC1–RC3）修订。`src/` 未改动，无 Native 运行。

```bash
python scripts/probes/a1_structural_gap.py                                        # 合成反例
python scripts/probes/a1_real_gap.py --q=uniform local/phase2a-h1-level-a-evidence-e3a02fd
python scripts/probes/a1_real_gap.py --q=deadline local/phase2a-h1-level-a-evidence-e3a02fd
```

---

## 0. 结论（三层分开陈述）

| 层级 | 结论 |
|---|---|
| **事实**：A1 的建模缺口 | **成立**。A1 的 $N_i$ 与实际 Native victim set 不等价，可量化（§2） |
| **代理模型比较**：该缺口是否造成模型损失差异 | 均匀 $q$ 下 **0/111**；deadline 代理 $q$ 下 48/111，平均 **0.0016 块**（§4） |
| **实际 Native 收益** | **未测**。本语料无 `aggregate_recomputed_tokens`，本文不作任何 token 结论 |

在此范围内：**ERC/MUS 在该语料与当前 proxy 模型下未显示优势**。
这**不**等于"Entry-level 优化空间为零"；是否继续投入应由 §7 的有效证据决定，而不是由本文的离线最优性决定。

---

## 1. 上一版的三个错误（已修正）

| 错误 | 上一版 | 本版 |
|---|---|---|
| **重放语义（RC1）** | 自写"最低分优先"顺序贪心，丢弃了 per-unit / pair-lookahead / deadline-fallback 分支 | 直接调用 `A1EntryCostAwareStrategy` + `replay_decision`，完整梯子 |
| **决策计数** | 每个 run 目录只取**最后一个** `FORCED_RELEASE_DECISION`，得 90 | 用 `load_decision_snapshots`，得 **123** |
| **损失口径（RC2）** | 把 candidate `block_ids` 顺序当作内容深度 | 深度只来自 `a2_evidence.prove_chain` 的**已验证**内容链 |

第一条影响所有数字：上一版"48/48 分支不可见"，本版实际分支使用为
`single_step 123 / per_unit 78`（per-unit 是 A1 的主要路径之一，旧脚本完全没有）。

---

## 2. 事实层：缺口是真实的

`src/kvopt/continuum/selection.py`：

```text
virtual_eligible_order = sorted(eligible, key=(eligibility_tier, native_lru_rank))
selected               = virtual_eligible_order[:target]
```

A1（`a1_entry.py`）：

```text
N_i    = |newly_eligible_after(i)|
Rhat_i = q_i * [ min(need, N_i) + λ * (N_i - min(need, N_i))^+ ]
```

$N_i$ 数的是「有多少块从受保护变成可回收」，**不读 rank、不区分 tier、不含实际淘汰谁**。

`a1_structural_gap.py` 的两个反例：

- **反例一**：`target = 3`，队列前 3 块 hashless ⇒ 目标已满足，释放 `e` 不改变淘汰集，
  真实重算 **0.0000**，A1 计费 $q_e N_e = 2.7000$（与 $q$ 无关）；
- **反例二**：两 entry 的 $N_i$ 同为 1，真实损失 **1.5000 vs 0.5000**，A1 评分同为 0.5000。

> 事实层结论：**A1 的代价量与代价函数依赖的量不是同一个**。此结论不依赖任何语料。

---

## 3. RC1：严格重放冻结 A1

复用仓库既有语义，不重写策略：

```python
strategy = A1EntryCostAwareStrategy()
outcome  = replay_decision(snapshot, strategy, rows)   # 完整梯子
```

**Gate**：重放通路自身必须先通过对 A0 的复现检验，否则整份分析作废：

```text
raw_runs                 136
snapshots                123
a0_decisions_compared    123
a0_set_match_rate        1.0      <- ExecutedP1BStrategy 精确复现观测 A0
a0_sequence_match_rate   1.0
```

A0 保真度 123/123 证明「事件 → snapshot → 淘汰」这条通路正确。
A1 自身在本语料**没有 selection trace**（这是 A0 语料），因此逐决策一致性只能通过
「梯子可复算 + 分支可枚举」保证，而不能与 A1 的实跑 trace 对比——这一点如实记录。

分支使用：

```text
single_step   123        <- 每决策第一步都走 single-step 分支
per_unit       78        <- 78 个决策的后续步骤走 per-unit 分支
pair_lookahead  0
deadline_fallback 0
```

> `per_unit` 出现 78 次，而这在上一版的简化贪心中完全不存在。这正是 RC1 指出的问题。

---

## 4. RC2：五个量分开

| 量 | 定义 | 本文字段 |
|---|---|---|
| (1) 新增可回收块 | `ReplayState.newly_eligible_after` 的差 | 用于复现 A1 的 $N_i$ |
| (2) 实际 Native victim 块 | `(eligibility_tier, native_lru_rank)` 前 `target` 个 | `victim_ids()` |
| (3) 已验证内容链深度 | `prove_chain` 证明的 `(chain, depth, hash)` | `VerifiedChain.depth_of` |
| (4) proxy 加权模型损失 | $\sum_c q_c (m_c - j_c + 1)$，$j_c$ 取自 (2)∩(3) | `model_loss()` |
| (5) Native 实际重算 token | `aggregate_recomputed_tokens` | **本语料无此数据** |

要点：

- **深度不取自 candidate `block_ids` 顺序**。深度来自 `prove_chain`
  （最新前序快照 + 有序 `block_ids` 相等 + 完整载荷 + 同进程无介入淘汰），
  与 A2 阶段使用的是同一套身份证明。
- **本语料 123/123 决策的全部候选链均可证明**，因此 (3) 无缺口；
  某个决策若触及未验证链，`model_loss()` 返回 `None` 并被排除，而不是按零记。
- **(4) 不换算为 token**，也不作为 token 上下界。$q$ 未校准、$L$ 为加权块单位、
  实测存在部分命中（`loss == 16×block_count` 仅 159/207）——这三个理由已在 PR #69 定性。
- **初始 eligibility** 由冻结规则决定（hashless 恒可回收；hashed 需全部 owner 已释放），
  并经 A0 保真度校验间接确认与观测一致（123/123）。

---

## 5. RC3：有效决策记账与比较

```text
replay-valid decisions              123
content-verified decisions          123
decisions compared against best     111
undecidable: too_many_candidates_to_enumerate  12
```

（12 个决策的候选数超过枚举上限 8，未能穷举替代方案，标为不可判定，不纳入统计。）

### 5.1 比较结果

| 权重口径 | A1 差于最优 | A1 优于最优 | 平均 (A1 − best) | 最大 (A1 − best) |
|---|---:|---:|---:|---:|
| **均匀 $q$（结构效应）** | **0 / 111** | 0 | **0.000000** | 0.000000 |
| **deadline 代理 $q$** | **48 / 111** | 0 | **0.001557** | **0.020617** |

结论分为两层：

1. **结构层**：均匀权重下 A1 在 111/111 决策上与最优可行集**损失完全相同**。
   缺口（§2）真实存在，但不改变模型损失。
2. **权重层**：用真实 deadline 代理 $q$ 后，48/111 决策存在更优集合，但平均差距
   **0.0016 块**、最大 0.0206 块。

典型例子（`h1-f1-draw-06-seed-101`，target=32）：

```text
A1   释放 1 个 entry                      -> 2.4741
最优 释放 2 个 entry（多释放 h1-agent-1） -> 2.4731     差 0.0010
```

基数分布（111 个可比较决策）：

| 情形 | 数量 |
|---|---:|
| 与最优同为基数，损失相同 | 63 |
| **与最优同为基数，损失更差** | **39** |
| 比最优少释放一个 entry | 9 |

⇒ 「多释放换微小改善」只解释 9/48；**其余 39 例在相同释放数下仍然更差**。
这削弱了上一版「最优解需要多释放所以不是真优」的辩解，也说明缺口在相同基数内
确实存在模型损失差异——只是均值为 0.0016 块。

### 5.2 不可比较的部分

| 原因 | 数量 |
|---|---:|
| 候选数超过枚举上限 | 12 |
| 缺少已验证内容链 | 0（本语料全部可证） |
| 缺少 (5) native 实际 token | 全部 123（本语料不含该指标） |

> 因此本文能回答的是「**模型损失**上 A1 是否落后」，不能回答「**真实重算 token** 上
> 入口层是否还有空间」。后者需要 A1 vs 其他策略的 paired native 测量。

---

## 6. ERC / MUS 的重新限定结论

按 RC3，不能再说"已被否证"，应说：

| 候选 | 原判据 | 本语料实测 | 限定结论 |
|---|---|---|---|
| **ERC**（以实际淘汰集为代价） | 同 relief 不同淘汰集需产生**模型损失**差异 | 均匀 $q$ 下差异为 **0** | 在该语料与均匀权重下**未显示优势**；deadline 权重下差异存在但均值 0.0016 块 |
| **MUS**（极小释放集） | 基数差异需产生损失差异 | 最优集与 A1 **同基数**者 102/111，少释放者 0 | 在该语料下 A1 **并未过度释放**；MUS 的前提不成立 |

**因此：`INCONCLUSIVE`** —— 不是"方向无效"，而是"该语料 + 该 proxy 模型不足以判定"。

$\lambda$ 敏感性的结论保持不变（合成探针）：0/0.5/1.0 → 1.6174 / 1.6408 / 1.7042，
非单调且差异极小；这支持「问题是 $N_i$ 不是代价，而非 $\lambda$ 取值」，但不构成否证。

---

## 7. 需要什么证据才能决定是否继续 ERC/MUS

M1 的问题应由有效证据回答。按当前缺口，最小证据集是：

1. **A1 的 selection trace 与在线事件同源**：本语料没有 A1 trace，只能离线复算。
   若存在 A1 实跑语料，应先用它做逐决策一致性检验（本版已留出接口）。
2. **entry 释放的资源代价进入目标**：9/48 例最优解需多释放一个 entry。
   若该代价不建模，这 9 例的「更优」就不是真实更优；
   但另 39 例同基数仍更差，这一部分不依赖该建模。
3. **paired native 测量**：本语料无 `aggregate_recomputed_tokens`，
   任何 token 层结论都必须另行测量。
4. **更大候选集的决策**：12/123 已超出枚举上限；真实压力决策的候选数可能更大，
   需要可扩展的替代方案生成，而不是穷举。

**在这些证据到位前，不建议实现 ERC/MUS**；也不建议据本文宣称 Entry-level 空间为零。

---

## 8. 与 A2 的关系（保留但不扩大）

A2 阶段的结论仍然成立且有价值：更精细的代价函数本身不产生收益。
本报告在 §5.1 观察到相同形态——**结构层差异为 0，权重层差异为 0.0016 块**。

但本文**不**把 A2 的结论外推为「Entry-level 空间为零」：
A2 测的是 block 层，本报告测的是 H1 语料上的模型损失，
两者都不能替代 A1 在真实 Native 负载上的 paired 测量。

---

## 9. 边界声明

- 语料：`local/phase2a-h1-level-a-evidence-e3a02fd`，136 run / **123** 个 forced-release 决策。
  不是 A2 bounded evaluation 语料，两者不可混算。
- A0 保真度 123/123 是本报告的前置门；未通过则分析作废。
- (3) 内容深度全部来自 `prove_chain`，本语料 123/123 可证。
- (4) 为 proxy 加权模型损失，**不换算 token、不作 token 界**。
- (5) native 实际重算 token **未测**，本文不对其作任何断言。
- 合成探针（477/3000 次优）与真实语料（均匀 $q$ 下 0/111）的差异原因见 §1 与 §5：
  合成生成器赋予差异很大的 $q$ 且随机打乱 rank，真实语料不产生该几何。以真实语料为准。
- 未修改 `src/`，未运行 Native，未实现 A3，未改 workload，未动 A1/A2 代码与结果。
