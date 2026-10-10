# Phase 2A H1/H2 — 阶段收口 Verdict Record

Status: **PHASE 2A H1/H2 EVIDENCE CAMPAIGN: CLOSED**
Recorded by: M4
Recorded at: 2026-10-10
Baseline: `origin/main` @ `9a0cdff`（PR #35 已合并 H1/H2 证据与最终裁定）

本文档是阶段级归档记录。它**不重复** M6 的实验产物，只做三件事：

1. 以可追溯方式固定 H1 与 H2 的最终裁定及其封存绑定；
2. 严格区分 **campaign acceptance / rule acceptance / method authorization** 三层；
3. 记录证据保全清单与**仍未获裁定**的治理事项。

---

## 0. 三层"接受"必须分开读

这是本阶段最容易误读的地方，因此放在最前。

| 层级 | 含义 | 本阶段结论 |
| --- | --- | --- |
| **Campaign acceptance** | 该实验作为一次研究交付是否成立、是否完整、是否可独立复算 | **H1：ACCEPTED。H2：REVIEW COMPLETED。** 两者均按计划交付并结束 |
| **Rule acceptance** | 被检验的规则是否达到冻结的候选标准 | **未通过。** H1-R1 维持 `DIAGNOSTIC_ONLY` |
| **Method authorization** | 是否授权方法设计或运行时实现 | **未授权。** 无任何 runtime policy 或 method design 被放行 |

三者**互不推出**：

```text
Campaign ACCEPTED        ⇏  Rule ACCEPTED
Rule NOT ACCEPTED        ⇏  Method impossible
Method NOT AUTHORIZED    ⇏  Method worthless
```

具体到 H1-R1：它**不是**统计上被证明失效（样本未达门槛，无法给出效力结论），而是**未获得独立验证支持**。

---

## 1. H1 最终裁定

**H1 CAMPAIGN ACCEPTED / EXPERIMENT CLOSED** · reviewed commit `e6bf74f`

### 1.1 Campaign 事实

| 项 | 值 |
| --- | --- |
| 计划运行数 | 126 |
| 成功 / 失败 | 96 / 30 |
| 封存独立 scenario draws | 42（每族 7） |
| 完整三种子结果的 scenario | 32 |
| 无效独立 scenario | 10 |
| **paired evaluable 独立 scenario draws** | **29** |
| 冻结门槛 | 30 |
| 覆盖族 | F1–F6（全） |

⚠️ **样本缺口来自运行损耗，不是设计要求。** 42 → 29 损失 13 个 draw（约 31%）。其中 3 个为 `runtime_valid_but_not_paired_evaluable`：
`h1-f1-draw-05`、`h1-f3-draw-04`、`h1-f5-draw-01`。

### 1.2 Replay 保真与缺失分类（独立复核通过）

| 项 | 值 |
| --- | --- |
| 参与比较的决策 | 120 |
| 实际评估的决策 | 114 |
| 排除的决策 | 6 |
| 排除原因 | `too_few_candidates` = 6 |
| release **set** 匹配 | 120 / 120 |
| release **sequence** 匹配 | 120 / 120 |
| marginal `initially_reclaimable` 匹配 | 471 字段 |
| missing candidate 总数 | **0** |

⇒ issue #34 的 feature-missingness 记账在正式 campaign 上生效；本阶段无任何缺失被静默吞掉。

### 1.3 H1-R1（`H1_R1_reverse_deadline`）Level-A 结果

```text
primary metric      : planned_return_weighted_prefill_proxy
statistical unit    : independent scenario draw
paired draws        : 29
better/worse/tied   : 13 / 14 / 2
mean delta          : -0.008328804890493039
95% CI              : [-0.03580353525786637, +0.017812089996253742]
family agreement    : 3/6
sign convention     : baseline_loss - challenger_loss；正值有利于 challenger
```

**冻结判据全部未通过**：

| 判据 | 结果 |
| --- | --- |
| holdout_adequate（≥30 draws） | ✗ 29 |
| scenario mean improvement > 0 | ✗ 均值为负 |
| CI 下界 > 0 | ✗ 区间跨零且下界为负 |
| better > worse draws | ✗ 13 < 14 |
| family agreement ≥ 2/3 | ✗ 3/6 = 0.5 |

### 1.4 正式 verdict

```text
campaign_disposition        : H1_CAMPAIGN_ACCEPTED_EXPERIMENT_CLOSED
formal_rule_verdict         : DIAGNOSTIC_ONLY
promoted_to_proxy_candidate : false
threshold_modified          : false
supplemental_runs_required  : false
```

⛔ **门槛未修改，也未追溯性改判为 `NOT_ACCEPTED`。** 这一点重要：`DIAGNOSTIC_ONLY` 的含义是「样本不足以判定」，不是「判定为无效」。

### 1.5 后续限制（冻结）

1. H1-R1 **不晋升** `PROXY_CANDIDATE`；
2. **不再**开展 Level-B runtime validation；
3. **不实施** H1-R1 runtime policy；
4. **不围绕现有结果**做规则修补或参数调整。

**H1-R1 归档定性：**

> 未获得独立验证支持的探索性假设（exploratory hypothesis without independent validation support）。
>
> ⚠️ 这**不等价于**统计学上已证明该规则无效。

---

## 2. H2 最终裁定

**H2 MEASUREMENT REVIEW COMPLETED / B1 REMAINS LOCKED**

| 条件 | 结论 | 关键量 |
| --- | --- | --- |
| H2-M1 真实 $C(r)$ 非线性 | **PASS** | 观测 = `isolated_native_prefill_elapsed_seconds`；每点 9 次重复；10,000 bootstrap（seed 20261007）；`delta_M1` = 0.19029591700382298 s；拟合增量 0.46337043935881883 s，q05 = 0.4407016205465704；**gamma q05 = 8.880469562324095e-9 s/token²** |
| H2-M2 partial-prefix APC 语义 | **PASS** | 6 个 exact probe、54 次重复、对照有效；保留前导 + 淘汰尾部 ⇒ 仅后缀重计算 |
| H2-M3 淘汰位置改变实际结果 | **PASS** | **12/12 单元全部支持**；108 个 measured pair；每单元 9 次重复；无未解效应单元 |
| H2-M4 block-level 额外 headroom | **FAIL** | 12 单元、108 对、9 次重复/单元；**supporting cells = 0**；resolved headroom cells = 0；**pairwise headroom = 0 tokens** |

### 2.1 M4 FAIL 的适用边界（M6 已冻结声明）

> M4 FAIL 只适用于**冻结的 single-prefix controlled comparator**；**不构成**对任何可能的 block-level 或多 entry 策略的否定。

同时须记录 M6 的另一条边界：

> M1 的非线性 isolated prefill cost **不构成**某条 cost-aware eviction 策略在运行时服务层面的收益证明。

### 2.2 汇总

```text
all_four_pass                       : false
b1_method_design_unlocked           : false
b1_runtime_implementation_authorized: false
b1_status                           : LOCKED
h2_measurement_campaign_closed      : true
no_selective_reruns_authorized      : true
```

⇒ B1 **不进入** method design 或 runtime implementation；**不追加**实验试图翻转 M4；**不修改**冻结阈值。H2 作为完整机制研究归档。

---

## 3. 证据保全清单（封存链）

以下绑定来自阶段裁定文件本身，用于在后续任何引用中校验证据未被改动。

### 3.1 H1

| 项 | SHA-256 / 定位 |
| --- | --- |
| evidence archive | `af5be5bd56a172f7945f12712289708aa55cda01f1b8c05a2bc3215b14c90af7` |
| evidence handoff | `ffebe24fc5fcc02b926d3a19b518092536f4a9caaf231e42f4988abb65a587d0` |
| formal analysis | `f51dbe67535c4d050ef20ab0e92794e0f5944e67d1015fc007c4fe9608d1b912` |
| review submission | `8349c0cbba7c00cb863bf54952fe3a470823a29ac65cd0cef0fa70812e495a9d` |
| sealed outcome | `da004c52e02105e4ffb366e7a5e1c1800bcad0c4e6542ecb5070011628e902a0` |
| analysis git sha | `2804382` |
| sealing tool git sha | `e3a02fd` |
| frozen: authorization / campaign / level-A contract / epsilon audit / seam validation / scenario seal | `fc478eca…` / `2c7ee26c…` / `f7ee77cb…` / `20875488…` / `1d6082bb…` / `54cb0a0e…`（全值见 `formal-level-a-review-submission.json`） |

### 3.2 H2

| 项 | SHA-256 / 定位 |
| --- | --- |
| evidence archive | `artifacts/phase2a-h2-final-evidence-c34a172.tar.gz`，`0ef7207b2baabca0fc77e2a1eef01ce272b2cb2e611fe7f0b6a5a2f556f2a5a7` |
| review submission | `5e4fa083b49dc5ce9e7285443a34457a2d03103b6ce59d7b648daa4227674812` |
| M2/M3 formal verdict | `0d7a5d42799e42dab4baca4538ba7f21903af93d64830906a508eace223a0874` |
| independent review report | `5d233dd05fac69a0c4d6f26000ef5f619838106ead060a56d2335df61d663848` |
| independent review verdict | `8a09bbd855b9efed0616ad5e29238f095a3ac0faa003be3d1dcb0a404973a47d` |
| M2/M3 outcome seal | `fc81472ee086692835efdbae178850f4497c2cb8f1e866894e9a4a1716097fb4` |
| M2 outcome / M3 outcome / provenance | `b0f36a90…` / `568aad9b…` / `cd59643c…` |
| measurement submission commit | `26caefc76a38f202b0de86ab13db2dbe8b6086c3` |

### 3.3 保全原则（已满足）

| 要求 | 状态 |
| --- | --- |
| 全部失败与无效运行记录保留 | ✅ 30 个 H1 失败运行、10 个无效场景、排除尝试均保留 |
| 排除项与正式统计分离 | ✅ 编译保真 v1–v3 作为 excluded diagnostics；H2 中 2 次零事件 SSL 尝试不计入正式统计 |
| 独立复算 | ✅ H1 的 10,000 bootstrap 独立复算；H2 的 bootstrap 由不导入生产实现的脚本复现 |
| 无选择性补跑 | ✅ 两个裁定均记录 `no_selective_reruns_authorized` |
| 原始运行与封存文件未被编辑 | ✅ H2 裁定明列 |

---

## 4. M4 H1 evidence request 的处置

M4 于 2026-10-07 提交的 `docs/phase2a-m4-h1-evidence-request.md` 请求已被本轮 campaign **实质满足**。逐项处置：

| 请求 | 处置 |
| --- | --- |
| ≥40 独立 scenario、每族 ≥6 | ✅ 42 个（每族 7）已生成并封存 |
| 独立性来自新 scenario 而非更多 seed | ✅ 42 个结构唯一的 scenario；seed 仅用于噪声估计 |
| 全成本分辨率（16–512 含中间值） | ✅ 设计冻结支持集 16–512 含 16/32/128/256/512 与中间尺寸 |
| `eta` / `queue_delay` 变化 | ✅ eta 在 1 两侧采样、queue delay 0–2 s，**且逐候选采样**（可能产生决策内变异） |
| 共享所有权 / 多次释放 / 重复压力 | ✅ 列入预声明变异与 corner-case 配额 |
| 窄观测缝（raw native facts） | ✅ Level-B seam 审计 S1–S5 已 hash 绑定；本轮走 Level-A proxy-first 路径 |
| ≥3 次 baseline 重复以标定 `epsilon_latency` | ✅ 5 次相同 native 全命中重复 ⇒ `epsilon_latency = 0.008793766604503617 s` |
| sealed holdout | ✅ 场景清单在结果执行前封存 |
| feature-missingness coverage | ✅ issue #34 实现并测试；正式 campaign 上 `missing_candidates = 0` |

⇒ **该请求无需再跟进，标记为 FULFILLED / SUPERSEDED。**

---

## 5. 仍未获裁定的治理事项

以下不属于本次裁定范围，需 M1 明确后才能开展。**本记录不预设结论。**

| # | 事项 | 为何需要裁定 |
| --- | --- | --- |
| G1 | **H1 的 42 个 sealed scenario 能否用于新假设？** | H1-R1 的结果已被观察并封存。若以同一语料评估**新**假设，即为 in-sample 选择。要么需要新的 sealed 语料，要么需要 M1 明确裁定复用条件与多重比较处置 |
| G2 | 新假设的 acceptance 是否仍用同一冻结协议 | 协议本身未变，但 `epsilon_latency`、family 门槛等绑定是否需要重签 |
| G3 | M4 能否以**诊断**目的读取已解封语料 | 例如测量 marginal relief 的决策内离差以判断某假设是否可证伪。这与「用该语料检验假设」是不同用途，但需 M1 划定 |

⛔ **本阶段不向 M6 提出新的正式测量任务，也不授权新的 runtime policy implementation。**
上述三项若需动作，均在 M1 完成下一轮研究方向裁定**之后**。

---

## 6. 可追溯性

| 陈述 | 来源 |
| --- | --- |
| H1 campaign 事实、fidelity、missingness、H1-R1 数字 | `docs/experiments/phase2a-m6-h1/formal-level-a-review-submission.json` |
| H1 裁定、授权状态、封存绑定 | `docs/experiments/phase2a-m6-h1/formal-level-a-verdict.json` |
| H2 四项结论、M1/M4 数值、integrity | `docs/experiments/phase2a-m6-h2/formal-final-verdict.json` |
| H2 M2/M3 量级 | `docs/experiments/phase2a-m6-h2/formal-m2-m3-review-submission.json`、`formal-m2-m3-verdict.json` |
| M1 观测边界（isolated native forward，非端到端延迟） | `docs/experiments/phase2a-m6-h2/README.md` |
| 42 draws、每族 7、预声明变异 | `docs/phase2a-m6-h1-independent-campaign-design.md` |
| `epsilon_latency` 与 5 次 baseline 重复 | `docs/experiments/phase2a-m6-h1/README.md` |
| canonical proxy loss 定义 | `src/kvopt/profiling/loss_views.py::_return_weighted_prefill_evidence` |
| acceptance 协议（单位、门槛、层级） | `docs/phase2a-m4-rule-acceptance-protocol.md` |
| H1-R1 预注册 | `docs/phase2a-m4-h1-r1-preregistration.md`、`src/kvopt/costaware/preregistrations.py` |
| M4 原 evidence request | `docs/phase2a-m4-h1-evidence-request.md` |
