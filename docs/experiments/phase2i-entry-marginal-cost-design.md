# Phase 2I — Entry-level Marginal Cost-Aware Algorithm Design

**分支**：`design/phase2i-entry-marginal-cost`
**输入**：Phase 2H Formal History-Rich Native Smoke（PR #86，HEAD `680f152a`），6/6 runs。
**边界**：纯离线设计与分析。未修改冻结 A1/A2，未新增 Native Run，未启动 Campaign，未提交实现。
**脚本**：`scripts/probes/entry_costaware_audit/phase2i_marginal_probe.py`（只读，可复现全部数字）

---

## 0. 摘要

1. **A1 退化为 Minimum Overshoot 有确定原因**：`need ≪ N_i` 时评分括号 ≈ `λN_i`，
   于是 `q×N` 实际是"按 q 加权的块数"，而本数据 6/6 决策中 **q 的次序与 N 的次序完全相同**，
   两条轴不冲突、互相强化，最终由 N 决定。
2. **在唯一分歧点，N 的比值压过了 q 的比值**：HR02 第 3 次释放（M1 记为 round 55）
   的 N 比 0.719 × q 比 1.150 = 0.827 < 1，A1 因此选了**更热**的那个 Entry。
3. **`N_i` 根本不是代价**：按冻结的 `(tier, rank)` 规则，**6/6 决策里每个候选被杀掉的块数完全相同**
   （受 `deficit` 上界限制）。N 只决定"能否满足需求"，不决定"死多少"。
4. **真正的代价是链条后缀**：同一决策中，被杀的块位于深度 451/799，意味着要重算 **349** 块；
   另一候选的受害者位于深度 631/647，只需重算 **17** 块。**差 20.5×**。
   A1 选的正是代价大的那个。
5. **推荐代价**：`L(X) = q_X × prefill_X × (m_X − d_min(X) + 1) / m_X`。
   量纲明确（期望重算秒数），决策时可算，复用 A2 已有的链损失语义。
6. **必须如实说明的边界**：该规则在 6/6 决策上与 **A0（Native LRU）选择相同**。
   它在构造上不同于 LRU（用了深度与 prefill，LRU 都不用），但**本轮证据无法证明它优于 LRU**。
   要区分两者，需要"最冷 Entry 恰好带有浅层冷块"的决策结构，本轮出现 0/6。

---

## 1. Phase 2H 负面结果的机制解释

### 1.1 冻结的资格规则决定了"谁死"，而它不含 N

从 `src/kvopt/continuum/selection.py` 读出，不需推断：

```text
EligibilityTier.TIER_1 = 0, TIER_2 = 1
virtual_eligible_order = sort(eligible, key=(int(tier), native_lru_rank))
selected               = virtual_eligible_order[:required_blocks]
```

而 `EligibilityPreparation` 的校验明确要求：一次 pressure 只把**被释放那一个 Entry** 的块
从 protected(None) 提升为 TIER_2，且提升到 target 满足即停止。

由此得到两步算术：

```text
deficit      = max(0, need − |TIER_1|)
candidate 的受害者数 = min(deficit, |该候选的新增 eligible 块|)
```

**因为所有 TIER_1 块都排在所有 TIER_2 块之前**，被释放的 Entry 只有在 TIER_1 不够时
才贡献受害者，而一旦它贡献，其贡献数量对所有候选都是 `deficit`。
Phase 2H 实测：

| run | idx | need | TIER_1 | deficit | 各候选受害块数 |
|---|---|---:|---:|---:|---|
| hr01 | 2170 | 126 | 93 | 33 | **33 / 33 / 33** |
| hr01 | 4244 | 128 | 78 | 50 | **50 / 50 / 50** |
| hr01 | 7305 | 128 | 72 | 56 | **56 / 56 / 56** |
| hr02 | 2166 | 128 | 122 | 6 | **6 / 6 / 6** |
| hr02 | 4384 | 18 | 1 | 17 | **17 / 17** |
| hr02 | 10388 | 17 | 0 | 17 | **17 / 17** |

> **6/6 决策：每个候选被杀的块数相同。**
> 所以"释放哪个 Entry"选择的不是**死多少块**，而是**死谁的内容**。
> `N_i`（新增 eligible 块数）在这一层完全不是代价，它只是覆盖 `deficit` 的可行性闸门。

### 1.2 为什么 A1 变成 Minimum Overshoot

评分（λ = 0.5）：

$$R_i=q_i\big[\lambda N_i+(1-\lambda)\min(\text{need},N_i)\big]$$

Phase 2H 的 `need` 只有 17–128，而 `N_i` 是 460–813，**`need ≪ N_i`**，于是
`min(need,N_i) = need` 只是常数加项，括号 ≈ `λN_i`：

$$R_i \approx 0.5\,q_i N_i$$

再叠加本数据的一个实测事实：

| run | idx | Spearman(N, q) | q 次序 vs N 次序 |
|---|---|---:|---|
| hr01 | 2170 | **+1.000** | 相同 |
| hr01 | 4244 | **+1.000** | 相同 |
| hr01 | 7305 | **+1.000** | 相同 |
| hr02 | 2166 | **+1.000** | 相同 |
| hr02 | 4384 | 2 个候选 | 相同 |
| hr02 | 10388 | 2 个候选 | **不同** |

**q 越大 = deadline 越晚 = 越热 = 越可能被复用**。而这里 q 与 N 同序，
意味着"块多的 Entry 也更热"。于是"最小化 qN"与"最小化 N"给出同一答案，
q 没有起任何区分作用 —— A1 与 Minimum Overshoot 6/6 相同，正是这个原因。

### 1.3 唯一分歧点的算术

HR02 第 3 次 pressure 释放（`idx=10388`，M1 记为 round 55，need = 17，TIER_1 = 0）：

| 候选 | N | 链长 m | 受害者深度 | 浅层受害者 d_min | 后缀 `m−d_min+1` | q | prefill |
|---|---:|---:|---|---:|---:|---:|---:|
| pylint-dev | 460 | 799 | 一个浅层块 + 其余深层块 | **451** | **349** | 0.463529 | 0.681184 |
| pytest-dev | 640 | 647 | 均为最深层 | **631** | **17** | 0.402859 | 0.551567 |

两种代价的判断方向相反：

| 规则 | pylint | pytest | 选谁 |
|---|---:|---:|---|
| 冻结 A1：`q×[0.5N+0.5·need]` | 110.55 | 132.34 | **pylint** |
| 最小 overshoot：`N` | 460 | 640 | **pylint** |
| 最早 deadline：`deadline` | 259.469 | 252.046 | pytest |
| **链后缀损失**：`q·prefill·suffix/m` | **0.1379** | **0.005837** | **pytest** |

- A1 与 MinOvershoot 选 pylint；A0 与 A2 实际释放的都是 pytest。
- 链后缀代价：pylint 比 pytest 高 **23.6×**（后缀块数比 **20.5×**）。
- M1 记录的后果：该分歧对应后续 **+6320 recomputed tokens**。

**N 为什么占优**：`N_{pylint}/N_{pytest} = 0.719`，`q_{pylint}/q_{pytest} = 1.150`，
乘积 0.827 < 1。N 的 28% 优势压过 q 的 15% 劣势，于是 A1 选了**更热、且代价高 20 倍**的那个。

**代理为什么没对上损失**：`N_i` 计的是"新增 eligible 块数"，与"被杀的块在链条中的位置"无关。
pylint 的受害者里有一个位于深度 451 的**浅层冷块**——单个这样的块就把整条 349 块的后缀判死。
`N` 看不见这一点，`q`（只按 elapsed）也看不见。

---

## 2. 现有信息的可用性与缺口

### 2.1 决策时确实可用（本轮已验证可算）

| 信息 | 来源 | 用途 |
|---|---|---|
| `original_free_queue`：`block_id` / `native_lru_rank` / `eligibility_tier` / `has_block_hash` | pressure payload | 判定 TIER_1 规模与 `deficit` |
| `required_blocks` | pressure payload | 同上 |
| 候选 `block_ids` / `initially_reclaimable_block_ids` | pressure payload | 受害者集合 |
| 候选 `prefill_reload_seconds` | pressure payload | 代价量纲（秒） |
| 候选 `retention_deadline_timestamp` | pressure payload | q |
| **链条有序块列表** `VLLM_PREFIX_SNAPSHOT`（`block_ids` 顺序 = 深度） | 每轮快照 | **d_min 与 m** |
| `ttl_history_mode` / `global_server_gap_sample_count` | `TTL_DECISION_OBSERVED` | 历史机制门禁 |

Phase 2H 已把 Gate H 需要的东西补齐了：`TTL_DECISION_OBSERVED` 直接记录 `history_mode`
（本数据 177 次决策中 76 次 `tool_specific`），`TTL_HISTORY_INPUT_OBSERVED` 记录
`global_server_gap_sample_count` 与完整样本数组。**历史机制门禁现在可判定。**

### 2.2 存在但本轮无区分度

| 信息 | 观察 |
|---|---|
| 跨 Entry 共享块 | 每对候选恒共享 **7** 块（公共 system prompt 前缀）。存在但恒定，不区分候选，且从不落入受害者窗口。 |
| `waiting_followup` | 6/6 决策的 3/3 候选全为 `True` |
| `eta` | 恒为 1.0 |
| `queue_delay_t_seconds` | 恒为 0.0 |

### 2.3 缺口（决定本轮无法做到的事）

| 缺口 | 影响 |
|---|---|
| **没有"逐出后是否被重取"的记录** | `r_i` 不可算；无法估计"被杀内容会不会回来" |
| 候选的 `prefix_id` 在 pressure payload 中有，但**没有显式的 `depth` 字段** | 深度需从 `VLLM_PREFIX_SNAPSHOT` 反查；运行时内存中可用，但日志未直接记录，离线核对成本高 |
| 没有逐块物理逐出与后续 APC 命中的关联 | 无法核对"预测的受害者集合"与"实际逐出集合"是否一致 |
| 右删失标记 | 窗口结束时未重取的内容无法区分"不会回来"与"还没回来" |

**结论：本轮能够把代价算准到"链条后缀块数"这一层，但不能算到"会不会真的被重算"。**
后者需要 M6 补逐出→重取证据（上一版设计 §5.1 第 6、8 项），本阶段不再追加。

---

## 3. 推荐的成本估计与 Entry 决策规则

### 3.1 代价对象

对候选 *X*，令

- $m_X$：该 Entry 链条的块数；
- $V_X$：按 `min(deficit, |新增 eligible|)` 取出的受害者集合（按 native rank 升序）；
- $d_{\min}(X)=\min\{d_X(b) : b\in V_X\}$，即受害者中最浅的深度；
- 后缀 $S_X = m_X - d_{\min}(X) + 1$ —— 一旦该深度被逐出，整条后缀都需重新 prefill
  （与 A2 冻结的链损失语义一致：只有最浅的受害者决定损失）。

### 3.2 评分

$$\boxed{\;L(X)\;=\;q_X\cdot\text{prefill}_X\cdot\frac{S_X}{m_X}\;}$$

三点说明：

1. **量纲是秒**：`prefill_X` 是该 Entry 前缀的重载耗时（秒），`S_X/m_X` 是被毁掉的比例，
   两者相乘是该 Entry 若被重取时的期望重载秒数，再乘 `q_X`（复用概率代理）得到期望损失。
   与现行 `q×块数` 相比，它不再把"块数"当"代价"。
2. **`N` 只保留为可行性闸门**：若某候选的新增 eligible 少于 `deficit`，
   释放它无法满足压力需求，直接排除（`N` 的正确定位）。
3. **`d_min` 是唯一引入**：它来自链条深度，LRU / Earliest Deadline / MinOvershoot 都不用。

### 3.3 决策规则（完整、无自由参数）

```text
1. 计算 deficit = max(0, need − |TIER_1|)
2. 可行集 F = { 候选 X : |新增 eligible(X)| >= deficit }
3. 若 F 为空 → 与冻结 A1 一致，按 deadline 升序释放（并记录该退化）
4. 否则对每个 X ∈ F：
       V_X   = X 的新增 eligible 中 native rank 最小的 deficit 个
       d_min = min depth(V_X)          # 深度来自该链有序块列表
       L(X)  = q_X * prefill_X * (m_X − d_min + 1) / m_X
5. 释放 argmin L(X)；平局按 (deadline, program_id) 升序
```

平局规则必须显式：本数据 4/6 决策的后缀完全相同（受害者恰为最深层，$S_X = |V_X|$），
此时排序由 `q × prefill` 决定，**规则退化为"按 q 加权的 prefill 排序"**，需要如实记录，
而不是当作"算法起了作用"。

---

## 4. 与 Minimum Overshoot、A0、冻结 A1 的结构性区别

| 维度 | MinOvershoot | A0 (Native LRU) | 冻结 A1 | **本方案** |
|---|---|---|---|---|
| 排序轴 | `N_i`（新增 eligible 块数） | 最冷块所在 Entry | `q·[λN+(1−λ)min(need,N)]` | `q · prefill · S/m` |
| 是否用深度 | 否 | 隐含（rank≈深度） | 否 | **是，显式 `d_min`** |
| 是否用 prefill 代价 | 否 | 否 | 否 | **是** |
| 是否用复用概率 | 否 | 否 | 是（仅 elapsed） | 是（仅 elapsed） |
| `N` 的作用 | 代价 | 无 | 代价（主项） | **仅可行性闸门** |
| 是否区分"死多少块" | 是（错） | 否 | 是（错） | **否（本就相同）** |
| 是否区分"死哪条链的哪一层" | 否 | 部分 | 否 | **是** |
| 平局时的行为 | — | — | — | 退化为 q×prefill 排序（显式） |

**结构性区别的关键一条**：受害者块数在合法决策里恒等于 `deficit`，
所以任何以 `N` 为主轴的规则都在优化一个**与伤害无关的量**。
本方案把注意力移到"受害者在链条中的位置"，这是三者都没有用的维度。

### 4.1 必须声明的失败风险

- 本方案的 `q` 仍是 elapsed 的单调函数（阻塞 3 未解除），所以"复用概率"这一项没有真正改进；
- 若 `d_min` 在所有决策中都与 `m − |V| + 1` 相同（即受害者总在最深层），
  则 $S_X = |V_X| = \text{deficit}$ 对所有候选相同，**规则立刻退化为 `q × prefill` 排序**，
  与 Earliest Deadline 仅差一个 prefill 权重。这不是假想：本数据 **4/6** 决策就是这种情形。

---

## 5. 离线快照上的决策差异与证据边界

### 5.1 六次真实决策的规则对照

| run | idx | A1 实际释放 | 冻结 A1 评分 | MinOvershoot | Earliest deadline | **链后缀损失** |
|---|---|---|---|---|---:|
| hr01 | 2170 | django | django | django | django | django |
| hr01 | 4244 | django | django | django | django | django |
| hr01 | 7305 | django | django | django | django | django |
| hr02 | 2166 | pytest | pytest | pytest | pytest | pytest |
| hr02 | 4384 | pytest | pytest | pytest | pytest | pytest |
| hr02 | 10388 | **pylint** | pylint | pylint | pytest | **pytest** |

一致性统计（与 A1 实际释放相比）：

| 规则 | 一致 |
|---|---|
| 冻结 A1 评分 | 6 / 6 |
| 最小 overshoot | 6 / 6 |
| 最早 deadline | 5 / 6 |
| **链后缀损失** | **5 / 6** |

### 5.2 证据边界（必须写进结论，不得省略）

1. **链后缀损失在 6/6 决策上与 A0（Native LRU）选择相同。**
   构造上它不同于 LRU（用了深度与 prefill），但**本轮没有一次决策能区分两者**。
   因此**不能**声称该方案优于 LRU。
2. **它唯一偏离 A1 的地方，正是 A1 出错的地方**（HR02 round 55，+6320 tokens）。
   这只能支持"该代价对象至少不与已知错误一致"，**不能**支持"它能带来收益"。
3. 样本量是 **6 次决策 / 2 个场景 / 1 次 repeat**。任何方向的统计结论都不成立。
4. `d_min` 依赖 `VLLM_PREFIX_SNAPSHOT` 的块顺序；本报告中它是**反查**得到的，
   运行时应直接从内存链结构取。若两者不一致，本报告的数值需要重算。
5. 受害者集合是按冻结的 `(tier, rank)` 规则**推算**的，未与 `BLOCK_EVICTED` 逐块核对。
6. `+6320 recomputed tokens` 取自 M1 对 PR #86 的审查结论，本脚本未独立复算。

### 5.3 若要区分"本方案 vs LRU"，需要什么决策结构

本方案与 LRU 只在一种情形下分歧：

> **最冷的那个 Entry 的受害者集合里有一个浅层块**（$d_{\min}\ll m-|V|+1$），
> 而另一个更热的 Entry 的受害者全在最深层。

此时 LRU 会选最冷的那个（代价大），本方案会选更热的那个（代价小）。
Phase 2H 中这种结构出现了 **2 次**（hr02 idx=4384 的 pylint、idx=10388 的 pylint），
但两次都恰好是**更热**的那个 Entry 带浅层块，所以两规则同向。
**需要一次"最冷 Entry 带浅层冷块"的决策，才能检验两者分歧时的对错。**
这是下一轮离线筛查的判据，也是设计一个能区分两者的 replay 的直接输入。

---

## 6. 最小实现方案与失败停止条件

### 6.1 最小实现（仅当 M1 批准）

只改 Entry 决策打分，不改 Native Ownership / BlockPool / 原生淘汰生命周期。

| # | 改动 | 说明 |
|---|---|---|
| 1 | 运行时按链维护 `block_id → depth` 与 `m`（已有链快照，只需暴露） | 不新增状态源 |
| 2 | pressure 决策处计算 `deficit`、`V_X`、`d_min`、`S_X` | 纯函数，输入全为决策时已有 |
| 3 | 用 `L(X)` 替换 `R(X)`；`N` 降为可行性闸门 | 公式替换，不新增参数 |
| 4 | 决策日志增加 `deficit / d_min / m / S / L(X)` | 使下一轮无需重跑即可审计 |
| 5 | 保留旧评分作为 shadow 字段并行记录 | 便于逐决策比较新旧 |

**不引入任何可调参数**（无 λ、无权重、无温度）。平局规则固定为 `(deadline, program_id)`。

### 6.2 验收判据（与 Phase 2H 的门禁对应）

| 门禁 | 判据 |
|---|---|
| H（历史机制） | 已由 Phase 2H 通过；本轮沿用 `TTL_DECISION_OBSERVED` 的 `history_mode` 与样本计数 |
| D（决策机会） | ≥2 合法候选；且**至少一次出现"最冷 Entry 带浅层冷块"的结构**（否则两规则不可区分） |
| M（机制自洽） | 记录的 `deficit`、`V_X`、`d_min` 可由 `original_free_queue` + 链快照复算一致 |
| E（效果） | 仅在 H、D、M 全部通过后才有意义；不要求产生收益 |

### 6.3 失败停止条件（出现即停，不追加 run、不调参）

1. `deficit` 与 `need − |TIER_1|` 无法复现 → 资格规则理解错误；
2. 受害者集合与 `BLOCK_EVICTED` 的逐块交集显著不符 → 推算规则错误（本方案的整个代价建立在它上面）；
3. 全部决策中 $d_{\min} = m - |V| + 1$ → 后缀恒等于 `deficit`，规则退化为 `q×prefill`，**应停止并报告"该负载无深度结构可利用"**；
4. 全部决策与 A0 选择相同 → 本方案在此负载上不可区分，**不得**据此宣布任何有效性结论；
5. 出现 `prefill_reload` 缺失或为 0 的候选 → 代价量纲失效，停止；
6. 决策数不足（< 10 次多候选决策）→ 任何效果判断都不成立，停止。

### 6.4 明确不做

- 不引入 `r_i`（缺口未补，见 §2.3），不引入多信号组合；
- 不改 τ、不改 λ、不改 `need`/`N` 语义；
- 不在 cold-start 未激活的场景上评估；
- 不通过反复换公式挑正向结果。

---

## 7. 复现

```bash
python scripts/probes/entry_costaware_audit/phase2i_marginal_probe.py
```

需要 `local/phase2h-history-rich-native-smoke-v1-evidence/`（Phase 2H 解包）。
脚本只读，ruff clean。输出四段：资格算术、逐候选几何与两种代价、四规则对照、
各臂在同一 pressure 事件上的实际释放。全部数字直接来自事件流，深度由
`VLLM_PREFIX_SNAPSHOT` 的 `block_ids` 顺序反查。
