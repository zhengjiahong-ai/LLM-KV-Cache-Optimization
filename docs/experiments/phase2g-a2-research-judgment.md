# Phase 2G A2 —— 算法价值判断（Bounded Native Value Evaluation 之后）

范围：仅算法层面的理论与冻结证据解释。对应 PR #68（`2095fa2`）之后 M1 提出的四个问题。

授权边界：A2 Mathematical Model Analysis / Frozen Native Evidence Interpretation —— 已授权；
A2 Algorithm Modification / New Native Campaign / Workload Redesign —— **未授权**；A3 DEFERRED、B1 LOCKED。
本文不含任何算法改动；文末的改法只是**待裁定的提案**，不是实现。

---

## 0. 一句话结论

**A2 的可利用空间由一个可测的结构条件决定：它只能在
（深度反转 ∨ 共享块被 native 错排 ∨ 链间 q 重排）成立时才优于 LRU，而在这些条件都不成立时，
成本模型对可行集的取值是恒等平坦的 —— 收益精确为 0，不是"近似为 0"。**

PR #68 与 PR #56 的证据显示这三个条件在可测语料中同时缺席
（反转 0/183 窗口、q 重排 0/39、受害集分歧 0/87）。因此：

> **不建议继续把 A2 作为主要算法方向优化。**
> 它的结构性内容（"先淘汰最深的块"）与 native 已做的事重复；
> 它的预测性内容（$q$）已被实测为与真实重算几乎无关，且在机制上与 recency 共线。
> 建议降级为**条件门控的可选安全层**，主线回到 Entry 层（A1/A3）——
> 那里已观测到 13 个选择分歧场景，而 A2 在 87 个已验证决策中是 0。

---

## 1. 目标函数只依赖一个向量

冻结目标（`a2_selector.py`）：

$$L(S)=\sum_{c:\,S\cap c\neq\varnothing} q_c\bigl(m_c-j_c(S)+1\bigr),
\qquad j_c(S)=\min\{d_c(b):b\in S,\ b\in c\}$$

它只依赖**开启剖面** $\mathbf{j}=(j_c)$，不依赖具体选了哪些块。由此立刻得到两条结构事实。

### 1.1 引理 A（链内单调）：最优集在每条链上必是最深的若干个

固定链 $c$ 与占用名额 $k_c$，把 $S\cap c$ 中任一深度换成同链更深的块，$j_c$ 单调不减，
$(m_c-j_c+1)$ 单调不增。故链内最优恒为"最深 $k_c$ 个"。

> **推论 A1**：链内排序**不携带任何决策信息**，它是一条不需要 $q$、不需要几何、
> 不需要任何预测的确定规则。$m_c$、$d_c(b)$、APC 前缀语义全部被这条规则吸收了。
>
> **推论 A2**：$C(n,k)$ 个受害集中有大量**等价类**（同一 $\mathbf{j}$ 剖面）。
> 决策空间不是 $\binom{n}{k}$，而是"把 $k$ 个名额分配到各链"的组合数与可达剖面数中的较小者。

### 1.2 引理 B（均匀 $q$ 下平坦）：$\Delta q = 0$ 时选择完全无差别

若各链 $q_c\equiv \bar q$ 且各链取最深若干个（引理 A），则每条链贡献 $\bar q\,k_c$，
总损失 $\bar q\sum_c k_c=\bar q k$ —— **与分配方式无关**。

> 这与联合设计 §3.5.2 已记录的结论一致（"相同 $q_c$ 下集中与分散的 token 总量完全相同"），
> 但这里是**逐个决策**成立的：均匀权重下，任何满足引理 A 的受害集损失相同。

**数值验证**（`scripts/probes/a2_decision_space.py`，3000 个随机几何，全部 deepest-first、
无共享块、$q\equiv 0.5$）：

```text
cost-aware strictly better: 0 / 3000    worst gain: 0.000000
```

---

## 2. 问题 1：成本函数提供了什么 LRU 不具备的信息？

把四项输入按"是否提供独立的、可用的排序信息"分开看：

| 输入 | 在目标里的作用 | 是否提供 LRU 之外的信息 | 判断 |
|---|---|---|---|
| `prefix_depth` + `chain_length` | 后缀长度 $m_c-j_c+1$ | **否**。它只导出引理 A（先淘汰最深的），而这条规则不需要任何外部信号 | 与 native **重复** |
| `reuse_weight` $q_c$ | 链间交换率 | **仅在链间竞争时**。链内所有块共享同一个 $q_c$，故 $q$ 对链内排序贡献恒为 0 | 唯一候选的独立信号 |
| shared membership | 同一次淘汰在多链各计一次 | **是**，但方向是"让 A2 更贵"，只在 native 把浅共享块错排为最冷时才转化为收益 | 真实但狭窄 |
| 决策时间戳 | 只用于算 $q$ | 否 | — |

### 2.1 $q$ 的机制形式：$q$ 其实是"剩余保留时间"，且与 recency 共线

仓库里 `retention_deadline_timestamp = ttl_decision_timestamp + ttl_seconds`
（`preregistrations.py` / `h1-r1-preregistration`），且
`ttl_seconds = max(0, ln(profile_seconds))` 或冻结 CDF 分位数（`continuum/ttl.py`，
按 tool 特定 / global / cold-start 三档选择）。代入 $q$：

$$q_c=\sigma\!\left(\frac{\text{deadline}_c-t}{\tau}\right)
=\sigma\!\left(\frac{\texttt{ttl}_c-\underbrace{(t-t_{\text{ttl},c})}_{\text{elapsed}}}{\tau}\right)$$

所以 **$q_c$ 排序 = 按（ttl − 已流逝时间）排序**。已流逝时间就是 recency。
于是：

- **ttl 跨链接近时，$q$ 序 ≈ recency 序 ≈ `native_lru_rank` 序** —— 这是常态；
- **q 重排只有在跨链 ttl 差异压过年龄差时才发生**，而 ttl 差异要求同一压力决策内
  **tool 类型异质**（不同 tool 的 CDF 分位数不同）。

这不是推测，有一个强证据：H1 derived bundle 的 `signal_support.jsonl` 里

| 特征 | ρ | 族一致 | 判定 |
|---|---:|---:|---|
| `retention_deadline_timestamp` | **+0.0585** | 0.667 | NOT_SUPPORTED |
| `elapsed_since_ttl_decision_seconds` | **−0.0585** | 0.667 | NOT_SUPPORTED |
| `decision_native_lru_position` | **+0.0585** | 0.667 | NOT_SUPPORTED |
| `block_count`（结构项） | **0.5999** | 1.000 | PROXY_SUPPORTED |

三者的 |ρ| 与族一致度**完全相同**，只有符号随单调方向翻转。
决策内秩相关对**单调变换不变** —— 这正是"$q$ 没有带来 recency 之外排序信息"的定量体现。
而具有判别力的是 `block_count`，即**结构项**，恰恰是引理 A 已经免费给出的那部分。

### 2.2 于是：A2 的独立信息只有 $\Delta q$，而 $\Delta q$ 只在多链窗口有意义

收益在"非反转 + 无共享 + 均匀 $q$"下恒为 0；一旦允许 $\Delta q\neq 0$，收益可精确算出。
非反转几何、$need=k=2$、链 a 便宜（$q_a$）、链 b 贵（$q_b$）：

| $q_a$ | $q_b$ | native | cost-aware | $L$(native) | $L$(aware) | 收益 | $k\,(q_b-q_a)$ |
|---:|---:|---|---|---:|---:|---:|---:|
| 0.50 | 0.50 | (107,106) | (107,106) | 1.0000 | 1.0000 | **0.0000** | 0.0000 |
| 0.48 | 0.52 | (107,106) | (103,102) | 1.0400 | 0.9600 | 0.0800 | 0.0800 |
| 0.40 | 0.60 | (107,106) | (103,102) | 1.2000 | 0.8000 | 0.4000 | 0.4000 |
| 0.20 | 0.80 | (107,106) | (103,102) | 1.6000 | 0.4000 | 1.2000 | 1.2000 |
| 0.01 | 0.99 | (107,106) | (103,102) | 1.9800 | 0.0200 | 1.9600 | 1.9600 |

> **收益 = $k\cdot(q_{\text{hot}}-q_{\text{cold}})$，逐位吻合。**
> 换成 token 需乘块大小 $B=16$：$k=4$、$\Delta q=0.1$ 时，单决策上限约 **6–7 tokens**。

这个量级本身就是结论：**A2 能移动的量是"几个 token / 决策"级别的**，
除非 $\Delta q$ 接近 1（即两条链的保留预期近乎相反）或出现深度反转/共享错排。

---

## 3. 问题 2：是否存在结构性的决策空间不足？

### 3.1 三个必要条件（完备）

| 来源 | 触发条件 | 均匀 $q$ 下的收益 | 实测（PR #56 语料） |
|---|---|---:|---|
| (D) 深度反转 | 同链内更浅的块反而更冷 → native 先打浅块 | 有（本探针 survey：**258 个无反转样本中分歧 0**） | `183/183` 窗口已是 deepest-first，**反转 0** |
| (S) 共享错排 | 浅共享块被 native 判为最冷；淘汰它一次抬高两条链的缺口 | 有（3000 例中 308 例，最大 3.5 块） | 有共享块，但受害集分歧 **0/87** |
| (Q) q 重排 | 多链窗口 + $\Delta q$ 足够大（机制上=跨链 ttl 异质） | 有，$=k\Delta q$ | `q vs rank` 可比 39，**一致 39，分歧 0** |

### 3.2 什么条件下 Cost-Aware **必然**退化为 LRU

1. **单链窗口 + native deepest-first** → 两者取同一个集（引理 A）。
   这是最常见形态：`multi_chain` 只占探针样本的 49.7%（1987/4000），
   在真实语料中多数压力窗口只涉及已释放 Entry 的少数链。
2. **多链窗口 + $\Delta q=0$ + native deepest-first + 无共享** → 引理 B，收益恒 0。
3. **`need = ` 合法块总数** → 任何规则都必须淘汰整个合法集，**在构造上不可能分歧**
   （机制报告 §5 的"陷阱"一行）。这类窗口计入"无分歧"是**无意义的**。

### 3.3 存在多个合法集但实际损失不同 —— 什么时候真有区别

只有当引理 A 的"最深优先"与 **跨链交换率**（$q$）或 **共享归属** 冲突时才成立。
三者的相对量级（探针，均匀 $q$）：

```text
(D) 反转        分歧只在反转窗口出现；无反转时 0/4000
(S) 共享错排    3000 例中 308 例获益，最大 3.5 块（≈56 tokens）
(Q) q 重排      收益 = k·Δq，线性，Δq 通常很小
```

### 3.4 当前 Greedy 能否利用这些差异？

**能，且这不是瓶颈。** 贪婪在单链上精确（引理 A），在 $q$ 重排下也精确
（按边际成本比较，单调）；它只在**共享块耦合**时次优，实测缺口
0.68%（25/3684，最大 0.70 块），且穷举搜索已覆盖。
**所以"算法选得不够好"不是本轮失败的原因** —— 反复确认的是"没有可选的差异"。

### 3.5 当 depth、共享、rank 高度相关时，还剩多少空间？

这正是实测语料的状态：rank 与 depth 单调（183/183）、$q$ 与 rank 一致（39/39）。
在这种共线下，**空间不是"小"，而是"被引理 B 精确归零"**。
所以"未观测窗口 = 有空间"这个提醒在本例里被反驳：
**空间可以由 $(\Delta q, \text{反转}, \text{共享错排})$ 三个可观测量直接判定，而不必观测到。**

---

## 4. 问题 3：Reuse Proxy 是否具备预测能力？

### 4.1 实测：接近零

| 关系 | ρ | n | 口径 |
|---|---:|---:|---|
| `retention_deadline_timestamp` ↔ proxy loss | +0.1376 | 471 | M4 独立复算 |
| `retention_deadline_timestamp` ↔ **runtime loss** | **−0.0178** | 207 | M4 独立复算 |
| `block_count` ↔ runtime loss | +0.5794 | 207 | 同上 |
| deadline 分离"返回/不返回" | 37 vs 38（方向性无） | 75 决策 | 直接计数，无统计假设 |

$q$ 是 deadline 的单调函数，因此上表直接约束 $q$ 的预测力：
**$q$ 与真实重算的相关性约为 0（−0.0178）**，而结构量 `block_count` 有 0.58。

### 4.2 五个具体缺陷

1. **链内零信息**：$q_c$ 是链级标量，链内所有块共享 → 对链内排序贡献恒 0（§1.1）。
2. **与 recency 共线**：$q_c=\sigma((\texttt{ttl}_c-\text{elapsed}_c)/\tau)$，
   常态下 ttl 跨链接近 ⇒ $q$ 序 ≈ 年龄序（§2.1，|ρ| 相同的三方证据）。
3. **Cold-start 无区分度**：`ttl.py` 在全局样本不足时返回 `COLD_START`，
   退化到同一常数 ttl ⇒ 同一次决策内 $q$ 全部相同 ⇒ 引理 B ⇒ 决策完全平坦。
   本轮 F1–F3、F5–F6 全 TIED 与该机制一致。
4. **错误时主动保护错链**：$q$ 高 ⇒ 模型认为该链该保护 ⇒ A2 改打别处。
   若 $q$ 判错，这是**单向的、有代价的错误**：不是"没帮上"，而是"帮了倒忙"。
   观测到的 0 BETTER / 3 WORSE 与该不对称性吻合。
5. **proxy loss 与真实 token 的三处漂移**：
   - 模型假设"链一旦返回，缺口以下全部重算"；实测 `loss == 16×block_count` 只成立
     **76.8%（159/207）**，存在**部分命中**，且每个可回收块的实际重算量跨度 **24×**；
   - 模型按 $B$ 常数计，末块可能是部分块；
   - 模型忽略"该链的 Entry 可能本来就会被 Continuum 释放"，
     为一个即将被释放的链付出当前代价。

---

## 5. 问题 4：Block-level 相对 A1 是否有独立贡献？

### 5.1 决策变量的层级：A1 是一阶，A2 是残差

- **A1 决定 $E(R)$**：哪些 Entry 被释放 ⇒ 哪些链**可以**被碰。
  这是"是否触碰某链"的 0/1 决策，直接决定 $j_c$ 是否变化。
- **A2 只在 $E(R)$ 内分配**：已确定要碰这些链，只决定碰多深、碰多少块。
  由引理 A，这是"取最深的那几个"，自由度只剩**分配向量** $(k_c)$。

$$L \;\approx\; \underbrace{\sum_{c\in E(R)} q_c\,(\text{链 }c\text{ 暴露的后缀})}_{\text{A1 决定哪些链进入求和}}
\;+\;\underbrace{\sum_c q_c\,k_c}_{\text{A2 只在均匀 }q\text{ 下平坦的部分}}$$

### 5.2 A2 的收益被 A1 自身的有效性压缩

A1 的评分 $\widehat R_i=q_i[\min(need,N_i)+\lambda(N_i-\min(need,N_i))^{+}]$
**用的就是同一个 $q$ 与同一个后缀逻辑**。A1 会把最便宜的 Entry 先放进来，
于是 $E(R)$ 内的 $q$ 是**已被筛过的低值且彼此接近**的一组。
由 §2.2，A2 的收益 $=k\,\Delta q$ —— **A1 越有效，$\Delta q$ 越小，A2 的收益上限越低**。

> 这是一个方向性结论：**A2 是一个残差优化器，其残差随 A1 改进而收缩；反向不成立**
> （A1 的收益不依赖 A2 存在）。

### 5.3 定量对照

| 证据 | A1（Entry 层） | A2（Block 层） |
|---|---|---|
| 选择分歧 | Gate 2 语料 **13 个场景** | 本语料 **0/87**；native 战役 **2 个窗口**（同一 draw 的两次 repeat） |
| 有真实重算收益 | 是（已有 paired 证据） | 未观测到（0 BETTER / 3 WORSE / 33 TIED） |
| 可移动量级 | Entry 是否释放 ⇒ 整链后缀 | $k\Delta q\cdot B$ ≈ 几个 token/决策（除反转/共享错排） |

### 5.4 但必须保留的边界

- 离线语料 **27.5%（33/120）不可证明**，native 战役 **402/778（51.7%）决策
  以 `content_unverified` 回退** ⇒ 该语料**未真正检验算法**，只是未能检验。
- 因此不能写"A2 被证明无效"。能写的是：**在三个结构条件都缺席的可测部分，
  收益可被引理 B 精确归零；在有空间的部分，我们没有可用的度量。**

---

## 6. 问题 5 的答案：建议（含可检验条件）

### 6.1 不建议继续把冻结 A2 作为主要算法方向

理由按强度排序：

1. **结构性重复**：链内部分（depth/chain length/APC 后缀）只导出"先淘汰最深的"，
   而 native 在 183/183 窗口已如此 ⇒ 这部分贡献恒 0（与实现质量无关）。
2. **预测性缺失**：唯一独立的信号 $q$ 与真实重算 ρ = −0.0178，且与 recency 共线
   （三方 |ρ| 相同的证据）⇒ 它无法提供 LRU 之外的**正确**信息。
3. **非对称风险**：$q$ 判错时是主动保护错链，因此期望值偏向负而非零。
4. **残差定位**：A2 与 A1 用同一目标函数，A1 先筛 ⇒ A2 的 $\Delta q$ 被系统性压缩。

### 6.2 如果继续，必须满足的可检验条件（不是"扩大数据集"）

把 A2 从"总是执行"改为**条件门控**，并且每个条件都可离线判定、可用现有字段计算：

| 条件 | 可检验表述 | 判据（建议阈值，待裁定） |
|---|---|---|
| C-D 深度反转 | 存在同链 $d_1<d_2$ 且 $\text{rank}(d_1)<\text{rank}(d_2)$ | 触发率 > 0 且反转窗口上的收益 > 0 |
| C-S 共享错排 | 存在共享块且其深度 $<$ 两链中最深可用深度 | 该窗口上 $L$(native) > $L$(aware) |
| C-Q q 重排 | 多链 且 $k\Delta q\cdot B >$ 观测噪声 | $\Delta q > 0.1$ 且多链窗口占比 > 20% |

**准入命题**（替代"平均收益>0"）：
> 在已验证（identity-proved、非回退）决策中，
> 三个条件的**联合触发率 $\times$ 单决策最大增益**必须能解释可观测的 token 量；
> 否则 A2 的期望收益上界低于测量噪声，不值得投入。

以本轮数字代入：单决策上限（除反转/共享）约 $k\Delta q B\approx 6$ tokens；
要达到 F4 中 +560 tokens 的**任一侧**变化，需 ~90 个决策同时最大偏离。这本身就是
"block-level 选择不可能是主因"的定量陈述。

### 6.3 建议的定位调整

1. **A2 降级为 opt-in 安全层**：默认返回 native；仅在 C-D/C-S/C-Q 为真时背离。
   在实测语料上该门控会 100% 走 native ⇒ 既不会退化，也不假装有收益。
2. **主线回到 Entry 层（A1 / A3）**：那是唯一观测到真实分歧与收益的层级。
3. **度量先行**：把"三条件的触发率与幅度"作为 A2 的**唯一**主指标，
   而不是 `aggregate_recomputed_tokens` 的均值 —— 后者在 33/36 TIED 下没有检出力，
   且回退率 51.7% 使其不可解释。

> 以上 1–3 均属 **Algorithm Modification / Workload Redesign 范围，本轮未获授权**，
> 此处只作为待裁定提案；未改动任何算法代码，未运行新的 Native campaign。

---

## 7. 复现

```bash
# 结构分析探针：引理 A/B、三个背离来源、收益对 Δq 的线性关系
python scripts/probes/a2_decision_space.py

# 贪心 vs 穷举的缺口（既有）
python scripts/probes/a2_greedy_gap.py --strict
```

探针输出（本机复现）：

```text
== structural survey: 4000 random decisions, uniform q ==
  inverted                                      3742
  multi_chain                                   1987
  diverges with no inverted chain at all           0
  diverges with neither inverted nor multi-chain    0

== uniform q, every chain deepest-first, no shared block ==
  3000 random decisions: cost-aware strictly better in 0, worst gain 0.000000

== uniform q, every chain deepest-first, one shared block above the deepest ==
  3000 random decisions: cost-aware strictly better in 308, worst gain 3.500000

== gain vs q spread on a non-inverted geometry (need = 2) ==
  收益与 k*(q_hot - q_cold) 逐位吻合
```

## 8. 引用口径声明

- PR #68 数字取自 `docs/experiments/phase2g-a2-bounded-value-evaluation.md`（144/144 run、36 场景、
  0/3/33、mean +26.2222、median 0、CI[0, 65.3333]、A0 24,832 / A2 26,720、new-suffix 6,440 两侧相同、
  778 决策 / 402 回退 / 122 完整证据 / 2 分歧 / 40 可比较）。
- 离线语料数字取自 `docs/experiments/phase2g-a2-mechanism/README.md`（120 决策、87 verified、
  183 窗口全 deepest-first、39/39 q 与 rank 一致、0/87 受害集分歧）。
- 相关性数字取自 `docs/phase2a-m4-method-opportunity-audit.md` §2.5 / §2.8，
  并区分"M4 独立复算"与 M6 `signal_support.jsonl` 两套口径（§2.5 已声明不逐位一致）。
- 本文不重新解释任何既有 verdict；PR #68 的结论仍为
  `INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN`。
