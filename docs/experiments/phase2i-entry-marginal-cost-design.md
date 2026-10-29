# Phase 2I — Entry-level Marginal Cost-Aware Algorithm Design（修订版 v2）

**分支**：`design/phase2i-entry-marginal-cost`
**输入**：Phase 2H Formal History-Rich Native Smoke（6/6 runs），M1 对 PR #87 的 RC1–RC4。
**边界**：纯离线设计与分析。未修改冻结 A1/A2，未新增 Native Run，未提交实现。
**脚本**：`scripts/probes/entry_costaware_audit/phase2i_marginal_probe.py`（只读）

> 本版按 RC1–RC4 修正了四处：基线语义、as-of 快照与跨臂关联、成本代理的定位、
> 不足量回退路径与结论强度。§0.4 列出具体改动。

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
  所以 **`L` 的实际排序 ≈ `q × S`**，`m` 与 `prefill` 是 ≤14% 的扰动项，不是新判别维度（§3.5）；
- 本方案与 A0 的分歧在 6/6 决策上**结构上不可能**（不仅未观察到），
  因为 A0 选中的 Entry 恰同时具有最小 `q` 与最小 `prefill/m`（§5.5）。

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
| **链条有序块列表** | 运行时 `RetentionEntrySnapshot.block_ids`（位置 = 深度）；离线用 as-of `VLLM_PREFIX_SNAPSHOT` | `m` 与 `d_min` |
| `history_mode` / `global_server_gap_sample_count` | `TTL_DECISION_OBSERVED` | 历史机制门禁 |

**深度不需要新状态**：`RetentionEntrySnapshot.block_ids` 本身是**有序** `tuple[BlockIdentity, ...]`，
下标即深度。A2 的 `A2NativeChainSnapshot` 同样持有有序 `block_ids`。

### 2.2 Phase 2H 已补齐的观测

`TTL_DECISION_OBSERVED` 现在直接记录 `history_mode`、`reason`、
`global_server_gap_sample_count`、`tool_server_gap_sample_count`、`ttl_decision_timestamp`。
本数据 177 次 TTL 决策中 **76 次为 `tool_specific`**、101 次 `cold_start`。
**历史机制门禁（H）至此可判定**，上一版设计要求的第 1、2 项观测已到位。

### 2.3 存在但本轮无区分度

| 信息 | 观察 |
|---|---|
| 跨 Entry 共享块 | 每对候选恒共享 **7** 块（公共前缀），从不落入受害者窗口 |
| `waiting_followup` | 6/6 决策的全部候选均为 `True` |
| `eta` | 恒 1.0；`queue_delay_t_seconds` 恒 0.0 |

### 2.4 缺口

| 缺口 | 影响 |
|---|---|
| 无"逐出后是否被重取"记录 | `r_i` 不可算；无法估计"被杀内容会不会回来" |
| 无逐块物理逐出与后续 APC 命中的关联 | 无法核对"推算的受害者集合"是否等于"实际逐出集合"（§6.3 停止条件 2） |
| 无右删失标记 | 窗口结束时未重取的内容无法区分"不回来"与"还没回来" |

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

### 3.5 本式在实测 profile 下实际等价于 `q × S`（重要）

profile 对 token 数近线性，而块数 ∝ token 数，所以 `prefill_X / m_X` 在一个决策内近乎常数。
Phase 2H 实测的 `prefill/m` 候选间 **max/min 跨度**：

| scenario | idx | prefill/m 跨度 |
|---|---|---:|
| hr01-balanced-gap | 2170 | 1.1421 |
| hr01-balanced-gap | 4244 | 1.0991 |
| hr01-balanced-gap | 7305 | 1.0811 |
| hr02-short-gap-long-context | 2166 | 1.0706 |
| hr02-short-gap-long-context | 4384 | 1.0309 |
| hr02-short-gap-long-context | 10388 | **1.0001** |

于是

$$L(X)=q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X}=q_X\,S_X\cdot\underbrace{\frac{\text{prefill}_X}{m_X}}_{\approx\,c\ (\text{跨度}\le 1.14)}\;\approx\;c\cdot q_X\,S_X$$

**结论必须直说**：在当前的近线性 profile 下，`L` 的排序 ≈ `q × 后缀块数`；
`m` 与 `prefill` 只是 ≤14% 的扰动项，**不是新的判别维度**。
`L` 相对 `q·S` 的唯一实质好处是量纲可解释（秒）与在 profile 变化时自动适应。

**这是设计的一部分，不是缺陷**，但也意味着：
推荐实现 `L`（保留量纲），而在分析时用 `q·S` 判断"是否有判别力"，
因为后者才是真正在起作用的量。任何声称"用了 prefill 与 m 所以更强"的说法都站不住。

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

一致率（与 A1 实际释放）：

| 规则 | 一致 |
|---|---|
| Minimum Overshoot | 6 / 6 |
| A0（deadline 规则） | 5 / 6 |
| Earliest Deadline | 5 / 6 |
| **本方案（Cost Proxy）** | **5 / 6** |

### 5.2 跨臂对照（按 `boundary_id` 严格匹配）

| scenario | barrier | A0 | A1 | A2 | 结论 |
|---|---|---|---|---|---|
| hr01-balanced-gap | round-40 | django | django | django | 一致 |
| hr01-balanced-gap | round-50 | django | django | django | 一致 |
| hr01-balanced-gap | round-55 | django | django | django | 一致 |
| hr02-short-gap-long-context | round-40 | pytest | pytest | pytest | 一致 |
| hr02-short-gap-long-context | round-50 | pytest | pytest | pytest | 一致 |
| hr02-short-gap-long-context | **round-55** | pytest | **pylint** | pytest | **分歧** |

与 M1 审阅的"唯一分歧位于 HR02 round 55"一致，且现在由 `boundary_id`
而非最近 event index 建立对应关系。

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

**因此准确的表述是**：在近线性 profile 下，本方案与 A0 的分歧**由 `S` 承担**，
更精确地说由 `d_min` 承担。用 `q·S` 复述：

$$\text{proxy}\ne\text{A0}\iff \exists Y:\ q_Y S_Y<q_{X^*}S_{X^*}\ \text{且}\ q_Y>q_{X^*}$$

因为 `q_{X*}` 是最小 q，这要求 **`S_{X*} > S_Y` 且超出比例足以抵消 q 差**。即：

> **本方案与 A0 分歧 ⟺ A0 会选的那个 Entry（最早 deadline）恰好带着最长的后缀
> （即它的受害块里有浅层块），且该劣势超过它在 q 上的优势。**

这正是 RC1 要求修正的地方：v1 把它写成"最冷 Entry 带浅层冷块"，
**"最冷"是错的**（A0 不是按冷度选 Entry），而且 v1 还断言这是"必要条件"——
在 `S` 恒定的决策里两者必然一致，这一半是对的；但在 `S` 变化时，
分歧依赖的是 `q·S` 的比值，**不只是"是否带浅层块"这个布尔量**。

**与 MinOvershoot 分歧的条件**：存在 X、Y 使 `N_X < N_Y` 但 `q_X S_X > q_Y S_Y`。
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

### 5.5 更强的结论：在 6 次决策上，分歧是**结构上不可能**的

不只"未观察到分歧"——可以证明在这 6 次决策里，**任何块几何都无法让本方案偏离 A0**。

理由：`S ≥ |V_X| = deficit`（受害者是链内互异深度的 `deficit` 个块，故
`d_min ≤ m − deficit + 1`，于是 `S ≥ deficit`）。所以每个候选的 proxy 有一个下界：

$$L_{\min}(X)=q_X\cdot\text{prefill}_X\cdot\frac{|V_X|}{m_X}$$

若 `L_min(Y) > L(X*)`，则候选 Y **无论块怎么摆放都不可能**胜出。
实测（§复现输出第 5 段）：

| scenario | idx | A0 选中（proxy） | 其余候选的 `L_min` | 结果 |
|---|---|---:|---|---|
| hr01 | 2170 | django 0.005341 | mwaskom 0.014554 / sympy 0.007683 | 不可能偏离 |
| hr01 | 4244 | django 0.018032 | mwaskom 0.021375 / sympy 0.018716 | 不可能偏离 |
| hr01 | 7305 | django 0.022321 | mwaskom 0.023660 / sympy 0.022616 | 不可能偏离 |
| hr02 | 2166 | pytest 0.000124 | pydata 0.002520 / pylint 0.000555 | 不可能偏离 |
| hr02 | 4384 | pytest 0.005272 | pylint 0.006810 | 不可能偏离 |
| hr02 | 10388 | pytest 0.005838 | pylint 0.006718 | 不可能偏离 |

**机理**：A0 选的那个 Entry 恰好同时具有最小的 `q` **和**最小的 `prefill/m` 足迹，
所以它在 `q·S` 上天然占优；`S` 唯一能起作用的两次（4384、10388）
也恰好与 q 的不利方向一致（pylint 的 `S` 大且 `q` 大，两头都输）。

**这对下一轮 replay 是明确的判据**：要让本方案与 A0 可区分，必须出现

> **最早 deadline 的 Entry 带着最长的后缀**（其受害块含浅层块），
> 而另一个 deadline 更晚的 Entry 的后缀明显更短。

本轮 0/6。这是设计下一轮 workload 时必须直接瞄准的结构，
而不是"多跑几次看看有没有分歧"。

---

## 6. 最小实现方案与停止条件

### 6.1 在线所需的最小状态（RC4 要求）

| 状态 | 来源 | 是否需要新增 |
|---|---|---|
| `entry.block_ids`（有序，下标 = 深度） | `RetentionEntrySnapshot` | **否**，已存在 |
| `m_X` = `len(entry.block_ids)` | 同上 | **否** |
| `block_id → native_lru_rank` | `EligibilityPreparation.original_free_queue` | **否** |
| `|TIER_1|` | 同一队列按 `eligibility_tier == 0` 计数 | **否** |
| 候选 `newly_eligible_block_ids` | `PressureReleaseEffect` | **否** |
| 候选 `prefill_reload_seconds` | 决策时已有 | **否** |
| `deadline` | `RetentionEntrySnapshot.deadline_timestamp` | **否** |
| **日志新增**：`deficit / V_X / d_min / m / S / L(X)` | 决策点计算 | 仅日志 |

**结论：不需要任何新的运行时状态源**。深度是 `block_ids` 的下标，
这是既有数据结构本来的语义。

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

| # | 条件 | 含义 |
|---|---|---|
| 1 | `deficit ≠ max(0, need − \|TIER_1\|)` | 资格规则理解错误，整个代价模型失效 |
| 2 | 推算的受害者集合与 `BLOCK_EVICTED` 逐块交集显著不符 | 推算规则错误；本方案的全部代价建立在其上 |
| 3 | 全部决策 `S_X = \|V_X\| = deficit`（`S` 在候选间恒定） | 后缀恒等于 deficit ⇒ `q·S` 退变为 `q·const`，规则与 A0 完全等价。**应报告“该负载无深度结构可利用”，而非继续调参** |
| 4 | 全部决策与 A0 选择相同（即使 `S` 有变化） | 本负载上不可区分，**不得**据此宣布有效性或无效性（§5.5 给出了本轮的具体机理） |
| 5 | 任一候选 `prefill_reload` 缺失或为 0 | 代价量纲失效 |
| 6 | 深度缺失 | Fail Closed：该决策改用冻结 A1 排序并记录，不猜深度 |

条件 3 的定位：它是**结论**（“该负载不适用”），不是调参信号。若第 3 条触发，
本方向应转向“寻找有深度结构的负载”，而不是修改 `S` 的定义。

**条件 3 与 4 的区别很重要**：`S` 有变化但结果仍与 A0 一致（条件 4）说明**该批决策的
`q` 与 `S` 方向恰好相反**，这是负载选择问题；`S` 本身恒定（条件 3）
说明**代价对象退化**，是更深一层的问题。两者都不应通过改公式解决。

### 6.4 明确不做

- 不引入 `r_i`（缺口未补）、不做多信号组合、不改 τ / λ / `need` / `N` 语义；
- 不改 Step 1、3、4、5 的任何行为；
- 不在 cold-start 未激活的场景上评估；
- 不通过反复换公式挑正向结果。

---

## 7. 机制 Smoke 判据（可验证）

| 门禁 | 判据 | 类型 |
|---|---|---|
| **H** 历史机制 | `TTL_DECISION_OBSERVED` 中至少一个决策 `global_server_gap_sample_count > 100` 且 `history_mode ≠ cold_start`；可用记录历史复现记录的 `ttl_seconds` | 硬门禁 |
| **M1** 资格一致 | `deficit` 与 `V_X` 可由 `original_free_queue` + `newly_eligible_block_ids` 复算一致（±0） | 硬门禁 |
| **M2** 身份一致 | 每个 `V_X` 的块都能在该 Entry 的 `block_ids` 中找到深度，缺失即 Fail Closed 并计数 | 硬门禁 |
| **M3** 逐出一致 | 推算 `V_X` 与 `BLOCK_EVICTED` 的逐块交集 = `V_X`（允许同决策内顺序无关） | 硬门禁 |
| **D** 决策机会 | ≥2 合法候选，**且至少一次出现：A0 会选的那个 Entry（最早 deadline）带着比另一候选更长的后缀，且该劣势越出 `q` 优势**（§5.3/§5.5） | 硬门禁（否则不可判别） |
| **E** 效果 | 仅在 H、M1–M3、D 全部通过后才有意义；**不要求产生收益** | 记录 |

**通过 H + M1–M3 但未通过 D** 的正确结论是：*“机制实现正确，但该负载无法区分本方案与 A0”*，
**不是**“算法无效”，也**不是**“算法有效”。

### 7.1 机制判断 vs 性能判断（RC4）

两类结论的证据基础不同，不能互相代替：

| 类型 | 例子 | 依据 | n=6 是否足够 |
|---|---|---|---|
| **机制判断** | `N_i` 不是代价；受害块数恒等于 `deficit`；`prefill/m` 近常数使排序≈`q·S` | 冻结规则的推导 + 已记录字段 | **足够**（这是确定性推导，不是抽样） |
| **判别力判断** | 本方案与 A0 是否可能分歧 | 上界（`S ≥ deficit`）+ 计入的候选 | **足够**（结论是“本轮不可能”，可被反例推翻） |
| **性能判断** | 本方案是否减少重算 tokens | 需多 scenario、多 repeat 的配对统计 | **不足**（n=6，不作结论） |

所以：

- 不能用 n=6 否定机制结论——“受害块数恒等于 `deficit`” 不依赖样本量；
- 也不能用 n=6 支持性能结论——“未观察到差异”不等于“无差异”。

---

## 8. 复现

```bash
python scripts/probes/entry_costaware_audit/phase2i_marginal_probe.py
```

需要 `local/phase2h-history-rich-native-smoke-v1-evidence/`。只读，ruff clean。

输出六段：

1. **as-of 与身份检查**：每条决策使用的快照 index、`boundary_id`、可评分候选数、Fail Closed 原因；
2. **逐候选几何**：`N / m / victims / d_min / S / q / prefill`，以及 `proxy` 与 `literal` 两种代价；
3. **规则比较**：A0（真实 deadline 规则）／MinOvershoot／EarliestDL／本方案 vs A1 实际释放；
   **2b** 另给 proxy vs A0、proxy vs MinOvershoot 的成对一致率；
4. **跨臂对照**：按 `boundary_id` 匹配的 A0/A1/A2 实际释放，以及后缀是否退化；
5. **结构余量**：每候选在 `S = |V|` 下界处的 `L_min`，判定“是否连最好的块几何都无法偏离 A0”（§5.5）；
6. **`prefill/m` 跨度**：验证 `prefill` 是否与 `m` 成正比，从而 `L` 是否等价于 `q·S`（§3.5）。

深度由 as-of `VLLM_PREFIX_SNAPSHOT` 的 `block_ids` 顺序恢复（位置 = 深度）；
运行时应改由 `RetentionEntrySnapshot.block_ids` 下标直接取，两者语义相同。

---

## 9. 向 M1 交回的五个问题

| # | 问题 | 位置 |
|---|---|---|
| 1 | 六次决策经严格 as-of 复核后的选择表 | §5.1（含 Fail Closed 统计）与 §5.2（跨臂） |
| 2 | 修正后的完整评分与 Fallback 规则 | §3.2–§3.3（只改 Step 2，Step 1/3/4/5 保持冻结） |
| 3 | 在线实现所需的最小状态与时间复杂度 | §6.1（**零新增状态源**）、§6.2（`O(|Q| + k·m)`） |
| 4 | 与 A0、MinOvershoot 结构上可能分歧的条件 | §5.3（真实基线语义）与 §5.5（本轮为何不可能） |
| 5 | 可验证的机制 Smoke 判据与停止条件 | §7（H/M1–M3/D/E）与 §6.3（六条停止条件） |

深度由 as-of `VLLM_PREFIX_SNAPSHOT` 的 `block_ids` 顺序恢复（位置 = 深度），
运行时应改由 `RetentionEntrySnapshot.block_ids` 下标直接取。
