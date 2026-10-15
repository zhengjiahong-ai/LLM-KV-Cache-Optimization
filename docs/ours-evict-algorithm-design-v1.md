# Ours-Evict — Algorithm Design（rev.3）

**提交人**：M4　**送审**：M1　**日期**：2026-10-15
**阶段**：Phase 2 Cost-Aware Eviction 算法设计（**设计 PR，不含 runtime 实现**）
**主目标**：`aggregate_recomputed_tokens`　**辅助观测**：TTFT / queue delay
**边界**：不改 native BlockPool / ref_cnt / hash cleanup / LRU，不改冻结 Continuum baseline，B1 保持 LOCKED，不实施 runtime

> **rev.3 说明**：M1 已独立发现 rev.2 的 Layer 1 问题。本轮我把该问题**做完**了实测，
> 并顺带把 Layer 2 也**量化**了。两个实测合起来给出一个更根本的结论：
> **在冻结的 block-level 接口内，几乎没有 LRU 尚未利用的成本信号。**
> 因此 rev.3 不再是"完善一个算法"，而是**如实报告接口天花板并请 M1 在三条例径中裁定**。

---

## 0. rev.3 结论摘要（先给答案）

### 0.1 核心实测：接口天花板

冻结接口暴露的全部字段（已核实到源码）：

```text
EvictionCandidate = { block_id, ref_cnt, has_block_hash, lru_rank }
EvictionContext   = { required_blocks, free_blocks, total_blocks, timestamp }
```

**逐字段评估它们能否作为成本信号**：

| 字段 | 可作成本信号？ | 实测证据 |
| --- | --- | --- |
| `lru_rank` | ❌ **它就是基线本身** | `NativeLRUAdapter` 即按其升序取值 |
| `has_block_hash` | ❌ **LRU 已经自动用掉了**（见 §0.2） | 顺序起作用的 54 个决策中，hashless 块归一化 rank **= 0.0000** |
| `ref_cnt` | ❌ **常数** | free-queue 块按定义 `ref_cnt == 0`；且**未持久化**在 H1 队列中（行字段仅 `{block_id, eligibility_tier, has_block_hash, native_lru_rank}`） |
| `required/free/total_blocks` | ❌ 只是**预算**，不是成本 | — |
| 前缀深度 `d(b)` | ⚠️ 若加入**可能**有用，但窗口极小（见 §0.2） | 729 个链窗口中 **93.4% 已被 LRU 满足** |
| owner / 内容身份 | ❌ 不在接口内 | 属 replay 层产物 |

⇒ **结论**：在该边界内，**除 `lru_rank` 外的每个可得信号，要么已被基线用尽、要么是常数。**
这不是实现不足，而是**接口的能力上限**。

### 0.2 支撑该结论的两组决定性实测

**实测 A —— Layer 1 无空间**（探针 `local/probe_l1_refined.py`）

```text
决策总数                                              : 87
  required_blocks >= len(queue)（顺序无关，全队列都要淘汰） : 33 = 37.9%
  required_blocks <  len(queue)（顺序才起作用）           : 54 = 62.1%

在"顺序起作用"的 54 个决策上：
  hashless 占比（整个队列）              : median 0.2980
  hashless 占比（冷端前缀 = LRU 先淘汰的） : median 0.8591
  冷端 hashless 富集（LRU 已这么做）      : 54 / 54 = 100%
  冷端 hashless 枯竭（Layer 1 才有空间）  :  0 / 54 =   0%
  最早 hashless 块归一化 rank            : median 0.0000
  最早 hashed   块归一化 rank            : median 0.3012
```

⇒ **无 hash 块就坐在 free queue 最前端。** 原因不是 vLLM 写了特殊规则，而是结构性必然：

```text
前缀命中只刷新"有 hash"的块（推到热端）
无 hash 块永不被任何命中触及 ⇒ 只能持续变冷 ⇒ 自动沉到冷端
⇒ 任何 LRU 系淘汰都会自动优先吃掉它们
```

**实测 B —— Layer 2 窗口极小**（探针 `local/probe_c3_and_refcnt.py`）

```text
链窗口数（87 个决策内，每窗口 = 一段按前缀序对齐的链）    : 729
链窗口长度 : median 12, min 3, max 32

rho = Spearman(前缀位置 k, lru_rank)
  median -1.0000    mean -0.8843    min -1.0000    max +1.0000

  rho < 0（深块更冷 ⇒ LRU 已"深优先" ⇒ 无空间） : 681  = 93.4%
  rho > 0（浅块更冷 ⇒ LRU"浅优先" ⇒ 有空间）    :  48  =  6.6%
```

⇒ **93.4% 的情形下 LRU 已经在淘汰最深块**（中位数是完美负相关 −1.0）。
⇒ **Layer 2 的可利用窗口只有 6.6%**，且即便在这 6.6% 内，收益还需"这些块随后真被重新请求"才兑现。
⇒ 这与 rev.2 的推断（"链内 LRU 很可能已近似深度序"）一致，但**从推断升级为实测，且量级更小**。

### 0.3 设计后果

| rev.2 的组件 | rev.3 处置 |
| --- | --- |
| **Layer 1（hashless 优先）** | **删除**（实测 A：0% 空间；M1 亦已指出） |
| **Layer 2（链内深度）** | **降级为 6.6% 窗口的窄假设**，且需 M1 授权一个只读字段 |
| rev.2 §3.3 的 64→0 正例 | **撤回**（它假设 hashless 块 rank 最大，实测为 rank 0） |
| 成本模型（Q1/Q2/Q3 + APC 语义） | **保留**（仍然正确，且是判断上述窗口的依据） |

⇒ **本设计目前不包含任何"可立即实现且有预期增益"的组件。**

---

## 0.4 变更轨迹（含我自己的三次撤回）

| 版本 | 主张 | 结果 |
| --- | --- | --- |
| v1 | `damage/(1+credit)` 的 entry-level 成本模型 | **撤回**：语义错（被保护的块不会被淘汰）+ 比值退化为 credit 的单调函数 |
| v2 | Layer 1 可证明弱占优 + 全局深优先定理 | **撤回**：全局深优先被跨链反例击破；**Layer 1 被实测否定**（§0.2） |
| v3 | 接口天花板 + 6.6% 窄窗口 | 本文 |

⇒ 三次撤回都由**实测或推导**驱动，不是措辞调整。我不再为保留一个"看起来可行"的算法而弱化证据。

---

## 1. 决策边界（RC1，沿用 rev.2 裁定）

### 1.1 Ours-Evict = block-level（方案 A）

```text
src/kvopt/runtime/vllm/adapter.py:11
    class EvictionPolicyAdapter(ABC):
        def select_victims(self, candidates: Sequence[EvictionCandidate],
                           context: EvictionContext) -> Sequence[int]
        """Choose block-level victims without mutating vLLM cache state directly."""
```

| 项 | 值 |
| --- | --- |
| **输入 1** | `Sequence[EvictionCandidate]` = `{block_id, ref_cnt, has_block_hash, lru_rank}` |
| **输入 2** | `EvictionContext` = `{required_blocks, free_blocks, total_blocks, timestamp}` |
| **输出** | `Sequence[int]` = victim block IDs 按淘汰顺序；唯一、取自 candidates |
| **约束** | 不得 mutate vLLM queue / block metadata |
| **下游** | `BlockPool.get_new_blocks()` → `_maybe_evict_cached_block()` 真实 hash cleanup |
| **生产者** | `bridge.py:35` `build_candidates()`：`lru_rank` = 队列序号；`has_block_hash = block.block_hash is not None` |

⚠️ **注意 `bridge.py` 的 `VLLMBlockLike` 只有 `{block_id, ref_cnt, block_hash}`**
——**没有前缀位置**。且 `EvictionCandidate` 把 `block_hash` **降级成布尔**，
内容身份在构造时被丢弃。这是 §0.1 天花板的具体来源。

### 1.2 entry-level 设计的定位（**不属于 Ours-Evict**）

`FORCED_RELEASE_DECISION.payload.candidates` 属**另一个决策边界**（Continuum retention pressure release）。
rev.2 已将其改名 `Cost-Aware Pressure Release`、降级为**离线 harness**。
rev.3 保持该定位，并把它列为 §7 的**候选路径 B**（需 M1 批准范围变更）。

---

## 2. 成本模型（保留 rev.2，仍然正确）

### 2.1 三个必须区分的量

| # | 量 | 等于重计算？ |
| --- | --- | --- |
| **Q1** | Logical protection released | ❌ |
| **Q2** | Physical cached blocks evicted | ❌（但**是** Q3 的必要条件） |
| **Q3** | Future recomputed prefix tokens | ✅ **主目标** |

⇒ **Q1 ⇏ Q2 ⇏ Q3**。成本模型只对 Q2 定价，Q2→Q3 映射写成显式假设。

### 2.2 APC 语义（唯一依据）

仓库既有事实（`docs/phase2b-m6-experimental-fidelity-repair-spec.md` §1）：APC 需**可匹配的连续前缀**。
故对请求 r 的链 `p₁…p_m`：

```text
j(r) = min{ k : p_k 已被淘汰 }        （均未淘汰则 j(r) = m+1）
recompute(r) = (m − j(r) + 1) × block_size_tokens
```

**关键**：`recompute(r)` **只由 r 链上最浅的已淘汰块决定**。

### 2.3 为什么该模型依然必要

它给出了 §0.2 实测的解释：**"深优先"正是 `j(r)` 最大化**，而实测 B 表明 **LRU 已在 93.4% 的窗口做到这一点**
⇒ 该模型用来自证"没有空间"，而非用来包装一个算法。

---

## 3. 两层的处置

### 3.1 Layer 1 —— **删除**（含撤回 rev.2 的正例）

**rev.2 的论证**（正确但**不适用**）：hashless 块不参与 APC 匹配 ⇒ 淘汰它 β=0。
**rev.2 的算例**（**错误，撤回**）：假定 hashless 块的 `lru_rank` 最大。
**实测**：其归一化 rank = **0.0000**（最冷）；冷端 hashless **富集 100%**、**枯竭 0%**。

⇒ **LRU 已经做了这件事**。Layer 1 在 100% 的顺序相关决策上冗余，
在其余 37.9% 上是空操作（全队列都要淘汰）。

⇒ **Layer 1 从设计中移除。** 其"可证明弱占优"命题依然为真，但**在真实队列顺序下永不被激活**。

### 3.2 Layer 2 —— **降级为 6.6% 窄窗口假设**

**可由 rev.2 §3.2 保留的弱命题**（**成立**）：

> **固定每条链被选中的块数**时，把某条链的选择从较浅优先改为较深优先，
> 则 `j(rγ)` 不减小 ⇒ `recompute(rγ)` 不增；对其它链无影响。

**必须同时保留的反例**（rev.2 §3.1，**成立**）：跨链全局深优先可为**更差**
（热长链 vs 冷短链）⇒ **深度不能作全局主键，`lru_rank` 必须保留为主序**。

**实测窗口（§0.2 B）**：只有 **6.6%** 的链窗口满足 `ρ > 0`（浅块更冷，即 recency 与 depth **分离**）。

⇒ Layer 2 的形态（若实现）：**仅在链内做次序校正，跨链分配不变**：

```text
形态 L2-A（仅需链身份 + 链内相对序）
    主键: lru_rank
    后处理: 若某链被选中 >= 2 块且其 lru_rank 序与链内序**不一致**，
            则在该链内部改为**更深优先**；跨链分配保持不动
```

⚠️ **实现前提（三个，缺一不可）**：
1. M1 授权一个**只读**字段（§6.3）——注意这是**直通**而非新插桩：`bridge.py` 已持有 `block.block_hash`，
   而前缀位置在 `VLLM_PREFIX_SNAPSHOT.block_ids`（**按前缀序**，已核实）+ `ordered_native_hashes` 中可得；
2. 该字段的覆盖率足够（依赖 P5，当前 `PARTIALLY_DEMONSTRATED`）；
3. 接受**预期效应极小**：6.6% × 二级效应（这些块需随后被重新请求）。

⇒ **我不建议优先实现 Layer 2**；它更像是"若 M1 一定要在 block-level 交付一个东西"的兜底选项。

---

## 4. 与既有规则及研究的边界

### 4.1 与 H1 规则族（**边界不同，不可比**）

H1 规则在 **entry-level** 打分（`DecisionCandidateRow`，含 `block_ids`）；
Ours-Evict 在 **block-level** 打分（`EvictionCandidate`，仅 4 字段）。
⇒ 必须分开报告；H1 的"无增益"既不证否也不支持 Ours-Evict。

### 4.2 与 `NativeLRUAdapter` 的真实关系（**rev.3 的核心表述**）

```text
在冻结接口内，Ours-Evict 能用的信号 = {lru_rank, has_block_hash, ref_cnt}
其中：lru_rank 就是基线；has_block_hash 已被 LRU 用掉；ref_cnt 恒为 0
⇒ 在本 campaign 的实测下，Ours-Evict 与 NativeLRUAdapter 的**预期差异≈6.6% 的窄窗口**
```

⚠️ 这不是说"LRU 最优"。而是说：**在只暴露这些字段的边界内，没有更多信息可加。**
若要更大空间，必须改变**决策边界**（→ entry-level）或**暴露更多字段**（→ 接口扩展）。

### 4.3 与 RR-EVICT 的关系

RR-EVICT 在 **entry/子 entry 粒度**（轮转 tail chunk），且需要 idle/active 区分。
它与本设计**不在同一决策边界**。⛔ "截尾/保根"直觉**不主张为创新**（早期 B1 草案已推导，RR-EVICT 亦含）。

### 4.4 RC6 — F4 / Phase 2D 边界（严格保持）

```text
F4 odd draws 01/03/05 = SHARED_ROOT treatment（机制 NOT_REALIZED）
F4 even draws 02/04/06 = NO_SHARED_PREFIX_NEGATIVE_CONTROL（已观察非零改善来自此处）
```

⇒ 旧 F4 数值**不作**本算法证据；仅**复用其 workload 构造方式**。
Phase 2D E2/E3 仅作**设计依据**，不作有效性证明。

---

## 5. 验证计划（RC5 修正，保留四层链）

### 5.1 四层机制链（替换"未观察即证伪"）

```text
第 1 层  是否产生**合法且不同**的选择？（输出 ⊆ candidates、|输出| = R、去重、≠ A0）
第 2 层  是否改变**物理缓存状态**？（淘汰后存活块集合不同）
第 3 层  是否改变 **aggregate recomputed tokens**？（同未来请求序列）
第 4 层  方向是否与主张一致？（A4/A6 劣于 A3）
```

**失败归因表**：

| 观察 | 归因 | 处置 |
| --- | --- | --- |
| 第 1 层不过 | **未触发**（无分离窗口） | 属**预期情形**：实测仅 6.6% 窗口；不是机制失败 |
| 第 1 层过、第 2 层不过 | **未实现**（未发生真实 hash cleanup） | 机制未受检验 |
| 第 1、2 层过、第 3 层不过 | **机制失败**（成本模型错） | 修订或放弃 |
| 第 3 层过但方向相反 | **机制失败** | 必须解释 |
| 全过但效应极小 | **有效但不可用** | 如实报告 |

⚠️ rev.3 新增：**"第 1 层不过"在本设计中是*最可能*的结果**（6.6% 窗口），
故它应被预先归类为 `NOT_TRIGGERED`，而不是事后辩解。

### 5.2 消融臂

| 臂 | 定义 | 预期 |
| --- | --- | --- |
| **A0** | `NativeLRUAdapter` | 基线 |
| **A1** | ~~Layer 1~~ | **已删除**（实测 0% 空间） |
| **A2** | 链内深度重排（不跨链） | 仅 6.6% 窗口生效 |
| **A3** | A2 + `lru_rank` 主序（= 候选完整形态） | 最佳 |
| **A4** | 链内方向反转（浅优先） | 应劣于 A3（方向判别） |
| **A6** | 去 `lru_rank`（identity 作 tie-break） | 应**显著劣于** A3（实证跨链反例） |

### 5.3 最小 fixture

```text
必须落在 6.6% 窗口内，故构造方式：
  一条链发生**部分命中**（只刷新其尾部）⇒ 使链内 lru_rank 序偏离链内位置序
  其余保持 lru_rank 主序 ⇒ 验证跨链分配不变
复用 Phase 2E F4 的 shared-root 模板；不引用其任何数值
```

**最小通过判据**：第 1–4 层完整，且 A4/A6 劣于 A3。**不要求**正式统计显著性。

---

## 6. 接口与实现映射（RC4 修正）

### 6.1 v1 的判断错在哪（保留）

```text
src/kvopt/costaware/replay.py:252
    def pick_next(self, remaining, state):
        del state                                  # 主动丢弃 state
        return self.rule.selection(remaining, 1)[0]
```

⇒ `CandidateRule` 只能静态评分。正确做法是 **state-aware `ReleaseStrategy`**。

### 6.2 最小接口映射（六问）

| # | 问题 | 答案（已核实） |
| --- | --- | --- |
| 1 | 决策状态来源 | `ReplayState(snapshot)`（`replay.py:146`） |
| 2 | 读已释放集合与新 eligibility | `state.released`；**`state.newly_eligible_after(key)`（`:193`）** |
| 3 | 每轮重排 | 实现 `ReleaseStrategy.pick_next(remaining, state)`（Protocol `:223`） |
| 4 | 满足 `required_blocks` | 复用冻结循环，`DecisionSnapshot.target` 判定停止 |
| 5 | 复用 fidelity 校验 | `ExecutedP1BStrategy`（`:256`）同路径，动态策略**有先例** |
| 6 | native 执行边界 | **`EvictionPolicyAdapter.select_victims`** |

### 6.3 唯一请求的字段（**直通，非新插桩**）

```text
若 M1 授权 Layer 2：
  EvictionCandidate 增加**可选只读** chain_pos: int | None（默认 None ⇒ 自动退回 A0）
  来源（全部已存在，无新插桩）:
      bridge.VLLMBlockLike.block_hash（bridge.py 已持有，当前被降级为布尔）
      VLLM_PREFIX_SNAPSHOT.block_ids（**按前缀序**）+ ordered_native_hashes
  ⇒ 这是把**已在内存中的信息**透出，不是新增观测能力
  覆盖率前置：P5（block→prefix position）当前 PARTIALLY_DEMONSTRATED
  depth/chain_pos = None 时算法**逐位等同 NativeLRUAdapter**
```

**代码改动范围**：`types.py` +1 可选字段（若授权）；`adapter.py` 新增 1 个类（~30 行）。
**不触碰**：`pressure.py` 默认键、`ttl.py`、BlockPool / ref_cnt / hash cleanup / LRU。

---

## 7. 请求 M1 裁定（三条例径，请择一）

| 路径 | 内容 | 我的评估 |
| --- | --- | --- |
| **A. 关闭 block-level 线** | 接受 §0.1 的天花板结论：冻结接口内无可加信号 | ⭐ **证据最支持**：实测 A 0%、实测 B 6.6%；M1 已独立发现同一问题 |
| **B. 授权范围变更 → entry-level** | 把 `Cost-Aware Pressure Release` 立为正式研究对象（那是唯一还有可观测量——共享/保护结构——的边界） | ⭐ **研究价值最高**：H1 中 `relief ≡ block_count`（471/471），Phase 2E F4 才首次出现共享结构 ⇒ 仍有未开发空间 |
| **C. 授权 Layer 2 窄实验** | 授予 `chain_pos` 字段，在 6.6% 窗口上做最小验证 | ⚠️ 成本低但**预期效应极小**，可能只换来一个"未触发"结论 |

**我的建议顺序：B > A > C。**

理由：实测已表明 block-level 边界**信息不足**（不是算法不好），
继续在 C 上投入的期望产出很低；而 A 与 B 都只需一次裁定即可推进。
若 M1 选 B，我将在批准后**另立设计**（不混入本文）。

### 附：另外两个小问题

1. **X1 已撤回**（`loss_views.py:74` 已有 `observed_recomputed_tokens`）；
2. **X3 已执行并附数字**：H1 中 `prefill_reload_seconds` 与 `block_count` **位置级完全同序**
   （114/114 决策、465/465 位置、99/99 ρ=1.0000）⇒ 不使用该字段。

⛔ 本设计**不**请求：改 native BlockPool / ref_cnt / hash cleanup / LRU；改冻结 Continuum 默认键或 TTL；
子 entry 释放（**不解锁 B1**）；新观测缝（除 §6.3 的单一直通字段）；重开 H1/H2；M1 通过前开始实现。

---

## 8. 局限（诚实前置）

| # | 局限 |
| --- | --- |
| **L1** | 实测 A/B 来自 **H1 语料**（87 决策 / 729 窗口）；**不自动外推** Phase 2E 语料或生产分布 |
| **L2** | 实测 A 的结论依赖"无 hash 块不被 APC 命中刷新"这一 APC 语义；若某实现会刷新它们，需重测 |
| **L3** | 6.6% 窗口是**上界**：即便在其中，收益还需"这些块随后被重新请求"才兑现（二级效应） |
| **L4** | `chain_pos` 依赖 P5 覆盖率（当前 `PARTIALLY_DEMONSTRATED`） |
| **L5** | **不承诺延迟收益**（Phase 2E 实测 token 下降未带来延迟改善） |
| **L6** | 合成网格；`max_new_tokens=1`，不代表 decode 期 |
| **L7** | 不用 `prefill_reload_seconds`（X3 实测同序） |
| **L8** | **不使用引用度/复用度**（runtime 不可得）⇒ 深度相同而共享度不同时无法区分 |

---

## 9. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| `EvictionPolicyAdapter.select_victims` 契约与"不得 mutate" | `src/kvopt/runtime/vllm/adapter.py:11-25` |
| `EvictionCandidate` / `EvictionContext` 字段 | `src/kvopt/runtime/vllm/types.py` |
| `bridge.build_candidates`：`lru_rank`=队列序号、`has_block_hash`=hash 非空 | `src/kvopt/runtime/vllm/bridge.py:32-42` |
| `VLLMBlockLike` = `{block_id, ref_cnt, block_hash}`（无前缀位置） | `src/kvopt/runtime/vllm/bridge.py:14-19` |
| `NativeLRUAdapter` 按 `lru_rank` 取 `required_blocks` | `src/kvopt/runtime/vllm/adapter.py:27-38` |
| **实测 A：冷端 hashless 富集 100%、枯竭 0%、rank=0.0000** | `local/probe_l1_refined.py`（H1 语料） |
| **实测 B：729 窗口中 93.4% 为 ρ<0（median −1.0000）** | `local/probe_c3_and_refcnt.py`（H1 语料） |
| free-queue 行字段 = `{block_id, eligibility_tier, has_block_hash, native_lru_rank}`（**无 ref_cnt**） | H1 `FORCED_RELEASE_DECISION.payload.original_free_queue` |
| `VLLM_PREFIX_SNAPSHOT.block_ids` 按前缀序 + `ordered_native_hashes` | H1 events（已核实长度一致） |
| `RuleStrategy` 丢弃 `state`（`del state`） | `src/kvopt/costaware/replay.py:252` |
| `ReplayState.newly_eligible_after` / `owners_by_block` / `ExecutedP1BStrategy` | `src/kvopt/costaware/replay.py:193` / `:131` / `:256` |
| `observed_recomputed_tokens` 视图已存在 | `src/kvopt/profiling/loss_views.py:74-75` |
| APC 需连续前缀 | `docs/phase2b-m6-experimental-fidelity-repair-spec.md` §1 |
| 基线键 `(deadline, min LRU over newly_eligible, identity)` | `src/kvopt/continuum/pressure.py:324` |
| eligibility 语义（hashless 恒 Tier 1） | `continuum/selection.py::BlockEligibilitySnapshot`；`pressure.py::_eligible_block_ids` |
| recency 同步 ⇒ 连续带 87/87 | `local/probe_s1_recency_sync.py`、`probe_s1b_lru_concentration.py` |
| `relief ≡ block_count` 471/471（H1 无共享结构） | `local/probe_relief_field.py` |
| F4 odd=treatment / even=negative control | `src/kvopt/workload/phase2e_materialize.py`；`docs/phase2e-m4-measured-review.md` §2.1 |
| F4 treatment 机制未建立（12 NOT_REALIZED） | `docs/phase2e-m6-measured-campaign-report.md` |
| X3：`prefill_reload_seconds` 与 `block_count` 位置级完全同序 | `local/probe_x3_prefill_reload_rank.py` |
| Phase 2E：token 下降未带来延迟改善 | `docs/phase2e-m6-measured-campaign-report.md` |
| 冻结接受协议 / 统计单位 | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| RR-EVICT 假设与目标 | `local/2609.32278v2.pdf` §3.3 |
