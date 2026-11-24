# DVA-ER Predictive Validity Gate

**建议裁定：CONDITIONAL GO。** 继续做决策时证据的 CPU 审计，Native 预测验证为 **NOT_EVALUABLE**。现有归档能定位真实释放、物理驱逐和请求级结果，但找不到一条把完整候选集的 DVA-ER 评分、可验证的实际 victim set 与后续重算归因连起来的记录。无法据此判断 v1 评分有效或无效。当前不具备进入 Native 策略效果实验的证据条件。

## Evidence Inventory

基线为 main `73effa9`。PR #135 `f369425` 和 PR #136 `b2cc282` 在审计时仍开放。公开轨迹保留为独立逻辑工作负载。下面的历史样本按来源和单位分别计数，Phase 4 和 Phase 3 使用同一 Archive。[PR #135](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/135) · [PR #136](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/136) · [R1 Evidence Ledger](../../research-consolidation/r1-experiment-evidence-ledger.md)

| 来源 | 可核对的证据及分母 | 对本门的缺口 |
| --- | --- | --- |
| Phase 2A–2C 受控审计及 Native pilot | Phase 2A 库内保留三个 curated raw exemplars。Phase 2C 的两次无压力与两次压力对照分别观测 384/384 和 384/256 个 eligible/cached tokens，后者记录同进程 release→eviction→return | 归档给出局部机制与时间层关联。没有 DVA-ER 评分、完整现时输入和候选逐块归因 |
| Phase 2D E2–E4 原始归档 | SHA-256 验证。14 个 canonical event runs，各一个真实多候选释放和记录的队列，164 条有 refcount 的 Native eviction，70 条 Native 请求观察（含压力请求）。排除 5 份前置 smoke event 文件，其中有空文件及复用 run ID。E3 的 8 次运行组成 4 个有效第一 Entry 释放对照，指定返回目标反转时 `N−C` 差为 ±64 tokens | 4 对是可信的受控逻辑释放对照，`N−C` 保留其历史口径。事件无显式决策绑定或 per-eviction decision ID，28 条 `FOLLOWUP_WAITING` 无 payload。没有 DVA-ER 评分，也没有每个 victim 对重算 token 的独立归因 |
| Phase 2G A2 Gate 2 v3 原始归档 | SHA-256 验证。144 个 event runs、108 个多候选真实释放和原生 free queue 记录、4,604 条含驱逐前 refcount 的 Native eviction、1,556 条 Native 请求观察。720 条 `FOLLOWUP_WAITING` 无 payload | 有候选 `block_ids`、`initially_reclaimable_block_ids` 及队列记录的 rank/tier/hash 标志。完整 BlockPool 与单一决策绑定缺失。回调无 decision ID。原裁定保留物理选择/归因缺口 |
| Phase 2H / 2I 证据报告 | 2H 的 18 个 Native 压力边界有真实竞争和后续部分命中。17 个观察到被选全前缀 Native key，HR02/A1 例外。2I 实际 CUDA preflight 的 Gate O 对 756 条物理驱逐未能唯一归属到 3 次 A3 决策 | 2H 是有界的稳定身份与时序关联，报告保留逐块内容因果缺口。2I 签入的 mock 事件不作 Native 样本。两个来源均缺 DVA-ER 决策变量 |
| Phase 3 Option F 签入审计产物 | 240 个 Main runs。A0/A1/A2/A3/E0 各 127 个真实 forced releases，合计 635 条带 SelectionPlan 和物理 outcome 的 arm-specific 决策记录。每臂 7 个两个候选、120 个单候选。实际提交顺序审计含 5,760 个请求×臂结果 | 可用 `(run_id, decision_id)` 确定决策，按 `run_id` 匹配实际提交与逐请求结果。635 条的 `downstream_recompute_attribution` 全为 `NOT_ESTABLISHED`。各臂共用 workload cells，不能当作独立样本。约 840 MB 原始 Archive 未提供可读位置，本轮直接核对签入审计及侧车 |
| Phase 4 同 Archive 续接研究 | 480 条请求、440 对 tool-gap、40 个窗口末端右删失，event stream 独立 Session 字段和 session-switch 均为 0 | 检查的是 Program continuation proxy。已结束 gap 或未来请求时点不能补做决策时 armed timer |
| Phase 5 CPU/Mock 与正式设计 | DVA-ER v1 及 Phase 5 candidate adapter 有 fail-closed 合同和 CPU 正确性。当前 Scope Amendment 与工程验收记录独立说明数据准备和 Native/GPU 门槛 | 目前提供的是设计与 CPU/Mock 记录，没有已归档的 DVA-ER Native 预测结果 |
| PR #135 / #136 Nebius 及逻辑 Oracle | 有真实公开请求内容和明确标记的合成压力、逻辑 victim 及事后损失 | 缺 Native rank、物理驻留、armed timer 与实际驱逐。只用于定义逻辑标签和动机，本轮不重建或新增模拟样本 |

来源与范围见 [Phase 2C pilot](../../phase2c-m6-native-pilot-review-submission.md)、[Phase 2D 原始归档交付](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/42)、[Phase 2G 归档清单](../../experiments/phase2g-a2-gate2-v3/evidence-manifest.json)、[Phase 2H](../../experiments/phase2h-history-rich-native-smoke-results.md)、[Phase 2I](../../experiments/phase2i-a3-target-cuda-native-preflight-plan.md)、[Phase 3 暴露审计](../../experiments/phase3-algorithm-exposure-audit.md)、[实际提交顺序审计](../../experiments/phase3-actual-order-audit.md)、[Phase 4](../../experiments/phase4-session-continuation-data/phase4-session-continuation-report.md)、[Phase 5 工程状态](../../experiments/phase5-formal-engineering-acceptance-status.md)和[当前 Scope Amendment](../../experiments/phase5-scope-amendment-2026-11-24.md)。

### 可用决策与归因

- **评分验证用 Native 记录为 0，能归因到指定 victim set 的可靠候选级 Native loss 为 0。** 这里的「可靠」要求在同一决策和原生内容身份下可连接下游需求。E3 的四对测到单次逻辑释放干预的 Native 请求结果。它们保留为有价值的 paired outcome 证据，不能当作同样数量的 DVA-ER 对比分数或归因样本。
- **历史 Native 决策本身可观察。** Phase 3 635 条 decision-arm 行中 35 条有两个候选，集中在 7 个 cell。以 A0 为单臂共同参考，127 条中 7 条竞争，来自 4 个 Workload Group。Phase 2D 和 2G 另有 14 和 108 条经原始事件文件核对的真实多候选释放，保留各自分母。同一 Workload Group 的多个 cell 或同一 Issue 的重复请求不增加独立研究单位。
- **归因缺口的位置清楚。** Phase 2D/2G `FORCED_RELEASE_DECISION` 有运行标识、事件序号、候选与 free queue。`PRESSURE_REQUEST_COMPLETED` 有请求身份和 `last_selected_block_ids`。驱逐回调有 Block ID、process-local hash 和 refcount，但没有唯一 decision/pressure binding。相同进程内 Block ID 可回收，时间接近和 ID 相似均不足以连接。Phase 3 有决策级物理计划/结果摘要和请求级 N/E/C；连接在 run 层成立，逐决策到下游重算仍不可观测。

## Online Features 与 Offline Labels

v1 在**决策时**用真实 Rank/Free Queue、全池 refcount、逻辑/保护所有者、合法 Entry 及所需块数，为每个候选构造预测 victim sequence。释放 Entry 只改保护资格。先取已 eligible blocks，再取该候选新解锁的 blocks，各层维持 Native rank。预测 victim 若至少有一个 owner 的 follow-up 处于 active、且已 armed timer 的 pending gap ≤60 秒，就计 1。每块最多计一次。Timer 来源、观测时间及 chain 建立时间必须可证为在决策时可用，A0 次序只破同分。[DVA-ER v1](../../experiments/dva-er-v1-implementation.md)

在固定决策快照上，score 等于每个候选预测 victim set 中被这一布尔掩码覆盖的块数。固定淘汰预算时，全覆盖会使 score 与 Victim Count 同分，全不覆盖使其全零。异质覆盖才提供额外排序可能。相同预测 victim set 在同一快照下必同分。评分不编码最浅缺口位置。以上是实现性质，实际 Native 样本中出现频率未知。`waiting_followup=true`、`TOOL_GAP_STARTED`、历史 gap 和事后看到的下一请求均不能充当 `CONTROLLER_ARMED_TIMER`。

| 评价对象 | 标签与可比窗口 | 本轮状态 |
| --- | --- | --- |
| 逻辑干预 | `B × Σ_r(H_r^base−H_r^X)`，H 是逻辑父链的连续驻留块数，B 是每块 token 数。回填按观察请求顺序处理。可分别报告下一请求、预定短窗口和全可观测窗口 | PR #136 已定义。Phase 3 Stage 0 另有 A0 锚定的历史全窗口反事实标签，保留各自定义 |
| Native 候选级预测 | 同一合法候选集、同一干预预算的 Native 实际 victim 与需求。使用独立捕获的同进程内容身份、真实到达和归因证据；替代动作需要可比的 paired intervention 或单独标记的反事实 | 三种窗口均 `NOT_EVALUABLE`。现有 Native 轨迹只执行了每个决策的一个候选，旧分臂结果不能用相同 Block ID 替代选项级可比性 |
| 请求级 Native 结果 | Protocol v4 的 `E−C` 或旧实验原指标，按 `run_id + request_id` 观察。它可汇总某个实际请求的重算 | 真实可观测。没有逐 victim 归因时仅保留请求/运行层结果，不充当候选级监督标签 |

未来观察只进入标签侧。下一请求要已观察到并有身份连接。短窗按可验证的时钟或明确 ordinal 预先固定，包括 follow-up 的观察边界。完整窗口在自然结束或归档观测终点截止，截断和缺失继续标为删失。自然终止后的空槽单独记录，缺少可评分 follow-up 的决策单列为 `NO_FOLLOWUP` 或 `CENSORED`；两者都不向 loss 序列填零。DVA 的 60 秒决策特征与评价窗口可以不同，需分别定义。

## 可执行的历史对照

本轮只复核已存在的 Stage 0 反事实及 P2 严格 identity-checked 几何。按 A0 cell、forced event index、候选 identity、decision ordinal 和 victim budget 对账。这里的损失差是 Stage 0 既有 24 请求窗口模型相对 A0 的差值。实际顺序/请求结果只锚定 A0，替代候选损失来自模型，不是 Native 实测。[Stage 0 Oracle](../../experiments/phase3-stage0-oracle-data/stage0-report.md) · [P2 Evidence](../../experiments/phase3-p2-depth-data/p2-depth-report.md)

| 基线 | 可用范围 | 观测 |
| --- | --- | --- |
| Victim Block Count | 7 个竞争 cell，4 个独立 Workload Groups | 两候选在每个 cell 的**模型预算**相同，Count 全部并列。4 个 cell 的窗口内模型损失分别相差 1,552、752、1,040、1,552 tokens，其余 3 个并列。单独的 Count 不能区分这 4 个同预算的模型对照 |
| 连续受害后缀长度 | P2 严格身份子集 5 个 cell | 在该子集，完整受害后缀大小等于预算，因此也并列。共同祖先的 owner membership 和真正的独占后缀需独立验证 |
| 最小保留前缀 / First Victim Depth | 同一 5 个严格身份 cell | 以更长保留前缀优先，5 个均指向 A0 的另一候选。在 3 个非并列标签上都和较低窗口损失相反，另 2 个标签并列。仅说明这个单链深度代理在该小范围可失效 |
| A1/A2/A3 与 DVA-ER | 同一候选集合内的完整可对账评分 | 历史存在部分其他策略的决定及代理。共同的决策时输入、DVA 评分和 candidate-level Native label 不齐，增量预测比较 `NOT_EVALUABLE` |
| Hindsight | 已封存的 Stage 0 反事实 | 7 个竞争 cell 上 A0 都达到 loss-only 模型最优，允许并列。对该历史 cohort 的可避免前缀损失上界仍为 0；容量收益保留 `NOT_EVALUATED` |

只报告有限集合的配对方向和分母。7 个 cell 来自 4 个 Group，5 个严格几何 cell 来自其中 3 个 Group。没有 Spearman/Kendall 稳定性、显著性或 DVA 的在线 regret 结论。未来若有候选级评分和相同标签，可按决策内比较 pairwise concordance、Top-1、分数并列率和 regret，再以独立 Issue 或原设计 Group 为单位聚类。Score 的量纲是 blocks；MAE/RMSE 或 calibration 需要独立训练/验证的 score→token 映射，当前不估计。

## Failure Analysis 与裁定

| 环节 | 本轮所见 |
| --- | --- |
| A 候选无差异 | Phase 3 每臂 120/127 单候选，先限制了排序可发挥的机会 |
| B Score 无分歧 | v1 的结构有两种极端同分情形。实际 frequency 缺 armed/score 证据 |
| C 分数变化但真实受害块相同 | v1 固定快照上相同**预测**集合必同分。预测不同是否传导至不同物理集合，本轮不可识别 |
| D 受害块不同但未来损失相同 | Stage 0 有 3 个不同 Entry 选项的模型标签并列。它们没有证明对应的替代 Native victim sets 被实际观察到 |
| E 排序反向 | 历史简单深度代理在 3 个非并列的模型对子上反向。DVA-ER 的排序方向未知 |
| F 影响损失的决策时特征缺失 | 公开工作负载的窗口损失对首返顺序敏感。原始 Native 老归档记录 waiting 状态，缺少 v1 可用的已 armed timer |
| G 物理及下游归因不足 | Phase 3 的 635 条归因均未建立。Phase 2D/E3 提供配对干预结果，但未包含完整候选评分与 per-victim downstream label |

**CONDITIONAL GO 的条件。** 先用现有或另行授权取得的资料，证明同一 `(run_id, decision_id, pressure_request_id)` 的决策快照、原生进程/内容身份、明确 armed timer、预测与实际 victim、下游提交及命中量可逐项对账。选择只观测一次的候选与对照候选分开统计，分别证明每一侧的标签来源。至少需要有两个合法选项、实际 victim 可区分、下游 label 可区分且跨独立任务的成组观测。随后比较固定预算 Victim Count、简单深度/共享几何与原样 DVA-ER score 的 pairwise ordering 和 regret。只有能评估增量预测价值之后，才具备重新考虑 Native 策略实验的依据。这个研究决定保留现有 Phase 5 授权边界和历史裁定。

## CPU 复核

[审计脚本](../../../scripts/audit_dva_er_predictive_evidence.py)通过原始 tar 文件只读检查事件，不解包、不执行历史记录。可选输入为 [Phase 2D](https://github.com/user-attachments/files/33390532/phase2d-m6-headroom-evidence-d682da8-v2.tar.gz) 和 [Phase 2G Gate 2 v3](https://github.com/user-attachments/files/33699380/phase2g-m6-a2-gate2-v3-root-cause-audit-071ff58.tar.gz) 两份固定归档，脚本检查 SHA-256。原始 Phase 3 Archive 的身份由 [PR #104](https://github.com/zhengjiahong-ai/LLM-KV-Cache-Optimization/pull/104) 记录。本轮使用签入的 Phase 3 派生资产。

```powershell
python scripts/audit_dva_er_predictive_evidence.py --phase2d C:/data/phase2d.tar.gz --phase2g C:/data/phase2g.tar.gz --output C:/data/dva-er-predictive-evidence.json
python -m pytest -q tests/test_dva_er.py tests/test_dva_er_predictive_evidence_audit.py
```

[机器可读结果](evidence-results/dva-er-predictive-evidence.json)记录逐源事件计数、Phase 3 各臂及 7 个已有模型对照的身份。
