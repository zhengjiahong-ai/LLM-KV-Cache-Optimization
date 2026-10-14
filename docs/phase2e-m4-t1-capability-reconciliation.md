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

## 0.5 分支推进后的复核（rev.2，2026-10-14）

⚠️ **本节是对全文的时效性修正，请优先阅读。**

### 0.5.1 版本落差（必须记录）

M1 审查的是 M6 的提交 **`228f940`**。但 M6 的分支
`feature/phase2e-m6-native-baseline-characterization` 已推进到 **`306c0cb`**，
其中两个提交**直接回应了 RC1/RC2/RC4**：

| 提交 | 内容 |
| --- | --- |
| `5c3caef` | *fix: complete Phase 2E joint freeze checks* —— 新增 `_config_comparability`、`_native_execution_overlap_seconds`、targeted forced-release fixture 与 materializer |
| `306c0cb` | *test: verify Phase 2E forced release evidence chain* —— 新增 RC4 专用审计与测试 |

**实测确认**：在 `228f940` 上检索 `expected_request_ids_equal` / `nonempty_*` /
`runtime_*_equal` / `_native_execution_overlap`
⇒ **全部不存在**（`git show 228f940:src/kvopt/profiling/phase2e_fidelity.py` 无命中）。
⇒ 因此 M1 关于「当前 audit 仅通过 trace SHA / Git SHA 检查配对条件」的描述
**对 `228f940` 成立，对分支 tip 已不成立**。

⚠️ 本文件 §B.1、§E.3 是按 `228f940` 状态写的，**下述复核取代其相应条目**。

### 0.5.2 RC1 — 已**大幅**落实（超出 M1 描述）

`_config_comparability` 实际执行的检查（`phase2e_fidelity.py:93-175`）：

| M1 的 RC1 条目 | 对应检查 | 判定 |
| --- | --- | --- |
| 1. 相同 materialized workload / expected request IDs | `expected_request_ids_equal` —— **请求 ID 集合**（非总数）相等，且**要求非空** | ✅ |
| 2. 相同模型 / tokenizer / KV 容量 / block size | `config_model_equal`、`config_tokenizer_equal`、`config_cache_equal`；`runtime_block_size_equal`、`runtime_cache_block_override_equal`、`runtime_gpu_memory_utilization_equal` | ✅ |
| 3. 相同 generation / runtime parameters | `config_generation_equal`、`config_batching_equal`、`config_seed_equal`、`config_runtime_mode_equal`、`config_backend_revision_equal` | ✅ |
| 4. 真实执行环境 / 版本 / 资源配置 | `runtime_vllm_release_version_equal`、`runtime_vllm_metal_distribution_version_raw_equal`、`runtime_vllm_metal_source_commit_equal`、`runtime_platform_plugin_identity_equal`、`runtime_platform_plugin_class_equal`、`runtime_metal_paged_kv_enabled_equal`、`runtime_engine_core_observation_topology_equal` | ✅ |
| 5. 两臂 instrumentation 开销与配置差异 | `intentional_differences`（记录 `policy` / `retention_mode` / `phase2e_stage.baseline` / `config_sha256`）+ 一段**定性** `instrumentation_difference_assessment` | ⚠️ **部分** |
| SHA 非空且一致，不得「双方均缺失视为可比」 | `nonempty_git_sha_equal`、`nonempty_trace_sha256_equal` —— 实现为 `all(isinstance(...) and row.get(field))` **且** 集合大小为 1 | ✅ |

⇒ **RC1 的 1–4 项与 SHA 规则已被落实**；仅第 5 项仍为定性。

**仍然缺的一项（我先前 §B.2 的 C2 主张仍有效）**：`trace_sha256` 只能证明**输入文件**相同，
不能证明**实际提交给 tokenizer 的 token 序列**相同。逐请求 `submitted_token_ids_sha256`
（`BACKEND_INPUT_MATERIALIZED` 事件已带该字段）**未被该审计比对**。
⇒ 这仍是「same materialized workload」在 **token 级**的残余缺口。

### 0.5.3 RC2 — 已改为 **admission 级**，但**缺一项 E4 已有的身份校验**

M6 新增的 `_native_execution_overlap_seconds`（`phase2e_fidelity.py:71-92`）：

```python
intervals = [(native_scheduler_admission_timestamp, native_first_token_timestamp) ...]
overlap  = max(min(left1,right1) - max(left0,right0))
```

对比 Phase 2D E4 的既有定义（`src/kvopt/profiling/phase2d_e4.py:73-83`）：

```python
overlap = min(completed_at) - max(scheduler_admission_at)     # admission -> completion
+ 且校验：distinct native_request_id、同一 native_hash_process_id
```

| 项 | E4（Phase 2D） | T1（Phase 2E） |
| --- | --- | --- |
| 区间 | admission → **completion** | admission → **first_token** |
| `native_request_id` 相异 | ✅ 校验 | ❌ **未校验** |
| 同 `native_hash_process_id` | ✅ 校验 | ❌ **未校验**（仅在 clock domain 上过滤） |

评定：

- ✅ **已不再是 M1 批评的 `SUBMITTED → COMPLETED` 生命周期重叠**；
- ✅ 审计自带诚实声明：`"overlapping engine-core admission-to-first-token windows; not a claim of simultaneous GPU kernel execution"` —— 符合 M1 的要求；
- ⚠️ **但缺 E4 的两项身份校验**。而「已验证的 native in-flight 证据」恰恰要求身份可核。
- 附带说明：因 `max_new_tokens = 1`，`admission→first_token` 与 `admission→completion` 在 T1 中**几乎重合**，
  故定义之差在当前 fixture 上不构成问题。

⇒ **RC2 的最小修法是把 E4 的两行身份校验并入 T1 的 overlap 检查**（不是新建插桩）。

### 0.5.4 RC4 — **装置已就绪，只差一次 run**

`5c3caef` 新增 `configs/phase2/phase2e-t1-targeted-forced-release-v1.json`
与 `phase2e_t1_targeted_materialize.py`（2 program × 2 turn、共享前缀、`tool_gap_seconds`）。
`306c0cb` 新增专用审计 `phase2e.t1_rc4_forced_release_audit.v1`，其 `checks` 恰为 M1 要求的链条：

```text
single_real_forced_release_decision
candidate_geometry_present                 (>= 2)
selected_logical_release_present
selected_blocks_became_physically_evicted
decision_precedes_selected_physical_evictions
selected_evictions_have_pre_eviction_identity
selected_evictions_map_to_selected_prefix
```

并显式声明 `content_level_counterfactual_causality: NOT_CLAIMED`、
`physical_event_persisted_logical_owner: NOT_OBSERVABLE`
（与我在任务 A §4.2 的 R1/R2 规则一致）。

⇒ **RC4 从「需补能力」降级为「需执行并出证」**。这是本次复核最重要的状态变化。

### 0.5.5 我在任务 A 中提出的 R1–R5，T1 的满足情况

| 我的要求 | T1 状态 |
| --- | --- |
| **R1** 三个时间戳齐备 | ✅ 审计以 `native_timestamps_complete` 作为 gate 项 |
| **R2** 淘汰时刻内容身份 | ✅ `pre_eviction_content_identity_observed` 为 gate 项，且已提供 |
| **R3** logical owners | ⛔ 仍 `NOT_OBSERVABLE`（M6 声明），符合「允许保留」 |
| **R4** 至少一个并发 > 1 的臂 | ✅ `max_concurrent_requests: 2` |
| **R5** agent 空闲间隔 + 多轮增长 | ✅ 物化器写入 `tool_gap_seconds: 1.0` 与 `{program}-turn-2-growth` |

⇒ **T1 已满足我提出的 5 项中的 4 项**，R3 为 M1 已允许的例外。

### 0.5.6 复核对结论的影响

§D 的推荐**不变**（仍为 `TARGETED_SMOKE_REQUIRED`），但**理由收窄为一条半**：

1. ~~RC1 未落实~~ ⇒ **已落实**（§0.5.2）；
2. ~~RC2 证据不足~~ ⇒ **已改善**，仅缺身份校验（§0.5.3）；
3. ✅ **仍成立**：核心机制未被实例化（T1 无 `FORCED_RELEASE_DECISION`）—— RC4 装置虽就绪但**未执行**；
4. ✅ **仍成立**：T1 archive 未获我独立核验（RC5）；
5. ✅ **仍成立**：P5 覆盖 1/7 且分散，位置类结论不可判定。

⚠️ 因此 §E 的「T2 最小定向 Smoke 规格」已**大幅缩水**：原本要求「新建」，现在多为「执行 + 补两行校验」。

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

⚠️ **rev.2 更新（见 §0.5.2）**：下表「是否充分 = 否」的三项中，**第 1–4 项已在 M6 的
`5c3caef` 中由 `_config_comparability` 实现；第 5 项仍为定性**。
**唯一残余缺口是第 1 项的 token 级强度**（逐请求 `submitted_token_ids_sha256` 未被比对，见 §B.2 的 C2）。
下表保留为**判据设计说明**，其「当前是否具备」请以 §0.5.2 为准。

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

⚠️ **rev.2 更新（见 §0.5.4）**：该状态对 **T1 smoke** 仍然成立（T1 确无 decision），
但 M6 已在 `5c3caef` / `306c0cb` 中**建成** targeted fixture 与
`phase2e.t1_rc4_forced_release_audit.v1`（7 项 checks 恰为下述链条）。
⇒ 本节的「不可测」**降级为「待执行」**：能力已就绪，缺的是一次 native run 及其证据。

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

## E. T2 最小定向 Smoke — 一次性规格（rev.2：已缩水）

⚠️ **本节已按 §0.5 改写。** 原版按 `228f940` 状态要求「新建」多项能力；
实测表明 M6 已在 `5c3caef` / `306c0cb` 中建成大部分。因此**当前所需仅为「执行 + 补两处小缺口」**。

### E.1 所需（按阻塞性排序，共 4 项）

| # | 项 | 状态 | 阻塞 |
| --- | --- | --- | --- |
| **E1** | **执行 RC4 targeted forced-release fixture**（装置已存在，一条命令） | ⏳ **待执行** | RC4 的 `DEMONSTRATED` 判定；B1 的「集中淘汰」与「NGR/再分配」 |
| **E2** | 把 **E4 的两行身份校验**并入 T1 的 `_native_execution_overlap_seconds`（`native_request_id` 相异 + 同 `native_hash_process_id`） | ⏳ **待补** | RC2「**已验证**的 native in-flight 证据」 |
| **E3** | 在可比性审计中增加**逐请求 `submitted_token_ids_sha256`** 相等性（字段已在 `BACKEND_INPUT_MATERIALIZED`） | ⏳ **待补** | RC1 第 1 项的 **token 级**强度 |
| **E4** | 提供 **T1 + RC4 的 evidence archive**（RC5 清单） | ⏳ **待提供** | Gate B 关闭的定义前提；我无法独立核验任何 SHA |

### E.2 明确**不**要求

```text
❌ 不新建 overlap 插桩（复用 E4 定义 + 已采集的 admission/first_token 时间戳即可）
❌ 不要求 100% 的 P5 覆盖（§C.1 已裁定：允许限缩为受限结论）
❌ 不要求 physical 级 logical owners（M1 已允许保留 NOT_OBSERVABLE）
❌ 不改 native ownership、不解锁 B1、不改 Continuum 默认策略
❌ 不启动 144 次 measured campaign
```

### E.3 P5：先**诊断 join 失败**，不要先补插桩

§C.1 的判定在 rev.2 中**不变**：P5 缺口看起来是 **join 失败**（1/7）而非能力缺失。
⇒ 请 M6 对这 6 次未命中各给一个 reason（snapshot 时刻不同 / hash 已移除 / 不在该请求快照内）。
这比新增插桩便宜，且能直接决定 P5 是否需要定向 smoke。

### E.4 通过判据（T2）

```text
E1 的 RC4 审计 status = PASS，且 7 项 checks 全通过；
E2 的身份校验加入后，两臂 overlap > 0 且身份合法；
E3 的逐请求 digest 集合相等；
E4 archive 可访问、SHA 与交接一致、可由我独立复算。
```

⚠️ 全部通过**仍不等于** `READY_FOR_JOINT_FREEZE` —— 联合冻结记录还须写明
**§C.3 已确认的观测缺口**（P5 覆盖、logical owners、无内容级反事实因果）。

---

## F. 请求 M1 裁定（rev.2）

1. **版本落差的处置**：M1 的 RC1/RC2 描述基于 `228f940`，而 M6 分支 tip `306c0cb`
   已实现 `_config_comparability` 与 admission 级 overlap（§0.5.1–0.5.3）。
   请确认**以分支 tip 为复核基准**，并把 RC1 记为「第 1–4 项已落实、第 5 项仍定性」。
2. **§E 的最小清单（4 项）**：是否接受 rev.2 缩水后的 **E1–E4** 作为**唯一**一次定向 smoke？
   ⭐ 其中 **E2（并入 E4 的两行身份校验）** 与 **E3（逐请求 digest 相等性）** 是我认为必须补的两处；
   **E1（执行 RC4 fixture）** 是 RC4 从「待执行」转 `DEMONSTRATED` 的唯一路径。
3. **§D 判定**：是否接受 `TARGETED_SMOKE_REQUIRED`（而非 `READY_FOR_JOINT_FREEZE`
   或 `BLOCKED_BY_OBSERVABILITY`），但**理由收窄为「核心机制未实例化 + archive 未核验 + P5 覆盖分散」**？
4. **§C.2 的层级切分**：是否接受 B3 **逻辑半边可做、物理半边 `NOT_OBSERVABLE`**？
5. **§C.1 的 P5 处置**：是否同意「**先诊断 6 次 join 失败**，而非先补插桩」？
6. **联合冻结记录的内容**：是否确认须写明 §C.3 的三项观测缺口
   （P5 覆盖、logical owners、无内容级反事实因果）？

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
