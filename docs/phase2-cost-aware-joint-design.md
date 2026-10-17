# Cost-Aware KV 淘汰：Entry + Block 联合设计（最小版）

> 状态：**设计草案，未实现**
> 依 M1 裁定：本文只做设计，不做 runtime 策略实现、不做大规模实验。
> 修订：rev.2 依 M1 RC1 为目标函数补充释放约束 (C1)–(C4)，
> 并撤回「压力满足后仍主动多释放 Entry」的表述（本轮不授权）。
> 关联：PR #50（`docs/ours-evict-algorithm-design-v1.md`）保留为**当前四字段接口局限性的分析记录**；
> 其中 H1 派生结论已按 M1 要求收紧到「该接口 + 该语料」范围内，本文**不**复用其外推。

---

## 0. 本文要回答的四件事（M1 指定）

```text
① 一个清楚的 Cost-Aware 优化目标，以及各个输入信息来自哪里      → §1, §4
② Entry 与 Block 两层各自控制什么，怎样影响实际重计算            → §2, §3
③ 一到两个能体现新策略与 Continuum 选择不同的具体例子           → §5
④ 一个最小实验方案（在修复后的真实共享前缀工作负载中验证）        → §6
```

---

## 1. 优化目标：单一物理损失，而不是两个损失相加

### 1.1 为什么必须统一

当前系统里存在三条被混用的量（PR #50 §1 已把它们分开）：

```text
Q1  Entry 解除保护   —— 逻辑动作，改变「谁可以被淘汰」，自身不删除任何 KV
Q2  Block 实际淘汰   —— 物理动作，唯一真正删除 KV 的一步
Q3  未来重算 token   —— 业务后果，由 Q2 的集合决定
```

**Entry 损失与 Block 损失不可相加**的两个原因：

```text
原因甲（重复计数）：Entry 解除保护 ≠ 该 Entry 的 Block 被淘汰。
                    解除保护后若无人淘汰，重算为 0，不存在「Entry 损失」。
原因乙（集合依赖）：E({A}) ∪ E({B}) ≠ E({A, B})，见 §3。
                    两层损失都不是各自独立的函数，无法预先加总。
```

⇒ 因此本设计的做法是：**只定义一次损失，定义在物理淘汰集合上**，
Entry 层和 Block 层是同一损失的**两个决策变量**，不是两项成本。

### 1.2 损失的定义（唯一记录量）

设一次淘汰决策为集合 $S$（实际被淘汰的物理 Block）。对任一未来会返回的请求 $r$，
其链上 Block 按深度 $k = 1, \dots, m_r$（根为 1）。定义

$$
j_S(r) \;=\; \min\{\, k \;:\; p_k(r) \in S \,\}
\qquad(\text{链上被淘汰的最浅深度})
$$

$$
\mathrm{recompute}_S(r) \;=\;
\begin{cases}
(m_r - j_S(r) + 1)\cdot B & j_S(r) \text{ 存在} \\
0 & \text{否则}
\end{cases}
$$

$$
\boxed{\;L(S) \;=\; \sum_{r \in \mathcal{R}_{\text{future}}} w_r \cdot \mathrm{recompute}_S(r)\;}
$$

$\mathcal{R}_{\text{future}}$：未来会返回且命中该前缀的请求；$B$：Block 的 token 数（见 §4.5）。

**要点**：$L$ 的自变量**只有 $S$**。$S$ 之外的任何量（是否解除保护、解除几个、顺序如何）
都不进入 $L$，因此结构上不可能重复计数。

### 1.3 两层只是 $L$ 的两个决策变量

$$
\min_{R \subseteq C,\; S \subseteq E(R)} \; L(S)
\qquad \text{s.t.} \quad \text{(C1)--(C4), 见下}
$$

```text
R  —— Entry 层变量：选择解除哪些 Entry 的保护（$C$ = 当前候选 Entry 集）
E(R)—— 由 R 决定的可行池
S  —— Block 层变量：在可行池内选择实际淘汰集合
```

**约束**：$S \subseteq E(R)$ 是硬约束。Block 层**不得**绕过 Continuum 的保护，
只能淘汰 $E(R)$ 内的 Block。这条约束本身就是 A0→A2 的合法性边界。

**释放约束（C1–C4）** —— 回应 RC1。第一版不追求联合最优，只把释放行为钉死在
冻结的按需压力语义之内：

```text
(C1) 合法淘汰    S ⊆ E(R)                           Block 层不得绕过保护
(C2) 不过量淘汰  |S| = min(required_blocks, |E(R)|)  同 target 语义，queue→E(R)
(C3) 按需最小    |E(R)| ≥ required_blocks 后立即停止  不主动多释放（本轮不授权）
(C4) 压力触发    仅在 free_blocks < required_blocks 时进入释放流程
```

**为什么必须有 (C3)**：$L$ 只对 $S$ 计费，对「释放了多少保护」**不计费**。
若只保留 $S \subseteq E(R)$，则 $E(R)$ 越大、可行集越大，而 $L$ 单调不增，
于是 $R = C$（**把全部候选 Entry 都解除保护**）恒为最优解之一。
那等于把 Continuum 的保护机制整体架空 —— 这正是 RC1 指出的退化。
因此释放量必须由**外生约束** (C3)(C4) 定住，**不能**指望 $L$ 去惩罚它。

**必须承认的代价**：在 (C3) 下 Entry 层不再能选「释放几个」，
只能选**以什么顺序释放、释放到够即止**。即 Entry 层的自由度由
子集选择**收缩为一个排列（permutation）选择**。这是本轮授权的边界而非缺陷；
§5.1 的例子正落在此边界内（两种策略都只释放 1 个 Entry，差别只在选谁）。

### 1.4 关于「局部最优 ≠ 系统最优」

M1 的提醒成立，本设计明确**不做**两层各自最优的声明：

- Entry 层使用的是**可行域启发式**（§3.3），它**不是** $L$ 的一部分，只是一个构造 $E(R)$ 的规则；
- Block 层在给定 $E(R)$ 上做加权轮询，其目标也只是 $L$ 的启发式代理（§3.4）；
- 两者都不声称最优；A3 的收益必须由 §6 的实测给出，而不是由两层的局部论证给出。

---

## 2. 两层各自控制什么

### 2.1 精确的可行池语义（已对源码核实）

对 `src/kvopt/costaware/replay.py::eligible_block_ids` 的逐步核对给出：

$$
b \in E(R) \iff
\begin{cases}
\text{true}, & b \text{ 无 } \texttt{block\_hash} \text{（native hashless 恒可淘汰，见 PR #50 §1.1）}\\\
O(b) \subseteq R, & b \text{ 有 } \texttt{block\_hash}
\end{cases}
$$

其中 $O(b)$ 是 Block $b$ 的**全部** owner Entry 集合（`DecisionSnapshot.owners_by_block`）。

### 2.2 分工

| | Entry 层 | Block 层 |
|---|---|---|
| 控制的量 | $R$（解除哪些保护） | $S \subseteq E(R)$（淘汰哪些） |
| 直接影响 | 可行池 $E(R)$ 的**大小与构成** | **实际** $j_S(r)$，即 $L$ |
| 对重算的作用 | **间接**：只决定「哪些内容有资格被牺牲」 | **直接**：$S$ 是 $L$ 的唯一自变量 |
| 稀缺信号 | 共属关系 $O(b)$：共享 Block 需要**全部** owner 都释放才解锁 | 深度 $j$、各链暴露量、温度/复用代理 |
| H1 中是否可分 | ❌ 不可分（0/81 决策存在 ≥2 Entry 共享 Block，见 §7） | ⚠️ 可分但区分度弱（PR #50 §3） |

**一句话**：Entry 层管「暴露面」，Block 层管「实际损失」。

### 2.3 关键结构事实：释放共享 Entry 是互补的（supermodular）

由 §2.1 直接得到：

$$
E(R) \;=\; \underbrace{\{b \text{ hashless}\}}_{\text{与 } R \text{ 无关}} \;\cup\; \{b \text{ hashed} : O(b) \subseteq R\}
$$

因此当 $A, B$ 共享一段根时（$O(b) = \{A,B\}$）：

$$
E(\{A\}) \cup E(\{B\}) \;\subsetneq\; E(\{A, B\})
\qquad\text{严格包含，而非相等}
$$

**边际可释放容量取决于别人**：这正是 M1 第 2 条要求的
「一次释放之后，其他 Entry 的边际可释放容量如何变化」的形式化答案——

$$
\Delta_B(A) \;:=\; |E(\{A,B\})| - |E(\{A\})| \;\ge\; |E(\{B\})|
$$

⇒ 释放 $A$ **提高**了 $B$ 的边际收益。这一项在 H1 中恒为等式（无共享 ⇒ 恒等），
所以 H1 **结构上无法**体现该效应（§7）。

**与 (C3) 的关系**：互补性只在「达到 `required_blocks` 必须释放多于一个 Entry」时
才有用武之地（§5.1 的 `required_blocks = 10` 情形）。它**不会**被用来论证
「压力已满足后还应该多释放」—— 那种用法已由 (C3) 明确排除。

---

## 3. 实现方案：分层启发式

M1 裁定「统一损失模型为优先设计方向，分层启发式为候选实现方案」。以下即该实现方案。

### 3.1 为什么不能只围绕 relief

`relief`（一次释放带来的新可行 Block 数）只是**容量信号**，它回答「能不能腾出地方」，
不回答「腾出来的是不是重要的内容」。本设计把 relief 降为**约束检查**，不作为排序主键。
排序所需的其余信号见 §3.2、§4。

### 3.2 四个输入维度（对应 M1 第 2 条列出的四项）

```text
① 容量   relief(i|R) = |E(R ∪ {i})| − |E(R)|          → 能否达到 required_blocks
② 复用   未来复用可能性（代理，见 §4.3）              → 牺牲它的代价有多大
③ 重算   丢失后实际需要重算的 token 量（§4.4）        → 代价的物理换算
④ 共享   跨 Entry 共属结构 O(b)（§2.3）               → 释放顺序的互补性
```

### 3.3 Entry 层：可行域启发式（不进入 $L$）

Entry 层**只做一件事**：构造一个 $E(R)$，使其
(a) 满足 $|E(R)| \ge \texttt{required\_blocks}$，且
(b) 尽量把「便宜的牺牲品」暴露出来、把「贵的根」保留。

```text
release_priority(i | R)  升序 = 先释放
   ( 0 if i 是某个 Block 的最后未释放 owner else 1 ,   # 先解锁共享组（互补性）
     share_i(R) ,                                      # 释放后仍被保护的占比：越高越"浪费"，越晚释放
     deadline_timestamp ,                              # 退化到 Continuum 的 TTL 语义
     native_lru_rank_of_newly_eligible_min ,           # 退化到 Continuum 的 LRU 语义
     identity )                                        # 稳定 tie-break
```

**与 Continuum 的差异**：Continuum 的主键是 `deadline_timestamp`，
relief 仅用于「判断是否已够容量」。本设计把**共属拓扑**提到主键之前——
当 `required_blocks` 已经满足时，Continuum 停止释放；
在满足 (C3)「释放到够即止」的前提下，决定**先释放谁**（而非释放几个）。
当 `share_i(R) ≡ 1`（H1 情形）时，主键退化为 Continuum，
**这保证了 A0→A1 是纯增量、不劣化**。

⚠️ **本轮明确不做**：「`required_blocks` 已满足后，仍主动多释放一个 Entry
以解锁共享组」已被 M1 判为超出冻结的按需压力释放语义，**本轮不授权**（RC1）。
该行为若将来确有必要，须单独论证，不得混入第一版。

### 3.4 Block 层：合法候选内的加权轮询

**合法候选集** = $E(R)$（硬约束，§1.3），**不是** native free queue。这是本层与
`NativeLRUAdapter` 的唯一接口差异：后者在 `build_candidates()` 给出的
「free-queue 原生 LRU 序」上排序，而它在语义上已等价于 `lru_rank` 升序取前 `required_blocks`。

给定 $E(R)$，按链分组。对链 $c$，设其 $E$ 内最小深度为 $d_c$、$E$ 内 Block 数 $e_c$，
已分配给 $c$ 的淘汰数 $s_c$，则剩余前缀长度

$$
\rho_c(s_c) \;=\; m_c - (d_c + s_c - 1)
$$

加权轮询每步选 $c^\ast = \arg\max_c \; \alpha_c \cdot \rho_c(s_c)$，
$\alpha_c$ 为该链的复用权重（§4.3）。**为什么不是纯深浅优先**：
PR #50 的跨链反例已证明深度不能作为全局主键（冷短链会因此被误伤）。
$\alpha_c$ 承担「谁更可能回来」，$\rho_c$ 承担「还剩下多长」。

### 3.5 一个必须诚实说明的预测（可能对 A2 不利）

本项目的实测代价曲线 $C(r)$（H2-M1：$r=16 \dots 30720$ tokens）
在 $r \in [16, 1024]$ 上 $C(r)/r$ **单调下降**（13.49×），最小值在 $r \approx 1024$ tokens，
之后才转为上升。

```text
⇒ 在本项目的链长尺度（约 192 tokens = 12 blocks，落在 C 的凹区间内），
  C 是凹的 ⇒ 把损伤拆分到两条链上，总重算代价 **大于** 集中到一条链上：
      C(r1) + C(r2)  >  C(r1 + r2)     (当 C 凹)
```

**因此 §3.4 的「轮询分散」在 aggregate token 口径下可能反而更差。**
这不是放弃 A2 的理由，而是 A2 的**明确待检验命题**：
A2 的价值必须来自**复用可能性不对称**（谁更可能回来），而不是来自「分散本身更好」。
若 §6 实测显示 A2 在 aggregate token 上变差，那就是 A2 的**否定结论**，应当照实记录，
把实现收敛到 A1。

---

## 4. 输入信息来自哪里（M1 第 ① 项要求）

| # | 信号 | 来源（现有代码/产物） | 决策时可得性 | 备注 |
|---|---|---|---|---|
| 4.1 | 候选 Entry 集 $C$、每 Entry 的 Block | `DecisionSnapshot.candidate_keys` / `block_ids_by_key` | ✅ 决策时 | 已冻结 |
| 4.2 | 共属关系 $O(b)$ | `DecisionSnapshot.owners_by_block` | ✅ 决策时 | 无未来信息 |
| 4.3 | 复用可能性代理 | Continuum 已冻结的四类信号：Program Identity、Tool Gap History（`tool_gap_seconds` / `next_tool_type`）、动态 TTL（`retention_deadline_timestamp`）、Prefill Cost（`prefill_reload_seconds`） | ✅ 决策时 | **不新训练模型**；直接复用 Continuum 的既有估计 |
| 4.4 | 重算 token 换算 | `block_hash_num_tokens`（vLLM `KVCacheBlock` 字段）→ `VLLM_PREFIX_SNAPSHOT.hash_num_tokens`（H1 中 903 条快照、10 个不同值、min 16 / median 112 / max 512） | ✅ 可离线重建 | 使 $B$ 不必假设为常数 |
| 4.5 | 物理淘汰集合 $S$、$j_S(r)$ | 由本设计产出；评测时用 `observed_recomputed_tokens` / `observed_physical_eviction_blocks` | 仅评测期 | 属 `FORBIDDEN_FEATURES`，**不得**作为决策输入 |
| 4.6 | 容量需求 | `EvictionContext.required_blocks` / `free_blocks` / `total_blocks` | ✅ 决策时 | 冻结 |
| 4.7 | Native 顺序 | `DecisionCandidateRow.decision_native_lru_position` | ✅ 决策时 | 仅作 warm-start / tie-break |

**合规红线**：`src/kvopt/costaware/rules.py::FORBIDDEN_FEATURES`
（`returned_after_decision`、`observed_recomputed_tokens`、`physical_eviction_count` 等）
在本设计中**一律不作为决策输入**，只出现在评测侧。
这与 PR #50 §5.6 的 `OursEvictAdapter` 规范保持一致。

---

## 5. 两个具体例子（M1 第 ③ 项要求）

### 5.1 例一（Entry 层）：共享根 + 不对称尾巴

```text
Block 布局（每 Block = B tokens）
  共享根 : p1..p8        O(pk) = {A, B}          ← 两份共享
  A 的尾 : p9..p16       O = {A}                 ← A 独有 8 blocks
  B 的尾 : p17..p18      O = {B}                 ← B 独有 2 blocks
required_blocks = 2
```

| | Continuum（`deadline` 为主键） | 本设计（共属拓扑优先） |
|---|---|---|
| 释放 | 若 $A$ 的 deadline 更早 → 释放 $A$ | 释放 $B$（$B$ 是唯一能独立解锁的组，且解锁量恰好够 2） |
| 可行池 | $E(\{A\}) = \{p_9..p_{16}\}$（8 blocks）；根仍被 $B$ 保护 | $E(\{B\}) = \{p_{17},p_{18}\}$（2 blocks） |
| 实际淘汰 | 必须从 $A$ 尾部淘汰 2 个 → $j(A)$ 下移 | 淘汰 $B$ 的 2 个 → $j(B)$ 下移 |
| 结果 | 破坏 $A$ 的可复用后缀（8 blocks 已全部暴露） | 只破坏 $B$ 的后缀 |

**选择确实不同**，且差异**不能**由单 Entry 的价值密度解释：
两条路径都能满足 `required_blocks = 2`，差别在**暴露面的形状**——
Continuum 一次性把 $A$ 的 8 个 Block 全部变成合法牺牲品（其中 6 个本不必动）。

⚠️ 注意：本例中「多释放」并未发生（两者都只释放 1 个 Entry），
所以**不触及 (C3) 的主动释放边界**。若把 `required_blocks` 改为 10，则必须同时释放 $A$ 与 $B$
才能解锁根，此时两层互补性才会显现。

### 5.2 例二（Block 层）：集中 vs 分散，并暴露 §3.5 的凹性预测

```text
链 α : m_α = 12,  E 内深度 9..12,  e_α = 4
链 β : m_β = 6,   E 内深度 1..6,   e_β = 6
required_blocks = 4
```

| 策略 | 淘汰集合 | $j_\alpha$ | $j_\beta$ | 重算 |
|---|---|---|---|---|
| 集中（native LRU 取最冷） | α@9,10,11,12 | 9 | 无 | $(12-9+1)B = 4B$ |
| 分散（加权轮询） | α@11,12 + β@5,6 | 11 | 5 | $(12-11+1)B + (6-5+1)B = 4B$ |

**线性代价下两者总量相同**（这正是 RR-EVICT 的线性不变性）。差异只能来自：

```text
(i)  C(r) 非线性 —— 本项目的 C 在当前尺度是凹的 ⇒ 分散更差（§3.5）
(ii) 链的返回概率不同 ⇒ 应保护 α_β 中更可能返回者 ⇒ 分散/集中由 α_c 决定
```

⇒ 例二的价值不在于「本设计更好」，而在于**它把 A2 的胜负条件显式化了**：
A2 只有在 (ii) 成立且强于 (i) 时才有 aggregate 收益。这正是 §6 要测的东西。

---

## 6. 最小实验方案（M1 第 ④ 项要求）

### 6.1 必须先修好的前提

M1 明确要求「在修复后的真实共享前缀工作负载中验证」，前提有两项：

```text
前提甲 : 真实共享前缀。PR #50 §1.0 已记录 H1 的 F-PREFIX 缺陷。
         修复点已定位在 src/kvopt/workload/phase2e_materialize.py::_segments
         （当前 even draw = NO_SHARED 负对照，odd draw = SHARED_ROOT 处理组）。
前提乙 : 多轮增长 + 返回概率不对称。H1 的 F-ARRIVAL / F-HISTORY 使
         「谁更可能回来」无区分度，导致 §3.4 的 α_c 无信号。
```

⚠️ 未修好前提就开跑，只会再得到一次「区分度弱」的结论。**建议先做 §6.2 的 Step 0。**

### 6.2 四臂递进（对应 M1 的 A0–A3）

| 臂 | 定义 | 目的 | 预期 |
|---|---|---|---|
| **A0** | 原始 Continuum（**冻结基线**） | 对照 | — |
| **A1** | Entry 层 Cost-Aware 释放 + native LRU 淘汰 | 最小增量，§3.3 | 若 A1 稳定有收益即先收敛到此 |
| **A2** | Continuum 释放 + Block 层加权轮询（$E(R)$ 内） | 检验 §3.5 的凹性预测 | **可能为负**，见 §3.5 |
| **A3** | Entry + Block 联合（即 §1.3 的两变量） | 仅在 A2 有额外收益时再做 | — |

### 6.3 Step 0 —— 离线的区分度门槛（先做，成本极低）

在修复后的语料上，**只做 replay，不跑 native**，先确认样本具备可区分性：

```text
门槛 0.1  存在 ≥2 Entry 共享 Block 的决策占比            > 0（H1 为 0/81）
门槛 0.2  这些决策中 E({A}) ∪ E({B}) ⊊ E({A,B}) 的占比   > 0（互补性可发生）
门槛 0.3  Σ_c 上 |C(r1)+C(r2) − C(r1+r2)| 的相对幅度      > 噪声
门槛 0.4  返回概率代理在链间存在非零方差（否则 α_c 无意义）
```

任一门槛不满足 ⇒ **停止**，报告该臂在本语料上不可测，不得继续扩实验。
（此即 PR #50 §1.0 的教训：先确认语料能表达该效应，再谈算法收益。）

### 6.4 Step 1 —— 离线 replay 主战场（成本低，可全量）

用 `src/kvopt/costaware/replay.py` 的 replay 框架，在**同一批决策**上比较
`A0 / A1 / A2 / A3` 四个 `ReleaseStrategy` + victim chooser。记录：

```text
主指标   L(S) 的代理：Σ_r (m_r − j_S(r) + 1)·B        ← §1.2，唯一记录量
分解     j_S(r) 分布、每链损伤深度、每链被淘汰 Block 数
对照     Σ_c [C(r_c) 实测] 与线性 Σ B 的差（实证凹/凸，检验 §3.5）
合法性   S ⊆ E(R) 被违反的次数（必须为 0，§1.3）
(C2) 违规   |S| ≠ min(required_blocks, |E(R)|) 的次数（必须为 0）
(C3) 违规   |E(R)| ≥ required_blocks 之后仍有释放的次数（必须为 0）
```

### 6.5 Step 2 —— 最小配对的 native 验证（成本高，样本小）

仅在 Step 1 出现 ≥1 个稳定方向后执行；方法沿用 Phase 2E 的配对协议
（同 seed、同 workload、同 backend，仅策略不同），样本量取最小可判读规模。

```text
主指标    TTFT（H1 已确认可直接测量：native_queued_timestamp →
          native_scheduler_admission_timestamp → native_first_token_timestamp）
注意      Spearman(重算 token, TTFT) = 0.4327 ⇒ token 收益 **不**按比例传导到延迟
          ⇒ 必须同时报告「重算 token」与「TTFT」两个口径，不得只报一个
```

### 6.6 明确不做的部分

```text
❌ 不修改 native BlockPool / ref_cnt / hash 清理 / LRU
❌ 不修改冻结的 Continuum baseline 与 TTL 估计器
❌ 不做正式 runtime 策略实现（M1 未授权）
❌ 不做大规模实验（M1 未授权）
❌ 不新增离线训练模型（§4.3 复用 Continuum 既有信号）
❌ 不在压力满足后主动多释放 Entry（RC1，本轮不授权）
```

---

## 7. 为什么 H1 无法支撑本设计（以及不重复审计）

```text
0/81     决策中存在 ≥2 个 Entry 共享 Block        ⇒ §2.3 的互补性恒不存在
0/81     Entry band 非连续或相交                  ⇒ Entry 层无拓扑可优化
471/471  relief ≡ block_count                     ⇒ relief 退化为单一整数，无信息量
294/294  native_lru_rank 与 index 单调一致(仅在 H1) ⇒ Block 层只剩名次取前 k
```

⇒ H1 上 A1 会**精确退化为 A0**（§3.3 的退化分支），A2 会退化为 `NativeLRUAdapter`。
**这解释了 PR #50 §3.3 / §5.6 那些 0 值**，也说明它们**不是**对 Block-level 方向的否定
（PR #50 已按 M1 要求收紧为「该接口 + 该语料」）。

本文**不再**对这四点做新一轮审计（M1：重点放在算法设计）。

---

## 8. 边界与待裁定事项

1. **B1 / 主动释放**：M1 已裁定「`required_blocks` 满足后仍主动多释放」**不授权**；
   §3.3 已按 (C3) 改为释放到够即止。该方向保持关闭，待单独论证后再议。
2. **部分前缀保护**：本设计只处理**整 Entry 释放**；若未来需要按 Block 粒度解除保护
   （即 PR #50 的四字段接口不足以表达 $O(b)$ 的按 Block 语义），需先扩展接口并另行评审。
3. **A2 的取舍**：若 §6.4 显示 A2 在 aggregate token 上为负而仅在尾部风险上为正，
   请裁定以哪个口径为准（本项目此前声明的主口径是 aggregate token）。

---

## 9. 与既有材料的关系

| 材料 | 关系 |
|---|---|
| `docs/ours-evict-algorithm-design-v1.md`（PR #50） | 保留为**当前接口局限性的分析记录**；本文不复用其 H1 外推 |
| PR #44 / Phase 2D | 提供 A2 验证所需的**共享保留**最小夹具 |
| PR #45 / Phase 2E Task A | 指标冻结；本文沿用其口径，不新增主指标 |
| `src/kvopt/continuum/pressure.py` | **冻结基线 A0**，只读；本文的 A1 是其增量，退化分支保证不劣化 |
| `src/kvopt/costaware/replay.py` | 提供 `ReleaseStrategy` 协议与 `ExecutedP1BStrategy` 先例，是 Step 1 的载体 |
| `src/kvopt/runtime/vllm/adapter.py` | A2 的实现落点（`EvictionPolicyAdapter`），但**当前只读** |

---

## 10. 可追溯性

| 本文结论 | 依据 |
|---|---|
| $E(R) = \{b : O(b) \subseteq R\} \cup \{$hashless$\}$ | `costaware/replay.py::eligible_block_ids` 逐行核对 |
| $E(\{A\}) \cup E(\{B\}) \subsetneq E(\{A,B\})$ | 由上式直接推出（$O(b)=\{A,B\}$） |
| Continuum 释放主键为 `deadline` 优先 | `continuum/pressure.py:324` |
| 线性代价下集中/分散总量相同 | §5.2 算例；与 PR #50 §4 的线性不变性一致 |
| (C2)(C3) 释放/淘汰量的口径 | `costaware/replay.py` 的 `target = min(required_blocks, len(queue))`；`continuum/pressure.py` 的按需释放循环 |
| $R = C$ 是未加 (C3) 时的退化最优解 | 由 $L$ 对释放量不计费、且 $E(R)$ 对 $R$ 单调不减直接推出（RC1） |
| $C(r)/r$ 在 $[16,1024]$ 单调下降（凹） | H2-M1 实测代价曲线（13.49× 跨度，最小值 $r\approx1024$） |
| `block_hash_num_tokens` 可离线重建 | `VLLM_PREFIX_SNAPSHOT` 含 `hash_num_tokens`（903 快照 / 10 值 / min16 med112 max512） |
| H1 无共享：0/81、0/471、294/294 | `local/probe_entry_vs_block.py`、`local/probe_rev3_verify.py`（本地探针，未纳入提交） |
| `FORBIDDEN_FEATURES` | `costaware/rules.py` |
| TTFT 可直接测量 | `VLLM_NATIVE_REQUEST_OBSERVATION` 三时间戳，100% 填充 |
| 重算 token 不按比例传导到 TTFT | Spearman = 0.4327 |
