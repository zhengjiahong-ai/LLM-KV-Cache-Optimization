# Phase 2E — M4 审查：METRIC / MECHANISM / RESEARCH_INTERPRETATION

**提交人**：M4　**送审**：M1　**对象**：PR #48（`77a0713`，`docs/phase2e-m6-measured-campaign-report.md`）
**日期**：2026-10-15
**性质**：**离线审查**。未跑新实验、未改分析器、未重开 H1/H2、未解锁 B1、未实施策略

---

## 0. 三项裁定摘要

| 项 | 裁定 | 依据 |
| --- | --- | --- |
| **METRIC_REVIEW** | **PASS_WITH_DEFECTS** | 指标定义与我的冻结合同**逐项一致**（含 NGR、D/I、聚合顺序）；但发现 **2 处分析器缺陷**（1 处我已定位为 fail-open），以及 **1 处我自己的合同缺陷**（A2.8 在本 workload 中退化） |
| **MECHANISM_REVIEW** | **ACCEPT_WITH_LIMITS** | 保留 12 个 NOT_REALIZED run 的做法**正确**；但 **F4 的 family 均值被稀释**，必须分层报告；且分析器**未继承 Gate C 的不可比较状态** |
| **RESEARCH_INTERPRETATION** | **SUPPORTED，但必须修正一处因果解释** | 「token 下降未转化为延迟」是**事实**；但 M6 的归因（queue-dominated masking）**不成立** —— 见 §3.3 |

### ⭐ 本轮最重要的发现（一句话）

> **时间三个分量（TTFT / queue / prefill）全部只动了 ~0.05%，而 actual prefill token 降了 14.48%。**
> 因此问题**不是**「收益被排队掩盖」，而是 **token→时间 的转化在 prefill 分量内部就已经失效**。
> 「queue-dominated」是**真实事实**，但**不是**该零结果的解释。

---

## 1. METRIC_REVIEW

### 1.1 与冻结合同的逐项一致性（通过对账代码）

对 `src/kvopt/profiling/phase2e_analysis.py` 逐行核对 `docs/phase2e-m4-task-a-metrics-freeze.md`：

| 合同项 | 代码实现 | 判定 |
| --- | --- | --- |
| **A1.1** = Σ(E−C) | `recomputed = [eligible - cached ...]` | ✅ 一致（含「不得回退为 N−C」的 NOT_COMPUTABLE 分支） |
| **A1.1a** = Σ(N−C)、**A1.1b** = Σ(N−E) | `actual_prefill`、`new_suffix` | ✅ 一致，且三者满足精确分解 |
| **A1.3/A1.4/A1.6** | 时间戳差；`mean(ttft)`、`sum(admission→first)`、`mean(queue)` | ✅ 一致 |
| **A2.5b** severe = `(E−C)/E > 1−θ`，θ=0.25 | `(eligible - cached) / eligible > 0.75`，且**限定 E>0** | ✅ 一致 |
| **A2.6** top1_share + Gini | `max(agent_totals)/total`、`_gini(agent_totals)`；压力请求**被排除** | ✅ 一致 |
| **A1.9 NGR** = \|ΣΔ\|/Σ\|Δ\| | `abs(aggregate)/gross`，gross=0 时 `NOT_APPLICABLE_ZERO_GROSS` | ✅ 一致（**且正确地未把 0 记为 0 或 1**） |
| **聚合顺序** seeds→请求→scenario | `scenarios` 先按 (scenario,baseline) 对 repeat 取 `_mean_metric`，再进入 family 均值 | ✅ 一致 |
| **D / I 视图** | run 级分位标 `I`；`_pooled_descriptive` 标 `D` | ✅ 结构一致 |
| **不插补** | 无 `fillna`/回退；`NOT_APPLICABLE_*` 显式 | ✅ 一致 |
| **C ≤ E ≤ N 与 queued ≤ admission ≤ first** | `_request_values` **抛错**而非修正 | ✅ 一致（fail-closed） |

**内部一致性核算**（我独立复算，`local/probe_2e_arithmetic.py`）：

```text
TTFT = queue + prefill-to-first      : 两臂均精确成立
new-suffix tokens = N−C−(E−C)        : LRU 999.22 vs Continuum 999.22  (Δ = 0.00)  ✓ 同 workload
```

⇒ **指标口径通过**；`new-suffix` 完全相等是一个**很强的自洽证据**（证明两臂确实是同一 workload）。

### 1.2 统计解释：合规，但有两个「无判别力」的诚实结论

| 项 | 状态 |
| --- | --- |
| 报告未做 CI / 阈值 / 显著性主张 | ✅ 与合同 §1.5 一致（36 draws 不足以支撑 P99 推断） |
| 明确标 `I-view exploratory summaries`、`D view descriptive only` | ✅ |
| **NGR 在本 campaign 中无判别力** | ⚠️ 所有非零配对 NGR=1 ⇒ 我设计的 `REDISTRIBUTION_DOMINATED`（<0.5）**从未触发**。这是**检查通过**，但该量**零方差** |
| **A2.8 在本 workload 中退化** | ⚠️ 见 §1.4 |

⚠️ **NGR=1 的含义值得单独指出**：NGR=1 ⟺ 全部非零 Δ **同号** ⇒ **没有任何请求因换策略而变差**。
这是一个**真实的、非平凡的**观察（不是必然的），值得写进收尾结论。

### 1.3 我确认 M1 的两项工程问题均**属实**

**问题 1（fail-open，比 M1 描述更精确）**：分析器**不继承 Gate C 的不可比较状态**。

```python
# phase2e_analysis.py  compare_run_pair(...)
if left.get("status") != "COMPUTABLE" or ... : return NOT_COMPARABLE
#   ^ 只检查本地可计算性，从不读 pair["status"]

# analyze_campaign(...)
valid = [row for row in rows if row["status"] == "COMPARABLE"]   # 本地状态，非 gate_status
```

`gate_status` 与 `mechanism_evaluable` **被记录但从不用于过滤**。
⇒ 若 Gate C 判某配对 `NOT_COMPARABLE`，只要两臂 `COMPUTABLE` 且 request ID 集合相同，
该配对**仍会进入 scenario 均值**。

**影响评估**：本 campaign `72/72 COMPARABLE`、`excluded = 0` ⇒ **当前无实际影响**，缺陷是**潜伏的**。
⚠️ 但这是**fail-open**：未来只要出现一个 Gate C 拒绝的配对，它会静默进入聚合。
⇒ 应改为 **fail-closed**（`gate_status != COMPARABLE` 即排除），并在联合冻结记录中记为前置条件。

**问题 2（确实依赖预设计数）**：`phase2e_evidence.py`

```python
"planned_run_count": 144,      # 硬编码字面量
"successful_run_count": 144,   # 硬编码字面量
"execution_git_sha": "9f9de319...",  # 硬编码字面量
```

- ✅ 强项：`files` 列表由 `root.rglob("*")` **实际遍历**生成，逐文件 SHA-256 + size ⇒ **可独立核验**；
- ⚠️ 弱点：`successful_run_count` **不是**对实际 run 目录的计数，`execution_git_sha` 也不是从 run 内取得。
  若实际 run 数 ≠ 144，manifest **不会失败**（但文件列表会少 4 个文件/run ⇒ 外部可发现）。
- ⚠️ 同类：`analyze_campaign` 中 `"excluded_runs": 0` 亦为**字面量**。

⇒ **结论**：归档的**逐文件哈希链是可靠的**；「144/144 成功」这一**计数**不是自证的，必须由核验者按实际 run 目录数与逐 run `status` 复算。M1 的判断准确。

### 1.4 ⭐ 我自己的合同缺陷：A2.8 在本 workload 中**退化**

M1 特别要求判断 token→TTFT 传递。但**我冻结的传递率指标 A2.8 在本 campaign 中 144/144 全部 `NOT_APPLICABLE_ZERO_MEDIAN`**：

```text
A2.8 = (p99 TTFT / median TTFT) / (p99 rec / median rec)
                                      ^^^^^^^^^^^^^^ median rec = 0 ⇒ 未定义
```

原因：本 workload 中**超过一半的请求 recomputed = 0**（首轮请求 E=0 ⇒ recomputed=0），
故 `median(recomputed) = 0`，分母为零。

- ✅ 分析器**正确地拒绝插补**（记 `NOT_APPLICABLE_ZERO_MEDIAN`），符合我的合同；
- ⛔ 但后果是：**我冻结的合同里，恰好缺少一个可用的「token↔延迟传递」量**，
  而那正是 M1 认为最重要的问题。

⇒ **这是我的合同设计缺陷，不是 M6 的实现缺陷。** 修正建议（下一轮 preregistration）：

```text
A2.8'  分母改为正分位或条件于 E>0：
       (p99 TTFT / median TTFT) / (p99 rec / median rec over requests with E>0)
       并同时报告 median rec == 0 的请求占比
```

本文件中 §3.3 的传递分析是**我用报告聚合值独立做的算术**（`local/probe_2e_arithmetic.py`），
**不属于冻结合同**，故标为 `DERIVED`。

### 1.5 我**无法**核验的部分（必须声明）

⚠️ 原始 archive **不在仓库也不在我这边**。因此：

- 我**未**独立复算任何 run 级或 scenario 级数值；
- 我**未**核验 144/144、72/72、132/12 或任何 SHA；
- 本审查是**基于报告聚合值 + 分析器代码 + 冻结合同**三方交叉的，**不是基于原始证据**的。

⇒ 凡涉及**逐 draw/逐 run** 的结论（尤其 §2.2 的 F4 分层），均标 `DERIVED_PENDING_ARCHIVE`。

---

## 2. MECHANISM_REVIEW

### 2.1 12 个 NOT_REALIZED 的处理：**正确**

12 = F4 draws 01/03/05 × 2 臂 × 2 repeats。已核实物化器：

```python
"shared_prefix_control": family == "F4" and draw % 2 == 0     # 偶数 draw 才是 SHARED_ROOT
```

⇒ F4 的 `draw % 2 != 0`（即 01/03/05）走的是**逐 agent 根**路径。
M6 将其保留（`retained rather than deleted or relabeled`）、参与**请求级**测量、
但**不参与物理淘汰机制声明** —— **完全符合** M1 的指示与我的 §A3 规则 R1/R2。

⇒ **我确认此处理正确，且不应改为删除或重标。**

### 2.2 ⭐ F4 的 family 均值**被稀释**，必须分层报告

报告给出 F4 `6 draws, 3 负 / 3 零 / 0 正`，均值 **−133.33**；并说明「三个零 draw 恰为
mechanism 未实现的 shared-root cases」。

⇒ 故 F4 的 −133.33 是**混合了 3 个机制未实现 draw（Δ=0）**的产物：

```text
F4 mean = (Σ 3 个已实现 Δ + Σ 3 个机制未实现 Δ) / 6 = −133.33
若 3 个零全来自机制未实现 ⇒ Σ 已实现 Δ = −800.00 ⇒ 条件均值 = −266.67
```

| Family | 报告均值（6 draws） | 零 draw 数 | 零 draw 性质 | **条件均值（非零 draw）** |
| --- | ---: | ---: | --- | ---: |
| F3 | −357.33 | 0 | — | **−357.33** |
| F1 | −266.67 | 0 | — | **−266.67** |
| **F4** | −133.33 | 3 | ⚠️ **全部为机制未实现** | **≈ −266.67**（`DERIVED_PENDING_ARCHIVE`） |
| F5 | −208.00 | 0 | — | **−208.00** |
| F6 | −58.67 | 4 | ✅ **机制已实现，是真平局** | **≈ −176.01**（`DERIVED_PENDING_ARCHIVE`） |
| F2 | −128.00 | 0 | — | **−128.00** |

⚠️ **这条区分很重要**：**F4 与 F6 的零 draw 性质完全不同** ——
F4 的零是**机制假象**，F6 的零是**真实平局**。
若不分层，会同时**低估 F4**（实际与 F1 同级）与**高估 F6 的实际差异**（其条件均值更高）。

⇒ **建议**：family 表**必须加一列 `mechanism_evaluable_repeat/scenario` 并给出条件均值**；
分析器已经计算了 `mechanism_evaluable_repeat_count`，只是**未用于分层**。
⚠️ 依 M1：这些 run 的**请求级**测量有效，故**保留**；但**不得**用于机制结论，**也不应混入 family 均值**。

### 2.3 能力边界：全部保持

| 边界 | 状态 | 我是否同意 |
| --- | --- | --- |
| P5 `PARTIALLY_DEMONSTRATED` | 保持 | ✅ |
| physical logical-owner attribution `NOT_OBSERVABLE` | 保持 | ✅ |
| eviction→recomputation causality `NOT_ESTABLISHED` | 保持 | ✅（且我的 §A3 R1 要求「同一 hash process + 内容身份可解析」，本 campaign 未逐条认证） |
| F6 是 lifecycle overlap 而非 GPU kernel concurrency；压力在完成之后 | 保持 | ✅ |
| workload 为预定义合成网格，非生产分布抽样 | 保持 | ✅ |
| `max_new_tokens=1` ⇒ 不刻画 decode 寿命 | 保持 | ✅ |

⚠️ 我补充一条**结构性事实**（来自物化器）：

```python
"max_concurrent_requests": 3 if family == "F6" else 1
```

⇒ **F1–F5 的并发度为 1**。因此 queue delay（0.657 s）**不是 GPU 争用**，
而是**同 scenario 内请求在串行执行下的排队等待**。

⚠️ 这**改变了对 §3.3 的初步解读**：90% 的 queue 份额是**测量与执行设计**的产物（含 planned offsets 与串行化），
**不能**直接外推为「生产环境中 recomputation 与延迟无关」。
但它**也不解释**零结果 —— 理由见 §3.3。

### 2.4 机制有效性的**可评估子集**

144 run 中 **132 REALIZED / 12 NOT_REALIZED**。但注意：`mechanism_evaluable` 在 Gate C 中要求
**两臂同时 REALIZED**。F4 的 01/03/05 两臂皆 NOT_REALIZED ⇒ 这 6 个 scenario 的
**配对机制不可评估**（其请求级 Δ 仍有效）。

⇒ 机制结论的**有效 scenario 数 = 36 − 6 = 30**（其中 F4 只剩 3）。
⚠️ 因此任何 family 级机制主张，其**有效样本是 30 而非 36**，须显式写出。

---

## 3. RESEARCH_INTERPRETATION

### 3.1 当前结果**能够支持**的探索性结论

| # | 结论 | 强度 |
| --- | --- | --- |
| **C1** | 在本冻结合成 workload 中，Continuum 在 scenario 级**保留了更多可复用前缀**：aggregate recomputed 326.67 → 134.67（**−58.77%**） | **实测**（29/7/0，方向一致） |
| **C2** | 该 token 收益**不是再分配**：所有非零配对 `NGR = 1` ⇒ **无任何请求变差** | **实测**（且非平凡） |
| **C3** | token 尾部同样改善：per-draw P99 recomputed **−29.17%** | **实测**（I 视图） |
| **C4** | **未观察到任何延迟层面的对应改善**：TTFT +0.056%、queue +0.057%、prefill-to-first +0.050%；I 视图 P99 TTFT −0.349%、D 视图 +0.036% | **实测** |
| **C5** | ⭐ **prefill 分量本身未响应 token 减少**：actual prefill token **−14.48%**，而 prefill-to-first 时间 **+0.050%** | **实测**（本节核心） |

### 3.2 当前结果**不能支持**的结论

⛔ 不能声称：
- Continuum 优于 Native LRU（**延迟未改善**，且无 CI ⇒ 不能声称「无差异」也不能声称「有改善」）；
- 某一物理淘汰导致了某次 miss（`NOT_ESTABLISHED`）；
- 效果可外推到生产分布（合成网格）；
- 任何 Cost-Aware policy 的收益。

### 3.3 ⭐ 为什么 recomputation savings 不能作为 latency benefit 的代理

**这是 M1 特别要求判断的一项。我的结论与 M6 的解释不同。**

**（a）已观察事实**

```text
queue  : 0.656917 -> 0.657290   +0.057%
prefill: 0.072453 -> 0.072489   +0.050%
TTFT   : 0.729370 -> 0.729779   +0.056%
份额（两臂相同）：queue 90.07% ／ prefill 9.93%
token ：recomputed -58.77%，actual prefill -14.48%
```

**（b）M6 的解释及其问题**

报告写：*"Queue delay dominates ... in this workload"*，以此解释零结果。
但**该解释不能成立**，理由是：

> queue 分量**只能通过 service time 变化**而缩小（`queue ≈ Σ 前序请求 service`）。
> 若 token 减少真的改善了 prefill，则 service time 会下降，**queue 与 prefill 会一起下降**。
> 实测**二者都没动**（+0.057% / +0.050%）。

⇒ 若「prefill 时间 ∝ prefill token」，则预期：

```text
prefill-to-first : 0.072453 × (1 − 0.1448) = 0.061961   （实测 0.072489）
TTFT             : 0.718878                              （实测 0.729779）
预期收益          : −1.438%  ≈ −10.49 ms
实测             : +0.056%  = +0.409 ms      ⇒ 实现比例 ≈ −3.9%
```

**（c）正确表述**

| 层 | 表述 |
| --- | --- |
| **已观察事实** | queue 占 TTFT 的 **90.07%**（两臂相同）；且 prefill-to-first **未响应** 14.48% 的 token 减少 |
| **已推导（DERIVED）** | 若 prefill 时间线性于 token，TTFT 应改善 **1.438%**；实测为 **+0.056%** ⇒ 实现比例 ≈ **−3.9%** |
| **未证明** | **为什么** prefill 时间不响应 token 数。候选（**均未检验**）：① 这些规模（≤256-token prompt、`max_new_tokens=1`）下 prefill 由**固定开销**主导（kernel launch / 调度 / 首 token 生成）；② `native_first_token_timestamp` 的时间粒度或噪声覆盖了 ~10 ms 效应；③ prefill token 数在引擎重批处理下**并非成本驱动量**。**无 CI，故不能做任何显著性主张** |

⇒ **结论**：**不是**「收益被排队掩盖」，而是 **token→时间 的转化在 prefill 分量内部就已经失效**。
「queue-dominated」是事实，但把它当作零结果的**解释**是**未被支持的推断**。

⚠️ **这一条对下一阶段是决定性的**：如果 prefill 时间在本 regime 不随 token 数变化，
那么 **`recomputed tokens` 作为面向延迟的目标函数是无效的**，
后续优化必须改用**时间锚定**的目标（见 §4）。

### 3.4 我无法判定的一项

`tail_transfer_ratio` 全 144 run 不适用（分母为 0，见 §1.4），
故**冻结合同中不存在可用的传递率量**。§3.3 的算术是我的替代分析，非合同指标。

---

## 4. 下一阶段建议

### 4.1 最值得验证的**成本目标**（必须换）

⛔ **不再以 `recomputed tokens` 作为主目标**（§3.3：它在本次 regime 中无时间信号）。
建议按优先级：

| # | 候选成本目标 | 理由 |
| --- | --- | --- |
| **T1** | **`prefill-to-first` 时间（条件于 E>0）** | 直接锚定时间；本 campaign 已证明它与 token 数脱钩，需先弄清其驱动量 |
| **T2** | **KV 容量 / admission 效应** | 若 per-request 延迟对 recomputation 不敏感，token 节省的价值可能体现在**总计算量与 KV 压力**上（间接影响 admission 与 queue）。本 campaign **未测** |
| **T3** | **完整请求延迟（含 decode）** | 本 campaign `max_new_tokens=1` ⇒ 无法刻画；需 `max_new_tokens>1` |

⚠️ **测量设计前置条件**：要验证任何延迟收益，必须存在一个 **prefill 份额足够大**的 regime。
本 campaign 的 queue 份额 90.07%（且 F1–F5 并发=1）使 token 效应在**原理上**被压到 ≤1.44%。
⇒ 下一轮**至少需要一个低队列/高 prefill 份额的臂**，否则延迟类结论不可检验。

### 4.2 最值得验证的**失败模式**

按「实测效应大小 × 未被已有方法覆盖」排序：

| 优先级 | 失败模式 | 实测依据 | 为何值得 |
| --- | --- | --- | --- |
| **①最高** | **F3 非等长前缀与成本异构** | 效应最大：**−357.33** | ⭐ **RR-EVICT 假设等长前缀 + 等比例轮转**（其 Eq 2 的 $h$ 对每个 agent 相同）⇒ **F3 正是该假设失效之处**，且我们有决策时可观测的代理（前缀长度） |
| **②** | **F1 多 agent 周期返回** | −266.67 | 与 RR-EVICT 的机制重叠（其主场），**创新性需谨慎** |
| **③** | **F4 跨 agent 共享前缀** | 条件 ≈ −266.67（待核） | 共享位于**前缀根部**，tail-first **天然保护共享头** ⇒ 与 RR-EVICT（假设无跨 agent 共享）方向一致，可能形成正向协同 |
| **④** | **F6 并发/突发** | 条件 ≈ −176.01，**4 个真平局** | 效应最小且平局最多 ⇒ **最低优先级**；且 `max_new_tokens=1` 使其不代表真实并发 |
| **⑤** | F2 冷热与非均匀返回 | −128.00（最小） | 与 H1 已测的返回因子方向重叠，证据已弱 |

⚠️ **F4 与 F6 的排序依赖 §2.2 的分层复核**（`DERIVED_PENDING_ARCHIVE`）。

### 4.3 建议的下一步（**不**请求新实验授权）

1. **修正分析器（M6 定点）**：
   - 继承 `gate_status`（fail-closed）；
   - family 表加 `mechanism_evaluable` 分层与条件均值；
   - manifest 的计数改为**实际遍历导出**。
2. **修正我的合同（M4）**：`A2.8'` 条件于 E>0（§1.4）；`A1.11` 增加 `prefill-to-first` 的条件化版本。
3. **收尾结论的措辞**（建议 M1 采纳）：
   > *本 campaign 提供了可复现证据：在冻结合成 workload 中，更多 KV 前缀复用**并未**带来请求延迟改善；
   > 且 token 的减少**未**在其自身的 prefill 时间分量上产生可测响应。*
   > *因此后续 Cost-Aware 研究不能以 recomputed-token 数量为目标函数，而须先建立一个
   > prefill 份额足够大、且能观测到 token→时间响应的测量 regime。*
4. **Phase 2E 收尾**：接受 `C1–C5` 为探索性结论；`C5` 为本轮最有价值的方法学发现。

---

## 5. 请求 M1 裁定

1. **METRIC_REVIEW** 是否接受 `PASS_WITH_DEFECTS`（口径合规 + 2 处分析器缺陷 + 1 处我的合同缺陷）？
2. **§3.3 的解释修正**：是否接受「**不是 queue-dominated masking，而是 prefill 分量内部 token→时间转化失效**」这一修正？
   ⚠️ 这是与 M6 报告措辞的**实质分歧**，请裁定。
3. **§2.2 的 F4 分层**：是否要求 family 表按 `mechanism_evaluable` 分层（F4 条件均值 ≈ F1）？
4. **§1.3 的 fail-open 缺陷**：是否要求**在联合冻结记录中**记为前置条件（改为 fail-closed）？
5. **§4.1 T1–T3**：是否确认下一轮的主目标**不再**是 `recomputed tokens`，并需要「低队列份额」的测量臂？
6. **§4.2 优先级**：是否确认 **F3（非等长前缀与成本异构）** 为下一阶段最高优先级的失败模式？

---

## 6. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| 报告全部聚合值 | `docs/phase2e-m6-measured-campaign-report.md`（PR #48，`77a0713`） |
| A1.1/A1.1a/A1.1b、A2.5b、A2.6、NGR、聚合顺序、D/I 视图 | `src/kvopt/profiling/phase2e_analysis.py`（`_request_values`、`compute_run_metrics`、`compare_run_pair`、`analyze_campaign`） |
| 冻结口径 | `docs/phase2e-m4-task-a-metrics-freeze.md`（A1/A2/A3 + §1.2 D/I + §1.3 证据分级） |
| `TTFT = queue + prefill`、`new-suffix` 两臂相等、预期 vs 实测传递 | `local/probe_2e_arithmetic.py`（我独立复算报告聚合值） |
| `max_concurrent_requests = 3 if F6 else 1`；F4 奇偶 draw 的共享控制；offsets | `src/kvopt/workload/phase2e_materialize.py`（`:106`、`:107`、`:51-58`） |
| family 数（6）× draws（6）× 2 臂 × 2 repeats = 144 | `configs/phase2/phase2e-workload-distribution-v1.json` |
| `planned_run_count`/`successful_run_count`/`execution_git_sha` 为字面量 | `src/kvopt/profiling/phase2e_evidence.py`（`:91-92`、`:95`） |
| Gate C 的 `status` / `mechanism_evaluable` | `src/kvopt/profiling/phase2e_campaign_gate.py`（`:38-48`） |
| P5 / logical owners / causality 边界 | `docs/phase2e-m4-t1-capability-reconciliation.md` §C |
| RR-EVICT 假设等长前缀 | `local/2609.32278v2.pdf` §3.3（Eq 2 的 $h$ 与 $n_s$） |
| 我的 A2.8 定义 | `docs/phase2e-m4-task-a-metrics-freeze.md` §3.2 |
