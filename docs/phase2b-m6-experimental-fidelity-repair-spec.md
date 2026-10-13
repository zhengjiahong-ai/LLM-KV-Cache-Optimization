# Phase 2B — M6 实验保真修复与真实 Runtime 集成：最终执行 Spec

**版本：FINAL HANDOFF · 2026-10-12**  
**项目：** `zhengjiahong-ai/LLM-KV-Cache-Optimization`  
**建议入库位置：** `docs/phase2b-m6-experimental-fidelity-repair-spec.md`  
**状态：** `APPROVED TASK SCOPE / IMPLEMENTATION PENDING`；**不是**新的正式科研实验授权。

| 事项 | 最终决定 |
|---|---|
| **唯一开发 Owner** | **M6**，负责需求落实、全部相关代码、接口扩展、真实 vLLM/Metal 集成、开发自测、GPU smoke、修复闭环和 PR |
| **最终验收与合并** | **M1**，独立审核实现、原始运行证据、科学边界、测试和原生不变量 |
| M5 / M3 / M4 | 本轮**不分配任务，也不是 M6 的交付前置依赖** |
| 工作性质 | 实验基础设施及 workload fidelity **工程修复**；非 holdout、非方法实验 |
| 研究主线 | **Cost-Aware KV Cache Eviction / Victim Selection**；Continuum 仍是强 baseline / 配套 retention context |
| 历史结论 | **H1/H2 保持 CLOSED；H1-R1 保持 `DIAGNOSTIC_ONLY`；H2-B1 保持 LOCKED；Issue #37 已结案** |
| 交付方式 | **一个完整、可评审的 M6 修复 PR**；附最小真实 GPU 证据和负控制；不再为此拆多个大文档 |

> **任务一句话：** M6 负责把实验声明的“共享内容、并发到达、真实历史信号和物理缓存压力”，从 trace 一直落实到 vLLM 原生运行时及可核验事件。能真实支持的条件必须被证明；当前不能支持的条件必须明确报错或声明不可测。**不允许为了获得预期 Cost-Aware 收益而改数据、改 baseline 或注入虚假状态。**

---

## 0. 研究结论与修复任务之间的边界

这次发现的不是“Cost-Aware 已失败”，也不是“M5 框架不合格”。M5 原先交付的 Phase 2 通用 substrate 是明确的顺序 `execute(PlannedRequest)` 与 backend-factory 接口；其 synthetic smoke 并没有承诺已经实现真实 vLLM 的多请求重叠和跨 program APC 内容共享。M6 在这个基础上实现了 H1 特定的 compiler、materializer、Metal 后端和实验执行，应由 M6 统一修复**正式实验的需求与实际运行时之间的落差**。M1 之前的准入审查也未充分检查 runtime-level fidelity，因此本 Spec 同时补齐准入断言。

**不得将工程问题推导为历史结果必须改判。** 冻结 H1/H2 在当时的实际环境中产生了真实观测；本任务只指出哪些实验条件没有被完整实现，不重写其原始结果、不选择性重跑，也不据此声称新算法有效。

### 0.1 已定位的四类问题

| ID | 原计划 / 研究目的 | 代码层实际情况 | 修复目标 |
|---|---|---|---|
| `F-PREFIX` | F6 中不同 logical programs 的 shared-prefix / ownership 使真实 APC 内容重叠 | `phase2_h1_compiler.py` 赋共同 `prefix_prompt`；真实 Metal `_turn_token_ids()` 却按 `program_id` 生成 token IDs | 共享声明必须落实到真实提交 token、原生 APC hash 和可测复用 |
| `F-ARRIVAL` | F5 的 overlap、burst 和 sustained queue 造成真实并发/排队状态 | `phase2_runner.py` 同步逐 action 调用 `backend.execute`；Metal 每次 `enqueue` 后立刻 `wait_for_completion` | 以 opt-in 多请求 submit/collect 执行真实重叠；不能把 planned overlap 当 observed overlap |
| `F-HISTORY` | H1 逐候选采样 eta、queue-delay，期望研究多维成本与 TTL benefit | 采样值主要停留在 `trace_derived_proxy_inputs`；Runtime TTL 实际从历史估计器读取，H1 结果 eta 恒 1、queue-delay 恒 0 | 构造合法历史与观测来源，明确哪些目标值在冻结语义下不可注入/不可实现 |
| `F-PRESSURE` | forced release 对应真实 KV 内容竞争和重计算影响 | 逻辑 unpin、native hashed-block eviction 和随后 APC miss 属不同事件；已有部分物理证据只携带 block-slot identity | 将各层证据分开记录和验证；不得从 logical release 推断物理淘汰 |

H1 的前缀长度 16–512、Level-A proxy-first，以及 H2-M4 的单前缀固定 `j` comparator，是**实验覆盖范围与科学解释限制**，不属于本轮必须“修复”的框架 bug。本轮绝不顺便扩展新 Cost-Aware 规则或正式数据分布。

---

## 1. 仓库真实接口及代码归属（开工前必读）

| 文件 | 当前作用 | M6 本轮权限 |
|---|---|---|
| `src/kvopt/workload/phase2.py` | `PlannedRequest`、`PressureStage`、`Phase2Trace.actions()`；`phase2.trace.v1` | 尽量不改 v1；必要时新增版本化 opt-in 字段/协议 |
| `src/kvopt/workload/phase2_runner.py` | `Phase2Backend.execute()`、顺序 replay、pressure bounded loop、run/artifact 状态 | 可为新模式增加最小 `submit/collect/drain` 接口，**保留 v1 默认同步行为** |
| `benchmarks/run_phase2.py` | 统一 benchmark CLI | 可增 opt-in 入口/参数，不能改变旧调用结果 |
| `src/kvopt/workload/phase2_h1_materialize.py` | H1 场景采样 | **冻结旧行为**；只参考设计，新增非 holdout fidelity materializer |
| `src/kvopt/workload/phase2_h1_compiler.py` | H1 共享组、arrival、pressure 编译 | **冻结旧行为**；不能改写 sealed H1 的再现语义 |
| `scripts/spikes/phase2_minimal_observability_metal.py` | vLLM/Metal 真正的 token 构造、enqueue/完成、APC/TTL/pressure 事件 | **M6 主要修复入口**；新增明确 opt-in 分支并保留旧执行路径 |
| `src/kvopt/continuum/history.py` | `QueueDelayHistory`、`CompletedProgramEtaHistory` | **只读语义**；允许添加不改变结果的观测/核验，禁止修改估计定义 |
| `src/kvopt/continuum/runtime.py` | Lifecycle、TTL 输入组装、history 记录入口 | 仅增加必要的合法观测/接线；不改 baseline 决策 |
| `src/kvopt/continuum/ttl.py` | 冻结 TTL objective | **不得修改** |
| `src/kvopt/runtime/vllm/{adapter,bridge,retention_integration}.py` | native victim adapter / Continuum eligibility | 以原有接口接入；不得改变 native owner、LRU 和排序规则 |
| `src/kvopt/profiling/{experiment_events,artifacts,runtime_evidence}.py` | 原始事件、写入、provenance 与衍生标签 | 只允许兼容性扩展观测；不要改旧字段含义或混淆 native/derived |
| `tests/test_phase2_substrate.py` | M5 substrate 原有测试 | 必须持续通过；允许**新增**测试，不可弱化旧断言 |

参考仓库：<https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization>。原有责任范围见 `docs/phase2-m5-runner.md`、`docs/phase2-m5-completion-status.md`、`docs/phase2-m6-profiling-spec.md`；历史裁定见 `docs/phase2a-h1-h2-closeout-verdict-record.md`。

**Native vLLM 0.27.1 的关键事实：** `BlockPool.get_new_blocks()` 从 `FreeKVCacheBlockQueue` 取 blocks，随后 `_maybe_evict_cached_block()` 对带 cache hashes 的 blocks 执行真正的 hash cleanup；APC 查找要求可匹配的连续前缀，正常全命中请求仍需重新计算最后 token（上限 `prompt_length-1`）。因此 **free-queue 数量、logical release 数、真实 hashed eviction 数、后续 recomputed tokens 不是同一个量**。

---

## 2. 不允许违反的最高优先级约束

1. **单一 Owner。** 全部开发、修复、调试、开发自测、真实 GPU smoke 由 M6 完成；最终 M1 验收。M5/M3/M4 不接受后继任务。若需要对通用 runner 做窄修改，M6 直接修改并承担回归。
2. **新实验路径 opt-in。** 建议命名 `phase2b_fidelity`，只在新配置中激活。`phase2.trace.v1` + 旧 `execute()` 同步执行必须仍可复现。不能改变历史 H1/H2 配置的执行含义。
3. **封存资产不可变。** 禁止修改、覆盖、重新采样或替换 `artifacts/phase2a-*`、sealed manifests、SHA-256 seals、正式指标及 verdict。新的 fixture 使用不同 trace/run ID 和输出目录。
4. **不改 baseline 算法。** 不改变 `RetentionAwareSelectionCoordinator` 排序、`TTL` 估计、Continuum scheduler 行为、Phase 1A victim adapter、native LRU rank、cache block hash 算法等。
5. **项目层只做只读观察/合法决策。** 不可自行改 vLLM `BlockPool`、native free queue 链表、`ref_cnt`、hash tables、allocation/lifecycle bookkeeping 的所有权。需要突破这些边界时，先提交给 M1 一个具体的最小接口提案，不默认交给 M3。
6. **三层来源严格分离：** `declared/intended`（计划条件）→ `materialized`（真实提交的 token/arrival/配置）→ `native_observed`（运行时原生时间、哈希、命中、淘汰）→ `derived`（由上述事实计算）。不可把计划值写成 native 事实。
7. **不允许伪造变量方差。** sampled `eta`/`queue_delay` 不得直接注入 frozen TTL estimator；不允许人为 sleep 后称为 native scheduler queue delay。
8. **能力不足要报错或降级结论，而不是静默退化。** 例如某 fixture 要求 `true_inflight_overlap`，但仍走同步 backend，不应报告实验保真 PASS。
9. **新方法不在范围内。** 不运行新的 reverse-deadline/Cost-Aware challenger，不开展正式统计验收、不选择性修补 H1 负面样本。
10. **局部实现，避免新框架。** 复用现有 event sink、manifest、trace、backend hooks 和阶段状态；优先一个 PR，不堆新层次、多套文档。

### 2.1 统一结果状态

每个 fidelity gate 均需要 `status + reason + source_event_indices + scope + runtime_identity`：

- `PASS`：真实必要条件有可核验 native/runtime 证据。
- `FAIL`：条件被证据反驳、数据非法、不变量破坏。
- `NOT_DEMONSTRATED`：运行发生，但证据不足以证明目标（例：计划并发，实际无 overlap）。
- `NOT_OBSERVABLE`：需要的观测缝不存在，列出精确缺口。
- `BLOCKED`：环境/平台前置条件未满足，说明阻塞点。
- `NOT_APPLICABLE`：fixture 本身明确不要求该维度。

**任何 required gate 为 `FAIL / NOT_DEMONSTRATED / NOT_OBSERVABLE / BLOCKED`，该 fixture 整体不具备 QUALIFIED PASS。** 输入级 PASS 不等于 native 级 PASS；不能将 `run.json.status=success`（仅代表程序正常结束）与 `fidelity_qualification=PASS` 混为一谈。

---

## 3. 方案整体结构：明确选用的最小接口契约

建议以 `src/kvopt/workload/phase2b_fidelity.py` 和 `phase2b_fidelity_runner.py` 实现 opt-in 的配置/能力门禁与执行，保留原 `phase2_runner.py` 同步入口。必要代码可以落在更合适文件，但外部可观测行为必须满足本节。

### 3.1 内容身份：显式 `prefix_content_key`，不能再由 program_id 隐式决定共享

建议在**新** fixture config 中定义：

```json
{
  "backend_options": {
    "phase2b_fidelity_mode": true,
    "prefix_generator_version": "phase2b-prefix-v1",
    "prefix_content_key_by_program": {
      "agent-a": "shared-group-0",
      "agent-b": "shared-group-0",
      "agent-c": "exclusive-agent-c"
    }
  }
}
```

这是推荐的字段布局；M6 可以选 trace 内 `prefix_content_key` 作为唯一规范来源，但**必须只保留一个权威映射**，不可让 `ownership_group`、`prefix_prompt`、runtime config 三处各自独立且可能相互矛盾。M6 如果从 H1 风格 ownership group 编译新 fixture，必须把它确定性映射成上述内容 key，并将结果固化到新 config/evidence。

**必须实现：**

- 相同 key 的不同 programs 使用**完全一致**的共享前缀 token IDs；128-token prefix 必须与同 key 256-token prefix 的前 128 tokens 完全一致；不同长度和不同 turn 都应 prefix-stable。
- 不同 keys 的测试 fixture 至少第一个完整 16-token block 不同；用实际 token IDs 断言，不能只假设 hash/取模没有碰撞。
- 同一 program 的不同 turns 可使用不同 request-specific suffix，不能破坏共享头部。压力请求应独立生成内容，并检查与目标前缀不意外相同。
- `program_id`、`request_id`、logical entry identity 始终独立；共享**内容**不等于合并两个 program，也不自动意味着 `ref_cnt`/物理 ownership 是双重持有。
- 固定 generator version 和 hash of submitted native token IDs（建议 SHA-256），记录 prefix token count、suffix token count、model/tokenizer revision、native APC hash chain 的实际来源。可以在测试内比对原始 token IDs，正式 evidence 可仅保存摘要。
- 新模式发现缺失 content key、同 program 冲突定义、非法长度/对齐或声称 shared 却无法 materialize 时必须 fail closed；不得静默回到按 `program_id` seed。
- 保留旧 Metal `_program_prefix_token_ids(program_id, ...)` legacy behavior，用明确模式选择新/旧路径。

**native 层判断：** 必须在同一真实 vLLM Engine/Core 中先建立缓存，再用另一 program 发送相同内容，比较实际提交 tokens、`native_apc_block_hashes`/cache keys、`num_cached_tokens`。在没有压力干预的 positive control 中，兼容的连续前缀应产生真实 APC reuse；如果 pressure 合法淘汰了内容而 miss，必须标为生命周期原因，不能误判为 token 错误。

### 3.2 并发执行：opt-in `submit/collect/drain`；同步 legacy 保留

旧 `Phase2Backend.execute(PlannedRequest)` 继续原样可用。新路径需要等价于以下语义（接口名可以不同，但不能改变核心契约）：

```python
submit(request: PlannedRequest) -> RequestHandle
collect_completed(*, until: float | None = None) -> Sequence[Completion]
drain(*, timeout_seconds: float) -> Sequence[Completion]
```

**精确执行要求：**

1. `submit` 只负责物化输入、进入真实 vLLM enqueue 并返回 handle；**不得等待该请求生成结束**。
2. 保存 logical request ID ↔ native request ID ↔ external request ID 的可核验映射；一个 completion 必须 exactly-once 归属一个 request。
3. `collect_completed` 支持一次返回 0、1 或多个 outputs，不要求按提交顺序完成；不能继续依赖旧 `_complete()` 中“每次只返回一个 output”的假定。若当前 vLLM API 的 poll/collect 语义有约束，按真实支持能力实现并在 README 说明，禁止将阻塞单请求循环包装成假异步。
4. runner 依据**统一 run-start clock 的绝对 planned arrival offsets**驱动提交；不因另一 program 上一条请求仍在执行就延迟它。若发生实际迟到，记录 `actual_arrival/submission` 与 `lateness`，绝不修改原 planned time。
5. 同一 program 的 turn 顺序、ToolGapStarted/Ended、FollowupWaiting 和前一 turn 完成条件必须正确；若计划的后续 turn 早于实际前驱完成，允许合理迟到并标记，而不是发出因果不可能的 lifecycle events。
6. planned offset 相同的 actions 使用固定 tie-break（trace 原始序号或明确 ID），跨程序 completion 顺序由 native 决定并记录。任何 lifecycle event 都不能关联错 program。
7. `max_concurrent_requests` 必须在**执行器**中真的限制 outstanding handles；配置上限为 1 但 fixture 要求 overlap ≥2 时，preflight 直接失败。
8. 必须设计 pressure stage 的同步边界。**默认先让目标前缀 warmup 请求完成、可观测的 protected entries 成立，再运行 pressure**。每次 pressure attempt 完成之后才读取 `forced_release_count` 并决定停止，保持 `max_requests/safety_ceiling`；需要 pressure 与在途目标重叠的 fixture 必须另行显式声明，不得因 executor 改动偶然产生未控竞态。
9. 限时、OOM、取消或 completion mismatch 时，保留 partial evidence、明确 incomplete IDs、状态和异常；不能使 `run.json` 显示全成功。所有等待必须 bounded。
10. 所有需要共享 APC 的 requests 必须运行在同一个 Engine/缓存上下文；不能在请求之间悄悄重建 LLM 导致缓存丢失。

**区分以下三种不同 PASS：**

- *planned overlap*：只有 trace 时间重合，不等于并发。
- *native in-flight overlap*：存在时刻 `t`，至少两个不同 requests 满足 `enqueued_at ≤ t < completed_at`；仅证明生命周期重叠。
- *true scheduler queueing / KV contention*：还需原生 `queued_ts/scheduled_ts`、waiting/occupancy 或真实 native allocation evidence；不能由前一项推断。

`max_new_tokens=1` 和短 prefill 可能导致真实请求完成过快；可以为**新非 holdout fixture**选择稍长请求增加重叠机会，但不能更改旧 H1/H2 并伪装为原实验。

### 3.3 Gate 合约：需要的能力不能用声明替代观测

建议新增独立版本化 manifest/config（不要替换旧通用 observation contract）：

```json
{
  "schema_version": "phase2b.fidelity_contract.v1",
  "run_kind": "NON_HOLDOUT_FIDELITY_REPAIR",
  "case_id": "AR-S1",
  "required_capabilities": ["true_request_overlap", "native_apc_hashes"],
  "constraints": {
    "max_in_flight": 2,
    "timeout_seconds": 120
  }
}
```

运行后生成逐 gate 的实际结果，至少有 `requested / observed / status / source_event_indices / clock_domain / reason / runtime_identity`。静态能检查的在 preflight 检查，动态条件在 execution/finalization 检查。不要让已存在的 `observation_capability_contract.complete=True` 变成“实验实现了并发与共享”的伪证明：前者只是观测接口声明，后者需要 native 结果。

---

## 4. P0-A：Shared Prefix 原生保真修复

**责任：M6 全部实现和开发测试。** 不单独委托 M5。

### 4.1 必交用例及判断规则

| Case ID | Fixture | 必须证明 |
|---|---|---|
| `PX-S1` | 两个不同 `program_id`，相同 content key，256 tokens + fresh suffix | 提交的 256 shared tokens 完全一致；原生 APC 首段 hashes/cache keys 兼容；无压力对照能命中原生缓存 |
| `PX-S2` | 相同 key，一方 128、一方 256 tokens | 128-token 头部完全相等；对应 8 个 16-token block 的原生 prefix hashes 一致 |
| `PX-S3` | 同一 program，两轮共享 prefix，suffix 不同 | prefix 不被 request-specific suffix 破坏；真实复用保持可测 |
| `PX-N1` | 不同 keys，相同长度 | 第一个 native full-block tokens/hash 不同，不出现虚假共享 |
| `PX-N2` | pressure request 与两个 target prefixes | 原生 target 前缀未与 pressure token 序列意外冲突 |
| `PX-N3` | 缺映射、非法长度/对齐、共享组冲突 | materialization/preflight 失败，输出明确错误，不静默回退 |

正负控制必须在实际真实 vLLM 上至少完成一次最小 smoke。prefix 不应包含越界/未对齐的重用声明；区分 eligible prefix 长度、native cached prefix tokens 和 fresh suffix，不能把必算的最后 token 计入 eviction loss。

**Gate `G-PREFIX`：** 输入级 materialization **与**真实 native APC reuse 同时 PASS；只检查 config 字段或 token digest 不能独立宣称原生共享 PASS。hash 相同不能推导多个 logical entries 对同一 slot 的 ownership，仍需另行证明。

---

## 5. P0-B：真实 Arrival / Concurrency / Pressure 执行修复

**责任：M6 修改必要的 runner + backend，并负责失败处理。**

### 5.1 必交用例

| Case ID | Fixture | 验收断言 |
|---|---|---|
| `AR-S1` | 两个独立 programs 同一 planned arrival，实际 cap ≥2 | 真实 enqueue 两个 native IDs 后，第一条尚未 completion；记录 `peak_inflight ≥2` 及准确 ID join |
| `AR-S2` | 错峰且应重叠的请求（足够的真实工作量） | 实际请求生命周期存在重叠；plan/actual arrival 和 lateness 独立保存 |
| `AR-N1` | 同一 planned-overlap trace 但通过旧 v1 sync executor | 负控制不能 PASS `true_request_overlap`；旧同步结果和事件序列保持语义一致 |
| `AR-Q1` | 在受控负载下试图产生真实 scheduler queueing | 若 `scheduled_ts > queued_ts`，记录实际正排队时间及来源；未产生则 `NOT_DEMONSTRATED`，不能注入非零值 |
| `AR-E1` | out-of-order completions、一个失败/超时（fake backend 可控） | 无错配、无重复 completion、超时有界、run/artifacts 保留完整失败来源 |
| `AR-P1` | 建立 protected entries 之后施加 pressure | 前置 warmup 完成；每个 pressure attempt 的 counter 在 completion 后检查；stop/ceiling 正确；没有错误关联 |

### 5.2 原生执行不可破坏的细节

- `VLLM_REQUEST_SUBMITTED`、native queued/scheduled/first token/completed 使用真实时钟与各自来源；不能拿 backend `enqueue` 时刻冒充 native scheduler admission。
- EngineCore monotonic 与 wrapper system-monotonic 跨 clock domain 不可未经对齐直接相减。
- 多请求完成时真实 output 可能批量返回，也可能乱序；先按 native/external ID 关联，再发与相应 program 对应的 lifecycle event。
- forced-release 只由成功完成且经过实际 runtime pressure 路径的 attempt 触发，不能根据“已经提交 pressure 请求”就算完成。
- 真实 `inflight ≥2` 不能代替“GPU kernels 并行”或“两个 requests 同时在 refcounted KV 中占用”，后两者只有原生证据才能声称。
- 任何并发相关 CPU/GPU 异常、native OOM、被取消请求都要进入失败统计，不能过滤掉以获得好看的 fidelity 指标。

**Gate `G-INFLIGHT`：** 请求级真实重叠与正确 completion join 为硬条件。`G-NATIVE-QUEUE` 是独立 gate；若 pinned backend 无法实际展示真实 queue delay，允许诚实 `NOT_DEMONSTRATED/NOT_OBSERVABLE`，但**未来实验不能宣称已经覆盖队列因素**。

---

## 6. P0-C：eta / queue-delay 历史及信号来源修复

这部分要格外严格：**目标是让数据满足 Continuum 的真实语义，不是让每个候选人为拥有不同数值。**

### 6.1 不允许改变的冻结定义

`src/kvopt/continuum/runtime.py::_handle_turn_finished()` 使用：

```python
queue_delay_seconds = self.queue_delay_history.mean_seconds()
eta, eta_provenance = self.eta_history.eta()
# 同时从 approved prefill provider 取 prefill_reload_seconds
```

`src/kvopt/continuum/history.py` 的 `QueueDelayHistory` 只接收 `EvictedRequestQueueDelayRecord`。没有合格历史样本时 `mean_seconds()` 返回 0.0。`CompletedProgramEtaHistory` 从**已经完成的程序**生成 `(turn_index, remaining_turns)` 历史对；样本过少或退化时返回 `eta=1.0`，reason 为 `FULLY_MEMORYFUL_COLD_START`。非冷启动时由真实历史的相关关系得到 eta。TTL 既有 benefit：

\[
\mathrm{benefit}=\mathrm{queue\_delay\_t\_seconds}\cdot\eta+\mathrm{prefill\_reload\_seconds}
\]

**注意：** 这里的 eta 是历史全局估计，**不是** H1 场景可为每个候选自由指定的独立在线特征；同一决策下多个候选获得相同 eta 可能完全正确。

### 6.2 M6 必须完成的修复

1. 新 fidelity schema 把 `scenario_target`、`materialized_workload`、`runtime_history_state`、`runtime_observed` 四类数据明确区分；原 H1 的 `trace_derived_proxy_inputs` 不重命名、不反向解释成 native TTL 输入。
2. 实现非 holdout 的 history-conditioning 程序：先真实完成多个不同长度的 multi-turn programs，再产生待测 nonterminal turn。记录已完成程序集合、每个已完成 turn count、样本对及其发生时间。估计值只能来自当前时间以前的历史。
3. 核对 native `queued_ts/scheduled_ts` 与 `EvictedRequestQueueDelayRecord` 的实际来源。**普通 native 排队时间不自动符合 frozen evicted-request history 语义。** 只有真实存在对应且合法的前置事件，才允许调用现有 `record_queue_delay()`；如缺口不可解决，明确标注所缺 observation seam 和 `NOT_OBSERVABLE`，不能把任意 native queue duration 填入该 history。
4. 记录每个 TTL decision 的 eta、provenance/cold-start reason、eta history sample count、queue-delay sample count/history mean、可用 native raw queue duration、time source 与事件索引。若没有合格历史，即使 native request 排队非零，TTL history 仍可能等于 0，这不是自动 bug。
5. 检查缺失字段与历史状态的**因果顺序**，禁止后续 program completion 反填之前的 TTL decision。
6. 对 H1 那种“在同一决策对各候选采样独立 eta”的想法，必须明确输出**frozen estimator 不支持该输入语义**，不得为了让 variance 出现而扩展 baseline 参数。

### 6.3 必交用例

| Case ID | 条件 | 正确结果 |
|---|---|---|
| `HI-E1` | 多个不同 turn-count 的程序已完成，之后一个待测非终止 turn | eta 与冻结 `CompletedProgramEtaHistory` 对之前历史的计算一致；来源、样本数和时序清楚 |
| `HI-E2` | 无样本/历史不足或退化 | eta=1.0 和正确 cold-start provenance，不伪装成已观察到的历史差异 |
| `HI-Q1` | 存在真实且合格的 evicted-request queue history | 每条记录可追溯到合法原生事实，TTL mean 与该时点之前的 history window 一致 |
| `HI-Q2` | 有 native 排队事实，但**没有**合格 `EvictedRequestQueueDelayRecord` | 两种含义分开：native queue duration 可以 >0，TTL `queue_delay_t_seconds` 可仍为 0，并给出原因 |
| `HI-N1` | scenario 只采样候选级 eta/queue-delay 数值，未构造有效历史 | 负控制必须拒绝“native signal variation 已实现”的断言 |

**Gate `G-HISTORY`：** 首先证明来源合法且与冻结实现一致，再看是否真的出现需要的数值差异。正确信号合法地恒定，不等于实现错误；但要求数值异质性的 fixture 就不能在未观察到方差时 PASS。

---

## 7. P1：Native Pressure / Eviction / Cost Visibility 最小链路

此任务是检查是否真实测试了缓存内容竞争，不是寻找更好 victim。要严格区分：

| 层级 | 实际含义 | 支持它的证据 |
|---|---|---|
| `L1 Logical Release` | Continuum 解除保护，改变 eligible set | `FORCED_RELEASE_DECISION`、retention snapshot、pressure release effects |
| `L2 Native Hash Eviction` | Native BlockPool 从 free queue 取 block 后，确实清除该 block 的 cached hash mapping | 分配/eviction 前的 native cache key/hash、block ID、free status/refcount、hash cleanup observation |
| `L3 Future APC Impact` | 后续请求的 APC prefix reuse 改变、必须重计算一段之前可重用的 token | Native request block-hash chain、`num_cached_tokens`、eligible prefix 与实际事件时序 |

**特别注意：** `free_queue_count` 中包含仍有缓存内容、可被复用/覆盖的 blocks；“产生 forced release”不等于 GPU 已分配失败，也不等于有哈希缓存必然被淘汰。`observed_recomputed_tokens = eligible - cached` 是项目分析层衍生值，不可声称其为 native 直接报告的独立事实。

### 7.1 最少提供两个非正式 fixtures

- `PR-S1`：两个内容不同的已缓存 prefixes + 合法 native allocation pressure；记录 unhashed free blocks、hashed cached blocks、native 被选中的真实 block/hash cleanup，以及之后请求的 APC 状态。**必须至少有一个真实 hashed-cache-entry eviction 正控制**，否则不具备该 gate 的 PASS。
- `PR-S2`：两个共享内容的 logical programs + pressure；记录 hash overlap 和后续 reuse，但**不得**把相同 hash / 物理 slot 直接等同于共享 logical ownership，也不得未经证明声称 `relief < block_count`。

如果目前的 native observation 只允许 `block_slot_only`，则要么通过已有获准 read-only hook 在事件发生时记录 content cache key/hash（附进程身份、版本、时间顺序），要么将 content-level attribution 标为 `NOT_OBSERVABLE`。不能用 slot ID 在不同时间段匹配内容，也不能拿 H2 的直接 hash invalidation 机制冒充正常 pressure 所产生的 BlockPool eviction。

**Gate `G-PRESSURE`：** 至少能区分 logical unpin、正常 native allocation-induced hashed eviction，以及 subsequent actual APC hit/miss。不能跳过 L2 直接从 L1 推论 L3。

---

## 8. 三阶段 fidelity 校验：preflight / execution / finalization

### 8.1 Preflight（新运行开始前）

必须检查以下内容并在不满足时**拒绝运行**：

- shared key 映射完整且无冲突；内容长度、block alignment、pressure token 配置合法；
- 所声明 `required_capabilities` 在本模式/backend 中有支持接口；
- 要求两个真实在途请求而并发上限为 1、或仍走 legacy 同步 backend；
- 需要 warmup 的 pressure stage 却没有可建立 protected entries 的前置请求；
- trace/schema 不兼容、请求标识重复、同 program turn 顺序非法；
- 当前 platform 不满足真实 vLLM/Metal 实验前置条件。

### 8.2 Execution（真实运行中）

必须记录：每个 request 的计划到达、实际尝试、native enqueue/queued/scheduled、实际 token digest、native ID join、完成/失败、APC 缓存量及 hashes、history 输入、pressure 决策及物理事件。所有数值注明 clock domain/source；允许真实运行时 jitter，但不修改计划记录。

### 8.3 Finalization（无论成功失败都执行）

1. 每个成功提交的 request 恰有一个最终状态；超时/取消/遗漏有独立明确的 terminal status。
2. 关联 logical/native/external IDs，检查事件索引单调和关键动作因果顺序。
3. 对每个 gate 使用**原始事件及其索引**计算 observed 条件，不可从 config 标签自动 PASS。
4. 分开记录 `execution_status`（程序是否执行完）与 `fidelity_qualification`（研究条件是否真的实现）。如果保留老 `run.json.status`，其 success 仅表示程序运行完毕，后续正式准入必须检查额外的 qualification 字段。
5. 对所有不合格 gate 给出清晰原因/缺少接口；不要将 `None` 自动写为 `0` 或静默过滤失败样本。

推荐输出结构（**非正式实验，不能覆盖旧路径**）：

```text
artifacts/phase2b-fidelity/<case-id>/<run-id>/
  run.json                     # runtime identity + execution_status
  trace.json                   # intended/planned
  replay.jsonl                 # attempted/materialized requests
  events.jsonl                 # raw native/source-tagged event stream
  fidelity-result.json         # all gate decisions + event indices + reasons
  stderr.log                   # error/timeout only
```

Repo 只需提交小规模可复现 fixtures/commands 和精简结果摘要；大型本地原始 GPU 证据保留实际路径及校验摘要，不能编造文件、结果或通过数。

---

## 9. 必须交付的测试矩阵（开发自测全由 M6 完成）

| 类别 | Case IDs | 级别 | 不可降低的验收条件 |
|---|---|---|---|
| Prefix content | `PX-S1,S2,S3,N1,N2,N3` | Python 单测 + native smoke | 内容 key → 真实 token IDs → 原生 hash/APC；包含共享与不共享负控制 |
| Real concurrency | `AR-S1,S2,N1,E1` | 假异步 backend 集成 + native smoke | submit 非阻塞、out-of-order joins、在途重叠、失败态完整 |
| Scheduler queue | `AR-Q1` | 原生时序观测 | 只有真实时间戳才能声明正 queue delay；否则明确未证明 |
| Pressure barrier | `AR-P1` | 集成 + native smoke | warmup 完成才允许默认 pressure；counter 在 pressure completion 后检查 |
| History provenance | `HI-E1,E2,Q1,Q2,N1` | 单测、因果事件测试、可行时 native 观测 | 冻结 history 规则，不能把 sampled targets 冒充 runtime values |
| Physical cache | `PR-S1,S2` | 真实 vLLM/Metal | logical unpin、hashed eviction、实际 APC reuse/miss 三级分开 |
| Legacy regression | `tests/test_phase2_substrate.py`、相关 H1/H2 单元测试、Phase 1A/1B 接口回归 | Python + 最小 native | v1 顺序、replay/trace hashes、policy-neutral observation、原生 owner 均无回归 |
| Failure/fail-closed | 缺 key、cap=1 却要求 overlap、不可观测字段、timeout/OOM、错配/重复 completion | 单测 + 可控 fake backend | 不误 PASS；失败证据可追溯；等待有界 |

**负控制不可缺少：**

- 逻辑上同 `ownership_group`、真实 token 不相同：**必须拒绝 shared-prefix native PASS**。
- planned overlap 仍通过同步 `execute()`：**必须拒绝 actual overlap PASS**。
- config 中采样了 eta/queue-delay，但没有对应历史：**必须拒绝 runtime variation PASS**。
- 只有 logical release，没有原生哈希删除：**必须拒绝 native hashed eviction PASS**。

### 9.1 真实 GPU smoke 检查清单

- [ ] 记录 vLLM 0.27.1 和 vLLM-Metal 的 source commit、运行机器、模型/tokenizer revisions、APC enabled、block size、GPU cache override；
- [ ] 同一 Engine/Core 内，不同程序同 content key 产生相同 token-prefix 和 native hash，并有无压力的 APC positive control；
- [ ] 不同内容 keys 产生独立的 negative control；
- [ ] 至少一个场景真的在任一时刻存在 ≥2 个未完成 native requests，而不只是计划同一时间；
- [ ] 真实 native queue duration 与 TTL `QueueDelayHistory` 值分别记录；不强求它们相等或非零；
- [ ] 默认 pressure 前真实 protected entries 已就绪；pressure 后 stop/counter 与生命周期正确；
- [ ] 能区分 native hashed eviction 与没有 hash eviction 的负控制、及后续 APC hit/miss；
- [ ] eta 来自截止该时间已完成程序的历史，TTL provenance 正确；
- [ ] 不改变 native `BlockPool`、queue 原始 `lru_rank`、refcount、hash cleanup；
- [ ] 保留所有失败/OOM/timeout，legacy tests 继续通过。

**不要运行新的 42-draw/126-run campaign。** 这一轮只需最少的可复现证明与正确的负控制，不以 statistically significant performance delta 为验收条件。

---

## 10. 实施顺序、检查点与阻塞处理

| 顺序 | M6 应完成的工作 | 进入下一步之前的硬检查点 |
|---|---|---|
| **S0 — 安全基线** | 记录 main full SHA、qualified backend 版本；固定 sealed H1/H2 不可修改文件清单；搭建新的非 holdout namespace | legacy v1 原始单元与 smoke 行为已留可比基线 |
| **S1 — 内容共享** | content-key schema、物化、真实 backend token 路径和 positive/negative fixtures | `PX-*` Python tests 和至少一次 native APC 正负控制 |
| **S2 — 并发执行** | submit/collect/drain、runner absolute-time scheduler、completion join、pressure barrier、失败处理 | fake async + real `AR-S1`，legacy 同步不受影响 |
| **S3 — 历史信号** | completed-program eta、合格 queue history 的事实来源、TTL read-only provenance、非支持情况明示 | `HI-*` 语义一致与因果检查；不能偷偷修改估计器 |
| **S4 — Native pressure** | hashed free block、native eviction 和后续 APC 的最小证据链 | `PR-*` 能正确区分三个层级；缺 seam 必须明示 |
| **S5 — 完整自测/PR** | 运行新/旧回归、最小真实 GPU smoke、修复所有非预期失败；附复现入口 | 一份可审查 PR + 机器可读 gate summary + 代码/环境 SHA |
| **S6 — M1 最终验收** | M1 对证据、边界与代码复核；必要时自行复现最小用例 | `ACCEPT / CHANGES_REQUESTED / BLOCKED`；失败由 **M6** 修正 |

**仅以下情况需提前请求 M1 决策（不是分配给其他成员）：**

- 需要修改 vLLM native BlockPool/scheduler/refcount/hash-table/queue ownership；
- 需要改变 Continuum TTL、pressure-release 或 scheduler 的冻结算法；
- 现有真实观测缝无法区分必需的 content identity / native queue history / hash cleanup，且实施必须突破已批准接口；
- 修复要求改变历史 H1/H2 sealed protocol、原始结果或正式研究定位；
- 任务扩张为新调度系统、全新观测框架、大规模实验或 Cost-Aware 策略实现。

如果合法的 `EvictedRequestQueueDelayRecord` 来源在当前 backend 中确实不可获得，M6 必须给出完整的 `NOT_OBSERVABLE` 技术说明并继续完成其他可独立修复的部分；**不能为了追求全 PASS 修改 baseline 语义**。由 M1 决定后续论文/实验对该维度应作何限制。

---

## 11. M6 PR 必交物与禁止事项

### 11.1 单一修复 PR

**建议 PR 标题：** `fix(phase2b): restore real workload fidelity and native evidence`

至少包含：

1. 版本化 opt-in fidelity contract / fixtures 和必要的 runner/backend 修复，旧模式向后兼容。
2. 内容身份、actual concurrency、合法 TTL history、native cache-pressure evidence 四条链路的正负控制测试。
3. 一份紧凑的 `fidelity-result.json` 或等价结果摘要，逐 gate 标记 `PASS/FAIL/NOT_DEMONSTRATED/NOT_OBSERVABLE/BLOCKED`、run IDs、事件索引和证据来源。
4. 真实 vLLM/Metal 非正式 smoke 的命令与原始结果，完整 engine/model/environment SHA；不能用 fake backend 单测替代 native 验证。
5. 旧 `tests/test_phase2_substrate.py` 及相关回归的命令和通过数；说明失败/缺失项。
6. 不超过几段的 change-impact 说明：哪些历史 *claim scope* 因此前实验未实现对应条件而受到限制；不重算 H1/H2 verdict。

**不要求额外独立设计文档、长篇审计报告或大量 PR。** 这份 Spec + 一个 PR + 结果摘要足够。

### 11.2 PR 描述模板（直接复制填写）

```text
Scope: NON_HOLDOUT_FIDELITY_REPAIR; no method experiment
M6 owner / M1 reviewer: ...
Base main SHA / vLLM + Metal source SHA / hardware / model: ...
Touched files and rationale: ...

Shared content:
- submitted prefix digest, content keys, actual native hash/APC (PX-S1/S2/N1): ...
- native negative controls: ...

Real concurrency:
- submit/collect contract and legacy compatibility: ...
- actual outstanding overlap, request IDs, event indices, peak_inflight: ...
- actual native queued/scheduled evidence or NOT_DEMONSTRATED: ...

TTL history:
- eta samples, value, provenance, decision cutoff: ...
- eligible EvictedRequestQueueDelayRecord source or NOT_OBSERVABLE: ...
- sampled target/native observed distinction: ...

Pressure:
- logical forced release: ...
- native hashed cached eviction and content identity: ...
- subsequent native APC hit/miss: ...

Negative controls and error paths: ...
Legacy substrate/Phase1A/Phase1B regression commands and results: ...
New tests and bounded real GPU smoke results: ...
Gate result manifest: ...
Known unsupported/undemonstrated conditions: ...

H1/H2 sealed artifacts or verdict modified: NO
Continuum TTL/policy algorithm modified: NO
Native BlockPool/queue/refcount ownership modified: NO
New Cost-Aware policy/formal campaign implemented: NO
M6 developer self-tests: COMPLETE/PARTIAL (with reasons)
M1 final acceptance: PENDING
```

### 11.3 严格禁止

- 改 H1/H2 历史实验配置、封存证据、正式统计结果、verdict 或用“修复版本”覆盖旧 run IDs。
- 改 native hash、复制伪造 APC content identity、手动设置 cache `ref_cnt`/hash tables，或重新排序并重算原生 `lru_rank`。
- 使用 `time.sleep` 或计划 queue-delay 字段充当 native scheduler 排队观测。
- 把 sampled eta 直接传入 TTL estimator，或为各候选增加未批准的 per-candidate eta override。
- 拿 `FORCED_RELEASE_DECISION` 代替 `BlockPool._maybe_evict_cached_block()` 的证据，或拿物理 block-slot ID 跨时间匹配 cache content。
- 以“所有 smoke 成功”声称当前 Cost-Aware 方法已被证明有效。
- 以尚无 native evidence 的 `NOT_OBSERVABLE` 宣称支持该维度的正式实验验收。

---

## 12. Definition of Done：M1 怎样判定可以结束本轮

### 12.1 M6 可以请求 Review 的条件

- [ ] 在一个 reviewable PR 中完成独立非 holdout opt-in 路径；M6 自己完成所有开发、自测、实际 GPU smoke。
- [ ] 共享 content key → 真实 token IDs → native APC hash/cache hit 的 positive 与 negative controls 均有证据。
- [ ] 多请求真实在途 overlap 成立、out-of-order completion/timeout 正确归属；旧同步 executor 无回归。
- [ ] TTL eta/queue-delay 只由冻结历史定义得到；缺失/冷启动/不可实现的候选级采样语义清楚记录。
- [ ] 能区分 logical unpin、native hashed eviction、后续 APC miss；无法做内容级归因的情况如实标注。
- [ ] 旧运行接口、事件写入、policy-neutral replay、Phase 1A/1B native ownership 相关回归继续通过。
- [ ] 所有 required gate 的证据、来源、状态和失败原因均可由 M1 追溯到原始事件；run config/代码/运行环境可以复现。
- [ ] H1/H2 artifacts/verdict、Continuum/Cost-Aware policies 未改。

### 12.2 M1 仅有三种最终裁定

| 裁定 | 条件与下一步 |
|---|---|
| `ACCEPT` | 修复的 native 证据与正负控制充分、旧模式回归正常、范围受控；合并 PR。**不自动批准新正式实验。** |
| `CHANGES_REQUESTED` | 已有明确 bug、安全/正确性回归、缺失必要负控制或声称超出证据；**M6** 修复并复测。 |
| `BLOCKED` | 本阶段某个 required native 能力在 pinned backend 中无法合法观察/实现，必须先由 M1 书面决定缩减后续实验主张或批准窄接口。不可假装该条件 PASS。 |

M1 合并后，未来任何正式实验都必须声明并在**真实 runtime**验证其关键 scenario 条件。**这份工程 Spec 的完成不是新方法取得收益的科学证据。**

---

## Appendix A. M1 最终验收表（由真实结果填写，预设均为 PENDING）

| Gate | 原始证据 / 准入条件 | M6 开发结果 | M1 裁定 |
|---|---|---|---|
| `G-PREFIX-INPUT` | 跨 program 同 content key，实际提交 token prefix 相同 | PENDING | PENDING |
| `G-PREFIX-NATIVE` | 相同 native hash chain + 无压力 APC hit；不同 key 负控制 | PENDING | PENDING |
| `G-INFLIGHT` | 至少两个 native requests 在完成前同时在途，request ID 无错配 | PENDING | PENDING |
| `G-NATIVE-QUEUE` | queued/scheduled 原生时序与 queueing 结果，不能由 in-flight 代替 | PENDING | PENDING |
| `G-TTL-HISTORY` | 已完成 program eta + 合资格 evicted-request queue history，时间无泄漏 | PENDING | PENDING |
| `G-PRESSURE` | logical unpin vs native hashed eviction vs future APC 分开 | PENDING | PENDING |
| `G-NEGATIVE` | 共享假标签、假并发、无历史的 sampled signals、仅 release 不 eviction 均不误 PASS | PENDING | PENDING |
| `G-LEGACY` | v1 sync、M5 substrate、Phase 1A/1B 核心不变量与 baseline 没有回归 | PENDING | PENDING |
| `G-PROVENANCE` | Full Git/runtime SHA、真实 event indices、状态/失败缺失全部保留 | PENDING | PENDING |

**最终向 M6 下达的执行指令：** **你是本轮唯一工程 Owner。把实际输入共享、真实多请求执行、历史信号来源、原生 cache eviction 与 APC 观测全部落实、测试并通过一个 PR 交付；不依赖 M5/M3，M1 最终验收。若冻结语义或 native 能力无法支持某项声明，必须实事求是标为 unsupported/undemonstrated，绝不伪造。禁止修改、重跑 H1/H2 或实现新 Cost-Aware 方法。**
