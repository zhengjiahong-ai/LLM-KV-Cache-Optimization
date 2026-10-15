# Ours-Evict — Algorithm Design v1

**提交人**：M4　**送审**：M1　**日期**：2026-10-15
**阶段**：Phase 2 Cost-Aware Eviction 算法设计（**设计 PR，不含 runtime 实现**）
**决策边界**：真实 vLLM 的**合法 KV cache victim selection**（在既有 eligibility / protection / refcount 之上只重排合法候选）
**主目标**：**aggregate recomputed tokens**　**辅助观测**：TTFT
**边界**：不改 native BlockPool / ref_cnt / hash cleanup，不改已冻结 Continuum baseline，不实施 runtime

---

## 0. 一页摘要

**核心机制（新）**：在共享前缀拓扑中，一个 block 只有在**其全部 owner 都被释放**后才会变成可回收。
因此**单个 entry 的释放可能回收不到它的共享块**；朴素地把 entry 当独立单位打分，
会反复释放同一共享组的成员、积累重算损伤，却始终不解锁共享容量。

Ours-Evict 的核心判据是：

```text
credit(i | S) = 释放 i（已释放集合为 S）时真正变为可回收的块数
damage(i | S) = 因释放 i 而被销毁、但并未因此回收的块数（"白白的损伤"）
release priority : damage / (1 + credit)  升序（每单位回收容量付出最少浪费损伤的 entry 先释放）
```

**与基线的关系**：基线的键 `(deadline, min(native_lru_rank of newly_eligible), identity)`
—— `credit` 的**计数**被丢掉（只取其中最冷块的秩），而 `damage` **从不进入排序**。
Ours-Evict 两者都进入。

**为何先前规则够不到它**：H1 语料中 `relief ≡ block_count`（471/471），
即 `damage ≡ 0` 对所有候选成立 ⇒ 该机制的判别项**在 H1 中恒为零、不可达**。
Phase 2E 的 F4 shared-root family 才产生 `relief < block_count`（`damage > 0`）的语料。
⇒ 这不是"重新组合已失败的简单启发式"，而是**在一个先前不可观测的维度上打分**。

**最小可证伪案例**：两个候选共持同一 root。若 Ours-Evict 与基线在该事件上给出不同 release，
则 aggregate recomputed tokens 出现差异；**若在 F4 shared-root family 上不优于基线与 size 规则，则本机制被证伪**。

---

## 1. 优化目标、候选集合与决策流程

### 1.1 优化目标

```text
主目标   : minimize aggregate recomputed tokens（scenario 级求和，冻结统计单位为 scenario draw）
约束     : Σ 已释放 entry 的 marginal reclaim ≥ required_blocks
辅助观测 : TTFT / queue delay / admission-to-first（仅观测，不作主判据）
```

**目标选择依据**（Phase 2E 实测）：Continuum 相对 Native LRU 把 aggregate recomputed
从 326.67 降到 134.67（−58.77%），**但** TTFT 三分量均只动 ≈+0.05%
（TTFT/queue/prefill 份额为 90.07% / 9.93%）。⇒ 顺序是对的：

> **以 token 为优化目标，把 TTFT 作为辅助观测**（M1 已裁定），
> 不假设 token 收益等比例转化为延迟收益。

### 1.2 候选集合（**合法集由现有机制决定，算法不改变合法性**）

```text
候选 = FORCED_RELEASE_DECISION.payload.candidates
       （已由 Continuum 判定 protected 且合法的 logical retention entries）

每候选可得：
  block_ids                      -> 名义 footprint（含共享块）
  initially_reclaimable_block_ids -> 共同所有权折减后的 marginal reclaim
  retention_deadline_timestamp / elapsed_since_ttl_decision_seconds
  prefill_reload_seconds / next_tool_type / waiting_followup
```

**算法不新增合法性判断**，也不触碰 refcount / hash cleanup / BlockPool。
它只回答：**在给定合法候选集内，按什么顺序释放。**

### 1.3 决策流程（一个 pressure event 内）

```text
输入：required_blocks R，合法候选集 C
S := {}                                  # 已释放集合
while newly_eligible(S) < R:
    对每个 i ∈ C \ S 计算 credit(i|S)、damage(i|S)        # 集合级，随 S 更新
    i* := argmin damage(i|S) / (1 + credit(i|S))          # 平局 -> 冻结 identity 次序
    释放 i*；S := S ∪ {i*}
输出：释放序列 S
```

**关键**：`credit`/`damage` 是**关于已释放集合 S 的函数**，不是候选的静态属性。
这正是基线未表达的部分（基线在循环中也更新 `newly_eligible`，但**只用它取 min LRU 秩**，
且损失侧永远不参与排序）。

### 1.4 形式化定义

对当前 protected 候选集，定义块的 owner 集合：

```text
O(b) = { i ∈ C : b ∈ B_i }                  B_i = block_ids(i)
```

则：

```text
credit(i | S) = |{ b ∈ B_i : O(b) ⊆ S ∪ {i} }|        # 释放 i 后变为可回收
damage(i | S) = |{ b ∈ B_i : O(b) ⊄ S ∪ {i} }|        # 仍被组外 owner 保护=白白销毁
note          : credit + damage = |B_i|
```

**恒等校验**（与既有机制一致）：

```text
credit(i | S₀) = |initially_reclaimable_block_ids(i)|
   其中 S₀ = 进入本次 pressure 循环前的 released_keys
   （含循环前已 ordinary-expired 的 entry）
```

证据：平台在 `pressure.py:94` 用 `_newly_eligible_blocks_after_release(key, ..., released_keys)`
计算 `initially_reclaimable_by_entry`，**与 `credit` 是同一个函数**，只是以循环前的 `released_keys` 为基准。

⇒ **`credit` 是 `initially_reclaimable` 在循环中（随 S 演进）的推广**；
因此该量**不需要新观测缝**，只需在循环中随 S 重算。
⚠️ 反之：若某个候选的 `initially_reclaimable_block_count` 已由 payload 给出，
它只对**首次**迭代有效，不能直接当作循环中的 `credit` 使用。

**退化行为（重要，用于消融预期）**：

```text
若无共享（∀b: |O(b)| = 1）  ⇒ damage(i|S) = 0 ∀i,S
                             ⇒ score 全部并列 0 ⇒ 平局由冻结 identity 决定
                             ⇒ 算法退化为"无语义"，与 size 规则无实质差异
```

⇒ **本算法在无共享语料上预期无增益**，这既是已知风险，也是一个**好的阴性对照**（§5.2 A5）。

---

## 2. Cost-Aware 评分机制与信号获取

### 2.1 主评分

```text
score(i | S) = damage(i | S) / (1 + credit(i | S))     # 升序释放
```

**语义**：每单位**真实回收容量**所付出的**浪费损伤**。
`score = 0` 表示"释放它正好把容量还给我，且不额外销毁任何被他人保护的内容"——最优。

### 2.2 为什么不是简单比例（避免退化为已失败启发式）

| 候选设计 | 结果 | 判定 |
| --- | --- | --- |
| `credit` 降序（纯回收量） | 在无共享时退化为 size 规则（H1 已证与基线同构 0/0/60） | ❌ 已失败 |
| `block_count` 升序（纯尺寸） | 已实现（`M1_block_count_ascending`），H1 无增益 | ❌ 已失败 |
| `prefill_reload / reclaimable` | 已实现且净负面（`M1_marginal_cost_per_reclaimable` 6/45/63） | ❌ 已失败 |
| **`damage / (1+credit)`** | **新增判别项 `damage`，且随 S 更新** | ✅ **本设计** |

**去重声明**：Ours-Evict **不是**上述任何一条的重命名。它的判别量 `damage`
在上述所有规则中**恒不被读取**；且它**只在与 S 的交互中存在**，不是候选的静态属性。

### 2.3 信号获取表（每项如何在决策时获得）

| 信号 | 来源 | 决策时可得 | 是否需要新观测缝 |
| --- | --- | --- | --- |
| `B_i` = `block_ids` | `FORCED_RELEASE_DECISION.payload.candidates[].block_ids` | ✅ | 否（已持久化） |
| `O(b)` owner 集合 | 由**候选集内**所有 `B_i` 反查得到 | ✅ | 否（`prepare` 内纯计算） |
| `credit(i\|S)` | 由 `B_i` 与 `O(b)` 按定义计数 | ✅ | 否 |
| `damage(i\|S)` | `\|B_i\| − credit` | ✅ | 否 |
| `initially_reclaimable_block_ids` | 同 payload | ✅ | 否（用于校验，非必需） |
| `required_blocks` | 同 payload | ✅ | 否 |
| `retention_deadline_timestamp` | 同 payload | ✅ | 否（**fallback / tie-break 用**） |
| `next_tool_type` / `waiting_followup` | 同 payload | ✅ | 否（本版**不使用**，见 §5.3） |
| block → 前缀内位置 | 需 P5 | ⚠️ `PARTIALLY_DEMONSTRATED` | **是 ⇒ 本版不使用** |
| physical logical owners | 能力矩阵 `NOT_OBSERVABLE` | ❌ | 是 ⇒ 设计**不依赖** |

⚠️ **本设计不依赖 P5、不依赖逻辑 owner 持久化、不依赖内容级反事实**。
`O(b)` **只**在**当前候选集内**计算——这是逻辑级（payload 内）事实，不是物理级归属。
⇒ 与既有能力边界（P5 PARTIALLY / logical-owner NOT_OBSERVABLE / causality NOT_ESTABLISHED）**不冲突**。

### 2.4 fallback 阶梯（遵守既有契约）

```text
1) 主键   : score(i|S) 升序
2) 平局   : retention_deadline_timestamp 升序（复用冻结 P1B 的第一分量语义）
3) 再平局 : 稳定逻辑 identity (program_id, prefix_id)
```

⛔ **绝不 fallback 到 LRU recency**——那会把本规则静默变回基线，使比较失去意义
（`src/kvopt/costaware/rules.py` 模块契约的既有规定）。

---

## 3. 结合 vLLM 前缀缓存：为何可能优于 Native LRU

### 3.1 vLLM APC 的结构性事实

```text
- 块按 token 前缀做 hash 链：block hash 依赖其之前全部 token
- 因此共享前缀 -> 相同 block hash -> 同一批物理块
- native 淘汰是 block 粒度、按 last-access 时间（LRU）
- 一次请求命中前缀时会 touch 其整条链上的所有块，故同一条链的块"同时变新"
```

⇒ Phase 2C/2D 已独立实测该后果：候选 entry 的块在 native LRU 序中**形成连续带**
（H1 `bands_contiguous = 87/87 = 100%`，`spread ≈ size − 1`）
⇒ **节点级 LRU 退化为 entry 级淘汰**（RR-EVICT 所述 recency synchronization 在我们的栈上被实测确认）。

### 3.2 Native LRU 的两个结构性盲点

**(a) 共享块在 LRU 视角里"只是一个块"。**
hash 链让多个 agent 的链共享同一批物理块，但 LRU 只记录**一个** last-access 时间。
⇒ 释放该块会同时损伤**所有**包含它的 agent，而 LRU 的判断里**没有任何一项**对应这个传播。
Ours-Evict 的 `damage` 正是这一项的显式估计。

**(b) 基线的第二分量丢弃了回收量。**
`min(native_lru_rank of newly_eligible)` 只问"我能释放的最冷块有多冷"，
不问"我释放了多少块"。在共享拓扑下这会做出**低回收、高损伤**的选择：
释放某 entry 只回收其私有尾部（`credit` 小），却把它与组内其他 entry 共享的 root 内容销毁
（`damage` 大）——**不推进压力目标，却付出了重算代价**。

### 3.3 Ours-Evict 的机制主张（可证伪陈述）

> 在共享前缀拓扑下，**共享块只能通过释放整个共属组才能被回收**。
> 因此存在一批压力事件，其中基线的 per-entry min-rank 键会按"最冷块"顺序释放，
> 反复命中同一共享组的成员却不解锁共享容量；
> 而 Ours-Evict 以 `damage/(1+credit)` 优先选择"能真正把容量还回来"的 entry，
> 从而在**相同 required_blocks 下释放更少/更省的 entry**，降低 aggregate recomputed tokens。

⚠️ **这不是"我们的算法比 LRU 好"的一般主张**，而是一个**条件性、可证伪**的陈述（§5.1）。

---

## 4. 与 H1 规则及相关研究的机制对比

### 4.1 与已失败规则族的对比

| 规则族 | 读什么 | H1 结果 | Ours-Evict 的差别 |
| --- | --- | --- | --- |
| `M0_p1b_executed_ordering`（冻结基线） | deadline → min LRU 秩 → identity | 对照 | `damage` 不参与；`credit` 只取 min 秩 |
| `M1_block_count_ascending` / `M1_prefill_reload_ascending` / `M3_size_score_*` | 尺寸 | 与基线同构（0/0/60，identity 1.000） | **size 不含 `damage`**；无共享时 Ours-Evict 也退化 ⇒ 二者在无共享语料上**应等价** |
| `M1_reclaimable_ascending` | `initially_reclaimable_block_count` | H1 中 ≡ `block_count` ⇒ 秩同构 | **H1 中该量退化，故这条规则测不到本机制** |
| `M1_marginal_cost_per_reclaimable` | `prefill_reload / max(reclaimable, 1)` | 净负面（6/45/63） | 它**读** `reclaimable`，但只作为**成本比的分母**，**不计算也不惩罚**未被回收的余项（`damage`） |
| `M2_non_code_first` / `M3_non_code_*` | `next_tool_type` | 仅 F1 有效，族一致 3/6 | 属**返回预测**路线，证据已弱；Ours-Evict **不使用**它 |

**核心论证**：上述规则的判别量在 H1 语料上**互相秩同构**，因为它们全部只依赖
`block_count` / `reclaimable`（二者在 H1 中恒等）与 `prefill_reload`（与尺寸同构）。
**`damage` 这一项在 H1 中恒为 0，没有任何一条既有规则读取它。**
（已逐行核实 `rules.py`：既有键只读 `retention_deadline_timestamp`、`decision_native_lru_position`、
`prefill_reload_seconds`、`block_count`、`initially_reclaimable_block_count`、`next_tool_type`；
**没有任何一条计算 `block_count − reclaimable`**。）
⇒ Ours-Evict 的新颖性**不在算子形式，而在打分维度**：它作用在一个 H1 无法表达的量上。

### 4.2 与 RR-EVICT（相关研究）的关系

| 维度 | RR-EVICT | Ours-Evict |
| --- | --- | --- |
| 目标 | 尾部 TTFT / 尾部 uncached | **aggregate recomputed tokens** |
| 手段 | 跨 idle agent **轮转** tail-chunk | 依据 `damage/credit` **排序** entry |
| 需要的结构 | 假设**等长**前缀、**无跨 agent 共享** | 明确利用**共享**与**非等长** |
| 粒度 | 子 entry（tail chunk） | **entry 级**（不要求子 entry 释放） |
| 未来预测 | 不需要 | **不需要** |

⇒ **重叠部分（"轮转/分散能改善尾部"）本设计不主张为创新。**
本设计的差异落在 RR-EVICT **假设不成立**的两处：**非等长**与**共享**。
⚠️ 依 M1 裁定：这仅是 **promising first candidate**，**不是已成立的贡献**。

### 4.3 明确的**不**主张

```text
❌ 不主张已改进 TTFT / 尾部延迟
❌ 不主张物理淘汰因果
❌ 不主张泛化到生产分布
❌ 不主张"共享" 本身是新问题（RR-EVICT 已识别 agent 私有性；共享属于其假设之外）
✅ 只主张：在共享/非等长语料上，damage 是一个新的、决策时可得的判别维度
```

---

## 5. 最小可证伪案例、消融设计与预期局限

### 5.1 最小可证伪案例（MFC）

**构造**（可直接复用 Phase 2E F4 shared-root 结构，无需新能力）：

```text
两个受保护候选 A、B 共持同一 root，各自独占一段尾部；required_blocks 小于二者之和
```

**两种情形**：

| 情形 | 基线（min LRU 秩） | Ours-Evict | 可观测分离 |
| --- | --- | --- | --- |
| **分离情形** | 释放 A（最冷块在 A） | 释放 B（`damage/(1+credit)` 更小） | aggregate recomputed tokens **不同** |
| **重合情形** | 释放 A | 释放 A | 无差异（阴性） |

**证伪条件**（必须明确）：

> 若在 F4 shared-root family 上，Ours-Evict 的 aggregate recomputed tokens
> **不显著低于**基线 **且不显著低于** size 规则（`M1_block_count_ascending`），
> 则 §3.3 的机制主张被证伪，本方向应停止，不得转入实现。

### 5.2 消融设计

| 臂 | 定义 | 预期 | 作用 |
| --- | --- | --- | --- |
| **A0** | 冻结 P1B 基线 | 对照 | — |
| **A1** | `credit` 降序（去 `damage`） | ≈ size 规则 | 隔离"计数 vs min 秩"的贡献 |
| **A2** | `damage` 升序（去 `credit`） | 退化/不稳定 | 证明二者**必须同时**存在 |
| **A3** | **完整 Ours-Evict `damage/(1+credit)`** | **最佳** | 主张主体 |
| **A4** | A3 关闭共同所有权折减（把 `B_i` 全视为可回收） | ≡ A1 | 隔离共同所有权信号本身 |
| **A5** | A3 跑在 **distinct-root 阴性对照** family | **无增益** | 关键阴性对照：证明增益来自共享而非其他 |
| **A6** | A3 去掉 deadline fallback（改用 identity） | ≈ A3 | 证明结论不依赖 fallback 次序 |

**A5 是本设计最重要的对照**：若 A3 在无共享语料上也有增益，则说明增益来自
尺寸/顺序等无关因素，机制主张不成立。

### 5.3 预期局限（诚实前置）

| # | 局限 | 说明 |
| --- | --- | --- |
| **L1** | **预期效应量小且条件性** | 仅在 `damage > 0` 的事件上才有判别力；无共享事件上退化为无操作 |
| **L2** | **不改善延迟** | Phase 2E 已实测 token 下降未带来延迟改善（90.07% queue 份额）。本设计**不承诺**延迟收益 |
| **L3** | **P5 未用于本设计** | 不使用 block→前缀位置，故**不能**主张 tail-first 正确性 |
| **L4** | **无物理归属** | `O(b)` 是**逻辑级**（payload 内）事实，**不是**物理 owner 归属；不得据此声称"某次物理淘汰由多 owner 保护导致" |
| **L5** | **依赖候选集完整性** | `O(b)` 仅覆盖 `payload.candidates`；若存在候选集外的 protected owner，`damage` 会**低估** |
| **L6** | **合成网格** | 不外推到生产分布 |
| **L7** | **`max_new_tokens=1`** | prefill-focused，不代表 decode 期 |
| **L8** | **`prefill_reload_seconds` 未使用** | 因 H1 中它与尺寸秩同构（需在 Phase 2E 语料上重新审计后再考虑） |

---

## 6. 接口复用与扩展（**含禁止事项**）

### 6.1 复用（**无需修改**）

| 接口 | 用途 |
| --- | --- |
| `src/kvopt/costaware/rules.py::CandidateRule` | 规则容器；**`prepare(candidates) -> Mapping[identity, float]` 已支持集合级上下文** ⇒ 本设计**不需要新接口** |
| `DECISION_TIME_FEATURES` | 合法特征白名单；`block_count`、`initially_reclaimable_block_count`、`retention_deadline_timestamp` 均在列 |
| `DecisionCandidateRow` | 提供 `block_ids` / `initially_reclaimable_block_ids`（**已持久化**） |
| `src/kvopt/costaware/offline_eval.py::evaluate_rules` | 离线评估主入口 |
| `src/kvopt/costaware/replay.py::DecisionSnapshot` | 决策快照 |
| `src/kvopt/costaware/acceptance.py` | 冻结接受协议（scenario-draw、≥30、seed 20261007、族一致 2/3） |
| `pressure.py::_entries_by_block` | 共同所有权映射（**只读参考**；算法在规则内自算等价映射） |

### 6.2 需**只读**扩展（设计阶段请求，实施阶段再落）

| # | 项 | 性质 | 理由 |
| --- | --- | --- | --- |
| **X1** | `PressureFeasibleOracle` 接受 **`observed_recomputed_tokens`** 作为目标视图 | 只读评估层 | M1 已定主目标为 aggregate recomputed tokens；现有 oracle 以 proxy 为主 |
| **X2** | 暴露**候选集内**的共同所有权计数（可选，便于审计 `damage`） | 只读 | 使 `damage` 可被独立复核；不改变任何默认策略 |
| **X3** | 在 Phase 2E 语料上**重新审计** `prefill_reload` 与尺寸的秩同构 | 只读分析 | 决定 L8 是否可解除 |

### 6.3 ⛔ 禁止事项（本设计**不**请求）

```text
❌ 修改 native BlockPool / ref_cnt / hash cleanup / LRU
❌ 修改已冻结的 Continuum baseline 默认策略（_release_sort_key 默认值）
❌ 修改 TTL estimator
❌ 子 entry / tail-chunk 释放（不要求 B1 解锁）
❌ 读取任何 FORBIDDEN_FEATURES（未来返回值、observed_recomputed_tokens 等）
❌ 新增 native 观测缝
❌ 重开 H1/H2
❌ 在 M1 审查通过前开始 runtime 实现
```

### 6.4 实施后（**仅在设计通过后**）的最小落点

```text
新规则注册：src/kvopt/costaware/rules.py 内新增 rule_id = "M4_ours_evict_v1"
   family   : "M4"
   features : ("block_count", "initially_reclaimable_block_count", "retention_deadline_timestamp")
   prepare  : 计算 O(b) 与 per-candidate credit/damage 上下文
评测入口  : python -m kvopt.costaware.cli（免 GPU / 免 vLLM / 免模型加载）
```

⚠️ **实施不改默认行为**：新规则只作为**被评估的候选规则**加入离线研究，
不改变 runtime 默认淘汰路径。runtime 接入须另行授权。

---

## 7. 请求 M1 裁定

1. **目标确认**：主目标 = aggregate recomputed tokens、TTFT 仅辅助观测，是否正确？
2. **机制新颖性**：是否接受 §4.1 的论证——**新颖性在 `damage` 这一判别维度，而非算子形式**？
3. **证伪条件**：是否接受 §5.1 的证伪条件（F4 上不优于基线与 size 规则即停止）？
4. **A5 阴性对照**：是否同意把 **distinct-root 无增益**作为机制成立的必要条件？
5. **只读扩展 X1–X3**：是否授权在设计阶段记录、在实施阶段落地？
6. **L8 处置**：是否同意**本版不使用** `prefill_reload_seconds`，待 X3 审计后再议？

---

## 8. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 基线键 `(deadline, min(native_lru_rank of newly_eligible), identity)` | `src/kvopt/continuum/pressure.py:324` |
| 压力循环为**整 entry 释放**、`newly_eligible` 随 `released_keys` 更新 | `src/kvopt/continuum/pressure.py:107`、`:150`、`:280-298` |
| `_entries_by_block`（共同所有权映射）**只用于资格判定** | `src/kvopt/continuum/pressure.py` |
| 规则契约、`DECISION_TIME_FEATURES`、`FORBIDDEN_FEATURES`、fallback 阶梯 | `src/kvopt/costaware/rules.py`（模块 docstring、常量、`CandidateRule.__post_init__`） |
| `prepare(candidates) -> Mapping[identity, float]` 钩子 | `src/kvopt/costaware/rules.py::CandidateRule.prepare` / `RuleKeyContext` |
| 候选行字段 `block_ids` / `initially_reclaimable_block_ids` | `FORCED_RELEASE_DECISION` payload（`src/kvopt/profiling/experiment_events.py`） |
| `relief ≡ block_count` 471/471（H1） | `local/probe_relief_field.py` |
| size 簇与基线同构（0/0/60，identity 1.000） | `docs/phase2a-m4-method-design-report.md` §6.1 |
| `M1_marginal_cost_per_reclaimable` 净负面（6/45/63） | 同报告 §6.5 |
| `M2_non_code_first` 仅 F1 有效 | 同报告 §5.3、§7.2 |
| Phase 2E：326.67 → 134.67（−58.77%），TTFT 三分量 ≈ +0.05% | `docs/phase2e-m6-measured-campaign-report.md` |
| Phase 2E：queue 份额 90.07%、`max_concurrent_requests = 3 if F6 else 1` | 同报告；`src/kvopt/workload/phase2e_materialize.py` |
| F4 奇偶 draw 语义（odd `SHARED_ROOT` / even `NO_SHARED_PREFIX_NEGATIVE_CONTROL`） | `src/kvopt/workload/phase2e_materialize.py`；`docs/phase2e-m4-measured-review.md` §2.1 |
| H1 连续带 87/87（节点级 LRU 退化为 entry 级） | `local/probe_s1_recency_sync.py`、`probe_s1b_lru_concentration.py` |
| 能力边界 P5 / logical owners / causality | `docs/phase2e-m4-t1-capability-reconciliation.md` §C |
| 冻结接受协议 | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| RR-EVICT 的假设（等长前缀、无跨 agent 共享）与目标 | `local/2609.32278v2.pdf` §3.3 |
| 禁止修改项 | `docs/phase2a-m4-method-design-input.md` §5、Phase 2E 授权边界 |
