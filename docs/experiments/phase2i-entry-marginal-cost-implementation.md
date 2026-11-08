# Phase 2I — Entry-level Prefix-suffix-aware Marginal Cost-Aware Algorithm（实现说明）

**授权**：M1 `APPROVED_FOR_BOUNDED_IMPLEMENTATION`（PR #87 冻结设计，v4）。
**本文档性质**：实现说明 + 代码审查材料。不重新讨论研究方向，不引入新算法分支。
**边界**：无 GPU Native Run、无新 Workload/Repeats/参数网格、无 A2 改造、无 `r_i`、无逐候选 λ_i、无学习模型。

---

## 1. 冻结算法与实现位置

$$L(X)\;=\;q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X},\qquad S_X=m_X-d_{\min}(X)+1$$

| 符号 | 实现来源 | 说明 |
|---|---|---|
| `q_X` | `a1_entry.reuse_proxy(deadline, timestamp, tau)` | **直接复用冻结实现**，未重定义，未改 τ |
| `prefill_X` | `DecisionCandidateRow.prefill_reload_seconds` | 决策时已有 |
| `m_X` | `ChainDepthProof.chain_length` | 观测时刻的完整链长，**不是存活块数** |
| `V_X` | `predict_victims(...)` | 冻结 Eligibility + Native LRU Rank 推算 |
| `d_min(X)` | `min(DepthResolution.depths)` | 受害块中最浅的**原始**深度 |
| `S_X` | `m_X - d_min + 1` | 潜在失效后缀长度 |

不简化为 `q×S`：代码中 `score = reuse_proxy * prefill * suffix / m` 与上式逐项对应，
回归测试显式断言该等式（`test_published_geometry_is_reproduced` 第二段）。

### 文件与调用路径

| 文件 | 作用 |
|---|---|
| `src/kvopt/costaware/entry_depth.py` | `ChainDepthProof` / `DepthQuery` / `DepthStatus` / `ChainDepthIndex` / `index_from_events` |
| `src/kvopt/costaware/a3_suffix.py` | `predict_victims` / `CandidateCostAudit` / `A3SuffixCostStrategy` / `replay_with_audit` / `build_strategy` |

调用路径（离线与未来 Native 共用同一条）：

```
ReplayState / DecisionSnapshot          (冻结)
        │
        ├─ A1EntryCostAwareStrategy.select(...)      ← 冻结阶梯，先跑
        │        └─ 返回 branch + 逐候选 q/N_i + 非 Step2 的选择
        │
        └─ A3SuffixCostStrategy.select(...)          ← 仅替换 Step 2 排序键
                 ├─ Step 1 / 3 / 4 / 5 → 原样返回冻结 A1 的结果
                 └─ Step 2 → predict_victims + ChainDepthIndex + L(X)
                          └─ 任一候选不可评分 → 整步回落冻结 A1（带原因码）
```

**未改动任何冻结文件**：`a1_entry.py`、`replay.py`、`rules.py`、`continuum/*`、`costaware/a2_*` 全部零修改。
新行为只能通过 `build_strategy("A3_entry_suffix_cost_proxy", ...)` 显式开启；
传入其它 id 直接 `ValueError`。

---

## 2. 与冻结 Branch Ladder 的对应关系

| Step | 冻结条件 | 本实现 | 代码位置 |
|---|---|---|---|
| **1** | `need <= 0` | 完全冻结 A1 | `a3_suffix.py` `select()` 早返回 |
| **2** | 存在 `N_i >= need` | **替换排序键**为 `(L, deadline, identity)` | `select()` → `_audit` / `_order` |
| **3** | 不足量，按 per-unit | 完全冻结 A1 | 早返回，`step_for_branch(BRANCH_PER_UNIT)` |
| **4** | 两两 lookahead | 完全冻结 A1 | 早返回，`step_for_branch(BRANCH_PAIR_LOOKAHEAD)` |
| **5** | deadline fallback | 完全冻结 A1 | 早返回，`step_for_branch(BRANCH_DEADLINE_FALLBACK)` |

保证方式不是"照着写一遍"，而是**持有 `A1EntryCostAwareStrategy` 实例并调用它**：
`need`、`N_i`、候选合法性、Tie-break、Native Eligibility 全部来自冻结对象，
`q` 也直接取冻结对象算出的 `reuse_proxy`，因此 τ 不可能漂移。

### `deficit` 的口径

设计文档写作 `deficit = max(0, need − |Tier 1|)`，其中 `need` 是 `required_blocks`。
冻结阶梯里的 `need = target − eligible` **已经**扣掉了 Tier 1，所以两者是同一个量。
实现直接使用 `selection.need`，并在每次迭代重算（阶梯本就每步重排）。

### `V_X` 与 `N_i` 的区别（硬性）

`N_i` 是"释放后可回收的块数"，`|V_X|` 是 `min(deficit, N_i)`。实现中
`predict_victims` 显式按 rank 排序后截断到 `deficit`，`CandidateCostAudit.victim_count`
报告的是截断后的数量。测试 `test_predict_victims_truncates_at_deficit_not_at_relief`
专门锁死这一点：`N_i = 4`、`deficit = 2` 时受害者是 2 个。

---

## 3. ChainDepthProof 的生命周期、身份与时效

### 3.1 生命周期

```
观察链 (VLLM_PREFIX_SNAPSHOT / 未来 Native 快照)
        │  block_ids 按深度升序 + ordered_native_cache_keys 逐位对齐 + native_hash_process_id
        ▼
ChainDepthProof.from_observation(...)      depths := 1..n  ← 唯一一次由位置得到深度
        │
        ▼
ChainDepthIndex.observe(proof)             append-only，按 observation_index 递增
        │
        ▼
latest_before(chain_id, decision_index)    ← 决策前最近一次有效观测
        │
        ▼
DepthQuery(pin expected_observation_index) ← 校验身份/顺序/时效/内容
        │
        ▼
DepthResolution(depths, failures)          failures 非空 ⇒ 整次决策 Fail Closed
```

**深度只在观测时刻由位置得到一次**。之后任何查询都不读 `RetentionEntrySnapshot.block_ids`
的下标——那正是设计文档 RC5 撤回的错误前提。

### 3.2 为什么不能用压缩后的下标

`retention.py::observe_eviction` 与 `::reconcile_entry_evictions` 用
`tuple(b for b in ... if ...)` 直接压缩 `block_ids`，于是

1. 内部逐出后剩余块的下标 ≠ 原始深度（系统性低估 `d_min`），
2. `len(block_ids)` 是存活块数而非 `m`（系统性低估 `S`）。

两者都让 `S` 变小，即让"深度信息缺失"的候选看起来更便宜。实现中 `m` 只来自
`proof.chain_length`，`d_min` 只来自 `resolution.depths`。

### 3.3 校验顺序与状态码

| 序 | 检查 | 失败状态 |
|---|---|---|
| 1 | 查询链身份 == 证明链身份 | `WRONG_CHAIN` |
| 2 | 查询进程 == 证明进程 | `WRONG_PROCESS` |
| 3 | `observation_index < decision_index` | `FUTURE_OBSERVATION` |
| 4 | 证明是该链**最近一次**观测 | `SUPERSEDED` |
| 5 | 同钟域时 `decision_time >= observed_at` | `FUTURE_OBSERVATION` |
| 6 | 同钟域时 `decision_time − observed_at <= max_age` | `STALE_OBSERVATION` |
| 7 | 证明具备内容标识 | `IDENTITY_UNVERIFIED` |
| 8 | `NATIVE_LIVE` 模式下已提供 live 内容标识 | `LIVE_IDENTITY_REQUIRED` |
| 9 | 槽位存在 / 内容一致 | `UNKNOWN_BLOCK` / `CONTENT_MISMATCH` |
| — | 全通过 | `OK` + 真实深度 |

只有 `OK` 返回深度。每一步都返回**单一原因码**，回落日志可以照抄，不需要二次推断。

### 3.4 `max_age` 的定位（明确不越界）

`max_age` 是**辅助时效上限**，不是有效性主判据：

- **主判据（钟域无关）**：`observation_index < decision_index` 且该证明是这条链的**最近**
  观测。这两条共同保证"证明描述的就是当下的那条链"。
- **辅助判据（钟域相关）**：仅在 `decision_clock_domain == proof.clock_domain` 时比较时间。

归档里 `VLLM_PREFIX_SNAPSHOT` 是 `system_monotonic`、`FORCED_RELEASE_DECISION` 是
`continuum_pressure`，两者相减无意义。因此**跨钟域时不使用时间比较**，时效完全由
顺序 + 最近性承担；这一点由 `test_cross_clock_domain_does_not_apply_the_auxiliary_age_check`
显式锁死（若误用时间比较，快照时间 49,949,695 与决策时间 158.4 会把所有证明判成 stale）。

### 3.5 Block ID 复用与验证模式（RC1）

复用可能伴随**新的链身份**（冻结 prefix id 内嵌 root native hash）或**该链的新观测**：
前者被 `WRONG_CHAIN` 拦住，后者被 `SUPERSEDED` 拦住。

但还有第三类情况：**block id 被回收复用了，而旧链再也不会产生新快照。**
此时既没有新链身份、也没有新观测，`SUPERSEDED` 永远不会触发，
旧 `Proof` 完全可能被错误接受——这正是 M1 RC1 指出的缺口。

因此深度查询分为两种**不可互换**的验证模式（`DepthVerificationMode`）：

| 模式 | 深度依据 | `content_verified` | 适用范围 |
|---|---|---|---|
| `HISTORICAL_REPLAY` | Proof 记录的内容标识 | **恒为 `False`** | 离线归档分析 |
| `NATIVE_LIVE` | **必须**由调用方提供当前内容标识 | 逐块比对通过才为 `True` | 真实 Native 评分 |

`NATIVE_LIVE` 下若未提供 live 内容标识，返回 `LIVE_IDENTITY_REQUIRED`
（`FAIL_LIVE_IDENTITY_MISSING`），**不得**回退到 Proof 记录值。

> **措辞纪律**：`HISTORICAL_REPLAY` 的“可用”仅意味着“可用于重放”，
> **不**意味着已经完成 Native Content 验证。任何把离线回放结果描述为
> “已验证当前内容”的陈述都不成立。

### 3.6 真实 Native 生命周期的关系

`ChainDepthProof` / `ChainDepthIndex` 是**只读元数据**：不改 `BlockPool`、
`FreeKVCacheBlockQueue`、ref count、hash cleanup、scheduler ownership，也不参与任何
逐出决策。它们只回答"这个块在链里的原始深度是多少"。

---

## 4. 逐候选评分审计

`CandidateCostAudit` 字段（与授权书逐项对应）：
`need / deficit / new_blocks(N) / victim_block_ids(V_X) / victim_depths / chain_length(m) /
d_min / suffix_blocks(S) / reuse_proxy(q) / prefill_reload_seconds / score(L) /
evidence / content_verified / selected / fallback_reason`

`A3SuffixSelection` 额外记录 `step`、`branch`、`a1_key`、`a1_branch`、`fell_back`、
`fallback_reason`，因此"这一步是不是被替换过"与"回落到哪里"都可复算。

`replay_with_audit(...)` 保留**每一次释放迭代**的审计，满足"评分与选择可离线复算"。

### 五类证据必须分开

`VictimEvidence` 枚举明确标注当前记录属于哪一类，实现只产出 `PREDICTED`：

| 类别 | 本实现 |
|---|---|
| `PREDICTED` 预测受害集 | ✅ 唯一产出 |
| `NATIVE_SELECTION` 实际 SelectionPlan | ❌ 不在本层 |
| `PHYSICAL_EVICTION` 已确认物理淘汰 | ❌ 不在本层 |
| `CONTENT_IDENTITY` 内容身份 | ⚠️ 仅用于校验深度，不作为归属 |
| `DOWNSTREAM_RECOMPUTE` | ❌ 不在本层 |

`forecast ≠ eviction`：`V_X` 是预测，不是 `SelectionPlan`，不是物理逐出，不是内容归属，
也不是重算量。任何把这些互相冒充的结论都不成立。

---

## 5. Phase 2H 六次决策离线回归

`tests/test_phase2i_snapshot_regression.py`（归档缺失时 skip）。

| idx | 选中 Entry | `m` | `d_min` | `S` | `L` |
|---|---:|---:|---:|---:|---:|
| 2170 | django | 368 | 336 | 33 | 0.0053411815 |
| 4244 | django | 440 | 391 | 50 | 0.018032459 |
| 7305 | django | 476 | 421 | 56 | 0.022321175 |
| 2166 | pytest | 491 | 486 | 6 | 0.00012379131 |
| 4384 | pytest | 597 | 581 | 17 | 0.0052718216 |
| 10388 | pytest | 647 | 631 | 17 | 0.0058384308 |
| 10388 | pylint（被否决） | 799 | 451 | 349 | 0.13791765 |

结论：

- **全部候选均可评分，0 次回落**（`test_every_candidate_is_scorable_without_fallback`）：
  真实归档走的是评分路径，不是 fallback 路径；
- 与 **A0（deadline 规则）6/6 一致**（`test_new_rule_reproduces_a0_on_all_six_decisions`）；
- 与 **冻结 A1 仅在 `idx=10388` 分歧**（`test_new_rule_reproduces_frozen_a1_except_at_the_known_divergence`
  断言分歧集合恰为 `[10388]`）；
- 上述 `L` 与冻结设计文档公布的数值一致，`rel=1e-6`；
- 同时断言 `score == q * prefill * S / m`，防止退化成 `q*S`。

**证据限制（承接 RC9）**：HR02 的 `CONTROLLED_REPLAY_PRESSURE_COMPLETED` 计数器链不自洽
（`before`/`after` 不接续），本回归**不按 barrier 分组**、不使用未通过配对校验的数据
宣称跨臂因果关系；所有断言只用决策级事实。

**证据限制（RC1 新增）**：本回归全部在 `HISTORICAL_REPLAY` 模式下运行，
深度只来自历史 `Proof`，**没有**当前内容标识。因此：

- 每一行 `content_verified` 均为 `False`（`test_offline_regression_does_not_claim_native_content_verification`
  逐行断言），**不得**把这批结果描述为“已完成 Native Content 验证”；
- 同一份归档切到 `NATIVE_LIVE` 且不提供 live 内容标识时，Step 2 **全部回落**
  （`test_native_mode_falls_back_on_the_same_archive`），说明“忘记传当前内容”会退化为冻结 A1，
  而不是默默信任历史。

---

## 6. 新算法与 A0 的独立选择（合成案例）

`test_new_rule_and_a0_make_recomputably_different_choices`：

| 项 | Entry `aaa` | Entry `bbb` |
|---|---|---|
| deadline | 120.0 | 120.0 |
| prefill | 1.0 | 1.0 |
| 链 | `(1,2,3,4,5,101..105)` | `(201,202,203,6,7,8,9)` |
| `m` | 10 | 7 |
| `V_X` | `{1,2,3,4}` → 深度 1..4 | `{6,7,8,9}` → 深度 4..7 |
| `d_min` | 1 | 4 |
| `S` | 10 | 4 |
| `q` | `sigmoid((120−100)/30)` | 相同 |
| `L` | `q·10/10 = q` | `q·4/7 ≈ 0.571q` |

- **A0 选 `aaa`**：deadline 相同，次级键 `min native rank` 为 0 而 `bbb` 为 5；
- **本算法选 `bbb`**：`L` 更小；
- 两者 `q` 完全相同，因此分歧**完全来自后缀几何**，与 `q` 无关。

该测试**只证明算法具有独立决策逻辑**，不作性能改善证据。

---

## 7. Fallback 覆盖与已知不可观测边界

### 7.1 Fallback 原因码

| 原因码 | 触发条件 | 测试 |
|---|---|---|
| `NO_OBSERVATION` | 该链在决策前无有效观测 | `test_fallback_records_a_reason_for_every_unscorable_candidate` |
| `DEPTH_UNAVAILABLE:<block>:<status>` | 任一受害者深度不可解析，状态原样携带 | `test_one_unscorable_candidate_falls_back_the_whole_step_two`、`test_process_mismatch_falls_back_...` |
| `PREFILL_MISSING` | `prefill` 缺失 / 非数值 / 非有限 / <= 0 | `test_unusable_prefill_becomes_a_fallback_not_an_exception`（7 组参数） |
| `LIVE_IDENTITY_MISSING` | `NATIVE_LIVE` 模式未提供 live 内容标识 | `test_native_scoring_without_live_content_hashes_falls_back` |
| `VICTIM_SHORTFALL` | 可用受害者少于 `deficit` | 代码分支（Step 2 下不可达，防御性） |
| `INVALID_GEOMETRY` | `m <= 0` / `d_min < 1` / `S` 越界 | 代码分支（防御性） |
| `STEP2_UNSCORABLE:...` | 决策级：Step 2 整体回落 | 同上多条 |

**`PREFILL_MISSING` 的防御性**：`math.isfinite(None)` 与 `math.isfinite("1.0")` 都会抛
`TypeError`。谓词 `_usable_prefill` 先做类型判定再算 `isfinite`，并把 `bool` 显式排除
（`isinstance(True, int)` 为真，若不排除会把一个标志位当成 `1.0`）。代价代理在缺失输入上抛异常
比回落更糟，因此该路径**不得抛异常**。

**回落范围是整次 Step 2 决策**，不是个别候选：只要有一个候选不可评分，全部候选都不参与
新排序，直接采用冻结 A1 在该步的选择。理由是不可部分评分——少算受害者会得到偏小的 `S`，
让"深度未知"的候选占便宜。

### 7.2 已知不可观测边界（实现层）

| 边界 | 说明 |
|---|---|
| 内容变化检测依赖"新观测" | 归档中每条链的 `prefix_id` 唯一，每个链只有 1 条快照；因此离线回归里 `CONTENT_MISMATCH` 不会自然出现，它由合成测试覆盖 |
| **离线无法验证当前内容** | `HISTORICAL_REPLAY` 只比对历史标识，`content_verified` 恒为 `False`；真实校验必须先由 M6 提供 live 内容标识并切到 `NATIVE_LIVE` |
| 无逐回合物理逐出归属 | 本层只产出 `PREDICTED`；物理逐出与内容归属分别属于 L2/L3，不在本层 |
| 无 `r_i`、无重算量 | `L` 是 cost proxy，不是实测重算时间 |
| 跨钟域无时效判断 | 只能靠顺序 + 最近性，见 §3.4 |
| Step 5 不可达 | 与冻结引擎一致：所有候选都不拥有队列块时，所有块已 eligible，实际走 Step 1 |

---

## 8. 后续 M6 Native Integration 所需接口与观测字段

### 8.1 需要 M6 提供的输入

| 字段 | 用途 | 现状 |
|---|---|---|
| `native_hash_process_id`（当前进程） | `DepthQuery` 进程身份；`NATIVE_LIVE` 下 **必填** | 归档已有，需在决策点透传 |
| chain 观测：`block_ids`（深度序）+ `ordered_native_cache_keys` + `program_id/prefix_id` + `event_index` | 构造 `ChainDepthProof` | `VLLM_PREFIX_SNAPSHOT` 已具备 |
| **决策时刻每个受害块的当前内容标识** | `NATIVE_LIVE` 的内容校验（RC1） | **需新增**（M6 提供） |
| `DecisionSnapshot.decision_event_index` / `timestamp` | 顺序与时效 | 已有 |
| 决策钟域 | 决定是否做时间比较 | **需新增透传**（当前只能离线指定） |
| `prefill_reload_seconds` | 代价量纲 | 已有 |

### 8.2 M6 调用契约（RC1）

```python
strategy = build_strategy(
    "A3_entry_suffix_cost_proxy",
    depth_index=index,
    native_hash_process_id=current_native_process_id,   # 必填，不得留空
    verification_mode=DepthVerificationMode.NATIVE_LIVE, # 显式声明为真实评分
    content_hashes=current_content_hashes,               # 每个受害块的当前内容标识
    decision_clock_domain=snapshot_clock_domain,
)
```

三条硬约束：

1. `NATIVE_LIVE` 而 `native_hash_process_id` 为空 ⇒ **构造期 `ValueError`**，
   （不允许回用 Proof 自身的进程 id，那等于拿一个值跟自己比）
2. `NATIVE_LIVE` 而 `content_hashes` 为空 ⇒ 所有候选 `LIVE_IDENTITY_MISSING`
   ⇒ 整次 Step 2 回落冻结 A1
3. `content_hashes` 中缺失某受害者 ⇒ 该块 `LIVE_IDENTITY_REQUIRED` ⇒ 整次 Step 2 回落

### 8.3 建议新增的观测字段

| 字段 | 理由 |
|---|---|
| 决策点 `decision_clock_domain` | 让 `max_age` 可判定，目前只能靠配置声明 |
| **决策点当前内容标识（block id → content key）** | `NATIVE_LIVE` 必需；没有它就只能走离线回放 |
| `last_selected_block_ids` **逐压力回合**写入 | RC9 遗留项：现在同 run 内规模恒定，导致 M3-1 只 1/6 可验证 |
| 逐回合 forced-release 计数器自洽性 | HR02 的 `before`/`after` 不接续，需先修才能做屏障级跨臂对照 |

### 8.4 决策日志建议字段

`per-candidate:` `program_id / prefix_id / need / deficit / N / V_X / m / d_min / S / q /
prefill / L / content_verified / selected`；`per-decision:` `step / branch / a1_key /
fell_back / fallback_reason`。与 `CandidateCostAudit` / `A3SuffixSelection` 一一对应，便于离线复算。

**`content_verified` 必须写入日志**：它是区分“离线回放”与“Native 内容验证”的唯一标识，
不得用 `selected` 或 `score is not None` 代替。

### 8.5 M6 不得改变的部分

`ChainDepthProof` / `ChainDepthIndex` 必须保持只读；不得由它们触发或否决逐出，
不得修改 `BlockPool`、free queue、ref count、hash cleanup、scheduler ownership
或物理逐出生命周期。

---

## 9. 测试清单

| 文件 | 覆盖 | 用例数 |
|---|---|---|
| `tests/test_costaware_entry_depth.py` | B：深度不漂移、链长、回收/内容、跨链/跨进程、未来/过期/边界、跨钟域、superseded、内容缺失、未知块、索引与归档构造；**RC1：验证模式与 live 内容标识** | 26 |
| `tests/test_costaware_a3_suffix.py` | A：Steps 1/3/4/5 与冻结 A1 一致、各类 Fallback、Step 2 公式与 Tie-break；C：受害者预测；D：独立选择；**RC1：Native 模式契约与 prefill 防御** | 40 |
| `tests/test_phase2i_snapshot_regression.py` | E：六次决策离线回归；**RC1：离线不宣称内容验证、Native 模式必回落** | 8 |

运行：

```bash
python -m pytest tests/test_costaware_entry_depth.py tests/test_costaware_a3_suffix.py \
                 tests/test_phase2i_snapshot_regression.py -q
```

### 冻结策略未受影响

`A1EntryCostAwareStrategy`、`ExecutedP1BStrategy`、A0/A2 选择器与 `replay_decision`
均未修改；`a1_entry.py` / `replay.py` / `a2_*` 在本 PR 中零 diff。
