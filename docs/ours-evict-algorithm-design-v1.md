# Ours-Evict — Algorithm Design（rev.5）

**提交人**：M4　**送审**：M1　**日期**：2026-10-17
**阶段**：Phase 2 Cost-Aware Eviction 算法设计（**设计 PR，不含 runtime 实现**）
**主目标**：`aggregate_recomputed_tokens`　**辅助观测**：TTFT / queue delay
**边界**：不改 native BlockPool / ref_cnt / hash cleanup / LRU，不改冻结 Continuum baseline，**B1 保持 LOCKED**，不实施 runtime

> **rev.5 说明**：本轮响应 M1 对 rev.4 的 `CHANGES_REQUESTED`（**结论范围修订**）。
> M1 的四项要求逐项落实：§2（结论降级）、§3（H1 缺陷逐项映射）、§4（保留两种粒度）、§6（最小验证方案）。
> **本轮不关闭 Block-level、不批准转向 Entry-level、不请求任何实现或观测缝扩张。**

### 结论（修订后）

```text
METHOD_BLOCKED_BY_CURRENT_INTERFACE
```

即：**在当前冻结的最小 Adapter 接口下，我找不到有成本依据、能改变 native victim set 的规则**。
这**既不等于**「Block-level 没有优化空间」，**也不等于**「Entry-level 研究价值更高」。

我**撤回** rev.4 中两个证据无法支持的判断：

| rev.4 的判断 | 处置 | 原因 |
| --- | --- | --- |
| 「`BLOCK_LEVEL_HAS_NO_HEADROOM`」 | **撤回** | 冻结接口 ≠ 全部可获得信息（native 还有 `block_hash_num_tokens` 等，见 §3.5）；且证据主要来自有已知缺陷的 H1 |
| 「建议 B（Entry-level）> A（关闭 Block-level）」 | **撤回** | 两条路线**缺少在可信工作负载上的直接对照**（§4） |

---

## 0. 变更轨迹（含我自己的五次撤回）

| 版本 | 主张 | 结果 |
| --- | --- | --- |
| v1 | `damage/(1+credit)` entry-level 成本模型 | **撤回**：语义错（被保护的块不会被淘汰）+ 比值退化为 credit 的单调函数 |
| v2 | Layer 1 可证明弱占优；全局深优先定理 | **撤回**：全局深优先被跨链反例击破 |
| v3 | Layer 2「6.6% 窗口」 | **撤回**：探针不存在、数字不可复现（重建后为 0%） |
| v4 | 「接口天花板」；建议 Entry-level 优先 | **结论范围撤回**（本轮，§2） |
| v5 | `METHOD_BLOCKED_BY_CURRENT_INTERFACE` + H1 局限映射 + 两种粒度并置 + 最小验证方案 | 本文 |

---

## 1. 已确认、且本轮**保留**的分析

以下结论证据充分，本轮不作改动。

### 1.1 native hashless-first 是引擎已有行为（源码级）

```text
vLLM v0.27.1  vllm/v1/core/block_pool.py
  free_blocks()     分离 blocks_without_hash / blocks_with_hash
                    → prepend_n(without_hash) + append_n(with_hash)     （M1 引 727–742 行）
  get_new_blocks()  free_block_queue.popleft_n(num_blocks)
                    → _maybe_evict_cached_block(block)
                    → **assert block.ref_cnt == 0**                      （M1 引 647–666 行）
```

⇒ ① 无 hash 块已被引擎**主动前置**；② 候选块 `ref_cnt` **恒为 0**。
含该逻辑的提交 `a82f1b3`（*Skip LRU hash-split in free_blocks when prefix caching is …*）
表明这是**显式、有条件的既有机制**。

**⇒ 结论（保留）**：hashless-first **不是我们的创新**，Layer 1 从 Ours-Evict 中**删除**。

### 1.2 冻结 Adapter 接口的字段集合（源码级）

```text
src/kvopt/runtime/vllm/adapter.py:11
    class EvictionPolicyAdapter(ABC):
        def select_victims(self, candidates: Sequence[EvictionCandidate],
                           context: EvictionContext) -> Sequence[int]
        "Choose block-level victims without mutating vLLM cache state directly."

EvictionCandidate = { block_id, ref_cnt, has_block_hash, lru_rank }
EvictionContext   = { required_blocks, free_blocks, total_blocks, timestamp }
上游 VLLMBlockLike = Protocol { block_id, ref_cnt, block_hash }   （bridge.py:12-17，无前缀位置）
```

⚠️ **`VLLMBlockLike` 是 `Protocol`（"Minimal shape required"）** ——
即它是一个**最小形状契约**，而非 vLLM 原生块的完整投影。
这从类型系统层面印证了 §3.5：**冻结的最小接口 ≠ 可获得的决策时信息上限。**

**⇒ 结论（保留）**：在该接口下 `lru_rank` 即基线、`has_block_hash` 已被引擎用掉、
`ref_cnt` 恒为 0 ⇒ **无可用成本信号**。这是一个**真实的工程瓶颈**。

⚠️ **但必须同时写明其范围**（M1 第 3 点）：**这是"当前接口"的限制，
不是"native vLLM 可获得的决策时信息"的上限**（§3.5）。

---

## 2. 结论范围修订（M1 要求 1）

### 2.1 判定文字

```text
旧：BLOCK_LEVEL_HAS_NO_HEADROOM          ← 撤回（过大范围）
新：METHOD_BLOCKED_BY_CURRENT_INTERFACE  ← 采用
```

### 2.2 三处必须限缩的表述

| # | 原文 | 修订后 | 理由 |
| --- | --- | --- | --- |
| **S1** | 「`0%` 重排自由度」 | 「**在 H1 语料中观测到 0%** 的 entry 内重排自由度」 | 该量定义在 `candidates[].block_ids` 下标上，**其是否等于真实 prefix depth 未被证明**（§3.3） |
| **S2** | 「`NO_HEADROOM_OBSERVED`（构造性结论）」 | 「**`NO_HEADROOM_OBSERVED` in H1 and under the frozen four-field interface**」 | 构造性部分只覆盖 hashless 轴（§1.1，可证明）；hashed 之间的选择**未被排除** |
| **S3** | 「hashed 之间无更优选择」（隐含） | 「**未在 H1 中观察到**可正当化不同 victim set 的成本信号」 | 见 §3.2：H1 无法表达共享/增长/异步，故**不能**由此否定这些机制 |

### 2.3 本轮**不**声称的内容

```text
❌ 不声称 Block-level 已无优化空间
❌ 不声称 Entry-level 研究价值更高（两条路线未在可信负载上对照）
❌ 不声称 hashed blocks 之间不存在更优选择
❌ 不声称 native LRU 在重计算意义上已最优
```

---

## 3. H1 数据限制与研究结论的逐项对应（M1 要求 2）

### 3.1 已确认的 H1 缺陷（Phase 2B/2C 审计）

| ID | 缺陷 | 含义 |
| --- | --- | --- |
| **F-PREFIX** | 跨 program 共享前缀**未落实到 native token 内容**；实际前缀主要由 `program_id` 决定 | 共享结构**未被表达** |
| **F-ARRIVAL** | **42/42** 场景均为单并发，无真实请求交错 | 并发/排队**未被表达** |
| **F-HISTORY** | `eta`、`queue_delay` 未形成运行时判别差异 | TTL/history 维度**退化** |
| — | 多轮请求**没有真实累积上下文**，前缀内容基本固定 | 上下文增长**未被表达** |
| **F-PRESSURE** | logical release / physical eviction / future recomputation 的因果不能等同；**未选择方案的反事实损失缺失** | 归因与反事实**不可得** |

### 3.2 缺陷 → 结论 的映射（**区分"未观察到"与"被证伪"**）

| 我此前的结论 | 依赖的 H1 特性 | 缺陷命中 | **正确表述** |
| --- | --- | --- | --- |
| hashless-first 无增益 | 自由队列顺序（引擎不变量，非负载性质） | 不受影响 | ✅ **可保留**（且已由源码与实测双重支撑） |
| entry 内重排自由度 0% | 前缀内容固定、无真实跨 program 共享、同步执行 | **F-PREFIX、F-ARRIVAL、前缀不增长** | 「**在 H1 的负载构造下未观察到**重排自由度」；**不得**外推为一般结论 |
| hashed 之间无更优选择 | 需要共享/增长/异步带来的候选差异 | **F-PREFIX、F-ARRIVAL、前缀不增长** | 「**当前语料未观察到**」；**不是**「机制被证伪」 |
| 方向（深/浅优先）不可判定 | 需 `block_id → prefix position` 映射 | P5 覆盖率不足 | ✅ 保留为 **`NOT_OBSERVABLE`** |
| 无法构造有效差异案例 | 需要成本信号区分候选 | **F-PRESSURE**（反事实缺失） | 「在**冻结四字段 + H1** 下无法构造」；**不得**推广为「无法构造」 |

### 3.3 ⭐ 一条重要的内部限制（`block_ids` 下标 ≠ prefix depth）

我此前的「ρ ≡ −1.0000 / 0% 重排自由度」定义为

```text
rho = Spearman(k, native_lru_rank)，k = candidates[].block_ids 的下标（升序）
```

| 项 | 是否已证明 |
| --- | --- |
| `native_lru_rank` 与下标 `k` **单调一致** | ✅ 已实测（294/294 恰为 −1） |
| `k` **等于**真实 prefix depth / 前缀位置 | ❌ **未证明**（需 P5 的 `block_id → token 位置`） |
| 该单调性在**重计算意义上最优** | ❌ **未证明** |

⇒ **因此本报告只主张「单调性」与「H1 观测到的 0% 重排自由度」，
不主张「该排序在重计算意义上已最优」。**

### 3.4 H2-M4 FAIL 的使用边界（M1 第 4 点）

```text
H2-M4 的 FAIL 保持不变（不重开、不改判）。
但它测试的是 **single-prefix + 固定淘汰数量**下，
"Entry + Native LRU" vs "trailing-j 受控机制" 的特定 comparator。

⇒ 只否定**该冻结 comparator**，**不能**否定整个 Block-level 方法空间。
⇒ M2/M3 关于"前缀位置与重计算关系"的**正面测量仍然有效**（未被本轮削弱）。
```

### 3.5 冻结接口 ≠ native 信息上限（M1 第 3 点）

M1 指正成立。native `KVCacheBlock` 还含**未被 Adapter 透出**的字段：

```text
vLLM v0.27.1（block_pool.py 中可见其真实使用）
  blk.block_hash_num_tokens          # 主 hash 覆盖的 token 边界
  block.set_block_hash(..., num_tokens=num_tokens)
  num_tokens = src_block.block_hash_num_tokens
```

⇒ 该字段提供**块的主 hash 前缀 token 边界**，是**决策时可读**的额外信息维度。
此外原生 hash 映射与既有观测机制可能支持更多只读内容关系。

⚠️ **但这些字段是否足以构建有效算法，尚未验证。** 本轮**不请求**扩张接口
（§7 列为待验证的**能力问题**，而非已批准的改动）。

⇒ 因此采用 `METHOD_BLOCKED_BY_CURRENT_INTERFACE`，
而**不是**「block-level 没有可用信息」。

---

## 4. 保留两种决策粒度（M1 要求 3：**本轮不作选择**）

两条路线**并置**，各自列出：可利用的合法在线信号、预期的成本机制、对应基线、当前缺失的证据。

### 4.1 对照表

| 维度 | **Block-level**（Ours-Evict 现状） | **Entry-level**（Cost-Aware Pressure Release） |
| --- | --- | --- |
| **决策边界** | `EvictionPolicyAdapter.select_victims`（返回 victim block IDs） | Continuum retention pressure release（`FORCED_RELEASE_DECISION.payload.candidates`） |
| **决策对象** | 物理 block | logical retention entry |
| **合法在线信号（现状）** | `lru_rank`、`has_block_hash`、`ref_cnt`（**实质无效**，§1.2） | `block_ids`、`initially_reclaimable_block_ids`、`retention_deadline_timestamp`、`elapsed_since_ttl_decision_seconds`、`prefill_reload_seconds`、`next_tool_type`、`waiting_followup` |
| **潜在但未透出的信号** | `block_hash_num_tokens`、原生 hash 映射（§3.5，**未验证**） | 候选集内的**共同所有权**（已在 `owners_by_block` 可得，仅用于 eligibility） |
| **预期成本机制** | 保留"链上更值得复用的块"⇒ 抬高 `j(r)` | 释放"回收量/损伤比"更好的 entry ⇒ 减少未选中方案的反事实重算 |
| **对应基线** | `NativeLRUAdapter`（= native free-queue LRU） | 冻结 Continuum 释放键 `(deadline, min LRU over newly_eligible, identity)` |
| **已有证据** | 四字段内**无可用成本信号**（源码 + H1 实测）；hashless 轴已由引擎占据 | H1 中 `relief ≡ block_count`（**471/471**）⇒ **无判别方差**；简单规则族无稳健增益；Phase 2D 构造出真实共享保护但**未证明 aggregate 收益或在线可预测性**；Phase 2E **未测试**本算法，且 F4 shared-root treatment 机制 `NOT_REALIZED` |
| **缺失证据（阻塞）** | ① 未透出字段是否足以区分候选（**能力问题**）；② 可信负载下的候选方差（H1 无共享/无增长） | ① 共享结构下 **候选间的边际差异**是否存在；② 是否存在**决策时可观测**的判别信号；③ 反事实损失（未选择方案的观测缺失） |
| **当前判定** | `METHOD_BLOCKED_BY_CURRENT_INTERFACE` | **未评估**（缺少可信负载上的直接对照） |

### 4.2 我不能在此作出的判断

```text
❌ 不能说 Block-level 已无空间（§3.5：接口 ≠ 信息上限）
❌ 不能说 Entry-level 更好（条目 4.1「已有证据」栏显示其正负证据均弱）
❌ 不能说两条路线中任一条已被证伪
```

⇒ **正确做法**：先用**修复后的运行环境 + 已有 workload** 取得
「哪种粒度存在可观测、可利用、可验证的额外优化空间」的**证据**（§6），再作选择。

### 4.3 历史脉络（M1 第 5 点）

项目初期确立的研究目标是 **Cost-Aware Eviction / Management**；
**独立 Block-level 算法是后来才被当作优先实现路径**；
Phase 2A 的计划本就把**决策粒度列为待研究问题**。

⇒ 现在**重新审议粒度是合规的**，但**不得**仅据「旧接口 + 旧数据」作出最终选择。

---

## 5. 已核实的技术事实（保留，供两条路线共用）

### 5.1 成本模型：三个必须区分的量

| # | 量 | 等于重计算？ |
| --- | --- | --- |
| **Q1** | Logical protection released | ❌ |
| **Q2** | Physical cached blocks evicted | ❌（但**是** Q3 的必要条件） |
| **Q3** | Future recomputed prefix tokens | ✅ **主目标** |

⇒ **Q1 ⇏ Q2 ⇏ Q3**。

### 5.2 APC 语义与边际重算（修正版）

```text
j(r) = min{ k : r 的链上第 k 块已被淘汰 }        （均未淘汰则 j(r) = m_r + 1）
recompute_level(r) = (m_r − j(r) + 1) × B
marginal:  ΔR = Σ_r B · max(0, j_old(r) − j_new(r))     ← 新旧成本差（rev.4 已修正）
```

⚠️ 两条限制：① `ΔR` 是**相对同一请求路径的额外 recomputation**，**不等于**该请求全部 prefill tokens；
② **共享前缀必须按未来请求逐一聚合**（一个物理 block 的淘汰同时影响所有经过它的路径）。

### 5.3 集合 vs 序列（已由 bridge 文档证实）

```text
bridge.select_blocks(): "This class does not evict blocks itself. The caller remains
                         responsible for handing the validated block IDs back to the
                         existing vLLM allocation and eviction path."
⇒ 只有 **selected victim SET 不同**才改变物理状态；同一集合内的**次序交换**无效。
```

### 5.4 契约：`bridge._validate_selection`（`bridge.py:65-80`）

```text
required_blocks >= 0
len(selected) >= min(required_blocks, len(candidates))    ← "足够"，不是"恰好 R"
无重复；selected ⊆ candidates
```

### 5.5 四层机制链与失败归因

```text
第 1 层  selected victim SET 是否不同（且合法）？
第 2 层  物理缓存状态是否改变（存活块集合不同）？
第 3 层  aggregate recomputed tokens 是否改变？
第 4 层  方向与主张是否一致？
```

| 观察 | 归因 | 处置 |
| --- | --- | --- |
| 第 1 层不过 | **未触发** | 属预期情形之一，**不是**机制失败 |
| 第 1 层过、第 2 层不过 | **未实现** | 检查是否发生真实 hash cleanup |
| 第 1、2 层过、第 3 层不过 | **机制失败**（成本模型错） | 修订或放弃 |
| 第 3 层过但方向相反 | **机制失败** | 必须解释，不得以"效应小"掩盖 |
| 全过但效应极小 | **有效但不可用** | 如实报告 |

---

## 6. 最小验证方案（M1 要求 4）

**目标**：回答「**在已修复的真实 vLLM 工作负载下，哪种决策粒度存在可观测、可利用、可验证的额外优化空间**」。
**不做** H1/H2 重跑、**不做** campaign、**不请求**新观测缝或接口扩张。

### Step 0 `[纯离线 · 用已有数据 · M4 主责]`

| # | 动作 | 用到的已有资产 | 输出判据 |
| --- | --- | --- | --- |
| **0-a** | 在 **Phase 2E** 语料上重跑 §5.2 的 `j(r)` / `ΔR` 计算，**按未来请求逐一聚合** | Phase 2E archive（`events.jsonl` + 请求级证据） | 是否存在**候选间**可分的 `ΔR` 方差 |
| **0-b** | 量 **block-level** 的候选方差：`has_block_hash` 之外的字段是否真的全无区分度（含未透出字段的**离线可用性**核查） | Phase 2E + native 事件（`VLLM_PREFIX_SNAPSHOT`） | 能否从已有记录**重建**某个未透出字段（如 `block_hash_num_tokens`），若能则说明是**透出问题**而非**能力缺失** |
| **0-c** | 量 **entry-level** 的候选方差：`initially_reclaimable_block_ids ⊊ block_ids` 是否在 Phase 2E 中出现（H1 恒等） | Phase 2E archive | 是否首次出现**可判别**的 `relief < block_count` |
| **0-d** | 归因能力核查：Phase 2E 是否提供「未选择方案」的任何只读对照 | Phase 2E archive | 若否，如实标 `NOT_OBSERVABLE`（不请求补采） |

**Step 0 的停止条件**：

```text
若 0-a 与 0-c 均显示"候选间无可分方差" ⇒ 如实报告 NO_OBSERVABLE_VARIANCE，
                                        不进入 Step 1，并请 M1 重新裁定研究方向
若 0-b 显示未透出字段**可离线重建** ⇒ 说明瓶颈是"透出"而非"信息"，
                                        据此提交**一个**最小字段请求（届时另批）
```

### Step 1 `[少量配对 native 运行 · 仅在 Step 0 显示存在分歧时 · M4+M6 共同]`

```text
前置：Step 0 找到「有成本依据、能改变真实 victim/release 选择」的场景
规模：最小配对（同输入、同后续工作负载），**不设正式统计门槛**
环境：Phase 2B/2C **修复后**的 native 运行环境（真实 vLLM + APC）
产出：四层链（§5.5）的逐层证据 + 失败归因
```

### 6.1 M4 / M6 分工

| 角色 | 负责 |
| --- | --- |
| **M4** | Step 0 全部离线分析；定义判据与可复核证据格式；撰写结论范围 |
| **M6** | Step 1 的 native 执行与证据归档；确认修复后环境的可比性（沿用 Phase 2E 的 Gate C 纪律） |
| **共同** | 交付一份**简短**的 Joint Evidence Note（不另立大型文档） |

### 6.2 本方案**不**包含

```text
❌ 不重做 H1/H2 ❌ 不启动 campaign ❌ 不实现 runtime policy
❌ 不请求新观测缝 ❌ 不扩张 Adapter 接口 ❌ 不解锁 B1 ❌ 不改 native ownership
```

---

## 7. 可复核证据（M1 要求：`local/` 探针需最小可复核证据）

⚠️ `local/` 在 `.gitignore` 中，故探针**不可入库**。为使 M1 可独立复算，
本节给出**定义 + 命令 + 观测输出**；探针逻辑均为对 H1
`…/phase2a-h1-formal-level-a-runs-v1/<run>/events.jsonl` 的
`FORCED_RELEASE_DECISION.payload` 的纯读取。

### 7.1 复现命令

```powershell
cd <repo>
python local\probe_hashless_prefix.py      # E1
python local\probe_l1_refined.py           # E2
python local\probe_rev3_verify.py          # E3
```

### 7.2 E1 — native hashless 严格前缀（`probe_hashless_prefix.py`）

**定义**：对每个 decision，令 `k` = 无 hash 块数、`H` = 这些块的 `native_lru_rank` 集合；
`strict prefix ⇔ H == {0..k−1}`。另测「hashless 优先」重排是否改变 victim **集合**。

```text
有 hashless 块的决策                                     : 54   （完全无 hashless：33）
  STRICT PREFIX (H == {0..k-1})                          : 54
  interleaved（有 hashed 块排在 hashless 之前）            :  0
  required <= k（整次选择都是零成本）                       :  0
顺序相关决策 (required < queue)                          : 54
  set CHANGED : 0        set SAME : 54
```

⇒ **hashless 块恰好占据最冷的 `0..k−1` 段** ⇒ 任何"hashless 优先"策略**不可能**选出不同集合。
⇒ Layer 1 的无效是**结构性**的（比"富集"表述更强），但**仅覆盖 hashless 轴**。

⚠️ 该探针此前被一个**不存在的文件**引用（`probe_hashless_prefix.py` 曾经缺失，见 §0 轨迹）。
本轮我**重新实现并运行**后才写入本节 —— 这是 L9 教训的直接应用。

### 7.3 E2 — 冷端富集与顺序相关性（`probe_l1_refined.py`）

```text
决策总数                                                : 87
  required >= queue（顺序无关）                          : 33 = 37.9%
  required <  queue（顺序才起作用）                       : 54 = 62.1%
在 54 个顺序相关决策上：
  hashless 占比（整队列）  median 0.2980
  hashless 占比（冷端）    median 0.8591
  冷端 hashless 富集       : 54 / 54 = 100%
  冷端 hashless 枯竭       :  0 / 54 =   0%
  最早 hashless 归一化 rank : median 0.0000
  最早 hashed   归一化 rank : median 0.3012
```

### 7.4 E3 — entry 内单调性与可审计快照（`probe_rev3_verify.py`）

```text
可测链窗口（>=3 可比块） : 294
rho = Spearman(k, native_lru_rank)： min = median = mean = max = −1.0000
恰为 −1.0000            : 294 / 294 = 100%
rho > 0（存在重排空间）  : 0 / 294 = 0%

可审计快照（生成路径见 §7.1，按 native_lru_rank 升序）：
  run_id = h1-f1-draw-04-seed-101   event_index = 95
    required_blocks=30  queue_len=83  hashless_in_queue=24  first_hashed_rank=24
    最冷 12: (60,0,F) (61,1,F) (62,2,F) (63,3,F) (64,4,F) (65,5,F)
            (66,6,F) (67,7,F) (68,8,F) (69,9,F) (70,10,F) (71,11,F)

ref_cnt 可观测性：original_free_queue 行数 6606，其中含 ref_cnt 的 0 行
```

⚠️ **E3 的适用范围**：`k` = `block_ids` 下标，**是否等于真实 prefix depth 未证明**（§3.3）；
故 E3 只支持"单调性"，**不**支持"该排序在重计算意义上最优"。

### 7.5 关于 evidence 的诚实说明

```text
- 以上三项均在 **H1** 语料上完成；**未**在 Phase 2E 语料上复核（§6 Step 0 即为此）。
- 探针文件位于未入库的 local/；本节给出定义与命令，M1 可独立复算。
- 若 M1 希望这些核查**入库**（例如置于 scripts/ 或 tools/），请指示，我将按最小脚本提交。
```

---

## 8. 局限（更新）

| # | 局限 |
| --- | --- |
| **L1** | 全部实测来自 **H1**；其负载构造有已确认缺陷（§3.1）⇒ **不外推** |
| **L2** | `candidates[].block_ids` 下标 **未证明等于** prefix depth（§3.3） |
| **L3** | 「0% 重排自由度」是 **H1 特定观测**，**不是**一般结论（§2.2 S1/S2） |
| **L4** | 冻结四字段 ≠ native 信息上限（§3.5：`block_hash_num_tokens` 等未透出） |
| **L5** | H1 中 `ref_cnt` 未持久化；其"恒 0"依据为 vLLM 源码断言 |
| **L6** | **不承诺延迟收益**（Phase 2E 实测 token 下降未带来延迟改善） |
| **L7** | 合成网格；`max_new_tokens=1`，不代表 decode 期 |
| **L8** | 不使用 `prefill_reload_seconds`（X3：H1 中与尺寸位置级同序；**Phase 2E 未核查**） |
| **L9** | ⚠️ **过程教训**：rev.3 与一次中间提交曾两次引用**不存在**的探针并写入不可复现数字。现已撤回，且本文每条实测均附定义、命令与输出（§7） |

---

## 9. 请求 M1 裁定

1. **结论范围**：是否接受 `METHOD_BLOCKED_BY_CURRENT_INTERFACE` 取代 rev.4 的
   `BLOCK_LEVEL_HAS_NO_HEADROOM`，并接受 §2.2 的三处限缩？
2. **H1 缺陷映射**：§3.2 的「缺陷 → 结论 → 正确表述」是否完整、无遗漏？
3. **两种粒度并置**：§4.1 的对照（信号 / 机制 / 基线 / 缺失证据）是否满足"不作选择但各自明确"？
4. **最小验证方案**：是否批准 §6 的 Step 0（纯离线、已有数据、M4 主责）？
   Step 1（少量配对 native 运行）是否**待 Step 0 结果后**再逐案批准？
5. **证据入库**：§7.5 的探针是否需要入库（`scripts/` 或 `tools/`）？请指示。

⛔ 本设计**不**请求：改 native BlockPool / ref_cnt / hash cleanup / LRU；改冻结 Continuum 默认键或 TTL；
子 entry 释放（**不解锁 B1**）；新观测缝；Adapter 字段扩张；重开 H1/H2；M1 通过前开始实现。

---

## 10. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| `free_blocks()` hash-split + `prepend_n`/`append_n` | vLLM v0.27.1 `vllm/v1/core/block_pool.py`（M1 引 727–742） |
| `get_new_blocks()` `popleft_n` + `assert ref_cnt == 0` | 同上（M1 引 647–666） |
| `block_hash_num_tokens` 存在（未透出） | 同上 `blk.block_hash_num_tokens`、`set_block_hash(..., num_tokens=...)` |
| hash-split 为显式机制 | 同文件提交 `a82f1b3` |
| `EvictionPolicyAdapter.select_victims` 契约 | `src/kvopt/runtime/vllm/adapter.py:11-25` |
| `EvictionCandidate` / `EvictionContext` 字段 | `src/kvopt/runtime/vllm/types.py` |
| `VLLMBlockLike` 是 Protocol、无前缀位置 | `src/kvopt/runtime/vllm/bridge.py:12-17` |
| `_validate_selection` 契约 | `src/kvopt/runtime/vllm/bridge.py:65-80` |
| bridge **不自行淘汰**（集合语义） | `src/kvopt/runtime/vllm/bridge.py:21-27` docstring |
| `NativeLRUAdapter` 按 `lru_rank` | `src/kvopt/runtime/vllm/adapter.py:27-38` |
| E1：hashless 严格前缀 54/54、set CHANGED 0/54 | `local/probe_hashless_prefix.py`（H1） |
| E2：冷端富集 54/54、最早 hashless rank 0.0000 | `local/probe_l1_refined.py`（H1） |
| E3：294 窗口 ρ ≡ −1.0000；快照；ref_cnt 0/6606 | `local/probe_rev3_verify.py`（H1） |
| H1 缺陷 F-PREFIX / F-ARRIVAL / F-HISTORY / F-PRESSURE | `docs/phase2b-m6-experimental-fidelity-repair-spec.md` §0.1；`docs/phase2c-m6-workload-reuse-audit.md` |
| H1 `relief ≡ block_count` 471/471 | `local/probe_relief_field.py` |
| 基线键 `(deadline, min LRU over newly_eligible, identity)` | `src/kvopt/continuum/pressure.py:324` |
| `RuleStrategy` 丢弃 `state` | `src/kvopt/costaware/replay.py:252` |
| `ReplayState.newly_eligible_after` / `ExecutedP1BStrategy` | `src/kvopt/costaware/replay.py:193` / `:256` |
| `observed_recomputed_tokens` 视图已存在 | `src/kvopt/profiling/loss_views.py:74-75` |
| APC 需连续前缀 | `docs/phase2b-m6-experimental-fidelity-repair-spec.md` §1 |
| H2-M4 FAIL 只否定其冻结 comparator | `docs/experiments/phase2a-m6-h2/formal-final-verdict.json` |
| Phase 2E：326.67 → 134.67、TTFT 分量 ≈ +0.05% | `docs/phase2e-m6-measured-campaign-report.md` |
| F4 odd=SHARED_ROOT treatment `NOT_REALIZED` / even=negative control | `src/kvopt/workload/phase2e_materialize.py`；`docs/phase2e-m4-measured-review.md` §2.1 |
| 冻结接受协议 / 统计单位 | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| 决策粒度原为待研究问题 | `docs/phase2a-m4-method-design-input.md` |
