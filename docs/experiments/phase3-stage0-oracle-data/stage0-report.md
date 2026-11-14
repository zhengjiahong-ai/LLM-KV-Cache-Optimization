# Phase 3 Stage 0：完整轨迹 Oracle 与 P2 离线价值模型

**Author**: M4  
**Status**: `STAGE0_CPU_ONLY_AUTHORIZED` — 只读 Archive，无 GPU，无 Native smoke，无生产算法修改。  
**Authorization**: M1 对 Stage 0 的正式授权（完整轨迹 Oracle + P2 离线研究）。  
**Model**: A0-anchored prefix-state counterfactual（A0 逐请求基线 + 候选受害者前缀损失 + 完整 24 请求重算）。

## 0. 结论

- Stage-0 gate：**`STOP_ENTRY_ORDERING`**。
- primary 18 Groups / 36 cells 全部完整；`count_complete(G_g >= 512) = 0`。
- Oracle Gain **上界合计 = 0 tokens**；18 个 primary Group 的上界均为 0。
- 在现有 Archive 的 7 次真实竞争决策上，A0 的选择已经是 oracle 最优：另一候选的全轨迹收益为 0 或负值。
- 因此本轮没有任何正的 **avoidable-loss** Oracle Gain；继续优化 Entry 排序在本 archive 上没有可实现的避免损失空间。

> 这是**avoidable-loss 上界为 0** 的结论，不是"所有 Entry 策略都无收益"的证明。模型只移除候选的预测受害者、并允许恢复 A0 已驱逐块；它**不建模**换一条链释放容量所带来的正效应。若上界仍为 0，则现有 7 次决策中没有可避免的受害者损失收益；容量效应需要更完整的 Native state 重放才能检验。

## 1. 合同与命名

本报告严格采用 Protocol v4 的 N/E/C：

$$
N = \text{Native Prompt Tokens},\quad E = \text{Eligible Prefix Tokens},\quad C = \text{Native APC Cached Tokens}
$$

$$
\text{Recomputed} = E - C,\qquad \text{Actual Prefill} = N - C
$$

`E - C` 不叫 `N`。A1/A3 公式里的候选新解锁量写作 `new_blocks`。

## 2. 方法

### 2.1 为什么是 A0-anchored 而不是 Native replay

Archive 没有可独立重置并重放的完整 Native cache state；跨 run 的 native prefix hash 不可移植（`cross_run_native_hash_identity = NOT_PORTABLE`）。因此本阶段不宣称 Native replay，而是：

1. 每个请求保留观测的 `N/E/C_A0`，A0 路径逐请求精确；
2. 在每次 forced-release 决策，把候选的最深 `need` 个 block（`initially_reclaimable_block_ids[:need]`）作为反事实受害者；
3. 与 A0 选择做集合差：`extra = D_candidate - D_A0` 从未来 cache 中移除，`restore = D_A0 - D_candidate` 恢复 A0 已驱逐但候选不会驱逐的块；
4. 对全部 24 个请求重新计算 `C_cf` 与 `Recomputed_cf = E - C_cf`，使用后重新加入；
5. Oracle 枚举每个 cell 的全部可达候选序列，取完整轨迹最小值；**不**把逐决策局部收益相加。

### 2.2 有效性验证

- A0 逐请求：`R_A0` 与 Archive `aggregate_recomputed_tokens` 逐 cell 精确一致（36/36 primary cells）。
- 每决策受害者集合：预测受害者是物理驱逐集的子集，`127/127`；7 次竞争决策 `7/7`。
- 19 次 `matched=128 > need` 的量子过量全部是单候选决策，不存在排序选择，因而不会改变 oracle 的候选空间。
- **`A0_NATIVE_REPLAY = NOT_AVAILABLE`**：本阶段没有把 prefix-state 模型冒充为 Native 重执行。

### 2.3 边界

- 结果为 **avoidable-loss upper bound**：只移除预测受害者，并允许恢复 A0 已驱逐块，均偏向候选；不建模换链释放容量的正效应；
- 不建模 19 次量子过量中的额外 block（全是单候选，无选择）；
- 不改变 `E`、请求时间线、TTL 或 Native 调度；
- P2 深度特征是事后 oracle 特征，不是在线可用特征。

## 3. Oracle 结果：7 次竞争决策

| cell | need | A0 选择 | 另一候选 | 另一候选全轨迹 gain (tokens) | oracle gain (tokens) |
|---|---:|---|---|---:|---:|
| g09-c1 | 97 | sympy__sympy-13551 | django__django-12050 | 0 | 0 |
| g09-c2 | 97 | sympy__sympy-13551 | django__django-12050 | -1552 | 0 |
| g10-c1 | 127 | matplotlib__matplotlib-26466 | django__django-15569 | -752 | 0 |
| g10-c2 | 127 | matplotlib__matplotlib-26466 | django__django-15569 | 0 | 0 |
| g16-c1 | 101 | django__django-13363 | matplotlib__matplotlib-25287 | -1040 | 0 |
| g16-c2 | 101 | django__django-13363 | matplotlib__matplotlib-25287 | 0 | 0 |
| g18-c2 | 97 | sympy__sympy-13974 | django__django-16032 | -1552 | 0 |

> 表中 `A0 选择` 与 `另一候选` 的 program 见证据 JSON；负 gain 表示该候选会让全轨迹重算量增加。7 次决策的 oracle 最优选择全部是 A0 的选择。

## 4. Group-level 门槛

- primary Groups：18；完整 Groups：18；完整 cells：36。
- `count_complete(G_g >= 512) = 0`。
- H3-0 sensitivity mean gain（upper bound）：**0 tokens/group**；g09/g18 的单 cell 不进入 primary gate。

| 判定条件 | 结果 |
|---|---|
| complete_cells >= 33 且 complete_groups >= 15 | 是 |
| count_complete(G_g >= 512) >= 8 | 否（0） |
| 4 <= count_complete < 8 | 否 |
| count_complete <= 3 | 是 → `STOP_ENTRY_ORDERING` |

## 5. P2 深度模型

- P2 depth-score 在 7 次竞争决策上的 flip 数：**0**；其中正 gain flip：**0**。
- P2 的 same-program depth proxy 在 7 次决策上没有产生正收益；与 A0 同选或在 tie 时按 A0 优先。

| cell | need | A0 | P2 choice | flip | P2 gain |
|---|---:|---|---|---|---:|
| g09-c1 | 97 | sympy__sympy-13551 | sympy__sympy-13551 | False | 0 |
| g09-c2 | 97 | sympy__sympy-13551 | sympy__sympy-13551 | False | 0 |
| g10-c1 | 127 | matplotlib__matplotlib-26466 | matplotlib__matplotlib-26466 | False | 0 |
| g10-c2 | 127 | matplotlib__matplotlib-26466 | matplotlib__matplotlib-26466 | False | 0 |
| g16-c1 | 101 | django__django-13363 | django__django-13363 | False | 0 |
| g16-c2 | 101 | django__django-13363 | django__django-13363 | False | 0 |
| g18-c2 | 97 | sympy__sympy-13974 | sympy__sympy-13974 | False | 0 |

**解释**：P2 的 depth 特征作为事后 oracle 特征，在 7 次真实竞争决策上没有找到比 A0 更好的选择；现有 7 次竞争决策是"风险"而不是"机会"。

## 6. 建议

1. **不启动 GPU Campaign。** avoidable-loss 上界为 0，且当前没有正收益路径；容量效应需要更完整的 Native state 重放，当前 archive 不支持。
2. **不推进 P2 的 GPU 验证。** 7 次竞争决策上 P2 无正 gain。
3. **P1 的 CPU 参数扫描可保留为暴露几何的诊断**，但它不再是"追求 oracle gain"的后续：本 archive 的候选暴露本身不足，先确认 P1 能否把 multi-candidate rate 提升到 ≥20%；若无，则 Entry 排序路线在本 workload 家族应停止。
4. **P3 仍暂缓**，本阶段不授权 Partial Release 实现。

## 7. 限制

- Native cache state is not replayable from the archive; results are A0-anchored prefix-state counterfactuals.
- The model is loss-only: it removes candidate victims and restores A0-evicted blocks, but does not model capacity gains from evicting a different chain. A positive capacity effect is outside this model.
- Counterfactual eviction uses each candidate's deepest need blocks; the 19 quantum over-eviction cases are not modeled and are single-candidate.
- Cross-run Native prefix hashes are not portable; all counterfactual block identities come from the A0 run.
- P2 depth scores are offline hindsight features and must not be treated as online features.
- This study does not authorize GPU execution, Protocol v4 changes, or P3 partial release.

## 8. 复现

```bash
python scripts/probes/phase3_stage0_oracle/stage0_oracle.py \
    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
    --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
    --out      docs/experiments/phase3-stage0-oracle-data
```

输出：`stage0-evidence.json`、`stage0-report.md`、`sha256-manifest.txt`。
