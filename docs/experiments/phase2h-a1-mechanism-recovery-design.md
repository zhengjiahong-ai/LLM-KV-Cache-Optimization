# Entry-level Cost-Aware 机制恢复与改进设计建议

**分支**：`design/phase2h-a1-history-rich-recovery`
**阶段**：History-Rich Native Replay 机制恢复研究（算法机制与研究层面）
**边界**：本文只做分析与设计。未修改冻结 A1/A2，未新增 λ/N 语义，未启动 Campaign，未提交 A1+ 实现。
**配套脚本**：`scripts/probes/entry_costaware_audit/history_recovery_analysis.py`（只读，可复现全部数字）

---

## 0. 结论摘要

1. 当前 A1 的失效不是单一原因，而是**四条相互独立的阻塞**，其中只有第一条是 M6 可以靠加历史解决的。
2. **本轮最重要的新发现：解除 Cold-start 不会让 q 获得区分度。** 用真实冻结算法 `ttl.estimate_ttl`
   在 18 个真实 A1 多候选决策上重算，经验 TTL 中位 **0.347 s**，由此引起的 q 变化中位仅 **+1.7e-3**
   （最大 +3.0e-3），q 的排序改变 **0 / 18**，argmin 改变 **0 / 18**。原因可写成一条不等式（§2.3）。
3. 因此"M6 提供更多历史 → q 变好 → A1 有收益"这条链条**在第二环就断了**。
   历史机制门禁通过之后，q 仍然由 elapsed 决定。
4. 真正缺的是**与 elapsed 独立的、在候选之间有变异的复用信号**；现有数据中唯一结构上满足这个定义的量是
   **"该 Entry 被逐出后是否被重新请求"**，而当前所有负载都不产生这种事件（首轮之后 180/180 全命中）。
5. 评分结构在**所有候选都 sufficient** 时退化为 q 排序（本数据集 18/18），λ 在此完全不起作用
   （λ ∈ {0, 0.25, 0.5, 1} 的 argmin 改变均为 0/18）。这是 `q × N` 的形式问题，不是调参问题。

---

## 1. 当前 A1 的主要失效原因及其证据

按"能否由 M6 解决"排序，四条互不替代。

### 1.1 阻塞一：历史机制不可达（M6 可解）

| 事实 | 值 | 来源 |
|---|---|---|
| 每 run 可产生的 server gap | `REQUEST_ARRIVED − PROGRAM_STARTED` = 216 − 36 = **180 / 18 runs = 10 / run** | v10 A1 臂事件计数 |
| 冻结阈值 | **100** | `continuum/config.py` `duration_history_threshold` |
| 因此 TTL 模式 | **恒为 `COLD_START`** | `ttl._select_history` |
| 归档是否记录 gap 样本数 | **否**：`TTL_HISTORY_INPUT_OBSERVED` 只有 eta 与 queue-delay 计数（180/180 全为 0） | 事件 payload |

所以 10 这个数字是**由事件计数推出**的，不是从归档读到的。这一点本身是 M6 的观测缺口（§5.1）。

### 1.2 阻塞二：**解除 Cold-start 后 q 仍然退化**（M6 不可解，本轮核心）

这是本轮唯一的新机制发现。做法：把 W1-A 的 443 条真实 gap 注入 `TTLInput`，
调用**冻结实现** `estimate_ttl(..., duration_history_threshold=100)`，得到该 run 会选的 TTL，
再按 `deadline = ttl_decision + ttl` 重算 q。

| 项 | 结果 |
|---|---|
| 历史来源 | W1-A，**443** 条，中位 0.2799 s，p90 0.3638 s |
| 样本数 > 阈值 | 是（443 > 100），**不再是 COLD_START** |
| `next_tool_type` = `observed-agent-gap` 在 W1-A 中的样本 | **0 条** → 模式是 `GLOBAL`，`TOOL_SPECIFIC` 仍不可达 |
| benefit `B = queue_delay·η + prefill_reload` | 0.2254 / **0.8934** / 1.4392（min / 中位 / max） |
| 经验 TTL（真实代码算出） | 中位 **0.3474 s**，范围 0.0157 – 0.3653 |
| 由此产生的 q 变化 | 中位 **+1.662e-3**，最大 **+3.044e-3** |
| 理论上界 `B/(4τ)` | **0.012** |
| **q 排序改变** | **0 / 18** |
| **argmin 改变** | **0 / 18** |

注：`prefill_reload` 必须取 `FORCED_RELEASE_DECISION` 候选里的**真实记录值**。
`selection_trace` 里的 `per_unit × new_blocks` 是加权块单位的 `expected_recompute`，
不是秒数；早期版本误用它做 B，已修正。

结论明确：**历史满足条件之后，q 的排序一动不动。**

### 1.3 阻塞三：q 与 elapsed 是同一个量（M6 不可解）

在 47 个带 trace 的候选行上验证：

```text
max |sigmoid((deadline − t)/τ) − 记录 q| = 0.000e+00
Spearman(elapsed, q)                     = −1.000000
```

`COLD_START` 下 `ttl = default_ttl_seconds` 是启动常数（v10 的记录值为 `0.0`），
所以 `deadline = TTL 决策时刻`，`q = sigmoid(−elapsed/τ)`。
**q 不是"较弱的复用信号"，它就是 recency 本身。**

### 1.4 阻塞四：评分在所有候选 sufficient 时退化为 q 排序（M6 部分可解）

18 个真实多候选决策：

| 项 | 值 |
|---|---|
| 每决策 sufficient 候选数 | **2 / 2（18/18 全部）** |
| `N_i` max/min 中位 | **1.53** |
| q 决策内跨度中位 | **0.441** |
| λ ∈ {0, 0.25, 0.5, 1} 的 argmin 改变 | **0 / 18** |

当所有候选都 sufficient 时，`min(need, N_i) = need` 对每个候选相同，
括号内只剩 `λ(N_i − need)`，而 `N_i` 的离散度只有 1.53×，远小于 q 的跨度。
**λ 在这个区间里几乎不参与决策。** 这也解释了此前 λ 消融"27 个无关、2 个改变"的结果。

### 1.5 补充：`N_i` 的语义本身不等同于重算代价

单个决策的实例（`g01-short-extreme-deep-a1-repeat-1`）：

| 量 | 值 |
|---|---|
| `required_blocks`（need） | **128** |
| 候选 A `django__django-13569` 的 `new_blocks` | **1620** |
| 候选 B `psf__requests-2931` 的 `new_blocks` | **200** |
| 实际释放的 `newly_eligible` | **200**（即不选 A） |

`N_i` = 释放该 Entry 后**新增 eligible** 的块数。它既不是物理逐出的块数，也不是会被重算的块数：
- 新增 eligible 之后，由 native 压力路径决定哪些真的被逐出（本 run 共 1084 次 `BLOCK_EVICTED`）；
- 被逐出的块只有在之后被重新请求、且 APC 未命中时，才产生重算。

---

## 2. 解除 Cold-start 后应当出现的可验证机制变化

### 2.1 应当出现（正向判据）

| # | 可验证变化 | 判据 |
|---|---|---|
| 1 | 历史样本数越过阈值 | `TTL_HISTORY_INPUT_OBSERVED` 中新增的 gap 计数字段 > 100 |
| 2 | 模式改变 | `mode = GLOBAL`（或 `TOOL_SPECIFIC`，若同 tool 标签样本 > 100） |
| 3 | TTL 不再恒为 0 | `ttl_seconds > 0`，且在同一 run 内随候选变化 |
| 4 | TTL 值由真实历史决定 | 手动重算 `_choose_empirical_ttl` 能与记录值一致 |
| 5 | 决策时实际使用了新 TTL | 同一 Entry 的 `deadline` 与 `ttl_decision + ttl` 一致 |

### 2.2 **应当不出现**（本轮的可反驳预测）

这一条比正向判据更重要，因为它直接检验 §1.2 的机制判断。

> **预测：解除 Cold-start 之后，q 的决策内跨度变化 < 0.012，q 的排序改变 0 次，A1 选择改变 0 次。**
> 实测（用 W1-A 历史注入冻结算法）为：Δq 中位 +0.0017、最大 +0.0030，排序与 argmin 均 0/18。
> 若 M6 的新 replay 出现明显不同的结果，则说明我对 TTL → q 的机制建模有误，需优先复核。

### 2.3 为什么可以给出这个预测（可写成不等式）

TTL 由 `_choose_empirical_ttl` 选出：

$$\text{ttl}^\*=\arg\max_{t\in\{0\}\cup\text{samples}}\big[\mathrm{CDF}(t)\cdot B-t\big],\qquad B=q_{\text{queue}}\cdot\eta+\text{prefill\_reload}$$

因为 `score(0) = 0`，要取正值必须 `CDF(t)·B > t`，故**必然 `ttl* < B`**。而

$$q=\sigma\!\left(\frac{\text{ttl}-\text{elapsed}}{\tau}\right)\Rightarrow|\Delta q|\le \frac{|\Delta\,\text{ttl}|}{4\tau}<\frac{B}{4\tau}$$

本数据中 `B = queue_delay·η + prefill_reload ≈ 0.893 s`（中位；`queue_delay = 0`，`η = 1`），`τ = 30 s`：

$$|\Delta q| < \frac{1.4392}{120} = 0.0120$$

与实测最大值 0.00304 一致（实测更小，因为 sigmoid 在该区间未饱和）。
**要让 |Δq| 达到 0.1，需要 `B ≈ 12 s`**，也就是 `queue_delay·η ≈ 10 s` 量级的排队延迟。

> 推论：**TTL 通道要影响 q，需要严重拥塞；当前负载的 prefill-only benefit 注定它只能产生 <1.2% 的扰动。**
> 这条是给 M6 的量化设计条件，不是建议调参。

---

## 3. q 可引入的最有价值的一至两个信号

先排除（本轮及此前已证）：

| 候选信号 | 结论 | 依据 |
|---|---|---|
| E1a 命中率 | 在 47 个带 trace 的候选行上**恒为 1.0** | 负载首轮后 180/180 全命中 |
| E1b hash-LCP 复用率 | **恒为 1.0** | 每 program 内容固定，哈希链恒等 |
| E1c 复用块数 | 就是前一次块数 → 与 N 共线 | H1 495 对 |
| E6 prefix 增长速率 | v10 由 materializer 给定，H1 恒为 0 | 无实测变异 |
| Server gap history | 只能改 TTL 量级，而 TTL < B < 12 s 时对 q 无影响 | §2.3 |

### 3.1 首选信号：**逐出后重取率（per-entry eviction → refetch rate）**

定义：对 Entry *i*，在历史中"曾被逐出"的周期里，统计其后被再次请求的比例

$$r_i=\frac{\#\{\text{evictions of } i \text{ followed by a re-request}\}}{\#\{\text{evictions of } i\}}$$

为什么是它：

1. **它就是 q 想代理的那个量。** 现行 q 估的是"未来会不会被用"；`r_i` 直接测"上次被逐出后有没有被用"。
2. **与 elapsed 独立。** 它按周期计数，不读时间戳；§1.3 的共线性问题不适用。
3. **变异来自真实负载。** 只要负载真的"逐出→重取"，`r_i` 天然在 [0,1] 上有分布；
   而现有负载从不 miss，所以 `r_i` 恒无定义——这正是"需要一个会丢内容的 workload"的原因。
4. **可归因。** 它的取值可以被 M6 的逐出/重取证据逐条核对，不需要信任模型。

需要的新观测：**每个 Entry 的逐出事件，以及随后同一 prefix 是否被再次请求**（§5.1 第 6 项）。

### 3.2 次选信号：**queue delay history（已有通道，缺数据）**

`_choose_empirical_ttl` 的 benefit 里已含 `queue_delay·η`，且 queue delay 在拥塞时可达秒级。
它是**唯一能在不新增代码的前提下把 benefit 抬到 10 s 量级的通道**，
从而让 TTL 真正影响 q（§2.3）。

- 优点：零实现成本，已有 `queue_delay_t_seconds` 与 `queue_delay_history_sample_count`；
- 限制：它是 TTL 通道，不是独立于 elapsed 的复用信号；只解决"q 的取值分布太窄"，不解决"q 只在测 recency"。

> **不推荐的信号**：Program 轮次/进度、工具类型、上下文长度。
> 前两者在决策时确实可用，但与 elapsed 强相关（任务越久，轮次越多）；
> 后者与 N 共线。加入它们等于给已有轴再加权，无法通过"独立信息"检验。

---

## 4. `q × N` 评分中最值得修正的结构性问题

按"值得改 / 改动小 / 可归因"排序。

### 4.1 问题一：λ 是**全局统一**的 overshoot 单价

$$R_i=q_i\big[\min(\text{need},N_i)+\lambda\max(0,N_i-\text{need})\big]=q_i\big[\lambda N_i+(1-\lambda)\min(\text{need},N_i)\big]$$

括号对 `N_i` 是仿射的，斜率恰为 λ。含义是：**每一块超额释放都按同一价格收费，
不管这一块是否可能被复用。** 这与代价的真实结构相反——超额释放的代价取决于它所在链的复用概率。

### 4.2 问题二：全部 sufficient 时评分退化为 q 排序

`min(need, N_i) = need` 对每个候选相同 ⇒ 排序主要由 `q_i` 决定（§1.4：18/18，λ 全不生效）。
这不是 λ 取错，而是**括号里缺少真正的代价项**：`N_i` 只是块数，不是代价。

### 4.3 问题三：`N_i` 被当成"需要重算的块数"

必须分开的四个量（§1.5 已给实例）：

| 层 | 量 | 本数据中的关系 |
|---|---|---|
| 1 | Entry 解除保护（release） | 每个决策释放 1 个 Entry |
| 2 | **新增 eligible blocks `N_i`** | 200 / 1620（候选间 8.1×） |
| 3 | **真实物理 eviction** | 由 native 压力路径决定，本 run 1084 次 |
| 4 | **最终重算损失** | 仅当被逐出块之后被重新请求且 APC 未命中 |

`N_i` 只在第 2 层。把第 2 层当第 4 层用，是"成本代理不准确"的确切位置。

### 4.4 值得保留的部分

- `Sufficient-first` 的语义是对的：`min(need, N_i)` 保证"先满足压力需求"计满、超额部分打折。
- `Earliest Deadline` 与 `Minimum Overshoot` 分别覆盖了 q 轴与 N 轴的两个极端，
  因此**不要把 A1 改成它们的组合**，否则无法归因。
- λ=0 与 λ=1 的边界已明确：λ=0 ⇒ 只按 q 排序（`q·need`，常数因子）；λ=1 ⇒ 按 `q·N`。
  两者都是同一族的端点，不是不同算法。

---

## 5. 对 M6 的观测要求与验收判据

### 5.1 机制观测清单（必要，缺一项则该门禁不可判定）

| # | 观测项 | 字段要求 | 现状 |
|---|---|---|---|
| 1 | Server gap 样本数与来源 | `global_server_gap_sample_count`、`tool_server_gap_sample_count`、`provenance` | **缺**（只有 eta / queue 计数） |
| 2 | TTL 模式 | `TTLDecision.mode`、`reason` | **缺** |
| 3 | 每候选输入与分数 | `q_i`、`N_i`、`need`、`λ`、`score_i`、`deadline_i`、`ttl_i`、`ttl_decision_ts` | **已有**（`selection_trace`） |
| 4 | 多候选决策及分歧 | 与 A0 / Sufficient-first / Earliest-Deadline / Min-Overshoot 的选择对比 | **部分**（仅 29/600 带 trace） |
| 5 | 每次 pressure release 的新增 eligible | `newly_eligible_block_ids` 计数 | **已有** |
| 6 | **逐出 → 重取证据** | 每 Entry 的 eviction 事件 + 之后同 prefix 是否被再请求 + APC 命中与否 | **缺**（决定 `r_i` 能否计算） |
| 7 | 物理逐出与重算 | `BLOCK_EVICTED`、`native_cached_prefix_tokens`、重算时长 | 部分 |

**必须补齐第 1、2、6 项。** 没有 1、2，历史机制门禁无法判定；没有 6，首选信号无法计算。

### 5.2 两个门禁（M1 要求区分）

**门禁 H（历史机制门禁）** —— 算法是否获得了真实可用的复用历史

| 判据 | 通过条件 |
|---|---|
| H1 | 至少一个决策的 `global_server_gap_sample_count > 100` |
| H2 | 该决策 `mode != COLD_START` |
| H3 | 该决策 `ttl_seconds` 与 `default_ttl_seconds` 不同 |
| H4 | 用记录的历史手动重算 `_choose_empirical_ttl`，与记录值一致（±1e-9） |
| H5 | 该 Entry 的 `deadline = ttl_decision_ts + ttl` 在其 trace 中成立 |

**门禁 D（决策机会门禁）** —— 算法是否真正存在多个有意义的合法选择

| 判据 | 通过条件 |
|---|---|
| D1 | ≥2 个候选通过 legality 检查 |
| D2 | 候选间 `score` 前两名差距 < 2×（否则选择被强制，无机会） |
| D3 | 至少一个决策与 Sufficient-first 或 Earliest-Deadline 的选择**不同** |
| D4 | 与 A0 的选择存在分歧（记录，不强求） |

**两个门禁的关系（必须写进结论）**：
- H 通过、D 不通过 → 说明历史恢复了但负载没有选择机会，**不能**据此判定算法有效或无效；
- H 通过、D 通过、A1 选择未变 → 必须能解释"为什么没变"（本轮已给出可检验的解释：TTL < B，`|Δq| < B/4τ`）；
- H 不通过 → 后续任何结论都只关于 cold-start 行为，不能推广。

**明确不要求 A1 产生收益才通过门禁。** 门禁检验的是机制是否成立、行为是否可解释。

### 5.3 建议的 Smoke 失败条件

以下任一条出现即应停止并复核，而不是继续加 run：

1. 出现带 trace 的决策，但 `q` 与该 Entry 的 `deadline`、`ttl` 不自洽（机制记录错误）；
2. `mode != COLD_START` 但 `ttl_seconds` 仍与 `default_ttl_seconds` 相同（历史未真正参与）；
3. 决策的 `need` 与 `sum(newly_eligible)` 关系无法复现（`N_i` 口径漂移）；
4. 负载在首轮之后仍 100% 命中（则 `r_i` 与 E1a 都无定义，Smoke 对问题的检验力为零）。

---

## 6. 后续算法改进的首选方案与备选方案

### 6.1 首选：**A1+ v1 —— 只把 λ 变成逐候选估计**

保留 `q` 与 `N` 的现有语义与形状，只把**全局常数 λ 换成逐 Entry 的 `λ_i`**：

$$R_i=q_i\Big[\min(\text{need},N_i)+\lambda_i\max(0,N_i-\text{need})\Big],\qquad \lambda_i=\hat r_i$$

其中 `r̂_i` 是 §3.1 的逐出后重取率（可用 Beta/拉普拉斯平滑避免 0/1 饱和）。

为什么选它：

| 优点 | 说明 |
|---|---|
| 最小改动 | 公式形状、`q`、`N` 语义、Sufficient-first 合规性全部不变 |
| 直接针对 §4.1 | 超额释放的单价改为"该 Entry 的复用概率"，而不是全局常数 |
| 可归因 | `λ_i` 与 `λ` 的差异是唯一变量；`λ_i ≡ λ` 时逐位退化为 A1 |
| 硬护栏自然 | 无逐出历史时 `λ_i = λ = 0.5`，A1+ 与 A1 逐位相同 |

**硬护栏**（必须写进实现契约）：`eviction_observations < k`（建议 k = 2）时 `λ_i = λ`。
这保证任何观测到的差异都只可能来自 `λ_i` 本身，满足 M1 的"可解释为何改变或不改变"。

**预期**：在现有负载上 `λ_i ≡ λ`（无逐出历史），所以 **A1+ v1 在 v10 上应当与 A1 逐位相同**。
这是它最重要的性质：**任何差异都必须在新的、会丢内容的 replay 上才出现。**

### 6.2 备选：**把代价项从块数换成预期重算秒数**

$$R_i=q_i\cdot\text{prefill\_reload}_i\cdot\Big[\min(\text{need},N_i)+\lambda_i\max(0,N_i-\text{need})\Big]$$

针对 §4.2/§4.3（`N_i` 不是代价）。但：

- 需要 §5.1 第 6、7 项的完整证据，成本高；
- 改变了"评分单位"（块 → 秒），会影响与 A0/A2 的可比性；
- 若首选方案已经在门禁 D 下产生可解释差异，则没有必要引入它。

**只有在首选方案在 H、D 双通过条件下仍不改变任何选择、且能证明原因是"代价项缺量纲"时，才启动备选。**

### 6.3 明确不做

- 不引入多信号特征组合或多参数评分（无法归因，且违反"不通过反复调参寻找正向结果"）；
- 不改 q 的 τ 去凑效果（τ 是冻结的设计尺度，改它等于换问题）;
- 不在 cold-start 未解除的数据上评估 A1+。

---

## 7. 复现

```bash
python scripts/probes/entry_costaware_audit/history_recovery_analysis.py
```

需要 `local/continuum-native-cost-aware-bounded-v10-final-evidence/`（v10 解包）
与 `origin/main` 上的 W1-A 历史文件（脚本用 `git show` 读取，因为该文件不在本分支）。
脚本只读；§1.2 的 TTL 反事实调用的是**冻结实现** `kvopt.continuum.ttl.estimate_ttl`，
不是复写公式。
