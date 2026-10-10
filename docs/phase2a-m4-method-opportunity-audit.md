# Phase 2A M4 — Method Opportunity Audit

Status: **AUDIT ONLY — no method proposed, no campaign requested, no implementation authorized**
Author: M4
Date: 2026-10-10
Baseline: `origin/main` @ `9a0cdff`

---

## 0. 范围与约束

本审计回答 M1 提出的核心问题：

> 已有证据证明了哪些 decision-time 信息具有意义？这些信息是否可能在**多 entry 竞争**条件下带来相对 Continuum baseline 的增量收益？

**约束（不越界）：**

| 项 | 保持不变 |
| --- | --- |
| 研究主线 | Cost-Aware KV Cache **Eviction / Victim Selection** |
| 决策粒度 | **logical retention entry** |
| 不重定位为 | TTL estimator optimization / scheduler optimization / physical block-level eviction |
| 不提出 | 完整算法、评分公式冻结、工程实现 |
| 不请求 | 新的 formal campaign、新的观测缝 |

**分类纪律。** 本文严格区分三类陈述，并在每一节标注：

```text
[事实]      已由封存证据或实现代码确立
[推断]      由事实推出的机制解释，尚未作为方法价值被验证
[假设]      待检验的研究假设，未经实验
```

⚠️ 任何标注为 `[假设]` 的内容**都不是结论**。

---

## 1. 证据来源与两条语料

本审计引用**两条不同语料**，必须分开读，因为它们的退化维度不同。

| 语料 | 规模 | 状态 | 关键退化 |
| --- | --- | --- | --- |
| **Discovery corpus**（Phase 2A M6 v5） | 54 runs / 60 decisions / 174 candidates | **已被 M1 归类为 DISCOVERY / CHARACTERIZATION DATA** | 成本仅 3 个取值；`eta` 与 `queue_delay` 全 campaign 各仅 1 个取值 |
| **H1 corpus**（独立 campaign） | 42 sealed draws（每族 7）→ 29 paired evaluable | **已闭合并封存** | 运行损耗 42→29；仅检验了 H1-R1 一条规则 |

**Discovery corpus 的定向结论不得直接沿用** —— §2.2 给出一条直接证据说明为什么。

---

## 2. 已验证事实

### 2.1 `[事实]` canonical loss 的结构

读取 `src/kvopt/profiling/loss_views.py::_return_weighted_prefill_evidence`：

```python
loss = candidate.prefill_reload_seconds if returned_within_horizon else 0.0
```

即 canonical proxy loss 是**两个因子之积**：

```text
loss = [该 entry 的 prefix 在 horizon 内被再次使用]  ×  C(prefix 长度)
```

这条是**结构性事实**，不是实验结果。它限定了任何规则的可改进空间：

> 规则只能通过「释放更可能**不**在 horizon 内返回的 entry」或「释放 $C(r)$ 更小的 entry」来降低 loss。

### 2.2 `[事实]` H1-R1 未复现，且**方向与 discovery corpus 相反**

| 语料 | 单位 | mean Δ（正 = 挑战者更好） | better/worse/tied |
| --- | --- | ---: | --- |
| Discovery corpus | raw 60 行 | **+0.014797** | 24 / 15 / 21 |
| Discovery corpus | 18 draws | +0.016086 | 8 / 3 / 7 |
| **H1 corpus** | **29 draws** | **−0.008328804890493039** | **13 / 14 / 2** |
| H1 corpus | CI | `[−0.035804, +0.017812]` | family 3/6 |

⇒ **符号翻转。** 同一条规则在两个语料上方向相反。

这条的意义超出「H1-R1 失败」本身：

> **discovery corpus 上的定向发现不具可迁移性。**
> 凡建立在该语料方向性结果之上的推断，都必须降级为「待重验」。

### 2.3 `[事实]` 真实 prefill 成本是非线性的

H2-M1 **PASS**。观测量为 `isolated_native_prefill_elapsed_seconds`（同步 native forward 执行，**非**端到端延迟）：

```text
每点重复 9 次；10,000 bootstrap，seed 20261007
delta_M1        = 0.19029591700382298 s
拟合增量         = 0.46337043935881883 s，q05 = 0.4407016205465704
gamma q05       = 8.880469562324095e-9 s/token²   （> 0）
```

⇒ **成本曲线在实测区间内确有曲率。** 这是 M1 层面的机制事实。

### 2.4 `[事实]` partial-prefix APC 语义成立

H2-M2 **PASS**：6 个 exact probe、54 次重复、对照有效。保留前导连续区间 + 淘汰尾部 ⇒ **仅后缀重计算**。

### 2.5 `[事实]` 淘汰位置改变**实际**重计算结果

H2-M3 **PASS**：**12/12 单元全部支持**，108 个 measured pair，每单元 9 次重复，无未解效应单元。

⇒ leading 与 trailing 在相同块数下代价不同。位置确实携带信息。

### 2.6 `[事实]` 单前缀受控比较中**不存在** block-level 额外 headroom

H2-M4 **FAIL**：12 单元、108 对、supporting cells = **0**、resolved headroom cells = **0**、**pairwise headroom = 0 tokens**。

M6 已冻结其适用边界：

> 仅适用于**冻结的 single-prefix controlled comparator**；不构成对所有 block-level 或多 entry 策略的否定。

### 2.7 `[事实]` 冻结基线的释放键

```text
_release_sort_key = (retention_deadline_timestamp,
                     min native LRU rank over NEWLY ELIGIBLE,
                     identity)
```

三个分量的性质：

| 分量 | 语义 | 与成本的关系 |
| --- | --- | --- |
| `deadline` | TTL 估计器输出（`timestamp + ttl_seconds`） | **间接**编码成本：discovery corpus 上 `prefill_reload ↔ deadline` = +0.938 |
| `min native LRU rank over newly eligible` | **新近度**摘要 | **与成本无关** |
| `identity` | 确定性 tie-break | 无 |

⇒ **基线的中间项是一个纯粹的新近度量，不含任何成本语义。** 这是基线中**最不 cost-aware 的部分**，且在本阶段**从未被挑战**（H1-R1 只反转了第一项）。

### 2.8 `[事实]` 基线在 H1 语料上可被忠实重放

H1 fidelity：release **set** 120/120、release **sequence** 120/120、marginal `initially_reclaimable` 471 字段匹配；6 个决策以 `too_few_candidates` 排除；**missing candidate = 0**。

⇒ 离线规则研究的基础设施是可靠的（这条支撑 §5 的离线前置检查可行性）。

### 2.9 `[事实｜discovery corpus，已被 §2.2 降级]` 早期定向结果

| 规则 | discovery corpus 结果 |
| --- | --- |
| size 簇（`prefill` / `block_count` / `initially_reclaimable`） | 与基线**逐决策同构**（0/0/60），消融同一率 1.000 |
| `M1_marginal_cost_per_reclaimable` | **净负面** 18/18/24，mean Δ = −0.002308 |
| `M2_non_code_first` | 零回归但收益**仅在 F1 一族**（族记忆化） |

⚠️ 这三条是 discovery corpus 事实。因 §2.2 已证明该语料的方向性不迁移，它们**只能作为弱先验**，不能作为排除依据。

---

## 3. 已被**排除**或**削弱**的方向

| 方向 | 状态 | 依据 |
| --- | --- | --- |
| **反转 / 取反基线排序** | **排除** | H1-R1 在独立语料上符号翻转且全部冻结判据未通过（§2.2） |
| **纯成本量级排序**（如按 `prefill_reload` 升序） | **强削弱** | discovery corpus 上与基线逐决策同构（§2.9）；且 §2.7 表明基线已近似成本序 |
| **尺寸 / 占用类特征作为判别维度** | **强削弱** | discovery corpus 消融同一率 1.000（§2.9） |
| **marginal cost per reclaimable** | **削弱，未排除** | discovery corpus 净负面；但该语料成本仅 3 个取值、`eta`/`queue_delay` 恒定，**使该检验本身信息量很低**。在修正了这两个退化维度的语料上**未被检验** |
| **单特征单调键作为规则形态** | **接近穷尽** | 上述三条组合覆盖了 discovery corpus 上大部分单维方向 |
| **block-level partial-prefix retention（B1）** | **LOCKED** | H2-M4 FAIL，在冻结比较器下无额外 headroom（§2.6） |

**一处必须澄清的边界：** §2.6 的 FAIL **不排除**「多 entry / 共享所有权 / 复杂压力条件下存在其他优化空间」—— M6 已明示该边界。B1 被锁的是**那条特定路线**，不是「block 位置信息永无价值」；§2.5 反而证明位置信息是**真实存在**的。

---

## 4. 仍存在的、尚未验证的优化机会

以下每条都给出：**基线实际怎么做** → **差在哪里**。这就是「与 Continuum baseline 的真正区别」。

### 4.1 `[推断]` 机会一：基线把「回收多少容量」当作新近度问题

- **基线做法**：用 `min native LRU rank over newly eligible` 在同等 deadline 下排序。
- **差在哪里**：该分量是**新近度**（哪块最旧），不是**收益**（这次释放能腾出多少容量、代价多少）。基线**从未把 loss 与 relief 联系起来**。
- **为何现在值得看**：§2.3 证明 $C(r)$ 有曲率 ⇒ 每多释放一块的边际成本**依赖位置与长度**，不同 entry 的「单位容量代价」可以显著不同。若成本是线性的，这个量对所有 entry 相同，该项无意义。
- **为何尚未验证**：H1-R1 只动第一项；§2.9 的 marginal-cost 检验发生在**成本只有 3 个取值**的语料上，几乎无法区分。

### 4.2 `[推断]` 机会二：loss 的返回因子在竞争中被隐性处理

- **基线做法**：返回倾向只通过 `deadline` 隐式进入 —— 而 deadline 是**单条 entry 的标量**，来自 `P(return ≤ t)·benefit − t` 的独立最优化。
- **差在哪里**：§2.1 的 loss 含**返回因子**，而基线在**多个 entry 之间**没有对返回可能性做**相对比较**。它比较的是各自的 deadline，而不是各自「谁更可能不返回」。
- **边界警告**：此方向**极易**滑向 TTL estimator optimization。必须严格限定为「在压力下选择受害者」，**不改变 `ttl_seconds` 的计算**。若某做法会改变 TTL 估计，即越界。
- **为何尚未验证**：discovery corpus 上唯一可用的生命周期信号 `next_tool_type=code` 的收益只在单族出现（§2.9），且该语料 `eta`/`queue_delay` 恒定。

### 4.3 `[推断]` 机会三：共享所有权未被当作决策变量

- **基线做法**：每次释放一个 entry；对块是否被**多个 entry** 共同拥有没有概念。
- **差在哪里**：释放一个被多 entry 共享的块，**一次**即可同时降低多个 owner 的复用能力 —— 这是单 entry 视角看不到的聚合代价。基线对此完全不可见。
- **状态**：H1 的 F6 **作为场景维度**覆盖了 shared ownership，但**没有任何规则把它作为决策变量**。因此这是三者中**最接近「完全未检验」**的一条。
- **已知约束**：绝不可触碰 `ref_cnt`；所有权信息只能停留在策略内部。

### 4.4 机会与基线差异总览

| 机会 | 基线实际使用的量 | 基线**未**使用的量 | 是否与 §2.2 的失败同源 |
| --- | --- | --- | --- |
| 一：容量归一化代价 | `min native LRU rank`（新近度） | relief 量 × $C(r)$ 的单位代价 | **否** —— 换了决策变量，不是符号翻转 |
| 二：返回因子的相对比较 | 单 entry 的 `deadline` 标量 | 竞争 entry 之间的返回倾向对比 | **否** —— 但需严防越界成 TTL 优化 |
| 三：共享所有权聚合 | 无 | 共享块的跨 owner 聚合代价 | **否** —— 基线完全未表达 |

---

## 5. 最值得进一步验证的假设

按「机制依据强度 × 可证伪性 × 与基线差异清晰度」排序。**以下两条均为 `[假设]`，未经任何实验。**

### 5.1 HYP-A（首选）：容量归一化的边际释放排序

```text
[假设] 在满足同一压力目标的前提下，按「每个 entry 释放后能新增的可用容量」
       对「预期重计算损失」的比值排序，优于按 (deadline, native LRU rank) 排序。
```

**与基线的真正区别**：基线在同等 deadline 下用**新近度** tie-break；本假设用**单位容量代价**。基线从不把 loss 与 relief 关联。

**为何不是 H1-R1 的翻版**：H1-R1 是对同一变量（`deadline`）取反 —— 一个保序变换的符号翻转。本假设**更换决策变量**，且**专门利用 §2.3 的非线性**：若 $C(r)$ 线性，则 `C(r)/blocks` 对每个 entry 相同，该规则退化为成本序，可预测为 null。

**可能否定它的观测（先做便宜的）：**

| # | 观测 | 若成立则 |
| --- | --- | --- |
| F-A1 | 决策内各 entry 的 `newly_eligible_block_count` 几乎无离差 | 比值退化为每一项相同的常数 ⇒ 与成本序同构 ⇒ **预期 null** |
| F-A2 | 决策内实现到的 $C(r)$ 取值分辨不足（类似 discovery corpus 的 3 个取值） | 单位代价无法区分 entry ⇒ **预期 null** |
| F-A3 | 独立语料上 family agreement < 2/3 | 族记忆化 ⇒ **否决** |
| F-A4 | 独立语料上 mean Δ ≤ 0 且 95% CI 含 0（≥30 draws） | **否决** |

⚠️ **必须同时记录的弱先验**：`M1_marginal_cost_per_reclaimable` 在 discovery corpus 上是净负面的（§2.9）。本假设是**在修正了该语料两个退化维度之后的重述**，不是新想法。诚实的说法是：「一个已知的弱先验，但其原始检验信息量很低」。

### 5.2 HYP-B（次选）：竞争条件下的返回因子相对比较

```text
[假设] 在多个 entry 竞争时，用可在线获得的返回倾向代理，
       偏好释放「更不可能在 horizon 内被复用」的 entry，同时受成本约束。
       不改变 TTL 估计器本身。
```

**与基线的真正区别**：基线的返回信息被封进**单 entry 标量** `deadline`，条目之间比较的是 deadline；本假设要求比较**返回倾向本身**。

**越界警告（必须写进任何后续 preregistration）**：若某实现会改变 `ttl_seconds`，则它属于 TTL estimator optimization，**超出本研究主线**，不得以此名义提出。

**可能否定它的观测：**

| # | 观测 | 若成立则 |
| --- | --- | --- |
| F-B1 | 决策内各 entry 的返回标志几乎恒定 | 该因子无法区分 entry ⇒ **预期 null**（可离线先查） |
| F-B2 | 任何可在线字段对返回标志的判别力都不优于 `deadline` 单独 | 无增量信息 ⇒ **否决**（可离线先查） |
| F-B3 | 需要改动 TTL 估计器才能取得收益 | **越界**，退回主线外 |
| F-B4 | family agreement < 2/3 或 CI 含 0 | **否决** |

### 5.3 若两者都被否定

则本阶段的正确读法是：**在 logical-entry 粒度、当前 decision-time 信息集与当前 loss 定义下，相对 Continuum baseline 的增量空间未被找到。**

此时应当**明确记录为负面结果**，而不是继续在同一信息集上改进规则形态。是否需要新的决策时信号（新一轮观测缝）应由 M1 裁定，而不是由 M4 自行扩张。

---

## 6. 建议的下一步（不含新实验）

按最小成本、最强约束排序。**全部为离线或文档动作。**

| # | 动作 | 产物 | 前置裁定 |
| --- | --- | --- | --- |
| S1 | 把本文档作为方向评审材料交 M1 | 本文 | — |
| S2 | 对 HYP-A 做**可证伪性前置检查**：测量决策内 `newly_eligible_block_count` 的离差，以及可实现到的 $C(r)$ 区分度 | 一份 scoping 备忘 | **需 M1 裁定 G3**（能否以**诊断**目的读取已解封语料） |
| S3 | 对 HYP-B 做**代理可用性前置检查**：候选在线字段对返回标志的判别力 vs `deadline` | 同上 | 同 S2 |
| S4 | 仅在 S2/S3 显示假设**可证伪**时，才preregister 一条规则（冻结 formula / direction / tie-break / fallback / boundary / 双层 metric） | preregistration 记录 | 需 M1 批准研究方向 |
| S5 | 若需要新语料：由 M1 裁定语料来源（新 sealed 语料 vs 复用条件） | — | **需 M1 裁定 G1** |

⛔ 本审计**不**请求新的 formal campaign，**不**请求新的观测缝，**不**授权任何 runtime policy。

---

## 7. 需要 M1 裁定的开放事项

| # | 事项 | 影响 |
| --- | --- | --- |
| G1 | H1 的 42 个 sealed scenario 是否可用于**新**假设？ | 决定 S4/S5 是否需要新语料。若复用，须预先声明多重比较处置 |
| G2 | 新假设是否沿用同一冻结 acceptance 协议与既有绑定（`epsilon_latency` 等） | 决定 preregistration 的绑定字段 |
| G3 | M4 能否以**诊断**（非假设检验）目的读取已解封语料 | 决定 S2/S3 能否启动。这是**最关键的解锁项** —— 没有它，HYP-A 与 HYP-B 的证伪性无法在投入任何 campaign 之前评估 |
| G4 | 本文档提出的三个机会是否属于「Cost-Aware victim selection」主线 | 防止选题漂移；特别是机会二存在滑向 TTL 优化的风险 |

---

## 8. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| loss = 返回标志 × `prefill_reload_seconds` | `src/kvopt/profiling/loss_views.py::_return_weighted_prefill_evidence` |
| 冻结释放键与其中间项语义 | `src/kvopt/continuum/pressure.py::_release_sort_key` |
| H1-R1 数字、fidelity、missingness | `docs/experiments/phase2a-m6-h1/formal-level-a-review-submission.json` |
| H1 裁定与授权状态 | `docs/experiments/phase2a-m6-h1/formal-level-a-verdict.json` |
| H2 M1/M2/M3/M4 结论与数值 | `docs/experiments/phase2a-m6-h2/formal-final-verdict.json` |
| M2/M3 量级 | `docs/experiments/phase2a-m6-h2/formal-m2-m3-review-submission.json` |
| M1 观测边界（isolated native forward） | `docs/experiments/phase2a-m6-h2/README.md` |
| H1 语料维度设计（42 draws、每族 7、预声明变异） | `docs/phase2a-m6-h1-independent-campaign-design.md` |
| discovery corpus 的定向结果（size 簇同构、marginal 净负面、tool 仅 F1） | `docs/phase2a-m4-method-design-report.md` §5–§7 |
| discovery corpus 的退化维度（成本 3 个取值、loss 4 个取值、`eta`/`queue_delay` 各 1 个取值、9 个 unique decision pattern） | `docs/phase2a-m4-h1-evidence-request.md` §1.1–§1.4；`docs/phase2a-m4-rule-acceptance-protocol.md` §1.1 |
| acceptance 协议（单位、门槛、双层 metric） | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| 阶段裁定与封存链 | `docs/phase2a-h1-h2-closeout-verdict-record.md` |
