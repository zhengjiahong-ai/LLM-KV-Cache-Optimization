# Phase 2G Cost-Aware —— 综合研究判断报告 v2（修订版）

**输入**：PR #82 / v10 Evidence Archive（54/54 runs），PR #80（M2 四方向）。
**修订依据**：M1 对 PR #83 的 RC1–RC7。
**授权边界**：仅离线只读分析。未改 A0/A1/A2，未覆盖原始归档，未启动 Native。
**本轮不提出最终研究裁定，也不申请执行任何 Campaign。**

分析脚本（已入库）：`scripts/probes/entry_costaware_audit/`
运行前提：归档解压到 `local/continuum-native-cost-aware-bounded-v10-final-evidence/`（`local/` 被 gitignore）。

---

## 0. 对 PR #83 的更正（先列错误，再给结论）

上一版有三处**实质错误**，均由 M1 指出或本轮复核发现：

| # | PR #83 的说法 | 更正 | 依据 |
|---|---|---|---|
| 1 | `native_lru_victims` 是 `legal[:N]` 的回显，"独立参照不存在" | **错误。** 它由 `NativeLRUAdapter().select_victims()` 独立按 `lru_rank` 排序产生（`a2_native.py:543`、`adapter.py`）。两者相同是因为**候选本身按 rank 升序传入**，是一个经验事实而非构造性同义反复 | 源码 + 601/601 |
| 2 | 复用历史"全部为零"，"该 workload 永不产生历史" | **错误。** 历史**确实被产生与记录**（`ServerGapHistory.record`，约 10 条/run）。为零的是观测事件里暴露的 **eta / queue-delay** 计数器，我误当成全部历史。真正原因是**冷启动阈值 100 在 12 请求/run 的窗口内不可达**，且 history 是 per-process，不跨 run 累积 | §RC4 |
| 3 | 翻转判据 `q_ratio < N_ratio` 称为"充要条件" | **过强。** 那是 `λ=1` / `N≫need` 的极限形式。精确判据用 `a_i = λN_i + (1−λ)need` | §RC5 |

另外三处需要收窄：

- `ttl = 0` 属**设计内截断**（`μ = 1 s` 参考尺度），不是公式缺陷（§RC3）；
- 单次运行不能证明稳定退化（保留）；`physical_eviction_divergence` 仍建议弃用；
- 归档存在**具体的一处清单失配**，且 M1 公布的 SHA 在归档内**不存在**（§RC7）。

---

## 1. RC1 —— A2 与 Native-LRU 的正确解释

### 1.1 代码事实

`src/kvopt/costaware/a2_native.py::A2NativeBlockAdapter.select_victims`：

```python
native = tuple(NativeLRUAdapter().select_victims(candidates, context))   # 独立执行
...
else:
    selected = tuple(outcome.selection.blocks)                            # 代价路径
audit = A2NativeDecisionAudit(
    legal_block_ids=tuple(candidate.block_id for candidate in candidates),  # 传入顺序
    native_lru_victims=native,
    selected_victims=selected,
    ...
)
```

`src/kvopt/runtime/vllm/adapter.py::NativeLRUAdapter`：

```python
ordered = sorted(candidates, key=lambda candidate: candidate.lru_rank)
return [candidate.block_id for candidate in ordered[: context.required_blocks]]
```

因此 `native_lru_victims` **是一个独立计算的参照**，不是回显。

### 1.2 五个必须分开的量

| 层 | 量 | 本归档实测 |
|---|---|---|
| L1 | A2 vs **同 Legal Set 上的 Native Rank-LRU** | `selected == native` **601 / 601** |
| L2 | A2 vs **真正的 A0 Tier-aware 选择** | **无法可靠判定**（见 §1.4） |
| L3 | A2 是否**实际使用**代价打分 | **434 / 601 是**（`selector=incremental_greedy`, `cost_known=true`）；167 回退 |
| L4 | 代价打分是否**改变**最终 victim | **0 / 601** |
| L5 | 最终 victim 是否被 Native **物理执行** | 未验证（无逐块物理归因；`claim_boundary` 明确为 proxy 选择） |

### 1.3 601/601 一致的真正原因

`NativeLRUAdapter` 返回的是"按 `lru_rank` 升序的前 N 个"。它返回的序列恰好等于
`legal_block_ids[:N]`，**说明传入的候选序列本身已按 `lru_rank` 升序排列**。
这是一个关于 vLLM 候选传递顺序的**经验事实**，不是定义上的同一。

对 L3/L4 的含义是实质性的：

> 在 434 个决策中，**代价打分真实执行了**，输入通过契约校验，
> 而它产出的集合**恰好与 rank-LRU 相同**。
> 这不是"没有参照"，而是"代价模型在有输入、有执行的情况下没有产生差异"。

### 1.4 L2 无法判定的原因（保留上一版的这条限制）

要比较 A2 的 `legal[:N]` 与 A0 的 `(tier, rank)` 序，需要 legal 列表的排序依据。
归档没有记录该依据；队列快照只在 `FORCED_RELEASE_DECISION` 事件中出现：

```text
块决策总数                              601
可定位队列快照                          229
legal 中含快照里已不存在的块（快照过期）   151
严格可比（全部 legal 块都在快照中）          78
其中 legal 顺序 == (tier, rank)            71
其中 legal 顺序 != (tier, rank)             7
```

那 7 例呈 rank **降序**（如 202, 201, 200），与"快照过期"一致，不能当作真实排序依据。

> **结论**：L1 是确定的（601/601 相同），L2 **不可判定**。
> 因此"A2 与 A0 差异的来源"在本归档中**不能归因**，只能标 `NOT_ATTRIBUTABLE`。

---

## 2. RC2 —— A2 的有效决策机会（不再用 601 作分母）

分类规则（互斥，按证据强度排序）：

| 类 | 定义 |
|---|---|
| S1 | 回退，代价打分未执行 |
| S2 | 退化几何：无已验证内容链，或损失与全部步进代价为 0 |
| S3 | 无自由度：legal ≤ 1 或 `required ≥ legal` |
| S4 | 有代价但**边际代价全相同**（无区分信号） |
| S5 | 多 legal 块 **且** 边际代价不同 → **真实存在可选差异** |

### 2.1 分布

| 类 | 计数 | 占比 | 其中与 rank-LRU 不同 |
|---|---:|---:|---:|
| S1 回退 | 167 | 27.8% | 0 |
| S2 退化几何 | 368 | **61.2%** | 0 |
| S3 无自由度 | 0 | 0% | — |
| S4 边际代价全同 | 28 | 4.7% | 0 |
| **S5 真实可选差异** | **38** | **6.3%** | **0** |

按阶段拆分：

| 类 | forced 之前 | forced 之后 |
|---|---:|---:|
| S1 回退 | 4 | 163 |
| S2 退化几何 | 368 | 0 |
| S4 边际代价全同 | 0 | 28 |
| S5 真实可选差异 | 0 | **38** |

**关键观察**：全部 368 个"退化几何"决策都发生在**任何 forced release 之前**，
此时压力尚未注入，缓存无内容可淘汰；全部 38 个 S5 都发生在 forced 之后。

### 2.2 用记录几何做只读反事实（不是改造出来的条件）

对 S5 中满足"内容已验证 + 损失非零"的 **66** 个决策，
用 payload 里的 `block_memberships` / `effective_chain_lengths` / `decision_reuse_weights`
重建 `DecisionGeometry`（即引擎当时使用的同一份几何），再跑穷举选择：

```text
decisions with verified content and nonzero loss:   66
  geometry rebuildable and scorable:                66
  every chain is already deepest-first:             66
  exhaustive counterfactual differs from rank-LRU:  0
```

**这是对 RC2 核心问题的直接回答**：

> **是的，存在 Cost-Aware 有机会改变选择却未改变的窗口：38 个（6.3%）。**
> 但即使允许完全穷举，在那 66 个几何上代价最优集合**仍与 rank-LRU 相同**。
> 原因是结构性的：**每条链内 rank 已是 deepest-first**，
> 于是"最浅缺口最小"与"rank 最靠前"是同一集合。

因此，缺的不是"决策自由度"，而是**能让代价最优集偏离 rank-LRU 的几何**——
即链内 rank 与内容深度不单调的窗口。本归档中此类窗口为 **0**。

---

## 3. RC3 —— TTL 与模型尺度退化

### 3.1 公式的设计尺度

`docs/archive/phase1b-continuum/phase1b-continuum-implementation-decisions.md` §1.4：

```text
T_default = max(0, mu * ln(RepresentativePrefillReload / mu)),   mu = 1 second
```

`mu = 1 s` 是**参考时间尺度**：只有当代表性 prefill-reload **大于 1 秒**时 TTL 才为正。

### 3.2 本轮的实测输入落在截断区

profile（`prefill-reload-profile-interpreted.json`，`status: complete`）：

| token | effective_cost_seconds | 状态 |
|---:|---:|---|
| 1024 | **0.0** | `INDISTINGUISHABLE_FROM_ZERO` |
| 4096 | 0.303 | `RAW_POSITIVE_MEASUREMENT` |
| 8192 | 0.454 | 同上 |
| 12288 | 0.639 | 同上 |
| **16384** | **0.986** | 同上（≈ μ） |
| 24576 | 1.323 | 同上（> μ） |
| 32256 | 1.937 | 同上 |

决策时观测到的 `prefill_reload_seconds`：**0.0095 – 0.1711 s**，全部 < μ = 1 s。

```text
ln(0.0095..0.1711) < 0    =>  max(0, ·) = 0    =>  ttl_seconds = 0
实测：ttl_seconds == 0 在 139 / 139 条候选记录上成立
```

同时还发现：**profile 1024-token 点本身已被判为"与零不可区分"**，
且 `ranking_sensitivity_status = INCONCLUSIVE_COST_ORDERING`。

### 3.3 因果关系：模型规模 → 输入落到截断区

`prefill_reload` 随模型变小而变快。1.5B 模型下，整个可观测范围（≤ 0.17 s）
远低于 `μ = 1 s`；按 profile，要超过 μ 需 ≳16k token。

**因此 `ttl = 0` 不是公式错误，而是 `μ` 与当前部署规模不匹配的必然结果。**

### 3.4 一个更重要的、此前未指出的机制

在 `COLD_START` 分支中，`ttl_seconds = ttl_input.default_ttl_seconds`，
而这个值是**启动时确定的常数**（`runtime.py` 构造参数），对所有请求相同。

于是

$$\text{deadline}_c-t=\underbrace{\text{ttl}_c}_{\text{同一常数}}-\text{elapsed}_c$$

**只要 TTL 是常数，$q$ 的排序就只由 elapsed 决定，与常数取值无关。**
所以：

- `ttl = 0` 影响的是 **$q$ 的量级**（变成 ~1e-2…1e-9），不是**序**；
- $q$ 与 recency 同序的根因是 **cold-start 使用常数 TTL**，而不是截断本身。

### 3.5 哪些结论受 TTL 退化条件限制

| 结论 | 是否依赖 TTL 退化 |
|---|---|
| `ttl = 0`（139/139） | 是（`μ` 尺度 + 1.5B） |
| $q$ 序 == deadline 序 | **是**（cold-start 常数 TTL） |
| A1 仅在 `q_ratio < a_ratio` 时偏离 | **否**（纯代数，对任意正 $q$ 成立） |
| A1 偏离的一次是退化（g05） | **否**（该几何的 $q$ 差来自 elapsed，属该负载事实） |
| A2 代价最优集 == rank-LRU（66/66） | **否**（原因是链内 deepest-first，与 TTL 无关） |
| 复用信号无判别力 | **是**（cold-start 分支根本不使用 gap 样本） |

---

## 4. RC4 —— 复用历史全零的根因（更正）

### 4.1 上一版的错误

我把 `TTL_HISTORY_INPUT_OBSERVED` 的四个字段（`eta_history_sample_count`、
`queue_delay_history_sample_count`、`queue_delay_history_recent_sample_count`、
`eta_completed_program_count`）当成了"全部历史"，得出"历史全零"。

**这四个字段里没有 server-gap 或 external-tool 的样本计数。** 该观测事件根本
不暴露它们（`runtime.py` 中 `TTL_HISTORY_INPUT_OBSERVED` 的 payload 只有这些字段）。

### 4.2 实际的产生与消费链路

| 环节 | 事实 |
|---|---|
| 产生 | `ServerGapHistory.record` 在 `_handle_request_arrived` 触发，前提是该 program 有 `_pending_server_gaps`（在每次 TTL 决策时写入） |
| 写入 | 每次"上一轮结束 → 下一轮到达"记一条 gap |
| 消费 | `runtime.py:365` `self.server_gap_history.global_samples()`；`:367` `samples_for_tool(...)` → 传给 `TTLInput` |
| 阈值 | `_select_history`：`len(global_samples) <= duration_history_threshold (100)` → **COLD_START** |
| 生命周期 | history 实例在 per-run runtime 内；每个 run 新进程，**不跨 run 累积** |
| 右删失 | 102 个 `W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED`，说明窗口在 session 结束前被截断 |

### 4.3 每 run 能产生多少条

该 run 有 **12** 个 `REQUEST_ARRIVED`、2 个 `PROGRAM_STARTED`、11 个 `TURN_FINISHED`。
每个 program 的首次到达无 pending gap，其余每次到达记一条：

```text
估计上界 = 12 - 2 = 10 条 / run
阈值     = 100
可用样本 = 10 << 100  ⇒ _select_history 恒为 COLD_START
```

### 4.4 根因判定

| 候选原因 | 判定 |
|---|---|
| Workload 天然不产生历史 | **否**（每 run 约 10 条） |
| Runtime 未记录 | **否**（`record` 路径存在且被到达事件触发） |
| **生命周期错位 / 样本量不足** | **是，主因**：阈值 100 vs 每 run ≈10 条；且 per-process 不累积 |
| 决策时读取错误 | **否**（`global_samples()` / `samples_for_tool()` 均被调用） |
| 右删失 | 加剧因素：窗口被截断，无法观察"是否返回" |

> **结论**：历史不是"不存在"，而是**样本量级差一个数量级**，
> 且因为没有跨 run 的状态，重复运行同一 workload **不会**累积样本。
> 上一版"该 workload 永不产生历史"的说法**撤回**。

### 4.5 一个可观测性缺陷（需记录）

归档的 `TTL_HISTORY_INPUT_OBSERVED` **不暴露** `global_server_gap_samples_seconds`
的长度，因此在归档层面**无法**核实样本数是否如推算的 10 条。
要验证 RC6 的第 2 项，需要该事件补两个计数字段（属日志改动，非算法改动）。

---

## 5. RC5 —— A1 的数学与归因

### 5.1 精确翻转判据

对全部 sufficient 候选（$N_i\ge\text{need}$）：

$$\widehat R_i=q_i\,a_i,\qquad a_i=\lambda N_i+(1-\lambda)\,\text{need}$$

$\lambda=0$ 取 $\arg\min q$；$\lambda>0$ 取 $\arg\min q\,a$。两者不一致的**精确条件**：

$$\frac{q_H}{q_L}\;<\;\frac{a_L}{a_H}$$

其中 $L$ 为低 $q$ 候选、$H$ 为高 $q$ 候选。

上一版用 $N_L/N_H$，那是 $\lambda\to1$ 或 $N\gg\text{need}$ 的极限。二者关系：

$$a_L/a_H \in [1,\;N_L/N_H]$$

即近似形式**系统性高估**翻转倾向。本归档中两者结论一致（18/18，近似式假阳性 0），
但**近似式不作为一般判据**。

### 5.2 验证（精确式）

```text
forced-release decisions replayed            29
runs with more than one step                 11     <- 覆盖多步释放
first observed pick not among candidates      0     <- 用完整 (program, prefix) 键比较，无截断
two-candidate decisions                      18
exact ratio (a_L/a_H) correct                18 / 18
approximate ratio (N_L/N_H) correct          18 / 18
approximate false positives                   0
```

g05 两例（唯一翻转）：

| run | need | N | q_ratio | **a_ratio** | N_ratio | flip |
|---|---:|---|---:|---:|---:|---|
| g05-deep | 114 | 649 / 993 | 1.4174 | **1.4509** | 1.5300 | 是 |
| g05-moderate | 1 | 649 / 993 | 1.4174 | **1.5292** | 1.5300 | 是 |

注意 moderate 的 `a_ratio`（1.5292）与 `q_ratio`（1.4174）**只差 7.9%**，
说明该决策在 λ 变化下**接近临界**——这是"单次运行下不稳定"的另一条理由。

### 5.3 五个层次必须分开（M1 要求）

| 层次 | 本归档状态 |
|---|---|
| **代数复算** | 完成：λ=0.5 打分 29/29 复现观测；精确判据 18/18 |
| **观测选择重现** | 完成：`replay reproduces observed first pick: 29/29` |
| **离线 λ 反事实** | 完成：λ=0 改变 2 / 29 个选择（均 g05） |
| **Native 重算结果** | 仅 g05-moderate 有（A0 16 tokens vs A1 3728 tokens） |
| **具内容身份的因果归因** | **未建立**（`content_level_causal_attribution: NOT_ESTABLISHED`） |

### 5.4 保留与收窄

- 保留：g05-moderate 的 **+3712** 是观测事实，且该决策的选择可由打分精确复现；
- 收窄：**单次运行不能证明稳定退化**；且该决策接近临界（§5.2），λ 微小变化即可翻转。

---

## 6. RC6 —— 有界实验可识别性检查方案（不申请 GPU）

### 6.1 第一步（零 GPU）：A2 是否存在真实机会 —— **已完成**

| 检查 | 结果 |
|---|---|
| 有可选差异的窗口（S5） | **38 / 601** |
| 其中能重建几何并穷举的 | 66（含 S5 与其他非零损失决策） |
| 穷举结果与 rank-LRU 不同 | **0 / 66** |
| 链内 rank 已 deepest-first | **66 / 66** |

**结论**：本归档中机会存在（38 个），但**在记录几何上代价模型不可能偏离**
（因为链内 deepest-first）。这是一个**几何性质的结论**，可推广为：

> 只有当某条链内出现"更浅的块反而更冷"时，A2 才可能偏离。
> 归档需记录这一条件是否出现——当前未记录。

### 6.2 第二步（零 GPU）：TTL / 历史的产生—传递—消费核查

| 环节 | 现状 | 可否离线验证 |
|---|---|---|
| 产生 | `ServerGapHistory.record` 存在，按到达事件触发 | 代码可读；**归档不记录样本数** |
| 传递 | `TTLInput.global_server_gap_samples_seconds` | 代码可读；归档不记录 |
| 消费 | `_select_history` 阈值 100 | 代码可读 |
| 判定 | `mode == COLD_START` | **归档未记录 `TTLDecision.mode`** |
| 处置 | `default_ttl_seconds` 为常数 | 可由 `ttl == 0` 反推 |

**需要的最小可观测性补丁（日志，不是算法）**：

1. `TTL_HISTORY_INPUT_OBSERVED` 增加 `global_server_gap_sample_count` 与 `tool_server_gap_sample_count`；
2. 事件中记录 `TTLDecision.mode`；
3. 块决策事件记录 `legal` 列表的**排序依据**与**当时的队列快照**（或 `lru_rank`）。

这三项使 §1.4 的 L2、§4.4 的样本数、§6.1 的几何性质都变成**可离线判定**。

### 6.3 第三步：是否需要受控负载

由 §2–§6.2，两种退化各自有独立的解除条件：

| 退化 | 解除条件 | 现有 workload 能否满足 |
|---|---|---|
| 历史样本不足（10 ≪ 100） | 单 run ≥ 100 个 gap 样本（≈100+ 请求），或降低阈值 | **否**（12 请求/run） |
| 几何不含可选差异 | 出现链内 rank 非单调的窗口 | **否**（66/66 单调） |
| TTL 截断 | 代表性 prefill-reload > μ = 1 s（≳16k token） | 部分可（`max_model_len=32768`） |

**结论：需要一个受控负载**，其设计目标应仅为"把三种退化解除"，而不是"制造收益"。
这属于 Workload Redesign —— **未获授权**，本文只提出判据，不提出实现。

### 6.4 第四步：若需 Native，先做机制确认

在完整 campaign 之前，建议**少量机制确认运行**（数量由 M1 定，本文建议个位数）：

| 确认项 | 判据 |
|---|---|
| 历史样本确实非零 | `TTL_HISTORY_INPUT_OBSERVED` 的样本计数 > 0 且 `mode != COLD_START` |
| TTL 非退化 | `ttl_seconds > 0` |
| 几何含可选差异 | 至少一个窗口的链内 rank 非单调 |
| A2 确实偏离 | `selected_victims != native_lru_victims` 出现 ≥1 次 |

**只有四项全部为真，才存在可评的"Cost-Aware 是否有效"的问题。**

### 6.5 λ=0 / SFED 的定位

保留为**强基线与消融对照**，但**不**升级为最终研究算法。
理由：本归档中 λ=0 使 A1 与最早 deadline 一致（27/29），即与 A0 同源；
它消除退化但不产生收益，因此只能作为"归因工具"。

---

## 7. RC7 —— 归档来源核验

### 7.1 可核对的事实

| 检查 | 结果 |
|---|---|
| `evidence-manifest.json` 条目 | 366 |
| 逐文件 SHA-256 匹配 | **365** |
| **不匹配** | **1** |
| 缺失 | 0 |
| `sha256-manifest.txt` 行数 | 370 |
| 可解析且匹配 | **370 / 370** |
| `sha256(evidence-manifest.json)` | `072d5264…` |
| `execution-summary.json` 声称的 `inventory_sha256` | `072d5264…` ✓ 一致 |
| run 目录（含 `run.json`） | **54**，`g01-short-extreme-deep-a0-repeat-1` … `g09-near-matched-moderate-a2-repeat-1` |

### 7.2 唯一的失配文件

```text
evidence-manifest.json 记录的 execution-summary.json:
  sha256 = 718e6e39…    size = 1091
实际:
  sha256 = e3b25be2…    size = 1635
```

差异内容为 `result_summary` 与 `wall_elapsed_seconds` 两段（共 +544 字节）。
这说明 **`execution-summary.json` 在清单生成之后被写入过**——
最可能是流水线"先写清单、后补最终统计"的顺序产物。

**但这只是推测，本文不把它当成结论**；它恰恰说明该文件不能用于链接外部 SHA。

### 7.3 关于两个 archive SHA

```text
M1 公布:  ac2b910e...   在解压后的归档树中【完全不出现】
归档内:   d4aaf36e...   仅出现在 execution-summary.json 的 archive.archive_sha256
```

因此：

- 本机这一份**内部自洽**（370/370 + 365/366）；
- 但 **无法证明** 它等于 M1 公布 SHA 所指的 tar.gz；
- 且唯一记录该 SHA 的文件本身**与清单不符**（§7.2），进一步削弱其可信度。

**可交由 M1 核对的链接字段**（这些字段是归档真实的、且未被修改的部分）：

| 字段 | 值 |
|---|---|
| `tooling_git_sha` | `7d0546ab6829060fa50fe40f5dcb47dd5212f091` |
| `manifest_sha256` | `13cba945ddddb3c48f0970e1d0e483bce95a675101ef32aa5db4ceb5881f605d` |
| `authorization_sha256` | `3ff0cf0294cdf9a6eca35822344c5ee3a4ba6db8c9d5d532c96c81442911c577` |
| `report_sha256` | `ad879105e21aedbf86b2dd5d4199688be4b7587b051b6be3e45b0100ec643b0e` |
| `profile_sha256` | `baf4497161e2326c5b884358350515abe35aff22d4d94a92b2acd9004db91cc6` |
| `raw_profile_sha256` | `24c2d425a1f16164d4428bba09cc8614d6f57f52d17f8280ee92abf78d1aafb0` |
| run ID 集合 | 见 §7.1（54 个） |

**建议**：以 `tooling_git_sha` + `report_sha256` + 54 个 run ID 作为跨份核对键，
而不是 archive 级的 tarball SHA。

---

## 8. Part A / B 的结论（按上述更正重述）

### 8.1 Entry 层

| 项 | 结论 | 强度 |
|---|---|---|
| `ttl = 0` 在 139/139 | 事实 | 强 |
| $q$ 与 deadline 同序 | 由 cold-start 常数 TTL 推出，**不是 TTL=0 导致** | 强（代数） |
| A1 精确翻转判据 | 18/18 | 强（代数 + 复算） |
| λ 改变选择 2 次，均 g05 | 事实 | 强 |
| g05-moderate = +3712 | 观测事实 | 强（但 n=1 repeat） |
| 该退化稳定存在 | **不可判定** | — |
| 复用概率型 EntryLoss | **无法在本归档构造**：样本 10 ≪ 100，非"不存在" | 中（§4） |

### 8.2 Block 层

| 项 | 结论 | 强度 |
|---|---|---|
| A2 使用代价打分 | 434/601 | 强 |
| 代价打分改变 victim | **0/601** | 强 |
| 有可选差异窗口（S5） | **38/601** | 强 |
| 穷举反事实仍不偏离 | **0/66** | 强（几何重建 + 复算） |
| 原因 | 链内 rank 已 deepest-first | 强（66/66） |
| A2 vs 真正 A0 | **不可判定**（快照过期 151/229） | — |
| 回退 167/601 | 事实；与 Gate 2 51.7% **不可比** | 强 |

### 8.3 M2 四方向（受上述更正影响的部分）

| 方向 | 修订后判定 |
|---|---|
| **B1** 条件介入 | **`CONDITIONALLY TESTABLE`**：机会存在（38 个），但在本归档几何上无差异。需先让几何含非单调 rank |
| **B2** 中间信号 | **`NO DATA BUT NOT ABSENT`**：历史存在（≈10/run），差一个数量级的样本；需 100+ 请求/run 或降阈值 |
| **B3** 下游感知排序 | 不变：`LIMITED`（A0 已消费下游 rank；单步即满足） |
| **B4** 部分尾部释放 | 不变：`HIGH COST`（超额是 `initial_shortage_blocks=1` 的设计产物） |

---

## 9. 本轮**不做**的裁定

按 M1 要求，本文**不**给出最终研究方向裁定，也**不**申请执行 Part D 的 54-run Freeze。
上一版的 Part C/D 视为**撤回**，待 §6 的可识别性检查完成后再提。

---

## 10. 边界

- 未修改 `src/`；未运行 Native；未覆盖归档；
- 全部 counterfactual 均标注为离线反事实，不是原始真实运行结果；
- 逆向推断（如"候选按 rank 升序传入"）均给出依据，并标明其为推断；
- `physical_eviction_divergence` 仍建议弃用（18/18 全 true，含 16 个 A1 序列与 A0 相同的 cell）。

---

## 11. 复现

```bash
# 需先解压 v10 archive 到 local/continuum-native-cost-aware-bounded-v10-final-evidence/
python scripts/probes/entry_costaware_audit/rc2_opportunity.py            # S1-S5 分类
python scripts/probes/entry_costaware_audit/rc3_scale_and_geometry.py     # 尺度 + 几何反事实
python scripts/probes/entry_costaware_audit/rc5_exact_flip.py             # 精确判据 18/18
python scripts/probes/entry_costaware_audit/rc7_archive_verify.py         # 归档核验
python scripts/probes/entry_costaware_audit/a1_decisions_detail.py
python scripts/probes/entry_costaware_audit/a1_lambda_ablation.py
python scripts/probes/entry_costaware_audit/a4_identity_gap.py
python scripts/probes/entry_costaware_audit/a4_divergence_check.py
python scripts/probes/entry_costaware_audit/a4_legal_strict.py
python scripts/probes/entry_costaware_audit/a2_field_variation.py
python scripts/probes/entry_costaware_audit/b2_signal_audit.py
python scripts/probes/entry_costaware_audit/b4_unlocked_vs_evicted.py
```
