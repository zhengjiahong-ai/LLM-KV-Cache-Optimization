# Cost-Aware 算法演进与公开工作负载的证据

## 结论

公开轨迹补足了真实 Agent 请求的逻辑前缀几何，并让事后重算损失能在明确的反事实下独立计算。实证支持三点。共享祖先可以属于多条链，最浅受害者往往支配静态后缀损失，短窗口的实际重算还取决于谁先返回及缺块何时被回填。最后一点说明仅靠当前长度或 victim 数量无法覆盖全部机制。

在本研究的两块预算、固定槽序与候选集合内，两 Program 都返回的 12 槽竞争里，相对浅层并列的 logical LRU 有平均 6,280 tokens 的理论空间，改用深层并列剩 1,286。当前几何穷举代理最接近 Oracle，该窗口平均 regret 为 0。只看第一槽时，几何代理仍平均损失 4,556 或 4,164 tokens，取决于第一个返回者。这为 A2 的几何项和 A3 的后缀项提供条件性依据。Native LRU、A1、A2、A3 和 DVA-ER 依赖的真实 rank、deadline、profile 或 armed follow-up 缺失，全部标为 **NOT_EVALUABLE**。离线结果不支持在这五个实现之间给出优劣排序。[成本几何、场景及 Oracle 定义](Public-Workload-Cost-Geometry-and-Oracle.md)

历史裁定以当时独立工作负载、合法候选、可观察性与指标为边界。下文的「新解释」限于把几何、时间、选择、物理执行和后续需求拆开。历史数值不与 Nebius 合并。[R1 Evidence Ledger](../../research-consolidation/r1-experiment-evidence-ledger.md) · [R1.3 M4 复核](../../research-consolidation/research-results-and-contributions.md)

## 四代机制分别得到什么证据

| 方法与决策层 | 数据支持 | 对比 Oracle 的边界 |
| --- | --- | --- |
| **A1，Entry Release** | 不同独占尾部大小确实存在，同时满足同一两块需求的选项可以释放之后造成不同量级的损失。工具交替和后续 Turn 很常见。 | 无真实 deadline、TTL、压力目标或计时，无法检验 `q` 比 deadline 增加多少价值，也无法估计充分性阶梯的独立增益。合成 Entry 对均可满足需求，故没有跨阶梯对照。 |
| **A2，Block Victim Selection** | 多链同祖先、同内容的共享有直接重建证据。单链最浅缺口支配联合后缀。共享祖先回填会改变未来损失，单位权重静态和实际时间序列分别计入。 | 几何 Greedy 与 Exact 是不同参照。静态几何在双链均返回窗口表现更好，短窗口的返回不对称仍留下 regret。真实权重、候选集、Native rank 和退化路径不可观测。 |
| **A3，Suffix-aware Entry Release** | 同一反事实动作预算下，绝对后缀与 `S/m` 都有变化，两种代理有时换选却不降低损失。真实返回前缀达到深度时，后缀可能成为大额重算。 | `q·prefill·S/m` 缺前两项的有效决策时输入。观测到比例信号不代表 Deadline 或 A1 的次序必然逆转，见 [乘子阈值汇总](evidence-results/oracle_summary.csv)。 |
| **DVA-ER，Downstream-victim-aware Entry Release** | 同一次释放中的实际 victim 身份及其后续可达性是合理目标。共享缺口可能在先到请求后回填，固定两块的 count 本身无法估计深度损失。 | 必须先证明 Tier 1/2 队列预测与物理受害块一致，再检验 armed follow-up 与未来重算的关联。当前结果没有检验 `H=60s`、A0 tie-break 或 DVA-ER 的实测收益。 |

A1 的 `q` 是 deadline 的单调变换，独立分歧还需要新增可回收量等其他条件。A3 移到由 victim 决定的后缀位置，减少只看 Entry 总量的盲点。DVA-ER 用真实队列和可观察 follow-up 预测损失，方向值得验证。其现实现按符合 follow-up 条件的 victim block 数计分，离线 Oracle 则按未来请求的连续命中损失计量。同一 victim 数可能对应不同下游深度，后者应保留为评价标签。[A1/A2 联合设计](../../phase2-cost-aware-joint-design.md) · [A2 实现与范围](../../experiments/phase2g-a2-algorithm/README.md) · [A3 实现](../../experiments/phase2i-entry-marginal-cost-implementation.md) · [DVA-ER 实现](../../experiments/dva-er-v1-implementation.md)

## 历史记录与新解释

| 历史研究 | 保留原裁定 | 这次可以补充的解释 |
| --- | --- | --- |
| [Phase 2C Workload Content / APC](../../phase2c-m6-workload-reuse-audit.md) | 1,068 请求中 495 个具可复用前缀资格，跨 Program 首链相等 0/771。旧 logical ownership 标签未形成共享 Native 内容。 | Nebius 可直接重建共同 scaffold 和任务重试前缀。它展示新负载能提供预期内容拓扑。将这些链映射到 Native 仍需实际 token、hash 和驻留证明。 |
| [Phase 2D Victim Selection Headroom](../../phase2d-m6-headroom-investigation.md) | E1 单合法 Entry。E2 建立共享八个 Native 块的受控夹具。E3 四对有效且绝对差 64 tokens，预设返回目标反转时效果方向反转。旧指标 N−C 不与 Protocol v4 E−C 池化。 | 公开未来也显示返回顺序能改变有限窗口损失，支持独立检验多候选和返回。其效应量没有在同一条件复制。 |
| [Phase 2E Native LRU vs Continuum](../../phase2e-m4-measured-review.md) | 36 冻结 synthetic draws，Continuum − Native LRU 平均 −192 recompute tokens，未见相应 TTFT 改善。 | 较长真实前缀使保留具备动机。Oracle 没有 GPU 排队和 TTFT，也不估计端到端 Continuum delta。 |
| A1 H1-R1 与 Gate 2 | H1 为 DIAGNOSTIC_ONLY，29 个有效配对少于 30 门槛。Gate 2 的 12/1/22/1 与 −24.23 为 provisional，旧 evaluator 用 N−C 且缺 Native 观测的请求被跳过，同归档未复跑修正版。 | 可构造多种不同深度，但没有时钟证据给 TTL 分数校准，也无法纠正旧档的缺失值。 |
| [A2 Gate 2 v3](../../experiments/phase2g-a2-gate2-v3/final-report.md) | 36 个 draw token 结果均并列，72 个 repeat 级选择比较均不可观测。INCONCLUSIVE。 | Oracle 提供独立的反事实同输入对照。历史选择仍不可识别，不等于选择已证实相同。 |
| [A2 bounded evaluation](../../experiments/phase2g-a2-bounded-value-evaluation.md) | 独立的 144-run 批次，36 draws 为 0 better / 3 worse / 33 tied，均值 +26.22 tokens。选择配对与物理身份不全，INCONCLUSIVE。 | 当前几何可非退化，仍可能因短窗口或祖先回填失去排序优势。历史三次更差的原因不可由此归因。 |
| [PR #82](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/82) 与 [Phase 2G 综合判断](../../experiments/phase2g-costaware-comprehensive-judgment.md) | 54 runs、9 W1-C groups、每臂一次。A1 和 A2 零组更好，分别 +412.44 与 +321.78 tokens，是有界负结果。A2 有 434 cost-known 贪心记录，0 次改变独立 Rank-LRU set，另 167 回退。66 个有信号的 case 未证实 exact LRU 最优。 | 公开合成候选展示几何代理可以产生不同集合，历史失败也包括冷启动、信号和实际执行过滤。短跑每进程约十个 tool gap，100 的冷启动阈值不可达。不能从 Nebius 推断完整 A0 Tier-rank 或改判该批次。 |
| [Phase 2H History-Rich Smoke](../../experiments/phase2h-history-rich-native-smoke-results.md) | 两场景六次运行。六个 A1 竞争决策具正 q span，但均与 sufficient-first/minimum overshoot 一致。唯一 A1/A0 分歧增加 6,320 tokens。A2 有效贪心与 Native LRU 一致。 | 有信号、选项改变、下游受益三个条件需分别审计。时间数据缺失使这批公开轨迹无法验证历史 q 路径。 |
| [Phase 2I A3 Native preflight](../../experiments/phase2i-a3-target-cuda-native-preflight-plan.md) | 实际 preflight 两个具内容证明的非回退竞争决定通过 Gate C。Gate O 对 756 次物理驱逐缺唯一归因，FAIL_CLOSED。 | `S/m` 变化让 A3 问题仍可研究。公开逻辑模拟不补物理归因，原 preflight 裁定保留。 |
| [Phase 3 暴露审计](../../experiments/phase3-algorithm-exposure-audit.md) 与 [Stage 0](../../experiments/phase3-stage0-oracle-data/stage0-report.md) | A3 的 127 压力决策中 120 单候选，7 个竞争决定中 Cost 与 Deadline 排序一致。A2 53 cost-known、74 回退，victim 顺序一致。18 组 A1/A2/A3/E0−A0 的 E−C 为零。历史 loss-only Oracle 对七个竞争决定未见增量 headroom。 | 公开场景通过固定深度、压力、返回序列扩大逻辑动作空间，得到非零损失跨度。解释为何需要测量候选暴露与可避免损失两个分母，也保留历史零效应。 |
| [Phase 3 Actual Native Order Audit](../../experiments/phase3-actual-order-audit.md) | 32/40 cells 偏离冻结顺序，各臂实顺序一致，5,760 项 E 不变，配对效应恢复。冻结顺序 FAIL/deviation 保留。 | 双链第一返回者改变短窗损失，固定顺序的控制需要明确。此处显式旋转顺序是研究敏感性，不能补写旧运行顺序。 |
| [Phase 4 Session Continuation](../../experiments/phase4-session-continuation-data/phase4-session-continuation-report.md) | 独立 session 与跳转事件缺失。经删失的 60 秒 Program TOOL_GAP proxy 只有弱区分，422 valid，Brier 0.0788、AUC 0.594。 | Nebius 可识别执行尝试中的 ordinal 后续，仍缺独立 session 与秒级时间。使用冻结的事后标签可复核内容需求，无法把 TOOL_GAP proxy 延伸为 calibrated online q。 |

阶段之间还存在成本模型层缺口。Phase 3 的 Stage 0 从真实 A0 决策锚定 loss-only 反事实，P2 对严格身份的五个 REAL case 未取得正收益。本轮从公开输入构造两个不同分母，出现可避免损失和短窗预测差距，只能指向待验证的条件。收益的物理必要条件仍包括竞争 Entry、不同 eligibility 或 victim set、可归因驱逐，以及窗口内可见的后续需求。

## 下一轮判断与论文主张

1. **继续 DVA-ER 的证据门槛研究。** 优先核对同一决策的完整 Native rank 与 refcount、保护所有者、预测 victim 与物理驱逐的一致性。用事后损失判定是否存在决策空间，再独立评估决策时的 armed follow-up 能否识别它。Oracle 结果只供事后评分。
2. **优先回放两种几何。** 一种是同 Issue 的深共享祖先加分叉后缀，覆盖祖先回填的记账及顺序敏感性。另一种是不同 Issue 的独立尾部竞争，保留固定公共头部，并配同深度、仅一条返回和两条均返回的等预算对照。额外保留已到目标 context 上限的样本计数。优先挑选本研究实际 Qwen2.5 投影可装入预算的案例。新 Replay/GPU 需要另行授权。
3. **Phase 5 D/E 的衔接。** D 中已有的身份、资格、候选竞争、队列与受害者证明应先通过。Nebius 几何可用于独立的 CPU/未来 Native 压力设计，不进入 SWE 正式、BFCL Derived 的采集、样本量、效应估计或 E 配对统计。真实持续压力、部署时序分布和 GPU 节省留待对应实验，当前研究的离线损失覆盖单次压力。
4. **论文证据。** Introduction 可用真实长程、多工具与大比例前缀的独立样本。Algorithm Design 可引用多链、祖先缺口与时间次序的条件性理论例子。Evaluation 可列完整归档描述与独立的反事实结果，明确配置及对照范围。应修正的假设是把更多长 Program、更多候选或不同的分数直接当成更多可避免重算。几类条件必须逐层实证。
