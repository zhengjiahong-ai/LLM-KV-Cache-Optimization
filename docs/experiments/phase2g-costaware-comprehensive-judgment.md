# Phase 2G Cost-Aware —— 综合研究判断报告 v3（RC1–RC7 + RC-A–RC-D）

**输入**：PR #82 / v10 Evidence Archive（54/54 runs），PR #80（M2 四方向）。
**修订依据**：M1 对 PR #83 的 RC1–RC7，以及对 v2（HEAD `df64445`）的 RC-A–RC-D。
**授权边界**：仅离线只读分析。未改 A0/A1/A2，未覆盖原始归档，未启动 Native。
**本轮不提出最终研究裁定，也不申请执行任何 Campaign。**

分析脚本（已入库）：`scripts/probes/entry_costaware_audit/`
运行前提：归档解压到 `local/continuum-native-cost-aware-bounded-v10-final-evidence/`（`local/` 被 gitignore）。

---

## 0. 对 PR #83 的更正（先列错误，再给结论）

上一版有三处**实质错误**，均由 M1 指出或本轮复核发现：

| # | PR #83 的说法 | 更正 | 依据 |
|---|---|---|---|
| 1 | `native_lru_victims` 是 `legal[:N]` 的回显，"独立参照不存在" | **错误。** 它由 `NativeLRUAdapter().select_victims()` 独立按 `lru_rank` 排序产生（`a2_native.py:543`、`adapter.py`）。两者相同是因为**候选本身按 rank 升序传入**，是一个经验事实而非构造性同义反复 | 源码 + 601/601 |
| 2 | 复用历史"全部为零"，"该 workload 永不产生历史" | **错误。** 历史**确实被产生与记录**（`ServerGapHistory.record`，约 10 条/run）。为零的是观测事件里暴露的 **eta / queue-delay** 计数器，我误当成全部历史。真正原因是**冷启动阈值 100 在 12 请求/run 的窗口内不可达**，且 history 是 per-process，不跨 run 累积 | §RC4 |
| 3 | 翻转判据 `q_ratio < N_ratio` 称为"充要条件" | **过强。** 那是 `λ=1` / `N≫need` 的极限形式。精确判据用 `a_i = λN_i + (1−λ)need` | §RC5 |

另外三处需要收窄：

- `ttl = 0` 属**设计内截断**（`μ = 1 s` 参考尺度），不是公式缺陷（§RC3）；
- 单次运行不能证明稳定退化（保留）；`physical_eviction_divergence` 仍建议弃用；
- 归档存在**具体的一处清单失配**，且 M1 公布的 SHA 在归档内**不存在**（§RC7）。

### 0.2 本轮（RC-A–RC-D）再更正五处方法错误

| # | 上一版（v2）的做法 | 问题 | 本轮处理 |
|---|---|---|---|
| 4 | 用 `step_costs` 区分 S4/S5 | 该字段是 greedy **每次选中块**的边际代价，一次选择一个值，不是同一时刻的候选成本分布 | 重做为"每步全部候选边际代价"（§2） |
| 5 | 用 `select_victims()` 的结果称"穷举"；重建时丢弃无 membership 的合法块 | 该函数受预算约束；丢块会同时改变 need 与 rank 口径 | 重建完整 legal set，Greedy / Exact / 超预算三态分开（§6.1） |
| 6 | 把"链内 deepest-first"当成"不可能偏离 LRU"的充分条件 | 多链不同 q 时该条件不成立，仓库已有反例测试 | 撤回，并在脚本内复现反例（§6.1） |
| 7 | 未审计既有 W1-A warm-start 路径 | 把冷启动归因于"没有历史"，但仓库已有一条 443 条历史的注入路径 | 新增设计审计（§4-补） |
| 8 | 365/366 匹配被读作"完整性验证" | 一个失配就是失配 | 保留 `SOURCE-UNVERIFIED` 标记（§7） |

---

## 1. RC1 —— A2 与 Native-LRU 的正确解释

### 1.1 代码事实

`src/kvopt/costaware/a2_native.py::A2NativeBlockAdapter.select_victims`：

```python
native = tuple(NativeLRUAdapter().select_victims(candidates, context))   # 独立执行
...
else:
    selected = tuple(outcome.selection.blocks)                            # 代价路径
audit = A2NativeDecisionAudit(
    legal_block_ids=tuple(candidate.block_id for candidate in candidates),  # 传入顺序
    native_lru_victims=native,
    selected_victims=selected,
    ...
)
```

`src/kvopt/runtime/vllm/adapter.py::NativeLRUAdapter`：

```python
ordered = sorted(candidates, key=lambda candidate: candidate.lru_rank)
return [candidate.block_id for candidate in ordered[: context.required_blocks]]
```

因此 `native_lru_victims` **是一个独立计算的参照**，不是回显。

### 1.2 五个必须分开的量

| 层 | 量 | 本归档实测 |
|---|---|---|
| L1 | A2 vs **同 Legal Set 上的 Native Rank-LRU** | `selected == native` **601 / 601** |
| L2 | A2 vs **真正的 A0 Tier-aware 选择** | **无法可靠判定**（见 §1.4） |
| L3 | A2 是否**实际使用**代价打分 | **434 / 601 是**（`selector=incremental_greedy`, `cost_known=true`）；167 回退 |
| L4 | 代价打分是否**改变**最终 victim | **0 / 601** |
| L5 | 最终 victim 是否被 Native **物理执行** | 未验证（无逐块物理归因；`claim_boundary` 明确为 proxy 选择） |

### 1.3 601/601 一致的真正原因

`NativeLRUAdapter` 返回的是"按 `lru_rank` 升序的前 N 个"。它返回的序列恰好等于
`legal_block_ids[:N]`，**说明传入的候选序列本身已按 `lru_rank` 升序排列**。
这是一个关于 vLLM 候选传递顺序的**经验事实**，不是定义上的同一。

对 L3/L4 的含义是实质性的：

> 在 434 个决策中，**代价打分真实执行了**，输入通过契约校验，
> 而它产出的集合**恰好与 rank-LRU 相同**。
> 这不是"没有参照"，而是"代价模型在有输入、有执行的情况下没有产生差异"。

### 1.4 L2 无法判定的原因（保留上一版的这条限制）

要比较 A2 的 `legal[:N]` 与 A0 的 `(tier, rank)` 序，需要 legal 列表的排序依据。
归档没有记录该依据；队列快照只在 `FORCED_RELEASE_DECISION` 事件中出现：

```text
块决策总数                              601
可定位队列快照                          229
legal 中含快照里已不存在的块（快照过期）   151
严格可比（全部 legal 块都在快照中）          78
其中 legal 顺序 == (tier, rank)            71
其中 legal 顺序 != (tier, rank)             7
```

那 7 例呈 rank **降序**（如 202, 201, 200），与"快照过期"一致，不能当作真实排序依据。

> **结论**：L1 是确定的（601/601 相同），L2 **不可判定**。
> 因此"A2 与 A0 差异的来源"在本归档中**不能归因**，只能标 `NOT_ATTRIBUTABLE`。

---

## 2. RC-A —— A2 的有效决策机会（重做，旧 S4/S5 撤回）

### 2.1 为什么旧分类无效

上一版用 `step_costs` 区分 S4/S5。这是错的。`a2_selector.greedy_select` 里
`step_costs.append(best_key[0])` 记录的是**每次被选中块的边际代价**，
一次选择一项。它描述的是"选了什么"，不是"当时所有候选各是多少"。
用一个单值序列判断"候选之间有没有差异"，在候选数为几百时结论与事实无关。

新分类改为：从 payload 重建**完整 legal set**（含 hashless），
再按 `greedy_select` 的同一规则逐步计算**每一步全部剩余候选**的边际代价。

重建保真度：

| 检查 | 结果 |
|---|---|
| `identity_state_counts` 逐决策复现 | **601 / 601** |
| `native_lru_victims == legal_block_ids[:need]` | **601 / 601** |
| 保留的 hashless 合法候选 | 441 994 |
| 标记为内容缺口的未验证候选 | 158 483 |
| 可比决策的 legal 规模 | 中位 1029，最大 2047 |

rank 不是推断出来的：`VLLMEvictionBridge.build_candidates` 用
`lru_rank = enumerate(blocks)` 给候选编号并把该列表原样传入，
所以 `legal_block_ids` 的下标就是原生 rank。上表 601/601 是对这一事实的**检查**，
不是对它的假设。

### 2.2 新分类（互斥）

| 类 | 定义 | 计数 | 占比 |
|---|---|---:|---:|
| F 未打分 | 回退，或重建发现内容缺口 | 167 | 27.8% |
| N 无自由度 | need ≤ 0，或 need ≥ legal 数 | 0 | 0% |
| D 无信号 | 每一步全部候选的边际代价都相同 | 368 | 61.2% |
| L 有信号但 Greedy 集合不变 | 边际代价有差异，Greedy 集合 = rank 集合；Exact 最优性未定 | 66 | 11.0% |
| **C 有信号且 Greedy 集合改变** | Greedy 集合 ≠ rank 集合 | **0** | **0%** |

第一步诊断（434 个可比决策）：

| 第一步条件 | 计数 |
|---|---:|
| 最冷候选代价为 0 | 386 |
| 最冷候选即最便宜（代价为正） | 48 |
| **更暖候选更便宜**（偏离的必要起点） | **0** |

参与比较的候选边际代价确实有区分度：可比决策里，单步出现的不同取值数
从 149 到 1663 个不等（368 个无信号决策为 1 个）。所以"没有偏离"不是
"没有信号"，而是**本轮有信号的决策未改变 Greedy 选择**；66 个超预算决策的 Exact 最优集合仍不可判定。

### 2.3 精确最优性：不能声称"穷举过"

| 状态 | 计数 | 说明 |
|---|---:|---|
| 零损失下界即可证明 rank 集最优 | 368 | 损失非负，且 rank 集损失为 0 |
| 枚举得到 exact | **0** | `C(1029, need)` 远超任何可执行预算 |
| 未定（超预算） | 66 | 只能说 greedy 集合 = rank 集合 |

引擎自身也从未跑过穷举：`search_truncated = true` 出现在 **434 / 434**，
且记录的 `selected_victims` 与 greedy 结果 **434 / 434** 一致。

> 正确表述：**Greedy 从不偏离（434/434）；Exact 在本几何下不可执行——
> 368 个决策可由零损失下界证明 rank 集最优，其余 66 个未定。**
> 上一版"0/66 差异"把不可执行的路径当成穷举结论，本轮撤回。


---

## 3. RC3 —— TTL 与模型尺度退化

### 3.1 公式的设计尺度

`docs/archive/phase1b-continuum/phase1b-continuum-implementation-decisions.md` §1.4：

```text
T_default = max(0, mu * ln(RepresentativePrefillReload / mu)),   mu = 1 second
```

`mu = 1 s` 是**参考时间尺度**：只有当代表性 prefill-reload **大于 1 秒**时 TTL 才为正。

### 3.2 本轮的实测输入落在截断区

profile（`prefill-reload-profile-interpreted.json`，`status: complete`）：

| token | effective_cost_seconds | 状态 |
|---:|---:|---|
| 1024 | **0.0** | `INDISTINGUISHABLE_FROM_ZERO` |
| 4096 | 0.303 | `RAW_POSITIVE_MEASUREMENT` |
| 8192 | 0.454 | 同上 |
| 12288 | 0.639 | 同上 |
| **16384** | **0.986** | 同上（≈ μ） |
| 24576 | 1.323 | 同上（> μ） |
| 32256 | 1.937 | 同上 |

决策时观测到的 `prefill_reload_seconds`：**0.0095 – 0.1711 s**，全部 < μ = 1 s；但这不是逐条计算 Cold-start TTL 的输入。

```text
Cold-start TTL = Runtime 初始化时的一次性常数 default_ttl_seconds。
composition.py 首先查询代表性 256-token Profile；该点不在本轮网格内，
因此回退到 default_ttl_reference() 的最小正值点：4096 tokens → 0.303 s。
max(0, ln(0.303)) = 0，因此本轮 Cold-start 默认 TTL 为 0。
实测：ttl_seconds == 0 在 139 / 139 条候选记录上成立。
```

同时还发现：**profile 1024-token 点本身已被判为"与零不可区分"**，
且 `ranking_sensitivity_status = INCONCLUSIVE_COST_ORDERING`。

### 3.3 机制边界：模型尺度与启动参考点

本轮 1.5B Profile 在**启动默认 TTL 实际使用的参考点**上低于 `μ = 1 s`，
因此默认 TTL 被截断为 0。决策时较小的 `prefill_reload_seconds` 反映本轮成本尺度，
却**不是**每次 Cold-start TTL 的独立计算依据。

Profile 的较长输入区间确有超过 `μ` 的测量值，但仅延长某次请求到 16k tokens 以上，
并不能改变 Runtime 启动时已经确定的默认 TTL 常数。不能将此归因为通用的 1.5B 模型必然失效；
它是**本轮冻结 Profile、代表性参考点和 μ 尺度**组合下的现象。

### 3.4 一个更重要的、此前未指出的机制

在 `COLD_START` 分支中，`ttl_seconds = ttl_input.default_ttl_seconds`，
而这个值是**启动时确定的常数**（`runtime.py` 构造参数），对所有请求相同。

于是

$$\text{deadline}_c-t=\underbrace{\text{ttl}_c}_{\text{同一常数}}-\text{elapsed}_c$$

**只要 TTL 是常数，$q$ 的排序就只由 elapsed 决定，与常数取值无关。**
所以：

- `ttl = 0` 影响的是 **$q$ 的量级**（变成 ~1e-2…1e-9），不是**序**；
- $q$ 与 recency 同序的根因是 **cold-start 使用常数 TTL**，而不是截断本身。

### 3.5 哪些结论受 TTL 退化条件限制

| 结论 | 是否依赖 TTL 退化 |
|---|---|
| `ttl = 0`（139/139） | 是（`μ` 尺度 + 1.5B） |
| $q$ 序 == deadline 序 | **是**（cold-start 常数 TTL） |
| A1 仅在 `q_ratio < a_ratio` 时偏离 | **否**（纯代数，对任意正 $q$ 成立） |
| A1 偏离的一次是退化（g05） | **否**（该几何的 $q$ 差来自 elapsed，属该负载事实） |
| A2 greedy 集 == rank-LRU（434/434） | **否**（与 TTL 无关；偏离的必要条件是“更暖但更便宜”的候选，本归档未出现） |
| 复用信号无判别力 | **是**（cold-start 分支根本不使用 gap 样本） |

---

## 4. RC4 —— 复用历史全零的根因（更正）

### 4.1 上一版的错误

我把 `TTL_HISTORY_INPUT_OBSERVED` 的四个字段（`eta_history_sample_count`、
`queue_delay_history_sample_count`、`queue_delay_history_recent_sample_count`、
`eta_completed_program_count`）当成了"全部历史"，得出"历史全零"。

**这四个字段里没有 server-gap 或 external-tool 的样本计数。** 该观测事件根本
不暴露它们（`runtime.py` 中 `TTL_HISTORY_INPUT_OBSERVED` 的 payload 只有这些字段）。

### 4.2 实际的产生与消费链路

| 环节 | 事实 |
|---|---|
| 产生 | `ServerGapHistory.record` 在 `_handle_request_arrived` 触发，前提是该 program 有 `_pending_server_gaps`（在每次 TTL 决策时写入） |
| 写入 | 每次"上一轮结束 → 下一轮到达"记一条 gap |
| 消费 | `runtime.py:365` `self.server_gap_history.global_samples()`；`:367` `samples_for_tool(...)` → 传给 `TTLInput` |
| 阈值 | `_select_history`：`len(global_samples) <= duration_history_threshold (100)` → **COLD_START** |
| 生命周期 | history 实例在 per-run runtime 内；每个 run 新进程，**不跨 run 累积** |
| 右删失 | 102 个 `W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED`，说明窗口在 session 结束前被截断 |

### 4.3 每 run 能产生多少条

该 run 有 **12** 个 `REQUEST_ARRIVED`、2 个 `PROGRAM_STARTED`、11 个 `TURN_FINISHED`。
每个 program 的首次到达无 pending gap，其余每次到达记一条：

```text
估计上界 = 12 - 2 = 10 条 / run
阈值     = 100
可用样本 = 10 << 100  ⇒ _select_history 恒为 COLD_START
```

### 4.4 根因判定

| 候选原因 | 判定 |
|---|---|
| Workload 天然不产生历史 | **否**（每 run 约 10 条） |
| Runtime 未记录 | **否**（`record` 路径存在且被到达事件触发） |
| **生命周期错位 / 样本量不足** | **是，主因**：阈值 100 vs 每 run ≈10 条；且 per-process 不累积 |
| 决策时读取错误 | **否**（`global_samples()` / `samples_for_tool()` 均被调用） |
| 右删失 | 加剧因素：窗口被截断，无法观察"是否返回" |

> **结论**：历史不是"不存在"，而是**样本量级差一个数量级**，
> 且因为没有跨 run 的状态，重复运行同一 workload **不会**累积样本。
> 上一版"该 workload 永不产生历史"的说法**撤回**。

### 4.5 一个可观测性缺陷（需记录）

归档的 `TTL_HISTORY_INPUT_OBSERVED` **不暴露** `global_server_gap_samples_seconds`
的长度，因此在归档层面**无法**核实样本数是否如推算的 10 条。
要验证 RC6 的第 2 项，需要该事件补两个计数字段（属日志改动，非算法改动）。

---

## 4-补. RC-C —— 既有 Warm-start 路径的设计审计

本节是只读审计：没有修改阈值，没有向任何实验注入历史，也没有预设 warm-start 会改善 A1。

### 4C.1 机制确实存在于仓库中

`origin/main`（`e2ac264`，`2026-10-24`）已包含完整的 W1-A warm-start 路径，
但本 PR 分支基于更早的 `main`，工作树里没有这些文件，因此审计直接从 git 读取：

| 组件 | 位置 | 作用 |
|---|---|---|
| 冻结历史 | `configs/phase2/continuum-w1a-server-gap-history-v1.json` | 443 条 server gap |
| 载入 | `src/kvopt/workload/continuum_native_history.py::load_history` | 校验 schema / 计数 / 时间戳来源 |
| 注入 | `Runtime.seed_server_gap_history` | 只允许在**受测生命周期开始前**注入 |
| 调用点 | `scripts/spikes/phase2_minimal_observability_metal.py:1101` | 读配置 → 校验 SHA → 注入 → 发事件 |
| 事件 | `SERVER_GAP_HISTORY_WARM_STARTED` | 记录 path / sha256 / 样本数 / `kv_cache_prewarms=false` |

历史本身的属性（由 `rc_c_warmstart_audit.py` 直接读出）：

| 字段 | 值 |
|---|---|
| `scope` | `INDEPENDENT_W1A_HISTORY_WARM_START_NO_KV_PREWARM` |
| `source_repository_scope` | `ASTROPY_ONLY`，10 个任务 |
| `server_gap_sample_count` | **443** |
| `duration_history_threshold` | 100 |
| `deduplication` | 每个源程序的连续成功调用对记一条 |
| gap 定义 | `NEXT_MODEL_SUBMIT_MINUS_PREVIOUS_MODEL_COMPLETION` |
| 外部工具时长算 gap？ | **否**（`PROVENANCE_ONLY_NOT_SERVER_GAP_SAMPLE`） |
| `kv_cache_prewarms` | **false** |
| tool_type 分布 | `mini-swe-agent-shell` 265，`None` 178 |

### 4C.2 为什么 v10 没有用它

不是能力缺失，是**协议层的硬门禁**。在 v10 campaign 记录的同一 tooling commit
`7d0546a` 上：

```python
if config.get("campaign_kind") != "continuum_native_costaware_formal":
    raise ValueError("history warm-start is restricted to the formal campaign")
```

而 v10 的 54 个 config 全部是
`campaign_kind = continuum_native_costaware_bounded_evaluation`，
且**没有一个**带 `continuum_server_gap_history_path` / `..._sha256`。
两条独立原因各自都足以让该路径不可达：

1. `campaign_kind` 不匹配 → 即使写了 path 也会直接抛错；
2. 配置没写 path → 连门禁分支都不会进入。

所以 §4.4 的冷启动根因需要补一句限定：

> 「样本量 10 ≪ 阈值 100」是**在 bounded campaign 的配置与生命周期下**成立的事实；
> 同一代码库另有 warm-start 通道，只是在 bounded campaign 中被 `campaign_kind` 门禁排除。

### 4C.3 若考虑启用，必须先回答的问题（本轮不回答）

| 维度 | 现状 | 为什么不能跳过 |
|---|---|---|
| 独立性 | 来源 W1-A（astropy ×10），与 v10 的 g01–g09 无重叠 | 需要证明"独立"，而不只是"另一个数据集" |
| 公平性 | 注入在生命周期前，且不改阈值 | 必须对 A0/A1/A2 **同样**注入，否则比较不对称 |
| 分布适用性 | v10 trace 的 `tool_gap_seconds` **全为 0**，下一轮由完成事件驱动 | gap 语义不同：W1-A 是 agent 工具延迟，v10 是 runner 开销 |
| 数值分布 | W1-A：中位 0.2799 s，p90 0.3638 s，max 58.1 s；v10 观测：中位 0.2825 s，p90 1.6635 s，max 4.58 s | 中位数几乎相同，尾部完全不同；同中位数 ≠ 同分布 |
| tool_type 匹配 | v10 的 `next_tool_type` 是 `observed-agent-gap`（214/216） | W1-A 对该标签 0 条样本 → 即使注入，模式仍停在 `GLOBAL`，到不了 `TOOL_SPECIFIC` |

最后一条是一个具体设计后果：warm-start 能解除 `COLD_START`，
但不能解除 `TOOL_SPECIFIC` 不可达；后者需要**同 tool 标签**的历史。

> **本轮结论**：warm-start 是"历史不足"的一条**备选路径**，不是已证实的改进手段。
> 它解除的是 `COLD_START`，不保证改变 A1 的选择，也不保证带来收益。
> 是否启用必须由独立 campaign 决定，且必须三臂对称。

### 4C.4 Cold-start 默认 TTL 是初始化常数

必须写清：`COLD_START` 分支是 `ttl_seconds = ttl_input.default_ttl_seconds`
（`ttl.py`），而该值在 **Runtime 初始化时**由
`compute_default_ttl_seconds(profile(256))` 一次算出（`composition.py`，
`REPRESENTATIVE_DEFAULT_TTL_TOKEN_COUNT = 256`），
**不是**在每次决策里对每个候选分别查 `PrefillReload`。

因此 `estimate_ttl` 的 `COLD_START` 分支不使用 `prefill_reload_seconds`、
`queue_delay` 或 `eta`；三者只在非 `COLD_START` 分支的 `_choose_empirical_ttl` 中参与。
这也解释了 §3.4 的代数结论：同一 run 内 `ttl` 是常数，`deadline − t` 只是"常数 − 已过时间"。

---

## 5. RC5 —— A1 的数学与归因

### 5.1 精确翻转判据

对全部 sufficient 候选（$N_i\ge\text{need}$）：

$$\widehat R_i=q_i\,a_i,\qquad a_i=\lambda N_i+(1-\lambda)\,\text{need}$$

$\lambda=0$ 取 $\arg\min q$；$\lambda>0$ 取 $\arg\min q\,a$。两者不一致的**精确条件**：

$$\frac{q_H}{q_L}\;<\;\frac{a_L}{a_H}$$

其中 $L$ 为低 $q$ 候选、$H$ 为高 $q$ 候选。

上一版用 $N_L/N_H$，那是 $\lambda\to1$ 或 $N\gg\text{need}$ 的极限。二者关系：

$$a_L/a_H \in [1,\;N_L/N_H]$$

即近似形式**系统性高估**翻转倾向。本归档中两者结论一致（18/18，近似式假阳性 0），
但**近似式不作为一般判据**。

### 5.2 验证（精确式）

```text
forced-release decisions replayed            29
runs with more than one step                 11     <- 覆盖多步释放
first observed pick not among candidates      0     <- 用完整 (program, prefix) 键比较，无截断
two-candidate decisions                      18
exact ratio (a_L/a_H) correct                18 / 18
approximate ratio (N_L/N_H) correct          18 / 18
approximate false positives                   0
```

g05 两例（唯一翻转）：

| run | need | N | q_ratio | **a_ratio** | N_ratio | flip |
|---|---:|---|---:|---:|---:|---|
| g05-deep | 114 | 649 / 993 | 1.4174 | **1.4509** | 1.5300 | 是 |
| g05-moderate | 1 | 649 / 993 | 1.4174 | **1.5292** | 1.5300 | 是 |

注意 moderate 的 `a_ratio`（1.5292）与 `q_ratio`（1.4174）**只差 7.9%**，
说明该决策在 λ 变化下**接近临界**——这是"单次运行下不稳定"的另一条理由。

### 5.3 五个层次必须分开（M1 要求）

| 层次 | 本归档状态 |
|---|---|
| **代数复算** | 完成：λ=0.5 打分 29/29 复现观测；精确判据 18/18 |
| **观测选择重现** | 完成：`replay reproduces observed first pick: 29/29` |
| **离线 λ 反事实** | 完成：λ=0 改变 2 / 29 个选择（均 g05） |
| **Native 重算结果** | 仅 g05-moderate 有（A0 16 tokens vs A1 3728 tokens） |
| **具内容身份的因果归因** | **未建立**（`content_level_causal_attribution: NOT_ESTABLISHED`） |

### 5.4 保留与收窄

- 保留：g05-moderate 的 **+3712** 是观测事实，且该决策的选择可由打分精确复现；
- 收窄：**单次运行不能证明稳定退化**；且该决策接近临界（§5.2），λ 微小变化即可翻转。

---

## 6. RC6 —— 有界实验可识别性检查方案（不申请 GPU）

### 6.1 第一步（零 GPU）：A2 是否存在真实机会 —— **已完成（重做）**

| 检查 | 结果 |
|---|---|
| 可比决策（代价模型可评估） | 434 / 601 |
| 有代价信号的决策中 Greedy 集合 ≠ rank 集合 | **0 / 66** |
| greedy 集合 ≠ rank 集合 | **0 / 434** |
| 引擎自身 `search_truncated` | **434 / 434** |
| 零损失下界可证 rank 集最优 | 368 |
| exact 不可判定（超预算） | 66 |
| 链内 rank 全部 deepest-first | 434 / 434 |

**必须撤回的说法**：上一版把"链内 rank deepest-first"当作"Cost-Aware 不可能偏离 LRU"
的**充分条件**。这是错的。多链且各自 q 不同时，每条链内部都可以是 deepest-first，
而"该先腾哪条链"仍然是一个代价决策。仓库自带的测试就是反例：

`tests/test_costaware_a2_selector.py::test_diverges_from_lru_when_a_cheap_chain_is_not_the_coldest`
——链 a 最冷（rank 0..2）但 `q = 0.9`，链 b 更暖（rank 10..12）但 `q = 0.1`，
两条链**各自都是 deepest-first**，`need = 1` 时 rank-LRU 取 `a@3`，代价最优取 `b@3`。
`rc3_scale_and_geometry.py` 在脚本内复现该反例（输出 `rank (13,) / greedy (23,)`）。

正确表述：

> 在本归档 434 个可比决策上，**实测偏离为 0**。这是经验观测，不是几何定理。
> 偏离的必要条件是"存在比最冷候选更便宜的更暖候选"，该条件 434/434 不成立；
> 归档不记录可用于确认该条件在更大负载下是否出现的量。

补充：所谓"完整 legal set"是指连 hashless 块一起保留。它们在本次归档里占
441 994 / 可行候选的多数，代价为 0（无 membership 即无重算），
正因如此"最冷候选代价为 0"的 386 个决策里，第一步必然取最冷块。


### 6.2 第二步（零 GPU）：TTL / 历史的产生—传递—消费核查

| 环节 | 现状 | 可否离线验证 |
|---|---|---|
| 产生 | `ServerGapHistory.record` 存在，按到达事件触发 | 代码可读；**归档不记录样本数** |
| 传递 | `TTLInput.global_server_gap_samples_seconds` | 代码可读；归档不记录 |
| 消费 | `_select_history` 阈值 100 | 代码可读 |
| 判定 | `mode == COLD_START` | **归档未记录 `TTLDecision.mode`** |
| 处置 | `default_ttl_seconds` 为常数 | 可由 `ttl == 0` 反推 |

**需要的最小可观测性补丁（日志，不是算法）**：

1. `TTL_HISTORY_INPUT_OBSERVED` 增加 `global_server_gap_sample_count` 与 `tool_server_gap_sample_count`；
2. 事件中记录 `TTLDecision.mode`；
3. 块决策事件记录 `legal` 列表的**排序依据**与**当时的队列快照**（或 `lru_rank`）。

这三项使 §1.4 的 L2、§4.4 的样本数、§6.1 的几何性质都变成**可离线判定**。

### 6.3 第三步：是否需要受控负载

由 §2–§6.2，两种退化各自有独立的解除条件：

| 退化 | 解除条件 | 现有 workload 能否满足 |
|---|---|---|
| 历史样本不足（10 ≪ 100） | 单 run ≥ 100 个 gap 样本（≈100+ 请求），或降低阈值 | **否**（12 请求/run） |
| 几何不含可选差异 | 出现“更暖但更便宜”的候选（不是链内单调性） | **未观测到**（434/434 未出现） |
| Cold-start 默认 TTL 为零 | 默认 TTL 由启动时代表性 Profile 参考点及 `μ` 决定；若改用经验 TTL，须另行满足历史门槛并验证输出 | **不能仅延长单次请求**；需要新的受控配置验证与冻结 |

**结论：需要一个受控负载**，其设计目标应仅为"把三种退化解除"，而不是"制造收益"。
这属于 Workload Redesign —— **未获授权**，本文只提出判据，不提出实现。

### 6.4 第四步：若需 Native，先做机制确认

在完整 campaign 之前，建议**少量机制确认运行**（数量由 M1 定，本文建议个位数）：

| 确认项 | 判据 |
|---|---|
| 历史样本确实非零 | `TTL_HISTORY_INPUT_OBSERVED` 的样本计数 > 0 且 `mode != COLD_START` |
| TTL 非退化 | `ttl_seconds > 0` |
| 几何含可选差异 | 至少一个窗口的最冷候选比更暖候选更贵 |
| A2 确实偏离 | `selected_victims != native_lru_victims` 出现 ≥1 次 |

**只有四项全部为真，才存在可评的"Cost-Aware 是否有效"的问题。**

### 6.5 λ=0 / SFED 的定位

保留为**强基线与消融对照**，但**不**升级为最终研究算法。
理由：本归档中 λ=0 使 A1 与最早 deadline 一致（27/29），即与 A0 同源；
它消除退化但不产生收益，因此只能作为"归因工具"。

---

## 7. RC7 —— 归档来源核验

### 7.1 可核对的事实

| 检查 | 结果 |
|---|---|
| `evidence-manifest.json` 条目 | 366 |
| 逐文件 SHA-256 匹配 | **365** |
| **不匹配** | **1** |
| 缺失 | 0 |
| `sha256-manifest.txt` 行数 | 370 |
| 可解析且匹配 | **370 / 370** |
| `sha256(evidence-manifest.json)` | `072d5264…` |
| `execution-summary.json` 声称的 `inventory_sha256` | `072d5264…` ✓ 一致 |
| run 目录（含 `run.json`） | **54**，`g01-short-extreme-deep-a0-repeat-1` … `g09-near-matched-moderate-a2-repeat-1` |

### 7.2 唯一的失配文件

```text
evidence-manifest.json 记录的 execution-summary.json:
  sha256 = 718e6e39…    size = 1091
实际:
  sha256 = e3b25be2…    size = 1635
```

差异内容为 `result_summary` 与 `wall_elapsed_seconds` 两段（共 +544 字节）。
这说明 **`execution-summary.json` 在清单生成之后被写入过**——
最可能是流水线"先写清单、后补最终统计"的顺序产物。

**但这只是推测，本文不把它当成结论**；它恰恰说明该文件不能用于链接外部 SHA。

### 7.3 关于两个 archive SHA

```text
M1 公布:  ac2b910e...   在解压后的归档树中【完全不出现】
归档内:   d4aaf36e...   仅出现在 execution-summary.json 的 archive.archive_sha256
```

因此：

- 本机这一份**内部自洽**（370/370 + 365/366）；
- 但 **无法证明** 它等于 M1 公布 SHA 所指的 tar.gz；
- 且唯一记录该 SHA 的文件本身**与清单不符**（§7.2），进一步削弱其可信度。

**可交由 M1 核对的链接字段**（这些字段是归档真实的、且未被修改的部分）：

| 字段 | 值 |
|---|---|
| `tooling_git_sha` | `7d0546ab6829060fa50fe40f5dcb47dd5212f091` |
| `manifest_sha256` | `13cba945ddddb3c48f0970e1d0e483bce95a675101ef32aa5db4ceb5881f605d` |
| `authorization_sha256` | `3ff0cf0294cdf9a6eca35822344c5ee3a4ba6db8c9d5d532c96c81442911c577` |
| `report_sha256` | `ad879105e21aedbf86b2dd5d4199688be4b7587b051b6be3e45b0100ec643b0e` |
| `profile_sha256` | `baf4497161e2326c5b884358350515abe35aff22d4d94a92b2acd9004db91cc6` |
| `raw_profile_sha256` | `24c2d425a1f16164d4428bba09cc8614d6f57f52d17f8280ee92abf78d1aafb0` |
| run ID 集合 | 见 §7.1（54 个） |

**建议**：以 `tooling_git_sha` + `report_sha256` + 54 个 run ID 作为跨份核对键，
而不是 archive 级的 tarball SHA。

### 7.4 来源状态：`SOURCE-UNVERIFIED`

不能把 365/366 读作“完整性验证通过”。本轮保留未验证标记，理由是两条同时成立：

1. 一个清单条目失配，说明**当前树不是清单描述的那棵树**；
2. 发布摘要在整个解包树中**不存在**，所以没有任何路径能从解包文件回溯到发布字节。

同时必须说明：`sha256-manifest.txt` 的 370/370 与本结论**不矛盾也不补偿**。
它证明的是“解包树内部自洽”，而这本来就是它自己生成的清单，
不可能证明与外部 tar.gz 相等。

| 可核对项 | 结果 | 能证明什么 |
|---|---|---|
| `evidence-manifest.json` 365/366 | 1 失配 | 解包树与**自身**清单不一致 |
| `sha256-manifest.txt` 370/370 | 全部匹配 | 解包树内部自洽 |
| 发布 archive SHA 出现次数 | 1（仅在失配文件内） | 不构成外部对应关系 |

升级条件只有两个，二者任一即可：

- 拿到原始 tar.gz 并本地计算 SHA-256；或
- 用当前树重新生成 manifest，并与发布方核对同一树的两个摘要值。

在两者任一发生前，本报告的结论只依赖**树内证据**（事件字段、run 目录、ID 集合），
不依赖发布摘要；这一点也写在 §10 的边界里。

---

## 8. Part A / B 的结论（按上述更正重述）

### 8.1 Entry 层

| 项 | 结论 | 强度 |
|---|---|---|
| `ttl = 0` 在 139/139 | 事实 | 强 |
| $q$ 与 deadline 同序 | 由 cold-start 常数 TTL 推出，**不是 TTL=0 导致** | 强（代数） |
| A1 精确翻转判据 | 18/18 | 强（代数 + 复算） |
| λ 改变选择 2 次，均 g05 | 事实 | 强 |
| g05-moderate = +3712 | 观测事实 | 强（但 n=1 repeat） |
| 该退化稳定存在 | **不可判定** | — |
| 复用概率型 EntryLoss | **无法在本归档构造**：样本 10 ≪ 100，非"不存在" | 中（§4） |

### 8.2 Block 层

| 项 | 结论 | 强度 |
|---|---|---|
| A2 使用代价打分 | 434/601 | 强 |
| 代价打分改变 victim | **0/601** | 强 |
| 有真实可选差异（新定义） | **0/434** | 强（全候选边际代价） |
| 有代价信号但不改集合 | 66/434 | 强 |
| 无代价信号 | 368/434 | 强 |
| 零损失下界证明 rank 集最优 | 368/434 | 强（下界，不需枚举） |
| exact 是否偏离 | **不可判定**（66 个超预算；引擎自述 434/434 截断） | — |
| 链内 deepest-first | 434/434 | 事实，**不构成判据** |
| A2 vs 真正 A0 | **不可判定**（快照过期 151/229） | — |
| 回退 167/601 | 事实；与 Gate 2 51.7% **不可比** | 强 |

### 8.3 M2 四方向（受上述更正影响的部分）

| 方向 | 修订后判定 |
|---|---|
| **B1** 条件介入 | **`CONDITIONALLY TESTABLE`**：本归档实测偏离 0/434；要评它，必须先出现"更暖但更便宜"的候选，且 exact 需落在预算内 |
| **B2** 中间信号 | **`NO DATA BUT NOT ABSENT`**：历史存在（≈10/run），差一个数量级的样本；另有 W1-A warm-start 通道（443 条，§4-补），但它只能解除 `COLD_START`，且分布适用性与公平性未验证 |
| **B3** 下游感知排序 | 不变：`LIMITED`（A0 已消费下游 rank；单步即满足） |
| **B4** 部分尾部释放 | 不变：`HIGH COST`（超额是 `initial_shortage_blocks=1` 的设计产物） |

---

## 9. 本轮**不做**的裁定

按 M1 要求，本文**不**给出最终研究方向裁定，也**不**申请执行 Part D 的 54-run Freeze。
上一版的 Part C/D 视为**撤回**，待 §6 的可识别性检查完成后再提。

---

## 10. 边界

- 未修改 `src/`；未运行 Native；未覆盖归档；
- 全部 counterfactual 均标注为离线反事实，不是原始真实运行结果；
- 逆向推断（如"候选按 rank 升序传入"）均给出依据，并标明其为推断；
- `physical_eviction_divergence` 仍建议弃用（18/18 全 true，含 16 个 A1 序列与 A0 相同的 cell）；
- warm-start 审计**只读**：文件从 `origin/main` 读，未改阈值、未注入实验、未改冻结算法；
- 本报告的所有结论只依赖**树内证据**，不依赖 §7 中未验证的发布摘要；
- “引擎从未穷举”是**归档事实**（`search_truncated` 434/434），不是对算法能力的评价：
  在 `|legal| ≈ 1029` 时 `C(n, k)` 必然超预算，这是配置与规模的结果。

---

## 11. 复现

```bash
# 需先解压 v10 archive 到 local/continuum-native-cost-aware-bounded-v10-final-evidence/
python scripts/probes/entry_costaware_audit/rc2_opportunity.py            # RC-A 机会分类 + 最优性状态
python scripts/probes/entry_costaware_audit/rc3_scale_and_geometry.py     # RC-B 完整几何 + greedy/exact/超预算 + 反例
python scripts/probes/entry_costaware_audit/rc7_archive_verify.py         # RC-D 归档核验（含 SOURCE-UNVERIFIED 状态）
python scripts/probes/entry_costaware_audit/rc_c_warmstart_audit.py       # RC-C warm-start 设计审计
python scripts/probes/entry_costaware_audit/rc5_exact_flip.py             # 精确判据 18/18
python scripts/probes/entry_costaware_audit/a1_decisions_detail.py
python scripts/probes/entry_costaware_audit/a1_lambda_ablation.py
python scripts/probes/entry_costaware_audit/a4_identity_gap.py
python scripts/probes/entry_costaware_audit/a4_divergence_check.py
python scripts/probes/entry_costaware_audit/a4_legal_strict.py
python scripts/probes/entry_costaware_audit/a2_field_variation.py
python scripts/probes/entry_costaware_audit/b2_signal_audit.py
python scripts/probes/entry_costaware_audit/b4_unlocked_vs_evicted.py
```

`rc_c_warmstart_audit.py` 需要能访问 `origin/main`（它从 git 读 warm-start 文件，
因为那些文件不在本分支）。其余脚本只读本地解压出来的归档。
公共的几何重建在 `scripts/probes/entry_costaware_audit/rebuild_geometry.py`。

---

## 12. 对 M1 四个问题的直接回答

### 12.1 实际 A2 Greedy 选择偏离 Rank-LRU 的决策有多少？

**0 / 434**（601 个块决策中 167 个代价模型未运行）；66 个有信号决策的 Exact 最优性未知。

- 旧的“38 个 S5”**撤回**：它来自 `step_costs` 被误读为候选分布。
- 真正有代价信号的决策有 66 个（边际代价在这 66 个里从 149 到 1663 个不同取值），
  **但 Greedy 选择集合仍与 Rank-LRU 相同；Exact 最优集合尚不可判定。**
- 无任何代价信号的 368 个，其 rank 集损失为 0，下界即可证明最优。

### 12.2 Greedy 与可执行的 Exact 是否偏离 Rank-LRU？

| 规则 | 是否偏离 | 依据 |
|---|---|---|
| Greedy | **否，0 / 434** | 直接执行 `greedy_select` |
| Exact | **不可执行** | `C(1029, need)` 超预算；引擎自述 `search_truncated` 434/434 |
| Exact（可证部分） | **否，368 / 368** | 损失非负且 rank 集损失为 0 |
| Exact（未定部分） | **未定，66** | 既不穷举完也不可证下界 |

必须同时说出三件事，缺一件都是过度声称：

1. 引擎实际跑的从来不是 exact，而是 greedy（434/434 一致）；
2. 在本几何上 exact 不可执行，因此“exact 也不偏离”只对这 368 个成立；
3. “链内 deepest-first”是事实，但**不是**“不会偏离”的充分条件（§6.1 反例）。

### 12.3 v10 的历史冷启动主要由什么造成？Warm-start 为何没有参与？

两个条件同时成立，缺一不可：

| 条件 | 具体值 |
|---|---|
| 配置：campaign kind | `continuum_native_costaware_bounded_evaluation`（不是 `..._formal`） |
| 配置：历史注入键 | 54/54 config 均无 `continuum_server_gap_history_path` |
| 生命周期：样本量 | 每 run 约 10 条 gap，阈值 100 |
| 生命周期：作用域 | history 是 per-process，不跨 run 累积 |

warm-start 未参与不是缺失能力：同一 tooling commit 已有 `seed_server_gap_history`，
但被 `campaign_kind` 门禁限定在 formal campaign，而 v10 不在其列。
即使启用，从 W1-A 注入的历史也只会让模式离开 `COLD_START`（443 > 100 → `GLOBAL`），
**不会**进入 `TOOL_SPECIFIC`（v10 的 tool 标签在 W1-A 中 0 条样本）。

### 12.4 哪些研究判断可以保留，哪些必须撤回？

| 判断 | 状态 |
|---|---|
| A2 确实执行了代价打分（434/601） | **保留** |
| A2 的输出与 rank-LRU 601/601 相同 | **保留** |
| `native_lru_victims` 是独立计算的参照 | **保留** |
| A2 存在 38 个“真实可选差异”窗口 | **撤回**（方法错误） |
| “穷举也不偏离”覆盖 66 个决策 | **撤回**（未穷举，且 66 个未定） |
| “链内 deepest-first ⇒ 不可能偏离” | **撤回**（仓库反例） |
| “该 workload 永不产生历史” | **撤回**（每 run 约 10 条，仅低于阈值） |
| “历史全零” | **撤回**（为零的是 eta / queue-delay 计数器） |
| `q_ratio < N_ratio` 是充要条件 | **撤回**（仅 `λ=1 / N≫need` 极限） |
| `ttl = 0` 是设计内截断（`μ = 1 s`） | **保留** |
| 常数 TTL 导致 `q` 与 deadline 同序 | **保留**（代数） |
| A1 精确翻转判据 18/18 | **保留** |
| L2（A2 vs 真正 A0）不可判定 | **保留** |
| 归档“完整性已验证” | **撤回**，改为 `SOURCE-UNVERIFIED` |
| exact 在本几何上不偏离 | **从未成立**，改为“不可执行 + 368 个可证” |

本轮**仍不**给出最终研究方向裁定，也**不**申请 Freeze；
§6 的三项日志补丁与 §4C.3 的五个前置问题解决前，任何方向的结论都还不具备可判别性。
