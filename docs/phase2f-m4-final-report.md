# Phase 2F 最终报告 — Ours-Evict × Continuum Retention 离线模拟研究

**提交人**：M4　**送审**：M1　**日期**：2026-10-16
**分支**：`sim/phase2f-agent-apc-eviction-retention`
**性质**：CPU-only 离线模拟研究（无 GPU、无真实模型、无 native run）。
**不宣称**：真实 GPU / 真实 vLLM / 真实 TTFT / TPOT / 吞吐 / 生产负载性能。

---

## 0. 一句话结论

> 在贴近 Agent 多轮工具调用的缓存工作负载中，**独立的 band 内深优先 victim 选择（Ours-Evict
> simulation candidate v0）在长会话与共享前缀场景带来大幅且零回归的重计算下降**
> （整体配对 −1658.5 tokens/draw，S5 达 −11465.6/draw，2088 个请求级比较 0 回归）；
> **Continuum Retention 的增量贡献真实但条件性强**：在突发并发与慢返回场景它通过
> **收缩合法候选集**提供主要收益（S4：−190.4/draw），且在该场景下**完全包含**驱逐规则的效果
> （A3 ≡ A1）；在 recency 已足够的场景两者皆无收益；对**已经最优的 victim 规则，Retention
> 反而是纯约束**（oracle + retention 比 oracle 单独差 +645.8/draw）。

---

## 1. 交付物与复现

| 交付物 | 位置 |
| --- | --- |
| 组合算法设计 | `docs/phase2f-m4-combined-algorithm-design.md` |
| 模拟器设计 | `docs/phase2f-m4-simulator-design.md` |
| 本报告 | `docs/phase2f-m4-final-report.md` |
| 实现 | `src/kvopt/agent_sim/`（content / pool / trace / workload_gen / retention_bridge / policies / simulator / experiments / report / cli） |
| 测试 | `tests/test_agent_sim_micro.py`（4 个核心微基准）、`tests/test_agent_sim_mechanics.py`（12）、`tests/test_agent_sim_invariants.py`（3） |
| 一条命令复现 | `python scripts/phase2f_run_simulation.py --out results/phase2f`（≈45 s，CPU-only） |
| 机器可读结果 | `results/phase2f/campaign.json`、`report.md`、3 张 PNG |

 campaign 规模：7 族 × 10 draws = **70 个独立 scenario draw**（统计单位）；
每 draw × 8 臂（A0/A1/A2/A3/A4/O1/O2/D1）。种子 `20261016`，trace hash 记录于
`results/phase2f/traces.json`。

---

## 2. 实验设置（摘要）

- **臂**：A0 Native LRU；A1 Retention + 原生 LRU（直接实例化冻结
  `RetentionAwareLRUAdapter`）；A2 Ours-Evict（candidate v0，无 Retention）；
  A3 = A2 + Retention（目标组合）；A4 = A1 + 冻结 `ContinuumSchedulingPolicy`
  准入排序（系统参照，单独报告）；O1/O2 = Belady 风格 oracle（± Retention，
  **不是** Ours-Evict）；D1 = band 内方向反转（诊断）。
- **candidate v0**：合法候选按 `(tier, band_min_rank, −depth, lru_rank)` 升序取
  R 个。零超参；`depth`/`band` 为**模拟可观测、线上需接口扩展**信号；
  信号缺失时逐位退化为 native LRU（单测 D3 断言）。
- **物理语义**：固定 block 池（block size 16）；链式内容 hash（trie）；
  严格前缀截断命中；free queue 复刻 vLLM 0.27.1 入队规则（hashless prepend /
  hashed append，band 内头先=假设 A1）；淘汰真实移除 hash mapping 并立即重用槽位。
- **Retention**：全部复用冻结组件（`RuntimeCoordinator` / `RetentionManager` /
  `RetentionAwareSelectionCoordinator`），未修改 `src/kvopt/continuum/**`。
- **统计**：draw 级配对；均值/中位数；10,000 次 paired bootstrap 95% CI
  （种子 20261016）；报告改善/平/退化 draw 数与 NGR。

---

## 3. 主要结果

### 3.1 臂级汇总（70 draws，measured 窗口）

| 臂 | 均值 recomputed tokens/draw | hashed 淘汰 | 强制释放 | 非平凡窗口占比 |
| --- | ---: | ---: | ---: | ---: |
| A0 Native LRU | 4981.0 | 23893 | 0 | 100.0% |
| A1 Retention + Native | 4925.9 | 23624 | 503 | 98.2% |
| **A2 Ours-Evict** | **3322.5** | 16630 | 0 | 100.0% |
| **A3 Ours-Evict + Retention** | **3275.2** | 16402 | 503 | 98.2% |
| A4 Full Continuum 参照 | 4891.7 | 23474 | 477 | 98.1% |
| O1 Oracle（无 Retention） | 2039.5 | 11537 | 0 | 100.0% |
| O2 Oracle + Retention | 2685.3 | 14362 | 503 | 98.2% |
| D1 方向反转（诊断） | 4981.0 | 23893 | 0 | 100.0% |

### 3.2 配对比较（负 = challenger 更少重算；ΔR 为任务公式 Σ B·max(0, j_old−j_new)）

| 家族 | A2 vs A0 | A1 vs A0 | A3 vs A1 | A3 vs A2 | A4 vs A1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| S1 连续工具调用 | 0 | 0 | 0 | 0 | 0 |
| S2 长短工具等待 | −11.2 | **−19.2** | 0 | −8.0 | 0 |
| S3 共享根+私有分支 | **−96.0** | −108.8 | −76.8 | −89.6 | 0 |
| S4 突发并发高压 | 0 | **−190.4** | 0 | −190.4 | **−240.0** |
| S5 长会话增量增长 | **−11465.6** | 0 | **−11465.6** | 0 | 0 |
| S6 冷/暖启动+漂移 | 0 | 0 | 0 | 0 | 0 |
| S7 负对照 | −36.8 | −67.2 | −12.8 | −43.2 | 0 |
| **ALL** | **−1658.5** | −55.1 | −1650.7 | −47.3 | −34.3 |

（完整 CI / 中位数 / 改善-平-退化计数 / NGR 见 `results/phase2f/report.md` §2。
除 A4 vs A1 的 mean ΔR = +4.8 外，所有主比较的 ΔR = 0——即没有任何策略相对其对照
产生逐请求的额外重计算。）

### 3.3 机制链验证（任务 §七）

```text
L1 候选合法   : validate_selection 在每次决策强制执行（唯一、⊆ candidates、
                数量 = min(required, |candidates|)）；560 个 draw×臂组合 0 失败
L2 决策不同   : A2 vs A0 victim 集合分歧率 36.9%（100% 决策处于非平凡窗口）；
                A3 vs A1 分歧率 36.6%（97.1% 非平凡）
L3 物理改变   : 淘汰真实移除 cache mapping（微基准 a/b；幽灵命中测试通过）
L4 重计算改变 : 同一未来 trace 重放，aggregate recomputed 显著改变（§3.2）
增量归因      : A0/A1、A2/A3、A1/A3、A2/A3 四方对比（§3.2 表）
```

**反事实（首次分歧的因果效应）**：60/70 个 draw 出现首次 victim 集合分歧；
把 challenger 的 victim 集合替换进该单一决策后，**平均避免 74.7 tokens 重计算**
（max 688），**反向损伤合计 0**——与支配性定理一致。

**机制不变量（campaign 级单测断言）**：

1. `D1 ≡ A0` **逐位相同**（70/70 draws 的每个决策 victim 序列完全一致）
   ⇒ 模拟中原生 free queue 的 band 内方向**确实是浅层先淘汰**，
   即 M1 RC-B 指出的结构信号在模拟内被直接证实；candidate v0 正是反转该方向。
2. candidate v0 对 native **2088/2088 个请求级比较零回归**（无任何请求命中深度下降）。
3. S7 负对照 draws 1–6 在所有臂下 recomputed **恒等于 0**（无复用/无压力 ⇒ 任何
   victim 选择等价）。

---

## 4. 增益来源归因（研究问题的直接回答）

### 4.1 三种通道的分离证据

| 通道 | 证据 | 量级 |
| --- | --- | --- |
| **更合理的物理 victim 选择** | A2 vs A0（Retention 关闭，唯一差异是 band 内方向） | 整体 −1658.5/draw；S5 −11465.6；S3 −96.0；per-request 0 回归；反事实 +74.7/决策 |
| **合法候选集变化（保护/释放）** | A1 vs A0（victim 规则同为原生，唯一差异是 Retention 资格过滤+压力释放） | 整体 −55.1/draw；S4 −190.4；S3 −108.8；503 次强制释放；保护窗口结束时 41180 块仍存活 / 11468 块被毁 |
| **延长有效复用** | 保护期间被跨 program 复用的块；保护窗口存活率 | 1540 块保护期间复用；78% 受保护块在窗口结束时仍可命中 |

### 4.2 关键交互：Retention 与驱逐规则是**替代**而非纯叠加

- **S2/S4**：`A3 ≡ A1`（10/10 draws 逐位相等）。Retention 把最有价值的浅层块移出
  候选集后，剩余候选里的 victim 选择不再影响重计算 ⇒ 收益**全部来自候选集变化**。
- **S5**：`A1 ≡ A0`（Retention 完全无效），但 `A2/A3` 大幅获益。冻结 Retention 只保护
  每个 program **最新一轮**的前缀（旧轮次 entry 在下次 admission 即解除保护），
  无法保护长会话累积的历史前缀；此时只有驱逐规则能保住链头。
- **S3**：两者**部分叠加**（A3−A0 = −166.4 > 各自单独的 −108.8 / −96.0，但 < 之和）。
- **Oracle 约束实验**：O2（2685.3）**差于** O1（2039.5）达 +645.8/draw；oracle 决策中
  53% 受到保护/强制释放约束。⇒ **Retention 的保护对"已经最优的 victim 规则"是纯负担**；
  它的价值依赖于基线规则会犯错（native LRU 会淘浅层块）。

### 4.3 收益存在与消失的条件

| 条件 | 场景 | 结果 |
| --- | --- | --- |
| 长会话累积前缀 + 持续压力 | S5 | 驱逐规则收益极大（−11465.6/draw）；Retention 无效 |
| 共享根前缀 + 压力 | S3 | 两者都有效且部分叠加 |
| 突发并发 / 慢返回 + 压力 | S2、S4 | Retention 主导（候选集机制），包含驱逐规则效果 |
| recency 已足够保护有价值内容 | S1、S6 | 两者均无收益（native LRU 已把热块留在队尾） |
| 无后续复用 / 无压力 | S7 draws 1–6 | 恒 0（负对照，符合预期） |
| victim 规则已最优 | O1 vs O2 | Retention 反而有害 |

---

## 5. Retention 专项指标（A1/A3 共享同一 Retention 路径，数值逐位相同）

| 指标 | 值（70 draws 合计/均值） |
| --- | ---: |
| 强制释放次数 | 503（零边际释放 0 次——本 campaign 的共享条目总与其他条目共块，见微基准 c） |
| 自然 TTL 过期次数 | **0**（结构性结论，见 §6.1） |
| 受保护 block-token-seconds | 6005 / draw |
| 保护期间实际再次复用（跨 program） | 1540 块 |
| 保护窗口结束时仍存活 / 被毁 | 41180 / 11468 块（78% / 22%） |
| 保护后从未被复用（finalize 口径） | A1 12740 块；**A3 7381 块**（candidate v0 使受保护容量浪费下降 42%） |
| 共享块因其他 owner 受保护而不可回收 | 微基准 (c) 逐事件验证；campaign 内 S3/S4 决策可观测 |
| cold vs warm（S6） | recomputed 均为 0；淘汰 7 → 41~47（warmup  flooding 缓存）；TTL 模式 cold_start → global |

---

## 6. 结构性与敏感性发现

### 6.1 冻结 TTL 估计器在这些尺度下坍缩为 0（与 Phase 2A F.2 一致）

`argmax_τ F(τ)·(T·η + R) − τ` 中 T（queue delay）在模拟内退化为 0（无排队模型），
R ≈ 0.02–0.3s（正式 PrefillReload profile，>512 tokens 线性外推已标注），
而 tool gap 为 0.05–20s ⇒ 经验 TTL 几乎恒为 0 ⇒ **自然 TTL 过期在模拟中不可达**，
Retention 的保护实际由 `waiting_followup` 窗口提供。TTL 探针（冻结估计器 +
T 扫描）：T = 0 / 0.05 / 0.65 时非零 TTL 决策数为 286 / 326 / 326（共 4506）。
⇒ **TTL 维度在本 workload 尺度下不构成判别力**；这是如实记录的结构性负面结果，
不是实现缺陷。

### 6.2 band 内方向假设（A1）的敏感性

全 campaign 以 `free_order=tail_first` 重跑：candidate v0 与 native 的 victim 集合
**一致率 100%**（7/7 族）⇒ 若真实 vLLM 的 band 内顺序本就是尾先，candidate v0
与 native 完全同选（无收益也无损害）。**收益的存在性完全依赖于假设 A1**；
A1 源自 pinned vLLM 源码语义（M1 RC-A 引用）与 Phase 2C 87/87 连续带证据，
但本项目的 P5 `(depth, native_lru_rank)` 对应关系 `NOT_OBSERVABLE`，
**必须在真实 runtime 上测量后才能声称可部署**。

### 6.3 与 PR #50 / M1 评审的对应

| M1 意见 | 本轮处置 |
| --- | --- |
| RC-A（hashless 优先是原生行为） | candidate v0 **不主张** hashless-first；hashless 保持原生优先，创新点仅在 hashed band 内方向 |
| RC-B（lru_rank 方向矛盾） | 用模拟直接测量：D1 ≡ A0 逐位证实"原生先淘浅层块"；`(depth, lru_rank)` 统计由模拟器输出（§模拟器设计 §7） |
| RC-C（共享前缀未覆盖） | 支配性定理经 free-event band 结构覆盖共享前缀（共享根位于 band 头部，深优先天然保护它）；微基准 (c) 验证 |
| RC-D（ΔR 公式） | 全程使用 `ΔR = Σ_r B·max(0, j_old(r) − j_new(r))`；报告同时给出带符号聚合差与 NGR |
| RC-E（接口不预授权） | `depth`/`band` 明确标注"模拟可观测、线上需接口扩展"；未请求任何 adapter 字段变更 |

---

## 7. 结论分级

### 7.1 模拟中已验证（可作为机制事实）

1. 原生 free queue 的 band 内顺序是浅层先淘汰（D1 ≡ A0 逐位，70/70 draws）。
2. band 内深优先选择相对浅层优先**弱占优**：campaign 内 2088/2088 请求零回归；
   反事实首次分歧反向损伤 0。
3. 该选择真实改变 victim 集合（分歧率 36.9%）与物理缓存状态，并在同 trace 重放下
   显著降低 aggregate recomputed tokens。
4. Retention 通过候选集收缩产生独立增量（A1 vs A0），并通过强制释放可观测地
   破坏受保护内容（11468 块）。
5. Retention 对已最优 victim 规则是纯约束（O2 > O1）。
6. 负对照（无复用/无压力）下所有臂恒等。

### 7.2 近似模型推断（依赖已声明假设）

1. 收益量级依赖假设 A1（band 内头先入队）——源码推导 + 连续带证据，未运行时实测。
2. 队列延迟退化为 0（无排队模型）⇒ TTL 维度结论受此限制（探针已量化）。
3. block size 16、block 对齐 segment、瞬时执行、最后 prompt block 不可缓存
   （冻结 cap）等建模抽象（见模拟器设计 §9 差异表）。
4. 合成 workload 不外推生产分布。

### 7.3 仍需真实 vLLM 验证

1. **band 内方向**：(block depth, native_lru_rank, same-free-event identity) 的
   真实对应关系与方向（P5 缺口）。
2. 部分 APC 命中行为（保留前导、重算后缀）与模拟假设一致。
3. 任何延迟/吞吐结论（本报告 NOT_MEASURED）。
4. candidate v0 若需 runtime 化：`depth` + free-event 分组信息的**最小只读接口扩展**
   （须 M1 批准，且不在本轮范围）。

---

## 8. GO / NO-GO 与最小真实运行时验证方案

### 8.1 裁定建议

```text
Ours-Evict (candidate v0) 机制线               : GO（有条件）——模拟证据强
  （零回归 + 大效应量 + 清晰的物理机制 + 反事实验证），但增益存在性依赖假设 A1。
Continuum Retention 作为 Ours-Evict 的补充     : CONDITIONAL GO
  ——在突发/慢返回/共享根场景有真实增量；在长会话场景无效；对强驱逐规则可能有害。
  它不是"免费的叠加层"，而是与驱逐规则**职能重叠**的替代机制。
TTL 动态估计维度                                : NO-GO（本尺度）——坍缩为 0，
  不构成判别力；除非换到 gap 与 reload 成本可比的尺度（探针已量化门槛）。
```

### 8.2 最小真实运行时验证（4 步，全部在既有授权边界内）

1. **只读测量 A1**（不需任何策略变更）：在 pinned vLLM 0.27.1 上用既有 observer
   快照能力，记录若干次 `get_new_blocks` 决策点的 `(block_id, has_block_hash,
   native_lru_rank, 同一 free event 的批次身份, 前缀深度)`，输出 band 内
   `(depth, lru_rank)` 的秩相关与方向统计。**判据**：若 hashed band 内
   depth 与 lru_rank 正相关（头先）且比例显著 ⇒ A1 成立，进入第 2 步；
   若尾先 ⇒ candidate v0 无增益，记录负面结果并关闭该方向。
2. **最小接口扩展申请**（仅在步骤 1 通过后）：向 `EvictionCandidate` 增加
   **可选只读** `depth: int | None` 与 free-event 分组标识（或等价的"同一入队
   批次 + 批次内位置"），默认 None 时 adapter 逐位退化为 `NativeLRUAdapter`。
   ——这是 RC-E 要求的事后最小申请，本轮**未**预先请求。
3. **受控 A/B**（Phase 1A controlled 模式）：一个共享根 + 长会话压力 fixture，
   native LRU vs candidate v0，主指标 `aggregate_recomputed_tokens`，
   配对重复；同时记录 `FORCED_RELEASE_DECISION` 与真实 hash eviction 台账。
4. **Retention 增量复测**：同一 fixture 上 A1/A3 对比，检验"候选集机制 vs
   victim 选择机制"的分离是否在真实 runtime 重现。

---

## 9. 失败与限制登记

- 无 arm × draw 执行失败（560 组合全部成功；`campaign.json` §failures 为空）。
- 已知平台性测试失败 33 个与 main 基线一致（Windows 环境产物；本轮新增 0 个代码回归；
  唯一差异是冻结 gate 对未提交工作树的反应，提交后恢复）。
- 统计效力：每族 10 draws ⇒ CI 较宽；本报告只做方向性与效应量陈述，
  不做 P99 推断（遵 Phase 2E §1.5 边界）。
- 反事实只覆盖**首次**分歧决策（其因果效应均值 74.7 tokens）；后续分歧的累积
  效应由端到端配对差覆盖。
