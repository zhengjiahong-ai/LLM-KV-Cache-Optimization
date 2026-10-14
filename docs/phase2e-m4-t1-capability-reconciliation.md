# Phase 2E T1 — M4 Capability Reconciliation

**提交人**：M4　**送审**：M1　**协作方**：M6　**日期**：2026-10-14
**依据**：M1 的 T1 Review（`T1_ACCEPT_WITH_LIMITATIONS`、`JOINT_FREEZE_PENDING`）、
`docs/phase2e-m4-task-a-metrics-freeze.md`（Measurement Contract）、T1 结果摘要
**性质**：能力对账。**未**实施策略、**未**新增 native run、**未**改动既有裁决
**边界**：H1/H2 CLOSED、B1 LOCKED、Measured campaign NOT_AUTHORIZED

---

## 0. 前置：本次对账的证据边界（必读）

⚠️ **我无法读取 T1 原始证据。** 具体：

```text
M6 的 T1 提交 228f940        : 不在本地（fetch 失败：github.com:443 连接超时）
PR #45 Measurement Contract  : 不在本地（本地 main 停在 ea36f9e = PR #44）
T1 evidence archive          : 未获得（RC5 正在索取）
```

因此本对账的依据是**三项可核实的内容**，而非 T1 数据本身：

| 依据 | 可核实性 |
| --- | --- |
| **仓库内的字段与 gate 实现**（`phase2d_e2/e3/e4.py`、event schema、`phase2_minimal_observability_metal.py`） | ✅ 已在本地逐行核对 |
| **Task A 的可测量性实测**（H1 语料 1068 条请求观测；同一 event schema） | ✅ 已实测 |
| **M1 对 T1 结果的摘要**（N/E/C、三时间戳、带 pre-eviction content identity 的淘汰事件） | ⚠️ 转述，非我直接核验 |

⚠️ **这不是形式主义**：**在 T1 archive 经独立核验前，Gate B 在定义上不可能关闭**。
本对账据此把结论标为 `PROVISIONAL_PENDING_ARCHIVE_REVIEW`，并把「可获得 archive」列为
T2 的**第一项**要求（§E）。

---

## A. Metrics — 哪些 A1/A2 指标已可算

### A.1 已可算（T1 摘要已声明具备的字段足以支撑）

⚠️ 前提：T1 的「N/E/C + 原生三时间戳」= `native_prompt_tokens`、`eligible_prefix_tokens`、
`native_cached_prefix_tokens` + `native_queued_timestamp` / `native_scheduler_admission_timestamp` /
`native_first_token_timestamp`。**我按该 schema 在 H1 上实测填充率 100%、单调性 0 违例**（Task A §6）。

| 组 | 指标 | 依赖 | 状态 |
| --- | --- | --- | --- |
| **A1** | `aggregate_recomputed_tokens`、`mean_recomputed_tokens_per_request`、`cache_reuse_efficiency` | prompt / cached | ✅ 可算 |
| **A1** | `mean_ttft_seconds`、`native_prefill_to_first_seconds`、`mean_queue_delay_seconds` | 三时间戳 | ✅ 可算 |
| **A1** | `aggregate_delta_tokens`、`abs_redistribution_tokens`、**`NGR`** | 配对臂 + 上述 | ✅ 可算（**前提：配对臂存在**，见 §B） |
| **A2** | `p95/p99_recomputed_tokens`、`p95/p99_ttft_seconds`、`max_single_request_recomputed` | 同上 | ✅ 可算 |
| **A2** | `worst_agent_cumulative_recovery`、`inter_agent_concentration`（top-1 share / Gini） | `program_id` + 每请求 recompute | ✅ 可算 |
| **A2** | `rho_recompute_ttft`、`tail_transfer_ratio` | 上述 | ✅ 可算 |
| **A2** | `severe_loss_rate`（$\theta$ 口径）、`kappa$ 敏感性 | cached / prompt | ✅ 可算 |
| **A3** | 决策几何（候选、LRU rank、`newly_eligible`） | `FORCED_RELEASE_DECISION` | ⛔ **T1 未产生该事件**（见 §C.3） |

### A.2 受缺失性影响 / 不可算

| 指标 | 问题 | 处理 |
| --- | --- | --- |
| `native_miss_rate`（A2.5a） | `apc_outcome` 是 `(eligible, cached)` 的**派生标签**，非独立上报 | 可算但**必须标 `OFFLINE_DERIVED`**；不得用作独立验证（Task A §4.2 R3） |
| **位置类指标**（前缀头/尾损失比例） | 需 block→prefix position | ⛔ 依赖 **P5**（§C.1） |
| `shared-owner` 物理归属类 | 需 logical owners | ⛔ `NOT_OBSERVABLE`（§C.2） |
| 淘汰→损失**因果**归因 | 需内容身份可解析 + 同一 hash process | ⚠️ T1 已带 pre-eviction content identity（**这是相对 H1 的实质进步**，H1 为 5757/5757 `block_slot_only`）⇒ 需在 archive 中核实其**对哪些淘汰成立** |

### A.3 ⭐ 关键结论（A）

> **A1 与 A2 的全部指标在 T1 schema 下已可算**，不需要新的插桩。
> 真正受限的是 **A3 的归因链**（缺 `FORCED_RELEASE_DECISION`）与 **P5 的位置类子问题**。
> ⇒ **指标层不是 Gate B 的瓶颈；归因层才是。**

---

## B. Comparability — 配对条件是否充分

### B.1 M1 列的 5 项：我的逐项裁定

| M1 项 | 是否**必要** | 是否**充分** | M4 意见 |
| --- | --- | --- | --- |
| 1. 相同 materialized workload / expected request IDs | 必要 | **否** | ⭐ **只比对总数不够，且只比对 trace SHA 也不够**。建议改用**逐请求 `submitted_token_ids_sha256` 集合**（见 §B.2） |
| 2. 相同模型 / tokenizer / **KV 有效容量** / block size | 必要 | 必要且近乎充分 | ⚠️ **`KV 有效容量` 是最容易被漏掉的一项**：容量不同 ⇒ 淘汰频率不同 ⇒ A1/A2 不可比 |
| 3. 相同 generation / runtime parameters | 必要 | — | 含 `max_new_tokens`、`temperature`、`gpu_memory_utilization` |
| 4. 真实执行环境 / 版本 / 资源配置 | 必要 | — | 须含 `vllm` / `vllm_metal` / `mlx` 版本与硬件 |
| 5. 两臂 instrumentation 开销与配置差异 | 必要 | — | ⚠️ 若一臂多启用了内容证据（pre-eviction hash），**两臂的 I/O 与内存行为可能不同** ⇒ 需声明 |

### B.2 ⭐ 我建议的**可执行**可比性校验（全部复用现有字段）

M1 指出「不能将双方均缺失视为可比」。我给出**可判定的**规则：

```text
C1  request_id 集合严格相等                      (不是只比总数)
C2  逐请求 submitted_token_ids_sha256 严格相等   <- 现有 BACKEND_INPUT_MATERIALIZED 事件已带该字段
C3  scenario / family / draw / seed 标识相等
C4  materialization manifest SHA 相等 且 非空
C5  model + revision、tokenizer、block_size 相等 且 非空
C6  KV 有效容量相等 且 非空
C7  generation 参数相等 且 非空
C8  runtime 版本 / 硬件标识相等 且 非空
C9  instrumentation 配置差异已声明（尤其内容证据开关）
C10 两臂 request 的到达时间剖面一致（inter-turn gap 对齐）   <- 见 §B.3
```

**判定规则**：

```text
C1..C9 任一为空 或 不相等            => NOT_COMPARABLE（不得以「双方均缺失」充数）
C10 不满足                            => COMPARABLE_WITH_LIMITATION（须在报告中标注）
全部满足                              => COMPARABLE
```

⚠️ **C2 是我认为比 SHA 更强的一项**：trace SHA 只能证明**输入文件**相同；
而 `submitted_token_ids_sha256` 证明**实际提交给 tokenizer 的 token 序列**相同
—— 后者才是 KV 复用行为的真正决定量。

### B.3 ⭐ M1 未列出但我认为**必要**的一项：到达剖面一致性

⚠️ **LRU / Continuum 的比较会被「内存需求时间线」混淆。**

即使请求集与内容完全相同，**请求的到达时间**（以及 inter-turn 空闲间隔）
决定任一时刻的并发与压力 ⇒ **淘汰发生次数不同** ⇒ A1/A2 不可直接比较。

**最小校验**：两臂的逐请求 `native_queued_timestamp` 相对 run 起点的**偏移剖面**应一致
（同 scenario 的 trace replay 应天然满足，但**须实测确认而非假定**）。

### B.4 裁定（B）

> **M1 的 5 项是必要条件，但不充分。**
> 补充 **C2（逐请求内容身份）** 与 **C10（到达剖面）** 后，才足以支撑 workload-level 的
> Native LRU / Continuum 比较。
> 且：**任何一项为空即判 `NOT_COMPARABLE`** —— 这一条我完全同意 M1，并已写成可判定规则。

---

## C. Attribution — P5 / logical ownership / forced-release 各支持什么

### C.1 P5（前缀逻辑位置 ↔ LRU 排序）

**当前状态**：`PARTIALLY_DEMONSTRATED`，每臂 **1/7** 淘汰事件有可靠映射。

⭐ **一个重要发现：P5 在原理上可能是可闭合的，且不需要新插桩。**

仓库已有构造映射所需的全部字段：

```text
prefix_segments_by_request  (segment content key + token_count)   <- 段级 token 偏移
    ↓ 累积 token 偏移 + block_size(16)
block index k  ~  覆盖 tokens [k*16, (k+1)*16)
    ↓
VLLM_PREFIX_SNAPSHOT.ordered_native_hashes[k]                     <- 第 k 块的 hash
    ↓ 与淘汰事件的 native_hash_hex 匹配
evicted block  ->  前缀内位置
```

⇒ **P5 的缺口看起来更像「join 失败」而非「能力缺失」**（1/7 命中，6/7 未命中）。
**建议让 M6 先诊断 6 次 join 失败的成因**，而非直接补插桩。可能原因：
snapshot 与 eviction 不同时刻 / 该块 hash 已被移除 / hash 不在该请求的快照列表中。

**各指标的 P5 依赖**：

| 不依赖 P5（⇒ T1 即可支撑） | 依赖 P5（⇒ 必须受限） |
| --- | --- |
| A1 全部（聚合、再分配、NGR） | 「被淘汰的是前缀**头部还是尾部**」 |
| A2.1–A2.4（分位、max、worst-agent） | **tail-first 正确性**（冷端 = 前缀尾部） |
| A2.5a/b、A2.6（miss/severe/集中度） | 前缀内的**部分命中位置**分析 |
| A2.7/A2.8（ρ、传递率） | B1 的位置性子结论 |
| B2 的**大部分**（异构成本：长度×重算×TTFT 均可算） | — |

⇒ **Phase 2E 的指标集大部分不依赖 P5**；受限的是**位置类**子问题。
⚠️ 依 M1：**不得**用部分映射去支持 tail-first 正确性。

**1/7 覆盖够不够检验至少一种位置机制？——我的判定：不够。**

理由：检验 P5 需要**同一个 entry 内**块与其位置的**完整顺序**（才能比较「LRU 序」与「前缀序」）。
若 7 个淘汰分散在不同 entry 上，每个 entry 只有 1 个点，则**无法判定任何序关系**。
⇒ **最小需求是一个 entry 的完整 block→position 映射**，而不是若干分散点（见 §E）。

### C.2 Logical ownership（`NOT_OBSERVABLE`）

⭐ **必须区分两个层级** —— 这是 M1 要求「明确限制 shared-owner 机制分析」的精确答案：

| 层级 | 可得性 | 允许的主张 |
| --- | --- | --- |
| **逻辑级 marginal relief**：`initially_reclaimable_block_ids` ⊂ `block_ids` | ✅ **可得**（Phase 2D E2 已实测：`relief`=4 vs `block_count`=12） | ✅ 可判「某 entry 的释放**不会**回收其全部块」⇒ **logical-release 层面的共享效应可测** |
| **物理级 owner attribution**：某物理块被哪些 logical entry 共同持有 | ⛔ `NOT_OBSERVABLE` | ⛔ **不得**声称某次物理淘汰由「多 owner 保护」导致 |

⇒ **裁定**：B3 的**逻辑半边可做，物理半边不可做**。
不因缺物理归属而放弃整个 B3；但 B3 的一切物理性结论标 `NOT_OBSERVABLE`。

⚠️ **不得**为满足观测要求修改 native ownership 或默认 Continuum 策略（M1 明令，我认同）。

### C.3 Forced-release decision（`NOT_DEMONSTRATED`）

⚠️ **这是本轮最重要的限制。**

T1 **未产生 `FORCED_RELEASE_DECISION`** ⇒ 整条归因链从未被实例化：

```text
FORCED_RELEASE_DECISION → selected logical release → eligibility → physical eviction
```

**后果（必须写进联合冻结记录）**：

| 研究项 | 状态 |
| --- | --- |
| 基线**行为**的观测（A1/A2 全部指标） | ✅ 可测（观测性，无需决策事件） |
| 冗余「**谁被选中释放**」 | ⛔ **不可测** |
| B1「连续压力是否**集中淘汰**少数 Agent」 | ⛔ **不可测**（集中度 A2.6 可测，但它**不能**归因到淘汰选择） |
| B1「与 Continuum **whole-entry** release 相比集中度如何」 | ⛔ **不可测**（缺决策几何 + 缺对照） |
| A1.9 `NGR` / 再分配分析 | ⛔ 需配对臂 ⇒ 不可测 |
| 我此前 H1 的 **87/87 连续 band** 线索 | ⚠️ **不能在新 workload 上确认** |

⇒ **裁定**：T1 证明了「请求测量」可用，但**未证明「归因测量」可用**。M1 的表述准确。

---

## D. Joint Freeze Recommendation

### `TARGETED_SMOKE_REQUIRED`

**不是** `READY_FOR_JOINT_FREEZE`，理由（三条，任一即足够）：

1. **核心机制未被实例化**：T1 无 `FORCED_RELEASE_DECISION` ⇒ Phase 2E 的**研究对象本身**
   （淘汰选择 → 损失）在 T1 中不存在。36 draws 若同样不产生决策，则整轮无法回答 B1。
2. **T1 archive 未获独立核验**：Gate B 在定义上不能关闭（§0）。
3. **P5 覆盖 1/7 且分散** ⇒ 位置类结论不可判定。

**不是** `BLOCKED_BY_OBSERVABILITY`，理由：

- A1/A2 **全部可算**，指标层无阻塞；
- 所需机制 **Phase 2D E2/E3/E4 已经实现并跑通过**（强制释放、真实并发、内容证据）
  ⇒ T2 **是复用任务，不是新能力开发**；
- P5 大概率是 **join 问题**而非能力缺失（§C.1）。

⇒ 判定为**定向 smoke**，且按 M1 要求**一次性给出规格**（§E）。

---

## E. T2 最小定向 Smoke — 一次性规格（给 M6）

⚠️ **一次性提出，不再拆分**。目标：**用一个最小的 run 集合同时消除 RC1–RC5 的阻塞**。

### E.1 要求（按阻塞性排序）

| # | 要求 | 消除 | 最小可接受量 |
| --- | --- | --- | --- |
| **E1** | **可访问的 T1 evidence archive**（含两臂原始 events、configs/manifests、fidelity-audit.json、request_evidence、physical_evictions、missingness、provenance、archive hash + 独立复算命令） | RC5 + §0 | **T1 归档本身**；附一个可复算命令 |
| **E2** | **一次真实的 `FORCED_RELEASE_DECISION`**，并保存完整链：决策几何（`required_blocks`、`original_free_queue` 含 `native_lru_rank`、`candidates`）→ `selected_releases` → eligibility → physical eviction | RC4 + §C.3 | **≥1 个决策点**；建议复用 Phase 2D E2 fixture 的共享保留结构 |
| **E3** | **两臂同 scenario 的配对**（Native LRU vs Continuum），且满足 §B.2 的 C1–C10 | RC1 + §B | **1 个 scenario**，每臂 2 次噪声重复 |
| **E4** | **并发证据用 admission 级**：`native_scheduler_admission_timestamp → completion` 区间重叠 + native identity 校验 | RC2 | 复用 `src/kvopt/profiling/phase2d_e4.py:73-83` 的**现成定义**（见 §E.3） |
| **E5** | **一个 entry 的完整 block→prefix position 映射** | RC3 + §C.1 | **≥1 个 entry 的全部块**（不是分散的点）；若可达则再加 **≥2 个 entry** 以查一般性 |
| **E6** | 逐请求 `submitted_token_ids_sha256` 与 request-ID 集合导出 | §B.2 C1/C2 | 全量 |

### E.2 明确**不**要求

```text
❌ 不要求 P5 达到 100% 覆盖
❌ 不要求新的插桩能力（E4/E5 原则上复用现有字段）
❌ 不要求 six-family / 36 draws 规模
❌ 不改 native ownership / B1 / 默认 Continuum 策略
❌ 不启动 144 次 measured campaign
```

### E.3 ⭐ 对 RC2 的技术修正（我认为 M1 的判断需要更新）

M1 写：*"当前 `_overlap_seconds()` 依据 `SUBMITTED → COMPLETED` 计算区间重叠"*。

我已逐行核对仓库实现，**E4 gate 实际不是这样**（`src/kvopt/profiling/phase2d_e4.py`）：

```python
overlap = max(0.0,
    min(left["completed_at"], right["completed_at"])
    - max(left["scheduler_admission_at"], right["scheduler_admission_at"]))   # :73-77
# 且校验：submit <= admission <= completion          (:61)
#        native_request_id 相异                        (:80-81)
#        同一 native_hash_process_id                   (:82-83)
#        pressure decision 在两个 completion 之后        (:116-119)
```

⇒ **E4 用的是 `scheduler_admission → completion`（真实原生时间戳）+ 身份校验**，
比「submitted→completed」**强**。

**因此 RC2 的修法应是「复用 E4 的现成定义」，而非新建插桩。**

⚠️ **但残余缺口仍须声明**（我认同 M1 的底层关切）：
admission→completion 重叠**不能排除**「二者被同时接纳但在 decode 阶段被顺序化」。
⇒ 若无法获得逐 decode step 证据，主张应**限定**为
「**两请求被并发接纳且 in-flight 区间正重叠**」，而**不是**「同时执行」。
`peak_inflight=2` 可保留为该主张的**辅证**，但不得单独承担。

### E.4 通过判据（T2）

```text
PASS : E1 到位 且 E2 产生并保存完整决策链 且 E3 的 C1..C9 全满足
      且 E4 给出 admission 级重叠 + 身份校验 且 E5 至少 1 个 entry 完整映射
PARTIAL : E2/E3 满足，但 E5 仅部分  => 允许，位置类结论标 NOT_OBSERVABLE
NOT_PASS : E1 或 E2 或 E3 任一未满足 => Gate B 不关闭
```

⇒ T2 通过后，**双方共同提交简短的 Joint Freeze Record**（合同 / runner / manifest / evaluator
版本与 SHA + 已知观测缺口），随后才谈 measured campaign。

---

## F. 请求 M1 裁定

1. **D 的判定**：是否接受 `TARGETED_SMOKE_REQUIRED`（而非 `READY` 或 `BLOCKED`）？
2. **§B.2 的 C1–C10**：是否采纳为联合冻结的可比性判据？
   ⭐ 特别是 **C2（逐请求 `submitted_token_ids_sha256`）** 与 **C10（到达剖面）** 这两项我新增的条件。
3. **§E.3 的 RC2 修正**：是否接受「复用 E4 的 admission 级定义」，
   并把主张限定为「并发接纳 + in-flight 重叠」而非「同时执行」？
4. **§C.2 的层级切分**：是否接受 B3 **逻辑半边可做、物理半边 `NOT_OBSERVABLE`**？
5. **§E 规格**：确认作为**唯一**一次 smoke 申请，不再拆分？

---

## G. 诚实声明

⚠️ **本对账未核验任何 T1 数据。** 上述结论建立在：

- 仓库内字段与 gate 实现的**逐行核对**（可复现）；
- Task A 在 **H1** 语料上的可测量性实测（同一 event schema）；
- **M1 对 T1 的摘要转述**。

若 T1 archive 到手后与摘要不符（例如时间戳并非全量填充、或淘汰事件未真正带内容身份），
**§A 与 §C 的结论须相应下调**。我把这一点写进文档而非含糊过去。

---

## H. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| T1 结果摘要（N/E/C、三时间戳、pre-eviction content identity、pipeline PASS） | M1 的 T1 Review（转述） |
| TTFT 可算、三时间戳 100% 填充、0 单调性违例 | Task A §6；`local/probe_a_measurability.py` |
| 派生标签不得充当独立验证（R3） | Task A §4.2；`runtime_evidence.py::derive_level_b_token_semantics` |
| E4 重叠用 admission→completion + 身份校验 | `src/kvopt/profiling/phase2d_e4.py:61-83`、`:116-119` |
| `submitted_token_ids_sha256` 逐请求存在 | `scripts/spikes/phase2_minimal_observability_metal.py:1124`、`:1150`（`BACKEND_INPUT_MATERIALIZED`） |
| `prefix_segments_by_request` 存在（P5 构造输入） | `phase2d_e2_materialize.py:132`、`phase2d_e3_materialize.py:147`、`phase2c_native_pilot_materialize.py:138` |
| `VLLM_PREFIX_SNAPSHOT` 含 `block_ids` + `ordered_native_hashes` | H1 事件 schema（本地核验） |
| 逻辑级 marginal relief 可得（`relief`=4 vs `block_count`=12） | Phase 2D E2；`docs/phase2d-m6-headroom-investigation.md` |
| H1 淘汰台账仅槽位身份（5757/5757 `block_slot_only`） | H1 derived `physical_evictions.jsonl` |
| 无 `FORCED_RELEASE_DECISION` ⇒ 归因链未实例化 | M1 的 T1 Review（RC4 `NOT_DEMONSTRATED`） |
| H1 上「一个 entry 的块在 LRU 序中 100% 连续（87/87）」 | `local/probe_s1_recency_sync.py` |
| 能力矩阵的 owner / content identity 状态 | `scripts/spikes/phase2_minimal_observability_metal.py` |
