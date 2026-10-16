# Phase 2F — 组合算法设计：Ours-Evict (simulation candidate v0) × Continuum Retention

**提交人**：M4　**送审**：M1　**日期**：2026-10-16
**分支**：`sim/phase2f-agent-apc-eviction-retention`
**性质**：**设计 + CPU 离线模拟验证**。不含 runtime 实现、不含 native run、不改冻结基线。
**上游边界**：PR #50（`docs/ours-evict-algorithm-design-v1.md` rev.2）当前状态
`CHANGES_REQUESTED / METHOD NOT YET APPROVED / RUNTIME IMPLEMENTATION NOT AUTHORIZED / B1 LOCKED`。

---

## 0. 本文档的位置与裁决承接

### 0.1 继承自 PR #50 的已裁定事实（本文档不再重新论证）

| # | 事实 | 来源 |
| --- | --- | --- |
| F1 | 冻结 block-level 边界只暴露 `EvictionCandidate = {block_id, ref_cnt, has_block_hash, lru_rank}`；`EvictionContext = {required_blocks, free_blocks, total_blocks, timestamp}`。不含 depth / owner / 内容身份 | PR #50 §0.1 结论 1；`runtime/vllm/types.py` |
| F2 | vLLM 0.27.1 原生路径已做 hashless 优先（`free_blocks()` 对无 hash 块 `prepend_n`、有 hash 块 `append_n`；`get_new_blocks()` `popleft_n`）⇒ **hashless-first 不是本方法的创新** | M1 RC-A；vLLM v0.27.1 `block_pool.py` L719–742 / L647–667 |
| F3 | `lru_rank` 方向：**数值越小越先被 Native LRU 选中**；`NativeLRUAdapter` 按 `lru_rank` 升序取 `required_blocks` 个 | M1 RC-B；`runtime/vllm/adapter.py:27-39` |
| F4 | Q1 logical release ⇏ Q2 physical eviction ⇏ Q3 future recomputed tokens；成本模型只对 Q2 建立，Q2→Q3 的映射必须显式假设 | PR #50 RC2；M1 RC-D |
| F5 | 增量重计算定义：`ΔR = Σ_r B·max(0, j_old(r) − j_new(r))`，`j` = 同一请求可命中的最长**连续**前缀深度；不是全部 prefill tokens | M1 RC-D；本任务硬性约束 |
| F6 | entry-level pressure-release replay 的效果**不得**当作 block-level Ours-Evict 的效果 | PR #50 §0.1；本任务 §七 |
| F7 | 不得向 `src/kvopt/continuum/**` 添加 Cost-Aware 评分；不得改 adapter 字段；不得改冻结释放键/TTL | `docs/phase2a-m4-block-level-design-draft.md` §7；PR #50 verdict |

### 0.2 本文档新增的裁决请求（仅此一项）

请求 M1 裁定：**是否批准将 `simulation candidate v0`（§2）作为 Phase 2F 离线模拟的研究对象**，
及其明确的非授权属性（simulation-observable signals、不得进入 runtime、不得宣称为正式方法）。
**不请求**：任何 adapter 字段扩张、任何 runtime 实现、B1 解锁、冻结基线变更。

---

## 1. 三个方法层级与本轮边界

```text
Layer 1  Ours-Evict                : 独立 block-level victim 选择（本轮实现 + 模拟评估）
Layer 2  Ours-Evict + Retention    : 叠加 Continuum 保留/保护（本轮重点）
Layer 3  Ours-Full                 : 再叠加调度协调（本轮不实现；A4 仅作单独报告的系统参照）
```

- Layer 1 必须能脱离 Retention 独立运行与评估（臂 A2）。
- Layer 2 评估 Retention 的**增量贡献**（A3 vs A2、A1 vs A0、A0/A1/A2/A3 四方对比）。
- 所有组件对照臂使用**同一 native 调度**（FIFO by (arrival, request_id)）；调度差异只允许出现在
  单独报告的 A4，且不得用于任何组件归因。

---

## 2. Ours-Evict — `simulation candidate v0`（精确定义）

### 2.1 动机：Native LRU 在 free-event band 内的结构性方向

vLLM 原生 free queue 的入队规则（F2）意味着：一次请求完成时释放的块构成一个 **band**——
无 hash 块被 `prepend_n` 到队首，有 hash 块被 `append_n` 到队尾，且**同一 band 内保持请求
block table 的顺序（前缀头 → 尾）**。因此在该 band 内，**链头块（浅层）的 `lru_rank` 小于
链尾块（深层）**，Native LRU 升序选取会**先淘汰浅层块**。

这正是 M1 RC-B 指出的方向问题，也是本候选方法针对的结构信号：

```text
淘汰浅层块 a_1  → 连续前缀从第 1 块即断裂 → 后续全部重算
淘汰深层块 a_m  → 连续前缀保留 1..m-1  → 仅损失后缀
```

⚠️ **band 内方向（头先 vs 尾先）是从 pinned vLLM 源码推出的假设 A1，不是本项目的运行时实测**
（P5 的 `(depth, native_lru_rank)` 对应关系 `NOT_OBSERVABLE`）。本模拟直接把该对应关系作为
**可测量**输出（见模拟器设计文档 §7），并用敏感性臂 S1 量化对假设 A1 的依赖。

### 2.2 支配性定理（candidate v0 的正确性依据）

**设定**：内容身份构成前缀 trie（块 hash 为链式 hash，与 vLLM prefix hash 语义一致）；
一个 band 是一个请求的完整 block 列表，是一条根到叶的链；候选集中的每个块属于唯一 band。

**定理**：固定淘汰数量，把一个 band 内的选择从"较浅优先"改为"较深优先"（跨 band 顺序不变），
则对**任意**未来请求集合与任意返回概率分布，aggregate recomputed tokens **弱不增**。

**证明**：任取未来请求 r。若 r 的路径不经过该 band，其命中深度不受影响。若经过，则 r 与该 band
的交集必为 band 的一个前缀 `1..q`（trie 性质：经过深层块必经过其全部祖先）。设 band 大小为 n，
本决策从该 band 取 k 块：

- 较浅优先（native，假设 A1）：淘汰位置 `1..k`。因 `1 ≤ k` 且 `1 ≤ q`，r 的第一个缺失块为 1
  ⇒ `j_native(r) = 0`。
- 较深优先（candidate v0）：淘汰位置 `n-k+1..n`。r 的路径只含 `1..q`：
  - 若 `q < n-k+1`：路径上无淘汰 ⇒ `j_candidate(r) = q`；
  - 若 `q ≥ n-k+1`：第一个缺失块为 `n-k+1` ⇒ `j_candidate(r) = n-k`。

两种情况均有 `j_candidate(r) ≥ j_native(r)`，且 `recompute(r) = (m_r − j(r) + 1)·B` 随 `j`
单调不增。∎

**与 PR #50 rev.2 的关系**：rev.2 只能给出"固定每链块数"的弱命题且被 RC-C 指出未覆盖共享前缀。
本定理利用**物理 free-event band 结构**（一个 band 就是一条链，共享块随最后所有者入队），
把"每条链被选块数不变"变为**结构事实**而非假设，从而同时覆盖共享前缀（共享根位于 band 头部，
深优先天然保护它）。

**定理不覆盖的情形（必须如实报告）**：

| # | 情形 | 后果 |
| --- | --- | --- |
| X1 | 假设 A1 不成立（band 内 native 顺序本就是尾先） | candidate v0 与 native **同选**，无分歧也无损害（分歧率指标会显示 0） |
| X2 | 淘汰切口落在 band 边界 | victim 集合与 native **逐位相同**（非平凡窗口缺失，见 §4.3） |
| X3 | 单次分配跨多个 band 且前面 band 已被取空 | 定理只约束每个 band 内部，跨 band 分配保持 native 顺序（见 §2.3 键设计） |

### 2.3 精确排序规则（零超参）

对每个合法候选块 b 定义：

```text
lru_rank(b)      : 原生 free queue 位置（0 = 队首 = native 最先选中）   [runtime 可得]
has_block_hash(b): 是否带 APC hash                                      [runtime 可得]
band(b)          : b 当前所在 band 的队列次序 = 该 band 全部块的最小 lru_rank
                   （= 该 band 在原生队列中的位置）                      [模拟可观测]
depth(b)         : b 在其前缀 trie 路径上的 1-based 深度（根 = 1）        [模拟可观测]
tier(b)          : Retention 资格层（TIER_1 / TIER_2）；无 Retention 时恒 TIER_1
```

**选择规则**（需取 R 个 victim）：

```text
Retention 开启 (A3):  key(b) = (tier(b), band(b), −depth(b), lru_rank(b))
Retention 关闭 (A2):  key(b) = (band(b), −depth(b), lru_rank(b))

victims = eligible 按 key 升序的前 R 个
```

性质：

1. **零超参**：没有任何权重、阈值、桶宽；全部键都是结构量。
2. **跨 band 分配不变**：`band(b)` 为主键 ⇒ 与 native 选取同一组 band、同一顺序；
   只有切口 band 内部的方向被反转。这正是 X3 的保证，也是跨链反例
   （热长链 vs 冷短链，PR #50 §3.1）不会击穿本规则的原因：冷链的 band 次序更小，仍先被取。
3. **hashless 保持原生优先**：hashless 块零重算成本，原生已优先选取（F2）⇒ candidate v0
   **不把 hashless-first 当作创新**，只保持该行为不变（band 键对 hashless band 同样适用，
   单个 hashless 块时无内部顺序可反转）。
4. **并列分数**：`(band, depth)` 在 band 内唯一（一个 band 是一条链，深度互异）；
   理论并列由 `lru_rank` 唯一确定，不存在随机 tie-break。
5. **安全回退**：若 `depth`/`band` 不可得（runtime 现状）或机制不适用，
   键退化为 `(lru_rank)` ⇒ **逐位等同于 `NativeLRUAdapter`**（不是 size rule、不是其他策略）。
   该退化由单测 D3 断言（深度置常数后必须与 A0 逐位一致）。

### 2.4 信号清单与运行时可用性（对应 RC-E）

| 信号 | 单位 | 来源 | 更新时间 | 运行时现状 |
| --- | --- | --- | --- | --- |
| `lru_rank` | queue position | 原生 free queue 快照 | 每次 free/acquire | ✅ `EvictionCandidate.lru_rank` |
| `has_block_hash` | bool | 原生块 hash 状态 | 分配/淘汰时 | ✅ `EvictionCandidate.has_block_hash` |
| `tier` | enum | Continuum `EligibilityPreparation` | 每次压力决策 | ⚠️ 只在 Retention 开启时存在（冻结路径已有） |
| `depth` | block index (1-based) | 前缀 trie 路径位置 | 内容分配时确定，不变 | ❌ **模拟可观测；线上需接口扩展** |
| `band` | free-event 次序 | 原生 free event 分组 | 每次 block 释放入队 | ❌ **模拟可观测；线上需接口扩展** |

**最小接口缺口（仅记录，不请求授权）**：若未来要 runtime 化 candidate v0，最小只读扩展是
`EvictionCandidate.depth: int | None` **加上** free-event 分组信息（或等价地"同一入队批次 +
批次内位置"）。`depth` 单独不足以恢复 band 结构（RC-E 已指出单字段不满足 L2-A）。
在取得该能力前，candidate v0 **不得**被称为可部署方法。

### 2.5 失败条件汇总（进报告的证伪清单）

```text
C1  候选集内所有 band 大小 ≤ 1，或切口均在 band 边界      → 与 native 同选（无分歧）
C2  假设 A1 不成立（band 内尾先）                        → 与 native 同选（S1 量化）
C3  未来请求不复用被保留的浅层前缀                        → 保留浅层无收益（负对照 G 族测量）
C4  Retention 使候选集收缩到非平凡窗口消失                → 组合无增量（A3 vs A2 测量）
C5  深块内容恰是唯一被复用的部分（共享 DAG 中反例）        → 定理前提被违反；由 S3 族 + 分歧归因检测
```

---

## 3. Continuum Retention 层（复用冻结实现，不新造）

### 3.1 复用清单（全部为冻结 Phase 1B 组件，直接调用，不修改）

| 职责 | 复用实现 | 语义 |
| --- | --- | --- |
| Agent/program 生命周期 | `continuum.events` + `RuntimeCoordinator.handle` | ProgramStarted/Arrived/Admitted/FollowupWaiting/Cancelled/ToolGap/TurnFinished/BlocksObserved/BlockEvicted |
| 工具间隔历史 | `ServerGapHistory` / `ExternalToolDurationHistory` | finish→next-arrival gap，按 tool_type 分桶 |
| 动态 TTL | `estimate_ttl`（`continuum.ttl`） | `argmax_τ F(τ)·(T·η + R) − τ`；COLD_START/GLOBAL/TOOL_SPECIFIC 分层 |
| 软保留 / 保护状态 | `RetentionManager`（`protected` / `waiting_followup` / `expire_due` / `admit_followup` / `cancel_followup` / `complete_program`） | 惰性过期；waiting 程序不普通过期 |
| 压力释放 | `RetentionAwareSelectionCoordinator.prepare`（`continuum.pressure`） | Tier 1（无 hash / 无受保护所有者）→ 循环释放 `(deadline, min newly-eligible lru_rank, key)` 直到 `min(required, len(queue))` |
| 共享所有权 | `_entries_by_block` + `_newly_eligible_blocks_after_release` | 块仅在**全部**所有者释放后变为可回收；共保护块的零边际释放被如实记录 |
| 释放提交 | `commit_pressure_releases` + `observe_eviction` | 逻辑解除保护与物理淘汰分开记账 |
| 冻结 LRU 基线臂 | `RetentionAwareLRUAdapter`（A1 臂直接使用该类，保证逐位忠实） | `(tier, lru_rank)` 序 |

### 3.2 Retention 层负责什么（明确边界）

```text
Retention 层决定：
  (a) 哪些缓存内容仍受保护            → entry.protected（waiting / TTL / 未释放）
  (b) 哪些物理块当前可参与正常淘汰     → Tier 1 = 无 hash 或全部所有者已释放/过期
  (c) 未保护块不足时如何释放软保护     → 冻结循环：按 (deadline, min rank, key) 整块释放
  (d) 释放后哪些块新变得可回收         → PressureReleaseEffect.newly_eligible_block_ids
Ours-Evict 层决定：
  (e) 在 (a)-(d) 产生的合法候选集中选哪些块做 victim
```

**禁止混淆**（对应任务 §二）：(c) 的逻辑释放 ≠ (e) 的物理淘汰 ≠ 未来重计算。
本模拟中三者分别记账：`pressure_releases`（Q1）、`physical evictions`（Q2）、
`recomputed tokens`（Q3），互不派生。

### 3.3 Retention 在模拟中的可观测效果（必须能观察到才算实现）

1. 保护生效：tool gap 期间受保护块不被普通淘汰；
2. 自然过期：非 waiting 程序到期 `expire_due` / coordinator `ordinary_expired`；
3. 压力强制释放：`pressure_releases` 非空；
4. 共享所有权导致的释放差异：共保护块只在最后一个所有者释放时进入 Tier 2（零边际释放可见）。

---

## 4. 实验臂、oracle 与判别臂

### 4.1 主对照臂（同一 trace / 容量 / block size / 事件时间 / 初始条件 / 种子）

| 臂 | Retention | Victim 选择 | 说明 |
| --- | --- | --- | --- |
| **A0** | 关 | `lru_rank` 升序（原生） | native 基线 |
| **A1** | 开（冻结路径） | `RetentionAwareLRUAdapter`（`(tier, lru_rank)`） | Retention 独立增量（**直接复用冻结 adapter 类**） |
| **A2** | 关 | candidate v0：`(band, −depth, lru_rank)` | Ours-Evict 独立运行 |
| **A3** | 开 | candidate v0：`(tier, band, −depth, lru_rank)` | **目标组合** |
| **A4** | 开 | 同 A1 + `ContinuumSchedulingPolicy` 准入次序 | 可选 Full-Continuum 系统参照，**单独报告**，不进组件对比 |

### 4.2 Oracle 对照（研究参照，**不是** Ours-Evict）

```text
O1  oracle-evict（无 Retention）：合法候选集中，按"未来再次使用距离"降序淘汰
    （不再使用 = ∞；Belady/MIN 风格）。使用未来 trace，仅评估器可用。
O2  oracle-evict + Retention：合法集由冻结资格决定，oracle 只在合法集内选择。
```

⚠️ O1/O2 **不得**被称作 Ours-Evict，其结果**不得**当作真实策略可取得的收益；
它只估计"完美 victim 选择"的 headroom（且 Belady 风格不保证严格最优，报告为估计值）。

### 4.3 非平凡窗口与判别臂（对应精修补丁 §3）

```text
平凡事件  : |EligibleCandidates| == required_blocks → 任何重排序选出同一集合
非平凡事件: |EligibleCandidates| >  required_blocks → victim 集合可能真实分歧
```

工作负载必须覆盖非平凡窗口，两类来源：

1. **Unpin overshoot**：压力释放解绑某 Entry 后释放出 M 个候选块，但当前仅需淘汰 K < M 个；
2. **多条未保护链并存**：候选池中同时存在多个未保护 band，切口落在某个 band 内部。

报告单列：**非平凡淘汰事件占比**、**Victim Set 真实分歧率**
（`VictimSet_A2 != VictimSet_A0`、`VictimSet_A3 != VictimSet_A1`，按淘汰事件计）。

判别臂（机制链诊断，不进主对比结论）：

| 臂 | 定义 | 预期 | 用途 |
| --- | --- | --- | --- |
| **D1** | candidate v0 方向反转（`+depth`，即 band 内浅层优先） | **实测：与 A0 逐位相同**（70/70 draws 每个决策的 victim 序列完全一致）⇒ 证实"原生 band 内顺序本就是浅层先淘汰"，即 candidate v0 所反转的正是原生方向 | 模型验证（对应 PR #50 A4 的方向判别；结果为正向验证而非劣化） |
| **D3** | `depth` 置常数（退化回 `lru_rank`） | 必须与 A0 **逐位一致** | 来源判别（对应 PR #50 A5） |
| **S1** | 全 campaign 重跑，free-order 假设翻转为尾先 | A2 与 A0 分歧率应降为 ~0 | 假设 A1 敏感性 |

### 4.4 机制验证链（四层，对应任务 §七）

```text
L1 候选合法   : victims ⊆ eligible、|victims| = R、无重复、满足 required_blocks
L2 决策不同   : 与 native 比较 victim ID 集合（不是顺序）
L3 物理改变   : cache mapping / 连续命中 / 后续可复用状态改变
L4 重计算改变 : 同一未来 trace 重放，aggregate recomputed tokens 改变
增量归因      : A0/A1（Retention 增量）、A2/A3（Retention 增量）、A0/A2 与 A1/A3（驱逐增量）
失败归因      : 未触发 / 未实现 / 机制失败 / 有效但不可用（见模拟器设计文档 §8）
```

**首次分歧反事实分支**：对 (A0,A2) 与 (A1,A3) 两对，逐 scenario 做 lockstep 双run，
在**第一个 victim 集合分歧的决策点**分支：从该状态出发用同一策略分别续跑，
用 `ΔR = Σ_r B·max(0, j_branchB(r) − j_branchA(r))` 计量**那一次决策**的因果效应。
这避免了"状态已分歧后按 index 对齐"的伪因果。

---

## 5. 指标口径（与 Phase 2E 冻结合约对齐的部分显式标注）

请求级（每个 measured request r）：

```text
N_r = prompt tokens（含非对齐尾块）
M_r = 完整 block 数 = floor(N_r / B)
E_r = eligible prefix tokens = LCP(r, 所有更早请求) · B      # 内容曾在更早请求出现才算可复用
C_r = j(r) · B，j(r) = 最长连续命中前缀深度（严格截断，见模拟器设计 §4.2）
recomputed_r = E_r − C_r                                        # = A1.1 的请求级分量
```

场景级（统计单位 = 独立 scenario draw）：

| 指标 | 定义 | 对应 |
| --- | --- | --- |
| `aggregate_recomputed_tokens` | Σ_r recomputed_r | A1.1 |
| `aggregate_delta_tokens` | Σ_r (rec_armB − rec_armA)（配对） | A1.7 |
| `gross_request_level_change` | Σ_r \|Δ_r\| | A1.8 |
| `NGR` | \|ΣΔ\| / Σ\|Δ\|；Σ\|Δ\|=0 → `NOT_APPLICABLE_ZERO_GROSS` | A1.9 |
| `cache_reuse_efficiency` | Σ C_r / Σ N_r | A1.5 |
| `physical_eviction_count` | 带 hash 块被真实移除的次数 | A3 环节 4（模拟内可解析内容身份） |
| `hashless_reuse_count` | 无 hash 块被直接重用次数 | — |
| `live_cached_blocks/tokens` | 期末仍在 cache mapping 中的内容量 | — |
| per-agent 分布与尾部 | 每 draw 内先算分位再跨 draw 配对（I 视图） | A2.1/D-vs-I |
| `nontrivial_eviction_share` | \|eligible\| > required 的淘汰事件占比 | 精修补丁 §3 |
| `victim_set_divergence_rate` | A2!=A0、A3!=A1 的淘汰事件占比 | 精修补丁 §3 |
| `first_divergence_delta_R` | 首次分歧决策的因果 ΔR（反事实分支） | 任务 §七.4 |
| 决策开销 | 每次策略决策的候选扫描/排序操作数 + CPU 时间 | experiment-plan |
| TTFT/TPOT/吞吐 | **NOT_MEASURED**（模拟不执行真实模型） | 显式标注 |

Retention 专项：受保护 block/token 量及持续时间；保护期间实际再次复用比例；
保护后未复用而占用的容量；自然 TTL 过期次数；压力强制释放次数；
共享块因其他 owner 仍受保护而不可回收的次数；cold-start 与 warm-start 差异。

统计：配对 bootstrap 95% CI（10,000 次，种子随配置记录）；报告均值/中位数/分布/
无收益（Δ=0）与退化（Δ>0）的 draw 数；请求数/回合数/决策数**不**作为独立样本。

---

## 6. 研究问题与预期判据

> 在贴近 Agent 多轮工具调用的缓存工作负载中，Continuum 的动态保留与压力释放是否能为独立的
> Cost-Aware block eviction 提供额外收益？增益来自更合理的物理 victim 选择、延长有效复用，
> 还是仅仅源于候选集变化？收益在什么场景存在、什么条件下消失？

判据（预先登记，避免事后叙事）：

```text
H-attr-1  A2 < A0（aggregate recomputed tokens，配对）且 victim 分歧率 > 0
          ⇒ 增益来自物理 victim 选择（band 内深优先）
H-attr-2  A1 < A0 且 A3 < A2 同向改善
          ⇒ Retention 提供独立于 victim 规则的增量（候选集收缩 + 延长有效复用）
H-attr-3  A3 ≈ A2 但 A3 的候选集显著小于 A2
          ⇒ Retention 只改变候选集、未降低重计算（如实记录为无增量）
H-null    负对照族（G）允许 Δ = 0 或 Δ > 0（策略成本）；不得预设受益
```

---

## 7. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 冻结 4 字段 candidate / native LRU 升序 | `src/kvopt/runtime/vllm/types.py`、`adapter.py:27-39` |
| hashless 优先是原生行为 | M1 RC-A（vLLM v0.27.1 `block_pool.py` L719–742、L647–667） |
| band 内头先入队假设 A1 | 同上（`append_n(blocks_with_hash)` 保持 block table 顺序）+ Phase 2C 87/87 连续带；方向未经 P5 实测 || Q1/Q2/Q3 分离、ΔR 公式 | M1 RC-D；PR #50 §2 |
| 冻结压力释放键与 Tier 语义 | `src/kvopt/continuum/pressure.py:300-324`、`selection.py` |
| 共享块全释放后才可回收 | `pressure.py:260-278`；`tests/test_continuum_pressure.py:277-290` |
| 冻结 TTL 目标与冷启动 concretization | `continuum/ttl.py:63-78`、`ttl.py:27-34` |
| PrefillReload 正式 profile | `docs/experiments/phase1b-continuum/artifacts/prefill-reload-profile-formal-20260920T045859Z-6183d106.json` |
| Phase 2E 指标口径与统计单位 | `docs/phase2e-m4-task-a-metrics-freeze.md` §1–§3 |
| 不得向 continuum 添加 cost-aware 评分 | `docs/phase2a-m4-block-level-design-draft.md` §7 |
| PR #50 当前 verdict | PR #50 review（`CHANGES_REQUESTED`，RC-A~RC-E） |
