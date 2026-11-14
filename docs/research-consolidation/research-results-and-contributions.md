# 研究结果综合分析与方法贡献提炼

**状态：** M1 综合分析修订稿（R1.3；吸收 M4 独立互审）  
**日期：** 2026-11-14  
**适用范围：** Phase 0/1 至 Phase 4 已提交的实验、审计与离线研究  
**证据索引：** [R1 跨阶段实验与证据账本](r1-experiment-evidence-ledger.md)  
**当前裁定边界：** Phase 3 Option F 的 270-run 执行及只读复核已完成，但最终 M1 adjudication 仍待完成。

> 本文是对既有证据的综合解释，不替代冻结协议、原始 Archive、阶段最终报告或 M1 正式裁定。它不修改历史结果、不合并不同 campaign 的样本、不将描述性结果升级为正式假设通过，也不授权新 GPU 实验。

---

## 0. 阅读规则：实验完成、假设成立与方法授权是三件事

必须区分：

1. **Campaign completion / acceptance：** 实验是否按其冻结范围完成并被接受。
2. **Hypothesis / rule verdict：** 被检验的假设是否达到预注册或阶段约定的证据门槛。
3. **Method authorization：** 是否允许据此设计、实现或部署下一种策略。

三者不能互相推出。一个 campaign 可以完整交付，但假设仍为 DIAGNOSTIC_ONLY 或 INCONCLUSIVE；一个机制可以在局部 fixture 中被证明存在，也不代表在线策略已获得授权或表现出服务收益。

### 0.1 Phase 3 六臂定义

Phase 3 中各臂的含义必须按决策层理解，不能把 A1/A2/A3 当成一个组合算法：

| Arm | Logical Entry Release | Physical Block Victim Selection | 作用 |
|---|---|---|---|
| N0 | 不执行强制 Entry Release | Native LRU | 强制 Entry Release 路径的对照 |
| A0 | 冻结的项目侧 Continuum-style Entry Release | Native LRU | Phase 3 基线；不是完整复现公开 Continuum |
| A1 | Cost-Aware Entry Release | Native LRU | 检验 Entry 层成本排序 |
| A2 | 与 A0 相同的 Entry Release | Cost-Aware Block selector | 只检验物理 Block victim 选择 |
| A3 | Suffix-cost-aware Entry Release | Native LRU | 检验后缀成本感知的 Entry 决策 |
| E0 | A1 分支阶梯中的 deadline-only Step 2 | Native LRU | A3 的强 deadline-only 对照 |

A1/A3/E0 改变逻辑 Entry 的释放选择；A2 改变物理 Block 的选择。Entry Release 只改变受保护 Entry 的 eligibility，不等于已经发生物理 Block eviction。

**A0 的冻结 Entry Release 排序键**为 `(entry.deadline_timestamp, min_{b ∈ NewlyEligible(e)} native_lru_rank(b), key.sort_key)`；若 `NewlyEligible(e)` 为空，第二键按 `+∞` 处理。因此 A0 不是纯 deadline-first：它以 deadline 为主键，再以仅因释放该 Entry 而新获得驱逐资格的 Blocks 中最小 Native LRU rank、以及确定性 Entry identity 排序；实际物理 Block victim selection 仍由 Native LRU 执行。

### 0.2 统一 Token 口径

对于有完整 Native prefix 证据的请求：

- N：Native prompt tokens；
- E：独立推导的 eligible reusable-prefix tokens；
- C：Native APC cached-prefix tokens；
- R = E - C：eligible-prefix recomputation，Phase 3 主指标；
- W = N - C：actual prefill work；
- S = N - E：new suffix tokens；
- 恒等式：W = R + S。

因此，N-C 是实际 prefill work，不应直接命名为重算 Token；E-C 才是本项目 Protocol v4 的 eligible-prefix recomputation。

**Phase 2D 特别说明：** E3 报告中的 observed_recomputed_tokens 实际由 native_prompt_tokens - native_cached_prefix_tokens 计算，即 N-C。其 64-token 配对差异保留为该 fixture 中的 Native prefill-work 差异，不能把其绝对数值直接并入 Protocol v4 的 E-C 结果。该局部差异仍支持“不同逻辑释放选择可改变后续 Native 计算量”的机制观察，但不应改写指标口径。

---

## 1. 实验结果综合分析：不同阶段究竟证明了什么？

### 1.1 Phase 0 / Phase 1：项目具备受限的 Native 集成基础

Phase 1A 将项目策略限制在合法 victim Block ID 的选择边界；BlockPool、FreeKVCacheBlockQueue、ref count、APC hash cleanup、分配与物理 eviction bookkeeping 仍由 Native vLLM 持有。

Phase 1B 在 vLLM 0.27.1 与固定 PrefillReload profile 下完成真实运行时验证，覆盖 retention、pressure-driven Entry Release、Native eviction callback / BlockPool cleanup、scheduler coordination 与 terminal cleanup。

**证明了：**
- 可以在不接管 Native BlockPool / APC 所有权的前提下，接入项目侧 retention、Entry Release 和物理 victim 选择边界；
- 项目侧 Continuum-style lifecycle / retention 适配在已验证的 runtime/profile 范围内能够运行。

**没有证明：**
- 对公开 Continuum 原系统的逐字节或完整系统复现；
- 原论文 workload 的复现；
- 相对于 Vanilla vLLM 的端到端性能优势；
- Phase 1B scheduling adapter 的性能收益。Phase 3 六臂均使用 Native scheduler，没有对 scheduler 做 treatment。

### 1.2 Phase 2A：早期代理假设与机制测量并未直接给出可部署策略

**H1-R1 reverse-deadline。** Campaign 计划 126 runs，成功 96，封存 42 个 scenario draws，最终只有 29 个 paired-evaluable draws，低于冻结门槛 30。结果为 13 better / 14 worse / 2 tied，mean delta = -0.00833，95% CI = [-0.03580, +0.01781]，family agreement = 3/6。Campaign 被接受并关闭，但正式规则结论是 DIAGNOSTIC_ONLY，没有晋升为 proxy candidate，也没有授权 runtime policy。正确含义是“没有取得独立验证支持”，不是统计上证明规则无效。

**H2 四项测量。**

| 子项 | 结果 | 能支持的结论 |
|---|---|---|
| H2-M1：真实 isolated prefill cost 非线性 | PASS | 固定测量条件下，Prefill cost 随 prefix length 呈现可测的非线性 |
| H2-M2：partial-prefix APC 语义 | PASS | 保留前导、淘汰尾部时，后续只需重算未缓存后缀 |
| H2-M3：淘汰位置改变实际结果 | PASS，12/12 cells | 冻结 probe 中淘汰位置会改变观测到的结果 |
| H2-M4：额外 block-level headroom | FAIL，supporting cells = 0，pairwise headroom = 0 tokens | 冻结 single-prefix comparator 中没有观察到额外 block-level headroom |

H2-M4 的 FAIL 只适用于冻结的 single-prefix controlled comparator，不能外推为所有多 Entry / shared-block 方案都没有空间。反过来，M1 的非线性 prefill cost 也不能单独证明 cost-aware 策略有 runtime 收益。B1 因四项未全部通过而保持 LOCKED。

**另一个独立的 Phase 2A M6 profiling campaign。** 这是 54-run、18 scenarios、60 forced-release decisions 的独立记录，不是 H1 的 126-run campaign。它在 planned-return-weighted prefill proxy 上得到 GAP-PROVISIONAL，四个特征达到 PROXY_SUPPORTED 阈值；但 10/174 个 planned/observed strict-horizon labels 发生变化，且 runtime_replicated=false。因此它支持继续研究 proxy signals，不支持称这些信号为 runtime-stable predictor，更不等于直接的 Native recomputation 或 serving-impact 证据。

### 1.3 Phase 2B / Phase 2C：逻辑共享标签不能代替 Native 内容身份

Phase 2B 修复了 bounded Native smoke 的输入身份与运行时证据路径，验证了真实 same-content APC reuse 和 Native request overlap；但 TTL-history 仍为 NOT_OBSERVABLE。

Phase 2C 对历史 H1 Archive 的只读审计进一步发现：
- 重建 1,068 条 request rows；
- 495 条 turn requests 具有 eligible reusable prefix，其中 288 full hits（58.18%）、48 partial hits（9.70%）、159 misses（32.12%）；
- 另有 408 个 first eligible-turn predecessors 被正确分类为 `NO_REUSE_ELIGIBLE_PREFIX`，不是 miss；
- 同一 program 的 native hash chain 保持一致；
- 不同 program 的 first native hash chain 相等次数为 0/771；
- H1 compiler 的 ownership_group / logical prefix 标签并没有形成跨 program 的相同 submitted token content。

因此必须分开看待：
- **Replay fidelity：** 冻结释放集合与顺序可以被重放；
- **Content-topology fidelity：** H1 原先期望的跨 program Native 内容共享没有实际发生。

前者通过不能替代后者。这个发现限制了 H1 对 shared-prefix Native cache geometry 的解释，但没有追溯性改写 H1 的原始 verdict。

### 1.4 Phase 2D：真实 shared-protected fixture 中存在局部 victim-selection headroom

Phase 2D 的证据链为：
- E1：历史压力决策只有一个 legal protected candidate，故无法比较多候选；
- E2：新 fixture 中两个受保护逻辑 Entry 在同一决策共享 8 个真实 Native blocks，每个候选 12 blocks、各有 4 blocks marginal relief；
- E3：四个有效配对观察到 64-token 的绝对差异，且差异方向随预设 future-return target 反转；
- E4：两个 bounded arms 都观察到真实 Native scheduler-to-completion interval 的正 overlap。

**证明了：** 在特定 shared-prefix / shared-protected fixture 中，不同逻辑 Entry release choice 可以改变后续 Native 计算工作，存在局部选择 headroom。

**没有证明：**
- 更好的选择可以由决策时可见信息在线预测；
- 该效应能推广到一般 workload；
- Cost-Aware 策略已实现或提高了 end-to-end performance；
- 64-token 的绝对数值可与 Protocol v4 的 E-C 直接合并。该报告按 N-C 计算观测值。

这与 H2-M4 不矛盾：两者测试的是不同的 candidate geometry。H2-M4 是冻结 single-prefix comparator；Phase 2D 则显式构造了同时受保护、共享物理块的多个 Entry。

### 1.5 Phase 2E：Continuum-style Entry Release 在受控负载下减少重算，但未转化为 TTFT 改善

Phase 2E 对 Native LRU 与冻结 Continuum baseline 做了 36 个预定义 scenario draws、每臂每场景两个 runtime repeats，共 144 个成功 runs。统计单位是 scenario draw，repeat 先聚合。

- Continuum − Native LRU 的 mean paired aggregate recomputation delta：**−192 tokens / scenario**；
- 36 draws 中 29 个为负、7 个为零、0 个为正；
- family mechanism 在 132/144 runs realized，12/144 未 realized 并保留为 missingness / mechanism limitation；
- Mean TTFT：Native LRU 0.729370 s，Continuum 0.729779 s；
- Queue delay 主导该 workload 的 queued-to-first-token interval，重算 Token 尾部变化没有形成相当的 TTFT-tail 改善。

**证明了：** 在这个冻结的 synthetic prefill-focused workload 中，Continuum baseline 相对 Native LRU 保留了更多可复用 prefix work，减少了场景级重算 Token。

**没有证明：** 对应的 TTFT 改善、逐 eviction 因果关系、production workload generality、多 token decode 生命周期收益，或 Cost-Aware 策略有效性。

### 1.6 W1-B 与 Phase 2G：早期正向 smoke、后续 bounded 结果和 Gate 2 诊断必须分开

**W1-B bounded smoke（12 runs，4 groups，每臂每组一次）。** A1−A0 的四个 group deltas 为 -1056、0、-1616、-1232 tokens，描述性合计 -3904；A2−A0 每组为 0。该结果是少量选定 group 的 bounded smoke，不是独立总体性能结论，也未建立 content-level eviction causality。

**PR #82 bounded Native evaluation（54 runs，9 groups，每 cell 一次）。** 主要指标为 Σ(E-C)，delta = policy − A0：

| Arm | Better | Worse | Tied | Mean delta |
|---|---:|---:|---:|---:|
| A1 | 0 | 1 | 8 | +412.44 |
| A2 | 0 | 3 | 6 | +321.78 |

没有 group 显示 A1 或 A2 的重算 Token 改善。M1 接受的是这九个预定义 group 上的 bounded exploratory negative finding；单次执行不能证明普遍劣势、run-to-run stability 或 content-level causality。

**A1 Gate 2 的 36-draw / 144-run 历史记录。** 早期报告中的 12 BETTER / 1 WORSE / 22 TIED / 1 INCONCLUSIVE 是将 144 runs 的 repeats 聚合后得到的 36 个 scenario-draw outcomes，不是 144 个独立结果；mean delta -24.23。但原 evaluator 把 N-C 当作 recomputation，且只从 Native observation 构造样本、可能静默遗漏缺失请求。指标缺陷已被源码审查证明，修正后的 evaluator 实现已接受；但在 M1 closeout 环境中，原始 144-run archive 不可用，未对同一 archive 完成修正后的数值重算。因此这组数值必须标为 **PROVISIONAL**，不能作为已验证的 A1 token benefit。

**A2 Gate 2 v3（独立的 144-run campaign）。** 36 draws 的 token result 为 0 BETTER / 0 WORSE / 36 TIED、mean delta 0；但 72/72 repeat-pair 的 selection evidence 均为 SELECTION_NOT_OBSERVABLE，proved-equal 和 proved-divergent 均为 0。因此该 campaign 对 A2 effectiveness 的正式判断是 INCONCLUSIVE，不是 A2 与 LRU 等价。

**A2 bounded-value evaluation（又一轮独立 144-run campaign）。** 36 draws 得到 0 BETTER / 3 WORSE / 33 TIED，mean delta +26.2222 tokens（A2−A0，正值不利于 A2）。三项 F4 arm-level deltas 为 +560、+96、+288。后续 offline correction 在 122 个 forced-release windows 中只得到 40 个完整 actual A0/A2 comparison，82 个仍不可配对或身份不完整；两次 f4-draw-04 的 selection divergence 已确认，但不能把整个 +560-token arm delta 全部归因于该决策，draw-05/06 仍无已确认的 selection divergence。结论为 INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN。

上述 A1 Gate 2、A2 Gate 2 v3、A2 bounded-value 和 PR #82 的 54-run 结果是不同 campaign，不能合并成一个 288-run 或 342-run 总体。

### 1.7 Phase 2G / Phase 2H：A1 的 q 与 A2 的 cost signal 未展示独立的下游收益

**A1 Entry Release：**
- Phase 2G 54-run archive 中，campaign 留在 COLD_START，run 内默认 TTL 恒定，使 q 与 deadline 保持同序；每 run 约 10 条历史样本，低于 100 的 threshold，history 不跨 run 累积。已有 W1-A warm-start 路径受 campaign-kind gate 限制；即使注入 443 条 W1-A history，也只会到 GLOBAL，因为 v10 的 tool label 在 W1-A 中没有匹配样本，不能到 TOOL_SPECIFIC。
- A1 offline replay 对 29/29 个观测 first picks 复现；改变 lambda 只影响 g05 的两个选择。只有 g05-moderate 出现 +3,712-token Native recomputation delta，且仅一个 repeat，不能据此判定稳定退化或建立完整 content-level causality。
- Phase 2H 的六个 A1 multi-candidate decisions 都有正 q span，但 A1 在六次中均可由 Sufficient-first + Minimum Overshoot 复现。唯一偏离 A0 的 HR02 round-55 决策使后续 recomputation 增加 6,320 tokens。该 smoke 只有两个 scenarios、每臂每场景一个 observation，属于描述性机制证据。
- Phase 3 中 A1 与 A0 的选择在 127 个 forced Entry Release decisions 中没有形成有效差异；但 120/127 是单候选决策，不能把零效果直接解释成 A1 在充分竞争下与 A0 等价。

**A2 Block Victim Selection：**
- PR #82 54-run archive 中，601 个 Block decisions 有 167 个 fallback、434 个 cost-known greedy；434 次 greedy 均未改变 Rank-LRU selected set。368 个无 marginal-cost signal；66 个有信号但 greedy 集合仍相同。对 66 个超预算案例不能声称 exact search 证明 LRU 最优。
- Phase 2H 中 54 个 effective incremental-greedy decisions 均匹配 Native LRU；另有 384 个 allocation decisions 因 content-unverified fallback 到 Native LRU。
- Phase 3 中 53/127 个 decisions 使用 cost-known incremental greedy，74/127 fallback；127 个最终 victim sequences 均与 Native LRU 相同。

跨 campaign 的共同观察是：**已测试的 A2 版本没有展示可复现的正向 recomputation gain**。原因包括 fallback、缺少可区分的 marginal cost、Greedy 不改变集合、以及 physical identity attribution 不完整；这不是对所有可能 Block Cost-Aware 算法的普遍否定。

### 1.8 Phase 2I 与 Phase 3：A3 运行路径存在，但真实竞争决策很少且排序与 deadline 对齐

Phase 2I 是一个 180-request HR02 CUDA Native preflight，不是 A3 value campaign。Gate C 在两个 content-verified、non-fallback multi-candidate A3 decisions 上通过；Gate O 因 756 个 physical evictions 无法唯一归属到三个 A3 Entry decisions 而失败，故 FAIL_CLOSED。

Phase 3 Option F 完成 30 Noise + 240 Main runs。Protocol v4 的 primary statistical unit 是 Workload Group，18 个 complete Groups 进入主配对总体：

| Primary arm effect | Groups | Mean delta vs A0 |
|---|---:|---:|
| A1 − A0 | 18 | 0.0 tokens |
| A2 − A0 | 18 | 0.0 tokens |
| A3 − A0 | 18 | 0.0 tokens |
| E0 − A0 | 18 | 0.0 tokens |
| N0 − A0 | 18 | +1,918.22 tokens |

A0−N0 的 H3-0 是 20 Groups / 38 cells，mean = -3,123.2 tokens；H3-R 是 9 RESPONSIVE Groups / 16 cells，mean = -6,435.56 tokens。这两个是不同注册总体，不应与 18-Group primary 混为一谈。

**Phase 3 的关键解释不是“压力不足”。** Exposure audit 在 39 个 cells 中记录了每个 release-enabled arm 127 个 forced-release decision events；这些事件按 cell 聚类，不能当作 127 个独立样本。
- 对 Entry-ordering treatment arms A1/A3/E0，120/127 个事件只有一个 legal Entry candidate，只有 7/127（5.5%）具有两个候选。A0 是冻结的 Entry Release 参照；A2 沿用 A0 的 Entry Release，所测试的增量决策位于物理 Block-victim 层，而不是另一种 Entry ordering。
- A3 的七次双候选决策中，Cost 与 Deadline 排名完全一致（Spearman 1.0），选择同一 Entry；A3 与 A1 在 127 个配对事件中选择同一 Entry。
- A2 的 127 个 Block-victim decision events 中，53 次使用 cost-known incremental greedy，74 次因 `content_unverified` fallback；最终 127 次 victim sequence 均与 Native LRU 相同。

因此该 campaign 有充分的资源压力与物理执行记录，却没有充分的 algorithm-decision exposure。策略被调用 127 次，不等于 cost model 获得 127 次真实的候选竞争机会；7/127 是描述性暴露计数，不是独立样本比例估计。

**Replay-order deviation 必须继续保留。** 实际 Native enqueue order 与 frozen order 完全一致的只有 8/40 cells；32/40 cells 中六臂共享同一个、但不同于 frozen 的实际顺序；没有 cell 出现 cross-arm-different order。只读 actual-order audit 对 5,760 个 request-arm observations 独立重建 E，全部 determinate，E 值 0 个变化，固定总体的注册效果完全复现。该结果支持在观察到的共同顺序偏差下解释配对效果，但不能把历史 frozen-order conformance FAIL 追认为 PASS。最终确认状态仍待 M1/M4 adjudication。

### 1.9 Stage 0 / P2 / Phase 4：当前 cohort 的损失空间与预测目标存在边界

**Stage 0 loss-only oracle：**
- 18 Primary Groups / 36 cells 完整；
- 七次真实 competitive decisions 中，A0 在 loss-only oracle 下均为最优；
- avoidable-prefix-loss upper bound 在当前 cohort 为 0 tokens；
- 该 oracle 不是 Native cache-state replay，也不模拟换链释放容量产生的收益，capacity benefit 为 NOT_EVALUATED。

**P2 future prefix-demand predictor：**
- 候选只有在 victim hashes 被证明为同一 program 历史链的连续后缀时才进入评估；18 个候选因此被 `EXCLUDED`（REAL 4、CONSTRUCTED_HISTORICAL 14），包括两个 REAL decisions（g10-c1、g10-c2），不以默认推断补齐，也不计作零收益；
- 七次真实竞争决策中只有五次通过 contiguous victim-identity eligibility；
- P2-A/B 在这五次 REAL decisions 全部 flip，但 0 次 positive-gain flip，REAL MAE 87.4 blocks；
- P2-C 在 REAL 上 0 flip、0 gain，MAE 346.5 blocks；
- 106 个 CONSTRUCTED_HISTORICAL scenarios 必须与 REAL 分开；构造场景的 oracle opportunity 不等于真实负载收益；
- 独立单决策反事实增量不是联合部署策略效果。

**Phase 4 Session Continuation：**
- 40 Sessions、480 C1 request rows；event stream 没有独立 `session_id`，且 `program_id == session instance_id`，没有 program 对应多个 sessions，因此 Session Continuation 与 Program Continuation 在该 Archive 中观测等价。
- 采用 replay-window right-censoring：5s / 15s / 60s / 300s 窗口的 censored share 分别为 4.8% / 8.1% / 12.1% / 54.2%；被删失窗口不作为负例，也不进入普通二分类指标。
- 在 60s 窗口，`TOOL_GAP` program-level proxy 有 422 个有效样本，Brier = 0.0788、AUC = 0.594，属于弱区分信号，不是 Session Continuation 证据。15s 窗口仅 12 个正例，估计不稳定；300s 窗口 220 个有效样本中只有 4 个负例，不应作为稳定结果。
- 报告只能提供 Program Continuation proxy，不能宣称识别或验证了 Session Continuation，也没有验证 continuation-cost 组合模型。

---

## 2. 研究假设复盘：哪些成立、哪些失败、失败原因是什么？

这里的“失败”指未达到冻结假设门槛、未观测到正向效果或当前数据不可识别；不自动等于理论上不可能。

| 假设 / 研究命题 | 最终状态 | 直接证据 | 失败 / 限制原因与边界 |
|---|---|---|---|
| H1-R1：reverse-deadline 规则可改善选择 | **未获独立验证支持；DIAGNOSTIC_ONLY** | 29 paired draws；13/14/2；mean -0.00833；CI 跨 0 | 样本低于 30 门槛，均值非正，better 不多于 worse，family agreement 仅 3/6；不是统计学证明无效 |
| H2-M1：isolated prefill cost 非线性 | **PASS** | 冻结测量、重复与 bootstrap | 只证明 cost curve，不证明在线策略收益 |
| H2-M2：partial-prefix APC 语义 | **PASS** | exact probes 与重复 | 只证明 Native APC 的前缀语义 |
| H2-M3：淘汰位置会改变观测结果 | **PASS** | 12/12 registered cells | 受控 comparator 结果，不等于 Cost-Aware policy benefit |
| H2-M4：冻结 single-prefix comparator 存在额外 block-level headroom | **FAIL（适用范围受限）** | 0 supporting cells、0 pairwise headroom | 该 comparator 未观察到 headroom；不能外推到 Phase 2D 的多 Entry shared-protected geometry |
| Phase 2A M6 proxy signals 能稳定预测 runtime loss | **仅 PROXY_SUPPORTED** | 4 个特征通过 planned-proxy thresholds | planned/observed label 有 10/174 flips；runtime_replicated=false |
| H1 workload 的跨 program logical sharing 代表 Native 内容共享 | **被 Phase 2C 否定** | different-program first hash chain 0/771 相等 | ownership_group / program labels 未物化成相同 submitted token content |
| Shared-protected 多 Entry 状态可存在选择 headroom | **在 Phase 2D fixture 中支持** | 2 Entry 共享 8 Native blocks；E3 四对有 64-token N-C 差异 | 局部 fixture；未来返回目标受控；在线可预测性与普遍性未证明 |
| Continuum-style Entry Release 可减少重算 prefix work | **在各自受控 cohort 中支持** | Phase 2E 是 36-draw synthetic scenario-level campaign；Phase 3 是 18-group Native campaign。两者 cohort 与 estimand 不同，分别观察到重算工作下降，不合并为 pooled effect | 不代表完整系统性能或 production generality |
| 减少重算 Token 会带来 TTFT 改善 | **未获支持** | Phase 2E mean TTFT 没有相应改善，queue delay 主导 | 该 workload 的 token-to-TTFT transfer 弱；不能外推为所有服务负载都无关系 |
| A1 的 q/λ 对简单规则有独立价值 | **未证明** | PR #82 无正向组；Phase 2H 六次选择均可由 Minimum Overshoot 复现；Phase 3 竞争机会稀少 | cold-start / history threshold 与 tool-label mismatch；q 与 deadline 同序或选择结果被更简单规则复现 |
| A2 的 Block cost-aware greedy 优于 Native LRU | **未证明；测试范围内没有正向收益** | PR #82 无正向组；Phase 2H 54/54 effective greedy 与 LRU 相同；Phase 3 127/127 victim sequence 相同 | fallback、缺少信号、Greedy 不改变集合；部分 exact / physical attribution 不可判定 |
| A3 suffix-cost ordering 优于 deadline-only E0 | **未证明** | Phase 3 仅 7 个双候选决策，Cost 与 Deadline 排序一致；A3/E0 无选择差异 | 竞争决策数量低，且信号排序同向；不能声称普遍等价 |
| Stage 0 的当前真实竞争决策存在正的 loss-only avoidable prefix loss | **当前 cohort 不支持** | 七次竞争决策中 A0 均为 loss-only oracle 最优；上界 0 | oracle 不模拟 capacity gain；capacity benefit NOT_EVALUATED |
| P2 能把未来 prefix-demand 预测转化为正向决策价值 | **当前 REAL cohort 不支持** | 5 个有效 REAL decisions 全部 flip（A/B）但 0 positive-gain flips；P2-C 不 flip | MAE / ranking accuracy 不等于 downstream gain；REAL 样本很少；构造样本不能替代真实 |
| Session Continuation 可由当前 Archive 独立学习 | **不可识别** | 无独立 `session_id`，program 与 session 一一对应；60s `TOOL_GAP` 仅提供弱 Program Continuation proxy（422 valid，Brier 0.0788，AUC 0.594） | right-censoring 已单独处理；数据结构缺少独立 session identity / switch events；不是模型算法失败 |

### 2.1 跨阶段看似矛盾的结果如何统一解释

1. **H2-M4 FAIL 与 Phase 2D HEADROOM_OBSERVED 不矛盾。** 两者的 candidate geometry 不同：single-prefix comparator 与 shared-protected multi-Entry fixture 不是同一个问题。
2. **W1-B A1 的 -3,904-token 描述性总和与 PR #82 / Phase 2H / Phase 3 不矛盾。** W1-B 只有四个选定 group、每 cell 一次；后续 campaign 有不同 workload、组数、算法定义和统计单位。早期正向 smoke 不应压过后续独立 campaign，也不能与其合并。
3. **Phase 2A proxy headroom 与 Phase 3 零增量不矛盾。** planned proxy 上存在损失异质性，不等于策略拥有可见、可区分、可正确排序的真实决策机会。
4. **Phase 2D 的局部 64-token 差异与 Stage 0 的 0-token loss-only upper bound 不矛盾。** 一个是特定 shared fixture 中的局部 Native prefill-work 对照；另一个是 Phase 3 当前 cohort 的 A0-anchored loss-only oracle，且不计算 capacity gain。
5. **A2 的 0-token Gate 2 v3 与第二轮 A2 的 +26.22-token mean 不矛盾。** 它们是两个独立 144-run campaigns；前者 selection evidence 不可观测，后者观察到 request-level arm differences 但 baseline / physical attribution 仍不完整。
6. **Phase 3 actual-order effects 复现不等于 execution conformance 通过。** 前者说明固定总体效果在共同实际顺序下未变化；后者仍是冻结执行顺序偏差，不能被追认。

---

## 3. 方法贡献提炼：真正获得了哪些研究价值？

下列贡献分为系统工程、测量方法、实证机制和负面发现。它们是本项目证据支持的贡献候选，不自动构成相对于既有文献的“首创”声明；文献新颖性仍需单独做 Related Work 对照。

### 3.1 系统工程贡献：在 Native vLLM 所有权边界内实现项目侧策略接入

Phase 1A/1B 将逻辑 retention / Entry Release 与物理 Block victim selection 分层：项目侧策略给出合法选择，Native vLLM 继续拥有 BlockPool、ref count、free queue、APC hash cleanup、分配和物理 eviction bookkeeping。

**价值：** 为在真实 vLLM 运行时研究 cache-management policy 提供了受限、可审计的集成边界。  
**性质：** 已验证的系统集成与工程贡献；不是完整 Continuum reproduction，也不是性能提升结论。

### 3.2 测量方法贡献：把 Native KV Cache 结果拆成 N/E/C 与独立证据链

通过独立推导 E，而不是从 C 补齐 E，明确区分：
- logical Entry Release；
- physical Block victim selection；
- Native hashed eviction；
- APC prefix eligibility / residency / hit state；
- request-level recomputed tokens；
- serving metrics。

并用 R=E-C、W=N-C、S=N-E 和 W=R+S 固定指标语义。证据缺失时保留 NOT_OBSERVABLE / INDETERMINATE，而不是把缺失当作相等、零收益或 PASS。

P2 进一步要求 victim hashes 必须可证明为同一 program 历史链的连续后缀才纳入候选；18 个候选（REAL 4、CONSTRUCTED 14）被 fail-closed 排除，包括两个 REAL decisions。Phase 4 则明确审计 session identity，并将 replay-window 末端 right-censored observations 排除出普通二分类负例，避免把不可识别目标或观察窗口不足误作模型标签。

**价值：** 避免把逻辑释放、物理淘汰、cache miss 和重算量混成同一事件；使跨臂比较的指标、统计总体和证据强度可以独立审查。  
**性质：** 方法学 / evaluator 贡献。

### 3.3 工作负载保真贡献：逻辑 ownership 不等于真实 Native content sharing

Phase 2B/2C 在审计的历史 H1 workload 中显示，workload compiler 的逻辑 `ownership_group` 不能替代真实 submitted token identity 与 Native hash chain。该结果支持一个一般实验原则，但不构成对所有 workload 的普遍证明。必须分别审计 content overlap potential、reuse eligibility、physical residency 和 realized APC。

**价值：** 给出了一套防止“逻辑上共享、运行时并未共享”误判的实验设计与审计方法。  
**性质：** 工作负载构造与证据识别方法贡献；同时是对早期 H1 workload 解释范围的重要修正。

### 3.4 实验设计贡献：资源压力暴露与算法决策暴露是两个不同维度

Phase 3 exposure audit 在 39 个 cells 中记录每个 release-enabled arm 127 个 decision events；对 A1/A3/E0 的 Entry-ordering treatment，只有 7/127 个事件具有双候选竞争（5.5%），其余 120 个只有一个 legal Entry candidate。A2 沿用 A0 的 Entry Release，其增量处理位于 Block-victim 层。上述计数按 cell 聚类，是描述性 exposure 统计，不是 127 个独立样本。这说明大量压力事件、物理 Block eviction 或策略函数调用，不能代替真正的算法决策机会。

建议后续所有策略实验明确报告：
- decision count；
- legal candidate count distribution；
- multi-candidate / multi-scored opportunity count；
- cost signal 有效的决策数；
- 与简单 comparator 的 selection divergence；
- divergence 后的 downstream outcome coverage。

**价值：** 将“算法是否有机会作出不同决策”作为独立的实验设计和解释维度，避免把无差异结果误读为算法在充分竞争条件下等价。  
**性质：** 实验方法与负结果解释贡献。

### 3.5 机制认识贡献：局部 headroom 不等于在线可预测性

Phase 2D 证明特定 shared-protected fixture 中可以存在 victim-selection headroom；Phase 3、Stage 0 与 P2 又显示，当前 cohort 的真实竞争决策稀少，A0 在 loss-only oracle 下已是七次竞争决策的最优选择，已测预测器也未产生正向 REAL gain。

**价值：** 将研究问题从“理论上是否有更好的 victim”推进到三个必须分别回答的问题：
1. 是否存在可利用的局部选择空间？
2. 决策时可见信号能否识别更好的候选？
3. 该选择差异能否在 Native 运行中转化为更低的 E-C？

**性质：** 跨阶段机制综合；不是已验证的在线 Cost-Aware 算法。

### 3.6 实证认识贡献：重算 Token 改善不自动等于服务性能改善

Phase 2E 观察到场景级 recomputation 下降，但 TTFT 没有相应改善，queue delay 主导该工作负载的 queued-to-first-token interval。

**价值：** 在研究 KV Cache policy 时，应同时报告 cache-work 指标和 serving-level 指标，并避免从 token savings 直接推导 TTFT / throughput gains。  
**性质：** 有边界的负向实证发现。

### 3.7 负面结果贡献：已测试 Cost-Aware 变体没有显示增量收益，且失败机制可区分

以下是不同 campaign 中反复出现的机制模式；各 campaign 的总体、统计单位、estimand 和策略定义不同，本节不合并样本量、效应量或显著性。

- A1：q / deadline 在冷启动数据中同序；History-Rich smoke 中 q 虽非退化，但选择可由 Minimum Overshoot 复现；唯一偏离 A0 的结果增加了重算量。
- A2：多轮中出现 fallback、无差异 cost signal 或 cost-known greedy 仍不改变 Native-LRU victim set；部分 campaign 的选择或物理归因不可观测。
- A3：Phase 3 真实多候选机会只有七次，Cost 与 Deadline 排序一致，未产生选择差异。
- P2：预测精度 / ranking 与正向单决策收益不一致；REAL 中没有正 gain flip。

**价值：** 把“没有收益”进一步分解为 candidate geometry 不足、信号缺少区分度、简单 comparator 已复现选择、物理身份 / 因果证据不足、预测精度没有转化为决策收益等不同机制。  
**性质：** 当前冻结 cohort 与已测实现范围内的负面结果；不构成对所有 Cost-Aware 目标函数或未来实现的普遍否定。

---

## 4. 最终研究主张矩阵

| 拟提出的主张 | 当前证据等级 | 推荐表述 |
|---|---|---|
| 项目侧 Continuum-style lifecycle / retention 能在 Native vLLM 上运行 | **直接支持（限定 runtime/profile）** | “实现并验证了保留 Native cache ownership 的项目侧适配” |
| Continuum-style Entry Release 在受控 cohort 中减少 eligible-prefix recomputation | **直接支持（各自冻结 cohort 内）** | “Phase 2E 与 Phase 3 的受控结果均显示重算工作下降；两 campaign 不合并” |
| shared-protected 多 Entry 存在局部选择 headroom | **直接支持（Phase 2D fixture）** | “在特定 shared-prefix fixture 中观察到局部 headroom；不声称在线可预测” |
| 当前 Cost-Aware A1/A2/A3 优于 A0 | **不支持** | 不得宣称已证明 Cost-Aware policy improvement |
| 当前测试证明所有 Cost-Aware 方法都无效 | **不支持** | 只能说“已测变体在已测 cohort 中未展示增量收益” |
| A1/A2/A3 与简单基线普遍等价 | **不支持** | 只能报告已测 cohort 的选择与指标结果，并列出 exposure / observability 限制 |
| 重算 Token 下降带来 TTFT / throughput 提升 | **未证明** | 需要独立 serving-level estimand 与测量 |
| 单个物理 eviction 导致某请求的特定 recomputation | **多数历史 campaign 未建立** | 只有完整 Block identity → later request/APC → E/C 链路才能作此归因 |
| Dynamic TTL 优于 Static TTL | **未评估** | Phase 3 没有 Static-TTL arm |
| Continuum scheduler adapter 有性能收益 | **未评估** | Phase 3 所有 arms 使用 Native scheduler |
| Session Continuation 可由当前 Archive 学习 | **不可识别** | 当前只支持 Program Continuation proxy |
| 结果可推广到生产 workload / 任意 vLLM 部署 | **未证明** | 当前多为 controlled / synthetic / bounded cohort |

---

## 5. 适合最终论文 / 项目报告的稳健叙事

当前证据更适合形成如下研究叙事：

> 本项目在 vLLM Native KV Cache 所有权边界内实现并验证了项目侧 Continuum-style cache-management 适配，建立了独立的 N/E/C 评测与证据审计路径。受控实验表明，Entry Release 相较不执行强制 Entry Release 的 Native baseline 能减少 eligible-prefix recomputation；在特定 shared-protected fixture 中，也观察到逻辑 victim-selection 的局部 headroom。
>
> 但进一步的 Cost-Aware A1/A2/A3 实验没有展示相对 A0 的增量重算收益。跨阶段审计发现，这并非单一的“成本模型不准确”：部分实验缺乏真实多候选竞争，部分 cost signal 与简单 comparator 排序一致，A2 存在 content-evidence fallback，部分历史 campaign 的选择或物理归因不可观测；即使离线预测精度较好，也未转化为正向 REAL decision gain。与此同时，重算 Token 的下降也未自动转化为 TTFT 改善。
>
> 因此，项目目前最扎实的研究认识是：**KV Cache cost-aware eviction 的有效性不仅取决于成本估计本身，还取决于真实候选竞争是否存在、决策时信号能否改变选择，以及选择差异能否沿 Native eviction / APC / recomputation 证据链转化为下游收益。**

该叙事是对当前证据的综合，不等于已经完成论文新颖性审查，也不替代 Phase 3 最终 M1/M4 adjudication。

---

## 6. 明确保留的未解决边界

1. Phase 3 frozen enqueue-order conformance deviation 仍保留；actual-order recovery 不追认原 Gate PASS。
2. Phase 3 最终 M1 adjudication 尚未完成。
3. A1 Gate 2 历史 144-run 数值仍为 PROVISIONAL，修正 evaluator 未在同一原始 Archive 上完成最终复算。
4. 多个历史 campaign 的 physical victim → downstream recomputation per-event causality 仍不完整。
5. Phase 2D 的 N-C 局部差异不与 Protocol v4 E-C 绝对值混用。
6. Phase 3 没有 Static-TTL arm，也没有 scheduler treatment。
7. 未完成 Native / Continuum Official / Continuum Adapted / Cost-Aware 的完整四系统对照；不声称完整系统排名。
8. 当前 controlled cohort 不等于生产 workload 分布；不声称普遍泛化。
9. Phase 4 Session Continuation 因身份字段缺失而不可识别。
10. 本次总结不授权新的 GPU campaign、Native smoke、算法实现或 Protocol v5。

---

## 7. 主要证据入口

### 早期假设与机制
- [Phase 2A H1/H2 closeout verdict](../phase2a-h1-h2-closeout-verdict-record.md)
- [Phase 2A M6 formal profiling](../phase2a-m6-formal-results.md)
- [Phase 2B fidelity repair](../phase2b-m6-final-review-submission.md)
- [Phase 2C workload content / APC reuse audit](../phase2c-m6-workload-reuse-audit.md)
- [Phase 2D victim-selection headroom](../phase2d-m6-headroom-investigation.md)
- [Phase 2E Native LRU / Continuum measured campaign](../phase2e-m6-measured-campaign-report.md)

### Cost-Aware 实验
- [W1-B bounded Native review](../continuum-native-cost-aware-bounded-results.md)
- [Phase 2G A1 offline review](../experiments/phase2g-a1/README.md)
- [Phase 2G A1 Gate 2 metric review](../experiments/phase2g-gate2-review/README.md)
- [Phase 2G comprehensive judgment](../experiments/phase2g-costaware-comprehensive-judgment.md)
- [Phase 2G A2 Gate 2 v3](../experiments/phase2g-a2-gate2-v3/final-report.md)
- [Phase 2G A2 bounded-value evaluation](../experiments/phase2g-a2-bounded-value-evaluation.md)
- [Phase 2H History-Rich Native smoke](../experiments/phase2h-history-rich-native-smoke-results.md)
- [Phase 2I A3 CUDA Native preflight](../experiments/phase2i-a3-target-cuda-native-preflight-plan.md)

### Phase 3 / Phase 4
- [Protocol v4](../phase3-final-evaluation-protocol-v4.md)
- [Phase 3 Option F final results](../experiments/phase3-option-f-final-results.md)
- [Phase 3 algorithm exposure audit](../experiments/phase3-algorithm-exposure-audit.md)
- [Phase 3 actual-order audit](../experiments/phase3-actual-order-audit.md)
- [Stage 0 loss oracle](../experiments/phase3-stage0-oracle-data/stage0-report.md)
- [P2 depth predictor study](../experiments/phase3-p2-depth-data/p2-depth-report.md)
- [Phase 4 Session Continuation feasibility](../experiments/phase4-session-continuation-data/phase4-session-continuation-report.md)

---

**M1 synthesis status:** 本文完成了跨阶段结果、假设状态与方法贡献的第一轮集中归纳。后续如 M1/M4 对 Phase 3 作出最终裁定，只更新对应裁定与主张矩阵，不重写历史实验结果。