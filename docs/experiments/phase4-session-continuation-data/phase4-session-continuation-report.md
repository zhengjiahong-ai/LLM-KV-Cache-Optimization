# Phase 4 Task 1：Session Continuation Prediction 可行性研究

**Author**: M4  
**Status**: `PHASE4_TASK1_CPU_ONLY_FEASIBILITY` — 只读 Archive，无 GPU、无 Native smoke、无生产算法修改。  
**Scope**: 数据可用性审计、目标契约、窗口续接概率、历史基线、初步 Expected Loss 代理。

## 0. 结论

- **Session Continuation 在本 Archive 中不可独立识别**：`SESSION_CONTINUATION_NOT_IDENTIFIABLE`。
- 事件流没有 `session_id`；session 只能从 cohort seal + `request_id` 恢复。
- `program_id == session instance_id`：**PASS**；没有任何 program 拥有多个 session（`multi_session_programs=0`）。
- 因此 Session Continuation 与 Program Continuation 在本 Archive 中观测上等价；本报告只给出 **Program Continuation proxy**，不冒充 Session Continuation 结论。

## 1. Data Availability Audit

| 项 | 观测 |
|---|---|
| Groups | 20 |
| Sessions | 40 |
| Sessions per Group | {"2": 20} |
| Selected requests per Session | {"12": 40} |
| Replay request rows (C1 only) | 480 |
| `session_id` in event stream | 0 |
| Program == Session | PASS |
| Programs with >1 session | 0 |
| Tool gap started/ended | 440/440 |
| Tool gap unpaired start/end | 0 |
| Source request timestamps | 480 |
| Explicit session-switch events | 0 |

**数据缺口**：

- `EVENT_STREAM_HAS_NO_SESSION_ID`
- `SESSION_ID_EQUALS_PROGRAM_ID`
- `NO_PROGRAM_WITH_MULTIPLE_SESSIONS`
- `NO_EXPLICIT_SESSION_SWITCH_EVENT`

**最小补充数据需求**：

1. 每个 request / tool-gap 事件带独立 `session_id`，且 `session_id` ≠ `program_id`。
2. 至少一个 program 拥有 ≥2 个 session（或同一 session 包含多个 program），才能区分 Session 与 Program 续接。
3. 显式的 session start / switch / end 事件，带时间戳。
4. 所有 replay request 的源 submit/completion 时间，以及 tool gap 的 session 归属。
5. 请求级 continuation 标签与 session 生命周期绑定，而不是从 `program_id` 反推。

## 2. Prediction Target Contract

| 目标 | 定义 | 本 Archive 可识别性 |
|---|---|---|
| **Session Continuation** | 给定时刻 t 与 session s，窗口 W 内 s 是否再出现请求 | **不可独立识别**（session≡program） |
| **Program Continuation** | 给定时刻 t 与 program p，窗口 W 内 p 是否再出现请求 | 可识别；本报告作为 proxy |
| **Prefix-Demand Overlap** | 候选链与未来请求前缀的最深重合深度 | 可计算；**不等于 APC cache hit** |

所有在线特征只使用决策前信息；窗口标签、oracle 与未来 overlap 只用于离线评估。

## 3. Continuation Probability by Window

| Window (s) | rows | positive | negative | positive rate |
|---:|---:|---:|---:|---:|
| 5 | 480 | 0 | 480 | 0.000 |
| 15 | 480 | 12 | 468 | 0.025 |
| 60 | 480 | 374 | 106 | 0.779 |
| 300 | 480 | 436 | 44 | 0.908 |

> 由于 session≡program，这张表同时是 session-level 与 program-level 的**同一组标签**；不能当作两个独立目标。

## 4. Baseline Comparison（Group-isolated）

Leave-one-Group-out；同一 Group 的两个 session 不跨 train/test。指标为 held-out Brier / AUC / accuracy。

| Window | Baseline | Brier | AUC | Accuracy |
|---:|---|---:|---:|---:|
| 5 | GLOBAL | 0.0000 | n/a | 1.000 |
| 5 | PROGRAM | 0.0000 | n/a | 1.000 |
| 5 | TOOL_GAP | 0.0003 | n/a | 1.000 |
| 5 | SESSION_HISTORY | 0.0000 | n/a | 1.000 |
| 15 | GLOBAL | 0.0251 | 0.038 | 0.975 |
| 15 | PROGRAM | 0.0251 | 0.038 | 0.975 |
| 15 | TOOL_GAP | 0.0240 | 0.960 | 0.960 |
| 15 | SESSION_HISTORY | 0.0251 | 0.038 | 0.975 |
| 60 | GLOBAL | 0.1760 | 0.245 | 0.779 |
| 60 | PROGRAM | 0.1760 | 0.245 | 0.779 |
| 60 | TOOL_GAP | 0.1028 | 0.686 | 0.881 |
| 60 | SESSION_HISTORY | 0.1760 | 0.245 | 0.779 |
| 300 | GLOBAL | 0.0833 | 0.460 | 0.908 |
| 300 | PROGRAM | 0.0833 | 0.460 | 0.908 |
| 300 | TOOL_GAP | 0.0745 | 0.646 | 0.908 |
| 300 | SESSION_HISTORY | 0.0833 | 0.460 | 0.908 |

**解读**：

- 5s 窗口没有正例，AUC 不可定义；15s 只有 12 个正例，估计不稳定。
- `PROGRAM` 与 `SESSION_HISTORY` 在本 Archive 上退化为 `GLOBAL`：每个 program 只属于一个 Group，leave-one-Group-out 时 test program 在 train 中完全 unseen，只能回退 global。这不是模型调参问题，而是 program/session 与 Group 绑定的数据设计限制。
- `TOOL_GAP` 是唯一有稳定信号的基线：60s 窗口 AUC 0.686、Brier 0.103，说明“上一次 tool gap 长度”比 program 身份更有用。
- 这仍是 **program-level proxy**；不能把 tool gap 对 program 续接的预测能力写成 session continuation 结论。

## 5. Expected Loss Proxy

模型形式：

```text
EL(candidate) = P_program_continue(program, t, W=60s) * P2-B_prefix_loss(candidate)
```

- `P_program_continue` 来自其他 Group 的历史频率，**不是** session continuation；由于 program 在 leave-one-Group-out 中完全 unseen，它实际退化为训练集 global rate，不能当作 program-specific 概率。
- `P2-B_prefix_loss` 来自 Stage 0 loss oracle 的 P2-B 深度代理；
- 每个场景只改一个决策，收益是独立单决策反事实增量，不是联合策略效果；
- 这是初步 proxy，不用于宣称算法有效。

- 场景：55（REAL 2，CONSTRUCTED 53）；
- flips：15；正 gain flips：0；
- 独立单决策 gain 合计：-6592 tokens；oracle gain 合计：640 tokens。

**解读**：

- 这里只使用 C1 cell 的 55 个有效场景（2 REAL + 53 CONSTRUCTED），不是 P2 的 111 个 C1+C2 场景；两组数字不可直接比较。
- 15 次 flip、0 次正 gain；EL proxy 没有找到可用的独立单决策收益。
- 预期损失中的 `P_program_continue` 是 program-level 历史频率，不是 session continuation；该结果不能用于宣称 Session 模型有效。

> 由于 Session Continuation 不可独立识别，本 EL 只能作为 **program-level proxy diagnostic**；不能把它当作 Session Continuation 模型的收益。

## 6. 解释边界

- 不能把 Program 当作 Session；本报告明确二者在 Archive 中同源。
- 不能把 Prefix-Demand Overlap 当作实际 APC cache hit。
- 不能因为 MAE / AUC 较好就宣称算法有效；预测质量与独立反事实收益分开报告。
- 不构造大量人工 session 样本来制造有效性；数据缺口直接列出。
- 不授权 GPU、Native smoke、Protocol v5、Partial Release 或生产算法修改。

## 7. 建议

1. **暂不进入 Session Continuation 算法实现**；当前 Archive 不支持独立 session 目标。
2. 若要继续，最小补充数据是显式 `session_id` + 一个 program 的多个 session + session switch 事件。
3. Program-level continuation proxy 可作为下一轮 CPU 可行性研究，但必须与 Session 目标分开命名。
4. P1 暴露几何仍作为独立诊断保留。

## 8. 复现

```bash
python scripts/probes/phase4_session_continuation/study.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --seal     local/cohort-seal.json \
    --out      docs/experiments/phase4-session-continuation-data
```
