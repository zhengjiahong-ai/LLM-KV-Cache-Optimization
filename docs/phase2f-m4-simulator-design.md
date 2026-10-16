# Phase 2F — 模拟器设计：物理 block 级 APC + Agent 生命周期 + Continuum Retention

**提交人**：M4　**送审**：M1　**日期**：2026-10-16
**性质**：CPU-only、无 GPU、无真实模型的事件驱动离线模拟。**不是**延迟模型，**不是** serving 基准。
**配套文档**：`docs/phase2f-m4-combined-algorithm-design.md`（算法层）。

---

## 0. 为什么需要新模拟器（现状核查结论）

已核查（Explore 清单，main @ `069e5dc`）：仓库内**不存在**具有物理 block、连续前缀命中、
共享前缀与淘汰后缓存状态语义的模拟器：

| 现有件 | 实际语义 | 缺口 |
| --- | --- | --- |
| `kv_cache/manager.py::KVCacheManager` | 请求级逻辑块计数 + `set[int]]` 空闲集 | 无内容身份、无连续前缀、整请求淘汰 |
| `runtime/simulator.py::Simulator` | 请求级功能循环（1 token/step） | 无 block 级事件、无 APC 命中 |
| `costaware/replay.py` | 对**已录制** `FORCED_RELEASE_DECISION` 快照重放压力循环 | entry 级；不模拟物理淘汰后果 |
| `workload/phase2e_*` | workload 生成/校验（CPU）+ Metal 后端执行 | 执行需真实后端 |

⇒ 按任务授权，建立**独立的物理 block 级 APC 模拟 harness**：
`src/kvopt/agent_sim/`。它**复用**冻结 Continuum 组件（§5），不修改它们，
并清楚记录与真实 vLLM 的差异（§9）。

---

## 1. 内容身份与前缀 trie

### 1.1 内容身份（链式 hash，trie 语义）

每个请求的 prompt 由若干 **segment** 组成，每段 token 数为 block size（16）的整数倍。
segment 依序铺成 block 序列；block i 的内容身份为链式 hash：

```text
content_id(b_0) = H("root", seg_key(b_0), 0)
content_id(b_i) = H(content_id(b_{i-1}), seg_key(b_i), i)
```

- 与 vLLM prefix hash 语义一致：**相同 token 在不同前缀位置 ⇒ 不同身份**（trie，非 DAG 展平）。
- 两个请求共享前缀 ⇔ 它们的 block 序列从头起逐块相同 ⇒ 共享块自动获得**相同 depth**
  （在 trie 路径上的 1-based 位置）。深度因此是内容属性，与物理槽位无关。

### 1.2 可缓存前缀上限（沿用冻结口径）

对 N tokens 的请求，可缓存前缀为 `M = (N − 1) // B` 个 block（冻结推导
`profiling/runtime_evidence.py::_eligible_prefix_tokens` 的 cap：最后一个 prompt block
不计入可复用前缀，保守于 vLLM 实际行为）。最后一个 block 分配为 **hashless** 物理块，
从不进入 cache mapping、永不被命中。

---

## 2. 物理 block 池与 free queue（对齐 vLLM 0.27.1 语义）

```text
pool: 固定 total_blocks 个物理槽位；block_size_tokens 默认 16（可配置）
每槽位状态: content_id(可空), depth, ref_cnt, band_id, band_pos, has_block_hash
cache mapping: content_id -> block_id   （仅 hashed 块；命中判定唯一来源）
free queue: 双向链表，顺序即原生 free queue 顺序；lru_rank = 位置（0 = 队首）
```

**入队规则**（假设 A1/A2，来源：M1 RC-A 引用的 vLLM v0.27.1 `block_pool.py`
L719–742：`prepend_n(blocks_without_hash)` / `append_n(blocks_with_hash)`）：

```text
一次 free event（某请求完成，按 block table 头→尾序释出全部块）:
  hashless 块 -> prepend 到队首（保持释出次序）   => 形成队首的 hashless band
  hashed   块 -> append 到队尾（保持释出次序）   => 形成一个 hashed band
band_id    = free event 序号（单调递增）
band_pos   = 块在该次释出列表中的 1-based 位置（头→尾）
```

⇒ 同一 band 内 hashed 块**头块 lru_rank 更小**（native 先淘汰浅层）；
hashless band 位于全部 hashed band 之前（native 先重用零成本块，**该行为不是本方法创新**）。

**acquire**（前缀命中或重分配）：从队中移除（O(1) 链表删除），`ref_cnt += 1`；
**release**（请求完成）：`ref_cnt -= 1`，归零则按上述规则入队（新 band）。
**淘汰**（victim 选中）：从队中弹出；若 hashed ⇒ 从 cache mapping 移除（真实 hash cleanup），
触发 `BlockEvicted` → `RetentionManager.observe_eviction`；随后**立即**分配给新内容
（vLLM `get_new_blocks` → `_maybe_evict_cached_block` 语义：victim 槽位被新内容复用）。

⚠️ **假设 A1（band 内头先）未经本项目运行时实测**（P5 depth NOT_OBSERVABLE）。
敏感性臂 S1 将整个 free-order 翻转为尾先重跑，量化结论对该假设的依赖。
模拟器直接把 `(depth, lru_rank)` 对应关系作为可测量输出（§7）。

---

## 3. 分配路径（一次 LLM 请求的完整流程）

```text
输入: 请求 r（prompt 的 block 内容序列 c_1..c_M + hashless 尾块），时刻 t
1. 连续前缀截断命中（严格公式，禁集合交集）:
     j = 0
     while j < M and c_{j+1} in cache_mapping: j += 1
     # 第一个未命中处立即截断；其后即使有缓存块也不算命中
2. acquire 命中块: 对 i in 1..j: 块 = cache_mapping[c_i]
     若在 free queue 中 -> 移出队列; ref_cnt += 1
3. needed = M - j (+ 1 个 hashless 尾块)
4. 若 len(free_queue) < needed: 失败（单请求超过容量；workload 生成器保证不出现）
5. victim 选择（arm 相关，见 §6）:
     candidates = free queue 全量（顺序即队列序, lru_rank = index）
     Retention 开: coordinator.prepare(candidates, entries, required_blocks=needed, timestamp=t)
                   -> eligible(T1∪T2) + pressure_releases; commit_pressure_releases
     Retention 关: eligible = 全量
     victims = 策略从 eligible 选 needed 个（键见算法设计 §2.3 / §4）
6. 执行淘汰: 对每个 victim（按策略序）:
     弹出队列; hashed -> cache_mapping 移除 + BlockEvicted(observe_eviction);
     分配给新内容: content_id = c, depth = trie 深度, ref_cnt = 1, band 清空
7. 记账: N_r, M_r, E_r = LCP(r, 更早请求的可缓存前缀)·B, C_r = j·B, recomputed_r = E_r − C_r
```

**物理 ID 生命周期**：victim 槽位立即复用；`content_id` 不同 ⇒ 旧内容身份不再可命中
（幽灵命中由 cache mapping 的唯一性 + 淘汰时移除保证；微基准 (b) 验证）。

---

## 4. Agent 生命周期（事件模型）

事件堆（`(timestamp, seq)` 字典序，seq 在生成时分配 ⇒ 全确定）：

```text
PROGRAM_STARTED / PROGRAM_COMPLETED      program 边界（观察性）
REQUEST_ARRIVED                         记录 server gap 历史（RuntimeCoordinator）
REQUEST_ADMITTED                         admit_followup（解除本 program 旧 entry 保护）
   -> 立即执行 §3 分配路径（瞬时执行模型，见 §9.4）
TOOL_GAP_STARTED / TOOL_GAP_ENDED       外部工具间隔（ExternalToolDurationHistory）
TURN_FINISHED(is_terminal, next_tool_type)  TTL 决策 + upsert retention entry(protected=True)
FOLLOWUP_WAITING                        mark_followup_waiting（gap 期间保护的关键）
FOLLOWUP_CANCELLED                      cancel_followup（异常结束；protected = deadline > now）
BLOCKS_OBSERVED / BLOCK_EVICTED         块关联观察 / 物理淘汰通知（retention 反向索引清理）
```

多轮结构：turn t 的 prompt = turn t−1 的可缓存前缀 + 新 segment（trie 自然延伸）。
终止方式可配置：`COMPLETED`（terminal turn → complete_program）、
`CANCELLED`（FollowupCancelled，异常结束）、`ABANDONED`（无后续请求，entry 悬挂——
与冻结行为一致：`ProgramCompleted` 在 `RuntimeCoordinator.handle` 中是 no-op，
只有 terminal turn 才 `complete_program`）。

**warmup / measured 双窗口**：trace 含 `warmup_requests` 与 `measured_requests`；
两者都真实执行（warmup 改变缓存状态与 TTL 历史），指标只统计 measured 窗口。
cold draw = warmup 为空；warm draw = warmup 含若干完整 program 生命周期。

---

## 5. Retention 复用映射（冻结组件 → 模拟器接线）

| 冻结组件 | 模拟器中的角色 |
| --- | --- |
| `RuntimeCoordinator`（clock=FakeClock） | 接收 §4 全部生命周期事件；维护 server-gap / tool-duration / queue-delay / eta 历史；在 `TurnFinished` 产生真实 `TTLDecision` 并 upsert `RetentionEntrySnapshot(protected=True, block_ids=本请求全部块)` |
| `RetentionManager` | 保护状态、惰性过期、waiting、admit/cancel/complete、`observe_eviction` 清理反向索引 |
| `RetentionAwareSelectionCoordinator.prepare` | 每次分配前计算 Tier 1/Tier 2 与压力释放（冻结键 `(deadline, min newly-eligible lru_rank, key)`） |
| `RetentionAwareLRUAdapter` | **A1 臂直接实例化**，保证与冻结路径逐位一致 |
| `load_prefill_reload_provider` + `compute_default_ttl_seconds` | TTL 的 R 与冷启动 TTL（正式 profile 工件，`InputSource.APPROXIMATED` 已由工件声明） |
| `ContinuumSchedulingPolicy` | 仅 A4 臂的准入排序 |

**TTL 输入的模拟器取值（InputSource 记录）**：

| 输入 | 取值 | 来源 |
| --- | --- | --- |
| `global/tool_server_gap_samples` | trace 生成的 tool gap | `OBSERVED`（workload 输入，freeze §2 允许 EXTERNAL→OBSERVED 记录） |
| `queue_delay_t_seconds` | **0.0**（模拟无排队模型，串行瞬时执行） | `OBSERVED` + 退化说明；敏感性扫描 {0.0, 0.05, 0.65}s |
| `eta` | `eta_history.eta()` 实算 | `OBSERVED`/`APPROXIMATED`（冻结估计器自带） |
| `prefill_reload_seconds` | 正式 profile（16–512 线性插值）；>512 用末段线性外推 | `APPROXIMATED`（profile 工件）+ 外推标注；敏感性：截断到 512 |
| `default_ttl_seconds` | `compute_default_ttl_seconds(profile(256))` = `max(0, log(0.0887))` = **0.0** | 冻结 concretization |

⚠️ 记录到的结构事实：`duration_history_threshold=100` ⇒ 小场景恒为 `COLD_START`（TTL=0）；
gap 尺度（0.5–2s）远大于 benefit（R≈0.089s, T=0）⇒ 经验 TTL 常退化为 0。
⇒ **Retention 的保护主要来自 `waiting_followup` 窗口，而非 TTL 延长**；
TTL 的作用集中在 `cancel_followup` 后的存活判定。该结论本身是报告内容（与 Phase 2A F.2 一致）。

---

## 6. 策略接口与无前视保证

```text
策略输入（每次淘汰决策）:
  SimCandidate = {block_id, lru_rank, has_block_hash, tier, depth, band_id, band_pos}
  context      = {required_blocks, free_blocks, total_blocks, timestamp}
策略输出: 有序 victim block_id 序列（唯一、⊆ candidates、数量 = min(required, |candidates|)）
```

- **无前视**：策略函数只接收上述快照；未来请求、未来复用、未来重计算**不在输入内**。
  单测断言：截断 trace 不影响已发生决策（lockstep 重放校验）。
- oracle 策略显式接收未来 trace（独立类，标注 `ORACLE`），与在线策略**不同代码路径**。
- 所有臂共用同一分配/记账路径；唯一差异是 victim 选择键与 Retention 开关。

---

## 7. 模拟器直接输出的运行时缺口测量（RC-B 要求）

模拟器对每次淘汰决策记录 `(block_id, depth, lru_rank, band_id, band_pos, tier, required, |eligible|)`，
从而首次提供本项目内 `(depth, native_lru_rank)` 对应关系的**可复核统计**：

```text
band 内 depth 与 lru_rank 的秩相关（按 band 分组）
native 先淘汰浅层（depth 小）的事件占比        <- RC-B 结构信号的直接度量
非平凡窗口占比（|eligible| > required）
victim 集合分歧率（A2≠A0、A3≠A1）
```

这些量在 runtime 因 P5 `NOT_OBSERVABLE` 不可得；模拟结果**不得**被当作 runtime 证据，
只能作为"若接口扩展后值得验证"的先验。

---

## 8. 确定性、可复现性与失败归因

- 单种子 RNG（`random.Random`，按 draw 种子化）只用于 workload 生成；模拟期无随机。
- 事件堆 `(timestamp, seq)`；dict 迭代全部按确定序；无 wall-clock、无线程。
- 同一 (trace hash, config hash, code version) ⇒ 逐位可复现；产物记录三者。
- 失败归因表（机制链不过时的诊断）：

| 观察 | 归因 | 模拟器内检测 |
| --- | --- | --- |
| L1 不过（victim 集合从不分歧） | 未触发（无非平凡窗口 / 假设 A1 不成立） | `nontrivial_share`、`divergence_rate` |
| L1 过、L3 不过（缓存状态不变） | 未实现（淘汰未真正移除 hash） | cache mapping 前后差 |
| L3 过、L4 不过（重计算不变） | 机制失败/无收益 | ΔR 分布 |
| 效应量极小 | 有效但不可用 | 效应量 + CI |

---

## 9. 与真实 vLLM 的差异（必须随报告发布）

| # | 差异 | 方向 | 处理 |
| --- | --- | --- | --- |
| 1 | 请求瞬时执行，无 running 期、无抢占、无并发执行 | 简化 | 与 Phase 2E F1–F5（`max_concurrent_requests=1`）一致；F6 式并发用同时到达 + 串行准入近似 |
| 2 | 无调度器争用；queue delay 退化为 0 | 保守（TTL benefit 偏小） | 敏感性扫描 queue_delay |
| 3 | 最后一个 prompt block 不可缓存（冻结 cap） | 保守（低估命中） | 沿用冻结口径；报告说明 |
| 4 | band 内头先入队为源码推导假设 | 关键假设 | S1 敏感性臂 + §7 直接测量 |
| 5 | 无 decode 期（`max_new_tokens=1` 同 regimes） | 与 Phase 2E 一致 | 不宣称 decode 结论 |
| 6 | segment 为 block 对齐的离散内容单元 | 建模抽象 | 生成器保证；近似假设记入 trace |
| 7 | 无 TTFT/TPOT/吞吐 | **NOT_MEASURED** | 显式标注；token 指标不作延迟代理（Phase 2E 教训） |
| 8 | PrefillReload 仅为 TTL 输入，不作为时间成本 | — | 成本一律用 token/block 数 |

---

## 10. 规模与性能

- 7 族 × 10 draws = 70 个独立 scenario draw（统计单位）。
- 每 draw × 每臂：~20–80 请求、capacity 64–512 blocks、淘汰决策 O(queue) 扫描。
- 全 campaign（主臂 5 + oracle 2 + 判别/敏感性）预计 CPU 秒级–分钟级；记录实际耗时。
