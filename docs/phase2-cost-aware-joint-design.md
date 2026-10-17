# Cost-Aware KV 淘汰：Entry + Block 联合设计（最小版）

> 状态：**设计草案，未实现**
> 依 M1 裁定：本文只做设计，不做 runtime 策略实现、不做大规模实验。
> 修订：rev.2 依 M1 RC1 为目标函数补充释放约束 (C1)–(C4)，
> 并撤回「压力满足后仍主动多释放 Entry」的表述（本轮不授权）。
> 修订：rev.3 依 M1 RC2 以期望重算代价 $\widehat{R}_i$ 取代纯拓扑排序键，
> 并按新公式重算 §5.1（旧版例子与旧版规则不自洽，已作勘误）。
> 修订：rev.4 依 M1 RC3 废弃 Block 层 WRR（权重方向错误 + 不表达 APC 连续前缀损失），
> 改为逐 Block 最小边际重算损失，并重算 §5.2。
> 修订：rev.5 依 M1 RC4 统一成本口径为 aggregate recomputed tokens；
> 撤回「$C(r)/r$ 下降 ⇒ $C$ 凹」的推断（正确蕴含是次可加），
> 并把 $C(r)$/TTFT/queue delay 降为辅助观测；勘误 `block_hash_num_tokens` 的语义。
> 修订：rev.6 依 M1 RC5 把 Step 0 门槛按臂拆分、如实列出 A2/A3 的工具缺口
> （replay 当前只支持 Entry 释放），并明确离线估计不等于收益。
> 修订：rev.7 依 M1 四处修正：C4 改用 |E(R)| 触发；补 N_i = 0 的零边际处理；
> 明确 q/λ 是启发式代理并给出 §5.2 的合法运行状态；删除「H1 上 A1 = A0」的断言。
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

$\mathcal{R}_{\text{future}}$：未来会返回且命中该前缀的请求；
$B = \texttt{block\_size}$，**常数**（见 §4.4 的勘误）。

**指标口径（RC4 统一，全文适用）**——本设计只有一套成本量纲：

```text
主目标    aggregate recomputed tokens = L(S)         ← 全部规则的排序与取舍依据
辅助观测  prefill 时间 C(r) / TTFT / queue delay      ← 只用于解释，不参与任何排序
```

两者**不可混用**：$L(S)$ 的记账单位是 token，$C(r)$ 的记账单位是时间。
本设计的所有排序量（$\widehat R_i$ 与 $\Delta(b)$）都只在 token 量纲内计算；
时间量纲只出现在 §6.5 的辅助观测中，用途是解释
「token 收益为何不按比例体现为延迟收益」，而不是用来判定策略优劣。

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

**释放约束（C1–C4）** —— 回应 RC1。这里 `target = min(required_blocks, len(original_free_queue))`，与冻结 `pressure.py` 一致。第一版不追求联合最优，只把释放行为钉死在
冻结的按需压力语义之内：

```text
(C1) 合法淘汰    S ⊆ E(R)                           Block 层不得绕过保护
(C2) 不过量淘汰  |S| = target（合法候选足够时）  不超额进行物理淘汰
(C3) 按需最小    |E(R)| ≥ target 后立即停止  不主动多释放（本轮不授权）
(C4) 压力触发    仅在 |E(R)| < target 时进入释放流程
```

**为什么必须有 (C3)**：$L$ 只对 $S$ 计费，对「释放了多少保护」**不计费**。
若只保留 $S \subseteq E(R)$，则 $E(R)$ 越大、可行集越大，而 $L$ 单调不增，
于是 $R = C$（**把全部候选 Entry 都解除保护**）恒为最优解之一。
那等于把 Continuum 的保护机制整体架空 —— 这正是 RC1 指出的退化。
因此释放量必须由**外生约束** (C3)(C4) 定住，**不能**指望 $L$ 去惩罚它。

**关于 (C4) 的触发量（rev.7 修正）**：触发条件必须用**合法可淘汰块数**，
**不能**用 `free_blocks`。`free_blocks` 是 native free queue 的长度，
其中包含仍受 Continuum 保护的缓存块，因此它 **不等于** 当前可淘汰的块数；
以它作判据会在仍有合法候选时误判为「需要解除保护」，或在无合法候选时误判为「无需释放」。

```text
Continuum 冻结语义：while len(tier_1_ids | tier_2_ids) < target   （pressure.py:107）
                           target = min(required_blocks, len(queue))
本设计等价式：      while |E(R)| < target
  其中 E(R) 就是 tier_1 ∪ tier_2 的重算（hashless 恒 eligible；hashed 需无受保护 owner）
⇒ 直接复用 Continuum 的判定，不引入 free_blocks 这个不同量纲的量
```

**必须承认的代价**：在 (C3) 下 Entry 层不再能选「释放几个」，
只能选**以什么顺序释放、释放到够即止**。即 Entry 层的自由度由
子集选择**收缩为一个排列（permutation）选择**。这是本轮授权的边界而非缺陷；
§5.1 的例子正落在此边界内（两种策略都只释放 1 个 Entry，差别只在选谁）。

### 1.4 关于「局部最优 ≠ 系统最优」

M1 的提醒成立，本设计明确**不做**两层各自最优的声明：

- Entry 层使用的是**成本排序启发式**（§3.3），它**不是** $L$ 的一部分，只是一个构造 $E(R)$ 的规则；
  其评分 $\widehat{R}_i$ 是 $L$ 的代理，但**不是** $L$ 本身（它含 $\lambda$ 这类启发式权重）；
- Block 层在给定 $E(R)$ 上按**最小边际重算损失**逐 Block 选择（§3.4），
  其目标是 $L$ 的精确单步增量，但逐步贪心**不保证**全局最优；
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
① 容量   N_i(R) = |E(R ∪ {i})| − |E(R)|          → 能否达到 required_blocks（约束）
② 复用   q_i，由 Continuum 的 TTL 单调给出        → 牺牲它的概率
③ 重算   丢弃后实际需要重算的 token 量（§4.4）    → 代价的物理换算，B × blocks
④ 共享   共属结构 O(b)（§2.3）                     → 决定 N_i，并通过 N_i 进入成本
```

M1 曾指出「不能只围绕 relief 设计」。本设计据此把 ① 降为**约束**，
把 ②③ 合成 **期望重算代价** 作为唯一排序量，把 ④ 作为产生 $N_i$ 的结构来源。

### 3.3 Entry 层：可计算的 Cost-Aware 释放排序

Entry 层只做一件事：在满足 (C3)「释放到够即止」的前提下，决定**先释放谁**。

> **RC2 修订说明**：旧版排序键为 `last-owner → share → deadline → LRU`，
> 其中没有任何成本量，实质是**共享拓扑启发式**，不是 Cost-Aware Release。
> 该键已整体废弃，替换为下面的期望重算排序。旧键的另一个问题是它与 §5.1 的例子
> 自相矛盾（按 `share` 升序会选 $A$ 而非文中声称的 $B$，见 §5.1 的勘误）。

#### 3.3.1 五个可计算量

```text
需求      D      = min(required_blocks, len(original_free_queue))  # 冻结 target
剩余缺口  G(R)   = max(0, D − |E(R)|)        # 已有合法候选先抵扣压力需求
新增暴露  N_i(R) = |E(R ∪ {i})| − |E(R)|    释放 i 新解锁的 Block 数（由 O(b) 决定）
复用概率  q_i    ∈ (0,1]                    见 3.3.3，Continuum 既有信号的单调变换
Block 大小 B                                 见 §4.4，block_hash_num_tokens，可不为常数
后续压力  λ      ∈ [0,1]                    见 3.3.3
```

#### 3.3.2 评分：期望未来重算 token

$$
\widehat{R}_i(R) \;=\; q_i \cdot B \cdot \Bigl[\,
\underbrace{\min(G,\,N_i)}_{\text{本次最多可能涉及的新暴露}}
\;+\;
\underbrace{\lambda\,\bigl(N_i-\min(G,N_i)\bigr)^{+}}_{\text{残留暴露面的后续代价}}
\,\Bigr]
$$

**两项的物理含义**：

- **第一项**：以剩余缺口 $G$ 截断新暴露量，是本次压力**最多可能选中**的新增候选数量；已有 eligible blocks 及 Block 选择顺序可能使实际被选中的数量更少。它只是 token 风险代理，**不是必然的物理淘汰量或精确重算损失**。
- **第二项**：未在本次压力中使用的新增 eligible blocks 可能在后续压力事件继续暴露，但仍可能被重新保护或更早被实际淘汰，因此这也只是风险代理。
  暴露面越大，后续压力事件可继续取用的就越多。$\lambda$ 是「$i$ 的剩余生命周期内
  还会发生一次强制淘汰」的估计概率。这一项是**共享结构进入成本的唯一通道**：
  $N_i$ 完全由 $O(b)$ 决定（§2.3）。
- 两项都乘 $q_i$：只有 $i$ 真的回来，重算才会发生。

**为什么不能把 $N_i$ 放进分母**：relief 是**可行域约束**（能否达到 $D$），
不是要最大化的量。第二项已经惩罚了「不必要的过度暴露」；再除以 $N_i$ 会把该惩罚
抵消，并导致「越过度暴露越优先」。旧键用 `share` 升序正是犯了这类错误。

#### 3.3.3 $q_i$ 与 $\lambda$ 怎么算（不训练新预测器）

$$
q_i \;=\; \sigma\!\left(\frac{\mathrm{deadline}_i - t}{\tau}\right),
\qquad \sigma(x)=\frac{1}{1+e^{-x}}
$$

- `deadline` = Continuum 动态 TTL 的 `retention_deadline_timestamp`。离过期越远 ⇒
  越可能被再次命中 ⇒ $q_i$ 越大。这是对 Continuum 既有估计的**单调变换**，
  因此 $q$ 的排序与 Continuum 的 `deadline` 一致 —— 本设计**不推翻** TTL，
  而是在同一偏好方向上补充「暴露面大小」与「重算量」两个维度。
- $\tau$ = 时间尺度常数，取 Tool Gap History 的典型间隔（§4.3），**无新增拟合参数**。
- **$q_i$ 的读法（rev.7 明确）**：$q_i > 0.5 \iff \text{deadline}_i > t$，
  即该 Entry 的 TTL **尚未到期**；$q_i < 0.5$ 表示 **已过 TTL 但尚未被释放**
  —— 这正是在一次强制释放决策上出现的合法状态，因为 Continuum 按 `deadline`
  升序释放，轮到它时其 deadline 往往已经在 $t$ 之前。
- **$q_i$ 与 $\lambda$ 都是启发式代理，不是已校准的未来事件概率**（M1 第 3 点）。
  它们只用于**排序**，量纲和取值不承担概率解释；不得把它们报成
  「该 Entry 以 0.3 的概率被复用」这类断言。
- $\lambda = \min(1, H_{\text{evict}} / H_{\text{total}})$，即历史决策中
  「发生强制淘汰」的占比。Continuum 的 pressure 统计与离线 replay 的决策序列
  都可直接给出该量。

可选精化（**不进第一版**）：$q_i$ 再乘 Program Identity 匹配度，或用
`prefill_reload_seconds` 做归一化项。第一版保持单参数，便于归因。

#### 3.3.4 释放流程（含 N_i = 0 的处理）

```text
1) D = min(required_blocks, len(queue))；G = max(0, D-|E(R)|)
   若 D = 0 或 G = 0                       → 不进入释放（C4，见 §1.3）
2) F  = { i ∈ C : |E(R ∪ {i})| >= D }     # 单步足够集
   C⁺ = { i ∈ C : N_i > 0 }               # 有正边际的候选
3) 分支：
   3a) F ≠ ∅        → 选 argmin_{i∈F} R̂_i          # 单步即可满足
   3b) F = ∅, C⁺≠∅  → 选 argmin_{i∈C⁺} R̂_i / N_i   # 边际稀缺，按单位成本换容量
   3c) C⁺ = ∅       → 两 Entry 前瞻（见下）
4) R ← R ∪ selected（单 Entry 为 {i}，两 Entry 前瞻为 {i,j}）；
   若 |E(R)| < D 回到 2)；否则停止（C3）；每轮重算 G
5) 并列时 deadline 升序 → identity 打破
```

##### 3.3.4.1 为什么会有 $N_i = 0$

若若干 Entry **共同**保护同一组 Block，释放其中任何一个都不解锁任何块：
$O(b) = \{i, j\}$ 时 $O(b) \not\subseteq \{i\}$ 且 $O(b) \not\subseteq \{j\}$。
此时 $N_i = 0$，$\widehat R_i / N_i$ **无定义**（不是无穷大，是未定义）。

```text
H1 实测：0/81 决策出现「全部候选 N_i = 0」（无共享 ⇒ 见 §7）
⇒ 该分支在 H1 上不会触发，但在修复后的共享前缀语料上**必然**会触发
```

##### 3.3.4.2 零边际候选的处理（第一版，不做全局优化）

**两 Entry 前瞻**：对每个候选对 $(i,j)$ 计算联合边际

$$
N_{ij} = \bigl|E(R\cup\{i,j\})\bigr| - |E(R)|
$$

只在 $N_{ij} > 0$ 的对上评分。联合损失沿用同一结构，
但**暴露面只计一次**（避免把联合解锁的块重复计入两个 Entry）：

$$
\widehat R_{ij} = \tilde q_{ij}\cdot B\cdot\Bigl[
\min(G, N_{ij}) + \lambda\bigl(N_{ij}-\min(G,N_{ij})\bigr)^{+}\Bigr],
\qquad \tilde q_{ij} = 1-(1-q_i)(1-q_j)
$$

选 $\arg\min_{(i,j):\,N_{ij}>0} \widehat R_{ij} / N_{ij}$，
依次释放 $i$ 与 $j$（两者都释放后才真正解锁共享块）。

```text
若不存在 N_ij > 0 的对 ⇒ 退化为 deadline 升序单步释放（保证有进展，
因为释放全部候选必然使每个队列块都无受保护 owner，|E(R)| 达到上界）
```

**明确的取舍**：只做 **两** Entry 前瞻，不做 $k$ Entry 的搜索。
三层以上共享需要 $O(|C|^k)$，超出第一版范围；若 §6.4 显示三元以上共享常见，
再单独评估（不在本轮）。

**$\tilde q_{ij}$ 的含义仅为有界的联合启发式权重**：$q_i,q_j$ 并非校准概率，且两条 Entry 的返回事件可能相关；因此 $1-(1-q_i)(1-q_j)$ **不能作为真实的并集概率或无相关性结论**。这里仅用其将共享块暴露风险压到一个有界权重中，后续效果须通过 native 观测验证。

**与 Continuum 的差别（可精确陈述）**：当所有候选的 $N_i$ **相同**时，
$\widehat R_i$ 方括号内为公共常数，故 $\widehat R_i \propto q_i$，
排序**精确退化**为 Continuum 的 `deadline` 序 —— 这是严格成立的条件，不是近似。

⚠️ **但这不等于「H1 上 A1 = A0」**（rev.7 修正，M1 第 4 点）。
H1 没有共享结构，只保证 $N_i$ 等于该 Entry 的私有块数，**不保证各 Entry 的 $N_i$ 相同**；
Entry 大小不同则 $N_i$ 不同，排序就会偏离 `deadline`。实测：

```text
H1：81 个多候选决策中，72 个（88.9%）存在 >1 个不同的 N_i
    平均每决策 3.04 个不同取值；「全部 N_i = 0」0/81
⇒ A1 与 A0 在 H1 上**一般不同**，必须按 §6.4.4 实测判定
```

其余情形本设计会与 Continuum 不同，且**不保证逐决策不劣化** ——
A1 的优劣必须由 §6.4.4 的离线 replay 判定（这也是 §6 先跑 replay 再跑 native 的原因）。

⚠️ **本轮明确不做**：「`required_blocks` 已满足后，仍主动多释放一个 Entry
以解锁共享组」已被 M1 判为超出冻结的按需压力释放语义，**本轮不授权**（RC1）。
该行为若将来确有必要，须单独论证，不得混入第一版。

### 3.4 Block 层：逐 Block 最小边际重算损失

**合法候选集** = $E(R)$（硬约束，§1.3），**不是** native free queue。这是本层与
`NativeLRUAdapter` 的接口差异：后者在 `build_candidates()` 给出的「free-queue 原生 LRU 序」
上排序，语义上等价于 `lru_rank` 升序取前 `required_blocks`。

> **RC3 修订说明**：旧版规则为
> $$c^\ast=\arg\max_c \alpha_c\rho_c(s_c),\qquad \rho_c(s_c)=m_c-(d_c+s_c-1)$$
> 该式有两个独立缺陷，M1 均指出且均成立：
>
> **(a) 权重方向反了**。$\alpha_c$ 是「未来越可能复用越大」，那么 $\arg\max$
> 会**优先淘汰价值最高的链**，与最小化期望重算的目标直接冲突。
>
> **(b) $\rho_c$ 不是 APC 的连续前缀损失**。APC 的损失由**最浅的被淘汰深度**
> $j_c$ 决定：淘汰位置 9 之后再淘汰 10，重算量不变；而从 12 继续退到 11，
> 才会扩大缺失后缀。$\rho_c$ 只数「还剩多长」，无法表达这一区别。
>
> 该式已整体废弃。

#### 3.4.1 APC 连续前缀损失的精确表述

链 $c$ 的前缀为 $p_1(r)\dots p_{m_c}(r)$，深度 1 为根。设 $S_c$ 为链 $c$ 上**已被淘汰**
的深度集合（可能为空）：

$$
j_c(S) = \min S_c \quad (S_c\neq\varnothing), \qquad j_c(S)=m_c+1 \quad (S_c=\varnothing)
$$

$$
R_c(S) = (m_c - j_c(S) + 1)\cdot B \quad (S_c\neq\varnothing), \qquad R_c(S)=0 \quad (S_c=\varnothing)
$$

**关键性质**：$R_c$ 只依赖 $j_c$，即「最浅缺口」。缺口以下的 Block 全部作废，
缺口以上完好 —— 这正是 APC 的前缀语义。

#### 3.4.2 单 Block 的边际损失（精确，非近似）

在候选 Block $b$ 处新增一次淘汰，其深度记为 $d_c(b) \notin S_c$：

$$
\Delta_c(b) \;=\; R_c(S\cup\{b\}) - R_c(S) \;=\; q_c \cdot B_b \cdot \bigl(j_c - d_c(b)\bigr)^{+}
$$

三种情形，逐一对应 M1 的观察：

```text
d_c(b) > j_c   ⇒ Δ = 0        更深于缺口：已经作废，淘汰它不增加任何重算  ← 免费块
d_c(b) < j_c   ⇒ Δ = q_c·B   更浅于缺口：缺口上移 (j_c − d) 位，缺失后缀随之扩大
S_c = ∅        ⇒ j_c = m_c+1    全新链：从尾部淘汰 Δ = q_c·B（正常代价）
```

由此还得到一个**必须遵守的次序性质**：在同一链上从尾部连续往浅处淘汰时，
每一步的 $\Delta$ 恒为 $q_c B$（线性）；若跳过中间块直接打更浅的位置，
单价会变成 $(j_c-d)$ 倍。所以「按深度由深到浅」是唯一不浪费的次序。

**$B_b$ 的口径**：$B_b$ 是**该 Block 的 token 数**，对满块恒等于常数
$B=\texttt{block\_size}$。唯一例外是每条链的**末块**可能是部分块
（token 数 $\le B$）。它只改变该链最后一个 Block 的单价，
不改变 §3.4.3 的排序结构；第一版按常数 $B$ 处理，
并在 §6.4 把末块实际 token 数列为核对项。

#### 3.4.3 选择规则

每步在**合法候选**中选边际损失最低的 Block：

$$
b^{\ast} = \arg\min_{b\in E(R)\setminus S}\; \Delta(b),
\qquad
\Delta(b) = \sum_{c\,:\,b\in \mathrm{chain}(c)} \Delta_c(b)
$$

重复 $\min(D,\,|E(R)|)$ 次（(C2)），每次重新计算 $j_c$ 与 $\Delta$。

实现上可用一个按 $\Delta$ 的最小堆：每淘汰一个 Block 只影响它所属链的 $\Delta$，
复杂度 $O(|E(R)|\log|E(R)|)$，无需迭代求解。

#### 3.4.4 这个规则自动满足 RC3 的两点要求

```text
方向    q_c 出现在分子并被最小化 ⇒ 高复用链的 Δ 大 ⇒ 最后才被淘汰
        （旧式 argmax 恰好相反，这是 RC3 (a) 的修正）
连续前缀 (j_c − d)^+ 直接来自 APC 语义 ⇒ 缺口以下的块 Δ=0，自动先收免费块；
        只有真正上移缺口才付费（RC3 (b) 的修正）
```

**注意一个反直觉但正确的推论**：本规则**不会**在链间分散损伤。
在一条完好链上连续从尾部淘汰时 $\Delta \equiv q_cB$ 为常数，
因此它会**先把最便宜的链打穿**（直到该链的合法最浅深度），再换下一条。
**但注意**：在 token 口径下这不带来任何优势 —— $q_c$ 相同时，集中与分散的
token 总量完全相同（§3.5.2）。旧 WRR 的分散行为也不是它更差的原因；
它更差是因为权重方向反了（§3.4 的 RC3 说明）。

#### 3.4.5 共享 Block 如何避免重复计数

一个物理 Block 可能同时属于多条链（$|O(b)|>1$，§2.1）。规则只有一条：

```text
Δ(b) 对「包含 b 的每条链」各计一次 —— 计的是链数，不是 owner 数。
```

**为什么这不是重复计数**：若 Block $b$ 被 A、B 共享且被淘汰，A 返回时要重算 $b$，
B 返回时**也要**重算 $b$ —— 这是两次真实的 prefill，不是同一笔成本记账两次。
真正的重复计数是另一种做法：既把 $b$ 记在「Entry 层损失」里，又把 $b$ 记在
「Block 层损失」里。本设计只有 §1.2 的单一损失 $L(S)$，$\Delta(b)$ 是其精确的
单步增量，所以该风险在结构上不存在。

**与 Entry 层的分工不重叠**：Entry 层决定 $E(R)$（谁可以进候选），
Block 层只在这个集合内按 $\Delta$ 排序。$N_i$ 的共享效应已经在 §3.3 的
$\widehat R_i$ 里计过一次（作为暴露面），此处计的是**实际淘汰哪个 Block**
造成的重算，两者对应不同的决策变量，不是同一件事的两份账。

#### 3.4.6 Weighted Round-Robin 的去留

M1 说「不必为了保留轮询而强行设计复杂公式」，我接受，**不再保留 WRR 作为主规则**。
若仍需一个轮询式对照，只能按以下修正后的形式，且必须写成：

```text
对照变体 WRR'（仅作 baseline，不作主张）：
  c* = argmin_c  q_c · (该链下一次淘汰的边际损失)
  即把旧式的 argmax 改为 argmin，并仍按链粒度而非 Block 粒度推进。
  WRR' 与 §3.4.3 的差别仅在「按链推进」vs「按 Block 取最小」，
  在 Δ 可加的情形下两者逐步等价；差异只在共享 Block 的聚合方式上。
```

**不主张 WRR' 更优**：它只是用来检查「按链推进」是否引入损失。

### 3.5 代价口径：为什么 token 口径下不引用 $C(r)$ 的凹性

> **RC4 修订**：旧版本节由「$C(r)/r$ 下降」推出「$C$ 是凹函数」，再用
> $C(r_1)+C(r_2)>C(r_1+r_2)$ 论证「分散更差」。这个推断**不成立**；
> 而且它把**时间**量纲的结论用在了**token**量纲的规则选择上。两点均已撤回。

#### 3.5.1 正确的蕴含是次可加，不是凹

$C(r)/r$ 在 $r>0$ 上单调不增，能严格推出的是**次可加性（subadditivity）**：

$$
\text{对 } r_1,r_2>0,\; s=r_1+r_2:\quad
C(r_1)+C(r_2)
= r_1\frac{C(r_1)}{r_1}+r_2\frac{C(r_2)}{r_2}
\;\ge\; r_1\frac{C(s)}{s}+r_2\frac{C(s)}{s}
= C(s)
$$

只需平均成本不增，即 $C(r_1)/r_1 \ge C(s)/s$（因 $r_1 \le s$）。

```text
凹 (concave)  ⇒  次可加         充分条件
次可加        ⇏  凹            所以「C(r)/r 下降」推不出凹性
```

⇒ 旧版的**结论方向对，来源写错了**：$C(r_1)+C(r_2)>C(r_1+r_2)$ 来自次可加，
不来自凹性。本节据实修正，不再使用「凹」这个说法。

#### 3.5.2 但这条对 token 口径没有用

即使次可加成立，它陈述的是**时间**。主目标是 aggregate recomputed tokens，
而 token 口径下 $L(S)$ 对每条链是**严格线性**的：

$$
L(S)=\sum_c q_c\cdot(\text{链 } c \text{ 被淘汰的 token 数}),
\qquad \text{线性}\;\Longrightarrow\; L_{c_1}+L_{c_2}=L_{c_1\cup c_2}
$$

```text
⇒ 在**相同 q_c** 下，把损伤集中在一条链与分散到多条链，token 总量完全相同。
⇒ token 口径**不能**为「集中更好」提供任何论据。
   唯一能区分集中与分散的是 q_c 的差异（期望权重），不是任何非线性。
```

这正是 §5.2 的实际情形：新规则 1.2B vs 旧 WRR 3.0B vs native 3.6B，
**全部**差异来自 $q_c$ 的排序，与 $C$ 的形状无关；§5.2 的数值不依赖本节。

#### 3.5.3 $C(r)$ 的定位：辅助观测，不参与排序

$C(r)$、TTFT、queue delay 只保留一个用途：解释 **token 收益为何不按比例传导到延迟**。

```text
Spearman(重算 token, TTFT) = 0.4327      ← 已实测，非估算
⇒ token 减少 14% 不意味着 TTFT 减少 14%。
⇒ 报告时两个口径并列，但**排序与取舍依据只取 token 口径**（§1.2）。
```

**A2 的待检验命题不变**：仍是「$q$ 序与 `lru_rank` 序的背离率」——
它才是 token 口径下唯一有效的区分信号。§6.4 记录：

```text
背离率统计   sign(q_c 排序) ≠ sign(lru_rank 排序) 的链对占比
条件收益     仅在该子集上比较 A2 与 A0/A1 的期望 token 损失
上界检查     A2 的全体平均收益 ≤ 背离率 × 单决策最大可能收益差
```

---

## 4. 输入信息来自哪里（M1 第 ① 项要求）

| # | 信号 | 来源（现有代码/产物） | 决策时可得性 | 备注 |
|---|---|---|---|---|
| 4.1 | 候选 Entry 集 $C$、每 Entry 的 Block | `DecisionSnapshot.candidate_keys` / `block_ids_by_key` | ✅ 决策时 | 已冻结 |
| 4.2 | 共属关系 $O(b)$ | `DecisionSnapshot.owners_by_block` | ✅ 决策时 | 无未来信息 |
| 4.3 | 复用可能性代理 | Continuum 已冻结的四类信号：Program Identity、Tool Gap History（`tool_gap_seconds` / `next_tool_type`）、动态 TTL（`retention_deadline_timestamp`）、Prefill Cost（`prefill_reload_seconds`） | ✅ 决策时 | **不新训练模型**；直接复用 Continuum 的既有估计 |
| 4.4 | Block token 数 $B$ | $B=\texttt{block\_size}$，引擎配置，**常数**。`block_hash_num_tokens` 是**累计前缀边界**，不是单块大小 | ✅ 决策时 | 见下方勘误 |
| 4.5 | 物理淘汰集合 $S$、$j_S(r)$ | 由本设计产出；评测时用 `observed_recomputed_tokens` / `observed_physical_eviction_blocks` | 仅评测期 | 属 `FORBIDDEN_FEATURES`，**不得**作为决策输入 |
| 4.6 | 容量需求 | `required_blocks`（**唯一判据**）。`free_blocks` / `total_blocks` 仅供参考，**不得**作为触发判据（§1.3 的 C4 修正） | ✅ 决策时 | 冻结 |
| 4.7 | Native 顺序 | `DecisionCandidateRow.decision_native_lru_position` | ✅ 决策时 | 仅作 warm-start / tie-break |
| 4.8 | 新增暴露 $N_i(R)$ | 由 4.1 + 4.2 直接计算（$|E(R\cup\{i\})|-|E(R)|$） | ✅ 决策时 | 无需额外输入 |
| 4.9 | 后续压力概率 $\lambda$ | 历史决策中发生强制淘汰的占比（Continuum pressure 统计 / replay 序列） | ✅ 决策时 | 全局统计量，非未来信息 |

**RC4 勘误 —— `block_hash_num_tokens` 不是 block_size**：

```text
它是「截至该 Block（含）的累计前缀 token 数」，即 hash 覆盖的 token 边界。
因此相邻两个边界的**差**才是一个 Block 的 token 数，对满块恒等于 block_size。
旧版把它读成「单 Block 的 token 大小、可不为常数」是错的，已撤回。

旁证：H1 快照中该字段的 10 个不同值为 min 16 / median 112 / max 512，
全部是 16 的整数倍（16=1×16, 112=7×16, 512=32×16），与 block_size=16 下的
累计边界一致；若它是单块大小，在固定 block_size 下不可能跨越 32 倍。
```

⇒ 因此本设计取 $B=\texttt{block\_size}$ 为**常数**。唯一例外是每条链的**末块**
可能是部分块（token 数 = 末个边界 − 前一边界 $\le B$）。末块只影响该链最后一个
Block 的单价，不改变 §3.4.3 的排序结构；第一版按常数 $B$ 处理，
并在 §6.4 把末块实际 token 数列为核对项。

**合规红线**：`src/kvopt/costaware/rules.py::FORBIDDEN_FEATURES`
（`returned_after_decision`、`observed_recomputed_tokens`、`physical_eviction_count` 等）
在本设计中**一律不作为决策输入**，只出现在评测侧。
这与 PR #50 §5.6 的 `OursEvictAdapter` 规范保持一致。

---

## 5. 两个具体例子（M1 第 ③ 项要求）

### 5.1 例一（Entry 层）：共享根 + 不对称尾巴

> **RC2 勘误**：本节的旧版声称「本设计选 $B$」，但当时给出的排序键按
> `share` 升序会选 $A$ —— 与文中结论相反。M1 的指正成立。
> 核算：$A$ 的 Block 共 16 个，释放 $A$ 后仍被 $B$ 保护 8 个 ⇒ $\text{share}_A=0.5$；
> $B$ 的 Block 共 10 个，释放 $B$ 后仍被 $A$ 保护 8 个 ⇒ $\text{share}_B=0.8$。
> 升序 ⇒ 选 $A$。旧版例子与旧版规则不自洽，已用下方新公式重算。

```text
Block 布局（每 Block = B tokens）
  共享根 : p1..p8        O(pk) = {A, B}          ← 两份共享
  A 的尾 : p9..p16       O = {A}                 ← A 独有 8 blocks，m_A = 16
  B 的尾 : p17..p18      O = {B}                 ← B 独有 2 blocks，m_B = 10
required_blocks D = 2 ，初始 R = ∅ ⇒ |E(∅)| = 0（无 hashless Block）
```

**第一步：算 $N_i$**（由 $O(b)$ 决定，§2.1）

```text
N_A = |E({A})| − |E(∅)| = 8   (p9..p16)
N_B = |E({B})| − |E(∅)| = 2   (p17,p18)
两者均 >= D = 2 ⇒ 都属于单步足够集 F ⇒ 直接比成本
```

**第二步：代入 §3.3.2 的成本公式**

取 $q_A = 0.5$、$q_B = 0.9$（$A$ 的 deadline 更早 ⇒ $q_A<q_B$，与 Continuum 一致）、

> 合法性核对（M1 第 3 点）：$q_A = 0.5$ 对应 $\text{deadline}_A = t$，
> $q_B = 0.9$ 对应 $\text{deadline}_B = t + \tau\ln 9$，两者都是合法状态。
> §5.2 的 $q_\beta = 0.3$ 对应 $\text{deadline}_\beta = t - \tau\ln(7/3)$，
> 即**已过 TTL 但尚未被释放**的冷链 —— 这正是强制释放决策上常见的情形（见 §3.3.3）。
$\lambda = 0.5$：

$$
\widehat{R}_A = 0.5\,B\,[\,\min(2,8) + 0.5\,(8-2)\,] = 0.5B\,[2+3] = 2.5\,B
$$

$$
\widehat{R}_B = 0.9\,B\,[\,\min(2,2) + 0.5\,(2-2)\,] = 0.9B\,[2+0] = 1.8\,B
$$

$$
\widehat{R}_B = 1.8B \;<\; 2.5B = \widehat{R}_A \quad\Longrightarrow\quad \text{选 } B
$$

| | Continuum（`deadline` 主键） | 本设计（§3.3.2） |
|---|---|---|
| 释放 | $A$（deadline 更早） | $B$ |
| 可行池 | $E(\{A\})=\{p_9..p_{16}\}$，8 blocks | $E(\{B\})=\{p_{17},p_{18}\}$，2 blocks |
| 本次淘汰 | 2 个（从 8 个里选，深度优先） | 2 个（$B$ 的尾恰好全占） |
| 本次重算 | $2B$ | $2B$ |
| **残留暴露面** | **6 blocks**（长期可被后续压力取用） | **0 blocks** |
| 期望总代价（$\lambda=0.5$） | $2.5B$ | $1.8B$ |

**为什么这个选择有机会降低重计算（关键在最后两行）**：

```text
本次淘汰量相同（都是 2 个 Block ⇒ 都是 2B 重算），单次决策分不出高下。
差别在**残留暴露面**：释放 A 会留下 6 个长期可淘汰的 Block，
而释放 B 的暴露面被完全消耗掉（N_B 恰好 = D）。
在 λ > 0（后续还会发生强制淘汰）的系统里，残留暴露面就是持续的风险敞口：
A 虽然在本次只损失 2B，但它的 8 个 Block 后续会被逐个蚕食，
使 j(A) 反复下移；B 的 2 个 Block 一次性用完即止。
因为 q_A·N_A = 0.5×8 = 4 > q_B·N_B = 0.9×2 = 1.8，
即使 A 的复用概率只有 B 的一半，它的期望敞口仍然更大。
```

**阈值（可检验，不是事后拟合）**：令 $\widehat R_B<\widehat R_A$，得

$$
0.9\,(2) \;<\; 0.5\,(2+6\lambda) \;\Longleftrightarrow\; \lambda \;>\; 0.2\overline{6}
$$

```text
λ = 0    ⇒ 退化为「谁更可能回来就牺牲谁」⇒ 选 A（与 Continuum 一致）
λ > 0.27 ⇒ 暴露面开始主导          ⇒ 选 B（与 Continuum 分歧）
```

这个阈值是本设计的**可证伪预测**：若 §6.4 实测发现 $\lambda$ 很低而 A1 仍有收益，说明模型缺项；若 $\lambda$ 高但 A1 无收益，
说明「残留暴露面」这一项没有真实作用。两种情况都应照实记录。

⚠️ 本例两种策略都只释放 1 个 Entry，**不触及 (C3) 的主动释放边界**。
若把 $D$ 改为 10，则必须同时释放 $A$ 与 $B$ 才能解锁根，此时才用到 §2.3 的互补性。

### 5.2 例二（Block 层）：新规则与旧 WRR 在同一场景下的分歧

> **RC3 修订**：旧版本用的是可加（线性）代价，得出「集中与分散总量相同 = 4B」，
> 因此这个例子当时**无法**体现任何规则差异。现改为带 $q_c$ 的期望代价，
> 并把三条规则在同一场景下逐一算出。

```text
链 α : m_α = 12,  合法候选深度 9..12,  q_α = 0.9  (热链，更可能返回)
链 β : m_β = 6,   合法候选深度 1..6,   q_β = 0.3  (冷链；deadline 已过，见下方合法性核对)
D = 4 ，B 统一，初始两链均完好 (j_α = 13, j_β = 7)
```

**规则一：§3.4.3 最小边际损失（新）**

```text
步骤  候选最小 Δ                     选取      j_α   j_β
 1    β@6: 0.3·(7−6)=0.3             β@6       13     6
 2    β@5: 0.3·(6−5)=0.3             β@5       13     5
 3    β@4: 0.3·(5−4)=0.3             β@4       13     4
 4    β@3: 0.3·(4−3)=0.3             β@3       13     3
期望损失 = 0.9·0 + 0.3·(6−3+1)·B = 1.2B
```

**规则二：旧 WRR $\arg\max_c \alpha_c\rho_c$（已废弃，仅作对照）**

```text
步骤  α 侧: 0.9·ρ_α       β 侧: 0.3·ρ_β     选取
 1    0.9·4 = 3.6         0.3·6 = 1.8        α  (热链先被打)
 2    0.9·3 = 2.7         0.3·6 = 1.8        α
 3    0.9·2 = 1.8         0.3·6 = 1.8        β (并列，tie-break)
 4    0.9·2 = 1.8         0.3·5 = 1.5        α
j_α = 10, j_β = 6 ⇒ 期望损失 = 0.9·3B + 0.3·1B = 3.0B
```

**规则三：native LRU（结果取决于 lru 序与 $q$ 是否一致）**

这里必须分开说，否则会得出错误的对比。native LRU 按 `lru_rank` 升序淘汰，
而 $q_c$ 来自 TTL／历史。两者**可能一致也可能背离**，结论完全不同：

```text
情形 (a) lru 与 q 一致：冷链 β 的块最旧 ⇒ native 淘汰 β@6,5,4,3
         j_β = 3 ⇒ 期望损失 = 0.3·4B = 1.2B        ← 与 §3.4.3 完全相同
情形 (b) lru 与 q 背离：α 的块更旧（α 上次访问更早，但 TTL 显示它仍会回来）
         ⇒ native 淘汰 α@12,11,10,9
         j_α = 9 ⇒ 期望损失 = 0.9·4B = 3.6B        ← 明显更差
```

| 规则 | 情形 (a) lru 与 $q$ 一致 | 情形 (b) lru 与 $q$ 背离 |
|---|---|---|
| §3.4.3 最小边际（新） | **1.2B** | **1.2B** |
| 旧 WRR $\arg\max\alpha\rho$（废弃） | 3.0B | 3.0B |
| native LRU | 1.2B（与新版相同） | 3.6B |

**因此诚实的结论是**：

```text
① **在本例中**新规则不劣于 native LRU：它按 q 与深度排序，两者一致时重合，
   背离时新版更好（1.2B vs 3.6B）。但这只是该例的结论，**不是一般性定理** ——
   §3.4.3 是逐步贪心，存在贪心劣于 LRU 的对抗性构造，必须由 §6.4 实测判定。
② **在本例的结构下**，新规则相对 native 的收益全部来自「lru 序与 q 序背离」：
   若背离比例很低，A2 对 native LRU 的增益就接近 0 —— 这与本项目此前
   「native 已经做了不少工作」的经验一致，不得期待大幅提升。
③ 旧 WRR 在情形 (a) 下**反而差于** native（3.0B vs 1.2B），
   在情形 (b) 下好于 native（3.0B vs 3.6B）。它的两个缺陷因此不是总能显现，
   这正是当初被漏掉的原因。
```

**可证伪的预测**：A2 的收益应与「$q$ 序与 `lru_rank` 序的背离率」正相关。
§6.4 因此把背离率列为必测的中间量：若背离率低而 A2 仍有收益，说明 §3.4.3
捕捉到了 $q$ 与 lru 之外的第三个信号；若背离率高而 A2 无收益，说明
$q$ 的估计本身不可靠。两种情况都必须照实记录。

**对称边界**：若 $q_\alpha = q_\beta$，两链对称，新规则与旧 WRR 的期望损失同为
$q\cdot 4B$（打穿任一链），此时**不得**宣称新规则更好。

---

## 6. 最小实验方案（M1 第 ④ 项要求）

### 6.1 两类前提：语料前提与工具前提（不要混为一谈）

> **RC5 修订**：旧版把「共享前缀 / 非线性成本 / 返回概率差异」当成**所有实验臂**
> 的共同前置条件，过强且不可执行；同时假定 replay 已经能做物理 Block 选择。
> 两个问题都已修正：前提按臂分别判定（§6.3），工具缺口如实列出（§6.4）。

```text
语料前提  取决于该臂需要用到的信号      → 按臂判定，见 §6.3
工具前提  取决于该臂需要记录的中间量    → 见 §6.4.2，A2/A3 当前不具备
```

语料方面仍有一条**全局**要求：必须在修复 F-PREFIX 之后的语料上跑。
修复点已定位在 `src/kvopt/workload/phase2e_materialize.py::_segments`
（当前 even draw = NO_SHARED 负对照，odd draw = SHARED_ROOT 处理组）。
但「修复后语料」不等于「每条臂都需要共享结构」—— 那是 §6.3 的事。

### 6.2 四臂递进（A0–A3 保持不变）

| 臂 | 定义 | 目的 |
|---|---|---|
| **A0** | 原始 Continuum（**冻结基线**） | 对照 |
| **A1** | Entry Cost-Aware 释放 + native LRU 淘汰（§3.3） | 最小增量；有稳定收益即先收敛到此 |
| **A2** | 原始 Continuum 释放 + Block Cost-Aware 淘汰（§3.4.3） | 检验「$q$ 序与 `lru_rank` 序背离率」命题 |
| **A3** | Entry + Block 联合（§1.3 的两变量） | 仅在 A2 有额外收益时再做 |

### 6.3 Step 0 —— 区分度门槛：按臂分别判定

每臂只要求**它自己用到的信号**具备区分度。任一臂的门槛不满足 ⇒ 该臂在本语料上
不可测，**只停该臂**，其余臂照常推进。

```text
A1 门槛（Entry 层）
  1a  存在 N_i 取值不同的决策占比             > 0     否则 argmin R̂ 恒等，退化为 deadline
  1b  q_i 在候选间有非零方差                   > 0     否则 R̂ ∝ N_i，只剩暴露面一项
  必备/不必需  不需要共享 Block；不需要 block 深度；不需要非线性成本

A2 门槛（Block 层）
  2a  合法候选链数 ≥ 2 的决策占比              > 0     单链时无链间比较
  2b  q_c 在链间有非零方差                     > 0     否则各链 Δ 同质
  2c  sign(q_c 序) ≠ sign(lru_rank 序) 的链对占比 > 0   §3.5 的操作条件
  2d  深度可重建率（§6.4.2 的工具前提）        = 100%  否则该决策不可用于 A2
  必备/不必需  不需要共享 Block（单 owner 链同样可分）

A3 门槛（联合）
  3a  A1 与 A2 门槛同时满足
  3b  E({A}) ∪ E({B}) ⊊ E({A,B}) 可发生的决策占比 > 0   互补性存在才可能有联合收益
  必备  共享结构是 A3 的**唯一**额外前提（这也是 A3 排在最后的原因）
```

**这一点很重要**：H1 的 0/81 共享只表示 A3 在 H1 上不可测，
**不**表示 A1/A2 不可测。旧版把它们绑在一起是错的。

### 6.4 Step 1 —— 离线阶段（A1 可跑；A2/A3 需先补工具）

#### 6.4.1 现状核实：replay 只支持 Entry 释放

已对源码逐项核对（`src/kvopt/costaware/replay.py`，并由 `scripts/probes/probe_replay_capability.py`
内省断言同一结论），A2/A3 需要的三样东西**当前都不具备**：

```text
① replay_decision 只产出 ReplayOutcome(released=Entry 键序列, ...,
   eligible_blocks_final=int)。**不记录被淘汰的 Block 集合 S**，
   因此 j_c 与 L(S) 都无法计算。
② DecisionSnapshot.QueueBlock 只有 block_id / has_block_hash / native_lru_rank。
   **没有深度、没有链归属**，Δ_c(b) = q_c·B·(j_c − d)^+ 无法求值。
③ DecisionSnapshot **丢弃了每 Entry 的 block_ids**（只保留 owners_by_block 与
   observed_initial_reclaimable），链归属无法从 replay 快照恢复，
   只能回到原始 payload 重建。
```

另有一项**未经验证**、不能当作已具备的前提：`DecisionCandidateRow.block_ids`
保留了元组顺序，但「该顺序即前缀深度序（深度 = 下标 + 1）」**尚未证实**。
它必须被验证，不能被假定。

#### 6.4.2 需要补的最小工具（设计，不实现）

```text
T1  深度重建       从原始 payload 的 per-entry block_ids 建 depth_by_block 与
                   chain_of_block；先用 §6.4.3 的次序检验通过后才可启用
T2  VictimStrategy  与 ReleaseStrategy 对称的新协议：
                   pick_next(legal: Sequence[int], state) -> int
                   合法集强制 ⊆ E(R)，违规即抛错（对齐 §1.3 的 (C1)）
T3  Outcome 扩字段  ReplayOutcome 增 evicted_blocks 与 per_chain_exposure，
                   纯增字段，不改变既有字段含义
T4  保真校验        若存在 observed_physical_eviction_blocks，则校验模拟的 S
                   与观测集合一致；**若不存在，本次只能称 simulation**
```

⚠️ **命名纪律**：T4 没有观测集合时，不得把 Step 1b 的结果称为 replay 或
「复现了 native 行为」。它是在给定释放顺序下对物理淘汰的**模拟**。

#### 6.4.3 必须先通过的次序检验（T1 的准入条件）

```text
检验 H1  对每个 Entry，block_ids 的下标序是否与其块在该链上的前缀序一致
         判据：同一 Entry 内 native_lru_rank 与 block_ids 下标是否同向
         （PR #50 已测得 hashless 在队列中恰为 {0..k−1}，方向一致但那是队列序，
           不是 Entry 内深度序，两者需分别验证）
检验 H2  跨 Entry 拼接时，共享根是否落在两条链的**相同**深度上
         若不一致 ⇒ 该语料的前缀结构不可用于深度计算，T1 停用
```

#### 6.4.4 Step 1a：Entry 阶段（A0 vs A1，当前即可执行）

用现有 `replay_decision`，在**同一批决策**上比较 A0 与 A1。记录：

```text
主指标   （**代理，不是 L(S)**）|E(R)| 与 N_i 的组合近似（A1 阶段尚无 S，
         故只能记期望量，不能记 j_S(r)）
释放侧   released 序列、迭代次数、satisfied / exhausted
合法性   released ⊆ C 且 R 满足 (C2)(C3)：违规次数必须为 0
臂门槛   1a / 1b 的实测值（§6.3）
```

⚠️ **A1 的这一行不是 L(S)**：由于 S 未产生，这里只有期望代理。
真实 L(S) 需要 T1–T3，见 §6.4.5。这也是 §6.5.3 强调离线不是收益的原因之一。

#### 6.4.5 Step 1b：Block 阶段（A2 vs A3，需 T1–T4 就绪后执行）

```text
主指标   L(S) = Σ_r (m_r − j_S(r) + 1)·B          ← §1.2，唯一记录量
分解     每链 j_c、每链被淘汰 Block 数、S 的深度分布
规则审计 每决策触及链数（检验 §3.4.4 的「集中而非分散」）、
         Δ(b) 与事后实测重算量的秩相关
背离率   sign(q_c 序) ≠ sign(lru_rank 序) 的链对占比（§3.5 操作条件）
末块核对 每链末块的实际 token 数（检验 §4.4 常数 B 的误差）
合法性   S ⊆ E(R) 违规次数 = 0；(C2) 违规 = 0；(C3) 违规 = 0
模拟标记 若 T4 无观测集合可比，本行结果标注为 simulation
```

### 6.5 Step 2 —— 最小配对 native 验证（离线之后，非可选）

#### 6.5.1 触发条件

```text
Step 1 出现 ≥1 个方向稳定、且通过该臂全部门槛的候选，才进入 Step 2。
Step 1 未出现稳定方向 ⇒ 结束，不得用离线数字充当结论。
```

#### 6.5.2 指标口径

```text
主指标    aggregate recomputed tokens（observed_recomputed_tokens，仅评测期可得）
辅助指标  TTFT（native_queued_timestamp → native_scheduler_admission_timestamp
          → native_first_token_timestamp，H1 已确认 100% 填充）
辅助指标  queue delay、prefill 时间
判定      **只按 token 口径判定优劣**；辅助指标用于解释传导损耗
报告      两个口径必须并列，不得只报一个
```

方法沿用 Phase 2E 的配对协议（同 seed、同 workload、同 backend，仅策略不同），
样本量取最小可判读规模。

#### 6.5.3 离线估计不是收益（RC5 明确要求）

```text
离线 L(S) 只是**在给定模型下的估计**，受三层误差影响：
  ① q_c 来自 TTL 的单调变换，是启发式，不是实测返回概率
  ② 深度与链归属来自 T1 重建，依赖 §6.4.3 的次序假设
  ③ S 是模拟集合，可能与 native 实际淘汰不同（T4 无观测时无法校验）

⇒ 因此必须同时报告：离线估计值、native 实测值、以及二者的差；
   差值本身就是发现（模型缺项 / 次序假设不成立 / 信号不可靠）。
⇒ 不得把离线估计写成「预计可降低 X%」这样的收益陈述。
```

### 6.6 明确不做的部分

```text
❌ 不修改 native BlockPool / ref_cnt / hash 清理 / LRU
❌ 不修改冻结的 Continuum baseline 与 TTL 估计器
❌ 不做正式 runtime 策略实现（M1 未授权）
❌ 不做大规模实验（M1 未授权）
❌ 不新增离线训练模型（§4.3 复用 Continuum 既有信号）
❌ 不在压力满足后主动多释放 Entry（RC1，本轮不授权）
❌ 不在 T1–T4 就绪前声称 A2/A3 的离线结果（§6.4.2）
```

## 7. 为什么 H1 无法支撑本设计（以及不重复审计）

```text
0/81     决策中存在 ≥2 个 Entry 共享 Block        ⇒ §2.3 的互补性恒不存在
0/81     Entry band 非连续或相交                  ⇒ Entry 层无拓扑可优化
471/471  relief ≡ block_count                     ⇒ relief 退化为单一整数，无信息量
294/294  native_lru_rank 与 index 单调一致(仅在 H1) ⇒ Block 层只剩名次取前 k
```

**rev.7 修正（M1 第 4 点）**：旧版此处断言「H1 上 A1 精确退化为 A0」——**该断言已删除**，
它不成立。新的 Entry 评分同时依赖 $q_i$、$N_i$ 与 $\lambda$；
无共享结构只保证 $N_i$ 等于该 Entry 的私有块数，**不保证各候选 $N_i$ 相同**。

```text
H1 实测（`scripts/probes/h1_entry_block_overlap.py` 的 F4，`--strict` 会断言下列数字）：
  多候选决策                    81
  存在 >1 个不同 N_i 的决策      72  = 88.9%
  平均每决策不同 N_i 取值数       3.04
  全部候选 N_i = 0 的决策         0  = 0.0%
⇒ 因此 A1 在 H1 上**一般不等于 A0**，是**可测的**，不是恒等。
```

同理，A2 也**不能**直接断言退化为 `NativeLRUAdapter`：294/294 只说明
链内 `native_lru_rank` 与深度单调一致，而 §3.4.3 的 $\Delta(b)$ 还含 $q_c$，
两者一般不同。A2 与 native 的差异是否出现、出现在多少决策上，
由 §6.4.5 的「背离率」实测决定。

上述四点仍然说明：**H1 无法体现共享结构带来的效应**，
因此 A3 在 H1 上不可测（§6.3 的 3b 门槛）。但 A1 与 A2 不受此限制。

本文**不再**对这四点做新一轮审计（M1：重点放在算法设计）。

---

## 8. 边界与待裁定事项

1. **B1 / 主动释放**：M1 已裁定「`required_blocks` 满足后仍主动多释放」**不授权**；
   §3.3 已按 (C3) 改为释放到够即止。该方向保持关闭，待单独论证后再议。
2. **部分前缀保护**：本设计只处理**整 Entry 释放**；若未来需要按 Block 粒度解除保护
   （即 PR #50 的四字段接口不足以表达 $O(b)$ 的按 Block 语义），需先扩展接口并另行评审。
3. **A2 的取舍**：若 §6.4.5 显示 A2 在 aggregate token 上为负而仅在尾部风险上为正，
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

### 9.1 复用与最小改动（对应 M1 第 4 项要求）

| 类别 | 内容 |
|---|---|
| **直接复用** | `costaware/replay.py` 的 `DecisionSnapshot` / `ReplayState` / `eligible_block_ids` / `replay_decision` / `validate_replay_fidelity`；`costaware/rules.py` 的 `CandidateRule` 与 `FORBIDDEN_FEATURES`；`eviction_decision` 的决策事件载荷（`candidates[].block_ids` 与 `original_free_queue`） |
| **最小改动** | 仅 §6.4.2 的 T1–T4：深度重建、`VictimStrategy` 协议、`ReplayOutcome` 两个纯增字段、保真校验。**不改**既有字段含义，不改 `replay_decision` 的循环语义 |
| **不改动** | native BlockPool / `ref_cnt` / hash 清理 / native LRU；冻结的 Continuum baseline（`continuum/pressure.py`）与 TTL 估计器；Phase 2E 的指标口径 |

**A0–A3 的比较方式**（同一批决策、同一语料、同一指标）：

```text
A0  →  ExecutedP1BStrategy（已存在，可先跑保真校验）
A1  →  §3.3 的 Entry 排序 + native LRU 淘汰（复用 replay_decision，今天可跑）
A2  →  ExecutedP1BStrategy + §3.4.3 的 VictimStrategy（需 T1–T3）
A3  →  §3.3 + §3.4.3 同时启用（需 T1–T3，且需 A3 门槛通过）
```

四臂共用同一个 `DecisionSnapshot` 序列，因此差异只来自策略本身，
不需要为每臂单独准备语料。

---

## 10. 可追溯性

本表引用的探针脚本全部位于 `scripts/probes/`，可独立运行并自断言；
自足探针已纳入 `tests/test_joint_design_probes.py`，会随测试套件执行。
H1 探针需要运行产物目录（不提交数据），用法见 `scripts/probes/README.md`。

| 本文结论 | 依据 |
|---|---|
| $E(R) = \{b : O(b) \subseteq R\} \cup \{$hashless$\}$ | `costaware/replay.py::eligible_block_ids` 逐行核对 |
| $E(\{A\}) \cup E(\{B\}) \subsetneq E(\{A,B\})$ | 由上式直接推出（$O(b)=\{A,B\}$） |
| Continuum 释放主键为 `deadline` 优先 | `continuum/pressure.py:324` |
| 线性代价下集中/分散总量相同 | §5.2 算例；与 PR #50 §4 的线性不变性一致；RC4 后统一按 token 口径表述 |
| (C2)(C3) 释放/淘汰量的口径 | `costaware/replay.py` 的 `target = min(required_blocks, len(queue))`；`continuum/pressure.py` 的按需释放循环 |
| $R = C$ 是未加 (C3) 时的退化最优解 | 由 $L$ 对释放量不计费、且 $E(R)$ 对 $R$ 单调不减直接推出（RC1） |
| $\widehat{R}_i$ 在 $N_i$ 相同且 $\lambda=0$ 时退化为 `deadline` 序 | §3.3.3 的 $q$ 是 `deadline` 的单调变换 |
| §5.1 的阈值 $\lambda>0.2\overline{6}$ | 代入 $q_A=0.5,q_B=0.9,N_A=8,N_B=2,D=2$ 解不等式 |
| 旧键按 `share` 升序会选 $A$ | $\text{share}_A=8/16=0.5<\text{share}_B=8/10=0.8$（RC2 勘误） |
| $R_c$ 只依赖最浅缺口 $j_c$ | APC 前缀语义；与 §3.4.1 的定义一致 |
| $\Delta_c(b)=q_c B_b (j_c-d)^{+}$ | 对 $R_c$ 逐项求差，三种情形穷举 |
| 旧 WRR 3.0B；native 在 lru 与 q 一致时 1.2B、背离时 3.6B | `scripts/probes/probe_example_block_eviction.py` 逐步复算并断言三种情形 |
| $C(r)/r$ 单调不增 ⇒ **次可加**（不是凹） | §3.5.1 的推导；`scripts/probes/probe_metric_semantics.py` 给出非凹反例并逐一检验不等式 |
| token 口径下集中与分散在 $q$ 相同时等值 | $L$ 对每条链严格线性（§3.5.2）；`scripts/probes/probe_metric_semantics.py` 数值确认 2.000B = 2.000B |
| $B=\texttt{block\_size}$ 为常数；`block_hash_num_tokens` 是累计前缀边界 | §4.4 勘误；H1 该字段 10 个值均为 16 的整数倍，与 block_size=16 的累计边界一致 |
| H1 上 A1 一般不等于 A0（72/81 决策存在 >1 个不同 $N_i$） | `scripts/probes/h1_entry_block_overlap.py` 的 F4；$N_i$ 取 `initially_reclaimable_block_ids` 长度，与 `replay.py` 的 `initial_reclaimable_match_rate` 同源 |
| (C4) 触发量是 $\lvert E(R)\rvert$ 而非 `free_blocks` | `continuum/pressure.py:107` 的 `while len(tier_1_ids \| tier_2_ids) < target` |
| H1 无共享：0/81、0/471、294/294 |
| replay 不产出淘汰 Block 集合 S | `costaware/replay.py::replay_decision` 与 `ReplayOutcome` 字段核对 |
| `QueueBlock` 无深度、无链归属 | `costaware/replay.py::QueueBlock` 三字段 |
| `DecisionSnapshot` 丢弃 per-entry `block_ids` | `_snapshot_from_event` 只保留 owners 与 observed_initial_reclaimable；`scripts/probes/probe_replay_capability.py` 内省断言 |
| `FORBIDDEN_FEATURES` | `costaware/rules.py` |
| TTFT 可直接测量 | `VLLM_NATIVE_REQUEST_OBSERVATION` 三时间戳，100% 填充 |
| 重算 token 不按比例传导到 TTFT | Spearman = 0.4327 |
