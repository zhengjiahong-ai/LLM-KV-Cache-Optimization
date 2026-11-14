# Phase 3 P2 离线研究：在线未来复用深度预测

**Author**: M4  
**Status**: `P2_CPU_ONLY_OFFLINE_RESEARCH` — 只读 Archive，无 GPU、无 Native smoke、无生产算法修改。  
**Input**: Stage 0 A0-Anchored Prefix-State Loss Oracle（完整 24 请求前缀状态重算；不是 Native State Oracle）。

## 0. 结论

- 场景总数：**127**（REAL 7，CONSTRUCTED_HISTORICAL 120）。
- 在线 P2 预测深度 MAE：**134.8 blocks**（REAL 91.6；CONSTRUCTED 137.3）。
- P2 decision flips：**35**（REAL 7；CONSTRUCTED 28）；其中正 gain flips：**0**。
- P2 全轨迹 gain 合计：**-20032 tokens**；hindsight oracle gain 合计：**704 tokens**。
- P2 与 one-decision hindsight oracle 同 gain：**108/127**（REAL 3/7；CONSTRUCTED 105/120）。

> 本轮没有发现 P2 在线预测器在现有/构造场景中稳定产生正收益的证据。该结论限于 prefix-state loss 通道；容量收益仍未评估。

**关键失败模式（REAL）**：7 次真实竞争决策上 P2 全部 flip，4 次为负 gain、3 次为 0；P2 的深度预测并不低（MAE 91.6 blocks），但它无法识别“未来请求会使用哪一条链”。REAL 的 oracle 最优始终是 A0，P2 却选择了另一条链；这说明下一轮 P2 的关键不是继续拟合深度，而是预测**未来请求/session 的 program 续接**。

## 1. 场景定义

- **REAL**：Archive 中真实存在两个候选的 7 次决策；A0 选择与另一候选均为观测。
- **CONSTRUCTED_HISTORICAL**：单候选决策与同一 cell 中最近的其他 program chain 配对；这是**反事实构造**，不是观测到的候选竞争。

REAL 与 CONSTRUCTED 在表中分开报告；任何 CONSTRUCTED 结果都不能直接当作真实决策收益。

## 2. 在线 P2 模型

P2 只能使用决策前信息：

- program 在决策前的 request 链与两两 LCP 深度；
- 若 program 无历史，使用决策前全 cell 的历史深度中位数；
- 候选的 `chain_length`、`first_victim_depth` 与 `need`。

预测目标：该 chain 在决策后的最深复用深度（hindsight label，仅用于离线评估）。
P2 loss score = `max(0, predicted_depth - first_victim_depth + 1) * 16`，越低越好。

## 3. 汇总

| 场景类 | n | MAE (blocks) | flips | 正 gain flips | P2 gain 合计 | oracle gain 合计 |
|---|---:|---:|---:|---:|---:|---:|
| REAL | 7 | 91.6 | 7 | 0 | -4896 | 0 |
| CONSTRUCTED_HISTORICAL | 120 | 137.3 | 28 | 0 | -15136 | 704 |
| ALL | 127 | 134.8 | 35 | 0 | -20032 | 704 |

## 4. REAL 场景明细

| cell | A0 | P2 choice | P2 gain | oracle gain | matches oracle |
|---|---|---|---:|---:|---|
| g09-c1 | sympy__sympy-13551 | django__django-12050 | 0 | 0 | True |
| g09-c2 | sympy__sympy-13551 | django__django-12050 | -1552 | 0 | False |
| g10-c1 | matplotlib__matplotlib-26466 | django__django-15569 | -752 | 0 | False |
| g10-c2 | matplotlib__matplotlib-26466 | django__django-15569 | 0 | 0 | True |
| g16-c1 | django__django-13363 | matplotlib__matplotlib-25287 | -1040 | 0 | False |
| g16-c2 | django__django-13363 | matplotlib__matplotlib-25287 | 0 | 0 | True |
| g18-c2 | sympy__sympy-13974 | django__django-16032 | -1552 | 0 | False |

## 5. CONSTRUCTED_HISTORICAL：oracle gain > 0 的全部场景

| cell | A0 | P2 choice | P2 gain | oracle gain | matches oracle |
|---|---|---|---:|---:|---|
| g16-c1 | matplotlib__matplotlib-25287 | matplotlib__matplotlib-25287 | 0 | 576 | False |
| g12-c1 | pydata__xarray-4695 | pydata__xarray-4695 | 0 | 64 | False |
| g12-c2 | pydata__xarray-4695 | pydata__xarray-4695 | 0 | 64 | False |

其余 117 个 CONSTRUCTED_HISTORICAL 场景 oracle gain = 0；P2 在这些场景中没有可实现的损失收益。

## 6. 解释与边界

- P2 是**在线**预测器：不使用未来 request、oracle 选择或事后 victim 信息；hindsight 只用于评估。
- CONSTRUCTED_HISTORICAL 场景是人为配对，不能替代真实候选竞争；其结果只用于检验模型是否能在更多历史形态上产生分歧。
- 全轨迹收益由 Stage 0 loss oracle 计算，不做局部收益累加；它不是 Native State Oracle，容量收益未评估。
- 不授权 GPU、Native smoke、Protocol v5 或 Partial Release 实现。

## 7. 后续

1. 保留本轮结果；不启动 GPU。
2. P2 继续 CPU-only 离线研究：优先预测**未来请求/session 的 program 续接**，而不是只拟合历史复用深度；扩大真实/构造场景，比较 A0、P2、ideal hindsight oracle。
3. P1 暴露几何作为独立诊断保留，不因 loss-only oracle 为零而取消。

## 8. 复现

```bash
python scripts/probes/phase3_p2_depth/p2_study.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      docs/experiments/phase3-p2-depth-data
```
