# Phase 2E — M4 → M6 观测需求清单（一页版）

**来自**：M4　**用途**：Phase 2E native baseline 采集的**只读**观测要求
**完整口径**：`docs/phase2e-m4-task-a-metrics-freeze.md`
**边界**：全部为**只读插桩或配置项**；**不含**任何 runtime policy 改动；不解锁 B1；不改 native ownership

---

## 1. 已存在的字段 —— 请在 Phase 2E 中**保持**

这些字段 Phase 2C/2D 已有，且实测**填充率 100%**（H1 的 1068 条请求观测）。
**它们是 M4 全部均值与尾部指标的唯一数据基础，请在重新物化时不要丢。**

| 事件 | 必须保留的字段 |
| --- | --- |
| `VLLM_NATIVE_REQUEST_OBSERVATION` | `native_prompt_tokens`、`native_cached_prefix_tokens`、**`native_queued_timestamp`**、**`native_scheduler_admission_timestamp`**、**`native_first_token_timestamp`**、`native_apc_block_hashes`、`native_hash_process_id`、`native_hash_function`、`native_hash_block_size` |
| `FORCED_RELEASE_DECISION` | `required_blocks`、`original_free_queue[].{block_id, native_lru_rank, has_block_hash, eligibility_tier}`、`candidates[].{program_id, block_ids, initially_reclaimable_block_ids, retention_deadline_timestamp, next_tool_type, waiting_followup}` |
| `VLLM_PREFIX_SNAPSHOT` | `block_ids`、`ordered_native_hashes`、`reusable_token_count` |
| `VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` | 现有字段 + 见下方 **R2** |
| 请求级 | `program_id`、`turn_index`、`request_id`、`native_request_id` |

⚠️ **`isolated_native_prefill_elapsed_seconds` 在 H1 填充率 0%**（那是 H2 的隔离测量字段）。
M4 用**时间戳差**代替，请**不要**为它额外工作。

---

## 2. 请求（按优先级）

### R1 `[阻塞]` 三个时间戳必须齐备

```text
native_queued_timestamp  <=  native_scheduler_admission_timestamp  <=  native_first_token_timestamp
```

H1 上 1068/1068 满足该单调序、**0 违例**。请保持。
⇒ 缺任一 ⇒ **M4 无法计算 TTFT**，A1.3 / A1.4 / A2.2 / A2.7 / A2.8 全部作废。

### R2 `[阻塞，A3 归因的硬前置]` 开启淘汰时刻的内容身份

```text
_content_evidence_enabled = true   (或在 Phase 2E 中等价的 opt-in)
```

**原因**：H1 的淘汰台账为 **5757/5757 `identity_kind = block_slot_only`、`native_hash_hex` 全为 null**。
⇒ 目前**无法**把某次物理淘汰关联到具体内容，因此「某次淘汰导致了该 miss」在 H1 **判 `NOT_IDENTIFIABLE`**。

若 R2 不开启，**M4 会在最终报告中据此限缩 A3 的全部因果结论** —— 这是可接受的，
但请**明确告知**，以免 M4 按可归因设计分析工具。

### R3 `[强烈建议]` 淘汰时刻记录 logical owners

能力矩阵当前声明 `native_block_logical_owners = UNAVAILABLE`
（*"current approved eviction callback does not persist logical owner attribution"*）。

**用途**：把「逻辑释放」与「物理淘汰」两条链**接起来**（B3 的 marginal capacity 分析）。

### R4 `[阻塞，否则延迟结论退化]` 至少一个臂并发 > 1

H1 为 `max_concurrent_requests = 1`。实测 **queue delay 最大仅 0.006 s** ⇒ 队列分量退化。

**影响**：在并发 = 1 时，token 尾部 ≈ 延迟尾部；一旦并发 > 1，两者**分离**。
M4 需要至少一个 > 1 的臂来标定「**token 成本下降是否等比例转化为延迟收益**」。

⚠️ 实测已有初步答案：H1 上 $\rho_{\text{Spearman}}(\text{recomputed}, \text{TTFT}) = \mathbf{0.4327}$，
**远非 1.0** ⇒ **token 指标不能代理 P99 TTFT**。并发臂用于确认该结论是否随并发加剧。

### R5 `[重要]` workload 必须表达 agent 空闲间隔与多轮增长

`tool_gap_seconds` 与 `W-TURN-GROW` 的 schema **已存在**；请确保它们**真正落在时间线上**
（不只是元数据字段），否则：
- 无「空闲但受保护」的 entry 组 ⇒ **没有证据的集中淘汰可观察**；
- regime 判定（RR-EVICT Eq. 1）不可算。

### R6 `[重要]` 交付物与命名

```text
<archive>/runs/<scenario>-<baseline>-<seed>/events.jsonl    原始事件（必须）
<archive>/derived/request_evidence.jsonl                     请求级派生
<archive>/derived/decision_candidates.jsonl                  候选与几何
<archive>/derived/physical_evictions.jsonl                   淘汰台账
<archive>/derived/missingness_summary.json                   缺失性（每 scenario/baseline 一张）
<archive>/manifest.json                                      哈希与版本绑定
```

### R7 `[重要]` 失败与被排除的 run 请保留并标 reason

M4 的缺失性规则要求**「排除」与「未观测」分开计数**，不得静默丢弃。

---

## 3. 分阶段交付（便于 M4 提前调试分析工具）

M1 已批准 M4/M6 **并行推进**。建议：

| 阶段 | M6 交付 | M4 可立即开展 |
| --- | --- | --- |
| **T1** | 任一 family 的 1 个 scenario（LRU + Continuum 各 1） | 跑通指标管线，核对字段与单调性 |
| **T2** | 3 个 family × 2 draws | 集中度与尾部形状的**描述性**初查 |
| **T3** | 完整 6 family × 6 draws × 2 baselines × 2 repeats | 最终报告的全部推断性分析 |

⚠️ **M4 承诺**：不依据 T1/T2 的早期有利结果临时改动主要指标或 workload 分布（M1 §六）。

---

## 4. 明确**不**要求 M6 做的事

```text
❌ 不实现任何 Cost-Aware / RR-EVICT / tail-chunk 策略
❌ 不改 native BlockPool / hash table / refcount / ownership / LRU
❌ 不解锁 B1 的 runtime 修改
❌ 不改 Continuum 默认 TTL 与释放顺序
❌ 不要求 hardware counters（如不可得，标 NOT_OBSERVABLE 即可）
❌ 不重开 H1/H2
```

---

## 5. 一句话总结

> **请在 Phase 2E 中保住三个时间戳（R1）、打开淘汰时刻的内容身份（R2）、
> 并给出至少一个并发 > 1 的臂（R4）。** 其余为增强项。
> 若 R2 无法落实，M4 会把 A3 的因果归因限缩为 `NOT_IDENTIFIABLE` 并在报告中说明 —— 请提前告知以便对齐。
