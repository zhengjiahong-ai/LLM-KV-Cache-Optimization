# Ours-Evict — Algorithm Design（rev.2）

**提交人**：M4　**送审**：M1　**日期**：2026-10-15
**阶段**：Phase 2 Cost-Aware Eviction 算法设计（**设计 PR，不含 runtime 实现**）
**主目标**：`aggregate_recomputed_tokens`　**辅助观测**：TTFT / queue delay
**边界**：不改 native BlockPool / ref_cnt / hash cleanup / LRU，不改冻结 Continuum baseline，B1 保持 LOCKED，不实施 runtime

> **rev.2 说明**：本文响应 M1 对 PR #50 的 `CHANGES_REQUESTED`（RC1–RC7）。
> rev.1 的 `credit/damage` 公式被**整体撤回**（§0.2）；rev.1 隐含的「全局深优先」被**主动撤回**（§3.1）。
> 两处撤回都改变了设计的形态，因此本文是**重构**而非修订稿。

---

## 0. rev.2 变更摘要

| RC | v1 的问题 | 处置 |
| --- | --- | --- |
| **RC1** | 层级错位：v1 实际是 Continuum **entry-level pressure release**，不是冻结的 block-level `Ours-Evict` | §0.1 裁定采用**方案 A（block-level）**；entry-level 改名 `Cost-Aware Pressure Release`，**只作离线 harness**，不属 Ours-Evict |
| **RC2** | `damage` 无物理语义：仍被他人保护的块**根本不会被淘汰**，不构成损伤 | §0.2 **撤回该公式**；§2 重建成本模型（区分 Q1/Q2/Q3），只对**将被淘汰的块**建模 |
| **RC3** | 「低 damage 高 credit 更优」无依据 | §3 **撤回全局深优先**并给出**跨链反例**；§3.2 给出可证明的**弱命题**；§3.3/§3.4 给出可手工复核的正例与反例 |
| **RC4** | 与 replay 接口兼容性判断错误 | §6 核实 `replay.py:252` 确有 `del state`；结论改为 **state-aware `ReleaseStrategy`**，不塞进静态 `CandidateRule` |
| **RC5** | 退化/消融/证伪设计有逻辑错误 | §5 逐条修正；证伪改为**四层机制链 + 失败归因表** |
| **RC6** | F4 使用边界 | §4.4 严格保持 M1 既定边界 |
| **RC7** | X1–X3 | §7：**X1 撤回**（视图已存在）；X2 原则允许但不预授权扩张；X3 同意并已执行 |

### ⚠️ 两个必须前置的诚实结论

**结论 1（RC1 事实核实）**：冻结的 block-level 边界**只暴露 4 个字段**：

```text
EvictionCandidate = { block_id, ref_cnt, has_block_hash, lru_rank }
EvictionContext   = { required_blocks, free_blocks, total_blocks, timestamp }
```

⇒ 该边界**不含**深度、owner、内容身份等成本信号。
v1 让算法读 `block_ids` / `owners_by_block`，那是 **replay 层（离线）** 的产物，
**不在 runtime 输入里** ⇒ v1 隐含假设了一个**不存在的观测缝**。这是 v1 的架构错误根源。

**结论 2（§3.4 的推断，需 P5 数据验证方向）**：**在单条 hash 链内部，LRU 很可能已经近似等于"深度降序"。**
推理链：APC 命中长度为 L 的前缀时**链上 1..L 的块同时被刷新**（Phase 2C/2D 实测的连续带 87/87 与之一致），
故浅块被刷新的次数**不少于**深块 ⇒ 浅块不会相对更旧 ⇒ LRU **倾向先淘汰深块**。

⚠️ **这是一条推断**（依赖 APC 刷新语义 + 观测到的连续性），**尚未直接测量方向**。
§3.4 的分离条件 C3 与 §6.3 的验证步骤**就是为检验它而设**。
若 C3 不成立（即 recency 与 depth 不分离），**Layer 2 应放弃**。

⇒ 这两点共同把设计收敛为：**Layer 1 是当前唯一可证明、可立即实现的增益；Layer 2 是有条件的假设。**

---

## 0.1 RC1 — 决策边界裁定（**BLOCKING，已裁定**）

### 裁定：采用**方案 A（block-level）**作为 Ours-Evict 的正式边界

M1 指正成立。已核实冻结路径：

```text
src/kvopt/runtime/vllm/adapter.py:11
    class EvictionPolicyAdapter(ABC):
        def select_victims(self, candidates: Sequence[EvictionCandidate],
                           context: EvictionContext) -> Sequence[int]
        """Choose block-level victims without mutating vLLM cache state directly."""
```

### 准确的输入 / 输出 / 执行位置 / 下游 / 比较层级

| 项 | 值（已核实到源码） |
| --- | --- |
| **算法类** | `EvictionPolicyAdapter`（`src/kvopt/runtime/vllm/adapter.py:11`） |
| **输入 1** | `Sequence[EvictionCandidate]` = `{block_id, ref_cnt, has_block_hash, lru_rank}`（`runtime/vllm/types.py`） |
| **输入 2** | `EvictionContext` = `{required_blocks, free_blocks, total_blocks, timestamp}` |
| **输出** | `Sequence[int]` = **victim block IDs，按淘汰顺序**；**必须唯一、必须取自 candidates** |
| **约束** | **不得** mutate vLLM queue / block metadata |
| **下游** | `BlockPool.get_new_blocks()` 取块 → `_maybe_evict_cached_block()` 对带 hash 的块做真实 hash cleanup |
| **比较层级** | `NativeLRUAdapter` vs `OursEvictAdapter`，**同一 candidates / context** |
| **评测** | block-level 淘汰顺序 → 既有 replay / eligibility → `aggregate_recomputed_tokens` |

### entry-level 设计的定位（**不属于 Ours-Evict**）

v1 描述的对象（`FORCED_RELEASE_DECISION.payload.candidates`）属于**另一个决策边界**：

```text
B. Continuum retention pressure release —— 决定先解除哪些 protected logical entries 的保护
```

本设计将其保留、改名 **`Cost-Aware Pressure Release`**，**只用作离线机制评估 harness**
（验证「共享结构下是否存在可被利用的边际差异」）。

⛔ **不作为 Ours-Evict 的提交物。** 若 M1 认为该边界本身值得作为研究范围，
需 M1 正式批准范围变更后另立设计。

---

## 0.2 RC2 — 撤回 v1 的 `credit/damage` 公式

**v1 定义**：`credit(i|S)` = 释放 i 后新增可回收块；`damage(i|S)` = i 中仍被其他 entry 持有、未变为可回收的块；`score = damage/(1+credit)`。

**该定义在语义上不成立**，三点：

1. **`damage` 不是损伤。** 仍被其他 owner 保护的共享块**根本不会被物理淘汰**，也不产生重计算。
   M1 的算例完全正确：释放 A 后 8 个共享 root 仍被 B 保护，它们安然存在，A 还能继续复用。
2. **`damage` 方向可能相反。** 若这些共享块是关键共享内容，则「释放 A 不动它们」是**好事**，
   而 v1 记为 8 分「损伤」并**惩罚** A ⇒ 惩罚方向可能错。
3. **该比值无判别力（我推导后发现的新问题）。** 在 eligibility 语义下 `newly_eligible_after(i)`
   恰好是「i 的私有块」，`damage` 是「i 的共享块」，故 `credit + damage = |B_i|` 恒成立：

   ```text
   score = damage/(1+credit) = (|B_i| − credit)/(1 + credit)
   ```

   这是 `credit` 的**单调递减函数** ⇒ **与 v1 的 A1「credit 降序」是同一个排序**，
   不是独立机制；v1 的 A1/A3 消融**根本无法区分**。

⇒ `credit/damage` **整体撤回**，v2 不保留任何形式。

---

## 1. 优化目标、决策对象与流程

### 1.1 优化目标

```text
主目标   : minimize aggregate recomputed tokens（冻结统计单位 = scenario draw）
硬约束   : 输出恰好满足 context.required_blocks 个 victim（不得多、不得少）
辅助观测 : TTFT / queue delay（仅观测，不要求同步收益）
```

依 M1 裁定：**以 block 数 / token 数作成本代理完全合理**，前提是代理量具有**正确的物理与算法语义**（§2）。

### 1.2 决策对象

```text
输入 = 已经合法可淘汰的 cached blocks（EvictionCandidate 序列）
输出 = 这些 block 中应优先淘汰的 block_id 序列
算法不改变合法性；合法性仍由 vLLM 的 free queue + hash 状态决定
```

### 1.3 单次决策流程（block-level）

```text
输入: candidates, context(required_blocks = R)
1. 分区:
     F = { b : not b.has_block_hash }        # 不可复用，零成本
     H = { b : b.has_block_hash }            # 可复用，有未来重算风险
2. 若 |F| >= R: 在 F 内按 lru_rank 升序取 R          # 全部零成本
3. 否则: 先取完 F；再从 H 中按 §2.4 的顺序取 (R − |F|) 个
4. 输出: 上述顺序拼接（唯一、取自 candidates）
```

**注意**：第 2、3 步都只是**重排 `candidates` 的子集**，不新增、不删除候选，符合 adapter 契约。

---

## 2. 成本模型（RC2 修正）

### 2.1 必须区分的三个量（M1 要求）

| # | 量 | 含义 | 等于重计算？ |
| --- | --- | --- | --- |
| **Q1** | Logical protection released | 解除了哪些 logical entry 的保护 | ❌ |
| **Q2** | Physical cached blocks evicted | 实际被 hash cleanup 的块 | ❌（但**是** Q3 的必要条件） |
| **Q3** | Future recomputed prefix tokens | 未来请求因缓存缺失而重算的 token | ✅ **主目标** |

⇒ **Q1 ⇏ Q2 ⇏ Q3**。本设计的成本模型**只对 Q2 建立**，并把 Q2 → Q3 的映射写成**显式假设**（§2.2）。

### 2.2 vLLM APC 语义（成本模型的唯一依据）

仓库既有事实（`docs/phase2b-m6-experimental-fidelity-repair-spec.md` §1）：

> APC 查找要求**可匹配的连续前缀**；正常全命中请求仍需重新计算最后 token。

设某未来请求的缓存前缀为 `p₁…p_m`（块序列），且

```text
j(r) = min{ k : p_k 已被淘汰 }        （若均未淘汰则 j(r) = m+1）
```

则

```text
recompute(r) = (m − j(r) + 1) × block_size_tokens
```

**关键结构性结论**：`recompute(r)` **只由 r 链上最浅的已淘汰块决定**。
淘汰深（靠尾）的块几乎不增成本；淘汰浅（靠根）的块会截断整条后缀。

### 2.3 β — 每块的真实淘汰成本（Q2 层）

单个淘汰动作的增量成本为

```text
Δrecompute = Σ_r [ j(r) 因本次淘汰而变小 ] × (m_r − j(r) + 1) × B
```

故定义 `β(b) = E[ 淘汰 b 之后未来因此增加的重算 token ]`。

⚠️ **β 不可在决策时精确求出**（依赖未来请求）。本设计**不预测未来**，
只使用**决策时可得、且与 β 单调相关的结构代理**，并在 §3 用可复核算例证明代理的**适用条件与边界**。

### 2.4 两层结构代理

#### Layer 1 — 可复用性闸门（**可证明，零新信号，可立即实现**）

```text
β(b) = 0   when not b.has_block_hash
```

**可证明**：无 hash 的块没有 cached content，APC **无法匹配**它 ⇒ 淘汰它**不增加任何重算**。
⇒ **优先淘汰 F** 在任何未来请求序列下**弱不劣于**先淘汰可复用块。

⚠️ 生效条件：仅当 `candidates` 内**确实含**无 hash 块；否则 Layer 1 为空操作。

#### Layer 2 — 链内深度次序（**有条件，需一个只读字段，且需先验证分离条件**）

⚠️ **先给结论**：由 §3.1 的反例与 §3.2 的推导，

```text
深度**不能**作为全局主键（会被跨链反例击破）
深度**只能**在"同一 hash 链内部"改变次序，且**跨链分配必须保持不变**
```

因此 v2 的 Layer 2 形态是**链内后处理**，不是全局重排：

```text
形态 L2-A（"同链退避"；仅需链身份 + 链内相对序）
    主键: lru_rank（保留 vLLM 热度语义）
    后处理: 在已由 lru_rank 选出的 R 个块中，若某条链被选中 >= 2 个块，
            则把该链**更深**的块提前、并优先换入该链**更深**的落选块
    ⇒ 只改"同一链内部谁先走"，**不改跨链分配**

形态 L2-B（"桶内降序"；需绝对深度 d）
    主键: lru_rank 的**分层桶**
    桶内: d(b) 降序
    ⇒ 仍不动跨桶（≈跨热度）分配
```

⚠️ **Layer 2 依赖 `d(b)`（或至少「链身份 + 链内相对序」），该信息目前不在 `EvictionCandidate` 中**（§6.3）。
在取得前，本设计**只交付 Layer 1**。

⚠️ **并且必须写明**：由**结论 2**（§0），链内 LRU 很可能**本就近似深度降序**，
⇒ L2-A/L2-B 的**预期增量有限**，其价值集中在**recency 与 depth 分离**的情形。§3.4 给出该分离条件。

---

## 3. 方向论证（RC3）

### 3.1 ⚠️ 一个**不成立**的强命题（我主动撤回）

rev.2 初稿曾提出并"证明"：

> ~~固定候选集与 R，按 `d(b)` **全局降序**淘汰，则每个未来请求的 `j(r)` 都不劣于任何其它顺序。~~

**该命题为假。跨链反例：**

```text
候选: 链 α（L=10 块，很热，rα 很可能返回）
      链 β（L=2  块，很冷，rβ 很少返回）
R = 2
全局深优先 : 淘汰 α10, α9   -> j(rα)=9   -> recompute(rα) = (10-9+1)B = 2B
按链长     : 淘汰 β2,  β1   -> j(rα)=11  -> recompute(rα) = 0
                               j(rβ)=1    -> recompute(rβ) = (2-1+1)B = 2B
```

⇒ 两者的 `Σ recompute` 取决于两条链**各自的返回概率**。若 `rα` 大概率返回、
`rβ` 几乎不返回，**全局深优先更差**。

**结论**：不存在"只看深度即可全局占优"的顺序。**深度不能凌驾于 recency 之上**。
`lru_rank` 编码的正是**链路热度**，且是 runtime **唯一可得**的热度信号 ⇒ **必须保留为主序**。

⚠️ 该反例**即为 RC3 所要求的反例案例**，并在 §3.4 形式化为失效条件。

### 3.2 修正后的方向论证（分层键）

**可证明的部分（弱但正确）**：

> **固定**「每条链被选中的块数」不变时，把某条链 γ 的选择从**较浅优先**改为**较深优先**，
> 则 `j(rγ)` **不减小**（可能增大），故 `recompute(rγ)` **不增**；且对其它链的请求**无影响**。

**证明**：设链 γ 有块 `p₁…p_L`，被选中 k 个且 k 不变。选较深者 ⇒ 选中的**最小位置更大** ⇒
`j(rγ)` 更大或相等。`recompute(rγ) = (L − j(rγ) + 1)B` 随 `j` **单调不增**。
其它链选块集合未变 ⇒ 其 `j` 不变。∎

⇒ 这是**「链内截尾」的正确性依据**，而**不是**全局深优先。
⚠️ 前提（**每条链被选中块数不变**）正是 L2-A/L2-B 强制保持的；
一旦允许深度改变跨链分配，§3.1 的反例立即生效。

### 3.3 正例（可手工复核）— Layer 1

**设定**（`block_size_tokens = 16`）

```text
候选（已合法可淘汰）:
   u1 : has_block_hash = False      （新分配、尚未进入 hash 链 ⇒ 不可复用）
   a1, a2, a3, a4 : has_block_hash = True，构成链 α，d = 1,2,3,4
lru_rank（升序 = 最冷优先）: a1 < a2 < a3 < a4 < u1     （u1 刚变为 free，rank 最大）
required_blocks R = 1
未来（决策时未知，仅供评审复核）: 请求 rα 需要链 α 全部 4 块
```

| 顺序 | 淘汰 | j(rα) | recompute(rα) | **合计 tokens** |
| --- | --- | ---: | ---: | ---: |
| **NativeLRUAdapter**（`lru_rank` 升序取 1） | `{a1}` | 1 | (4−1+1)×16 = **64** | **64** |
| **Ours-Evict（Layer 1）** | `{u1}` | 5（未淘汰） | **0** | **0** |

⇒ Layer 1 把合计从 **64 降到 0**，且**不依赖任何未来信息**、**可手工复核**。
（关键：LRU 只看 `lru_rank`，而 `u1` 虽不可复用却不是最冷的，故被跳过。）

⚠️ **真实感检查**：`u1` 的 `lru_rank` 较大是**合理且常见**的——无 hash 块通常是**新分配**的，
其最后一次使用时间最近。因此该情形**不是人为构造**。

### 3.4 反例与失效条件

**反例 1（跨链，§3.1）**：全局深优先在「热长链 vs 冷短链」下可能更差。
⇒ **失效条件 C1**：深度被用作**跨链**主键。

**反例 2（链内 LRU 很可能已近似深度序 —— 即"结论 2"）**：

```text
设链 α 的 3 个块 a1(浅) a2 a3；链 α 最近被某请求命中 ⇒ **其全部块同时刷新**
⇒ lru_rank 序 ≈ a1 < a2 < a3（浅者更旧）
⇒ NativeLRU 已会**先淘汰 a3**（最深）
⇒ 此时 Layer 2 **与基线逐位同选**，无增量
```

⚠️ 方向（浅者更旧）是**推断**，须由 P5 数据验证。

⇒ **失效条件 C2**：候选集**只含单链**，或各链的 `lru_rank` 序**恰好与深度序一致**
（recency 与 depth **不分离**）。

**分离条件 C3（Layer 2 有意义的前提）**：存在至少一条链，其块的 `lru_rank` 序与深度序
**不一致**。可能来源：部分命中（只刷新前缀一部分）、多链交错使 rank 交叉、跨链重分配边界。
**该条件必须在实现 Layer 2 之前用 P5 数据检验**（§6.3）。

⚠️ **另一类明确局限**：**深度相同而共享度不同**时（同样 d 但引用该链的未来请求数不同），
本模型**不使用**引用度（runtime 不可得）⇒ 该情形下可能不如能预测复用度的策略（§5.5 L2）。

---

## 4. 与既有规则及研究的机制对比

### 4.1 与 H1 既有规则（**边界不同，不可直接比**）

| 项 | H1 规则族 | Ours-Evict v2 |
| --- | --- | --- |
| 决策边界 | Continuum entry-level release | **vLLM block-level victim** |
| 打分对象 | logical entry | physical block |
| 输入 | `DecisionCandidateRow`（含 `block_ids` 等） | `EvictionCandidate`（仅 4 字段） |
| 是否同一算法 | — | **否** |

⇒ **必须分开报告**：不得把 H1 的「规则无增益」当作 Ours-Evict 的既有否定证据；
反之也不得把 Ours-Evict 的增益归给 H1 规则族。

### 4.2 与 `NativeLRUAdapter` 的机制差异（诚实版）

```text
NativeLRUAdapter : sorted(candidates, key=lru_rank)[:R]
Ours-Evict       : ①Layer 1: 先取全部 hashless 块（零成本）
                   ②Layer 2: **仅在同一链内**按深度重排（不动跨链分配）
```

**差异的诚实分级**：

| 层 | 差异性质 | 证据强度 |
| --- | --- | --- |
| **Layer 1** | **可证明弱占优**（hashless 淘汰不增加重算） | ✅ **定理 + 可复核算例** |
| **Layer 2** | **有条件的局部改进**；链内 LRU 很可能已近似深度序 ⇒ 增量限于分离条件 C3 | ⚠️ **假设，需实测分离度** |

⚠️ **不等同于**「Ours-Evict 用深度替换了 LRU」。真实说法是：
**Layer 1 增加了一个 LRU 完全不看的维度；Layer 2 只是在 LRU 内部做次序校正。**

### 4.3 与 RR-EVICT 的关系

| 维度 | RR-EVICT | Ours-Evict v2 |
| --- | --- | --- |
| 粒度 | 跨 agent 轮转 **tail chunk**（entry/子 entry） | **block**（adapter 边界） |
| 目标 | 尾部 TTFT / 尾部 uncached | **aggregate recomputed tokens** |
| 机制 | 分散淘汰以均衡尾部损失 | hashless 优先 + 链内截尾 |
| 前提 | 需 idle/active 区分、子 entry 释放 | **不需要**，也**不需要 B1 解锁** |

⛔ **重叠部分（「截尾/保根」这一直觉）不主张为创新**——它在早期 B1 草案
（`docs/phase2a-m4-block-level-design-draft.md` §4）中已被推导，RR-EVICT 亦含此直觉。
本设计的可主张之处**仅在于**：把它落到**冻结的 block-level adapter 边界**、以**最小字段**实现，
并给出**可证明的 Layer 1** 与**明确标注条件的 Layer 2**。

### 4.4 RC6 — F4 / Phase 2D 历史证据的使用边界（严格保持）

```text
F4 odd draws 01/03/05 : SHARED_ROOT treatment，所需物理淘汰机制 NOT_REALIZED
F4 even draws 02/04/06: NO_SHARED_PREFIX_NEGATIVE_CONTROL（已观察到的非零改善来自这里）
```

⇒ **不得**把旧 F4 的改善当作本算法共享机制的证据。
**可以**复用的是其 **workload 构造方式**（共享根 + 私有尾部）作为 §5 的 fixture 模板。

Phase 2D E2/E3 边界同样保持：

```text
已证明: 真实共享保护可构造；不同 logical release 可导致个别请求重算差异
未证明: 该差异必然改善 aggregate recomputed tokens
未证明: 决策时可识别更优选择
```

⇒ 它们**是设计依据，不是有效性证明**。

---

## 5. 最小案例、消融与验证（RC5 修正）

### 5.1 修正「无共享时的退化行为」

**v1 错误**：「无共享 ⇒ 退化为 size rule」。
**v2 修正**：v2 的输入里**没有「共享」这个概念**（runtime 不可得），故该问题对 v2 不成立。

v2 真正的退化条件是**深度信息不可用或不可比**：

```text
若 d(b) 不可得（depth=None）或全部相同
  ⇒ Layer 2 主键并列 ⇒ 完全由 lru_rank 决定
  ⇒ 算法 **逐位等同于 NativeLRUAdapter**（不是 size rule）
```

⇒ **退化目标是 `NativeLRUAdapter`，不是 `M1_block_count_ascending`。**

### 5.2 修正消融臂（替换 v1 的 A1/A4）

| 臂 | 定义 | 比较对象 | 预期 |
| --- | --- | --- | --- |
| **A0** | `NativeLRUAdapter` | 基线 | — |
| **A1** | **仅 Layer 1**（hashless 优先 + `lru_rank`，**无 d**） | A0 | ✅ **≥ A0**；含 hashless 时严格更优 |
| **A2** | **仅 Layer 2**（链内深度重排，**不优先 hashless**） | A0 | 仅在**分离条件 C3** 成立时更优；否则 ≈ A0 |
| **A3** | **完整**（Layer 1 + Layer 2 + `lru_rank`） | A0, A1, A2 | 最佳 |
| **A4** | **链内深度方向反转**（链内浅优先） | A3 | ⭐ **应劣于 A3**（方向判别） |
| **A5** | **深度全部置常数**（d ≡ 1） | A3 | ⭐ **应逐位等同 A0**（来源判别） |
| **A6** | A3 但去掉 `lru_rank`（改 identity 作 tie-break） | A3 | 应**显著劣于** A3（验证 §3.1 反例：不能丢热度） |

⭐ **A4 / A5 / A6 是核心判别臂**：

- **A4** 检验**链内方向**是否有意义（v1 的 A1/A4 比较对象是错的，此处已校正）；
- **A5** 检验**信息来源**——若 A5 仍优于 A0，则增益来自别处（如 tie-break 偶然），机制不成立；
- **A6** 检验**热度主序的必要性**——预期明显变差，这正是 §3.1 反例的实证。

⚠️ 依 M1：**A5 不设为「必须完全等于 A0」的绝对必要条件**，而是：
若 A5 ≠ A0，**必须归因到具体排序差异**方可继续（§5.4）。

### 5.3 四层验证链（替换 v1 的「未观察即证伪」）

```text
第 1 层  算法是否产生**合法且不同**的选择？
        证据: 输出 ⊆ candidates、|输出| = R、无重复；且与 A0 序列**不同**
        不通过 ⇒ 问题在**触发条件**（无 hashless / 无分离），不是机制错误
第 2 层  不同选择是否改变**物理缓存状态**？
        证据: 淘汰后存活块集合不同（由既有 replay / eligibility 计算）
        不通过 ⇒ 问题在**物理淘汰未发生**，不是机制错误
第 3 层  物理状态变化是否改变 **aggregate recomputed tokens**？
        证据: 同未来请求序列下 Σ recompute 不同
        不通过 ⇒ 可能是**成本模型选错**（真失败）
第 4 层  改变方向是否与主张一致？
        证据: A4 劣于 A3、A6 劣于 A3
```

**失败归因表**（M1 要求区分「机制有效 / 未触发 / 机制失败」）：

| 观察 | 归因 | 处置 |
| --- | --- | --- |
| 第 1 层不过 | **未触发** | 调整 fixture 使 hashless 或分离条件出现；机制未受检验 |
| 第 1 层过、第 2 层不过 | **未实现** | 检查是否发生真实 hash cleanup；机制未受检验 |
| 第 1、2 层过、第 3 层不过 | **机制失败**（成本模型错） | 修订或放弃 |
| 第 3 层过但方向相反 | **机制失败** | 必须解释；不得以「效应小」掩盖 |
| 四层全过但效应量极小 | **有效但不可用** | 如实报告，交 M1 决定 |

### 5.4 最小 fixture

```text
需要**同时**满足两个触发条件，故 fixture 分两段：
  I.  hashless 触发: 候选集中同时含 1 个 hashless 块与若干 hashed 块，
      且 hashless 块的 lru_rank **不是最小**（新分配 ⇒ 自然满足）
  II. 分离触发: 一条链的块在 lru_rank 序与 depth 序**不一致**
      （可用「部分命中」或「多链交错」构造；须先由 P5 数据确认可构造）
构造方式复用 Phase 2E F4 的 shared-root 模板；机制结论**不**引用旧 F4 的任何数值
```

**最小通过判据**：第 1–4 层链完整，且 A4、A6 劣于 A3。
⚠️ **不要求**正式统计显著性（课程项目：先用少量可复核实验建立机制链）。

### 5.5 预期局限（诚实前置）

| # | 局限 |
| --- | --- |
| **L1** | **Layer 1 仅在候选集含 hashless 块时有效**；否则为空操作 |
| **L2** | **不使用引用度/复用度**（runtime 不可得）⇒ 深度相同而共享度不同时可能不如覆盖度类方法 |
| **L3** | Layer 2 依赖 `d(b)`；**当前不在 adapter 输入内**，且需先验证**分离条件 C3** |
| **L4** | **链内 LRU 很可能已近似深度序**（结论 2）⇒ Layer 2 的**预期增量有限**，可能逐位同选 |
| **L5** | **不承诺延迟收益**（Phase 2E 实测 token 下降未带来延迟改善） |
| **L6** | 合成网格，不外推生产分布；`max_new_tokens=1`，不代表 decode 期 |
| **L7** | 不使用 `prefill_reload_seconds`（H1 中与尺寸秩同构，见 §7 X3） |
| **L8** | 不使用 P5 的内容身份；`d(b)` 与 P5 的 block→position 是同一信息 ⇒ P5 覆盖不足时 Layer 2 不可用 |

---

## 6. 接口与实现映射（RC4 修正）

### 6.1 v1 的判断错在哪

v1 声称「`CandidateRule.prepare(candidates)` 已满足需求」。**不准确**，因为：

```text
src/kvopt/costaware/replay.py:229  class RuleStrategy:
src/kvopt/costaware/replay.py:252      def pick_next(self, remaining, state):
                                           del state                      # <-- 丢弃 state
                                           return self.rule.selection(remaining, 1)[0]
```

⇒ `RuleStrategy` **主动丢弃** `state` ⇒ `CandidateRule` 只能做**静态**评分，
**无法**表达依赖已释放集合的量。

### 6.2 最小接口映射（entry-level harness 用）

| # | 问题 | 答案（已核实） |
| --- | --- | --- |
| 1 | 从何获取真实决策状态 | `ReplayState(snapshot)`（`replay.py:146`）；`snapshot: DecisionSnapshot`（`:122`） |
| 2 | 如何读已释放集合与新 eligibility | `state.released`（`:163`）；**`state.newly_eligible_after(key)`（`:193`）** 已按真实 eligibility 语义返回当前状态下新增可回收块 |
| 3 | 每轮如何重排 | 实现 `ReleaseStrategy.pick_next(remaining, state)`（Protocol `:223`），**每轮被调用**，可基于 `state` 重算 |
| 4 | 如何保证满足 `required_blocks` | 复用冻结循环：`state.release(key)` 后由 `DecisionSnapshot.target`（`min(required_blocks, len(queue))`）判定停止 |
| 5 | 如何复用既有 replay fidelity 校验 | 复用 `ExecutedP1BStrategy`（`:256`）同一路径；其注释已说明「middle term is recomputed against the *current* released set」⇒ **动态策略有先例** |
| 6 | 接入 native runtime 需过哪个边界 | **`EvictionPolicyAdapter.select_victims`**（`adapter.py:15`）——§0.1 的 block-level 边界 |

⭐ **结论**：正确做法是 **state-aware `ReleaseStrategy`**（不是静态 `CandidateRule`），
且**优先复用** `state.newly_eligible_after`，**不新增状态管理系统**。

### 6.3 实现落点与代码改动范围

```text
Layer 1（可立即实现，无接口变更）:
    src/kvopt/runtime/vllm/adapter.py 新增 class OursEvictLayer1Adapter(EvictionPolicyAdapter)
    逻辑: 分区 F/H → F(lru_rank) 先 → H(lru_rank) 后 → 取 R
    纯函数式重排；不 mutate vLLM 状态
    预估: ~40 行 + 单测

Layer 2（需授权，且需先验证分离条件）:
    前置 A: P5 覆盖率提升 ⇒ 由 ordered_native_hashes + block_ids 得到 depth
    前置 B: 用 P5 数据**先检验分离条件 C3**（各链 lru_rank 序是否偏离 depth 序）
            若 C3 不成立 ⇒ Layer 2 **应放弃**，不作为提交物
    若成立: types.py 的 EvictionCandidate 增加**可选只读** depth: int | None（默认 None）
            depth=None 时**自动退回 Layer 1**
    预估: types.py +1 可选字段；adapter 内 +30 行
```

**不触碰**：`pressure.py` 默认释放键、`ttl.py`、native BlockPool / ref_cnt / hash cleanup / LRU。

---

## 7. RC7 回应

### X1 — **撤回**

M1 指正正确：视图**已存在**。已核实

```text
src/kvopt/profiling/loss_views.py:74  _RECOMPUTE = "observed_recomputed_tokens"
src/kvopt/profiling/loss_views.py:75  _GATE_ELIGIBLE_VIEWS = {_PLANNED_PROXY, _PHYSICAL, _RECOMPUTE}
```

⇒ **不需要新增同名列**。M1 也点明了真正的问题：**未被选择的释放路径没有反事实观测**，
而这不是「补一个 loss view」能解决的。本设计因此**不依赖反事实损失**：
两层成本模型只使用**决策时可得**的结构量（§2.4）。

（v1 的 X1 请求**作废**。）

### X2 — 原则允许，**不预授权扩张**

已核实 `DecisionSnapshot.owners_by_block: Mapping[int, frozenset[CandidateKey]]`（`replay.py:131`）
与 `ReplayState._hashed_owners`（`:154`）**已足以**完成共同所有权审计。
⇒ **优先直接复用**，本设计**不提交**接口扩张请求。
仅当确认「候选集外 owner」或「运行时保护状态」存在不可忽略缺口时（§5.5 L2），再单独提交。

### X3 — **同意，且本轮已执行**（附实测数字）

已用既有 H1 语料检查 `prefill_reload_seconds` 与 `block_count` 的秩关系
（探针：`local/probe_x3_prefill_reload_rank.py`，输入 `decision_candidates.jsonl`）：

```text
决策数（含 >=2 候选且两字段均非空）      : 114
秩完全一致的决策（每个位置都相同）        : 114 / 114 = 100.0%
位置级一致率                            : 465 / 465 = 100.0%
决策内 Spearman(block_count, prefill_reload) : min 1.0000 / median 1.0000 / max 1.0000
  （非退化决策 99/99 全部恰为 1.0000）

结论: 在 H1 中 prefill_reload_seconds 与 block_count **位置级完全同序**（不只是相关）
      ⇒ 它**不能**为该语料增加任何信息，本版不将其作为成本信号（L7）
      ⇒ 与 M1「设计简化可接受」一致
约束: 不由此重开 H1/H2，不启动新的正式 campaign
```

接受 M1 的澄清：**没有显式 prefill-time 信号不是问题**；
本设计以 **block 数 / token 数**作成本代理，并已给出其物理语义（§2.2）与算法语义（§2.4）。

---

## 8. 请求 M1 裁定

1. **RC1 确认**：是否接受 **Ours-Evict = block-level（方案 A）**、
   entry-level 仅作 `Cost-Aware Pressure Release` 离线 harness（不属 Ours-Evict）？
2. **交付切分**：是否接受**先交付 Layer 1**（可证明、零新信号），
   Layer 2 **先做分离条件 C3 的离线检验**，C3 不成立则**放弃 Layer 2**？
3. **§6.3 的单一字段**：若 C3 成立，是否授权在 `EvictionCandidate` 增加可选只读 `depth: int | None`
   （默认 None，自动退回 Layer 1）？
4. **方向依据**：是否接受 §3.2 的「**链内截尾弱占优**」作为方向论证，
   并接受 §3.1 的跨链反例作为**放弃全局深优先**的依据？
5. **验证链**：是否接受 §5.3 的四层链与 §5.4 的失败归因表（不再以「未观察即证伪」）？
6. **A4/A5/A6**：是否确认为核心判别臂（方向 / 来源 / 热度主序）？

⛔ 本设计**不**请求：改 native BlockPool / ref_cnt / hash cleanup / LRU；改冻结 Continuum 默认键或 TTL；
子 entry 释放（**不解锁 B1**）；新观测缝（除 §6.3 单一可选字段）；重开 H1/H2；M1 通过前开始实现。

---

## 9. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| `EvictionPolicyAdapter.select_victims` 契约与「不得 mutate」 | `src/kvopt/runtime/vllm/adapter.py:11-25` |
| `EvictionCandidate` = `{block_id, ref_cnt, has_block_hash, lru_rank}` | `src/kvopt/runtime/vllm/types.py` |
| `EvictionContext` = `{required_blocks, free_blocks, total_blocks, timestamp}` | 同上 |
| `NativeLRUAdapter` 按 `lru_rank` 取 `required_blocks` | `src/kvopt/runtime/vllm/adapter.py:27-38` |
| `RuleStrategy` 丢弃 `state`（`del state`） | `src/kvopt/costaware/replay.py:252` |
| `ReplayState.newly_eligible_after` 按真实 eligibility 计算 | `src/kvopt/costaware/replay.py:193-217` |
| `DecisionSnapshot.owners_by_block` 已存在 | `src/kvopt/costaware/replay.py:131` |
| `ExecutedP1BStrategy` 为 state-aware 先例 | `src/kvopt/costaware/replay.py:256-278` |
| `observed_recomputed_tokens` 视图已存在 | `src/kvopt/profiling/loss_views.py:74-75` |
| APC 需连续前缀；free-queue 数 ≠ hash eviction 数 ≠ recomputed tokens | `docs/phase2b-m6-experimental-fidelity-repair-spec.md` §1 |
| 基线键 `(deadline, min LRU over newly_eligible, identity)` | `src/kvopt/continuum/pressure.py:324` |
| eligibility 语义（hashless 恒 Tier 1；被 protected owner 持有则不可回收） | `continuum/selection.py::BlockEligibilitySnapshot`；`pressure.py::_eligible_block_ids` |
| recency 同步 ⇒ 连续带（87/87） | `local/probe_s1_recency_sync.py`、`probe_s1b_lru_concentration.py` |
| F4 odd=SHARED_ROOT treatment / even=negative control | `src/kvopt/workload/phase2e_materialize.py`；`docs/phase2e-m4-measured-review.md` §2.1 |
| F4 treatment 机制未建立（12 NOT_REALIZED） | `docs/phase2e-m6-measured-campaign-report.md` |
| tail-first 早期推导（**不主张为创新**） | `docs/phase2a-m4-block-level-design-draft.md` §4（B1，LOCKED） |
| Phase 2E：token 下降未带来延迟改善 | `docs/phase2e-m6-measured-campaign-report.md` |
| 冻结接受协议 / 统计单位 | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| RR-EVICT 假设与目标 | `local/2609.32278v2.pdf` §3.3 |
| X3：`prefill_reload_seconds` 与 `block_count` 位置级完全同序（114/114；465/465；ρ=1.0000×99） | `local/probe_x3_prefill_reload_rank.py`（H1 `decision_candidates.jsonl`） |
| `credit + damage = |B_i|` ⇒ v1 公式退化为 credit 的单调函数 | §0.2 推导（eligibility 语义：`newly_eligible_after` 即私有块） |
