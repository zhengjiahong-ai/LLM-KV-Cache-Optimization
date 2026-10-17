# Ours-Evict — Algorithm Design（rev.4）

**提交人**：M4　**送审**：M1　**日期**：2026-10-17
**阶段**：Phase 2 Cost-Aware Eviction 算法设计（**设计 PR，不含 runtime 实现**）
**主目标**：`aggregate_recomputed_tokens`　**辅助观测**：TTFT / queue delay
**边界**：不改 native BlockPool / ref_cnt / hash cleanup / LRU，不改冻结 Continuum baseline，**B1 保持 LOCKED**，不实施 runtime

> **rev.4 说明**：本轮响应 M1 对 rev.2（`5c2f8a9`）的 `CHANGES_REQUESTED`（RC1–RC6）。
> ⚠️ **同时更正 rev.3**：rev.3（未推送草稿）曾引用一个**不存在的探针**
> `local/probe_c3_and_refcnt.py`，其「729 窗口 / 93.4% / 6.6%」数字**不可复现**。
> 我已重建该测量（新探针 `local/probe_rev3_verify.py`），**结论与原数字相反**（见 §0.2）。
> 该失真数字**已从本文撤回**；相关结论按可复现数据重写。

**结论（一句话）**：在冻结的 block-level 接口内，**Ours-Evict 目前没有可实现的、能改变 native victim set 的成本信号** ⇒ 判定 **BLOCKED**，并请 M1 在两条路径中裁定（§7）。

---

## 0. 变更轨迹（含我自己的四次撤回）

| 版本 | 主张 | 结果 |
| --- | --- | --- |
| v1 | `damage/(1+credit)` entry-level 成本模型 | **撤回**：语义错（被保护的块不会被淘汰）+ 比值退化为 credit 的单调函数 |
| v2 | Layer 1 可证明弱占优；全局深优先定理 | **撤回**：全局深优先被跨链反例击破 |
| v3 | Layer 1「实测无空间」；Layer 2「6.6% 窗口」 | **Layer 1 部分保留**；**Layer 2 的 6.6% 撤回**（不可复现，见文首说明） |
| v4 | 接口天花板 = BLOCKED；Layer 1 降为 native invariant；Layer 2 = NOT_OBSERVABLE | 本文 |

⇒ 四次撤回均由**实测或推导**驱动。**我不保留任何"看起来可行"的组件。**

---

## 0.1 M1 RC1–RC6 落实对照（供核对）

| RC | 要求 | 本文落实位置 |
| --- | --- | --- |
| **RC1** | 撤回 Layer 1 独立增益；给出 native 机制；需合法 free-queue snapshot 或降为 sanity check | **§1**（native 机制 + 可复核快照 + 无例外 ⇒ 降为 sanity check） |
| **RC2** | 修正 rank/depth 方向矛盾；删去由连续带推出深度序 | **§2**（方向约定 + 重建实测 ρ≡−1.0000 + 方向 `NOT_OBSERVABLE`） |
| **RC3** | 弱命题限独立无共享链；共享情形单独说明；只留一个可执行版本；fail-closed | **§3**（共享反例 + 单一版本 + fail-closed；并指出 `chain_pos` 单字段不足） |
| **RC4** | 边际重算改为新旧成本差 | **§4**（`ΔR = Σ_r B·max(0, j_old − j_new)` + M1 的 4/3/2 算例） |
| **RC5** | 消融/契约/集合 vs 序列；最小路径 | **§5**（含 `bridge._validate_selection` 真实契约 + `NO_HEADROOM_OBSERVED` 判据） |
| **RC6** | X3 交付边界 | **§8 附 2**（H1 已核查；**Phase 2E 尚未核查**） |

---

## 0.2 两组实测（全部可复现）

### 实测 A —— Layer 1 无空间

探针 `local/probe_l1_refined.py`（H1 `original_free_queue`）：

```text
决策总数                                             : 87
  required_blocks >= len(queue)（顺序无关，全队列都要淘汰）: 33 = 37.9%
  required_blocks <  len(queue)（顺序才起作用）          : 54 = 62.1%

在"顺序起作用"的 54 个决策上：
  hashless 占比（整个队列）                : median 0.2980
  hashless 占比（冷端 = LRU 先淘汰的前缀）  : median 0.8591
  冷端 hashless 富集（LRU 已这么做）        : 54 / 54 = 100%
  冷端 hashless 枯竭（Layer 1 才有空间）    :  0 / 54 =   0%
  最早 hashless 块归一化 rank              : median 0.0000
  最早 hashed   块归一化 rank              : median 0.3012
```

### 实测 B —— 链窗口的重排自由度（**重建，取代 rev.3 的失真数字**）

探针 `local/probe_rev3_verify.py`；**定义已写死在探针里**：

```text
chain window = 一个 decision 内的一个候选 entry（candidates[].block_ids）
k            = 该 entry 内 block_ids 的下标（升序）
rho          = Spearman(k, 该块的 native_lru_rank)        （取自同一 decision 的 original_free_queue）

结果：
  可测窗口（>=3 个可比块）      : 294
  rho  min −1.0000   median −1.0000   mean −1.0000   max −1.0000
  恰为 −1.0000                  : 294 / 294 = 100%
  rho > 0（存在重排空间）        :   0 / 294 =   0%
```

⇒ **在一个 entry 内部，`native_lru_rank` 是 block 下标的一个完美单调函数。**
⇒ **entry 内部不存在任何重排自由度**（不是"6.6% 有空间"，而是 **0%**）。

⚠️ **方向（哪一端更冷）仍不可判定**：把下标等同于"前缀深度"需要 `block_id → token 前缀位置`
的映射，而该能力（P5）当前为 `PARTIALLY_DEMONSTRATED`（T2 实测覆盖率约 1/7）。
因此本文**不声称**「LRU 已在做深优先」，只声称**单调性**（见 §2）。

### 附：`ref_cnt` 的可观测性

```text
H1 全部 decision 的 original_free_queue 行数 : 6606
  其中携带 ref_cnt 字段的行                  :    0   ⇒ H1 中 ref_cnt 未持久化
```

⇒ 在既有语料上 `ref_cnt` 为 `NOT_OBSERVABLE`；其"恒为 0"的依据来自**vLLM 源码**（§1.1），
不是来自我们的数据。

---

## 1. RC1 — Layer 1 是 **native invariant**，不是 Ours-Evict 组件

### 1.1 native 机制（源码级，M1 已核对，我独立引用）

```text
vLLM v0.27.1  vllm/v1/core/block_pool.py
  free_blocks()     分离 blocks_without_hash / blocks_with_hash，
                    再 prepend_n(blocks_without_hash) + append_n(blocks_with_hash)
                    （M1 引：第 727–742 行）
  get_new_blocks()  free_block_queue.popleft_n(num_blocks)
                    随后对每块 _maybe_evict_cached_block(block)
                    并 **assert block.ref_cnt == 0**                （M1 引：第 647–666 行）
```

⇒ 两点结构性事实：

1. **无 hash 块被 native 主动前置**（`prepend_n`）⇒ 会被优先取用/淘汰，
   **不需要任何策略去"发现"它们**；
2. **free queue 中每个候选块的 `ref_cnt` 恒为 0**（源码断言）⇒ `ref_cnt` **不携带任何成本信息**。

补充旁证：该文件的提交历史含 *"Skip LRU hash-split in free_blocks when prefix caching is …"*
（commit `a82f1b3`），说明该 hash-split 是 vLLM 的**显式、有条件的既有机制**，而非偶然现象。

### 1.2 可复核的 free-queue snapshot（M1 要求）

**生成路径**：H1 语料 `…/phase2a-h1-formal-level-a-runs-v1/<run>/events.jsonl`
→ `FORCED_RELEASE_DECISION.payload.original_free_queue`
→ 按 `native_lru_rank` 升序（= native 淘汰顺序）；脚本 `local/probe_rev3_verify.py`。

```text
run_id = h1-f1-draw-04-seed-101   event_index = 95
  required_blocks = 30   queue_len = 83   hashless_in_queue = 24
  first_hashed_rank = 24                       ← 前 24 个全是 hashless
  最冷 12 项 (block_id, lru_rank, has_block_hash):
    (60,0,False) (61,1,False) (62,2,False) (63,3,False) (64,4,False) (65,5,False)
    (66,6,False) (67,7,False) (68,8,False) (69,9,False) (70,10,False) (71,11,False)
```

⇒ **无 hash 块占据 rank 0..23（连续），第一个有 hash 块在 rank 24。**
⇒ 在 `required_blocks = 30` 下，native 取的前 24 个**全部**是零成本块。

### 1.3 是否存在例外？（M1 要求回答）

我按 M1 的要求检索了全部 87 个决策：

```text
冷端 hashless 富集 : 54 / 54（顺序相关子集）
冷端 hashless 枯竭 :  0 / 54
```

⇒ **未发现任何例外**（不存在"hashless 块排在热端、需要策略去救"的决策）。

### 1.4 处置

| rev.2 的表述 | rev.4 处置 |
| --- | --- |
| 「Layer 1 可立即实现，含 hashless 时严格更优」 | **撤回** |
| 「Layer 1 是可证明弱占优的独立增益」 | **降级为 native invariant 的 sanity check**，**不列为交付** |
| rev.2 §3.3 的 64→0 正例 | **撤回**（其前提"hashless 块 rank 最大"与 native `prepend_n` 不符） |

> **Layer 1 从 Ours-Evict 中删除。** 其"hashless 淘汰不增加重算"的命题**依然为真**，
> 但它**描述的是 native 已有行为**，不能作为本设计的贡献。

---

## 2. RC2 — 方向约定修正，且**方向判定为 NOT_OBSERVABLE**

### 2.1 修正方向约定（解释 rev.2 的矛盾）

rev.2 §3.4 写 `a1(浅) < a2 < a3(深)`（`<` 表示 `lru_rank` 更小），随后却推断
「NativeLRU 已先淘汰 a3」。**该推断错误**：升序排序**先淘汰 a1**。方向约定现固定为：

```text
lru_rank 升序  = 淘汰顺序（小 → 先淘汰）
depth/前缀位置 k 升序 = 越靠前缀根部越浅（k 小 = 浅）
ρ = Spearman(k, lru_rank)
   ρ = −1  ⇔ 深块 rank 更小 ⇔ LRU 先淘汰深块 ⇔ 无深优先空间
   ρ = +1  ⇔ 浅块 rank 更小 ⇔ 有空间
```

### 2.2 撤回「由连续带推出深度序」

rev.2 曾以「87/87 连续带」推断 LRU 已深优先。**连续带只说明块在 rank 上相邻，
不说明浅深排列方向。** 该推断**已删除**。

### 2.3 重建后的实测（取代 rev.3 的失真数字）

见 §0.2 实测 B：

```text
294 / 294 窗口 ρ ≡ −1.0000（完美单调）  ⇒ entry 内无重排自由度
但"−1"对应的方向解释需要 P5（block → token 前缀位置）⇒ 当前不可靠
```

⇒ **正确表述**：

> 在一个 entry 内部，native LRU 序与 block 下标**完美单调一致**（ρ ≡ −1.0000，294/294），
> 因此**不存在 entry 内重排空间**。
> **该单调性对应"深优先"还是"浅优先"，当前 `NOT_OBSERVABLE`**（需 P5，覆盖率不足）。
> 本文不据此授权 Layer 2（M1 明确要求：没有可靠 depth/chain identity 则标 `NOT_OBSERVABLE`）。

---

## 3. RC3 — 弱命题的适用条件与 Layer 2 的阻塞

### 3.1 修正：弱命题**仅在无共享的独立链**下成立

rev.2 §3.2 的弱命题原文含「**对其它链无影响**」。**该句在共享前缀下为假**：

```text
设 A、B 两个请求的前缀共享 root。
若把淘汰目标从共享 root 改到 A 的私有尾部：
  → root 得以保留 ⇒ B 的命中**同时改善**
⇒ 说"对其它链无影响"是错的
```

更根本地：**一个物理 block 可以属于多条逻辑链**（这正是 Phase 2C/2D 的共享结构），
且「每条链固定 k 个」**不是一个天然可实施的不变量**（策略在物理 block 上做选择，
链配额是它的**涌现结果**而非约束）。

**修正后的命题（严格限定）**：

> **当被比较的链块集合互不相交（无共享）时**，保持"每条链被选中的块数不变"，
> 把某条链的选择从较浅优先改为较深优先，则该链对应请求的 `j(r)` 不减小 ⇒ `recompute(r)` 不增；
> 且**对其余链无影响**（因块集互不相交）。
> ⚠️ **共享情形下本命题不适用**，须按物理 block / 前缀 DAG 逐一计算未来请求的 `j(r)`。

### 3.2 只保留一个可执行版本（且当前判定为阻塞）

rev.2 的 L2-A（同链退避）与 L2-B（桶内降序）**只保留 L2-A**（B 已被 §3.1 的无共享前提击破）。

```text
L2-A（唯一版本）
  主键: lru_rank（跨链分配不动）
  后处理: 若某链被选中 >= 2 块，且其**链内 lru_rank 序与链内位置序不一致**，
          则在该链内部改为更深优先
  fail-closed: 当 (a) 链身份或链内位置不可确定，或 (b) 该链块集合与其它候选块**有交集**（共享），
               或 (c) 该链被选中块数 < 2 时 —— **一律不做改动，退回原生 lru_rank 序**
```

### 3.3 阻塞：`chain_pos: int | None` **不足以**实现 L2-A

M1 指正成立。§3.2 的后处理需要三样东西，而一个 `int` 只给了其中一样：

| L2-A 需要 | `chain_pos: int \| None` 是否提供 |
| --- | --- |
| 块在其链内的位置 | ✅ |
| **链身份**（哪两个块属于同一条链） | ❌ **缺失** |
| **祖先/共享关系**（用于 fail-closed 判交集） | ❌ **缺失** |

⇒ **因此本文不再请求该字段**（依 M1：「若当前能力无法满足则如实标记阻塞，不抢先要求增加 depth 字段」）。

**Layer 2 判定：`BLOCKED`（能力不足）**，而非「6.6% 的窄机会」。
实现它至少需要 `(chain_id, chain_pos)` 成对可读，**且**在共享情形下还需块级 owner 交集的
只读视图——这已超出「直通一个已存在字段」的范围，属**新观测缝**，本轮不请求。

---

## 4. RC4 — 边际重算的正确公式（新旧成本差）

### 4.1 rev.2 的错误

rev.2 §2.3 把「本次使 `j(r)` 变小」乘以**淘汰后的全部未命中后缀长度**当作增量，
**会重复计算此前已缺失的部分**。M1 的算例：

```text
长度 m=4，原 j_old=3，现 j_new=2
真实增量 = (3 − 2) × B = B
rev.2 的算法 = (4 − 2 + 1) × B = 3B        ← 错，多算了 2B
```

### 4.2 修正后的定义

```text
recompute_level(r) = (m_r − j(r) + 1) × B            ← 绝对水平（§2.2 已正确）
marginal:  ΔR = Σ_r  B · max(0, j_old(r) − j_new(r))  ← 边际增量（本版修正）
```

⚠️ **两条限制**（必须与公式同时表述）：

1. `ΔR` 是**相对同一请求路径的额外 recomputation**，
   **不等于**该请求实际发生的全部 prefill tokens（后者还含自然新增内容）；
2. **共享前缀的聚合必须按未来请求逐一计算**——一个物理 block 的淘汰会同时影响
   所有经过它的请求路径，**不可**把一个物理淘汰直接等同于固定 token 损失。

---

## 5. RC5 — 验证计划修正

### 5.1 契约修正：`bridge._validate_selection` 的真实要求

已核实 `src/kvopt/runtime/vllm/bridge.py:65-80`：

```text
1. required_blocks >= 0
2. len(selected) >= min(required_blocks, len(candidates))   ← "足够数量"，不是"恰好 R"
3. len(selected) == len(set(selected))                      ← 无重复
4. selected ⊆ {candidate.block_id}                          ← 取自 candidates
```

⇒ rev.2 写的「**恰好** required_blocks 个（不得多、不得少）」**是错的**，已更正。
新策略可以返回 `min(R, len(candidates))` 个。

### 5.2 ⭐ 关键区分：**排序序列不同 ≠ 淘汰集合不同**

```text
adapter 返回的序列中，被淘汰的是**被选中的那一批块**；
同一集合内的**次序交换**不改变哪些块被淘汰 ⇒ 不改变物理状态 ⇒ 不能作为有效提升。
真正有效的差异 = **selected victim SET 不同**（等价地：消费了 free queue 的不同前缀）。
```

⇒ 本设计的"分歧"判据一律定义为**集合层面**的分歧。

### 5.3 最小路径（M1 要求的先后顺序）

```text
第 0 步（已有数据即可做，无需新实验）:
    在某个合法 block-level 候选集合下，确认新规则与 native 的 **victim SET 有可复核分歧**
    若无分歧 ⇒ 如实写 **NO_HEADROOM_OBSERVED**，不进入后续步骤
第 1 步: 同一输入、同一后续工作负载，做**少量配对 native 执行**
第 2 步: 四层机制链 + 失败归因表
```

**第 0 步的当前答案（本文已给出）**：

```text
冻结接口内可用于排序的量 = {lru_rank, has_block_hash, ref_cnt}
  lru_rank     = 基线本身
  has_block_hash = native 已用（prepend_n；实测冷端富集 54/54）
  ref_cnt      = 恒为 0（源码 assert）；H1 中未持久化
⇒ 无任何字段能**有依据地**产生不同的 victim SET
⇒ 结论：**NO_HEADROOM_OBSERVED at the frozen block-level boundary**
   （这是构造性结论，不是"实验未观察到"）
```

⚠️ 存在排序余地的决策有 54/87（§0.2 实测 A），但**没有成本信号去正当化任何偏离**。

### 5.4 四层机制链（保留）与失败归因表

```text
第 1 层  selected victim SET 是否不同（且合法）？
第 2 层  物理缓存状态是否改变（存活块集合不同）？
第 3 层  aggregate recomputed tokens 是否改变？
第 4 层  方向与主张是否一致？
```

| 观察 | 归因 | 处置 |
| --- | --- | --- |
| 第 1 层不过 | **未触发** | 本文预期即为该情形（§5.3） |
| 第 1 层过、第 2 层不过 | **未实现** | 检查是否发生真实 hash cleanup |
| 第 1、2 层过、第 3 层不过 | **机制失败**（成本模型错） | 修订或放弃 |
| 第 3 层过但方向相反 | **机制失败** | 必须解释，不得以"效应小"掩盖 |
| 全过但效应极小 | **有效但不可用** | 如实报告 |

### 5.5 消融臂（按 M1 修正）

| 臂 | 定义 | 说明 |
| --- | --- | --- |
| **A0** | `NativeLRUAdapter` | 基线 |
| ~~A1~~ | ~~Layer 1~~ | **已删除**（§1.4） |
| **A2** | L2-A（链内深度校正，跨链不动） | 依赖 §3.3 的阻塞字段 ⇒ **当前不可实现** |
| **A3** | A2 + `lru_rank` 主序 | 同上 |
| **A4** | 链内方向反转（浅优先） | **报告项，不是硬门槛**：应报告合法分歧、真实物理淘汰、token 方向与原因 |
| **A5** | 深度/位置全部置常数 | 层内触发条件失效 ⇒ **应逐位等同 A0**；若不等，须归因到**具体排序差异**（不是绝对必要条件） |
| **A6** | 去掉 `lru_rank` 主序（改用**稳定 `block_id` 升序**作 tie-break） | 说明：`EvictionCandidate` **没有**逻辑身份字段，此处的 identity = **`block_id`**；预期显著劣于 A3（实证跨链反例）。**报告项，非硬门槛** |

⚠️ A4/A6 若**更差**，按 M1 要求**不得**视为"必须满足的先验门槛失败"，而应报告方向与原因。

### 5.6 两个案例（M1 交付项 4）

**（a）无效差异案例 —— 可手工复核：序列交换不改变集合**

用 §1.2 的同一快照（`h1-f1-draw-04-seed-101` @ event 95）：

```text
required_blocks = 30；queue_len = 83；hashless = 24（rank 0..23）；first_hashed_rank = 24
native 选中的是 rank 0..29 = 全部 24 个 hashless + 最冷的 6 个 hashed
```

现假设某策略返回**同样的 30 个块**，只把其中两个 hashed 块**互换次序**。依据：

```text
bridge.select_blocks() 文档字符串：
  build_candidates()  = "Snapshot free-queue blocks in their current native LRU order."
  "This class does not evict blocks itself. The caller remains responsible for
   handing the validated block IDs back to the existing vLLM allocation and eviction path."
```

⇒ 执行方按**返回的 ID 集合**去驱动 vLLM 的分配/淘汰路径，**返回序列的次序不参与淘汰决策**
⇒ **被淘汰的集合不变 ⇒ 物理状态不变 ⇒ 该差异无效**（不能作为提升）。

进一步：要真正得到**不同的集合**，就必须跳过 rank 24..29 中某个 hashed 块、改取 rank ≥ 30 的
另一个 hashed 块。两者都带 hash（成本同类），**唯一区别是 `lru_rank`** ——
即**用更热的块替换更冷的块**，且**没有任何成本信号可以正当化它**。

**（b）有效差异案例 —— 在当前边界内 `无法构造`（这本身就是阻塞结论）**

"有效差异"需满足：**存在一个由实测成本正当化的、不同的 victim SET**。逐字段排除（§0.1、§1.1）：

```text
has_block_hash : 任何"排除 hashless 改取 hashed"的集合都更差（β(hashless)=0）；
                 native 已把 hashless 置于冷端 ⇒ 该轴上 native 已是最好，无正当分歧
ref_cnt        : 恒为 0（源码 assert）；H1 中未持久化（6606 行出现 0 次）⇒ 无法区分
lru_rank       : 就是基线主键；以别的方式使用它 = 无依据的偏离
required/free/total_blocks : 全局标量，不能对候选排序
```

⇒ **无法构造有效差异案例**，故判定 **`NO_HEADROOM_OBSERVED`**（§5.3）。
此外 33/87 的决策 `required_blocks >= queue_len`，**集合被完全固定**（必须全取），
在这些决策上连"不同集合"都不存在。

⇒ 一个**有效**案例需要至少一个缺失信号（块→前缀位置 / 链身份 / owner 集合）——
这些在本轮**不予请求**（§3.3、§7）。

---

## 6. 决策边界与接口映射（沿用 rev.2/rev.3，已核实）

### 6.1 边界

```text
src/kvopt/runtime/vllm/adapter.py:11   class EvictionPolicyAdapter(ABC)
    select_victims(candidates: Sequence[EvictionCandidate],
                   context: EvictionContext) -> Sequence[int]
    "Choose block-level victims without mutating vLLM cache state directly."
```

| 项 | 值（已核实） |
| --- | --- |
| 输入 | `EvictionCandidate` = `{block_id, ref_cnt, has_block_hash, lru_rank}`；`EvictionContext` = `{required_blocks, free_blocks, total_blocks, timestamp}` |
| 输出 | victim block IDs 序列；契约见 §5.1 |
| 下游 | `BlockPool.get_new_blocks()` → `_maybe_evict_cached_block()` 真实 hash cleanup |
| 生产者 | `bridge.py:32-42` `build_candidates()`：`lru_rank` = 队列序号；`has_block_hash` = `block.block_hash is not None` |
| 上游类型 | `VLLMBlockLike` = `{block_id, ref_cnt, block_hash}` ⇒ **无前缀位置** |

### 6.2 `RuleStrategy` 丢弃 `state`（保留）

```text
src/kvopt/costaware/replay.py:252
    def pick_next(self, remaining, state):
        del state
        return self.rule.selection(remaining, 1)[0]
```

⇒ entry-level 若要表达依赖已释放集合的量，须用 **state-aware `ReleaseStrategy`**
（Protocol `:223`；`ExecutedP1BStrategy` `:256` 为先例），复用 `state.newly_eligible_after`（`:193`）。

---

## 7. 请求 M1 裁定（两条路径；原 C 路径已失去依据）

| 路径 | 内容 | 我的评估 |
| --- | --- | --- |
| **A. 关闭 block-level 线** | 接受 §5.3 的 `NO_HEADROOM_OBSERVED` | ⭐ **证据最强**：三条字段全部无可用信息（源码 + 实测） |
| **B. 授权范围变更 → entry-level** | 把 `Cost-Aware Pressure Release` 立为正式研究对象（唯一还有可观测量——共享/保护结构——的边界） | ⭐ **研究价值最高** |
| ~~C. Layer 2 窄实验~~ | ~~授予 `chain_pos` 做 6.6% 窗口验证~~ | **撤回**：① 6.6% 不可复现（实测 0% 重排自由度）；② 单字段不足（§3.3）⇒ 需新观测缝 |

**建议顺序：B > A。**

若 M1 选 **B**，我将在批准后**另立设计**（不混入本文），并沿用：
entry-level 边界、Q1/Q2/Q3 区分、F4 使用边界、四层链与失败归因表。

---

## 8. 局限与附件

### 8.1 局限

| # | 局限 |
| --- | --- |
| **L1** | 实测 A/B 来自 **H1 语料**（87 决策 / 6606 队列行 / 294 窗口）；**不外推** Phase 2E 或生产分布 |
| **L2** | 实测 B 只证明**单调性**；**方向（深/浅优先）为 `NOT_OBSERVABLE`**（P5 覆盖率不足） |
| **L3** | 实测 A 依赖 APC 语义（前缀命只刷新有 hash 块）；若某实现会刷新无 hash 块则需重测 |
| **L4** | `ref_cnt` 恒 0 的依据是 vLLM 源码断言；**H1 数据中该字段未持久化** |
| **L5** | **不承诺延迟收益**（Phase 2E 实测 token 下降未带来延迟改善） |
| **L6** | 合成网格；`max_new_tokens=1`，不代表 decode 期 |
| **L7** | 不用 `prefill_reload_seconds`（X3：H1 中与尺寸位置级同序） |
| **L8** | 不使用引用度/复用度（runtime 不可得） |
| **L9** | ⚠️ **过程教训**：rev.3 曾引用不存在的探针并写入不可复现数字。已撤回，且此后每条实测均附探针文件与定义 |

### 8.2 附件

1. **X1 已撤回**（`loss_views.py:74` 已有 `observed_recomputed_tokens`）；
2. **X3（RC6 修正）**：`prefill_reload_seconds` 与 `block_count` 的秩关系在 **H1 已核查**
   （114/114 决策、465/465 位置、99/99 决策内 ρ=1.0000）；
   **Phase 2E 语料尚未核查** —— 本文不据此对 Phase 2E 作任何结论。

⛔ 本设计**不**请求：改 native BlockPool / ref_cnt / hash cleanup / LRU；改冻结 Continuum 默认键或 TTL；
子 entry 释放（**不解锁 B1**）；**新观测缝**；重开 H1/H2；M1 通过前开始实现。

---

## 9. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| `free_blocks()` 分离 hashless/hashed 并 `prepend_n`/`append_n` | vLLM v0.27.1 `vllm/v1/core/block_pool.py`（M1 引第 727–742 行） |
| `get_new_blocks()` 用 `popleft_n` 且 `assert block.ref_cnt == 0` | 同上（M1 引第 647–666 行） |
| hash-split 为显式、有条件机制 | 上述文件的提交 `a82f1b3`（*Skip LRU hash-split in free_blocks when prefix caching is …*） |
| `EvictionPolicyAdapter.select_victims` 契约 | `src/kvopt/runtime/vllm/adapter.py:11-25` |
| `EvictionCandidate` / `EvictionContext` 字段 | `src/kvopt/runtime/vllm/types.py` |
| `bridge.build_candidates`；`VLLMBlockLike` 无前缀位置 | `src/kvopt/runtime/vllm/bridge.py:32-42`、`:14-19` |
| `_validate_selection` 真实契约（≥ min(R,n)、无重复、取自 candidates） | `src/kvopt/runtime/vllm/bridge.py:65-80` |
| `NativeLRUAdapter` 按 `lru_rank` 取 `required_blocks` | `src/kvopt/runtime/vllm/adapter.py:27-38` |
| 实测 A：冷端 hashless 富集 54/54、枯竭 0/54、最早 hashless rank 0.0000 | `local/probe_l1_refined.py`（H1） |
| 实测 B：294 窗口 ρ ≡ −1.0000（100%），0% 存在重排空间 | `local/probe_rev3_verify.py`（H1） |
| 快照：`h1-f1-draw-04-seed-101`@95 `queue=83 hashless=24 first_hashed_rank=24` | 同上 |
| `ref_cnt` 在 6606 条队列行中出现 0 次 | 同上 |
| `RuleStrategy` 丢弃 `state` | `src/kvopt/costaware/replay.py:252` |
| `ReplayState.newly_eligible_after` / `ExecutedP1BStrategy` | `src/kvopt/costaware/replay.py:193` / `:256` |
| `observed_recomputed_tokens` 视图已存在 | `src/kvopt/profiling/loss_views.py:74-75` |
| APC 需连续前缀 | `docs/phase2b-m6-experimental-fidelity-repair-spec.md` §1 |
| F4 odd=SHARED_ROOT treatment / even=negative control | `src/kvopt/workload/phase2e_materialize.py`；`docs/phase2e-m4-measured-review.md` §2.1 |
| 基线键 `(deadline, min LRU over newly_eligible, identity)` | `src/kvopt/continuum/pressure.py:324` |
| 冻结接受协议 / 统计单位 | `docs/phase2a-m4-rule-acceptance-protocol.md` |
