# Phase 2A — 门禁与 Profiling 契约差距核对

状态：M4 差距审计（AUDIT）—— 供 M1/M6 评审

## 0. 目的与范围

本文档核对 `docs/phase2a-empirical-gap-gate.md` 的四项必需门禁（外加一项辅助门禁）与
`main` 上既有 profiling 契约的实际差距，逐项回答：

> 现有契约是否**足以**让 M6 计算出该门禁项？若不足，缺的到底是什么、归谁处理？

本文档不做经验判断，不预测门禁结果，不实现任何东西。它只做一件事：把「契约能不能算」与
「结果好不好」分开，因为前者是工程问题（可以立刻修），后者是研究结论（必须等数据）。

## 1. 门禁要求逐条抽取

### 1.1 决策有效性前置条件

一条 forced-release 决策可用于候选级分析，必须满足：

```text
V1  candidate_count >= 2
V2  完整的决策时候选快照
V3  selected logical release(s) 可追溯
V4  决策后生命周期可追溯
V5  必需能力的缺失被显式记录
```

### 1.2 五项门禁

| 编号 | 门禁 | 类型 | 通过条件 |
| --- | --- | --- | --- |
| G1 | 数据完整性 | 必需 | ≥ 95% 的有效决策能从 decision join 到选中逻辑释放与决策后生命周期；物理驱逐要么可 join、要么显式标为 unavailable；派生行不得丢失 `run_id` / `decision_event_index` 溯源 |
| G2 | 事件量 | 必需 | ≥ 30 个有效多候选 forced-release 决策，跨 ≥ 3 个场景族，≥ 3 个 seed 有代表 |
| G3 | 异质性 | 必需 | ≥ 1 个非平凡 realized-loss 视角同时满足：≥ 25% 的有效决策有正决策内 spread；均值决策内 spread 的 bootstrap 95% CI 严格 > 0 |
| G4 | 基线 headroom | 必需 | 对 ≥ 1 个 realized-loss 视角：Continuum 在 ≥ 10% 的有效非平局决策中严格劣于 hindsight；归一化 regret 的 bootstrap 95% CI 下界 > 0 |
| G5 | 决策时信号 | 辅助 | ≥ 1 个决策时特征或预先注册的简单组合，其关联跨场景族与 seed 稳定 |

### 1.3 门禁自己声明的损失视角层级

G3/G4 都要求「realized-loss 视角」，而门禁按直接程度排序：

```text
1  actual recompute work          （最直接）
2  serving impact
3  physical eviction cost
4  logical release / PrefillReload proxy   （代理）
```

并明确：

> Proxy-only evidence can establish HETEROGENEITY-PROVISIONAL but not the strongest final claim.

**这行文字是本审计的核心约束。** §4 会说明它为什么决定了当前契约只能拿到什么级别的结论。

## 2. 契约现状（逐层核对）

数据源：`src/kvopt/profiling/forced_release.py`、`src/kvopt/profiling/experiment_events.py`、
`src/kvopt/profiling/artifacts.py`、`src/kvopt/continuum/pressure.py`、
`src/kvopt/workload/phase2_runner.py`、`docs/experiments/phase2-minimal-real-observability.md`。

### Layer A — 决策时状态与逻辑释放：**完整**

`FORCED_RELEASE_DECISION` 由 `ExperimentForcedReleaseObserver.observe()` 发出
（`experiment_events.py:278-352`），payload 覆盖数据契约 §3 的全部要求：

| 契约要求 | 现状 | 来源 |
| --- | --- | --- |
| `event_index` | ✅ 由 `JsonlExperimentEventSink.emit()` 按 run 单调分配 | `artifacts.py:18-19,27` |
| `timestamp` | ✅ `snapshot.timestamp` = `preparation.preparation_timestamp` | `forced_release.py:122-123` |
| `clock_domain` | ✅ 固定 `"continuum_pressure"` | `experiment_events.py:325` |
| `required_blocks` | ✅ | `experiment_events.py:328` |
| `original_free_queue` | ✅ 含 `block_id` / `native_lru_rank` / `has_block_hash` / `eligibility_tier` | `experiment_events.py:329-340` |
| `ordinary_expired_entries` | ✅ | `experiment_events.py:341-347` |
| `candidates` | ✅ 决策时全部受保护且未过期条目 | `forced_release.py:178-215` |
| `selected_releases` | ✅ 与决策同事件，**无需 join** | `forced_release.py:130-131` |

候选级字段（数据契约 §3 要求的全部 11 项）：`program_id`、`prefix_id`、
`retention_deadline_timestamp`、`waiting_followup`、`block_ids`、
`initially_reclaimable_block_ids`、`next_tool_type`、`elapsed_since_ttl_decision_seconds`、
`prefill_reload_seconds`、`eta`、`queue_delay_t_seconds` —— **全部具备**。

两项有利的结构性事实：

1. **观察只在真正发生强制释放时才触发。** `pressure.py:155-163` 的
   `if preparation.pressure_releases:` 守卫意味着普通过期不会污染决策流，
   所以「是不是真的 forced release」不需要下游判别。
2. **`candidates` 与 `selected_releases` 的粒度天然正确。** 候选是决策时的**全部**受保护条目
   （不限于被释放的），因此 `candidate_count >= 2`（V1）可以直接从事件读出，且一次决策
   可以含多个 `selected_releases`（同一次分配内的迭代释放循环，`pressure.py:100-127`）。

⇒ **Layer A 对 V1/V2/V3 无差距。**

### Layer B — 物理缓存动作：**部分**

`BLOCK_EVICTED` 由生命周期桥接发出（`experiment_events.py:262-264`），含 `event_index` /
`timestamp` / `block_id`。

数据契约 §4 的「期望富化」三项全部缺失：

```text
native_hash_hex or equivalent content identity   缺
known logical owners [(program_id, prefix_id)]   缺
native LRU position at that exact boundary       缺
```

契约允许这些字段缺席——但要求「record it as unavailable rather than fabricating it」，
即**必须显式记录为不可用**。当前没有逐字段的可用性记录（见 §4 的 F-F）。

更关键的是一致性边界问题：契约写明物理槽位 join

> only within a bounded state interval

因为 `block_id` 是会被复用的槽位，而非内容身份。**但当前没有任何事件界定该区间**——
既没有槽位释放事件，也没有内容变更事件。因此「决策 → 物理驱逐」的 join 只能靠
`block_id ∈ selected_release.newly_eligible_block_ids` 加 `event_index` 先后关系，
这在槽位复用发生时会**静默地**产生假 join。

⇒ G1 的「物理驱逐可 join」在**机制上成立**，但在**正确性上未经约束**。

### Layer C — 未来缓存与重计算事实：**生命周期完整，后端事实全缺**

| 契约要求 | 现状 |
| --- | --- |
| `REQUEST_ARRIVED` / `REQUEST_ADMITTED` / `BLOCKS_OBSERVED` / `VLLM_PREFIX_SNAPSHOT` / `TURN_FINISHED` / `PROGRAM_COMPLETED` | ✅ 全部具备（`continuum/events.py:20-33` 的 12 类生命周期事件 + Metal 适配器发出的 `VLLM_PREFIX_SNAPSHOT`） |
| native APC hit/miss、cached-token count、computed/recomputed/prefill-token count、native cache lookup result | ❌ 全部 capability-gated 且当前为 UNAVAILABLE |

`VLLM_PREFIX_SNAPSHOT` 提供 `reusable_token_count` 与 `block_ids`，能支撑
「前缀 → 原生块」映射，但**不能**推出命中了多少或重算了多少——
数据契约对此有明确禁令：

> Do not infer native hit/miss or recompute-token count from prefix identity alone.

⇒ V4（决策后生命周期可追溯）**满足**；但重计算层证据**结构性缺失**。

### Layer D — 时序与 serving 结果：**计划侧完整，观察侧缺关键锚点**

`docs/experiments/phase2-minimal-real-observability.md` 的能力审计记录了三项关键 UNAVAILABLE：

```text
native_first_token_timestamp             UNAVAILABLE
native_scheduler_admission_timestamp     UNAVAILABLE
hardware performance counters            UNAVAILABLE
```

且明确禁止语义漂移：

> The current Phase 2 `REQUEST_ADMITTED` boundary must not be silently relabelled as native scheduler-admission timing.

⇒ serving 层指标（TTFT / E2E / queue wait）**当前不可得**；`generated token count` 可得。

## 3. 差距矩阵

| 门禁项 | 契约就绪度 | 阻塞方 |
| --- | --- | --- |
| V1 候选数 ≥ 2 | ✅ 可直读 | 无 |
| V2 决策时快照完整 | ✅ 完整 | 无 |
| V3 选中释放可追溯 | ✅ 同事件，无需 join | 无 |
| V4 决策后生命周期可追溯 | ✅ 生命周期事件齐全 | 无 |
| V5 缺失能力显式记录 | ❌ 仅 4 键，缺 Layer B/C/D 逐项登记 | M1 / M5 |
| G1 数据完整性 | ⚠️ 机制成立，物理 join 无区间约束 | M6 量化歧义；M1 可选加身份 |
| G2 事件量 | ⚠️ 机制具备，配置不足（每 run 目前 1 决策） | M6 |
| G3 异质性 | ⚠️ 仅视角 3/4 可算，视角 1/2 不可算 | M6（算）；M1（若要最强结论） |
| G4 基线 headroom | ⚠️ 同 G3 | M6（算）；M1（若要最强结论） |
| G5 决策时信号 | ✅ 9/9 特征可得 | 无 |

## 4. 关键结论

### F-A：Layer A 无差距，V1–V4 全部满足

这是好消息：决策时证据链在契约层面已经完备，不需要任何接口变更即可支撑 G5 与
「决策内特征 spread」的计算。

### F-B：物理驱逐可 join，但缺槽位区间约束

`BLOCK_EVICTED` 存在，但 join 正确性依赖一个**未被任何事件界定**的槽位有效期。
形式化矩阵 F6 已经预期了这一点（要求报告 "ambiguity rate if joining only by block_id"），
所以这是 M6 必须**量化并如实报告**的已知限制，而非必须立刻修复的阻塞项。
但它意味着：**只用 `block_id` 做的物理驱逐归因，其可信度必须被显式标注。**

### F-C：损失视角是**最关键的差距**——它决定了门禁能拿到什么级别的结论

把 §1.3 的视角层级与 §2 的能力现状对齐：

| 门禁视角 | 所需能力 | 当前状态 | 可支撑的门禁结论级别 |
| --- | --- | --- | --- |
| 1 实际重计算工作量 | recomputed / prefill token count | ❌ UNAVAILABLE | 不可用 |
| 2 serving 影响 | first-token ts + scheduler-admission ts | ❌ 双项 UNAVAILABLE | 不可用 |
| 3 物理驱逐成本 | `BLOCK_EVICTED` | ✅ AVAILABLE | 见下 |
| 4 逻辑释放 / PrefillReload 代理 | `FORCED_RELEASE_DECISION` | ✅ AVAILABLE | 仅 `HETEROGENEITY-PROVISIONAL` |

因此当前契约下**唯一可能支撑「非 provisional」结论的视角是 3（物理驱逐成本）**。

⚠️ **需要 M1 裁定的解释歧义**：门禁把视角 3 列在「按直接程度排序」的清单里，却只对
「proxy-only evidence」作了降级规定。**视角 3 究竟算 direct 还是 proxy，文本没有明说。**
这不是文字游戏——它直接决定：

- 若视角 3 算 direct → 现有契约**可能**足以支撑 `GAP-PASS`，无需新增观察锚点；
- 若视角 3 算 proxy → 现有契约最高只能到 `GAP-PROVISIONAL`，要拿 `GAP-PASS` 必须先由
  M1 新增至少一个观察锚点（重计算 token 或 serving 时序）。

**这是本审计中唯一一个必须由 M1 明确裁定的问题**，因为它可以完全改变 M4 后续的
工作量分配。

### F-D：决策时信号在契约层面无阻塞

门禁 §6 列出的候选输入全部可得：

```text
prefix/block footprint          ✅ 经 candidate.block_ids 长度或 VLLM_PREFIX_SNAPSHOT.reusable_token_count
PrefillReload                   ✅ candidate.prefill_reload_seconds
next_tool_type                  ✅
elapsed_since_ttl_decision      ✅
retention deadline              ✅
waiting_followup                ✅
eta                             ✅
queue delay                     ✅ candidate.queue_delay_t_seconds
native LRU position             ✅ 经 original_free_queue 的 native_lru_rank 按 block_ids 派生
```

额外可得：`has_block_hash`、`eligibility_tier`（逐块，来自 `original_free_queue`）。

已知预期弱点（源自 spike F.3）：`queue_delay_t_seconds` 是全局均值，同一次决策内对所有
候选相同，因此该特征预期会被分析判为「可用但无区分力」。这是**已知结论**，不是契约差距。

⇒ G5 在契约层面无阻塞。

### F-E：缺「前缀内位置」信号（非门禁阻塞，但是设计前置）

门禁 §6 的特征清单**不包含**前缀内位置索引，所以它**不是**门禁阻塞项。

但它是 `docs/phase2a-m4-block-level-design-draft.md` §6 中选项 B1（部分前缀保留）的硬前置。
两者必须分开记录，否则容易混淆优先级：门禁不需要它，但设计需要它。

### F-F：能力可用性登记不完整（直接违反 V5 与数据契约 §5）

两处记录不一致：

| 位置 | 内容 |
| --- | --- |
| `run.json.observation_availability`（通用 runner，`phase2_runner.py:180-185`） | 仅 **4 键**：`lifecycle`、`forced_release`、`native_apc_hit_miss`、`hardware_counters` |
| `observation-report.json.capabilities`（Metal spike launcher，`run_phase2_minimal_observability_metal.py:266-310`） | **10 项**，逐项 `status` + `reason` |

数据契约 §5 的要求是：

> Every capability must be either AVAILABLE or UNAVAILABLE + reason.

通用 runner 的 4 键映射**不满足**该要求：Layer B 的富化字段、Layer C 的 token 计数、
Layer D 的时序锚点都未登记。富能力审计只存在于 Metal spike launcher，而那个 launcher
不是正式 campaign 的执行路径——正式 campaign 走的是 `benchmarks/run_phase2a_full_pilot.py`
→ `run_phase2()`。

⇒ 这是**当前唯一一条「可直接修复且必须修复」的契约违反**，且修复成本很低。

### F-G：事件量机制具备，但配置不足

机制事实：

- runner 的 `stop_on_forced_release` 在**首个**强制释放后结束该 pressure stage
  （`phase2_runner.py:207-232`）；
- 一次决策可含多个 `selected_releases`，所以「多候选 + 多释放」在单决策内即可表达；
- 每个 run 的决策数 = 触发强制释放的 pressure stage 数。
  `tests/test_phase2_substrate.py:289-348` 已证明 2 个 stage → 2 个决策。

配置事实：

- 现有 `configs/phase2/profiling/p*.json` 每场景只有 1 个 pressure stage；
- foundation suite 是 10 场景 × 3 seed = 30 runs = **30 个决策，正好在最低线**；
- 而门禁明确说 foundation suite **不能**独立作为门禁输入，
  形式化矩阵要求「with margin, not exactly at the minimum」。

⇒ 正式 campaign 必须通过**多 stage trace 或更多 run**取得有余量的决策量。
这是 M6 的场景/配置工作，不是代码缺陷。

### F-H：G3/G4 本身是经验结论，不是契约差距

契约的责任只是让它们**可计算**。是否真的存在异质性与 headroom，必须等 M6 数据。
特别提醒：spike 的 F.2 已经指出 TTL 过滤器会把保护池**同质化**，
这正是 G3 最可能失败的路径——而它**无法靠增加契约字段解决**。

### F-I：无未来信息泄漏——契约已合规

- `forced_release.py:32-41` 的 docstring 明确排除 future reuse / return time / 实际重计算 /
  下游延迟；
- 数据契约 §8 把 `recomputed_tokens`、`hindsight_loss`、`oracle_candidate`、`regret`
  全部划归 **M6 派生处理**，不属于运行事件 schema；
- runtime 不发出任何 oracle / regret / future-derived 标签。

⇒ 契约层面无差距。M6 仍需按正式测试计划 §6 实现 `online features` 白名单与
no-future-leakage 测试，但那是 M6 的交付项。

### F-J：`REQUEST_ADMITTED` 语义边界已被妥善处理

数据契约 §6 与 Metal 能力审计都把 `native_scheduler_admission_timestamp` 标为 UNAVAILABLE，
并给出正确理由（该边界是**逻辑保留边界**，不是原生调度时序）。

⇒ 无差距，但 M6 派生 serving 指标时必须遵守此边界，不得把逻辑边界当作调度时序。

## 5. 按 owner 的变更请求

### M1（观察锚点与契约）

| 编号 | 请求 | 优先级 | 理由 |
| --- | --- | --- | --- |
| L1 | 把 10 项能力审计从 Metal spike launcher 提升到通用 runner 的 `run.json`，替换现有 4 键 `observation_availability` | **高** | 唯一可立即修复的 V5 / 数据契约 §5 违反；成本低 |
| L2 | 为 `BLOCK_EVICTED` 的富化字段（content identity / owners / LRU position）增加显式 availability 条目 | **高** | 契约要求「record as unavailable rather than fabricating」 |
| L3 | **裁决 F-C 的解释歧义**：门禁视角 3（物理驱逐成本）算 direct 还是 proxy？ | **高** | 它决定 M4 是否需要等待新观察锚点 |
| L4 | （条件性）若 L3 判定视角 3 为 proxy → 新增至少一个观察锚点：`recomputed/prefill token count` 或 `first-token timestamp` | 中 | 决定能否拿到「最强最终结论」 |
| L5 | （设计前置，非门禁）前缀内位置索引 + block → owner 映射 | 中 | 设计草案 B1 的硬前置 |

### M6（配置与派生）

| 编号 | 请求 | 优先级 | 理由 |
| --- | --- | --- | --- |
| L6 | 正式 campaign 采用多 stage trace 或更多 run，使决策量**有余量** | **高** | G2；foundation suite 不合格 |
| L7 | 量化并报告 `block_id`-only join 的 ambiguity rate | **高** | G1；形式化矩阵 F6 已预期 |
| L8 | 按 4 个损失视角**分别**构建 `decision_outcomes` 表，显式展示分歧 | **高** | 数据契约 §9；门禁 §4 |
| L9 | 实现 online-feature 白名单与 no-future-leakage 测试 | **高** | 正式测试计划 §6 |
| L10 | 如实报告视角 1/2 为 UNAVAILABLE，不得用代理值静默替代 | **高** | 数据契约 §5 |

## 6. 无法靠增加契约解决的项目

必须明确区分，避免把工程工作误当成研究推进：

1. **G3/G4 的经验结论本身。** 加字段只能让计算可行，不能让异质性或 headroom 存在。
2. **TTL 过滤器造成的保护池同质化。** spike F.2 指出保护池被预先同质化；这不是观测不足，
   而是基线机制的结构性后果。若 G3 因此失败，正确结论是 `NO-MEASURABLE-GAP`，
   而不是「再加点字段试试」。
3. **真实 $C(r)$ 曲线的非线性程度。** 这是测量问题，与契约无关；
   由设计草案 §8 认定为该技术路线的唯一决定性实验。
4. **物理驱逐与逻辑释放的语义差异。** 契约已正确地把二者分开；
   不能通过"取其一"来简化，只能分别报告。

## 7. 建议推进顺序

```text
第 1 步  M1 做 L1 + L2（成本低，且是当前唯一的契约违反）
第 2 步  M1 裁定 L3（视角 3 的档位）—— 这是分叉点
第 3 步  M6 并行做 L6/L7/L9/L10，启动正式 campaign
第 4 步  用视角 3（物理驱逐成本）与视角 4（逻辑释放代理）跑 G3/G4
第 5 步  若 G3/G4 只在视角 4 通过 → 最高 GAP-PROVISIONAL，转第 6 步
         若在视角 3 通过且 L3 判定为 direct → 可考虑 GAP-PASS
第 6 步  仅在需要「最强结论」时才投入 L4
第 7 步  独立于门禁并行排期：真实 C(r) 测量（设计草案 §8）
```

关键判断：**第 2 步（L3 裁定）应当尽早完成**，因为它决定第 6 步是否需要存在。
在它裁定之前，M4 无法合理估算自己距方法设计还有多远。

## 8. 可追溯性

| 章节 | 来源 |
| --- | --- |
| §1 | `docs/phase2a-empirical-gap-gate.md` §2–§7 |
| §2 Layer A | `src/kvopt/profiling/forced_release.py`、`experiment_events.py`、`artifacts.py`、`continuum/pressure.py:155-163` |
| §2 Layer B/C/D | `docs/phase2a-profiling-data-contract.md` §4–§6、`docs/experiments/phase2-minimal-real-observability.md` 能力审计 |
| §3, §4-F-G | `src/kvopt/workload/phase2_runner.py:180-232`、`tests/test_phase2_substrate.py:289-348` |
| §4-F-F | `phase2_runner.py:180-185` 对比 `run_phase2_minimal_observability_metal.py:266-310` |
| §4-F-C | `docs/phase2a-empirical-gap-gate.md` §4 |
| §6 | `docs/phase2a-m4-block-level-design-draft.md` §2.1（F.1/F.2）、§8 |
| §5 L5 | `docs/phase2a-m4-block-level-design-draft.md` §6 |

相关文档：`docs/phase2a-m4-method-support-pack.md`、`docs/phase2a-m6-formal-test-plan.md`、
`docs/phase2a-m6-formal-experiment-matrix.md`。
