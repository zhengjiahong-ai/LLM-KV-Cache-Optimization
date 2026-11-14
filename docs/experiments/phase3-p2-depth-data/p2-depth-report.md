# Phase 3 P2 离线研究：候选链条件化在线预测

**Author**: M4  
**Status**: `P2_CPU_ONLY_OFFLINE_RESEARCH` — 只读 Archive，无 GPU、无 Native smoke、无生产算法修改。  
**Oracle**: Stage 0 A0-Anchored Prefix-State Loss Oracle（完整 24 请求前缀状态重算；不是 Native State Oracle）。

## 0. 结论

- 预测目标与标签已重新对齐：在线预测的是候选链的未来 **prefix-demand overlap**，不是经过 Native Cache 验证的真实复用深度。
- 所有 P2 变体只使用决策时刻之前的信息；未来 overlap、oracle 选择与 victim 信息只作为离线标签。
- 每一条收益都是**独立单决策反事实增量**，不是联合部署 P2 的策略效果；REAL 与 CONSTRUCTED_HISTORICAL 继续分开。

**一句话结果**：P2-A/B 的预测 MAE 较低（134.3 blocks）但在有效 REAL 5 次上全部 flip、0 次正 gain；P2-C 的 MAE 更差（460.1 blocks）且 0 次 flip、0 次 gain。预测精度与实际决策价值没有对齐。

## 1. 三种在线预测器

- **P2-A** `P2_A_ORIGINAL_MAX`：原始对照。program 历史请求两两 LCP 的最大值。
- **P2-B** `P2_B_CHAIN_MAX`：候选链条件化。当前候选链与每个历史同 program 链的 LCP，取最大值。
- **P2-C** `P2_C_CHAIN_WEIGHTED`：候选链条件化加权估计。对上述 LCP 做 recency-weighted mean。

三者都只使用决策前历史；无历史时使用决策前全 cell 的 pairwise 中位数 fallback。

## 2. Victim identity 与 Fail-Closed

- 候选只在 victim hashes 可证明为某条历史同 program 链的**连续后缀**时进入评估。
- 不能证明连续后缀的候选/场景记为 `EXCLUDED`，不使用 `chain_length - need + 1` 默认推断。
- 本轮排除：**18** 个候选（REAL 4，CONSTRUCTED 14）；原因：{'victim_hashes_not_a_contiguous_suffix_of_any_prior_chain': 18}。
- REAL 的 4 个候选排除对应 g10-c1、g10-c2 两个决策；其余 5 个 REAL 决策进入评估（7 个真实竞争决策中 2 个被排除）。
- REAL 与 CONSTRUCTED 的排除项都保留在证据 JSON 的 exclusions 中，不当作 0 收益。

## 3. 汇总：预测精度与决策价值分开

| 方法 | 场景类 | n | MAE (blocks) | ranking accuracy | flips | 正 gain flips | 独立单决策 P2 gain 和 | 独立单决策 oracle gain 和 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| P2-A original history max LCP | REAL | 5 | 87.4 | 0.200 | 5 | 0 | -4144 | 0 |
| P2-A original history max LCP | CONSTRUCTED_HISTORICAL | 106 | 136.6 | 0.745 | 24 | 0 | -11104 | 704 |
| P2-A original history max LCP | ALL | 111 | 134.3 | 0.721 | 29 | 0 | -15248 | 704 |
| P2-B candidate-chain max LCP | REAL | 5 | 87.4 | 0.200 | 5 | 0 | -4144 | 0 |
| P2-B candidate-chain max LCP | CONSTRUCTED_HISTORICAL | 106 | 136.6 | 0.745 | 24 | 0 | -11104 | 704 |
| P2-B candidate-chain max LCP | ALL | 111 | 134.3 | 0.721 | 29 | 0 | -15248 | 704 |
| P2-C candidate-chain weighted mean | REAL | 5 | 346.5 | 0.800 | 0 | 0 | 0 | 0 |
| P2-C candidate-chain weighted mean | CONSTRUCTED_HISTORICAL | 106 | 465.4 | 0.972 | 0 | 0 | 0 | 704 |
| P2-C candidate-chain weighted mean | ALL | 111 | 460.1 | 0.964 | 0 | 0 | 0 | 704 |

> `independent_single_decision_p2_gain_sum_tokens` 是各场景“只改一个决策”的增量之和，**不是**联合 P2 策略的总体效果；不能把任何一个总和表述为部署 P2 的收益。

## 4. REAL 场景明细（仅完整后缀可证明的决策）

| cell | A0 | oracle | P2-A | P2-B | P2-C |
|---|---|---|---|---|---|
| g09-c1 | sympy__sympy-13551 | django__django-12050 (0) | django__django-12050 (0) | django__django-12050 (0) | sympy__sympy-13551 (0) |
| g09-c2 | sympy__sympy-13551 | sympy__sympy-13551 (0) | django__django-12050 (-1552) | django__django-12050 (-1552) | sympy__sympy-13551 (0) |
| g16-c1 | django__django-13363 | django__django-13363 (0) | matplotlib__matplotlib-25287 (-1040) | matplotlib__matplotlib-25287 (-1040) | django__django-13363 (0) |
| g16-c2 | django__django-13363 | django__django-13363 (0) | matplotlib__matplotlib-25287 (0) | matplotlib__matplotlib-25287 (0) | django__django-13363 (0) |
| g18-c2 | sympy__sympy-13974 | sympy__sympy-13974 (0) | django__django-16032 (-1552) | django__django-16032 (-1552) | sympy__sympy-13974 (0) |

## 5. CONSTRUCTED_HISTORICAL：oracle gain > 0 的场景

| cell | A0 | oracle | P2-C choice | P2-C gain | oracle gain |
|---|---|---|---|---:|---:|
| g12-c1 | pydata__xarray-4695 | django__django-14170 | pydata__xarray-4695 | 0 | 64 |
| g12-c2 | pydata__xarray-4695 | django__django-14170 | pydata__xarray-4695 | 0 | 64 |
| g16-c1 | matplotlib__matplotlib-25287 | django__django-13363 | matplotlib__matplotlib-25287 | 0 | 576 |

其余 103 个有效 CONSTRUCTED 场景 oracle gain = 0。

## 6. 解释与边界

- **P2-A 与 P2-B 在本 cohort 上完全同值**：候选链条件化的最大 LCP 已经由另一条历史链达到，因此 P2-B 没有改变排序；这是观测事实，不是实现错误。
- **P2-C 的 MAE 更差但 flip 为 0**：加权估计把预测深度压低，候选分数在多数场景落到 0，tie 保留 A0；因此它“不犯错”但不产生任何决策价值。
- `ranking_accuracy` 在 oracle gain = 0 的场景中被 tie 抬高，不能单独当作预测能力；必须与 positive-gain flip、全轨迹 gain 一起看。
- 预测精度与实际决策价值分开报告；MAE/ranking accuracy 不能替代全轨迹 gain。
- `future_prefix_demand_overlap` 是请求前缀重合，不等于 Native cache hit。
- REAL 与 CONSTRUCTED_HISTORICAL 不可合并解释；CONSTRUCTED 是反事实构造。
- 全轨迹收益来自 loss oracle，不是 Native State Oracle；容量收益未评估。
- 不授权 GPU、Native smoke、Protocol v5 或 Partial Release 实现。

## 7. 后续

1. 保留本轮结果；不启动 GPU。
2. P2 继续 CPU-only：先解决“未来请求/session program 续接”的预测目标，再扩展候选与场景。
3. P1 暴露几何作为独立诊断保留。

## 8. 复现

```bash
python scripts/probes/phase3_p2_depth/p2_study.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      docs/experiments/phase3-p2-depth-data
```
