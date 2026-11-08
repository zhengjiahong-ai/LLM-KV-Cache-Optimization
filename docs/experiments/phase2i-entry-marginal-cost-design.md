# Phase 2I — Entry-level Marginal Cost-Aware Algorithm Design（修订版 v4）

**分支**：`design/phase2i-entry-marginal-cost`
**输入**：Phase 2H Formal History-Rich Native Smoke（6/6 runs），M1 对 PR #87 的 RC1–RC9（三轮）。
**边界**：纯离线设计与分析。未修改冻结 A1/A2，未新增 Native Run，未提交实现。
**脚本**：`scripts/probes/entry_costaware_audit/phase2i_marginal_probe.py`（只读）
**契约检查**：`scripts/probes/entry_costaware_audit/phase2i_depth_contract.py`（只读，9/9 PASS）
**证据分级**：`scripts/probes/entry_costaware_audit/phase2i_m3_evidence.py`（只读）

> v2 按 RC1–RC4 修正了四处：基线语义、as-of 快照与跨臂关联、成本代理的定位、
> 不足量回退路径与结论强度。
> **v3 按 RC5–RC7 再修正三处，其中 RC5 是实质性撤回**：
> `RetentionEntrySnapshot.block_ids` 的下标**不等于**深度（该元组会被压缩），
> v2 的 §6.1 前提作废，替换为内容键控的 `ChainDepthProof` 契约；
> RC6 恢复与 A0 分歧的精确不等式，`q×S` 降为近似；
> RC7 把物理证据分为 L1–L4 四档并重新分档判读 M3。
> **v4 按 RC8–RC9 完成两项闭环**：深度证明的身份与时效**被校验**而不只是被存储；
> 屏障配对增加区间与计数器链检查，并因此**发现 hr02 的计数器不自洽**（整 run 排除）；
> M3 拆成四类互不等价的证据，不再用单一“通过/失败”概括。
> §0.5 列出具体改动。

---

## 0. 摘要

### 0.1 机制结论（由冻结规则推导，与样本量无关）

**`N_i` 不是代价。** 冻结的资格规则按 `(tier, native_lru_rank)` 排序，`TIER_1 = 0`，
而一次 pressure 只把被释放的那**一个** Entry 提升为 `TIER_2`。因此所有 TIER_1 块先被消耗完，
被释放 Entry 只在 TIER_1 不足以覆盖 `required_blocks` 时才贡献受害者：

$$\text{deficit}=\max(0,\ \text{need}-|\text{TIER\_1}|),\qquad
\text{victims}(X)=\min(\text{deficit},\ |\text{newly eligible}(X)|)$$

只要候选能覆盖 `deficit`，**受害块数对所有候选都等于 `deficit`**。这是对排序规则的推导，
不依赖本轮样本是否够大。Phase 2H 的 6 次决策与此一致（§5.1）。

### 0.2 经验结论（受样本量限制，仅陈述观察）

在 Phase 2H 的 6 次决策上：

- A1 的实际释放与 **Minimum Overshoot** 的选择 **6/6** 相同；
- 与 **A0**（Continuum deadline 规则）**5/6** 相同；与 Earliest Deadline 也 5/6 相同。

可归因的代数原因是 `need ≪ N_i`（`need` ≤ 128，`N_i` ≥ 460）使评分括号退化为 `0.5·N_i`。
`q` 与 `N` 在候选间同序只是这 6 次决策的**观察**（4/6 Spearman = +1.000），
**不可推广为“两者总是同序”**。

**样本量定位**：n = 6 决策 / 2 scenario / 1 repeat。它足以支撑“机制在这类决策上如何运作”
的判断（后者由冻结规则推导），**不足以支撑任何性能或优劣的统计结论**。

### 0.3 推荐方向

把代价对象从“新增 eligible 块数”改为“该 Entry 的 prefix **后缀**损失”：

$$L(X)\;=\;q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X}$$

其中 $S_X=m_X-d_{\min}(X)+1$，$d_{\min}$ 是预计受害块中最浅的 Chain Depth。
**本式是 Prefix-suffix-aware **Cost Proxy**，不是已校准的期望重算时间**（§3.4）。

两条必须同时看到的限定：

- 在实测的近线性 profile 下 `prefill/m` 候选间跨度仅 1.0001–1.1421，
  所以 **`L` 的实际排序 ≈ `q × S`**，`m` 与 `prefill` 是 ≤14% 的扰动项，不是新判别维度（§3.5）。
  但**这是本负载下的近似，不是等价**：精确判据始终是完整不等式
  `q_Y·prefill_Y·S_Y/m_Y < q_X·prefill_X·S_X/m_X`（RC6）。
- 本方案与 A0 的分歧在 6/6 决策上**在 A0 选中项几何不变的前提下结构上不可能**
  （不仅未观察到），因为 A0 选中的 Entry 恰同时具有最小 `q` 与最小 `prefill/m`（§5.5）。
  **不得**由此声明"只要 `S` 恒定就与 A0 完全等价"。

### 0.4 本版相对 v1 的改动

| 项 | v1 | v2 |
|---|---|---|
| **RC1** A0 语义 | 写作"选择最冷 Entry" | A0 = `(deadline, min native rank over newly eligible, identity)`；Native LRU 属 **Block 层**，不参与 Entry 选择 |
| **RC1** 可判别条件 | “最冷 Entry 带浅层块”才算可判别 | 用**真实基线规则**定义：A0 = `argmin deadline` = `argmin q`；分歧 ⟺ 最早 deadline 的 Entry 同时带最长后缀，且越出 q 差。另证明 `m`/`prefill` 在本 profile 下近似惰性，实际由 `S` 承担 |
| **RC2** 几何来源 | 用整次 run 的最后一条 snapshot | **as-of**：`event_index < 决策 index` 的最新同 `(program, prefix)` snapshot |
| **RC2** 深度缺失 | 静默跳过 | **Fail Closed**，整条决策标记不可评分并排除 |
| **RC2** 跨臂对照 | 最近 event index | **`boundary_id`**（如 `pressure:after-round-55`）严格关联 |
| **RC3** 公式定位 | "期望重算秒数" | **Cost Proxy**，附三条明确假设 |
| **RC4** 不足量回退 | 自行改为 deadline 排序 | **沿用冻结 A1 的完整阶梯**（per_unit → pair lookahead → deadline） |
| **RC4** 结论强度 | "六次完全一致" / 少于十次即全无效 | 区分**机制判断**（推导得出，不依赖 n）与**性能判断**（n=6，不作结论） |

### 0.5 v3 相对 v2 的改动（RC5–RC7）

| 项 | v2 | v3 |
|---|---|---|
| **RC5** 深度来源 | 断言 `RetentionEntrySnapshot.block_ids` 下标 = 深度，`m = len(block_ids)`，并称"不需要任何新状态" | **撤回**。该元组在 `retention.py:144 observe_eviction` 与 `:176 reconcile_entry_evictions` 被压缩，下标会漂移、长度不再是 `m`。改用内容键控的 `ChainDepthProof`，四条性质逐条契约验证（5/5 PASS），无法解析即 Fail Closed（§6.1） |
| **RC6** 与 A0 的判据 | 用 `q·S` 当等价式，并声称"`S` 恒定 ⇒ 与 A0 等价" | **恢复完整不等式** `q_Y·prefill_Y·S_Y/m_Y < q_X·prefill_X·S_X/m_X`；`q·S` 降为"本负载下的近似解释"（跨度 ≤1.1421）；停止条件 3 改为按 **Score/Selection 是否可区分** 判定（§3.5、§5.3、§6.3） |
| **RC6** §5.5 的下界结论 | "任何块几何都无法偏离 A0" | **限定前提**：仅在 **A0 选中项的 `q`/`prefill`/`m`/几何保持不变** 时成立；并标注 hr01 idx=4244 裕度仅 3.7%，小于 14% 带，结论对该带不稳健（§5.5） |
| **RC7** 屏障配对 | 按位置顺序配对 | 增加 **数量 / 事件顺序 / 唯一 `boundary_id` / 阶段归属** 四项检查，任一失败整 run 排除（§6.3 条件 6） |
| **RC7** 物理证据 | 未分级；曾把整跑 `BLOCK_EVICTED` 全命中当作归属证据 | 建立 **L1 预计受害者 / L2 真实 Native Eviction / L3 完整内容级 Attribution / L4 重算代价** 四档；明确整跑交集是**时间关联而非因果归属**（§2.4、§7.1） |
| **RC7** M3 门 | 单一判据 | **分档判读 A/B/C/D**；本轮实测 **1 A / 5 B / 0 C / 0 D**，即"未发现推算错误，也未能逐块确认"（§7.1）。**v4 认为该分档仍是错误的抽象，已改为四类主张，见 §0.6 与 §7.1** |
| **RC7** 缺口措辞 | "无回调 ⇒ `r_i` 不可算" | 改为分级陈述：属**回调完整性**限制，既非算法错误证据也非正确证据（§2.4） |

### 0.6 v4 相对 v3 的改动（RC8–RC9）

| 项 | v3 | v4 |
|---|---|---|
| **RC8** 身份校验 | `ChainDepthProof` 存了 `native_hash_process_id` / `chain_id` / `observed_at`，但 `depth_of()` **不校验**它们 | 查询改为携带 `DepthQuery(chain_id, native_hash_process_id, decision_at)`，四项逐一拒绝：跨链 `WRONG_CHAIN`、跨进程 `WRONG_PROCESS`、未来证明 `FUTURE_PROOF`、过期 `STALE_PROOF`；内容不符 `CONTENT_MISMATCH`（§6.1.5） |
| **RC8** 部分逐出用例的复合条件 | `real_depth != depths[i] and real_depth != {...}[block_id]` —— 两个候选值任一命中即 PASS，且 `survivors.index()` 本身就是压缩下标 | 改为对每个幸存块**逐一断言**预期深度，并反向检查“确实至少有 3 个块的深度不等于下标”（§6.1.4） |
| **RC8** 离线身份不足 | 未定义 | 新增 `IDENTITY_UNVERIFIED`：内容键缺失时**不返回深度**，不得以仅深度记录冒充已验证。本轮实测内容键齐全，未被触发（§7.1） |
| **RC9** 屏障区间 | 只要求 release 早于自己的 completion | 增加 `previous_completion < release < current_completion` 的**区间包含**检查（§6.3 条件 6） |
| **RC9** 计数器 | 旧检查为 `after == position + 1`，**恰好**在 hr02 上误通过 | 改为 `before == 上一 completion 的 after` 且 `after == before + 1`。**该检查在 hr02 上失败**（§5.2、§6.3） |
| **RC9** 冻结身份 | 只查 `stage_id` 非空 | `boundary_id` 与 `stage_id` 均需非空且全局唯一（§6.3） |
| **RC9** M3 | 单一档位 A/B/C/D | 拆为 **M3-1 选择一致 / M3-2 真实逐出 / M3-3 内容身份 / M3-4 重算后果** 四类，互不等价（§7.1） |

---

## 1. Phase 2H 负面结果的机制解释

### 1.1 冻结的资格规则决定"谁死"，且不含 N

从 `src/kvopt/continuum/selection.py` 读出（非推断）：

```text
EligibilityTier.TIER_1 = 0, TIER_2 = 1
virtual_eligible_order = sort(eligible, key=(int(tier), native_lru_rank))
selected               = virtual_eligible_order[:required_blocks]
```

`EligibilityPreparation.__post_init__` 进一步约束：一次 pressure 的
`pressure_releases` 必须**恰好解释全部 TIER_2 块**，且每个块的 `newly_eligible_block_ids`
只能属于一个 release。所以"释放哪个 Entry"= "把哪个 Entry 的冷块放进 TIER_2 窗口"。

两步算术：

```text
deficit = max(0, need − |TIER_1|)
candidate 的受害块数 = min(deficit, |该候选的新增 eligible|)
```

Phase 2H 实测（as-of 复核后不变）：

| scenario | idx | barrier | need | TIER_1 | deficit | 各候选受害块数 |
|---|---|---:|---|---:|---:|---|
| hr01-balanced-gap | 2170 | round-40 | 126 | 93 | 33 | **33 / 33 / 33** |
| hr01-balanced-gap | 4244 | round-50 | 128 | 78 | 50 | **50 / 50 / 50** |
| hr01-balanced-gap | 7305 | round-55 | 128 | 72 | 56 | **56 / 56 / 56** |
| hr02-short-gap-long-context | 2166 | round-40 | 128 | 122 | 6 | **6 / 6 / 6** |
| hr02-short-gap-long-context | 4384 | round-50 | 18 | 1 | 17 | **17 / 17** |
| hr02-short-gap-long-context | 10388 | round-55 | 17 | 0 | 17 | **17 / 17** |

> 决策选择的不是**死多少块**，而是**死谁的内容**。`N_i` 只决定"能否满足需求"。

### 1.2 A1 为什么在这批决策上等于 Minimum Overshoot

评分（冻结 λ = 0.5）：

$$R_i=q_i\big[\lambda N_i+(1-\lambda)\min(\text{need},N_i)\big]$$

本数据 `need` ∈ [17, 128]、`N_i` ∈ [460, 813]，`min(need, N_i)` 对每个候选都是同一个常数，
括号只剩 `λ(N_i − need)`，而 `N_i` 的候选间 max/min 仅 1.53：

$$R_i \approx 0.5\,q_i N_i + \text{const}$$

再加上 `q` 与 `N` 在 4/6 决策中 Spearman = **+1.000**，两条轴同向 ⇒ 最小化 `qN` 与最小化 `N` 同解。

**必须区分两种说法**：

- **机制判断**：括号退化为 `λN` 是 `need ≪ N` 的代数结果，对本数据 6/6 成立；
  `q` 与 `N` 同序是这 6 次决策的观察，**不能推广为一般规律**。
- **性能判断**：A1 与 MinOvershoot 的 6/6 一致只说明"在这两个 scenario 的一次 repeat 上一致"，
  **不构成"两者等价"的结论**。

### 1.3 唯一分歧点（HR02 round 55，`idx=10388`）

as-of 复核后数值不变：

| 候选 | N | 链长 m | 受害块深度 | 最浅 `d_min` | 后缀 `S` | q | prefill |
|---|---:|---:|---|---:|---:|---:|---:|
| pylint-dev | 460 | 799 | 17 块，含深度 451 | **451** | **349** | 0.463529 | 0.681184 |
| pytest-dev | 640 | 647 | 17 块，全在最深层 | **631** | **17** | 0.402859 | 0.551567 |

| 规则 | pylint | pytest | 选谁 |
|---|---:|---:|---|
| 冻结 A1 `q×[0.5N+0.5need]` | 110.55 | 132.34 | **pylint** |
| Minimum Overshoot `N` | 460 | 640 | **pylint** |
| **A0** `(deadline, min rank)` | deadline 259.469 | deadline **252.046** | **pytest** |
| 本方案 `q·prefill·S/m` | **0.137918** | **0.005838** | **pytest** |

- `N_pylint/N_pytest = 0.719`，`q_pylint/q_pytest = 1.150`，乘积 **0.827 < 1**：
  N 的 28% 优势压过 q 的 15% 劣势，A1 因此选了**更热、且代价高 20 倍**的那个。
- A0 与 A2 在此 barrier 实际释放的都是 pytest（§5.2 按 `boundary_id` 严格配对确认）。
- 该分歧对应 M1 记录的 **+6320 recomputed tokens**（本脚本未独立复算）。

**代理为什么没对上损失**：pylint 的受害者里有一个位于深度 451 的**浅层块**，
单个这样的块就把 349 块后缀判死。`N`（块数）看不见位置，`q`（仅 elapsed）也看不见。

---

## 2. 现有信息的可用性与缺口

### 2.1 决策时确实可用（本轮已验证可算）

| 信息 | 来源 | 用途 |
|---|---|---|
| `original_free_queue`：`block_id` / `native_lru_rank` / `eligibility_tier` / `has_block_hash` | pressure payload | 判定 `|TIER_1|` 与 `deficit` |
| `required_blocks` | pressure payload | 同上 |
| 候选 `block_ids` / `initially_reclaimable_block_ids` | pressure payload | 受害者集合 |
| `prefill_reload_seconds` | pressure payload | 代价量纲 |
| `retention_deadline_timestamp` | pressure payload | `q` 与 A0 主键 |
| **链条有序块列表 + 内容标识** | 运行时需 `ChainDepthProof`（§6.1.2）；离线用 as-of `VLLM_PREFIX_SNAPSHOT` | `m` 与 `d_min` |
| `history_mode` / `global_server_gap_sample_count` | `TTL_DECISION_OBSERVED` | 历史机制门禁 |

**深度确实需要一份新状态（RC5 修正）**：`RetentionEntrySnapshot.block_ids` 虽然是有序
`tuple[BlockIdentity, ...]`，但它在 `retention.py:144 observe_eviction` 与
`:176 reconcile_entry_evictions` 处会被**压缩**，因此
① 一旦发生内部逐出，剩余块的下标**不再等于**其原始深度；
② `len(block_ids)` 是**存活块数**而非链长 `m`。
v2 此处"深度不需要新状态、下标即深度"的说法错误，已撤回；
正确做法见 §6.1.2 的内容键控 `ChainDepthProof`。
（`A2NativeChainSnapshot` 同时持有 `block_ids` + `content_hashes` + `native_hash_process_id`，
是 `ChainDepthProof` 的直接蓝本。）

### 2.2 Phase 2H 已补齐的观测

`TTL_DECISION_OBSERVED` 现在直接记录 `history_mode`、`reason`、
`global_server_gap_sample_count`、`tool_server_gap_sample_count`、`ttl_decision_timestamp`。
本数据 177 次 TTL 决策中 **76 次为 `tool_specific`**、101 次 `cold_start`。
**历史机制门禁（H）至此可判定**，上一版设计要求的第 1、2 项观测已到位。

### 2.3 存在但本轮无区分度

| 信息 | 观察 |
|---|---|
| 跨 Entry 共享块 | 每对候选恒共享 **7** 块（公共前缀），且 **0/179 个受害者落入该共享前缀** |
| `waiting_followup` | 6/6 决策的全部候选均为 `True` |
| `eta` | 恒 1.0；`queue_delay_t_seconds` 恒 0.0 |

共享前缀这一项在 v4 中被重新测量（`phase2i_m3_evidence.py`）：每个 run 有 **177 条**请求级
prefix 快照，其中恰有 **7** 个内容键出现在**全部** 177 条快照里，即真正的公共前缀；
对 6 次决策的 179 个受害者逐一比对，**0 个**落在该 7 块共享前缀内。
这直接支持 §3.4 假设 3（共享内容外部性未触发），而不再只是断言。

### 2.4 证据分级与缺口（RC7 + RC9：四类主张互不等价）

先固定分级，后文一律按此措辞，**不得混用、不得由前一级推出后一级**：

| 等级 | 含义 | 本轮状态 |
|---|---|---|
| **L1** 预计受害者 | 由冻结资格规则 + `native_lru_rank` 推算 | 可算，6/6 决策 |
| **L2** 真实 Native 逐出 | 归档中真实记录的 `BLOCK_EVICTED`，限定在**同一压力回合窗口**内 | **可观测**，受害者 **179/179** 命中 |
| **L3** 内容身份 | 逐出时的 `native_cache_key_before` 与该链快照在该槽位记录的内容键是否一致 | **可观测**，**179/179** 一致 |
| **L4** 重算代价 | 被逐内容是否真的导致下游 APC miss / 重算 | **不可观测** |

**关键界线**：L3 成立**不等于**归属成立。归档自己在
`VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED` 里写明
`attribution_reason = "native hash identity does not prove logical ownership"`、
`logical_owner_attribution = null`。本轮实测同一内容键同时出现在 **5–31 条**不同
请求前缀中，因此「这个块属于哪条链」在内容层面**原则上不可判定**。
**L3 = 内容身份已证明，归属未证明**。

M3 因此拆成四类主张（v3 曾把它们压成一个"通过/失败"）：

| 主张 | 定义 | 本轮实测 | 说明了什么 |
|---|---|---|---|
| **M3-1** 选择一致 | 项目层 `SelectionPlan` 记录 `last_selected_block_ids` 与 L1 全选择集是否相同 | **1 精确 / 5 不符** | 两个计算之间的一致性；**不是**物理观测 |
| **M3-2** 真实逐出 | L1 受害者是否在窗口内被真实逐出 | **179/179** | 物理发生，但**无归属** |
| **M3-3** 内容身份 | 逐出内容键与链快照记录是否一致 | **179/179** | 内容已确认；**归属不可确认** |
| **M3-4** 重算后果 | 逐出是否导致重算 | **不可观测** | 本轮不谈 |

M3-1 的 5 次"不符"记录规模在同一 run 内恒为 126（hr01）/ 123（hr02），而 `need` 在变
（128/18/17），说明该回调不逐回合写入。**这属回调完整性限制**：
既**不**构成"算法推算错误"的证据，也**不**构成"逐块因果确认"。
因此**不能用 1/6 精确去声明已完成内容级物理因果归因**。

其余缺口：

| 缺口 | 影响 | 严重程度 |
|---|---|---|
| 无"逐出后是否被重取"记录 | `r_i` 不可算；本轮**不对 `r_i` 作任何数值主张** | 结构性，不影响 §3 决策规则（该规则不含 `r_i`） |
| 无 L4（重算后果） | 无法把"逐出"换算成"算力损失" | 结构性；本轮结论不依赖它 |
| 无右删失标记 | 窗口结束时未重取的内容无法区分"不回来"与"还没回来"；因此本轮**不报告任何"未重取"计数或比例** | 结构性 |

> 措辞纪律（RC7/RC9）：上述三行**不得**被引用为"本方案无效"的证据。它们只说明
> "某些量在本归档里不可测"，而不可测的量既不能支持也不能否证任何算法主张。
> 同理，**不得**把 L2 的全命中称作"因果确认"，也**不得**把 L3 的内容一致称作"归属确认"。

---

## 3. 推荐的成本估计与 Entry 决策规则

### 3.1 代价对象

对候选 X：

- $m_X$：该 Entry 链条块数；
- $V_X$：新增 eligible 块中 native rank 最小的 `deficit` 个；
- $d_{\min}(X)=\min\{d_X(b):b\in V_X\}$，受害者中最浅深度；
- $S_X=m_X-d_{\min}(X)+1$ —— 该深度一旦被逐出，整条后缀都需重新 prefill
  （与 A2 冻结链损失语义一致：只有最浅受害者决定损失）。

### 3.2 评分（Prefix-suffix-aware Cost Proxy）

$$\boxed{\;L(X)\;=\;q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X}\;}$$

### 3.3 完整决策规则（= 冻结 A1 阶梯，只替换第 2 步的排序键）

```text
need    = target − |currently eligible|
deficit = max(0, need − |TIER_1|)

Step 1  need <= 0
        冻结 A1：min by (expected_recompute, deadline, key)          ← 不变

Step 2  sufficient = { X : N_X >= need }
        若 sufficient 非空：
          本方案：min by (L(X), deadline_X, key_X)                    ← 唯一改动
          若某些 X 的 L(X) 不可算（深度缺失），整个决策 Fail Closed，
          改用冻结 A1 的 expected_recompute 排序并记录原因

Step 3  positive = { X : N_X > 0 }   （无 sufficient 但有 N>0）
        冻结 A1：min by (per_unit, deadline, key)                     ← 不变

Step 4  全部 N_X == 0
        冻结 A1：pair lookahead（按每单位 relief 的最优二元组）        ← 不变

Step 5  pair 不存在
        冻结 A1：min by (deadline, key)                               ← 不变
```

**为什么只改第 2 步**：Phase 2H 的 6 次决策**全部**满足"所有候选 sufficient"
（`N_i` 最小 460 ≫ `need` 最大 128），即全部走 Step 2。只改这一步，
① 覆盖 100% 已观察决策；② 与冻结 A1 的差异只有一个排序键，可归因；
③ 不改动不足量释放机制，符合 RC4。

**若未来出现 insufficient 候选**：Step 3–5 保持冻结行为，
即本方案在该区间**逐位等价于 A1**。这一点必须写进实现契约，否则一旦 Step 3 也改了，
就无法判断效果来自哪一处。

### 3.4 成本代理的三条假设（RC3，必须随结论一起引用）

| # | 假设 | 后果 |
|---|---|---|
| 1 | **`q` 未做概率校准**：`q = sigmoid((deadline − t)/τ)`，只有"序"有第一性依据 | `L` 不是期望值，只在同一 τ 下可比较；不得解读为概率 |
| 2 | **`prefill` 为线性近似**：按链的 profile 值给出，profile 本身对 token 数近线性 | 绝对秒数不可当实测；同决策内相对比较仍有效 |
| 3 | **共享内容外部性未计**：若两 Entry 共享前缀块，逐出一个会同时降低另一个的重算代价 | 本数据共享块恒为 7 且不落入受害者窗口，故未触发（§2.3） |

$$\text{因此 } L \text{ 是 **Prefix-suffix-aware Cost Proxy**，不是已校准的期望重算时间。}$$

### 3.5 与 `q × S` 的关系（RC6：`prefill/m` 只是本负载下的近似常数，不是严格常数）

**先写严格条件，再说近似。** `L` 与对照方案（记为 A0，即只按 `q × S` 排序的键）在候选
$X,Y$ 上产生不同排序，当且仅当

$$\frac{q_Y\cdot\text{prefill}_Y\cdot S_Y}{m_Y}<\frac{q_X\cdot\text{prefill}_X\cdot S_X}{m_X}$$

这是**唯一的**分歧判据，任何"二者等价"的说法都必须回到这条不等式。
`q × S` 只有在 `prefill/m` 对两候选完全相等时才与 `L` 同序；把 `prefill/m` 约掉的每一步
都是一个**近似**，不是恒等变形。

**为什么在本负载下该近似很紧**：profile 对 token 数近线性，而块数 ∝ token 数，所以
`prefill_X / m_X` 在一个决策内近乎常数。Phase 2H 实测的 `prefill/m` 候选间 **max/min 跨度**：

| scenario | idx | prefill/m 跨度 |
|---|---|---:|
| hr01-balanced-gap | 2170 | 1.1421 |
| hr01-balanced-gap | 4244 | 1.0991 |
| hr01-balanced-gap | 7305 | 1.0811 |
| hr02-short-gap-long-context | 2166 | 1.0706 |
| hr02-short-gap-long-context | 4384 | 1.0309 |
| hr02-short-gap-long-context | 10388 | **1.0001** |

于是可以把 `L` 读作

$$L(X)=q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X}=q_X\,S_X\cdot\underbrace{\frac{\text{prefill}_X}{m_X}}_{\approx\,c\ (\text{跨度}\le 1.14)}\;\approx\;c\cdot q_X\,S_X$$

**必须同时说清的三件事**：

1. **`q × S` 是本负载下的近似解释，不是等价式。** 跨度最大 1.1421 意味着 `prefill/m`
   可以把一次 `q×S` 排序的边际（例如 1.150 vs 1.000 的比值差）放大或缩小到 1.14 倍；
   只有当比值差本身超过约 14% 时，`L` 与 `q×S` 才**不可能**给出不同排序。
2. **`prefill` 与 `m` 不是"新的判别维度"。** 在本负载下它们的扰动幅度只有 14% 量级，
   所以本轮 6 次决策上的排序**恰好**与 `q×S` 一致（§5.1、§5.3）。这是观察，不是定理。
3. **口径纪律。** 若某次比较的 `q×S` 比值差 < 14%，则必须回到完整不等式判分歧，
   **不得**因为"`prefill/m` 近似恒定"就宣布"与 A0 完全等价"。

**结论**：推荐实现 `L`（保留量纲、profile 变化时自动适应）；分析判别力时用 `q·S` 作为
一阶近似，且必须附带上述 14% 的精度声明。任何声称"用了 prefill 与 m 所以更强"的说法
都站不住，任何声称"只要 `S` 恒定就与 A0 严格等价"的说法同样站不住。

> **由此得到一个可检验预测**：若某个 workload 的 profile 对块数严重非线性
> （例如长短 prompt 混用导致同块数不同 prefill），`prefill` 项才会成为活跃通道。
> 本数据不是这种情形。

不新增参数、不训练模型、不引入可调权重。

---

## 4. 与三条基线的结构性区别（RC1 修正）

先纠正 v1 的基线描述：

| 层 | 规则 | 定义 | 来源 |
|---|---|---|---|
| **Block Eviction** | Native LRU | 按 `lru_rank` 逐出块。**不选择 Entry** | vLLM APC 内部 |
| **Entry Release** | **A0** | `(deadline, min native_lru_rank over newly eligible, identity)` | `continuum/pressure.py::_release_sort_key` → `costaware/replay.py::ExecutedP1BStrategy` |
| **Entry Release** | 冻结 A1 | `q·[λN+(1−λ)min(need,N)]` | `costaware/a1_entry.py` |
| **Entry Release** | MinOvershoot | `N_i` | 消融基线 |
| **Entry Release** | EarliestDeadline | `deadline` | 消融基线 |

> **A0 是 Continuum 的 deadline 规则，不是"选最冷 Entry"。** 它确实用 native rank，
> 但只作为 **deadline 相同时的次级键**。Native LRU 属于 Block 层，不参与 Entry 选择。

| 维度 | A0 | MinOvershoot | 冻结 A1 | **本方案** |
|---|---|---|---|---|
| Entry 排序主键 | `deadline` | `N_i` | `q·[λN+(1−λ)min(need,N)]` | `q·prefill·S/m` |
| 次级键 | `min native rank` | identity | `deadline` | `deadline` |
| 用 Chain Depth | 否 | 否 | 否 | **是（`d_min`）** |
| 用 prefill 代价 | 否 | 否 | 否 | **是** |
| `N` 的作用 | 无 | 代价 | 主项 | **仅可行性闸门** |

**结构性区别的关键一条**：受害者块数在合法决策里恒为 `deficit`，
任何以 `N` 为主轴的规则都在优化一个与伤害无关的量。本方案把注意力移到
"受害者在链条中的位置"，这是三者都没有用的维度。

---

## 5. 离线快照上的决策差异与证据边界

### 5.1 六次决策经严格 as-of 复核后的选择表（RC2）

复核规则：快照必须 `event_index < 决策 index`，且 `(program_id, prefix_id)` 精确匹配；
任一预计受害块的深度不可恢复即整条决策 Fail Closed。

| scenario | idx | barrier | need | deficit | 可评分候选 | A1 实际释放 | A0 | MinOvershoot | EarliestDL | **本方案** |
|---|---|---:|---|---:|---|---|---|---|---|---|
| hr01-balanced-gap | 2170 | round-40 | 126 | 33 | 3/3 | django | django | django | django | django |
| hr01-balanced-gap | 4244 | round-50 | 128 | 50 | 3/3 | django | django | django | django | django |
| hr01-balanced-gap | 7305 | round-55 | 128 | 56 | 3/3 | django | django | django | django | django |
| hr02-short-gap-long-context | 2166 | round-40 | 128 | 6 | 3/3 | pytest | pytest | pytest | pytest | pytest |
| hr02-short-gap-long-context | 4384 | round-50 | 18 | 17 | 2/2 | pytest | pytest | pytest | pytest | pytest |
| hr02-short-gap-long-context | 10388 | round-55 | 17 | 17 | 2/2 | **pylint** | pytest | pylint | pytest | **pytest** |

**Fail Closed 统计**：6 次决策，**0 次**因深度缺失被排除。
as-of 复核后的 `d_min`、`S`、规则选择与 v1 **完全一致** —— 说明 v1 使用末条快照
在这 6 次决策上恰好未引入未来信息，但**方法上不安全**，已改为按 index 查询。

> **RC9 注记**：本表的 `barrier` 列对 hr01 是**已校验的配对结果**，对 hr02 仅为
> **标签**——hr02 的屏障配对未通过计数器链检查，已整 run 排除（§5.2）。
> 本表所有行（含 hr02）的结论来自 `FORCED_RELEASE_DECISION` 自身携带的
> `original_free_queue` / `candidates` / `selected_releases` 与 as-of 快照，
> **不依赖屏障配对**，因此不受该排除影响。

一致率（与 A1 实际释放）：

| 规则 | 一致 |
|---|---|
| Minimum Overshoot | 6 / 6 |
| A0（deadline 规则） | 5 / 6 |
| Earliest Deadline | 5 / 6 |
| **本方案（Cost Proxy）** | **5 / 6** |

### 5.2 跨臂对照（RC9：屏障配对先过检查，再谈匹配）

RC9 的计数器链检查**推翻了 v3 对 hr02 的跨臂结论的可信度**：

| scenario | barrier | `before` | `after` | 计数器链 |
|---|---|---:|---:|---|
| hr01 | round-40 | 0 | 1 | OK |
| hr01 | round-50 | 1 | 2 | OK |
| hr01 | round-55 | 2 | 3 | OK |
| hr02 | round-40 | 0 | 1 | OK |
| hr02 | round-50 | **2** | **2** | **断链 + 未消耗释放** |
| hr02 | round-55 | **3** | **3** | **断链 + 未消耗释放** |

hr02 的三次 completion 中，后两次的计数既不等于上一次的 `after`（2 ≠ 1，3 ≠ 2），
且 `after == before`（未消耗任何 forced release）。v3 使用的
`after == position + 1` 检查在这里**恰好误通过**——这正是 RC9 要求换成
before/after 语义的原因。

按 RC9 的 Fail Closed 要求，**hr02 整 run 排除在屏障级跨臂对照之外**。
排除后可由 `boundary_id` 严格匹配的只有 hr01：

| scenario | barrier | A0 | A1 | A2 | 结论 |
|---|---|---|---|---|---|
| hr01-balanced-gap | round-40 | django | django | django | 一致 |
| hr01-balanced-gap | round-50 | django | django | django | 一致 |
| hr01-balanced-gap | round-55 | django | django | django | 一致 |
| hr02-short-gap-long-context | round-40/50/55 | — | — | — | **EXCLUDED（配对未通过）** |

**三点必须同时说明（不得省略任何一点）**：

1. hr02 的**区间**条件其实成立：`2166 < 2430 < 4384 < 5296 < 10388 < 11200`，
   每个 release 都严格落在唯一一个 completion 区间内，配对在顺序上无歧义；
2. 失败的是**计数器**不变量，原因未知（可能是计数器来源不同或存在未记录的内部释放），
   本轮**不推测原因**；
3. 因此 v3 中"唯一分歧位于 HR02 round 55"这句话**不能再由屏障配对支撑**。
   该分歧本身仍然成立，但依据是 `FORCED_RELEASE_DECISION.payload.selected_releases`
   直接记录的选择（§1.3），**不依赖**屏障配对。这一点必须写清，否则会把一个
   决策级事实误挂在一个已失效的配对论证上。

### 5.3 本方案与各基线可能分歧的**真实**条件（RC1 修正）

v1 声称"只有最冷 Entry 带浅层冷块才可能分歧"—— **这是错的，且不是必要条件**。
正确推导：

在固定决策时刻，`q = sigmoid((deadline − t)/τ)` 对 `deadline` **严格单调递增**。
因此 `argmin deadline` ⇔ `argmin q`：A0 选的是**最小 deadline**，也就是**最小 q**
（即最接近到期、最该放手的那个）。

设 X 是 A0 的选择（`deadline_X` 最小 ⇒ `q_X` 最小），Y 是任一 `deadline_Y > deadline_X`
的候选（⇒ `q_Y > q_X`）。本方案偏离 A0 当选 Y，条件是

$$q_Y A_Y<q_X A_X
\iff \frac{A_Y}{A_X}<\frac{q_X}{q_Y}<1,\qquad A=\text{prefill}\cdot\frac{S}{m}\approx c\,S$$

即：**后 deadline 者的 `A` 必须比先到期的那个按比例更小**，且小到能抵消它在 `q` 上的劣势。

三个**形式上**的独立通道 —— 但在实测 profile 下强弱极不对称：

| 通道 | 是否活跃 | 依据 |
|---|---|---|
| **S 更小**（`d_min` 更大） | **是唯一活跃通道** | `S` 在候选间的跨度可达 349/17 ≈ **20.5×** |
| `m` 更大 | **≈ 惰性** | `m` 与 `prefill` 相消，`prefill/m` 候选间跨度仅 1.0001–1.1421（§3.5） |
| `prefill` 更小 | **≈ 惰性** | 同上，属同一比值 |

**因此准确的表述是**：在近线性 profile 下，本方案与 A0 的分歧**主要由 `S` 承担**，
更精确地说由 `d_min` 承担。**但判据必须写成完整不等式（RC6）**：

$$\text{proxy}\ne\text{A0}\iff \exists Y:\ \frac{q_Y\cdot\text{prefill}_Y\cdot S_Y}{m_Y}<\frac{q_{X^*}\cdot\text{prefill}_{X^*}\cdot S_{X^*}}{m_{X^*}}\ \text{且}\ q_Y>q_{X^*}$$

把 `prefill/m` 约掉后的简化形式

$$\frac{q_Y S_Y}{q_{X^*} S_{X^*}}<\underbrace{\frac{\text{prefill}_{X^*}/m_{X^*}}{\text{prefill}_Y/m_Y}}_{\in[1/1.1421,\ 1.1421]}$$

只是把上式的常数因子收到一侧，**是近似而非等价**：当 `q·S` 的比值落在 1 附近
±14% 的带状区间内时，两个判据会给出不同结论，此时必须以完整不等式为准。
因为 `q_{X*}` 是最小 q，上式要求 **`S_{X*} > S_Y` 且超出比例足以抵消 q 差与该 14% 带**。即：

> **本方案与 A0 分歧 ⟺ A0 会选的那个 Entry（最早 deadline）恰好带着最长的后缀
> （即它的受害块里有浅层块），且该劣势超过它在 q 上的优势（按完整不等式判定）。**

这正是 RC1 要求修正的地方：v1 把它写成"最冷 Entry 带浅层冷块"，
**"最冷"是错的**（A0 不是按冷度选 Entry），而且 v1 还断言这是"必要条件"——
在**几何完全相同的决策**里两者必然一致，这一半是对的；但在 `S` 变化时，
分歧依赖的是完整不等式的比值，**不只是"是否带浅层块"这个布尔量**。
RC6 补充：**`S` 恒定不足以推出等价**，因为 `prefill/m` 仍可差到 1.14 倍。

**与 MinOvershoot 分歧的条件**：存在 X、Y 使 `N_X < N_Y` 但 `L_Y < L_X`（完整不等式）。
通道数为三个（`q`、`S`、以及 `N` 本身与二者无关），因为 MinOvershoot 完全不用 `q` 与 `S`。

**与冻结 A1 分歧的条件**：`q_X[\lambda N_X+(1-\lambda)\min(need,N_X)]` 与 `q_X S_X` 的
argmin 不同。在 `need ≪ N` 的区间，前者 ≈ `0.5 q_X N_X`，故分歧条件近似为
`N` 的排序与 `S` 的排序相反且幅度足够。

### 5.4 本轮的判别力边界（不夸大、不过度否定）

**可以说的**：

- 6 次决策中本方案与 A0 的选择 **6/6 相同**，因此**本轮数据无法区分二者**（更精确的说明见 §5.5）；
- 本方案与 A1 在 1 次决策上分歧，且该次正是 A1 被判为出错的一次。

**不能说的**：

- ❌ "本方案优于 A0" —— 没有一次决策能区分；
- ❌ "本方案优于 A1" —— 一次分歧只说明"不与已知错误一致"，不是收益证据；
- ❌ "本方案无效" —— 6 次决策只能支持"本轮不具判别力"，不能支持性能结论。

### 5.5 在 A0 当前选中项几何不变的前提下，这 6 次决策上分歧是**结构上不可能**的

**先声明前提（RC6 必须）**：本小节的结论限定在
**「A0 选中项 $X^*$ 的块几何与 `q`、`prefill`、`m` 保持本次快照的取值」** 这一前提下。
若 $X^*$ 自身的后缀发生改变（例如它的受害块被换成浅层块），下界论证**不再成立**，
因为那时右侧的 $L(X^*)$ 本身也会变大。因此本小节说的是：

> 在 $X^*$ 已确定的条件下，**其余候选无论块怎么摆放**都无法反超 $X^*$ 的当前取值。

**不**意味着"本方案与 A0 在任何几何下都等价"，也**不**意味着"只要 $S$ 恒定就等价"（见 §3.5、§6.3）。

理由：`S ≥ |V_X| = deficit`（受害者是链内互异深度的 `deficit` 个块，故
`d_min ≤ m − deficit + 1`，于是 `S ≥ deficit`）。所以每个候选的 proxy 有一个下界：

$$L_{\min}(X)=q_X\cdot\text{prefill}_X\cdot\frac{|V_X|}{m_X}$$

若 `L_min(Y) > L(X*)`，则在 $X^*$ 取值固定的前提下，候选 Y **无论块怎么摆放都不可能**胜出。
实测（§复现输出第 5 段）：

| scenario | idx | A0 选中（proxy） | 其余候选的 `L_min` | 结果 |
|---|---|---:|---|---|
| hr01 | 2170 | django 0.005341 | mwaskom 0.014554 / sympy 0.007683 | 不可能偏离 |
| hr01 | 4244 | django 0.018032 | mwaskom 0.021375 / sympy 0.018716 | 不可能偏离 |
| hr01 | 7305 | django 0.022321 | mwaskom 0.023660 / sympy 0.022616 | 不可能偏离 |
| hr02 | 2166 | pytest 0.000124 | pydata 0.002520 / pylint 0.000555 | 不可能偏离 |
| hr02 | 4384 | pytest 0.005272 | pylint 0.006810 | 不可能偏离 |
| hr02 | 10388 | pytest 0.005838 | pylint 0.006718 | 不可能偏离 |

**判读纪律（RC6）**：把每行的最小裕度 `min(L_min(Y))/L(X*) − 1` 与 §3.5 的 14% `prefill/m` 带比较：

| scenario | idx | 最小裕度 | 是否超过 14% 带 | 可表述为 |
|---|---|---:|---|---|
| hr01 | 2170 | 43.8%（sympy） | 是 | 对该带稳健的"不可偏离" |
| hr01 | 4244 | **3.8%**（sympy） | **否** | 仅"当前 `prefill` 取值下不可偏离" |
| hr01 | 7305 | **1.3%**（sympy） | **否** | 仅"当前 `prefill` 取值下不可偏离" |
| hr02 | 2166 | 348%（pylint） | 是 | 对该带稳健 |
| hr02 | 4384 | 29.2%（pylint） | 是 | 对该带稳健 |
| hr02 | 10388 | 15.1%（pylint） | 是（勉强） | 对该带稳健，但裕度有限 |

即 **6 次中有 2 次（4244、7305）的驻留裕度小于 `prefill/m` 带**，因此"结构上不可能"
的结论在这 2 次上**只对当前 `prefill` 取值成立**，不对 `prefill` 波动稳健。
这是 RC6 要求保留的精度声明，不得省略。

**机理**：A0 选的那个 Entry 恰好同时具有最小的 `q` **和**最小的 `prefill/m` 足迹，
所以它在完整不等式上天然占优；`S` 唯一能起作用的两次（4384、10388）
也恰好与 q 的不利方向一致（pylint 的 `S` 大且 `q` 大，两头都输）。

**这对下一轮 replay 是明确的判据**：要让本方案与 A0 可区分，必须出现

> **最早 deadline 的 Entry 带着最长的后缀**（其受害块含浅层块），
> 而另一个 deadline 更晚的 Entry 的后缀明显更短。

本轮 0/6。这是设计下一轮 workload 时必须直接瞄准的结构，
而不是"多跑几次看看有没有分歧"。

---

## 6. 最小实现方案与停止条件

### 6.1 在线所需的最小状态（RC4 + RC5 修正）

#### 6.1.1 先撤回 v2 的一个错误前提

v2 的 §6.1 写的是「`entry.block_ids` 下标即 Prefix Depth，`m_X = len(entry.block_ids)`」。
**这个前提是错的**，本轮已在冻结代码中确认：

- `src/kvopt/continuum/retention.py:144`（`observe_eviction`）
- `src/kvopt/continuum/retention.py:176`（`reconcile_entry_evictions`）

两处都用 `tuple(block for block in entry.block_ids if block not in evicted)` 之类的写法
**直接压缩 `block_ids` 元组**。后果有两条，都会直接毁掉 `d_min` 与 `S`：

1. **下标漂移**：一条 6 块链的深度 3 被淘汰后，剩余块在新元组中的位置是 3,4,5，
   但它们真实的深度是 4,5,6。若按下标取深度，`d_min` 会被系统性低估 1。
2. **长度不再是 `m`**：`len(entry.block_ids)` 是**当前存活块数**，不是链的历史长度。
   `S = m − d_min + 1` 中的 `m` 一旦取成活块数，后缀长度会被系统性低估。

因此 **`RetentionEntrySnapshot.block_ids` 结构上不足以提供深度**，
不是实现细节问题。v2 的这张表作废，替换为下面 6.1.2 的契约。

#### 6.1.2 替换方案：内容键控的 `ChainDepthProof`

不改变 Native BlockPool 与 Eviction Ownership，只在**项目层增加必要元数据**：
在观察到一条链的时刻，把「真实深度」与「完整链长」一次性固化下来，
之后**永不按位置推测**。

```python
@dataclass(frozen=True, slots=True)
class DepthQuery:
    chain_id: tuple[str, str]              # 查询方所属的链
    native_hash_process_id: str            # 查询方所属的 native 哈希进程
    decision_at: float                     # 该深度将被用于的时刻

@dataclass(frozen=True, slots=True)
class ChainDepthProof:
    chain_id: tuple[str, str]              # (program_id, prefix_id)
    native_hash_process_id: str            # 该快照所属的 native 哈希进程
    block_ids: tuple[int, ...]             # 观测时刻的链内块，按深度升序
    content_hashes: tuple[str | None, ...]  # 与 block_ids 逐位对齐
    depths: tuple[int, ...]                # 权威深度，1..n，逐位对齐
    observed_at: float
    max_age_seconds: float = 600.0

    @property
    def chain_length(self) -> int:
        """m。取自记录，永远不等于当前存活块数。"""
        return len(self.depths)

    @property
    def identity_verified(self) -> bool:
        """任一槽位缺少可用内容标识时为 False。"""

    def depth_of(self, query: DepthQuery, block_id: int, content_hash: str
                 ) -> tuple[int | None, DepthStatus]:
        """按 chain → process → 时间 → 内容 → 槽位的顺序逐项校验。"""

    def depths_for(self, query: DepthQuery, victims, live_hashes
                   ) -> tuple[dict[int, int], dict[int, DepthStatus]]:
        """返回 (已解析, 无法解析→原因)；后者非空即整次决策 Fail Closed。"""
```

这个结构并非新发明：冻结的 `A2NativeChainSnapshot` 已经同时携带
`block_ids` + `content_hashes` + `native_hash_process_id`，本方案只是把
`depths` 一并固化，并把**查询方式从「按下标」改为「按（block_id, content_hash）双键」**。
RC8 又补上了此前只存不验的三项：链身份、进程身份、时效。

#### 6.1.3 九条必须成立的性质（RC5 + RC8，均已可执行验证）

| # | 性质 | 失败后果 | 契约检查 | 结果 |
|---|---|---|---|---|
| P1 | 内部逐出不导致深度漂移 | `d_min` 低估 → `S` 高估 → 选错 | `check_partial_eviction_does_not_drift_depth` | PASS |
| P2 | block id 回收不继承旧深度 | 复用槽位拿到过期深度 → 乐观偏差 | `check_recycled_block_id_does_not_inherit_depth` | PASS |
| P3 | 无法验证的深度单独上报，不被静默丢弃 | 悄悄少算受害者 → 假阴性 | `check_resolution_reports_unresolvable_separately` | PASS |
| P4 | 后缀用记录链长而非存活块数 | `S` 系统性低估 | `check_suffix_uses_recorded_length_not_live_count` | PASS |
| P5 | 退化几何可被识别 | 把 `S=1` 的极深受害者误当无害 | `check_degenerate_geometry_is_detected` | PASS |
| P6 | **查询须属同一 Native Process 与 Chain** | 跨链/跨进程借用到他人深度 | `check_query_must_match_chain_and_process` | PASS |
| P7 | **证明须早于决策且未过期** | 用未来或陈旧观测为当下定价 | `check_proof_must_precede_decision_and_stay_fresh` | PASS |
| P8 | **内容标识缺失 ⇒ `IDENTITY_UNVERIFIED`** | 只有深度就冒充已验证身份 | `check_missing_content_identity_is_unverified_not_ok` | PASS |
| P9 | 归档形状的证明可自洽还原 | 离线构造与运行时语义不一致 | `check_archive_shaped_proof_round_trips` | PASS |

**可执行证明**：`python scripts/probes/entry_costaware_audit/phase2i_depth_contract.py`
→ `all contract checks passed`，**9/9 PASS**。该文件同时充当最小单元测试：

- P1 用例：6 块链（深度 1..6），淘汰深度 3；**逐个断言**存活块 13/14/15 的深度是
  **4/5/6** 而非数组位置 3/4/5，并反向检查"恰有 3 个块的深度不等于其下标"。
- P2 用例：槽位 21 被写入内容 `"zz"` → 状态必须是 `CONTENT_MISMATCH` 且深度为 `None`；
  用原内容 `"a2"` 查询 → `(2, OK)`。
- P3 用例：受害者 99 内容未知 → 必须出现在 `unresolved` 且原因为 `UNKNOWN_BLOCK`。
- P4 用例：10 块链中淘汰 4 块，从深度 5 起的后缀按记录算 **5**，按存活块数算只有 **2**。
- P6 用例：换成 `("program-f","prefix-OTHER")` → `WRONG_CHAIN`；
  换成 `pid-B` → `WRONG_PROCESS`；两者都必须返回 `None`。
- P7 用例：`decision_at=999 < observed_at=1000` → `FUTURE_PROOF`；
  `decision_at − observed_at = max_age + 1` → `STALE_PROOF`；
  恰好等于 `observed_at` 与恰好等于 `max_age` 都必须**仍然可用**（边界不误杀）。
- P8 用例：`content_hashes=("g1", None, "g3")` → `identity_verified=False`，
  两个受害者都解析失败且原因保留为 `IDENTITY_UNVERIFIED`。
- P9 用例：按 `VLLM_PREFIX_SNAPSHOT` 形状（`block_ids` + `ordered_native_cache_keys` +
  `native_hash_process_id`）构造，内部逐出后块 84 必须仍是深度 5。

#### 6.1.4 身份与时效校验（RC8 的核心要求）

存储而不校验等于没有约束。`depth_of` 按固定顺序逐项判定，**每一项都返回单一原因**，
以便把"为什么不可评分"如实上报，而不是笼统地置空：

| 序 | 检查 | 不通过时的状态 |
|---|---|---|
| 1 | `query.chain_id == proof.chain_id` | `WRONG_CHAIN` |
| 2 | `query.native_hash_process_id == proof.native_hash_process_id` | `WRONG_PROCESS` |
| 3 | `query.decision_at >= observed_at`（证明不得来自未来） | `FUTURE_PROOF` |
| 4 | `decision_at − observed_at <= max_age_seconds` | `STALE_PROOF` |
| 5 | `proof.identity_verified`（该证明具备可用内容标识） | `IDENTITY_UNVERIFIED` |
| 6 | 槽位存在且内容键一致 | `UNKNOWN_BLOCK` / `CONTENT_MISMATCH` |
| — | 全部通过 | `OK`，并返回真实深度 |

**时效上限的性质**：`max_age_seconds` 是**正确性上限，不是调参旋钮**。它约束的是
"这条证明是否仍描述同一条链"。更强、更结构化的要求（证明必须是该链在决策前
**最近一次**观测）由调用方在取 proof 时保证（离线等价于 `asof_chains` 的
`event_index < 决策 index` 语义）。两者都满足才可解析。

**关于 `IDENTITY_UNVERIFIED`（RC8 明确允许的降级）**：若离线事件不足以完成内容身份
校验，则必须标记为 `IDENTITY_UNVERIFIED` 并 Fail Closed，**不得**退化为"只看深度"。
本轮实测归档内容键**齐全**（`VLLM_PREFIX_SNAPSHOT.ordered_native_cache_keys` 与
`block_ids` 逐位对齐），因此该降级路径**未被触发**；它仍然必须实现，
因为静默退化会让内容复用重新变成不可检测的风险。

#### 6.1.5 Fail Closed 契约

> **任何一个受害者的深度无法解析——链或进程不符、证明来自未来、证明已过期、
> 内容标识缺失、内容不匹配、或该块不在观测记录内——整次决策即不可评分**；
> 此时回落到冻结 A1 排序，并记录**具体原因码**，**不得猜测、不得按下标兜底、
> 不得只算能算的那部分**。

理由：部分解析会产生一个**偏小**的 `S`，而偏小的 `S` 会让该候选看起来更便宜，
从而系统性地偏向"深度信息缺失"的候选。宁可回落到基线，也不能让缺失信息变成优势。
同理，**不得**把"证明过期但仍能返回一个数"当作可用证据——那正是 RC8 指出的漏洞。

#### 6.1.6 状态来源汇总

| 状态 | 来源 | 是否新增 |
|---|---|---|
| `ChainDepthProof`（含 `depths`、`chain_length`、`observed_at`、`max_age`） | **项目层新增元数据**，观测链时固化 | **是**，但**不改动 Native BlockPool / Eviction Ownership** |
| `DepthQuery`（`chain_id` / `native_hash_process_id` / `decision_at`） | 决策点当场的身份与时间 | 仅查询参数 |
| `block_id → native_lru_rank` | `EligibilityPreparation.original_free_queue` | 否 |
| `\|TIER_1\|` | 同一队列按 `eligibility_tier == 0` 计数 | 否 |
| 候选 `newly_eligible_block_ids` | `PressureReleaseEffect` | 否 |
| 候选 `prefill_reload_seconds` | 决策时已有 | 否 |
| `deadline` | `RetentionEntrySnapshot.deadline_timestamp` | 否 |
| **日志新增**：`deficit / V_X / d_min / m / S / L(X) / unresolved(含原因码)` | 决策点计算 | 仅日志 |

**结论**：新增的只有一份**只读的深度证明**，不引入新的淘汰权、不改 Native 状态机，
也不触碰 `src/kvopt/continuum/*`。v2 中"不需要任何新状态"的说法不成立，已撤回。

### 6.2 时间复杂度

设 `|Q|` = free queue 长度，`k` = 候选数，`m` = 最大链长，`d` = `deficit`。

| 步骤 | 复杂度 | 说明 |
|---|---|---|
| 统计 `|TIER_1|`、构建 `rank_of` | `O(|Q|)` | 每决策一次 |
| 取每候选的 `V_X` | `O(k·|N_X|)` 或 `O(k·d)`（若队列已按 rank 有序） | 依赖实现 |
| 每候选 `depth_of` | `O(k·m)` | 可优化为只查 `d` 个块：`O(k·d·m)` 最坏，或用一次性映射 `O(k·m)` |
| `d_min` / `S` / `L` | `O(k·d)` | |

**总计 `O(|Q| + k·m)`**，与现有评分同阶（现有评分已需 `O(|Q|)` 建队列）。
`|Q| ≈ 1100–1900`、`k ≤ 3`、`m ≤ 800`，单次决策的额外开销在微秒量级，
相对 `prefill_reload` 的毫秒级不构成负担。

### 6.3 失败停止条件（出现即停，不追加 run、不调参）

| # | 条件 | 证据等级 | 含义 |
|---|---|---|---|
| 1 | `deficit ≠ max(0, need − \|TIER_1\|)` | L1 | 资格规则理解错误，整个代价模型失效 |
| 2 | 在**同一压力回合内**，推算的受害者集合与 `last_selected_block_ids` **逐块不一致** | L3 | 推算规则错误；本方案全部代价建立在其上。**证据缺席不算触发**，见下 |
| 3 | 全部决策**实际 Score / Selection 无法区分**本方案与 A0 | L1 | 本负载上不可区分。**`S` 恒定既不是充分条件也不是必要条件**，见下 |
| 4 | 任一候选 `prefill_reload` 缺失或为 0 | L1 | 代价量纲失效 |
| 5 | 任一受害者深度在 `ChainDepthProof` 中不可解析 | L1 | Fail Closed（§6.1.5）：该决策回落冻结 A1 并记录**原因码** |
| 6 | 屏障配对任一检查失败：数量 / 区间 / 计数器链 / `boundary_id` 唯一 / `stage_id` 唯一 | L2 | 跨臂对照不可信，**整 run 排除** |

**条件 2 的证据纪律（RC7 + RC9）**：四类情况必须分开，不可混为一谈。

| 情况 | 判读 | 本轮实测 |
|---|---|---|
| **M3-1** Selected Victim Agreement（L1↔项目层记录） | 两个计算之间的一致性，**不是**物理观测 | 1 精确 / 5 不符 |
| **M3-2** Native Eviction（L2） | 物理逐出，但**无归属** | 179/179 窗口内命中 |
| **M3-3** Content Identity（L3） | 内容身份已证明，**归属仍未证明** | 179/179 内容键一致 |
| **M3-4** Downstream Recompute（L4） | 不可观测 | 无数据 |

> **条件 2 的判据取自 M3-1**，而 M3-1 在本轮为 **1 精确 / 5 不符**。
> 这 5 次的原因是回调字段在同一 run 内规模恒定（126 / 123），与当次 `need` 变化不对应，
> 属**回调不完整**。因此本轮**不把条件 2 判为通过，也不判为失败**，标记为
> `M3-1 partially verified`，并把"该回调改为逐回合写入"列为下一轮工程项。
>
> 三条禁令（RC9 明确要求）：
> 1. **不得**把"回调不完整"解释成"推算错了"；
> 2. **不得**把 M3-2 的窗口内全命中（179/179）称作"内容级物理因果归因"——
>    它只说明这些块确实被逐出，不说明它们是被**本次释放**逐出的；
> 3. **不得**把 M3-3 的内容键一致（179/179）称作"归属确认"——
>    归档自己写明 `native hash identity does not prove logical ownership`，
>    且同一内容键同时出现在 5–31 条不同请求前缀中。
>
> 特别地：**1/6 精确不能被表述为"已完成内容级物理因果归因"**。
> 它能支持的最强结论是"这一次的两个 SelectionPlan 计算一致"。

**条件 3 的判定必须基于可区分性，而非 `S` 是否恒定（RC6）**：

v2 把条件 3 写成"全部决策 `S_X = |V_X| = deficit`"，并据此宣布"与 A0 完全等价"。
**这是错的**，理由有二：

1. `S` 恒定只让 `q·S` 退化为 `q·const`，`L` 中仍有 `prefill/m` 因子；
   该因子在候选间可差 **1.14 倍**（§3.5），足以翻转 `q` 上的微小差距。
   因此 **`S` 恒定 ⇏ 与 A0 等价**。
2. 反之，`S` 有变化也**不保证**能区分——若变化的幅度小于 `q` 差与 `prefill/m` 带之和，
   两个选择的 Score 仍可能落在同一分辨极限内。

因此条件 3 的正确形式是：

> **逐次决策检查 `argmin L` 与 `argmin L_{q·S}`（以及 A0 的实际选择）是否可区分。**
> 只有当**所有**决策的候选中，完整不等式的差值都严格落在
> `|ΔL| / L` 小于数值/观测分辨极限的区间内时，才判"不可区分"。
> 一旦存在某次决策可区分而选择仍相同，则不属于条件 3，而属于条件 4 的负载选择问题。

条件 3 的定位不变：它是**结论**（"该负载不适用"），不是调参信号。

**条件 3 与 4 的区别**：Score 可区分但结果仍与 A0 一致（条件 4）说明**该批决策的
`q` 与 `S` 方向恰好相反**，是负载选择问题；Score 本身不可区分（条件 3）
说明**代价对象在该负载上退化**，是更深一层的问题。两者都不应通过改公式解决。

**条件 6 的判定细节（RC9）**：`barrier_for()` 按顺序检查五项，任一失败即整 run 排除。

| 序 | 检查 | 本轮结果 |
|---|---|---|
| 1 | **数量**：`len(releases) == len(completions)` | 6/6 通过 |
| 2 | **区间**：`previous_completion < release < current_completion` | 6/6 通过 |
| 3 | **计数器链**：`before == 上一 completion 的 after` 且 `after == before + 1` | **hr01 3/3 通过；hr02 1/3 通过** |
| 4 | **`boundary_id` 唯一且非空** | 6/6 通过 |
| 5 | **`stage_id` 唯一且非空** | 6/6 通过 |

hr02 的失败明细：`round-50` 为 `before=2, after=2`，`round-55` 为 `before=3, after=3`，
且 `round-40` 的 `after=1` 与 `round-50` 的 `before=2` 之间缺一次增量。
v3 使用的 `after == position + 1` 在 hr02 上**恰好全部成立**，因此完全掩盖了这个缺陷——
这就是 RC9 要求改为 before/after 语义的直接原因。

**结论**：hr02 整 run 排除在**屏障级**跨臂对照之外（§5.2）。注意其**区间**条件其实成立，
配对在顺序上无歧义；失败的是计数器不变量，本轮**不推测其原因**。
按 RC9 的 Fail Closed 要求，"无法验证"必须按"不可用"处理，不能按"可接受"处理。

### 6.4 明确不做

- 不引入 `r_i`（缺口未补）、不做多信号组合、不改 τ / λ / `need` / `N` 语义；
- 不改 Step 1、3、4、5 的任何行为；
- 不在 cold-start 未激活的场景上评估；
- 不通过反复换公式挑正向结果。

---

## 7. 机制 Smoke 判据（可验证，RC7：逐门标注证据等级）

| 门禁 | 判据 | 证据等级 | 类型 |
|---|---|---|---|
| **H** 历史机制 | `TTL_DECISION_OBSERVED` 中至少一个决策 `global_server_gap_sample_count > 100` 且 `history_mode ≠ cold_start`；可用记录历史复现记录的 `ttl_seconds` | L1 | 硬门禁 |
| **M1** 资格一致 | `deficit` 与 `V_X` 可由 `original_free_queue` + `newly_eligible_block_ids` 复算一致（±0） | L1 | 硬门禁 |
| **M2** 深度可解 | 每个 `V_X` 的块都能在 `ChainDepthProof` 中以 `(block_id, content_hash)` 解析出深度；缺失即 Fail Closed 并计入 `unresolved` | L1 | 硬门禁 |
| **M3** 逐出证据 | 拆为四类：**M3-1** 选择一致（L1↔记录）／**M3-2** 真实逐出（L2）／**M3-3** 内容身份（L3）／**M3-4** 重算后果（L4）；**四者不得互相代替** | L2–L4 | 分档判读（§7.1） |
| **D** 决策机会 | ≥2 合法候选，**且至少一次出现：A0 会选的那个 Entry（最早 deadline）带着比另一候选更长的后缀，且该劣势按完整不等式越出 `q` 优势与 1.14 倍 `prefill/m` 带**（§5.3/§5.5） | L1 | 硬门禁（否则不可判别） |
| **E** 效果 | 仅在 H、M1–M3、D 全部通过后才有意义；**不要求产生收益** | L4 | 记录 |

### 7.1 M3 的四类证据（RC7 + RC9）

M3 曾经是一个单一门，这本身就是错误的抽象："选择一致""真实逐出""内容身份""重算后果"
四件事的证据强度与含义完全不同，任何一件成立都推不出下一件。v4 把它拆开并分别判读。

| 主张 | 怎么算 | 说明了什么 | 不能推出什么 |
|---|---|---|---|
| **M3-1** 选择一致 | `last_selected_block_ids`（项目层 SelectionPlan 输出） vs L1 全选择集 | 两个**计算**一致 | 不能推出物理逐出，更不能推出因果归属 |
| **M3-2** 真实逐出 | L1 受害者是否在**同回合窗口**内出现于 `BLOCK_EVICTED` | 物理逐出确实发生 | 不能推出"是本候选导致的" |
| **M3-3** 内容身份 | 逐出事件 `native_cache_key_before` vs 该链快照记录的槽位内容键 | 逐出时该槽位的**内容**与记录一致 | 不能推出归属（同内容属多条链） |
| **M3-4** 重算后果 | 下游 APC miss / 重算 | 真正的代价 | 本归档无数据 |

**本轮实测（`phase2i_m3_evidence.py`）**：

| scenario | idx | need | deficit | M3-1 选择一致 | M3-2 受害块逐出 | M3-3 内容键一致 |
|---|---:|---:|---:|---|---|---|
| hr01 | 2170 | 126 | 33 | **EXACT (126)** | 33/33 | 33/33 |
| hr01 | 4244 | 128 | 50 | MISMATCH (128 vs 126) | 50/50 | 50/50 |
| hr01 | 7305 | 128 | 56 | MISMATCH (128 vs 126) | 56/56 | 56/56 |
| hr02 | 2166 | 128 | 6 | MISMATCH (128 vs 123) | 6/6 | 6/6 |
| hr02 | 4384 | 18 | 17 | MISMATCH (18 vs 123) | 17/17 | 17/17 |
| hr02 | 10388 | 17 | 17 | MISMATCH (17 vs 123) | 17/17 | 17/17 |
| **合计** | | | | **1 精确 / 5 不符** | **179/179** | **179/179** |

三条必须同时写出的限定：

1. **M3-1 的 5 次不符不代表推算错误**。记录规模在同一 run 内恒为 126（hr01）/ 123（hr02），
   而 `need` 在变（128/18/17），因此是**回调不逐回合写入**，属证据完整性限制。
   本轮既**不判通过也不判失败**，记为 `M3-1 partially verified`。
2. **M3-2 的 179/179 不是因果确认**。窗口内确实发生了大量逐出
   （单次回合可见 33–510 次），所以"出现在窗口内"只是**必要条件**，不是充分条件。
3. **M3-3 的 179/179 也不是归属确认**。归档自己写明
   `attribution_reason = "native hash identity does not prove logical ownership"`、
   `logical_owner_attribution = null`；且同一内容键同时出现在 **5–31** 条不同请求前缀中。
   另外 **0/179** 个受害者落在全 run 共享的 7 块公共前缀内，
   因此 §3.4 假设 3（共享内容外部性未触发）在本负载上成立。

**因此 M3 的正确表述是**：*L2 与 L3-内容均已确认，L3-归属与 L4 不可确认，M3-1 证据不完整*。
**不得**写成“M3 通过”，也**不得**用 1/6 精确去声明已完成内容级物理因果归因。

下一轮实现必须把 `last_selected_block_ids` 改为**逐压力回合写入**，
并在原生层提供逐回合同一性，使 M3-1 与归属级证据可以升档。
本轮不实施（授权边界：只改设计文档与只读验证代码）。

### 7.2 机制判断 vs 性能判断（RC4，措辞纪律）

**通过 H + M1–M3 但未通过 D** 的正确结论是：*“机制实现正确，但该负载无法区分本方案与 A0”*，
**不是**“算法无效”，也**不是**“算法有效”。

两类结论的证据基础不同，不能互相代替：

| 类型 | 例子 | 依据 | n=6 是否足够 |
|---|---|---|---|
| **机制判断** | `N_i` 不是代价；受害块数恒等于 `deficit` | 冻结规则的推导 + 已记录字段 | **足够**（确定性推导，不是抽样） |
| **判别力判断** | 本方案与 A0 是否可能分歧 | `S ≥ deficit` ⇒ `L ≥ L_min` 的下界 + 计入的候选 | **足够**（结论是"本轮不可能"，可被反例推翻），**但** 6 次中 2 次裕度小于 14% `prefill/m` 带，该 2 次仅对当前 `prefill` 取值成立（§5.5） |
| **性能判断** | 本方案是否减少重算 tokens | 需多 scenario、多 repeat 的配对统计 | **不足**（n=6，不作结论） |

所以：

- 不能用 n=6 否定机制结论——“受害块数恒等于 `deficit`” 不依赖样本量；
- 也不能用 n=6 支持性能结论——“未观察到差异”不等于“无差异”。

---

## 8. 复现

```bash
python scripts/probes/entry_costaware_audit/phase2i_depth_contract.py    # 9/9 PASS
python scripts/probes/entry_costaware_audit/phase2i_m3_evidence.py       # M3 四类证据
python scripts/probes/entry_costaware_audit/phase2i_marginal_probe.py
```

需要 `local/phase2h-history-rich-native-smoke-v1-evidence/`。只读，ruff clean。

输出六段：

1. **as-of 与身份检查**：每条决策使用的快照 index、`boundary_id`、可评分候选数、Fail Closed 原因；
2. **逐候选几何**：`N / m / victims / d_min / S / q / prefill`，以及 `proxy` 与 `literal` 两种代价；
3. **规则比较**：A0（真实 deadline 规则）／MinOvershoot／EarliestDL／本方案 vs A1 实际释放；
   **2b** 另给 proxy vs A0、proxy vs MinOvershoot 的成对一致率；
4. **跨臂对照**：按 `boundary_id` 匹配的 A0/A1/A2 实际释放，以及后缀是否退化；
   配对先过五项检查，不过则整 run 标为 `EXCLUDED`（§5.2、§6.3 条件 6）；
5. **结构余量**：每候选在 `S = |V|` 下界处的 `L_min`，判定“是否连最好的块几何都无法偏离 A0”（§5.5）；
   **3b** 另给出 L1/L2/L3 分级与“整跑全量交集”的反例对照，明确指出后者**不是**归属证据；
6. **`prefill/m` 跨度**：验证 `prefill` 是否与 `m` 成正比，从而 `L` 是否**近似**为 `q·S`（§3.5）。

`phase2i_m3_evidence.py` 单独输出 M3-1/M3-2/M3-3/M3-4 四类证据，
并按**释放集 / 逐出集**拆分分母（TIER_1 是被释放到 free queue，不是被逐出）。

深度由 as-of `VLLM_PREFIX_SNAPSHOT` 的 `block_ids` 顺序恢复（**观测时刻的位置 = 深度**，
这一点只在快照刚建立时成立）；运行时**不得**改由 `RetentionEntrySnapshot.block_ids`
下标直接取——该元组会被 `observe_eviction` / `reconcile_entry_evictions` 压缩，
下标已不等于深度（§6.1.1）。运行时应实现 §6.1.2 的 `ChainDepthProof`。

---

## 9. 向 M1 交回的问题

| # | 问题 | 位置 |
|---|---|---|
| 1 | 六次决策经严格 as-of 复核后的选择表 | §5.1（含 Fail Closed 统计）与 §5.2（跨臂） |
| 2 | 修正后的完整评分与 Fallback 规则 | §3.2–§3.3（只改 Step 2，Step 1/3/4/5 保持冻结） |
| 3 | 在线实现所需的最小状态与时间复杂度 | §6.1.2（`ChainDepthProof`）、§6.2（`O(|Q| + k·m)`） |
| 4 | 与 A0、MinOvershoot 结构上可能分歧的条件 | §5.3（完整不等式）与 §5.5（本轮为何不可能，附前提） |
| 5 | 可验证的机制 Smoke 判据与停止条件 | §7（H/M1–M3/D/E，M3 拆为四类）与 §6.3（六条停止条件） |

**RC5 交回项**：深度契约的可执行证明
`scripts/probes/entry_costaware_audit/phase2i_depth_contract.py`，
覆盖内部逐出漂移、槽位回收继承、无法解析上报、后缀用记录长度四条性质（§6.1.3）。

**RC8 交回项（v4 新增）**：同一文件扩到 **9/9 PASS**。
`depth_of()` 现在按 chain → process → 时间 → 内容 → 槽位逐项校验，
分别返回 `WRONG_CHAIN` / `WRONG_PROCESS` / `FUTURE_PROOF` / `STALE_PROOF` /
`IDENTITY_UNVERIFIED` / `CONTENT_MISMATCH` / `UNKNOWN_BLOCK`；
部分逐出用例的复合条件已改为**逐块显式断言**（§6.1.3、§6.1.4）。
`IDENTITY_UNVERIFIED` 降级路径已实现且经测试，本轮归档内容键齐全故**未触发**。

**RC9 交回项（v4 新增）**：`barrier_for()` 增加区间与计数器链检查（§6.3 条件 6），
并因此发现 **hr02 计数器不自洽**，整 run 在屏障级跨臂对照中 **Fail Closed**（§5.2）；
M3 拆为四类且不再用单一“通过/失败”概括（§7.1）。
**本轮明确不用 1/6 精确声明内容级物理因果归因。**

**RC6 交回项**：完整不等式保留在 §3.5 与 §5.3；`q·S` 仅作近似并附 1.1421 跨度声明；
§5.5 已限定前提；停止条件 3 已改为按 Score/Selection 可区分性判定（§6.3）。

**RC7 交回项**：L1–L4 证据分级（§2.4、§7.1）；M3 由单一档位改为四类主张，实测
M3-1 **1 精确 / 5 不符**、M3-2 **179/179**、M3-3 **179/179**、M3-4 无数据；
屏障配对五项检查（§6.3 条件 6）。
**本轮明确不对"回调不完整"作算法层面的解读**：既不当作出错，也不当作正确。

深度由 as-of `VLLM_PREFIX_SNAPSHOT` 的 `block_ids` **观测时刻**顺序恢复；
运行时**不得**改用 `RetentionEntrySnapshot.block_ids` 下标（会被压缩，§6.1.1）。
